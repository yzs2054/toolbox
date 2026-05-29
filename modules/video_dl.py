"""视频提取与下载模块，供 Flask 调用。"""

import re
import threading
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests
import yt_dlp
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 10; Pixel 4) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/91.0.4472.114 Mobile Safari/537.36"
    ),
}

DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

# 全局任务存储
_tasks: dict[str, dict] = {}


def fetch_html(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


def extract_videos(url: str) -> list[dict]:
    html = fetch_html(url)
    soup = BeautifulSoup(html, "lxml")
    title = soup.title.string.strip() if soup.title and soup.title.string else "video"
    videos = []

    # 1) 腾讯视频 iframe 嵌入
    for iframe in soup.find_all("iframe", src=True):
        src = iframe["src"]
        if "v.qq.com" in src or "txvideo" in src:
            parsed = urlparse(src)
            vid = parse_qs(parsed.query).get("vid", [None])[0]
            if not vid:
                m = re.search(r"/([a-zA-Z0-9]+)(?:\.html)?$", parsed.path)
                vid = m.group(1) if m else None
            if vid:
                videos.append({
                    "type": "qq_video",
                    "url": f"https://v.qq.com/x/page/{vid}.html",
                    "title": title,
                    "vid": vid,
                })

    # 2) 腾讯视频 vid 正则兜底（排除广告上下文）
    _AD_KW = ("gdt_", "weixinad", "traceid", "adkey", "group_id", "uxinfo")
    if not any(v["type"] == "qq_video" for v in videos):
        for m in re.finditer(r'vid[=:]\s*["\']?([a-zA-Z0-9]{8,15})["\']?', html):
            vid = m.group(1)
            ctx = html[max(0, m.start() - 80):m.start()]
            if any(kw in ctx for kw in _AD_KW):
                continue
            if not any(v.get("vid") == vid for v in videos):
                videos.append({
                    "type": "qq_video",
                    "url": f"https://v.qq.com/x/page/{vid}.html",
                    "title": title,
                    "vid": vid,
                })

    # 3) mpvideo 直链
    for m in re.finditer(r'(https?://mpvideo\.qpic\.cn/[^"\'<>\s]+)', html):
        videos.append({"type": "mpvideo", "url": m.group(1), "title": title})

    # 4) HTML5 <video> 标签
    for tag in soup.find_all("video"):
        src = tag.get("src") or ""
        if not src:
            source = tag.find("source", src=True)
            src = source["src"] if source else ""
        if src and not src.startswith("blob:"):
            videos.append({"type": "html5_video", "url": src, "title": title})

    # 5) 直接的 .mp4 / .m3u8 链接
    for m in re.finditer(r'(https?://[^"\'<>\s]+\.(?:mp4|m3u8)(?:\?[^"\'<>\s]*)?)', html):
        videos.append({"type": "direct", "url": m.group(1), "title": title})

    # 去重
    seen = set()
    return [v for v in videos if v["url"] not in seen and not seen.add(v["url"])]


def _sanitize(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', '_', name).strip()[:80]


def _run_ytdlp(url: str, output_dir: str, title: str, task_id: str = "") -> dict:
    outtmpl = str(Path(output_dir) / f"{_sanitize(title)}.%(ext)s")

    def progress_hook(d):
        if task_id and task_id in _tasks:
            if d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                if total:
                    _tasks[task_id]["progress"] = round(d["downloaded_bytes"] / total * 100)
            elif d["status"] == "finished":
                _tasks[task_id]["progress"] = 100

    try:
        with yt_dlp.YoutubeDL({
            "outtmpl": outtmpl,
            "restrictfilenames": True,
            "no_warnings": True,
            "quiet": True,
            "progress_hooks": [progress_hook],
        }) as ydl:
            ydl.download([url])
        return {"ok": True, "msg": "下载完成"}
    except Exception as e:
        return {"ok": False, "msg": str(e)[:300]}


def _run_direct(url: str, output_dir: str, title: str, task_id: str) -> dict:
    ext = ".ts" if ".m3u8" in url else ".mp4"
    filepath = Path(output_dir) / f"{_sanitize(title)}{ext}"
    try:
        resp = requests.get(url, headers=HEADERS, stream=True, timeout=120)
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", 0))
        done = 0
        with open(filepath, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
                done += len(chunk)
                if total:
                    _tasks[task_id]["progress"] = round(done / total * 100)
        return {"ok": True, "msg": f"已保存到 {filepath.name}"}
    except Exception as e:
        return {"ok": False, "msg": str(e)[:200]}


def _worker(task_id: str, video: dict):
    task = _tasks[task_id]
    try:
        if video["type"] == "qq_video":
            r = _run_ytdlp(video["url"], str(DOWNLOAD_DIR), video["title"], task_id)
        else:
            r = _run_direct(video["url"], str(DOWNLOAD_DIR), video["title"], task_id)
            if not r["ok"]:
                r = _run_ytdlp(video["url"], str(DOWNLOAD_DIR), video["title"], task_id)
        task["status"] = "done" if r["ok"] else "error"
        task["message"] = r["msg"]
        task["progress"] = 100 if r["ok"] else task["progress"]
    except Exception as e:
        task["status"] = "error"
        task["message"] = str(e)[:200]


def start_download(video: dict) -> str:
    task_id = uuid.uuid4().hex[:12]
    _tasks[task_id] = {
        "id": task_id,
        "status": "downloading",
        "progress": 0,
        "message": "",
        "video": video,
    }
    t = threading.Thread(target=_worker, args=(task_id, video), daemon=True)
    t.start()
    return task_id


def get_task(task_id: str) -> dict | None:
    return _tasks.get(task_id)


def list_tasks() -> list[dict]:
    return list(_tasks.values())
