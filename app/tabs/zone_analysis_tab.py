"""존(Zone) 분석 탭 — 배터리 캡 녹 검사 도구. 라운드 1: 탭 스켈레톤.

기존 4탭(모델/라벨링/학습/추론)과 완전히 독립된 도구 — `app.core.project`의
프로젝트 시스템(images/annotations/checkpoints/user_models)을 사용하지 않는다.
이미지·체크포인트를 임의 경로에서 직접 열고, 그 자리에서 모델을 재구성해
추론한다. 자세한 스펙: docs/specs/zone-analysis-tab-2026-08-25.md

라운드 1 범위: 이미지/체크포인트 로드 + 모델 재구성(preset 자동 / 커스텀 코드
붙여넣기) + 추론 실행 + 타겟(녹) 클래스 즉석 구성 + ZoneCanvas 순수 뷰어 표시.
원 검출/편집·존 퍼센티지·블랍 삭제는 이후 라운드.
"""
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFileDialog,
    QMessageBox, QGroupBox, QPlainTextEdit, QTextEdit, QLineEdit, QComboBox,
    QSplitter,
)
from PyQt6.QtCore import Qt
import torch.nn as nn

from app.core import inference_engine as engine
from app.core.inference_engine import (
    InferenceResult, load_checkpoint_meta, load_model_from_ckpt, model_source_label,
)
from app.core.model_validator import validate
from app.core.model_loader import load_from_code
from app.core.annotation_store import ClassDef, DEFAULT_PALETTE
from app.core.logger import get_logger
from app.widgets.zone_canvas import ZoneCanvas

log = get_logger(__name__)


class ZoneAnalysisTab(QWidget):
    """이미지 파일 + 체크포인트 파일을 직접 열어 추론하는 독립 도구."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._image_path: Path | None = None
        self._ckpt_path: Path | None = None
        self._model: nn.Module | None = None
        self._last_result: InferenceResult | None = None
        self._detected_ids: list[int] = []   # raw_class_map의 배경(0) 제외 고유 클래스 id
        self._build_ui()

    # ── UI 구성 ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # ── 이미지 / 체크포인트 선택 ─────────────────────────────────────────
        file_row = QHBoxLayout()
        self._btn_image = QPushButton("이미지 열기…")
        self._lbl_image = QLabel("선택된 이미지 없음")
        self._lbl_image.setStyleSheet("color:#9ca3af;")
        file_row.addWidget(self._btn_image)
        file_row.addWidget(self._lbl_image, stretch=1)
        root.addLayout(file_row)

        ckpt_row = QHBoxLayout()
        self._btn_ckpt = QPushButton("체크포인트 열기 (.pt)…")
        self._lbl_ckpt = QLabel("선택된 체크포인트 없음")
        self._lbl_ckpt.setStyleSheet("color:#9ca3af;")
        ckpt_row.addWidget(self._btn_ckpt)
        ckpt_row.addWidget(self._lbl_ckpt, stretch=1)
        root.addLayout(ckpt_row)

        self._lbl_model_info = QLabel("")
        self._lbl_model_info.setStyleSheet(
            "color:#9ca3af; font-size:11px; padding:2px 4px;"
            "background:#1a1d23; border-radius:3px;"
        )
        root.addWidget(self._lbl_model_info)

        # ── 커스텀 모델 코드 박스 (preset이 아닌 체크포인트일 때만 노출) ────────
        self._code_box = QGroupBox("모델 아키텍처 코드 (이 체크포인트는 프리셋이 아님)")
        code_layout = QVBoxLayout(self._code_box)
        self._code_editor = QPlainTextEdit()
        self._code_editor.setPlaceholderText(
            "import torch.nn as nn\n\nclass MyModel(nn.Module):\n    ..."
        )
        code_layout.addWidget(self._code_editor)
        code_btn_row = QHBoxLayout()
        self._btn_validate = QPushButton("검증 (Validate)")
        self._btn_load_code = QPushButton("로드 (Load Model)")
        self._btn_load_code.setEnabled(False)
        code_btn_row.addWidget(self._btn_validate)
        code_btn_row.addWidget(self._btn_load_code)
        code_btn_row.addStretch()
        code_layout.addLayout(code_btn_row)
        self._code_log = QTextEdit()
        self._code_log.setReadOnly(True)
        self._code_log.setMaximumHeight(80)
        code_layout.addWidget(self._code_log)
        self._code_box.hide()
        root.addWidget(self._code_box)

        # ── 추론 실행 ────────────────────────────────────────────────────────
        run_row = QHBoxLayout()
        self._btn_run = QPushButton("▶  추론 실행")
        self._btn_run.setStyleSheet("font-weight:bold; padding:4px 12px;")
        run_row.addWidget(self._btn_run)
        run_row.addStretch()
        root.addLayout(run_row)

        # ── 타겟(녹) 클래스 즉석 구성 ────────────────────────────────────────
        target_row = QHBoxLayout()
        target_row.addWidget(QLabel("타겟(녹) 클래스:"))
        self._target_name_edit = QLineEdit()
        self._target_name_edit.setPlaceholderText("클래스 이름 (예: 녹)")
        self._target_name_edit.setFixedWidth(160)
        self._target_name_edit.hide()
        target_row.addWidget(self._target_name_edit)
        self._target_combo = QComboBox()
        self._target_combo.setFixedWidth(200)
        self._target_combo.hide()
        target_row.addWidget(self._target_combo)
        self._lbl_target_info = QLabel("추론을 먼저 실행하세요")
        self._lbl_target_info.setStyleSheet("color:#9ca3af;")
        target_row.addWidget(self._lbl_target_info)
        target_row.addStretch()
        root.addLayout(target_row)

        # ── 캔버스 ───────────────────────────────────────────────────────────
        self._canvas = ZoneCanvas()
        root.addWidget(self._canvas, stretch=1)

        # ── 시그널 ───────────────────────────────────────────────────────────
        self._btn_image.clicked.connect(self._on_select_image)
        self._btn_ckpt.clicked.connect(self._on_select_checkpoint)
        self._btn_validate.clicked.connect(self._on_validate)
        self._btn_load_code.clicked.connect(self._on_load_code)
        self._btn_run.clicked.connect(self._on_run)
        self._target_name_edit.editingFinished.connect(self._on_target_changed)
        self._target_combo.currentIndexChanged.connect(self._on_target_changed)

    # ── 슬롯 — 이미지 / 체크포인트 선택 ─────────────────────────────────────

    def _on_select_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "이미지 선택", "",
            "Images (*.jpg *.jpeg *.png *.bmp *.tiff *.tif)"
        )
        if not path:
            return
        self._image_path = Path(path)
        self._lbl_image.setText(self._image_path.name)
        self._lbl_image.setStyleSheet("color:#e5e7eb;")

    def _on_select_checkpoint(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "체크포인트 선택", "", "Checkpoint (*.pt)"
        )
        if not path:
            return
        self._ckpt_path = Path(path)
        self._lbl_ckpt.setText(self._ckpt_path.name)
        self._lbl_ckpt.setStyleSheet("color:#e5e7eb;")
        self._model = None
        self._code_box.hide()

        meta = load_checkpoint_meta(self._ckpt_path)
        label = model_source_label(meta.model_source)

        if meta.model_source.startswith("preset:"):
            model = load_model_from_ckpt(self._ckpt_path)
            if model is not None:
                self._model = model
                self._lbl_model_info.setText(f"{label}  (자동 준비됨)")
                self._lbl_model_info.setStyleSheet(
                    "color:#34d399; font-size:11px; padding:2px 4px;"
                )
            else:
                self._lbl_model_info.setText(f"{label} 프리셋 로드 실패 — 아래에 코드를 붙여넣으세요")
                self._lbl_model_info.setStyleSheet(
                    "color:#f87171; font-size:11px; padding:2px 4px;"
                )
                self._code_box.show()
        else:
            reason = "사용자 정의 모델" if meta.model_source == "loaded" else "모델 정보 없는 체크포인트"
            self._lbl_model_info.setText(
                f"{reason} — 이 체크포인트를 학습한 모델 코드를 아래에 붙여넣고 Validate → Load 하세요"
            )
            self._lbl_model_info.setStyleSheet(
                "color:#fbbf24; font-size:11px; padding:2px 4px;"
            )
            self._code_box.show()

    # ── 슬롯 — 커스텀 모델 코드 (Validate → Load, save_user_code 호출 안 함) ──

    def _on_validate(self) -> None:
        code = self._code_editor.toPlainText().strip()
        self._code_log.clear()
        if not code:
            self._log_code("[WARN] 코드가 비어 있습니다.", "#fbbf24")
            return
        result = validate(code)
        for err in result.errors:
            self._log_code(f"[ERR] {err}", "#f87171")
        for warn in result.warnings:
            self._log_code(f"[WARN] {warn}", "#fbbf24")
        if result.ok:
            self._log_code(f"[OK] 검증 통과 — 클래스: {result.model_class_name}", "#10b981")
            self._btn_load_code.setEnabled(True)
        else:
            self._log_code(f"[ERR] 검증 실패 — {len(result.errors)}개 오류", "#f87171")
            self._btn_load_code.setEnabled(False)

    def _on_load_code(self) -> None:
        code = self._code_editor.toPlainText().strip()
        result = load_from_code(code)   # save_user_code() 호출하지 않음 — 세션 메모리에만 유지
        if not result.ok:
            self._log_code(f"[ERR] 로드 실패: {result.error}", "#f87171")
            return
        self._model = result.model
        self._log_code(
            f"[OK] 로드 완료 — 클래스: {result.class_name}  파라미터: {result.num_params:,}",
            "#10b981",
        )
        self._lbl_model_info.setText(f"{result.class_name}  (커스텀 모델 로드됨)")
        self._lbl_model_info.setStyleSheet(
            "color:#34d399; font-size:11px; padding:2px 4px;"
        )

    def _log_code(self, msg: str, color: str) -> None:
        self._code_log.append(f'<span style="color:{color}">{msg}</span>')

    # ── 슬롯 — 추론 실행 ──────────────────────────────────────────────────────

    def _on_run(self) -> None:
        if self._image_path is None:
            QMessageBox.warning(self, "이미지 없음", "이미지를 먼저 선택하세요.")
            return
        if self._ckpt_path is None:
            QMessageBox.warning(self, "체크포인트 없음", "체크포인트를 먼저 선택하세요.")
            return
        if self._model is None:
            QMessageBox.warning(
                self, "모델 없음",
                "모델이 준비되지 않았습니다. 프리셋이 아닌 체크포인트라면 코드를 "
                "붙여넣고 Validate → Load 하세요.",
            )
            return

        self._btn_run.setEnabled(False)
        self._btn_run.setText("추론 중…")
        try:
            # 1차 실행 — classes=None (프로젝트 classes.json과 무관, raw_class_map 확보용)
            result = engine.run(
                model=self._model,
                image_path=self._image_path,
                checkpoint_path=self._ckpt_path,
                opacity=0.5,
                classes=None,
            )
            self._last_result = result
            self._setup_target_classes(result)
        except Exception as exc:
            log.exception(f"존 분석 추론 실패 — image={self._image_path}, ckpt={self._ckpt_path}")
            QMessageBox.critical(self, "추론 오류", str(exc))
        finally:
            self._btn_run.setEnabled(True)
            self._btn_run.setText("▶  추론 실행")

    # ── 타겟(녹) 클래스 즉석 구성 (판단 4) ────────────────────────────────────

    def _setup_target_classes(self, result: InferenceResult) -> None:
        ids = sorted(int(i) for i in set(result.raw_class_map.ravel().tolist()) if i != 0)
        self._detected_ids = ids

        self._target_name_edit.hide()
        self._target_combo.hide()

        if not ids:
            self._lbl_target_info.setText("배경 외 클래스가 검출되지 않았습니다.")
            self._canvas.set_pixmap(result.overlay_pixmap)
            return

        if len(ids) == 1:
            self._target_name_edit.blockSignals(True)
            self._target_name_edit.setText("class_1")
            self._target_name_edit.blockSignals(False)
            self._target_name_edit.show()
            self._lbl_target_info.setText(f"클래스 1개 검출됨 (id={ids[0]}) — 이름 수정 가능")
        else:
            self._target_combo.blockSignals(True)
            self._target_combo.clear()
            for i, cid in enumerate(ids):
                self._target_combo.addItem(f"class_{i + 1} (id={cid})", cid)
            self._target_combo.blockSignals(False)
            self._target_combo.show()
            self._lbl_target_info.setText(f"클래스 {len(ids)}개 검출됨 — 타겟을 선택하세요")

        self._on_target_changed()

    def _on_target_changed(self) -> None:
        if self._last_result is None or not self._detected_ids:
            return

        if len(self._detected_ids) == 1:
            cid = self._detected_ids[0]
            name = self._target_name_edit.text().strip() or "class_1"
        else:
            cid = self._target_combo.currentData()
            if cid is None:
                return
            idx = self._target_combo.currentIndex()
            name = f"class_{idx + 1}"

        classes = [
            ClassDef(0, "background", DEFAULT_PALETTE[0]),
            ClassDef(cid, name, DEFAULT_PALETTE[cid % len(DEFAULT_PALETTE)]),
        ]
        try:
            result = engine.refilter(
                self._last_result.raw_class_map,
                self._last_result.confidence_map,
                self._image_path,
                min_confidence=0.0,
                min_pixel_size=0,
                opacity=0.5,
                classes=classes,
            )
            self._last_result = result
            self._canvas.set_pixmap(result.overlay_pixmap)
        except Exception as exc:
            log.exception("존 분석 타겟 클래스 재필터링 실패")
            QMessageBox.critical(self, "재필터링 오류", str(exc))
