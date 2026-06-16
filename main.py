"""多功能工具箱 — Desktop 入口（PySide6，不启动 Flask）"""

import os
import sys
from pathlib import Path


def resource_path(rel: str) -> Path:
    """PyInstaller frozen 模式下从 sys._MEIPASS 读资源，否则从仓库根。"""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    return base / rel


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
