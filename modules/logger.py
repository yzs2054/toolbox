"""跨模块日志：写文件 + console。

Desktop --noconsole 打包模式下 stdout/stderr 无效但不报错，
排查问题主要靠文件：data/logs/toolbox.log（相对工作目录，跟 exe 同级）。

入口（app.py / main.py）调一次 setup_logging() 即可。
其他模块 `from .logger import get_logger; log = get_logger(__name__)`。
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_DIR = Path("data/logs")
_LOG_FILE = _LOG_DIR / "toolbox.log"
_initialized = False


def setup_logging(level: int = logging.INFO) -> None:
    """在入口调一次。重复调用幂等。"""
    global _initialized
    if _initialized:
        return
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        # 连 data/logs 都建不了（极端情况，比如只读介质）——退化到 stderr，
        # 至少开发模式下能看到
        pass

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_h: logging.Handler | None = None
    try:
        file_h = RotatingFileHandler(
            _LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=3,
            encoding="utf-8",
        )
        file_h.setFormatter(fmt)
    except Exception:
        file_h = None

    stream_h = logging.StreamHandler(sys.stderr)
    stream_h.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(level)
    if file_h:
        root.addHandler(file_h)
    root.addHandler(stream_h)

    _initialized = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
