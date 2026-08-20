"""오토 라벨링 결과 미리보기 — 샘플 몇 장을 그리드로 보여주고 '합치기' 확인."""
from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

import numpy as np
from PIL import Image
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QScrollArea, QWidget, QFrame, QGroupBox,
)
from PyQt6.QtGui import QImage, QPixmap, QColor, QFont
from PyQt6.QtCore import Qt, QSize

from app.core.annotation_store import load_classes, ClassDef


# 결과 튜플 타입: (이미지 경로, 어노테이션 리스트, w, h)
ResultTuple = Tuple[Path, list, int, int]

# 미리보기 썸네일 크기
THUMB_W, THUMB_H = 260, 180
# 한 번에 보여줄 최대 샘플 수
MAX_SAMPLES = 9
OVERLAY_ALPHA = 0.5


class AutoLabelPreviewDialog(QDialog):
    def __init__(self, results: List[ResultTuple], parent=None) -> None:
        super().__init__(parent)
        self._results = results
        self.setWindowTitle("오토 라벨링 미리보기")
        self.setMinimumSize(900, 680)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        # ── 요약 ─────────────────────────────────────────────────────────────
        title = QLabel("오토 라벨링 결과 미리보기")
        tf = QFont(); tf.setBold(True); tf.setPointSize(14)
        title.setFont(tf)
        title.setStyleSheet("color:#60a5fa;")
        root.addWidget(title)

        n_total = len(self._results)
        n_with_ann = sum(1 for _, anns, _, _ in self._results if anns)
        n_shown = min(MAX_SAMPLES, n_total)
        summary = QLabel(
            f"전체 <b>{n_total}</b>개 이미지에 어노테이션이 생성되었습니다. "
            f"(그 중 <b>{n_with_ann}</b>개에는 객체 포함)<br>"
            f"아래는 무작위로 선별된 <b>{n_shown}</b>개 샘플입니다. "
            f"확인 후 '합치기'를 누르면 프로젝트에 저장됩니다."
        )
        summary.setStyleSheet("color:#cbd5e1; font-size:12px;")
        summary.setWordWrap(True)
        root.addWidget(summary)

        # ── 샘플 그리드 ──────────────────────────────────────────────────────
        classes = load_classes()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        grid_w = QWidget()
        grid = QGridLayout(grid_w)
        grid.setSpacing(8)

        samples = self._pick_samples(self._results, MAX_SAMPLES)
        for idx, (path, anns, w, h) in enumerate(samples):
            tile = self._make_tile(path, anns, w, h, classes)
            grid.addWidget(tile, idx // 3, idx % 3)

        scroll.setWidget(grid_w)
        root.addWidget(scroll, stretch=1)

        # ── 클래스 범례 ──────────────────────────────────────────────────────
        legend = QHBoxLayout()
        legend.setContentsMargins(0, 0, 0, 0)
        legend.addWidget(QLabel("범례:"))
        for c in classes:
            if c.class_id == 0:
                continue
            sw = QLabel()
            sw.setFixedSize(14, 14)
            sw.setStyleSheet(
                f"background: rgb({c.color[0]},{c.color[1]},{c.color[2]}); "
                f"border:1px solid #555; border-radius:3px;"
            )
            legend.addWidget(sw)
            lab = QLabel(c.name)
            lab.setStyleSheet("color:#cbd5e1; margin-right:12px;")
            legend.addWidget(lab)
        legend.addStretch()
        root.addLayout(legend)

        # ── 버튼 ─────────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._btn_cancel = QPushButton("취소 (결과 버리기)")
        self._btn_commit = QPushButton("합치기 — 프로젝트에 저장")
        self._btn_commit.setStyleSheet(
            "background:#065f46; font-weight:bold; padding:8px 18px; font-size:13px;"
        )
        self._btn_cancel.clicked.connect(self.reject)
        self._btn_commit.clicked.connect(self.accept)
        btn_row.addWidget(self._btn_cancel)
        btn_row.addWidget(self._btn_commit)
        root.addLayout(btn_row)

    # ── 내부 ─────────────────────────────────────────────────────────────────

    def _pick_samples(self, results, n):
        """어노테이션이 있는 이미지 우선으로 최대 n 개 선택."""
        with_ann = [r for r in results if r[1]]
        without  = [r for r in results if not r[1]]
        # 앞·중간·뒤에서 골고루 고르기
        picks = []
        if with_ann:
            step = max(1, len(with_ann) // n)
            picks = with_ann[::step][:n]
        if len(picks) < n and without:
            picks += without[: n - len(picks)]
        return picks[:n]

    def _make_tile(self, path: Path, anns: list, w: int, h: int,
                   classes: list[ClassDef]) -> QWidget:
        tile = QFrame()
        tile.setFrameStyle(QFrame.Shape.Box)
        tile.setStyleSheet(
            "QFrame { background:#1a1f27; border:1px solid #374151; border-radius:6px; }"
            "QLabel { border:none; background:transparent; }"
        )
        v = QVBoxLayout(tile)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(3)

        pixmap = self._render_preview(path, anns, classes)
        img_lbl = QLabel()
        img_lbl.setPixmap(pixmap)
        img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        img_lbl.setMinimumSize(THUMB_W, THUMB_H)
        v.addWidget(img_lbl)

        name_lbl = QLabel(path.name)
        name_lbl.setStyleSheet("color:#e5e7eb; font-size:11px;")
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(name_lbl)

        if anns:
            per_class: dict[int, int] = {}
            for a in anns:
                per_class[a.class_id] = per_class.get(a.class_id, 0) + 1
            cls_names = {c.class_id: c.name for c in classes}
            parts = [f"{cls_names.get(cid, f'#{cid}')}:{n}"
                     for cid, n in sorted(per_class.items())]
            info = QLabel("  ·  ".join(parts))
            info.setStyleSheet("color:#93c5fd; font-size:10px;")
        else:
            info = QLabel("어노테이션 없음")
            info.setStyleSheet("color:#6b7280; font-size:10px;")
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(info)

        return tile

    def _render_preview(self, img_path: Path, anns: list,
                        classes: list[ClassDef]) -> QPixmap:
        """원본 이미지에 어노테이션 오버레이를 합성해 썸네일로 반환."""
        cls_color = {c.class_id: c.color for c in classes}
        try:
            img = Image.open(str(img_path)).convert("RGB")
        except Exception:
            # 이미지 로드 실패 시 회색 썸네일
            blank = QPixmap(THUMB_W, THUMB_H)
            blank.fill(QColor("#2a2f38"))
            return blank

        arr = np.array(img, dtype=np.float32)
        overlay = np.zeros_like(arr)
        mask_union = np.zeros(arr.shape[:2], dtype=bool)

        for ann in anns:
            if ann.type == "brush_mask" and ann.mask is not None:
                color = cls_color.get(ann.class_id, (200, 200, 200))
                if ann.mask.shape != arr.shape[:2]:
                    continue
                m = ann.mask.astype(bool)
                overlay[m] = color
                mask_union |= m
            elif ann.type == "polygon" and len(ann.points) >= 3:
                color = cls_color.get(ann.class_id, (200, 200, 200))
                from PIL import ImageDraw
                poly_mask = Image.new("L", img.size, 0)
                ImageDraw.Draw(poly_mask).polygon(
                    [(float(x), float(y)) for x, y in ann.points], fill=1
                )
                pm = np.array(poly_mask, dtype=bool)
                overlay[pm] = color
                mask_union |= pm

        if mask_union.any():
            arr[mask_union] = (
                arr[mask_union] * (1 - OVERLAY_ALPHA) + overlay[mask_union] * OVERLAY_ALPHA
            )
        blended = Image.fromarray(arr.astype(np.uint8))
        blended.thumbnail((THUMB_W, THUMB_H), Image.BILINEAR)
        return _pil_to_qpixmap(blended)


def _pil_to_qpixmap(img: Image.Image) -> QPixmap:
    if img.mode != "RGB":
        img = img.convert("RGB")
    arr = np.ascontiguousarray(np.array(img))
    h, w, _ = arr.shape
    qimg = QImage(arr.data, w, h, w * 3, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(qimg.copy())
