"""多功能工具箱 — Web 入口"""

import os
import sys
import webbrowser
import threading
from pathlib import Path

os.environ["TOOLBOX_VARIANT"] = "web"

# PyInstaller 打包后，捆绑的 ffmpeg.exe / ffprobe.exe 与主程序同目录，
# 但 Windows 双击运行时不会自动把该目录加入 PATH。这里主动注入。
if getattr(sys, "frozen", False):
    _exe_dir = str(Path(sys.executable).parent)
    os.environ["PATH"] = _exe_dir + os.pathsep + os.environ.get("PATH", "")

from flask import Flask, jsonify, render_template, request, send_from_directory

from modules import video_dl
from modules import audio_extract
from modules import video_transcode
from modules import system_info
from modules import updater
from modules.file_ops import reveal_in_file_manager

VERSION = updater.get_current_version()
app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/video/extract", methods=["POST"])
def api_extract():
    data = request.get_json(force=True)
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "请输入 URL"}), 400
    try:
        videos = video_dl.extract_videos(url)
        return jsonify({"videos": videos})
    except Exception as e:
        return jsonify({"error": str(e)[:200]}), 500


@app.route("/api/video/download", methods=["POST"])
def api_download():
    data = request.get_json(force=True)
    video = data.get("video")
    if not video or not video.get("url"):
        return jsonify({"error": "无效的视频信息"}), 400
    task_id = video_dl.start_download(video)
    return jsonify({"task_id": task_id})


@app.route("/api/video/tasks", methods=["GET"])
def api_tasks():
    task_id = request.args.get("id")
    if task_id:
        task = video_dl.get_task(task_id)
        if not task:
            return jsonify({"error": "任务不存在"}), 404
        return jsonify(task)
    return jsonify({"tasks": video_dl.list_tasks()})


@app.route("/downloads/<path:filename>")
def serve_download(filename):
    return send_from_directory(video_dl.DOWNLOAD_DIR, filename, as_attachment=True)


@app.route("/api/audio/upload", methods=["POST"])
def api_audio_upload():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "未收到文件"}), 400
    input_path, source_name = audio_extract.save_upload(f)
    task_id = audio_extract.start_task(input_path, source_name, owns_input=True)
    return jsonify({"task_id": task_id})


@app.route("/api/audio/tasks", methods=["GET"])
def api_audio_tasks():
    task_id = request.args.get("id")
    if task_id:
        task = audio_extract.get_task(task_id)
        if not task:
            return jsonify({"error": "任务不存在"}), 404
        return jsonify(task)
    return jsonify({"tasks": audio_extract.list_tasks()})


@app.route("/downloads/audio/<path:filename>")
def serve_audio(filename):
    return send_from_directory(audio_extract.AUDIO_DIR, filename, as_attachment=True)


@app.route("/api/video_transcode/upload", methods=["POST"])
def api_video_transcode_upload():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "未收到文件"}), 400
    codec = (request.form.get("codec") or "h264").strip()
    quality = (request.form.get("quality") or "balanced").strip()
    resolution = (request.form.get("resolution") or "source").strip()
    input_path, source_name = video_transcode.save_upload(f)
    task_id = video_transcode.start_task(input_path, source_name, codec, quality, resolution, owns_input=True)
    return jsonify({"task_id": task_id})


@app.route("/api/video_transcode/tasks", methods=["GET"])
def api_video_transcode_tasks():
    task_id = request.args.get("id")
    if task_id:
        task = video_transcode.get_task(task_id)
        if not task:
            return jsonify({"error": "任务不存在"}), 404
        return jsonify(task)
    return jsonify({"tasks": video_transcode.list_tasks()})


@app.route("/downloads/video_transcode/<path:filename>")
def serve_video_transcode(filename):
    return send_from_directory(video_transcode.TRANSCODE_DIR, filename, as_attachment=True)


@app.route("/api/file/reveal", methods=["POST"])
def api_file_reveal():
    data = request.get_json(force=True)
    kind = data.get("kind")
    task_id = data.get("id")
    if kind not in ("video", "audio", "video_transcode") or not task_id:
        return jsonify({"error": "参数缺失"}), 400

    if kind == "video":
        task = video_dl.get_task(task_id)
        base_dir = video_dl.DOWNLOAD_DIR
    elif kind == "audio":
        task = audio_extract.get_task(task_id)
        base_dir = audio_extract.AUDIO_DIR
    else:
        task = video_transcode.get_task(task_id)
        base_dir = video_transcode.TRANSCODE_DIR

    if not task or not task.get("output_file"):
        return jsonify({"error": "任务或文件不存在"}), 404

    target = (base_dir / task["output_file"]).resolve()
    try:
        target.relative_to(base_dir.resolve())
    except ValueError:
        return jsonify({"error": "非法路径"}), 400

    if not target.exists():
        return jsonify({"error": "文件已被移动或删除"}), 404

    try:
        reveal_in_file_manager(str(target))
    except Exception as e:
        return jsonify({"error": str(e)[:200]}), 500
    return jsonify({"ok": True})


@app.route("/api/update/check", methods=["GET"])
def api_check_update():
    return jsonify(updater.check_update())


@app.route("/api/system/info", methods=["GET"])
def api_system_info():
    return jsonify(system_info.collect())


@app.route("/api/update/start", methods=["POST"])
def api_start_update():
    data = request.get_json(force=True)
    url = data.get("download_url", "")
    if not url:
        return jsonify({"error": "缺少下载地址"}), 400
    updater.start_update(url)
    return jsonify({"ok": True})


@app.route("/api/update/progress", methods=["GET"])
def api_update_progress():
    return jsonify(updater.get_progress())


def _open_browser(port: int):
    import time
    time.sleep(0.8)
    webbrowser.open(f"http://localhost:8080")


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8080))
    threading.Thread(target=_open_browser, args=(port,), daemon=True).start()
    print(f"工具箱已启动: http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
