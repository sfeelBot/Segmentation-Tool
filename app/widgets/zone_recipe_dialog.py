"""Zone 분석 탭 — "일괄 적용" 모드 전용 레시피 관리 팝업.

기준 이미지에 적용할 원(zone) 집합을 레시피로 불러오거나 새로 만들어 메인 탭에
반영한다. 2026-08-30에 삭제된 `circle_detect_preview_dialog.py`(오프라인 원 검출
테스트)와 동일한 "임베디드 ZoneCanvas + 라운드트립 적용" 골격을 재사용하되,
목적은 '오프라인 테스트'가 아니라 '레시피 관리'로 바뀐다.
"""
import time

import numpy as np
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSlider,
    QComboBox, QLineEdit, QMessageBox,
)
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtCore import Qt

from app.core.circle_detector import detect_circles
from app.core.zone_metrics import scale_circles
from app.core import zone_recipe_store as recipe_store
from app.widgets.zone_canvas import ZoneCanvas
from app.core.logger import get_logger

log = get_logger(__name__)


def _qpixmap_to_bgr(pixmap: QPixmap) -> np.ndarray:
    """`annotation_canvas._apply_channel_filter()`와 동일한 QPixmap -> numpy 변환
    패턴 재사용(RGB888로 변환 후 stride 보정 reshape), RGB -> BGR만 뒤집는다."""
    qimg = pixmap.toImage().convertToFormat(QImage.Format.Format_RGB888)
    w, h = qimg.width(), qimg.height()
    ptr = qimg.bits()
    ptr.setsize(qimg.sizeInBytes())
    stride = qimg.bytesPerLine()
    rgb = (np.frombuffer(ptr, dtype=np.uint8)
           .reshape(h, stride)[:, :w * 3]
           .reshape(h, w, 3).copy())
    return rgb[:, :, ::-1].copy()


class ZoneRecipeDialog(QDialog):
    """레시피를 불러오거나 새로 만들어 "메인 탭에 적용"할 원 집합을 확정하는
    모달 팝업. 메인 탭의 현재 로드된 이미지(원본 스케일 pixmap은 너무 무거워
    이미 만들어둔 미리보기 pixmap)를 기준 이미지로 그대로 받는다."""

    def __init__(self, reference_pixmap: QPixmap, ref_size: tuple[int, int], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("영역(Zone) 설정 — 레시피")
        self._ref_pixmap = reference_pixmap
        self._ref_size = ref_size   # (w, h) 원본 이미지 픽셀 크기
        self._recipe_paths: list = []
        self._result_circles: list[tuple[float, float, float]] = []
        self._build_ui()
        self._load_most_recent()

    def _build_ui(self) -> None:
        self.resize(760, 720)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        title = QLabel("영역(Zone) 설정 — 레시피 불러오기/새로 만들기")
        title.setStyleSheet("font-size:14px; font-weight:bold;")
        root.addWidget(title)

        self._canvas = ZoneCanvas()
        self._canvas.setMinimumHeight(420)
        self._canvas.set_image_size(*self._ref_size)
        self._canvas.set_pixmap(self._ref_pixmap)
        root.addWidget(self._canvas, stretch=1)

        self._lbl_stats = QLabel("원 개수: 0")
        self._lbl_stats.setStyleSheet("color:#e5e7eb;")
        root.addWidget(self._lbl_stats)

        detect_row = QHBoxLayout()
        detect_row.addWidget(QLabel("민감도:"))
        self._sensitivity_slider = QSlider(Qt.Orientation.Horizontal)
        self._sensitivity_slider.setRange(0, 100)
        self._sensitivity_slider.setValue(50)
        detect_row.addWidget(self._sensitivity_slider, stretch=1)
        self._lbl_sensitivity = QLabel("50%")
        self._lbl_sensitivity.setFixedWidth(36)
        detect_row.addWidget(self._lbl_sensitivity)
        self._btn_detect = QPushButton("자동 검출")
        detect_row.addWidget(self._btn_detect)
        self._btn_align = QPushButton("정렬(중심 맞추기)")
        detect_row.addWidget(self._btn_align)
        self._btn_undo = QPushButton("Undo")
        detect_row.addWidget(self._btn_undo)
        root.addLayout(detect_row)

        recipe_row = QHBoxLayout()
        recipe_row.addWidget(QLabel("레시피:"))
        self._recipe_combo = QComboBox()
        self._recipe_combo.setMinimumWidth(160)
        recipe_row.addWidget(self._recipe_combo, stretch=1)
        self._btn_load_recipe = QPushButton("불러오기")
        recipe_row.addWidget(self._btn_load_recipe)
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("레시피 이름")
        recipe_row.addWidget(self._name_edit, stretch=1)
        self._btn_save_recipe = QPushButton("저장")
        recipe_row.addWidget(self._btn_save_recipe)
        root.addLayout(recipe_row)

        bottom_row = QHBoxLayout()
        bottom_row.addStretch()
        self._btn_cancel = QPushButton("취소")
        bottom_row.addWidget(self._btn_cancel)
        self._btn_apply = QPushButton("메인 탭에 적용")
        self._btn_apply.setStyleSheet("font-weight:bold;")
        self._btn_apply.setEnabled(False)
        bottom_row.addWidget(self._btn_apply)
        root.addLayout(bottom_row)

        self._sensitivity_slider.valueChanged.connect(
            lambda v: self._lbl_sensitivity.setText(f"{v}%")
        )
        self._btn_detect.clicked.connect(self._on_detect)
        self._btn_align.clicked.connect(self._canvas.align_centers)
        self._btn_undo.clicked.connect(self._canvas.undo)
        self._btn_load_recipe.clicked.connect(self._on_load_recipe)
        self._btn_save_recipe.clicked.connect(self._on_save_recipe)
        self._btn_cancel.clicked.connect(self.reject)
        self._btn_apply.clicked.connect(self._on_apply)
        self._canvas.circles_changed.connect(self._on_circles_changed)

        self._refresh_recipe_list()

    # ── 레시피 목록/로드/저장 ────────────────────────────────────────────────

    def _refresh_recipe_list(self) -> None:
        self._recipe_paths = recipe_store.list_recipes()
        self._recipe_combo.clear()
        for path in self._recipe_paths:
            recipe = recipe_store.load_recipe(path)
            label = recipe["name"] if recipe else path.stem
            self._recipe_combo.addItem(label)

    def _load_most_recent(self) -> None:
        """다이얼로그 오픈 시 가장 최근(mtime) 레시피를 자동 로드 — 없으면 빈
        캔버스로 시작."""
        paths = recipe_store.list_recipes()
        if not paths:
            return
        recipe = recipe_store.load_recipe(paths[0])
        if recipe is None:
            return
        scaled = scale_circles(recipe["circles"], recipe["ref_size"], self._ref_size)
        self._canvas.set_circles(scaled)
        self._name_edit.setText(recipe["name"])

    def _on_load_recipe(self) -> None:
        idx = self._recipe_combo.currentIndex()
        if not (0 <= idx < len(self._recipe_paths)):
            return
        path = self._recipe_paths[idx]
        recipe = recipe_store.load_recipe(path)
        if recipe is None:
            QMessageBox.warning(self, "불러오기 실패", "레시피 파일을 읽을 수 없습니다.")
            return
        scaled = scale_circles(recipe["circles"], recipe["ref_size"], self._ref_size)
        self._canvas.set_circles(scaled)
        self._name_edit.setText(recipe["name"])
        recipe_store.touch_recipe(path)   # "최근 사용"에도 반영

    def _on_save_recipe(self) -> None:
        name = self._name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "이름 없음", "레시피 이름을 입력하세요.")
            return
        circles = self._canvas.get_circles()
        if not circles:
            QMessageBox.warning(self, "원 없음", "저장할 원이 없습니다.")
            return
        try:
            recipe_store.save_recipe(name, circles, self._ref_size)
        except OSError as exc:
            QMessageBox.critical(self, "저장 실패", str(exc))
            return
        self._refresh_recipe_list()
        QMessageBox.information(self, "저장 완료", f"'{name}' 레시피를 저장했습니다.")

    # ── 자동 검출/정렬/적용 ──────────────────────────────────────────────────

    def _on_detect(self) -> None:
        sensitivity = self._sensitivity_slider.value() / 100.0
        bgr = _qpixmap_to_bgr(self._ref_pixmap)
        start = time.perf_counter()
        try:
            circles = detect_circles(bgr, sensitivity=sensitivity)
        except Exception as exc:
            log.exception("Zone 레시피 다이얼로그 — 자동 검출 실패")
            QMessageBox.critical(self, "자동 검출 오류", str(exc))
            return
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        pixmap_size = (self._ref_pixmap.width(), self._ref_pixmap.height())
        scaled = scale_circles(circles, pixmap_size, self._ref_size)
        self._canvas.set_circles(scaled)
        self._lbl_stats.setText(f"원 개수: {len(scaled)}    검출 소요시간: {elapsed_ms:.0f}ms")

    def _on_circles_changed(self) -> None:
        count = len(self._canvas.get_circles())
        self._lbl_stats.setText(f"원 개수: {count}")
        self._btn_apply.setEnabled(count >= 1)

    def _on_apply(self) -> None:
        self._result_circles = self._canvas.get_circles()
        self.accept()

    # ── 결과 조회 (호출부가 exec() 후 사용) ─────────────────────────────────

    def result_circles(self) -> list[tuple[float, float, float]]:
        return self._result_circles

    def result_ref_size(self) -> tuple[int, int]:
        return self._ref_size
