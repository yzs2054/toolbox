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

from .subprocess_util import NO_WINDOW

DATA_DIR = Path("data")
PLUGINS_DIR = Path("plugins")
STATE_FILE = DATA_DIR / "plugins_state.json"
PLUGINS_DIR.mkdir(parents=True, exist_ok=True)

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
        "description": "通过本地代理拦截微信 PC 客户端的视频号流量并解密保存。Windows 专用，启动需管理员权限（首次会弹 UAC 安装根证书）。",
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
    out["running_pid"] = proc.pid if running else None
    out["install_progress"] = _install_progress.get(pid)
    return out


# ---------------- GitHub Release 拉取（镜像抢答） ----------------

def _fetch_release(repo: str) -> tuple[str, dict] | None:
    """多镜像并发抢答，返回 (镜像前缀, release_json)。失败返回 None。"""
    api = f"https://api.github.com/repos/{repo}/releases/latest"

    def _try(mirror: str):
        url = mirror + api if mirror else api
        try:
            resp = requests.get(url, timeout=_FETCH_PER_SOURCE_TIMEOUT)
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


def _stream_download(url: str, pid: str) -> bytes:
    """流式下载，边下边写进度。返回完整 bytes。失败抛异常。"""
    resp = requests.get(url, stream=True, timeout=(10, 30))
    resp.raise_for_status()
    total = int(resp.headers.get("content-length", 0))
    buf = bytearray()
    done = 0
    for chunk in resp.iter_content(64 * 1024):
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


def _install_worker(pid: str, repo: str, force: bool) -> None:
    """后台线程：拉 Release、选 asset、下载、解压。"""
    try:
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
            rec = _state.setdefault(pid, {})
            rec["installed_version"] = latest
            rec["latest_version"] = latest
            rec["latest_checked_at"] = time.time()
            rec["exec_relpath"] = exec_relpath
            rec["last_error"] = ""
            _save_state_locked()

        _set_progress(pid, "done", 100, f"已安装 {latest}")
        time.sleep(1)
        _clear_progress(pid)

    except Exception as e:
        msg = str(e)[:200]
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
            return

        exe = (PLUGINS_DIR / plugin_id / rec["exec_relpath"]).resolve()
        if not exe.exists():
            rec["last_error"] = f"可执行文件不存在：{rec['exec_relpath']}"
            _save_state_locked()
            raise RuntimeError(rec["last_error"])

        workdir = (PLUGINS_DIR / plugin_id).resolve()
        needs_admin = bool(rec.get("needs_admin")) and _current_os() == "windows"

        if needs_admin:
            ok = _spawn_elevated(exe, workdir)
            if not ok:
                rec["last_error"] = "启动失败（可能拒绝了授权）"
                _save_state_locked()
                raise RuntimeError(rec["last_error"])
            # ShellExecuteW 拿不到 Popen，用一个 sentinel 占位，stop 走 taskkill
            _processes[plugin_id] = _ElevatedSentinel(exe.name)
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
                raise
            _processes[plugin_id] = proc

        rec["last_error"] = ""
        _save_state_locked()


class _ElevatedSentinel:
    """ShellExecuteW 启动的进程占位对象，poll() 永远返回 0（无法判断），
    terminate()/kill() 用 taskkill 兜底。"""

    def __init__(self, image_name: str):
        self.image_name = image_name

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
        return
    try:
        proc.terminate()
        try:
            proc.wait(timeout=3)
            return
        except Exception:
            pass
        proc.kill()
    except Exception:
        pass


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
        if not rec:
            # 可能是 preset 还未实例化
            preset = next((p for p in _PRESETS if p["id"] == plugin_id), None)
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
        repo = _parse_repo(rec["repo_url"])

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
        repo = _parse_repo(rec["repo_url"])

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

        # preset 没实例化时临时取 repo_url
        repo_url = (rec or {}).get("repo_url") or next(
            (p["repo_url"] for p in _PRESETS if p["id"] == pid), ""
        )
        if not repo_url:
            continue
        result = _fetch_release(_parse_repo(repo_url))
        if not result:
            continue
        _, release = result
        latest = release.get("tag_name", "")
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
