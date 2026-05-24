"""하이퍼파라미터 설정 폼 위젯."""
from PyQt6.QtWidgets import (
    QWidget, QFormLayout, QHBoxLayout, QSpinBox, QDoubleSpinBox,
    QComboBox, QCheckBox, QLabel, QGroupBox, QVBoxLayout,
    QPushButton, QToolTip,
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

        root.addStretch()

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
        )
