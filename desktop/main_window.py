"""主窗口：QMainWindow + QTabWidget 装载功能 tab + 菜单栏。"""

from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QMainWindow, QTabWidget

from desktop.about_dialog import AboutDialog
from desktop.audio_tab import AudioTab
from desktop.icon import make_app_icon
from desktop.plugins_tab import PluginsTab
from desktop.transcode_tab import TranscodeTab
from desktop.video_tab import VideoTab


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
        about_action = help_menu.addAction("关于(&A)...")
        about_action.triggered.connect(self._open_about)

        QShortcut(QKeySequence("Ctrl+Q"), self, activated=self.close)

    def _open_about(self):
        dlg = AboutDialog(self)
        dlg.exec()
