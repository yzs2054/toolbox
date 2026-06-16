"""微信视频号解析与下载模块。"""

import json
import re
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

DOWNLOAD_DIR = Path("data/downloads")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Yuanbao cookie 存储
COOKIE_FILE = Path("channels_cookie.txt")

# 全局任务存储
_tasks: dict[str, dict] = {}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
}


def get_cookie() -> str:
    if COOKIE_FILE.exists():
        return COOKIE_FILE.read_text(encoding="utf-8").strip()
    return ""


def set_cookie(cookie: str):
    COOKIE_FILE.write_text(cookie.strip(), encoding="utf-8")


def _parse_sph_url(share_url: str, cookie: str) -> dict:
    """Step 1: 调用 Yuanbao API 解析分享链接，获取 exportId 和 token。"""
    resp = requests.post(
        "https://yuanbao.tencent.com/api/weixin/get_parse_result",
        json={"type": "video_channel_url", "url": share_url, "scene": 1},
        headers={
            **_HEADERS,
            "Content-Type": "application/json",
            "Origin": "https://yuanbao.tencent.com",
            "Referer": "https://yuanbao.tencent.com/",
            "Cookie": cookie,
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise ValueError(data.get("msg") or "Yuanbao API 返回错误，Cookie 可能已过期")
    return data["data"]


def _get_feed_info(export_id: str, general_token: str) -> dict:
    """Step 2: 调用视频号公开 API 获取视频地址。"""
    ts_hex = format(int(time.time()), "x")
    rid_chars = [re.sub(r'[0-9a-f]', lambda m: m.group(), c) for c in uuid.uuid4().hex[:8]]
    rid = f"{ts_hex}-" + uuid.uuid4().hex[:8]

    resp = requests.post(
        f"https://channels.weixin.qq.com/finder-preview/api/feed/get_feed_info"
        f"?_rid={rid}"
        f"&_pageUrl=https://%2F%2Fchannels.weixin.qq.com%2Ffinder-preview%2Fpages%2Ffeed",
        json={"baseReq": {"generalToken": general_token}, "exportId": export_id},
        headers={
            **_HEADERS,
            "Content-Type": "application/json",
            "Origin": "https://channels.weixin.qq.com",
            "Referer": "https://channels.weixin.qq.com/finder-preview/pages/feed",
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("errCode") != 0:
        raise ValueError(data.get("errMsg") or "视频号 API 返回错误")
    return data["data"]


def parse_share_link(share_url: str) -> dict:
    """解析视频号分享链接，返回视频信息。"""
    cookie = get_cookie()
    if not cookie:
        raise ValueError("未设置 Cookie，请先在设置中填入腾讯元宝的 Cookie")

    # Step 1: 解析分享链接
    parse_data = _parse_sph_url(share_url, cookie)
    playable_url = parse_data.get("playable_url", "")
    export_id = parse_data.get("wx_export_id", "")

    # 从 playable_url 提取 token 和 eid
    if playable_url:
        qs = parse_qs(urlparse(playable_url).query)
        general_token = qs.get("token", [None])[0] or ""
        eid = qs.get("eid", [None])[0] or export_id
    else:
        general_token = ""
        eid = export_id

    if not general_token or not eid:
        raise ValueError("无法从分享链接中提取 token，请检查链接是否有效")

    # Step 2: 获取视频详情
    feed_data = _get_feed_info(eid, general_token)
    feed_info = feed_data.get("feedInfo", {})
    author_info = feed_data.get("authorInfo", {})

    # 优先 h264，其次 h265，最后兜底
    video_url = ""
    h264 = feed_info.get("h264VideoInfo", {})
    h265 = feed_info.get("h265VideoInfo", {})
    if h264 and h264.get("videoUrl"):
        video_url = h264["videoUrl"]
    elif h265 and h265.get("videoUrl"):
        video_url = h265["videoUrl"]
    elif feed_info.get("videoUrl"):
        video_url = feed_info["videoUrl"]

    if not video_url:
        raise ValueError("未找到视频下载地址")

    return {
        "title": feed_info.get("description", "视频号视频")[:80],
        "author": author_info.get("nickname", ""),
        "author_icon": author_info.get("headImgUrl", ""),
        "cover_url": feed_info.get("coverUrl", ""),
        "video_url": video_url,
        "description": feed_info.get("description", ""),
        "like_count": feed_info.get("likeCountFmt", ""),
        "share_url": share_url,
    }


def _sanitize(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', '_', name).strip()[:80]


def _download_worker(task_id: str, video_url: str, title: str):
    task = _tasks[task_id]
    try:
        filepath = DOWNLOAD_DIR / f"{_sanitize(title)}.mp4"
        resp = requests.get(video_url, headers=_HEADERS, stream=True, timeout=300)
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", 0))
        done = 0
        with open(filepath, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
                done += len(chunk)
                if total:
                    _tasks[task_id]["progress"] = round(done / total * 100)
        task["status"] = "done"
        task["message"] = f"已保存到 {filepath.name}"
        task["progress"] = 100
    except Exception as e:
        task["status"] = "error"
        task["message"] = str(e)[:200]


def start_download(video_url: str, title: str) -> str:
    task_id = uuid.uuid4().hex[:12]
    _tasks[task_id] = {
        "id": task_id,
        "status": "downloading",
        "progress": 0,
        "message": "",
        "video": {"url": video_url, "title": title},
    }
    t = threading.Thread(target=_download_worker, args=(task_id, video_url, title), daemon=True)
    t.start()
    return task_id


def get_task(task_id: str) -> dict | None:
    return _tasks.get(task_id)


def list_tasks() -> list[dict]:
    return list(_tasks.values())
