"""R 분석 탭 — 검사 설정 팝업 다이얼로그 (threshold/분모/스펙 상하한/ROI 버튼).

threshold 슬라이더는 `zone_analysis_tab.py`의 confidence 슬라이더와 동일한 150ms
QTimer(singleShot) 디바운스 패턴(요구사항 4) — 라이브 프리뷰가 슬라이더를 드래그하는
동안 매 프레임 재검출을 돌리지 않도록 한다. ROI 지정 버튼 2개는 실제 ROI 그리기
동작(캔버스 접근)을 다이얼로그가 직접 수행하지 않고 전용 시그널로 탭에 위임한다
(다이얼로그는 캔버스를 모름 — 레이어 분리).
"""
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QPushButton,
    QSlider, QDoubleSpinBox, QLabel,
)

from app.core.i18n import t

_DEBOUNCE_MS = 150


class RSettingsPanel(QDialog):
    """threshold/분모/스펙 상하한 입력 + ROI 지정 버튼 2개를 담은 팝업 모달."""

    settings_changed = pyqtSignal()        # threshold/분모/스펙 중 하나라도 바뀌면(디바운스 후)
    roi_global_requested = pyqtSignal()     # "전역 지정" 클릭 — 모든 셀에 적용할 ROI 그리기 시작
    roi_override_requested = pyqtSignal()   # "이 이미지만 보정" 클릭 — 현재 이미지 전용 override

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("r_settings.window_title"))
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(_DEBOUNCE_MS)
        self._debounce.timeout.connect(self.settings_changed.emit)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        roi_row = QHBoxLayout()
        self._btn_roi_global = QPushButton(t("r_settings.btn_roi_global"))
        self._btn_roi_global.setToolTip(t("r_settings.roi_global_tip"))
        self._btn_roi_global.clicked.connect(self.roi_global_requested.emit)
        roi_row.addWidget(self._btn_roi_global)
        self._btn_roi_override = QPushButton(t("r_settings.btn_roi_override"))
        self._btn_roi_override.setToolTip(t("r_settings.roi_override_tip"))
        self._btn_roi_override.clicked.connect(self.roi_override_requested.emit)
        roi_row.addWidget(self._btn_roi_override)
        layout.addLayout(roi_row)

        self._chk_auto_detect = QCheckBox(t("r_settings.auto_detect_checkbox"))
        self._chk_auto_detect.setChecked(True)
        self._chk_auto_detect.toggled.connect(self._on_auto_detect_toggled)
        layout.addWidget(self._chk_auto_detect)

        form = QFormLayout()

        self._thr_row = QHBoxLayout()
        self._threshold_slider = QSlider(Qt.Orientation.Horizontal)
        self._threshold_slider.setRange(0, 255)
        self._threshold_slider.setValue(128)
        self._lbl_threshold = QLabel("128")
        self._lbl_threshold.setFixedWidth(32)
        self._threshold_slider.valueChanged.connect(self._on_threshold_changed)
        self._thr_row.addWidget(self._threshold_slider)
        self._thr_row.addWidget(self._lbl_threshold)
        form.addRow("Threshold:", self._thr_row)

        self._denominator_spin = QDoubleSpinBox()
        self._denominator_spin.setRange(0.0, 1e9)
        self._denominator_spin.setDecimals(2)
        self._denominator_spin.valueChanged.connect(lambda _v: self._debounce.start())
        form.addRow(t("r_settings.row_denominator"), self._denominator_spin)

        self._spec_lower_spin = QDoubleSpinBox()
        self._spec_lower_spin.setRange(0.0, 1e6)
        self._spec_lower_spin.setDecimals(4)
        self._spec_lower_spin.valueChanged.connect(lambda _v: self._debounce.start())
        form.addRow(t("r_settings.row_spec_lower"), self._spec_lower_spin)

        self._spec_upper_spin = QDoubleSpinBox()
        self._spec_upper_spin.setRange(0.0, 1e6)
        self._spec_upper_spin.setDecimals(4)
        self._spec_upper_spin.valueChanged.connect(lambda _v: self._debounce.start())
        form.addRow(t("r_settings.row_spec_upper"), self._spec_upper_spin)

        layout.addLayout(form)

        btn_close = QPushButton(t("common.close"))
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)

    def _on_threshold_changed(self, value: int) -> None:
        self._lbl_threshold.setText(str(value))
        self._debounce.start()

    def _on_auto_detect_toggled(self, checked: bool) -> None:
        self._threshold_slider.setEnabled(checked)
        self._lbl_threshold.setEnabled(checked)
        self.settings_changed.emit()   # 바이너리 토글 — 디바운스 없이 즉시 발화

    # ── 공개 getter/setter — 탭이 r_cell_store 세션과 동기화할 때 사용 ───────────

    def auto_detect_enabled(self) -> bool:
        return self._chk_auto_detect.isChecked()

    def set_auto_detect_enabled(self, value: bool) -> None:
        self._chk_auto_detect.setChecked(value)

    def threshold(self) -> int:
        return self._threshold_slider.value()

    def set_threshold(self, value: int) -> None:
        self._threshold_slider.setValue(value)

    def denominator(self) -> float:
        return self._denominator_spin.value()

    def set_denominator(self, value: float) -> None:
        self._denominator_spin.setValue(value)

    def spec_lower(self) -> float:
        return self._spec_lower_spin.value()

    def set_spec_lower(self, value: float) -> None:
        self._spec_lower_spin.setValue(value)

    def spec_upper(self) -> float:
        return self._spec_upper_spin.value()

    def set_spec_upper(self, value: float) -> None:
        self._spec_upper_spin.setValue(value)


if __name__ == "__main__":
    import os
    import sys

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)

    panel = RSettingsPanel()
    panel.set_threshold(100)
    assert panel.threshold() == 100
    panel.set_denominator(500.0)
    assert panel.denominator() == 500.0
    panel.set_spec_lower(0.9)
    panel.set_spec_upper(1.1)
    assert panel.spec_lower() == 0.9 and panel.spec_upper() == 1.1

    fired: list[int] = []
    panel.settings_changed.connect(lambda: fired.append(1))
    panel._threshold_slider.setValue(140)   # valueChanged -> debounce.start()
    assert panel._debounce.isActive(), "슬라이더 변경 시 150ms debounce 타이머가 시작돼야 함"
    assert not fired, "디바운스 시간 전에는 즉시 발화하면 안 됨"

    roi_global_clicks: list[int] = []
    panel.roi_global_requested.connect(lambda: roi_global_clicks.append(1))
    panel._btn_roi_global.click()
    assert roi_global_clicks == [1]

    roi_override_clicks: list[int] = []
    panel.roi_override_requested.connect(lambda: roi_override_clicks.append(1))
    panel._btn_roi_override.click()
    assert roi_override_clicks == [1]

    assert panel.auto_detect_enabled() is True, "기본값은 켜짐이어야 함(하위호환)"
    fired.clear()
    panel.set_auto_detect_enabled(False)
    assert panel.auto_detect_enabled() is False
    assert not panel._threshold_slider.isEnabled(), "자동검출 꺼지면 threshold 슬라이더도 비활성화"
    assert fired == [1], "체크박스 toggled는 디바운스 없이 즉시 settings_changed를 발화해야 함"
    panel.set_auto_detect_enabled(True)
    assert panel._threshold_slider.isEnabled()

    print("r_settings_panel self-check OK")
