"""R 분석 탭 — 셀(cell) 목록 + 선택된 셀의 이미지 목록 패널.

"셀"은 여러 이미지를 묶는 신규 데이터 모델(스펙 "배경" 절) — 폴더 일괄 업로드 시
바로 아래 하위폴더명이 셀 ID가 되고(요구사항 2a), 개별 파일을 사용자가 지정한
셀 ID(신규/기존)에 수동 추가도 가능하다(요구사항 2b). 선택된 셀의 이미지 표시는
`InferenceImageList`(검색/정렬/Delete 키 제거/파일 다이얼로그를 이미 제공)를
그대로 재사용한다 — 재구현하지 않음(CLAUDE.md 원칙).
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget, QListWidgetItem,
    QLabel, QFileDialog, QInputDialog,
)

from app.core.i18n import t
from app.widgets.icons import icon as svg_icon
from app.widgets.inference_image_list import InferenceImageList, SUPPORTED_EXTS

_STATUS_COLORS: dict[bool | None, str] = {True: "#10b981", False: "#ef4444", None: "#6b7280"}
_CELL_ID_ROLE = Qt.ItemDataRole.UserRole


class RCellPanel(QWidget):
    """셀 목록(판정 dot 포함) + 선택 셀의 이미지 목록(삭제/추가) + 가져오기 버튼."""

    cell_selected = pyqtSignal(str)
    cells_changed = pyqtSignal()
    image_selected = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._cells: dict[str, list[Path]] = {}
        self._cell_status: dict[str, bool | None] = {}
        self._current_cell: str | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        layout.addWidget(QLabel(t("r_cell.list_title")))
        btn_row = QHBoxLayout()
        self._btn_import_folder = QPushButton(t("r_cell.btn_import_folder"))
        self._btn_import_folder.setToolTip(t("r_cell.import_folder_tip"))
        self._btn_import_folder.clicked.connect(self._on_import_folder)
        btn_row.addWidget(self._btn_import_folder)
        self._btn_add_files = QPushButton(t("r_cell.btn_add_files"))
        self._btn_add_files.clicked.connect(self._on_add_files)
        btn_row.addWidget(self._btn_add_files)
        layout.addLayout(btn_row)

        self._cell_list = QListWidget()
        self._cell_list.currentItemChanged.connect(self._on_cell_selected)
        layout.addWidget(self._cell_list, stretch=1)

        layout.addWidget(QLabel(t("r_cell.image_list_title")))
        self._image_list = InferenceImageList()
        self._image_list.set_multi_select(True)   # Zone 탭과 동일 — Shift/Ctrl 다중선택 + Delete 일괄 제거
        self._image_list.image_selected.connect(lambda p: self.image_selected.emit(str(p)))
        self._image_list.images_removed.connect(self._on_images_removed)
        layout.addWidget(self._image_list, stretch=2)

        self._btn_add_to_cell = QPushButton(t("r_cell.btn_add_to_cell"))
        self._btn_add_to_cell.clicked.connect(self._on_add_images_to_current_cell)
        layout.addWidget(self._btn_add_to_cell)

    # ── 공개 API ─────────────────────────────────────────────────────────────

    def set_cells(self, cells: dict[str, list[Path]]) -> None:
        self._cells = {cid: list(paths) for cid, paths in cells.items()}
        self._refresh_cell_list()

    def get_cells(self) -> dict[str, list[Path]]:
        return {cid: list(paths) for cid, paths in self._cells.items()}

    def set_cell_status(self, cell_id: str, status: bool | None) -> None:
        """셀 R/판정 재계산 후 탭이 호출 — 목록 행의 dot 색만 갱신."""
        self._cell_status[cell_id] = status
        for i in range(self._cell_list.count()):
            item = self._cell_list.item(i)
            if item.data(_CELL_ID_ROLE) == cell_id:
                item.setIcon(self._status_icon(status))
                return

    def selected_cell(self) -> str | None:
        return self._current_cell

    def select_image(self, path: Path) -> None:
        """R 분석 탭이 썸네일 스트립/◀▶ 네비게이션으로 현재 이미지를 바꿨을 때
        좌측 이미지 목록의 강조 표시도 맞추기 위해 호출(스펙 요구사항 2 "3곳
        동일 상태 공유"). path가 선택된 셀 소속이 아니면 조용히 무시한다."""
        self._image_list.select_path(path)

    # ── 셀 가져오기/추가 ─────────────────────────────────────────────────────

    def _on_import_folder(self) -> None:
        root_str = QFileDialog.getExistingDirectory(self, t("r_cell.import_folder_dialog_title"))
        if not root_str:
            return
        root = Path(root_str)
        changed = False
        for sub in sorted(p for p in root.iterdir() if p.is_dir()):
            images = sorted(
                p for p in sub.iterdir()
                if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS
            )
            if not images:
                continue
            existing = self._cells.setdefault(sub.name, [])
            for img in images:
                if img not in existing:
                    existing.append(img)
            self._cell_status.setdefault(sub.name, None)
            changed = True
        if changed:
            self._refresh_cell_list()
            self.cells_changed.emit()

    def _on_add_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, t("r_cell.select_image_files_title"), "", t("r_cell.image_filter"),
        )
        if not files:
            return
        cell_id = self._prompt_cell_id()
        if cell_id is None:
            return
        existing = self._cells.setdefault(cell_id, [])
        for f in files:
            p = Path(f)
            if p not in existing:
                existing.append(p)
        self._cell_status.setdefault(cell_id, None)
        self._refresh_cell_list()
        self._select_cell(cell_id)
        self.cells_changed.emit()

    def _on_add_images_to_current_cell(self) -> None:
        if self._current_cell is None:
            return
        files, _ = QFileDialog.getOpenFileNames(
            self, t("r_cell.select_image_files_title"), "", t("r_cell.image_filter"),
        )
        if not files:
            return
        existing = self._cells.setdefault(self._current_cell, [])
        for f in files:
            p = Path(f)
            if p not in existing:
                existing.append(p)
        self._image_list.load_files(existing)
        self._refresh_cell_list()
        self._select_cell(self._current_cell)
        self.cells_changed.emit()

    def _prompt_cell_id(self) -> str | None:
        items = sorted(self._cells.keys())
        text, ok = QInputDialog.getItem(
            self, t("r_cell.cell_id_dialog_title"), t("r_cell.cell_id_dialog_label"), items, 0, True,
        )
        if not ok:
            return None
        text = text.strip()
        return text or None

    def _on_images_removed(self, removed: list) -> None:
        if self._current_cell is None:
            return
        removed_set = set(removed)
        self._cells[self._current_cell] = [
            p for p in self._cells.get(self._current_cell, []) if p not in removed_set
        ]
        self._refresh_cell_list()
        self._select_cell(self._current_cell)
        self.cells_changed.emit()

    # ── 내부 ─────────────────────────────────────────────────────────────────

    def _on_cell_selected(self, current: QListWidgetItem | None, _previous) -> None:
        cell_id = current.data(_CELL_ID_ROLE) if current is not None else None
        self._current_cell = cell_id
        if cell_id is not None:
            self._image_list.load_files(self._cells.get(cell_id, []))
            self.cell_selected.emit(cell_id)

    def _refresh_cell_list(self) -> None:
        prev = self._current_cell
        self._cell_list.blockSignals(True)
        self._cell_list.clear()
        for cell_id in sorted(self._cells.keys()):
            item = QListWidgetItem(f"{cell_id}  ({len(self._cells[cell_id])})")
            item.setData(_CELL_ID_ROLE, cell_id)
            item.setIcon(self._status_icon(self._cell_status.get(cell_id)))
            self._cell_list.addItem(item)
        self._cell_list.blockSignals(False)
        if prev is not None and prev in self._cells:
            self._select_cell(prev)
        elif self._cell_list.count():
            self._cell_list.setCurrentRow(0)

    def _select_cell(self, cell_id: str) -> None:
        for i in range(self._cell_list.count()):
            item = self._cell_list.item(i)
            if item.data(_CELL_ID_ROLE) == cell_id:
                self._cell_list.setCurrentItem(item)
                return

    def _status_icon(self, status: bool | None) -> QIcon:
        return svg_icon("status_dot", _STATUS_COLORS.get(status, "#6b7280"), 12)


if __name__ == "__main__":
    import os
    import sys

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)

    panel = RCellPanel()
    panel.set_cells({"CELL-A": [Path("a.jpg"), Path("b.jpg")], "CELL-B": [Path("c.jpg")]})
    assert panel.get_cells()["CELL-A"] == [Path("a.jpg"), Path("b.jpg")]
    assert panel._cell_list.count() == 2, "셀 2개가 목록에 표시돼야 함"

    panel._select_cell("CELL-A")
    assert panel.selected_cell() == "CELL-A"

    panel.set_cell_status("CELL-A", True)
    assert panel._cell_status["CELL-A"] is True

    # 선택 셀에서 이미지 1장 제거 시뮬레이션(InferenceImageList.images_removed emit 경로)
    panel._on_images_removed([Path("a.jpg")])
    assert panel.get_cells()["CELL-A"] == [Path("b.jpg")], "제거된 이미지가 빠져야 함"

    # 다른 셀 선택 시 current_cell 전환
    panel._select_cell("CELL-B")
    assert panel.selected_cell() == "CELL-B"

    # Zone 탭과 동일한 Shift/Ctrl 다중선택 + Delete 일괄 제거 동작(이번 변경)
    from PyQt6.QtWidgets import QTreeWidget
    assert panel._image_list._tree.selectionMode() == QTreeWidget.SelectionMode.ExtendedSelection
    panel._select_cell("CELL-A")
    panel._on_images_removed([Path("a.jpg"), Path("b.jpg")])
    assert panel.get_cells()["CELL-A"] == [], "다중 선택 삭제 시 전부 제거돼야 함"

    print("r_cell_panel self-check OK")
