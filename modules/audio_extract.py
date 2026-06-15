"""视频转 MP3 模块，供 Flask 调用。"""

import json
import re
import subprocess
import threading
import time
import uuid
from pathlib import Path

DOWNLOAD_DIR = Path("downloads")
AUDIO_DIR = DOWNLOAD_DIR / "audio"
UPLOAD_TMP_DIR = DOWNLOAD_DIR / "_uploads"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_TMP_DIR.mkdir(parents=True, exist_ok=True)

_HISTORY_FILE = AUDIO_DIR / "history.json"
_HISTORY_MAX = 200
_BITRATE = "192k"

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


def _sanitize(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', '_', name).strip()[:120]


def save_upload(file_storage) -> tuple[str, str]:
    """把上传文件落到 _uploads/<uuid>.<ext>，返回 (保存路径, 原始文件名)。"""
    original = file_storage.filename or "video"
    ext = Path(original).suffix or ".mp4"
    saved = UPLOAD_TMP_DIR / f"{uuid.uuid4().hex}{ext}"
    file_storage.save(str(saved))
    return str(saved), original


def _probe_duration(path: str) -> float:
    """ffprobe 拿视频时长（秒），失败返回 0。"""
    try:
        out = subprocess.check_output(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            stderr=subprocess.DEVNULL,
            timeout=30,
        ).decode().strip()
        return float(out) if out else 0.0
    except Exception:
        return 0.0


def _run_ffmpeg(input_path: str, output_path: str, duration: float, task_id: str) -> bool:
    """执行转码；duration>0 时实时更新 progress。返回是否成功。"""
    cmd = [
        "ffmpeg", "-nostats", "-progress", "pipe:1", "-nostdin",
        "-i", input_path,
        "-vn", "-acodec", "libmp3lame", "-b:a", _BITRATE,
        "-y", output_path,
    ]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        for line in proc.stdout:
            line = line.strip()
            if line.startswith("out_time_ms=") and duration > 0:
                try:
                    us = int(line.split("=", 1)[1])
                    pct = min(100, round(us / 1_000_000 / duration * 100))
                    _tasks[task_id]["progress"] = pct
                except ValueError:
                    pass
        proc.wait()
        return proc.returncode == 0
    except Exception:
        return False


def _worker(task_id: str, input_path: str, source_name: str):
    task = _tasks[task_id]
    try:
        base = _sanitize(Path(source_name).stem)
        output_path = AUDIO_DIR / f"{base}.mp3"

        duration = _probe_duration(input_path)
        task["duration_sec"] = round(duration, 1)

        ok = _run_ffmpeg(input_path, str(output_path), duration, task_id)
        if ok and output_path.exists() and output_path.stat().st_size > 0:
            task["status"] = "done"
            task["progress"] = 100
            task["output_file"] = output_path.name
            task["message"] = f"已转换到 {output_path.name}"
        else:
            task["status"] = "error"
            task["message"] = "ffmpeg 转换失败"
    except Exception as e:
        task["status"] = "error"
        task["message"] = str(e)[:200]
    finally:
        # 清理临时上传文件
        try:
            Path(input_path).unlink(missing_ok=True)
        except Exception:
            pass
        task["finished_at"] = time.time()
        _persist()


def start_task(file_storage) -> str:
    task_id = uuid.uuid4().hex[:12]
    input_path, source_name = save_upload(file_storage)
    with _tasks_lock:
        _tasks[task_id] = {
            "id": task_id,
            "status": "downloading",
            "progress": 0,
            "message": "",
            "source_name": source_name,
            "output_file": "",
            "started_at": time.time(),
            "finished_at": None,
        }
    t = threading.Thread(target=_worker, args=(task_id, input_path, source_name), daemon=True)
    t.start()
    return task_id


def get_task(task_id: str) -> dict | None:
    return _tasks.get(task_id)


def list_tasks() -> list[dict]:
    with _tasks_lock:
        items = list(_tasks.values())
    items.sort(key=lambda t: t.get("started_at") or 0, reverse=True)
    return items


_load_history()
