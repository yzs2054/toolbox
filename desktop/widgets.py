"""Desktop 通用控件：任务卡、视频源卡、dropzone。"""

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from modules.file_ops import reveal_in_file_manager

CODEC_LABEL = {"h264": "H.264", "h265": "H.265", "vp9": "VP9"}
RES_LABEL = {"source": "原分辨率", "1080": "1080p", "720": "720p", "480": "480p"}
QUALITY_LABEL = {"high": "高质", "balanced": "平衡", "compressed": "压缩"}


def _format_time(unix_sec: float) -> str:
    if not unix_sec:
        return ""
    import time
    t = time.localtime(unix_sec)
    return time.strftime("%m-%d %H:%M", t)


class TaskCard(QFrame):
    """任务进度卡片。task dict 字段参考 modules/video_dl.py / audio_extract.py / video_transcode.py。"""

    reveal_requested = Signal(str, str)  # (kind, task_id)

    def __init__(self, task: dict, kind: str, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.task_id = task.get("id", "")
        self.setProperty("card", True)
        self._build(task)
        self.refresh(task)

    def _build(self, task: dict):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        # 第一行：标题 + 状态徽章
        top = QHBoxLayout()
        top.setSpacing(8)
        self.title_label = QLabel()
        self.title_label.setProperty("role", "title")
        self.title_label.setWordWrap(True)
        top.addWidget(self.title_label, 1)

        self.badge_label = QLabel()
        self.badge_label.setProperty("role", "badge")
        top.addWidget(self.badge_label, 0, Qt.AlignRight)
        layout.addLayout(top)

        # 第二行：源/输出文件名
        self.subtitle_label = QLabel()
        self.subtitle_label.setProperty("role", "muted")
        self.subtitle_label.setWordWrap(True)
        layout.addWidget(self.subtitle_label)

        # 进度条
        self.progress = QProgressBar()
        self.progress.setFixedHeight(8)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)

        # 底部：消息 + 打开目录按钮
        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        self.msg_label = QLabel()
        self.msg_label.setProperty("role", "hint")
        bottom.addWidget(self.msg_label, 1)
        self.reveal_btn = QPushButton("打开所在目录")
        self.reveal_btn.setProperty("variant", "secondary")
        self.reveal_btn.setCursor(Qt.PointingHandCursor)
        self.reveal_btn.clicked.connect(self._on_reveal)
        self.reveal_btn.setVisible(False)
        bottom.addWidget(self.reveal_btn, 0, Qt.AlignRight)
        layout.addLayout(bottom)

    def refresh(self, task: dict):
        self.task_id = task.get("id", "")
        source = task.get("source_name") or (task.get("video") or {}).get("title") or "未命名"
        self.title_label.setText(source)

        status = task.get("status", "")
        progress = task.get("progress", 0) or 0
        # 状态徽章
        if status == "done":
            self.badge_label.setText("完成")
            self.badge_label.setStyleSheet(
                "background:#064e3b;color:#6ee7b7;border:1px solid #047857;"
            )
        elif status == "error":
            self.badge_label.setText("失败")
            self.badge_label.setStyleSheet(
                "background:#7f1d1d;color:#fca5a5;border:1px solid #991b1b;"
            )
        else:
            self.badge_label.setText("进行中")
            self.badge_label.setStyleSheet(
                "background:#1e3a8a;color:#93c5fd;border:1px solid #1e40af;"
            )

        # 副标题：根据 kind 组装
        subtitle_parts = []
        if self.kind == "video":
            v = task.get("video") or {}
            q = v.get("quality") or ""
            if q:
                subtitle_parts.append(q)
        elif self.kind == "video_transcode":
            codec = CODEC_LABEL.get(task.get("codec", ""), task.get("codec", ""))
            res = RES_LABEL.get(str(task.get("resolution", "")), task.get("resolution", ""))
            q = QUALITY_LABEL.get(task.get("quality", ""), task.get("quality_label", ""))
            subtitle_parts = [x for x in [codec, res, q] if x]
        out = task.get("output_file", "")
        if out:
            subtitle_parts.append(f"→ {out}")
        self.subtitle_label.setText("  ·  ".join(subtitle_parts) if subtitle_parts else "")

        # 进度
        if status == "done":
            self.progress.setValue(100)
        elif status == "error":
            self.progress.setValue(progress)
        else:
            self.progress.setValue(int(progress))

        # 消息 + 完成时显示「打开所在目录」
        msg = task.get("message", "")
        if status == "downloading":
            msg = f"{progress}%"
        self.msg_label.setText(msg)
        self.reveal_btn.setVisible(status == "done" and bool(out))

    def _on_reveal(self):
        self.reveal_requested.emit(self.kind, self.task_id)


class VideoCard(QFrame):
    """视频源卡片（提取出来后展示），点「下载」触发信号。"""

    download_requested = Signal(dict)

    def __init__(self, video: dict, parent=None):
        super().__init__(parent)
        self.video = video
        self.setProperty("card", True)
        self._build()

    def _build(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)

        info = QVBoxLayout()
        info.setSpacing(4)
        title = QLabel(self.video.get("title") or "未命名")
        title.setProperty("role", "title")
        title.setWordWrap(True)
        info.addWidget(title)

        url_text = self.video.get("url", "")
        url = QLabel(url_text)
        url.setProperty("role", "hint")
        url.setWordWrap(True)
        url.setTextInteractionFlags(Qt.TextSelectableByMouse)
        url.setToolTip(url_text)
        info.addWidget(url)
        layout.addLayout(info, 1)

        quality = self.video.get("quality")
        if quality:
            badge = QLabel(quality)
            badge.setProperty("role", "badge")
            layout.addWidget(badge, 0, Qt.AlignTop)

        btn = QPushButton("下载")
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(lambda: self.download_requested.emit(self.video))
        layout.addWidget(btn, 0, Qt.AlignTop)


class Dropzone(QFrame):
    """可拖入文件的 QFrame。file_dropped 信号带文件路径 (str)。"""

    file_dropped = Signal(str)

    def __init__(self, hint: str = "点击选择 或 拖拽视频文件到这里", accept_video=True, parent=None):
        super().__init__(parent)
        self.setProperty("dropzone", True)
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self._hint = hint
        self._accept_video = accept_video

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        self.hint_label = QLabel(hint)
        self.hint_label.setAlignment(Qt.AlignCenter)
        self.hint_label.setProperty("role", "muted")
        layout.addWidget(self.hint_label)

        self.clicked = False

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._open_file_dialog()
        super().mousePressEvent(e)

    def _open_file_dialog(self):
        filt = "视频文件 (*.mp4 *.mkv *.mov *.avi *.webm *.ts *.flv);;所有文件 (*)" if self._accept_video else "所有文件 (*)"
        path, _ = QFileDialog.getOpenFileName(self, "选择文件", "", filt)
        if path:
            self.file_dropped.emit(path)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            self.setProperty("drag-active", True)
            self.style().unpolish(self)
            self.style().polish(self)
            e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self.setProperty("drag-active", False)
        self.style().unpolish(self)
        self.style().polish(self)
        super().dragLeaveEvent(e)

    def dropEvent(self, e):
        self.setProperty("drag-active", False)
        self.style().unpolish(self)
        self.style().polish(self)
        urls = e.mimeData().urls()
        if urls:
            local = urls[0].toLocalFile()
            if local:
                self.file_dropped.emit(local)
        e.acceptProposedAction()

    def set_filename(self, name: str | None):
        """外部更新提示文案（比如选完文件后显示文件名）。"""
        self.hint_label.setText(name if name else self._hint)
