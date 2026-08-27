"""Golden paths for labeling-tab multi-selection OK processing."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication, QMessageBox

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import annotation_store as store
from app.core.annotation_store import AnnotationItem
from app.core import project
from app.tabs.labeling_tab import LabelingTab
from app.widgets.image_browser import ImageBrowser

_APP = QApplication.instance() or QApplication(sys.argv)


@pytest.fixture()
def sample_project(tmp_path: Path):
    previous = project.current()
    current = project.Project(tmp_path / "project")
    current.ensure_dirs()
    project._current = current
    paths = []
    for name in ("b.png", "a.png", "c.png"):
        path = current.images_dir / name
        assert QImage(4, 4, QImage.Format.Format_RGB32).save(str(path))
        paths.append(path)
    try:
        yield paths
    finally:
        project._current = previous


def _write(path: Path, annotations: list[dict] | None = None, ok: bool = False) -> None:
    data = {
        "version": "1.0", "image": path.name, "width": 4, "height": 4,
        "annotations": annotations or [],
    }
    if ok:
        data["ok"] = True
    (project.annotations_dir() / f"{path.stem}.json").write_text(
        json.dumps(data), encoding="utf-8"
    )


def _select(browser: ImageBrowser, paths: list[Path], current: Path) -> None:
    browser._tree.clearSelection()
    browser._tree.setCurrentItem(browser._path_to_item[current])
    for path in paths:
        browser._path_to_item[path].setSelected(True)


def test_store_clears_labels_and_marks_ok_atomically_without_decode(
        sample_project, monkeypatch) -> None:
    path = sample_project[0]
    _write(path, [{"type": "brush_mask", "rle": "0 16"}])
    monkeypatch.setattr(store, "rle_decode", lambda *_args: pytest.fail("decoded mask"))

    store.set_ok_and_clear_annotations(path)
    store.set_ok_and_clear_annotations(path)  # idempotent

    data = json.loads((project.annotations_dir() / "b.json").read_text(encoding="utf-8"))
    assert data["annotations"] == []
    assert data["ok"] is True
    assert data["width"] == 4
    assert not list(project.annotations_dir().glob("*.tmp"))


@pytest.mark.parametrize("content", ["{broken", "[]"])
def test_store_rejects_existing_invalid_document(sample_project, content: str) -> None:
    path = sample_project[0]
    json_path = project.annotations_dir() / "b.json"
    json_path.write_text(content, encoding="utf-8")

    with pytest.raises((json.JSONDecodeError, ValueError)):
        store.set_ok_and_clear_annotations(path)

    assert json_path.read_text(encoding="utf-8") == content


def test_selected_paths_are_display_ordered_and_fall_back_to_current(sample_project) -> None:
    browser = ImageBrowser()
    a, b = sample_project[1], sample_project[0]
    _select(browser, [a, b], current=b)
    assert browser.selected_paths() == [a, b]

    browser._tree.clearSelection()
    # Qt keeps the current item selected in ExtendedSelection; explicitly clear its flag.
    browser._tree.currentItem().setSelected(False)
    assert browser.selected_paths() == [b]


def test_multi_ok_confirms_once_skips_existing_ok_and_preserves_selection(
        sample_project, monkeypatch) -> None:
    b, a, c = sample_project
    label = [{"annotation_id": "x", "class_id": 1, "type": "polygon",
              "points": [[0, 0], [1, 0], [1, 1]], "order": 0}]
    _write(a, label)
    _write(c, ok=True)
    tab = LabelingTab()
    _select(tab._image_browser, [a, b, c], current=b)
    questions = []
    monkeypatch.setattr(QMessageBox, "question", lambda *args: questions.append(args) or QMessageBox.StandardButton.Yes)

    tab._act_ok.trigger()

    assert len(questions) == 1
    assert all(store.get_ok(path) for path in (a, b, c))
    assert not store.has_annotations(a)
    assert tab._canvas._image_path == b
    assert tab._canvas._annotations == []
    assert set(tab._image_browser.selected_paths()) == {a, b, c}


def test_multi_ok_cancel_and_partial_failure_keep_prior_success(
        sample_project, monkeypatch) -> None:
    b, a, _c = sample_project
    label = [{"annotation_id": "x", "class_id": 1, "type": "polygon",
              "points": [[0, 0], [1, 0], [1, 1]], "order": 0}]
    _write(a, label)
    tab = LabelingTab()
    _select(tab._image_browser, [a, b], current=b)
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.No)
    tab._act_ok.trigger()
    assert not store.get_ok(a) and not store.get_ok(b)
    assert store.has_annotations(a)

    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Yes)
    original = store.set_ok_and_clear_annotations
    monkeypatch.setattr(
        store, "set_ok_and_clear_annotations",
        lambda path: (_ for _ in ()).throw(OSError("locked")) if path == a else original(path),
    )
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    tab._act_ok.trigger()
    assert store.get_ok(b)
    assert not store.get_ok(a) and store.has_annotations(a)
    assert len(warnings) == 1


def test_current_unsaved_labels_are_confirmed_and_flushed_before_batch_clear(
        sample_project, monkeypatch) -> None:
    b, a, _c = sample_project
    tab = LabelingTab()
    _select(tab._image_browser, [a, b], current=b)
    tab._canvas._annotations = [AnnotationItem(
        annotation_id="pending", class_id=1, type="polygon",
        points=[(0, 0), (1, 0), (1, 1)],
    )]
    tab._canvas._save_timer.start(60_000)
    questions = []
    monkeypatch.setattr(QMessageBox, "question", lambda *args: questions.append(args) or QMessageBox.StandardButton.Yes)

    tab._act_ok.trigger()

    assert len(questions) == 1
    assert store.get_ok(b) and not store.has_annotations(b)
    assert tab._canvas._annotations == []


def test_current_batch_helper_failure_preserves_flushed_labels_and_canvas(
        sample_project, monkeypatch) -> None:
    b, a, _c = sample_project
    tab = LabelingTab()
    _select(tab._image_browser, [a, b], current=b)
    pending = AnnotationItem(
        annotation_id="pending", class_id=1, type="polygon",
        points=[(0, 0), (1, 0), (1, 1)],
    )
    tab._canvas._annotations = [pending]
    tab._canvas._save_timer.start(60_000)
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Yes)
    original = store.set_ok_and_clear_annotations
    monkeypatch.setattr(
        store, "set_ok_and_clear_annotations",
        lambda path: (_ for _ in ()).throw(OSError("locked")) if path == b else original(path),
    )
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: None)

    tab._act_ok.trigger()

    assert not store.get_ok(b) and store.has_annotations(b)
    assert not tab._canvas._save_timer.isActive()
    assert [ann.annotation_id for ann in tab._canvas._annotations] == ["pending"]


def test_status_sort_refresh_preserves_visible_selection_without_reload(
        sample_project, monkeypatch) -> None:
    b, a, _c = sample_project
    browser = ImageBrowser()
    browser._sort_mode = "status_done"
    _select(browser, [a, b], current=b)
    _write(a, ok=True)
    monkeypatch.setattr(browser, "reload", lambda: pytest.fail("full rescan"))

    browser.refresh_items([a])

    assert browser.current_path() == b
    assert set(browser.selected_paths()) == {a, b}
    assert browser._paths[0] == a


def test_filter_rebuild_keeps_visible_current_and_selected_items(sample_project) -> None:
    b, a, _c = sample_project
    browser = ImageBrowser()
    _select(browser, [a, b], current=b)

    browser._filter_text = ".png"
    browser._apply_display()

    assert browser.current_path() == b
    assert browser.selected_paths() == [a, b]


def test_name_sort_refresh_updates_only_targets_without_rebuilding(
        sample_project, monkeypatch) -> None:
    b, a, _c = sample_project
    browser = ImageBrowser()
    browser._sort_mode = "name_asc"
    _write(a, ok=True)
    calls = []
    real_status = store.get_label_status
    monkeypatch.setattr(
        "app.widgets.image_browser.get_label_status",
        lambda path: calls.append(path) or real_status(path),
    )
    monkeypatch.setattr(browser, "_apply_display", lambda: pytest.fail("tree rebuilt"))

    browser.refresh_items([a, b])

    assert calls == [a, b]
    assert browser._status_cache[a] == "ok"
    assert browser.current_path() is not None
