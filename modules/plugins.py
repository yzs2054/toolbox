"""插件管理：从 GitHub Release 下载外部可执行程序，启停进程，显示状态。

工具箱只做四件事：下载 Release、解压到本地、spawn/kill 进程、显示状态。
插件本身是黑盒 exe，工具箱不调用其内部 API。
"""

import atexit
import io
import json
import os
import platform
import re
import shutil
import subprocess
import tarfile
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

import requests

from . import fnnas_share
from .logger import get_logger
from .subprocess_util import NO_WINDOW

log = get_logger(__name__)

DATA_DIR = Path("data")
PLUGINS_DIR = Path("plugins")
STATE_FILE = PLUGINS_DIR / "state.json"
PROXY_FILE = PLUGINS_DIR / "proxy.json"
FALLBACK_FILE = PLUGINS_DIR / "fallback.json"
PLUGINS_DIR.mkdir(parents=True, exist_ok=True)

# 用户配置的 HTTP 代理（仅作用于插件下载：Release metadata + asset）
_proxy: str = ""

# check_updates 缓存：避免在 1s 轮询里狂打 GitHub API（未鉴权 60/hr 限流）
_UPDATE_CACHE_TTL = 600  # 秒

# 当前系统映射
_OS_KEYWORDS = {
    "windows": ["windows", "win64", "win32", "win-", ".msi"],
    "darwin": ["darwin", "macos", "mac-os", ".dmg", ".pkg"],
    "linux": ["linux", ".appimage", ".deb"],
}
_ARCH_KEYWORDS = {
    "x64": ["x64", "x86_64", "amd64"],
    "arm64": ["arm64", "aarch64"],
}
# 命中以下标签的 asset 优先级降低（safe / lite / minimal 通常是阉割版）
_DEPRIORITIZE = ["safe", "lite", "minimal", "mini"]
# 资产格式优先级（zip 最容易处理）
_FORMAT_PRIORITY = {".zip": 0, ".tar.gz": 1, ".tgz": 1, ".exe": 2, ".appimage": 2}

# GitHub 镜像（同 updater.py 模式）
_GH_MIRRORS = ["", "https://ghproxy.com/", "https://gh-proxy.com/", "https://github.moeyy.xyz/"]
_FETCH_TOTAL_TIMEOUT = 8.0
_FETCH_PER_SOURCE_TIMEOUT = (3, 5)

# 内置预设
_PRESETS = [
    {
        "id": "weixin_channels",
        "name": "微信视频号下载",
        "repo_url": "https://github.com/ltaoo/wx_channels_download",
        "platforms": ["windows"],
        "needs_admin": True,
        "exec_relpath": "wx_video_download.exe",
        "description": (
            "通过本地代理拦截微信 PC 客户端的视频号流量并解密保存为本地 MP4 文件。\n"
            "\n"
            "使用步骤：\n"
            "1. 点「安装」从 GitHub 下载（失败会自动切备用源）。\n"
            "2. 点「启动」，首次会弹 UAC 授权——用于安装抓包用的根证书。\n"
            "3. 授权后插件本身会弹一个新窗口，按照它自己的提示操作。\n"
            "4. 在微信 PC 客户端里打开视频号视频，插件会自动捕获并下载。\n"
            "5. 不用时点「停止」即可。\n"
            "\n"
            "注意：仅 Windows；管理员权限必需；卸载请从「删除」按钮走。"
        ),
    },
]

_state: dict[str, dict] = {}
_processes: dict[str, subprocess.Popen] = {}
_install_progress: dict[str, dict] = {}
_lock = threading.RLock()


# ---------------- 状态持久化（参照 audio_extract.history.json 模式） ----------------

def _load_state() -> None:
    if not STATE_FILE.exists():
        return
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            for rec in data:
                if isinstance(rec, dict) and rec.get("id"):
                    _state[rec["id"]] = rec
    except Exception:
        pass


def _save_state_locked() -> None:
    items = list(_state.values())
    tmp = STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_FILE)


def _persist() -> None:
    with _lock:
        _save_state_locked()


_load_state()


def _load_proxy() -> None:
    global _proxy
    if not PROXY_FILE.exists():
        return
    try:
        data = json.loads(PROXY_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            _proxy = str(data.get("proxy") or "").strip()
    except Exception:
        pass


def _save_proxy_locked() -> None:
    tmp = PROXY_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"proxy": _proxy}, ensure_ascii=False), encoding="utf-8")
    tmp.replace(PROXY_FILE)


def _proxies() -> dict | None:
    """返回 requests.get 用的 proxies 参数。无代理返回 None。"""
    if not _proxy:
        return None
    return {"http": _proxy, "https": _proxy}


def get_proxy() -> str:
    return _proxy


def set_proxy(url: str) -> str:
    """设置代理。空串清空。返回设置后的值。"""
    global _proxy
    url = (url or "").strip()
    with _lock:
        _proxy = url
        _save_proxy_locked()
    return _proxy


_load_proxy()


# ---------------- 备用下载源配置（不公开：用户手动编辑 plugins/fallback.json） ----------------
# 结构：{plugin_id: {"source": "fnos", "share_url": ..., "share_path": ..., "asset_pattern": ...}}
_fallbacks: dict[str, dict] = {}
_fallbacks_mtime: float = 0.0  # 上次加载时的文件 mtime；用于增量 reload


def _load_fallbacks() -> None:
    """加载 fallback.json。幂等：文件 mtime 没变就直接 return，变了才重新解析。

    用户手动编辑文件后无需重启——下次 _get_fallback 调用会触发本函数，
    stat 拿到新 mtime 自动 reload。出错（JSON 语法错）时保留旧内存配置，
    等用户改对后再 reload。
    """
    global _fallbacks_mtime
    if not FALLBACK_FILE.exists():
        if _fallbacks:
            _fallbacks.clear()
            _fallbacks_mtime = 0.0
            log.info("fallback.json removed, cleared in-memory fallbacks")
        return
    try:
        mtime = FALLBACK_FILE.stat().st_mtime
        if mtime == _fallbacks_mtime:
            return  # 文件没变
        data = json.loads(FALLBACK_FILE.read_text(encoding="utf-8"))
        new_fbs: dict[str, dict] = {}
        if isinstance(data, dict):
            for pid, fb in data.items():
                if not isinstance(fb, dict) or not pid:
                    continue
                fb.setdefault("source", "fnos")
                if fb.get("source") == "fnos" and fb.get("share_url") \
                        and fb.get("share_path") and fb.get("asset_pattern"):
                    new_fbs[pid] = fb
        # 原子替换：clear + update，避免半加载状态
        _fallbacks.clear()
        _fallbacks.update(new_fbs)
        _fallbacks_mtime = mtime
        log.info("fallback.json reloaded: %d entries", len(_fallbacks))
    except Exception as e:
        log.warning("fallback.json parse failed, keeping old config: %s", e)


def _save_fallbacks_locked() -> None:
    global _fallbacks_mtime
    tmp = FALLBACK_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(_fallbacks, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(FALLBACK_FILE)
    # 更新 mtime，避免下次 _load_fallbacks 多余 reload（reload 出来的也是同一份内容，无害，但省一次 stat 后的文件读）
    try:
        _fallbacks_mtime = FALLBACK_FILE.stat().st_mtime
    except Exception:
        pass


def _get_fallback(pid: str) -> dict | None:
    """取插件 fallback 配置。state 里的（用户运行时塞进来的）优先于文件。"""
    _load_fallbacks()  # 幂等 stat，mtime 变了才真 reload
    rec = _state.get(pid) or {}
    return rec.get("fallback") or _fallbacks.get(pid)


def get_fallback(plugin_id: str) -> dict | None:
    with _lock:
        fb = _get_fallback(plugin_id)
        return dict(fb) if fb else None


def set_fallback(plugin_id: str, fb: dict | None) -> dict | None:
    """设置/清空插件 fallback。fb=None 删除。返回设置后的值。"""
    with _lock:
        if fb is None:
            _fallbacks.pop(plugin_id, None)
            rec = _state.get(plugin_id)
            if rec:
                rec.pop("fallback", None)
        else:
            clean = {
                "source": str(fb.get("source") or "fnos"),
                "share_url": str(fb.get("share_url") or ""),
                "share_path": str(fb.get("share_path") or ""),
                "asset_pattern": str(fb.get("asset_pattern") or ""),
            }
            if clean["source"] != "fnos" or not clean["share_url"] \
                    or not clean["share_path"] or not clean["asset_pattern"]:
                raise ValueError("fallback 字段不完整：需要 source/share_url/share_path/asset_pattern")
            _fallbacks[plugin_id] = clean
        _save_fallbacks_locked()
        return dict(_fallbacks.get(plugin_id)) if plugin_id in _fallbacks else None


_load_fallbacks()


# ---------------- 工具 ----------------

def _current_os() -> str:
    s = platform.system().lower()
    if s.startswith("win"):
        return "windows"
    if s == "darwin":
        return "darwin"
    return "linux"


def _current_arch() -> str:
    m = platform.machine().lower()
    if m in ("arm64", "aarch64"):
        return "arm64"
    return "x64"


def _parse_repo(github_url: str) -> str:
    """从任意形式的 GitHub URL 提取 'owner/repo'。"""
    p = urlparse(github_url.strip())
    if "github.com" not in (p.netloc or ""):
        raise ValueError("仅支持 github.com 仓库地址")
    parts = [s for s in p.path.split("/") if s]
    if len(parts) < 2:
        raise ValueError("无法解析仓库地址")
    return f"{parts[0]}/{parts[1]}"


def _repo_id(repo: str) -> str:
    """owner/repo → plugin_id（用 repo 名做 slug）。"""
    return repo.split("/")[-1].lower().replace("-", "_").replace(".", "_")


def _record_view(rec: dict) -> dict:
    """合并运行时 status 后给前端看的视图。"""
    pid = rec["id"]
    installed = bool(rec.get("installed_version"))
    installing = _install_progress.get(pid, {}).get("status") in ("downloading", "extracting")
    proc = _processes.get(pid)
    running = bool(proc and proc.poll() is None)

    if rec.get("last_error") and not installing:
        status = "error"
    elif installing:
        status = "installing"
    elif running:
        status = "running"
    elif installed:
        status = "installed"
    else:
        status = "not_installed"

    out = dict(rec)
    out["status"] = status
    out["running_pid"] = getattr(proc, "pid", None) if running else None
    out["install_progress"] = _install_progress.get(pid)
    return out


# ---------------- GitHub Release 拉取（镜像抢答） ----------------

def _fetch_release(repo: str) -> tuple[str, dict] | None:
    """多镜像并发抢答，返回 (镜像前缀, release_json)。失败返回 None。"""
    api = f"https://api.github.com/repos/{repo}/releases/latest"

    def _try(mirror: str):
        url = mirror + api if mirror else api
        try:
            resp = requests.get(url, timeout=_FETCH_PER_SOURCE_TIMEOUT, proxies=_proxies())
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict) and data.get("tag_name"):
                return mirror, data
        except Exception:
            return None
        return None

    with ThreadPoolExecutor(max_workers=len(_GH_MIRRORS)) as ex:
        futures = {ex.submit(_try, m): m for m in _GH_MIRRORS}
        try:
            for fut in as_completed(futures, timeout=_FETCH_TOTAL_TIMEOUT):
                r = fut.result()
                if r:
                    return r
        except Exception:
            pass
    return None


def _pick_asset(assets: list[dict]) -> dict | None:
    """从 Release assets 里挑出当前平台/架构最合适的那个。"""
    os_kw = _OS_KEYWORDS.get(_current_os(), [])
    arch_kw = _ARCH_KEYWORDS.get(_current_arch(), [])

    def fmt_prio(name: str) -> int:
        low = name.lower()
        for ext, p in _FORMAT_PRIORITY.items():
            if low.endswith(ext):
                return p
        return 99

    def score(a: dict) -> tuple:
        """分值越小越优：(deprioritize, format_prio, name)。"""
        low = a["name"].lower()
        depri = 1 if any(tag in low for tag in _DEPRIORITIZE) else 0
        return (depri, fmt_prio(low), low)

    candidates: list[dict] = []
    for a in assets:
        low = a["name"].lower()
        if not any(kw in low for kw in os_kw):
            continue
        # 拒绝不支持的格式
        if low.endswith((".dmg", ".pkg", ".msi")):
            continue
        candidates.append(a)

    if not candidates:
        return None

    # 优先选同时匹配 arch 的
    arch_match = [a for a in candidates if any(kw in a["name"].lower() for kw in arch_kw)]
    pool = arch_match if arch_match else candidates
    pool.sort(key=score)
    return pool[0]


# ---------------- 安装/更新 ----------------

def _set_progress(pid: str, status: str, progress: int, message: str) -> None:
    with _lock:
        _install_progress[pid] = {"status": status, "progress": progress, "message": message}


def _clear_progress(pid: str) -> None:
    with _lock:
        _install_progress.pop(pid, None)


def _stream_download(url: str, pid: str, stall_timeout: int = 15) -> bytes:
    """流式下载，边下边写进度。失败抛异常。

    stall_timeout：单次 iter_content 阻塞超过 N 秒就抛 TimeoutError。
    解决"连接活着但偶尔吐 1 byte 永不触发 read timeout"的慢镜像——
    每次取一块 64KB 都卡住 N 秒，说明镜像本身在拖。
    """
    resp = requests.get(url, stream=True, timeout=(10, 30), proxies=_proxies())
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
        if total:
            _set_progress(pid, "downloading", round(done / total * 100), "下载中...")
    return bytes(buf)


def _safe_extract_zip(buf: bytes, target: Path) -> None:
    """解压 zip 到 target，校验 zip-slip。"""
    target_resolved = target.resolve()
    with zipfile.ZipFile(io.BytesIO(buf)) as zf:
        for member in zf.namelist():
            dest = (target / member).resolve()
            try:
                dest.relative_to(target_resolved)
            except ValueError:
                continue
            zf.extract(member, target)


def _safe_extract_tar(buf: bytes, target: Path) -> None:
    target_resolved = target.resolve()
    with tarfile.open(fileobj=io.BytesIO(buf), mode="r:*") as tf:
        for m in tf.getmembers():
            try:
                (target / m.name).resolve().relative_to(target_resolved)
            except ValueError:
                continue
            tf.extract(m, target)


def _guess_exec_relpath(plugin_dir: Path, hint: str = "") -> str:
    """从解压后的目录里猜可执行文件的相对路径。"""
    if hint:
        p = plugin_dir / hint
        if p.exists():
            return hint

    os_name = _current_os()
    candidates: list[Path] = []
    for p in plugin_dir.rglob("*"):
        if not p.is_file():
            continue
        name = p.name.lower()
        if os_name == "windows" and name.endswith(".exe"):
            candidates.append(p)
        elif os_name == "darwin" and (p.stat().st_mode & 0o111) and "." not in p.name:
            candidates.append(p)
        elif os_name == "linux" and (p.stat().st_mode & 0o111) and "." not in name:
            candidates.append(p)

    if not candidates:
        return ""
    # 按路径深度浅的优先，名字带项目名（wx_channels/wx_video）的优先
    candidates.sort(key=lambda p: (len(p.parts), -len(p.name), str(p)))
    return str(candidates[0].relative_to(plugin_dir))


def _maybe_unwrap_nested_zip(plugin_dir: Path) -> None:
    """fnos 单文件分享会自动多套一层 zip 壳：外层 dirname/realfile.zip，
    内层才是真正的程序包。如果解压后 plugin_dir 里**只有一个 .zip 文件**
    且没有其他非目录文件，把它就地再解压一次，删掉外层 zip。

    GitHub Release 是原生 zip，不会触发这个。
    """
    zip_files = list(plugin_dir.rglob("*.zip"))
    if len(zip_files) != 1:
        return
    other_files = [
        p for p in plugin_dir.rglob("*")
        if p.is_file() and not p.name.endswith(".zip")
    ]
    if other_files:
        return
    outer = zip_files[0]
    try:
        _safe_extract_zip(outer.read_bytes(), outer.parent)
        outer.unlink()
    except Exception:
        pass


def _try_install_from_github(pid: str, repo: str, force: bool) -> None:
    """主源：拉 GitHub Release、选 asset、多镜像下载、解压。
    成功（含已是最新版本）返回 None；失败抛异常，外层会尝试 fallback。
    """
    rec = _state.get(pid) or {}
    installed_version = rec.get("installed_version", "")

    _set_progress(pid, "downloading", 0, "查询 GitHub Release...")
    result = _fetch_release(repo)
    if not result:
        raise RuntimeError("无法获取 Release 信息（GitHub 不可达且镜像全部失败）")
    # 用户可能在下载阶段就点删除，提前退出
    with _lock:
        if pid not in _state:
            _clear_progress(pid)
            return
    mirror, release = result
    latest = release["tag_name"]
    if not force and installed_version == latest:
        _set_progress(pid, "done", 100, f"已是最新版本 {latest}")
        time.sleep(1)
        _clear_progress(pid)
        return

    asset = _pick_asset(release.get("assets") or [])
    if not asset:
        raise RuntimeError("未找到适合当前系统的安装包")

    # 元数据赢家优先，失败按镜像列表往下试，最后兜底直连
    dl_url = asset["browser_download_url"]
    tried: set[str] = set()
    order: list[str] = []
    if mirror and mirror not in tried:
        order.append(mirror)
        tried.add(mirror)
    for m in _GH_MIRRORS:
        if m not in tried:
            order.append(m)
            tried.add(m)

    data: bytes | None = None
    last_err: Exception | None = None
    for m in order:
        label = m.rstrip("/") or "直连"
        url = m + dl_url if m else dl_url
        _set_progress(pid, "downloading", 0, f"下载 {asset['name']}（{label}）...")
        try:
            data = _stream_download(url, pid)
            break
        except Exception as e:
            last_err = e
            _set_progress(pid, "downloading", 0, f"{label} 失败，切换镜像...")
            continue
    if data is None:
        raise RuntimeError(f"所有镜像下载失败：{last_err}")

    plugin_dir = PLUGINS_DIR / pid
    if plugin_dir.exists():
        shutil.rmtree(plugin_dir, ignore_errors=True)
    plugin_dir.mkdir(parents=True, exist_ok=True)

    _set_progress(pid, "extracting", 100, "解压中...")
    name_low = asset["name"].lower()
    if name_low.endswith(".zip"):
        _safe_extract_zip(data, plugin_dir)
    elif name_low.endswith((".tar.gz", ".tgz")):
        _safe_extract_tar(data, plugin_dir)
    elif name_low.endswith(".exe"):
        (plugin_dir / asset["name"]).write_bytes(data)
    elif name_low.endswith(".appimage"):
        target = plugin_dir / asset["name"]
        target.write_bytes(data)
        target.chmod(0o755)
    else:
        raise RuntimeError(f"暂不支持该安装包格式: {asset['name']}")

    exec_relpath = _guess_exec_relpath(plugin_dir, rec.get("exec_relpath", ""))

    with _lock:
        # 安装过程中被 remove：清掉刚解压的目录就退出，不复活 state
        if pid not in _state:
            shutil.rmtree(plugin_dir, ignore_errors=True)
            _clear_progress(pid)
            return
        # 用 preset 做底，避免历史残缺记录丢字段（如 repo_url）
        preset = next((p for p in _PRESETS if p["id"] == pid), None)
        base = dict(preset) if preset else {}
        rec = _state.setdefault(pid, base)
        if preset:
            for k, v in preset.items():
                rec.setdefault(k, v)
        rec["installed_version"] = latest
        rec["latest_version"] = latest
        rec["latest_checked_at"] = time.time()
        rec["exec_relpath"] = exec_relpath
        rec["last_error"] = ""
        _save_state_locked()

    _set_progress(pid, "done", 100, f"已安装 {latest}")
    time.sleep(1)
    _clear_progress(pid)


def _install_from_fnos(pid: str, fb: dict, force: bool) -> None:
    """备用源：从 fnos 公开分享下载。
    fb 字段：{share_url, share_path, asset_pattern}。版本号用 modTime 格式化成 vYYYY-MM-DD。
    """
    pattern = re.compile(fb["asset_pattern"])
    _set_progress(pid, "downloading", 0, "查询备用源（fnnas）...")
    # fnos 是国内服务，不走 GitHub 代理（否则代理打不通 fnnas 会整条线挂掉）
    client = fnnas_share.ShareClient(fb["share_url"], None)
    entry = client.list_latest_file(fb["share_path"], pattern)
    if not entry:
        raise RuntimeError("备用源中未找到匹配文件")

    latest = "v" + time.strftime("%Y-%m-%d", time.localtime(entry["modTime"]))

    with _lock:
        rec = _state.get(pid) or {}
        if not force and rec.get("installed_version") == latest:
            _set_progress(pid, "done", 100, f"已是最新版本 {latest}")
            time.sleep(1)
            _clear_progress(pid)
            return

    _set_progress(pid, "downloading", 0, f"备用源下载 {entry['file']}...")
    def on_progress(d, t):
        pct = round(d / t * 100) if t else 0
        _set_progress(pid, "downloading", pct, "下载中（fnnas）...")
    data = client.stream_download(entry, on_progress=on_progress)

    plugin_dir = PLUGINS_DIR / pid
    if plugin_dir.exists():
        shutil.rmtree(plugin_dir, ignore_errors=True)
    plugin_dir.mkdir(parents=True, exist_ok=True)

    _set_progress(pid, "extracting", 100, "解压中...")
    _safe_extract_zip(data, plugin_dir)
    _maybe_unwrap_nested_zip(plugin_dir)

    exec_relpath = _guess_exec_relpath(plugin_dir, rec.get("exec_relpath", ""))

    with _lock:
        if pid not in _state:
            shutil.rmtree(plugin_dir, ignore_errors=True)
            _clear_progress(pid)
            return
        preset = next((p for p in _PRESETS if p["id"] == pid), None)
        base = dict(preset) if preset else {}
        rec = _state.setdefault(pid, base)
        if preset:
            for k, v in preset.items():
                rec.setdefault(k, v)
        rec["installed_version"] = latest
        rec["latest_version"] = latest
        rec["latest_checked_at"] = time.time()
        rec["exec_relpath"] = exec_relpath
        rec["last_error"] = ""
        _save_state_locked()

    _set_progress(pid, "done", 100, f"已安装 {latest}（备用源）")
    time.sleep(1)
    _clear_progress(pid)


def _install_worker(pid: str, repo: str, force: bool) -> None:
    """后台线程：先试 GitHub 主源，失败时尝试 fallback。"""
    log.info("install start: pid=%s repo=%s force=%s", pid, repo, force)
    try:
        try:
            _try_install_from_github(pid, repo, force)
            log.info("install ok: pid=%s via github", pid)
            return
        except Exception as gh_err:
            # 主源失败，看有没有备用源
            with _lock:
                fb = _get_fallback(pid)
            if not fb:
                log.warning("install failed (no fallback): pid=%s err=%s",
                            pid, gh_err)
                raise
            src = fb.get("source", "?")
            log.info("primary failed, switching to fallback: pid=%s source=%s err=%s",
                     pid, src, gh_err)
            _set_progress(
                pid, "downloading", 0,
                f"主源失败（{str(gh_err)[:60]}），切换备用源（{src}）..."
            )
            if fb.get("source") == "fnos":
                _install_from_fnos(pid, fb, force)
                log.info("install ok: pid=%s via fnos", pid)
            else:
                raise RuntimeError(f"不支持的 fallback source: {fb.get('source')}")
    except Exception as e:
        msg = str(e)[:200]
        log.exception("install failed: pid=%s", pid)
        with _lock:
            rec = _state.get(pid)
            if rec is not None:
                rec["last_error"] = msg
                _save_state_locked()
        _set_progress(pid, "error", 0, msg)


# ---------------- 进程启停 ----------------

def _spawn_elevated(exe: Path, workdir: Path) -> bool:
    """Windows 下用 ShellExecuteW 触发 UAC 启动。返回是否成功。"""
    import ctypes
    rc = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", str(exe), "", str(workdir), 1  # SW_SHOWNORMAL
    )
    # 返回 HINSTANCE，>32 表示成功
    return int(rc) > 32


def _taskkill_by_name(image_name: str) -> None:
    """Windows 下按映像名强杀。"""
    try:
        subprocess.run(
            ["taskkill", "/F", "/IM", image_name],
            capture_output=True, timeout=10,
            creationflags=NO_WINDOW,
        )
    except Exception:
        pass


def _platform_supported(rec: dict) -> bool:
    return _current_os() in (rec.get("platforms") or [])


def start(plugin_id: str) -> None:
    with _lock:
        rec = _state.get(plugin_id)
        if not rec:
            raise ValueError("插件不存在")
        if not rec.get("installed_version"):
            raise RuntimeError("插件未安装")
        if not _platform_supported(rec):
            raise RuntimeError(f"该插件仅支持 {rec.get('platforms') or []}，当前系统 {_current_os()}")

        # 已在跑就别再起
        existing = _processes.get(plugin_id)
        if existing and existing.poll() is None:
            log.info("start skipped (already running): pid=%s", plugin_id)
            return

        exe = (PLUGINS_DIR / plugin_id / rec["exec_relpath"]).resolve()
        if not exe.exists():
            rec["last_error"] = f"可执行文件不存在：{rec['exec_relpath']}"
            _save_state_locked()
            raise RuntimeError(rec["last_error"])

        workdir = (PLUGINS_DIR / plugin_id).resolve()
        needs_admin = bool(rec.get("needs_admin")) and _current_os() == "windows"
        log.info("start: pid=%s exe=%s needs_admin=%s", plugin_id, exe, needs_admin)

        if needs_admin:
            ok = _spawn_elevated(exe, workdir)
            log.info("_spawn_elevated returned %s: pid=%s", ok, plugin_id)
            if not ok:
                rec["last_error"] = "启动失败（可能拒绝了授权）"
                _save_state_locked()
                raise RuntimeError(rec["last_error"])
            # ShellExecuteW 拿不到 Popen，用一个 sentinel 占位，stop 走 taskkill
            _processes[plugin_id] = _ElevatedSentinel(exe.name)
            log.info("sentinel added: pid=%s image=%s", plugin_id, exe.name)
        else:
            try:
                proc = subprocess.Popen(
                    [str(exe)],
                    cwd=str(workdir),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=NO_WINDOW,
                )
            except Exception as e:
                rec["last_error"] = f"启动失败：{e}"
                _save_state_locked()
                log.exception("Popen failed: pid=%s", plugin_id)
                raise
            _processes[plugin_id] = proc
            log.info("Popen ok: pid=%s proc_pid=%s", plugin_id, proc.pid)

        rec["last_error"] = ""
        _save_state_locked()


class _ElevatedSentinel:
    """ShellExecuteW 启动的进程占位对象，poll() 永远返回 None（无法判断），
    terminate()/kill() 用 taskkill 兜底。pid 为 None（ShellExecuteW 拿不到）。"""

    def __init__(self, image_name: str):
        self.image_name = image_name
        self.pid = None  # _record_view 会读 proc.pid

    def poll(self):
        return None  # 视为仍在运行

    def terminate(self):
        _taskkill_by_name(self.image_name)

    def kill(self):
        _taskkill_by_name(self.image_name)


def stop(plugin_id: str) -> None:
    with _lock:
        proc = _processes.pop(plugin_id, None)
    if not proc:
        log.info("stop noop (not running): pid=%s", plugin_id)
        return
    log.info("stop: pid=%s", plugin_id)
    try:
        proc.terminate()
        try:
            proc.wait(timeout=3)
            return
        except Exception:
            pass
        proc.kill()
    except Exception as e:
        log.warning("stop failed: pid=%s err=%s", plugin_id, e)


def _cleanup_processes() -> None:
    with _lock:
        ids = list(_processes.keys())
    for pid in ids:
        stop(pid)


atexit.register(_cleanup_processes)


# ---------------- Public API ----------------

def list_plugins() -> list[dict]:
    """合并 preset + state，附 runtime status。"""
    with _lock:
        out = []
        seen = set()
        # 先 preset
        for preset in _PRESETS:
            seen.add(preset["id"])
            rec = _state.get(preset["id"]) or dict(preset)
            # preset 提供默认字段，state 覆盖
            merged = {**preset, **{k: v for k, v in rec.items() if v not in (None, "")}}
            out.append(_record_view(merged))
        # 再用户自己加的
        for pid, rec in _state.items():
            if pid in seen:
                continue
            out.append(_record_view(dict(rec)))
        return out


def add_repo(github_url: str) -> dict:
    """添加 GitHub 仓库作为插件源。"""
    repo = _parse_repo(github_url)
    pid = _repo_id(repo)
    with _lock:
        # 按 repo_url 去重：避免用户把 preset 的同一个仓库又加一遍
        existing_urls = {p.get("repo_url", "").rstrip("/") for p in _PRESETS}
        existing_urls |= {r.get("repo_url", "").rstrip("/") for r in _state.values()}
        if f"https://github.com/{repo}".rstrip("/") in existing_urls:
            raise ValueError("该仓库已添加")
        if any(p["id"] == pid for p in _PRESETS):
            raise ValueError(f"插件 id {pid} 与内置插件冲突")
        if pid in _state:
            raise ValueError(f"插件 {pid} 已存在")

        # 拉 Release 探测 platforms（从 asset 名字推断）
        result = _fetch_release(repo)
        if not result:
            raise RuntimeError("无法访问该仓库的 Release（GitHub 不可达）")
        _, release = result
        assets = release.get("assets") or []
        platforms = set()
        for a in assets:
            name = a["name"].lower()
            if any(kw in name for kw in _OS_KEYWORDS["windows"]):
                platforms.add("windows")
            if any(kw in name for kw in _OS_KEYWORDS["darwin"]):
                platforms.add("darwin")
            if any(kw in name for kw in _OS_KEYWORDS["linux"]):
                platforms.add("linux")
        if not platforms:
            platforms = {"windows", "darwin", "linux"}

        rec = {
            "id": pid,
            "name": repo.split("/")[-1],
            "repo_url": f"https://github.com/{repo}",
            "platforms": sorted(platforms),
            "needs_admin": False,
            "exec_relpath": "",
            "installed_version": "",
            "latest_version": release.get("tag_name", ""),
            "latest_checked_at": time.time(),
            "added_at": time.time(),
            "last_error": "",
        }
        _state[pid] = rec
        _save_state_locked()
        return _record_view(dict(rec))


def install(plugin_id: str) -> None:
    """后台下载并安装最新 Release。"""
    with _lock:
        rec = _state.get(plugin_id)
        preset = next((p for p in _PRESETS if p["id"] == plugin_id), None)
        if not rec:
            if not preset:
                raise ValueError("插件不存在")
            rec = dict(preset)
            rec.update({
                "installed_version": "",
                "latest_version": "",
                "latest_checked_at": 0,
                "added_at": time.time(),
                "last_error": "",
            })
            _state[plugin_id] = rec
            _save_state_locked()
        elif preset:
            # state 记录可能因历史 bug 残缺（缺 repo_url 等），用 preset 兜底
            for k, v in preset.items():
                rec.setdefault(k, v)
        repo_url = rec.get("repo_url")
        if not repo_url:
            raise ValueError("插件缺少 repo_url")
        repo = _parse_repo(repo_url)

    # 已在跑就别重装
    if _install_progress.get(plugin_id, {}).get("status") in ("downloading", "extracting"):
        return

    t = threading.Thread(
        target=_install_worker,
        args=(plugin_id, repo, False),
        daemon=True,
    )
    t.start()


def update(plugin_id: str) -> None:
    """强制重装最新版（不论是否已是最新）。"""
    with _lock:
        rec = _state.get(plugin_id)
        if not rec:
            raise ValueError("插件不存在")
        preset = next((p for p in _PRESETS if p["id"] == plugin_id), None)
        if preset:
            for k, v in preset.items():
                rec.setdefault(k, v)
        repo_url = rec.get("repo_url")
        if not repo_url:
            raise ValueError("插件缺少 repo_url")
        repo = _parse_repo(repo_url)

    if _install_progress.get(plugin_id, {}).get("status") in ("downloading", "extracting"):
        return

    t = threading.Thread(
        target=_install_worker,
        args=(plugin_id, repo, True),
        daemon=True,
    )
    t.start()


def check_updates(plugin_id: str | None = None, force: bool = False) -> dict[str, str]:
    """刷新 latest_version。force=True 时忽略缓存。返回 {plugin_id: latest_version}。"""
    now = time.time()
    targets: list[str] = []
    with _lock:
        if plugin_id:
            if plugin_id not in _state and not any(p["id"] == plugin_id for p in _PRESETS):
                raise ValueError("插件不存在")
            targets = [plugin_id]
        else:
            targets = list(_state.keys())
            for p in _PRESETS:
                if p["id"] not in targets:
                    targets.append(p["id"])

    out: dict[str, str] = {}
    for pid in targets:
        with _lock:
            rec = _state.get(pid)
            if rec and not force and rec.get("latest_checked_at", 0) + _UPDATE_CACHE_TTL > now:
                out[pid] = rec.get("latest_version", "")
                continue

        # preset 没实例化时临时取 repo_url / fallback
        preset = next((p for p in _PRESETS if p["id"] == pid), None)
        repo_url = (rec or {}).get("repo_url") or (preset or {}).get("repo_url", "")
        fallback = _get_fallback(pid)

        latest = ""
        if repo_url:
            result = _fetch_release(_parse_repo(repo_url))
            if result:
                _, release = result
                latest = release.get("tag_name", "")

        # GitHub 不可达 / 没配 repo_url → 尝试 fallback
        if not latest and fallback and fallback.get("source") == "fnos":
            try:
                client = fnnas_share.ShareClient(fallback["share_url"], None)
                entry = client.list_latest_file(
                    fallback["share_path"],
                    re.compile(fallback["asset_pattern"]),
                )
                if entry:
                    latest = "v" + time.strftime(
                        "%Y-%m-%d", time.localtime(entry["modTime"])
                    )
            except Exception:
                pass

        if not latest:
            continue

        with _lock:
            r = _state.setdefault(pid, {})
            r["latest_version"] = latest
            r["latest_checked_at"] = now
            _save_state_locked()
        out[pid] = latest
    return out


def remove(plugin_id: str) -> None:
    """停止 + 删除插件目录 + 删除 state 记录。preset 不删（仍出现在列表里）。"""
    stop(plugin_id)
    with _lock:
        plugin_dir = PLUGINS_DIR / plugin_id
        if plugin_dir.exists():
            shutil.rmtree(plugin_dir, ignore_errors=True)
        _state.pop(plugin_id, None)
        _install_progress.pop(plugin_id, None)
        _save_state_locked()


def get_status(plugin_id: str | None = None) -> dict:
    """单个或全部状态，附 install 进度。"""
    if plugin_id:
        with _lock:
            rec = _state.get(plugin_id)
            if not rec:
                preset = next((p for p in _PRESETS if p["id"] == plugin_id), None)
                if not preset:
                    raise ValueError("插件不存在")
                rec = dict(preset)
            return _record_view(dict(rec))
    with _lock:
        items = list_plugins()
    return {
        "items": items,
        "installs": dict(_install_progress),
    }


def get_install_progress() -> dict[str, dict]:
    with _lock:
        return dict(_install_progress)
