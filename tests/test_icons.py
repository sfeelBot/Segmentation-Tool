from PyQt6.QtWidgets import QApplication

from app.widgets import icons

_APP = QApplication.instance() or QApplication([])


def test_pixmap_missing_file_returns_empty_pixmap_instead_of_crashing():
    pm = icons.pixmap("__no_such_icon__", size=16)
    assert not pm.isNull()
    assert pm.width() == 16 and pm.height() == 16


def test_icon_missing_file_returns_icon_without_raising():
    ic = icons.icon("__no_such_icon__")
    assert ic is not None
