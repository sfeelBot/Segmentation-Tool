"""하이퍼파라미터 설정 폼 위젯."""
from PyQt6.QtWidgets import (
    QWidget, QFormLayout, QHBoxLayout, QSpinBox, QDoubleSpinBox,
    QComboBox, QCheckBox, QLabel, QGroupBox, QVBoxLayout,
    QPushButton, QToolTip, QStackedWidget,
)
from PyQt6.QtCore import Qt

from app.core.trainer import TrainingConfig
from app.core.i18n import t


class ConfigForm(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(8)

        # ── 🔲 이미지 샘플링 (최상단 — 데이터보다 먼저) ─────────────────────────
        patch_box = QGroupBox(t("cfg.sampling"))
        patch_form = QFormLayout(patch_box)

        self._sample_mode = QComboBox()
        self._sample_mode.addItem("📦 random_crop  (패치 학습, 대형 이미지 권장)", "random_crop")
        self._sample_mode.addItem("🔍 resize        (전체 이미지 축소)", "resize")
        self._sample_mode.addItem("⬛ center_crop   (중앙 패치 크롭)", "center_crop")
        self._sample_mode.setCurrentIndex(0)
        self._sample_mode.setToolTip(
            "random_crop: 원본 해상도를 유지하며 패치 크기 단위로 잘라서 학습\n"
            "             → IMG SIZE = 패치 크기 (원본 해상도 그대로)\n"
            "resize:      전체 이미지를 IMG SIZE 로 축소해서 학습\n"
            "             → IMG SIZE = 다운스케일 해상도\n"
            "center_crop: 이미지 중앙에서 IMG SIZE 크기만큼 잘라냄"
        )
        patch_form.addRow(t("cfg.sampling_mode"), self._sample_mode)

        self._patches_per_img = QSpinBox()
        self._patches_per_img.setRange(1, 500)
        self._patches_per_img.setValue(50)
        self._patches_per_img.setToolTip(
            "epoch당 이미지 1장에서 뽑을 패치 수.\n"
            "예) 20장 × 50 = 1000 샘플/epoch\n"
            "  → 배치 수: 1000 / batch_size\n\n"
            "크게 잡을수록 epoch당 학습량 증가.\n"
            "50~100 이 대형 이미지(50MB급)에 적합."
        )

        self._btn_auto_patches = QPushButton(t("cfg.auto_calc"))
        self._btn_auto_patches.setFixedWidth(90)
        self._btn_auto_patches.setToolTip(
            "프로젝트 이미지 최대 5장을 샘플링해서\n"
            "IMG SIZE 대비 비중복 패치 수의 40%를\n"
            "권장값으로 자동 설정합니다."
        )
        self._btn_auto_patches.clicked.connect(self._auto_calc_patches)

        patches_row = QWidget()
        patches_hl = QHBoxLayout(patches_row)
        patches_hl.setContentsMargins(0, 0, 0, 0)
        patches_hl.setSpacing(4)
        patches_hl.addWidget(self._patches_per_img)
        patches_hl.addWidget(self._btn_auto_patches)

        patch_form.addRow(t("cfg.patches_per_img"), patches_row)

        self._defect_prob = QDoubleSpinBox()
        self._defect_prob.setRange(0.0, 1.0)
        self._defect_prob.setSingleStep(0.05)
        self._defect_prob.setDecimals(2)
        self._defect_prob.setValue(0.7)
        self._defect_prob.setToolTip(
            "random_crop 시 결함 중심으로 패치를 뽑는 확률.\n"
            "0.7 = 70% 는 결함 근처에서, 30% 는 전체 랜덤."
        )
        patch_form.addRow(t("cfg.defect_prob"), self._defect_prob)
        root.addWidget(patch_box)

        # ── 데이터 ────────────────────────────────────────────────────────────
        data_box = QGroupBox(t("cfg.data"))
        data_form = QFormLayout(data_box)

        self._img_w = QSpinBox()
        self._img_w.setRange(32, 2048); self._img_w.setSingleStep(32); self._img_w.setValue(512)
        self._img_w.setToolTip(
            "random_crop / center_crop: 패치 너비 (원본 해상도 그대로)\n"
            "resize: 전체 이미지를 축소할 너비"
        )
        self._img_h = QSpinBox()
        self._img_h.setRange(32, 2048); self._img_h.setSingleStep(32); self._img_h.setValue(512)
        self._img_h.setToolTip(
            "random_crop / center_crop: 패치 높이 (원본 해상도 그대로)\n"
            "resize: 전체 이미지를 축소할 높이"
        )
        self._val_split = QDoubleSpinBox()
        self._val_split.setRange(0.05, 0.5); self._val_split.setSingleStep(0.05); self._val_split.setValue(0.2)
        self._num_workers = QSpinBox()
        self._num_workers.setRange(0, 8); self._num_workers.setValue(0)
        self._num_workers.setToolTip(
            "이미지 로딩 병렬 프로세스 수.\n"
            "0 = 메인 프로세스 (Windows 에서 안전)\n"
            "2~4 = GPU 대기 시간 줄임 (Mac/Linux 권장)"
        )

        data_form.addRow(t("cfg.img_w"),   self._img_w)
        data_form.addRow(t("cfg.img_h"),   self._img_h)
        data_form.addRow(t("cfg.val_split"), self._val_split)
        data_form.addRow(t("cfg.workers"), self._num_workers)
        root.addWidget(data_box)

        # ── 학습 ──────────────────────────────────────────────────────────────
        train_box = QGroupBox(t("cfg.training"))
        train_form = QFormLayout(train_box)

        self._epochs = QSpinBox(); self._epochs.setRange(1, 9999); self._epochs.setValue(50)
        self._batch  = QSpinBox(); self._batch.setRange(1, 128);   self._batch.setValue(4)
        self._lr = QDoubleSpinBox()
        self._lr.setRange(1e-7, 1.0); self._lr.setSingleStep(1e-5)
        self._lr.setDecimals(6); self._lr.setValue(1e-4)
        self._ckpt_every = QSpinBox(); self._ckpt_every.setRange(1, 9999); self._ckpt_every.setValue(5)

        train_form.addRow("Epochs", self._epochs)
        train_form.addRow("Batch Size", self._batch)
        train_form.addRow("Learning Rate", self._lr)
        train_form.addRow(t("cfg.ckpt_every"), self._ckpt_every)
        root.addWidget(train_box)

        # ── 옵티마이저 ────────────────────────────────────────────────────────
        opt_box = QGroupBox(t("cfg.optimizer_group"))
        opt_form = QFormLayout(opt_box)

        self._optimizer = QComboBox()
        self._optimizer.addItems(["Adam", "AdamW", "SGD", "RMSprop"])

        self._weight_decay = QDoubleSpinBox()
        self._weight_decay.setRange(0, 1)
        self._weight_decay.setSingleStep(1e-5)
        self._weight_decay.setDecimals(6)
        self._weight_decay.setValue(1e-4)   # 산업용 약한 정규화 기본값
        self._weight_decay.setToolTip(
            "파라미터 크기를 억제해 과적합 방지 (L2 정규화).\n"
            "0.0001 (1e-4) = 약한 정규화 — 산업용 결함 검출 권장\n"
            "0.0       = 정규화 없음 (데이터가 충분할 때)\n"
            "0.01      = 강한 정규화 (극소수 데이터)"
        )

        self._momentum = QDoubleSpinBox()
        self._momentum.setRange(0, 1); self._momentum.setSingleStep(0.01); self._momentum.setValue(0.9)
        self._momentum.setToolTip("SGD 전용 관성 계수. Adam 계열에서는 무시됩니다.")

        opt_form.addRow("Optimizer", self._optimizer)
        opt_form.addRow("Weight Decay", self._weight_decay)
        opt_form.addRow(t("cfg.momentum_label"), self._momentum)
        root.addWidget(opt_box)

        # ── 손실 함수 / 장치 ──────────────────────────────────────────────────
        misc_box = QGroupBox(t("cfg.misc"))
        misc_form = QFormLayout(misc_box)

        self._loss_fn = QComboBox()
        self._loss_fn.addItems(["CrossEntropyLoss", "DiceLoss", "FocalLoss"])
        self._loss_fn.setToolTip(
            "CrossEntropyLoss: 일반적인 경우 기본값\n"
            "DiceLoss:         결함 영역이 작을 때 (픽셀 불균형)\n"
            "FocalLoss:        결함이 드물게 나타날 때 (어려운 샘플 집중)"
        )

        self._device = QComboBox()
        self._device.addItems(["auto", "cpu", "cuda", "mps"])

        self._mixed_prec = QCheckBox("Mixed Precision (AMP)")
        self._mixed_prec.setChecked(True)
        self._mixed_prec.setToolTip(
            "FP16 + FP32 혼합 정밀도 (Automatic Mixed Precision).\n"
            "GPU 메모리 ~50% 절약 + 학습 속도 1.5~3배 향상.\n"
            "CC < 7.0 (Maxwell/Pascal) GPU 에서는 자동 비활성화."
        )

        misc_form.addRow("Loss Function", self._loss_fn)
        misc_form.addRow("Device", self._device)
        misc_form.addRow("", self._mixed_prec)
        root.addWidget(misc_box)

        # ── LR 스케쥴러 ───────────────────────────────────────────────────────
        root.addWidget(self._build_scheduler_group())

        root.addStretch()

    # ── LR 스케쥴러 UI ───────────────────────────────────────────────────────

    def _build_scheduler_group(self) -> QGroupBox:
        """스케쥴러 종류 선택 + 해당 파라미터 패널 (QStackedWidget)."""
        box  = QGroupBox("LR Scheduler")
        vlay = QVBoxLayout(box)
        vlay.setSpacing(6)

        # ── 종류 선택 콤보박스 ────────────────────────────────────────────────
        self._sched_type = QComboBox()
        _SCHEDS = [
            ("없음 — 고정 LR",                                      "none"),
            ("StepLR — N 에폭마다 LR × γ",                         "step"),
            ("ExponentialLR — 매 에폭 LR × γ",                     "exp"),
            ("CosineAnnealingLR — 코사인 감쇠",                     "cosine"),
            ("CosineWarmRestarts — 코사인 + 주기 재시작 (SGDR)",    "cosine_restart"),
            ("ReduceLROnPlateau — Val Loss 정체 시 자동 감소",      "plateau"),
            ("OneCycleLR — 웜업 → 피크 → 코사인 (1 사이클)",       "onecycle"),
            ("WarmupCosine — 선형 웜업 + 코사인 감쇠",              "warmup_cosine"),
            ("PolynomialLR — 다항식 감쇠 (DeepLab 계열)",           "poly"),
        ]
        for label, key in _SCHEDS:
            self._sched_type.addItem(label, key)
        self._sched_type.setToolTip(
            "None      : LR 변경 없음\n"
            "StepLR    : 일정 에폭마다 LR 계단 감소 — 단순·안정적\n"
            "Exp       : 매 에폭 지수 감소 — 빠른 감소\n"
            "Cosine    : 코사인 곡선으로 점진 감소 — ViT·UNet 표준\n"
            "SGDR      : 코사인 + 주기 재시작 — 더 좋은 최솟값 탐색\n"
            "Plateau   : Val Loss 정체 시 LR 감소 — 자동·범용적\n"
            "OneCycle  : 웜업 후 하강 — 빠른 수렴 (학습률 찾기 불필요)\n"
            "WarmupCos : 선형 웜업 후 코사인 — 대형 모델·배치에 권장\n"
            "Poly      : 다항식 감쇠 — FCN/DeepLab 원논문 표준"
        )

        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("Scheduler"))
        type_row.addWidget(self._sched_type, stretch=1)
        vlay.addLayout(type_row)

        # ── 파라미터 패널 (QStackedWidget) ───────────────────────────────────
        self._sched_stack = QStackedWidget()

        # Page 0: none — 설명만
        self._sched_stack.addWidget(self.__sched_page_none())
        # Page 1: step
        self._sched_stack.addWidget(self.__sched_page_step())
        # Page 2: exp
        self._sched_stack.addWidget(self.__sched_page_exp())
        # Page 3: cosine
        self._sched_stack.addWidget(self.__sched_page_cosine())
        # Page 4: cosine_restart
        self._sched_stack.addWidget(self.__sched_page_cosine_restart())
        # Page 5: plateau
        self._sched_stack.addWidget(self.__sched_page_plateau())
        # Page 6: onecycle
        self._sched_stack.addWidget(self.__sched_page_onecycle())
        # Page 7: warmup_cosine
        self._sched_stack.addWidget(self.__sched_page_warmup_cosine())
        # Page 8: poly
        self._sched_stack.addWidget(self.__sched_page_poly())

        vlay.addWidget(self._sched_stack)
        self._sched_type.currentIndexChanged.connect(self._sched_stack.setCurrentIndex)

        return box

    # ── 스케쥴러 파라미터 페이지들 ────────────────────────────────────────────

    @staticmethod
    def _sched_form(parent: QWidget) -> QFormLayout:
        f = QFormLayout(parent)
        f.setContentsMargins(4, 4, 4, 4)
        f.setSpacing(4)
        return f

    def __sched_page_none(self) -> QWidget:
        w = QWidget(); f = self._sched_form(w)
        lbl = QLabel("LR 가 에폭 전반에 걸쳐 고정됩니다.")
        lbl.setStyleSheet("color:#9ca3af; font-size:11px;")
        f.addRow(lbl)
        return w

    def __sched_page_step(self) -> QWidget:
        w = QWidget(); f = self._sched_form(w)
        self._s_step_size = QSpinBox()
        self._s_step_size.setRange(1, 9999); self._s_step_size.setValue(10)
        self._s_step_size.setToolTip("몇 에폭마다 LR 을 감소시킬지")
        self._s_gamma = QDoubleSpinBox()
        self._s_gamma.setRange(0.01, 0.99); self._s_gamma.setSingleStep(0.05)
        self._s_gamma.setDecimals(3); self._s_gamma.setValue(0.5)
        self._s_gamma.setToolTip("LR 감소 배율 — 0.5 = 절반으로 줄임")
        f.addRow("Step Size (에폭)", self._s_step_size)
        f.addRow("Gamma  (γ)", self._s_gamma)
        return w

    def __sched_page_exp(self) -> QWidget:
        w = QWidget(); f = self._sched_form(w)
        self._e_gamma = QDoubleSpinBox()
        self._e_gamma.setRange(0.5, 0.9999); self._e_gamma.setSingleStep(0.01)
        self._e_gamma.setDecimals(4); self._e_gamma.setValue(0.95)
        self._e_gamma.setToolTip("에폭마다 LR = LR × γ\n0.95 → 50 에폭 후 약 8% 수준")
        f.addRow("Gamma  (γ)", self._e_gamma)
        return w

    def __sched_page_cosine(self) -> QWidget:
        w = QWidget(); f = self._sched_form(w)
        self._c_T_max = QSpinBox()
        self._c_T_max.setRange(0, 9999); self._c_T_max.setValue(0)
        self._c_T_max.setToolTip("코사인 주기 에폭 수 (0 = 자동 = 전체 Epochs)")
        self._c_eta_min = QDoubleSpinBox()
        self._c_eta_min.setRange(0, 1e-2); self._c_eta_min.setSingleStep(1e-7)
        self._c_eta_min.setDecimals(8); self._c_eta_min.setValue(1e-6)
        self._c_eta_min.setToolTip("코사인 감쇠 최솟값 LR")
        f.addRow("T_max  (0=auto)", self._c_T_max)
        f.addRow("Min LR  (η_min)", self._c_eta_min)
        return w

    def __sched_page_cosine_restart(self) -> QWidget:
        w = QWidget(); f = self._sched_form(w)
        self._cr_T0 = QSpinBox()
        self._cr_T0.setRange(1, 9999); self._cr_T0.setValue(10)
        self._cr_T0.setToolTip("첫 번째 재시작 주기 에폭 수")
        self._cr_Tmult = QSpinBox()
        self._cr_Tmult.setRange(1, 10); self._cr_Tmult.setValue(2)
        self._cr_Tmult.setToolTip("재시작마다 주기를 몇 배 늘릴지 (1 = 주기 고정)")
        self._cr_eta_min = QDoubleSpinBox()
        self._cr_eta_min.setRange(0, 1e-2); self._cr_eta_min.setSingleStep(1e-7)
        self._cr_eta_min.setDecimals(8); self._cr_eta_min.setValue(1e-6)
        f.addRow("T_0  (첫 주기 에폭)", self._cr_T0)
        f.addRow("T_mult  (주기 배율)", self._cr_Tmult)
        f.addRow("Min LR  (η_min)", self._cr_eta_min)
        return w

    def __sched_page_plateau(self) -> QWidget:
        w = QWidget(); f = self._sched_form(w)
        self._p_patience = QSpinBox()
        self._p_patience.setRange(1, 999); self._p_patience.setValue(5)
        self._p_patience.setToolTip("Val Loss 개선 없을 때 몇 에폭 기다린 후 LR 감소")
        self._p_factor = QDoubleSpinBox()
        self._p_factor.setRange(0.01, 0.99); self._p_factor.setSingleStep(0.05)
        self._p_factor.setDecimals(3); self._p_factor.setValue(0.5)
        self._p_factor.setToolTip("LR 감소 배율 (new_lr = lr × factor)")
        self._p_min_lr = QDoubleSpinBox()
        self._p_min_lr.setRange(0, 1e-3); self._p_min_lr.setSingleStep(1e-8)
        self._p_min_lr.setDecimals(9); self._p_min_lr.setValue(1e-7)
        self._p_min_lr.setToolTip("LR 의 하한선")
        f.addRow("Patience  (에폭)", self._p_patience)
        f.addRow("Factor  (배율)", self._p_factor)
        f.addRow("Min LR", self._p_min_lr)
        return w

    def __sched_page_onecycle(self) -> QWidget:
        w = QWidget(); f = self._sched_form(w)
        self._oc_max_lr = QDoubleSpinBox()
        self._oc_max_lr.setRange(0.0, 1.0); self._oc_max_lr.setSingleStep(1e-4)
        self._oc_max_lr.setDecimals(6); self._oc_max_lr.setValue(0.0)
        self._oc_max_lr.setToolTip(
            "웜업이 도달할 피크 LR\n"
            "0 = 자동 (Base LR × 10)\n"
            "권장: 기본 LR 의 5~20 배"
        )
        self._oc_pct = QDoubleSpinBox()
        self._oc_pct.setRange(0.01, 0.5); self._oc_pct.setSingleStep(0.05)
        self._oc_pct.setDecimals(2); self._oc_pct.setValue(0.3)
        self._oc_pct.setToolTip("전체 스텝 중 웜업이 차지하는 비율 (0.3 = 30%)")
        f.addRow("Max LR  (0=auto)", self._oc_max_lr)
        f.addRow("Warmup %  (pct_start)", self._oc_pct)
        return w

    def __sched_page_warmup_cosine(self) -> QWidget:
        w = QWidget(); f = self._sched_form(w)
        self._wc_warmup = QSpinBox()
        self._wc_warmup.setRange(1, 999); self._wc_warmup.setValue(5)
        self._wc_warmup.setToolTip("선형 웜업 에폭 수 — 이후 코사인 감쇠 시작")
        self._wc_eta_min = QDoubleSpinBox()
        self._wc_eta_min.setRange(0, 1e-2); self._wc_eta_min.setSingleStep(1e-7)
        self._wc_eta_min.setDecimals(8); self._wc_eta_min.setValue(1e-6)
        self._wc_eta_min.setToolTip("코사인 감쇠가 수렴하는 최솟값 LR")
        f.addRow("Warmup Epochs", self._wc_warmup)
        f.addRow("Min LR  (η_min)", self._wc_eta_min)
        return w

    def __sched_page_poly(self) -> QWidget:
        w = QWidget(); f = self._sched_form(w)
        self._poly_power = QDoubleSpinBox()
        self._poly_power.setRange(0.1, 5.0); self._poly_power.setSingleStep(0.1)
        self._poly_power.setDecimals(2); self._poly_power.setValue(0.9)
        self._poly_power.setToolTip(
            "LR = LR_init × (1 - epoch/total)^power\n"
            "0.9 = DeepLab 원논문 값, 1.0 = 선형 감쇠"
        )
        f.addRow("Power  (지수)", self._poly_power)
        return w

    # ── 자동 계산 ─────────────────────────────────────────────────────────────

    def _auto_calc_patches(self) -> None:
        """프로젝트 이미지를 샘플링해서 patches_per_image 권장값을 계산."""
        import random
        from PIL import Image as PILImage
        from app.core import project as _project

        img_dir = _project.images_dir()
        if not img_dir.exists():
            QToolTip.showText(
                self._btn_auto_patches.mapToGlobal(
                    self._btn_auto_patches.rect().bottomLeft()),
                "⚠ 프로젝트 이미지 폴더가 없습니다.",
                self._btn_auto_patches,
            )
            return

        exts = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"}
        paths = [p for p in img_dir.iterdir() if p.suffix.lower() in exts]
        if not paths:
            QToolTip.showText(
                self._btn_auto_patches.mapToGlobal(
                    self._btn_auto_patches.rect().bottomLeft()),
                "⚠ 이미지가 없습니다.",
                self._btn_auto_patches,
            )
            return

        sample = random.sample(paths, min(5, len(paths)))
        widths, heights = [], []
        for p in sample:
            try:
                with PILImage.open(p) as img:
                    widths.append(img.width)
                    heights.append(img.height)
            except Exception:
                continue

        if not widths:
            return

        avg_w = sum(widths) / len(widths)
        avg_h = sum(heights) / len(heights)
        pw = self._img_w.value()
        ph = self._img_h.value()

        tiles_x = max(1, int(avg_w // pw))
        tiles_y = max(1, int(avg_h // ph))
        non_overlap = tiles_x * tiles_y
        recommended = max(10, int(non_overlap * 0.4))

        self._patches_per_img.setValue(recommended)
        from PyQt6.QtCore import QRect
        QToolTip.showText(
            self._btn_auto_patches.mapToGlobal(
                self._btn_auto_patches.rect().bottomLeft()),
            f"평균 이미지: {avg_w:.0f}×{avg_h:.0f}px\n"
            f"패치: {pw}×{ph}px  →  비중복 {tiles_x}×{tiles_y}={non_overlap}개\n"
            f"권장값 (40% 커버리지): {recommended}",
            self._btn_auto_patches,
            QRect(),
            3000,
        )

    # ── 공개 API ──────────────────────────────────────────────────────────────

    def get_config(self) -> TrainingConfig:
        sched = self._sched_type.currentData()
        return TrainingConfig(
            epochs              = self._epochs.value(),
            batch_size          = self._batch.value(),
            image_w             = self._img_w.value(),
            image_h             = self._img_h.value(),
            lr                  = self._lr.value(),
            optimizer           = self._optimizer.currentText(),
            weight_decay        = self._weight_decay.value(),
            momentum            = self._momentum.value(),
            loss_fn             = self._loss_fn.currentText(),
            mixed_precision     = self._mixed_prec.isChecked(),
            device              = self._device.currentText(),
            checkpoint_every    = self._ckpt_every.value(),
            val_split           = self._val_split.value(),
            num_workers         = self._num_workers.value(),
            sample_mode         = self._sample_mode.currentData(),
            patches_per_image   = self._patches_per_img.value(),
            defect_sample_prob  = self._defect_prob.value(),
            # ── LR 스케쥴러 ─────────────────────────────────────────────────
            scheduler           = sched,
            sched_step_size     = self._s_step_size.value(),
            sched_gamma         = self._s_gamma.value()
                                  if sched in ("step",)
                                  else self._e_gamma.value(),
            sched_T_max         = self._c_T_max.value(),
            sched_T_0           = self._cr_T0.value(),
            sched_T_mult        = self._cr_Tmult.value(),
            sched_eta_min       = {
                "cosine":         self._c_eta_min.value(),
                "cosine_restart": self._cr_eta_min.value(),
                "warmup_cosine":  self._wc_eta_min.value(),
            }.get(sched, 1e-6),
            sched_patience      = self._p_patience.value(),
            sched_factor        = self._p_factor.value(),
            sched_min_lr        = self._p_min_lr.value(),
            sched_max_lr        = self._oc_max_lr.value(),
            sched_pct_start     = self._oc_pct.value(),
            sched_warmup_epochs = self._wc_warmup.value(),
            sched_power         = self._poly_power.value(),
        )
