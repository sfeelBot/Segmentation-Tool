"""Golden paths for image-list "N. " numbering (image_browser / inference_image_list)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import project
from app.widgets.image_browser import ImageBrowser
from app.widgets.inference_image_list import InferenceImageList, _SORT_MODES

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


def test_image_browser_numbers_reflect_display_order(sample_project) -> None:
    browser = ImageBrowser()
    # name_asc (default) → a, b, c
    assert [browser._path_to_item[p].text(0) for p in sorted(sample_project)] == [
        "1. a.png", "2. b.png", "3. c.png",
    ]


def test_image_browser_filter_renumbers_from_one(sample_project) -> None:
    browser = ImageBrowser()
    browser._filter_text = "a"
    browser._apply_display()
    a = sample_project[1]
    assert browser._path_to_item[a].text(0) == "1. a.png"


def test_image_browser_refresh_item_preserves_number(sample_project) -> None:
    browser = ImageBrowser()
    b, a, c = sample_project  # name_asc order: a(1) b(2) c(3)
    assert browser._path_to_item[b].text(0) == "2. b.png"

    browser.refresh_item(b)  # single-item refresh path, no full rebuild

    assert browser._path_to_item[b].text(0) == "2. b.png"


def test_inference_list_folder_mode_uses_continuous_numbering(tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "sub").mkdir(parents=True)
    p1 = root / "a.png"
    p2 = root / "sub" / "b.png"
    for p in (p1, p2):
        assert QImage(4, 4, QImage.Format.Format_RGB32).save(str(p))

    lst = InferenceImageList()
    lst.load_folder(root)
    folder_idx = [m[0] for m in _SORT_MODES].index("folder")
    lst._sort_combo.setCurrentIndex(folder_idx)

    assert lst._path_to_item[p1].text(0) == "1. a.png"
    assert lst._path_to_item[p2].text(0) == "2. b.png"


def test_inference_list_status_update_keeps_number(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    p1 = root / "a.png"
    p2 = root / "b.png"
    for p in (p1, p2):
        assert QImage(4, 4, QImage.Format.Format_RGB32).save(str(p))

    lst = InferenceImageList()
    lst.load_folder(root)
    assert lst._path_to_item[p2].text(0) == "2. b.png"

    lst.set_item_status(p2, "done", badge="완료")

    assert lst._path_to_item[p2].text(0) == "2. b.png  [완료]"
