"""오프라인 원 검출 테스트 팝업 — 체크포인트 없이 이미지만으로
`circle_detector.detect_circles()`를 미리보고 민감도를 튜닝하는 독립 다이얼로그.

`app.core.project`/체크포인트/모델 관련 import가 전혀 없는 완전 독립 도구다
(스펙 docs/specs/zone-analysis-tab-features-2026-08-26.md 판단 A, R-A 범위).
메인 탭(`ZoneAnalysisTab`)의 상태(로드된 이미지/체크포인트/추론결과)와는 완전히
분리되어 있다 — 이 다이얼로그에서 연 이미지는 메인 탭에 아무 영향도 주지 않는다.

미리보기·편집은 `ZoneCanvas`를 그대로 재사용한다(원 렌더링/드래그 이동/반지름
조절/추가/삭제가 전부 공짜로 딸려옴, 신규 캔버스 작성 금지 — 스펙 판단 A).
"""
import time
from pathlib import Path

import numpy as np
from PIL import Image
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFileDialog, QSlider,
)
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtCore import Qt

from app.core.circle_detector import detect_circles
from app.widgets.zone_canvas import ZoneCanvas
from app.core.logger import get_logger

log = get_logger(__name__)


def _rgb_to_qpixmap(rgb: np.ndarray) -> QPixmap:
    """플레인 RGB numpy 배열을 QPixmap으로 변환하는 단순 표시 헬퍼 — 신규 "검출"
    로직이 아니라 auto_label_preview_dialog._pil_to_qpixmap()과 동일한 패턴."""
    rgb = np.ascontiguousarray(rgb)
    h, w, _ = rgb.shape
    qimg = QImage(rgb.data, w, h, w * 3, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(qimg.copy())


# 미리보기 픽스맵 다운스케일 기준 — circle_detector._MAX_DETECT_DIM과 동일 값
# (화면에 보이는 스케일과 검출 파이프라인 내부 스케일을 맞추는 것뿐, 좌표 정확성과는
# 무관 — detect_circles()는 항상 넘겨받은 배열 스케일로 좌표를 되돌려준다).
_PREVIEW_MAX_DIM = 2048


class CircleDetectPreviewDialog(QDialog):
    """체크포인트 없이 이미지만으로 원 검출 알고리즘을 확인·튜닝하는 모달 팝업."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("오프라인 원 검출 테스트")
        self._image_path: Path | None = None
        self._rgb_full: np.ndarray | None = None   # 원본 스케일 RGB — detect_circles 입력용
        self._orig_size: tuple[int, int] = (0, 0)   # (w, h)
        self._build_ui()

    def _build_ui(self) -> None:
        self.resize(760, 720)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        header_row = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title = QLabel("오프라인 원 검출 테스트")
        title.setStyleSheet("font-size:15px; font-weight:bold;")
        subtitle = QLabel("체크포인트 없이 이미지만으로 검출 알고리즘을 확인·튜닝합니다")
        subtitle.setStyleSheet("color:#9ca3af;")
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        header_row.addLayout(title_col, stretch=1)
        btn_close_x = QPushButton("✕")
        btn_close_x.setFixedWidth(28)
        btn_close_x.setToolTip("닫기")
        header_row.addWidget(btn_close_x, alignment=Qt.AlignmentFlag.AlignTop)
        root.addLayout(header_row)

        file_row = QHBoxLayout()
        self._btn_open = QPushButton("이미지 열기…")
        self._lbl_file = QLabel("선택된 이미지 없음")
        self._lbl_file.setStyleSheet("color:#9ca3af;")
        file_row.addWidget(self._btn_open)
        file_row.addWidget(self._lbl_file, stretch=1)
        root.addLayout(file_row)

        self._canvas = ZoneCanvas()
        self._canvas.setMinimumHeight(420)
        root.addWidget(self._canvas, stretch=1)

        self._lbl_stats = QLabel("검출 개수: -    소요시간: -")
        self._lbl_stats.setStyleSheet("color:#e5e7eb;")
        root.addWidget(self._lbl_stats)

        sens_row = QHBoxLayout()
        sens_row.addWidget(QLabel("민감도:"))
        self._sensitivity_slider = QSlider(Qt.Orientation.Horizontal)
        self._sensitivity_slider.setRange(0, 100)
        self._sensitivity_slider.setValue(50)
        sens_row.addWidget(self._sensitivity_slider, stretch=1)
        self._lbl_sensitivity = QLabel("50%")
        self._lbl_sensitivity.setFixedWidth(36)
        sens_row.addWidget(self._lbl_sensitivity)
        self._btn_redetect = QPushButton("다시 검출")
        self._btn_redetect.setEnabled(False)
        sens_row.addWidget(self._btn_redetect)
        root.addLayout(sens_row)

        bottom_row = QHBoxLayout()
        bottom_row.addStretch()
        self._btn_close = QPushButton("닫기")
        bottom_row.addWidget(self._btn_close)
        root.addLayout(bottom_row)

        self._btn_open.clicked.connect(self._on_open_image)
        self._sensitivity_slider.valueChanged.connect(
            lambda v: self._lbl_sensitivity.setText(f"{v}%")
        )
        self._btn_redetect.clicked.connect(self._on_redetect)
        self._btn_close.clicked.connect(self.close)
        btn_close_x.clicked.connect(self.close)

    # ── 슬롯 ─────────────────────────────────────────────────────────────────

    def _on_open_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "이미지 선택", "",
            "Images (*.jpg *.jpeg *.png *.bmp *.tiff *.tif)"
        )
        if not path:
            return
        self._image_path = Path(path)
        try:
            with Image.open(str(self._image_path)) as im:
                rgb_im = im.convert("RGB")
                self._orig_size = rgb_im.size   # (w, h)
                self._rgb_full = np.array(rgb_im)
        except Exception as exc:
            log.exception(f"오프라인 원 검출 테스트 — 이미지 로드 실패: {self._image_path}")
            self._lbl_stats.setText(f"이미지 로드 실패: {exc}")
            self._rgb_full = None
            self._btn_redetect.setEnabled(False)
            return

        self._lbl_file.setText(self._image_path.name)
        self._lbl_file.setStyleSheet("color:#e5e7eb;")

        preview_im = Image.fromarray(self._rgb_full)
        preview_im.thumbnail((_PREVIEW_MAX_DIM, _PREVIEW_MAX_DIM), Image.BILINEAR)
        self._canvas.set_image_size(*self._orig_size)
        self._canvas.set_pixmap(_rgb_to_qpixmap(np.array(preview_im)))
        self._canvas.clear_circles()
        self._btn_redetect.setEnabled(True)
        self._lbl_stats.setText("검출 개수: -    소요시간: -")
        self._on_redetect()

    def _on_redetect(self) -> None:
        if self._rgb_full is None:
            return
        sensitivity = self._sensitivity_slider.value() / 100.0
        bgr = self._rgb_full[:, :, ::-1].copy()
        start = time.perf_counter()
        try:
            circles = detect_circles(bgr, sensitivity=sensitivity)
        except Exception as exc:
            log.exception("오프라인 원 검출 테스트 — 검출 실패")
            self._lbl_stats.setText(f"검출 실패: {exc}")
            return
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        self._canvas.set_circles(circles)
        self._lbl_stats.setText(f"검출 개수: {len(circles)}    소요시간: {elapsed_ms:.0f}ms")
