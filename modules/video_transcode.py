"""视频转码模块，供 Flask 调用。"""

import json
import re
import subprocess
import threading
import time
import uuid
from pathlib import Path

DOWNLOAD_DIR = Path("downloads")
TRANSCODE_DIR = DOWNLOAD_DIR / "video_transcode"
UPLOAD_TMP_DIR = DOWNLOAD_DIR / "_uploads"
TRANSCODE_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_TMP_DIR.mkdir(parents=True, exist_ok=True)

_HISTORY_FILE = TRANSCODE_DIR / "history.json"
_HISTORY_MAX = 200

# 编码 → (ffmpeg 视频编码器, 输出扩展名, 音频编码器)
CODECS = {
    "h264": ("libx264", ".mp4", "aac"),
    "h265": ("libx265", ".mp4", "aac"),
    "vp9":  ("libvpx-vp9", ".webm", "libopus"),
}

QUALITY_CRF = {"high": 18, "balanced": 23, "compressed": 28}
QUALITY_LABEL = {"high": "高质", "balanced": "平衡", "compressed": "压缩"}

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
    original = file_storage.filename or "video"
    ext = Path(original).suffix or ".mp4"
    saved = UPLOAD_TMP_DIR / f"{uuid.uuid4().hex}{ext}"
    file_storage.save(str(saved))
    return str(saved), original


def _probe_duration(path: str) -> float:
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


def _build_ffmpeg_cmd(input_path, output_path, codec, crf, scale_height):
    vcodec, _, acodec = CODECS[codec]
    cmd = [
        "ffmpeg", "-nostats", "-progress", "pipe:1", "-nostdin",
        "-i", input_path,
        "-c:v", vcodec,
    ]
    if vcodec == "libvpx-vp9":
        cmd += ["-crf", str(crf), "-b:v", "0"]
    else:
        cmd += ["-crf", str(crf), "-preset", "medium"]
    if scale_height and scale_height > 0:
        cmd += ["-vf", f"scale=-2:{scale_height}"]
    cmd += ["-c:a", acodec, "-b:a", "128k", "-y", output_path]
    return cmd


def _run_ffmpeg(input_path, output_path, codec, crf, scale_height, duration, task_id) -> bool:
    cmd = _build_ffmpeg_cmd(input_path, output_path, codec, crf, scale_height)
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        for line in proc.stdout:
            line = line.strip()
            if line.startswith("out_time_ms=") and duration > 0:
                try:
                    us = int(line.split("=", 1)[1])
                    pct = min(99, round(us / 1_000_000 / duration * 100))
                    _tasks[task_id]["progress"] = pct
                except ValueError:
                    pass
        proc.wait()
        return proc.returncode == 0
    except Exception:
        return False


def _worker(task_id: str, input_path: str, source_name: str, codec: str, quality: str, resolution: str):
    task = _tasks[task_id]
    try:
        if codec not in CODECS:
            raise ValueError(f"未知编码: {codec}")
        _, ext, _ = CODECS[codec]
        crf = QUALITY_CRF.get(quality, 23)
        scale_height = 0 if resolution == "source" else int(resolution)

        stem = _sanitize(Path(source_name).stem)
        output_path = TRANSCODE_DIR / f"{stem}.{codec}{ext}"

        duration = _probe_duration(input_path)
        task["duration_sec"] = round(duration, 1)

        ok = _run_ffmpeg(input_path, str(output_path), codec, crf, scale_height, duration, task_id)
        if ok and output_path.exists() and output_path.stat().st_size > 0:
            task["status"] = "done"
            task["progress"] = 100
            task["output_file"] = output_path.name
            task["message"] = f"已转码到 {output_path.name}"
        else:
            task["status"] = "error"
            task["message"] = "ffmpeg 转码失败"
    except Exception as e:
        task["status"] = "error"
        task["message"] = str(e)[:200]
    finally:
        try:
            Path(input_path).unlink(missing_ok=True)
        except Exception:
            pass
        task["finished_at"] = time.time()
        _persist()


def start_task(file_storage, codec: str, quality: str, resolution: str) -> str:
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
            "codec": codec,
            "quality": quality,
            "quality_label": QUALITY_LABEL.get(quality, quality),
            "resolution": resolution,
            "started_at": time.time(),
            "finished_at": None,
        }
    t = threading.Thread(
        target=_worker,
        args=(task_id, input_path, source_name, codec, quality, resolution),
        daemon=True,
    )
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
