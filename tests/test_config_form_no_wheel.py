from __future__ import annotations

import sys

import pytest
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QApplication, QAbstractSpinBox, QComboBox

from app.widgets.config_form import ConfigForm


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def _wheel_up() -> QWheelEvent:
    return QWheelEvent(
        QPointF(4, 4), QPointF(4, 4), QPoint(), QPoint(0, 120),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate, False,
    )


def test_training_parameter_editors_ignore_mouse_wheel() -> None:
    form = ConfigForm()
    editors = [
        *form.findChildren(QAbstractSpinBox),
        *form.findChildren(QComboBox),
    ]
    assert editors

    before = [
        editor.value() if isinstance(editor, QAbstractSpinBox)
        else editor.currentIndex()
        for editor in editors
    ]
    for editor in editors:
        QApplication.sendEvent(editor, _wheel_up())
    after = [
        editor.value() if isinstance(editor, QAbstractSpinBox)
        else editor.currentIndex()
        for editor in editors
    ]

    assert after == before


def test_direct_parameter_changes_remain_available() -> None:
    form = ConfigForm()
    original = form._epochs.value()
    form._epochs.setValue(original + 1)
    assert form._epochs.value() == original + 1
