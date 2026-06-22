"""主窗口：QMainWindow + QTabWidget 装载功能 tab + 菜单栏。"""

from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QMainWindow, QMessageBox, QTabWidget

from desktop.about_dialog import AboutDialog
from desktop.audio_tab import AudioTab
from desktop.icon import make_app_icon
from desktop.plugins_tab import PluginsTab
from desktop.transcode_tab import TranscodeTab
from desktop.video_tab import VideoTab
from modules.usage import USAGES


_TAB_IDS = ["video", "audio", "transcode", "plugins"]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("多功能工具箱")
        self.setWindowIcon(make_app_icon())
        self.resize(900, 650)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.video_tab = VideoTab()
        self.audio_tab = AudioTab()
        self.transcode_tab = TranscodeTab()
        self.plugins_tab = PluginsTab()
        self.tabs.addTab(self.video_tab, "视频下载")
        self.tabs.addTab(self.audio_tab, "音频提取")
        self.tabs.addTab(self.transcode_tab, "视频转码")
        self.tabs.addTab(self.plugins_tab, "插件管理")
        self.setCentralWidget(self.tabs)

        file_menu = self.menuBar().addMenu("文件(&F)")
        exit_action = file_menu.addAction("退出(&X)")
        exit_action.triggered.connect(self.close)

        help_menu = self.menuBar().addMenu("帮助(&H)")
        usage_action = help_menu.addAction("使用说明(&U)...")
        usage_action.triggered.connect(self._open_usage)
        about_action = help_menu.addAction("关于(&A)...")
        about_action.triggered.connect(self._open_about)

        QShortcut(QKeySequence("Ctrl+Q"), self, activated=self.close)

    def _open_about(self):
        dlg = AboutDialog(self)
        dlg.exec()

    def _open_usage(self):
        idx = self.tabs.currentIndex()
        if idx < 0 or idx >= len(_TAB_IDS):
            return
        usage = USAGES.get(_TAB_IDS[idx])
        if not usage:
            return
        QMessageBox.information(self, usage[0], usage[1])
