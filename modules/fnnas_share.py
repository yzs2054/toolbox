"""飞牛 NAS（fnos）公开分享协议封装。

fnnos 私有 API，需要逆向签名。协议常量从 SPA bundle 里抠出来的：
  - _SALT: 签名拼接前缀
  - _API_KEY: XOR 247 解出的 34 字节常量

来源：https://s6.fnnas.net/s/static/1.0.5/index-jtKAjfbv.js
对应 fnos SPA 版本 1.0.5。若 fnos 升级换密钥，需重新抠。

签名算法（每个 POST 请求都要带 authx header）：
  body_hash = md5(json_dumps(body))         # 紧凑、UTF-8
  nonce     = 6 位随机数
  timestamp = 毫秒级 Unix
  sign      = md5(f"{_SALT}_{path}_{nonce}_{ts}_{body_hash}_{_API_KEY}")
  authx     = f"nonce={nonce}&timestamp={ts}&sign={sign}"

token 行为：分享页每次 GET 都换新 token。**同一 token 连续 POST 多次
会被服务端拒绝（"invalid sign"）**，所以 ShareClient 在遇到该错误时
自动 parse_share 拿新 token 重试。
"""

import hashlib
import json
import random
import re
import threading
import time
from urllib.parse import urlparse

import requests

from .logger import get_logger

log = get_logger(__name__)

# 协议常量
_HOST = "https://s6.fnnas.net"
_SALT = "NDzZTVxnRKP8Z0jXg1VAMonaG8akvh"
_API_KEY = "814&d6470861a4cfbbb4fe2fd3f$6581f6"

# 分享页里嵌入 token 的 JSON：抠 {"token":"...","name":"...","type":...}
_SHARE_DATA_RE = re.compile(
    r'<script id="share-data"[^>]*>(.*?)</script>', re.DOTALL
)


# ---------------- 签名 / HTTP ----------------

def _sign(api_path: str, body_str: str) -> str:
    """生成 authx header。api_path 必须不含 query string。"""
    body_hash = hashlib.md5(body_str.encode("utf-8")).hexdigest()
    nonce = f"{random.randint(0, 999999):06d}"
    ts = str(int(time.time() * 1000))
    raw = f"{_SALT}_{api_path}_{nonce}_{ts}_{body_hash}_{_API_KEY}"
    sign = hashlib.md5(raw.encode("utf-8")).hexdigest()
    return f"nonce={nonce}&timestamp={ts}&sign={sign}"


def _parse_share_url(share_url: str) -> str:
    """从分享 URL 抠 share_id。"""
    p = urlparse(share_url.strip())
    parts = [s for s in p.path.split("/") if s]
    if not parts or parts[0] != "s" or len(parts) < 2:
        raise ValueError(f"不像 fnos 分享链接: {share_url}")
    return parts[1]


def _fetch_token(share_url: str, proxies: dict | None) -> tuple[str, str]:
    """GET 分享页，抠 share_id 和 auth_token。"""
    share_id = _parse_share_url(share_url)
    resp = requests.get(share_url, proxies=proxies, timeout=(10, 20),
                        headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    m = _SHARE_DATA_RE.search(resp.text)
    if not m:
        raise RuntimeError("分享页未找到 share-data（可能链接已失效或被加密）")
    try:
        payload = json.loads(m.group(1).strip())
        token = (payload.get("data") or {}).get("token") or ""
    except Exception as e:
        raise RuntimeError(f"解析 share-data 失败: {e}")
    if not token:
        raise RuntimeError("分享页 token 字段为空（可能需要密码）")
    return share_id, token


def _post_raw(share_id: str, auth: str, api_path: str, body: dict,
              proxies: dict | None) -> dict:
    """单次 POST，不重试。失败抛 RuntimeError 含 'invalid sign'。"""
    body_str = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
    authx = _sign(api_path, body_str)
    resp = requests.post(
        f"{_HOST}{api_path}",
        data=body_str.encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Auth": auth,
            "authx": authx,
            "User-Agent": "Mozilla/5.0",
        },
        proxies=proxies,
        timeout=(10, 30),
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(
            f"fnos API 错误: {data.get('msg')} (code={data.get('code')})"
        )
    return data.get("data") or {}


# ---------------- ShareClient ----------------

class ShareClient:
    """飞牛 NAS 分享会话。封装 token 自动刷新逻辑。

    用法：
        c = fnnas_share.ShareClient("https://s6.fnnas.net/s/xxx")
        files = c.list_files("path/to/dir")
        data = c.stream_download(file_entry)
    """

    def __init__(self, share_url: str, proxies: dict | None = None,
                 max_refresh: int = 3):
        self.share_url = share_url
        self.proxies = proxies
        self.max_refresh = max_refresh  # 单次操作最多刷新 token 几次
        self.share_id, self.auth = _fetch_token(share_url, proxies)

    def _refresh(self) -> None:
        log.debug("refreshing fnnos token: share=%s", self.share_url)
        self.share_id, self.auth = _fetch_token(self.share_url, self.proxies)

    def _post(self, api_path: str, body: dict) -> dict:
        """POST，遇 'invalid sign' 自动刷新 token 重试。"""
        last_err: Exception | None = None
        for attempt in range(self.max_refresh):
            try:
                return _post_raw(self.share_id, self.auth, api_path, body,
                                 self.proxies)
            except RuntimeError as e:
                if "invalid sign" not in str(e):
                    raise
                log.info("fnos invalid sign, refreshing token (attempt %d/%d)",
                         attempt + 1, self.max_refresh)
                last_err = e
                self._refresh()
        raise last_err  # type: ignore

    # ---------------- 列目录 ----------------

    def _list_once(self, path: str, parent_file_id: int) -> list[dict]:
        api = f"/s/{self.share_id}/api/v1/share/list"
        data = self._post(api, {
            "shareId": self.share_id,
            "path": path,
            "fileId": parent_file_id,
        })
        files = data.get("files") or []
        return [f for f in files if isinstance(f, dict)]

    def list_files(self, path: str = "") -> list[dict]:
        """列指定目录。path 多层时自动逐层解析 fileId。

        fnos 协议特性：fileId 才是真正控制列哪个目录的，path 必须配合
        当前层的 fileId。从 root 出发按 path 段逐层向下，每段匹配名字
        找子目录的 fileId。
        """
        path = (path or "").strip("/")
        if not path:
            return self._list_once("", 0)

        segments = path.split("/")
        cur_id = 0
        cur_path = ""
        for seg in segments:
            files = self._list_once(cur_path, cur_id)
            match = next(
                (f for f in files if f.get("file") == seg),
                None,
            )
            if not match:
                return []  # 路径不存在
            cur_id = match.get("fileId", 0)
            cur_path = f"{cur_path}/{seg}".lstrip("/") if cur_path else seg
        return self._list_once(cur_path, cur_id)

    def list_latest_file(self, path: str,
                         file_pattern: re.Pattern) -> dict | None:
        """列 path 目录，按 file_pattern 正则筛选文件（非目录），
        返回 modTime 最大的那个。用于 check_updates。
        """
        files = self.list_files(path)
        candidates = [
            f for f in files
            if not f.get("isDir") and file_pattern.search(f.get("file", ""))
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda f: f.get("modTime", 0))

    # ---------------- 下载 ----------------

    def fetch_download_url(self, file_entry: dict) -> str:
        """POST /share/download，返回一次性下载 path。"""
        api = f"/s/{self.share_id}/api/v1/share/download"
        body = {
            "files": [file_entry],
            "shareId": self.share_id,
            "downloadFilename": file_entry.get("file", ""),
        }
        data = self._post(api, body)
        dl_path = data.get("path") or ""
        if not dl_path:
            raise RuntimeError("fnos 未返回下载地址")
        return dl_path

    def stream_download(self, file_entry: dict, stall_timeout: int = 15,
                        on_progress=None) -> bytes:
        """拉一次性下载 URL → 流式下载。

        关键：必须带 Cookie: {share_id}={auth}，否则返回 SPA HTML 而非文件。
        on_progress(done_bytes, total_bytes) 回调每次写盘后触发。

        stall_timeout：单次 iter_content 阻塞超过 N 秒抛 TimeoutError。
        """
        name = file_entry.get("file", "?")
        size = file_entry.get("size", 0)
        log.info("fnos download start: %s size=%s", name, size)
        dl_path = self.fetch_download_url(file_entry)
        resp = requests.get(
            f"{_HOST}{dl_path}",
            headers={
                "User-Agent": "Mozilla/5.0",
                "Cookie": f"{self.share_id}={self.auth}",
            },
            proxies=self.proxies,
            stream=True,
            timeout=(10, 30),
        )
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", 0))
        buf = bytearray()
        done = 0
        it = resp.iter_content(64 * 1024)
        while True:
            iter_start = time.time()
            try:
                chunk = next(it)
            except StopIteration:
                break
            if time.time() - iter_start > stall_timeout:
                raise TimeoutError(f"下载停滞超过 {stall_timeout}s")
            if not chunk:
                continue
            buf.extend(chunk)
            done += len(chunk)
            if on_progress:
                try:
                    on_progress(done, total)
                except Exception:
                    pass
        log.info("fnos download done: %s bytes=%d", name, len(buf))
        return bytes(buf)
