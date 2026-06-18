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

        # 顶部：name + 平台 badge + 状态 badge
        top = QHBoxLayout()
        top.setSpacing(8)
        self.name_label = QLabel()
        self.name_label.setProperty("role", "title")
        self.name_label.setWordWrap(True)
        top.addWidget(self.name_label, 1)

        self.platform_label = QLabel()
        self.platform_label.setProperty("role", "muted")
        top.addWidget(self.platform_label, 0, Qt.AlignRight)

        self.status_label = QLabel()
        self.status_label.setProperty("role", "badge")
        top.addWidget(self.status_label, 0, Qt.AlignRight)
        layout.addLayout(top)

        # 版本信息
        self.version_label = QLabel()
        self.version_label.setProperty("role", "muted")
        self.version_label.setWordWrap(True)
        layout.addWidget(self.version_label)

        # 来源链接
        self.repo_label = QLabel()
        self.repo_label.setProperty("role", "hint")
        self.repo_label.setOpenExternalLinks(True)
        self.repo_label.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.repo_label.setVisible(False)
        layout.addWidget(self.repo_label)

        # 描述
        self.desc_label = QLabel()
        self.desc_label.setProperty("role", "hint")
        self.desc_label.setWordWrap(True)
        self.desc_label.setVisible(False)
        layout.addWidget(self.desc_label)

        # 错误
        self.error_label = QLabel()
        self.error_label.setStyleSheet("color:#fca5a5;")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)

        # 安装进度
        self.progress_label = QLabel()
        self.progress_label.setProperty("role", "hint")
        self.progress_label.setVisible(False)
        layout.addWidget(self.progress_label)

        # 按钮行
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self.start_btn = self._mk_btn("启动", "success", self._on_start)
        self.stop_btn = self._mk_btn("停止", "danger", self._on_stop)
        self.install_btn = self._mk_btn("安装", None, self._on_install)
        self.update_btn = self._mk_btn("更新", "warning", self._on_update)
        self.remove_btn = self._mk_btn("删除", "secondary", self._on_remove)
        for b in (self.start_btn, self.stop_btn, self.install_btn, self.update_btn, self.remove_btn):
            btn_row.addWidget(b)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

    def _mk_btn(self, text: str, variant: str | None, slot) -> QPushButton:
        btn = QPushButton(text)
        btn.setCursor(Qt.PointingHandCursor)
        if variant:
            btn.setProperty("variant", variant)
        btn.clicked.connect(slot)
        return btn

    def refresh(self, p: dict):
        self.name_label.setText(p.get("name") or p["id"])
        self.platform_label.setText(" / ".join(p.get("platforms") or []) or "未声明")

        status = p.get("status", "")
        text, color = _STATUS_META.get(status, ("", "#9ca3af"))
        self.status_label.setText(text)
        self.status_label.setStyleSheet(
            f"background:#1f2937;color:{color};border:1px solid #374151;padding:1px 8px;"
            f"border-radius:3px;font-size:11px;"
        )

        installed = p.get("installed_version") or "—"
        latest = p.get("latest_version") or ""
        has_update = bool(installed) and installed != "—" and latest and installed != latest
        version_parts = [f"当前版本: {installed}"]
        if latest:
            version_parts.append(f"最新: {latest}")
        if has_update:
            version_parts.append("可更新")
        self.version_label.setText("  ·  ".join(version_parts))

        repo_url = p.get("repo_url") or ""
        if repo_url:
            short = repo_url.replace("https://github.com/", "").replace("http://github.com/", "")
            # 蓝色链接，点击用系统浏览器打开
            self.repo_label.setText(
                f'来源: <a href="{repo_url}" style="color:#60a5fa;">{short}</a>'
            )
            self.repo_label.setVisible(True)
        else:
            self.repo_label.setVisible(False)

        desc = p.get("description") or ""
        self.desc_label.setText(desc)
        self.desc_label.setVisible(bool(desc))

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
