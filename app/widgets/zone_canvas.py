"""존 분석 탭 캔버스 — 이미지 + 추론 오버레이 표시 전용 뷰어.

라운드 1: 순수 뷰어(원 검출/편집 UI 없음). `overlay_viewer.OverlayViewer`가
이미 구현한 줌/팬 QPainter 패턴을 그대로 재사용한다 — QGraphicsView가 아니라
QWidget + paintEvent 커스텀 구현 관례를 따른다.

라운드 2에서 원(circle) 오버레이 표시/드래그 편집이 이 위에 추가될 예정
(paintEvent를 오버라이드해 self._zoom/self._pan 기준으로 원을 그리는 방식).
"""
from app.widgets.overlay_viewer import OverlayViewer


class ZoneCanvas(OverlayViewer):
    """존 분석 탭 전용 캔버스.

    라운드 1에서는 OverlayViewer와 동일하게 동작한다(이미지+추론 오버레이
    표시만). 원 검출/편집은 라운드 2 범위.
    """
    pass
