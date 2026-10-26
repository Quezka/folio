"""Settings: appearance and language."""
from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QHBoxLayout, QPushButton, QVBoxLayout

from . import i18n, theme, uiscale
from .background import restart_app
from .fit import scrollable
from .i18n import _
from .views.common import Card, Segmented, caption, label


class SettingsDialog(QDialog):
    def __init__(self, services, updater=None, parent=None):
        super().__init__(parent)
        self.services = services
        self.setWindowTitle(_("Settings"))
        self.setMinimumWidth(391)
        manager = theme.manager()
        appearance = Card(_("Appearance"))
        mode = Segmented([("system", _("System")), ("light", _("Light")), ("dark", _("Dark"))])
        mode.set_value(manager.mode)
        mode.changed.connect(manager.set_mode)
        appearance.add(mode)
        contrast = QCheckBox(_("High contrast (black and white, thick lines)"))
        contrast.setChecked(manager.contrast)
        contrast.toggled.connect(manager.set_contrast)
        appearance.add(contrast)
        appearance.add(label(_("Exported pictures are always drawn on white."), "hint"))

        language = Card(_("Language"))
        self.language = QComboBox()
        for code, name in i18n.LANGUAGES:
            self.language.addItem(_(name) if code == "" else name, code)
        self.language.setCurrentIndex(max(0, self.language.findData(i18n.chosen_language())))
        self.restart_size = QPushButton(_("Restart Folio now"))
        self.restart_size.hide()
        self.restart_size.clicked.connect(self._restart)
        self.restart = QPushButton(_("Restart Folio now"))
        self.restart.hide()
        self.restart.clicked.connect(self._restart)
        self.language.currentIndexChanged.connect(self._language_changed)
        language.add(caption(_("Interface language")))
        language.add(self.language)
        language.add(self.restart)

        size = Card(_("Interface size"))
        self.scale = QComboBox()
        for choice in uiscale.CHOICES:
            self.scale.addItem(_("Automatic") if choice == "auto" else f"{choice}%", choice)
        self.scale.setCurrentIndex(max(0, self.scale.findData(uiscale.chosen())))
        self.scale.currentIndexChanged.connect(self._scale_changed)
        size.add(self.scale)
        size.add(label(_("Applies after a restart. Automatic is a comfortable, slightly larger size."), "hint"))
        size.add(self.restart_size)

        updates = Card(_("Updates"))
        auto = QCheckBox(_("Check for new versions once a day"))
        auto.setChecked(services.updates.auto_check())
        auto.toggled.connect(services.updates.set_auto_check)
        updates.add(auto)
        check = QPushButton(_("Check now"))
        check.setEnabled(updater is not None)
        if updater is not None:
            check.clicked.connect(lambda: updater.check_now())
        updates.add(check)
        updates.add(label(_("You have version {version}.").format(
            version=services.updates.current_version), "hint"))

        close = QPushButton(_("Close"))
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(close)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(14)
        layout.addWidget(appearance)
        layout.addWidget(language)
        layout.addWidget(size)
        layout.addWidget(updates)
        layout.addLayout(row)
        scrollable(self)

    def _scale_changed(self):
        uiscale.set_chosen(self.scale.currentData())
        self.restart_size.show()

    def _language_changed(self):
        i18n.set_chosen_language(self.language.currentData())
        self.restart.show()

    def _restart(self):
        self.accept()
        restart_app()
