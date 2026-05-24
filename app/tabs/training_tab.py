"""학습 탭 — 다중 학습 작업 큐 + 진행 상황 팝업."""
import time
from dataclasses import dataclass, field
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QScrollArea,
    QPushButton, QLabel, QProgressBar, QTableWidget,
    QTableWidgetItem, QSizePolicy, QMessageBox, QListWidget,
    QListWidgetItem, QLineEdit, QGroupBox, QComboBox,
)
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtCore import Qt

from app.core.trainer import TrainerWorker, TrainingConfig
from app.core.annotation_store import load_classes
from app.core.logger import get_logger
from app.core.i18n import t
from app.core.model_loader import load_from_code
from app.core.device_info import prompt_gpu_availability
from app.core.cuda_diag import run_cuda_diagnostics, DiagStatus
from app.widgets.cuda_diag_dialog import show_cuda_diag
from app.model_presets import PRESETS, preset_by_key, load_preset_code
from app.widgets.config_form import ConfigForm
from app.widgets.loss_chart import LossChart
from app.widgets.training_progress_dialog import (
    TrainingProgressDialog, STATUS_ICON, STATUS_COLOR, _fmt_time,
)

log = get_logger(__name__)


def _fmt_step_eta(seconds: float) -> str:
    if seconds <= 0 or seconds != seconds:
        return "--:--"
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _model_source_label(source: str) -> str:
    if source == "loaded":
        return "현재 로드됨"
    if source.startswith("preset:"):
        key = source[len("preset:"):]
        info = preset_by_key(key)
        return info.title if info else key
    return source


@dataclass
class TrainingJob:
    name: str
    config: TrainingConfig
    model_source: str = "loaded"       # "loaded" | "preset:<key>"
    status: str = "waiting"            # waiting | running | done | error | stopped
    epochs_done: int = 0
    epoch_times: list = field(default_factory=list)
    last_metrics: dict = field(default_factory=dict)
    last_train_loss: float = 0.0
    last_val_loss: float = 0.0

    @property
    def avg_epoch_time(self) -> float:
        return sum(self.epoch_times) / len(self.epoch_times) if self.epoch_times else 0.0

    @property
    def eta_seconds(self) -> float:
        remaining = max(0, self.config.epochs - self.epochs_done)
        return remaining * self.avg_epoch_time


class TrainingTab(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._jobs: list[TrainingJob] = []
        self._running_idx: int | None = None
        self._queue_active: bool = False
        self._queue_stop_all: bool = False
        self._worker: TrainerWorker | None = None
        self._dialog: TrainingProgressDialog | None = None
        self._job_counter = 0
        # Step 추적 (patch training ETA 정확도 향상)
        self._total_batches: int = 1
        self._total_steps: int = 1
        self._current_step: int = 0
        self._train_start_time: float = 0.0
        self._cuda_diag_result = run_cuda_diagnostics()   # 탭 초기화 시 1회 진단
        self._build_ui()

    # ── UI 구성 ──────────────────────────────────────────────────────────────

    def _build_cuda_banner(self) -> QWidget:
        """CUDA 가용 여부를 한 줄로 표시하는 배너. 클릭 시 상세 진단 팝업."""
        r = self._cuda_diag_result
        banner = QWidget()
        banner.setFixedHeight(32)
        row = QHBoxLayout(banner)
        row.setContentsMargins(10, 0, 4, 0)
        row.setSpacing(8)

        if r.cuda_available:
            # 사용 가능한 GPU 이름 수집
            gpu_items = [it for it in r.items if it.name.startswith("GPU [")]
            gpu_str = "  |  ".join(it.value.split("—")[0].strip() for it in gpu_items) or "GPU"
            lbl = QLabel(f"CUDA  {gpu_str}")
            lbl.setStyleSheet("color:#6ddf6d; font-size:11px; font-weight:bold;")
            banner.setStyleSheet("background:#0d1f0d; border-radius:4px;")
        else:
            lbl = QLabel(f"CUDA 사용 불가  |  {r.root_cause}")
            lbl.setStyleSheet("color:#f87171; font-size:11px; font-weight:bold;")
            banner.setStyleSheet("background:#1f0d0d; border-radius:4px;")

        row.addWidget(lbl, stretch=1)

        btn_diag = QPushButton("진단 보기")
        btn_diag.setFixedHeight(22)
        btn_diag.setStyleSheet(
            "font-size:11px; padding:0 8px; border:1px solid #4b5563; border-radius:3px;"
        )
        btn_diag.setToolTip("CUDA / GPU 환경 진단 결과를 봅니다")
        btn_diag.clicked.connect(lambda: show_cuda_diag(self, self._cuda_diag_result))
        row.addWidget(btn_diag)

        return banner

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(8)

        # ── 왼쪽: 설정 폼 ─────────────────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(300)
        self._config_form = ConfigForm()
        scroll.setWidget(self._config_form)
        root.addWidget(scroll)

        # ── 오른쪽: 큐 + 모니터링 ────────────────────────────────────────────
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setSpacing(8)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # ── CUDA 상태 배너 ────────────────────────────────────────────────────
        self._cuda_banner = self._build_cuda_banner()
        right_layout.addWidget(self._cuda_banner)

        # ── 큐 관리 그룹 ─────────────────────────────────────────────────────
        queue_box = QGroupBox(t("train.queue"))
        queue_layout = QVBoxLayout(queue_box)

        # 이름 + 모델 + 추가 행
        add_row = QHBoxLayout()
        add_row.addWidget(QLabel(t("train.job_name")))
        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText("예: 학습1")
        self._name_input.setFixedWidth(150)
        add_row.addWidget(self._name_input)

        add_row.addWidget(QLabel(t("train.model_label")))
        self._model_combo = QComboBox()
        self._model_combo.setMinimumWidth(220)
        self._model_combo.addItem("🧠 현재 로드된 모델", "loaded")
        for p in PRESETS:
            self._model_combo.addItem(p.title, f"preset:{p.key}")
        add_row.addWidget(self._model_combo, stretch=1)

        self._btn_add_job = QPushButton(t("train.add"))
        self._btn_add_job.setStyleSheet(
            "background:#1e3a5f; font-weight:bold; padding:4px 12px;"
        )
        self._btn_add_job.clicked.connect(self._on_add_job)
        add_row.addWidget(self._btn_add_job)
        queue_layout.addLayout(add_row)

        # 큐 목록
        self._queue_list = QListWidget()
        self._queue_list.setAlternatingRowColors(True)
        self._queue_list.setMaximumHeight(140)
        queue_layout.addWidget(self._queue_list)

        # 큐 제어 버튼
        ctrl_row = QHBoxLayout()
        self._btn_start_all = QPushButton(t("train.run_all"))
        self._btn_start_all.setStyleSheet(
            "background:#065f46; font-weight:bold; padding:6px 14px;"
        )
        self._btn_stop      = QPushButton(t("train.stop"))
        self._btn_stop.setEnabled(False)
        self._btn_show_dlg  = QPushButton(t("train.progress_window"))
        self._btn_remove    = QPushButton(t("train.remove"))
        self._btn_clear     = QPushButton(t("train.clear_queue"))
        self._btn_start_all.clicked.connect(self._on_start_queue)
        self._btn_stop.clicked.connect(self._on_stop)
        self._btn_show_dlg.clicked.connect(self._on_show_dialog)
        self._btn_remove.clicked.connect(self._on_remove_job)
        self._btn_clear.clicked.connect(self._on_clear_queue)

        ctrl_row.addWidget(self._btn_start_all)
        ctrl_row.addWidget(self._btn_stop)
        ctrl_row.addWidget(self._btn_show_dlg)
        ctrl_row.addStretch()
        ctrl_row.addWidget(self._btn_remove)
        ctrl_row.addWidget(self._btn_clear)
        queue_layout.addLayout(ctrl_row)

        # 전체 ETA
        self._lbl_total_eta = QLabel(t("train.total_eta"))
        self._lbl_total_eta.setStyleSheet("color:#93c5fd; font-weight:bold;")
        queue_layout.addWidget(self._lbl_total_eta)

        right_layout.addWidget(queue_box)

        # ── 현재 학습 상태 ───────────────────────────────────────────────────
        # Epoch 진행바
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setFormat("Epoch %v / %m")
        right_layout.addWidget(self._progress)

        # 상태 + Step 카운터 행
        status_row = QHBoxLayout()
        self._lbl_status = QLabel(t("train.waiting"))
        self._lbl_status.setStyleSheet("color:#cbd5e1; font-size:12px;")
        self._lbl_step = QLabel("")
        self._lbl_step.setStyleSheet(
            "color:#93c5fd; font-size:11px; font-family:Consolas; padding:0 6px;"
        )
        status_row.addWidget(self._lbl_status, stretch=1)
        status_row.addWidget(self._lbl_step, stretch=0)
        right_layout.addLayout(status_row)

        # ── 그래프 (좌) + 메트릭·체크포인트 (우) 수평 분할 ─────────────────
        from PyQt6.QtWidgets import QSplitter
        h_splitter = QSplitter(Qt.Orientation.Horizontal)

        # 좌: 손실 그래프 (Y축 최대 활용)
        chart_box = QGroupBox(t("train.chart_title"))
        chart_layout = QVBoxLayout(chart_box)
        chart_layout.setContentsMargins(4, 4, 4, 4)
        self._chart = LossChart()
        self._chart.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        chart_layout.addWidget(self._chart)
        h_splitter.addWidget(chart_box)

        # 우: 컴팩트 메트릭 + 체크포인트 (좁은 패널)
        side_panel = QWidget()
        side_panel.setMinimumWidth(150)
        side_panel.setMaximumWidth(220)
        side_layout = QVBoxLayout(side_panel)
        side_layout.setContentsMargins(4, 0, 0, 0)
        side_layout.setSpacing(4)

        # 메트릭 (3열 — Epoch / Val / IoU)
        side_layout.addWidget(QLabel(t("train.metrics_title")))
        self._metrics_table = QTableWidget(0, 3)
        self._metrics_table.setHorizontalHeaderLabels(["Ep", "Val", "IoU"])
        self._metrics_table.setStyleSheet("font-size:10px;")
        self._metrics_table.horizontalHeader().setStyleSheet("font-size:10px;")
        self._metrics_table.horizontalHeader().setStretchLastSection(True)
        self._metrics_table.verticalHeader().setVisible(False)
        self._metrics_table.verticalHeader().setDefaultSectionSize(18)
        self._metrics_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        side_layout.addWidget(self._metrics_table, stretch=1)

        # 체크포인트
        side_layout.addWidget(QLabel(t("train.ckpt_title")))
        self._ckpt_list = QListWidget()
        self._ckpt_list.setStyleSheet("font-size:10px;")
        side_layout.addWidget(self._ckpt_list, stretch=1)

        h_splitter.addWidget(side_panel)
        h_splitter.setSizes([10000, 180])   # 기본: 그래프 최대, 사이드 180px
        h_splitter.setStretchFactor(0, 1)
        h_splitter.setStretchFactor(1, 0)

        right_layout.addWidget(h_splitter, stretch=1)

        root.addWidget(right, stretch=1)

    # ── 큐 관리 슬롯 ──────────────────────────────────────────────────────────

    def _on_add_job(self) -> None:
        name = self._name_input.text().strip()
        if not name:
            self._job_counter += 1
            name = f"학습{self._job_counter}"
        else:
            # 중복 이름 방지
            existing = {j.name for j in self._jobs}
            if name in existing:
                QMessageBox.warning(self, "중복 이름",
                    f"'{name}' 이라는 이름의 작업이 이미 있습니다.")
                return
        cfg = self._config_form.get_config()
        model_source = self._model_combo.currentData() or "loaded"
        self._jobs.append(TrainingJob(
            name=name, config=cfg, model_source=model_source,
        ))
        self._name_input.clear()
        self._refresh_queue_list()

    def _on_remove_job(self) -> None:
        row = self._queue_list.currentRow()
        if row < 0 or row >= len(self._jobs):
            return
        job = self._jobs[row]
        if job.status == "running":
            QMessageBox.warning(self, "삭제 불가",
                "실행 중인 작업은 중지 후 삭제할 수 있습니다.")
            return
        del self._jobs[row]
        self._refresh_queue_list()

    def _on_clear_queue(self) -> None:
        if self._queue_active:
            QMessageBox.warning(self, "초기화 불가",
                "큐가 실행 중입니다. 먼저 중지하세요.")
            return
        reply = QMessageBox.question(
            self, "전체 초기화", "큐의 모든 작업을 삭제하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._jobs.clear()
            self._job_counter = 0
            self._refresh_queue_list()

    def _refresh_queue_list(self) -> None:
        self._queue_list.clear()
        for job in self._jobs:
            icon = STATUS_ICON.get(job.status, "•")
            color = STATUS_COLOR.get(job.status, "#cccccc")
            model_lbl = _model_source_label(job.model_source)
            text = (f"{icon}  {job.name}  🧠 {model_lbl}   "
                    f"[epochs={job.config.epochs}, bs={job.config.batch_size}, "
                    f"lr={job.config.lr:.1e}]   "
                    f"({job.epochs_done}/{job.config.epochs})")
            if job.status == "running":
                text += f"   ETA {_fmt_time(job.eta_seconds)}"
            item = QListWidgetItem(text)
            item.setForeground(QColor(color))
            self._queue_list.addItem(item)
        self._update_total_eta()

    def _update_total_eta(self) -> None:
        total = 0.0
        for job in self._jobs:
            if job.status in ("waiting", "running"):
                # waiting 은 avg_epoch_time 없음 — 임시로 running 평균 사용
                avg = job.avg_epoch_time
                if avg == 0 and self._running_idx is not None:
                    avg = self._jobs[self._running_idx].avg_epoch_time
                remaining = max(0, job.config.epochs - job.epochs_done)
                total += remaining * avg
        self._lbl_total_eta.setText(
            f"⏱️  전체 예상 시간: {_fmt_time(total) if total > 0 else '—'}"
        )

    # ── 큐 실행 슬롯 ──────────────────────────────────────────────────────────

    def _on_start_queue(self) -> None:
        if not self._jobs:
            QMessageBox.information(self, "큐 비어있음",
                "'➕ 큐에 추가' 로 먼저 학습 작업을 추가하세요.")
            return
        # '현재 로드됨' 을 쓰는 작업이 있는데 모델이 없으면 경고
        needs_loaded = any(j.model_source == "loaded" for j in self._jobs
                           if j.status == "waiting")
        if needs_loaded and self._get_model() is None:
            QMessageBox.warning(self, "모델 없음",
                "'🧠 현재 로드된 모델' 을 사용하는 작업이 있습니다.\n"
                "Model 탭에서 모델을 먼저 로드하거나, 각 작업의 모델을 프리셋으로 바꾸세요.")
            return
        # GPU 가용성 확인 — 사용 불가 시 CPU 로 계속할지 팝업
        if not prompt_gpu_availability(self, "학습"):
            return
        if self._queue_active:
            return
        self._queue_active = True
        self._queue_stop_all = False
        self._btn_start_all.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._show_dialog()
        self._run_next_job()

    def _run_next_job(self) -> None:
        # 다음 waiting 작업 찾기
        next_idx = None
        for i, job in enumerate(self._jobs):
            if job.status == "waiting":
                next_idx = i
                break

        if next_idx is None or self._queue_stop_all:
            self._queue_active = False
            self._running_idx = None
            self._btn_start_all.setEnabled(True)
            self._btn_stop.setEnabled(False)
            if self._dialog:
                self._dialog.set_done()
                self._dialog.update_queue(self._jobs)
            self._lbl_status.setText("✅ 모든 학습 완료")
            return

        job = self._jobs[next_idx]
        try:
            model = self._resolve_model_for_job(job)
        except Exception as e:
            log.error(f"'{job.name}' 모델 로드 실패: {e}")
            job.status = "error"
            self._refresh_queue_list()
            QMessageBox.critical(self, "모델 로드 실패",
                f"'{job.name}' 작업의 모델을 준비할 수 없습니다:\n\n{e}\n\n다음 작업으로 진행합니다.")
            self._run_next_job()
            return

        self._running_idx = next_idx
        job.status = "running"
        job.epoch_times = []
        job.epochs_done = 0
        classes = load_classes()
        num_classes = len(classes)

        self._chart.reset()
        self._metrics_table.setRowCount(0)
        self._progress.setMaximum(job.config.epochs)
        self._progress.setValue(0)
        self._lbl_status.setText(f"🎯 '{job.name}' 학습 중…")

        if self._dialog:
            self._dialog.reset_running_state()
            self._dialog.set_current_job(job.name, job.config.epochs)

        self._worker = TrainerWorker(model, job.config, num_classes,
                                     ckpt_prefix=job.name, model_source=job.model_source)
        self._worker.training_started.connect(self._on_training_started)
        self._worker.batch_done.connect(self._on_batch_done)
        self._worker.epoch_done.connect(self._on_epoch_done)
        self._worker.checkpoint_saved.connect(self._on_checkpoint_saved)
        self._worker.training_finished.connect(self._on_job_finished)
        self._worker.training_error.connect(self._on_job_error)
        self._worker.start()
        self._refresh_queue_list()

    def _on_stop(self) -> None:
        """현재 작업 중지. 큐 전체 중지 여부 확인."""
        if not self._worker:
            return
        reply = QMessageBox.question(
            self, "중지",
            "전체 큐를 중지하시겠습니까?\n\n예: 전체 중지\n아니오: 현재 작업만 중지하고 다음으로 진행",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Cancel:
            return
        self._queue_stop_all = (reply == QMessageBox.StandardButton.Yes)
        self._worker.request_stop()
        self._lbl_status.setText("⏸️ 중지 요청됨…")

    # ── Worker 시그널 슬롯 ────────────────────────────────────────────────────

    def _on_training_started(self, total_batches: int, total_epochs: int) -> None:
        """DataLoader 준비 완료 — step 추적 초기화."""
        import time
        self._total_batches   = max(1, total_batches)
        self._total_steps     = max(1, total_batches * total_epochs)
        self._current_step    = 0
        self._train_start_time = time.monotonic()
        self._lbl_step.setText(f"Step 0 / {self._total_steps:,}")

    def _on_batch_done(self, epoch: int, batch_idx: int, loss: float) -> None:
        """배치마다 train loss 를 EMA 스무딩 후 차트에 실시간 반영.
        Step 카운터와 스텝 기반 ETA 도 갱신."""
        import time
        frac = (epoch - 1) + (batch_idx + 1) / self._total_batches
        self._chart.append_batch(frac, loss)

        self._current_step = (epoch - 1) * self._total_batches + (batch_idx + 1)

        # Step 라벨 — 매 10 스텝마다 갱신 (너무 잦은 UI 업데이트 방지)
        if self._current_step % 10 == 0 or self._current_step == self._total_steps:
            elapsed = time.monotonic() - self._train_start_time
            if elapsed > 0 and self._current_step > 0:
                sps = self._current_step / elapsed             # steps/sec
                remain = self._total_steps - self._current_step
                eta_sec = remain / sps if sps > 0 else 0
                eta_str = _fmt_step_eta(eta_sec)
                self._lbl_step.setText(
                    f"Step {self._current_step:,} / {self._total_steps:,}"
                    f"  ·  ETA {eta_str}"
                )

            # 팝업 다이얼로그 step ETA 업데이트
            if self._dialog and self._running_idx is not None:
                job = self._jobs[self._running_idx]
                total_eta = self._compute_total_eta_step()
                self._dialog.update_epoch(
                    epoch, job.config.epochs,
                    job.last_train_loss, job.last_val_loss,
                    job.last_metrics.get("mean_iou", 0.0),
                    self._step_eta(), total_eta,
                )

    def _on_epoch_done(self, epoch: int, train_loss: float,
                       val_loss: float, metrics: dict) -> None:
        if self._running_idx is None:
            return
        job = self._jobs[self._running_idx]
        job.epochs_done = epoch
        job.last_train_loss = train_loss
        job.last_val_loss = val_loss
        job.last_metrics = metrics
        epoch_time = float(metrics.get("epoch_time", 0))
        if epoch_time > 0:
            job.epoch_times.append(epoch_time)

        # Val loss 는 epoch 단위로 (train 은 batch_done 에서 이미 실시간 반영)
        self._chart.append_val(epoch, val_loss)
        self._progress.setValue(epoch)
        iou = metrics.get("mean_iou", 0.0)

        row = self._metrics_table.rowCount()
        self._metrics_table.insertRow(row)
        self._metrics_table.setItem(row, 0, QTableWidgetItem(str(epoch)))
        self._metrics_table.setItem(row, 1, QTableWidgetItem(f"{val_loss:.3f}"))
        self._metrics_table.setItem(row, 2, QTableWidgetItem(f"{iou:.3f}"))
        self._metrics_table.scrollToBottom()

        self._lbl_status.setText(
            f"🎯 '{job.name}'  Epoch {epoch}/{job.config.epochs}  "
            f"train={train_loss:.4f}  val={val_loss:.4f}  IoU={iou:.4f}  "
            f"· {epoch_time:.1f}s/epoch"
        )

        # 팝업 업데이트
        if self._dialog:
            total_eta = self._compute_total_eta()
            self._dialog.update_epoch(
                epoch, job.config.epochs,
                train_loss, val_loss, iou,
                job.eta_seconds, total_eta,
            )
            self._dialog.update_queue(self._jobs)
        self._refresh_queue_list()

    def _on_checkpoint_saved(self, path: str) -> None:
        self._ckpt_list.addItem(Path(path).name)
        self._ckpt_list.scrollToBottom()

    def _on_job_finished(self) -> None:
        if self._running_idx is not None:
            job = self._jobs[self._running_idx]
            # 유저가 중지 요청해서 일찍 끝났는지 판단
            if job.epochs_done < job.config.epochs:
                job.status = "stopped"
            else:
                job.status = "done"
        self._worker = None
        self._refresh_queue_list()
        self._run_next_job()

    def _on_job_error(self, msg: str) -> None:
        name = self._jobs[self._running_idx].name if self._running_idx is not None else "?"
        log.error(f"학습 오류 — job='{name}': {msg}")
        if self._running_idx is not None:
            self._jobs[self._running_idx].status = "error"
        self._worker = None
        self._refresh_queue_list()
        QMessageBox.critical(self, "학습 오류",
            f"'{name}' 학습 중 오류:\n{msg}\n\n큐의 다음 작업으로 진행합니다.")
        self._run_next_job()

    # ── 진행 창 ──────────────────────────────────────────────────────────────

    def _show_dialog(self) -> None:
        if self._dialog is None:
            self._dialog = TrainingProgressDialog(self)
            self._dialog.stop_current_requested.connect(self._on_dialog_stop_current)
            self._dialog.stop_all_requested.connect(self._on_dialog_stop_all)
        self._dialog.update_queue(self._jobs)
        self._dialog.show()
        self._dialog.raise_()
        self._dialog.activateWindow()

    def _on_show_dialog(self) -> None:
        self._show_dialog()

    def _on_dialog_stop_current(self) -> None:
        if self._worker:
            self._worker.request_stop()
            self._lbl_status.setText("⏸️ 현재 작업 중지 요청됨…")

    def _on_dialog_stop_all(self) -> None:
        self._queue_stop_all = True
        if self._worker:
            self._worker.request_stop()
        self._lbl_status.setText("⏸️ 전체 큐 중지 요청됨…")

    # ── ETA 계산 ─────────────────────────────────────────────────────────────

    def _step_eta(self) -> float:
        """현재 진행 중인 작업의 스텝 기반 남은 시간(초)."""
        import time
        elapsed = time.monotonic() - self._train_start_time
        if elapsed <= 0 or self._current_step <= 0:
            return 0.0
        sps = self._current_step / elapsed
        remain = self._total_steps - self._current_step
        return remain / sps if sps > 0 else 0.0

    def _compute_total_eta_step(self) -> float:
        """전체 큐(대기 포함)의 스텝 기반 예상 시간(초)."""
        import time
        current_eta = self._step_eta()
        # 대기 중인 나머지 작업은 현재 학습 속도(steps/sec) 기준으로 추산
        elapsed = time.monotonic() - self._train_start_time
        sps = (self._current_step / elapsed) if elapsed > 0 and self._current_step > 0 else 0

        waiting_eta = 0.0
        for job in self._jobs:
            if job.status == "waiting":
                total = job.config.epochs * self._total_batches
                waiting_eta += total / sps if sps > 0 else 0
        return current_eta + waiting_eta

    def _compute_total_eta(self) -> float:
        total = 0.0
        current_avg = 0.0
        if self._running_idx is not None:
            current_avg = self._jobs[self._running_idx].avg_epoch_time

        for job in self._jobs:
            if job.status == "running":
                total += job.eta_seconds
            elif job.status == "waiting":
                avg = current_avg if current_avg > 0 else job.avg_epoch_time
                total += max(0, job.config.epochs - job.epochs_done) * avg
        return total

    # ── 모델 접근 ─────────────────────────────────────────────────────────────

    def _get_model(self):
        win = self.window()
        if hasattr(win, "_model_tab"):
            return win._model_tab.loaded_model
        return None

    def _resolve_model_for_job(self, job):
        """job.model_source 를 보고 실제 nn.Module 인스턴스를 준비."""
        src = job.model_source
        if src == "loaded":
            m = self._get_model()
            if m is None:
                raise RuntimeError("Model 탭에서 모델을 먼저 로드하세요.")
            log.info(f"[{job.name}] 현재 로드된 모델 사용")
            return m
        if src.startswith("preset:"):
            key = src[len("preset:"):]
            info = preset_by_key(key)
            code = load_preset_code(key)
            if not code:
                raise RuntimeError(f"프리셋 '{key}' 코드를 찾을 수 없습니다.")
            result = load_from_code(code)
            if not result.ok:
                raise RuntimeError(f"프리셋 '{info.title if info else key}' 로드 실패: {result.error}")
            log.info(
                f"[{job.name}] 프리셋 사용: {info.title if info else key} "
                f"({result.num_params:,} params)"
            )
            return result.model
        raise RuntimeError(f"알 수 없는 모델 소스: {src}")
