"""Saige 라벨링 XML 포맷 ↔ 프로젝트 어노테이션 변환.

Saige XML 구조:
  ClassGroup/Class: 이름 + ARGB 정수 색상
  ImageGroup/Image: 경로/크기/SplitState
    LabelGroup/IsNormal=true  → OK 이미지 (어노테이션 없음)
    LabelGroup/Label:
      ClassIndex (0-based)
      Type=Contours
      ContourGroup/Contour[@Type="Outer"] → 폴리곤 꼭짓점
      ContourGroup/Contour[@Type="Inner"] → 내부 구멍 (현재 무시)
"""
from __future__ import annotations

import shutil
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from app.core.annotation_store import (
    AnnotationItem, ClassDef,
    load_classes, save_classes,
    load as load_ann, save,
    get_ok, set_ok, new_id,
)
from app.core import project as _project
from app.core.logger import get_logger

log = get_logger(__name__)


# ── 색상 변환 ─────────────────────────────────────────────────────────────────

def saige_color_to_rgb(color_int: int) -> tuple[int, int, int]:
    """Saige ARGB 정수(signed 32-bit) → (R, G, B)."""
    if color_int < 0:
        color_int += (1 << 32)
    return ((color_int >> 16) & 0xFF,
            (color_int >>  8) & 0xFF,
             color_int        & 0xFF)


def rgb_to_saige_color(r: int, g: int, b: int, a: int = 255) -> int:
    """(R, G, B) → Saige ARGB 정수(signed 32-bit)."""
    v = (a << 24) | (r << 16) | (g << 8) | b
    return v - (1 << 32) if v >= (1 << 31) else v


# ── 가져오기 (Saige → 프로젝트) ──────────────────────────────────────────────

def import_saige(
    xml_path: Path,
    copy_images: bool = True,
) -> dict:
    """Saige XML 프로젝트를 현재 프로젝트로 가져온다.

    Returns:
        {"images_ok": int, "anns_added": int, "skipped": int, "errors": list[str]}
    """
    stats: dict = {"images_ok": 0, "anns_added": 0, "skipped": 0, "errors": []}

    try:
        tree = ET.parse(str(xml_path))
    except Exception as e:
        stats["errors"].append(f"XML 파싱 실패: {e}")
        return stats

    root     = tree.getroot()
    xml_dir  = xml_path.parent
    img_dir  = _project.images_dir()
    img_dir.mkdir(parents=True, exist_ok=True)

    # ── 클래스 파싱 ──────────────────────────────────────────────────────────
    saige_idx_to_class_id = _merge_classes(root)

    # ── 이미지·어노테이션 처리 ────────────────────────────────────────────────
    ig = root.find("ImageGroup")
    if ig is None:
        stats["errors"].append("ImageGroup 을 찾을 수 없습니다.")
        return stats

    for img_elem in ig.findall("Image"):
        raw_path = img_elem.findtext("Path") or ""
        img_src  = Path(raw_path)
        if not img_src.is_absolute():
            img_src = (xml_dir / raw_path).resolve()

        img_dst  = img_dir / img_src.name
        w = int(img_elem.findtext("Width")  or 0)
        h = int(img_elem.findtext("Height") or 0)

        # 이미지 복사
        if copy_images:
            if img_src.exists():
                if not img_dst.exists():
                    try:
                        shutil.copy2(img_src, img_dst)
                    except Exception as e:
                        stats["errors"].append(f"복사 실패 {img_src.name}: {e}")
                        stats["skipped"] += 1
                        continue
            else:
                stats["errors"].append(f"이미지 없음: {img_src}")
                stats["skipped"] += 1
                continue
        elif not img_dst.exists():
            stats["errors"].append(f"이미지 없음(복사 미선택): {img_dst}")
            stats["skipped"] += 1
            continue

        # 실제 이미지 크기 (XML 에 없을 때 PIL 로 보완)
        if w == 0 or h == 0:
            try:
                from PIL import Image
                with Image.open(img_dst) as im:
                    w, h = im.size
            except Exception:
                pass

        label_group = img_elem.find("LabelGroup")
        if label_group is None:
            stats["images_ok"] += 1
            continue

        is_normal = label_group.findtext("IsNormal", "false").strip().lower() == "true"
        if is_normal:
            set_ok(img_dst, True, w, h)
            stats["images_ok"] += 1
            continue

        # 어노테이션 변환
        annotations: list[AnnotationItem] = []
        for label in label_group.findall("Label"):
            saige_idx = int(label.findtext("ClassIndex") or 0)
            class_id  = saige_idx_to_class_id.get(saige_idx, saige_idx + 1)
            ltype     = label.findtext("Type") or ""

            if ltype == "Contours":
                cg = label.find("ContourGroup")
                if cg is None:
                    continue
                for contour in cg.findall("Contour"):
                    if contour.get("Type", "Outer") != "Outer":
                        continue   # Inner(구멍) 은 현재 무시
                    pts = [(int(p.get("X", 0)), int(p.get("Y", 0)))
                           for p in contour.findall("Point")]
                    if len(pts) >= 3:
                        annotations.append(AnnotationItem(
                            annotation_id = new_id(),
                            class_id      = class_id,
                            type          = "polygon",
                            order         = len(annotations),
                            points        = pts,
                        ))
                        stats["anns_added"] += 1

        if annotations and w > 0 and h > 0:
            save(img_dst, annotations, w, h)

        stats["images_ok"] += 1

    log.info(
        f"Saige 가져오기 완료 — 이미지 {stats['images_ok']}개, "
        f"어노테이션 {stats['anns_added']}개, 건너뜀 {stats['skipped']}개"
    )
    return stats


def _merge_classes(root: ET.Element) -> dict[int, int]:
    """Saige ClassGroup 을 현재 프로젝트 클래스 목록과 병합.
    Returns: {saige_class_index: project_class_id}"""
    existing = {c.name: c for c in load_classes()}
    merged   = list(existing.values()) if existing else [
        ClassDef(0, "background", (0, 0, 0))
    ]

    mapping: dict[int, int] = {}
    cg = root.find("ClassGroup")
    if cg is None:
        return mapping

    for saige_idx, cls_elem in enumerate(cg.findall("Class")):
        name      = (cls_elem.findtext("Name") or f"class_{saige_idx+1}").strip()
        color_int = int(cls_elem.findtext("Color") or 0)
        color     = saige_color_to_rgb(color_int)

        if name in existing:
            mapping[saige_idx] = existing[name].class_id
        else:
            new_cid = max((c.class_id for c in merged), default=0) + 1
            nc = ClassDef(class_id=new_cid, name=name, color=color)
            merged.append(nc)
            existing[name] = nc
            mapping[saige_idx] = new_cid

    save_classes(merged)
    return mapping


# ── 내보내기 (프로젝트 → Saige) ──────────────────────────────────────────────

def export_saige(xml_out_path: Path) -> dict:
    """현재 프로젝트 어노테이션을 Saige XML 포맷으로 내보낸다.
    brush_mask 는 cv2.findContours 로 윤곽선 추출 후 폴리곤으로 변환.

    Returns: {"images_exported": int, "errors": list[str]}
    """
    stats: dict = {"images_exported": 0, "errors": []}

    img_dir = _project.images_dir()
    exts    = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"}
    paths   = sorted(p for p in img_dir.iterdir() if p.suffix.lower() in exts)

    classes      = load_classes()
    non_bg_cls   = [c for c in classes if c.class_id != 0]
    cid_to_sidx  = {c.class_id: i for i, c in enumerate(non_bg_cls)}

    # ── XML 루트 구성 ──────────────────────────────────────────────────────
    root = ET.Element("Project")
    ET.SubElement(root, "Version").text      = "0.9"
    ET.SubElement(root, "Type").text         = "Segmentation"
    ET.SubElement(root, "SpecificType").text = "Developer"
    ET.SubElement(root, "ModifiedDate").text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ClassGroup
    cg_elem = ET.SubElement(root, "ClassGroup")
    ET.SubElement(cg_elem, "NumberOfClasses").text = str(len(non_bg_cls))
    for cls in non_bg_cls:
        ce = ET.SubElement(cg_elem, "Class")
        ET.SubElement(ce, "Name").text  = cls.name
        ET.SubElement(ce, "Color").text = str(rgb_to_saige_color(*cls.color))

    # ImageGroup
    ig_elem = ET.SubElement(root, "ImageGroup")
    ET.SubElement(ig_elem, "NumberOfImages").text = str(len(paths))

    for img_path in paths:
        try:
            from PIL import Image
            with Image.open(img_path) as im:
                w, h = im.size
        except Exception as e:
            stats["errors"].append(f"이미지 로드 실패: {img_path.name} — {e}")
            continue

        img_elem = ET.SubElement(ig_elem, "Image")

        # 경로: XML 파일 기준 상대경로 시도
        try:
            rel = img_path.relative_to(xml_out_path.parent)
            path_str = str(rel).replace("\\", "/")
        except ValueError:
            path_str = str(img_path)
        ET.SubElement(img_elem, "Path").text   = path_str
        ET.SubElement(img_elem, "Width").text  = str(w)
        ET.SubElement(img_elem, "Height").text = str(h)
        ET.SubElement(img_elem, "SplitState").text = "Training"

        anns = load_ann(img_path)
        lg   = ET.SubElement(img_elem, "LabelGroup")
        ok   = get_ok(img_path) and not anns

        if not anns or ok:
            ET.SubElement(lg, "IsNormal").text        = "true"
            ET.SubElement(lg, "NumberOfLabels").text  = "0"
        else:
            # brush_mask → 폴리곤 변환
            poly_anns = _to_polygon_list(anns, w, h)
            ET.SubElement(lg, "IsNormal").text        = "false"
            ET.SubElement(lg, "NumberOfLabels").text  = str(len(poly_anns))
            for ann in poly_anns:
                sidx = cid_to_sidx.get(ann.class_id, 0)
                le   = ET.SubElement(lg, "Label")
                ET.SubElement(le, "ClassIndex").text = str(sidx)
                ET.SubElement(le, "Type").text       = "Contours"
                cgr  = ET.SubElement(le, "ContourGroup")
                co   = ET.SubElement(cgr, "Contour")
                co.set("Type", "Outer")
                for x, y in ann.points:
                    pt = ET.SubElement(co, "Point")
                    pt.set("X", str(int(x)))
                    pt.set("Y", str(int(y)))

        stats["images_exported"] += 1

    # 파일 쓰기
    _indent_xml(root)
    tree = ET.ElementTree(root)
    xml_out_path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(str(xml_out_path), encoding="utf-8", xml_declaration=True)
    log.info(f"Saige 내보내기 완료 — {stats['images_exported']}개 이미지 → {xml_out_path}")
    return stats


def _to_polygon_list(anns: list[AnnotationItem], w: int, h: int) -> list[AnnotationItem]:
    """brush_mask 를 윤곽 폴리곤으로 변환해서 polygon 리스트로 반환."""
    result = []
    for ann in anns:
        if ann.type == "polygon":
            result.append(ann)
        elif ann.type == "brush_mask" and ann.mask is not None:
            mask = ann.mask
            if mask.shape != (h, w):
                mask = cv2.resize(mask, (w, h), interpolation=cv2.INTER_NEAREST)
            contours, _ = cv2.findContours(
                mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            for c in contours:
                pts = [(int(pt[0][0]), int(pt[0][1])) for pt in c]
                if len(pts) >= 3:
                    result.append(AnnotationItem(
                        annotation_id = new_id(),
                        class_id      = ann.class_id,
                        type          = "polygon",
                        order         = len(result),
                        points        = pts,
                    ))
    return result


def _indent_xml(elem: ET.Element, level: int = 0) -> None:
    pad = "\n" + "  " * level
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = pad + "  "
        if not elem.tail or not elem.tail.strip():
            elem.tail = pad
        for child in elem:
            _indent_xml(child, level + 1)
        if not child.tail or not child.tail.strip():
            child.tail = pad
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = pad
