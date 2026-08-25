"""export_dialog.py(JSON 포맷)로 내보낸 어노테이션 데이터를 현재 프로젝트로 가져오기."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import cv2
from PIL import Image
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QRadioButton, QButtonGroup, QFileDialog, QGroupBox,
    QProgressBar, QMessageBox,
)

from app.core import project as _project
from app.core.annotation_store import (
    AnnotationItem, ClassDef, load as load_annotations, load_classes,
    save as save_annotations, save_classes, rle_decode, new_id,
)
from app.core.i18n import t
from app.core.logger import get_logger

log = get_logger(__name__)


class ImportAnnotationDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("import_ann.title"))
        self.setMinimumWidth(520)
        self._in_dir: Path | None = None
        self.imported_any = False
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(16, 16, 16, 16)

        box = QGroupBox(t("import_ann.title"))
        lay = QVBoxLayout(box)

        # 입력 폴더
        in_row = QHBoxLayout()
        in_row.addWidget(QLabel(t("import_ann.choose_dir") + ":"))
        self._lbl_in = QLabel("—")
        self._lbl_in.setStyleSheet("color:#60a5fa;")
        in_row.addWidget(self._lbl_in, stretch=1)
        btn_pick = QPushButton(t("import_ann.choose_dir"))
        btn_pick.clicked.connect(self._on_pick_dir)
        in_row.addWidget(btn_pick)
        lay.addLayout(in_row)

        conflict_label = QLabel(t("import_ann.conflict"))
        lay.addWidget(conflict_label)
        self._rb_overwrite = QRadioButton(t("import_ann.conflict.overwrite"))
        self._rb_skip = QRadioButton(t("import_ann.conflict.skip"))
        self._rb_skip.setChecked(True)
        self._conflict_group = QButtonGroup(self)
        self._conflict_group.addButton(self._rb_overwrite)
        self._conflict_group.addButton(self._rb_skip)
        lay.addWidget(self._rb_overwrite)
        lay.addWidget(self._rb_skip)

        self._chk_new_images = QCheckBox(t("import_ann.include_new_images"))
        self._chk_new_images.setChecked(True)
        lay.addWidget(self._chk_new_images)

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
        self._btn_run = QPushButton(t("import_ann.run"))
        self._btn_run.setStyleSheet("background:#065f46; font-weight:bold;")
        self._btn_run.clicked.connect(self._on_run)
        btn_row.addWidget(self._btn_close)
        btn_row.addWidget(self._btn_run)
        root.addLayout(btn_row)

    # ── 슬롯 ─────────────────────────────────────────────────────────────────

    def _on_pick_dir(self) -> None:
        start = str((_project.current().path if _project.current() else Path.home()))
        d = QFileDialog.getExistingDirectory(self, t("import_ann.choose_dir"), start)
        if d:
            self._in_dir = Path(d)
            self._lbl_in.setText(str(self._in_dir))

    def _on_run(self) -> None:
        if self._in_dir is None:
            QMessageBox.warning(self, t("import_ann.title"), t("import_ann.choose_dir"))
            return

        ann_src_dir = self._in_dir / "annotations"
        if not ann_src_dir.is_dir():
            QMessageBox.critical(self, t("import_ann.title"), t("import_ann.invalid_dir"))
            return

        ann_files = sorted(ann_src_dir.glob("*.json"))
        if not ann_files:
            QMessageBox.information(self, t("import_ann.title"), t("import_ann.no_data"))
            return

        overwrite = self._rb_overwrite.isChecked()
        include_new_images = self._chk_new_images.isChecked()

        try:
            self._progress.show()
            self._progress.setMaximum(len(ann_files))
            self._progress.setValue(0)

            new_classes = self._merge_classes()

            imported = 0
            skipped_existing = 0
            skipped_missing = 0
            new_images = 0

            images_dir = _project.images_dir()
            src_images_dir = self._in_dir / "images"

            for i, ann_file in enumerate(ann_files, 1):
                self._progress.setValue(i)
                self._lbl_status.setText(f"{i} / {len(ann_files)}  {ann_file.name}")

                try:
                    doc = json.loads(ann_file.read_text(encoding="utf-8"))
                except Exception:
                    log.warning(f"어노테이션 JSON 파싱 실패 — 건너뜀: {ann_file}")
                    continue

                image_name = doc.get("image")
                if not image_name:
                    continue
                img_path = images_dir / image_name

                if not img_path.exists():
                    src_img = src_images_dir / image_name
                    if not (include_new_images and src_img.exists()):
                        skipped_missing += 1
                        continue
                    images_dir.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_img, img_path)
                    new_images += 1
                else:
                    existing = load_annotations(img_path)
                    if existing and not overwrite:
                        skipped_existing += 1
                        continue

                img_w, img_h = _image_size(img_path)
                items = _doc_to_items(doc, img_w, img_h)
                save_annotations(img_path, items, img_w, img_h)
                imported += 1

            log.info(
                f"어노테이션 가져오기 완료 — imported={imported}, "
                f"skipped_existing={skipped_existing}, skipped_missing={skipped_missing}, "
                f"new_images={new_images}, new_classes={new_classes}"
            )
            self.imported_any = imported > 0 or new_images > 0
            QMessageBox.information(
                self, t("import_ann.title"),
                t("import_ann.done").format(
                    imported=imported, skipped_existing=skipped_existing,
                    skipped_missing=skipped_missing, new_images=new_images,
                    new_classes=new_classes,
                ),
            )
            self.accept()
        except Exception as e:
            log.exception("어노테이션 가져오기 실패")
            QMessageBox.critical(self, t("import_ann.failed"), str(e))
        finally:
            self._progress.hide()

    def _merge_classes(self) -> int:
        """classes.json 을 읽어 로컬에 없는 class_id 만 추가. 새로 추가된 개수 반환."""
        classes_src = self._in_dir / "classes.json"
        if not classes_src.exists():
            return 0
        try:
            data = json.loads(classes_src.read_text(encoding="utf-8"))
        except Exception:
            log.warning(f"classes.json 파싱 실패 — 클래스 병합 건너뜀: {classes_src}")
            return 0

        local = load_classes()
        local_ids = {c.class_id for c in local}
        added = 0
        for c in data:
            if c["class_id"] in local_ids:
                continue
            local.append(ClassDef(
                class_id=c["class_id"], name=c["name"], color=tuple(c["color"]),
            ))
            local_ids.add(c["class_id"])
            added += 1
        if added:
            save_classes(sorted(local, key=lambda c: c.class_id))
        return added


# ── 헬퍼 ─────────────────────────────────────────────────────────────────────

def _image_size(path: Path) -> tuple[int, int]:
    with Image.open(str(path)) as im:
        return im.width, im.height


def _doc_to_items(doc: dict, img_w: int, img_h: int) -> list[AnnotationItem]:
    """export JSON 문서를 AnnotationItem 리스트로 변환 (절대좌표화 + 마스크 리사이즈)."""
    relative = doc.get("coords") == "relative"
    items: list[AnnotationItem] = []
    for a in doc.get("annotations", []):
        ann_id = a.get("annotation_id") or new_id()
        if a["type"] == "polygon":
            pts = a["points"]
            if relative:
                pts = [(x * img_w, y * img_h) for x, y in pts]
            else:
                pts = [(x, y) for x, y in pts]
            items.append(AnnotationItem(
                annotation_id=ann_id, class_id=a["class_id"], type="polygon",
                order=a.get("order", 0), points=pts,
            ))
        elif a["type"] == "brush_mask":
            src_w, src_h = a["width"], a["height"]
            mask = rle_decode(a.get("rle", ""), src_h, src_w)
            if (src_w, src_h) != (img_w, img_h):
                mask = cv2.resize(mask, (img_w, img_h), interpolation=cv2.INTER_NEAREST)
            items.append(AnnotationItem(
                annotation_id=ann_id, class_id=a["class_id"], type="brush_mask",
                order=a.get("order", 0), mask=mask, width=img_w, height=img_h,
            ))
    return sorted(items, key=lambda x: x.order)
