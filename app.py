"""多功能工具箱 — Web 入口"""

import webbrowser
import threading

from flask import Flask, jsonify, render_template, request, send_from_directory

from modules import video_dl
from modules import updater

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


@app.route("/api/update/check", methods=["GET"])
def api_check_update():
    return jsonify(updater.check_update())


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
