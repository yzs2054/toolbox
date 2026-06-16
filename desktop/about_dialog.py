"""关于对话框：应用信息 / OS / 工具版本 / 存储 + 软件更新。"""

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from modules import system_info, updater


class AboutDialog(QDialog):
    _check_done = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("关于")
        self.resize(620, 600)
        self._update_url: str = ""
        self._build()
        self._load_info()
        self._check_done.connect(self._apply_check_result)

        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self._poll_update)

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)

        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        from desktop.icon import make_app_pixmap
        logo = QLabel()
        logo.setPixmap(make_app_pixmap(48))
        title_row.addWidget(logo, 0, Qt.AlignTop)
        title_text = QLabel("多功能工具箱")
        title_text.setProperty("role", "section-title")
        title_text.setStyleSheet("font-size:18px; font-weight:600;")
        title_row.addWidget(title_text, 1)
        layout.addLayout(title_row)

        top = QHBoxLayout()
        top.setSpacing(8)
        section = QLabel("系统信息")
        section.setProperty("role", "section-title")
        top.addWidget(section)
        top.addStretch(1)
        refresh_btn = QPushButton("刷新")
        refresh_btn.setProperty("variant", "secondary")
        refresh_btn.setCursor(Qt.PointingHandCursor)
        refresh_btn.clicked.connect(self._load_info)
        top.addWidget(refresh_btn)
        layout.addLayout(top)

        self.info_host = QVBoxLayout()
        self.info_host.setSpacing(8)
        layout.addLayout(self.info_host, 1)

        layout.addWidget(self._hr())
        update_title = QLabel("软件更新")
        update_title.setProperty("role", "section-title")
        layout.addWidget(update_title)

        self.update_card = QFrame()
        self.update_card.setProperty("card", True)
        uc = QVBoxLayout(self.update_card)
        uc.setContentsMargins(12, 10, 12, 10)
        uc.setSpacing(6)
        self.update_status_label = QLabel("点击「检查更新」查看最新版本")
        self.update_status_label.setProperty("role", "muted")
        uc.addWidget(self.update_status_label)
        self.update_action_btn = QPushButton("检查更新")
        self.update_action_btn.setProperty("variant", "secondary")
        self.update_action_btn.setCursor(Qt.PointingHandCursor)
        self.update_action_btn.clicked.connect(self._check_update)
        uc.addWidget(self.update_action_btn, alignment=Qt.AlignLeft)

        self.update_progress_area = QWidget()
        upa_layout = QVBoxLayout(self.update_progress_area)
        upa_layout.setContentsMargins(0, 0, 0, 0)
        upa_layout.setSpacing(4)
        self.update_progress = QProgressBar()
        self.update_progress.setFixedHeight(8)
        self.update_progress.setTextVisible(False)
        upa_layout.addWidget(self.update_progress)
        self.update_msg = QLabel()
        self.update_msg.setProperty("role", "hint")
        upa_layout.addWidget(self.update_msg)
        self.update_progress_area.setVisible(False)
        uc.addWidget(self.update_progress_area)
        layout.addWidget(self.update_card)

        layout.addStretch(1)

        close_row = QHBoxLayout()
        close_row.setContentsMargins(16, 8, 16, 12)
        close_row.addStretch(1)
        close_btn = QPushButton("关闭")
        close_btn.setProperty("variant", "secondary")
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.clicked.connect(self.reject)
        close_row.addWidget(close_btn)
        outer.addLayout(close_row)

    @staticmethod
    def _hr() -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background:#374151; max-height:1px;")
        return line

    def _load_info(self):
        while self.info_host.count():
            item = self.info_host.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

        try:
            data = system_info.collect()
        except Exception as e:
            err = QLabel(f"加载失败：{e}")
            err.setStyleSheet("color:#fca5a5;")
            self.info_host.addWidget(err)
            return

        row1 = QHBoxLayout()
        row1.setSpacing(8)
        row1.setContentsMargins(0, 0, 0, 0)
        os_card = self._info_card("操作系统", [
            ("系统", f"{data['os']['system']} {data['os']['release']}"),
            ("架构", data["os"].get("machine") or "-"),
            ("CPU", f"{data['os'].get('processor') or '-'} ({data['os'].get('cpu_count', 0)} 核)"),
            ("Python", data["os"].get("python") or "-"),
        ])
        row1.addWidget(os_card, 1)
        tools_card = self._info_card("工具版本", [
            ("应用版本", data.get("app_version") or "-"),
            ("ffmpeg", data["tools"].get("ffmpeg") or "-"),
            ("yt-dlp", data["tools"].get("yt_dlp") or "-"),
        ])
        row1.addWidget(tools_card, 1)
        self.info_host.addLayout(row1)

        st = data["storage"]
        storage_card = self._info_card("存储", [
            ("下载目录", f"{(st.get('downloads') or {}).get('size_human', '0 B')} / {(st.get('downloads') or {}).get('file_count', 0)} 文件"),
            ("音频目录", f"{(st.get('audio') or {}).get('size_human', '0 B')} / {(st.get('audio') or {}).get('file_count', 0)} 文件"),
            ("转码目录", f"{(st.get('transcode') or {}).get('size_human', '0 B')} / {(st.get('transcode') or {}).get('file_count', 0)} 文件"),
            ("磁盘剩余", f"{st.get('disk_free_human', '-')} / {st.get('disk_total_human', '-')}"),
        ])
        self.info_host.addWidget(storage_card)

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    def _info_card(self, title: str, rows: list[tuple[str, str]]) -> QFrame:
        card = QFrame()
        card.setProperty("card", True)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(12, 10, 12, 10)
        cl.setSpacing(2)
        t = QLabel(title)
        t.setProperty("role", "section-title")
        cl.addWidget(t)
        for label, value in rows:
            row = QHBoxLayout()
            l = QLabel(label)
            l.setProperty("role", "hint")
            row.addWidget(l)
            row.addStretch(1)
            v = QLabel(value)
            v.setStyleSheet("color:#e5e7eb; font-family: monospace;")
            row.addWidget(v)
            cl.addLayout(row)
        return card

    def _check_update(self):
        self.update_action_btn.setEnabled(False)
        self.update_action_btn.setText("检查中...")
        self.update_status_label.setText("正在检查更新...")

        from threading import Thread
        def worker():
            r = updater.check_update()
            self._check_done.emit(r)

        Thread(target=worker, daemon=True).start()

    def _apply_check_result(self, r: dict):
        r = r or {}
        self.update_action_btn.setEnabled(True)
        self.update_action_btn.setText("检查更新")
        if r.get("error"):
            self.update_status_label.setText(f"检查失败：{r['error']}")
            self.update_action_btn.setVisible(True)
            return
        current = r.get("current", "")
        latest = r.get("latest", "")
        if r.get("has_update"):
            self._update_url = r.get("download_url", "")
            self.update_status_label.setText(f"发现新版本：{current} → {latest}")
            self.update_action_btn.setText("立即更新")
            self.update_action_btn.setProperty("variant", "success")
            self.update_action_btn.clicked.disconnect()
            self.update_action_btn.clicked.connect(self._start_update)
        else:
            self.update_status_label.setText(f"当前版本 {current}（已是最新）")
            self.update_action_btn.setText("检查更新")
            self.update_action_btn.setProperty("variant", "secondary")

    def _start_update(self):
        if not self._update_url:
            return
        updater.start_update(self._update_url)
        self.update_action_btn.setEnabled(False)
        self.update_action_btn.setText("更新中...")
        self.update_progress_area.setVisible(True)
        self.update_timer.start(500)

    def _poll_update(self):
        p = updater.get_progress()
        status = p.get("status", "")
        progress = p.get("progress", 0) or 0
        self.update_progress.setValue(int(progress))
        self.update_msg.setText(p.get("message", ""))
        if status in ("ready", "error"):
            self.update_timer.stop()
            self.update_action_btn.setEnabled(True)
            if status == "ready":
                self.update_action_btn.setText("重启后生效")
            else:
                self.update_action_btn.setText("重试")
                self.update_action_btn.setEnabled(True)
