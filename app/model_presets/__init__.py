"""산업용 검사에 자주 쓰이는 최신 세그멘테이션 모델 프리셋 모음.

각 프리셋은 단일 Python 파일로 저장되어 있으며, 모델 탭의 드롭다운에서 선택해
에디터에 그대로 불러올 수 있다. 모든 프리셋은 `model_validator` 를 통과하도록
허용된 import 만 사용한다.
"""
from dataclasses import dataclass
from pathlib import Path

PRESET_DIR = Path(__file__).parent


@dataclass
class PresetInfo:
    key: str           # 파일명 (확장자 제외)
    title: str         # 드롭다운에 표시될 이름
    tagline: str       # 한줄 요약
    use_case: str      # 어디에 쓰기 좋은가
    params: str        # 대략적 파라미터 수
    pros: str
    cons: str


PRESETS: list[PresetInfo] = [
    PresetInfo(
        key="simple_unet",
        title="U-Net (2015) — 표준 베이스라인",
        tagline="가장 고전적이고 신뢰성 높은 세그멘테이션 네트워크",
        use_case="소량 데이터의 표면 결함·균열 검출, 의료영상, 산업 QC의 기본 베이스라인",
        params="≈ 2.0M",
        pros="빠른 학습, 적은 데이터에서도 동작, 해석 용이",
        cons="수용영역이 제한적이라 대형 구조 인식에 약함",
    ),
    PresetInfo(
        key="unet_plusplus",
        title="U-Net++ (2018) — 촘촘한 스킵 연결",
        tagline="중첩 디코더로 경계 품질과 세부 정확도 향상",
        use_case="미세 결함·작은 스크래치·PCB 인쇄 결함 등 세부 경계가 중요한 작업",
        params="≈ 9.0M",
        pros="경계 정밀도 향상, Deep supervision 가능",
        cons="메모리·연산량 증가",
    ),
    PresetInfo(
        key="attention_unet",
        title="Attention U-Net (2018) — 관심영역 집중",
        tagline="스킵 연결에 Attention Gate 를 추가해 잡음에 강함",
        use_case="배경이 복잡한 현장(금속 표면, 직물, 용접부) 결함 탐지",
        params="≈ 3.0M",
        pros="관심영역 자동 강조, 잡음 억제",
        cons="U-Net 대비 약간의 추가 연산",
    ),
    PresetInfo(
        key="deeplab_mobilenet",
        title="DeepLabV3 + MobileNetV3 — 경량 다중스케일",
        tagline="torchvision의 경량 DeepLab — 다양한 크기의 결함에 강함",
        use_case="엣지·임베디드 배포, 양·저품질 혼재 라인 검사, 실시간 요구",
        params="≈ 11M",
        pros="ASPP 로 다중스케일 처리, 모바일 친화적",
        cons="사전학습 가중치 없이 학습 시 수렴이 느릴 수 있음",
    ),
    PresetInfo(
        key="deeplab_resnet",
        title="DeepLabV3 + ResNet50 — 고정확도",
        tagline="산업 표준급 정확도, 넓은 수용영역",
        use_case="고정 설비의 고정확 검사(반도체, 디스플레이, 자동차 외판)",
        params="≈ 40M",
        pros="최고 수준의 정확도, 안정적 수렴",
        cons="무거움, 큰 GPU·많은 데이터 권장",
    ),
    PresetInfo(
        key="lraspp_mobilenet",
        title="LR-ASPP + MobileNetV3 — 초경량 실시간",
        tagline="추론 속도가 최우선인 생산 라인용",
        use_case="컨베이어·고속 카메라·드론 탑재 검사(실시간 FPS 중요)",
        params="≈ 3.2M",
        pros="매우 빠른 추론, 작은 모델 크기",
        cons="정확도는 중간 수준",
    ),
    PresetInfo(
        key="fpn_segnet",
        title="FPN-SegNet — 다중스케일 피라미드",
        tagline="서로 다른 크기의 결함을 동시에 잘 잡는 FPN 구조",
        use_case="결함 크기 편차가 큰 현장(작은 핀홀부터 큰 변형까지)",
        params="≈ 7M",
        pros="스케일 변동에 강건, 균형잡힌 성능",
        cons="커스텀 구현 — 튜닝 여지 있음",
    ),
    PresetInfo(
        key="segformer",
        title="SegFormer (2021) — 경량 트랜스포머",
        tagline="계층적 트랜스포머 인코더 + all-MLP 디코더, 위치인코딩 없이 Mix-FFN으로 대체",
        use_case="조명·질감 변화가 큰 현장에서 전역 문맥이 중요한 대형 이물·넓은 얼룩·표면 패턴 이상 검출",
        params="≈ 3.7M",
        pros="넓은 수용영역, 해상도에 강건한 Efficient Self-Attention",
        cons="CNN 계열보다 학습에 더 많은 데이터·시간이 필요할 수 있음",
    ),
    PresetInfo(
        key="segnext",
        title="SegNeXt (2022) — 대형 커널 conv attention",
        tagline="Self-attention 없이 MSCA(멀티스케일 스트립 conv)로 트랜스포머급 문맥 포착",
        use_case="실시간성이 필요하면서도 넓은 수용영역이 필요한 도장·코팅면 얼룩, 직물 패턴 결함 검출",
        params="≈ 3.4M",
        pros="연산 대비 성능 우수, self-attention보다 가볍고 빠름",
        cons="원 논문의 Hamburger 디코더를 경량 concat-fuse 디코더로 단순화 — 정확도는 원 논문보다 낮을 수 있음",
    ),
    PresetInfo(
        key="pidnet",
        title="PIDNet (2023) — 실시간 3-브랜치",
        tagline="Detail/Context/Boundary 3-브랜치, 경계 attention 게이트로 융합하는 실시간 구조",
        use_case="컨베이어·고속 라인 등 실시간 처리량이 중요하면서 경계가 뚜렷한 스크래치·크랙 검출",
        params="≈ 0.9M",
        pros="매우 가볍고 빠름, boundary attention으로 경계 품질 보완",
        cons="단일 출력 계약상 boundary는 내부 게이트로만 사용 — 원 논문의 auxiliary loss 학습은 미지원",
    ),
]


def load_preset_code(key: str) -> str:
    path = PRESET_DIR / f"{key}.py"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def preset_by_key(key: str) -> PresetInfo | None:
    for p in PRESETS:
        if p.key == key:
            return p
    return None
