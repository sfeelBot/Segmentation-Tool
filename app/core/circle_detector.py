"""동심원(배터리 캡 크림핑/가스켓 링) 자동 검출 — Qt 의존성 없음.

파이프라인(스펙 판단 2 최종본): cv2.Canny → cv2.findContours(RETR_LIST) →
원형도(4π·area/perimeter²)+면적 필터로 링 후보 컨투어 선별 → 대수적 최소자승
원피팅(Kasa method, scipy 미사용) → 잔차 큰 점 제외 후 1~2회 재피팅으로
이상치(녹 등 불량이 침범한 에지 부분) 제거.

기본 파라미터는 scripts/zone_circle_proto.py로 실제 배터리 캡 샘플 이미지
5장(projects/nok/images/7~11번.bmp)을 튜닝한 결과(구현 로그 참고).
"""
from dataclasses import dataclass

import cv2
import numpy as np

# 화면 표시와 동일한 다운스케일 관례 (annotation_canvas.py / inference_engine.py의
# _MAX_OVERLAY_DIM=2048과 동일 기준) — 20MP 원본에서 검출 비용을 줄이고, 좌표는
# 검출 후 원본 스케일로 역산한다.
_MAX_DETECT_DIM = 2048


@dataclass(frozen=True)
class DetectParams:
    canny_low: float = 40.0
    canny_high: float = 120.0
    circularity_min: float = 0.55
    circularity_max: float = 1.35
    min_area_frac: float = 0.003    # 이미지 면적 대비 최소 컨투어 면적 비율 (먼지/스크래치 등
                                     # 잔 노이즈 원 배제 — 실측 배터리 캡 최소 링(내부 원판
                                     # 개구부)도 통상 3~5% 이상이라 여유 있게 구분됨)
    max_area_frac: float = 0.98
    min_contour_points: int = 30
    close_kernel_size: int = 15     # Canny 에지의 국소 끊김(글레어/그림자)을 잇는 모폴로지 CLOSE 커널
    close_iterations: int = 2
    outlier_iterations: int = 2
    outlier_keep_frac: float = 0.85   # 잔차 기준 하위 85%만 남기고 재피팅
    max_residual_ratio: float = 0.12  # 최종 피팅 잔차 표준편차/반지름 상한 (초과 시 기각)
    merge_center_frac: float = 0.02   # 중심 거리 < 이 비율*max(img_w,img_h) 이면 같은 원으로 병합
    merge_radius_frac: float = 0.05   # 반지름 차이 < 이 비율*r 이면 같은 원으로 병합


def _params_for_sensitivity(sensitivity: float) -> DetectParams:
    """민감도(0.0~1.0, 기본 0.5) 슬라이더 1개를 Canny 임계값/원형도 필터에 매핑.

    민감도가 높을수록 Canny 임계값을 낮추고 원형도 허용 범위를 넓혀 더 많은
    (약한) 에지 후보를 링 후보로 받아들인다.
    """
    s = max(0.0, min(1.0, sensitivity))
    canny_low = 70.0 - 50.0 * s     # 0.0 -> 70, 1.0 -> 20
    canny_high = canny_low * 3.0
    circularity_min = 0.70 - 0.30 * s   # 0.0 -> 0.70, 1.0 -> 0.40
    return DetectParams(
        canny_low=canny_low,
        canny_high=canny_high,
        circularity_min=circularity_min,
    )


def _fit_circle_kasa(points: np.ndarray) -> tuple[float, float, float] | None:
    """대수적 최소자승 원피팅 (Kasa method). points: (N, 2) float array."""
    if len(points) < 3:
        return None
    x = points[:, 0]
    y = points[:, 1]
    a_mat = np.column_stack([x, y, np.ones_like(x)])
    b_vec = x ** 2 + y ** 2
    try:
        sol, *_ = np.linalg.lstsq(a_mat, b_vec, rcond=None)
    except np.linalg.LinAlgError:
        return None
    d, e, f = sol
    cx, cy = d / 2.0, e / 2.0
    r_sq = f + cx ** 2 + cy ** 2
    if r_sq <= 0:
        return None
    return float(cx), float(cy), float(np.sqrt(r_sq))


def _fit_circle_robust(
    points: np.ndarray, iterations: int, keep_frac: float
) -> tuple[float, float, float, float] | None:
    """잔차 큰 점을 제외하며 1~2회 재피팅. 반환: (cx, cy, r, residual_std)."""
    pts = points.astype(np.float64)
    fit = _fit_circle_kasa(pts)
    if fit is None:
        return None
    cx, cy, r = fit
    for _ in range(max(0, iterations)):
        dist = np.hypot(pts[:, 0] - cx, pts[:, 1] - cy)
        residual = np.abs(dist - r)
        keep_n = max(3, int(len(pts) * keep_frac))
        if keep_n >= len(pts):
            break
        keep_idx = np.argsort(residual)[:keep_n]
        pts = pts[keep_idx]
        fit = _fit_circle_kasa(pts)
        if fit is None:
            break
        cx, cy, r = fit
    dist = np.hypot(pts[:, 0] - cx, pts[:, 1] - cy)
    residual_std = float(np.std(np.abs(dist - r)))
    return cx, cy, r, residual_std


def _merge_circles(
    circles: list[tuple[float, float, float, float]], params: DetectParams, ref_dim: float
) -> list[tuple[float, float, float]]:
    """중심·반지름이 가까운 중복 후보를 병합 — 잔차가 더 작은(품질 좋은) 쪽을 남긴다."""
    circles = sorted(circles, key=lambda c: c[3])  # residual_std 오름차순 (품질 좋은 것부터)
    kept: list[tuple[float, float, float, float]] = []
    for cx, cy, r, resid in circles:
        duplicate = False
        for kcx, kcy, kr, _ in kept:
            center_dist = float(np.hypot(cx - kcx, cy - kcy))
            if (
                center_dist < params.merge_center_frac * ref_dim
                and abs(r - kr) < params.merge_radius_frac * max(r, kr, 1.0)
            ):
                duplicate = True
                break
        if not duplicate:
            kept.append((cx, cy, r, resid))
    return [(cx, cy, r) for cx, cy, r, _ in kept]


def detect_circles(
    bgr_np: np.ndarray,
    sensitivity: float = 0.5,
    params: DetectParams | None = None,
) -> list[tuple[float, float, float]]:
    """이미지에서 동심원 후보를 검출한다.

    Args:
        bgr_np: OpenCV BGR 배열 (H, W, 3).
        sensitivity: 0.0(엄격)~1.0(관대), 기본 0.5. `params`가 주어지면 무시.
        params: 세부 파라미터 직접 지정(주로 테스트/튜닝용). None이면 sensitivity로 계산.

    Returns:
        반지름 오름차순 (cx, cy, r) 리스트 — 좌표는 입력 이미지(원본) 스케일.
    """
    if params is None:
        params = _params_for_sensitivity(sensitivity)

    h, w = bgr_np.shape[:2]
    max_dim = max(h, w, 1)
    scale = min(1.0, _MAX_DETECT_DIM / max_dim)
    if scale < 1.0:
        work = cv2.resize(
            bgr_np, (max(1, round(w * scale)), max(1, round(h * scale))),
            interpolation=cv2.INTER_AREA,
        )
    else:
        work = bgr_np
    work_h, work_w = work.shape[:2]
    img_area = work_h * work_w

    gray = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(gray, params.canny_low, params.canny_high)
    # 글레어/그림자/미세 스크래치로 인한 에지 끊김을 이어 붙여 링이 닫힌 컨투어로
    # 잡히게 한다 — 실제 배터리 캡 샘플에서 이 단계 없이는 큰 원(케이스 테두리 등)이
    # 대부분 열린 호(arc)로 쪼개져 원형도 필터를 통과하지 못했다(구현 로그 참고).
    if params.close_kernel_size > 1 and params.close_iterations > 0:
        kernel = np.ones((params.close_kernel_size, params.close_kernel_size), np.uint8)
        edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=params.close_iterations)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)

    candidates: list[tuple[float, float, float, float]] = []
    for cnt in contours:
        if len(cnt) < params.min_contour_points:
            continue
        area = cv2.contourArea(cnt)
        perimeter = cv2.arcLength(cnt, True)
        if perimeter <= 0:
            continue
        area_frac = area / img_area
        if not (params.min_area_frac <= area_frac <= params.max_area_frac):
            continue
        circularity = 4.0 * np.pi * area / (perimeter ** 2)
        if not (params.circularity_min <= circularity <= params.circularity_max):
            continue

        points = cnt.reshape(-1, 2).astype(np.float64)
        fit = _fit_circle_robust(points, params.outlier_iterations, params.outlier_keep_frac)
        if fit is None:
            continue
        cx, cy, r, residual_std = fit
        if r <= 0 or residual_std > params.max_residual_ratio * r:
            continue
        candidates.append((cx, cy, r, residual_std))

    merged = _merge_circles(candidates, params, max(work_w, work_h))

    inv_scale = 1.0 / scale if scale > 0 else 1.0
    result = [(cx * inv_scale, cy * inv_scale, r * inv_scale) for cx, cy, r in merged]
    result.sort(key=lambda c: c[2])
    return result


def demo() -> None:
    """자가 점검 — 합성 원 이미지로 검출 파이프라인이 기대대로 동작하는지 확인.

    실제 배터리 캡 이미지(다운스케일 후 최대 2048px)와 비슷한 스케일로 만들어야
    기본 파라미터(특히 close_kernel_size)가 실물과 같은 조건에서 검증된다.
    """
    img = np.zeros((1600, 1600, 3), dtype=np.uint8)
    img[:] = (30, 30, 30)
    center = (800, 800)
    # 바깥 원(반지름 600)은 둘레 대부분(20°~340°)을 정상 반지름으로 그리고, 나머지
    # 작은 구간(-20°~20°)만 반지름을 살짝(+30, ~5%) 부풀려 그린다 — 녹(불량)이
    # 에지 일부를 침범해 국소적으로 바깥으로 밀어낸 상황을 모사. 별개의 원이 아니라
    # 링 자체의 일부가 튀어나온 형태라야 강건한 원피팅의 이상치 제거가 실제로 시험된다.
    cv2.ellipse(img, center, (600, 600), 0, 20, 340, (200, 200, 200), 3)
    cv2.ellipse(img, center, (630, 630), 0, -20, 20, (200, 200, 200), 3)
    cv2.circle(img, center, 320, (200, 200, 200), 3)

    circles = detect_circles(img, sensitivity=0.5)
    assert len(circles) >= 2, f"동심원 2개를 기대했으나 {len(circles)}개 검출됨: {circles}"
    radii = sorted(c[2] for c in circles)
    assert abs(radii[0] - 320) < 40, f"안쪽 원 반지름이 기대(320)와 크게 다름: {radii[0]}"
    assert abs(radii[-1] - 600) < 40, f"바깥 원 반지름이 기대(600, 이상치 무시)와 크게 다름: {radii[-1]}"
    print("circle_detector.demo() OK", circles)


if __name__ == "__main__":
    demo()
