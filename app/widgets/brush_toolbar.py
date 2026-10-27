"""공유 브러시 툴바 컨트롤러 — 브러시/지우개/영역삭제/pan/undo/브러시크기.

라벨링 탭(+2단계: 존분석/R분석 탭)에서 동작까지 완전히 통일된 공통 도구만 다룬다.
자체 QWidget이 아니다 — QAction/QSpinBox 객체만 만들어 노출하고, 호스트가 자신의
QToolBar에 `addAction()`/`addWidget()`으로 원하는 위치에 삽입한다. 툴바에
자동으로 끼워 넣지 않는 이유: 호스트의 기존 아이콘 좌→우 순서(폴리곤/브러시/
채움/지우개/영역삭제/select/pan)가 키보드 단축키(Q/W/E/R/D/A/S)와 1:1 공간
대응을 이루고 있어, 공유 클러스터를 한 덩어리로 묶어 넣으면 이 대응이 깨진다
(디자인 리뷰 피드백, 2026-10-27). 호스트는 로컬 도구 액션 생성과 이 클래스가
노출하는 액션의 `addAction()` 호출을 기존 순서 그대로 인터리빙하면 된다.
"""
from __future__ import annotations

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QToolBar, QSpinBox
from PyQt6.QtCore import QObject, pyqtSignal

from app.core.i18n import t
from app.widgets.icons import icon as svg_icon

TOOL_BRUSH        = "brush"
TOOL_ERASER       = "eraser"
TOOL_ERASER_FLOOD = "eraser_flood"
TOOL_PAN          = "pan"


class BrushToolbar(QObject):
    """기존 QToolBar에 브러시/지우개/영역삭제/pan/undo/브러시크기 액션을 꽂아주는
    컨트롤러. `toolbar`는 생성되는 QAction/QSpinBox의 부모(수명 관리)로만 쓰이고,
    실제 삽입 위치는 호스트가 각 `act_*`/`spin_brush_size`를 `toolbar.addAction()`/
    `addWidget()`으로 직접 호출해 결정한다."""

    tool_changed        = pyqtSignal(str)   # 사용자가 클릭으로 브러시/지우개/영역삭제/pan 중 하나를 선택
    brush_size_changed  = pyqtSignal(int)   # 스핀박스를 사용자가 직접 바꿨을 때만 emit
    undo_requested       = pyqtSignal()

    _CLUSTER_TOOLS = (TOOL_BRUSH, TOOL_ERASER, TOOL_ERASER_FLOOD, TOOL_PAN)

    def __init__(self, toolbar: QToolBar, *, show_delete_region: bool = True,
                 brush_size_range: tuple[int, int] = (1, 200), parent=None) -> None:
        super().__init__(parent)
        self._tool: str | None = None

        self.act_brush = QAction(svg_icon("tool_brush"), "", toolbar)
        self.act_brush.setToolTip(t("tool.brush.tip"))
        self.act_brush.setCheckable(True)
        self.act_brush.triggered.connect(lambda: self._on_tool_clicked(TOOL_BRUSH))

        self.act_eraser = QAction(svg_icon("tool_eraser"), "", toolbar)
        self.act_eraser.setToolTip(t("tool.eraser.tip"))
        self.act_eraser.setCheckable(True)
        self.act_eraser.triggered.connect(lambda: self._on_tool_clicked(TOOL_ERASER))

        # R분석(show_delete_region=False)엔 영역삭제 개념이 없음 — 액션 자체를
        # 만들지 않는다(만들고 setVisible(False)로 숨기지 않음, 2단계 혼동 방지).
        if show_delete_region:
            self.act_delete_region: QAction | None = QAction(
                svg_icon("tool_eraser_flood"), "", toolbar
            )
            self.act_delete_region.setToolTip(t("tool.eraser_flood.tip"))
            self.act_delete_region.setCheckable(True)
            self.act_delete_region.triggered.connect(
                lambda: self._on_tool_clicked(TOOL_ERASER_FLOOD)
            )
        else:
            self.act_delete_region = None

        self.act_pan = QAction(svg_icon("tool_pan"), "", toolbar)
        self.act_pan.setToolTip(t("tool.pan.tip"))
        self.act_pan.setCheckable(True)
        self.act_pan.triggered.connect(lambda: self._on_tool_clicked(TOOL_PAN))

        self.spin_brush_size = QSpinBox(toolbar)
        lo, hi = brush_size_range
        self.spin_brush_size.setRange(lo, hi)
        self.spin_brush_size.setValue(20)
        self.spin_brush_size.setMinimumWidth(76)   # GitHub #3(a) — 폭 고정 회귀 방지
        self.spin_brush_size.valueChanged.connect(self.brush_size_changed)

        self.act_undo = QAction(svg_icon("undo"), "", toolbar)
        self.act_undo.setToolTip(t("tool.undo.tip"))
        self.act_undo.setShortcut("Ctrl+Z")
        self.act_undo.triggered.connect(self.undo_requested)

    # ── 공개 API ──────────────────────────────────────────────────────────────

    def current_tool(self) -> str:
        return self._tool

    def set_tool(self, tool: str) -> None:
        """tool이 이 클러스터 소속이면 그 액션만 checked, 아니면(호스트 로컬 도구가
        활성화된 경우) 클러스터 전체 unchecked. tool_changed는 재발행하지 않음 —
        호스트가 자기 쪽 도구 전환 시 동기화 호출용."""
        self._tool = tool
        self.act_brush.setChecked(tool == TOOL_BRUSH)
        self.act_eraser.setChecked(tool == TOOL_ERASER)
        if self.act_delete_region is not None:
            self.act_delete_region.setChecked(tool == TOOL_ERASER_FLOOD)
        self.act_pan.setChecked(tool == TOOL_PAN)

    def set_brush_size(self, value: int) -> None:
        """캔버스→스핀박스 역동기화. blockSignals로 루프 방지(기존
        `_canvas.brush_size_changed.connect(self._spin_brush.setValue)` 패턴과 동등)."""
        self.spin_brush_size.blockSignals(True)
        self.spin_brush_size.setValue(value)
        self.spin_brush_size.blockSignals(False)

    # ── 내부 ─────────────────────────────────────────────────────────────────

    def _on_tool_clicked(self, tool: str) -> None:
        # 체크 가능한 QAction을 QActionGroup 없이 쓰므로, 이미 checked인 액션을
        # 다시 클릭하면 Qt가 자동으로 꺼버린다 — set_tool()이 매번 명시적으로
        # 올바른 최종 상태(클릭한 것만 checked)를 강제한다.
        self.set_tool(tool)
        self.tool_changed.emit(tool)
