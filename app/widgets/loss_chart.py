"""실시간 Train / Val 손실 그래프 — matplotlib FigureCanvasQTAgg.

두 가지 데이터 흐름:
  append_batch(frac_epoch, loss) — 배치마다 실시간 EMA 스무딩 train loss
  append_val(epoch, val_loss)    — epoch마다 val loss 포인트
  append(epoch, train, val)      — 기존 epoch 단위 호환 메서드 (resize 모드 등)
"""
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure


_DARK   = "#1e1e1e"
_PANEL  = "#2d2d2d"
_TRAIN  = "#4fc3f7"   # 밝은 파란색 — train
_VAL    = "#ef9a9a"   # 밝은 붉은색 — val
_GRID   = "#3a3a3a"
_TEXT   = "#cccccc"
_EPOCH  = "#555555"   # epoch 경계 세로선


class LossChart(FigureCanvasQTAgg):
    # EMA 스무딩 창 (배치 수 기준 절반 너비)
    _EMA_ALPHA = 0.08       # 낮을수록 부드럽고 느리게 반응
    # 배치 누적 후 몇 개마다 화면 갱신할지
    _DRAW_EVERY = 5

    def __init__(self, parent=None) -> None:
        fig = Figure(facecolor=_DARK, tight_layout=True)
        super().__init__(fig)
        self.setParent(parent)

        self._ax = fig.add_subplot(111)

        # 배치 레벨 train (EMA 스무딩, 많은 포인트)
        self._bx: list[float] = []   # fractional epoch
        self._by: list[float] = []   # EMA loss
        self._ema: float | None = None
        self._pending = 0            # draw 미루기 카운터

        # Epoch 레벨 val
        self._vx: list[float] = []   # epoch
        self._vy: list[float] = []   # val loss

        # 라인 객체
        self._line_train, = self._ax.plot(
            [], [], color=_TRAIN, linewidth=1.2, alpha=0.9, label="Train Loss"
        )
        self._line_val, = self._ax.plot(
            [], [], color=_VAL, linewidth=2.0,
            marker="o", markersize=3.5, label="Val Loss"
        )

        # epoch 경계 세로선 목록 (pyplot.axvline 대신 Line2D 관리)
        self._epoch_lines: list = []
        self._last_full_epoch: int = 0

        self._style_ax()

    # ── 공개 API ──────────────────────────────────────────────────────────────

    def append_batch(self, frac_epoch: float, loss: float) -> None:
        """배치마다 호출. EMA 스무딩 후 train 라인 갱신."""
        if self._ema is None:
            self._ema = loss
        else:
            self._ema = _EMA_ALPHA * loss + (1.0 - _EMA_ALPHA) * self._ema
        self._bx.append(frac_epoch)
        self._by.append(self._ema)

        # epoch 경계 세로선 (정수 경계 넘을 때)
        full = int(frac_epoch)
        if full > self._last_full_epoch and full > 0:
            self._last_full_epoch = full
            vl = self._ax.axvline(full, color=_EPOCH, linewidth=0.6, linestyle="--")
            self._epoch_lines.append(vl)

        self._pending += 1
        if self._pending >= self._DRAW_EVERY:
            self._pending = 0
            self._update_plot()

    def append_val(self, epoch: int, val_loss: float) -> None:
        """Epoch 마다 호출. val 라인 갱신 + 즉시 화면 갱신."""
        self._vx.append(float(epoch))
        self._vy.append(val_loss)
        self._pending = 0   # 강제 갱신
        self._update_plot()

    def append(self, epoch: int, train_loss: float, val_loss: float) -> None:
        """기존 호환 메서드 — resize 모드 등 epoch 단위 업데이트에 사용."""
        if not self._bx or self._bx[-1] < float(epoch):
            self._bx.append(float(epoch))
            self._by.append(train_loss)
            if self._ema is None:
                self._ema = train_loss
            else:
                self._ema = 0.3 * train_loss + 0.7 * self._ema
        self.append_val(epoch, val_loss)

    def reset(self) -> None:
        self._bx.clear(); self._by.clear()
        self._vx.clear(); self._vy.clear()
        self._ema = None
        self._pending = 0
        self._last_full_epoch = 0
        for vl in self._epoch_lines:
            vl.remove()
        self._epoch_lines.clear()
        self._line_train.set_data([], [])
        self._line_val.set_data([], [])
        self._ax.relim()
        self.draw_idle()

    # ── 내부 ─────────────────────────────────────────────────────────────────

    def _update_plot(self) -> None:
        if self._bx:
            self._line_train.set_data(self._bx, self._by)
        if self._vx:
            self._line_val.set_data(self._vx, self._vy)
        self._ax.relim()
        self._ax.autoscale_view()
        self.draw_idle()

    def _style_ax(self) -> None:
        ax = self._ax
        ax.set_facecolor(_PANEL)
        ax.tick_params(colors=_TEXT, labelsize=8)
        ax.xaxis.label.set_color(_TEXT)
        ax.yaxis.label.set_color(_TEXT)
        ax.set_xlabel("Epoch", fontsize=9)
        ax.set_ylabel("Loss",  fontsize=9)
        ax.set_title("Train / Val Loss", color="#eeeeee", fontsize=10)
        ax.legend(facecolor="#3a3a3a", labelcolor=_TEXT, fontsize=8)
        ax.grid(True, color=_GRID, linewidth=0.4, alpha=0.6)
        for spine in ax.spines.values():
            spine.set_edgecolor("#555555")


# 모듈 레벨에서 상수 접근용 (LossChart 내부 _EMA_ALPHA 와 동기화)
_EMA_ALPHA = LossChart._EMA_ALPHA
