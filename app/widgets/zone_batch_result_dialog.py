"""존 분석 탭 — 일괄 처리 결과 표시 다이얼로그 (R-C 3b/3c, R3-2 wide format).

long format 채택 이유: docs/specs/zone-analysis-tab-features-2026-08-26.md C-3 —
"개별 자동검출" 모드에서 이미지마다 원(=존) 개수가 달라질 수 있어 wide format(이미지×존
열)이 들쭉날쭉해지기 때문. 엑셀 내보내기(3c) 포함 — inference_tab.py의 완료 다이얼로그
패턴을 그대로 따른다. R3-2에서 QTabWidget으로 long format 옆에 wide format(이미지×존
피벗) 뷰를 추가했다 — long format이 여전히 원본 데이터, wide는 보조 뷰
(docs/specs/zone-analysis-tab-features-round3-2026-08-27.md 판단 4).
"""
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem, QPushButton, QLabel,
    QHBoxLayout, QHeaderView, QFileDialog, QMessageBox, QTabWidget, QWidget,
)

from app.core.logger import get_logger
from app.core.zone_metrics import export_zone_percentages_to_excel, pivot_wide_format, ZoneBlobStat

log = get_logger(__name__)


class ZoneBatchResultDialog(QDialog):
    """일괄 처리 결과 — (이미지, 존, 타겟 비율%) long format + wide format(이미지×존 피벗) 탭.

    R3: `blob_rows`(zone별 blob 크기 + AI 점수)는 Excel 내보내기 시에만 3번째 시트로
    쓰인다 — 화면 Long/Wide 탭 표시는 이번 라운드 범위 밖(스펙 명시).
    """

    def __init__(
        self,
        rows: list[tuple[str, str, float]],
        blob_rows: list[tuple[str, ZoneBlobStat]],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("일괄 처리 결과")
        self.resize(560, 480)
        self._rows = rows
        self._blob_rows = blob_rows
        self._build_ui(rows)

    def _build_ui(self, rows: list[tuple[str, str, float]]) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"총 {len(rows)}개 행 (이미지 × 존)"))

        tabs = QTabWidget()
        tabs.addTab(self._build_long_tab(rows), "목록별 (Long)")
        tabs.addTab(self._build_wide_tab(rows), "이미지별 (Wide)")
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

    def _build_long_tab(self, rows: list[tuple[str, str, float]]) -> QWidget:
        table = QTableWidget(len(rows), 3)
        table.setHorizontalHeaderLabels(["이미지", "존", "타겟 비율(%)"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for r, (img_name, zone_name, pct) in enumerate(rows):
            table.setItem(r, 0, QTableWidgetItem(img_name))
            table.setItem(r, 1, QTableWidgetItem(zone_name))
            table.setItem(r, 2, QTableWidgetItem(f"{pct:.2f}"))
        return table

    def _build_wide_tab(self, rows: list[tuple[str, str, float]]) -> QWidget:
        # 개별 자동검출 모드에서는 이미지마다 원(=존) 개수가 다를 수 있어 "링 1"이
        # 이미지마다 물리적으로 다른 고리를 가리킬 수 있음(wide format 본질적 한계,
        # 스펙 판단 4) — long format 탭이 여전히 정확한 원본 데이터임을 안내.
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        note = QLabel(
            "참고: 이미지마다 원(존) 개수가 다르면 같은 열이라도 다른 위치를 가리킬 "
            "수 있습니다. 정확한 원본 데이터는 '목록별' 탭을 참고하세요."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#9ca3af; font-size:11px;")
        layout.addWidget(note)

        images, zone_cols, values = pivot_wide_format(rows)
        table = QTableWidget(len(images), 1 + len(zone_cols))
        table.setHorizontalHeaderLabels(["이미지"] + zone_cols)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for r, img in enumerate(images):
            table.setItem(r, 0, QTableWidgetItem(img))
            for c, zone_name in enumerate(zone_cols, start=1):
                pct = values.get((img, zone_name))
                table.setItem(r, c, QTableWidgetItem(f"{pct:.2f}" if pct is not None else ""))
        layout.addWidget(table, stretch=1)
        return container

    def _on_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Excel로 내보내기", "zones.xlsx", "Excel (*.xlsx)"
        )
        if not path:
            return
        try:
            export_zone_percentages_to_excel(self._rows, Path(path), self._blob_rows)
        except Exception as exc:
            log.exception("Excel 내보내기 실패")
            QMessageBox.critical(self, "내보내기 오류", str(exc))
            return
        QMessageBox.information(
            self, "내보내기 완료", f"{len(self._rows)}개 행을 내보냈습니다."
        )
