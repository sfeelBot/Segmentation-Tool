"""Golden paths for the "N. " display-order numbering prefix on image lists."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import project
from app.widgets.image_browser import ImageBrowser
from app.widgets.inference_image_list import InferenceImageList

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


def _make_image(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    assert QImage(4, 4, QImage.Format.Format_RGB32).save(str(path))


def test_image_browser_numbers_display_order(sample_project) -> None:
    browser = ImageBrowser()  # name_asc default -> a, b, c
    a, b, c = sample_project[1], sample_project[0], sample_project[2]
    assert browser._path_to_item[a].text(0) == "1. a.png"
    assert browser._path_to_item[b].text(0) == "2. b.png"
    assert browser._path_to_item[c].text(0) == "3. c.png"


def test_image_browser_refresh_item_preserves_number(sample_project) -> None:
    browser = ImageBrowser()
    b = sample_project[0]
    assert browser._path_to_item[b].text(0) == "2. b.png"

    browser.refresh_item(b)  # single-item refresh path, no full rebuild

    assert browser._path_to_item[b].text(0) == "2. b.png"
    # sibling numbers untouched
    a, c = sample_project[1], sample_project[2]
    assert browser._path_to_item[a].text(0) == "1. a.png"
    assert browser._path_to_item[c].text(0) == "3. c.png"


def test_image_browser_filter_renumbers_from_one(sample_project) -> None:
    browser = ImageBrowser()
    browser._filter_text = "c.png"
    browser._apply_display()
    c = sample_project[2]
    assert browser._path_to_item[c].text(0) == "1. c.png"


def test_inference_list_flat_numbers_in_display_order(tmp_path: Path) -> None:
    a, b = tmp_path / "b.png", tmp_path / "a.png"
    _make_image(a)
    _make_image(b)
    widget = InferenceImageList()
    widget.load_files([a, b])  # name_asc default -> a.png, b.png
    assert widget._path_to_item[b].text(0) == "1. a.png"
    assert widget._path_to_item[a].text(0) == "2. b.png"


def test_inference_list_folder_mode_headers_unnumbered_leaves_continuous(
        tmp_path: Path) -> None:
    root = tmp_path / "root"
    f1 = root / "folder1" / "x.png"
    f2 = root / "folder2" / "y.png"
    _make_image(f1)
    _make_image(f2)
    widget = InferenceImageList()
    widget.load_folder(root)
    widget._sort_combo.setCurrentIndex(4)  # "folder" sort mode

    numbers = []
    for path, item in widget._path_to_item.items():
        assert item.text(0).split(". ", 1)[0].isdigit()
        numbers.append(int(item.text(0).split(". ", 1)[0]))
    assert sorted(numbers) == [1, 2]  # continuous global numbering, not per-folder

    # folder header items must not carry a numeric prefix
    root_item = widget._tree.topLevelItem(0)
    assert not root_item.text(0)[0].isdigit()
