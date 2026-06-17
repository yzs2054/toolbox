"""自动更新模块 — 从 GitHub Releases 检查并下载新版本。"""

import io
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

from version import VERSION

# 改成你自己的 GitHub 仓库地址
GITHUB_REPO = "yzs2054/toolbox"
RELEASE_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

# 国内访问 api.github.com / github.com 经常超时，加几个反代兜底。
# 元素结构：(镜像前缀, 该镜像下完整的 releases/latest URL)
#   - 镜像前缀为 "" 表示直连，对应的 URL 是原始地址
#   - 其他镜像前缀用于把后续 download_url 也走同一个镜像
_MIRRORS = [
    ("", RELEASE_API),
    ("https://ghproxy.com/", f"https://ghproxy.com/{RELEASE_API}"),
    ("https://gh-proxy.com/", f"https://gh-proxy.com/{RELEASE_API}"),
    ("https://github.moeyy.xyz/", f"https://github.moeyy.xyz/{RELEASE_API}"),
]
_CHECK_TOTAL_TIMEOUT = 8.0
_CHECK_PER_SOURCE_TIMEOUT = (3, 5)  # (connect, read)

_progress = {"status": "idle", "progress": 0, "message": ""}
_working_mirror = ""  # 检查阶段成功的镜像前缀，下载阶段复用


def get_current_version() -> str:
    return VERSION


def get_variant() -> str:
    """入口文件（main.py / app.py）在启动时设 TOOLBOX_VARIANT 环境变量。"""
    return os.environ.get("TOOLBOX_VARIANT", "dev")


def _parse_version(v: str) -> tuple:
    """'v1.2.0' → (1, 2, 0)，非数字段当 0 处理。"""
    parts = []
    for p in (v or "").lstrip("vV").split("."):
        n = ""
        for ch in p:
            if ch.isdigit():
                n += ch
            else:
                break
        parts.append(int(n) if n else 0)
    return tuple(parts) or (0,)


def _fetch_release_json() -> tuple[str, dict] | None:
    """多源并发拉 releases/latest，返回 (生效的镜像前缀, release json)。
    所有源都失败或总超时则返回 None。"""
    global _working_mirror

    def _try(mirror_prefix: str, url: str):
        try:
            resp = requests.get(url, timeout=_CHECK_PER_SOURCE_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict) and data.get("tag_name"):
                return mirror_prefix, data
        except Exception:
            return None
        return None

    with ThreadPoolExecutor(max_workers=len(_MIRRORS)) as ex:
        futures = {ex.submit(_try, m, u): m for m, u in _MIRRORS}
        try:
            for fut in as_completed(futures, timeout=_CHECK_TOTAL_TIMEOUT):
                r = fut.result()
                if r:
                    return r
        except Exception:
            pass
    return None


def check_update() -> dict:
    """检查 GitHub Releases 是否有新版本。"""
    try:
        result = _fetch_release_json()
        if not result:
            return {
                "has_update": False,
                "current": get_current_version(),
                "error": "所有更新源都不可用（可能网络受限，稍后重试）",
            }
        mirror_prefix, release = result
        latest = release["tag_name"]
        current = get_current_version()
        variant = get_variant()
        assets = release.get("assets", [])
        download_url = ""
        # 按 variant 选 asset（dev 模式默认 web）
        target_variant = variant if variant != "dev" else "web"
        for a in assets:
            name = a["name"].lower()
            if "windows" in name and f"-{target_variant}" in name:
                download_url = a["browser_download_url"]
                break
        # 下载阶段继续用检查阶段跑通的镜像
        if mirror_prefix and download_url:
            download_url = mirror_prefix + download_url
        _working_mirror = mirror_prefix
        return {
            "has_update": _parse_version(latest) > _parse_version(current),
            "current": current,
            "latest": latest,
            "notes": (release.get("body") or "")[:500],
            "download_url": download_url,
        }
    except Exception as e:
        return {"has_update": False, "current": get_current_version(), "error": str(e)[:200]}


def _stream_download(url: str, timeout=(10, 30)) -> requests.Response | None:
    """发起流式 GET，连接失败/4xx/5xx 返回 None。"""
    try:
        resp = requests.get(url, stream=True, timeout=timeout)
        resp.raise_for_status()
        return resp
    except Exception:
        return None


def _do_update(download_url: str):
    """后台下载并准备更新。"""
    global _progress
    _progress = {"status": "downloading", "progress": 0, "message": "正在下载更新包..."}

    try:
        resp = _stream_download(download_url)
        # 下载失败时兜底走原始 github.com 直链
        if resp is None and _working_mirror and download_url.startswith(_working_mirror):
            original = download_url[len(_working_mirror):]
            _progress["message"] = "镜像下载失败，切换到原始源..."
            resp = _stream_download(original)
        if resp is None:
            raise RuntimeError("下载失败，请检查网络后重试")

        total = int(resp.headers.get("content-length", 0))
        buf = io.BytesIO()
        done = 0
        for chunk in resp.iter_content(8192):
            buf.write(chunk)
            done += len(chunk)
            if total:
                _progress["progress"] = round(done / total * 100)

        _progress["message"] = "正在解压并替换文件..."
        _progress["progress"] = 100

        # 解压到临时目录
        tmp = tempfile.mkdtemp()
        with zipfile.ZipFile(buf) as zf:
            zf.extractall(tmp)

        # 找到 exe 所在目录
        if getattr(sys, "frozen", False):
            app_dir = Path(sys.executable).parent
            app_name = Path(sys.executable).name
        else:
            app_dir = Path(".").resolve()
            app_name = ""

        # 把新文件复制到更新目录
        update_dir = app_dir / "_update"
        update_dir.mkdir(exist_ok=True)
        for f in Path(tmp).iterdir():
            shutil.copy2(f, update_dir / f.name)

        shutil.rmtree(tmp, ignore_errors=True)

        # 生成更新脚本
        if platform.system() == "Windows":
            _write_windows_updater(app_dir, app_name, update_dir)
        else:
            _write_linux_updater(app_dir, app_name, update_dir)

        _progress = {"status": "ready", "progress": 100, "message": "更新已就绪，重启后生效"}

    except Exception as e:
        _progress = {"status": "error", "progress": 0, "message": f"更新失败: {e}"}


def _write_windows_updater(app_dir: Path, app_name: str, update_dir: Path):
    script = app_dir / "_update.bat"
    content = f"""@echo off
echo 正在更新工具箱...
taskkill /f /im {app_name} 2>nul
timeout /t 2 /nobreak >nul
copy /y "{update_dir}\\*" "{app_dir}\\"
echo 更新完成，正在启动...
start "" "{app_dir}\\{app_name}"
rd /s /q "{update_dir}"
del "%~f0"
"""
    script.write_text(content, encoding="gbk")
    subprocess.Popen(["cmd", "/c", str(script)], shell=True)


def _write_linux_updater(app_dir: Path, app_name: str, update_dir: Path):
    script = app_dir / "_update.sh"
    content = f"""#!/bin/bash
echo "正在更新工具箱..."
sleep 2
cp -f {update_dir}/* {app_dir}/
echo "更新完成，正在启动..."
rm -rf {update_dir}
rm -- "$0"
"""
    script.write_text(content)
    subprocess.Popen(["bash", str(script)])


def start_update(download_url: str):
    global _progress
    _progress = {"status": "downloading", "progress": 0, "message": ""}
    t = threading.Thread(target=_do_update, args=(download_url,), daemon=True)
    t.start()


def get_progress() -> dict:
    return _progress
