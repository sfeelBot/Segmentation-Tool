"""존 분석 탭 — 일괄 처리 결과 표시 다이얼로그 (R-C 3b/3c).

long format 채택 이유: docs/specs/zone-analysis-tab-features-2026-08-26.md C-3 —
"개별 자동검출" 모드에서 이미지마다 원(=존) 개수가 달라질 수 있어 wide format(이미지×존
열)이 들쭉날쭉해지기 때문. 엑셀 내보내기(3c) 포함 — inference_tab.py의 완료 다이얼로그
패턴을 그대로 따른다.
"""
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem, QPushButton, QLabel,
    QHBoxLayout, QHeaderView, QFileDialog, QMessageBox,
)

from app.core.logger import get_logger
from app.core.zone_metrics import export_zone_percentages_to_excel

log = get_logger(__name__)


class ZoneBatchResultDialog(QDialog):
    """일괄 처리 결과 — (이미지, 존, 타겟 비율%) long format 테이블."""

    def __init__(self, rows: list[tuple[str, str, float]], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("일괄 처리 결과")
        self.resize(520, 480)
        self._rows = rows
        self._build_ui(rows)

    def _build_ui(self, rows: list[tuple[str, str, float]]) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"총 {len(rows)}개 행 (이미지 × 존)"))

        table = QTableWidget(len(rows), 3)
        table.setHorizontalHeaderLabels(["이미지", "존", "타겟 비율(%)"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for r, (img_name, zone_name, pct) in enumerate(rows):
            table.setItem(r, 0, QTableWidgetItem(img_name))
            table.setItem(r, 1, QTableWidgetItem(zone_name))
            table.setItem(r, 2, QTableWidgetItem(f"{pct:.2f}"))
        layout.addWidget(table, stretch=1)

        btn_row = QHBoxLayout()
        btn_export = QPushButton("Excel로 내보내기")
        btn_export.clicked.connect(self._on_export)
        btn_row.addWidget(btn_export)
        btn_row.addStretch()
        btn_close = QPushButton("닫기")
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

    def _on_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Excel로 내보내기", "zones.xlsx", "Excel (*.xlsx)"
        )
        if not path:
            return
        try:
            export_zone_percentages_to_excel(self._rows, Path(path))
        except Exception as exc:
            log.exception("Excel 내보내기 실패")
            QMessageBox.critical(self, "내보내기 오류", str(exc))
            return
        QMessageBox.information(
            self, "내보내기 완료", f"{len(self._rows)}개 행을 내보냈습니다."
        )
