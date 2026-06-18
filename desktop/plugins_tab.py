"""插件管理 tab：列出插件、添加 GitHub 源、安装/启停/删除。"""

import threading

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from modules import plugins


_STATUS_META = {
    "not_installed": ("未安装", "#6b7280"),
    "installed":     ("已停止", "#9ca3af"),
    "installing":    ("安装中", "#60a5fa"),
    "running":       ("运行中", "#6ee7b7"),
    "error":         ("失败",   "#fca5a5"),
}


class PluginCard(QWidget):
    """单条插件卡片。通过 plugin_changed 信号通知父级刷新。"""

    plugin_changed = Signal()

    def __init__(self, plugin: dict, parent=None):
        super().__init__(parent)
        self.plugin_id = plugin["id"]
        self._build()
        self.refresh(plugin)

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        # 主行：name + 版本 + 状态 + 按钮组（一行搞定）
        row = QHBoxLayout()
        row.setSpacing(10)

        self.name_label = QLabel()
        self.name_label.setProperty("role", "title")
        row.addWidget(self.name_label)

        self.version_label = QLabel()
        self.version_label.setProperty("role", "muted")
        row.addWidget(self.version_label)

        self.status_label = QLabel()
        self.status_label.setProperty("role", "badge")
        row.addWidget(self.status_label)

        row.addStretch(1)

        self.start_btn = self._mk_btn("启动", "success", self._on_start)
        self.stop_btn = self._mk_btn("停止", "danger", self._on_stop)
        self.install_btn = self._mk_btn("安装", None, self._on_install)
        self.update_btn = self._mk_btn("更新", "warning", self._on_update)
        self.remove_btn = self._mk_btn("删除", "secondary", self._on_remove)
        for b in (self.start_btn, self.stop_btn, self.install_btn, self.update_btn, self.remove_btn):
            row.addWidget(b)
        layout.addLayout(row)

        # 错误 / 安装进度（仅在相关时显示）
        self.error_label = QLabel()
        self.error_label.setStyleSheet("color:#fca5a5;")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)

        self.progress_label = QLabel()
        self.progress_label.setProperty("role", "hint")
        self.progress_label.setVisible(False)
        layout.addWidget(self.progress_label)

    def _mk_btn(self, text: str, variant: str | None, slot) -> QPushButton:
        btn = QPushButton(text)
        btn.setCursor(Qt.PointingHandCursor)
        if variant:
            btn.setProperty("variant", variant)
        btn.clicked.connect(slot)
        return btn

    def refresh(self, p: dict):
        self.name_label.setText(p.get("name") or p["id"])

        status = p.get("status", "")
        text, color = _STATUS_META.get(status, ("", "#9ca3af"))
        self.status_label.setText(text)
        self.status_label.setStyleSheet(
            f"background:#1f2937;color:{color};border:1px solid #374151;padding:1px 8px;"
            f"border-radius:3px;font-size:11px;"
        )

        installed = p.get("installed_version") or ""
        latest = p.get("latest_version") or ""
        has_update = bool(installed) and latest and installed != latest
        if not installed:
            version_text = "未安装"
        elif has_update:
            version_text = f"{installed} → {latest}"
        else:
            version_text = installed
        self.version_label.setText(version_text)
        self.version_label.setStyleSheet("color:#fbbf24;" if has_update else "color:#9ca3af;")

        err = p.get("last_error") or ""
        self.error_label.setText(err)
        self.error_label.setVisible(bool(err) and status == "error")

        installing = status == "installing"
        prog = p.get("install_progress") or {}
        if installing and prog:
            self.progress_label.setText(f"{prog.get('message', '')}  {prog.get('progress', 0)}%")
        else:
            self.progress_label.setText("")
        self.progress_label.setVisible(installing)

        running = status == "running"
        not_installed = status == "not_installed"
        self.start_btn.setEnabled(not installing and not running and not not_installed)
        self.stop_btn.setEnabled(running)
        self.install_btn.setEnabled(not installing and not_installed)
        self.update_btn.setEnabled(not installing and bool(has_update))
        self.remove_btn.setEnabled(not installing)

    def _on_start(self):
        try:
            plugins.start(self.plugin_id)
        except Exception as e:
            QMessageBox.warning(self, "启动失败", str(e))
        self.plugin_changed.emit()

    def _on_stop(self):
        plugins.stop(self.plugin_id)
        self.plugin_changed.emit()

    def _on_install(self):
        try:
            plugins.install(self.plugin_id)
        except Exception as e:
            QMessageBox.warning(self, "安装失败", str(e))
        self.plugin_changed.emit()

    def _on_update(self):
        try:
            plugins.update(self.plugin_id)
        except Exception as e:
            QMessageBox.warning(self, "更新失败", str(e))
        self.plugin_changed.emit()

    def _on_remove(self):
        if QMessageBox.question(self, "确认", "删除该插件？会停止进程并清理本地文件。") != QMessageBox.Yes:
            return
        try:
            plugins.remove(self.plugin_id)
        except Exception as e:
            QMessageBox.warning(self, "删除失败", str(e))
        self.plugin_changed.emit()


class PluginsTab(QWidget):
    # 后台 check_updates 完成后，靠这个 signal 回到 Qt 主线程刷新
    _update_checked = Signal()

    def __init__(self):
        super().__init__()
        self._cards: dict[str, PluginCard] = {}
        self._checking_updates = False
        self._build()
        self._reload()

        self._update_checked.connect(self._reload)
        # 首次加载异步触发更新检查（后端 10 分钟缓存）
        self._kick_check_updates()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._poll)
        self.timer.start(1000)

    def _kick_check_updates(self):
        if self._checking_updates:
            return
        self._checking_updates = True

        def bg():
            try:
                plugins.check_updates()
            except Exception:
                pass
            finally:
                self._checking_updates = False
                self._update_checked.emit()

        threading.Thread(target=bg, daemon=True).start()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # 错误条
        self.error_label = QLabel()
        self.error_label.setStyleSheet("color:#fca5a5;background:#7f1d1d;padding:8px;border-radius:4px;")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)

        # 列表
        section = QLabel("插件列表")
        section.setProperty("role", "section-title")
        layout.addWidget(section)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        inner = QWidget()
        self.list_layout = QVBoxLayout(inner)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(8)
        self.list_layout.addStretch(1)
        self.scroll.setWidget(inner)
        layout.addWidget(self.scroll, 1)

    def _reload(self):
        items = plugins.list_plugins()
        # 清空旧卡片（保留 stretch）
        while self.list_layout.count() > 1:
            item = self.list_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._cards.clear()
        for p in items:
            card = PluginCard(p)
            card.plugin_changed.connect(self._reload)
            self.list_layout.insertWidget(self.list_layout.count() - 1, card)
            self._cards[p["id"]] = card

    def _poll(self):
        # 仅在存在安装中/运行中的插件时刷新
        items = plugins.list_plugins()
        need_refresh = False
        for p in items:
            if p["status"] == "installing":
                need_refresh = True
                break
        if need_refresh:
            self._reload()
