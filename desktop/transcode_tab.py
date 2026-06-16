"""视频转码 tab：选文件 → 选 codec/分辨率/质量 → 转码 → 进度。"""

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from modules import video_transcode
from modules.file_ops import reveal_in_file_manager
from desktop.widgets import Dropzone, TaskCard


class TranscodeTab(QWidget):
    def __init__(self):
        super().__init__()
        self._polling_ids: set[str] = set()
        self._cards: dict[str, TaskCard] = {}
        self._selected_path: str | None = None
        self._build()
        self._load_tasks()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._poll)
        self.timer.start(1000)

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # dropzone
        self.dropzone = Dropzone(hint="点击选择 或 拖拽视频文件到这里")
        self.dropzone.setMinimumHeight(70)
        self.dropzone.file_dropped.connect(self._on_file_picked)
        layout.addWidget(self.dropzone)

        # 三个下拉
        opts = QHBoxLayout()
        opts.setSpacing(10)

        v1 = QVBoxLayout()
        v1.addWidget(self._caption("输出格式"))
        self.codec_box = QComboBox()
        self.codec_box.addItem("MP4 / H.264（兼容最好）", "h264")
        self.codec_box.addItem("MP4 / H.265（体积更小）", "h265")
        self.codec_box.addItem("WebM / VP9", "vp9")
        v1.addWidget(self.codec_box)
        opts.addLayout(v1, 1)

        v2 = QVBoxLayout()
        v2.addWidget(self._caption("分辨率"))
        self.res_box = QComboBox()
        self.res_box.addItem("保持原分辨率", "source")
        self.res_box.addItem("1080p", "1080")
        self.res_box.addItem("720p", "720")
        self.res_box.addItem("480p", "480")
        v2.addWidget(self.res_box)
        opts.addLayout(v2, 1)

        v3 = QVBoxLayout()
        v3.addWidget(self._caption("质量"))
        self.quality_box = QComboBox()
        self.quality_box.addItem("平衡（CRF 23）", "balanced")
        self.quality_box.addItem("高质（CRF 18）", "high")
        self.quality_box.addItem("压缩（CRF 28）", "compressed")
        v3.addWidget(self.quality_box)
        opts.addLayout(v3, 1)

        layout.addLayout(opts)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.convert_btn = QPushButton("开始转码")
        self.convert_btn.setProperty("variant", "success")
        self.convert_btn.setCursor(Qt.PointingHandCursor)
        self.convert_btn.setEnabled(False)
        self.convert_btn.clicked.connect(self._on_convert)
        btn_row.addWidget(self.convert_btn)
        layout.addLayout(btn_row)

        # 错误
        self.error_label = QLabel()
        self.error_label.setStyleSheet("color:#fca5a5;background:#7f1d1d;padding:8px;border-radius:4px;")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)

        # 任务记录
        section = QLabel("转码记录")
        section.setProperty("role", "section-title")
        layout.addWidget(section)
        self.task_area = QScrollArea()
        self.task_area.setWidgetResizable(True)
        inner = QWidget()
        self.task_layout = QVBoxLayout(inner)
        self.task_layout.setContentsMargins(0, 0, 0, 0)
        self.task_layout.setSpacing(8)
        self.task_layout.addStretch(1)
        self.task_area.setWidget(inner)
        layout.addWidget(self.task_area, 1)

    @staticmethod
    def _caption(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setProperty("role", "hint")
        return lbl

    def _on_file_picked(self, path: str):
        self._selected_path = path
        self.dropzone.set_filename(Path(path).name)
        self.convert_btn.setEnabled(True)
        self.error_label.setVisible(False)

    def _on_convert(self):
        if not self._selected_path:
            return
        self.error_label.setVisible(False)
        source_name = Path(self._selected_path).name
        codec = self.codec_box.currentData()
        quality = self.quality_box.currentData()
        resolution = self.res_box.currentData()
        task_id = video_transcode.start_task(
            self._selected_path, source_name,
            codec=codec, quality=quality, resolution=resolution,
            owns_input=False,
        )
        card = TaskCard(video_transcode.get_task(task_id), kind="video_transcode")
        card.reveal_requested.connect(self._on_reveal)
        self.task_layout.insertWidget(0, card)
        self._cards[task_id] = card
        self._polling_ids.add(task_id)
        # 重置选择
        self._selected_path = None
        self.dropzone.set_filename(None)
        self.convert_btn.setEnabled(False)

    def _load_tasks(self):
        for t in video_transcode.list_tasks():
            card = TaskCard(t, kind="video_transcode")
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
            t = video_transcode.get_task(tid)
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
        t = video_transcode.get_task(task_id)
        if not t or not t.get("output_file"):
            return
        target = video_transcode.TRANSCODE_DIR / t["output_file"]
        try:
            reveal_in_file_manager(str(target))
        except Exception as e:
            self.error_label.setText(f"打开失败：{e}")
            self.error_label.setVisible(True)
