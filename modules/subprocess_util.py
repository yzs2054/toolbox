"""跨平台 subprocess helper：Windows 上隐藏子进程控制台窗口。"""
import subprocess

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
