# Segmentation-Tool

PyTorch 세그멘테이션 모델을 위한 로컬 데스크탑 GUI. 라벨링 → 학습 → 추론 전 과정을 하나의
앱에서 수행합니다.

## 다운로드

Windows용 설치 프로그램(exe)은 [Releases](https://github.com/sfeelBot/Segmentation-Tool/releases/latest) 페이지에서 받을 수 있습니다. 소스 빌드 없이 바로 설치해서 쓰려면 이쪽을 이용하세요.

## 설치 (소스에서 직접 실행)

```powershell
# 1) 가상환경
py -3.12 -m venv .venv
.venv\Scripts\activate

# 2) PyTorch — 반드시 GPU에 맞는 CUDA 빌드로 먼저 설치 (순서 중요!)
#    이 단계를 건너뛰고 바로 requirements.txt를 설치하면 CPU 전용 빌드가 깔립니다.
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128

# 3) 나머지 의존성
pip install -r requirements.txt

# 4) 실행
python main.py
```

GPU별 CUDA 빌드 선택은 [docs/USER_MANUAL.md](docs/USER_MANUAL.md#-시작하기)의 표를 참고하세요.

## 문서

- [docs/USER_MANUAL.md](docs/USER_MANUAL.md) — 사용자 매뉴얼 (설치, 워크플로우, 단축키, 트러블슈팅)
- [docs/USER_MANUAL_ZONE.html](docs/USER_MANUAL_ZONE.html) — Zone 분석 에디션 사용자 매뉴얼 (실제 UI 캡처, 프로젝트 시작부터 존 분석까지 전체 흐름)
- [CLAUDE.md](CLAUDE.md) — 프로젝트 구조·개발 규칙
- [QA.md](QA.md) — 버그·VOC 추적
