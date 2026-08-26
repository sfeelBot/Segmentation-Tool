"""존 분석 탭 — 일괄 처리 결과 표시 다이얼로그 (R-C 3b).

long format 채택 이유: docs/specs/zone-analysis-tab-features-2026-08-26.md C-3 —
"개별 자동검출" 모드에서 이미지마다 원(=존) 개수가 달라질 수 있어 wide format(이미지×존
열)이 들쭉날쭉해지기 때문. 엑셀 내보내기(3c)는 이번 라운드 범위 밖 — 화면 표시만 담당.
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem, QPushButton, QLabel,
    QHBoxLayout, QHeaderView,
)


class ZoneBatchResultDialog(QDialog):
    """일괄 처리 결과 — (이미지, 존, 타겟 비율%) long format 테이블."""

    def __init__(self, rows: list[tuple[str, str, float]], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("일괄 처리 결과")
        self.resize(520, 480)
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
        btn_row.addStretch()
        btn_close = QPushButton("닫기")
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)
