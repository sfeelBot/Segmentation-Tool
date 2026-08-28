# Changelog — Segmentation Model UI

버전 구분 기준: 사용자 요청 단위로 묶어 릴리즈.  
형식: `[vX.Y.Z] YYYY-MM-DD` — Major.Minor.Patch

---

## [v1.10.2] 2026-08-28

### 수정
- GitHub #27: 일반 PowerShell/CMD에서 `build.bat` 실행 시 Microsoft Store용
  `WindowsApps\\python.exe` 별칭을 실제 Python으로 오인하던 문제 수정.
- 가상환경 활성화 없이 `py -3.12`로 등록된 시스템 Python 3.12를 우선 선택하고,
  실패 시에도 `WindowsApps` 별칭은 후보에서 제외.
- 필수 패키지가 없으면 선택된 Python에 실행할 정확한 pip 명령을 안내.

### 빌드
- installer 및 EXE 버전을 `1.10.2`로 갱신.

---

## [v1.10.1] 2026-08-28

### 수정
- `build.bat`이 프로젝트 의존성이 없는 다른 Python을 선택해 설치판에서
  `ModuleNotFoundError: No module named 'PyQt6'`가 발생할 수 있던 문제 수정.
- 선택한 단일 Python에서 PyQt6·PyInstaller를 먼저 검증하고 메타데이터 생성과
  PyInstaller 빌드까지 같은 인터프리터만 사용.
- Anaconda의 간접 의존성이 PyQt5/PySide를 함께 수집하지 않도록 PyQt6 외 Qt 바인딩 제외.
- PyQt6·PyTorch·torchvision·OpenCV·NumPy·Pillow·Albumentations·openpyxl·matplotlib을
  빌드 전에 모두 검사해, 오프라인 설치본에서 필수 패키지가 누락되는 불완전한 빌드를 차단.
- Windows 독립 실행본에서 Qt가 CUDA Torch보다 먼저 초기화되어 `c10.dll` WinError 1114가
  발생하지 않도록 Torch를 PyQt6보다 먼저 로드.

### 빌드
- installer 및 EXE 버전을 `1.10.1`로 갱신.

---

## [v1.10.0] 2026-08-28

### 추가
- GitHub #23 전체 이미지 비동기 추론과 즉시 진행률 표시.
- 최고 IoU Best Model과 epoch별 train/val loss·IoU JSON/PNG 자동 저장.
- 추론 결과 원본/오버레이 `F` 전환.
- 설치판 실행 직후 준비 상태와 현재 로딩 단계를 표시하는 시작 splash 화면.

### 수정 및 성능
- 오버레이 불투명도가 배경 밝기를 바꾸지 않도록 전경에만 혼합 적용.
- 슬라이더 입력 디바운스, 오버레이 재블렌딩, 줌·팬 보존과 대형 결과 메모리 복사 축소.
- 접근할 수 없는 최근 프로젝트 경로 때문에 시작 창이 열리지 않는 문제 수정.

### 빌드
- installer 및 EXE 버전을 `1.10.0`으로 갱신.

---

## [v1.9.0] 2026-08-27

### 추가
- 추론 결과에 AI score·픽셀 threshold를 제공하고 blob별 결과를 Excel로 내보내는 기능.
- 라벨링 목록에서 선택한 이미지 파일명을 `Ctrl+C`로 복사하는 기능 (GitHub #17).
- 기존 라벨을 경계로 사용하는 브러시 채우기와 도구 타입과 무관한 동일 클래스 병합
  (GitHub #15, #12).
- 라벨링 탭에서 여러 이미지를 선택해 한 번에 양품화하는 일괄 처리 기능.

### 수정 및 성능
- 첫 이미지 자동 로드 문제(BUG-017), annotation 삭제·가져오기·내보내기 병목과
  내보내기 메모리 부족 문제를 개선.
- 사용 중인 내보내기 파일의 잠금이 풀릴 때까지 재시도하도록 처리 (GitHub #16).

### 빌드
- `release.ini`를 버전·제품 정보의 단일 기준으로 사용하고 Windows EXE 및 installer
  버전 메타데이터를 자동 생성·검증.

---

## [v1.8.0] 2026-08-25

### 사용자 요청
> "v1.7.0 이후 13커밋이 쌓였다. 새 버전으로 태깅하고, exe/installer를 처음부터 다시
> 빌드해서 GitHub Release로 업데이트해줘."

### 추가
- **어노테이션 가져오기(Import)**: 내보내기(export)의 짝 기능. 이미지 목록에서 기존
  어노테이션과 충돌 시 덮어쓰기/기존 유지 정책을 선택해 가져올 수 있음
- **SegFormer / SegNeXt / PIDNet 모델 프리셋**: 모델 탭 프리셋 팝업에 최신 논문·주요
  기업 공개 세그멘테이션 아키텍처 3종 추가

### 수정
- 팬 드래그 중 휠 줌 시 초점이 어긋나던 문제 수정 (GitHub #9)
- 지우개 브러시 실시간 프리뷰 색상을 빨강 대신 중립 회색으로 변경 (칠하기 색과 혼동 방지)
- 브러시 채우기 시 시작·끝점 강제 연결 제거 (의도치 않은 폐곡선 생성 방지)

### 기술
- `installer/setup.iss`: `MyAppVersion "1.8.0"`
- `app/widgets/import_dialog.py`(신규): 가져오기 다이얼로그 (충돌 정책 선택 포함)
- `app/model_presets/`(신규 패키지): `segformer.py` / `segnext.py` / `pidnet.py` 프리셋 정의

---

## [v1.7.0] 2026-08-24

### 사용자 요청
> "github에 installer 빌드된 것까지 포함해서 올려줘."

v1.6.0 이후 161커밋 동안 버전 태깅이 누락된 채 기능 추가·GitHub 이슈 대응·성능
개선·UI 재편이 누적됐다. 이번 릴리즈는 그 전체를 하나의 배포 단위로 묶어 정식
버전을 매기고, 처음으로 Windows 설치 프로그램(exe installer)을 제공한다.

### 추가
- **Windows exe + Inno Setup 인스톨러**: `build.spec`(PyInstaller onedir) +
  `installer/setup.iss`(Inno Setup) + `build.bat` 원클릭 빌드 스크립트. per-user
  설치(관리자 권한 불필요), 앱 로고("Vertex Frame") 아이콘을 exe/설치 프로그램에 적용
- **프로젝트 내보내기/가져오기** (GitHub #2): 프로젝트 전체(이미지·어노테이션·체크포인트·
  classes.json)를 zip으로 내보내고 되가져오기
- **UI 재편**: 라벨링/학습/추론 탭에 자유 리사이즈 서브스플리터 적용, 학습 탭 큐 영역·
  추론 탭 이미지 목록(검색/정렬/트리형 폴더) 개편
- **LR 스케줄러 9종**, **CUDA 종합 진단 팝업**, 단축키 왼손 QWER 재배치, 폴더 접기/펼치기
  그룹 헤더, 앱 종료 전 확인 팝업, RGB 채널별 그레이스케일 뷰어 등 다수 UX 개선
- **디자인 톤 정리**: 장식 이모지 제거 → 기능 아이콘 19종 SVG/QIcon화, i18n 전체 영어
  전환, matplotlib 손실 그래프·모델 탭 에디터 팔레트를 앱 표준 배색으로 정규화

### 수정 (성능)
- 어노테이션 개수 증가 시 로딩 지연 8.6×/2.1× 개선(GitHub #6-B), 오버레이 재생성 중
  깜빡임 제거(#6-A), 학습 데이터로더 이미지 캐시 + `num_workers` 자동 감지,
  추론 결과 미리보기 다운스케일, 이미지 브라우저 검색 디바운스, 앱 기동 시
  torchvision/albumentations 지연 임포트로 콜드 스타트 단축
- `rle_encode` 언더플로우로 인한 데이터 유실(BUG-002), 캔버스 유령 어노테이션·undo
  OOM 크래시(BUG-003/014), 서브스플리터 접힘·아이콘 stale 경쟁조건·브러시 크기
  다이얼로그 stray 어노테이션 등 버그 다수 수정 (BUG-005~015)
- `build.bat` 한글 텍스트 인코딩 깨짐(`chcp 65001`로도 못 잡던 파싱 오류) → ASCII 전환,
  `SetupIconFile` 경로를 dist 레이아웃 대신 소스 저장소 기준으로 고정

### 기술
- `installer/setup.iss`: `MyAppVersion "1.7.0"`, `PrivilegesRequired=lowest`,
  `SetupIconFile=..\app\resources\app_icon.ico`
- `app/resources/app_icon.ico` 신규 자산 (앱/exe/설치 프로그램 공용 아이콘)

---

## [v1.6.0] 2026-05-16

### 사용자 요청
> "첫번째 도구에서 선이 연결되는걸 찾는게 어려워. 적당히 합쳐질 것 같으면 합쳐질 수 있도록 해줘. UI 상에서 원의 테두리가 흰색으로 칠해진다거나 하는 방식으로 구별해줘. RGB를 분리해서 볼 수 있도록 해줘 — 이미지 뷰어 밑에 UI를 분리해서 만들어줘. 마우스가 올라가있는 부분의 pixel 값들도 옆에다가 label로 표시해줘."

### 추가
- **폴리곤 Snap-to-Close**: 첫 꼭짓점 15px 이내 접근 시 흰 원 + 반투명 내부 표시 → 클릭으로 즉시 닫기 (더블클릭 불필요)
- **채널 분리 뷰어**: 캔버스 하단 20px 스트립에 [원본] [R] [G] [B] 토글 버튼
- **픽셀 값 표시**: 마우스 위치의 `x,y  R:255  G:128  B:0` 실시간 표시 (스트립 우측)

### 기술
- `annotation_canvas.py`: `_poly_snap` 상태, `_SNAP_PX=15`, `pixel_hovered` 시그널, `set_channel()`, `_apply_channel_filter()`, `_cache_pixel_image()`
- `labeling_tab.py`: `_build_channel_strip()`, `_on_pixel_hovered()`, `QButtonGroup` 채널 뮤텍스

---

## [v1.5.0] 2026-05-16

### 사용자 요청
> "annotation 있는 이미지를 불러올 때 되게 느려."  
> "annotation 처음 그릴때는 속도가 괜찮은데 하나 그리고 나서부터 되게 느려."

### 수정 (성능)
- **`rle_encode` Python 루프 → numpy 벡터화**: 2000만 픽셀 순회 제거 → `np.diff + np.where` 수 ms
- **저장 백그라운드 스레드**: `_do_save` 에서 `rle_encode` 를 `threading.Thread(daemon=True)` 로 분리
- **오버레이 백그라운드 빌드**: `_OverlayWorker(QThread)` — 이미지 즉시 표시, 오버레이 비동기 교체

---

## [v1.4.0] 2026-05-16

### 사용자 요청
> "이미지 로드할때부터 엄청 느려. 여전히 너무 느려. 어디서 병목이 생기는지 확인할 수 있도록 log 를 만들어줘."  
> "perf log 기반으로 다시 최적화해줘."

### 추가
- **PerfProfiler** (`app/core/perf_logger.py`): 30프레임마다 단계별 avg/max ms 리포트 → `data/logs/perf.log`
- **Bbox 기반 마스크 연산**: `_resolve_overlap_and_merge`, `_consolidate_class_region` — 전체 20MP 대신 칠한 bbox 영역만 처리 (500× 빠름)
- **`_flood_erase` bbox 최적화**: connectedComponents 를 non-zero bbox 로 제한

### 수정 (성능)
- `_apply_eraser`: bbox 단락 평가로 빈 마스크 검사 개선
- `change_selected_class`: 선택 어노테이션 union bbox 기준 통합

---

## [v1.3.0] 2026-05-04

### 사용자 요청
> "라벨링할 때 엄청 버벅이고 있어. 이미지가 20MP 카메라로 찍은 거라 5000×4000 정도야."

### 추가 / 수정 (성능)
- **Display Pixmap 캐시**: zoom 버킷별 pre-scaled pixmap → 25× 작아진 blit 비용
- **Overlay 해상도 캡 (`MAX_OVERLAY_DIM=2048`)**: 80MB ARGB32 → 13MB (6× 감소)
- **Pan/Zoom 30Hz 쓰로틀**: `_schedule_repaint()` — mousemove마다 update() 방지
- **Smooth 백그라운드 스케일** (`_SmoothScaleWorker`): idle 후 고품질 보간을 비블로킹으로

---

## [v1.2.0] 2026-05-04

### 사용자 요청
> "추론에서 무조건 모델을 업로드해야 하는 것 같아. 체크포인트를 선택하면 학습할 때 사용했던 모델로만 돌릴 수 있게 해줘."

### 수정
- 체크포인트 선택 즉시 `config.model_source` 읽어 모델 자동 인스턴스화
- 추론 탭 체크포인트 테이블에 "모델" 컬럼 추가
- 체크포인트 메타에 `model_source` 저장 (trainer)

### 사용자 요청
> "학습할 때 AI 모델을 선택할 수 있도록 변경해줘. AI 모델 프리셋 부분 추가하는 건 따로 팝업을 띄우는 식으로 바꿔줘."

### 추가
- **`ModelPresetDialog`** 팝업: 7종 프리셋 목록 + 설명 + 에디터 불러오기
- **학습 탭 모델 선택**: 큐 작업별 모델 드롭다운 (현재 로드 or 프리셋)

### 사용자 요청
> "학습 창에서 손실 그래프 크기를 키워줘. Y축으로 키우라는 이야기야. EPOCH 메트릭과 체크포인트는 최소한으로 옆에다가 작게 만들거나 삭제해."

### 수정
- 손실 그래프 / 메트릭·체크포인트 수평 분할 (QSplitter)
- 메트릭 3열(Ep/Val/IoU), 10px 소형 폰트

---

## [v1.1.0] 2026-05-04

### 사용자 요청
> "학습할 때 PATCH TRAINING 이면 EPOCH 이랑 다르게 샘플링 이미지는 많아서 LOSS 들이 더 많이 나오지 않아? 이걸 시간 순서대로 TRAIN, VAL LOSS 그래프에 더 실시간으로 그려질 수 있게 하면 좋을 것 같은데."

### 추가
- **배치 레벨 실시간 Train Loss**: `training_started(total_batches)` 시그널 → 분수 epoch 좌표
- **EMA 스무딩** (α=0.08): 노이즈 많은 배치 loss 부드럽게
- **Step 카운터**: `Step N / M · ETA HH:MM` 스텝 기반 정확한 ETA
- **Epoch 경계 점선**: 그래프에 epoch 구분선 자동 추가

### 사용자 요청
> "현재 이미지에서의 라벨링 데이터를 볼 수 있는 리스트창을 하나 추가해주고 그 리스트에서 선택 시 해당 라벨링 데이터가 표시될 수 있게 해줘."  
> "같은 class라도 다른 곳에 있으면 따로 표시해줘."

### 추가
- 어노테이션 목록 패널 (오른쪽 180px): `#순번 [타입] 클래스명 @(cx,cy) · 면적px`
- 목록↔캔버스 양방향 선택 동기화

---

## [v1.0.0] 2026-04-19  (초기 완성 버전)

### 사용자 요청
> "PyTorch 세그멘테이션 모델을 위한 로컬 데스크탑 GUI. 라벨링 → 학습 → 추론 전 과정."

### 구현된 전체 기능

#### 🗂 프로젝트 시스템
- 시작 다이얼로그: 새 프로젝트 / 기존 열기 / 최근 목록
- 프로젝트별 격리: images / annotations / checkpoints / user_models / classes.json
- 전환 버튼 🔄, 폴더 열기 📁, 저장 경로 설정 (설정 탭)

#### 🎨 라벨링 탭
- 도구: 📐폴리곤 / 🖌브러시 / 🪣윤곽채우기 / 🧹지우개 / 🧲연결지우개 / 🔲선택 / ✋이동
- 브러시 픽셀 독점성 + 같은 클래스 연결 자동 병합
- 선택 도구: 단일클릭 / Shift다중 / 드래그범위 / 이동(드래그)
- 이미지 목록: 리스트뷰 ●라벨됨 ✓OK ○미라벨, 다중선택 Del 삭제
- ✅ OK 표시 / N 이전 이미지 어노테이션 복사
- ↑↓ 이미지 이동, Tab 패널 숨김
- 어노테이션 목록 패널 / 로그 패널

#### 🎯 학습 탭
- 다중 작업 큐 (이름 설정, 작업별 모델 선택)
- 실시간 손실 그래프 (배치 레벨 EMA + Epoch Val)
- Step 카운터 + 스텝 기반 ETA
- 진행 팝업 (비모달)
- 자동 patches_per_image 계산 버튼 🔄

#### 🔍 추론 탭
- resize / sliding_window 모드, 오버랩 설정
- 체크포인트 선택 시 모델 자동 결정
- 투명도 슬라이더, 클래스 범례

#### 🧠 모델 탭
- AST 샌드박스 검증 + 제한적 exec
- 📚 프리셋 팝업 (7종: U-Net / U-Net++ / Attention U-Net / DeepLabV3 계열 / FPN-SegNet)

#### ✨ 오토 라벨링
- 빠른 학습 + 오토 라벨링 (고정 30 epochs, 결함 우선 샘플링)
- 미리보기 팝업 → 합치기 확인 후 저장

#### ⚙️ 설정
- 언어 (한국어 / English)
- 단축키 테이블
- 로그 경로 (app.log / errors.log / perf.log)
- 프로젝트 저장 경로

#### 📤 내보내기
- JSON (상대좌표) / YOLO-seg / COCO 포맷

#### 🔧 성능 / 안정성
- GPU 사용 불가 시 팝업 (CPU 진행 여부)
- AMP CC<7.0 자동 비활성화
- Maxwell/Pascal GPU 경고
- 배경 overlay/smooth 스케일 (비블로킹)
- Bbox 기반 마스크 연산

---

## 버전 관리 정책

```
vMAJOR.MINOR.PATCH
  MAJOR: 핵심 아키텍처 변경 (프로젝트 시스템, 학습 파이프라인 등)
  MINOR: 기능 추가 (새 도구, 탭, 다이얼로그)
  PATCH: 버그 수정, 성능 개선, UI 조정
```

### 브랜치 전략 (권장)
```
main        — 안정 버전 (릴리즈 태그)
dev         — 개발 통합
feature/*   — 개별 기능
hotfix/*    — 긴급 수정
```

### 커밋 메시지 형식
```
feat: 새 기능 요약
fix:  버그 수정 요약
perf: 성능 개선
docs: 문서만 변경
refactor: 기능 변경 없는 코드 정리
```
