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
from pathlib import Path

import requests

# 改成你自己的 GitHub 仓库地址
GITHUB_REPO = "yzs2054/toolbox"
RELEASE_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

_progress = {"status": "idle", "progress": 0, "message": ""}


def get_current_version() -> str:
    version_file = Path(__file__).parent.parent / "version.txt"
    if version_file.exists():
        return version_file.read_text().strip()
    return "v0.0.0"


def check_update() -> dict:
    """检查 GitHub Releases 是否有新版本。"""
    try:
        resp = requests.get(RELEASE_API, timeout=10)
        resp.raise_for_status()
        release = resp.json()
        latest = release["tag_name"]
        current = get_current_version()
        assets = release.get("assets", [])
        download_url = ""
        for a in assets:
            if "windows" in a["name"].lower():
                download_url = a["browser_download_url"]
                break
        return {
            "has_update": latest != current,
            "current": current,
            "latest": latest,
            "notes": release.get("body", "")[:500],
            "download_url": download_url,
        }
    except Exception as e:
        return {"has_update": False, "current": get_current_version(), "error": str(e)[:200]}


def _do_update(download_url: str):
    """后台下载并准备更新。"""
    global _progress
    _progress = {"status": "downloading", "progress": 0, "message": "正在下载更新包..."}

    try:
        resp = requests.get(download_url, stream=True, timeout=120)
        resp.raise_for_status()
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
