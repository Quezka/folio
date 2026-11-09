"""Settings: appearance and language."""
from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QPushButton
from quezka_ui.settings import SettingsWindow

from . import i18n, theme, uiscale
from .background import restart_app
from .i18n import _
from .views.common import Segmented


class SettingsDialog(SettingsWindow):
    """Look (appearance, glass, contrast, language, size) and Updates, in the suite's Settings window."""

    def __init__(self, services, updater=None, parent=None):
        super().__init__(_("Settings"), _("Close"), parent, width=820, height=560)
        self.services = services
        manager = theme.manager()

        look = self.section(_("Appearance"), "palette")
        card = look.card()
        mode = Segmented([("system", _("System")), ("light", _("Light")), ("dark", _("Dark"))])
        mode.set_value(manager.mode)
        mode.changed.connect(manager.set_mode)
        card.row(_("Appearance"), mode, _("Exported pictures are always drawn on white."))
        card.switch(_("Glass look"), manager.glass,
                    _("Menus, bars and headers blur what's under them."), manager.set_glass)
        if hasattr(manager, "set_see_through"):
            from quezka_ui import theme as kit_theme
            possible = kit_theme.SEE_THROUGH_POSSIBLE
            see_through = card.switch(_("See-through windows"), manager.see_through and possible,
                            _("The desktop shows through, blurred. Takes effect the next time the app starts.") if possible
                            else _("On GNOME this needs the Blur my Shell extension."), manager.set_see_through)
            see_through.setEnabled(possible)
        card.switch(_("High contrast (black and white, thick lines)"), manager.contrast,
                    on_toggled=manager.set_contrast)

        card = look.card()
        self.language = QComboBox()
        for code, name in i18n.LANGUAGES:
            self.language.addItem(_(name) if code == "" else name, code)
        self.language.setCurrentIndex(max(0, self.language.findData(i18n.chosen_language())))
        self.restart = QPushButton(_("Restart Folio now"))
        self.restart.hide()
        self.restart.clicked.connect(self._restart)
        self.restart_size = self.restart  # one button for either change
        self.language.currentIndexChanged.connect(self._language_changed)
        card.row(_("Interface language"), self.language, stretch_control=True)
        self.scale = QComboBox()
        for choice in uiscale.CHOICES:
            self.scale.addItem(_("Automatic") if choice == "auto" else f"{choice}%", choice)
        self.scale.setCurrentIndex(max(0, self.scale.findData(uiscale.chosen())))
        self.scale.currentIndexChanged.connect(self._scale_changed)
        card.row(_("Interface size"), self.scale, _("Applies after a restart. Automatic is a comfortable, slightly larger size."), stretch_control=True)
        card.wide(self.restart)

        updates = self.section(_("Updates"), "download")
        card = updates.card()
        card.switch(_("Check for new versions once a day"), services.updates.auto_check(),
                    on_toggled=services.updates.set_auto_check)
        check = QPushButton(_("Check now"))
        check.setEnabled(updater is not None)
        if updater is not None:
            check.clicked.connect(lambda: updater.check_now())
        card.row(_("You have version {version}.").format(version=services.updates.current_version), check)

    def _scale_changed(self):
        uiscale.set_chosen(self.scale.currentData())
        self.restart_size.show()

    def _language_changed(self):
        i18n.set_chosen_language(self.language.currentData())
        self.restart.show()

    def _restart(self):
        self.accept()
        restart_app()
