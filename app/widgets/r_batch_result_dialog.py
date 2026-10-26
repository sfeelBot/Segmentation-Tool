"""R 분석 탭 — 셀 기준 일괄 분석 결과 다이얼로그. `zone_batch_result_dialog.py`의
Long/Wide + Excel export 구조를 셀 기준으로 재구성한 것(요구사항 8/9) — "셀"
탭(요약 1행 = 1셀, 이미지별 개별 판정 없음) + "이미지별(참고)" 탭(면적만 참고 표시).
"""
from pathlib import Path

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem, QPushButton,
    QHeaderView, QFileDialog, QMessageBox, QTabWidget, QWidget, QLabel,
)

from app.core.logger import get_logger
from app.core.r_analysis_metrics import export_r_results_to_excel

log = get_logger(__name__)

_PASS_BG = QColor("#10b981")
_FAIL_BG = QColor("#ef4444")
_NA_FG = QColor("#9ca3af")


class RBatchResultDialog(QDialog):
    """cells: {cell_id: {"sum_area","image_count","ratio","pass_fail","images":[(name,area),...]}}
    (`r_analysis_metrics.cell_rollup()` + "images" 키를 더한 구조, export 함수와 동일 스키마)."""

    def __init__(self, cells: dict, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("셀 일괄 분석 결과")
        self.resize(900, 600)
        self._cells = cells
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        tabs = QTabWidget()
        tabs.addTab(self._build_cell_tab(), "셀")
        tabs.addTab(self._build_image_tab(), "이미지별(참고)")
        layout.addWidget(tabs, stretch=1)

        btn_row = QHBoxLayout()
        btn_export = QPushButton("Excel로 내보내기")
        btn_export.clicked.connect(self._on_export)
        btn_row.addWidget(btn_export)
        btn_row.addStretch()
        btn_close = QPushButton("닫기")
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

    # ── 셀 탭 ────────────────────────────────────────────────────────────────

    def _build_cell_tab(self) -> QWidget:
        cell_ids = sorted(self._cells.keys())
        table = QTableWidget(len(cell_ids), 5)
        table.setHorizontalHeaderLabels(["셀", "이미지 수", "면적 합계", "ratio", "판정"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for r, cell_id in enumerate(cell_ids):
            data = self._cells[cell_id]
            ratio = data.get("ratio")
            pf = data.get("pass_fail")
            table.setItem(r, 0, QTableWidgetItem(cell_id))
            table.setItem(r, 1, QTableWidgetItem(str(data.get("image_count", 0))))
            table.setItem(r, 2, QTableWidgetItem(str(data.get("sum_area", 0))))
            table.setItem(r, 3, QTableWidgetItem(f"{ratio:.4f}" if ratio is not None else "N/A"))
            verdict_item = QTableWidgetItem("PASS" if pf else ("FAIL" if pf is False else "N/A"))
            if pf is True:
                verdict_item.setBackground(_PASS_BG)
            elif pf is False:
                verdict_item.setBackground(_FAIL_BG)
            else:
                verdict_item.setForeground(_NA_FG)
            table.setItem(r, 4, verdict_item)
        container = QWidget()
        v = QVBoxLayout(container)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(table)
        self._cell_table = table
        return container

    # ── 이미지별(참고) 탭 ────────────────────────────────────────────────────

    def _build_image_tab(self) -> QWidget:
        rows: list[tuple[str, str, int]] = [
            (cell_id, image_name, area)
            for cell_id, data in sorted(self._cells.items())
            for image_name, area in data.get("images", [])
        ]
        table = QTableWidget(len(rows), 3)
        table.setHorizontalHeaderLabels(["셀", "이미지", "면적(참고)"])
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for r, (cell_id, image_name, area) in enumerate(rows):
            table.setItem(r, 0, QTableWidgetItem(cell_id))
            table.setItem(r, 1, QTableWidgetItem(image_name))
            table.setItem(r, 2, QTableWidgetItem(str(area)))
        container = QWidget()
        v = QVBoxLayout(container)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(table)
        caption = QLabel(
            "이미지별 면적은 셀 판정을 구성하는 참고 데이터입니다 — 이미지별 개별 판정은 없습니다."
        )
        caption.setStyleSheet("color:#6b7280;font-size:10.5px;")
        v.addWidget(caption)
        self._image_table = table
        return container

    # ── Excel 내보내기 ───────────────────────────────────────────────────────

    def _on_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Excel로 내보내기", "r_results.xlsx", "Excel (*.xlsx)"
        )
        if not path:
            return
        try:
            export_r_results_to_excel(self._cells, Path(path))
        except Exception as exc:
            log.exception("Excel 내보내기 실패")
            QMessageBox.critical(self, "내보내기 오류", str(exc))
            return
        QMessageBox.information(self, "내보내기 완료", f"{len(self._cells)}개 셀을 내보냈습니다.")


if __name__ == "__main__":
    import os
    import sys
    import tempfile

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)

    sample_cells = {
        "CELL-A": {
            "sum_area": 300, "image_count": 3, "ratio": 1.0, "pass_fail": True,
            "images": [("a.jpg", 100), ("b.jpg", 150), ("c.jpg", 50)],
        },
        "CELL-B": {
            "sum_area": 10, "image_count": 1, "ratio": 0.03, "pass_fail": False,
            "images": [("d.jpg", 10)],
        },
        "CELL-C": {
            "sum_area": 0, "image_count": 0, "ratio": None, "pass_fail": None,
            "images": [],
        },
    }
    dlg = RBatchResultDialog(sample_cells)
    assert dlg._cell_table.rowCount() == 3
    assert dlg._image_table.rowCount() == 4   # CELL-A 3장 + CELL-B 1장 (CELL-C는 0장)
    assert dlg._cell_table.item(0, 0).text() == "CELL-A"   # 정렬순 첫 행
    assert dlg._cell_table.item(0, 4).background().color().name() == "#10b981"
    assert dlg._cell_table.item(1, 4).background().color().name() == "#ef4444"

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out.xlsx"
        export_r_results_to_excel(sample_cells, out)
        assert out.exists()

    print("r_batch_result_dialog self-check OK")
