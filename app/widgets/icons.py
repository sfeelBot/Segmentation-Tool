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

from app.core.logger import get_logger

_ICON_DIR = Path(__file__).resolve().parent.parent / "resources" / "icons"

DEFAULT_COLOR = "#e5e7eb"   # 앱 표준 기본 아이콘색

log = get_logger(__name__)


@lru_cache(maxsize=None)
def pixmap(name: str, color: str = DEFAULT_COLOR, size: int = 20) -> QPixmap:
    """이름의 SVG를 지정 색상·크기로 렌더링한 QPixmap 반환 (캐시됨).

    설치본에서 아이콘 파일이 누락/손상된 경우(패키징 결함, 바이러스 백신
    격리 등) 빈 투명 아이콘으로 대체한다 — 학습 취소처럼 아이콘 하나 때문에
    핵심 동작 전체가 크래시하면 안 됨 (issue #41).
    """
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    try:
        svg_text = (_ICON_DIR / f"{name}.svg").read_text(encoding="utf-8")
    except OSError:
        log.warning(f"아이콘 파일 로드 실패, 빈 아이콘으로 대체: {name}.svg")
        return pm
    svg_text = svg_text.replace("currentColor", color)
    renderer = QSvgRenderer(QByteArray(svg_text.encode("utf-8")))
    painter = QPainter(pm)
    renderer.render(painter)
    painter.end()
    return pm


def icon(name: str, color: str = DEFAULT_COLOR, size: int = 20) -> QIcon:
    """이름의 SVG를 지정 색상·크기로 렌더링한 QIcon 반환."""
    return QIcon(pixmap(name, color, size))
