"""跨平台文件操作工具，给 web 和 desktop 入口共用。"""

import platform
import subprocess
from pathlib import Path


def reveal_in_file_manager(path: str) -> None:
    """打开系统文件管理器并高亮选中文件。失败抛异常。"""
    p = Path(path).resolve()
    if not p.exists():
        raise FileNotFoundError(str(p))
    system = platform.system()
    if system == "Windows":
        subprocess.Popen(["explorer", "/select,", str(p)])
    elif system == "Darwin":
        subprocess.Popen(["open", "-R", str(p)])
    else:
        # Linux 无统一标准，打开父目录
        subprocess.Popen(["xdg-open", str(p.parent)])
