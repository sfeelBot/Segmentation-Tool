"""오토 라벨링 다이얼로그 — 빠른 학습 모드 + 기존 체크포인트 모드 (두 탭)."""
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QCheckBox, QProgressBar,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QWidget, QTabWidget, QComboBox, QGroupBox,
)
from PyQt6.QtCore import Qt

from app.core.inference_engine import list_checkpoints, load_checkpoint_meta, CheckpointMeta
from app.core.auto_labeler import (
    AutoLabelWorker, collect_unlabeled, collect_all_images, commit_results,
)
from app.widgets.auto_label_preview_dialog import AutoLabelPreviewDialog
from app.core.annotation_store import load_classes, load as load_ann
from app.core.trainer import TrainerWorker, TrainingConfig
from app.core.model_loader import load_from_code
from app.core.device_info import prompt_gpu_availability
from app.core.logger import get_logger
from app.core import project as _project
from app.model_presets import PRESETS, preset_by_key, load_preset_code

log = get_logger(__name__)

# ── 빠른 학습 모드 고정 하이퍼파라미터 ───────────────────────────────────────
QUICK_EPOCHS      = 30
QUICK_BATCH       = 4
QUICK_LR          = 1e-4
QUICK_IMG_SIZE    = 512
QUICK_CKPT_PREFIX = "autolabel_bootstrap"


class AutoLabelDialog(QDialog):
    def __init__(self, model, parent=None) -> None:
        super().__init__(parent)
        self._model = model   # 기존 모드에서 사용 (user-loaded)
        self._worker: AutoLabelWorker | None = None
        self._trainer: TrainerWorker | None = None
        self._quick_trained_ckpt: Path | None = None
        self._quick_trained_model = None
        self._ckpt_metas: list[CheckpointMeta] = []
        self.setWindowTitle("✨ 오토 라벨링")
        self.setMinimumSize(620, 500)
        self._build_ui()
        self._refresh_checkpoints()
        self._refresh_counts()

    # ── UI ───────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(8)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_quick_tab(),    "🚀  빠른 학습 + 자동 라벨링")
        self._tabs.addTab(self._build_existing_tab(), "📂  기존 체크포인트 사용")
        root.addWidget(self._tabs)

        # ── 공용 진행 상태 ───────────────────────────────────────────────────
        self._lbl_status = QLabel("대기 중")
        self._lbl_status.setStyleSheet("color:#9ca3af;")
        root.addWidget(self._lbl_status)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        root.addWidget(self._progress)

        # ── 공용 버튼 ─────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._btn_start  = QPushButton("▶  시작")
        self._btn_start.setStyleSheet("background:#065f46; font-weight:bold; padding:6px 14px;")
        self._btn_cancel = QPushButton("■ 중지")
        self._btn_cancel.setEnabled(False)
        self._btn_close  = QPushButton("닫기")
        btn_row.addWidget(self._btn_start)
        btn_row.addWidget(self._btn_cancel)
        btn_row.addWidget(self._btn_close)
        root.addLayout(btn_row)

        self._btn_start.clicked.connect(self._on_start)
        self._btn_cancel.clicked.connect(self._on_cancel)
        self._btn_close.clicked.connect(self.reject)

    def _build_quick_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(10)

        info = QLabel(
            "📝  라벨링된 이미지만으로 빠르게 학습한 뒤,\n"
            "     아직 라벨링 안 된 이미지에 자동으로 어노테이션을 생성합니다."
        )
        info.setStyleSheet("color:#cbd5e1;")
        lay.addWidget(info)

        count_box = QGroupBox("📊  현재 프로젝트 이미지 현황")
        cl = QVBoxLayout(count_box)
        self._lbl_counts = QLabel("— / —")
        self._lbl_counts.setStyleSheet("font-size:13px; color:#60a5fa;")
        cl.addWidget(self._lbl_counts)
        lay.addWidget(count_box)

        model_box = QGroupBox("🧠  학습할 모델")
        ml = QVBoxLayout(model_box)
        self._quick_model = QComboBox()
        for p in PRESETS:
            self._quick_model.addItem(p.title, f"preset:{p.key}")
        # 기본: 경량 모델 (U-Net)
        ml.addWidget(self._quick_model)
        hint_m = QLabel("⚠️ 학습이 매번 새로 시작됩니다 (프리셋 = fresh weights)")
        hint_m.setStyleSheet("color:#9ca3af; font-size:11px;")
        ml.addWidget(hint_m)
        lay.addWidget(model_box)

        cfg_box = QGroupBox("⚙️  고정 학습 설정")
        cl2 = QVBoxLayout(cfg_box)
        cfg_text = QLabel(
            f"• Epochs: <b>{QUICK_EPOCHS}</b>\n"
            f"• Batch Size: <b>{QUICK_BATCH}</b>\n"
            f"• Learning Rate: <b>{QUICK_LR:.0e}</b>\n"
            f"• Image Size: <b>{QUICK_IMG_SIZE}×{QUICK_IMG_SIZE}</b>\n"
            f"• 학습 데이터: 어노테이션이 있는 이미지만 자동 사용"
        )
        cfg_text.setStyleSheet("color:#e5e7eb; font-size:12px;")
        cfg_text.setTextFormat(Qt.TextFormat.RichText)
        cl2.addWidget(cfg_text)
        lay.addWidget(cfg_box)

        lay.addStretch()
        return w

    def _build_existing_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(8)

        hdr = QHBoxLayout()
        hdr.addWidget(QLabel("체크포인트 선택"))
        hdr.addStretch()
        self._btn_refresh = QPushButton("↺")
        self._btn_refresh.setFixedWidth(28)
        self._btn_refresh.clicked.connect(self._refresh_checkpoints)
        hdr.addWidget(self._btn_refresh)
        lay.addLayout(hdr)

        self._ckpt_table = QTableWidget(0, 4)
        self._ckpt_table.setHorizontalHeaderLabels(["파일명", "Epoch", "Val Loss", "IoU"])
        self._ckpt_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._ckpt_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._ckpt_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        th = self._ckpt_table.horizontalHeader()
        th.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in (1, 2, 3):
            th.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        lay.addWidget(self._ckpt_table, stretch=1)

        self._chk_unlabeled = QCheckBox("미라벨 이미지만 (어노테이션 없는 이미지)")
        self._chk_unlabeled.setChecked(True)
        lay.addWidget(self._chk_unlabeled)
        return w

    # ── 카운트 갱신 ────────────────────────────────────────────────────────

    def _refresh_counts(self) -> None:
        img_dir = _project.images_dir()
        exts = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"}
        total = [p for p in img_dir.iterdir() if p.is_file() and p.suffix.lower() in exts] if img_dir.exists() else []
        labeled = [p for p in total if load_ann(p)]
        unlabeled = [p for p in total if not load_ann(p)]
        self._lbl_counts.setText(
            f"전체 {len(total)}개  ·  🏷 라벨링됨 {len(labeled)}개  ·  ⬜ 미라벨 {len(unlabeled)}개"
        )

    def _refresh_checkpoints(self) -> None:
        self._ckpt_metas = [load_checkpoint_meta(p) for p in list_checkpoints()]
        self._ckpt_table.setRowCount(0)
        for meta in self._ckpt_metas:
            row = self._ckpt_table.rowCount()
            self._ckpt_table.insertRow(row)
            self._ckpt_table.setItem(row, 0, QTableWidgetItem(meta.path.name))
            self._ckpt_table.setItem(row, 1, QTableWidgetItem(
                str(meta.epoch) if meta.epoch else "—"))
            self._ckpt_table.setItem(row, 2, QTableWidgetItem(
                f"{meta.val_loss:.4f}" if meta.val_loss == meta.val_loss else "—"))
            self._ckpt_table.setItem(row, 3, QTableWidgetItem(
                f"{meta.mean_iou:.4f}" if meta.mean_iou == meta.mean_iou else "—"))
        if self._ckpt_metas:
            self._ckpt_table.selectRow(len(self._ckpt_metas) - 1)

    # ── 시작 디스패치 ─────────────────────────────────────────────────────────

    def _on_start(self) -> None:
        if not prompt_gpu_availability(self, "오토 라벨링"):
            return
        if self._tabs.currentIndex() == 0:
            self._start_quick_train()
        else:
            self._start_existing_ckpt()

    # ── 모드 1: 빠른 학습 + 자동 라벨링 ─────────────────────────────────────

    def _start_quick_train(self) -> None:
        # 라벨링된 이미지 수 체크
        img_dir = _project.images_dir()
        exts = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"}
        labeled = [p for p in img_dir.iterdir()
                   if p.is_file() and p.suffix.lower() in exts and load_ann(p)]
        if len(labeled) < 3:
            QMessageBox.warning(self, "데이터 부족",
                f"라벨링된 이미지가 최소 3장 이상 필요합니다 (현재 {len(labeled)}개).\n"
                f"라벨링 탭에서 몇 장 더 어노테이션 해주세요.")
            return

        # 모델 인스턴스화 (프리셋에서 fresh)
        src = self._quick_model.currentData()
        key = src[len("preset:"):] if src.startswith("preset:") else src
        code = load_preset_code(key)
        if not code:
            QMessageBox.critical(self, "프리셋 오류", f"'{key}' 프리셋을 찾을 수 없습니다.")
            return
        result = load_from_code(code)
        if not result.ok:
            QMessageBox.critical(self, "모델 로드 실패", result.error or "알 수 없는 오류")
            return
        self._quick_trained_model = result.model
        info = preset_by_key(key)

        # 학습 설정
        cfg = TrainingConfig(
            epochs          = QUICK_EPOCHS,
            batch_size      = QUICK_BATCH,
            image_w         = QUICK_IMG_SIZE,
            image_h         = QUICK_IMG_SIZE,
            lr              = QUICK_LR,
            optimizer       = "Adam",
            loss_fn         = "CrossEntropyLoss",
            mixed_precision = True,
            device          = "auto",
            checkpoint_every= QUICK_EPOCHS,   # 마지막 epoch 에만 저장
            val_split       = 0.2 if len(labeled) >= 5 else 0.1,
            num_workers     = 0,
        )

        num_classes = len(load_classes())
        self._progress.setMaximum(QUICK_EPOCHS)
        self._progress.setValue(0)
        self._lbl_status.setText(
            f"🎯 '{info.title if info else key}' 학습 중… (데이터 {len(labeled)}장, "
            f"{QUICK_EPOCHS} epochs)"
        )
        self._btn_start.setEnabled(False)
        self._btn_cancel.setEnabled(True)

        self._trainer = TrainerWorker(
            self._quick_trained_model, cfg, num_classes,
            ckpt_prefix=QUICK_CKPT_PREFIX,
        )
        self._trainer.epoch_done.connect(self._on_quick_epoch)
        self._trainer.checkpoint_saved.connect(self._on_quick_ckpt_saved)
        self._trainer.training_finished.connect(self._on_quick_trained)
        self._trainer.training_error.connect(self._on_quick_train_error)
        self._trainer.start()

    def _on_quick_epoch(self, epoch: int, train_loss: float,
                        val_loss: float, metrics: dict) -> None:
        self._progress.setValue(epoch)
        iou = metrics.get("mean_iou", 0.0)
        self._lbl_status.setText(
            f"🎯 학습 중  Epoch {epoch}/{QUICK_EPOCHS}  "
            f"train={train_loss:.4f}  val={val_loss:.4f}  IoU={iou:.4f}"
        )

    def _on_quick_ckpt_saved(self, path: str) -> None:
        self._quick_trained_ckpt = Path(path)
        log.info(f"[빠른 학습] 체크포인트 저장: {path}")

    def _on_quick_trained(self) -> None:
        self._trainer = None
        if self._quick_trained_ckpt is None:
            QMessageBox.warning(self, "체크포인트 없음",
                "학습은 끝났지만 체크포인트가 저장되지 않았습니다. 중지된 경우일 수 있습니다.")
            self._btn_start.setEnabled(True)
            self._btn_cancel.setEnabled(False)
            return
        # 학습된 체크포인트로 자동 라벨링 (미라벨만)
        paths = collect_unlabeled()
        if not paths:
            QMessageBox.information(self, "완료",
                "학습은 완료됐지만 라벨링할 미라벨 이미지가 없습니다.")
            self._lbl_status.setText("✅ 학습만 완료")
            self._btn_start.setEnabled(True)
            self._btn_cancel.setEnabled(False)
            self.accept()
            return

        self._progress.setMaximum(len(paths))
        self._progress.setValue(0)
        self._lbl_status.setText(f"🏷 자동 라벨링 중… 0 / {len(paths)}")
        log.info(f"[빠른 학습] 학습 완료 → 자동 라벨링 시작 ({len(paths)}장)")
        self._worker = AutoLabelWorker(
            self._quick_trained_model, self._quick_trained_ckpt, paths,
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_quick_train_error(self, msg: str) -> None:
        self._trainer = None
        self._btn_start.setEnabled(True)
        self._btn_cancel.setEnabled(False)
        log.error(f"[빠른 학습] 실패: {msg}")
        QMessageBox.critical(self, "학습 오류", msg)

    # ── 모드 2: 기존 체크포인트 ────────────────────────────────────────────

    def _start_existing_ckpt(self) -> None:
        ckpt_path = self._get_selected_ckpt()
        if ckpt_path is None:
            QMessageBox.warning(self, "체크포인트 없음",
                "체크포인트를 선택하세요.\n학습 탭에서 먼저 학습을 진행해 주세요.")
            return
        if self._model is None:
            QMessageBox.warning(self, "모델 없음",
                "Model 탭에서 모델을 먼저 로드하세요.")
            return

        paths = (collect_unlabeled() if self._chk_unlabeled.isChecked()
                 else collect_all_images())
        if not paths:
            QMessageBox.information(self, "완료",
                "라벨링할 이미지가 없습니다.")
            return

        self._progress.setMaximum(len(paths))
        self._progress.setValue(0)
        self._lbl_status.setText(f"🏷 자동 라벨링 중… 0 / {len(paths)}")
        self._btn_start.setEnabled(False)
        self._btn_cancel.setEnabled(True)

        self._worker = AutoLabelWorker(self._model, ckpt_path, paths)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    # ── 공용 슬롯 ─────────────────────────────────────────────────────────────

    def _on_cancel(self) -> None:
        if self._trainer:
            self._trainer.request_stop()
        if self._worker:
            self._worker.request_stop()
        self._lbl_status.setText("⏸ 중지 요청 중…")
        self._btn_cancel.setEnabled(False)

    def _on_progress(self, done: int, total: int, name: str) -> None:
        self._progress.setValue(done)
        self._lbl_status.setText(f"🏷 {done} / {total}  {name}")

    def _on_finished(self, count: int, results: list) -> None:
        self._progress.setValue(self._progress.maximum())
        self._lbl_status.setText(f"🔎 {count}개 생성됨 — 미리보기로 확인하세요.")
        log.info(f"오토 라벨링 생성 완료: {count}개 (미리보기 대기)")

        if not results:
            QMessageBox.information(self, "결과 없음",
                "자동 라벨링된 이미지가 없습니다.")
            self._btn_start.setEnabled(True)
            self._btn_cancel.setEnabled(False)
            return

        # 미리보기 팝업 — 사용자가 합치기 여부 결정
        preview = AutoLabelPreviewDialog(results, parent=self)
        if preview.exec():
            saved = commit_results(results)
            self._lbl_status.setText(f"✅ 프로젝트에 저장됨 — {saved}개 이미지")
            log.info(f"오토 라벨링 적용: {saved}개 저장")
            self.accept()
        else:
            self._lbl_status.setText("❌ 취소됨 — 저장하지 않았습니다.")
            log.info("오토 라벨링 취소 (사용자가 합치기 거부)")
            self._btn_start.setEnabled(True)
            self._btn_cancel.setEnabled(False)

    def _on_error(self, msg: str) -> None:
        self._btn_start.setEnabled(True)
        self._btn_cancel.setEnabled(False)
        log.error(f"오토 라벨링 실패: {msg}")
        QMessageBox.critical(self, "오토 라벨링 오류", msg)

    # ── 내부 ─────────────────────────────────────────────────────────────────

    def _get_selected_ckpt(self) -> Path | None:
        rows = self._ckpt_table.selectionModel().selectedRows()
        if not rows:
            return None
        idx = rows[0].row()
        if 0 <= idx < len(self._ckpt_metas):
            return self._ckpt_metas[idx].path
        return None
