"""학습 진행 상황 팝업 — 비모달, 큐 상태 + 현재 작업 ETA 표시."""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar,
    QPushButton, QListWidget, QListWidgetItem, QGroupBox,
)
from PyQt6.QtGui import QColor
from PyQt6.QtCore import Qt, QSize, pyqtSignal

from app.widgets.icons import icon as svg_icon

_QUEUE_ICON_SIZE = 14

STATUS_ICON_NAME = {
    "waiting": "status_ring",
    "running": "status_dot",
    "done":    "status_done",
    "error":   "status_error",
    "stopped": "status_square",
}

STATUS_COLOR = {
    "waiting": "#888888",
    "running": "#60a5fa",
    "done":    "#34d399",
    "error":   "#f87171",
    "stopped": "#fbbf24",
}


def _fmt_time(seconds: float) -> str:
    if seconds <= 0 or seconds != seconds:  # handles NaN
        return "--:--"
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


class TrainingProgressDialog(QDialog):
    stop_current_requested = pyqtSignal()
    stop_all_requested     = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("학습 진행 상황")
        self.setModal(False)
        self.setMinimumWidth(420)
        self.setMinimumHeight(440)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(14, 14, 14, 14)

        # ── 현재 작업 정보 ────────────────────────────────────────────────────
        cur_box = QGroupBox("▶  현재 작업")
        cur_layout = QVBoxLayout(cur_box)
        cur_layout.setSpacing(6)

        self._lbl_job = QLabel("—")
        self._lbl_job.setStyleSheet("font-size:15px; font-weight:bold; color:#60a5fa;")
        cur_layout.addWidget(self._lbl_job)

        self._lbl_epoch = QLabel("Epoch —")
        self._lbl_epoch.setStyleSheet("color:#ccc;")
        cur_layout.addWidget(self._lbl_epoch)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setFormat("%v / %m  (%p%)")
        cur_layout.addWidget(self._progress)

        # 메트릭 한 줄 요약
        metrics_row = QHBoxLayout()
        self._lbl_train_loss = QLabel("Train: —")
        self._lbl_val_loss   = QLabel("Val: —")
        self._lbl_iou        = QLabel("IoU: —")
        for lbl in (self._lbl_train_loss, self._lbl_val_loss, self._lbl_iou):
            lbl.setStyleSheet("color:#aaa; font-size:11px;")
            metrics_row.addWidget(lbl)
        metrics_row.addStretch()
        cur_layout.addLayout(metrics_row)

        root.addWidget(cur_box)

        # ── ETA 정보 ─────────────────────────────────────────────────────────
        eta_box = QGroupBox("예상 소요 시간")
        eta_layout = QVBoxLayout(eta_box)

        self._lbl_eta_job   = QLabel("이 작업: —")
        self._lbl_eta_total = QLabel("전체 큐: —")
        self._lbl_eta_job.setStyleSheet("color:#e5e7eb;")
        self._lbl_eta_total.setStyleSheet("color:#e5e7eb;")
        eta_layout.addWidget(self._lbl_eta_job)
        eta_layout.addWidget(self._lbl_eta_total)
        root.addWidget(eta_box)

        # ── 큐 상태 ──────────────────────────────────────────────────────────
        q_box = QGroupBox("학습 큐")
        q_layout = QVBoxLayout(q_box)
        self._queue_list = QListWidget()
        self._queue_list.setAlternatingRowColors(True)
        self._queue_list.setIconSize(QSize(_QUEUE_ICON_SIZE, _QUEUE_ICON_SIZE))
        q_layout.addWidget(self._queue_list)
        root.addWidget(q_box, stretch=1)

        # ── 버튼 ─────────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        self._btn_stop_current = QPushButton("■ 현재 작업만 중지")
        self._btn_stop_all     = QPushButton("■■ 전체 중지")
        self._btn_close        = QPushButton("창 닫기")
        self._btn_stop_current.clicked.connect(self.stop_current_requested.emit)
        self._btn_stop_all.clicked.connect(self.stop_all_requested.emit)
        self._btn_close.clicked.connect(self.hide)
        btn_row.addWidget(self._btn_stop_current)
        btn_row.addWidget(self._btn_stop_all)
        btn_row.addStretch()
        btn_row.addWidget(self._btn_close)
        root.addLayout(btn_row)

    # ── 공개 API ──────────────────────────────────────────────────────────────

    def set_current_job(self, job_name: str, total_epochs: int) -> None:
        self._lbl_job.setText(job_name)
        self._progress.setMaximum(total_epochs)
        self._progress.setValue(0)
        self._lbl_epoch.setText(f"Epoch 0 / {total_epochs}")
        self._lbl_train_loss.setText("Train: —")
        self._lbl_val_loss.setText("Val: —")
        self._lbl_iou.setText("IoU: —")

    def update_epoch(self, epoch: int, total: int,
                     train_loss: float, val_loss: float, iou: float,
                     eta_job_sec: float, eta_total_sec: float) -> None:
        self._progress.setValue(epoch)
        self._lbl_epoch.setText(f"Epoch {epoch} / {total}")
        self._lbl_train_loss.setText(f"Train: {train_loss:.4f}")
        self._lbl_val_loss.setText(f"Val: {val_loss:.4f}")
        self._lbl_iou.setText(f"IoU: {iou:.4f}")
        self._lbl_eta_job.setText(f"이 작업: {_fmt_time(eta_job_sec)}")
        self._lbl_eta_total.setText(f"전체 큐: {_fmt_time(eta_total_sec)}")

    def update_queue(self, jobs: list) -> None:
        """jobs: TrainingJob 리스트."""
        self._queue_list.clear()
        for job in jobs:
            icon_name = STATUS_ICON_NAME.get(job.status, "status_ring")
            color = STATUS_COLOR.get(job.status, "#cccccc")
            text = f"{job.name}   ({job.epochs_done}/{job.config.epochs})"
            if job.status == "running":
                text += f"  · ETA {_fmt_time(job.eta_seconds)}"
            item = QListWidgetItem(svg_icon(icon_name, color, _QUEUE_ICON_SIZE), text)
            item.setForeground(QColor(color))
            self._queue_list.addItem(item)

    def set_done(self) -> None:
        self._lbl_job.setText("모든 학습 완료")
        self._btn_stop_current.setEnabled(False)
        self._btn_stop_all.setEnabled(False)

    def reset_running_state(self) -> None:
        self._btn_stop_current.setEnabled(True)
        self._btn_stop_all.setEnabled(True)
