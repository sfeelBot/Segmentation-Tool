"""라벨링된 데이터만 상대좌표(0~1 정규화)로 내보내기."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
from PIL import Image
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QComboBox, QFileDialog, QGroupBox, QProgressBar,
    QMessageBox,
)

from app.core import project as _project
from app.core.annotation_store import load as load_annotations, load_classes, rle_encode
from app.core.i18n import t
from app.core.logger import get_logger

log = get_logger(__name__)

SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"}


class ExportWorker(QThread):
    """내보내기 파일 I/O 루프를 백그라운드에서 실행 — UI 스레드 비블로킹.
    run() 안에서는 QWidget을 절대 건드리지 않는다(순수 파일 I/O만)."""
    progress = pyqtSignal(int, int, str)   # current, total, filename
    finished = pyqtSignal(int)             # exported count
    error    = pyqtSignal(str)

    def __init__(
        self, out_dir: Path, fmt: str, pairs: list[tuple[Path, list]],
        include_imgs: bool, relative: bool,
    ) -> None:
        super().__init__()
        self._out_dir      = out_dir
        self._fmt          = fmt
        self._pairs        = pairs
        self._include_imgs = include_imgs
        self._relative     = relative

    def run(self) -> None:
        try:
            self._out_dir.mkdir(parents=True, exist_ok=True)
            if self._fmt == "json":
                self._export_json(self._pairs, self._include_imgs, self._relative)
            elif self._fmt == "yolo":
                self._export_yolo(self._pairs, self._include_imgs)   # YOLO는 항상 상대좌표
            elif self._fmt == "coco":
                self._export_coco(self._pairs, self._include_imgs, self._relative)
            self.finished.emit(len(self._pairs))
        except Exception as e:
            log.exception("내보내기 실패")
            self.error.emit(str(e))

    # ── 포맷별 ────────────────────────────────────────────────────────────────

    def _export_json(self, pairs, include_images: bool, relative: bool) -> None:
        classes = [
            {"class_id": c.class_id, "name": c.name, "color": list(c.color)}
            for c in load_classes()
        ]
        (self._out_dir / "classes.json").write_text(
            json.dumps(classes, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        ann_dir = self._out_dir / "annotations"
        ann_dir.mkdir(exist_ok=True)
        img_out = self._out_dir / "images"
        if include_images:
            img_out.mkdir(exist_ok=True)

        for i, (img_path, anns) in enumerate(pairs, 1):
            w, h = _image_size(img_path)
            ann_list = []
            for a in anns:
                if a.type == "polygon":
                    pts = _norm_points(a.points, w, h) if relative else [[float(x), float(y)] for x, y in a.points]
                    ann_list.append({
                        "annotation_id": a.annotation_id,
                        "class_id": a.class_id,
                        "type": "polygon",
                        "order": a.order,
                        "points": pts,
                        "coords": "relative" if relative else "absolute",
                    })
                elif a.type == "brush_mask" and a.mask is not None:
                    ann_list.append({
                        "annotation_id": a.annotation_id,
                        "class_id": a.class_id,
                        "type": "brush_mask",
                        "order": a.order,
                        "width": a.width, "height": a.height,
                        "rle": rle_encode(a.mask),
                    })
            doc = {
                "version": "1.0",
                "image": img_path.name,
                "width": w, "height": h,
                "coords": "relative" if relative else "absolute",
                "annotations": ann_list,
            }
            (ann_dir / f"{img_path.stem}.json").write_text(
                json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8",
            )
            if include_images:
                shutil.copy2(img_path, img_out / img_path.name)
            self.progress.emit(i, len(pairs), img_path.name)

    def _export_yolo(self, pairs, include_images: bool) -> None:
        """YOLO segmentation 포맷: `class_id x1 y1 x2 y2 … xn yn` (모두 0~1 상대좌표).
        brush_mask 는 외곽 컨투어를 폴리곤으로 변환해서 저장."""
        import cv2

        (self._out_dir / "classes.txt").write_text(
            "\n".join(c.name for c in load_classes() if c.class_id != 0),
            encoding="utf-8",
        )
        lbl_dir = self._out_dir / "labels"
        lbl_dir.mkdir(exist_ok=True)
        img_out = self._out_dir / "images"
        if include_images:
            img_out.mkdir(exist_ok=True)

        for i, (img_path, anns) in enumerate(pairs, 1):
            w, h = _image_size(img_path)
            lines: list[str] = []
            for a in anns:
                cid = a.class_id - 1   # YOLO 는 0-index, 우리는 0=background 이므로 -1
                if cid < 0:
                    continue
                if a.type == "polygon" and len(a.points) >= 3:
                    flat = []
                    for x, y in a.points:
                        flat.extend([f"{x/w:.6f}", f"{y/h:.6f}"])
                    lines.append(f"{cid} " + " ".join(flat))
                elif a.type == "brush_mask" and a.mask is not None:
                    contours, _ = cv2.findContours(
                        a.mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
                    )
                    for c in contours:
                        if len(c) < 3:
                            continue
                        flat = []
                        for pt in c[:, 0, :]:
                            flat.extend([f"{pt[0]/w:.6f}", f"{pt[1]/h:.6f}"])
                        lines.append(f"{cid} " + " ".join(flat))
            (lbl_dir / f"{img_path.stem}.txt").write_text(
                "\n".join(lines), encoding="utf-8",
            )
            if include_images:
                shutil.copy2(img_path, img_out / img_path.name)
            self.progress.emit(i, len(pairs), img_path.name)

    def _export_coco(self, pairs, include_images: bool, relative: bool) -> None:
        """COCO segmentation 포맷. relative=True 일 경우 segmentation 좌표만 0~1."""
        import cv2

        classes = load_classes()
        categories = [
            {"id": c.class_id, "name": c.name}
            for c in classes if c.class_id != 0
        ]

        images = []
        annotations = []
        ann_id = 1

        img_out = self._out_dir / "images"
        if include_images:
            img_out.mkdir(exist_ok=True)

        for i, (img_path, anns) in enumerate(pairs, 1):
            w, h = _image_size(img_path)
            images.append({
                "id": i, "file_name": img_path.name,
                "width": w, "height": h,
            })
            for a in anns:
                if a.class_id == 0:
                    continue
                seg: list = []
                bbox: list[float] = []
                area = 0.0
                if a.type == "polygon" and len(a.points) >= 3:
                    if relative:
                        flat = [v for x, y in a.points for v in (x / w, y / h)]
                    else:
                        flat = [v for x, y in a.points for v in (x, y)]
                    seg = [flat]
                    xs = [p[0] for p in a.points]
                    ys = [p[1] for p in a.points]
                    bx, by = min(xs), min(ys)
                    bw, bh = max(xs) - bx, max(ys) - by
                    bbox = [bx / w, by / h, bw / w, bh / h] if relative else [bx, by, bw, bh]
                    area = float(bw * bh)
                elif a.type == "brush_mask" and a.mask is not None:
                    contours, _ = cv2.findContours(
                        a.mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
                    )
                    for c in contours:
                        if len(c) < 3:
                            continue
                        if relative:
                            flat = [v for pt in c[:, 0, :] for v in (pt[0] / w, pt[1] / h)]
                        else:
                            flat = [float(v) for pt in c[:, 0, :] for v in (pt[0], pt[1])]
                        seg.append(flat)
                    ys, xs = np.where(a.mask > 0)
                    if len(xs):
                        bx, by = float(xs.min()), float(ys.min())
                        bw, bh = float(xs.max() - bx), float(ys.max() - by)
                        bbox = [bx / w, by / h, bw / w, bh / h] if relative else [bx, by, bw, bh]
                        area = float(a.mask.sum())
                if seg:
                    annotations.append({
                        "id": ann_id, "image_id": i,
                        "category_id": a.class_id,
                        "segmentation": seg,
                        "bbox": bbox,
                        "area": area,
                        "iscrowd": 0,
                    })
                    ann_id += 1
            if include_images:
                shutil.copy2(img_path, img_out / img_path.name)
            self.progress.emit(i, len(pairs), img_path.name)

        (self._out_dir / "annotations.json").write_text(
            json.dumps({
                "info": {
                    "description": _project.current().name if _project.current() else "",
                    "coords": "relative" if relative else "absolute",
                },
                "images": images,
                "annotations": annotations,
                "categories": categories,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


class ExportDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("export.title"))
        self.setMinimumWidth(520)
        self._out_dir: Path | None = None
        self._worker: ExportWorker | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(16, 16, 16, 16)

        # 옵션 박스
        box = QGroupBox(t("export.title"))
        lay = QVBoxLayout(box)

        self._chk_labeled = QCheckBox(t("export.labeled_only"))
        self._chk_labeled.setChecked(True)
        lay.addWidget(self._chk_labeled)

        self._chk_images  = QCheckBox(t("export.include_images"))
        self._chk_images.setChecked(True)
        lay.addWidget(self._chk_images)

        self._chk_relative = QCheckBox(t("export.relative_coords"))
        self._chk_relative.setChecked(True)
        lay.addWidget(self._chk_relative)

        rel_hint = QLabel(t("export.relative_coords.hint"))
        rel_hint.setStyleSheet("color:#9ca3af; font-size:11px; margin-left:20px;")
        rel_hint.setWordWrap(True)
        lay.addWidget(rel_hint)

        fmt_row = QHBoxLayout()
        fmt_row.addWidget(QLabel(t("export.format") + ":"))
        self._combo_fmt = QComboBox()
        self._combo_fmt.addItem("JSON (프로젝트 포맷)", "json")
        self._combo_fmt.addItem("YOLO-seg (polygon txt)", "yolo")
        self._combo_fmt.addItem("COCO (segmentation)", "coco")
        fmt_row.addWidget(self._combo_fmt, stretch=1)
        lay.addLayout(fmt_row)

        # 출력 폴더
        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("출력 폴더:"))
        self._lbl_out = QLabel("—")
        self._lbl_out.setStyleSheet("color:#60a5fa;")
        out_row.addWidget(self._lbl_out, stretch=1)
        btn_pick = QPushButton(t("export.choose_dir"))
        btn_pick.clicked.connect(self._on_pick_dir)
        out_row.addWidget(btn_pick)
        lay.addLayout(out_row)

        root.addWidget(box)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.hide()
        root.addWidget(self._progress)

        self._lbl_status = QLabel("")
        self._lbl_status.setStyleSheet("color:#9ca3af;")
        root.addWidget(self._lbl_status)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._btn_close = QPushButton(t("common.close"))
        self._btn_close.clicked.connect(self.reject)
        self._btn_run   = QPushButton(t("export.run"))
        self._btn_run.setStyleSheet("background:#065f46; font-weight:bold;")
        self._btn_run.clicked.connect(self._on_run)
        btn_row.addWidget(self._btn_close)
        btn_row.addWidget(self._btn_run)
        root.addLayout(btn_row)

    # ── 슬롯 ─────────────────────────────────────────────────────────────────

    def _on_pick_dir(self) -> None:
        start = str((_project.current().path if _project.current() else Path.home()))
        d = QFileDialog.getExistingDirectory(self, t("export.choose_dir"), start)
        if d:
            self._out_dir = Path(d)
            self._lbl_out.setText(str(self._out_dir))

    def _on_run(self) -> None:
        if self._out_dir is None:
            QMessageBox.warning(self, t("export.title"), t("export.choose_dir"))
            return

        labeled_only = self._chk_labeled.isChecked()
        include_imgs = self._chk_images.isChecked()
        relative     = self._chk_relative.isChecked()
        fmt          = self._combo_fmt.currentData()

        img_dir = _project.images_dir()
        pairs: list[tuple[Path, list]] = []
        for p in sorted(img_dir.iterdir()):
            if p.suffix.lower() not in SUPPORTED_EXTS:
                continue
            anns = load_annotations(p)
            if labeled_only and not anns:
                continue
            pairs.append((p, anns))

        if not pairs:
            QMessageBox.information(self, t("export.title"), t("export.no_data"))
            return

        self._progress.show()
        self._progress.setMaximum(len(pairs))
        self._progress.setValue(0)
        self._lbl_status.setText("")
        self._btn_run.setEnabled(False)
        self._btn_close.setEnabled(False)

        self._worker = ExportWorker(self._out_dir, fmt, pairs, include_imgs, relative)
        self._worker.progress.connect(self._on_worker_progress)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.error.connect(self._on_worker_error)
        self._worker.start()

    def _on_worker_progress(self, current: int, total: int, filename: str) -> None:
        self._progress.setValue(current)
        self._lbl_status.setText(f"{current} / {total}  {filename}")

    def _on_worker_finished(self, count: int) -> None:
        self._progress.hide()
        self._btn_run.setEnabled(True)
        self._btn_close.setEnabled(True)
        log.info(f"내보내기 완료 — {count}개 → {self._out_dir}")
        QMessageBox.information(
            self, t("export.title"),
            t("export.done").format(n=count),
        )
        self.accept()

    def _on_worker_error(self, message: str) -> None:
        self._progress.hide()
        self._btn_run.setEnabled(True)
        self._btn_close.setEnabled(True)
        QMessageBox.critical(self, t("export.failed"), message)


# ── 헬퍼 ─────────────────────────────────────────────────────────────────────

def _image_size(path: Path) -> tuple[int, int]:
    with Image.open(str(path)) as im:
        return im.width, im.height


def _norm_points(points, w: int, h: int) -> list[list[float]]:
    return [[float(x) / w, float(y) / h] for x, y in points]
