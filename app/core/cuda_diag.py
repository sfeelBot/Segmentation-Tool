"""CUDA 가용성 종합 진단 — 드라이버·cuDNN·런타임·버전 불일치 등 8가지 항목 점검."""
from __future__ import annotations

import os
import platform
import subprocess
import sys
from dataclasses import dataclass, field
from enum import Enum

import torch


class DiagStatus(Enum):
    OK   = "ok"
    FAIL = "fail"
    WARN = "warn"
    INFO = "info"


@dataclass
class DiagItem:
    name:   str
    status: DiagStatus
    value:  str
    detail: str = ""
    fix:    str = ""


@dataclass
class CudaDiagResult:
    items:          list[DiagItem] = field(default_factory=list)
    cuda_available: bool           = False
    root_cause:     str            = ""
    fix_summary:    list[str]      = field(default_factory=list)


# ── 공개 API ──────────────────────────────────────────────────────────────────

def run_cuda_diagnostics() -> CudaDiagResult:
    """CUDA 환경 8단계 진단을 실행하고 결과를 반환한다."""
    result = CudaDiagResult()
    add = result.items.append

    torch_cuda_ver = torch.version.cuda  # None = CPU-only 빌드

    # ── 1. PyTorch CUDA 빌드 여부 ────────────────────────────────────────────
    if torch_cuda_ver is None:
        add(DiagItem(
            "PyTorch CUDA 빌드",
            DiagStatus.FAIL,
            f"CPU-only (torch {torch.__version__})",
            "torch.version.cuda = None — CUDA 지원이 포함되지 않은 빌드입니다.",
            "pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124",
        ))
        result.root_cause = "PyTorch가 CPU-only 빌드입니다."
        result.fix_summary.append(
            "CUDA 빌드로 재설치:\n"
            "pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124"
        )
    else:
        add(DiagItem(
            "PyTorch CUDA 빌드",
            DiagStatus.OK,
            f"CUDA {torch_cuda_ver} 빌드 (torch {torch.__version__})",
        ))

    # ── 2. NVIDIA 드라이버 (nvidia-smi) ─────────────────────────────────────
    driver_ver, smi_raw, gpu_names = _query_nvidia_smi()
    if driver_ver:
        detail = f"GPU 목록: {', '.join(gpu_names)}" if gpu_names else smi_raw[:400]
        add(DiagItem("NVIDIA 드라이버", DiagStatus.OK, f"버전 {driver_ver}", detail))
    else:
        add(DiagItem(
            "NVIDIA 드라이버",
            DiagStatus.FAIL,
            "감지 안됨",
            smi_raw,
            "NVIDIA 드라이버 설치: https://www.nvidia.com/Download/index.aspx",
        ))
        if not result.root_cause:
            result.root_cause = "NVIDIA 드라이버가 설치되지 않았거나 인식되지 않습니다."
            result.fix_summary.append("NVIDIA 드라이버 설치: https://www.nvidia.com/Download/index.aspx")

    # ── 3. CUDA Runtime 버전 (nvcc) ─────────────────────────────────────────
    nvcc_ver = _query_nvcc_version()
    if nvcc_ver and torch_cuda_ver:
        nvcc_major   = nvcc_ver.split(".")[0]
        torch_major  = torch_cuda_ver.split(".")[0]
        if nvcc_major != torch_major:
            add(DiagItem(
                "CUDA Runtime 버전",
                DiagStatus.WARN,
                f"시스템 CUDA {nvcc_ver} ↔ PyTorch 빌드 CUDA {torch_cuda_ver} [불일치]",
                "메이저 버전이 다릅니다. 일부 연산이 동작하지 않을 수 있습니다.",
                f"CUDA Toolkit {torch_cuda_ver} 설치 또는 torch cu{torch_major}x 빌드로 재설치.",
            ))
            result.fix_summary.append(
                f"CUDA Toolkit {torch_cuda_ver} 버전으로 맞추거나 "
                f"torch --index-url cu{torch_major}x 빌드로 재설치하세요."
            )
        else:
            add(DiagItem(
                "CUDA Runtime 버전",
                DiagStatus.OK,
                f"시스템 CUDA {nvcc_ver} ↔ PyTorch 빌드 CUDA {torch_cuda_ver} (일치)",
            ))
    elif nvcc_ver:
        add(DiagItem("CUDA Runtime 버전", DiagStatus.INFO, f"nvcc {nvcc_ver}"))
    else:
        add(DiagItem(
            "CUDA Runtime 버전",
            DiagStatus.INFO,
            "nvcc 미설치 — PyTorch 런타임에 CUDA가 내장되어 별도 설치 불필요",
        ))

    # ── 4. torch.cuda.is_available() ────────────────────────────────────────
    cuda_avail = False
    try:
        cuda_avail = torch.cuda.is_available()
    except Exception as e:
        add(DiagItem(
            "torch.cuda.is_available()",
            DiagStatus.FAIL,
            "예외 발생",
            str(e),
        ))

    if cuda_avail:
        add(DiagItem("torch.cuda.is_available()", DiagStatus.OK, "True"))
    else:
        add(DiagItem(
            "torch.cuda.is_available()",
            DiagStatus.FAIL,
            "False",
            "CUDA GPU가 PyTorch에 인식되지 않습니다.",
        ))
        if not result.root_cause and torch_cuda_ver:
            result.root_cause = "CUDA GPU가 PyTorch에 인식되지 않습니다."
            result.fix_summary.append("nvidia-smi 명령으로 GPU 인식 여부 먼저 확인하세요.")

    # ── 5. cuDNN ─────────────────────────────────────────────────────────────
    try:
        cudnn_avail = torch.backends.cudnn.is_available()
        if cudnn_avail:
            ver_int = torch.backends.cudnn.version()   # 예: 90201
            major   = ver_int // 10000
            minor   = (ver_int % 10000) // 100
            patch   = ver_int % 100
            add(DiagItem("cuDNN", DiagStatus.OK, f"{major}.{minor}.{patch}  (빌드번호 {ver_int})"))
        else:
            add(DiagItem(
                "cuDNN",
                DiagStatus.FAIL,
                "사용 불가",
                "cuDNN이 PyTorch 빌드에 포함되지 않았거나 드라이버 문제로 초기화 실패.",
                "CUDA 빌드 PyTorch에는 cuDNN이 내장되어 있습니다. 드라이버를 최신으로 업데이트하세요.",
            ))
    except Exception as e:
        add(DiagItem("cuDNN", DiagStatus.WARN, f"조회 실패: {e}"))

    # ── 6. GPU 상세 정보 ─────────────────────────────────────────────────────
    if cuda_avail:
        try:
            n = torch.cuda.device_count()
            add(DiagItem("GPU 개수", DiagStatus.OK, f"{n}개"))
            for i in range(n):
                name   = torch.cuda.get_device_name(i)
                cc     = torch.cuda.get_device_capability(i)
                prop   = torch.cuda.get_device_properties(i)
                mem_gb = prop.total_memory / (1024 ** 3)
                notes  = []
                if cc[0] < 5:
                    notes.append("CC < 5.0 — 최신 PyTorch 미지원")
                elif cc[0] == 5:
                    notes.append("Maxwell (CC 5.x) — CUDA 12.x 에서 커널 누락 가능")
                elif cc[0] == 6:
                    notes.append("Pascal (CC 6.x) — Tensor Core 없음, AMP 이득 없음")
                elif cc[0] == 7 and cc[1] == 0:
                    notes.append("Volta (CC 7.0) — AMP 사용 권장")
                status = DiagStatus.WARN if cc[0] < 6 else DiagStatus.OK
                note_str = f"  [{', '.join(notes)}]" if notes else ""
                add(DiagItem(
                    f"GPU [{i}]",
                    status,
                    f"{name} — CC {cc[0]}.{cc[1]}, {mem_gb:.1f} GB, {prop.multi_processor_count} SMs{note_str}",
                ))
        except Exception as e:
            add(DiagItem("GPU 정보", DiagStatus.WARN, f"조회 실패: {e}"))
    else:
        add(DiagItem("GPU 개수", DiagStatus.FAIL, "0개 (CUDA 미사용 가능)"))

    # ── 7. 실제 CUDA 텐서 할당 테스트 ───────────────────────────────────────
    if cuda_avail:
        try:
            probe = torch.zeros(1, device="cuda")
            torch.cuda.synchronize()
            del probe
            add(DiagItem("CUDA 텐서 할당", DiagStatus.OK, "성공"))
            result.cuda_available = True
        except Exception as e:
            add(DiagItem(
                "CUDA 텐서 할당",
                DiagStatus.FAIL,
                f"실패 — {type(e).__name__}",
                str(e),
                "GPU 메모리 부족 또는 드라이버 오류. nvidia-smi 로 상태를 확인하세요.",
            ))
            if not result.root_cause:
                result.root_cause = f"CUDA 텐서 할당 실패: {type(e).__name__}"

    # ── 8. Python / OS / 환경 변수 ──────────────────────────────────────────
    add(DiagItem(
        "Python",
        DiagStatus.INFO,
        f"{sys.version.split()[0]}  ({platform.architecture()[0]})  {sys.executable}",
    ))
    add(DiagItem("OS", DiagStatus.INFO, platform.platform()))
    cuda_path = os.environ.get("CUDA_PATH") or os.environ.get("CUDA_HOME") or "미설정"
    add(DiagItem("CUDA_PATH 환경변수", DiagStatus.INFO, cuda_path))

    if not result.cuda_available and not result.root_cause:
        result.root_cause = "CUDA 사용 불가 (원인 불명 — 로그를 확인하세요)"

    return result


# ── 내부 헬퍼 ─────────────────────────────────────────────────────────────────

def _query_nvidia_smi() -> tuple[str, str, list[str]]:
    """(driver_version, raw_output, gpu_name_list).  실패 시 ('', error_msg, [])."""
    try:
        out = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=driver_version,gpu_name,memory.total",
             "--format=csv,noheader"],
            capture_output=True, text=True, timeout=8,
        )
        if out.returncode == 0 and out.stdout.strip():
            lines = [l.strip() for l in out.stdout.strip().splitlines() if l.strip()]
            if lines:
                parts = lines[0].split(",")
                driver = parts[0].strip() if parts else ""
                gpu_names = []
                for line in lines:
                    p = line.split(",")
                    if len(p) >= 2:
                        gpu_names.append(f"{p[1].strip()} ({p[2].strip() if len(p) > 2 else '?'})")
                return driver, out.stdout, gpu_names
        # CSV 쿼리 실패 시 일반 nvidia-smi 로 재시도
        out2 = subprocess.run(["nvidia-smi"], capture_output=True, text=True, timeout=8)
        if out2.returncode == 0:
            for line in out2.stdout.splitlines():
                if "Driver Version" in line:
                    ver = line.split("Driver Version:")[1].strip().split()[0]
                    return ver, out2.stdout[:600], []
            return "", out2.stdout[:600], []
        return "", f"nvidia-smi 종료코드 {out.returncode}: {out.stderr[:300]}", []
    except FileNotFoundError:
        return (
            "",
            "nvidia-smi 를 찾을 수 없습니다.\n"
            "NVIDIA 드라이버가 설치되지 않았거나 PATH 에 없습니다.",
            [],
        )
    except Exception as e:
        return "", f"nvidia-smi 실행 중 오류: {e}", []


def _query_nvcc_version() -> str:
    """nvcc --version 에서 CUDA 버전 문자열을 추출. 없으면 ''."""
    try:
        out = subprocess.run(
            ["nvcc", "--version"],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0:
            for line in out.stdout.splitlines():
                if "release" in line.lower():
                    # "Cuda compilation tools, release 12.1, V12.1.66"
                    after = line.split("release", 1)[1]
                    return after.strip().split(",")[0].strip()
    except Exception:
        pass
    return ""
