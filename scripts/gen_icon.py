"""app/resources/logo.svg → app/resources/app_icon.ico (멀티 해상도) 1회성 생성 스크립트.

로고 디자인이 바뀌면 다시 실행해서 .ico를 재생성한다. 실행: py -3 scripts/gen_icon.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image
from PyQt6.QtCore import QByteArray, Qt
from PyQt6.QtGui import QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QApplication

RESOURCES = Path(__file__).resolve().parent.parent / "app" / "resources"
SIZES = (16, 32, 48, 256)


def main() -> None:
    _app = QApplication.instance() or QApplication([])  # QPixmap 렌더링에 필요
    svg_path = RESOURCES / "logo.svg"

    # 최대 해상도(256)로 한 번만 렌더링 → Pillow가 sizes=[...]로 각 크기를
    # 다운샘플링해서 ICO 안에 넣는다 (append_images 방식은 이 Pillow 버전에서
    # 크기별 프레임을 제대로 묶지 못해 16x16 한 장만 저장되는 문제가 있었음).
    base_size = max(SIZES)
    renderer = QSvgRenderer(QByteArray(svg_path.read_bytes()))
    pm = QPixmap(base_size, base_size)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    renderer.render(painter)
    painter.end()
    qimg = pm.toImage()
    buf = qimg.bits().asstring(qimg.sizeInBytes())
    base_img = Image.frombuffer("RGBA", (base_size, base_size), buf, "raw", "BGRA", 0, 1)

    out_path = RESOURCES / "app_icon.ico"
    base_img.save(out_path, format="ICO", sizes=[(s, s) for s in SIZES])
    print(f"saved {out_path} (sizes={SIZES})")


if __name__ == "__main__":
    main()
