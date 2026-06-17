"""视频提取与下载模块，供 Flask 调用。"""

import json
import re
import threading
import time
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

_DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

DOWNLOAD_DIR = Path("data/downloads")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

_HISTORY_FILE = DOWNLOAD_DIR / "history.json"
_HISTORY_MAX = 200

# 全局任务存储
_tasks: dict[str, dict] = {}
_tasks_lock = threading.Lock()


def _load_history() -> None:
    if not _HISTORY_FILE.exists():
        return
    try:
        data = json.loads(_HISTORY_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            for t in data:
                if isinstance(t, dict) and t.get("id"):
                    _tasks[t["id"]] = t
    except Exception:
        pass


def _save_history_locked() -> None:
    items = sorted(_tasks.values(), key=lambda t: t.get("started_at", 0), reverse=True)[:_HISTORY_MAX]
    tmp = _HISTORY_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    tmp.replace(_HISTORY_FILE)


def _persist() -> None:
    with _tasks_lock:
        _save_history_locked()


_load_history()


def fetch_html(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


def _fetch(url: str, headers: dict) -> str:
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.text


def _extract_baidu_haokan(url: str) -> list[dict]:
    """百度新闻视频落地页 → 走好看视频 JSON API 拿多路清晰度直链。

    mbd.baidu.com/newspage/data/videolanding 反爬极重（IP 层验证码）。
    同一个 nid 在 haokan.baidu.com 是公开页，且 ?_format=json 直接返回 JSON，
    路径 data.apiData.curVideoMeta.clarityUrl[] 含多路清晰度 mp4 直链。
    """
    parsed = urlparse(url)
    nid = parse_qs(parsed.query).get("nid", [None])[0]
    if not nid:
        return []

    try:
        resp = requests.get(
            f"https://haokan.baidu.com/v?vid={nid}&_format=json",
            headers={"User-Agent": _DESKTOP_UA},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []

    meta = (data.get("data") or {}).get("apiData", {}).get("curVideoMeta") or {}
    main_title = meta.get("title") or "baidu_video"

    videos: list[dict] = []
    seen: set[str] = set()
    for c in meta.get("clarityUrl", []) or []:
        video_url = c.get("url") or ""
        if not video_url or video_url in seen:
            continue
        seen.add(video_url)
        quality = c.get("title") or c.get("key") or "?"
        videos.append({
            "type": "direct",
            "url": video_url,
            "title": f"{main_title} ({quality})",
        })
    return videos


def extract_videos(url: str) -> list[dict]:
    if "mbd.baidu.com/newspage/data/videolanding" in url:
        videos = _extract_baidu_haokan(url)
        if videos:
            return videos

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
                fn = d.get("filename") or ""
                if fn:
                    _tasks[task_id]["output_file"] = Path(fn).name

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
        _tasks[task_id]["output_file"] = filepath.name
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
    finally:
        task["finished_at"] = time.time()
        _persist()


def start_download(video: dict) -> str:
    task_id = uuid.uuid4().hex[:12]
    with _tasks_lock:
        _tasks[task_id] = {
            "id": task_id,
            "status": "downloading",
            "progress": 0,
            "message": "",
            "video": video,
            "started_at": time.time(),
            "finished_at": None,
            "output_file": "",
        }
    t = threading.Thread(target=_worker, args=(task_id, video), daemon=True)
    t.start()
    return task_id


def get_task(task_id: str) -> dict | None:
    return _tasks.get(task_id)


def list_tasks() -> list[dict]:
    with _tasks_lock:
        items = list(_tasks.values())
    items.sort(key=lambda t: t.get("started_at") or 0, reverse=True)
    return items
