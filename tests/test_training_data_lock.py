from __future__ import annotations

import sys
import threading
import time

import pytest
from PyQt6.QtWidgets import QApplication

from app.tabs.labeling_tab import LabelingTab
from app.widgets.annotation_canvas import AnnotationCanvas
from app.widgets.class_panel import ClassPanel
from app.widgets.image_browser import ImageBrowser


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.mark.parametrize(
    ("factory", "method"),
    [
        (ImageBrowser, "_on_add"),
        (ImageBrowser, "_on_add_folder"),
        (ImageBrowser, "_on_delete"),
        (ClassPanel, "_on_add"),
        (ClassPanel, "_on_delete"),
        (ClassPanel, "_on_change_color"),
    ],
)
def test_widget_mutations_stop_at_common_guard(monkeypatch, factory, method):
    widget = factory()
    calls = []
    widget.set_mutation_guard(lambda: calls.append(method) and False)

    getattr(widget, method)()

    assert calls == [method]


def test_canvas_undo_is_blocked_by_guard():
    canvas = AnnotationCanvas()
    original = list(canvas._annotations)
    canvas._undo_stack.append([object()])
    canvas.set_mutation_guard(lambda: False)

    canvas.undo()

    assert canvas._annotations == original
    assert len(canvas._undo_stack) == 1


def test_training_preflight_flushes_pending_canvas_save(monkeypatch):
    tab = LabelingTab()
    saved = []
    monkeypatch.setattr(tab._canvas._save_timer, "isActive", lambda: True)
    monkeypatch.setattr(tab._canvas._save_timer, "stop", lambda: saved.append("stop"))
    monkeypatch.setattr(tab._canvas, "_do_save", lambda sync=False: saved.append(sync))

    assert tab.prepare_for_training() is True
    assert saved == ["stop", True]


def test_training_preflight_waits_for_running_background_save(monkeypatch):
    tab = LabelingTab()
    finished = threading.Event()
    def complete_save():
        time.sleep(0.02)
        finished.set()
        with tab._canvas._save_threads_lock:
            tab._canvas._save_threads.discard(threading.current_thread())

    worker = threading.Thread(target=complete_save)
    with tab._canvas._save_threads_lock:
        tab._canvas._save_threads.add(worker)
    worker.start()
    monkeypatch.setattr(tab._canvas._save_timer, "isActive", lambda: False)

    assert tab.prepare_for_training() is True
    assert finished.is_set()
