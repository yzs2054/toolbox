"""视频下载 tab：粘 URL → 提取 → 选源下载 → 进度。"""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from modules import video_dl
from modules.file_ops import reveal_in_file_manager


class VideoTab(QWidget):
    def __init__(self):
        super().__init__()
        self._polling_ids: set[str] = set()
        self._cards: dict[str, object] = {}  # task_id -> TaskCard
        self._build()
        self._load_tasks()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._poll)
        self.timer.start(1000)

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # URL 输入 + 提取按钮
        top = QHBoxLayout()
        top.setSpacing(8)
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("粘贴网页链接，如微信公众号文章...")
        top.addWidget(self.url_input, 1)
        self.extract_btn = QPushButton("提取视频")
        self.extract_btn.setCursor(Qt.PointingHandCursor)
        self.extract_btn.clicked.connect(self._on_extract)
        top.addWidget(self.extract_btn)
        layout.addLayout(top)

        # 错误提示
        self.error_label = QLabel()
        self.error_label.setStyleSheet("color:#fca5a5;background:#7f1d1d;padding:8px;border-radius:4px;")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)

        # 视频列表区
        self.video_area = QScrollArea()
        self.video_area.setWidgetResizable(True)
        video_inner = QWidget()
        self.video_layout = QVBoxLayout(video_inner)
        self.video_layout.setContentsMargins(0, 0, 0, 0)
        self.video_layout.setSpacing(8)
        self.video_layout.addStretch(1)
        self.video_area.setWidget(video_inner)
        self.video_area.setVisible(False)
        layout.addWidget(self.video_area, 1)

        # 任务记录区
        section = QLabel("下载记录")
        section.setProperty("role", "section-title")
        layout.addWidget(section)
        self.task_area = QScrollArea()
        self.task_area.setWidgetResizable(True)
        task_inner = QWidget()
        self.task_layout = QVBoxLayout(task_inner)
        self.task_layout.setContentsMargins(0, 0, 0, 0)
        self.task_layout.setSpacing(8)
        self.task_layout.addStretch(1)
        self.task_area.setWidget(task_inner)
        layout.addWidget(self.task_area, 1)

    def _on_extract(self):
        url = self.url_input.text().strip()
        if not url:
            return
        self.error_label.setVisible(False)
        self.extract_btn.setEnabled(False)
        self.extract_btn.setText("分析中...")
        QApplication = None
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()

        try:
            videos = video_dl.extract_videos(url)
            self._render_videos(videos)
        except Exception as e:
            self.error_label.setText(f"提取失败：{e}")
            self.error_label.setVisible(True)
        finally:
            self.extract_btn.setEnabled(True)
            self.extract_btn.setText("提取视频")

    def _render_videos(self, videos: list[dict]):
        # 清空旧的
        while self.video_layout.count() > 1:
            item = self.video_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not videos:
            self.error_label.setText("未找到视频源")
            self.error_label.setVisible(True)
            self.video_area.setVisible(False)
            return
        from desktop.widgets import VideoCard
        for v in videos:
            card = VideoCard(v)
            card.download_requested.connect(self._on_download)
            self.video_layout.insertWidget(self.video_layout.count() - 1, card)
        self.video_area.setVisible(True)

    def _on_download(self, video: dict):
        task_id = video_dl.start_download(video)
        from desktop.widgets import TaskCard
        card = TaskCard({"id": task_id, **video_dl.get_task(task_id)}, kind="video")
        card.reveal_requested.connect(self._on_reveal)
        self.task_layout.insertWidget(0, card)
        self._cards[task_id] = card
        self._polling_ids.add(task_id)

    def _load_tasks(self):
        """启动时恢复历史任务。"""
        from desktop.widgets import TaskCard
        for t in video_dl.list_tasks():
            card = TaskCard(t, kind="video")
            card.reveal_requested.connect(self._on_reveal)
            self.task_layout.insertWidget(self.task_layout.count() - 1, card)
            self._cards[t["id"]] = card
            if t.get("status") not in ("done", "error"):
                self._polling_ids.add(t["id"])

    def _poll(self):
        if not self._polling_ids:
            return
        done = set()
        for tid in list(self._polling_ids):
            t = video_dl.get_task(tid)
            if not t:
                done.add(tid)
                continue
            card = self._cards.get(tid)
            if card:
                card.refresh(t)
            if t.get("status") in ("done", "error"):
                done.add(tid)
        self._polling_ids -= done

    def _on_reveal(self, kind: str, task_id: str):
        t = video_dl.get_task(task_id)
        if not t or not t.get("output_file"):
            return
        target = video_dl.DOWNLOAD_DIR / t["output_file"]
        try:
            reveal_in_file_manager(str(target))
        except Exception as e:
            self.error_label.setText(f"打开失败：{e}")
            self.error_label.setVisible(True)
