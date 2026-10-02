"""존 분석 탭 — 일괄 처리 결과 표시 다이얼로그 (R-C 3b/3c, R3-2 wide format).

long format 채택 이유: docs/specs/zone-analysis-tab-features-2026-08-26.md C-3 —
"개별 자동검출" 모드에서 이미지마다 원(=존) 개수가 달라질 수 있어 wide format(이미지×존
열)이 들쭉날쭉해지기 때문. 엑셀 내보내기(3c) 포함 — inference_tab.py의 완료 다이얼로그
패턴을 그대로 따른다. R3-2에서 QTabWidget으로 long format 옆에 wide format(이미지×존
피벗) 뷰를 추가했다 — long format이 여전히 원본 데이터, wide는 보조 뷰
(docs/specs/zone-analysis-tab-features-round3-2026-08-27.md 판단 4).

2026-10-01 재설계(라운드 F): "최대 blob 픽셀수" 열 추가(Excel `zones` 시트 + 화면
Long 탭), 클립보드 복사 버튼, Long 탭 이미지명 셀 그룹화(`setSpan`), Long/Wide
공통 필터 바(이미지명 검색 + 존 다중 토글 + "N/전체" 카운터 + 초기화). 필터는
화면 표시 행만 걸러낸다 — Excel/클립보드 내보내기는 항상 전체 데이터 기준
(스펙 명시, "찾아보기" 용도이지 "내보내기 범위 제한" 용도가 아님).
"""
from pathlib import Path

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem, QPushButton, QLabel,
    QHBoxLayout, QHeaderView, QFileDialog, QMessageBox, QTabWidget, QWidget,
    QLineEdit, QApplication,
)

from app.core.logger import get_logger
from app.core.zone_metrics import (
    export_zone_percentages_to_excel, pivot_wide_format, ZoneBlobStat,
    max_blob_pixels_by_zone, zone_name_sort_key,
)

log = get_logger(__name__)


class ZoneBatchResultDialog(QDialog):
    """일괄 처리 결과 — (이미지, 존, 타겟 비율%, 최대 blob 픽셀수) long format +
    wide format(이미지×존 피벗) 탭. 검색/존 필터는 화면 표시용이고 내보내기는
    항상 전체 데이터 기준이다."""

    def __init__(
        self,
        rows: list[tuple[str, str, float]],
        blob_rows: list[tuple[str, ZoneBlobStat]],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("일괄 처리 결과")
        self.resize(1000, 700)
        self._rows = rows
        self._blob_rows = blob_rows
        self._zone_buttons: dict[str, QPushButton] = {}
        self._long_rows_sorted: list[tuple[str, str, float]] = []
        self._build_ui(rows)

    def _build_ui(self, rows: list[tuple[str, str, float]]) -> None:
        layout = QVBoxLayout(self)

        layout.addLayout(self._build_filter_bar(rows))

        tabs = QTabWidget()
        tabs.addTab(self._build_long_tab(rows, self._blob_rows), "Long (이미지 × 존)")
        tabs.addTab(self._build_wide_tab(rows), "Wide (피벗)")
        layout.addWidget(tabs, stretch=1)

        btn_row = QHBoxLayout()
        btn_export = QPushButton("Excel로 내보내기")
        btn_export.clicked.connect(self._on_export)
        btn_row.addWidget(btn_export)
        btn_copy = QPushButton("클립보드로 복사")
        btn_copy.clicked.connect(self._on_copy_clipboard)
        btn_row.addWidget(btn_copy)
        btn_row.addStretch()
        btn_close = QPushButton("닫기")
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

        self._apply_filter()

    # ── 필터 바(Long/Wide 공통) — 표시 행만 거름, 내보내기 범위와 무관 ────────

    def _build_filter_bar(self, rows: list[tuple[str, str, float]]) -> QHBoxLayout:
        bar = QHBoxLayout()
        lbl_filter = QLabel("필터")
        lbl_filter.setStyleSheet("color:#9ca3af;font-weight:bold;")
        bar.addWidget(lbl_filter)
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("이미지명 검색...")
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.textChanged.connect(self._apply_filter)
        bar.addWidget(self._search_edit, stretch=1)

        bar.addWidget(QLabel("존:"))
        zone_names = sorted({zone for _, zone, _ in rows}, key=zone_name_sort_key)
        for zone in zone_names:
            btn = QPushButton(zone)
            btn.setCheckable(True)
            btn.setChecked(True)
            btn.setStyleSheet("""
                QPushButton { background:#2b313a; border:1px dashed #4b5563; border-radius:12px;
                              padding:2px 10px; color:#9ca3af; }
                QPushButton:checked { background:#1e3a5f; border:1px solid #60a5fa;
                                      color:#93c5fd; }
            """)
            btn.toggled.connect(self._apply_filter)
            bar.addWidget(btn)
            self._zone_buttons[zone] = btn

        self._lbl_filter_count = QLabel()
        self._lbl_filter_count.setStyleSheet("color:#9ca3af;")
        bar.addWidget(self._lbl_filter_count)

        btn_reset = QPushButton("초기화")
        btn_reset.clicked.connect(self._on_reset_filter)
        bar.addWidget(btn_reset)
        return bar

    def _on_reset_filter(self) -> None:
        self._search_edit.clear()
        for btn in self._zone_buttons.values():
            btn.setChecked(True)
        self._apply_filter()

    def _apply_filter(self) -> None:
        if not hasattr(self, "_long_table"):
            return   # 필터 바가 테이블보다 먼저 만들어져 초기 connect 시점엔 테이블 없음
        text = self._search_edit.text().strip().lower()
        active_zones = {z for z, btn in self._zone_buttons.items() if btn.isChecked()}

        visible = 0
        for r, (img_name, zone_name, _pct) in enumerate(self._long_rows_sorted):
            match = (not text or text in img_name.lower()) and zone_name in active_zones
            self._long_table.setRowHidden(r, not match)
            if match:
                visible += 1
        self._lbl_filter_count.setText(f"{visible} / {len(self._long_rows_sorted)}")

        for r, img in enumerate(self._wide_images):
            self._wide_table.setRowHidden(r, bool(text) and text not in img.lower())
        for c, zone_name in enumerate(self._wide_zone_cols, start=1):
            self._wide_table.setColumnHidden(c, zone_name not in active_zones)

    # ── Long 탭 ──────────────────────────────────────────────────────────────

    def _build_long_tab(
        self, rows: list[tuple[str, str, float]], blob_rows: list[tuple[str, ZoneBlobStat]],
    ) -> QWidget:
        # 이미지명 기준 정렬 — 같은 이미지의 zone 행이 연속해야 setSpan 그룹화가
        # 의미를 가진다(스펙 명시). 파이썬 정렬은 stable이라 같은 이미지 안에서
        # zone 순서(보통 중심부->바깥쪽)는 원래 순서 그대로 유지된다.
        sorted_rows = sorted(rows, key=lambda row: row[0])
        self._long_rows_sorted = sorted_rows
        max_blobs = max_blob_pixels_by_zone(blob_rows)

        table = QTableWidget(len(sorted_rows), 4)
        table.setHorizontalHeaderLabels(["이미지", "존", "타겟 비율(%)", "최대 blob 픽셀수"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for r, (img_name, zone_name, pct) in enumerate(sorted_rows):
            table.setItem(r, 0, QTableWidgetItem(img_name))
            table.setItem(r, 1, QTableWidgetItem(zone_name))
            table.setItem(r, 2, QTableWidgetItem(f"{pct:.2f}"))
            table.setItem(r, 3, QTableWidgetItem(str(max_blobs.get((img_name, zone_name), 0))))

        group_colors = ["#111418", "#15181d"]
        group_idx = 0
        start = 0
        for r in range(1, len(sorted_rows) + 1):
            at_boundary = r == len(sorted_rows) or sorted_rows[r][0] != sorted_rows[start][0]
            if at_boundary:
                color = group_colors[group_idx % 2]
                for rr in range(start, r):
                    for cc in range(4):
                        item = table.item(rr, cc)
                        if item is not None:
                            item.setBackground(QColor(color))
                if r - start > 1:
                    table.setSpan(start, 0, r - start, 1)
                group_idx += 1
                start = r

        container = QWidget()
        v = QVBoxLayout(container)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(table, stretch=1)
        caption = QLabel(
            "\"최대 blob 픽셀수\"는 해당 (이미지, 존) 안에서 가장 큰 연결 영역 1개의 "
            "픽셀 수입니다 — 존재하지 않으면 0."
        )
        caption.setStyleSheet("color:#6b7280;font-size:10.5px;")
        v.addWidget(caption)
        self._long_table = table
        return container

    # ── Wide 탭 ──────────────────────────────────────────────────────────────

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
        self._wide_images = images
        self._wide_zone_cols = zone_cols
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
        self._wide_table = table
        return container

    # ── 내보내기 — 항상 전체 데이터 기준(필터 영향 없음) ─────────────────────

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

    def _on_copy_clipboard(self) -> None:
        max_blobs = max_blob_pixels_by_zone(self._blob_rows)
        lines = ["이미지\t존\t타겟 비율(%)\t최대 blob 픽셀수"]
        for img_name, zone_name, pct in self._rows:
            lines.append(
                f"{img_name}\t{zone_name}\t{pct:.2f}\t{max_blobs.get((img_name, zone_name), 0)}"
            )
        QApplication.clipboard().setText("\n".join(lines))
