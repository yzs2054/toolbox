"""多功能工具箱 — Desktop 入口（PySide6，不启动 Flask）"""

import os
import sys
from pathlib import Path

os.environ["TOOLBOX_VARIANT"] = "desktop"


def resource_path(rel: str) -> Path:
    """PyInstaller → sys._MEIPASS；开发态 → main.py 所在目录。"""
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / rel
    return Path(__file__).parent / rel


if __name__ == "__main__":
    if getattr(sys, "frozen", False):
        _exe_dir = str(Path(sys.executable).parent)
        os.environ["PATH"] = _exe_dir + os.pathsep + os.environ.get("PATH", "")

    from PySide6.QtWidgets import QApplication
    from desktop.icon import make_app_icon
    from desktop.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("多功能工具箱")
    icon = make_app_icon()
    app.setWindowIcon(icon)
    try:
        qss_path = resource_path("desktop/style.qss")
        app.setStyleSheet(qss_path.read_text(encoding="utf-8"))
    except Exception:
        pass

    win = MainWindow()
    win.show()
    sys.exit(app.exec())
