"""라운드 2a 프로토타입 — 실제 배터리 캡 이미지로 circle_detector 파라미터 튜닝.

projects/nok/images/{7,8,9,10,11}번.bmp (junction 공유, 읽기 전용)를 로드해
detect_circles()를 돌리고, 결과를 원본 위에 그려 이미지로 저장한다(육안 확인용).
Qt 없이 순수 OpenCV로 실행 — `python scripts/zone_circle_proto.py`.

출력: scratchpad 임시 디렉터리 (이 저장소 밖) — 구현 로그에 확정 파라미터와
판단 근거를 남기고, 이 스크립트 자체는 저장소에 남겨 재현 가능하게 유지한다.
"""
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.circle_detector import DetectParams, detect_circles  # noqa: E402

IMAGES_DIR = Path(__file__).resolve().parents[1] / "projects" / "nok" / "images"
OUT_DIR = Path(
    r"C:\Users\Feel\AppData\Local\Temp\claude\d--segmentation-model"
    r"\6601b6b5-5d86-491f-8786-9c4f151f70ec\scratchpad\zone_circle_proto_out"
)


def imread_unicode(path: Path) -> np.ndarray:
    """cv2.imread는 Windows 비-ASCII 경로를 못 읽으므로 np.fromfile+imdecode로 우회."""
    data = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    params = DetectParams()  # circle_detector.py 기본값 그대로 사용

    for path in sorted(IMAGES_DIR.glob("*.bmp")):
        img = imread_unicode(path)
        if img is None:
            print(f"[SKIP] 읽기 실패: {path}")
            continue

        circles = detect_circles(img, params=params)
        print(f"{path.name}: shape={img.shape} -> {len(circles)}개 검출")
        for cx, cy, r in circles:
            print(f"    cx={cx:.1f} cy={cy:.1f} r={r:.1f}")

        vis = img.copy()
        for i, (cx, cy, r) in enumerate(circles):
            color = ((37 * i) % 255, (91 * i + 60) % 255, (173 * i + 30) % 255)
            cv2.circle(vis, (int(cx), int(cy)), int(r), color, 6)
            cv2.circle(vis, (int(cx), int(cy)), 10, color, -1)

        # 육안 확인용으로 다운스케일 저장 (원본 20MP는 뷰어 부담)
        max_dim = 1600
        h, w = vis.shape[:2]
        scale = min(1.0, max_dim / max(h, w))
        if scale < 1.0:
            vis = cv2.resize(vis, (round(w * scale), round(h * scale)))

        out_path = OUT_DIR / f"{path.stem}_circles.png"
        ok, buf = cv2.imencode(".png", vis)
        if ok:
            buf.tofile(str(out_path))
            print(f"    -> {out_path}")


if __name__ == "__main__":
    main()
