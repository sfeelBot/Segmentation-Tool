"""디바이스(CUDA/MPS/CPU) 감지 및 구형 GPU 호환성 처리."""
from __future__ import annotations

import platform
import sys

import torch

from app.core.logger import get_logger

log = get_logger(__name__)


def log_environment() -> None:
    """앱 시작 시 환경 정보 전체를 로그로 기록."""
    log.info(f"Python {sys.version.split()[0]}  |  {platform.platform()}")
    log.info(f"PyTorch {torch.__version__} (build CUDA: {torch.version.cuda})")
    log.info(f"cuDNN: {torch.backends.cudnn.version() if torch.backends.cudnn.is_available() else '없음'}")

    try:
        cuda_ok = torch.cuda.is_available()
    except Exception as e:
        log.error(f"CUDA 상태 조회 중 예외: {e!r} — CPU 로 동작합니다.")
        cuda_ok = False

    if not cuda_ok:
        log.warning("CUDA 사용 불가 — 학습은 CPU 로 진행됩니다 (매우 느림).")
        log.warning(
            "해결: (1) NVIDIA 드라이버 설치, (2) PyTorch CUDA 빌드로 재설치 — "
            "`pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121` 등."
        )
    else:
        try:
            n = torch.cuda.device_count()
            log.info(f"CUDA 사용 가능 — GPU {n}개")
            for i in range(n):
                name = torch.cuda.get_device_name(i)
                cc   = torch.cuda.get_device_capability(i)
                prop = torch.cuda.get_device_properties(i)
                mem_gb = prop.total_memory / (1024 ** 3)
                log.info(
                    f"  [{i}] {name}  — CC {cc[0]}.{cc[1]}, {mem_gb:.1f}GB, "
                    f"SMs {prop.multi_processor_count}"
                )
                _warn_for_old_arch(cc, name)
        except Exception as e:
            log.error(f"GPU 정보 조회 실패: {e!r}")

    # Apple MPS
    try:
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            log.info("Apple MPS 사용 가능")
    except Exception:
        pass


def _warn_for_old_arch(cc: tuple[int, int], name: str) -> None:
    major, minor = cc
    if major < 5:
        log.error(
            f"  → {name}: compute capability {major}.{minor} — 너무 오래된 GPU, "
            f"최근 PyTorch 빌드에서 지원하지 않을 수 있습니다. CPU 권장."
        )
    elif major == 5:
        # Maxwell: M4000/M5000/GTX 9xx 등
        log.warning(
            f"  → {name}: Maxwell 세대 (CC {major}.{minor}). "
            f"PyTorch CUDA 11.x 까지 안정, 12.x 휠은 커널 누락 가능성이 있습니다. "
            f"AMP 는 자동으로 꺼집니다."
        )
    elif major == 6:
        # Pascal
        log.warning(
            f"  → {name}: Pascal 세대 (CC {major}.{minor}). "
            f"Tensor Core 없음 — AMP 속도 이득 거의 없음."
        )
    elif major == 7 and minor == 0:
        log.info(f"  → {name}: Volta — AMP 사용 권장.")
    # Turing / Ampere / Ada 는 최신 GPU 로 별도 경고 없음


def pick_device(device_str: str = "auto") -> torch.device:
    """요청된 디바이스로 시도 후 실패 시 CPU 로 안전 폴백."""
    if device_str not in ("auto", "cuda", "mps", "cpu"):
        log.warning(f"알 수 없는 device '{device_str}' → 'auto' 로 처리.")
        device_str = "auto"

    wanted_cuda = device_str in ("auto", "cuda")
    wanted_mps  = device_str in ("auto", "mps")

    if wanted_cuda:
        try:
            if torch.cuda.is_available():
                try:
                    # 실제 할당으로 살아있는지 검증
                    probe = torch.zeros(1, device="cuda")
                    del probe
                    torch.cuda.synchronize()
                    return torch.device("cuda")
                except Exception as e:
                    log.error(
                        f"CUDA 할당 실패 — CPU 로 폴백합니다.\n"
                        f"  원인: {type(e).__name__}: {e}"
                    )
            elif device_str == "cuda":
                log.error("'cuda' 요청 — CUDA 사용 불가. CPU 로 폴백.")
        except Exception as e:
            log.error(f"CUDA 확인 중 예외 — CPU 로 폴백: {e!r}")

    if wanted_mps:
        try:
            if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                return torch.device("mps")
        except Exception as e:
            log.error(f"MPS 확인 중 예외: {e!r}")

    return torch.device("cpu")


def should_use_amp(device: torch.device, user_wants_amp: bool) -> bool:
    """디바이스 특성에 맞춰 AMP(mixed precision) 사용 여부 결정.
    CC 7.0(Volta) 미만에서는 자동 비활성화 — 속도 이득이 없고 수치 불안정 위험."""
    if not user_wants_amp:
        return False
    if device.type != "cuda":
        if user_wants_amp:
            log.info("AMP: CUDA 가 아니므로 비활성화.")
        return False
    try:
        cc = torch.cuda.get_device_capability(device)
        if cc[0] < 7:
            log.warning(
                f"AMP 자동 비활성화 — compute capability {cc[0]}.{cc[1]} "
                f"에서는 Tensor Core 가 없어 오히려 느려지고 수치 불안정이 발생할 수 있습니다."
            )
            return False
    except Exception as e:
        log.warning(f"GPU CC 조회 실패 — AMP 비활성화: {e!r}")
        return False
    return True


def format_oom_help(batch_size: int, image_w: int, image_h: int) -> str:
    """OOM 시 사용자에게 보여줄 해결책 메시지."""
    return (
        "GPU 메모리가 부족합니다.\n\n"
        f"• Batch Size 를 줄이세요 (현재 {batch_size} → 절반 시도)\n"
        f"• 이미지 크기를 줄이세요 (현재 {image_w}×{image_h})\n"
        "• DataLoader Workers 를 0 으로 하세요\n"
        "• 다른 프로그램이 GPU 를 점유 중인지 확인 (nvidia-smi)\n"
        "• Mixed Precision 을 끄면 더 적은 메모리로 동작하는 경우도 있습니다"
    )


def check_gpu_available() -> tuple[bool, str]:
    """(GPU 사용 가능 여부, 이유 문자열) 튜플 반환."""
    try:
        if not torch.cuda.is_available():
            if torch.version.cuda is None:
                return False, "PyTorch 가 CPU-only 로 설치되어 있습니다 (torch.version.cuda=None)."
            return False, "CUDA GPU 가 감지되지 않습니다. NVIDIA 드라이버를 확인하세요."
        # 실제 할당 시도
        probe = torch.zeros(1, device="cuda")
        del probe
        torch.cuda.synchronize()
        return True, torch.cuda.get_device_name(0)
    except Exception as e:
        return False, f"CUDA 초기화 오류: {type(e).__name__}: {e}"


def prompt_gpu_availability(parent, context: str = "작업") -> bool:
    """GPU 를 사용할 수 없으면 상세 진단 팝업을 띄우고 CPU 로 계속할지 물어본다.
    True = 진행해도 좋음 (GPU 사용 가능 or 사용자가 CPU 수락),
    False = 사용자가 취소."""
    from PyQt6.QtWidgets import QMessageBox, QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel
    from app.core.cuda_diag import run_cuda_diagnostics
    from app.widgets.cuda_diag_dialog import CudaDiagDialog

    ok, reason = check_gpu_available()
    if ok:
        log.info(f"[{context}] GPU 사용 가능: {reason}")
        return True

    log.warning(f"[{context}] GPU 사용 불가: {reason}")

    # 진단 실행 (nvidia-smi 등 subprocess 포함 — 짧은 지연 있음)
    diag = run_cuda_diagnostics()

    # GPU 사용 불가 + 자세한 진단 + CPU 진행 여부 묻는 커스텀 다이얼로그
    dlg = QDialog(parent)
    dlg.setWindowTitle(f"GPU 사용 불가 — {context}")
    dlg.setMinimumSize(680, 560)
    dlg.resize(720, 580)

    outer = QVBoxLayout(dlg)
    outer.setSpacing(10)
    outer.setContentsMargins(12, 12, 12, 12)

    # 상단 안내
    from PyQt6.QtWidgets import QTextBrowser
    from app.widgets.cuda_diag_dialog import _build_html
    browser = QTextBrowser()
    browser.setOpenExternalLinks(False)
    browser.setStyleSheet("background:#111827;border:1px solid #374151;border-radius:6px;")
    browser.setHtml(_build_html(diag))
    outer.addWidget(browser)

    # 하단 버튼 행
    btn_row = QHBoxLayout()
    lbl_q = QLabel(f"CPU 로 {context}을(를) 진행하시겠습니까?  (매우 느릴 수 있습니다)")
    lbl_q.setStyleSheet("color:#fbbf24;font-size:12px;")
    btn_row.addWidget(lbl_q)
    btn_row.addStretch()

    btn_yes = QPushButton("CPU 로 진행")
    btn_yes.setStyleSheet("background:#065f46;color:white;font-weight:bold;padding:6px 14px;")
    btn_no  = QPushButton("취소")
    btn_no.setStyleSheet("padding:6px 14px;")
    btn_yes.clicked.connect(dlg.accept)
    btn_no.clicked.connect(dlg.reject)
    btn_row.addWidget(btn_yes)
    btn_row.addWidget(btn_no)
    outer.addLayout(btn_row)

    accepted = dlg.exec() == QDialog.DialogCode.Accepted
    if accepted:
        log.info(f"[{context}] 사용자가 CPU 로 진행을 선택")
    else:
        log.info(f"[{context}] 사용자가 취소")
    return accepted
