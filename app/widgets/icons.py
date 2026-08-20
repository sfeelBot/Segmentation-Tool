"""SVG 라인 아이콘 로더 — app/resources/icons/*.svg 를 QIcon/QPixmap 으로 렌더링.

이모지(컬러 폰트) 대신 미니멀 SVG 아이콘을 쓰기 위한 경량 유틸. SVG 파일은
stroke="currentColor" (또는 fill="currentColor") 로 저장하고, 로드 시 문자열
치환으로 원하는 색을 입힌다. 결과는 (이름, 색상, 크기) 단위로 캐시한다.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PyQt6.QtCore import QByteArray, Qt
from PyQt6.QtGui import QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

_ICON_DIR = Path(__file__).resolve().parent.parent / "resources" / "icons"

DEFAULT_COLOR = "#e5e7eb"   # 앱 표준 기본 아이콘색


@lru_cache(maxsize=None)
def pixmap(name: str, color: str = DEFAULT_COLOR, size: int = 20) -> QPixmap:
    """이름의 SVG를 지정 색상·크기로 렌더링한 QPixmap 반환 (캐시됨)."""
    svg_text = (_ICON_DIR / f"{name}.svg").read_text(encoding="utf-8")
    svg_text = svg_text.replace("currentColor", color)
    renderer = QSvgRenderer(QByteArray(svg_text.encode("utf-8")))
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    renderer.render(painter)
    painter.end()
    return pm


def icon(name: str, color: str = DEFAULT_COLOR, size: int = 20) -> QIcon:
    """이름의 SVG를 지정 색상·크기로 렌더링한 QIcon 반환."""
    return QIcon(pixmap(name, color, size))
