"""존(Zone) 분석 — 원판(disk) 마스크 집합 차집합 기반 존 분할·퍼센티지 계산.

스펙: docs/specs/zone-analysis-tab-2026-08-25.md "판단 2"·"존 계산 로직" 절.
Qt 의존성 없음(core 규칙) — 순수 numpy 함수.

원을 반지름 오름차순 [C_0(최소), ..., C_{N-1}(최대)]로 정렬했을 때:
    Zone_center = mask(C_0)
    Zone_i      = mask(C_{i+1}) AND NOT mask(C_i)   (i = 0..N-2)
    Zone_outside = 전체 이미지 AND NOT mask(C_{N-1})
전제: 원들이 대략 nested(중첩)돼 있다 — 배터리 캡 실제 구조상 항상 성립. 수동 편집으로
원을 교차시키는 비정상 입력은 v1에서 방지하지 않는다(스펙 명시, YAGNI).
"""
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass
class Circle:
    id: int
    cx: float
    cy: float
    r: float


@dataclass
class Zone:
    index: int          # 0=중심부, 1..N-1=링, N=바깥쪽 (원 N개 기준)
    name: str
    mask: np.ndarray     # (H, W) bool


def _disk_mask(cx: float, cy: float, r: float, img_shape: tuple[int, int]) -> np.ndarray:
    """(x-cx)^2 + (y-cy)^2 <= r^2 벡터화 비교로 원판 마스크 생성 — fillPoly 아님."""
    h, w = img_shape
    yy, xx = np.ogrid[:h, :w]
    return (xx - cx) ** 2 + (yy - cy) ** 2 <= r ** 2


def zones_from_circles(circles: list[Circle], img_shape: tuple[int, int]) -> list[Zone]:
    """반지름 오름차순 정렬 후 원판 마스크 차집합으로 존 목록 생성.

    원이 없으면 빈 리스트(존 개념 자체가 성립하지 않음). 원 N개면 존 N+1개.
    """
    if not circles:
        return []
    sorted_c = sorted(circles, key=lambda c: c.r)
    n = len(sorted_c)
    masks = [_disk_mask(c.cx, c.cy, c.r, img_shape) for c in sorted_c]

    zones = [Zone(0, "중심부", masks[0])]
    for i in range(n - 1):
        zones.append(Zone(i + 1, f"링 {i + 1}", masks[i + 1] & ~masks[i]))
    zones.append(Zone(n, "바깥쪽", ~masks[-1]))
    return zones


def zone_stats(zone_mask: np.ndarray, target_class_mask: np.ndarray) -> float:
    """존 마스크 면적 대비 타겟 클래스(AND) 픽셀 비율(%)."""
    area = int(zone_mask.sum())
    if area == 0:
        return 0.0
    hit = int((zone_mask & target_class_mask).sum())
    return hit / area * 100.0


def compute_blob_labels(mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """타겟 클래스 이진 마스크 -> (라벨맵, stats). 라운드 4 블랍 클릭 삭제 전용 헬퍼.

    `cv2.connectedComponentsWithStats(connectivity=8)`를 그대로 노출한다 —
    `inference_engine._compute_blobs_and_filter()`와 API는 비슷하지만 confidence/
    size threshold 필터링까지 가져오면 이 탭엔 불필요한 결합이 생겨(스펙 "블랍 삭제"
    절) 별도로 둔다. 라벨 0 = 배경. `stats[label] = [x, y, w, h, area]`(OpenCV 표준
    컬럼 순서, `CC_STAT_LEFT/TOP/WIDTH/HEIGHT/AREA`).
    """
    _, labels, stats, _ = cv2.connectedComponentsWithStats(
        mask.astype(np.uint8), connectivity=8
    )
    return labels, stats


def export_zone_percentages_to_excel(rows: list[tuple[str, str, float]], out_path: Path) -> None:
    """(이미지파일명, 존이름, 타겟비율%) long format 목록을 xlsx로 저장.

    `inference_engine.export_blobs_to_excel()`과 동일한 openpyxl 패턴(헤더만 볼드,
    시트 1개)을 스키마만 바꿔 복제. wide format(이미지×존 피벗) 아님 — 스펙 C-3 참고.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "zones"
    ws.append(["이미지파일명", "존이름", "타겟비율(%)"])
    for cell in ws[1]:
        cell.font = Font(bold=True)

    for image_name, zone_name, pct in rows:
        ws.append([image_name, zone_name, round(pct, 2)])

    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(out_path))


if __name__ == "__main__":
    # ── self-check: 5x5 합성 이미지, 원 1개(cx=2, cy=2, r=1) — 손계산 검산 ──────
    # (x-2)^2+(y-2)^2<=1 만족 픽셀: (2,1)(1,2)(2,2)(3,2)(2,3) = 5개 (전체 25개 중)
    shape = (5, 5)
    circles = [Circle(1, 2, 2, 1)]
    zones = zones_from_circles(circles, shape)
    assert len(zones) == 2, "원 1개 -> 존 2개(중심부/바깥쪽)"
    assert zones[0].name == "중심부" and zones[1].name == "바깥쪽"
    assert zones[0].mask.sum() == 5, f"중심부 면적 5 예상, 실측 {zones[0].mask.sum()}"
    assert zones[1].mask.sum() == 20, f"바깥쪽 면적 20 예상, 실측 {zones[1].mask.sum()}"

    # 타겟 마스크 = 중심부와 정확히 일치 -> 중심부 100%, 바깥쪽 0%
    target = zones[0].mask
    assert zone_stats(zones[0].mask, target) == 100.0
    assert zone_stats(zones[1].mask, target) == 0.0

    # ── 원 2개 중첩 — 파티션 불변식: 존들의 합집합 = 전체 이미지, 겹침 없음 ──────
    circles2 = [Circle(1, 4, 4, 1), Circle(2, 4, 4, 3)]
    zones2 = zones_from_circles(circles2, shape)
    assert len(zones2) == 3
    assert [z.name for z in zones2] == ["중심부", "링 1", "바깥쪽"]
    total = sum(int(z.mask.sum()) for z in zones2)
    assert total == shape[0] * shape[1], "존 면적 합 = 전체 픽셀 수(겹침/누락 없음)"
    for a in zones2:
        for b in zones2:
            if a is not b:
                assert not (a.mask & b.mask).any(), "존끼리 겹치면 안 됨"

    # 타겟 마스크 = 전체 이미지(전부 녹) -> 모든 존 100%
    all_ones = np.ones(shape, dtype=bool)
    for z in zones2:
        assert zone_stats(z.mask, all_ones) == 100.0

    # 원 0개 -> 존 없음
    assert zones_from_circles([], shape) == []

    # ── compute_blob_labels: 서로 떨어진 블랍 2개 검산 ──────────────────────
    blob_mask = np.zeros((6, 6), dtype=np.uint8)
    blob_mask[0:2, 0:2] = 1   # 블랍 A, 면적 4
    blob_mask[4:6, 4:6] = 1   # 블랍 B, 면적 4
    labels, stats = compute_blob_labels(blob_mask)
    assert labels.shape == blob_mask.shape
    unique_labels = set(np.unique(labels).tolist()) - {0}
    assert len(unique_labels) == 2, f"블랍 2개 예상, 실측 {len(unique_labels)}"
    for lbl in unique_labels:
        assert stats[lbl, 4] == 4, f"블랍 면적 4 예상, 실측 {stats[lbl, 4]}"
    assert labels[0, 0] != labels[5, 5] and labels[0, 0] != 0 and labels[5, 5] != 0

    print("zone_metrics self-check OK")
