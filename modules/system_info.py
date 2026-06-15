"""系统信息收集模块，供 Flask 调用。"""

import platform
import shutil
import subprocess
import sys
from pathlib import Path

import yt_dlp

from . import video_dl
from . import audio_extract
from . import video_transcode
from . import updater


def _ffmpeg_version() -> str:
    try:
        out = subprocess.check_output(
            ["ffmpeg", "-version"], stderr=subprocess.STDOUT, timeout=5
        ).decode(errors="ignore")
        first = out.splitlines()[0] if out else ""
        # "ffmpeg version 5.1.7-0+deb12u1 Copyright ..."
        parts = first.split()
        if len(parts) >= 3 and parts[0] == "ffmpeg" and parts[1] == "version":
            return parts[2]
        return first[:60]
    except Exception as e:
        return f"(不可用: {e.__class__.__name__})"


def _dir_stats(path: Path) -> dict:
    """递归统计目录下文件总大小与数量。"""
    total = 0
    count = 0
    if path.exists():
        for p in path.rglob("*"):
            if p.is_file():
                try:
                    total += p.stat().st_size
                    count += 1
                except OSError:
                    pass
    return {"size_bytes": total, "file_count": count}


def _human_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    for unit in ("KB", "MB", "GB", "TB"):
        n /= 1024
        if n < 1024:
            return f"{n:.1f} {unit}"
    return f"{n:.1f} PB"


def collect() -> dict:
    os_info = {
        "system": platform.system() or "Unknown",
        "release": platform.release() or "",
        "version": platform.version() or "",
        "machine": platform.machine() or "",
        "processor": platform.processor() or platform.machine() or "",
        "python": platform.python_version(),
        "cpu_count": os_cpu_count(),
    }

    ffmpeg_ver = _ffmpeg_version()

    downloads_stat = _dir_stats(video_dl.DOWNLOAD_DIR)
    audio_stat = _dir_stats(audio_extract.AUDIO_DIR)
    transcode_stat = _dir_stats(video_transcode.TRANSCODE_DIR)
    try:
        du = shutil.disk_usage(video_dl.DOWNLOAD_DIR.resolve())
        disk = {"free_bytes": du.free, "total_bytes": du.total}
    except Exception:
        disk = {"free_bytes": 0, "total_bytes": 0}

    return {
        "app_version": updater.get_current_version(),
        "os": os_info,
        "tools": {
            "ffmpeg": ffmpeg_ver,
            "yt_dlp": yt_dlp.version.__version__,
        },
        "storage": {
            "downloads": {**downloads_stat, "size_human": _human_bytes(downloads_stat["size_bytes"])},
            "audio": {**audio_stat, "size_human": _human_bytes(audio_stat["size_bytes"])},
            "transcode": {**transcode_stat, "size_human": _human_bytes(transcode_stat["size_bytes"])},
            "disk_free_human": _human_bytes(disk["free_bytes"]),
            "disk_total_human": _human_bytes(disk["total_bytes"]),
            "disk_free_bytes": disk["free_bytes"],
            "disk_total_bytes": disk["total_bytes"],
        },
        "features": [
            {
                "name": "视频下载",
                "tab": "video",
                "desc": "微信公众号（腾讯视频）、百度新闻视频、mpvideo 直链、HTML5 video、mp4/m3u8 直链",
            },
            {
                "name": "音频提取",
                "tab": "audio",
                "desc": "上传视频文件，转 192 kbps MP3",
            },
            {
                "name": "视频转码",
                "tab": "transcode",
                "desc": "H.264 / H.265 / VP9，可选分辨率与质量档位",
            },
        ],
    }


def os_cpu_count() -> int:
    import os
    return os.cpu_count() or 0
