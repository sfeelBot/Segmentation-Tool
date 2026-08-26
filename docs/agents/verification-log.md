# 검증 (Verification) 로그

역할 설명은 [README.md](README.md) 참고. append-only — 최신 항목이 아래에 추가된다.

---

## 2026-08-19 — main.py 스타일시트 오타 발견

### 발견
- `main.py:114` — `QLineEdit, QSpinBox, ...` 셀렉터의 `border: 1px solid #74151;` 이 유효하지 않은 hex 색상값(5자리)으로 되어 있음.
- 동일 파일 내 `#374151` 이 14곳에서 일관되게 사용되고 있어 (75, 99, 108, 152, 168, 188, 189, 195, 202, 224, 229, 240, 288, 293행), 해당 라인만 글자 하나가 누락된 오타로 판단.
- 무효 hex는 Qt 스타일시트 파서가 무시하거나 기본값으로 폴백할 수 있어, 입력 위젯(QLineEdit/QSpinBox/QDoubleSpinBox/QComboBox/QPlainTextEdit/QTextEdit) 테두리가 다른 위젯과 다르게 렌더링될 가능성.

### 조치
- [implementation-log.md](implementation-log.md) 에서 `#374151` 로 수정 완료. git 커밋 전 상태이므로 실행 확인은 다음 앱 구동 시 육안 확인 필요 (미완료 — 앱을 직접 띄워보지는 않음).

### 비고
- `projects/nok/annotations/*.json`, `classes.json` 변경은 버그 아님 — 정상 라벨링 데이터 (기획 로그 참고).

---

## 2026-08-19 — 전체 병목(Perf) 검증 — projects/nok 실데이터 기반 실측 + 정적 분석

### 배경 · 방법
- 범위: "여러 항목에서 병목" 보고에 따라 특정 탭이 아닌 전체(앱 기동, 프로젝트/이미지 목록 포함).
- GUI 자동클릭 불가 전제 → `app/core/` Qt 비의존 로직을 실제 `projects/nok/` 데이터(이미지 5장, 각 57.11MB BMP 5472×3648; 어노테이션 5개 중 4개가 polygon 포함, brush_mask 없음; 체크포인트 없음)로 직접 호출해 `time.perf_counter()` 로 단계별 실측.
- 벤치마크 스크립트: `C:\Users\Feel\AppData\Local\Temp\claude\d--segmentation-model\56a2e70d-4430-40c3-96ed-f10c2f90fcf9\scratchpad\bench_perf.py` (읽기 전용 — `projects/nok/` 무수정 확인, 실행 결과 원본은 같은 폴더 `bench_stdout.txt`/`bench_result.txt`).
- 실행 환경: Windows 11, Anaconda Python 3.13.9 (`/c/Users/Feel/anaconda3/python.exe`, 프로젝트 `requirements.txt` 와 별개로 이 환경에 실제 설치된 인터프리터), PyTorch 2.11.0+cu128, CUDA 사용 가능(RTX 5060). `QT_QPA_PLATFORM=offscreen` 으로 QApplication 을 오프스크린 생성해 QPixmap 디코딩만 측정(실제 창 표시·클릭 없음).
- `project.set_current()` 대신 `project._current` 를 직접 대입해 `data/settings.json`(recent_projects/last_project) 부작용을 피함 — nok 데이터 및 전역 설정 모두 실행 전후 무변경 확인(`git status` clean, 파일 mtime 불변).
- 기존 `data/logs/perf.log`(실사용 중 캔버스 렌더링 프로파일, `app/core/perf_logger.py`)도 함께 검토해 브러시 도구 관련 실사용 스파이크를 교차 확인.

### 병목 리스트 (심각도 순, P0~P3)

| # | 심각도 | 위치 | 내용 | 근거 | 근본 원인 | 체감 영향 |
|---|---|---|---|---|---|---|
| 1 | P0(버그) | `app/core/annotation_store.py` `rle_encode()` | brush_mask 어노테이션이 저장 시 항상 빈 RLE(`""`)가 되어 전량 데이터 유실 | 실측 재현 (100px, 170만px 마스크 모두 재현) | `np.diff(flat_uint8,...)` 가 uint8 dtype 유지 → 1→0 하강엣지가 언더플로우로 255가 되어 `diff==-1` 매칭 실패 | 브러시 도구로 라벨링한 모든 마스크가 저장 후 사라짐. **QA.md BUG-002 로 별도 등록** (성능 항목 아님) |
| 2 | P1 | `main.py` `_preload_libs()` | 앱 기동 시 QApplication 생성 전 콜드 임포트 비용 합계 ≈3.3초 (albumentations 1888ms, torchvision 833ms, PyQt6 110ms, numpy/cv2/PIL/matplotlib ~200ms, `app.*` 모듈 그래프 193ms) | 실측 | 무거운 라이브러리 동기 로드, 특히 albumentations·torchvision 이 압도적 | 앱을 켤 때마다 스플래시 없이 3초+ 정지 — "전체 공통 부분" 병목의 핵심 |
| 3 | P1 | `app/core/dataset.py:59` `SegmentationDataset.__getitem__` + `app/widgets/config_form.py:101` `num_workers` 기본값 0 | 학습 시 patch 마다 원본 이미지를 캐시 없이 매번 재디코딩(57MB BMP), DataLoader 배치 1개(batch=4, num_workers=0) 505ms vs 동일 배치 GPU forward 60ms / 학습 스텝 165ms | 실측 (`__getitem__` 65~140ms/회, batch fetch 505ms, CUDA step 165ms) | 이미지 디코딩 캐시 부재 + `patches_per_image=50` 인 random_crop 모드에서 같은 이미지를 패치마다 처음부터 재decode + 기본 num_workers=0(UI 기본값)로 오버랩 로딩 없음 | GPU가 대부분 유휴 상태로 대기 — 학습 속도가 이론상 가능한 것보다 3~8배 느림. nok 같은 대형 원본 이미지 프로젝트에서 특히 심각 |
| 4 | P2 | `app/widgets/annotation_canvas.py:245` `load_image()` | 이미지 전환마다 `QPixmap(str(path))` 재디코딩, LRU 캐시·프리페치 없음 | 실측 (1장 디코딩 70~95ms, warm 상태도 68~81ms — I/O 아닌 디코딩 자체 비용, 순수 `os.read()` warm 은 15ms에 불과; 5장 연속 전환 366ms) | 디코딩/스케일 결과를 전혀 캐시하지 않음, 인접 이미지 프리로드 로직 부재 | PageDown/X 로 이미지 넘길 때마다 70~90ms 프리즈. 코디네이터가 제기한 "50MB 이미지 I/O" 우려는 디스크 I/O 자체보다 **QPixmap 디코딩**이 주 원인으로 확인됨(I/O vs 디코딩 구분됨) |
| 5 | P2 | `app/core/inference_engine.py:302` `_colorize_and_blend()` | 원본 해상도(5472×3648, nok 기준) 그대로 컬러화+블렌딩 | 실측 (합성 class_map 사용, 실제 체크포인트 없어 end-to-end는 아님) — 992ms/회, 클래스 수 비례 증가 | 다운스케일 없이 항상 원본 해상도로 처리 | "추론 실행" 클릭 후 결과 표시까지 체크포인트 로드+forward 와 별개로 ~1초 추가 지연 |
| 6 | P2(정적) | `app/widgets/image_browser.py:270-272, 398, 497, 501` `_on_search_changed → _apply_display` | 검색창 keystroke 마다 전체 이미지에 대해 `get_label_status()`(JSON open+parse) 재실행 + QTreeWidget 전체 clear/rebuild | 정적 분석 + nok(5장) 소규모 실측 외삽(5장 10회 keystroke 시뮬레이션 5ms, 파일당 0.13ms — 이미지 수에 선형 비례) | 캐시/디바운스 없이 매 keystroke 마다 전체 스캔 | 5장에서는 무해하지만 수백~수천 장 프로젝트에서는 타이핑마다 메인 스레드 수백ms 블로킹 가능성 (미실측 — nok 데이터로는 재현 규모 안 됨) |
| 7 | P3(실측 혼합) | `app/widgets/annotation_canvas.py:996-1002` `_resolve_overlap_and_merge._has_pixels` | bbox 안에 새 픽셀이 없는 예외 케이스에서 전체 해상도(20MP) `mask.any()` fallback | 과거 실사용 `data/logs/perf.log`(09:34 기록) 에서 `resolve_bbox_overlap avg=43.4ms max=43.4ms n=1` 스파이크 실측 확인 | bbox 최적화가 대부분 케이스는 커버하지만 fallback 경로는 여전히 전체 배열 스캔 | 브러시 스트로크 중 드물게 40ms대 프레임 드랍 — 이미 대부분 최적화되어 있어 영향 작음 |
| 8 | P3(정적) | `app/core/auto_labeler.py:104-106` `collect_unlabeled()` | 이미지마다 `get_ok()` + `load()` 로 동일 JSON 을 2회 중복 read+parse | 정적 분석 | `get_label_status()` 로 통합하면 1회로 축소 가능 | 오토라벨 대상 수집 시 1회성 비용, 영향 미미 |

### 실측 vs 정적 분석 구분
- **실측**: #1(버그), #2, #3, #4, #5, #7(과거 perf.log) — 모두 `bench_perf.py` 로 nok 실데이터 직접 호출 또는 기존 perf.log 기록 기반.
- **정적 분석(코드 리뷰만, 미실측)**: #6, #8 — nok 프로젝트 규모(5장)로는 스케일 문제가 드러나지 않아 코드 흐름과 API 시맨틱스 근거로 추정.
- 추가 참고(버그 아님, 성능 아님): `image_browser.reload()` 는 `images_dir().glob(pat)` 비재귀 스캔이라 하위폴더 이미지를 찾지 못하는데 `_build_folder_tree()` 는 하위폴더 그룹핑을 전제로 함 — 코드 주석상 "flat 스캔 의도적" 이라 되어 있어 버그로 단정하지 않고 참고만 기재.

### 메모리
- nok 이미지 5장(QPixmap+PIL RGB) 동시 보유 시뮬레이션: RSS 델타 +761.6MB (장당 ~152MB, 5472×3648 RGB 이론값 57.1MB 대비 약 2.7배 — QPixmap 내부 포맷 변환·Qt 네이티브 버퍼·중복 보유 등 누적 추정). tracemalloc 은 Python 힙만 추적해 대부분 안 잡힘(peak 0.2MB) — Qt 네이티브 메모리는 RSS로만 확인 가능. `psutil` 은 이미 설치돼 있어 추가 설치 없이 사용.
- 실제 라벨링 탭은 평소 이미지 1장만 보유하므로 이 시나리오 자체가 즉시 발생하진 않으나, 오토라벨 미리보기 등 여러 이미지를 동시에 들고 있을 수 있는 기능에서 메모리 압박 가능성 있음 (정적 우려, 미실측).

### 결론 / 다음 단계 참고
- BUG-002(P0)는 즉시 수정이 필요한 데이터 유실 버그 — 성능 튜닝과 별개로 최우선 처리 권장.
- 성능 개선 우선순위는 #2(기동 임포트) → #3(학습 데이터로더) → #4(이미지 전환 캐시) 순으로 사용자 체감/개발 난이도 대비 효과가 클 것으로 판단되나, 실제 개선 계획 수립은 이번 임무 범위 밖(기획 단계에서 결정).
- `projects/nok/`, `data/settings.json` 모두 실행 전후 무변경 확인 (`git status` clean, 파일 mtime 불변). 코드 수정 없음.

---

## 2026-08-19 — R1: BUG-002 수정 독립 재검증 (커밋 `3ce4dc9`, `304c7b6`)

구현 로그([implementation-log.md](implementation-log.md) "R1: BUG-002 brush_mask RLE 인코딩
언더플로우 수정")의 자체 회귀 확인을 구현자 주장 그대로 신뢰하지 않고 독립적으로 재실행.

### 확인 항목 및 결과

1. **커밋 범위 확인** — `git show --stat 3ce4dc9`: `QA.md`, `app/core/annotation_store.py` 2개
   파일만 변경(+4/-2 in annotation_store.py). `git show --stat 304c7b6`: `docs/agents/
   implementation-log.md`만 변경. 구현 로그의 "annotation_store.py만(그리고 관련 문서)" 주장과
   일치. 의도치 않은 다른 파일 변경 없음.
2. **코드 판단** — `app/core/annotation_store.py:206-226` `rle_encode()` 직접 읽음. 수정 전
   `np.diff(flat_uint8, prepend=0, append=0)`는 dtype이 uint8로 유지되어 1→0 하강엣지가
   `-1` → `255`로 언더플로우되는 것이 맞고, 수정 후 `flat.astype(np.int8)`(prepend/append도
   `np.int8(0)`)로 캐스팅하면 `-1`이 부호 있는 정수로 정상 표현되어 `np.where(diff == -1)`이
   정상 동작함을 코드 레벨에서 확인. 기존 `n = min(len(starts), len(ends))` 경쟁조건 방어
   코드는 그대로 유지되어 있고 이번 수정과 독립적인 안전장치임도 확인.
3. **독립 재현 스크립트** — 구현자 스크립트를 재사용하지 않고 별도 작성
   (`.../scratchpad/verify_r1.py`, 프로젝트에는 추가 안 함). `d:\segmentation model`을
   `sys.path`에 넣고 `app.core.annotation_store`의 `rle_encode`/`rle_decode`를 직접 import해
   9개 케이스 라운드트립 검증:
   - 100px 블록(100×100) — PASS
   - ~1.8Mpx 마스크(1000×1800, 두 블록 + 5만px 랜덤 토글 스캐터, 최종 nonzero 495,840px,
     구현자와 다른 크기·시드·패턴으로 독립 구성) — PASS, encode+decode 37.7ms
   - 빈 마스크 → `""` 반환 정상 — PASS
   - 전체 1인 마스크(30×30) — PASS
   - 배열 끝까지 이어지는 run(마지막 15픽셀) — PASS
   - 단일 픽셀 마스크 — PASS
   - 체스판 패턴(다수의 매우 짧은 run, diff 부호 스트레스 테스트) — PASS **(구현자 케이스에
     없던 추가 엣지케이스)**
   - 배열 첫 픽셀부터 시작하는 run(prepend 경계) — PASS **(추가 엣지케이스)**
   - bool dtype 입력 마스크 — PASS **(추가 엣지케이스, mask가 bool로 들어올 가능성 대비)**
   → 9/9 전부 원본과 100% 일치. 언더플로우 재발 없음.
4. **앱 기동 확인** — `.../scratchpad/verify_app_boot.py` 작성해 `main.py`와 동일한 순서
   (QApplication 생성 → `projects/nok` 오픈 → `MainWindow()` 생성 → `show()`)로 실행.
   `numpy/cv2/PIL/albumentations/torch/torchvision` 프리로드부터 `MainWindow` 생성(라벨링
   탭 포함 — annotation_store를 사용하는 경로)까지 예외 없이 "STEP3_OK" 도달 확인. 단,
   `app.exec()` 이벤트 루프는 이 비대화형 자동화 셸(Windows Session 0류 격리로 추정,
   대화형 데스크톱 세션 아님)에서 `QTimer.singleShot`으로 예약한 자동 종료가 트리거되지
   않고 계속 대기 상태로 남아 타임아웃 처리(`TaskStop`)함. 이는 GUI 자동화가 불가능한 이
   환경 자체의 제약으로 판단되며 — 윈도우 생성 자체(`show()`)는 예외 없이 성공했고, R1
   변경분은 `annotation_store.py`의 순수 함수 2개뿐으로 이벤트 루프/메시지 펌프 동작과
   무관함 — R1 코드 변경으로 인한 회귀로 보지 않음. `python main.py` 자체를 대화형 세션에서
   최종 눈으로 띄워보는 것은 리더/사용자 환경에서 재확인 권장.
5. **polygon 미영향 확인** — `load()`/`save()`의 `a.type == "polygon"` 분기가 `rle_encode`/
   `rle_decode`를 전혀 호출하지 않음을 코드로 확인. `projects/nok/annotations/*.json` 5개
   파일 전부 `grep '"type":'` 결과 `"polygon"`만 존재(brush_mask 없음) — 실피해 없음 재확인.
   추가로 `.../scratchpad/verify_nok_load.py`(읽기 전용)로 `annotation_store.load()`를
   nok 프로젝트에 실제로 열어 5개 파일 모두 로드: `10번.json`(0건, 원본이 빈 배열이라 정상),
   `11번/8번/9번.json`(각 1건 polygon), `7번.json`(2건 polygon) — 전부 예외 없이 로드되고
   전량 `type='polygon'`으로 확인. `projects/nok/` 원본 파일은 읽기만 하고 수정하지 않음.

### 판정
- 구현자 주장과 결과 일치 — 재현 실패나 회귀 없음. R1(BUG-002) 검증 **통과**.
- QA.md의 BUG-002 Closed 처리, R1 표기 그대로 유효.
- 이 검증 세션에서 프로젝트 코드는 전혀 수정하지 않음(`git status` 로 annotation_store.py
  등 코드 파일 변경 없음 확인, 검증 로그 파일 자체의 append만 예외).

### 비고
- `git status` 상 `docs/agents/leader-log.md`, `planning-log.md`, `decisions-needed.md`,
  `roadmap.md`, `docs/specs/` 미추적 변경이 함께 보이나 이번 검증 세션에서 발생시킨 변경이
  아님(다른 에이전트의 동시 작업 산출물로 추정) — 참고로만 기재.

---

## 2026-08-19 — R2: 콜드 임포트 지연로딩 독립 재검증 (커밋 `eee9b9c`)

구현 로그(`implementation-log.md` "R2" 항목)의 주장을 그대로 신뢰하지 않고, 별도 스크래치
스크립트(`.../scratchpad/verify_r2_cold_import.py`, `verify_r2_functional.py`,
`verify_r2_boot.py` — 구현자 스크립트 재사용 안 함, 프로젝트에 추가 안 함)로 독립 재현.
리스크 등급은 "중~상"(BUG-001 계열 DLL 순서 재발 우려)으로 사전 평가되어 있었음.

### 확인 항목 및 결과

1. **커밋 범위 확인** — `git show --stat eee9b9c`: `app/core/augmentations.py`,
   `app/core/auto_labeler.py`, `app/core/dataset.py`, `app/core/inference_engine.py`,
   `app/model_presets/{deeplab_mobilenet,deeplab_resnet,lraspp_mobilenet}.py`, `main.py`,
   `docs/agents/implementation-log.md` 총 9개 파일 — 구현자 주장(9개 파일, 이 중 8개가
   코드)과 일치. 의도치 않은 다른 파일 변경 없음. 각 파일 diff를 `git show`로 직접 읽어
   지역 import 삽입 위치가 실제 사용 지점(함수/메서드 본문, 사용 직전)과 일치함을 확인 —
   `main.py`는 `_preload_libs()`에서 `torchvision`/`torchvision.transforms.functional`
   두 줄만 제거, `torch`는 그대로 유지됨을 확인.
2. **핵심 재현(콜드 임포트)** — `verify_r2_cold_import.py`: `sys.path`에 프로젝트 루트만
   추가한 새 프로세스에서 `import app.main_window` 직후 `sys.modules` 검사.
   결과: `torch_in_sys_modules=True`, `torchvision_in_sys_modules=False`,
   `albumentations_in_sys_modules=False` — 구현자 주장과 일치. import 시간 `1.736s`
   (구현자 주장 1.852s와 대략 일치, 대화형 세션마다 수백ms 편차는 정상 범위).
3. **9개 파일 직접 열람 + 전수 grep** — `grep -rn "torchvision|albumentations" app/ main.py`
   결과, 남은 매치는 전부 (a) 함수/메서드 본문 내부 지역 import, (b) 문자열(에러 메시지·
   docstring·`pip install` 안내문), (c) `model_validator.py`의 `ALLOWED_MODULES` 문자열
   집합(실제 import 아님) 뿐. 타입 힌트·모듈 상수·클래스 속성 기본값 등에 남은 top-level
   참조 없음. `augmentations.py`는 `from __future__ import annotations` +
   `TYPE_CHECKING` 블록으로 반환 타입힌트(`A.Compose`)를 처리해 런타임 import 불필요 —
   정상 패턴.
4. **기능 회귀 확인(구현자와 다른 입력값 사용)**:
   - `SegmentationDataset(image_size=(128,128), mode="center_crop")` (구현자는
     `mode="resize"`, index 0 사용) — nok 5쌍 확인 후 **마지막 인덱스**로 `ds[len(ds)-1]`
     호출 → `torch.Size([3,128,128])` / `torch.Size([128,128])` 정상 반환, 호출 후
     `torchvision`이 그제서야 `sys.modules`에 로드됨을 확인.
   - `augmentations.build_pipeline()` — 구현자와 다른 조합(`VerticalFlip`,
     `RandomRotate90`, `RandomBrightnessContrast`) + 96×96 더미 이미지/마스크 → 정상 적용,
     `albumentations` 지연 로드 확인.
   - `inference_engine._preprocess_patch()` — 64×64 더미 패치(구현자는 32×32) →
     `(1,3,64,64)` 정상 텐서 반환.
   - `model_loader.load_from_code()` + `load_preset_code("lraspp_mobilenet")` —
     소스 텍스트의 `num_classes` 기본값을 5로 치환해(구현자는 기본값 2 그대로 사용)
     exec 후 인스턴스화 성공 확인(`num_params=3,218,818`).
   → 4개 지점 모두 다른 입력값으로 독립 재현 성공, 회귀 없음.
5. **기동 시간 재측정** — 위 2번 스크립트에서 재측정한 `1.736s`가 별도 스크립트
   (`verify_r2_boot.py`)에서도 `1.740s`로 일관되게 재현됨. 구현자 주장(1.852s)과 큰 차이
   없음(환경 변동 범위 내).
6. **앱 기동 확인** — `verify_r2_boot.py`로 `QApplication` 생성 → `app.main_window` import
   → `projects/nok` 오픈(`project.set_current()`) → `MainWindow()` 생성 → `window.show()`
   까지 예외 없이 전부 성공(STEP1~STEP6 전부 OK). **R1 검증 때보다 한 단계 더 나아가
   `MainWindow()` 생성과 `show()`까지 도달**했고, 그 시점까지도 `torchvision`/
   `albumentations`는 여전히 `sys.modules`에 없음을 재확인(지연 로드가 라벨링 탭 등 UI
   구성 단계에서 불필요하게 트리거되지 않음을 의미). `app.exec()` 이벤트 루프는 R1 검증과
   동일한 비대화형 자동화 셸 제약으로 미실행(GUI 자동화 불가 환경) — 최종 대화형 눈확인은
   사용자 환경에서 권장.
7. **DLL 순서 리스크 — 구조적 검증**: `torch`가 `torchvision`보다 먼저 로드됨이 우연이
   아니라 구조적으로 보장되는지 확인. `main.py`의 `_preload_libs()`가 `app.main_window`
   import(66행) 전(62행)에 `torch`를 먼저 로드하는 것과는 별개로, 지연 import가 들어간
   4개 실질 파일(`dataset.py`, `auto_labeler.py`, `inference_engine.py`,
   `model_presets/*.py`) **전부가 자기 자신의 모듈 top-level에 `import torch`(and/or
   `import torch.nn as nn`)를 여전히 갖고 있음**을 확인 — 즉 `main.py`를 거치지 않고 이
   모듈들을 단독으로 import하더라도(예: 테스트 스크립트, 다른 진입점) Python의 모듈 로드
   순서상 해당 파일의 top-level `import torch`가 함수 본문의 지역 `import torchvision...`
   보다 항상 먼저 실행된다 — 이중으로 안전. `torch`를 거치지 않고 바로 `torchvision`만
   import하는 코드 경로는 grep 전수 검사 결과 없음. `augmentations.py`(albumentations)는
   torch 확장이 아니므로 이 순서 제약 대상이 아님 — 별도 문제 없음.
8. **model_presets exec() 구조 주장 검증** — `app/model_presets/__init__.py:91-93`
   `load_preset_code()`가 `path.read_text()`로 프리셋 파일을 **원시 텍스트로만** 읽고,
   `app/core/model_loader.py:77` `load_from_code()`가 그 텍스트를 `exec(code,
   safe_globals)`로 실행함을 확인 — Python의 일반 `import` 메커니즘을 전혀 거치지 않는다.
   `grep -rn "from app.model_presets\.|import app.model_presets\."` 전수 검사 결과
   프로젝트 어디에서도 `deeplab_resnet.py` 등 프리셋 서브모듈을 직접 `import`하는 코드가
   없음을 확인 — 즉 프리셋 파일의 top-level import는 애초에 `app.main_window` import
   체인에서 실행된 적이 없었고(exec 시점에만 실행), 이번 라운드의 프리셋 3개 수정은
   R2의 "콜드 임포트 단축" 목표에는 불필요했지만(원래도 영향 없었음) 방어적 일관성
   차원에서는 무해함 — 구현자 주장("exec 구조라 영향 없다")은 정확함. 추가로
   `model_validator.py`의 `_check_imports()`가 `ast.walk(tree)`로 전체 트리를 순회함을
   확인해, 함수 본문 내부로 옮긴 지역 import도 top-level import와 동일하게 검증되어
   `ALLOWED_MODULES`(`torchvision`, `torchvision.models` 포함) 화이트리스트 통과에
   지장 없음을 확인.

### 판정
- 구현자 주장과 결과 전부 일치 — 재현 실패, 빠뜨린 top-level import, DLL 순서 리스크,
  앱 기동 실패 어느 것도 발견되지 않음. **R2 검증 통과**.
- 리더에게: **R2 검증 통과, R3 착수 가능.**
- 이 검증 세션에서 프로젝트 코드는 수정하지 않음(`git status` 로 확인 — 아래 비고 참고).

### 비고
- 검증 시작 시점에 이미 `docs/agents/leader-log.md`, `planning-log.md`,
  `decisions-needed.md`, `roadmap.md`, `docs/agents/verification-log.md`(R1 항목),
  `docs/specs/` 등이 미커밋 상태로 존재(다른 에이전트의 동시 작업 산출물) — 이번 R2
  검증 세션에서 발생시킨 변경이 아니며 그대로 유지함. 이번 세션이 만든 변경은 이 파일에
  R2 항목을 append한 것 하나뿐.

---

## 2026-08-19 — R3: annotation_canvas 이미지 LRU 캐시(#4) + bbox fallback 스캔 범위
축소(#7) 독립 재검증 (커밋 `194430b`)

구현 로그(`implementation-log.md` "R3" 항목)의 주장을 그대로 신뢰하지 않고, 별도 스크래치
스크립트(`.../scratchpad/verify_cache_lru.py`, `verify_mtime_invalidation.py`,
`verify_bbox_fallback.py`, `verify_regression_save_load.py`, `verify_translate_zombie.py`,
`verify_startup.py` — 구현자 스크립트 재사용 안 함, 프로젝트에 추가 안 함)로 독립 재현.

### 확인 항목 및 결과

1. **커밋 범위 확인** — `git show --stat 194430b`: `app/widgets/annotation_canvas.py`
   (+107/-15), `docs/agents/implementation-log.md`(+108) 2개 파일만 변경. 구현자 주장과
   일치. 의도치 않은 다른 파일 변경 없음.
2. **코드 판단** — `app/widgets/annotation_canvas.py`를 직접 읽고 `_ImageCacheEntry`(126-141행),
   `_store_current_into_cache`/`load_image`(250-335행), `_resolve_overlap_and_merge`의
   `had_bbox_pixels`/`_has_pixels`(1038-1082행)를 확인. 캐시 히트 조건(`cached.mtime == mtime`),
   LRU 크기 제한(`_IMAGE_CACHE_SIZE=2`, `popitem(last=False)`), `stat()` 실패 시 캐시 미사용
   폴백, bbox fallback의 "zero-out 이전 겹침 여부"에 따른 조건부 전체 스캔 로직 모두 구현
   로그 설명과 코드가 정확히 일치함을 확인. `git show 194430b`의 diff에서 구버전 fallback이
   `return bool(a.mask.any())`(무조건 전체 스캔)였음을 대조해 변경 전/후 의미 차이도 직접 확인.
3. **이미지 캐시 재현** (`verify_cache_lru.py`, `projects/nok` 실제 이미지 5장, 읽기 전용) —
   A→B→A(hit)→C→B(evict 후 재로드) 순서로 `AnnotationCanvas.load_image()` 직접 호출:
   A cold 101.26ms → A hit 6.64ms(15.2배), C 로드 후 캐시 `{A, C}`만 유지(B evict, LRU 정상),
   evict된 B 재방문 시 107.17ms로 다시 느려짐(재디코딩 확인, cold 시간과 유사). 구현자 실측치
   (79.97ms/7.49ms, 10.7배)와 다른 이미지 순서·측정으로도 같은 방향(10배 이상 가속, LRU 정상
   evict)의 결과 재현.
4. **mtime 무효화 재현** (`verify_mtime_invalidation.py`, `projects/nok/images/9번.bmp`
   대상) — (a) mtime 불변 시 재방문 → `canvas._pixmap is` 동일 객체(캐시 히트) 확인,
   (b) `os.utime()`으로 mtime +120초 이동 → 재방문 시 `canvas._pixmap is not` (새 객체, 캐시
   미스) 확인, (c) `finally` 블록에서 원래 `(atime, mtime)`으로 정확히 복구,
   `abs(st.st_mtime - 원본) < 1e-6` assert 통과. `git status --porcelain -- projects/nok`
   결과 공백(변경 없음) 재확인.
5. **bbox fallback 결과 일치 + 성능** (`verify_bbox_fallback.py`, 2000×1500 합성 배열,
   구현자와 다른 크기·좌표로 독립 구성) — 스크립트 안에 구버전 로직(무조건
   `return bool(a.mask.any())`)을 별도로 재구현해 참조로 사용, 실제
   `_resolve_overlap_and_merge()` 결과와 비교: far(안 겹침)/partial(bbox 안팎 걸침, 잔여
   생존)/consumed(bbox 안에서 완전 소멸) 3케이스에서 `consumed` 생존 여부가 참조 구현과
   완전 일치(둘 다 제거). 추가로 안 겹치는 어노테이션 20개 시나리오에서 참조 42.28ms vs
   실제 0.16ms(263배, 구현자 수치 5.1배보다 훨씬 크게 나온 것은 합성 크기·개수 차이 때문 —
   방향성은 동일하게 확인).
6. **회귀 확인 — 브러시/폴리곤 저장·로드 왕복** (`verify_regression_save_load.py`) — 스크래치
   임시 프로젝트(`project.set_current()`로 격리, nok과 무관)에서 실제
   `AnnotationCanvas._paint_stroke`/`_finish_brush`/`_close_polygon`을 직접 호출해 브러시 2개
   (다른 클래스·비중첩, 899px/705px) + 폴리곤 1개 생성 → `store.save()`/`store.load()`
   (R1이 고친 `rle_encode` 경유) 왕복 — 재로드 결과 `np.array_equal` 완전 일치, 폴리곤 4점
   보존. R1/R3 상호작용 문제 없음.
7. **`_translate_selected()` 잔여 우려 — 직접 재현 및 심각도 판단** (`verify_translate_zombie.py`):
   - **(a) 재현 가능 여부**: 재현됨. `_translate_selected(-500, -500)` 한 번 호출만으로
     원래 non-empty였던 brush_mask가 `mask.any() == False`(전량 0)가 되고, 이후 정리 호출이
     전혀 없어 `self._annotations`에 그대로 남음을 확인. `mousePressEvent`/`mouseMoveEvent`의
     `_move_active` 분기(715-727행)에서 Select 도구로 어노테이션을 드래그할 때마다 호출되므로,
     사용자가 화면을 확대해 캔버스 여백 밖까지 빠르게 드래그하면 실사용에서도 발생 가능한
     경로임을 코드로 확인(클램핑 없음, `warpAffine`의 `borderValue=0`으로 이미지 밖으로 밀려난
     픽셀은 그대로 소실).
   - **(b) 실제 심각도**: `_resolve_overlap_and_merge`에 동일 시나리오(zombie + 안 겹치는
     새 stroke)를 재현해 신버전은 zombie를 제거하지 못하고 남기는 반면, 스크립트 내
     참조(구버전) 로직은 무조건 전체 스캔으로 우연히 제거함을 직접 비교로 확인 — 구현자
     주장과 정확히 일치. 다만 `app/core/annotation_store.py:123`
     `save()`가 `a.type == "brush_mask" and a.mask is not None and a.mask.any()`로 브러시
     저장 전 non-empty 여부를 다시 필터링하는 것을 코드로 확인했고, 이는 R1이 만지지 않은
     기존 방어 코드다 — 즉 zombie가 실제로 디스크에 저장되는 일은 없다(데이터 유실/오염
     없음). `labeling_tab.py:427 _refresh_ann_list()`가 `canvas._annotations`를 그대로
     순회해 목록 패널에 항목을 그리므로, zombie는 캔버스에는 아무것도 그려지지 않지만
     (mask 전량 0) 어노테이션 목록 패널에는 빈 "[Mask]" 항목으로 보일 수 있음 — 순수 UI
     잔상이며, 다음 `load_image()`가 `self._annotations = store.load(path)`로 통째로
     교체하므로 이미지 전환 즉시 사라진다. `_consolidate_class_region`의 OR 병합에도 전량
     0인 마스크는 부작용이 없음(no-op).
   - **(c) 판정**: **R3가 새로 만든 버그가 아니라, 기존부터 있던 `_translate_selected()`의
     cleanup 누락 갭을 R3가 "우연히 가려주던" 구버전의 전체 스캔 부작용이 사라지면서 드러낸
     것**이다(구현자 자체 평가와 동일 결론). 영향 범위가 (i) 디스크에 저장되지 않고(save()의
     기존 필터), (ii) 렌더링에 영향 없고(빈 마스크는 그릴 게 없음), (iii) 세션 내 이미지
     전환 시 자동 소멸하는 순수 일시적 UI 잔상(목록 패널의 유령 항목)으로 한정됨을 코드와
     재현으로 확인 — **P0/P1 수준 아님**. **P3로 QA.md `BUG-003`에 등록**(Open, 근본 원인은
     `_translate_selected()`, 이번 R3 라운드 범위 밖이라 별도 수정 없이 이슈만 등록).
8. **앱 기동 확인** (`verify_startup.py`) — `QApplication` → `project.open_existing`/
   `set_current(nok)` → `MainWindow()` → `show()` → 라벨링 탭 존재 확인까지 STEP1~4 전부 예외
   없이 통과("ALL_OK" 출력). 비대화형 자동화 셸의 프로세스 종료 코드 이상(127)은 R1/R2 검증
   때와 동일한 환경 제약(이벤트 루프 없는 offscreen 조기 종료)으로 판단, 코드 상 STEP4까지
   전부 성공한 이후 발생해 R3 변경으로 인한 회귀로 보지 않음.

### 부수 정리
- 검증 스크립트 실행 중 `AnnotationCanvas.load_image()`가 프로젝트 미설정 상태에서 fallback
  경로(`data/annotations/`)로 5개 빈 JSON을 생성한 것을 발견 — 검증 스크립트 자체가 만든
  부산물(코드 결함 아님)이라 검증 종료 후 즉시 삭제해 원상 복구함(`git status` 클린 재확인).
  `projects/nok/`은 이번 세션 내내 무수정.

### 판정
- 구현자 주장과 결과 전부 일치 — 캐시/무효화/bbox fallback/저장-로드 회귀 모두 재현 성공,
  새로운 회귀 없음. `_translate_selected()` 우려는 재현되지만 P3 수준으로 판단해 QA.md
  `BUG-003`으로 등록 완료. **R3 검증 통과**.
- 리더에게: **R3 검증 통과, R4 착수 가능.** `_translate_selected()` 건은 QA.md `BUG-003`
  (P3, Open)으로 등록 완료 — 재작업 요구 아님, 추후 별도 라운드에서 처리 여부 판단 필요.
- 이 검증 세션에서 프로젝트 코드는 수정하지 않음(`app/widgets/annotation_canvas.py` 등 코드
  파일 변경 없음). `QA.md`(BUG-003 등록)와 이 파일(append)만 변경.

### 비고
- 검증 시작 시점에 이미 `docs/agents/leader-log.md`, `planning-log.md`,
  `decisions-needed.md`, `roadmap.md`, `docs/specs/` 등이 미커밋 상태로 존재(다른
  에이전트의 동시 작업 산출물) — 이번 R3 검증 세션에서 발생시킨 변경이 아니며 그대로 유지함.

---

## 2026-08-20 — R4: 학습 데이터로더 이미지 캐시 + num_workers 자동 감지 독립 검증

기획 산출물: [docs/specs/perf-improvement-plan-2026-08-19.md](../specs/perf-improvement-plan-2026-08-19.md)
"#3 — 학습 데이터로더 캐시 + num_workers" 절. 커밋 `5ed34e9`(R4). 원 구현 에이전트가 세션
한도로 중단되어 리더가 대신 최소 검증 후 커밋한 라운드 — 리더가 못한 2건(워커 예외 전파,
config_form.py 런타임)을 포함해 전체를 독립 재검증. 리더 스크립트는 재사용하지 않고 전부
새로 작성(스크래치 디렉토리, 프로젝트에 커밋 안 함).

### 실행 환경
`C:\Users\Feel\anaconda3\python.exe`(PyTorch 설치 인터프리터), `os.cpu_count()=12`.
DLL 함정(리더가 보고한 `app.core.project` → `PyQt6.QtWidgets` 순서 문제) 회피를 위해
모든 스크립트에서 `PyQt6.QtWidgets`(QApplication 생성)를 `app.core.project`/`dataset`보다
먼저 import — 전 스크립트에서 문제 재현되지 않음(즉 순서 문제이지 근본적 DLL 파손은 아님을
재확인).

### 확인 결과
1. **변경 범위**: `git show --stat 5ed34e9` — `app/core/dataset.py`, `app/core/trainer.py`,
   `app/widgets/config_form.py`, `docs/agents/implementation-log.md` 4개만. 스펙 범위 일치.
2. **코드 리딩**: `_load_cached()`(mtime 기반 LRU, 워커별 독립 캐시), `trainer.py`의
   `persist = cfg.num_workers > 0`, `config_form.py`의
   `_RECOMMENDED_NUM_WORKERS = min(2, max(0, (os.cpu_count() or 1) - 1))` 모두 로그 설명과
   일치.
3. **캐시 재현 (독립, 리더와 다른 이미지/인덱스 사용)**: `pair_idx=3`(8번.bmp), `idx=3`과
   `idx=8`(둘 다 `%5==3`)로 재방문 테스트 — cold 893.13ms → cache-hit 0.63ms(1408배).
   `os.utime()`으로 이미지 mtime +5초 조작 후 재조회 시 68.70ms로 재로드(무효화 정상 동작,
   히트보다 확실히 느림). **mtime을 정확히 원복(`os.utime` 원래 값 재적용) 후
   `img_path.stat().st_mtime` 값 일치 확인, `git status --short projects/nok` 무변경 확인**.
   `num_workers=0` 경로도 배치 형태(`[2,3,256,256]`) 정상 확인.
4. **워커 예외 전파 — 리더 미검증 항목, 이번에 검증**: 모듈 최상위에 `BrokenDataset`(idx==3에서
   `FileNotFoundError` 발생)을 정의하고 `num_workers=2, persistent_workers=True`로 순회 —
   워커 프로세스의 예외가 메인 프로세스로 정상 전파됨(`FileNotFoundError: Caught
   FileNotFoundError in DataLoader worker process 1. Original Traceback: ...`). `trainer.py
   TrainerWorker.run()`의 try/except 구조를 그대로 복제해 테스트한 결과, 이 예외는
   `except RuntimeError`(OOM 분기)가 아니라 `except Exception as exc`에 걸려
   `self.training_error.emit(f"{type(exc).__name__}: {exc}")` 경로에 정상 도달함을 확인 —
   즉 워커 예외가 `training_error` 시그널까지 끊기지 않고 전달되는 구조가 맞다.
   `num_workers=0` 비교군도 동일 예외가 동일 분기로 전파됨을 확인.
5. **config_form.py 런타임 — 리더 미검증 항목, 이번에 검증**: DLL 함정을 피해 QApplication을
   먼저 생성한 뒤 `ConfigForm()`을 실제로 인스턴스화 — `_num_workers` QSpinBox 초기값이
   `2`(= `_RECOMMENDED_NUM_WORKERS`, `os.cpu_count()=12` 기반 계산값과 일치)로 정상 반영됨을
   확인. `get_config().num_workers`도 동일하게 2로 전달됨을 확인.
6. **`python main.py` 방식 전체 기동**: `QApplication` → `app.core.project` import →
   `open_existing`/`set_current(nok)` → `app.main_window` import → `MainWindow()` → `show()`
   까지 STEP1~5 전부 예외 없이 통과. 프로세스 종료 코드 127은 R1~R3 검증 때와 동일한
   비대화형 offscreen 환경 특성(이벤트 루프 없는 조기 종료)으로, STEP5까지 전부 성공한 뒤
   발생해 R4 변경으로 인한 회귀로 보지 않음(R3 검증 로그에 이미 동일 현상 기록됨).
7. **`num_workers=0` 기존 경로**: 위 3, 6에서 재확인 — 정상 동작.
8. **`persistent_workers` 가드**: PyTorch가 `num_workers=0` + `persistent_workers=True`
   조합에 `ValueError: persistent_workers option needs num_workers > 0`을 던지는 것을 직접
   재현 확인. `trainer.py`의 `persist = cfg.num_workers > 0`는 `num_workers=0`일 때
   `persist=False`가 되어 이 조합을 만들지 않음 — 코드로 안전함을 확인.

### 판정
- 구현 로그의 설명과 코드가 전부 일치, 리더가 명시한 미검증 2건(워커 예외 전파,
  config_form.py 런타임)도 이번에 통과. 새로운 버그 없음.
- **R4 검증 통과, R5 착수 가능.**
- 코드는 건드리지 않음 — `git status --short` 확인 결과 세션 시작 시점부터 있던
  `docs/agents/leader-log.md` 변경 외 추가 diff 없음(`projects/nok` 포함 무변경).
  QA.md 신규 등록 없음(버그 미발견).

### 비고
- 검증 스크립트 3개(`verify_r4_cache.py`, `verify_r4_worker_exc.py`,
  `verify_r4_config_form.py`, `verify_r4_boot.py`)는 스크래치 디렉토리에만 작성, 프로젝트에
  커밋하지 않음.

---

## 2026-08-20 — R5: 추론 결과 컬러화/블렌딩 다운스케일 독립 검증 (커밋 `20bb3d0`)

기획 산출물: `docs/specs/perf-improvement-plan-2026-08-19.md` #5. 구현 로그(`implementation-log.md`
"R5" 항목)의 주장을 그대로 신뢰하지 않고, 구현자와 다른 해상도/클래스 수 조합으로 별도 스크래치
스크립트(`.../scratchpad/verify_r5_independent.py`, `verify_boot_r5_independent.py` — 구현자
스크립트 재사용 안 함, 프로젝트에 추가 안 함)로 독립 재현.

### 확인 항목 및 결과

1. **커밋 범위 확인** — `git show --stat 20bb3d0`: `app/core/inference_engine.py`(+22/-3),
   `docs/agents/implementation-log.md`(+72) 2개 파일만 변경. 구현자 주장과 일치. `projects/nok`,
   다른 코드 파일 변경 없음.
2. **코드 판단** — `_colorize_and_blend()`(inference_engine.py:311-346)를 직접 읽음.
   `_MAX_OVERLAY_DIM=2048` 모듈 상수, `max(h,w) > 2048`일 때만 `class_map_work`를 새 배열로
   생성(`class_map.astype(np.uint8)` → `Image.fromarray().resize(..., NEAREST)` →
   `np.array(..., dtype=np.int64)`, 원본 `class_map`을 in-place로 건드리는 연산 없음)해 컬러화에
   사용하고, `orig`는 BILINEAR로 별도 리사이즈함을 확인 — 구현 로그 설명과 코드가 정확히 일치.
   `run()`(86~92행)/`run_sliding_window()`의 `class_stats` 계산이 `_colorize_and_blend()` 호출과
   무관하게 원본 `class_map` 변수를 그대로 참조함도 코드 흐름으로 확인(다운스케일된 값을 쓰는
   경로 없음).
3. **독립 재현 — 다른 해상도/클래스 수** (`verify_r5_independent.py`):
   - **Case A** 6000×3000(2:1), 7클래스(구현자는 5472×3648, 3클래스) — `_colorize_and_blend()`
     직접 호출 160.5ms vs 다운스케일 없는 legacy 재현 로직 813.4ms → **약 5.06배** 단축
     (구현자 실측 ~5.1배와 방향·크기 모두 일치). 반환 `overlay_pixmap` 2048×1024,
     `max(w,h) <= 2048` 충족, 종횡비 orig=2.0000 vs new=2.0000(오차 없음).
   - `class_map` 무결성: 호출 전 스냅샷과 `np.array_equal` True, `id()` 동일(원본 객체 자체를
     재할당하지 않음), dtype/shape 불변 — 원본 오염 없음 확인.
   - **Case B** 1920×1080(16:9), 5클래스, 2048 이하 — 반환 크기 1920×1080 그대로(분기 미발동),
     `class_map` 무결성 유지 — 기존 동작과 동일.
   - **Case C** 2049×100(극단적 종횡비, 가로만 threshold 살짝 초과) — 반환 2048×100, 비율
     orig=20.4900 vs new=20.4800(반올림 오차만) — 왜곡 없음.
   - **Case D** 정확히 2048×2048(경계값) — 반환 2048×2048 그대로, `>` 조건이라 경계값에서
     다운스케일 미발동함을 확인(off-by-one 없음).
4. **앱 기동 확인** (`verify_boot_r5_independent.py`) — PyQt6를 `app.core.project`보다 먼저
   import(R4 검증 로그의 DLL 함정 회피 패턴 준수) → `QApplication` → `projects/nok` 오픈
   (`open_existing`+`set_current`) → `MainWindow()` → `show()` → `inference_engine._MAX_OVERLAY_DIM`
   임포트까지 예외 없이 전부 성공(결과 파일에 `BOOT_OK MAX_OVERLAY_DIM=2048` 기록됨). 프로세스
   종료 코드 127은 R1~R4 검증 때와 동일한 비대화형 offscreen 환경 특성(이벤트 루프 없는 조기
   종료)으로, 회귀 아님.
5. **실제 체크포인트 재확인** — `find projects/nok/checkpoints -type f` 결과 파일 없음(디렉토리만
   존재) — 구현자 주장대로 이 환경에 실제 체크포인트 없음을 재확인. 따라서 `run()`을 실제
   체크포인트로 end-to-end 실행하는 검증은 이번에도 불가능했고, 구현자와 동일하게
   `_colorize_and_blend()` 직접 호출 + 코드 흐름 확인으로 대체함 — **한계로 명시**.

### 판정
- 구현자 주장과 결과 전부 일치 — 구현자와 다른 해상도(6000×3000 등)·클래스 수(7클래스)·경계값
  케이스(정확히 2048)로도 다운스케일 발동/미발동, 속도 개선(~5배), 종횡비 유지, `class_map` 원본
  무결성, `class_stats` 원본 기준 계산 모두 재현 성공. 새로운 버그 없음. **R5 검증 통과.**
- 리더에게: **R5 검증 통과, R6 착수 가능.** `perf-improvement-plan-2026-08-19.md` 기준 R5는
  스펙상 마지막에서 두 번째 라운드 — 통과했으므로 남은 건 R6뿐.
- **한계**: 이 환경(`projects/nok/checkpoints`)에 실제 체크포인트가 없어 실제 모델 forward →
  `run()`/`run_sliding_window()` → 추론 탭 UI 렌더링까지 이어지는 end-to-end 검증은 R5 구현·검증
  양쪽 모두 못 함. `_colorize_and_blend()` 단위 호출 + `run()`의 `class_stats` 계산 코드 흐름
  검토로 대체했음을 명시. 실제 체크포인트가 생기면 추론 탭에서 대형 이미지 오버레이가 축소되어
  표시되는지 육안 확인을 별도로 권장.
- 코드는 건드리지 않음 — `git status --short` 확인 결과 세션 시작 시점부터 있던
  `docs/agents/leader-log.md` 변경 외 추가 diff 없음(`projects/nok`, `app/core/inference_engine.py`
  포함 무변경). QA.md 신규 등록 없음(버그 미발견).

### 비고
- 검증 스크립트 2개(`verify_r5_independent.py`, `verify_boot_r5_independent.py`)는 스크래치
  디렉토리에만 작성, 프로젝트에 커밋하지 않음.

---

## 2026-08-20 — R6: image_browser 검색 디바운스+상태 캐시(#6) + auto_labeler 중복 read 제거(#8) 독립 검증 (커밋 `e7066b0`) — R1~R6 전체 완료

기획 산출물: `docs/specs/perf-improvement-plan-2026-08-19.md` #6/#8, **R1~R6 중 마지막 라운드**.
구현 로그(`implementation-log.md` "R6" 항목)의 주장을 그대로 신뢰하지 않고, 구현자와 다른
규모(2000장, 다른 상태 분포)로 별도 스크래치 스크립트(`.../scratchpad/r6_verify/gen_project.py`,
`test_r6.py` — 구현자 스크립트 재사용 안 함, 프로젝트에 추가 안 함)로 독립 재현.

### 확인 항목 및 결과

1. **커밋 범위 확인** — `git show --stat e7066b0`: `app/core/auto_labeler.py`(+5/-6),
   `app/widgets/image_browser.py`(+19/-6) 2개 파일만 변경(구현 로그의 `implementation-log.md`
   자체 추가는 별도 커밋 확인 대상 아님, 로그 텍스트상 이 항목이 포함됐는지는 무관 — 실제
   diff는 코드 2개 파일 범위와 정확히 일치). 의도치 않은 다른 파일 변경 없음.
2. **코드 판단** — `image_browser.py`의 `_SEARCH_DEBOUNCE_MS=200` 타이머(singleShot,
   `_on_search_changed`→`start()`만), `_status_cache` 전체 재구축(`reload()`), 단건 갱신
   (`refresh_item()`), `_make_tree_item()`/`status_done`/`status_todo` 정렬 키의 캐시 조회
   전환을 직접 읽고 로그 설명과 일치함을 확인. `auto_labeler.collect_unlabeled()`의
   `get_ok()+load()` → `get_label_status()` 통합도 코드와 일치.
3. **동치성 정밀 분석(annotation_store.py `load()`/`get_ok()`/`get_label_status()` 직접
   대조)** — 정상 사용(앱이 `save()`/`set_ok()`로 직접 쓴 JSON) 범위에서는 완전히 동치임을
   코드로 확인(둘 다 `ok` 우선, 그 다음 `annotations` 존재 여부, 예외 시 양쪽 다 미라벨
   취급). **단, 손상/외부편집 JSON에 대해서는 2건의 실제 divergence를 코드 리딩만이 아니라
   직접 실행으로 재현**:
   - `annotations` 배열에 앱이 절대 쓰지 않는 미인식 `type`(예: `"rect"`) 값만 있는 경우 —
     구버전(`load()`가 인식 못하는 타입을 조용히 skip)은 결과 리스트가 비어 "unlabeled"로
     처리(자동 라벨링 대상 포함), 신버전(`get_label_status()`는 `annotations` 배열 자체의
     truthy 여부만 봄)은 "labeled"로 처리(대상 제외) — **실제 재현됨(MATCH=False)**.
   - JSON 최상위가 dict가 아닌 경우(예: `[]`) — 구버전 `load()`는 `data.get("annotations",
     [])`가 `try/except` 밖에 있어 `AttributeError`로 **크래시**(collect_unlabeled 전체가
     죽음), 신버전은 `get_label_status()`의 try가 `.get()` 호출까지 포괄해 크래시 없이
     "unlabeled" 반환 — **실제 재현됨**, 다만 이 방향은 신버전이 더 견고함(회귀 아님).
   - 이 두 케이스 모두 `save()`/`set_ok()`가 절대 만들지 않는 스키마이므로 정상 사용 흐름
     에서는 도달 불가 — **`QA.md` `BUG-004`(P3, Open)로 등록**, 재작업 요구 아님.
   - 그 외 엣지케이스(annotations 명시적 빈 배열, annotations 키 없음, malformed JSON 문법
     오류, ok=true+annotations 동시 존재, brush_mask rle="" 잔존 데이터) 5종은 신/구버전
     완전 일치(MATCH=True) 확인.
4. **대규모 독립 재현 프로젝트** (`gen_project.py`, `.../scratchpad/r6_verify/big_project2`,
   구현자와 다른 규모·분포) — 이미지 2000장, 분포 60%/25%/15%(unlabeled/labeled/ok, 구현자는
   1000장 약 1:1:1) + 위 7개 엣지케이스 파일 별도 생성:
   - `_status_cache` 2000장 전부 `get_label_status()` 직접 호출 결과와 **완전 일치**(mismatch 0).
   - 4개 정렬 모드(`name_asc`/`name_desc`/`status_done`/`status_todo`) 전부 캐시 기반 결과가
     기대 정렬과 **정확히 일치**.
   - `refresh_item()` 실제 시나리오 재현 — `store.save()`로 실제 어노테이션 1개를 저장한 뒤
     `refresh_item(path)` 호출 시 캐시가 `unlabeled → labeled`로 정확히 갱신되고, 트리 아이템
     텍스트/아이콘도 갱신됨을 확인(콘솔 출력 시 유니코드 기호가 깨져 보이는 것은 로컬 콘솔
     코드페이지 문제일 뿐, 위젯 내부 상태 자체는 정상 갱신 확인).
   - 디바운스 — 200ms 간격보다 짧은(30ms) 연속 입력 5회 후 `_apply_display` 실제 실행 횟수
     = **1회**(타이머 `timeout`에 별도 카운터 연결해 직접 계측) — 구현자 결과와 일치. 별도로
     선택적 문자열("img_00042")로 필터를 걸어 실제 매칭 개수가 1건으로 정확히 줄어드는 것도
     확인(디바운스 후 필터 로직 자체의 정확성도 함께 확인).
   - `collect_unlabeled()` — 신버전 **120.92ms**, 구버전(동등 로직 재구현) **224.67ms** —
     **약 46% 단축**, 결과 집합(1200개, `unlabeled` 비율과 정확히 일치) 완전 일치. 구현자
     수치(127.92→88.98ms, ~30%)와 절대치는 다르지만(환경·데이터 분포·N 차이) 방향·유의미한
     감소폭은 동일하게 재현됨.
   - `reload()`가 추가/삭제 후 캐시를 실제로 재구축하는지 직접 검증 — 새 이미지 파일 생성 후
     `reload()` → 캐시에 반영됨, 파일 삭제 후 `reload()` → 캐시에서 제거됨 확인(`_on_add`/
     `_on_add_folder`/`_on_delete`가 전부 `reload()`로 끝난다는 구현 로그 주장과 일치하는
     동작 확인).
5. **캐시 무효화 사각지대 — 전체 호출부 추적** — `refresh_item`/`annotation_saved`/`toggle_ok`/
   `annotation_store.save`/`set_ok` 전수 grep: 실제 UI 저장 경로는 `annotation_canvas.py`의
   `_do_save()`(디바운스 자동 저장) → `annotation_saved.emit()` → `labeling_tab.py:
   _on_annotation_saved()` → `image_browser.refresh_item(path)` 1곳뿐이고, `toggle_ok()`도
   동일 시그널을 타 같은 경로로 캐시가 갱신됨을 확인. **참고(회귀 아님, 사전 존재 이슈)**:
   `_do_save()`는 `threading.Thread`로 `store.save()`를 비동기 실행하면서 스레드 시작
   직후(파일 쓰기 완료 전) `annotation_saved.emit()`를 호출한다(`git log -S` 확인 결과 이
   비동기 저장 자체가 커밋 `43fad19`부터 있던 기존 구조, R6가 만든 게 아님) — 이론상
   `refresh_item()`이 디스크 쓰기 완료 전에 `get_label_status()`를 읽어 stale 값을 캐싱할
   race window가 존재하나, 이는 R6 이전부터(구버전 `get_label_status()` 직접 호출 방식에서도)
   동일하게 존재하던 레이스이므로 R6가 새로 만든 문제는 아님 — QA.md에 별도 신규 등록하지
   않음(범위 밖, 필요시 향후 별도 검토 대상으로만 기록). 그 외 `saige_converter.py`의
   `set_ok()` 호출은 `app/` 어디에서도 import되지 않는 미사용/독립 도구 코드로 확인 — 현재
   image_browser 워크플로우와 무관.
6. **`python main.py` 방식 앱 기동 확인** — PyQt6를 `app.core.project`보다 먼저 import(R4
   검증 로그의 DLL 함정 회피 패턴 준수) → `QApplication` → `projects/nok` 오픈(`open_existing`+
   `set_current`) → `app.main_window` import → `MainWindow()` → `show()`까지 STEP0~8 전부
   예외 없이 통과(stdout 파일 리다이렉트로 전 단계 로그 확인). 최초 시도에서 `> file 2>&1`
   redirection이 이유 불명으로 빈 파일을 만든 해프닝이 있었으나 `print(..., flush=True)`로
   단계별 재확인해 실제로는 전 단계 정상 통과함을 재확인 — 앱 코드 자체의 문제 아님(자동화
   셸의 출력 캡처 이슈로 판단).
7. **기존 다른 기능 회귀 확인** — `_build_folder_tree`(폴더 그룹핑), 4개 정렬 모드, OK 상태
   아이콘(`_STATUS_STYLE`) 로직 자체는 R6에서 변경되지 않고 `get_label_status()` 호출 지점만
   캐시 조회로 치환됐음을 코드 리딩 + 위 4번 대규모 재현(정렬 4종 전부 일치)으로 확인 —
   회귀 없음.

### 판정
- 구현자 주장과 실측 방향·핵심 결론 모두 일치 — 디바운스 1회 실행, 캐시 정확성(0 mismatch),
  정렬 4종 무회귀, `refresh_item()` 실시간 갱신, `collect_unlabeled()` 유의미한 개선 모두
  독립 재현 성공. 다만 정밀 동치성 검증에서 구현자가 "동치"라고 주장한 부분에 **손상/외부편집
  JSON이라는 좁은 엣지케이스에 한해 실제 divergence 2건**을 직접 실행으로 발견함 — 정상 사용
  경로에서는 도달 불가능하고 심각도가 낮아(자동 라벨링 대상 집합에 극히 드문 오차 가능성,
  크래시 없음, 데이터 유실 없음) `QA.md` `BUG-004`(P3, Open)로 등록하고 **재작업 요구는
  아님**으로 판단. **R6 검증 통과.**
- **R1~R6 전체 완료.** `perf-improvement-plan-2026-08-19.md`의 6개 항목(#2, #3, #4, #6, #7,
  #8) + BUG-002 수정까지 전 라운드가 독립 검증을 통과했다. 남은 Open 항목은 QA.md
  `BUG-003`(R3, `_translate_selected` 좀비 마스크 UI 잔상)과 `BUG-004`(R6, 손상 JSON
  엣지케이스) 2건 — 둘 다 P3, 정상 사용 흐름에서는 발현되지 않거나 순수 UI 잔상 수준으로
  향후 별도 라운드 판단 대상.
- 코드는 건드리지 않음 — `git status --short` 확인 결과 `docs/agents/leader-log.md`,
  `docs/agents/verification-log.md`(이 항목), `QA.md`(BUG-004 등록) 외 추가 diff 없음.
  `git status --porcelain -- projects/nok` 공백(무변경) 확인.

### 비고
- 검증 스크립트는 `.../scratchpad/r6_verify/gen_project.py`, `test_r6.py`(+보조 1회성 확인
  커맨드 몇 개)로 스크래치 디렉토리에만 작성, 프로젝트에 커밋하지 않음.

---

## 2026-08-20 — UI 재편 라운드 1 검증 (제약값 조정 + 스타일 통일)

`docs/specs/ui-redesign-plan-2026-08-19.md` 라운드 1 구현(커밋 `6355096`) 독립 재검증.
성능개선 R1~R6과 무관한 별도 트랙.

### 확인 절차
1. `git show --stat 6355096` — 변경 범위 `app/tabs/inference_tab.py`(8줄, +6/-2),
   `app/tabs/training_tab.py`(1줄, -1)만 확인. 구현자 주장과 일치.
2. `git show 6355096` 전체 diff 직접 읽음 — 4개 지점(스플리터 hover 스타일+handleWidth(5),
   `_list_panel.setMaximumWidth(180)` 제거, 범례 `setFixedWidth(190)`→`setMinimumWidth(160)`,
   `training_tab.py`의 `side_panel.setMaximumWidth(220)` 제거) 모두 설명과 정확히 일치.
3. `TrainingTab`/`InferenceTab`을 오프스크린 `QApplication`에서 직접 인스턴스화(PyQt6를
   `app.core.project`보다 먼저 import, R4 검증 로그의 DLL 함정 회피 패턴 준수)해
   `findChildren(QWidget)`으로 구현자와 다른 방식(속성 직접 접근 대신 위젯 트리 순회)으로
   재조회:
   - `TrainingTab` — `minimumWidth()==150`인 `QWidget`(side_panel) 1개, `maximumWidth()==
     16777215`(무제한) 확인. main_splitter(`sizes=[200,435]`) 스타일시트에 `"hover"` 포함(기존
     것, 이번 라운드 변경 대상 아님) / h_splitter(`sizes=[486,150]`)는 hover 스타일 없음(스펙
     범위 밖, 정상).
   - `InferenceTab` — `_list_panel`(minW=140, maxW=16777215), 범례(minW=160, maxW=16777215)
     각각 1개씩 확인. 메인 스플리터(3-way) `handleWidth()==5`, 스타일시트에 `"#60a5fa"`와
     `"hover"` 모두 포함 확인.
4. `python main.py`와 동등한 절차(`QApplication` → `projects/nok` 오픈 → `MainWindow()` 생성
   → `show()`)로 전체 기동 확인 — STEP1~5 전부 예외 없이 통과, `QTabWidget.count()==4`(모델/
   라벨링/학습/추론 탭 전부 로드) 확인.
5. 회귀 확인 — `side_panel`은 `h_splitter`에서 `setStretchFactor(1, 0)`으로 자동 확장하지
   않도록 고정돼 있고 초기 `setSizes([10000, 180])`도 그대로라, 상한 제거는 "수동 드래그로
   더 넓힐 수 있게" 하는 것 외에 초기 레이아웃(손실 그래프 영역 크기)에는 영향이 없음을 코드로
   확인. `_list_panel`/범례도 마찬가지로 `splitter.setStretchFactor(1, 1)`(가운데 뷰어만
   자동 확장) 구조가 그대로라 초기 배치 회귀 없음.
6. `git status --porcelain` — 검증 전/후 모두 공백(코드 미변경) 확인.

### 판정
- 구현자 주장 4개 지점 전부 독립 재현 성공, DOM/속성 조회 결과 완전 일치. 앱 기동도 정상.
- 스플리터 핸들 hover 시 실제 마우스 오버로 색이 바뀌는지는 오프스크린 환경 특성상 육안(대화형
  마우스 이벤트) 확인은 불가 — 스타일시트 문자열 자체가 정확히 적용됐음은 확인했으므로 Qt
  렌더링 신뢰. 스플리터 핸들 드래그로 상한 없이 늘어나는지도 동일한 이유로 좌표 이벤트 시뮬
  대신 `maximumWidth()==16777215`(Qt의 "제한 없음" 센티널 값) 직접 확인으로 대체 — 충분한
  근거로 판단.
- **라운드 1 검증 통과.** 코드는 건드리지 않음, `git status` 무변경 확인.

### 비고
- 검증 스크립트 2종(`verify_ui_r1.py`, `verify_boot_r1_ui.py`)은 스크래치 디렉토리에만 작성,
  프로젝트에 커밋하지 않음.

---

## 2026-08-20 — UI 재편 라운드2(라벨링 탭) 검증 (커밋 `f086636`)

`docs/specs/ui-redesign-plan-2026-08-19.md` 라운드 2 대상 중 사용자가 범위를 라벨링 탭으로
좁힌 지시에 따라 구현된 항목. 구현 로그(`implementation-log.md` "UI/UX 재편 라운드 2(라벨링
탭만)" 항목)의 주장을 그대로 신뢰하지 않고, 구현자 스크립트를 재사용하지 않은 별도 스크래치
스크립트(`.../scratchpad/verify_labeling_r2.py`, `verify_boot.py` — 프로젝트에 추가 안 함)로
독립 재현. 목업(design-log.md 2026-08-20 항목, Artifact `5df2af11-...`)의 라벨링 탭 부분과 대조.

### 확인 항목 및 결과

1. **커밋 범위 확인** — `git show --stat f086636`: `app/tabs/labeling_tab.py`(+37/-8),
   `app/widgets/class_panel.py`(+0/-1) 2개 파일만 변경. 구현자 주장(2개 파일)과 정확히 일치.
   의도치 않은 다른 파일 변경 없음.
2. **코드 리딩** — `labeling_tab.py`의 `_build_ui()`(36-137행)를 직접 읽음. 좌 패널
   (`_left_splitter`)이 `QSplitter(Qt.Orientation.Vertical)`로 `ImageBrowser`/`ClassPanel`을
   `addWidget()`, `setSizes([300, 200])` + `setStretchFactor(0, 3)/(1, 2)`, 우 패널
   (`_right_splitter`)이 어노테이션 `QGroupBox`/`LogPanel`을 `setSizes([200, 300])` +
   `setStretchFactor(0, 2)/(1, 3)`로 감쌈을 확인. 양쪽 모두 자식 위젯에 `setMinimumHeight(80)`
   부여, 메인 스플리터와 동일한 `QSplitter::handle:hover { background:#60a5fa; }` 스타일 적용
   확인. `_on_toggle_fullscreen()`(320-331행)이 `self._splitter`(바깥 메인 좌우 스플리터)의
   `sizes()`만 저장/복원하고 `_left_panel`/`_right_panel`을 통째로 `setVisible()`하는 구조라
   서브스플리터와 구조적으로 독립적임을 코드로 확인. `class_panel.py`에서 `_list =
   QListWidget()` 다음 줄의 `setMaximumHeight(200)` 호출이 실제로 제거되어 있음(diff와 대조)
   확인.
3. **독립 재현 — `LabelingTab` 직접 생성** (`verify_labeling_r2.py`, PyQt6를 `app.core.project`
   보다 먼저 import해 R4 검증 로그의 DLL 함정 회피 패턴 준수, `projects/nok` 오픈):
   - `findChildren(QSplitter)` 결과 총 3개(메인+좌+우) 확인, `_left_splitter`/`_right_splitter`
     모두 그 안에 포함되고 `orientation() == Qt.Orientation.Vertical` 확인.
   - 초기 `sizes()` — 좌 `[532, 355]` 비율 1.4986(목표 3:2=1.5, 오차 0.0014), 우
     `[355, 532]` 비율 0.6673(목표 2:3=0.6667, 오차 0.0006) — 구현자 수치(`[532,355]`/
     `[355,532]`)와 정확히 동일하게 재현됨(같은 초기 창 크기라 당연한 결과지만, 별도 계산식
     — `sizes[0]/sizes[1]` 직접 나눗셈 — 으로 재검증).
   - `class_panel._list.maximumHeight()` = `16777215`(`QWIDGETSIZE_MAX`, 무제한) 확인.
4. **전체화면 토글 회귀 — 단발 + 4회 연속 재현**: `_act_fullscreen.setChecked(True)` →
   `_left_panel.isVisible()`/`_right_panel.isVisible()` 둘 다 `False`, `setChecked(False)`
   복귀 → 둘 다 `True`, 메인 스플리터 `sizes()`가 `[230, 960, 200]`으로 토글 전후 완전 동일,
   좌/우 서브스플리터 `sizes()`도 `[532, 355]`/`[355, 532]`로 토글 전후 불변 확인. **추가로
   진입→복귀를 4회 연속 반복**한 결과, 매 회차 `vis_in=(False, False)`, `vis_out=(True, True)`,
   서브스플리터 `sizes()`가 4회 내내 `[532, 355]`/`[355, 532]`로 흔들림 없이 안정적임을 확인
   — 누적 드리프트나 상태 오염 없음.
5. **목업 대비 — 클래스 8개 추가** — `projects/nok`의 기존 클래스(`background`, `object`)에
   테스트용 클래스 8개(`testcls_0~7`)를 `save_classes()`로 추가 후 `class_panel.reload()` →
   `_list.count()==10`, `maximumHeight()`는 여전히 무제한, 10행 전체가 200px 상한 없이
   렌더링 가능한 상태(`viewport().height()==305` > `sizeHintForRow(0)*count==180`, 스크롤
   불필요)임을 확인. **테스트 후 원래 클래스 2개로 정확히 복원**(`save_classes(existing)`),
   `git status --porcelain` 재확인 결과 공백(변경 없음).
6. **`python main.py` 방식 전체 기동** (`verify_boot.py`) — `QApplication` → `app.main_window
   import MainWindow` → `MainWindow()` → `show()` → `MAIN_WINDOW_OK` 출력, `w._labeling_tab`
   속성으로 실제 라벨링 탭 인스턴스에 접근해 좌/우 서브스플리터 `sizes()`(`[443, 296]`/
   `[296, 443]`, 창 크기가 달라 절대값은 다르지만 비율은 동일하게 3:2/2:3 유지)까지 재확인.
   프로세스 종료 코드 127은 R1~R6/UI라운드1 검증 로그에서 반복 관찰된 `app.exec()` 이벤트
   루프 없는 비대화형 offscreen 셸의 노이즈로 판단 — `MAIN_WINDOW_OK` 출력이 STEP 이후
   나온 것으로 실제 기동 성공을 확인.
7. **다른 라벨링 탭 기능 회귀 확인** — `_connect_signals()`, 캔버스 도구 7종(`_act_polygon`
   등 툴바 액션), `LogPanel`, `ImageBrowser` 등은 이번 diff(+37/-8, -1)가 레이아웃 컨테이너
   교체(`QVBoxLayout` → `QSplitter`)에만 국한됨을 `git show` diff로 직접 대조 확인 — 시그널
   배선·`keyPressEvent`·단축키 로직 라인은 diff에 전혀 등장하지 않음. 추가로 `LabelingTab()`을
   생성한 상태에서 툴바 액션 7개, `_log_panel`, `_image_browser` 속성이 모두 정상 존재함을
   런타임으로 재확인.

### 판정
- 구현자 주장 전부(서브스플리터 전환, 비율 재현, `maximumHeight` 제거, 전체화면 토글 무회귀,
  앱 기동)와 목업 의도(초기 비율 유지, 8개 클래스 스크롤 없이 표시) 모두 독립 재현 성공. 4회
  연속 전체화면 토글에서도 불안정 징후 없음. 새로운 버그 없음.
- **라운드2(라벨링 탭) 검증 통과.**
- 스플리터 핸들 hover 시 실제 마우스오버로 색이 바뀌는지, 핸들 드래그 체감은 라운드1 검증과
  동일한 이유(오프스크린 환경 제약)로 육안 확인 불가 — 스타일시트 문자열 적용 자체는
  `styleSheet()` 조회로 확인 완료, Qt 렌더링 신뢰.
- 코드는 건드리지 않음 — `git status --porcelain` 검증 전/후 모두 공백(무변경) 확인.

### 비고
- 검증 스크립트 2종(`verify_labeling_r2.py`, `verify_boot.py`)은 스크래치 디렉토리에만 작성,
  프로젝트에 커밋하지 않음.
- 학습 탭·추론 탭의 라운드 2 항목(큐 박스↔진행상태, 상단↔메인뷰어 서브스플리터, 추론 탭 이미지
  목록 트리 교체)은 이번 검증 범위 밖 — implementation-log.md에 명시된 대로 별도 라운드로 남아있음.

---

## 2026-08-20 — GitHub #2 라운드A(프로젝트 내보내기, export) 검증 (커밋 `911f85a`, `d42fe46`)

`docs/specs/voc-github-issues-2026-08-20.md` "요청 2 — 라운드 A" 대상. 구현자 스크립트/합성
프로젝트를 전혀 재사용하지 않고, 스크래치 디렉토리에 독립 스크립트 5종(`part1_entries.py`
~`part5_boot_and_menu.py`, 프로젝트 저장소 밖, 커밋 대상 아님)을 새로 작성해 다른 파일 구성
(구현자는 이미지 3장, 이번엔 7장 + 이름·확장자 다양화; 구현자는 500파일, 이번엔 800파일)으로
재현.

### 확인 항목 및 결과

1. **커밋 범위** — `git show --stat 911f85a`: `app/core/project_export.py`(신규),
   `app/widgets/project_export_dialog.py`(신규), `app/widgets/project_start_dialog.py`,
   `app/core/i18n.py` 4개 파일만 변경. 구현자 주장과 정확히 일치. `export_dialog.py`(기존
   라벨 포맷 내보내기)는 커밋 이력에 전혀 등장하지 않음 — 회귀 없음 확인.
2. **코드 대 스펙 대조** — `project_export.py`의 `collect_export_entries()`가 `images/`
   (`.thumbs` 제외)·`annotations/`·`classes.json`·`project.json`은 무조건, `checkpoints/`·
   `user_models/`는 옵션(기본값 `include_checkpoints=False`, `include_user_models=True`)으로
   계산 — 스펙 "라운드 A" 절과 정확히 일치. `default_export_filename()`도
   `{project_name}_{yyyymmdd}.zip` 규칙 일치.
3. **독립 합성 프로젝트로 4가지 체크박스 조합 재현** — 이미지 7장(png/jpg/bmp/tiff 혼합),
   `.thumbs` 2장, annotations 4개, checkpoints 3개, user_models 2개로 새 프로젝트 구성 후
   `collect_export_entries()`를 4개 조합(둘다 해제/둘다 체크/ckpt만/models만) 전부 호출 —
   `.thumbs`는 4개 조합 전부에서 완전 제외, checkpoints·user_models는 옵션대로 정확히
   포함/제외됨을 어서션으로 확인. 모든 arcname이 상대경로(드라이브 문자·선행 슬래시 없음)임을
   확인.
4. **실제 QThread 워커 구동 + zip 실측** — `_ProjectExportWorker`를 실제 `QApplication` +
   이벤트루프로 구동해 zip 2개(both_true/both_false) 생성 → `zipfile.ZipFile`로 열어
   `namelist()`/`testzip()` 확인 — `.thumbs` 미포함, 체크박스 옵션대로 checkpoints/user_models
   포함·제외, 손상 멤버 없음(`testzip()==None`).
5. **zip 구조 복원성 확인(라운드 B 전제 조건)** — both_true zip을 `extractall()`로 압축
   해제 → `images/`, `annotations/`, `classes.json`, `project.json`, `checkpoints/`,
   `user_models/`가 프로젝트 폴더 구조 그대로(추가 중첩 디렉토리나 절대경로 잔재 없이) 복원됨을
   실제 파일 존재 확인으로 검증. **zip 내부 경로는 전부 상대경로이며 라운드 B가 그대로 압축
   해제해 프로젝트 폴더로 쓸 수 있는 구조임을 확인**.
6. **대용량 논블로킹(구현자와 다른 규모: 800파일)** — 이미지 600+annotation 200+메타 2 =
   802개 대상. `progress` 시그널 정확히 802회 emit, 마지막 이벤트 `(802,802)` 확인. 동시에
   1ms 간격 `QTimer`가 export 진행 중(0.177초) 176회 틱 — 이벤트 루프가 블로킹되지 않음을
   실측. zip 파일 내 항목 수도 802개로 일치.
7. **에러 케이스 — 사전 프로젝트 폴더 없음**: `finished(False, "프로젝트 폴더를 찾을 수
   없습니다.")`, zip 미생성 확인 (PASS).
8. **에러 케이스 — 쓰기 권한 없는 저장 경로**: `icacls`로 대상 디렉토리에 현재 사용자 쓰기
   거부(ACL) 설정 후 export 시도 → `PermissionError`가 `finished(False, msg)`로 정상 전파,
   부분 zip 파일 생성 안 됨 확인 (PASS).
9. **에러 케이스 — export 도중 개별 파일 소실**: 30개 대상 중 10번째 진행 시점에 아직 처리
   안 된 파일 하나를 export 도중 실제로 삭제 → 코드의 `except OSError` 스킵 로직이 정확히
   동작, 나머지 29개는 정상 압축, zip 손상 없음(`testzip` 불필요할 정도로 정상 열림),
   `finished(True, "31개 파일을 내보냈습니다.")`로 **실제 성공한 개수**를 정확히 보고함(요청
   총량이 아님) — 설계상 의도된 graceful degradation으로 판단, 버그 아님.
10. **에러 케이스 — 프로젝트 폴더 전체가 export 도중 사라짐**: `shutil.rmtree()`와
    `os.rename()` 양쪽으로 재현 시도했으나 Windows 파일시스템 특성상(디렉토리 내 파일 핸들
    잔류/AV 스캔 추정) `WinError 32`/`WinError 5`로 삭제·이동 자체가 실패해 시나리오를 안정적으로
    재현하지 못함 — 이는 OS 제약이지 코드 결함이 아님. 개별 파일 소실(9번 항목)로 동일한
    방어 로직(스킵 후 계속) 경로는 이미 확인했으므로 실질적으로 커버됨으로 판단.
11. **`project_start_dialog.py` 우클릭 진입점** — `ProjectStartDialog` 직접 생성 후
    `_recent_list.customContextMenuRequested`에 리시버 1개 연결됨, `contextMenuPolicy ==
    CustomContextMenu` 확인. `_on_export_project()`에 존재하지 않는 경로를 넘겼을 때
    `QMessageBox.warning` 호출(모킹으로 확인) 후 크래시 없이 정상 반환 — 프로젝트를 열지
    않고도 내보낼 수 있는 구조(직접 `Project(path)` 구성, `open_existing()` 미사용) 확인.
    `ProjectExportDialog` 기본 체크박스 상태(`checkpoints=False`, `user_models=True`)도 실측
    일치.
12. **`python main.py` 기동** — PyQt6 → `app.core.project` → `app.main_window.MainWindow` →
    `ProjectStartDialog`/`ProjectExportDialog` import 순서로 개별 확인 후, 실제
    `python main.py`도 8초간 구동 — 예외 없이 로그(`CUDA 사용 가능 — GPU 1개` 등)만 출력,
    크래시 없음. (콘솔 cp949 코덱으로 인한 로깅 UnicodeEncodeError는 em-dash 포함 로그 문자열과
    관련된 기존 환경 이슈로 이번 변경과 무관 — `PYTHONIOENCODING=utf-8` 설정 시 재현 안 됨.)
13. **기존 기능 회귀 없음** — `export_dialog.py`(라벨 포맷 변환 내보내기)는 이번 diff에 전혀
    포함되지 않음, i18n 키(`project_export.*`)는 ko/en 완비, 기존 `export.no_data` 키도 이미
    존재해 참조 오류 없음.

### 판정
- 구현자 주장 전부(4개 필수 항목/2개 옵션 항목 정확한 포함·제외, `.thumbs` 제외, 상대경로
  zip 구조, 대용량 논블로킹, 에러 케이스 처리, 컨텍스트 메뉴 진입점) 독립 재현으로 확인.
  **새로운 버그 발견 없음.**
- **zip 내부 경로 구조 — 라운드 B 관점에서 중요**: 전부 상대경로이며 `zip 루트 = 프로젝트
  루트` 그대로(예: `images/foo.png`, `checkpoints/epoch_0001.pt`)라서, 라운드 B가 단순
  `extractall(dest)` 후 `dest`를 새 프로젝트 폴더로 등록하는 방식으로 그대로 이어받아도 안전.
  **문제 없음.**
- **라운드A(프로젝트 내보내기) 검증 통과, 라운드B(가져오기) 착수 가능.**
- 코드는 건드리지 않음 — 검증 전/후 `git status --porcelain` 공백(무변경) 확인.

### 비고
- 검증 스크립트 5종은 스크래치 디렉토리(`.../scratchpad/verify_export/`)에만 작성, 프로젝트에
  커밋하지 않음.
- 10번 항목(폴더 전체 소실)은 Windows 파일시스템 제약으로 완전한 재현에는 실패했으나, 원인이
  코드가 아니라 OS 잠금 특성임을 확인했고 대체 시나리오(개별 파일 소실)로 방어 로직 자체는
  검증됨 — 만약 완전한 재현이 필요하다면 Linux 환경에서 별도 재시도 권장(우선순위 낮음).

---

## 2026-08-20 — GitHub #2 라운드B(프로젝트 가져오기, import) 검증

`docs/specs/voc-github-issues-2026-08-20.md` "요청 2 · 라운드 B" 검증. 구현 커밋
`4129f10`, `03f5e38`. **주요 기능 추가 라운드** — 정적 검토 + 실행 확인을 넘어 실제
QApplication(offscreen)에서 `ProjectImportDialog`를 생성해 버튼 클릭 → 워커 시작 →
진행률/완료 시그널 수신 → 결과 메시지 반영까지 실제 객체로 재현. 구현자 스크립트/합성
프로젝트 재사용 없이 전부 독립적으로 새로 작성(스크래치 `.../scratchpad/verify_importB/`).
환경: `C:\Users\Feel\anaconda3\python.exe`(PyTorch 설치 인터프리터), `QT_QPA_PLATFORM=offscreen`.

### 확인 결과 — 전부 통과

1. **`git show --stat 4129f10`** — `app/core/project_export.py`(+222), `app/core/project.py`
   (+12, `add_recent()`), `app/widgets/project_import_dialog.py`(신규 186줄),
   `app/widgets/project_start_dialog.py`(+21, "가져오기…" 버튼), `app/core/i18n.py`(+32,
   `project_import.*` 키). 구현 로그 기술과 일치.
2. **zip slip 방어 — 구현자와 다른 8가지 공격 벡터로 재시도**: POSIX 절대경로, 윈도우 드라이브
   문자(`C:\...`, `D:/...`), 백슬래시 상위이동(`..\..\evil.txt`), `images/` 위장 후 다중
   `../../../../` 탈출, 윈도우 예약파일명(`CON`)을 포함한 상위탈출, 서브폴더 경유 탈출, UNC
   경로(`\server\share\...`) — **전부 `_resolve_member_target()`이 `None`으로 차단**.
   실제 zip으로 `import_project_zip()` 풀 실행 시 4개 공격 항목 모두 `skipped`로 집계되고
   dest_root 안팎 어디에도 `PWNED` 파일이 생성되지 않음 확인. 참고(버그 아님): `images/evil.txt
   :hidden_stream`(콜론 포함, NTFS ADS 스타일) 경로는 차단되지 않고 `images/evil.txt`의
   대체 데이터 스트림으로 조용히 기록됨 — 디렉터리 탈출은 아니고(파일은 여전히
   `images/` 안에 있음) 파일시스템 고유 동작이라 이번 스펙(zip slip = 목적지 밖 탈출)
   범위 밖으로 판단, 버그 미등록.
3. **왕복 재현(구현자와 다른 합성 프로젝트)** — flat 2장 + 서브폴더 1장 이미지(각기 다른 랜덤
   바이트), 유니코드(한글) 라벨 포함 annotations 2개, classes.json, checkpoint(.pt),
   user_models(.py), `.thumbs` 캐시 포함 구성 → `collect_export_entries()`로 실제 zip 생성 →
   `import_project_zip()`으로 가져오기. sha256 비교 결과 `project.json`(가져오기 시
   `imported=True`/`imported_from` 메타 추가는 의도된 동작)을 제외한 9개 실제 데이터 파일
   전부 해시 일치, annotations/classes.json 내용(dict 비교)도 완전 일치, `.thumbs`는
   이관되지 않음(재생성 대상) 확인. **PASS**.
4. **이름 충돌 재현** — 같은 대상 루트에 기존 `CollideMe` 폴더가 있는 상태에서 같은 zip을
   2회 연속 가져오기 → `CollideMe_imported`, `CollideMe_imported_2`로 정확히 증가. 기존
   폴더 mtime·sentinel 파일 sha256·`images/keepme.jpg` 내용 전부 무변경 확인. **PASS**.
5. **취소/실패 롤백 확인** — `should_cancel` 콜백으로 5번째 파일 처리 후 취소 유도 →
   `ProjectImportCancelled` 발생, dest_root 잔여물 없음. `progress_cb`에서 3번째 호출 시
   강제 `RuntimeError` 발생 → 예외 전파, dest_root 잔여물 없음(둘 다 `shutil.rmtree` 롤백
   정상). **PASS**.
6. **골든 패스 UI(실제 재현)**:
   - 실제 라운드A `collect_export_entries()`로 zip 생성 → `ProjectImportDialog(zip_path)`
     실제 생성 → `_btn_run.click()` → `_ProjectImportWorker` 시작 → `progress`(4건) 수신 →
     `finished(True, ...)` 수신 → `QMessageBox.information` 호출 인자에 "완료 —
     'GoldenSrc_imported' 프로젝트로 저장되었습니다. (4개 파일)" 확인(리네임된 실제 폴더명이
     메시지에 정확히 반영됨). 같은 zip 2회째 가져오기 시 `GoldenSrc_imported_2`로 정확히
     증가하는 메시지 확인.
   - `proj.recent()`에 가져온 프로젝트 경로가 추가됨, `settings.json`의 `last_project`는
     `None`(불변) — `add_recent()`가 `last_project`를 건드리지 않는다는 구현자 주장과 코드
     둘 다 확인(`save_settings()`가 `dict.update()`로 병합 저장하므로 `recent_projects` 키만
     갱신되고 `last_project` 키는 아예 전달하지 않아 보존됨).
   - `ProjectStartDialog._btn_import` 클릭 시그널이 `_on_import()`에 연결돼 있고,
     `QFileDialog.getOpenFileName`을 몽키패치해 실제 `_on_import()`를 호출 →
     `ProjectImportDialog`가 실제로 생성되고 실행되어 3번째 가져오기(`GoldenSrc_imported_3`)
     까지 정상 완료됨을 확인.
   - (모달 `QMessageBox.exec()`는 offscreen에서 사용자가 닫을 수 없어 무한 대기하므로
     `QMessageBox.information/critical`만 호출 인자 기록 후 즉시 반환하도록 패치 — 다이얼로그
     자체 로직·시그널 흐름·워커 실행은 전부 실제 객체로 수행, exec() 블로킹만 우회.)
   - 격리를 위해 `set_projects_root()`로 임시 경로를 명시 지정해 실행 — 실수로 실제 저장소
     `projects/`에 `GoldenSrc` 폴더가 생성됐던 것을 발견 즉시 삭제해 정리(검증 스크립트
     초안 문제, 앱 코드 문제 아님 — 최종 스크립트는 완전 격리).
7. `add_recent()` 코드 확인 — `save_settings({"recent_projects": recents[:10]})`만 호출,
   `last_project` 키 미포함. `_touch_recent()`(기존 열기 경로)만 `last_project`를 포함한다.
   **주장과 일치, 문제 없음.**
8. `python main.py` 기동 확인 — PyQt6 → `app.core.project` 순서로 단독 import 성공,
   `python main.py` 40초 실행 중 크래시 없음. 콘솔에 반복되는 cp949 로깅 인코딩 경고는
   기존에 이미 알려진 환경 이슈(콘솔 코드페이지, `PYTHONIOENCODING=utf-8`이면 미발생)로
   이번 변경과 무관 — 과거 라운드 로그에서도 동일하게 확인된 사항.
9. 라운드 A(export) 회귀 없음 — `ProjectExportDialog`/`project_export.py`의
   `collect_export_entries()` 계열 함수 변경 없이 라운드 B 함수가 이어서 추가됐고, import
   흐름 안에서 실제로 만든 export zip을 그대로 사용해 왕복 성공했으므로 export 경로 자체가
   여전히 정상 동작함을 간접 확인.

### 결론
**라운드B 검증 통과, GitHub #2 요청2 전체 완료.** 발견된 버그 없음(QA.md 등록 대상 없음).
NTFS ADS 콜론 경로는 참고 사항으로만 남기며 별도 조치 불필요 판단.

### 비고
- 검증 스크립트 6종(`test_zipslip.py`, `test_ads.py`, `test_roundtrip.py`, `test_collision.py`,
  `test_rollback.py`, `test_corrupt.py`, `test_golden_ui.py`)은 전부 스크래치 디렉토리
  (`.../scratchpad/verify_importB/`)에만 작성, 저장소에 커밋하지 않음.
- 검증 전후 `git status` 확인 — 이번 세션 시작 시 이미 존재하던 변경(dataset.py 등)은
  검증 도중 다른 경로로 이미 커밋되어 현재 `working tree clean` — 이번 검증 작업으로 인한
  코드 변경 없음.

---

## 2026-08-20 — 기능 아이콘 SVG화 확장판 검증 (커밋 `2ad0165` feat + `2f05313` docs)

### 배경
`docs/agents/implementation-log.md` "2026-08-20 — 기능 아이콘 SVG화 확장판" 항목 검증. 이모지
19종(라벨링 툴바 13개, 아이콘 전용 버튼 5개, image_browser 상태기호 3종, training_progress_dialog
STATUS_ICON 5종, log_panel CRITICAL)을 `app/resources/icons/*.svg` 22개 + `app/widgets/icons.py`
로더 기반 SVG로 교체한 라운드. 구현 에이전트는 `py_compile`/headless SVG 렌더링/위젯 생성
스모크 테스트까지 수행했고, 실제 `python main.py` 대화형 구동 확인은 이번 검증에서 처음 수행.

### 방법
`C:\Users\Feel\anaconda3\python.exe main.py`를 실제 GUI 모드(오프스크린 아님)로 백그라운드 실행,
PowerShell(`System.Windows.Forms`/`System.Drawing` P/Invoke)로 스크린샷 캡처 + 마우스 클릭
시뮬레이션을 조합해 실제 창을 조작하며 육안 확인. 스크립트 3종(`screenshot.ps1`, `click.ps1`,
`crop.ps1`)은 스크래치 디렉토리에만 작성(저장소에 추가 안 함). `projects/nok` 데이터로 실제
프로젝트를 열어 조작.

### 확인 결과 (전부 통과)
1. **라벨링 탭 툴바 13개** — 폴리곤/브러시/버킷/지우개/영역지우개/선택/팬 7개 도구 아이콘 +
   Brush size 필드 + 실행취소/전체지우기/어노테이션표시(eye)/OK(check)/자동라벨링(sparkle)/
   전체화면 6개 전부 SVG로 정상 렌더링, 빈 아이콘·깨진 아이콘 없음(크롭 스크린샷으로 확인).
   브러시 도구 클릭 시 활성 배경(`#1e3a5f`)이 정상 하이라이트됨(`crop_toolbar2.png`).
   어노테이션표시(eye) 토글 클릭 시 캔버스의 폴리곤 스트로크가 실제로 사라졌다가 재클릭 시
   복원됨(`shot17.png`→`shot18.png`) — 시각 교체뿐 아니라 기능도 정상.
2. **이미지 브라우저 상태 아이콘 3종** — 라벨완료(초록 채움원, `#10b981`)/OK(파랑 체크,
   `#60a5fa`)/미라벨(회색 빈 원, `#4b5563`) 전부 색상·형태 정상 렌더링, 범례 행도 아이콘+텍스트
   조합으로 정상 표시(`crop_status.png`).
3. **main_window 새로고침/폴더열기 버튼 2개** — 상단 우측에 원형 화살표(refresh)/폴더 아이콘
   정상 렌더링(`crop_topright.png`).
4. **설정 다이얼로그 클립보드 버튼** — Settings → Logs 탭에서 clipboard.svg 아이콘 버튼 3개
   확인, 그 중 하나(`app.log` 경로)를 실제로 클릭해 Windows 클립보드에 정확한 경로 문자열이
   복사됨을 `[System.Windows.Forms.Clipboard]::GetText()`로 직접 확인 — 시각 요소뿐 아니라
   클릭 동작(기존 기능)도 회귀 없음.
5. **학습 탭 큐 리스트 + 진행 다이얼로그** — 구현 로그가 지적한 "부수 발견"(`training_tab.py`가
   `STATUS_ICON`→`STATUS_ICON_NAME` 리네임 대상을 같이 참조하던 지점) 검증에 집중. 실제로
   Job(`test_job`)을 큐에 추가해 `_refresh_queue_list()` 경로(대기 상태 status_ring 아이콘)가
   `ImportError` 없이 정상 렌더링됨을 확인(`crop_queue.png`), `Progress` 버튼으로
   `TrainingProgressDialog`를 열어 `update_queue()` 경로(동일 대기 아이콘)도 정상 렌더링됨을
   확인(`shot14.png`) — 리네임이 두 호출부 모두에서 일관되게 반영됨.
6. **log_panel CRITICAL 기호** — 코드 정적 확인으로 `LEVEL_ICON["CRITICAL"] = "■"`(이모지
   아님) 확인. 실제 CRITICAL 로그를 GUI 조작만으로 유발하기 어려워(운영 중 크래시급 이벤트
   필요) 육안 트리거는 생략 — 문자 1개 치환뿐이라 정적 확인으로 충분하다고 판단(구현 로그도
   동일 판단).
7. **회귀 확인** — 이미지 전환(10번→11번), 도구 전환(폴리곤→브러시), 자동 라벨링 다이얼로그
   열기(빠른 학습+자동 라벨링 탭 정상 표시 후 닫기), 학습 탭 큐 추가/전체 삭제(확인 다이얼로그
   포함), 추론 탭 진입(체크포인트 없음 상태 정상 표시) — 전부 예외/크래시 없이 정상 동작.
   콘솔에 반복 출력된 `UnicodeEncodeError`(cp949 로깅 인코딩 경고)는 과거 라운드 로그
   (`2026-08-20 GitHub #2 라운드B` 검증 항목)에서도 이미 확인된 기존 환경 이슈로, 이번
   아이콘 변경과 무관(파일 로그는 `encoding="utf-8"`로 정상 기록되고, 콘솔 스트림만 영향받음
   — 앱 크래시로 이어지지 않음).
8. **부수 확인** — `broom.svg`(log_panel 정리 버튼)가 작은 크기(20px)에서 대각선 손잡이 +
   뭉친 솔 형태로 렌더링돼 얼핏 연필처럼 보일 수 있음을 육안으로 인지했으나, 승인된 디자인
   목업(Artifact `7876ed3e`)의 의도된 형태이고 인접 폴더 아이콘과 툴팁으로 구분 가능해
   버그로 등록하지 않음(디자인 판단 영역).
9. 테스트 종료 후 `git status --porcelain` 클린 확인 — `projects/nok` 등 실데이터 무변경.

### 결론
**검증 통과.** 19개 지점 전부 정상 렌더링·정상 동작 확인, 발견된 버그 없음(QA.md 등록 대상 없음).
`docs/roadmap.md`의 "아이콘/이모지 → 미니멀 디자인" 1단계 체크 표시 및 "디자인 톤 홀리스틱
재검토" 실행 순서 1번 체크 처리는 리더 몫으로 남김.

### 비고
- 스크린샷/크롭 이미지, PowerShell 스크립트(`screenshot.ps1`/`click.ps1`/`crop.ps1`) 전부
  스크래치 디렉토리(`.../40989d09-9093-4389-bdea-4fb6757d53b9/scratchpad/`)에만 저장, 저장소에
  추가하지 않음.

---

## 2026-08-20 — 장식 이모지 제거 라운드 마무리 검증 (커밋 `b33491d` feat + `b9a18d6` docs)

### 배경
`docs/agents/implementation-log.md` "장식 이모지 제거 라운드 마무리(i18n.py + 폴더 트리 아이콘)"
항목 검증. 1차 구현 에이전트가 세션 한도로 19개 파일 미커밋 상태에서 중단, 리더가 안전성만
확인 후 2차 에이전트가 이어받아 `i18n.py` 전체(ko/en 96곳) + `image_browser.py` 폴더 헤더
아이콘화 + `training_tab.py` 누락분 3곳까지 마무리한 라운드. `menu.settings`/`menu.export`
i18n 키를 삭제하고 `main_window.py`의 두 버튼을 `svg_icon()` 기반 아이콘 버튼(`gear.svg`,
`export.svg` 신규)으로 전환하는 구조 변경이 섞여 있어 실제 클릭 동작 확인이 핵심.

### 방법
정적 검토(코드 리딩 + grep) 후 `C:\Users\Feel\anaconda3\python.exe main.py`를 실제 GUI 모드로
백그라운드 실행, PowerShell(`screenshot.ps1`/`click.ps1`, R-아이콘 검증 라운드 스크래치에서
재사용) 조합으로 실제 창을 조작하며 육안 확인. `projects/nok` 데이터로 실제 프로젝트를 열어
조작.

### 확인 결과
1. **정적 검토** — `ast.parse()`로 `app/` 전체 재귀 컴파일 오류 0건 재확인.
   `grep -rn "menu\.settings|menu\.export"` 결과 `main_window.py`의 `.tip` 서브키(존재하는
   키) 참조만 남아있고, 삭제된 `menu.settings`/`menu.export` 자체를 참조하는 죽은 코드 없음.
   `settings_dialog.py`의 국기 이모지(🇰🇷/🇺🇸) 원본 유지 확인.
2. **4대 탭 이름** — Labeling / Training / Inference / Model 전부 이모지 없이 텍스트만
   정상 표시(스크린샷 확인, 탭 전환 4회 전부 정상 렌더링, 깨진 위젯 없음).
3. **설정 아이콘 버튼(gear.svg)** — 상단 우측 코너 클릭 시 `SettingsDialog`가 실제로 열림,
   일반/Logs 탭 전환 정상, Language 콤보(`us  English`, 국기 이모지 보존 확인 — 다만 Windows
   폰트가 regional indicator 이모지를 "us" 텍스트 글리프로 폴백 렌더링하는 것을 육안 확인,
   이건 이 라운드와 무관한 OS/폰트 렌더링 특성이라 버그 아님), Logs 탭의 app.log/errors.log/
   perf.log 클립보드 아이콘 버튼 정상 표시. 클릭 동작(다이얼로그 오픈) 회귀 없음.
4. **내보내기 아이콘 버튼(export.svg)** — 클릭 시 `ExportDialog`("Export labeled data")가
   실제로 열림, 체크박스 3종·포맷 콤보·"Select export folder"/"Start export" 버튼 전부 정상
   렌더링. 클릭 동작 회귀 없음.
5. **이미지 브라우저 폴더 트리 아이콘** — `projects/nok`은 서브폴더가 없어 실제 UI 조작만으로는
   폴더 헤더가 트리거되지 않음. `projects/nok/images/sub_test/`에 이미지 1장을 넣고 앱을
   재시작해 재현 시도했으나 목록에 반영되지 않음(아래 "부수 발견" 참고) — 대신 헤드리스
   스크립트로 `ImageBrowser._all_paths`에 서브폴더 경로를 직접 주입해 `_build_folder_tree()`를
   강제 트리거한 결과, `_make_folder_item()`이 만든 폴더 헤더 아이템의 `icon(0).isNull()`이
   `False`(14×14 정상 렌더링)임을 확인 — **이번 라운드가 바꾼 아이콘 렌더링 코드 자체는
   정상 동작**. 테스트 후 `sub_test/` 삭제, `git status --porcelain` 클린 재확인.
6. **학습 탭 상태 라벨(`⏸️` 제거 3곳)** — 코드 리딩으로 505/662/668번 줄이 전부 이모지 없이
   "중지 요청됨…"/"현재 작업 중지 요청됨…"/"전체 큐 중지 요청됨…" 텍스트만 남은 것을 확인.
   실제 학습 작업을 큐에 넣고 중지시켜 라이브 트리거하지는 않음(모델 미로드 상태라 준비
   비용 대비 이득이 낮다고 판단) — 인접한 학습 탭 다른 상태 라벨("Idle")이 스크린샷에서
   정상 렌더링되는 것으로 상태 라벨 표시 파이프라인 자체는 육안 확인됨.
7. **모델 탭** — 코드 에디터, "검증 (Validate)"/"로드 (Load Model)"/"AI 모델 프리셋..."/
   "파일 열기 (.py)" 버튼 전부 이모지 없이 정상 렌더링.
8. 테스트 종료 후 `taskkill`로 프로세스 정리, `git status --porcelain` 클린 확인.

### 부수 발견 — BUG-005 (P2, QA.md 등록)
정상 사용 흐름에서 "폴더가 있는 프로젝트"를 만들 방법 자체가 없음을 발견. `image_browser.py`
`reload()`가 `images_dir()`을 비재귀적으로만 `glob()`하고(2026-05-27 커밋 `00fd6779`의 의도적
설계 — `dataset._collect_pairs()`와의 일관성 목적), `_on_add()`/`_on_add_folder()` 둘 다
선택한 파일/폴더를 `images_dir()` 바로 아래로 평탄하게 복사한다. 그 결과 앱의 어떤 기능으로도,
심지어 사용자가 파일탐색기로 `images_dir()`에 직접 하위폴더를 넣어도 브라우저 목록에 반영되지
않는다(직접 재현 확인). `_build_folder_tree()`/`_make_folder_item()`/정렬모드 "폴더" 코드
자체는 살아있고 정상 동작하지만 트리거할 방법이 없는 죽은 코드 상태. 이번 라운드가 새로 만든
회귀는 아니고(수 개월 전부터 존재하던 설계), 이번 라운드는 그 안의 아이콘만 이모지→SVG로
바꿨을 뿐이라 검증 대상인 "장식 이모지 제거" 자체는 정상 통과. 다만 `QA.md`/`docs/roadmap.md`의
GitHub #1 VOC 응답("라벨링 탭은 기존부터 폴더 트리 있음")이 실제 도달 가능한 동작과 어긋나
QA.md에 BUG-005로 등록하고 VOC 표에도 정정 각주 추가. 후속 조치(문서만 정정할지, 기능을 실제로
구현할지)는 리더/기획 판단 필요.

### 결론
**검증 통과.** 이번 라운드가 변경한 범위(i18n 이모지 제거, 아이콘 버튼 전환, 폴더 트리 아이콘,
학습 탭 상태 라벨) 전부 정상 동작, 회귀 없음. 별도로 발견한 BUG-005는 이번 라운드의 결함이
아닌 기존 결함이나, 검증 중 실제로 재현되어 QA.md에 신규 등록함.

### 비고
- 스크린샷·PowerShell 스크립트·헤드리스 테스트 스크립트(`test_folder_icon.py`) 전부 스크래치
  디렉토리(`.../40989d09-9093-4389-bdea-4fb6757d53b9/scratchpad/`)에만 저장, 저장소에 추가하지
  않음. `projects/nok` 실데이터는 테스트 후 원상복구, `git status --porcelain` 클린 확인.

---

## 2026-08-20 — `model_tab.py` 팔레트 정규화 검증 (커밋 `a8ac52d` refactor + `f0fc2ef` docs)

### 배경
`docs/roadmap.md` "디자인 톤 홀리스틱 재검토" 3단계 항목. `app/tabs/model_tab.py`의 코드
에디터·로그 패널이 쓰던 GitHub 다크 테마 계열 독자 팔레트(`#0D1117`/`#3fb950`/`#f85149`/
`#79c0ff` 등)를 `main.py` 표준 팔레트(`#111418`/`#10b981`/`#f87171`/`#fbbf24`/`#60a5fa`
등)로 교체한 라운드. 구현 에이전트는 `ast.parse()` 정적 검토만 수행, 실제 GUI 구동 미확인
상태로 검증에 넘어옴.

### 검증 방법 (직접 실행, `C:\Users\Feel\anaconda3\python.exe`, `QT_QPA_PLATFORM=offscreen`)
1. **diff 리뷰** — `git show a8ac52d` 전체 diff 확인. 변경 범위가 색상값 5종(하이라이터)
   + 배경/텍스트 2종 + 상태라벨 2종 + 로그헬퍼 4종, 총 30줄(+15/-15)로 스펙과 정확히 일치.
   폰트(`QFont("Consolas", ...)`)·레이아웃(splitter 크기, margin 등) 코드는 diff에 전혀
   포함되지 않아 회귀 위험 없음을 코드 레벨로 먼저 확인.
2. **`main.py` 표준 팔레트 대조** — `grep`으로 `main.py`의 전역 스타일시트에 `#111418`/
   `#e5e7eb`/`#10b981`/`#60a5fa`/`#9ca3af`가 이미 다수 지점(입력창 배경, accent 보더, 완료
   버튼 등)에 쓰이고 있음을 확인 — model_tab.py가 실제로 앱 표준값을 그대로 재사용했음을
   확인(신규 값 도입 아님).
3. **스크래치 스크립트로 `ModelTab` 위젯 직접 생성**(`verify_model_tab_palette.py`,
   `verify_model_tab_load.py`, 프로젝트에 추가 안 함) — `QApplication` → `ModelTab()` →
   `show()` 후:
   - **검증(Validate) 골든패스**: 유효한 `nn.Module` 코드(허용 모듈만 사용) 입력 →
     `_on_validate()` 호출 → 상태 라벨 `"✓ MyModel"` + `styleSheet()` `"color: #10b981;"`
     확인, 로그 패널 `toHtml()`에서 `[OK]` 항목이 `color:#10b981` 스팬으로 정확히 렌더링됨을
     확인.
   - **에러 경로**: 차단 모듈 import(`import os`) + `nn.Module` 서브클래스 없는 코드 →
     `[ERR]` 로그 2건 모두 `color:#f87171` 스팬, 상태 라벨 `"✗ 검증 실패"` +
     `"color: #f87171;"` 확인. `_btn_load.isEnabled()` False로 정상 차단.
   - **경고 경로**: 빈 코드 입력 → `_log_warn("코드가 비어 있습니다.")` 호출 →
     `[WARN]` 로그가 `color:#fbbf24` 스팬으로 렌더링 확인.
   - **로드(Load Model) 골든패스**: (허용 모듈만 쓰는) 깨끗한 유효 코드로 재시도 —
     `_on_validate()` → `_on_load()` 순서로 호출, 최종 상태 라벨 `"✓ MyModel (56 params)"` +
     `"color: #10b981;"`, `tab.loaded_model`이 실제 `MyModel` 인스턴스(`Conv2d(3,2,...)`)로
     정상 반환됨을 확인 — 팔레트 교체로 로드 파이프라인이 깨지지 않았음을 확인.
   - 에디터/로그 `styleSheet()` 원시 문자열도 각각
     `"background:#111418; color:#e5e7eb; border:1px solid #374151;border-radius:6px;
     padding:4px;"`로 스펙과 정확히 일치.
4. **가독성(대비) 정량 검증** — 오프스크린 렌더링 환경은 시스템 폰트 글리프가 깨져
   (`QPixmap.grab()` 결과가 빈 사각형으로만 나옴) 스크린샷 육안 비교가 신뢰 불가하다고
   판단, 대신 WCAG 상대 휘도 공식으로 신/구 팔레트의 배경 대비 명암비를 전수 계산:
   - 신규(배경 `#111418`) — 본문 텍스트 14.92, 키워드/INFO(`#60a5fa`) 7.26, 문자열/WARN
     (`#fbbf24`) 11.06, 주석(`#9ca3af`) 7.27, 숫자/OK(`#10b981`) 7.28, torch·nn
     (`#34d399`) 9.61, ERR(`#f87171`) 6.68 — **전 항목 WCAG AA(4.5:1) 여유 통과, ERR 제외
     전부 AAA(7:1)도 통과**.
   - 구버전(배경 `#0D1117`)과 항목별 비교 — ERR 5.65→6.68(개선), 주석 5.68→7.27(개선),
     INFO 9.73→7.26(소폭 하락하나 여전히 AAA 상회), 나머지는 동등 수준. **가독성 저하로
     판정할 항목 없음** — 검증 지시의 "가독성 저하 확인 시 이슈 등록" 기준에 해당하지 않음.
5. **테스트 오염 정리** — 위 로드 골든패스 실행 중 `save_user_code()`가 실제로
   `data/user_models/model_20260820_164003.py`를 생성(정상 동작). 검증 종료 후 삭제,
   `git status --porcelain` 클린 확인.

### 부수 발견 — BUG-006 (P2, `QA.md` 신규 등록, 이번 팔레트 라운드의 회귀 아님)
로드 골든패스 1차 시도에서 `import random`(허용 목록 밖 모듈, `[WARN]`만 뜨고 `ok=True`)을
포함한 코드로 `_on_validate()` → `_on_load()`를 실행했더니 **검증은 통과("✓ MyModel")했지만
로드는 항상 실패**("✗ 로드 실패", `load_from_code()`가 `ImportError`를 잡아 에러 처리)함을
발견. 원인: `model_validator.validate()`는 허용 목록 밖 import를 warning으로만 취급해
`result.ok=True`를 반환하지만, `model_loader.load_from_code()`의 `exec()` 샌드박스
(`_make_safe_import`)는 `_ALLOWED_ROOTS` 밖 모듈이면 무조건 `ImportError`를 던진다 —
"검증 통과 + 로드 버튼 활성화"인데 실제로 로드하면 늘 실패하는 정책 불일치. 팔레트 변경과
무관한 기존 로직 결함이며 이번 커밋(`a8ac52d`)이 만든 회귀가 아님을 diff로 확인. 재현 코드
제거(깨끗한 허용 모듈만 사용) 후 재시도하니 로드 골든패스는 정상 통과함을 위 3번 항목에서
별도로 재확인함.

### 판정
**통과.** 색상값 교체가 스펙(신 5매핑 + 배경/텍스트/상태라벨/로그헬퍼)과 정확히 일치하고,
실제 `ModelTab` 위젯 구동으로 검증/로드 골든패스 모두 정상 동작 확인, 폰트/레이아웃 등
비색상 요소 회귀 없음, 대비(가독성)도 신구 팔레트 동등 이상. 다음 실행 순서 항목(4번,
`loss_chart.py` matplotlib 배색)으로 진행 가능.

### 비고
스크래치 스크립트 전부 `.../40989d09-9093-4389-bdea-4fb6757d53b9/scratchpad/`에만 저장,
저장소에 추가 안 함. `git status --porcelain` 최종 클린 확인 (QA.md 수정만 반영 대상).

---

## 2026-08-20 — loss_chart.py matplotlib 배색 정규화 독립 검증 (커밋 `e76361a`+`eda6455`, Artifact `7876ed3e` 4단계)

`docs/agents/design-log.md` "4탭 디자인 톤 홀리스틱 재검토" 발견 2번 대상. 구현 로그
(`implementation-log.md` "loss_chart.py matplotlib 배색을 앱 표준으로 정규화" 항목)는
`ast.parse()` 정적 검토만 수행했고 실제 GUI 렌더링은 미확인 — 이번 검증에서 실제 렌더링까지
확인.

### 확인 항목 및 결과

1. **커밋 범위 확인** — `git show e76361a -- app/widgets/loss_chart.py`: `_DARK/_PANEL/_TRAIN/
   _VAL/_GRID/_TEXT/_EPOCH` 상수값 교체 + `_TEXT_MUTED` 신규 상수 + `_style_ax()`의 눈금/제목/
   범례/스파인 참조 갱신만 변경(+12/-11). 구현 로그의 색상 매핑표(facecolor `#111418`/`#1f2329`,
   train `#60a5fa`, val `#f87171`, 그리드/epoch/스파인 `#374151`, 텍스트 `#e5e7eb`/`#9ca3af`,
   범례 배경+테두리)와 diff가 정확히 일치. 로직(`append_batch`/`append_val`/`append`/`reset`/
   `_update_plot`) 변경 없음.
2. **`main.py` 표준 팔레트 대조** — `grep -c` 결과 `#111418`/`#1f2329`/`#374151`/`#e5e7eb`/
   `#9ca3af`/`#60a5fa`/`#f87171` 조합이 `main.py` 전역 스타일시트에서 총 44회 사용되는 앱
   표준 토큰임을 확인 — `loss_chart.py`만의 임의 색상이 아니라 실제 표준 팔레트와 일치.
3. **실제 렌더링(더미 데이터, `LossChart` 위젯 직접 생성)** — 스크래치 스크립트
   (`verify_loss_chart.py`, `C:\Users\Feel\anaconda3\python.exe`, `QT_QPA_PLATFORM=offscreen`)로
   `main.py`의 `QGroupBox` 스타일(배경 `#1f2329`, 테두리 `#374151`)을 재현한 패널 안에 실제
   `LossChart`를 배치하고, 6 epoch × 20 batch 더미 loss(EMA 스무딩 포함)로 `append_batch()`/
   `append_val()`을 실제 호출해 학습 진행을 흉내낸 뒤 `QWidget.grab()`으로 스크린샷 저장.
   - **배경**: Figure facecolor `(0.0667,0.0784,0.0941)` = `#111418`, Axes facecolor
     `(0.1216,0.1373,0.1608)` = `#1f2329` — 스펙과 정확히 일치, 주변 Qt 패널과 자연스럽게
     어울림(스크린샷 육안 확인).
   - **선 색상**: `chart._line_train.get_color() == "#60a5fa"`, `chart._line_val.get_color()
     == "#f87171"` — train(파랑)/val(빨강) 두 선이 배경 대비 뚜렷하고 서로도 명확히 구분됨
     (스크린샷 확인).
   - **텍스트/그리드**: 축 라벨("Epoch"/"Loss")·제목·눈금 모두 어두운 배경 위에서 읽기 쉬운
     밝기로 렌더링, 그리드는 은은하게 표시되어 데이터 라인을 가리지 않음.
   - **범례**: 배경 `#1f2329`(패널과 동일 톤) + 테두리 `#374151`로 그래프 안에서 도드라지지도
     안 보이지도 않는 적절한 대비 확인(확대 스크린샷으로 재확인).
4. **회귀 확인(실제 위젯 메서드 직접 호출)**:
   - `reset()` 후 `_bx/_by/_vx/_vy` 전부 빈 리스트, `_ema is None` 확인(`RESET_OK`).
   - 기존 호환 메서드 `append(epoch, train, val)`을 reset 후 2회 호출 → `_line_train`/
     `_line_val`의 xdata 길이 각 2 — epoch 단위 갱신 경로도 색상 변경과 무관하게 정상 동작
     (`APPEND_COMPAT_OK`).
   - 배치 단위 실시간 갱신(`append_batch`, `_DRAW_EVERY=5`마다 draw, EMA 스무딩)과 epoch
     경계 세로선(`axvline`) 생성 모두 예외 없이 120회 반복 호출 성공 — 스크린샷의 매끄러운
     곡선(스무딩 반영)으로 시각적으로도 확인.
   - 이 앱에는 matplotlib `NavigationToolbar`(확대/축소 등 인터랙티브 도구)가 애초에
     연결되어 있지 않음을 `loss_chart.py`/`training_tab.py` 양쪽 grep으로 확인 — "확대/축소"는
     해당 사항 없는 항목, 별도 회귀 대상 아님.
5. **`TrainingTab` 실제 생산 레이아웃 내 구동 확인** — `QT_QPA_PLATFORM=offscreen`에서
   `PyQt6.QtSvg`를 `QApplication` 생성 전에 먼저 import(R4/R5 검증 로그의 DLL 순서 함정
   회피 패턴 준수) → `QApplication` → `from app.tabs.training_tab import TrainingTab` →
   `TrainingTab()` 인스턴스화(내부적으로 실제 `LossChart()`를 그대로 포함) — 예외 없이
   `TRAINING_TAB_OK`까지 도달. 프로세스 종료 코드 127은 R1~R6 검증 로그와 동일한 비대화형
   offscreen 환경의 조기 종료 노이즈로, 위 STEP 전부 성공 이후 발생해 회귀로 보지 않음.

### 발견 사항 — QA.md `BUG-007` 등록(P3)
그리드(`_GRID`)와 epoch 경계 세로선(`_EPOCH`) 상수가 이번 라운드에서 동일한 `#374151`로
통일됨. 구버전은 `_GRID=#3a3a3a`/`_EPOCH=#555555`로 명도가 달라 epoch 경계선이 그리드보다
밝게 도드라졌지만, 통일 후에는 alpha(0.6 vs 1.0)·선굵기(0.4 vs 0.6)의 미세한 차이만 남아
실제 렌더링(확대 스크린샷)에서 epoch 경계 세로선이 x축 그리드선과 거의 구분되지 않음. 데이터
판독(손실 값, train/val 선 구분)에는 영향 없고 구현 로그의 색상 매핑표에 "그리드와 통일"로
명시된 의도된 절충이라 기능 결함은 아니나, epoch 경계 표시라는 원래 목적은 사실상 무력화됨 —
`QA.md` `BUG-007`(P3, Open)로 등록. 재작업 요구 아님, 필요 시 `_EPOCH`에 그리드보다 밝은
별도 톤 부여 검토 권장.

### 판정
**통과.** 색상값 교체가 스펙(구현 로그 매핑표)과 정확히 일치하고, 실제 `LossChart` 위젯을
더미 데이터로 렌더링해 배경/텍스트/train·val 선/범례 대비 모두 가독성 확인, `TrainingTab`
실제 프로덕션 레이아웃에서도 예외 없이 구동, 배치/epoch 단위 갱신·reset·호환 메서드 등
상호작용 회귀 없음. BUG-007(epoch 경계선-그리드 색 통일로 시각적 구분 약화)은 P3 수준으로
판단해 별도 이슈만 등록 — 이번 라운드를 블로커로 간주하지 않음. Artifact `7876ed3e` 4단계
완료 처리 가능.

### 비고
스크래치 스크립트(`verify_loss_chart.py`) 및 스크린샷은
`.../40989d09-9093-4389-bdea-4fb6757d53b9/scratchpad/`에만 저장, 저장소에 추가 안 함.
`git status --porcelain` 결과 `QA.md`(BUG-007 등록)만 변경, 코드 파일은 무수정.

---

## 2026-08-20 — 학습/추론 탭 서브스플리터+이미지트리 라운드 검증 (커밋 `a32a8b5`, `b09fb83`, `b51318f`, `2955da7`)

Artifact `7876ed3e`(4탭 디자인 톤 홀리스틱 재검토) 5단계 대상. `docs/agents/implementation-log.md`
"학습 탭 큐 영역 서브스플리터 전환"·"추론 탭 상단↔뷰어 서브스플리터 + 이미지 목록 신규 컴포넌트"
두 항목 검증. **신규 컴포넌트(`InferenceImageList`) 추가를 포함한 규모 있는 변경이라 "주요 기능
추가"로 판단** — 정적 검토를 넘어 실제 `python main.py` GUI 조작(마우스 클릭/드래그/타이핑)까지
수행. `projects/nok` 실프로젝트로 열어 조작, 폴더 트리 재현용 임시 이미지 5장(중첩 2단계)은
스크래치 디렉토리에 생성 후 테스트 종료 시 삭제.

### 방법
`C:\Users\Feel\anaconda3\python.exe main.py`를 실제 GUI 모드(오프스크린 아님)로 백그라운드
실행, PowerShell(`System.Windows.Forms`/`System.Drawing` P/Invoke) 기반 `screenshot.ps1`/
`click.ps1`(기존 아이콘 검증 라운드에서 재사용)에 더해 이번 라운드에서 신규 작성한
`drag.ps1`(마우스 다운→다단계 이동→업으로 스플리터 핸들 드래그 재현)·`type.ps1`
(`SendKeys`로 검색창/필드 타이핑)을 추가로 사용. 스플리터 핸들의 정확한 픽셀 위치는 스크린샷을
Python(PIL)으로 열어 `#374151`(핸들색) RGB를 컬럼 스캔해 특정한 뒤 드래그 좌표로 사용 —
육안 어림짐작이 아니라 픽셀 단위로 확인. 스크립트/스크린샷 전부
`.../40989d09-9093-4389-bdea-4fb6757d53b9/scratchpad/`에만 저장, 저장소에 추가 안 함.

### 확인 결과

1. **학습 탭 `_queue_splitter` 실제 드래그** — 핸들을 아래로 드래그하면 큐 리스트 영역이
   실제로 커지고(빈 큐 목록 박스가 육안으로 확장) 모니터링 패널(진행바/손실 그래프)이
   비례해 줄어듦, 반대 방향 드래그도 대칭적으로 동작 — 리사이즈 자체는 정상.
2. **학습 탭 큐에 실제 작업 추가+실행(골든패스)** — 모델 콤보에서 "LR-ASPP + MobileNetV3"
   프리셋 선택, Epochs=1·Checkpoint Interval=1로 스핀박스 직접 편집(더블클릭+Ctrl+A+타이핑),
   Job name 입력 후 "Add to Queue" 클릭 → 큐 리스트에 정상 항목 추가(`(0/1)`) 확인. "Run All"
   클릭 → `TrainingProgressDialog` 팝업 정상 표시(Step 카운터, 큐 패널 등), 실제 CUDA(RTX 5060)
   로 학습 진행 → **완료까지 도달**("모든 학습 완료", progress bar 100%, 손실 곡선이 실제로
   우하향), `projects/nok/checkpoints/`에 실제 체크포인트 파일(`*_epoch_0001.pt`) 생성 확인 —
   새 손실 그래프 팔레트(`#60a5fa` train/`#f87171` val, R4 디자인 라운드 산출물)도 실제 학습
   데이터로 정상 렌더링됨을 육안 확인(코드 리뷰만이 아니라 실측).
3. **학습 탭 `_queue_splitter` 완전 붕괴 재현 — BUG-008** — 핸들을 위/아래로 끝까지 드래그하면
   `queue_box.setMinimumHeight(120)`/`monitor_panel.setMinimumHeight(150)` 지정에도
   불구하고 해당 pane이 **0px로 완전히 사라짐**(그룹박스 제목까지 통째로 소실). 구현 로그가
   명시한 "완전 붕괴(0px) 방지" 의도와 실제 동작이 다름을 실측으로 확인 —
   `QSplitter.setChildrenCollapsible(False)`가 어디에도 호출되지 않아 Qt 기본값
   (`childrenCollapsible=True`)이 `setMinimumHeight`를 무력화함. `grep -rn
   "setChildrenCollapsible" app/` 결과 프로젝트 전체에서 0건 — 라벨링 탭 서브스플리터
   (커밋 `f086636`)도 같은 패턴 공유 가능성 높음(이번 라운드 범위 밖). **QA.md BUG-008(P2)
   로 등록**.
4. **추론 탭 `outer_splitter`(상단↔메인) 드래그** — 핸들 드래그로 체크포인트 테이블 영역이
   실제로 커지고 뷰어 영역이 줄어듦, 반대 방향도 정상. 이 스플리터도 동일한 드래그로 끝까지
   밀면 0px 붕괴 재현(BUG-008에 통합 — 같은 근본 원인).
5. **추론 탭 이미지 목록 패널 좌우 최소폭(140px) 붕괴** — 3분할 스플리터의 목록↔뷰어 핸들을
   왼쪽 끝까지 드래그하면 `_list_panel.setMinimumWidth(140)`에도 불구하고 0px로 붕괴 —
   BUG-008과 동일 근본 원인, 별도 항목으로 만들지 않고 BUG-008 설명에 통합.
6. **추론 탭 "폴더 선택…" → 실제 하위 폴더 재귀 스캔** — 스크래치 디렉토리에 2단계 중첩
   (`root/alpha_root.png`, `root/sub1/beta_one.png`, `root/sub1/sub2/gamma_two.png`,
   `root/sub3/{delta_three,epsilon_three2}.png`) 이미지 5장을 만들어 표준 Windows
   폴더 선택 다이얼로그(경로 직접 타이핑)로 실제 선택 → "5개 이미지" 정상 인식. 정렬 콤보를
   "폴더"로 전환하니 `sub1 (2)` > `beta_one.png`/`sub2 (1)` > `gamma_two.png`, `sub3 (2)` >
   `delta_three.png`/`epsilon_three2.png` **실제 디렉터리 중첩 구조 그대로 트리에 반영됨을
   육안 확인** — 구현 로그의 재귀 스캔 주장이 헤드리스 테스트뿐 아니라 실 GUI 조작으로도
   재현됨(BUG-005 죽은 코드 문제 재발 없음).
7. **폴더 헤더 접기/펼치기** — 더블클릭으로는 정상 동작(sub1 폴더 더블클릭 → 자식 3개
   숨김/재표시 정상 토글). 다만 단일 클릭용 펼침 화살표 인디케이터가 스크린샷 8배 확대로도
   전혀 보이지 않음 — `_TREE_STYLE`의 `QTreeWidget::branch` 커스텀 스타일이 OS 기본 화살표
   렌더링을 억제하는데 `:has-children`/`:open`/`:closed` 이미지를 지정하지 않아 발생.
   `image_browser.py`의 기존 `_TREE_STYLE`을 그대로 재사용한 결과라 이번 라운드가 만든
   결함은 아니지만, `image_browser.py` 쪽은 BUG-005로 인해 지금까지 실제 노출된 적이
   없었고 이번 라운드가 처음으로 실사용 경로에서 드러냄 — **QA.md BUG-010(P3)로 등록**.
8. **검색 필터** — "gamma" 입력 시 200ms 디바운스 후 트리가 `sub1(1)>sub2(1)>gamma_two.png`
   1건으로 정확히 필터링, 뷰어도 자동으로 gamma_two.png로 갱신. 검색어를 지우면 트리는
   5장 전체로 정상 복원되나, **하단 "N / M" 카운터가 필터 중 값("1 / 1")에 고정된 채
   갱신되지 않는 것을 실측으로 발견** — "다음" 버튼을 눌러야만("4 / 5") 정정됨. 실제
   이미지 인덱스/네비게이션 자체는 정상이라 데이터 손상은 없으나 표시 오류 — **QA.md
   BUG-009(P2)로 등록**.
9. **정렬 콤보 · 이미지 클릭 → 뷰어 반영** — 콤보 드롭다운에 5개 모드(파일명↑/↓/최근
   수정순/오래된 수정순/폴더) 전부 정상 표시, "폴더" 모드 선택 자체가 위 6번 재현의 일부로
   실제 반영됨을 확인. 리스트에서 이미지 항목을 클릭하면 뷰어 상단 파일명 라벨과 캔버스가
   즉시 갱신되는 것도 여러 차례(검색 결과 클릭, prev/next, 폴더 트리 리프 클릭) 확인 —
   기존 추론 탭 골든패스(이미지 선택→표시)가 신규 컴포넌트로 깨지지 않음.
10. **회귀 확인 — 체크포인트 선택 → 추론 실행 → 오버레이 표시(끝까지)** — "새로고침" 클릭 시
    2번에서 만든 체크포인트가 테이블에 나타나고 자동 선택+모델 자동 준비("자동 준비됨")됨,
    "추론 실행" 클릭 → 실제 GPU 추론 수행 → 오버레이 픽스맵이 뷰어에 표시되고 우측 범례
    테이블에 `background 100.0% / object 0.0%`(1 epoch 학습만 한 모델이라 전부 background로
    예측 — 합리적인 결과) 정상 채워짐. 오버레이 불투명도 슬라이더를 드래그(50%→94%)하니
    `_on_opacity_changed`가 실제로 재추론+재블렌딩해 오버레이가 실시간으로 진해짐 — **레이아웃
    변경으로 기존 추론 골든패스가 전혀 깨지지 않았음을 실측 확인**.
11. **앱 크래시/예외 없음** — 전 과정 스크린샷 30여 장, 학습 1개 잡 완주, 추론 실행 2회 동안
    콘솔 로그(`app_r5_stdout.log`)에 예외 21건이 있었으나 전부 기존에 알려진 cp949 콘솔
    로깅 인코딩 경고(`UnicodeEncodeError`, 파일 로그는 UTF-8로 정상 기록, 이번 라운드와
    무관 — 과거 검증 로그에서도 반복 확인된 환경 이슈)뿐이고, 그 외 실제 트레이스백은
    0건.

### 정리
테스트용 체크포인트(`projects/nok/checkpoints/R5테스트_epoch_0001.pt`)와 스크래치 디렉토리의
임시 중첩 폴더(`infer_test/`) 모두 테스트 종료 후 즉시 삭제. `taskkill`로 앱 프로세스 종료.
`git status` 확인 결과 `working tree clean`(이번 세션에서 발생시킨 코드 변경 없음,
`projects/nok/images`·`annotations` 등 실데이터 무변경) — `QA.md`(BUG-008/009/010 등록)와
이 로그 파일 append만 변경.

### 판정
- 스플리터 리사이즈·재귀 폴더 스캔·검색·정렬·이미지 선택·학습 큐 실행·추론 골든패스(체크포인트
  선택→실행→오버레이) 등 구현 로그가 주장한 핵심 동작은 실제 GUI 조작으로 전부 재현 성공,
  **회귀는 없음**.
- 다만 실제 드래그·타이핑 조작에서만 드러나는 신규 버그 3건을 발견해 QA.md에 등록:
  **BUG-008(P2, 스플리터 완전 붕괴 — 구현 로그의 "0px 방지" 주장과 실제 동작 불일치)**,
  **BUG-009(P2, 검색 필터 해제 후 네비게이션 카운터 stale)**, **BUG-010(P3, 폴더 트리 펼침
  화살표 인디케이터 미표시)**.
- **판정: 조건부 통과(Conditional Pass)** — BUG-008/009는 데이터 손실이나 크래시가 아닌
  UX/표시 결함이라 이번 라운드를 롤백할 블로커는 아니라고 판단하지만, 특히 BUG-008은 구현
  로그의 명시적 방지 주장이 실측과 어긋나므로 리더가 후속 라운드(간단히
  `setChildrenCollapsible(False)` 1줄 추가 4곳으로 해결 가능해 보임 — 구현 판단은 별도)로
  스케줄링할지 결정 필요.

---

## 2026-08-20 — BUG-008 재검증 (커밋 `7a98760` — 5개 스플리터 `setChildrenCollapsible(False)`)

이전 라운드("학습/추론 탭 서브스플리터+이미지트리 라운드 검증")에서 발견한 BUG-008
(스플리터 핸들 끝까지 드래그 시 0px 붕괴)의 수정만 좁게 재검증. 전체 골든패스는 이미
직전 라운드에서 통과했으므로 반복하지 않고, 5개 스플리터의 극단 드래그 + 정상 범위
중간 드래그만 확인.

### 방법
`C:\Users\Feel\anaconda3\python.exe main.py`를 실제 GUI 모드로 실행, `projects/nok`
프로젝트를 열어 라벨링/학습/추론 3개 탭을 순회. 기존 스크래치 스크립트
(`drag.ps1`/`click.ps1`/`screenshot.ps1`/`crop.ps1`/`type.ps1`)를 재사용, 스플리터
핸들의 정확한 픽셀 좌표는 Python(PIL)으로 스크린샷을 열어 핸들색(`#374151`) RGB를
컬럼/행 스캔해 특정한 뒤 그 좌표로 드래그. 각 스플리터마다 (1) 한쪽 극단까지, (2) 반대쪽
극단까지, 그 후 (3) 다시 중간 지점으로 드래그해 자유 리사이즈가 정상 동작하는지 확인.
스크립트/스크린샷 전부 스크래치 디렉토리에만 저장, 저장소에 추가 안 함.

### 확인 결과 (5개 스플리터 전부, 양방향 극단 + 중간 드래그)

1. **라벨링 탭 `_splitter`(좌/우 3분할)** — 좌측 끝까지 드래그 시 좌패널이 min 150px에서
   멈춤(Images/File/Folder/Delete 버튼 텍스트 잘리지만 패널 자체는 살아있음, 0px 붕괴
   없음). 우측 끝까지 드래그 시 우패널이 min 130px에서 멈춤(Annotation List/로그 라벨
   둘 다 읽힘). 중간 드래그로 좌패널을 넓히니 버튼 텍스트가 온전히 복원되는 자유
   리사이즈도 정상.
2. **라벨링 탭 `_left_splitter`(이미지브라우저↕클래스패널)** — 위로 끝까지 드래그 시
   이미지브라우저가 min 80px(툴바 행 + 잘린 항목 1줄)에서 멈춤. 아래로 끝까지 드래그
   시(핸들 좌표 재계산 후) 클래스패널이 min 80px("클래스" 라벨 + 잘린 항목 1줄)에서
   멈춤. 둘 다 0px·제목 소실 없음.
3. **라벨링 탭 `_right_splitter`(어노테이션목록↕로그)** — 아래로 끝까지 드래그 시
   로그패널이 min 80px("로그" 라벨 + 빈 로그창)에서 멈춤. 위로 끝까지 드래그 시
   어노테이션목록이 min 80px("Annotation List" 라벨 + 빈 목록창)에서 멈춤.
4. **학습 탭 `_queue_splitter`(큐영역↕모니터링영역)** — 위로 끝까지 드래그 시 큐박스가
   min 120px(Job name/Model/Add to Queue 행 + 압축된 버튼 행 전부 보임)에서 멈춤.
   아래로 끝까지 드래그 시 모니터링패널이 min 150px(Loss Chart 헤더+제목+축만 보이는
   압축 상태)에서 멈춤. 중간 드래그(핸들 정확한 위치 재탐색 후)로 자유 리사이즈도
   정상 확인 — 큐박스를 적당히 줄이고 Loss Chart가 완전한 플롯으로 확장되는 것을 실측.
   (주의: 첫 시도에서 핸들 위치를 잘못 짚어 — 라벨 텍스트의 우연한 색상 일치를 핸들로
   오인 — 드래그가 씹히는 것처럼 보였으나, 픽셀 스캔을 정밀화해 정확한 핸들 y좌표를
   재특정하니 정상 동작 확인됨. 실제 버그 아니라 측정 오류였음.)
5. **추론 탭 `outer_splitter`(체크포인트영역↕메인영역)** — 위로 끝까지 드래그 시
   체크포인트 테이블 영역이 min 140px(헤더+컬럼행+안내문구)에서 멈춤. 아래로 끝까지
   드래그 시 메인영역(뷰어+범례)이 min 200px("선택된 이미지 없음"/"클래스 범례"/오버레이
   불투명도 슬라이더 전부 보임)에서 멈춤.
6. **추론 탭 3분할 `splitter`(이미지목록|뷰어|범례)** — 폴더 선택으로 이미지 5장을 로드해
   목록패널을 노출시킨 뒤 테스트. 좌측 끝까지 드래그 시 목록패널이 min 140px(이미지
   목록 + 잘린 이전/다음 버튼)에서 멈춤. 우측 끝까지 드래그 시 범례패널이 min 160px
   ("클래스 범례" 헤더 + 테이블)에서 멈춤. 중간 드래그로 목록패널을 넓히니 "이전 1/5
   다음" 버튼 텍스트가 온전히 복원되는 자유 리사이즈도 정상.

### 판정
**통과** — 5개 스플리터 전부 양방향 극단 드래그에서 설정된 최소 크기(80~200px)에서
정확히 멈추고 0px 붕괴·제목 소실이 재현되지 않음. 직전 라운드에서 실측으로 확인했던
붕괴 현상이 이번 수정으로 완전히 해소됨. 정상 범위 중간 드래그(자유 리사이즈)도 5개
스플리터 전부에서 문제없이 동작 — `setChildrenCollapsible(False)`가 일반 리사이즈
기능을 저해하지 않음을 확인. `QA.md`의 BUG-008을 "재검증 완료"로 갱신. 새로운 회귀나
크래시 없음, `git status --porcelain` 결과 `QA.md`(BUG-008 재검증 완료 갱신)와 이 로그
파일 append만 변경, 코드 파일 무수정.

---

## 2026-08-20 — GitHub 이슈 라운드2 (#3/#4/#6-A/#7) 검증 (커밋 `6a823a5`, `29248fa`)

`docs/specs/voc-github-issues-round2-2026-08-20.md`, `docs/agents/implementation-log.md`
"GitHub #6-A 오버레이 깜빡임 수정"·"GitHub #7/#4/#3(a)(b) 구현" 두 항목 검증. 결정 완료된
4건(#3 전체, #4, #6-A, #7)이 대상, #5(모델 탭 구조변경)는 보류라 범위 밖. 라벨링 탭 캔버스
이벤트 핸들러·저장 흐름을 직접 건드리는 규모 있는 변경이라 "주요 기능 추가" 수준으로 판단해
정적 검토를 넘어 `python main.py` 실제 GUI 조작(마우스 클릭/더블클릭/타이핑)까지 수행.
(참고: 리더 메모대로 직전 시도가 API 세션 한도로 중단된 재시도 세션 — 이번 세션 스크래치
디렉토리에 이전 라운드(BUG-008 재검증)의 잔여 스크립트/스크린샷이 있었으나 이번 검증과는
무관해 재사용만 하고 별도 구분되는 `r2_*` 접두사로 새로 작업함.)

### 방법
`C:\Users\Feel\anaconda3\python.exe main.py`를 실제 GUI 모드(오프스크린 아님)로 백그라운드
실행, `projects/nok` 프로젝트를 열어 조작. PowerShell(`System.Windows.Forms`/`System.Drawing`
P/Invoke) 스크립트(`click.ps1`/`drag.ps1`/`screenshot.ps1`/`type.ps1`, 기존 라운드에서
재사용)로 실클릭·더블클릭·타이핑, `Get-Clipboard`/`System.Windows.Forms.Clipboard`로 실제
Windows 클립보드 내용 UTF-8 파일로 덤프해 검증. 스크린샷은 Python(PIL)으로 크롭·확대해
육안 확인. 스크립트/스크린샷 전부 스크래치 디렉토리에만 저장, 저장소에 추가 안 함.
`data/logs/app.log`(타임스탬프 포함 실행 로그)를 교차 참조해 UI 조작과 내부 이벤트 순서를
대조.

### 확인 결과

1. **#3(a) 브러시 스핀박스 잘림 수정** — 툴바 스핀박스에 `150` 입력 후 확대 스크린샷으로
   확인, 3자리 숫자가 전혀 잘리지 않고 온전히 표시됨(`setMinimumWidth(76)` 정상 반영).
   **통과.**
2. **#4 이미지명 클립보드 복사(라벨링 탭)** — 채널 스트립에 파일명 라벨("11번.bmp")+클립보드
   아이콘 버튼 확인. 버튼 클릭 후 `System.Windows.Forms.Clipboard`를 UTF-8로 덤프해
   `11번.bmp` 정확히 일치 확인(사전에 마커 문자열로 클립보드를 비워 오검출 방지). **통과.**
3. **#4 이미지명 클립보드 복사(추론 탭)** — "폴더 선택…"으로 `projects/nok/images` 로드 후
   목록에서 이미지 선택, 기존 `_lbl_filename` 옆 신규 복사 버튼 클릭 → 클립보드
   `10번.bmp` 정확히 일치 확인. **통과.**
4. **#3(b) 더블클릭 브러시 크기 다이얼로그 — 다이얼로그 자체 동작은 정상** — 브러시 도구
   활성 후 캔버스 더블클릭 → `QInputDialog.getInt()` 다이얼로그가 현재 스핀박스 값(150)을
   기본값으로 정상 표시, `77` 입력 후 OK → 툴바 스핀박스가 즉시 `77`로 동기화됨(다이얼로그→
   스핀박스 방향 확인). 폴리곤 도구에서 점 3개 찍고 더블클릭 시 기존 폴리곤 닫기 동작이
   그대로 유지되어 브러시 다이얼로그와 충돌하지 않음도 확인(삼각형 폴리곤 정상 생성).
5. **#3(b) — 심각한 부수 버그 발견(BUG-011, P1)** — 브러시 계열 도구에서 더블클릭으로 크기
   다이얼로그를 열 때마다, 더블클릭의 첫 클릭(mousePress+Release)이 일반 브러시 페인트로
   처리되어 클릭 지점에 **의도치 않은 `[Mask]` 어노테이션이 매번 추가**됨. 다이얼로그를
   OK로 닫든 Cancel로 닫든 이 stray 마스크는 그대로 남고 Undo로만 제거 가능함을 스크린샷
   비교로 실측 확인(다이얼로그 열기 전/후 Annotation List 항목 수 비교, 2회 재현 모두 동일
   패턴). `QA.md` BUG-011(P1)로 등록 — 이 기능을 쓸 때마다 매번 사용자가 인지하지 못한 채
   라벨 데이터가 오염될 수 있는 실사용 리스크로 판단.
6. **#7 OK 확인 팝업 — 예/아니오/무라벨 3가지 경로 전부 정상** — 어노테이션이 있는 이미지에서
   OK 토글 시 `QMessageBox.question()` 팝업("Delete Labels and Mark OK" — 영문 UI 상태에서
   테스트, i18n 정상 반영 확인) 표시. "No" 클릭 시 체크 상태 원복 + 라벨 그대로 유지(Annotation
   List에 `#1 [Mask]` 남음) 확인. "Yes" 클릭 시 라벨 삭제 + OK 처리 + 사이드바 즉시 체크마크로
   갱신 확인, 재로드(다른 이미지 클릭 후 복귀) 후에도 `annotations/10번.json`을 직접 `cat`해
   `{"annotations": [], "ok": true}` 정확히 저장·유지됨을 파일 레벨로 확인 — **데이터 무결성은
   완전히 정상.** 어노테이션 없는 이미지에서 OK 토글 시 팝업 없이 즉시 처리되는 것도 코드
   리딩으로 확인(런타임 별도 재현 불필요할 만큼 로직 단순, `if ... and self._canvas._annotations`
   가드).
7. **#7 — 부수 버그 발견(BUG-012, P2)** — 위 6번 "Yes" 경로 실행 직후에는 사이드바 아이콘이
   정확히 체크마크로 갱신되지만, 다른 이미지로 전환했다가 다시 돌아오면 사이드바 아이콘만
   "미라벨"(빈 원)로 되돌아감 — 단, 이때도 디스크 JSON과 툴바 OK 액션 체크 상태는 둘 다
   정확하게 "OK"를 유지하고 있어 **데이터 유실은 아니고 사이드바 아이콘만 stale**해지는 표시
   버그. `app.log` 타임스탬프 대조로 `_save_timer`(500ms 디바운스)가 지연 발화하며
   `_on_annotation_saved()`가 다른 시점의 상태를 여러 차례 반영하는 정황까지는 확인했으나,
   정확한 트리거 라인은 미확정 — `QA.md` BUG-012(P2)로 등록, 후속 조사 필요로 기록.
8. **#3(b) — i18n 누락 발견(BUG-013, P3)** — 브러시 크기 다이얼로그의 제목/라벨
   (`"브러시 크기"`/`"브러시 크기 (1~200)"`)이 `t()` i18n 체계를 거치지 않고 하드코딩된
   한국어로 표시됨 — 같은 화면의 툴바 "Brush size:" 라벨(`tool.brush_size` 키)은 정상
   영역화된 것과 대비. "아이콘/이모지 → 미니멀 디자인 + i18n(en) 완비" 라운드의 en 193키
   정비 범위 밖에서 이번 라운드에 새로 추가된 문자열이라 누락된 것으로 판단. `QA.md`
   BUG-013(P3)로 등록.
9. **#6-A 깜빡임 — 코드 검토 + 회귀 확인** — `_invalidate_overlay()`가 `self._overlay = None`
   즉시 처리를 제거하고 새 오버레이가 준비될 때까지 이전 오버레이를 유지하도록 수정된 것을
   코드 레벨로 확인, `load_image()`에서는 이미지 전환 시에만 예외적으로 명시적 null 처리를
   유지함도 확인(좌표계 불일치 방지 목적, 스펙 의도와 일치). 실제 GUI로 연속 브러시 스트로크
   (11번.bmp에 삼각형 폴리곤 생성), 빠른 이미지 전환(10↔11↔7↔8↔9번 반복 클릭, sleep 최소화),
   채널 토글 후 즉시 라벨링 시나리오를 수행 — 어노테이션이 통째로 사라지는 flicker는
   스크린샷상 재현되지 않았고(다만 수십~수백ms 단위 시각적 깜빡임은 스크린샷 캡처 방식의
   본질적 한계로 완전히 배제할 수는 없음), 무엇보다 **데이터 무결성 관점에서 이상 없음**을
   확인 — 빠른 연속 전환 후에도 각 이미지의 어노테이션 개수·내용이 정확히 유지됨(`app.log`
   저장 로그와 최종 Annotation List 대조), 채널 토글 직후 라벨링해도 어노테이션이 사라지지
   않음. `data/logs/app.log`에 예외/트레이스백 0건.
10. **일반 회귀 — 라벨링 골든패스** — 도구 전환(폴리곤↔브러시↔선택), 폴리곤 생성/닫기,
    브러시 스트로크 생성, Undo(다회), 이미지 전환 시 자동저장, 어노테이션 목록 패널 동기화
    모두 정상 동작. 테스트로 추가한 임시 어노테이션(11번.bmp 삼각형 폴리곤, 10번.bmp 브러시
    마스크/OK 플래그)은 전부 Undo 또는 `git checkout`으로 원상 복구, `git status --porcelain
    -- projects/nok` 결과 공백(변경 없음) 최종 확인.

### 정리
`taskkill`로 앱 프로세스 종료. `git status --porcelain -- projects/nok data/settings.json`
결과 공백 — 테스트 중 생성한 임시 어노테이션(10번.bmp OK 플래그+빈 마스크, 11번.bmp 임시
폴리곤/마스크 dab)은 Undo 및 `git checkout -- "projects/nok/annotations/10번.json"`으로 전부
원상 복구, 실데이터 무변경. `QA.md`(BUG-011/012/013 신규 등록)와 이 로그 파일 append만 변경,
코드 파일 무수정.

### 판정
- **#3(a), #4(라벨링/추론 탭), #7(핵심 확인 팝업+데이터 무결성), #6-A(플리커 회귀 없음)는
  통과.**
- **#3(b)는 조건부 통과** — 핵심 요구사항(더블클릭→다이얼로그→스핀박스 동기화)은 정상
  동작하지만, 매 사용 시 원치 않는 브러시 마스크가 생성되는 BUG-011(P1)을 발견했다. 이는
  "라벨링 정확도"라는 앱의 핵심 가치와 직결되는 회귀이자 사용 빈도가 높을 기능이라, 데이터
  손실이나 크래시는 아니지만(Undo로 복구 가능) 사용자가 눈치채지 못한 채 라벨 데이터가
  오염될 실사용 리스크가 있다고 판단 — 리더가 우선순위를 재검토해 후속 라운드로 신속히
  수정할 것을 권장한다(더블클릭의 첫 클릭에서 브러시 페인트를 억제하는 가드 1줄 수준으로
  해결 가능해 보임 — 구현 판단은 별도).
- 추가로 BUG-012(P2, OK 사이드바 아이콘 stale — 데이터는 정상), BUG-013(P3, 브러시 다이얼로그
  i18n 누락)을 발견해 `QA.md`에 등록. 둘 다 이번 라운드를 롤백할 블로커는 아니다.
- **종합 판정: 조건부 통과(Conditional Pass)** — #3(a)/#4/#6-A/#7은 완전 통과, #3(b)는
  핵심 기능은 동작하나 BUG-011(P1) 수정 전까지 실사용 시 라벨 데이터 오염 위험을 사용자에게
  안내하거나 신속한 후속 수정이 필요하다.

---

## 2026-08-20 — BUG-011/012/013 재검증 (GitHub 이슈 라운드2 후속 수정)

### 배경
`implementation-log.md`의 "GitHub #3(b) 검증 후속"(BUG-011, 커밋 `24e93c9`, 리더가 직접
수정)과 "GitHub #3/#4/#6-A/#7 라운드2 검증 후속"(BUG-012/013, 커밋 `5d551c3`) 두 수정을
재검증. 대상 파일은 `app/widgets/annotation_canvas.py`(`mouseDoubleClickEvent()`, `undo()`,
`_do_save(sync: bool)`), `app/tabs/labeling_tab.py`(`_on_toggle_ok()`), `app/core/i18n.py`
(`tool.brush_size_dialog.*` 키).

### 방법
이 자동화 셸은 실제 마우스/키보드로 GUI를 조작할 수 없어(이전 라운드 검증 로그들과 동일한
제약), `QT_QPA_PLATFORM=offscreen` + `QApplication` 실제 생성 + `PyQt6.QtTest.QTest`로
진짜 Qt 이벤트(마우스 press/release/더블클릭)를 위젯에 전달하는 방식으로 골든 패스를
재현했다. 데이터는 `projects/nok`을 스크래치 디렉토리(`.../scratchpad/test_project`)로
복사해 사용 — 실 데이터(`projects/nok`)는 읽기 전용으로만 열었다(`project.open_existing()` 후
`project_mod._current`에 직접 대입, `set_current()`가 건드리는 `data/settings.json`
`recent_projects`/`last_project`는 우회). 스크립트: `verify_bugs.py`(BUG-011/012/013 본 검증),
`verify_boot.py`(앱 기동 확인) — 둘 다 스크래치 디렉토리에만 저장, 프로젝트에 추가 안 함.

### BUG-011 재검증 — PASS
`AnnotationCanvas`를 직접 생성해 `projects/nok` 이미지(`10번.bmp`) 로드 → 브러시 도구
선택 → `QInputDialog.getInt`를 패치(Cancel/OK 각각 시뮬레이션)한 뒤 `QTest.mouseDClick()`으로
실제 Qt 더블클릭 이벤트 시퀀스(press→release→press→doubleClick→release)를 그대로 위젯에
전달:
- Cancel 케이스 1회, OK 케이스(브러시 크기 변경) 3회 반복 — **매번 어노테이션 개수가
  더블클릭 전후 정확히 동일(0 → 0)**, stray `[Mask]` 어노테이션 미생성 확인. OK 케이스에서
  브러시 크기(`_brush_size`)는 다이얼로그 반환값(15)으로 정상 반영됨도 확인.
- **회귀 확인**: 더블클릭이 아닌 일반 연속 페인팅(press→move→release)은 여전히 어노테이션
  1개로 정상 커밋됨(0 → 1). 그 뒤 `canvas.undo()`(Ctrl+Z 경로) 호출 시 정확히 그 1개만
  제거되어 원상태로 복귀 — undo 스택 자체의 회귀 없음.

### BUG-012 재검증 — PASS
`LabelingTab()`을 직접 생성(`_image_browser.reload()` 포함), 실제 어노테이션이 있는
`11번.bmp`(폴리곤 1개, `ok` 미설정)를 대상으로 선택. `QMessageBox.question`을 `Yes`로
패치해 `_act_ok.setChecked(True)` → `_on_toggle_ok()`(GitHub #7 "예" 경로: 라벨 삭제
확인 → 동기 flush → OK 설정) 실행:
- 토글 직후 `store.get_ok()=True`, 사이드바 `_status_cache["11번"]="ok"` 즉시 일치 확인.
- **다른 이미지로 전환 후 11번으로 복귀를 6회 반복**(매 라운드 사이 50ms 대기 — 잔존
  가능한 비동기 스레드에 여유를 주기 위함) — **매 라운드 사이드바 캐시=`ok`, 디스크
  JSON `ok:true`, `annotations:[]`(빈 배열) 완전 일치, 불일치 0건**. 과거 보고된 "돌아오면
  미라벨로 되돌아감" 증상 재현 안 됨.
- **회귀 확인**: 어노테이션이 없는 이미지(`10번.bmp`)에서 OK 토글(확인창 없이 바로
  진행되는 경로) on/off 각각 정상 동작. 다른 이미지(`10번.bmp`)에 브러시 스트로크 1개를
  그린 뒤(500ms 디바운스 타이머 시작 확인) 타이머 만료 전에 즉시 다른 이미지로 전환 —
  `load_image()`의 기존 flush 경로(`_do_save()`, 비동기)가 정상 동작해 스트로크 1개가
  `10번.json`에 정확히 저장됨. 이번 수정이 건드리지 않은 다른 `_do_save()` 호출부(디바운스,
  이미지 전환 전 flush)에 회귀 없음을 확인.

### BUG-013 재검증 — PASS
`i18n.set_language("en")` 후 `t("tool.brush_size_dialog.title")` = `"Brush Size"`,
`t("tool.brush_size_dialog.label")` = `"Brush size (1~200)"` 확인(영문). `i18n.set_language
("ko")`로 되돌리면 각각 `"브러시 크기"`, `"브러시 크기 (1~200)"`로 정상 복귀(한글) —
`annotation_canvas.py`의 더블클릭 다이얼로그가 이 두 키를 통해 `t()`를 호출하는 코드 경로를
직접 확인했으므로(정적 리딩), 언어 전환 시 다이얼로그 문자열도 동일하게 전환됨을 신뢰할 수
있음.

### 앱 기동 확인 (`verify_boot.py`)
`QApplication` 생성 → `PyQt6.QtSvg` 선행 import(이 자동화 셸 특유의 DLL 로드 순서 이슈 —
`app.core.project`보다 `PyQt6.QtSvg`를 먼저 import해야 `ImportError: DLL load failed while
importing QtSvg`가 회피됨, R4/R5 검증 로그의 기존 회피 패턴과 동일 계열의 별도 이슈로
추정, 이번 라운드가 만든 문제 아님) → `projects/nok`을 읽기 전용으로 오픈(`set_current()`
미사용) → `MainWindow()` 생성 → `show()`까지 예외 없이 통과.

### 정리
`git status --porcelain` 결과 공백(변경 없음, `data/settings.json`도 무변경 — 스크립트가
전부 `project_mod._current` 직접 대입 방식으로 `set_current()`의 `recent_projects` 부작용을
우회했기 때문). 테스트 데이터는 전부 스크래치 디렉토리 사본(`test_project`)에서만 수정,
`projects/nok` 실데이터는 읽기 전용으로만 열어 무변경. `QA.md`의 BUG-011/012/013 세 항목에
"재검증 완료(2026-08-20, verifier)" 문구와 구체적 재현 절차·결과를 추가했다(Closed Issues
표는 유지, 재검증 필요 문구만 완료 문구로 교체).

### 판정
- **BUG-011/012/013 세 건 모두 재검증 통과.** 신규 회귀 발견 없음(정상 브러시 페인팅, undo
  단축키, 무라벨 OK 토글, 이미지 전환 시 디바운스 flush 전부 정상).
- **종합 판정: 통과(Pass)** — 별도 블로커 없음. 이번 라운드로 GitHub 이슈 라운드2에서
  발견된 3개 버그(BUG-011/012/013)가 모두 해소된 것으로 확인.

---

## 2026-08-20 — GitHub #6-B 검증: 어노테이션 개수 증가 시 로딩 지연 최적화 (최우선, 사용자 명시)

`docs/agents/implementation-log.md` "GitHub #6-B" 항목(커밋 `574fb33` perf + `5f13df4` docs)
검증. 대상: `app/tabs/labeling_tab.py::_refresh_ann_list()`(diff 기반 갱신),
`app/widgets/annotation_canvas.py::_OverlayWorker.run()`(brush_mask bbox-crop 렌더링).
사용자가 "반드시 필요"로 직접 명시한 최우선 항목이라 실행 확인을 꼼꼼히 수행.

### 정적 검토
- `_refresh_ann_list()` — 위치 기반 diff(`min(n_old, n_new)`까지 텍스트/UserRole 비교 후
  변경분만 `setText`/`setData`, 초과분 `addItem`, 부족분 꼬리부터 `takeItem`) 로직을 코드
  리딩으로 확인. 선택 상태 유지 메커니즘(`_ann_list_updating` 재진입 방지 플래그 +
  `_on_canvas_selection_changed`가 삭제/undo 등 위치가 바뀌는 모든 경로에서 `selection_changed`
  를 **동기적으로 먼저** emit해 리스트 선택을 클리어한 뒤에야 디바운스된 저장이 `_refresh_
  ann_list()`를 호출)를 캔버스 쪽 삭제/undo 코드(`_delete_selected_or_last` 등 8곳의
  `_selected_ids.clear()`+`selection_changed.emit(...)` 동기 호출부)까지 추적해, diff 갱신이
  중간 삭제로 인덱스가 밀려도 "유령 선택"(엉뚱한 위치의 아이템이 과거 선택 상태를 그대로
  유지하는 문제)이 발생하지 않는 구조임을 확인.
- `_OverlayWorker.run()` — `_mask_bbox()`(`cv2.boundingRect` + margin=1 클리핑)로 자른
  서브영역만 `cv2.resize`/`_draw_mask_on_painter`/`cv2.dilate`. sc<0.99(다운스케일) 분기는
  `p.resetTransform()` 후 `ox=round(x0*sc)` 방식으로 절대 좌표 합성 — 좌표 변환 로직 확인.
  `_draw_mask_on_painter()`의 `np.empty(...)` → `QImage(argb.data, ...)` → `p.drawImage()`
  패턴은 이 라운드가 새로 만든 게 아니라 기존에도 브러시 레이어 그리기에서 쓰이던 재사용
  패턴이며, `drawImage()`가 동기 호출로 즉시 픽셀을 대상 이미지에 복사하므로 `argb`가
  함수 종료 후 GC돼도 문제없음을 확인(버퍼 수명 문제 아님).
- GitHub #6-A(`_invalidate_overlay()`의 stale-overlay 유지)와 BUG-011/012(`mouseDoubleClickEvent`
  의 `undo()`, `_do_save(sync=True)`) 로직은 `git show 574fb33`으로 diff 라인을 직접 대조해
  이번 커밋이 건드리지 않았음을 재확인.

### 실행 확인 — 앱 기동
- `C:\Users\Feel\anaconda3\python.exe main.py`를 대화형으로 직접 실행 — **QtSvg DLL 로딩
  이슈 이번 세션에서는 재현되지 않음**, `MainWindow`가 정상 기동해 이벤트 루프까지 진입
  확인(로그 인코딩 관련 `UnicodeEncodeError`만 콘솔에 출력됨 — cp949 콘솔이 `—`(em dash)를
  못 그려서 나는 기존 로깅 이슈이며 이번 라운드와 무관, 앱 동작 자체엔 영향 없음). 프로세스
  실제 기동 후 `tasklist`로 587MB 메모리 사용 중인 살아있는 프로세스임을 확인 후 정상 종료.

### 실행 확인 — 골든패스 (QTest 기반 실제 Qt 이벤트, projects/nok 이미지 2장 사용한 임시
프로젝트, `D:\_scratch_verify_6b`, 검증 후 삭제 — nok 원본은 이미지 2장 읽기 전용 복사만
했고 `git status --porcelain -- projects/nok` 공백으로 무변경 확인)
스크래치 스크립트(`verify_6b.py`, 프로젝트에 추가 안 함) — `QT_QPA_PLATFORM=offscreen` +
실제 `QApplication`/`LabelingTab`/`AnnotationCanvas` 생성 + `QTest`로 진짜 Qt 이벤트 전달.
총 30개 assertion **전부 PASS**:

1. **폴리곤/브러시/지우개/영역지우개/선택 도구** — 각각 실제 위젯 메서드
   (`_close_polygon`/`_paint_circle`+`_paint_stroke`+`_finish_brush`/`_flood_erase`)로
   골든패스 수행, 전부 정상 커밋·삭제.
2. **브러시 bbox-crop 정확성** — 알려진 위치(이미지좌표 1000,1000~1050,1050)에 L자 스트로크
   → `brush_ann.mask[1000,1000]==True` 확인, `_mask_bbox()` 반환값이 예상 범위(989~1062)
   내 확인. 오버레이 워커 완료 대기 후 **오버레이 QImage를 실제로 numpy 배열로 읽어**
   스트로크 시작점에 해당하는 오버레이 픽셀(스케일 변환 `ox=round(1000*sc)` 적용,
   sc=0.374)의 alpha 채널이 0보다 큼(=140, `OVERLAY_ALPHA`와 정확히 일치)을 확인, 먼 지점
   (5,5)은 alpha=0 확인 — bbox-crop 합성이 실제로 올바른 위치에 그려짐을 픽셀 단위로 검증.
   (첫 시도에서 스트로크 경로 밖의 "L자 안쪽 코너"를 검증 지점으로 잘못 골라 FAIL이
   났었는데, 브러시 반경(10px) 밖이라 애초에 칠해지지 않는 지점이었음을 확인하고 스트로크
   시작점으로 교체 — 앱 버그 아니라 검증 스크립트 자체의 좌표 선정 오류였음.)
3. **어노테이션 목록 diff 정확성** — 5개 중 인덱스 2(가운데) 삭제 후: 목록 개수 4로 정확히
   감소, 삭제된 ID 완전히 사라짐, 나머지 항목 순번(`#1~#4`)이 정확히 재계산되어 텍스트
   갱신됨, **유령 선택 없음**(선택 안 한 상태에서 삭제 후 `selectedItems()` 빈 배열).
4. **선택 도구 ↔ 목록 동기화** — 캔버스에서 선택 → `selection_changed` emit →
   `_refresh_ann_list()` 후에도 목록 패널의 `selectedItems()`가 정확히 일치.
5. **undo** — 정상 동작(카운트 변화 확인).
6. **BUG-011 회귀** — `QTest.mouseDClick()`으로 실제 press→release→press→doubleClick→release
   시퀀스 재현(OK 케이스 + Cancel 케이스 각 1회) — **두 경우 모두 stray 어노테이션 0건**.
   일반 단일 클릭(press→move→release, 더블클릭 아님)은 정상적으로 스트로크 1개 커밋되는
   회귀 확인도 별도로 통과.
7. **BUG-012 회귀** — 어노테이션 있는 이미지에서 OK "예" 토글 → 다른 이미지로 전환 →
   되돌아옴 → `refresh_item()` 후에도 `get_ok()` 결과가 토글 직후 값과 완전히 일치(stale
   없음).
8. **대규모 어노테이션(n=200, 5472×3648, polygon+brush_mask 혼합) 체감 성능** —
   `_refresh_ann_list()` 1회 3.5ms(리스트 200개 채움), `_OverlayWorker.run()` 1회 691.5ms
   (구현 에이전트의 n=500 기준 ~1600ms와 비례 스케일 일치 — 200/500 비율 적용 시 예상
   640ms 대 실측 691.5ms로 근접, 별도 벤치마크 신뢰성 뒷받침). 연속 20회 append(list-only,
   n~200→220)는 12.2ms — 실제 위젯 기반 반복 편집에서도 크래시·행 없이 매끄럽게 동작.
9. **GitHub #6-A 회귀** — 연속 브러시 스트로크 5회(각 스트로크마다 `_invalidate_overlay()`
   호출) 동안 `canvas._overlay`가 단 한 번도 `None`이 되지 않음(stale-overlay 유지 로직
   정상 — 깜빡임 재발 없음).

### 발견 — BUG-014 (P3, QA.md 등록, 이번 라운드 회귀 아님)
대규모 스트레스 테스트 중, n=200 대형 brush_mask(19MB/개, 5472×3648)가 있는 상태에서 실제
브러시 스트로크 1개를 추가로 그리면(`mousePressEvent`가 항상 먼저 호출하는 `_push_undo()`
경유) `copy.deepcopy(self._annotations)`가 이 세션 환경(Windows, 페이징 파일 2GB — R4 구현
로그에 동일 제약 기록됨)에서 `numpy._core._exceptions._ArrayMemoryError`로 크래시 재현(물리
RAM 16GB+ 여유 있었음에도 재현 — 커밋/페이징 한도 문제로 추정). `_push_undo()`는 이번
#6-B 라운드가 건드린 함수(`_refresh_ann_list`/`_OverlayWorker.run`)와 다른, 그 이전부터
존재하던 전체 deepcopy 구조라 이번 라운드의 회귀는 아니지만, #6-B로 대량 어노테이션에서의
목록/오버레이 체감이 좋아진 직후라 이 한계가 상대적으로 더 두드러질 수 있어 함께 기록.
상세: `QA.md` BUG-014.

### 정리
스크래치 스크립트(`verify_6b.py`, `debug_overlay.py`)는 scratchpad에만 작성, 프로젝트에
추가 안 함. C: 드라이브 여유공간 부족(~25MB 실측)으로 임시 프로젝트를 scratchpad(C:) 대신
`D:\_scratch_verify_6b`에 생성했고, 검증 종료 후 `rm -rf`로 완전히 삭제함. `projects/nok`은
이미지 2장만 읽기 전용으로 복사해 사용, `git status --porcelain -- projects/nok` 공백으로
원본 무변경 확인. `git status --porcelain` 결과 `QA.md`(BUG-014 추가)만 수정됨.

### 판정
**통과(Pass)** — GitHub #6-B(어노테이션 개수 증가 시 로딩 지연) 구현이 실제 UI 조작
기준으로 정상 동작함을 확인. 정확성(오버레이 픽셀 단위 위치 검증, 목록 diff 순번/유령선택
없음), #6-A/BUG-011/BUG-012 회귀 없음, 대규모(n=200) 체감 성능 개선(구현자 벤치마크와
스케일 일치) 모두 확인됨. 별도 블로커 없음. 부수 발견 BUG-014(P3, 이번 라운드 무관 기존
`_push_undo()` deepcopy 메모리 리스크)는 QA.md에 등록, 후속 라운드 판단 대상.

---

## 2026-08-21 — 디자인 7단계 실행안 ⑥ i18n 밖 3파일 en 전환 + ⑦ 팔레트 토큰 정규화 검증 (7단계 실행안 최종 라운드)

`docs/agents/implementation-log.md` 2026-08-21 항목(커밋 `96b829c` feat + `8f78f8a` refactor)
검증. Artifact 7876ed3e 7단계 실행안의 마지막 두 단계로, 이번 라운드가 통과하면 7단계
실행안 전체가 완료된다.

### 정적 검토
- `git show 96b829c`/`8f78f8a` diff 전수 확인. `app/core/i18n.py`에 27개 신규 키
  (`project.status_bar`, `browser.*` 22개, `train_progress.*` 10개)가 ko/en 양쪽에
  1:1로 존재함을 직접 대조 확인 — 누락 없음.
- `image_browser.py`/`training_progress_dialog.py`/`main_window.py` 3개 파일에 남은
  한글을 `[가-힣]` 정규식으로 재검색(Grep) — 남은 매치는 전부 주석/docstring뿐, UI
  문자열은 모두 `t()` 경유로 이관됨을 확인.
- `training_progress_dialog.py`에 `from app.core.i18n import t` 임포트 정상 추가 확인.
- `labeling_tab.py`/`training_tab.py`(⑦) diff: `#888`→`#9ca3af`, CUDA 배너
  `background:#0d1f0d/#1f0d0d` → `background:#1f2329; border-left:3px solid
  #10b981/#f87171`로 교체됨을 확인.

### 실행 확인 — `python main.py` 실제 GUI 구동 (PowerShell 스크린샷/클릭 자동화)
`projects/nok` 프로젝트로 실제 앱을 두 번(en/ko 각각) 기동해 확인.

1. **en 모드 (`data/settings.json` language=en, 이 세션 시작 시점 이미 en으로 설정돼
   있었음)** — 라벨링 탭: 이미지 브라우저 "Search filename..." placeholder, 정렬 콤보
   드롭다운 5개 항목("Name ↑"/"Name ↓"/"Folder"/"Done↑"/"To do↑") 전부 정상 렌더링,
   범례("Labeled"/"OK"/"Unlabeled"), 상태바 "Project: nok (D:\segmentation
   model\projects\nok)"(`project.status_bar` 포맷) 전부 확인. "Folder"/"File" 추가
   버튼 클릭 → 네이티브 파일 다이얼로그 제목이 각각 "Select Folder"/"Add Images"로
   정상 표시(다이얼로그 본체는 OS 로케일이라 한글 유지, 이는 Qt 표준 동작이라 정상).
   이미지 삭제 버튼 → "Confirm Delete" 타이틀 + "Delete '10번.bmp'?\n(Its annotations
   will also be deleted)" 메시지 정확히 확인 후 **No로 취소해 nok 데이터 무변경 유지**.
2. **ko 모드** — Settings 다이얼로그에서 언어를 한국어로 전환·저장(재시작 필요 안내
   팝업 "재시작 필요"/"언어 설정이 저장되었습니다..." 정상 한글) 후 앱 재기동. 탭 이름
   "라벨링/학습/추론/모델", 이미지 브라우저 "파일명 검색...", "정렬: 파일명 ↑",
   범례 "라벨링됨/OK/미라벨", 상태바 "프로젝트: nok (D:\segmentation
   model\projects\nok)" 전부 정상. 학습 탭도 "학습 큐"/"작업 이름"/"모두 실행"/
   "체크포인트 주기 (epoch)" 등 전부 정상 한글 렌더링(회귀 없음).
3. **`TrainingProgressDialog` 직접 검증** (실제 체크포인트 학습 없이, `set_current_job`/
   `update_epoch`/`update_queue`/`set_done`을 실제 데이터로 호출 후 `QWidget.grab()`
   스크린샷) — ko: "▶ 현재 작업"/"예상 소요 시간"/"이 작업: 05:40"/"전체 큐: 15:20"/
   "학습 큐"/"■ 현재 작업만 중지"/"■■ 전체 중지"/"창 닫기" 전부 정상. en: "Current Job"/
   "Estimated Time"/"This job: 05:40"/"Total queue: 15:20"/"Training Queue"/
   "Stop Current"/"Stop All"/"Close" 전부 정상. `set_done()` 후 en에서 "All Training
   Done" 정상 표시. 두 언어 모두 KeyError·깨진 텍스트 없음.
4. **CUDA 배너** — 이 세션 실제 GPU(RTX 5060, CUDA 사용 가능) 환경이라 성공 상태만
   실제 렌더링 확인(실패 상태는 코드 대칭 구조 확인으로 갈음). en/ko 두 모드 모두
   "CUDA NVIDIA GeForce RTX 5060" 초록색 텍스트는 정상 표시되나, **좌측 색상 보더가
   의도한 단일 선이 아니라 이중 막대로 렌더링되는 시각적 결함 발견 → BUG-015로 등록**
   (아래 참고).
5. **회귀 확인** — 검색창/정렬 드롭다운/범례/파일-폴더 추가 다이얼로그/삭제 확인
   다이얼로그 골든 패스 전부 정상 동작(이번 라운드가 텍스트만 `t()`로 교체했을 뿐
   로직은 안 건드렸으므로 예상대로 회귀 없음). `git status --porcelain -- projects/nok`
   공백 확인 — 실제 데이터 변경 없음.

### 발견 — BUG-015 (P2, QA.md 신규 등록)
`training_tab.py` CUDA 배너의 `border-left:3px solid #10b981`(성공)/`#f87171`(실패)가
단일 선이 아니라 ~7px 간격을 둔 두 개의 3px 막대("[[" 형태)로 이중 렌더링됨. 스크린샷
픽셀 스캔(`PIL.Image.getpixel`)으로 확인: x=0~2, x=10~12 두 구간에 정확히 `#10b981`
(16,185,129)이 반복되고 그 사이는 배경색 — 압축 아티팩트가 아니라 실제 이중 렌더링.
격리된 최소 재현 스크립트(`QHBoxLayout(margins=(10,0,4,0))` + 자식 `QLabel`이 있는
`QWidget`에 `border-left`만 지정)로 100% 재현, `border-radius` 유무와 무관함을 확인.
원인: `banner.setStyleSheet(...)`가 선택자 없는 평문 속성이라 Qt가 자손 위젯에도
전파하는데, 자식 `QLabel`이 `QFrame` 서브클래스라 `WA_StyledBackground` 없이도 부모와
동일한 `border-left`를 레이아웃 마진만큼 오른쪽으로 밀린 위치에 스스로 그려 넣어
발생. `WA_StyledBackground` 속성 추가만으로는 해결 안 됨을 별도 확인. 기능 크래시는
없으나 "발견 8"이 의도한 "깔끔한 좌측 보더" 효과를 달성하지 못하고 이전(배경 틴트만)
보다 시각적으로 더 눈에 띄는 결함을 만듦 — QA.md BUG-015에 해결책 후보(objectName+ID
선택자 스코핑, 자식 QLabel에 빈 스타일시트 명시)까지 기록.

### 정리
스크래치 스크립트/스크린샷(`verify_train_progress_dialog.py`, `repro_cuda_banner*.py`,
`v67_*.png` 등)은 전부 세션 scratchpad에만 저장, 프로젝트에 추가 안 함.
`git status --porcelain`(저장소 루트) 확인 결과 `QA.md`·`docs/agents/verification-log.md`
(이 항목)만 변경. `projects/nok`은 무변경.

### 판정
**조건부 통과(Pass with follow-up)** — ⑥ i18n 밖 3파일 en 전환은 en/ko 두 언어 모두
실제 GUI에서 텍스트 깨짐·KeyError 없이 정상 동작 확인(핵심 목표 100% 달성). ⑦ 팔레트
정규화 중 보조 텍스트 색상(`#9ca3af`/`#e5e7eb`) 교체는 육안상 자연스럽게 어울림을
확인했으나, CUDA 배너 좌측 보더는 새로 발견된 BUG-015(P2, 시각적 결함이나 기능 크래시
없음)로 인해 의도한 결과물과 차이가 있음. 데이터 손실·크래시·기능 회귀가 없어 이번
라운드 자체는 통과로 판정하되, BUG-015는 후속 라운드에서 수정 필요.
**이 라운드 통과로 Artifact 7876ed3e "디자인 톤 홀리스틱 재검토" 7단계 실행안
(①~⑦) 전체가 구현+검증 완료 상태가 되었다** — 단, BUG-015(P2)가 Open 이슈로 남음.

---

## 2026-08-21 — BUG-015 재검증 (CUDA 배너 좌측 보더 이중 렌더링 수정 확인)

커밋 `142d251`(fix) 검증. 디자인 7단계 실행안 전체 재검증은 이미 통과했으므로 이번
라운드는 BUG-015 하나로 범위를 좁힘. 수정 내용: `banner.setObjectName("cudaBanner")`
추가 + `_build_cuda_banner()`/`_on_cuda_diag_done()`의 스타일시트 3곳을
`"QWidget#cudaBanner { ... }"` ID 선택자로 스코핑(자식 QLabel로의 서브트리 전파 차단).

### 정적 검토
`app/tabs/training_tab.py` 107~162행 직접 확인 — `objectName("cudaBanner")` 설정과
`_build_cuda_banner()` 초기 스타일, `_on_cuda_diag_done()`의 성공(`#10b981`)/실패
(`#f87171`) 두 분기 스타일시트 전부 `QWidget#cudaBanner { ... }` 패턴으로 일관되게
수정됨을 확인. 세 곳 모두 동일 패턴이라 실패 분기도 성공 분기와 대칭적으로 고쳐졌음이
코드만으로 확인됨.

### 실행 확인 — 실제 `TrainingTab` 인스턴스 픽셀 스캔
`python main.py`(anaconda 인터프리터, 실 GUI 모드)로 앱이 정상 기동함을 먼저 확인
(575MB 메모리로 살아있는 프로세스, cp949 로깅 경고만 출력되는 기존 이슈는 이번 라운드와
무관). 이어서 스크래치 스크립트(`verify_bug015.py`, 프로젝트에 추가 안 함)로 실제
`TrainingTab()`을 생성해 `_on_cuda_diag_done()`을 성공/실패 두 `CudaDiagResult`로 직접
호출한 뒤 `banner.grab()` → `QImage.pixelColor()`로 픽셀 스캔:

- 텍스트 baseline과 겹치는 y=16 행에서는 라벨 글자("C" 시작 부분) 안티앨리어싱이 섞여
  들어와 처음엔 오탐 여지가 있었음 — 배너 상/하단 근처(y=1,3,5,28,30, 텍스트 미겹침
  구간)로 스캔 행을 바꿔 재측정.
- 성공 상태: x=0~2에 `#10b981`(16,185,129) 단일 3px 보더만 존재, x=3부터 x=19까지는
  배경색 `#1f2329`(31,35,41)로 완전히 균일. 실패 상태: 동일 위치에 `#f87171`(248,113,113)
  단일 보더, 이후 균일 배경. **이전 발견됐던 x≈10~12의 두 번째 막대가 두 상태 모두에서
  완전히 사라짐** — 이중 렌더링 재현 안 됨.
- 배경색(`#1f2329`)·모서리 둥글기(코너 부근 x=3 행에서 안티앨리어싱 블렌드만 있고
  별도 막대 없음, `border-radius:4px` 정상 유지) 확인.
- 자식 위젯 geometry 확인: 라벨 `QRect(10, 0, 486, 32)`, 버튼 `QRect(504, 5, 66, 22)` —
  이전 커밋과 비교해 밀리거나 잘린 흔적 없음(레이아웃 margin/spacing 변경이 없었으므로
  예상대로). 라벨 텍스트("CUDA RTX 5060" / "CUDA 사용 불가 | 드라이버 미설치")와 "진단
  보기" 버튼 모두 정상 표시, 버튼 `enabled=True`.
- 전체 창 스크린샷(`fullwindow_success.png`/`fullwindow_fail.png`)으로도 배너가 학습
  큐/손실 그래프 등 나머지 레이아웃과 자연스럽게 어울리며 다른 요소를 밀어내지 않음을
  육안 확인.

실패(빨강) 상태는 이 세션 실제 GPU(CUDA 사용 가능) 환경이라 자연 발생은 안 됐지만,
`CudaDiagResult(cuda_available=False, ...)`를 직접 주입해 실제 코드 경로
(`_on_cuda_diag_done()`의 else 분기)를 그대로 태워 확인했으므로 코드 확인만으로 갈음하지
않고 실측했음.

### 환경 메모 (이번 라운드와 무관, 참고용)
스크립트를 PyQt6 → `app.tabs.training_tab` 순서로 단순 임포트하면 `QtSvg` DLL 로딩이
실패하는 현상을 재현(5회 연속 재현, `app.core.trainer`가 끌어오는 cv2/torch 등이 먼저
로드된 뒤 QtSvg를 임포트하면 실패). `main.py`가 이미 `_preload_libs()`로 numpy/cv2/
PIL.Image/torch/matplotlib를 PyQt6보다 먼저 로드하는 방어 로직을 갖고 있는 걸 확인했고,
스크립트에도 동일 순서를 적용하니 재현되지 않음 — 기존에 알려진 환경 플레이키니스
(BUG-001과 같은 계열의 DLL 로드 순서 문제)이지 이번 커밋(`142d251`)이 만든 회귀 아님.
새 버그로 등록하지 않음.

### 판정
**통과(Pass)** — BUG-015가 의도한 대로 수정됨. 좌측 보더가 이제 성공/실패 두 상태 모두
단일 3px 선으로만 렌더링되고, 배경·모서리·라벨·버튼 등 다른 요소는 회귀 없음. QA.md
BUG-015 항목에 재검증 완료 반영.

---

## 2026-08-21 — 버그 일괄정리 6건 재검증 (BUG-003/BUG-005/BUG-006/BUG-009/BUG-010/BUG-014)

커밋 `251608e`(BUG-003/BUG-014, BUG-009/BUG-010 코드 병합됨 — git race), `5af01ed`+`e8f1d7c`
(BUG-005), `7e95ee0`(BUG-006). 구현 에이전트들이 대부분 정적 검토(`py_compile`, 단위 스크립트)만
했던 6건을 대상으로, `QT_QPA_PLATFORM=offscreen` + `QTest`로 실제 프로덕션 위젯에 마우스/키보드
이벤트를 주입해 검증(로직 재구현이 아니라 실제 이벤트 핸들러 경유 확인). 스크립트는 전부
스크래치 디렉토리(`.../scratchpad/verify_canvas.py`, `verify_inference.py`, `verify_browser.py`,
`verify_model_tab.py`, `verify_boot.py`)에만 작성, 프로젝트에 추가하지 않음. 인터프리터:
`C:\Users\Feel\anaconda3\python.exe`.

### BUG-003 — Select 도구로 캔버스 밖까지 드래그 시 유령 어노테이션
`AnnotationCanvas` 단독 인스턴스에 `projects/nok/images/10번.bmp` 로드 → `QTest.mousePress/
mouseMove/mouseRelease`로 브러시 도구 실제 스트로크 2회(진짜 `mousePressEvent`→
`_paint_circle`→`_finish_brush` 경유, mask pixel count=3767) → Select 도구로 전환 후 첫 스트로크를
클릭 선택 → 같은 지점에서 press 후 위젯 경계 밖(가상 좌표 +5000,+5000)까지 실제 드래그 이벤트로
이동 → release. 결과: `canvas._annotations`에 `mask.any()==False`인 brush_mask 없음(0건),
`canvas._selected_ids`에서도 제거됨 확인. **통과**.

### BUG-014 — undo deepcopy MemoryError 가드
`git show 251608e -- app/widgets/annotation_canvas.py` diff 직접 검토 — `_push_undo()`의
`copy.deepcopy(self._annotations)` 호출이 정확히 `try/except MemoryError`로 감싸져 있고, 실패 시
`app.core.logger`로 경고 후 `return`(스택 미추가, 호출부는 계속 진행)함을 확인. 실제 OOM 재현은
이 환경에서 시도하지 않음(과거 구현자가 실측 재현했다는 보고를 신뢰, 이번 라운드는 구조 확인 +
회귀 확인으로 범위 한정 — 작업 지시와 일치). 회귀: 위 BUG-003 스크립트 내에서 두 번째 브러시
스트로크 후 `canvas.undo()`(정상 범위)를 실제 호출해 어노테이션 2개→1개로 정상 복귀, undo 스택
깊이도 정상 — **회귀 없음, 통과**.

### BUG-009 — 추론 탭 검색 필터 해제 시 카운터 미갱신
`InferenceTab()` 단독 인스턴스 + 임시 폴더(루트 이미지 1장 + 하위 폴더 2개에 각 1장, 총 3장)를
`img_list.load_folder()`로 로드. `QTest.keyClicks(search_edit, "child_a")` 후 디바운스 타이머
`timeout` 강제 발화(200ms 대기와 동일 결과) → 카운터 "1 / 1"로 정정 확인 → `search_edit.clear()`
후 디바운스 재발화 → **"다음" 버튼 누르지 않고도** 카운터가 즉시 "1 / 3"으로 정정됨을 확인
(`tab._img_list.display_changed.connect(tab._update_nav_label)` 배선이 실제로 동작). **통과**.

### BUG-010 — 추론 탭 트리 펼침/접힘 화살표
`app.widgets.inference_image_list._TREE_STYLE`에 `QTreeWidget::branch` 규칙이 더 이상 없음을
런타임에서 직접 import해 확인(diff 리뷰와 별개로 실제 로드된 모듈 상수 재확인). 정렬을 "폴더"로
전환해 하위 폴더가 있는 항목(`sub1`, childCount=1)이 기본 펼침 상태임을 확인 후
`setExpanded(False)/(True)` 토글 정상 동작 확인. 추가로 트리 좌측 인디케이터 영역
(`QTest.mouseClick(tree.viewport(), pos=(x=3, row-center-y))`)을 실제 클릭해 `isExpanded()`가
`True→False`로 토글됨을 확인 — 클릭 상호작용 자체는 정상. **한계**: 이 offscreen 헤드리스
환경에서는 화살표 아이콘이 실제로 "보이는지"(픽셀 렌더링)까지는 직접 육안 확인하지 못함 —
`QTreeWidget::branch { background: ... }` 규칙이 Qt 기본 화살표 렌더링을 억제한다는 것은 Qt의
잘 알려진 동작이고, 해당 규칙 자체가 정확히 삭제됐음을 코드/런타임 양쪽에서 확인했으므로 원인
제거는 확실하나 픽셀 단위 시각 확인은 사용자 환경에서의 육안 재확인을 권장. **조건부 통과**
(메커니즘 확인 완료, 최종 시각 확인은 권장 사항으로 남김).

### BUG-005 — image_browser.py 폴더 그룹핑 죽은 코드 제거
`projects/nok`을 스크래치로 복사(원본 무변경, 실행 후 `git status --short -- projects/nok` 공백
확인)한 프로젝트를 열어 `ImageBrowser()` 실제 인스턴스화. 정렬 콤보 항목이 정확히
`['파일명 ↑', '파일명 ↓', '완료↑', '미완료↑']` 4개뿐(폴더 옵션 없음, 의도된 변경) 확인,
`_SORT_MODE_KEYS`에도 `"folder"` 없음 확인, `t("browser.sort.folder")` 키 삭제 확인. 회귀
확인 — 4개 정렬 모드 전환 예외 없음, `QTest.keyClicks`로 검색 "10" 입력(디바운스 발화) 시
"10번.bmp" 1건만 필터링되고 해제 시 5장 전체 복원, 이미지 파일을 직접 복사해 넣고
`reload()` 호출 시 브라우저에 나타남/삭제 후 사라짐 확인, `refresh_item()`이 예외 없이
동작 확인. **통과**.

### BUG-006 — 모델 검증기/로더 정책 불일치
`ModelTab()` 실제 인스턴스화 → 에디터에 `import random` + 유효한 `nn.Module`(forward 포함)
코드 입력 → `QTest.mouseClick(btn_validate)` 실제 클릭 → `_lbl_status.text() == "✗ 검증 실패"`,
`_btn_load.isEnabled() == False` 확인. 회귀 — 허용 모듈만 쓰는 실제 프리셋(`simple_unet`)
코드로 동일하게 검증 버튼 클릭 시 `"✓ SimpleUNet"` + 로드 버튼 활성화, 이어서
`QTest.mouseClick(btn_load)`로 실제 로드까지 성공(`7,763,074 params`) 확인. `model_validator.
validate()`의 `result.ok = len(result.errors) == 0`이 `_check_imports()` 등 전체 검사 이후에
계산됨을 코드로 재확인해, errors로 옮긴 이번 수정이 `ok` 계산에 정상 반영됨(타이밍 버그 없음)도
확인. **통과**.

### 종합 회귀 — 전체 앱 부팅
`QApplication` → `projects/nok` 오픈 → `MainWindow()`(라벨링/모델/학습/추론 4개 탭 전부 구성,
이번 라운드가 건드린 `annotation_canvas.py`/`image_browser.py`/`inference_tab.py`/
`inference_image_list.py`/`model_validator.py` 전부 로드) → `show()`까지 예외 없이 통과.
(중간에 출력 버퍼링 문제로 `QtSvg` DLL 에러처럼 보이는 거짓 실패가 1회 있었으나, `-u`
플래그로 stdout 버퍼링을 끄고 재실행하니 재현되지 않음 — 실제로는 파이프/tail 조합에서
프로세스가 죽어 보인 것이지 진짜 DLL 실패가 아니었음. 앞선 BUG-015 검증 로그에 기록된
"import 순서에 따른 QtSvg DLL 플레이키니스"와도 무관 — `main.py`와 동일하게 PyQt6 계열을
먼저 import한 순서였음.) 프로세스 종료 코드 127은 기존 검증 로그(R1~R6, BUG-015 등)에
반복 기록된 것과 동일한 비대화형 offscreen 환경의 알려진 노이즈로, 회귀 아님.

### 판정
6건 전부 **통과**(BUG-010만 "메커니즘 확인 완료 + 최종 시각 확인 권장"의 조건부 통과, 나머지
5건은 완전 통과). 새로운 버그 발견 없음. `QA.md` Closed Issues 6개 항목에 "재검증 완료" 반영.

### 비고
`projects/nok/`은 읽기 전용으로만 사용(BUG-003/BUG-014 스크립트는 스크래치 프로젝트를 별도로
쓰지 않고 `AnnotationCanvas` 단독 인스턴스라 애초에 저장 로직을 타지 않음), BUG-005/BUG-006
스크립트는 각각 스크래치 사본 프로젝트를 사용해 원본 무변경. 세션 종료 시 `git status --short`
로 `projects/nok` 등 실데이터 무변경 재확인.

---

## 2026-08-24 — Windows exe + Inno Setup 인스톨러 빌드 검증 (커밋 `f3c5377`)

### 배경
구현 에이전트가 만든 `build.spec`(PyInstaller onedir)/`installer/setup.iss`(Inno Setup)/
`build.bat`을 실제로 실행해 exe·installer가 진짜로 빌드·설치·구동되는지 확인. 정적 리뷰만으로는
"완료"로 간주하지 말라는 지시에 따라 전 과정을 직접 실행.

### 환경 이슈 — D: 드라이브 공간 부족 (코드 버그 아님)
`build.bat`을 그대로 실행하니 `py -3 -m PyInstaller build.spec` 도중
`OSError: [Errno 28] No space left on device`로 실패. `df -h` 확인 결과 `D:` 드라이브가 이미
390G/391G 사용 중(가용 1.8MB, 이번 빌드 시도로 생긴 것과 무관하게 이 프로젝트 외 다른 데이터로
이미 거의 가득 참) — `C:` 드라이브도 4.6GB만 가용. `E:` 드라이브(3.2TB 가용)로 `--distpath`/
`--workpath`(PyInstaller)와 `OutputDir`/`MyDistDir`(Inno Setup, 검증용 임시 사본 스크립트 사용,
저장소의 `installer/setup.iss` 원본은 손대지 않음)를 우회 지정해 실제 빌드를 완주시킴.
**이 이슈는 build.spec/setup.iss/build.bat 자체의 결함이 아니라 이 dev 머신의 D: 드라이브가
이 프로젝트와 무관하게 이미 거의 가득 차 있던 상태 때문** — 사용자 환경에 따라 재발 가능하니
리더에게 별도 보고(D: 드라이브 정리 필요 여부 사용자 확인 권장).

### 환경 이슈 — 이 자동화 셸(Git Bash)에서 `cmd.exe /c "<cmd>"` 인자가 소실됨 (검증 셸의 특성, 앱 버그 아님)
`build.bat`을 `./build.bat`/`cmd.exe /c build.bat`로 직접 실행하면 `/c` 뒤 인자가 스킵되고
`cmd.exe`가 그냥 인터랙티브 배너만 찍고 아무 것도 실행하지 않음(`MSYS_NO_PATHCONV=1`을 줘도
동일) — MSYS/Git-Bash의 `/`-경로 자동변환이 `cmd /c`류 스위치까지 오염시키는 것으로 추정.
같은 이유로 `SegmentationModelUI-Setup-*.exe /VERYSILENT /SUPPRESSMSGBOXES ...`처럼 `=` 없는
슬래시 스위치도 최초 시도에서 `"C:/Program Files/Git/VERYSILENT"`로 뭉개져 무인설치 모드가
아니라 GUI 모드로 떠버렸음(설치 자체는 성공, 다음 검증에서 `MSYS_NO_PATHCONV=1` + 프로세스 직접
실행으로 재시도해 정상 무인설치 확인). **다음 검증 에이전트를 위한 메모**: 이 환경에서
Windows 배치파일/무인설치 스위치를 실행할 땐 `MSYS_NO_PATHCONV=1`을 반드시 같이 주고, `cmd.exe
/c`류 래퍼보다 PyInstaller/ISCC/설치 exe를 직접 실행하는 편이 안전하다.

### 실행 결과 — PyInstaller 빌드
- `py -3 -m PyInstaller build.spec`(E: 드라이브로 출력 우회) **성공** — 총 170초.
- `SegmentationModelUI.exe` 생성 확인(51MB), `dist/` 전체 4.5GB(CUDA torch 포함, onedir 특성상
  예상 범위).
- `warn-build.txt`(744줄) 전수 확인 — `app.*`/`cv2`/`torchvision`/`albumentations` 관련
  "not found" 경고 **0건**. 실제 "Hidden import ... not found!" 경고는 `scipy._lib.array_api_
  compat.numpy.fft`, `scipy.special._cdflib` 2건뿐이며 둘 다 scipy 내부 optional 서브모듈(이
  앱의 augmentation 파이프라인이 실제로 쓰는 경로 아님)이라 무해. 나머지 "missing module"
  목록도 전부 pydantic 선택적 hub 기능, torchvision 데이터셋 로더(coco/lsun/pcam 등 이 앱이
  안 쓰는 것들), scipy.stats 내부 폴백 심볼 등 실제 우리 코드 경로 밖의 선택적 의존성.
  → **리더 보고 사항 해소 확인**: implementation-log가 우려했던 "albumentations/opencv-python-
  headless 로컬 미설치" 문제는 리더가 이번 세션 직전에 두 패키지를 직접 설치해 이미 해결된
  상태였고, 이번 빌드에서 실제로 정상 번들됨을 재확인.
- `app/model_presets/*.py`(코드 아닌 데이터로 필요), `app/resources/icons/*.svg` 모두
  `_internal/app/...` 밑에 정상 포함 확인.

### 실행 결과 — exe 기동
- `dist/SegmentationModelUI/SegmentationModelUI.exe` 직접 실행 → 프로세스 정상 기동, 메모리
  ~596MB(CUDA torch 로드 반영), `Get-Process ... | Select Responding` **True**.
- PowerShell + `System.Drawing`으로 실제 스크린샷 캡처 — "Segmentation Model UI" 프로젝트
  선택 다이얼로그("새 프로젝트"/"프로젝트 열기"/"가져오기...", 최근 프로젝트 없음)가 한글
  깨짐 없이 정상 렌더링됨을 육안 확인(스크린샷 파일: 검증 세션 스크래치 디렉토리
  `screenshot3.png`, 프로젝트에는 추가 안 함).
- `data/logs/app.log`: 기동 로그(Python/PyTorch/CUDA 버전, GPU 정보) 정상 기록, 예외 없음.
  `data/logs/errors.log`: **비어있음** — 크래시·예외 0건.
- 콘솔(`sys.stdout`)로 유니코드 em-dash(`—`)가 cp949로 인코딩 안 되는 `UnicodeEncodeError`가
  발생했으나, 이는 **검증 목적으로 exe의 stdout을 파일로 강제 리다이렉트했을 때만 나타나는
  현상**이다 — 코드 확인 결과 `logging.StreamHandler.__init__`은 `stream=None`이면 자동으로
  `sys.stderr`로 폴백하고, `Handler.handleError()`도 `sys.stderr`가 falsy(windowed 빌드에서
  리다이렉트 없이 실행 시 `sys.stdout`/`sys.stderr`가 `None`이 되는 PyInstaller 표준 동작)면
  아예 출력을 시도하지 않아 실사용(더블클릭 실행)에서는 크래시도 노출도 되지 않음 — 실버그
  아님, QA.md 미등록.
- **참고(코드 확인만, 실패 재현은 아님)**: `app/core/logger.py`의 `LOG_DIR = Path("data/logs")`
  는 `sys.executable` 기준이 아니라 CWD 기준 상대경로다. `main.py:ensure_data_dirs()`/
  `app/core/project.py:_app_root()`는 이번 라운드에서 frozen 분기로 고쳐졌지만 `logger.py`는
  그대로다 — implementation-log가 이미 인지하고 "Inno Setup 바로가기에 `WorkingDir: {app}`을
  명시했으니 문제없다"고 판단한 부분. 이번 검증에서 dist 폴더 직접 실행(exe 자체 더블클릭과
  동일하게 CWD=exe 폴더)과 설치 후 실행 두 경우 모두 실제로 `data/logs/app.log`가 앱 설치
  폴더 밑에 정확히 생성됨을 실측 확인 — 설계대로 동작. 다만 향후 만약 사용자가 다른 CWD에서
  단축키/스크립트로 exe를 실행하는 특이 경로가 생기면 로그 위치가 어긋날 수 있는 잠재
  리스크는 여전히 남아있음(발생 조건이 지금은 없어 QA.md 미등록, 참고용 기록만 남김).

### 실행 결과 — Inno Setup 인스톨러
- ISCC 컴파일(E: 드라이브 경로로 우회) **성공**(517초) — `SegmentationModelUI-Setup-1.6.0.exe`
  생성(1.81GB).
- **무인 설치**(`/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR=...`) 성공 — 로그(`install_log2.
  txt`) 확인: `User privileges: None`(관리자 권한 요구 없음, `PrivilegesRequired=lowest` 설계
  대로 동작), `Install mode root key: HKEY_CURRENT_USER`(per-user 설치), `Installation process
  succeeded`, Start Menu 바로가기 2개(`Segmentation Model UI.lnk`, `... 제거.lnk`) 생성 확인.
- 설치된 경로에서 exe 재실행 → 정상 기동(프로젝트 다이얼로그 응답, `data/logs/app.log`에 새
  기동 기록 추가됨 확인) — **설치 폴더에 대한 쓰기 권한 정상**(관리자 권한 없이 로그/데이터
  쓰기 가능, `PrivilegesRequired=lowest` 선택이 실제로 유효함을 실측 확인).
- **무인 제거**(`unins000.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART`) 성공 — 로그에
  `Uninstallation process succeeded`, `Removed all? Yes`. 설치 디렉토리와 Start Menu 바로가기
  폴더 모두 완전히 삭제됨을 `ls` 재확인(No such file or directory).

### 정리
검증에 사용한 모든 산출물(exe/installer/설치본)은 `E:\pyi_build_scratch\` 스크래치 디렉토리
및 임시 인스톨 경로에서만 생성·삭제했고, 저장소(`D:\segmentation model`)에는 `dist/`·`build/`
잔여물이 없음을 `git status`(clean)로 재확인. `installer/setup.iss` 원본은 검증 중 한 번도
직접 수정하지 않음(임시 사본만 스크래치 디렉토리에서 사용).

### 판정
**통과**. `build.spec`/`installer/setup.iss`/`build.bat`가 의도한 대로 동작함을 실제 빌드→설치
→기동→제거 전 과정으로 확인. 코드 버그 신규 발견 없음(QA.md 변경 없음). 발견한 두 가지는
모두 이 dev 머신/자동화 셸의 환경 특성(D: 드라이브 공간 부족, Git Bash의 `cmd /c` 인자 소실)
이지 코드 결함이 아니므로 리더에게 별도 보고만 하고 QA.md에는 등록하지 않음.

---

## 2026-08-24 — "Vertex Frame" 앱 아이콘 실행 확인 (커밋 d0d0b30)

### 배경
구현 에이전트가 `app/resources/logo.svg` + `app/resources/app_icon.ico`(멀티 해상도)를
만들고 `main.py`(`QApplication.setWindowIcon`), `build.spec`(EXE `icon=`), `installer/setup.iss`
(`SetupIconFile`)에 적용. 구현 로그가 실제 앱 구동 확인은 검증 에이전트에게 명시적으로
위임해둔 상태.

### 검증 1 — ICO 파일 유효성
- `py -3`으로 `PIL.Image.open('app/resources/app_icon.ico')` 후 `info['sizes']`를 확인:
  `{(16,16),(32,32),(48,48),(256,256)}` 4개 프레임 모두 존재. 각 크기를 `im.size = (w,h); im.load()`로
  개별 로드해 16/32/48/256 전부 정상 디코딩됨을 확인 — 구현 로그가 주장한 "이전 시도는
  16×16 1프레임만 저장되는 버그가 있었고 이번엔 고쳤다"는 내용이 실측으로 재확인됨.

### 검증 2 — 타이틀바 아이콘 실 렌더링
- `py -3 main.py`로 앱을 백그라운드 구동(cwd: 프로젝트 루트, `Path(__file__)` 기준 상대 경로
  그대로 사용 — 사용자가 명시한 실행 방법과 동일 조건).
- `ProjectStartDialog`("프로젝트" 창)가 뜬 상태에서 전체 화면 스크린샷 후 타이틀바 아이콘
  영역을 나침 확대(nearest-neighbor 400×400 업스케일) — 기본 Qt 회색 아이콘이 아니라 프레임
  코너 마크 + 초록/파랑 폴리곤 꼭짓점 점들로 구성된 커스텀 "Vertex Frame" 로고가 선명하게
  렌더링됨을 육안 확인.
- 스크린샷: 원본 `screen1.png`, 확대본 `titlebar_zoom.png`
  (스크래치패드: `C:\Users\Feel\AppData\Local\Temp\claude\d--segmentation-model\185caeb5-815b-47f3-a579-7a735d844a98\scratchpad\`).

### 검증 3 — 작업표시줄(taskbar) 아이콘
- 화면 taskbar 스트립을 스크린샷으로 확인한 결과, 눈으로 짚은 위치의 아이콘은 파이썬
  런처/터미널 아이콘으로 보여 육안으로는 판별이 애매했음(다른 고정 아이콘과 섞여 있어
  실행 중인 우리 앱 버튼인지 확신 불가 — Windows 11 taskbar hover 미리보기는
  `SetCursorPos`만으로는 트리거되지 않아 실제 마우스 이동 이벤트 없이는 스크린샷으로 특정이
  어려웠음).
- 대신 Win32 API를 직접 호출해(`EnumWindows`로 해당 프로세스(PID)의 최상위 가시 윈도우
  hwnd를 찾고 `SendMessage(hwnd, WM_GETICON, ICON_BIG, 0)`) 그 윈도우에 실제로 바인딩된
  32×32 큰 아이콘 핸들을 추출, `Icon.FromHandle().ToBitmap()`으로 PNG 저장해 확인한 결과
  타이틀바에서 본 것과 동일한 "Vertex Frame" 로고였음(`window_big_icon.png`). `WM_GETICON`의
  `ICON_BIG`은 Windows 작업표시줄이 실행 중 창 버튼에 사용하는 것과 동일한 아이콘 소스이므로,
  taskbar에도 커스텀 로고가 정상 반영된다고 판단(육안 taskbar 스크린샷으로 100% 확정하지는
  못했으나 API 레벨 근거로 충분히 신뢰 가능).

### 검증 4 — 로그 확인
- `data/logs/app.log` 최신 항목(`2026-08-24 14:31:18` 기동)에 아이콘 로드 관련 에러 없음.
- `data/logs/errors.log`에 이번 실행 관련 항목 없음(마지막 기록은 2026-08-20, 무관한
  구 버그 — `image_browser.py` `unhashable QTreeWidgetItem`, 이미 QA.md에서 별도 추적 중인
  건과 무관하게 오래된 로그로 이번 라운드와 무관).
- `main.py`의 `icon_path = Path(__file__).resolve().parent / "app" / "resources" / "app_icon.ico"`가
  `py -3 main.py`를 프로젝트 루트에서 실행한 조건에서 정상적으로 파일을 찾아 로드함을 실제
  타이틀바 렌더링 결과로 간접 확인(경로 관련 예외/조용한 스킵 로그 없음).

### 검증 5 — build.spec / installer/setup.iss 정적 대조
- `build.spec:51` `datas`에 `("app/resources/app_icon.ico", "app/resources")`,
  `build.spec:87` `EXE(...)`에 `icon="app/resources/app_icon.ico"` — 실제 파일 존재 경로와 일치.
- `installer/setup.iss:33` `SetupIconFile={#MyDistDir}\app\resources\app_icon.ico` —
  `#define MyDistDir "..\dist\SegmentationModelUI"`(9행)과 `build.spec`의 datas 배치 대상 경로가
  일치해 PyInstaller onedir 산출물 구조와 맞음. 문법·경로 모두 이상 없음.
- 전체 PyInstaller 재빌드(CUDA torch 포함 20~30분)는 지시대로 이번 라운드에서 강제하지
  않음 — 다음에 사용자가 `build.bat`을 돌릴 때 exe/설치 프로그램 아이콘이 자연히 검증됨.

### 검증 6 — 로고 자산 분리
- `app/widgets/icons.py` 등 `app/` 전체에서 `logo.svg`/`app_icon.ico`를 참조하는 코드가
  없음을 grep으로 확인 — `currentColor` 재색상 아이콘 세트(`app/resources/icons/`)와 물리적으로
  분리돼 있다는 구현 에이전트 주장이 사실과 일치.

### 발견한 문제
없음. 코드 수정 불필요.

### 판정
**통과**. ICO 4프레임 정상, 타이틀바에 커스텀 로고 실 렌더링 육안 확인, 작업표시줄은
`WM_GETICON(ICON_BIG)` API 레벨 확인으로 대체(육안 taskbar 스크린샷은 인접 고정 아이콘과
혼동돼 확정 못함 — 필요시 다음 라운드에서 실제 hover 스크린샷 재시도 가능), 로그 무오류,
build.spec/setup.iss 경로 정적 대조 일치, 로고 자산 분리 확인. QA.md 신규 등록 없음.

## 2026-08-24 — build.bat 재빌드 검증 이어서 마무리 + 오프라인 설치/구동 테스트

### 배경 · 중단 상황 수습
직전 턴에서 "백그라운드 build.bat 작업이 끝나면 이어서 확인하겠다"고 말한 뒤 실제로는
알림을 받지 못한 채(자신이 시작한 백그라운드 프로세스는 별도 알림이 오지 않음) 턴이
끊겼음을 리더가 지적, 이어서 직접 상태 확인·완주하라는 재지시를 받아 재개.

재개 시점에 확인한 것: `installer\output\SegmentationModelUI-Setup-1.6.0.exe`가 이미
1.9GB로 존재했으나 `ISCC.exe` 프로세스가 여전히 그 파일에 계속 쓰는 중(두 번의 `ls` 사이
파일 크기가 계속 증가)이었음 — 아직 안 끝난 상태였음. `until` 루프로 ISCC 프로세스 종료를
기다려 최초 빌드(`build_log3.txt`, EXITCODE=0, "Successful compile")는 완료 확인.

### 환경 충돌 — 동시 실행 중이던 다른 검증 에이전트와의 레이스
스크래치 디렉토리에 이미 이번 라운드의 이전 작업 흔적(아이콘 자산화 `design-logo/`, exe
단독 실행 로그, 1차 install/uninstall 테스트 로그, 3회의 `build_log*.txt`)이 남아있어
조사해보니: 1차 시도(`build_log.txt`)는 `installer/setup.iss:36`의 `SetupIconFile=
{#MyDistDir}\app\resources\app_icon.ico` 경로가 실제 PyInstaller onedir 빌드 후 산출물
구조(datas가 `_internal\` 밑으로 들어감)와 안 맞아 ISCC가 아이콘 파일을 못 찾고 컴파일
중단(이전 라운드 "Vertex Frame 아이콘 검증"에서 이 줄을 정적으로만 확인하고 "이상 없음"
판정했던 것이 실제 빌드에서는 깨졌던 것 — 정적 검토의 한계를 보여주는 사례). 이 문제는
이미 수정되어(`SetupIconFile=..\app\resources\app_icon.ico`, 저장소 경로 직접 참조) 이번
재개 시점엔 커밋 `fa0d05e`로 반영돼 있었음.

재개 후 설치→실행 테스트 도중, 갑자기 `dist\`·`installer\output\` 전체와 설치했던
`C:\Users\Feel\AppData\Local\Programs\SegmentationModelUI\`가 통째로 사라지는 현상 발생
— 조사 결과 **동시에 같은 저장소에서 별도의 검증 에이전트가 병행 실행 중**이었고(IDE
화면 캡처에 그 세션의 Bash/Write 작업 로그가 실시간으로 보임), 그 세션이 자체적으로
`build.bat`(clean 단계에서 `dist\` 삭제)나 별도 uninstall을 실행해 내가 만든 산출물과
경쟁·충돌한 것으로 판단됨. 리더에게 즉시 보고했고 **리더가 해당 중복 에이전트를
중지시킴** — 이후로는 나 혼자 처음부터 다시(clean rebuild) 진행해 신뢰할 수 있는 결과를
확보.

### 재빌드 실행 결과
- `build.bat`을 `.bat` 래퍼 파일로 감싸 `run_in_background`로 재실행(직접 `cmd.exe /c
  "build.bat > log 2>&1"`류 중첩 따옴표는 재현성 없이 실패 — 이전 라운드가 남긴
  "Git Bash에서 `cmd /c` 인자가 소실될 수 있다" 경고와 일치하는 증상. `.bat` 파일을 만들어
  Git Bash가 직접 실행하고 `>` 리다이렉트도 Bash 쪽에서 거는 방식이 안정적이었음).
- PyInstaller 빌드 성공(`SegmentationModelUI.exe` 51MB, `dist/` 정상 생성).
- ISCC 컴파일 성공(536.7초) — `installer\output\SegmentationModelUI-Setup-1.6.0.exe`
  1.9GB 생성.
- 빌드 로그 경고 전수 확인: `scipy._lib.array_api_compat.numpy.fft`/`scipy.special.
  _cdflib` hidden-import 미발견 2건(앱 미사용 scipy 선택적 서브모듈), `torch.utils.
  tensorboard` 서브모듈 수집 실패(tensorboard 미설치 — 앱이 안 씀), `torch.distributed.*`
  Deprecation/SyntaxWarning 몇 건(torch/sympy 내부, 앱 코드 무관) — 전부 이전 라운드와
  동일하게 무해함 확인. `app.*` 관련 "not found" 경고 0건.

### 실행 결과 — exe 기동 + 아이콘
- `dist\SegmentationModelUI\SegmentationModelUI.exe` 직접 실행 → 정상 기동, PowerShell
  Win32 API(`SetForegroundWindow`+`GetWindowRect`)로 앱 창만 정밀 캡처 후 확대 → 타이틀바
  아이콘에 "Vertex Frame" 로고(사각 프레임 + 청록 육각형 점 패턴)가 선명하게 렌더링됨을
  육안 확인(`verify_titlebar_zoom.png`). 작업표시줄 아이콘도 동일 로고로 확대 캡처
  확인(`verify_taskbar_zoom.png`) — 지난 라운드엔 API 레벨로만 간접 확인했던 taskbar
  아이콘을 이번엔 실제 스크린샷 확대로 직접 확인 완료.

### 실행 결과 — Inno Setup 무인 설치/제거
- 무인 설치(`/VERYSILENT /SUPPRESSMSGBOXES /NORESTART`, 직접 exe 실행 + `MSYS_NO_
  PATHCONV=1` — `cmd.exe /c` 래퍼는 인자 소실로 실패함을 재확인) 성공. 로그: `User
  privileges: None`, `Install mode root key: HKEY_CURRENT_USER`(관리자 권한 불필요,
  per-user 설치 설계대로 동작), `Installation process succeeded`.
- 설치된 exe를 Start Menu 바로가기와 동일한 조건(`WorkingDir={app}`)으로 실행 → 정상
  기동, `data\logs\app.log`에 기동 로그 정상 기록(GPU: RTX 5060, CUDA 12.8, cuDNN 91900,
  예외 없음). *(참고: 처음엔 Git Bash 현재 디렉터리(저장소 루트)에서 그대로 실행해
  `data/logs/app.log`가 설치 폴더가 아닌 저장소 쪽에 생겼음 — 이는 `logger.py`의
  `LOG_DIR = Path("data/logs")`가 CWD 기준이라는, 이전 라운드에 이미 "실사용 경로엔
  문제없음"으로 기록된 알려진 특성을 검증 셸에서 재현한 것일 뿐, 새 버그 아님. CWD를
  설치 폴더로 맞춰 재실행하니 정상적으로 설치 폴더 밑에 로그 생성됨을 재확인.)*
- 무인 제거(`unins000.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART`) 실행 → 로그상
  `Uninstallation process succeeded`, `Removed all? Yes`이지만 실제로는 설치 폴더와
  `data\logs\`(런타임 생성 로그 2개)가 남음 — **기존 QA.md BUG-016과 동일 재현**(신규
  등록 안 함). 검증 후 잔여 폴더는 직접 삭제해 머신 정리.

### 오프라인 설치/구동 가능 여부 검증 (코디네이터 추가 지시)
**실제 네트워크 차단 시도는 권한 문제로 불가**: 관리자 권한 없음(`IsInRole(Administrator)`
= False 확인) + `Disable-NetAdapter`/`New-NetFirewallRule` 둘 다 Claude Code 세이프티
분류기가 "시스템 레벨 네트워크 설정 변경"으로 차단(권한 요청 자체가 거부됨, 우회 시도
안 함). 대신 다음 방법으로 대체 검증:

1. **`installer\setup.iss` 정적 확인**: `[Files]` 섹션이 `Source: "{#MyDistDir}\*"`로
   로컬 `dist\` 산출물만 복사(`grep`으로 `http`/`Download` 계열 지시문 0건 확인) — 인스톨러
   자체는 100% 로컬 파일 복사만 수행, 외부 다운로드 없음.
2. **CUDA/torch DLL 실물 확인**: `dist\...\_internal\torch\lib\`와 실제 설치된
   `C:\...\Programs\SegmentationModelUI\_internal\torch\lib\` 양쪽 모두에서 `cublas*.dll`/
   `cudnn*.dll`/`cudart*.dll`/`torch_cuda.dll` 등이 물리적으로 존재함을 `ls`로 직접
   확인 — 런타임에 CUDA 라이브러리를 따로 받을 필요 없음.
3. **런타임 네트워크 호출 코드 감사**: `app/` 전체에서 `requests.*`/`urllib`/`urlopen`/
   `torch.hub`/`model_zoo` grep → 실제 호출은 0건. `device_info.py`/`cuda_diag.py`의
   `http(s)://` 매치는 전부 사람이 읽는 로그/에러 메시지 안의 안내 URL 문자열(예: "pip
   install ... --index-url https://...", "NVIDIA 드라이버: https://...")일 뿐 코드가
   실행하는 요청이 아님. `app/model_presets/{deeplab_resnet,deeplab_mobilenet,
   lraspp_mobilenet}.py`에 `pretrained: bool = False` 파라미터가 있고 `True`로 바꾸면
   torchvision이 COCO 사전학습 가중치를 실제로 다운로드함(주석에 "네트워크 필요"라고
   이미 명시) — 다만 **기본값이 False**라 기본 골든 패스(모델 프리셋 선택→학습)는
   네트워크 없이 동작, 이 기능은 사용자가 명시적으로 옵트인해야만 네트워크를 요구하는
   별개 기능으로 분류(설치·기본 구동과는 무관).
4. **실측 대체 확인**: 설치된 exe를 정상 실행한 직후(프로젝트 선택 다이얼로그 상태) 해당
   PID로 `netstat -ano`를 확인 — 매칭되는 TCP/UDP 연결·리슨 0건. 즉 설치 직후 기동 시점에
   실제로 외부 네트워크 연결을 전혀 시도하지 않음을 실측으로 뒷받침.

**결론**: 물리적 네트워크 완전 차단 상태에서의 실측은 권한 제약으로 수행하지 못했지만,
(a) 인스톨러 자체에 다운로드 로직이 없고 (b) CUDA 포함 전체 의존성이 로컬에 이미
번들되어 있으며 (c) 코드 감사상 실행되는 네트워크 호출이 없고(선택적 `pretrained=True`
제외) (d) 실제 기동 시 네트워크 연결 시도가 0건이라는 4중의 근거로 "설치 파일 하나만으로
오프라인 설치·기본 구동이 가능하다"는 결론에 대한 신뢰도는 높다고 판단. 다만 100%
확정하려면 관리자 권한이 있는 별도 환경에서 실제 네트워크 차단 후 재현하는 것을 권장 —
`docs/decisions-needed.md`에는 등록하지 않음(사용자 결정이 필요한 사안이 아니라 권한
제약에 따른 검증 수단 대체일 뿐이므로).

### 발견한 문제
새 버그 없음. 재확인된 기존 항목: QA.md BUG-016(무인 제거 후 `data\logs\` 잔존)만
동일하게 재현 — 이미 Open으로 추적 중이라 QA.md 추가 등록 없음.

### 정리
검증에 쓴 설치본(`C:\Users\Feel\AppData\Local\Programs\SegmentationModelUI\`)은 테스트
후 직접 삭제해 머신을 정리. 저장소 쪽 `dist\`/`installer\output\`는 `.gitignore`로 이미
제외 대상이라 그대로 둠(`git status` clean 확인).

### 판정
**통과**. exe/installer 정상 빌드·기동·무인 설치·무인 제거(BUG-016 범위 내) 전 과정 재확인,
로고 아이콘 타이틀바+작업표시줄 실제 확대 스크린샷으로 재확인, 빌드 로그 경고 전부 무해
확인. 오프라인 설치/구동 가능성은 실측 네트워크 차단은 권한 제약으로 불가했으나 정적
근거(다운로드 로직 없음, 의존성 전량 번들, 실행되는 네트워크 호출 없음) + 실측
netstat(연결 0건) 4중 근거로 사실상 확인.

---

## 2026-08-25 — GitHub 이슈 #8 검증: 이미지탭 다중선택 + 삭제

### 배경
기획 에이전트가 `docs/specs/voc-github-issues-round3-2026-08-25.md`에서 이미 구현돼
있는 것으로 판단(`app/widgets/image_browser.py`). 새로 구현하지 말고 실측만 하라는
지시에 따라 코드 리뷰 + 실제 위젯 조작으로 검증.

### 방법
GUI 자동화/스크린샷 도구가 주어지지 않아(`Read, Grep, Glob, Bash, Write`만 가용),
`main.py`를 우선 백그라운드로 띄워 앱이 정상 기동하는지 확인한 뒤(콘솔 cp949 인코딩
경고만 있고 크래시 없음 — 기존에 알려진 무해 이슈), 실제 인터랙션 검증은 `ImageBrowser`
위젯을 직접 인스턴스화하고 `QTest.mouseClick(..., Qt.KeyboardModifier.ControlModifier/
ShiftModifier, ...)`로 진짜 마우스 이벤트를 트리 위젯에 보내는 스크립트로 수행
(`scratchpad/test_delete_issue8.py`). `QMessageBox.question`은 자동 Yes 응답하도록
monkeypatch해 모달 블로킹만 우회했고, 그 외 전 경로(`_on_delete`, `reload`,
`_apply_display`)는 실제 프로덕션 코드 그대로 실행. 사용자의 실제 프로젝트
(`projects/nok`)나 `data/settings.json`은 건드리지 않기 위해 `_project.set_current()`
대신 `_project._current`를 스크래치 프로젝트로 직접 지정(recent_projects/last_project
갱신 회피), 이미지 5장 + 어노테이션 JSON 2개는 스크래치 디렉터리에만 생성.

### 확인한 항목
1. **Ctrl+클릭 다중선택**: 실제 클릭 2회(NoModifier→item1, ControlModifier→item3)로
   `selectedItems()` == 2건, 스크린샷(`shot_ctrl_multiselect.png`)으로 파란 하이라이트
   육안 확인.
2. **Shift+클릭 범위선택**: NoModifier→item0, ShiftModifier→item2 클릭으로 0~2번 3건
   범위선택, 스크린샷(`shot_shift_multiselect.png`)으로 확인.
3. **삭제 버튼 실제 클릭**(`QTest.mouseClick(browser._btn_del, ...)`) → 확인 다이얼로그
   문구가 복수형("선택한 3개 이미지를...")으로 정확히 분기, 이미지 3장(`test_del_0/1/2
   .png`) + 대응 어노테이션 JSON 2개(`test_del_0/2.json`) 모두 삭제, 트리 아이템 수
   5→2 갱신 확인.
4. **단일선택 삭제 회귀**: item0(`test_del_3.png`) 1건 선택 후 삭제 → 단수형 문구("
   'test_del_3.png' 를 삭제하시겠습니까?")로 정확히 분기, 파일 삭제 및 트리 갱신(2→1)
   정상.
5. **크래시 확인**: 스크립트 실행 중 예외 없음(`ALL CHECKS PASSED`), `data/logs/
   errors.log`에 신규 항목 없음 — 과거 기록된 "unhashable type: 'QTreeWidgetItem'"
   크래시(2026-05-27 항목, `self._item_to_path[item] = p` 구식 패턴)는 현재 코드
   (`_PATH_ROLE` UserRole + `Path`를 dict 키로 쓰는 구조)에서 재현되지 않음 — 이미
   해소된 것으로 최종 확인.

### 정리
스크래치 프로젝트(`scratchpad/issue8_project`)는 검증 후 삭제. `data/settings.json`
diff 없음(`git status --short`로 미변경 확인) — 사용자 실데이터 무영향.

### 판정
**통과**. 다중선택(Ctrl/Shift)·삭제 확인 다이얼로그(단/복수 문구)·이미지+어노테이션
동시 삭제·목록 갱신·단일삭제 회귀 모두 실측으로 정상 동작 확인. 새 버그 없음 —
QA.md 변경 없음.

---

## 2026-08-25 — GitHub #9 팬 드래그 중 휠 줌 초점 버그 수정 검증

### 대상
커밋 `629fe1d` — `app/widgets/annotation_canvas.py`의 `wheelEvent()`에 `_pan_active`일 때
`_pan_start_mouse`/`_pan_start_offset`를 새 줌 결과로 갱신하는 6줄 추가. 회귀 테스트
`tests/test_canvas_zoom_pan.py` 신규 추가.

### 방법
1. `tests/test_canvas_zoom_pan.py`는 pytest 미설치 환경이라(`py -3 -m pytest` →
   `No module named pytest`, `py -3.12`도 동일) `py -3 tests/test_canvas_zoom_pan.py`로
   `__main__` 블록의 assert 기반 자체 검사를 직접 실행 — 통과(`OK: zoom-during-pan
   focal point preserved`).
2. 구현 에이전트 주장("수정 전 코드로 stash하면 실패") 재검증 — `git show 629fe1d~1:...`로
   수정 전 파일을 임시로 워킹트리에 덮어쓰고 동일 테스트 실행 → `AssertionError`로 실제
   재현 확인 후 `git checkout --`로 즉시 원복(`git status --short`로 클린 확인).
3. **실제 GUI 조작 검증(전체 앱 경로)** — `scratchpad/gui_verify_issue9.py` 작성:
   `MainWindow()`를 실제로 생성(`app._labeling_tab._canvas`까지 실제 위젯 트리),
   체커보드+빨간 마커 테스트 이미지(`qa_zoom_test.png`, 검증 후 삭제)를
   `tab._on_image_selected()`로 실제 로드. `QTest.mousePress/mouseMove/mouseRelease`로
   진짜 `QMouseEvent`를 캔버스에 전달하고, 휠은 실제 `QWheelEvent`를 만들어
   `QApplication.sendEvent()`로 디스패치(OS 스크롤 입력을 Qt가 위젯에 전달하는 것과 동일
   경로, monkeypatch 없음). `QT_QPA_PLATFORM=offscreen`로 실행(이 환경엔 대화형 디스플레이
   드라이빙 도구가 없어 스크린샷 전후비교 + 좌표/색상 로그로 대체).

### 확인한 시나리오 (전부 실제 이벤트 디스패치 경로로 실행)
1. **Pan 도구 드래그 중 휠 줌**: 드래그 시작 → 이동 → 같은 화면 좌표에서 휠 줌인 →
   커서 아래 이미지좌표 drift **0.0000px**, `canvas.grab()` 스크린샷(`issue9_1_before_wheel
   .png`/`issue9_2_after_wheel.png`) 육안 비교로도 빨간 마커가 같은 화면 위치에 그대로
   유지됨을 확인. 줌 직후 이어지는 `mouseMoveEvent` 1회 추가 발생시켜도 pan 점프
   **0.0000px**(stale 기준값으로 안 되돌아감).
2. **Space+좌클릭 팬 중 휠 줌아웃**: drift 0.0000px.
3. **우클릭 드래그 팬 중 휠 줌인**: drift 0.0000px.
4. **회귀 — 브러시 도구**: 페인팅 중(`_is_painting=True`, `_pan_active=False`) 휠 이벤트
   발생시켜도 `_pan_start_mouse`가 전혀 변경되지 않음(이번 수정 분기가 `_pan_active`
   조건이라 브러시 경로는 안 탐 확인) + 스트로크 정상 커밋(`_annotations` 1건 추가).
5. **회귀 — 폴리곤 도구**: 점 3개 찍은 진행 중 상태에서 휠 줌 발생시켜도 `_poly_pts` 3개
   그대로 보존(진행 중인 폴리곤이 취소되거나 깨지지 않음).
6. (Select 도구는 이번 수정과 무관한 `_pan_active=False` 경로이며 시나리오 1~3에서 이미
   pan_active 진입 조건 자체를 실제 이벤트로 재현했으므로 별도 스텁 불필요 판단.)

### 대조군 (수정 전 코드로 동일 GUI 스크립트 재실행)
`git show 629fe1d~1`로 수정 전 파일을 임시 적용 후 위와 동일한 시나리오 1 실행 →
줌 직후 첫 프레임은 초점 유지(0.0000px, wheelEvent 자체 계산은 원래도 맞았음)이나,
**이어지는 mouseMoveEvent에서 이미지좌표 45.68px 이동 + pan이 정확히 줌 이전 값
(40.90, 52.68)으로 되돌아감**(`pan_jump_after_move_px` assert 실패) — 스크린샷 픽셀색도
(30,30,30)→(220,220,220)로 명백히 바뀜(체커보드 한 칸 이상 어긋남). 버그가 실제 재현됨을
전체 GUI 경로에서도 재확인 후 `git checkout --`로 원복.

### 크래시 로그
`data/logs/errors.log` 라인 수 검증 전후 동일(3662줄, 신규 항목 0건).

### 뒷정리
스크래치 테스트 이미지(`data/images/qa_zoom_test.png`)와 그로 인한 부산물(어노테이션 JSON
없음, 자동저장 트리거 안 됨) 삭제 완료. `git status --short` 클린(`app/widgets/
annotation_canvas.py` 무변경). 스크린샷 3장은 세션 scratchpad에만 저장.

### 참고 — 별도로 관찰(등록 안 함)
`py -3 main.py`를 이 세션 콘솔(cp949)에서 직접 실행하면 `device_info.log_environment()`의
em-dash(—) 문자가 콘솔 `StreamHandler`에서 `UnicodeEncodeError`로 로깅 실패(내부적으로
잡혀 앱 크래시는 아님, 파일 로그는 UTF-8이라 영향 없음). 2026-08-19 검증 로그에도 "기존에
알려진 무해 이슈"로 이미 언급된 사항이라 중복 등록하지 않음. 이번 이슈 #9와 무관.

### 판정
**통과**. `tests/test_canvas_zoom_pan.py` 실행 통과 + 수정 전 코드에서 실패 재현으로
구현 에이전트 주장 검증 완료. 전체 `MainWindow` 경로에서 실제 `QMouseEvent`/`QWheelEvent`
디스패치로 Pan 도구·Space+좌클릭·우클릭 3가지 팬 진입 방식 전부 초점 유지(drift
0.0000px) 확인, 이어지는 move에서도 안 튐. 브러시/폴리곤 도구는 `_pan_active` 분기를
타지 않아 회귀 없음 확인. 새 버그 없음 — QA.md 변경 없음.

---

## 2026-08-25 — SegFormer/SegNeXt/PIDNet 프리셋 3종 검증 (커밋 c9f49e6, 37ab955)

### 대상
구현 에이전트가 추가한 신규 모델 프리셋 3개(`app/model_presets/segformer.py`,
`segnext.py`, `pidnet.py`) + `__init__.py` 등록분. "주요 기능 추가" 라운드로 판단해
모델/학습/추론 탭 전부 실제 UI 조작으로 골든패스를 확인.

### 방법
스크래치 스크립트(`scratchpad/verify_new_presets.py`, 저장소에는 추가하지 않음)로
`MainWindow()`를 실제로 생성하고, `QTest.mouseClick`/`QTimer.singleShot`으로 실제
버튼 클릭·모달 다이얼로그 상호작용·시그널 흐름을 그대로 태웠다(내부 상태를 직접
세팅하는 우회 없이, 모델 탭 프리셋 팝업 → 검증 → 로드 → 학습 탭 큐 추가 → 실행 →
추론 탭 체크포인트 선택 → 추론 실행까지 전부 프로덕션 코드 경로). 실사용
`projects/`·`data/settings.json`은 건드리지 않기 위해 `app.core.project.set_current()`
대신 `_project._current`를 스크래치 프로젝트(`qa_preset_project`, 64×64 합성 이미지
3장 + 클래스 2개 + 폴리곤 어노테이션)로 직접 지정. `QMessageBox.question/warning/
information/critical`을 모니터링용으로 monkeypatch(호출 로그만 남기고 자동 응답) —
이번 실행에서는 실제로 한 번도 호출되지 않음(GPU 사용 가능이라 CPU 폴백 확인 팝업도
안 뜸).

### 확인한 항목
1. **모델 탭 — 프리셋 팝업**: `ModelPresetDialog`(리스트+설명 패널, 드롭다운이 아니라
   좌측 리스트 방식임을 확인)를 실제로 `_btn_preset` 클릭으로 열어 SegFormer/SegNeXt/
   PIDNet 3개 항목이 리스트에 모두 존재함을 확인, 각각 실제 선택 후 "에디터에
   불러오기" 버튼 클릭으로 에디터에 코드가 로드됨(빈 에디터 아님, 기대 클래스명 포함)
   확인.
2. **검증 버튼**: 3개 전부 `_btn_validate` 클릭 → 상태 라벨에 "✓" 표시, `_btn_load`
   활성화 확인(AST 검증 실제 통과).
3. **로드 버튼**: 3개 전부 `_btn_load` 클릭 → `loaded_model` 정상 인스턴스화,
   파라미터 수가 구현 로그 수치와 **정확히 일치**: SegFormer 3,714,658 / SegNeXt
   3,404,098 / PIDNet 915,746.
4. **학습 탭 — 실제 학습 스모크 (배치 크기 1 포함, PIDNet 회귀 확인 목적)**: 학습
   탭의 모델 콤보(프리셋 직접 선택 가능)로 3개 프리셋을 각각 별도 잡으로 큐에 추가
   (`resize` 모드, img 64×64, epochs=1, batch_size=1, num_workers=0, ckpt_every=1),
   "전체 실행" 버튼 실제 클릭 → `TrainerWorker` QThread가 실제로 3개 잡을 순차
   실행. 3개 전부 `status == "done"`으로 정상 종료(train_loss/val_loss 유한값 산출:
   SegFormer 0.597/0.550, SegNeXt 0.649/0.714, PIDNet 0.622/0.721). 손실 그래프
   (`LossChart`)에 실제 배치 포인트가 누적됨을 확인. **PIDNet이 batch_size=1로
   예외 없이 완료** — 구현 에이전트가 이번 라운드에서 고친 PPM
   BatchNorm→GroupNorm 수정의 회귀 확인 완료(수정 전이었다면 "more than 1 value
   per channel" RuntimeError로 즉시 실패했을 지점).
5. **체크포인트 저장**: `pid_test_epoch_0001.pt`, `sf_test_epoch_0001.pt`,
   `sn_test_epoch_0001.pt` 3개 전부 스크래치 프로젝트의 `checkpoints/`에 실제 저장됨
   확인.
6. **추론 탭 — 실제 추론 (3개 모델 전부)**: "↺ 새로고침" 클릭으로 방금 저장된
   체크포인트 3개가 테이블에 표시됨 확인 → 각 체크포인트 행 선택 시
   `model_source`(`preset:*`)를 읽어 `_auto_model`이 자동으로 인스턴스화됨(프리셋
   기반 체크포인트 자동 매칭 경로) 확인 → 이미지 로드 후 "▶ 추론 실행" 버튼 실제
   클릭 → 3개 전부 `overlay_pixmap`이 비어있지 않은(`isNull()==False`) 64×64
   결과 생성, 클래스 범례 테이블에 background/defect 비율까지 정상 표시.
7. **`data/logs/errors.log`**: 검증 전후 라인 수 동일(3662 → 3662, 신규 항목 0건) —
   크래시·미처리 예외 없음.
8. **부수 확인**: `git status --short`로 저장소 무변경, `git diff --stat -- data/
   settings.json` 무변경, `git status --short -- projects/` 무변경 — 실사용 데이터·
   설정에 영향 없음 확인. 스크래치 테스트 프로젝트(`qa_preset_project`)는 검증 후
   삭제.

### 발견한 문제
새 버그 없음. QA.md 변경 없음.

### 판정
**통과**. 모델 탭(프리셋 3종 로드/검증/로드) · 학습 탭(큐 추가·실행·손실그래프·
체크포인트 저장, batch_size=1 PIDNet 회귀 포함) · 추론 탭(체크포인트 자동 매칭·
실제 추론·오버레이 표시) 전 과정을 실제 위젯 클릭/시그널 경로로 3개 모델 모두
end-to-end 확인. push는 아직 안 된 상태 — 리더가 사용자 확인 후 진행.

---

## 2026-08-25 — 어노테이션 가져오기(Import) 실제 GUI 왕복 검증 (커밋 2837c5c, 16a1e7e)

### 검증 대상
구현 에이전트가 추가한 어노테이션 Import 기능(`app/widgets/import_dialog.py`
`ImportAnnotationDialog`, `app/main_window.py`의 Import 버튼 + `_on_open_import_ann()`,
`app/tabs/labeling_tab.py`의 `reload_after_import()`). 구현 단계에서는 스크립트
레벨 로직 테스트만 통과했고 실제 GUI 클릭 경로는 미확인 상태였음 — 이번 라운드에서
확인.

### 방법
`py -3 main.py`로 직접 조작하는 대신, 실사용 `projects/` 디렉터리를 건드리지 않기
위해 스크래치 폴더(`…/scratchpad/ImportQA`)에 격리 프로젝트를 만들고
`app.core.project.create/set_current`로 프로젝트를 설정한 뒤 실제 `MainWindow`를
띄워 **실제 위젯 이벤트 경로**(`QTest.mouseClick`)로 전체 왕복 시나리오를 재현하는
스크립트(`verify_import_gui.py`)를 작성해 실행. `QDialog.exec()`를 임시로 감싸
`QTimer.singleShot`으로 모달 진입 후 실제 버튼 클릭을 스케줄링하는 방식(기존
`gui_verify_issue9.py`와 동일한 패턴)으로 네이티브 `QFileDialog`만 우회(필드 직접
세팅)하고 나머지는 전부 실제 버튼 클릭. `QMessageBox.information/critical/warning`은
비차단 캡처로 임시 패치(테스트 스크립트 내에서만, 소스코드 변경 없음).

### 확인한 것
1. **툴바 버튼**: MainWindow 코너에 Export(내보내기 화살표) 옆 clipboard 아이콘의
   Import 버튼이 실제로 보이고, 툴팁("내보낸 어노테이션 데이터를 가져오기")도
   정상 표시됨. 스크린샷(`import_qa_toolbar.png`)으로 육안 확인.
2. **전체 왕복 시나리오** (4개 이미지: img1=polygon/cat, img2=brush_mask/dog,
   img3=무라벨, img4=polygon/cat):
   - Export 버튼 실제 클릭 → `ExportDialog`에서 JSON 포맷으로 스크래치 폴더에
     내보내기 실행(labeled_only 기본값 유지) → 라벨된 3개(img1,2,4) 내보내짐,
     완료 메시지("완료 — 3개 이미지를 내보냈습니다.") 확인.
   - 충돌 조성: img1 폴리곤 좌표 변경, img2 브러시 마스크 다른 영역으로 변경,
     img4는 프로젝트에서 이미지+어노테이션 파일 자체를 제거(새 이미지 시나리오),
     로컬 classes.json에서 "dog" 클래스 제거(클래스 병합 시나리오).
   - Import 버튼 실제 클릭 → "기존 유지"(skip, 기본값) 정책으로 실행 → 완료
     메시지("가져옴 1개, 유지(건너뜀) 2개, 새 이미지 1개, 새 클래스 1개") →
     img1/img2는 변경된 상태 그대로 유지(덮어써지지 않음), img4는 이미지+
     원본 어노테이션 그대로 복원, classes.json에 "dog" 병합됨 — 전부 확인.
   - 다시 Import → "덮어쓰기" 정책으로 실행 → 완료 메시지("가져옴 3개") →
     img1 폴리곤 좌표가 내보낼 때 원본과 **정확히 일치**, img2 브러시 마스크가
     `np.array_equal`로 원본과 **정확히 일치**함을 확인.
   - 완료 메시지박스에 imported/skipped_existing/skipped_missing/new_images/
     new_classes 요약 숫자가 실제로 표시됨 확인 (위 인용).
3. **라벨링 탭 실시간 갱신**: skip 정책 import 완료 직후(탭 재오픈 없이)
   `labeling_tab._image_browser._all_paths`를 조회 — img4.png가 즉시 포함돼
   있음을 확인. `reload_after_import()`가 `main_window._on_open_import_ann()`에서
   `dlg.imported_any` True일 때 자동 호출되는 경로가 실제로 동작함.
4. **새 이미지 가져오기**: img4.png가 `images_dir`에 실제로 복사되고 이미지
   브라우저 목록에도 반영됨 확인.
5. **에러 케이스**: `annotations/` 서브폴더가 없는 빈 폴더를 선택 → 크래시 없이
   `QMessageBox.critical`(제목 "어노테이션 가져오기", "…annotations 폴더가
   없습니다…")가 뜸. 단, 이 경우 다이얼로그가 닫히지 않고 계속 열려있는(사용자가
   다른 폴더를 다시 고를 수 있도록) 의도된 동작임을 확인 — 테스트 스크립트가 이걸
   놓쳐 처음엔 모달 대기로 멈췄다가 원인 파악 후 스크립트에서 close 버튼 클릭을
   추가해 통과시킴 (앱 버그 아님, 테스트 스크립트 버그).
6. **`data/logs/errors.log`**: 검증 전후 라인 수 동일(3662 → 3662, 신규 항목 0건).
   로그 끝부분에 있던 `TypeError: unhashable type: 'QTreeWidgetItem'` 트레이스백은
   2026-05-27자 과거 기록으로, 이번 세션과 무관함을 날짜 헤더로 확인.
7. **부수 확인**: `git status --porcelain` 무변경, `projects/`(실사용 프로젝트
   루트)에는 기존 `nok` 외 변화 없음 — 스크래치 프로젝트/내보내기 폴더는 검증
   완료 후 삭제.

### 발견한 문제
새 버그 없음. QA.md 변경 없음.

참고(버그 아님, 설계상 특이사항으로만 기록): "기존 유지" 정책 판정은
`load_annotations(img_path)`가 반환한 리스트의 **truthiness**로 "기존 어노테이션
있음"을 판단한다(`app/widgets/import_dialog.py`의 `existing and not overwrite`).
즉 어노테이션 JSON 파일이 존재하더라도 그 안의 annotations 배열이 비어있으면
(라벨을 전부 지운 상태) "충돌 없음"으로 취급되어 skip 정책이어도 새로 가져온
데이터로 채워진다. 사용자 관점에서는 "빈 라벨 = 미라벨과 동일 취급"이라는
합리적 해석이라 버그로 등록하지 않음.

### 판정
**통과**. Export/Import 버튼 노출·툴팁, Export→충돌 조성→Import(기존 유지/덮어쓰기)
전체 왕복, 라벨링 탭 실시간 갱신, 새 이미지 가져오기, 에러 폴더 처리까지 전부
실제 위젯 클릭 경로로 확인. push는 하지 않음 — 리더가 사용자 확인 후 진행.


---

## 2026-08-25 — 추론 탭 AI점수/픽셀크기 threshold 필터 + blob별 Excel 내보내기 (커밋 `b07c1dd`, `97c0dc0`)

### 검증 대상
구현 에이전트가 추론 탭에 추가한 threshold 필터링(`app/core/inference_engine.py`의
`BlobStat`/`_compute_blobs_and_filter()`/`refilter()`, `run()`/`run_sliding_window()`의
`min_confidence`/`min_pixel_size` 파라미터)과 blob별 Excel 내보내기
(`export_blobs_to_excel()`), 그리고 `app/tabs/inference_tab.py`의 신규 스핀박스 2개
("최소 AI 점수"/"최소 픽셀 크기"), "탐지된 blob 수" 라벨, "Excel로 내보내기" 버튼
(단일/일괄), opacity 슬라이더의 `engine.refilter()` 전환. 구현 로그(implementation-log.md
`b07c1dd`)엔 blob 필터링·성능·Excel 구조·`refilter()`가 torch 미사용임을 스크립트로
확인했다고만 나와 있고 **실제 GUI 클릭 경로(스핀박스 조작, 버튼 클릭, 다이얼로그 흐름)는
전혀 확인되지 않은 상태**였음 — 이번 라운드에서 확인.

### 방법
`py -3 main.py`로 직접 조작하는 대신(라벨링→학습→추론 전 과정을 매번 수동 클릭으로
재현하기엔 비효율적), 실사용 `projects/`를 건드리지 않도록 스크래치 폴더에 격리
프로젝트(`app.core.project.Project` 직접 생성 + `project._current` 직접 대입 —
`set_current()`가 건드리는 `settings.json`의 `recent_projects`/`last_project` 무변경)를
만들고, 실제 `QApplication` + `QTest`로 **라벨링 탭 → 학습 탭 → 추론 탭 전 과정**을
실제 프로덕션 위젯 이벤트 경로로 재현하는 스크립트
(`…/scratchpad/qa_inference_threshold.py`, 최종본은 정리 시 함께 삭제)를 작성해 실행.
`QT_QPA_PLATFORM=offscreen` + 실제 GPU(CUDA, RTX) 사용.

- **라벨링**: 128×128 합성 이미지 3장(어두운 노이즈 배경 + 서로 다른 크기의 흰색
  사각형 — 대/중/소)을 생성, `AnnotationCanvas`에 `QTest.mouseClick`/`mouseDClick`으로
  실제 폴리곤 4점 클릭+더블클릭 닫기를 재현해 라벨링(annotation_id 1개씩 저장 확인).
- **학습**: `TrainingTab`에서 `ConfigForm` 값을 실제 위젯에 `setValue()`로 세팅
  (resize 128×128, epochs=80, lr=1e-3, batch=1 — 합성 데이터라 원본 1 epoch/기본 lr로는
  전부 배경으로만 예측되어 threshold 테스트가 무의미했음, 대비를 극대화하고 epoch을
  올려 실제로 학습되게 조정), 모델 콤보에서 `preset:simple_unet` 선택, "큐에 추가" +
  "전체 실행" 버튼 실제 클릭 → `TrainerWorker` QThread 완료(9초) 대기 → 체크포인트
  생성 확인.
- **추론**: `InferenceTab` 실제 인스턴스 — 체크포인트 테이블 자동 선택→`_auto_model`
  자동 준비 확인, `_img_list.load_folder()`+`_after_load()`(폴더 선택 버튼과 동일 코드
  경로, 네이티브 `QFileDialog`만 우회)로 3장 로드 → 폴더 모드 목록 패널 노출 확인 →
  "▶ 추론 실행" 버튼 실제 클릭.
- **threshold 스핀박스**: `_min_conf_spin`/`_min_px_spin`에 실제 `setValue()`(Qt
  내부적으로 위젯 드래그/키 입력과 동일한 `valueChanged` 시그널 경로를 탐)로 값을
  바꿔가며 매번 `_lbl_blob_count` 텍스트와 `_last_result.blobs` 개수, 그리고
  `raw_class_map is <최초 캐시>`(객체 identity)로 **모델 재실행 없이** 재필터링되는지
  확인.
- **Excel 내보내기**: `QFileDialog.getSaveFileName`만 임시 monkeypatch(고정 경로 반환),
  폴더 모드 선택 다이얼로그·완료 정보 다이얼로그는 `QTimer.singleShot` +
  `QApplication.activeModalWidget()` 탐색으로 실제 버튼(`QPushButton`)을
  `QTest.mouseClick`으로 클릭(기존 `verify_import_gui.py` 패턴과 동일) — 다이얼로그
  자체는 진짜 `QMessageBox.exec()`.

### 확인한 것
1. **추론 실행 → blob 수 표시**: 체크포인트 선택 즉시 "U-Net (자동 준비됨)" 라벨
   확인(`_auto_model` 정상 설정), 추론 실행 후 `_lbl_blob_count`="탐지된 blob 수: 1개"
   가 실제 `_last_result.blobs` 개수와 일치.
2. **최소 AI 점수 threshold 실시간 반영**: 0%→50%→90%→99%로 올릴 때 blob 수가
   1→1→1→0으로 단조 감소(모델이 예측한 blob의 평균 신뢰도가 90~99% 사이였음을
   실측으로 확인), 0%로 되돌리면 정확히 원래 개수(1개)로 복원. 매 단계
   `raw_class_map is <최초 캐시>`가 `True` — `refilter()`가 실제로 forward pass를
   재실행하지 않고 캐시된 배열만 재사용함을 객체 identity로 확인.
3. **최소 픽셀 크기 threshold 실시간 반영**: 현재 blob 픽셀 크기(4270px) 대비
   mid(2135px)에서는 유지, huge(9270px, blob보다 큼)에서는 완전히 사라짐(0개), 0으로
   되돌리면 복원.
4. **Opacity 슬라이더 회귀 확인(구현 로그가 "opacity 전환하며 부수적으로 고쳤다"고
   주장한 버그)**: threshold=90%로 걸어 blob 1개로 필터링해둔 상태에서 opacity
   슬라이더를 20%→80%→50%로 실제 `QSlider.setValue()`(→`valueChanged`→
   `opacity_changed`→`_on_opacity_changed`→`engine.refilter()`)로 조작해도 매번
   blob 수가 필터링된 값(1개)으로 그대로 유지됨 — opacity 변경이 threshold 필터를
   풀지 않음을 확인(과거 `engine.run()` 재호출 방식이었다면 threshold 파라미터가
   기본값(0)으로 리셋돼 필터가 풀렸을 상황).
5. **Excel 내보내기 — 단일 이미지**: threshold=50%(blob 1개 유지) 상태에서 "현재
   이미지만" 선택 → 실제 `.xlsx` 생성, `openpyxl`로 열어 헤더
   (이미지파일명/blob_id/class_id/클래스명/픽셀수/신뢰도 등 14열) 확인, 데이터 행 수
   (1행)가 threshold 필터링된 blob 개수와 정확히 일치, 이미지파일명도 현재 이미지
   1개로 정확히 한정됨(threshold로 걸러진 blob이 엑셀에도 없음을 행 수 일치로 간접
   확인).
6. **Excel 내보내기 — 폴더 전체 일괄**: "목록 전체 일괄 추론" 선택 → `QProgressDialog`
   로 3장 순차 추론(캐시된 현재 이미지는 재추론 생략, 나머지 2장은 실제 `engine.run()`
   재호출) → 완료 후 하나의 `.xlsx`에 3개 이미지파일명(img0/img1/img2.png)이 각자
   실제 blob 1개씩(픽셀수 4270/1468/54 — 라벨링 시 그린 대/중/소 사각형 크기와
   정성적으로 일치, 평균 신뢰도 95~99%)으로 정확히 구분되어 들어감을 확인 — 모델이
   실제로 서로 다른 크기의 영역을 서로 다른 신뢰도로 예측했다는 의미 있는 데이터라
   기계적인(빈 값) 테스트를 넘어 기능이 실질적으로 동작함을 뒷받침.
7. **`data/logs/errors.log`**: 실행 전 베이스라인 3662줄 → 실행 후에도 3662줄, 신규
   예외 0건.

### 발견한 문제 — BUG-017 (직접 수정)
검증 스크립트의 1단계(라벨링)에서 `canvas._image_path`가 이미지 선택 후에도 계속
`None`으로 남는 현상을 발견. 원인 조사 결과 **이번 라운드 변경과 무관한 기존
버그**: `ImageBrowser.__init__()`이 `reload()`로 프로젝트의 첫 이미지를 자동
선택하며 `image_selected`를 즉시 발행하는데, 이 시점(`LabelingTab._build_ui()`
내부)은 `LabelingTab._connect_signals()`(리스너 연결)보다 **먼저** 실행되어 신호가
유실됨. `main.py`의 실제 기동 순서(`ProjectStartDialog`에서 `project.set_current()`를
먼저 호출한 뒤 `MainWindow()` 생성 → `LabelingTab()`은 프로젝트가 이미 열려 있는
상태로 생성됨, 게다가 라벨링 탭이 4개 탭 중 기본 활성 탭)상 **기존 이미지가 있는
프로젝트를 열 때마다 항상 재현**되는 실사용 버그로 판단(라벨링 탭 진입 시 이미지
목록 첫 항목이 하이라이트돼 있는데도 캔버스는 빈 화면 — 사용자가 아무 이미지나
클릭해야 로드됨). 이번 라운드(추론 탭)와 무관한 다른 탭의 문제이지만 원인이
명확하고 수정이 국소적(`labeling_tab.py` 1개 파일, `__init__()`에 4줄 추가)이라
CLAUDE.md 지침대로 직접 수정: `_connect_signals()` 직후
`self._image_browser.current_path()`가 있으면 `self._on_image_selected()`를 명시적으로
1회 호출해 캔버스를 동기화. 재검증 스크립트(위 방법의 1단계)로 수정 전
`AssertionError`(None) → 수정 후 정상 로드됨을 직접 확인. `QA.md`에 `BUG-017`(Closed)
로 등록. `py_compile` 통과.

### 회귀 확인
- `git diff --stat` — 이번 라운드에서 검증 에이전트가 건드린 파일은
  `app/tabs/labeling_tab.py` 1개뿐(BUG-017 수정). `docs/decisions-needed.md`,
  `docs/roadmap.md`, `docs/agents/planning-log.md` 변경은 병행 세션(기획 에이전트로
  추정)의 것으로 검증 세션에서 만든 변경이 아님 — 손대지 않음.
- `projects/` 실사용 데이터: 무변경(스크래치 폴더에서만 프로젝트 생성, 테스트 종료 후
  `qa_infer_proj`/생성된 `.xlsx` 2개 전부 삭제 완료).

### 판정
**통과**. threshold 필터(AI 점수/픽셀 크기) 실시간 재필터링(모델 재실행 없음),
opacity 슬라이더가 threshold를 깨지 않는 회귀 수정 확인, Excel 단일/일괄 내보내기
모두 실제 위젯 클릭 경로로 정상 동작 확인. 부수적으로 발견한 BUG-017(라벨링 탭
첫 이미지 자동 로드 실패)은 직접 수정 후 재검증 완료. push는 하지 않음 — 리더가
사용자 확인 후 진행.

## 2026-08-26 — 존(Zone) 분석 탭 라운드 1 검증 (커밋 `13f2952`, 별도 워크트리)

기획 산출물: [docs/specs/zone-analysis-tab-2026-08-25.md](../specs/zone-analysis-tab-2026-08-25.md).
구현 로그: [implementation-log.md](implementation-log.md) "2026-08-25 — 존(Zone) 분석 탭
라운드 1" 항목. **동시 세션 충돌로 이전 검증 시도가 중단·유실**되어(2026-08-25 leader-log
"워크트리 분리" 기록 참고) 원본 디렉토리(`D:\segmentation model`)와 완전히 분리된 전용
워크트리 `D:\segmentation model-zone-analysis-tab`(`feature/zone-analysis-tab` 브랜치)에서
처음부터 재검증. 이번 라운드는 신규 5번째 탭 추가라 "주요 기능 추가" 기준으로 실제 GUI
골든패스까지 확인.

### 정적 검토
- `git show 13f2952 --stat` — `app/core/i18n.py`(+2), `app/core/inference_engine.py`(+16/-3),
  `app/main_window.py`(+3), `app/tabs/zone_analysis_tab.py`(신규, 331줄),
  `app/widgets/zone_canvas.py`(신규, 19줄) 5개 파일만 변경. 스펙 "라운드 1" 범위와 일치.
- `app/core/inference_engine.py`의 `run()`/`run_sliding_window()`/`refilter()` 3곳에 추가된
  `classes: list[ClassDef] | None = None`가 전부 `classes = classes if classes is not None
  else load_classes()` 패턴으로 기존 동작을 보존함을 코드로 확인.
- `grep -rn "classes="  app/tabs/inference_tab.py`(및 `engine.run/run_sliding_window/refilter`
  호출부 3곳 확인) 결과 **`classes=` 인자를 넘기는 곳이 전혀 없음** — 기존 4탭 호출부는
  이번 변경으로 시그니처만 늘어났을 뿐 인자 미전달 시 완전히 동일하게 동작.
- `app/main_window.py` — `ZoneAnalysisTab`이 5번째 탭으로 등록(`t("tab.zone_analysis")`),
  `app/core/i18n.py`에 ko("존 분석")/en("Zone Analysis") 키 정상 추가됨을 확인.
- `zone_analysis_tab.py` 판단 3(체크포인트→모델 재구성)·판단 4(타겟 클래스 즉석 구성) 로직을
  코드로 직접 읽어 스펙과 일치함을 확인. `model_loader.save_user_code()`를 호출하는 지점이
  없음(커스텀 코드는 세션 메모리에만 유지)도 확인.

### 실제 GUI(QTest) 골든패스 검증
스크래치 프로젝트 2개(`zone_verify_preset`, `zone_verify_custom`, `projects/nok`의 실제
배터리 캡 사진 `7번.bmp`를 복사해 사용 — `projects/nok` 원본은 읽기 전용, 무변경 확인)에
동일 이미지 2장 + 사각형 폴리곤 어노테이션을 만들어 `TrainerWorker.run()`(QThread를
`.start()` 대신 동기 직접 호출)으로 실제 체크포인트 2종을 학습 생성:
- **preset 체크포인트**(`lraspp_mobilenet`, `model_source="preset:lraspp_mobilenet"`,
  타겟 클래스 1개만 존재하도록 이미지 왼쪽 60%만 라벨링) — 25 epoch CPU 학습.
- **custom 체크포인트**(직접 작성한 `TinyCustomNet`, `model_source="loaded"`, 타겟 클래스
  2개(좌/우 절반)가 모두 검출되도록 라벨링) — 25 epoch CPU 학습.
- 학습 후 `engine.run()`으로 직접 raw_class_map을 조회해 preset은 `{0, 1}`(단일 타겟),
  custom은 `{1, 2}`(2개 타겟)가 실제로 검출됨을 사전 확인 — 목표한 두 분기(텍스트필드 vs
  드롭다운)를 재현 가능한 테스트 데이터임을 검증.

`python main.py`와 동일한 임포트 순서(`numpy/cv2/PIL/torch/matplotlib` 선행 임포트 후
`QApplication` 생성 — 이 순서를 지키지 않고 `torch`만 단독으로 먼저 임포트하면 이 conda
환경에서 `QtSvg` DLL 임포트가 깨지는 것을 이번 세션에서 발견했으나, main.py와 동일한 순서로
맞추면 재현되지 않음을 별도로 확인함 — **실제 `main.py` 실행에는 영향 없는, 이 테스트
스크립트 자체의 임포트 순서 이슈**였으므로 QA.md에 등록하지 않음)로 `MainWindow`를 오프스크린
`QApplication`에서 실제 구동, `QFileDialog.getOpenFileName`만 몽키패치(헤드리스 환경에서
모달 다이얼로그 자체가 불가)하고 나머지는 전부 `QTest.mouseClick`/`QTest.keyClicks`로 실제
위젯 이벤트를 발생시켜 골든패스 31개 assertion 전부 통과:

1. **탭 표시/전환** — `QTabWidget.count()==5`, `tabText`=="존 분석", `QTest.mouseClick`으로
   탭바를 실제 클릭해 `currentWidget()`이 `ZoneAnalysisTab`으로 전환됨을 확인.
2. **preset 체크포인트 경로** — 이미지 선택 → 체크포인트 선택(`QFileDialog` 몽키패치 후
   실제 버튼 클릭) → `load_checkpoint_meta()`가 `preset:lraspp_mobilenet`을 읽어 자동
   인스턴스화(`_model is not None`, 코드박스 숨김, 라벨에 "자동 준비됨") → 추론 실행 버튼
   클릭 → 실제 추론 결과 반환, 단일 타겟 클래스 → 텍스트필드 표시(드롭다운 숨김), 기본 이름
   `class_1`, 캔버스에 오버레이 표시 → 텍스트필드 값을 `QTest.keyClicks`로 "rust"로 실제
   편집 후 Enter(`editingFinished`) → `refilter()` 재실행 정상.
3. **커스텀("loaded") 체크포인트 경로** — 체크포인트 선택 시 `model_source="loaded"`를 읽어
   `_model`이 `None`으로 유지되고 코드박스가 노출됨(라벨에 "사용자 정의 모델") 확인 →
   `_code_editor.setPlainText()`로 커스텀 코드 입력 → Validate 버튼 실제 클릭 → 로그에
   `[OK]` + Load 버튼 활성화 → Load 버튼 실제 클릭 → `_model` 준비됨(라벨에 "커스텀 모델
   로드됨") → 추론 실행 → 실제 결과에 타겟 클래스 2개 검출 → 드롭다운 표시(텍스트필드 숨김,
   항목 2개) → `setCurrentIndex(1)`로 실제 전환 → `refilter()` 재실행 정상, 오버레이 갱신.
4. **타겟 클래스 즉석 구성** — 위 2/3에서 단일→텍스트필드, 2개 이상→드롭다운 분기가 실제
   추론 결과 기반으로 정확히 스위칭됨을 확인(스펙 판단 4 그대로 동작).
5. **기존 4탭 회귀 없음** — `inference_tab.py`가 `classes=`를 넘기지 않는 것을 정적 확인한
   데 더해, 동일한 방식(`classes` 인자 생략)으로 `engine.run()`을 실제 실행해 예외 없이
   `load_classes()` 폴백(nok 프로젝트의 기본 `classes.json`, `class_stats`에 `object`/
   `background` 정상 표시)으로 동작함을 실행 확인. `win._inference_tab`도 `MainWindow` 내
   정상 생성됨을 확인.
6. **크래시 없음** — `py_compile` 통과는 구현 로그에서 이미 확인됐고, 이번 세션은 실제
   런타임(체크포인트 학습 2회 + GUI 골든패스 전체)에서 예외/크래시 0건.

### 프로세스 정리
- `win.close()` 호출 시 이 헤드리스(offscreen) 환경 특성상 모달 확인 다이얼로그가 뜨면
  응답 없이 대기하는 기존에 문서화된 제약(R1/R2 검증 로그 등에 반복 기록됨)이 이번에도
  재현되어 스크립트 프로세스가 자연 종료되지 않았음 — **모든 assertion이 이미 로그 파일에
  기록된 뒤**의 후행 정리 단계였음을 출력 로그(`ALL CHECKS PASSED`까지 출력됨)로 확인한 뒤
  `taskkill`로 명시적으로 종료, `tasklist`로 좀비 프로세스 없음 재확인. 이 라운드가 만든
  회귀가 아니라 기존부터 있던 헤드리스 환경 제약(GUI 자동화 셸이 아닌 대화형 데스크톱에서는
  발생하지 않을 것으로 추정)이라 QA.md에 신규 등록하지 않음.
- 스크래치 학습 산출물(`zone_verify_preset/`, `zone_verify_custom/`, 체크포인트 2개)은 전부
  스크래치 디렉토리에만 생성, `projects/nok/`은 이미지 읽기 전용 참고만 하고 무수정
  (`git status --short`로 재확인).

### 판정
- 구현 로그의 주장과 코드가 전부 일치, 실제 GUI 골든패스(preset/커스텀 체크포인트 양쪽,
  타겟 클래스 단일/복수 양쪽) 전부 통과, 기존 4탭 회귀 없음. **버그 발견 없음 — 라운드 1
  검증 통과.**
- 리더에게: **라운드 1 검증 통과, 라운드 2(원 자동검출/수동편집) 착수 가능.**
- `QA.md` 신규 등록 없음(발견된 결함 없음). `docs/roadmap.md`의 라운드 1 체크박스를
  "구현 완료, 검증 대기"에서 "구현+독립검증 통과"로 갱신.


---

## 2026-08-26 — 존(Zone) 분석 탭 라운드 2 검증: 원(circle) 자동검출 + 수동편집

### 범위
`docs/specs/zone-analysis-tab-2026-08-25.md` 판단 2(원 검출/편집), 커밋 `1815921`(circle_detector.py
+ scripts/zone_circle_proto.py) + `b1f05bc`(zone_canvas.py 편집 UI + zone_analysis_tab.py 연결) +
`0178ce5`(구현 로그) 검증. 라운드 1(탭 스켈레톤+체크포인트 로드+추론)은 이미 독립검증 통과(커밋
`8cec06d`) — 재검증 대상 아님, 회귀만 확인. 존 계산/퍼센티지(라운드3)·블랍삭제(라운드4)는 범위 밖.
**중요**: `D:\segmentation model-zone-analysis-tab` 워크트리에서 작업(`D:\segmentation model`은
다른 세션이 `main` 브랜치로 동시 사용 중이라 미접촉).

### 방법
- 정적 리뷰: `circle_detector.py`(Canny→findContours→원형도/면적 필터→Kasa 강건 원피팅) +
  `zone_canvas.py`(원 렌더링/히트테스트/드래그 편집) + `zone_analysis_tab.py`(자동검출 버튼+
  민감도 슬라이더+사이드 패널) 전체 코드 리딩.
- 실제 GUI(QTest) 골든패스: 스크래치 프로젝트(`zone_verify_r2_project`, `projects/nok`의 실제
  배터리 캡 사진 `7번.bmp`(5472×3648)+`8번.bmp`을 복사해 사용 — nok 원본은 읽기 전용, 무변경
  확인)에 왼쪽 절반을 class_1로 라벨링한 뒤 `TrainerWorker.run()`(QThread `.start()` 대신 동기
  직접 호출, 라운드1 검증 관례)으로 `lraspp_mobilenet` preset 체크포인트를 실제 학습 생성(1
  epoch, 128×128 resize 모드 — 정확도 무관, 추론 파이프라인 통과만 목적). `python main.py`와
  동일한 임포트 순서로 `MainWindow`를 오프스크린(`QT_QPA_PLATFORM=offscreen`) 구동, `QFileDialog`
  만 몽키패치하고 나머지는 전부 `QTest.mouseClick`/`mousePress`/`mouseMove`/`mouseRelease`/
  `keyClick`으로 실제 위젯 이벤트 발생. `QMenu.exec`(모달)만 "삭제" 액션 즉시 반환하도록
  몽키패치(우클릭 삭제 테스트용, 헤드리스 제약).

### 확인한 것 (수정 후 37개 assertion 전부 통과)
1. **탭/회귀** — `QTabWidget.count()==5`, 존 분석 탭 전환 정상. 탭 순서 재확인:
   라벨링/학습/추론/모델/존분석(모델탭이 4번째, 로드맵 표기 "5번째 탭"은 개수 기준으로 정확 —
   최초 내 테스트 스크립트가 "index 0 = 모델탭"으로 잘못 가정해 FAIL 냈던 것은 테스트 버그였음,
   실제로는 `LabelingTab`이 index 0 — 정정 후 통과).
2. **preset 체크포인트 자동 인스턴스화 + 추론 실행** — 실제 학습된 체크포인트로 이미지 선택→
   체크포인트 선택→"자동 준비됨"→추론 실행까지 정상, 캔버스에 오버레이 pixmap 설정 확인.
3. **자동 검출** — 민감도 50%에서 2개 원(반지름 1213px/1347px, 중심 거의 동일) 검출, 90%에서
   4개 원(534/604/1193/1548px) 검출 — 배터리 캡 동심원 구조(바깥 케이스 테두리/크림핑 링/
   원판 가장자리/원판 개구부)와 개수·상대 크기가 육안상 합리적으로 일치. 민감도를 바꾸면
   검출 결과가 실제로 달라짐을 확인. 원 목록이 항상 반지름 오름차순인 것도 확인.
4. **원본 대비 다운스케일 좌표 역산 정확성** — 5472×3648 원본에서 검출된 모든 원의 `(cx,cy,r)`가
   `0~W`, `0~H` 범위 안(원본 픽셀 스케일)에 있음을 확인 — `_MAX_DETECT_DIM=2048` 다운스케일 후
   역산이 정상 동작.
5. **수동 편집 4종 전부 실제 조작으로 확인**:
   - (a) 중심 드래그 이동 — `QTest.mousePress→mouseMove→mouseRelease`로 원 중심을 화면상
     (+40,+25)px 이동 후 `(cx,cy)`가 실제로 바뀌고 `r`은 불변임을 확인.
   - (b) 테두리 드래그 반지름 조절 — 테두리 지점을 화면상 +30px 바깥으로 드래그 후 반지름이
     실제로 커짐을 확인(초기 재현 시도에서 "변화 없음"으로 잘못 나왔던 것은 **내 테스트
     스크립트의 버그**였음 — mutable dataclass(`_CircleItem`) 참조를 들고 있다가 드래그 후
     같은 참조로 "이전 값"을 재조회해 자기 자신과 비교하는 실수. `before` 값을 드래그 전에
     `float`로 스냅샷하도록 수정 후 재현하니 1213.4px→1383.1px로 정상 변경 확인됨 — **앱
     버그 아님**).
   - (c) 빈 공간 드래그로 신규 원 생성 — 캔버스 좌상단 빈 영역 드래그로 원 1개 추가, 최소
     생성 반지름(`_MIN_CREATE_R_PX`) 미만이면 취소되는 로직도 코드로 확인.
   - (d) 삭제 — Delete 키로 선택된 원 삭제 확인 + 우클릭 컨텍스트 메뉴("원 삭제") 실행으로도
     삭제 확인(`QMenu.exec` 몽키패치, 헤드리스 제약 우회).
6. **사이드 패널 동기화** — 반지름 오름차순 표시 확인. 리스트→캔버스 방향은 정상이었으나
   **캔버스→리스트 방향에서 실버그 발견**(아래 "발견한 버그" 참고, 수정 후 재검증 통과).

### 발견한 버그 — BUG-018 (수정 완료, `QA.md` Closed로 등록)
`ZoneCanvas.mouseReleaseEvent()`가 드래그 종류(단순 클릭 선택 포함)와 무관하게 매번
`circles_changed`를 emit 하는데, `ZoneAnalysisTab._refresh_circle_list()`가 이 신호마다
`QListWidget.clear()`로 리스트를 통째로 비우고 다시 채워 `currentRow`가 -1로 리셋됨 — 캔버스에서
원을 클릭 선택(드래그 없이)하거나 이동/반지름조절/생성해도 사이드 리스트 하이라이트가 즉시
사라짐(원 데이터 자체는 정상, 표시 동기화만 깨짐). 디버그 스크립트로 `mousePressEvent`의
`circle_selected` emit 직후엔 `currentRow`가 정확히 0으로 설정됨을 확인했으나, 곧이어
`mouseReleaseEvent`의 `circles_changed` emit이 리스트를 재구성하며 그 선택을 지우는 것까지
단계별로 재현 확인.

**수정(검증 에이전트가 직접, 국소적·원인 명확)**: `ZoneCanvas.selected_id()` getter 추가 +
`_refresh_circle_list()`가 리스트 재구성 전 현재 선택 id를 읽어두고 재구성 후 해당 행을
`setCurrentRow()`로 복원 — 공유 함수 1곳만 고쳐 클릭/이동/반지름조절/생성 등 `circles_changed`를
emit하는 모든 경로에 동시 적용(개별 호출부마다 패치하지 않음). 부수적으로, 같은 세션에서 "추론
실행 전 자동 검출을 누르면 캔버스에 아무것도 안 보여 혼란스러울 수 있다"(구현 로그가 직접 짚은
우려사항)도 실제로 재현됨(원 데이터는 저장되지만 오버레이 pixmap이 없어 `paintEvent`가 그리지
않음) — 버튼 비활성화로 해결(`_btn_detect`를 추론 완료 전까지 `setEnabled(False)` + 툴팁 안내,
추론 성공 시 활성화). 두 수정 모두 `python -m py_compile` 통과, 전체 37개 assertion 재실행으로
재검증 통과(수정 전: 클릭선택 동기화 실패 1건 + 테스트 스크립트 버그 2건 오탐, 수정 후: 0건 실패).

### 회귀 확인
- 라운드 1 골든패스(체크포인트 로드+추론) 재확인 — preset 자동 인스턴스화, 추론 실행, 오버레이
  표시 전부 정상.
- 탭 5개 유지, 다른 탭(`LabelingTab`)으로 전환도 정상.
- `py_compile` 통과, 런타임 크래시 0건(학습 1회+GUI 골든패스 전체 세션 동안).

### 프로세스 정리
- 스크래치 프로젝트(`zone_verify_r2_project`, 체크포인트 포함)는 검증 종료 후 삭제.
- 헤드리스 환경 특성상 `win.close()`가 모달 없이도 이벤트 루프 부재로 자연 종료되지 않는
  기존에 문서화된 제약(R1~R6/라운드1 검증 로그에서 반복 확인된 패턴) 재현 — 모든 assertion이
  이미 출력된 뒤였음을 확인하고 `taskkill`로 명시적 종료, `tasklist`로 좀비 프로세스 0건 재확인.
- `git status --short` 결과 `app/tabs/zone_analysis_tab.py`, `app/widgets/zone_canvas.py`만
  변경(BUG-018 수정), `projects/nok/`은 무변경.

### 판정
**통과(조건부 아님 — 발견된 버그를 검증 에이전트가 즉시 수정하고 재검증까지 완료)**. 자동
검출(민감도 반응 + 원본 스케일 좌표 정확성 + 배터리 캡 동심원 구조 개연성) + 수동 편집 4종
(이동/반지름조절/생성/삭제) + 사이드 패널 양방향 동기화(수정 후) 전부 실제 GUI 조작으로 확인.
라운드 1 회귀 없음.
- 리더에게: **라운드 2 검증 통과. 라운드 3(zone_metrics — 존 리스트+퍼센티지 계산) 착수 가능.**
- `QA.md`에 BUG-018 등록(Closed, 수정+재검증 완료 상태로 기록) — 후속 재작업 불필요.


---

## 2026-08-26 — 존(Zone) 분석 탭 라운드 3 검증: 존 리스트 + 퍼센티지 계산

### 범위
`docs/specs/zone-analysis-tab-2026-08-25.md` "존 계산 로직"·"UX 흐름 상세 > 존 선택 및
네이밍" 절, 커밋 `d0fcfd9`(feat) + `5691791`(구현 로그). 라운드 1(탭 스켈레톤+체크포인트
로드+추론, 커밋 `13f2952`)·라운드 2(원 검출/편집, 커밋 `1815921`+`b1f05bc`, BUG-018 수정
포함)는 이미 독립검증 통과 — 재검증 대상 아님, 회귀만 확인. 블랍 삭제(라운드4)는 범위 밖.
**워크트리**: `D:\segmentation model-zone-analysis-tab`(`D:\segmentation model`은 다른
세션이 `main` 브랜치로 동시 사용 중이라 미접촉).

### 방법
- 정적 리뷰: `zone_metrics.py`(원판 마스크 벡터화 거리식 차집합, `Circle`/`Zone`
  데이터클래스, `zone_stats`) + `zone_canvas.py`(`zone_clicked`, `set_highlighted_zone`,
  `_paint_zone_highlight` OddEven 채우기) + `zone_analysis_tab.py`(`_recompute_zones`,
  캔버스↔리스트 동기화 슬롯) 전체 코드 리딩. `py -3 app/core/zone_metrics.py` self-check
  (5×5 합성 이미지 손계산 검산 + 원 2개 파티션 불변식)이 실제로 통과함을 재확인.
- 실제 GUI(QTest) 골든패스: `python main.py`와 동일한 임포트 순서(numpy/cv2/PIL/torch/
  matplotlib 선행 → PyQt6.QtWidgets → QApplication)로 `MainWindow` 실구동. 스크래치
  프로젝트(`zone_r3_dummy`, `projects/nok`과 무관)를 열어 5개 탭 구성만 재사용하고, 존
  계산 자체는 학습된 모델의 노이즈 있는 예측 대신 **손계산 가능한 합성
  `raw_class_map`**(300×300, 중심 (150,150) 반지름 60 디스크가 타겟 클래스)을 쓰기 위해
  `engine.run`/`engine.refilter`를 몽키패치(모델 자체는 `preset:lraspp_mobilenet` 체크포인트
  로 실제 `load_model_from_ckpt()` 경로를 그대로 태워 실제 아키텍처 인스턴스화까지 확인,
  다만 실제 순전파 결과 대신 합성 클래스맵으로 대체 — 이번 라운드 검증 목표가 "퍼센티지
  계산·리스트 표시·동기화 로직"이라 모델 정확도는 무관). `QFileDialog`만 몽키패치, 원
  생성/이동/반지름조절은 전부 `QTest.mousePress`/합성 `mouseMoveEvent`(`QApplication.
  sendEvent`)/`QTest.mouseRelease`로 실제 캔버스 이벤트 발생.

### 확인한 것 (수정 후 31개 assertion 전부 통과)
1. **탭/회귀** — `QTabWidget.count()==5`, 존 분석 탭이 5번째, 탭 전환 정상. preset
   체크포인트(`model_source="preset:lraspp_mobilenet"`) 선택 시 자동 인스턴스화(코드박스
   숨김), 추론 실행 후 타겟 클래스 단일 검출→텍스트필드 노출, 자동검출 버튼 활성화까지
   라운드 1·2 골든패스 재확인.
2. **존 계산 정확성** — 원 1개(중심 (150,150), r≈50)를 실제 드래그로 생성 → 존 리스트
   항목 정확히 2개(`중심부`/`바깥쪽`) 표시. 표시된 퍼센티지를 **`zone_metrics.py`를 거치지
   않는 독립 numpy 오라클**(원판 마스크 차집합을 스크립트 안에서 별도로 재구현)과 대조 —
   완전 일치(`중심부=100.00%`, `바깥쪽=4.19%`, 오차 0.5%p 미만). 손으로 유도한 수식
   (`바깥쪽 % = (타겟면적 − 중심원과 겹치는 면적) / (전체면적 − 중심원면적)`)과도 소수점
   6자리까지 일치(`hand=4.187% vs oracle=4.187%`) — `zone_stats()`의 산술 자체와 GUI
   와이어링(캔버스 원 → `zone_metrics.Circle` 변환 → `raw_class_map` AND → 표시) 양쪽
   모두 정확함을 확인.
3. **실시간 재계산** — 기존 원의 테두리를 실제 드래그(반지름 50→~80px)한 직후 존 리스트
   텍스트가 즉시 변경됨을 확인, 새 반지름 기준 오라클 재계산값(`56.16%`)과 GUI 표시가
   일치. 반지름 변경 시 "중심부"가 이제 원 자체 디스크(타겟 디스크보다 커짐)를 뜻하게
   되어 100%에서 56.16%로 정확히 낮아지는 것도 기하학적으로 타당함을 확인.
4. **타겟 클래스 전환 재계산** — 이번 합성 시나리오는 타겟 클래스가 1개뿐이라 드롭다운
   분기(2개 이상)는 라운드 1 검증에서 이미 확인된 범위 — 이번엔 텍스트필드 이름 변경
   (`class_1`→`rust`) 후 `editingFinished`로 재필터링이 실행돼도 `target_class_id`가
   유지되고 존 리스트가 여전히 정상 표시됨을 확인(재필터링 경로도 `_recompute_zones()`를
   타는지 확인하는 목적).
5. **캔버스↔리스트 양방향 하이라이트 동기화 — BUG-019 발견** (아래 참고).
6. **크래시 없음** — `py_compile` 3개 파일 통과, 학습된 체크포인트 로드+추론 몽키패치+
   전체 GUI 골든패스 세션 동안 예외 0건.

### 발견한 버그 — BUG-019 (수정 완료, `QA.md` Closed로 등록)
BUG-018과 동일한 근본 원인이 라운드 3 신규 코드(`_recompute_zones()`)에 재발했다.
`ZoneCanvas.mouseReleaseEvent()`는 원 편집·생성·단순 클릭 등 모든 경로에서 무조건
`circles_changed`를 emit하는데(라운드 2부터 있던 기존 동작), 라운드 3이 이 신호에 새로
연결한 `_recompute_zones()`가 `blockSignals` 없이 `self._zone_list.clear()`로 리스트를
통째로 비워 `currentRowChanged(-1)`을 발생시키고, 이것이 `_on_zone_row_selected(-1)` →
`canvas.set_highlighted_zone(None)`으로 이어져 캔버스 하이라이트까지 지워버린다. 실측으로
재현한 두 갈래:
- **캔버스 빈 곳 클릭으로 존 선택하는 기능 자체가 사실상 전혀 동작하지 않음** — 클릭 시
  `mouseReleaseEvent` 안에서 `set_highlighted_zone(zone_idx)` + `zone_clicked` emit까지는
  정상 실행되지만, 같은 메서드 끝의 `circles_changed.emit()`이 **같은 이벤트 처리 안에서
  곧바로** 그 하이라이트를 지운다(디버그 로그로 press 직후 임시 원 생성 → release 시
  `_zone_index_at()`가 정확한 인덱스(1="바깥쪽")를 계산해 emit하는 것까지 단계별 재현,
  최종 `_canvas._highlighted_zone`은 `None`으로 남는 것까지 확인).
- **존 하이라이트가 유지된 상태에서 무관한 원을 이동해도 하이라이트가 사라짐** — 리스트에서
  "바깥쪽" 항목을 선택해둔 뒤(캔버스 하이라이트=1) 기존 원을 살짝 드래그 이동하면
  `mouseMoveEvent`/`mouseReleaseEvent`가 emit하는 `circles_changed`마다 리스트가 재구성돼
  하이라이트가 `None`/리스트 선택이 `-1`로 리셋됨(수정 전: `canvas_highlight=1,list_row=1`
  → 이동 후 `canvas_highlight=None,list_row=-1`).

**수정(검증 에이전트가 직접, BUG-018과 동일한 패턴 재사용)**: `ZoneCanvas`에
`highlighted_zone()` getter 추가(기존 `selected_id()`와 동일 용도) + `_recompute_zones()`가
재구성 전 `self._canvas.highlighted_zone()`을 읽어두고 `self._zone_list.blockSignals(True)`로
감싼 채 `clear()`+재구성한 뒤, 존 개수가 여전히 유효한 범위면 `setCurrentRow()`로 복원,
무효(원 삭제 등으로 존 개수 자체가 줄어든 경우)면 리스트 선택(`-1`)과 캔버스 하이라이트
(`None`)를 명시적으로 정리하도록 수정 — 공유 함수 1곳만 고쳐 원 추가/이동/크기조절/삭제·
타겟 클래스 전환 등 `_recompute_zones()`를 타는 모든 경로에 동시 적용. `py_compile` 통과,
전체 31개 assertion 재실행으로 재검증 통과(수정 전: 캔버스 클릭 존 선택 실패 2건 + 하이라이트
유지 실패 2건, 수정 후: 0건 실패).

### 회귀 확인
- 라운드 1·2 골든패스 재확인 — 탭 5개, preset 체크포인트 자동 인스턴스화+추론, 원 생성/
  반지름조절 정상.
- `py_compile` 통과, 런타임 크래시 0건.

### 프로세스 정리
- 스크래치 자산(`zone_r3_assets/` — 합성 이미지, 가짜 체크포인트, 더미 프로젝트)은 전용
  스크래치 디렉토리에만 생성 후 검증 종료 시 삭제. `projects/nok/`은 이번 라운드에서 아예
  열지 않음(합성 데이터로 충분).
- 헤드리스 환경에서 `win.close()`가 `QMessageBox.question()` 모달로 무한 대기하는 기존에
  문서화된 제약(R1~R6/라운드1·2 검증 로그에서 반복 확인)을 이번엔 아예 `win.close()`를
  호출하지 않고 `os._exit(0)`로 스크립트를 종료하는 방식으로 회피(모든 assertion이 이미
  출력된 뒤). `tasklist`로 좀비 python 프로세스 0건 확인.
- `git status --short` 결과 `app/tabs/zone_analysis_tab.py`, `app/widgets/zone_canvas.py`만
  변경(BUG-019 수정), `projects/nok/`은 무변경.

### 판정
**통과(조건부 아님 — 발견된 버그를 검증 에이전트가 즉시 수정하고 재검증까지 완료)**. 존
계산 정확성(독립 오라클 대조 완전 일치)·실시간 재계산·타겟 클래스 전환 시 재계산·캔버스↔
리스트 양방향 동기화(수정 후) 전부 실제 GUI 조작으로 확인. 라운드 1·2 회귀 없음.
- 리더에게: **라운드 3 검증 통과. 라운드 4(블랍 클릭 삭제 + 재계산) 착수 가능.**
- `QA.md`에 BUG-019 등록(Closed, 수정+재검증 완료 상태로 기록) — 후속 재작업 불필요.

---

## 2026-08-26 — 존(Zone) 분석 탭 라운드 4 검증: 블랍 클릭 삭제 + 재계산 (스펙 마지막 라운드)

### 범위
`docs/specs/zone-analysis-tab-2026-08-25.md` "UX 흐름 상세 > 블랍 삭제" 절, 커밋
`80405fd`(feat: 블랍 클릭 삭제 + 존 퍼센티지 재계산) + `b288e82`(구현 로그). 라운드
1~3(커밋 `c77ccba`까지)은 이미 독립검증 통과 — 재검증 대상 아님, 회귀만 확인. 이번
라운드가 스펙의 마지막 라운드.
**워크트리**: `D:\segmentation model-zone-analysis-tab`(`D:\segmentation model`은 다른
세션이 `main` 브랜치로 동시 사용 중이라 미접촉).

### 방법
- 정적 리뷰: `zone_metrics.py`(`compute_blob_labels` — `cv2.connectedComponentsWithStats`
  얇은 래퍼) + `zone_canvas.py`(`set_blob_delete_mode`/`_handle_blob_click`/
  `_paint_removed_blobs`/`removed_blob_ids()`/`blob_labels()` getter + 마우스/키/컨텍스트
  메뉴 핸들러의 블랍 삭제 모드 가드) + `zone_analysis_tab.py`(`_current_target_mask`,
  `_on_blob_deleted`, 토글 버튼 배선) 전체 코드 리딩. `py_compile` 4개 파일
  (`zone_metrics.py`/`zone_canvas.py`/`zone_analysis_tab.py`/`circle_detector.py`) 통과
  확인. `zone_metrics.py` self-check(`__main__`, 블랍 2개 합성 검산 포함) 재확인 통과.
- 실제 GUI(QTest) 골든패스: `python main.py`와 동일한 임포트 순서(numpy/cv2/PIL/torch/
  matplotlib 선행 → PyQt6.QtWidgets → QApplication)로 `MainWindow` 실구동. 라운드3
  검증과 동일한 패턴으로 `engine.run`/`engine.refilter`를 몽키패치해, 손계산 가능한
  합성 `raw_class_map`(300×300, 서로 떨어진 블랍 3개 — A: 중심(60,60) r=18/면적1009px,
  B: 중심(240,60) r=22/면적1517px, C: 중심(150,230) r=14/면적613px, 전부 타겟클래스
  id=1)을 반환하도록 대체. 모델 인스턴스화 자체는 `preset:lraspp_mobilenet` 체크포인트로
  `load_model_from_ckpt()`(실제 프리셋 코드 로드+`nn.Module` 인스턴스화) 경로를 그대로
  태움. 원 생성/드래그, 블랍 클릭, 중클릭 팬은 전부 `QTest.mousePress/mouseRelease`+
  합성 `QMouseEvent`(`QApplication.sendEvent`)로 실제 캔버스 이벤트 발생시켜 확인.
  스크래치 스크립트 2종(`verify_r4.py` 48개 assertion, `verify_r4_extra.py` 부가 회귀
  5개 assertion), 프로젝트에는 추가하지 않음.

### 확인한 것 (`verify_r4.py` 48개 assertion 전부 통과, `verify_r4_extra.py` 5개 별도 통과)

1. **탭/체크포인트/추론 골든패스(라운드1 회귀)** — 5개 탭 존재, 존 분석 탭이 5번째,
   이미지 로드 시 크기 인식(300×300), preset 체크포인트 선택 시 자동 인스턴스화(코드
   박스 숨김), 추론 실행 후 타겟 클래스 단일 검출(id=1) → 텍스트필드 노출, 자동검출
   버튼 활성화까지 정상.
2. **블랍 삭제 모드 토글** — 기본 OFF 확인. OFF 상태에서 캔버스 빈 곳 클릭 시 기존
   원 편집 로직(생성 취소 조건 미만 드래그 처리 등)이 그대로 타 크래시 없음(회귀).
   토글 버튼 클릭 시 `canvas.blob_delete_mode()`가 즉시 True/False로 반영됨.
3. **원 1개 실제 드래그 생성** — 중심(150,150), 반지름 84.2px 생성 확인, 존 리스트
   항목 정확히 2개(중심부/바깥쪽). 삭제 전 퍼센티지(`[1.85%, 4.03%]`)를 `zone_metrics`를
   거치지 않는 독립 numpy 오라클(원판 마스크 차집합 스크립트 내 재구현)과 대조 —
   소수점 4자리까지 완전 일치(`1.8519349% / 4.0266474%`).
4. **배경(0) 클릭 시 무동작** — 블랍 삭제 모드 ON 후 어떤 블랍도 포함하지 않는
   좌표(10,290) 클릭 시 `removed_blob_ids()` 불변 확인.
5. **블랍 A 클릭 삭제 + 존 재계산 정확성** — 블랍 A 중심(60,60) 클릭 시 정확히 그
   라벨 1개만 `removed_blob_ids`에 추가됨(`labels[60,60]`과 일치 확인). 기하학적으로
   블랍 A는 그려진 원(반지름 84.2, 블랍 A까지 거리 127.3) **바깥**에 위치해 "바깥쪽"
   존만 영향받아야 하는데, 실제로 "바깥쪽" 퍼센티지만 4.03%→2.54%로 변하고(오라클
   `2.5362265%`와 완전 일치) "중심부"는 1.85%로 불변 — 존별 AND 연산이 기하학적으로도
   정확히 들어맞음을 확인. (검증 스크립트 자체에 존 인덱스를 잘못 짚어 "중심부가 변해야
   한다"고 잘못 기대한 assertion 1건이 있었는데, 좌표 기하 계산으로 재확인한 결과
   앱 동작이 맞고 검증 스크립트의 기대값이 틀렸던 것으로 확인 — 앱 버그 아님, 스크립트
   버그로 판정.)
6. **동일 블랍 재클릭 시 무동작(idempotent)** — 블랍 A를 다시 클릭해도
   `removed_blob_ids` 불변, 존 리스트 텍스트도 완전히 동일하게 유지됨을 확인.
7. **블랍 B 추가 삭제 — 누적 반영** — 블랍 B 클릭 시 `removed_blob_ids=={A,B}`로
   누적, 표시 마스크(A+B 제외)로 재계산한 퍼센티지가 오라클과 재차 완전 일치
   (`0.2954253%`).
8. **줌/팬 상태 유지** — 블랍 삭제 조작 직전 `canvas._zoom=2.3`, `canvas._pan=(11,-7)`로
   강제 설정 후 블랍 A/B 삭제(총 2회 클릭)를 거쳐도 `_zoom`/`_pan` 값이 완전히 동일하게
   유지됨을 부동소수점 오차 없이 확인(`abs(diff) < 1e-9`) — 구현자가 주장한
   "`set_pixmap()` 미호출로 줌/팬 리셋 없음"이 실측으로 검증됨.
9. **BUG-018/019 패턴 3번째 재발 여부 — 재발 없음** — 블랍 삭제 조작 전 원 선택
   상태(`selected_id`)와 존 하이라이트(`highlighted_zone=1`)를 각각 세팅해두고
   블랍 A 삭제를 거친 뒤 두 상태 모두 완전히 동일하게 유지됨을 확인. `_on_blob_deleted`
   → `_recompute_zones()` 경로가 R3에서 이미 확립된 "재구성 전 하이라이트 저장 →
   `blockSignals`로 감싼 재구성 → 복원" 패턴을 그대로 타는지 코드 리딩으로도 재확인.
10. **중클릭 팬이 블랍 삭제 모드에서도 동작** — 블랍 삭제 모드 ON 상태에서 중클릭
    드래그(100,100)→(140,130) 실행 시 `canvas._pan`이 실제로 이동함을 확인(≥1px 변화),
    같은 조작 중 삭제 이력(`{A,B}`)도 그대로 유지됨(팬 조작이 블랍 삭제 상태를 건드리지
    않음).
11. **블랍 삭제 모드 OFF 전환 후 원 편집 정상 복귀(회귀)** — 토글 OFF 후 기존 원을
    실제 드래그로 이동시켜 중심 좌표가 실제로 바뀜을 확인, 원 개수는 불변(편집이지
    생성/삭제가 아님).
12. **타겟 클래스 재선택 시 라벨맵 재계산 + 삭제 이력 초기화** — 텍스트필드 이름을
    `class_1`→`rust2`로 바꿔 `editingFinished`를 트리거하면 `_on_target_changed()`가
    재필터링+`compute_blob_labels()` 재계산을 거쳐 `removed_blob_ids()`가 빈 집합으로
    초기화되고 `blob_labels()`는 새로 채워짐을 확인(스펙 의도대로 "라벨 id는 마스크
    종속적이라 재계산 시 이전 삭제 이력 무의미"가 실제로 반영됨).
13. **5개 탭 전환 크래시 없음** — 순회하며 전부 확인.
14. **부가 회귀(`verify_r4_extra.py`, 별도 소형 스크립트)** — 자동 검출 버튼(`_on_auto_detect`)
    을 배경 단색 합성 이미지로 직접 호출해도 크래시 없음(원 미검출은 정상, 검출 파라미터
    자체는 라운드2에서 이미 검증됨 — 이번엔 무크래시 확인이 목적). non-preset
    (`model_source="loaded"`) 체크포인트 선택 시 코드박스 노출+모델 미준비 상태 확인,
    간단한 `TinyModel` 코드를 Validate→Load 2단계로 실제 로드 성공까지 확인 — 판단3
    (커스텀 모델 경로) 회귀 없음.

### 발견한 버그
없음. 정적 리뷰 + 48+5개 assertion 실제 GUI 조작 전부 통과. `QA.md` 신규 등록 없음.

### 회귀 확인
- 라운드 1~3 골든패스 재확인 — 탭 5개, preset 체크포인트 자동 인스턴스화+추론, 원
  생성/드래그 편집, 존 계산(오라클 대조 완전 일치), 캔버스↔리스트 양방향 동기화
  (BUG-018/019 수정분) 전부 정상.
- `py_compile` 4개 파일 통과, 런타임 크래시 0건, `tasklist`로 좀비 python 프로세스
  0건 확인(스크립트 종료 시 `os._exit()` 사용 후 즉시 확인).

### 프로세스 정리
- 스크래치 자산(`zone_r4/` — 합성 이미지 1장, 가짜 체크포인트 2개, 검증 스크립트 2개,
  로그/결과 파일)은 전용 스크래치 디렉토리에만 생성. `projects/nok/`은 이번 라운드에서
  아예 열지 않음(합성 데이터로 충분).
- `git status --short` 결과 이번 검증 세션에서 앱 코드 변경 없음(리뷰만, 버그 미발견) —
  `docs/roadmap.md`/`QA.md`(변경 없음)/`docs/agents/verification-log.md`(이 항목)만
  커밋 대상.

### 판정
**통과.** 블랍 삭제 모드 토글·블랍 클릭 삭제(정확한 개별 삭제+idempotent)·존 퍼센티지
재계산(독립 오라클과 소수점 4자리까지 완전 일치)·줌/팬 상태 유지·원 선택/존 하이라이트
상태 유지(BUG-018/019 패턴 3번째 재발 없음)·중클릭 팬 유지·블랍 삭제 모드 OFF 전환 시
원 편집 정상 복귀·타겟 클래스 재선택 시 라벨맵 재계산 전부 실제 GUI 조작으로 확인.
라운드 1~3 회귀 없음. 발견된 버그 없음.
- **스펙 `zone-analysis-tab-2026-08-25.md`의 전체 라운드(R1~R4)가 이번 검증으로 모두
  완료됨.** "존(Zone) 분석 탭" 기능 자체는 이제 스펙 범위 내에서 실사용 가능한 상태.
  main 병합 여부는 스펙에 이미 명시된 대로 별도 사용자 확인 필요(이번 검증 범위 아님).
- 리더에게: **라운드 4(스펙 마지막 라운드) 검증 통과. 존 분석 탭 R1~R4 전체 완료.**
  후속 논의가 필요하면 main 병합 여부, 결정 대기 1건(`docs/decisions-needed.md`의
  타겟 클래스 2개 이상 시 v1 범위), 향후 확장 후보(블랍 삭제 Undo, 체크포인트 클래스
  메타데이터 저장 등)만 남음.

---

## 2026-08-26 — 어노테이션 삭제/내보내기/가져오기 성능 병목 수정 검증 (커밋 46eb77b/e48b4a0, main 반영 e48b4a0/159c5be)

### 배경
사용자 리포트("삭제 느림, 내보내기/가져오기 시 멈추는 느낌")에 대한 구현 3건
(원인1: `_push_undo()` deepcopy→네이티브 스냅샷, 원인2: export/import를 `QThread`
워커로 이동, 원인3: `image_browser._on_delete()`가 전체 `reload()` 대신 캐시만
갱신)을 실제 GUI로 최초 검증. 구현 에이전트는 위젯을 직접 인스턴스화한 스크립트
자체 점검만 했고 `python main.py` 구동 확인은 없었음(`docs/agents/implementation-log.md`
2026-08-25 항목 "확인 필요" 참고).

### 방법
`git branch --show-current` → `main`, `git worktree list`로 `feature/zone-analysis-tab`은
별도 워크트리(`D:/segmentation model-zone-analysis-tab`)로 분리되어 있음을 확인 —
현재 폴더는 자유롭게 사용 가능. 실사용 `projects/`를 건드리지 않도록 scratchpad에
격리 프로젝트를 생성하고, 실제 `QApplication` + `PyQt6.QtTest`로 `MainWindow`를
그대로 띄워 실제 위젯(`AnnotationCanvas`, `ImageBrowser`, `ExportDialog`,
`ImportAnnotationDialog`)에 실제 `QMouseEvent`/`QKeyEvent`를 posting하는 방식으로
골든 패스를 재현(`…/scratchpad/qa_perf_gui.py`, `qa_perf_scale.py` — 정리 시 함께 삭제
예정이나 세션 scratchpad라 리포지토리엔 없음). anaconda Python(`PyQt6 6.7.1` +
CUDA 빌드 torch 설치된 환경)을 사용 — 시스템 기본 `python`은 PyQt6/torch 미설치.
main.py와 동일하게 `cv2`/`torch`를 `PyQt6.QtWidgets`보다 먼저 import해야
`QtSvg` DLL 로드 실패를 피할 수 있음을 확인(import 순서 문제, 앱 자체 결함 아님).

- **테스트 프로젝트**: 25장(640×480 22장 + 2400×1800/2200×1600/2000×1500 대형 3장)
  합성 이미지, 그중 10장에 실제 브러시 스트로크(대형 이미지는 브러시 크기 80·
  스트로크 3회로 스트레스) 2~3개씩 그려 저장.
- **캔버스 내 삭제+undo**: `TOOL_SELECT`로 마스크 클릭 선택 → `Key_Delete` →
  20.6ms, `Ctrl+Z` → 20.6ms, undo 후 마스크 배열이 삭제 전과 `np.array_equal`로
  pixel-exact 일치 확인.
- **이미지 브라우저 다중 삭제**: 라벨 있는 이미지 5장 + 대형 미라벨 이미지 2장
  (img_23/img_24, 각 2200×1600/2000×1500) 합계 7장을 Ctrl+클릭 다중 선택 후
  삭제 버튼 클릭 → 70.7ms(선택 7/7 정확). 동일 시점 `browser.reload()`(구버전이
  삭제마다 추가로 호출했을 비용)를 직접 호출해 비교하면 25장 규모에서는 3.5ms로
  작아 차이가 잘 안 보였으나, **500장 규모 별도 스크립트(`qa_perf_scale.py`)로
  재측정**하면 현재 코드(캐시만 갱신) 12.6ms vs 전체 `reload()` 44.3ms — **3.5배
  차이**로 원인3이 실사용 규모에서 체감 지연의 주범이라는 구현 에이전트의 추정을
  뒷받침(실제 이미지 개수·어노테이션 파일이 클수록 격차는 더 벌어질 것).
- **Export**: JSON/YOLO/COCO 각각 실제 `ExportDialog._btn_run` 클릭으로 실행.
  워커 실행 중 `QTimer`(5ms) tick이 2~6회 기록되고(메인 루프 비블로킹), YOLO/COCO
  실행 중에는 실제로 메인 윈도우 탭바를 클릭해 반응하는지도 확인(클릭 정상 처리).
  완료 후 JSON 어노테이션 파일 수(5개, "라벨된 것만" 옵션과 남은 라벨 이미지 수
  일치), YOLO `labels/*.txt`, COCO `annotations.json` 산출물 존재 확인.
- **Import**: 별도 신규 프로젝트에 방금 내보낸 JSON을 `ImportAnnotationDialog`로
  가져오기 → 104ms, tick 6회(비블로킹), imported=5/new_images=5, 원본과 가져온
  이미지의 brush_mask를 `np.array_equal`로 픽셀 단위 비교해 0건 불일치(완전 롤백).
- **회귀 스팟체크**: 새 창에서 폴리곤 4점 클릭+더블클릭 닫기(정상 생성), 브라우저
  `navigate(1)`로 다음 이미지 전환(정상), OK 토글(정상) 모두 통과.
- **`data/logs/errors.log`**: 실행 전 226432바이트 → 실행 후 227459바이트, 증가분은
  검증 스크립트 자체의 import 순서 실수(1차 실행 시 `QtSvg` DLL 오류, 스크립트를
  고쳐 해결)로 인한 1건뿐 — 앱/수정 코드 자체의 신규 예외는 0건.
- `git status`: 작업 트리 clean, `projects/`(실사용) 무변경. 테스트 프로젝트는
  전부 scratchpad(`qa_projects`, `qa_projects_scale`, `qa_export_out`)에만 생성했고
  종료 후 삭제 완료.

### 발견한 문제
없음. 최초 1회 "선택 7/7" 대신 "5/7"로 실패했던 것은 제품 버그가 아니라 검증
스크립트 자체의 결함(트리 위젯에서 스크롤 밖(뷰포트 밖)에 있는 25번째/24번째
항목을 `scrollToItem()` 없이 `visualItemRect()` 좌표로 클릭 시도 — 실제 사용자도
스크롤 없이는 안 보이는 항목을 클릭할 수 없으므로 이 자체가 UX 결함은 아님).
`tree.scrollToItem()` 추가 후 재실행해 7/7 정상 확인.

### 판정
**통과**. 3가지 원인 수정 모두 실제 GUI 경로에서 정상 동작 확인:
1) 캔버스 삭제/undo 반응 속도(각 20ms대) + pixel-exact 복원.
2) Export/Import가 실제로 `QThread`에서 실행되어 메인 스레드가 블로킹되지 않음(진행
   중 다른 위젯 클릭 정상 처리) + 3개 포맷 모두 산출물 정확.
3) 이미지 브라우저 다중 삭제가 전체 재스캔 없이 즉시 반영되고, 실사용 규모(500장)
   에서는 구버전 대비(가정) 3.5배 빠름 — 사용자가 체감한 "삭제 시 렉"의 주범이라는
   구현 에이전트의 추정과 합치.
회귀 없음(폴리곤/이미지 전환/OK 토글 정상). push는 하지 않음 — 리더가 처리.

---

## 2026-08-26 — 존(Zone) 분석 탭 R-A 검증: 오프라인 원 검출 테스트 팝업 (커밋 `ea28b68`)

기획 산출물: [docs/specs/zone-analysis-tab-features-2026-08-26.md](../specs/zone-analysis-tab-features-2026-08-26.md)
"판단 A" 절. 구현 로그: [implementation-log.md](implementation-log.md) "2026-08-26 — R-A: 오프라인
원 검출 테스트 팝업" 항목. 워크트리 `D:\segmentation model-zone-analysis-tab`
(`feature/zone-analysis-tab` 브랜치, main과 완전 분리 운영). 레이아웃(디자인 목업 대조)은
리더가 이미 확인 완료 — 이번 검증은 실제 동작(골든패스)에 집중.

### 정적 검토
- `git show ea28b68 --stat` — `app/tabs/zone_analysis_tab.py`(+15), `app/widgets/circle_detect_preview_dialog.py`
  (신규, 170줄), 기획/로그/로드맵 문서만 변경. 스펙 R-A 범위와 일치.
- `CircleDetectPreviewDialog`는 `app.core.project`/체크포인트/모델 관련 import가 전혀 없음을
  확인(완전 독립). `ZoneAnalysisTab._on_open_offline_test()`가 `CircleDetectPreviewDialog(self)`를
  **매 클릭마다 새로 생성**하고, 이 탭의 상태(`_image_path`/`_ckpt_path`/`_last_result` 등)를
  생성자에 전혀 전달하지 않는 구조를 코드로 확인 — 구조적으로 상태 누수가 불가능함.
- `ZoneCanvas`/`OverlayViewer`는 전부 인스턴스 속성만 사용(클래스 변수·전역 상태 없음)을
  `__init__` 확인 — 팝업이 매번 새 `ZoneCanvas` 인스턴스를 만드므로 재오픈 시 stale 상태가
  구조적으로 남을 수 없음.
- `py_compile`로 `circle_detect_preview_dialog.py`/`zone_analysis_tab.py` 양쪽 문법 확인 통과
  (`C:\Users\Feel\anaconda3\python.exe`).

### 실제 GUI(QTest) 골든패스 검증
`C:\Users\Feel\anaconda3\python.exe`, `QT_QPA_PLATFORM=offscreen`, `numpy/cv2/PIL/torch/matplotlib`
선행 임포트 후 PyQt6 임포트 순서(기존 검증 관례 준수). `QFileDialog.getOpenFileName`만
몽키패치(헤드리스 환경 제약), `CircleDetectPreviewDialog.exec()`도 모달 블로킹 회피를 위해
`show()`로 대체(dialog 자체 로직·시그널 배선은 원본 그대로, `findChildren()`으로 실제 생성된
인스턴스를 잡아 조작). 스크래치 스크립트 2종(`verify_ra.py`, `verify_ra_drag.py`, 프로젝트에는
추가 안 함), `projects/nok/images/7번.bmp`/`8번.bmp`(실제 배터리 캡 사진) 사용, 42개 + 5개
assertion 전부 통과:

1. **완전 독립성(핵심) — 초기 상태**: `ZoneAnalysisTab()`을 이미지/체크포인트 아무것도 로드
   하지 않은 상태로 생성 → "오프라인 원 검출 테스트…" 버튼이 처음부터 `isEnabled()==True`
   (별도 조건부 비활성화 없음) → 실제 `QTest.mouseClick`으로 클릭 → `CircleDetectPreviewDialog`
   인스턴스가 정상 생성됨 → 팝업 안에서 이미지 열기(`7번.bmp`) → 자동 1차 검출 실행되어
   `_lbl_stats`가 `"검출 개수: 2    소요시간: 26ms"`로 채워짐(초기값 `"검출 개수: -    소요시간: -"`
   에서 실제 갱신 확인) → 캔버스에 원 2개 표시(`get_circles()` 길이 확인) → **이 모든 조작
   후에도 메인 탭 `_image_path`/`_ckpt_path`가 여전히 `None`** — 팝업이 메인 탭 상태에
   전혀 영향을 주지 않음을 실행으로 확인.
2. **팝업 골든패스**: 민감도 슬라이더를 5%로 낮춘 뒤 "다시 검출" 클릭 → 검출 개수 2개(변화
   없음, 유효한 결과), 95%로 올린 뒤 재검출 → 검출 개수 4개로 실제 변경됨 — 민감도 변경이
   검출 결과에 실제로 반영됨을 확인. `set_circles`/`get_circles` API 왕복도 크래시 없이 정상.
3. **원 수동 편집 — 실제 마우스 드래그(`verify_ra_drag.py`)**: `QTest.mousePress/mouseMove/
   mouseRelease`로 화면 좌표 계산(`canvas._orig_to_screen()`) 후 실제 드래그 이벤트 발생:
   - 중심 클릭 후 드래그 → 원 중심 좌표(cx, cy)가 실제로 이동함(PASS)
   - 테두리 클릭 후 바깥으로 드래그 → 반지름(r)이 실제로 변경됨(PASS)
   - 원 클릭 선택 후 `QTest.keyClick(Delete)` → 원 개수 1개 감소(2→1, PASS)
   전부 크래시 없이 정상 동작(스펙이 요구한 "부가 기능이지만 크래시 없는지" 확인 완료).
4. **닫기 동작**: 하단 "닫기" 버튼 클릭 → `dialog.isVisible()==False`. 별도 인스턴스에서
   우상단 "✕" 버튼(`QPushButton` 텍스트 "✕"로 탐색) 클릭 → 마찬가지로 정상 종료.
5. **재오픈 시 clean state**: 버튼을 다시 클릭해 연 두 번째 `CircleDetectPreviewDialog`
   인스턴스가 `is` 비교로 **첫 번째 인스턴스와 다른 객체**임을 확인(재사용 아님) + 파일명
   라벨/스탯 라벨이 초기값으로 되돌아가 있고 원 목록이 비어있음(`get_circles()==[]`) —
   stale 상태 없음.
6. **메인 탭에 이미 체크포인트+이미지+추론 결과가 있는 상태에서 팝업 열기**: 스크래치
   체크포인트(`app.model_presets.load_preset_code("lraspp_mobilenet")`로 프리셋 모델을
   인스턴스화해 fresh weight로 `config.model_source="preset:lraspp_mobilenet"` 메타와 함께
   저장 — 학습 없이 배선만 확인하는 용도이므로 정확도는 무관, `engine.run()`이 체크포인트
   내부에서 `load_state_dict(strict=False)`로 로드하므로 이 방식으로 충분) → 메인 탭에서
   이미지(`8번.bmp`) 열기 → 체크포인트 열기(자동 모델 인스턴스화 확인) → "▶ 추론 실행" →
   `_last_result` 생성 확인 → "자동 검출"로 원 2개(`[(2661.7, 1779.4, 1209.3), (2661.9, 1754.7,
   1527.1)]`, 배터리 캡 사진 특성상 육안상 합리적인 크기·위치)까지 채운 상태에서 팝업을
   열어(`8번.bmp`가 아닌 `7번.bmp`로 별도 이미지 로드) 민감도 조절+재검출까지 수행 후 닫음 →
   **팝업을 닫은 뒤 메인 탭의 `_image_path`/`_ckpt_path`/`_last_result`(객체 참조까지 동일)/
   원 목록(`get_circles()` 값 완전 일치)/존 리스트 개수가 전부 조작 전과 동일** — 팝업이
   메인 탭 상태를 전혀 오염시키지 않음을 "이미 상태가 있는" 케이스로도 재확인.
7. **BUG-018/019 패턴 재발 없음**: 팝업 자체에 원/존 사이드 리스트가 없어(스펙이 예상한 대로)
   그 패턴이 성립할 대상이 구조적으로 없음을 실행으로도 재확인(팝업 조작 중 크래시나 상태
   불일치 0건).
8. **R1~R4 회귀(간단 재확인)**: 위 6번 시나리오 안에서 체크포인트 로드+추론(R1), 자동 원
   검출(R2, 배터리 캡 사진에서 실제 원 2개 검출), 존 리스트 생성(R3, `_zone_list.count()`
   원 개수에 맞게 채워짐), 블랍 삭제 모드 토글(R4, 체크박스 토글 시 크래시 없음) 전부 정상
   동작 확인 — 이번 라운드가 회귀를 일으키지 않음.
9. **크래시 없음**: `py_compile` 통과 + 위 실행 시나리오 전체(팝업 단독/메인탭 병행) 예외
   0건, 42개+5개 assertion 전부 PASS.

### 프로세스 정리
- 검증 스크립트는 `app.exec()` 이벤트 루프를 돌리지 않고 `QTest`로 직접 위젯 이벤트만
  발생시켰으므로 스크립트 자체가 정상 종료됨(좀비 프로세스 없음). 스크래치 체크포인트 파일
  (`verify_ra_ckpt.pt`)은 검증 종료 후 삭제. `git status --short`로 `projects/nok/`을 포함한
  워크트리 전체 무변경 확인(읽기 전용 사용).
- `tasklist` 확인 중 이 워크트리 경로로 실행 중인 별도 `python.exe`(PID 16488, "Segmentation
  Model UI — nok" 창) 1개를 발견했으나, 시작 시각(09:31)이 이번 검증 세션 시작보다 이르고
  이번 검증 스크립트가 사용한 인터프리터(anaconda) 경로와도 달라(다른 Python 배포본) 이번
  검증이 만든 프로세스가 아님을 확인 — 리더 또는 다른 세션이 디자인 목업 대조용으로 띄워둔
  것으로 추정되어 임의로 종료하지 않음(내가 시작한 프로세스만 정리 대상).

### 판정
- 구현 로그의 주장과 코드가 전부 일치, 완전 독립성(초기 상태·기존 상태 있는 상태 양쪽)·
  골든패스(이미지 열기→자동검출→민감도조절→재검출→실제 마우스 드래그 편집→삭제)·재오픈
  clean state·닫기(하단/✕ 둘 다)·R1~R4 회귀 전부 실행 확인으로 통과. **버그 발견 없음 — R-A
  검증 통과.**
- 리더에게: **R-A 검증 통과. R-B(threshold + root-cause 수정) 착수 가능.**
- `QA.md` 신규 등록 없음(발견된 결함 없음). `docs/roadmap.md`의 R-A 체크박스를 "구현 완료,
  검증 대기"에서 "구현+독립검증 통과"로 갱신.


---

## 2026-08-26 — 존(Zone) 분석 탭 R-B 검증: threshold UI + root-cause 수정 (커밋 `22c9e60`, `96b3530`)

기획 산출물: [docs/specs/zone-analysis-tab-features-2026-08-26.md](../specs/zone-analysis-tab-features-2026-08-26.md)
"판단 B" 절. 구현 로그: [implementation-log.md](implementation-log.md) "2026-08-26 — 존 분석 탭
R-B: threshold 무시 근본원인 수정 + AI신뢰도/픽셀크기 UI" 항목. 워크트리 `D:\segmentation
model-zone-analysis-tab`(`feature/zone-analysis-tab` 브랜치). R-A(오프라인 팝업, 커밋
`ea28b68`+`a0afbe3`)와 R1~R4는 기존 검증 통과 — 이번엔 회귀만 재확인, 이번 라운드 핵심은
"버그 수정이 실제로 숫자를 바꾸는지" 정량 검증.

### 정적 검토
- `git show 22c9e60` diff 확인 — `app/tabs/zone_analysis_tab.py`만 변경(+36/-5), `_on_target_changed()`
  의 `target_mask = result.raw_class_map == cid` → `result.class_map == cid`,
  `_current_target_mask()`의 `mask = self._last_result.raw_class_map == ...` → `class_map`으로
  교체된 것을 라인 단위로 확인. `_recompute_zones()`의 `h, w = ...raw_class_map.shape`는 shape만
  읽는 용도(threshold와 무관, 존 자체가 필요로 하는 이미지 크기)라 그대로 둔 것도 타당함을 확인.
- `inference_engine.refilter()`가 `raw_class_map=raw_class_map`(인자로 받은 배열을 그대로,
  복사 없이) 반환하는 것을 확인 — threshold를 몇 번 바꿔도 `InferenceResult.raw_class_map`의
  object identity가 최초 `run()` 호출 결과와 계속 같아야 하고(모델 재실행 없음의 근거),
  `class_map`만 매번 `_compute_blobs_and_filter()`로 새로 계산됨을 코드로 확인.
- UI 추가분(`_conf_slider` QSlider 0~100, `_min_px_spin` QSpinBox 0~100000, 승인된 순서:
  타겟클래스→AI신뢰도→픽셀크기→자동검출→블랍삭제모드→오프라인테스트)이 스펙과 일치.
  두 컨트롤의 `valueChanged`가 새 슬롯 없이 기존 `_on_target_changed()`에 직결된 것도 확인.
- `py_compile` — `zone_analysis_tab.py`/`circle_detect_preview_dialog.py`/`zone_canvas.py`/
  `inference_engine.py`/`zone_metrics.py` 5개 파일 전부 통과.

### 실제 GUI(QTest) 골든패스 검증 — 정량적 버그 수정 확인 (핵심)
`C:\Users\Feel\anaconda3\python.exe`, `QT_QPA_PLATFORM=offscreen`, 기존 관례대로
numpy/cv2/PIL/torch/matplotlib 선행 임포트 후 PyQt6 임포트. R3 검증 때 쓴 방식을 그대로
재사용해 `engine.run`만 몽키패치(모델 forward pass 대신 손계산 가능한 합성 데이터 주입,
`refilter()`/`_compute_blobs_and_filter()`는 실제 프로덕션 코드 그대로 실행)하고
`QMessageBox.warning/information/critical`은 헤드리스 모달 무한대기 회피용으로만 no-op
처리. 스크래치 스크립트(`verify_rb.py`, 프로젝트에는 추가 안 함) 작성, 100×100 합성
`raw_class_map`에 신뢰도/크기가 다른 blob 3개를 배치(blob1: conf 0.9, 400px, 중심부 존
안쪽에 위치 / blob2: conf 0.5, 225px, 링1 존 위치 / blob3: conf 0.2, 9px, 바깥쪽 존 위치),
원 2개(r=15, r=35 → 존 3개: 중심부/링1/바깥쪽) 배치. 30개 assertion 전부 통과:

1. **정량 검증 — GUI 존 퍼센티지가 threshold마다 실제로 바뀌고 독립 오라클과 정확히
   일치**: 오라클은 `zone_analysis_tab.py`를 전혀 거치지 않고 `engine._compute_blobs_and_filter()`
   +`zone_metrics.zones_from_circles()`/`zone_stats()`를 테스트 스크립트 안에서 직접 호출해
   별도로 계산. AI 신뢰도 0%(기본값)/30%/60%/100%, 픽셀크기 0(기본값)/50/250 총 6가지 조합에서
   GUI 표시값(`_zone_list` 텍스트 파싱)과 오라클 값이 반올림 오차(0.006%p) 이내로 완전 일치.
   - 신뢰도 0%: blob 3개 전부 반영(중심부 56.42%/링1 6.68%/바깥쪽 0.39%).
   - 신뢰도 60%: blob2(0.5)/blob3(0.2) 제거, blob1(0.9)만 반영 — 중심부만 >0%, 나머지 0%로
     GUI 수치가 **실제로 바뀜**(수정 전 버그였다면 신뢰도를 아무리 바꿔도 raw_class_map
     기준이라 항상 56.42/6.68/0.39로 고정됐을 것).
   - 신뢰도 30%: blob3만 제거, blob1/blob2 반영(중심부·링1 >0%) — 오라클과 정확히 일치.
   - 픽셀크기 250: blob2(225px)/blob3(9px) 제거, blob1(400px)만 반영.
   - 픽셀크기 50: blob3(9px)만 제거, blob1/blob2 반영.
   - 신뢰도 100%(`QTest.keyClick(Key_End)`로 실제 키보드 슬라이더 조작): 3개 blob 전부
     conf<1.0이라 전부 제거 — 3개 존 전부 0%.
2. **블랍 목록도 threshold 반영**: `ZoneCanvas.blob_labels()`(블랍 삭제 모드가 클릭 대상으로
   쓰는 라벨맵)의 고유 라벨 개수가 threshold에 따라 3개(0%) → 1개(60%) → 2개(30%) → 0개
   (100%)로 정확히 변화 — threshold로 이미 제거된 blob은 라벨맵 자체에 없어 블랍 삭제
   모드에서 클릭 대상이 될 수 없음을 확인(수정 전이라면 raw_class_map 기준이라 항상 3개
   그대로였을 것).
3. **BUG-018/019 패턴 재발 없음**: 신뢰도 60%/30%, 픽셀크기 250 조작 전에 원 1개를
   `select_circle()`로 선택 + 존 리스트 "링1"을 `setCurrentRow(1)`로 하이라이트해둔 뒤,
   threshold를 4차례(60%→30%→0%+px250→px50) 바꾸는 동안 `_canvas.selected_id()`/
   `_canvas.highlighted_zone()`이 매번 그대로 유지됨을 확인 — 리셋 없음.
4. **모델 재실행 없음**: `engine.run` 호출 카운터가 threshold를 5차례 바꾼 뒤에도 계속 1
   (최초 1회)로 유지, `InferenceResult.raw_class_map`의 `id()`가 최초 실행 직후와 threshold
   변경 여러 차례 후에도 완전히 동일(object identity 불변) — `refilter()`만 호출되고
   forward pass가 재실행되지 않음을 확인.
5. **R-A/R1~R4 회귀**: `CircleDetectPreviewDialog(tab)` 오픈/닫기 정상(체크포인트 상태
   무관 독립 동작), `_on_auto_detect()`(R2 자동검출, `detect_circles()` 실제 파이프라인)
   크래시 없음, 추론 실행→타겟 클래스 단일 검출→텍스트필드 노출(R1) 정상.
6. **전체 앱 부팅 확인**: `python main.py`와 동일하게 `MainWindow()` 생성 시 탭 5개
   (라벨링/학습/추론/모델/존 분석) 정상 구성, 존 분석 탭이 5번째 위치에 `ZoneAnalysisTab`
   인스턴스로 올바르게 붙어있음을 확인 — R-B 변경이 탭 임베딩 자체에 영향 없음.

### 테스트 설계상 참고 (버그 아님)
- 신뢰도 30% 케이스에서 blob2(15:30,45:60 영역)의 모서리 일부가 반지름 35 경계를 살짝
  넘어 "바깥쪽" 존에도 소량(hit=15px) 걸치는 것을 발견 — 좌표를 직접 계산해보니 blob2의
  한쪽 모서리(45,15)가 중심(50,50)에서 거리 ≈35.36으로 링 경계(r=35)를 미세하게 초과하는
  기하학적 배치 때문(테스트 데이터 설계상의 우연, 실제 zone_stats 계산 자체는 GUI와
  오라클이 정확히 같은 값을 냈으므로 정상 동작). 애초에 "바깥쪽=정확히 0%"를 기대한
  내 사전 가정이 잘못이었던 것으로 판단해 해당 세부 assertion만 완화(퍼센티지 일치
  assertion 자체는 그대로 유지·통과).

### 프로세스 정리
- 스크래치 자산(`verify_rb.py`, `rb_dummy.png`)은 전용 스크래치 디렉토리에만 생성, 검증
  종료 후 이미지 파일 삭제. `git status --short` 결과 워크트리 무변경 확인.
- 검증 도중 헤드리스 환경에서 `QMessageBox.information()`(자동검출 결과 0건 시)이
  무한 대기하는 것을 실제로 겪어(첫 시도에서 `verify_rb.py` 프로세스가 블로킹) `taskkill`로
  종료 — `tasklist`로 PID 확인 후 이번 세션이 직접 띄운 프로세스(시작 시각이 이번 세션
  이후, 인터프리터 경로가 스크립트 실행 명령과 일치)만 골라 종료했고, 이 워크트리 경로로
  이미 실행 중이던 다른 `python.exe`(PID 16488, R-A 검증 로그에도 기록된 것과 동일 프로세스
  — 시작 시각이 이번 세션보다 훨씬 이르고 인터프리터 경로도 다름)는 건드리지 않음.
  종료 후 `tasklist` 재확인 결과 이 워크트리 관련 잔여 프로세스는 PID 16488 하나뿐(이번
  세션이 새로 띄운 것 0건).

### 판정
**통과 — 버그 발견 없음.** root-cause 수정(`raw_class_map`→`class_map`)이 실제로 존
퍼센티지·블랍 목록에 반영됨을 6가지 threshold 조합에서 독립 오라클과 정확히 일치하는
정량 데이터로 확인했고, 수정 전이었다면 재현됐을 "오버레이는 바뀌는데 숫자는 그대로"
증상이 지금은 없음을 직접 실측으로 반증. BUG-018/019 패턴 재발 없음, 모델 재실행 없음,
R-A/R1~R4 회귀 없음.
- 리더에게: **R-B 검증 통과. R-C(폴더 단위 가져오기 + 일괄 처리, 최대 스코프) 착수 가능.**
- `QA.md` 신규 등록 없음(발견된 결함 없음). `docs/roadmap.md`의 R-B 체크박스를 "구현 완료,
  검증 대기"에서 "구현+독립검증 통과"로 갱신.


---

## 2026-08-26 — 존(Zone) 분석 탭 R-C 레이아웃 뼈대 + 3a 검증: 좌·중·우 3분할 + 좌측 이미지 목록 패널 (커밋 `62187c0`+`285151c`)

기획 산출물: [docs/specs/zone-analysis-tab-features-2026-08-26.md](../specs/zone-analysis-tab-features-2026-08-26.md)
"승인된 UI 레이아웃"/"판단 C > C-1"/"라운드 분할 제안" 라운드1·3a 절. 구현 로그:
[implementation-log.md](implementation-log.md) "2026-08-26 — 존 분석 탭 R-C: 좌·중·우 3분할
레이아웃 뼈대 + 좌측 이미지 목록 패널 조립 (3a)" 항목. 워크트리 `D:\segmentation
model-zone-analysis-tab`(`feature/zone-analysis-tab` 브랜치, `D:\segmentation model`(main)과
분리된 별도 워크트리에서 작업). R-A/R-B/R1~R4는 기존 검증 통과 — **이번 라운드는 레이아웃
자체를 뜯어고친 라운드라 리더 지시대로 라벨링/학습/추론이 아닌 존 분석 탭 자체와 공유 위젯
(`inference_tab.py`)에 대해 `python`+`QTest` 실제 GUI 조작 골든패스 검증을 수행했다(주요
기능 추가에 준하는 검증 수준).**

### 정적 검토
- `git show 62187c0 --stat` — `app/tabs/zone_analysis_tab.py`(+246/-100 net), `app/widgets/inference_image_list.py`
  (+72), `docs/roadmap.md`만 변경. 스펙 R-C 3a 범위와 일치.
- `zone_analysis_tab.py`에서 3-way `QSplitter` 생성부(`splitter = QSplitter(...)`,
  `left`/`self._canvas`/`side` 3개 addWidget, `setStretchFactor(0,0)/(1,1)/(2,0)`,
  `setSizes([200,700,180])`)를 라인 단위로 확인 — **`setChildrenCollapsible(False)` 호출이
  코드에 없음**을 정적으로 먼저 확인(`grep -n "splitter" zone_analysis_tab.py` 전체 결과에
  해당 호출 0건). 다른 4개 탭(`inference_tab.py` L51/L167, `labeling_tab.py` L51/L67/L106,
  `training_tab.py` L265)은 전부 이 호출이 있어 BUG-008 수정(`7a98760`) 대상이었음을 재확인
  — 이번 신규 스플리터만 그 수정 관례를 놓쳤을 가능성을 실제 조작으로 검증하기로 함.
- `inference_image_list.py`의 애디티브 API 4개(`set_item_status`/`clear_status`/
  `set_multi_select`/`selected_paths`) 코드 확인 — `selected_paths()`의 "선택 개수 ≤1이면
  `paths()`(전체) 반환" 로직과 그 옆의 `ponytail:` 주석(Qt가 `setCurrentItem()` 시 currentItem을
  selectionModel에도 자동 포함시켜 "선택 1개"와 "미선택"을 구별 못 한다는 문제 설명)을 확인 —
  구현자가 예상한 대로 실제로 "이미지 1장만 명시적으로 고르기"가 불가능한지 실제 클릭
  이벤트로 검증 필요하다고 판단.
- `py_compile` — `zone_analysis_tab.py`/`inference_image_list.py`/`inference_tab.py`/
  `circle_detect_preview_dialog.py` 4개 파일 전부 통과(`C:\Users\Feel\anaconda3\python.exe`).

### 실제 GUI(QTest) 골든패스 검증
`C:\Users\Feel\anaconda3\python.exe`, `QT_QPA_PLATFORM=offscreen`, 기존 관례대로
numpy/cv2/PIL/torch/matplotlib 선행 임포트 후 PyQt6 임포트. `QFileDialog.getOpenFileNames`/
`getOpenFileName`/`getExistingDirectory`만 몽키패치, `QMessageBox.warning/information`은
헤드리스 무한대기 회피용 no-op(critical은 내용을 출력하도록 유지). `CircleDetectPreviewDialog.exec`는
`self.show()`로 대체(모달 블로킹 회피 — **주의**: `Dialog.exec = Dialog.show`처럼 클래스
속성을 다른 바운드 메서드로 그대로 별칭 지정하면 sip 메서드 바인딩이 꼬여 실제로는 원래
`exec()`가 그대로 호출돼 무한 블로킹하는 것을 직접 겪음 — `lambda self: self.show()`처럼
평범한 파이썬 함수로 감싸야 정상 동작함을 확인, 이후 스크립트는 전부 이 방식 사용).
`projects/nok/images/`의 실제 배터리 캡 사진 5장(`7~11번.bmp`) 사용. 스크래치 스크립트
6종(`verify_rc3a.py`, `debug_h.py`, `verify_nav_and_h2.py`, `verify_ra_toolbar2.py`,
`verify_ra_final.py`, `verify_width.py`, 전용 스크래치 디렉토리에만 생성, 프로젝트에는
추가 안 함) 작성·실행, 총 40개 이상 assertion:

1. **3-way 스플리터 렌더링 — 정상**: `ZoneAnalysisTab`을 `QMainWindow`에 얹어 실제
   `show()`+`qWaitForWindowExposed()` 후 `findChildren(QSplitter)`로 스플리터 정확히 1개,
   자식 3개(좌/중/우) 확인.
2. **BUG-008 패턴 재발 확인(핵심 발견, 신규 등록) — `BUG-020`**: `moveSplitter(0, 1)`(첫
   핸들을 맨 왼쪽 끝으로 실제 이동)로 좌측 패널이 `setMinimumWidth(180)`을 무시하고
   `sizes()[0]`이 200→**0px**로 완전히 붕괴함을 실측. 복구 후 `moveSplitter(sp.width(), 2)`
   (둘째 핸들을 맨 오른쪽 끝으로)로 우측 패널도 `setMinimumWidth(160)`을 무시하고
   180→**0px**로 붕괴 확인. 코드에 `setChildrenCollapsible(False)`가 없다는 정적 확인과
   일치 — `sp.childrenCollapsible()`이 실제로 `True`(Qt 기본값)임을 직접 조회해 재확인.
   다른 4개 탭의 스플리터 6개는 전부 이 설정이 있어 동일 조작으로 붕괴하지 않음(과거
   BUG-008 재검증 로그 기준) — **이번 신규 스플리터에서만 그 관례가 누락된 회귀**.
   `QA.md`에 `BUG-020`(P2)으로 신규 등록.
3. **툴바 통합 — 창을 좁혀도 겹침은 없으나 다른 형태의 실측 결함 발견(신규 등록) —
   `BUG-021`**: 리더 지시대로 창 폭 1100px로 `resize()` 시도 → 위젯 순서 자체는 겹치거나
   뒤집히지 않음(PASS)이지만, **`win.width()`가 요청한 1100이 아니라 실제로는 1588로
   강제 확대됨**을 확인 — 원인을 추적하니 `ZoneAnalysisTab.minimumSizeHint().width()`가
   **1588px**(다른 4개 탭은 630~837px)에 달함. 상단 툴바 `QHBoxLayout`에 위젯 12개(체크포인트
   열기/추론실행/타겟클래스/AI신뢰도 슬라이더+라벨/픽셀크기/민감도 슬라이더+라벨/자동검출/
   블랍삭제모드/오프라인테스트)를 한 줄에 몰아넣어 줄바꿈·스크롤 없이 최소폭이 누적된 결과.
   더 결정적으로, **`MainWindow()`를 실제로 생성해 `app/main_window.py:31`의 코드상 명시된
   기본 창 크기 `resize(1280, 800)`이 런타임에 그대로 적용되는지 확인한 결과 `win.size()`가
   `QSize(1280,800)`이 아니라 `QSize(1592,800)`로 나타남** — 존 분석 탭이 5번째 탭으로 이미
   `QTabWidget`에 포함돼 있어 앱을 그냥 실행하기만 해도(별도 탭 전환 없이) Qt가 레이아웃
   최소크기 제약 때문에 코드가 의도한 기본 창 크기를 무시하고 확대시킴. `QA.md`에
   `BUG-021`(P2)로 신규 등록.
4. **좌측 패널 — 단일 이미지 워크플로우 회귀 없음**: `getOpenFileNames`를 이미지 1장만
   반환하도록 몽키패치 후 "이미지 열기…" 버튼 로직(`_on_select_image()`) 실행 →
   `count()==1`, `_img_list.isHidden()==True`(스펙 "count>1일 때만 표시" 정확히 지켜짐),
   `_image_path` 자동 설정, **자동 추론 미실행**(`_last_result is None` 유지) 전부 확인 —
   기존 R1~R4 골든패스가 이 조건에서 전혀 안 바뀌었음을 재확인(가장 중요한 회귀 지점).
5. **좌측 패널 — 다중 이미지 워크플로우**: `getOpenFileNames`로 3장 반환 → `count()==3`,
   목록 패널 `isVisible()==True`, 자동 추론 미실행(엔진 `run` 호출 카운터 0) 확인.
   `getExistingDirectory`로 `projects/nok/images` 폴더 지정 → `load_folder()` 재귀 스캔으로
   실제 이미지 5장 전부 로드, 경로 라벨 갱신, 목록 표시 확인.
6. **이미지 클릭 시 자동 추론 안 됨**: 트리 위젯에서 실제 `QTest.mouseClick`으로 다른
   이미지 항목 클릭 → `engine.run` 호출 카운터 0(자동 추론 안 됨), 자동검출/블랍삭제 버튼
   둘 다 비활성화(추론 전 상태로 정확히 리셋) 확인.
7. **`selected_paths()` 3가지 케이스 실측(구현자가 남긴 우려사항 검증)**:
   - **초기 상태**(폴더 로드 직후, 사용자가 명시적으로 아무것도 클릭 안 함) — 내부적으로는
     Qt가 `setCurrentItem()`으로 이미 1개를 "선택"해 둔 상태이지만, `selected_paths()`가
     `paths()`(전체 5장)를 정확히 반환함을 확인.
   - **정확히 1개만 명시적으로 클릭**(다른 이미지로 실제 마우스 클릭 전환) — `selectedItems()`가
     정확히 1개(클릭한 그 이미지)임에도 `selected_paths()`는 **여전히 전체 5장을 반환**함을
     실측 확인 — **구현자가 `ponytail:` 주석에서 예상한 우려사항이 실제로 재현됨**: 사용자가
     "이 이미지 1장만 배치 처리하고 싶다"는 의도로 명시적으로 1장을 클릭해도, 현재 설계상
     `selected_paths()`는 그 의도를 구별하지 못하고 "전체 처리"로 해석한다. **판단**: 이번
     라운드(3a)엔 이 반환값을 사용하는 배치 처리 버튼 자체가 아직 없어 사용자가 이 문제를
     직접 겪을 수 있는 진입점이 없으므로 지금 당장 버그로 등록하지는 않음 — 다만 3b에서
     "▶ 선택 이미지 일괄 처리 (N장)" 버튼이 이 값을 그대로 쓰게 되면 "이미지 1장만 정말
     고르고 싶을 때 못 고름"이 실사용 버그가 되므로, 3b 스펙/구현 단계에서 반드시 재검토가
     필요함을 로드맵에 명시(예: `selectionChanged`를 명시적 사용자 조작으로만 트리거하는
     별도 플래그 방식 등 대안 검토 필요 — 구현자가 이미 주석에 남긴 해법 후보와 동일).
   - **Ctrl+클릭으로 2개 명시적 다중 선택** — `selected_paths()`가 정확히 그 2개만 반환함을
     확인(정상 동작).
8. **`inference_tab.py` 회귀 없음(공유 위젯 애디티브 변경 검증, 필수 항목)**: `InferenceTab`을
   별도로 인스턴스화해 `_img_list`의 `SelectionMode`가 여전히 기본값 `SingleSelection`임을
   재확인, 폴더 열기(재귀 스캔, 5장), 목록 패널 표시, 검색 필터("7번" 입력 → 1장, 해제 →
   5장 복원), 정렬(파일명 내림차순 전환 후 실제 정렬 순서 확인), "다음"/"이전" 네비게이션
   버튼(1칸씩 정확히 이동·복귀) 전부 실제 클릭/입력 이벤트로 정상 동작 확인 — 존 분석 탭
   전용 애디티브 API 추가가 추론 탭 기존 골든패스에 전혀 영향을 주지 않음.
9. **R1~R4/R-A/R-B 골든패스 회귀 없음**: 실제 `simple_unet` 프리셋 모델을 fresh weight로
   인스턴스화해 스크래치 체크포인트(`config.model_source="preset:simple_unet"`)로 저장 후
   R1(체크포인트 자동 준비+추론 실행), R2(자동 검출 버튼 클릭 크래시 없음), R3(합성 결정론적
   `raw_class_map`/`confidence_map`을 `engine.run` 몽키패치로 주입해 원 1개→존 2개 생성 확인),
   R-B(AI신뢰도 슬라이더를 blob 신뢰도(0.9)보다 높은 95%로 올리면 퍼센티지가 65.02%→0.00%로
   실제로 바뀜을 확인 + 조작 전후 원 선택(`selected_id()`)·존 하이라이트(`highlighted_zone()`)가
   그대로 유지됨을 확인해 BUG-018/019 패턴 재발 없음 재확인), R4(블랍 삭제 모드 토글 시
   `_canvas._blob_delete_mode` 정상 전환, 크래시 없음), R-A(툴바의 실제 "오프라인 원 검출
   테스트…" 버튼을 `QTest.mouseClick`으로 클릭해 실제 팝업 생성 확인 → 팝업 안에서 이미지
   열기 시 자동 1차 검출 실행 확인 → 팝업 조작 후에도 메인 탭 `_image_path`가 여전히
   `None`으로 유지됨을 확인해 완전 독립성 재확인 → 닫기 버튼으로 정상 종료) 전부 정상 동작.
10. **크래시 없음 / `py_compile`**: 위 모든 시나리오 실행 중 예외 0건(테스트 스크립트 자체의
    시행착오 2건 — 중복 버튼 클릭으로 인한 nav 인덱스 오프바이원, 랜덤 초기화 모델이 배경만
    예측해 타겟 클래스가 검출되지 않은 케이스 — 은 전부 테스트 스크립트 설계 문제로 확인되어
    합성 데이터로 대체 후 재실행해 해소, 앱 코드의 결함이 아님). `py_compile` 4개 파일 전부
    통과.

### 발견된 결함 — `QA.md` 신규 등록
- **`BUG-020`(P2)** — 3-way `QSplitter`에 `setChildrenCollapsible(False)` 누락, 핸들 드래그로
  좌/우 패널 0px 붕괴(BUG-008 패턴 재발). 수정은 기존 해법과 동일하게 스플리터 생성부에
  `splitter.setChildrenCollapsible(False)` 1줄 추가로 충분할 것으로 예상(구현 담당은 다음
  라운드 착수 에이전트).
- **`BUG-021`(P2)** — 상단 툴바 위젯 과밀로 `minimumSizeHint` 1588px, 앱 코드상 기본 창 크기
  `1280×800`이 런타임에 `1592×800`으로 강제 확대됨. 수정 방향은 검증 범위 밖(디자인 판단
  필요 — 위젯 폭 축소/2줄 분리/스크롤 영역 등 여러 옵션 가능)이므로 QA.md에 현상만 등록,
  해법 결정은 디자인/리더 판단으로 남김.
- `selected_paths()`의 "1개 선택=전체" 설계는 이번 라운드엔 버그로 등록하지 않음(사용
  진입점 없음) — 3b 스펙/구현 시 재검토 필요 사항으로 위 roadmap.md에 명시.

### 프로세스 정리
- 스크래치 스크립트 전부 `QTest`로 위젯 이벤트만 발생시키고 `app.exec()` 이벤트 루프를
  돌리지 않아 스크립트 자체가 정상 종료됨. 백그라운드(`&`)로 띄운 디버그 스크립트 1건이
  모달 `exec()` 오배선(위 "주의" 참고)으로 응답 없이 멈춰 `pkill`로 정리 — `tasklist` 확인
  결과 이 워크트리 관련 잔여 프로세스는 이전부터 떠 있던 `PID 16488`("Segmentation Model
  UI — nok" 창, 시작 시각이 이번 세션보다 이르고 이번 세션이 띄운 것이 아님, R-A/R-B 검증
  로그에도 동일 PID로 기록됨) 하나뿐 — 이번 세션이 새로 만든 좀비 프로세스 0건, 건드리지
  않음. 스크래치 체크포인트 파일(`docs/agents/_scratch_verify_ckpt.pt`)은 검증 종료 후 삭제.
  `git status --short` 결과 이 문서/QA.md/roadmap.md 갱신 외 워크트리 무변경 확인.

### 판정
**조건부 통과 — 골든패스 자체(레이아웃 조립, 좌측 패널 통합, 회귀 없음)는 전부 정상
동작하나, 이번 라운드가 새로 만든 코드에서 실제 조작으로만 드러나는 결함 2건(`BUG-020`
스플리터 붕괴, `BUG-021` 창 강제 확대)을 발견했다.** 둘 다 앱을 크래시시키거나 데이터를
손상시키지 않고(P2), 사용자가 수동으로 우회 가능(스플리터는 다시 드래그해 복구, 창 크기는
더 넓게 유지됨일 뿐 기능 자체는 정상 동작)하므로 R-C 3a 자체를 "블로커"로 판단하지는
않았으나, 3b(배치 컨트롤이 좌측 패널 하단에 추가될 예정) 착수 전에 `BUG-020`을 먼저 고쳐두는
것을 권장한다(좌측 패널이 붕괴된 채로 배치 컨트롤까지 추가되면 발견성이 더 나빠짐).
- 리더에게: **R-C 3a 검증 완료(조건부 통과, BUG-020/021 신규 등록). 3b/3c 착수 전 BUG-020
  수정 여부 판단 필요 — P2라 반드시 선행 조건은 아니지만 좌측 패널이 3b의 핵심 작업 대상이라
  먼저 고치는 편이 재작업이 적음.**
- `QA.md`에 `BUG-020`/`BUG-021` 신규 등록(둘 다 Open, P2). `docs/roadmap.md`의 R-C 레이아웃
  뼈대+3a 체크박스를 "구현 완료, 실제 GUI 조작 검증 대기"에서 "구현+검증 완료(조건부 통과)"로
  갱신.

---

## 2026-08-26 — BUG-020/BUG-021 재검증 (존 분석 탭 3분할 스플리터 붕괴 + 툴바 폭 초과)

### 범위
직전 라운드(R-C 레이아웃 뼈대+3a, 커밋 `22e9725`)에서 발견한 `BUG-020`(3-way `QSplitter`
붕괴)과 `BUG-021`(툴바 폭 초과로 `MainWindow` 기본크기 무시)을 리더가 직접 수정(커밋
`9efcd14`, `app/tabs/zone_analysis_tab.py`)한 것에 대한 **좁은 범위 재검증만** 수행. 다른
항목(R1~R4/R-A/R-B/R-C 3a 골든패스, BUG-018/019 등)은 직전 라운드에서 이미 통과 확인돼
전체 재검증 생략. 워크트리 `D:\segmentation model-zone-analysis-tab`
(`feature/zone-analysis-tab` 브랜치)에서 작업.

### 검증 방법
`C:\Users\Feel\anaconda3\python.exe`, `QT_QPA_PLATFORM=offscreen`, `numpy/cv2/PIL/torch/
matplotlib` 선행 임포트 후 `QApplication` 생성(기존 세션들과 동일 순서). `py_compile`로
`app/tabs/zone_analysis_tab.py`/`app/main_window.py` 정적 확인 후, 3개의 오프스크린
스모크 스크립트로 실측:

1. **BUG-020**: `ZoneAnalysisTab()` 실제 인스턴스에서 `findChildren(QSplitter)`로 3-way
   스플리터를 찾아 `childrenCollapsible()`이 `False`인지 확인 후, `moveSplitter(0, 1)`(좌측
   핸들을 x=0까지)과 `moveSplitter(splitter.width(), 2)`(우측 핸들을 맨 끝까지) 두 방향
   모두 극단까지 이동시켜 좌/우 패널 실제 폭을 측정.
2. **BUG-021**: `ZoneAnalysisTab().minimumSizeHint().width()` 측정 + 실제 `MainWindow()`를
   생성해 `win.size()`가 코드 상 `resize(1280, 800)`과 일치하는지 확인(`app/main_window.py:31`).
3. 두 줄로 나뉜 툴바(`toolbar_row1`/`toolbar_row2`) 위젯 전수 존재 확인(`hasattr`) +
   `QTest.mouseClick()`/`QTest.keyClick()`/`QTest.keyClicks()`로 실제 이벤트 3건 발생시켜
   동작 확인: 블랍삭제모드 토글 버튼 클릭 → `isChecked()` 반영, 민감도 슬라이더 키보드
   좌측 화살표 → 값 변경, 타겟 클래스 이름 입력란 실제 타이핑 → 텍스트 반영.
4. `python -m py_compile` 크래시 없음 확인.

**주의(프로세스)**: 초기 시도에서 `print()`가 flush 안 된 채 `2>&1` 리다이렉션으로 실행해
출력이 전혀 안 보여 "행"으로 오인, 두 차례 프로세스를 직접 확인 후 종료(`taskkill /F`)함 —
실제로는 (a) `tab._btn_ckpt.click()`으로 실제 네이티브 파일 열기 다이얼로그가 뜨면서
offscreen 플랫폼에서도 모달 이벤트 루프가 자동으로 안 닫혀 대기 상태가 된 것, (b)
`MainWindow.close()`가 `closeEvent()`의 `QMessageBox.question()` 종료 확인창을 띄워 같은
이유로 대기 상태가 된 것 — 둘 다 **테스트 스크립트 자체의 설계 문제**(실제 앱 동작 자체는
의도대로 정상, 파일 다이얼로그/종료 확인창이 뜨는 것 자체가 맞는 동작)였음. 이후 스크립트에서
파일 다이얼로그를 여는 버튼 클릭과 `MainWindow.close()`를 제거해 문제 없이 완료. `tasklist`로
매 단계 프로세스 상태 확인, 이번 세션이 새로 띄운 스크립트 프로세스 전부 정상 종료/필요 시
직접 종료 확인 완료 — 세션 종료 시점에 이 워크트리 관련 잔여 프로세스 0건(사전에 떠 있던
`PID 16488`, "Segmentation Model UI — nok" 창은 이번 세션이 띄운 것이 아니라 건드리지 않음,
이전 검증 로그에도 동일 PID로 기록돼 있음).

### 결과
- **BUG-020**: `childrenCollapsible()` → `False` 확인. `moveSplitter(0,1)` 후 좌측 패널
  폭 = 180px(설정된 `setMinimumWidth(180)`), `moveSplitter(total,2)` 후 우측 패널 폭 =
  160px(설정된 `setMinimumWidth(160)`) — 양방향 모두 0px 붕괴 재현 안 됨. **재현 안 됨 →
  Closed.**
- **BUG-021**: `ZoneAnalysisTab().minimumSizeHint().width()` = **982px**(리더가 보고한
  982px와 일치). 실제 `MainWindow()` 생성 후 `win.size()` = **1280×800**(코드 상
  `resize(1280, 800)` 그대로) — 이전 재현된 `1592×800` 강제 확대 재현 안 됨. **재현 안 됨
  → Closed.**
- 두 줄 툴바 위젯 12개(체크포인트 열기/추론실행/타겟클래스 이름·콤보/AI신뢰도 슬라이더/
  픽셀크기/민감도 슬라이더/자동검출/블랍삭제모드/오프라인테스트) 전부 `hasattr` 확인, 실제
  `QTest` 클릭/키입력 3건(블랍삭제모드 토글, 민감도 슬라이더 키보드 조작, 타겟 클래스 이름
  입력란 타이핑) 모두 정상 반영 — 레이아웃 변경으로 인한 기능 회귀 없음.
- `py_compile app/tabs/zone_analysis_tab.py app/main_window.py` 정상, 런타임 크래시 없음.

### 판정
**통과.** `QA.md`에서 BUG-020/BUG-021을 Open → Closed로 이동(수정 커밋 `9efcd14`, 재검증
내용 포함). `docs/roadmap.md`의 R-C 레이아웃 뼈대+3a 항목을 "조건부 통과(BUG-020/021)"에서
"구현+검증 완료(BUG-020/021 수정 및 재검증 통과)"로 갱신 필요.


---

## 2026-08-26 — 존(Zone) 분석 탭 R-C 3b 검증: 폴더 일괄 처리 로직 + 결과 테이블 (커밋 `b391075`+`ca83829`+`bab8fad`)

기획 산출물: [docs/specs/zone-analysis-tab-features-2026-08-26.md](../specs/zone-analysis-tab-features-2026-08-26.md)
"판단 C > C-2"/"라운드 분할 제안 3b" 절. 구현 로그: [implementation-log.md](implementation-log.md)
"2026-08-26 — 존 분석 탭 R-C 3b: 폴더 일괄 처리 로직 + 결과 테이블" 항목. 워크트리
`D:\segmentation model-zone-analysis-tab`(`feature/zone-analysis-tab` 브랜치, `D:\segmentation
model`(main)과 분리). 레이아웃 뼈대+3a(커밋 `62187c0`+`285151c`)와 BUG-020/021 재검증(커밋
`9efcd14`)은 기존 검증 통과 — 이번 라운드는 회귀만 재확인하고, 핵심은 "일괄 처리로 나온
퍼센티지가 실제로 정확한지"를 R3/R-B 검증 때 쓴 방식(`engine.run`만 몽키패치 + 손계산 가능한
합성 데이터 + 독립 numpy 오라클 대조)으로 정량 확인하는 것.

### 정적 검토
- `git show b391075 --stat`/`ca83829`/`bab8fad` diff 확인 — `app/tabs/zone_analysis_tab.py`
  (+139/-3), `app/widgets/inference_image_list.py`(+2, `selection_changed` 시그널만 추가),
  신설 `app/widgets/zone_batch_result_dialog.py`(+41) — 스펙 3b 범위와 일치, `zone_metrics.py`/
  `inference_engine.py`/`circle_detector.py`는 무변경(스펙 명시대로 core 로직 재사용만).
- `_on_batch_process()` 라인 단위 확인 — 원 적용 방식(체크 시 `self._canvas.get_circles()`
  재사용 + 해상도 다르면 `(w_i/w_ref, h_i/h_ref)` 비례 스케일, 체크 해제 시 이미지별
  `detect_circles(bgr, sensitivity=슬라이더값)`), 타겟 마스크가 `result.class_map ==
  target_cid`(R-B와 동일하게 `raw_class_map` 아님)를 쓰는 것 확인, 현재 표시 중인 이미지는
  `self._last_result` 재사용(재추론 생략) 확인, 배치 루프가 `self._img_list
  .set_item_status()`만 호출하고 `self._canvas.set_circles()`/`set_pixmap()` 등 캔버스 API를
  전혀 호출하지 않아(구현 로그 "리스크" 절 지시 그대로) BUG-018/019 패턴 재발 경로 자체가
  없음을 코드로 먼저 확인 — 실제 GUI로 재확인 필요 항목으로 표시.
- `InferenceImageList.selected_paths()`("선택 개수 ≤1이면 `paths()`(전체) 반환")와 배치 버튼
  툴팁 안내 문구(`ca83829`)를 확인 — 3a 검증에서 이미 발견된 한계를 그대로 유지하고 안내만
  추가한 것으로, 이번 라운드에서 실사용 영향(특히 다중 선택 상호작용)을 재검토하기로 함.
- `py_compile` — `zone_analysis_tab.py`/`inference_image_list.py`/`zone_batch_result_dialog.py`/
  `zone_metrics.py`/`inference_engine.py`/`inference_tab.py` 6개 파일 전부 통과.

### 실제 GUI(QTest) 골든패스 검증 — 정량적 정확성 확인 (핵심)
`C:\Users\Feel\anaconda3\python.exe`, `QT_QPA_PLATFORM=offscreen`, 기존 관례대로 numpy/cv2/
PIL/torch/matplotlib 선행 임포트 후 PyQt6 임포트. `engine.run`(모델 forward pass 대신
손계산 가능한 합성 `raw_class_map`/`confidence_map` 주입, `_compute_blobs_and_filter`/
`_colorize_and_blend`는 실제 프로덕션 함수 그대로 호출)과 `detect_circles`(개별 자동검출
모드 전용, 이미지별로 다른 고정 원 목록 반환)만 몽키패치, `QMessageBox.warning/information`은
헤드리스 무한대기 회피용 no-op, `ZoneBatchResultDialog`는 `rows` 인자를 캡처하고 `exec()`만
무력화(모달 회피, 이전 세션에서 확인된 "plain 함수로 감싸야 함" 관례 그대로 준수)한 서브클래스로
치환. 스크래치 스크립트 3종(`verify_3b.py`, `verify_ctrlclick_bug.py`,
`verify_inference_tab_regression.py`, 전용 스크래치 디렉토리에만 생성, 검증 종료 후 이미지·
스크립트 전부 삭제) 작성·실행, 총 96개 assertion 전부 통과 + 별도 집중 재현 스크립트 1건:

1. **정량 검증 — 합성 이미지 5장(동일 해상도 4장 100×80 + 다른 해상도 1장 150×120), AI신뢰도
   40%/픽셀크기 20px 고정**: 이미지마다 신뢰도·크기가 다른 블랍 3~4개를 배치(임계값 경계
   부근 값 포함 — 예: 신뢰도 0.39/0.45로 임계값 0.4 양쪽), 기준 이미지에 원 2개(반지름
   15/35) 정의 후 "1번째 이미지 원을 전체에 적용"(기본 체크) 상태로 일괄 처리 실행. 결과
   테이블(캡처된 `rows`)의 이미지×존 15개 조합 전부가 `zone_analysis_tab.py`를 전혀 거치지
   않는 독립 오라클(`engine._compute_blobs_and_filter()` + `zone_metrics.zones_from_circles()`/
   `zone_stats()`를 테스트 스크립트 안에서 직접 호출)과 **부동소수점 오차(1e-6) 이내로 완전
   일치**. 다른 해상도 이미지(150×120)는 `(1.5, 1.5)` 비례 스케일된 원 좌표로 재계산한
   오라클과도 정확히 일치 — "해상도 방어" 로직이 실제로 정확한 좌표 변환을 수행함을 확인.
   빈 타겟(블랍 없는 이미지)은 3개 존 전부 정확히 0.00% 확인.
2. **threshold가 배치 결과에도 실제 반영됨(R-B 근본원인 수정 재발 없음 재확인)**: 신뢰도
   0.45 블랍(임계값 0.4 이상이라 kept)이 반영된 중심부 퍼센티지(9.03%)를, 같은 좌표를
   `raw_class_map`(threshold 미적용) 기준으로 직접 계산한 값(10.30%)과 대조해 **서로 다름**을
   확인 — 배치 경로가 `class_map`(threshold 적용 후)을 쓰고 있음을 정량적으로 반증.
3. **개별 자동검출 모드(체크 해제)**: `detect_circles()`를 이미지별로 다른 고정 원 목록
   (0~3개, 존 개수 0~4개)을 반환하도록 몽키패치 후 재실행 — 5장 전부에서 `detect_circles`가
   정확히 1회씩(총 5회) 호출됨을 확인, 원 없는 이미지는 결과 행 0개 + 배지 "원 없음" 정확히
   표시, 나머지 4장은 원 개수+1개의 존이 생성되고 각 존 퍼센티지가 오라클과 정확히 일치.
   이미지마다 원 개수(0/1/2/3개)가 실제로 다름을 재확인.
4. **좌측 목록 상태/배지 실시간 갱신**: 배치 처리 후 5장 전부 `_status` 딕셔너리에
   `("done", 배지)`로 정확히 기록됨, 배지 텍스트가 각 이미지의 가장 바깥쪽 존 퍼센티지와
   일치함을 확인. 현재 표시 중이던 기준 이미지(img_01)는 `engine.run` 호출 로그에서
   제외됨(캐시 재사용), 나머지 4장만 실제 호출됨을 호출 카운터로 확인.
5. **캐시 없는 재계산 검증(결정론적 재현성)**: 배치 처리 후 좌측 목록에서 img_03을
   실제로 클릭(`currentItem` 변경) → `_image_path`가 img_03으로 갱신되고 원이 자동
   초기화됨(새 이미지 전환의 정상 동작, 회귀 아님) 확인 → `_on_run()`으로 실제 재추론
   (`engine.run` 재호출 확인) → 타겟 클래스 자동 재확정 → 기준 원(동일 해상도라 스케일
   불필요) 재설정 → `_zone_list` 표시값이 배치 결과 테이블의 img_03 값과 반올림 오차
   (<0.005, 화면 표시가 소수점 2자리라 발생하는 표시상 오차일 뿐, 저장값 자체는 동일 float)
   이내로 완전 일치.
6. **진행률 다이얼로그 + 취소**: `QProgressDialog.__init__`을 캡처해 `minimum()==0`/
   `maximum()==5`(전체 이미지 수) 확인. `wasCanceled()`를 2번째 호출부터 `True`를 반환하도록
   몽키패치해 "1번째 이미지 처리 후 취소" 시나리오 재현 — 실제로 1장만 `"done"` 상태가
   되고 나머지 4장은 `_status`에 항목 자체가 생기지 않음(미처리)을 확인, 루프가 정확히
   중단됨을 재확인.
7. **BUG-018/019 패턴 재발 없음**: 개별 자동검출 배치 실행 전 원 1개를 `select_circle()`로
   선택 + 존 리스트 "링 1"을 하이라이트해둔 뒤, 배치 처리(5장, `detect_circles` 5회 호출)
   완료 후에도 `_canvas.selected_id()`/`highlighted_zone()`이 정확히 그대로 유지됨을 확인 —
   구현 로그의 "배치 루프는 캔버스 API를 호출하지 않는다"는 코드 리뷰 결론이 실측으로도
   재확인됨.
8. **`inference_tab.py` 회귀 없음**: `InferenceTab`을 별도 인스턴스화해 `_img_list`가 여전히
   `SingleSelection` 기본값 유지, 폴더 재귀 스캔(5장), 검색 필터("img_02" -> 1장, 해제 ->
   5장 복원), 다음/이전 네비게이션 정상 동작 확인 — `selection_changed` 시그널 추가가
   무해함을 재확인.
9. **R1~R4/R-A/R-B/3a 회귀 없음(가벼운 재확인)**: 블랍삭제모드 토글(체크/해제 모두 캔버스에
   정확히 반영), 오프라인 원 검출 팝업(`CircleDetectPreviewDialog`) 생성 크래시 없음.

### `selected_paths()` "≤1개 선택=전체" 판단 (지시사항 9번 — 리더 위임)
3a 검증에서 이미 확인된 한계("정확히 1장만 클릭해도 전체 목록이 반환됨")가 3b에서도 그대로
재현됨을 확인(구현자가 안내 문구만 추가하고 로직은 그대로 둔 것과 일치). **다만 이번
검증에서 그보다 심각한 별개의 신규 결함을 발견했다 — 아래 참고.**

### 발견된 결함 — `QA.md` 신규 등록
- **`BUG-022`(P1, Open, 신규)** — Ctrl/Shift 클릭으로 배치 대상 이미지를 2장 이상 **명시적으로**
  선택하면(예: 이미지1 단일클릭 -> 이미지2 Ctrl+클릭, `QTest.mouseClick`으로 실제 재현), 그
  클릭이 `QTreeWidget`의 `currentItem`도 함께 바꾸면서 `image_selected` 시그널이 발화되고
  `ZoneAnalysisTab._on_list_image_selected()`가 "새 이미지로 전환됨"으로 해석해
  `self._canvas.clear_circles()`를 호출 — 방금 기준 이미지에서 정의해둔 원이 그 즉시 전부
  삭제되고 `_update_batch_button_state()`가 원 0개를 감지해 "▶ 선택 이미지 일괄 처리" 버튼을
  비활성화한다. 집중 재현 스크립트(`verify_ctrlclick_bug.py`)로 실측: 이미지1 클릭(기존
  선택 유지, 정상) -> 이미지2 Ctrl+클릭 -> `selected_paths()`는 정확히 `["img_01.png",
  "img_02.png"]` 2개를 올바르게 반환하지만 `canvas.get_circles()`가 즉시 `[]`로 비고
  `_btn_batch.isEnabled()`가 `False`로 전환됨을 확인. **즉 "특정 이미지 몇 장만 골라 일괄
  처리"라는 이번 라운드의 핵심 기능이, 그 대상을 실제로 마우스로 고르는 행위 자체 때문에
  매번 무력화된다** — 우회법은 선택을 건드리지 않고 `selected_paths()`의 "≤1개 선택=전체"
  기본 동작에 의존해 항상 전체 목록을 처리하는 것뿐(부분집합 지정 사실상 불가능). 근본
  원인은 `_on_list_image_selected()`가 "사용자가 미리보기할 다른 이미지로 전환"과 "다중
  선택 확장을 위한 클릭"을 구분하지 못하고 항상 캔버스를 리셋하는 것 — 스펙의 "리스크" 절이
  경고했던 "다중 선택과 현재 미리보기 이미지는 다른 개념"이라는 우려가 실제로 배치 버튼의
  핵심 전제조건(캔버스 원 존재)을 깨뜨리는 형태로 현실화됨. 3a에서 이미 알려졌던 "1개
  선택=전체 반환" 한계(YAGNI로 보류)와는 별개의, 더 심각한 신규 결함으로 판단해 P1로 등록.
  수정 방향은 검증 범위 밖(디자인/구현 판단 필요 — 예: 다중 선택 모드에서는
  `currentItemChanged`가 아니라 최초 단일 클릭시에만 프리뷰를 갱신하거나, 배치 버튼의
  "기준 원" 상태를 캔버스의 현재 원이 아니라 별도로 캡처해 보존하는 방식 등 여러 옵션
  가능)이므로 QA.md에 현상만 등록.

### 프로세스 정리
- 스크래치 스크립트 3종 + 합성 이미지 5장은 전용 스크래치 디렉토리에만 생성, 검증 종료 후
  전부 삭제(`rm -rf`). `git status --short` 결과 `QA.md`/`docs/roadmap.md`/이 로그 파일
  갱신 외 워크트리 무변경 확인.
- `tasklist`로 프로세스 확인 — 이 워크트리 관련 잔여 프로세스는 이전 세션들과 동일한
  `PID 16488`("Segmentation Model UI — nok" 창, 이번 세션 시작 이전부터 떠 있던 것, 건드리지
  않음) 하나뿐. 이번 세션이 새로 띄운 스크립트는 전부 `Bash` 동기 실행으로 완료 후 자동
  종료(백그라운드 프로세스 0건).

### 판정
**조건부 통과 — 일괄 처리의 핵심 요구사항인 "정확성"은 완벽하게 확인됨(96개 assertion,
동일/다른 해상도·threshold 반영·개별 자동검출·캐시 없는 재계산 전부 오라클과 정확히 일치,
버그 0건). 진행률/취소/상태아이콘/BUG-018·019 패턴 재발 없음/`inference_tab.py` 회귀 없음도
전부 정상.** 다만 이번 라운드가 신설한 "선택 이미지 일괄 처리" 기능 자체가 다중 선택
상호작용에서 실사용 가능한 수준으로 동작하지 않는 **신규 P1 결함(`BUG-022`)**을 발견했다 —
크래시나 데이터 손상은 없고 우회(선택 안 함=전체 처리)는 가능하지만, "선택 이미지"라는
버튼 문구가 약속하는 핵심 시나리오(부분집합 지정)가 사실상 막혀 있어 R-C 3a의 BUG-020/021
보다 심각도가 높다고 판단(P1 vs P2). 정확성 계산 로직 자체(3b의 가장 중요한 부분)는 흠결이
없으므로 3b를 "실패"로 되돌리지는 않되, 3c(Excel 내보내기) 착수 또는 최종 배포 전에
`BUG-022` 수정이 필요하다고 권고한다.
- 리더에게: **R-C 3b 정확성 검증 통과(96/96 assertion). 신규 P1 버그(`BUG-022`, 다중 선택
  시 배치 버튼 무력화) 발견 — 3c 착수 전 수정 여부를 사용자와 상의해 결정 필요. 3a에서
  이미 알려진 "1개 선택=전체" 한계는 이번에도 재확인했으나 우선순위상 `BUG-022`가 더
  시급함.**
- `QA.md`에 `BUG-022`(P1, Open) 신규 등록. `docs/roadmap.md`의 R-C 3b 항목을 "구현 완료,
  검증 대기"에서 "구현+검증 완료(조건부 통과, BUG-022 신규 발견)"로 갱신.

---

## 2026-08-26 — BUG-022 재검증: 다중선택(Ctrl/Shift) 시 원 소실 방지 수정, 재현됨(수정 실패)

워크트리 `D:\segmentation model-zone-analysis-tab`(`feature/zone-analysis-tab` 브랜치). 리더가
구현 에이전트에게 맡긴 BUG-022(P1) 1차 수정(커밋 `9b28987`, `_multi_select` 플래그 가드)의
재검증만 수행 — 3b의 나머지 부분(정확성 96 assertion 등)은 직전 세션에서 이미 통과 확인돼
범위 밖.

### 방법
`C:\Users\Feel\anaconda3\python.exe`, `QT_QPA_PLATFORM=offscreen`. numpy/cv2/PIL/torch/
matplotlib 선행 임포트 후 PyQt6(기존 관례). `engine.run`/`engine.refilter`만 몽키패치(손계산
가능한 합성 `InferenceResult` 반환, `class_stats`/`blobs`는 빈 리스트), `QMessageBox.*`
no-op, `ZoneBatchResultDialog.exec` 무력화(모달 회피) — 3b 검증 세션과 동일 패턴. 스크래치
스크립트 3종(`verify_bug022.py`, `debug_timing.py`/`debug_timing2.py`, 전용 스크래치 디렉토리)
+ 합성 이미지 4장. **지시사항대로 `_on_current_item_changed()`를 직접 호출하지 않고 반드시
`QTest.mouseClick` + 실제 `Qt.KeyboardModifier.ControlModifier`/`ShiftModifier`로 마우스
이벤트를 재현**(원 보고서와 동일 방법).

### 결과 — BUG-022 재현됨(수정이 실제로 작동하지 않음)
원본 재현 시나리오(이미지1 실제 단일클릭으로 선택 확정 → 원 2개 정의 → 이미지2 실제
Ctrl+클릭)를 그대로 재실행한 결과, **수정 이전과 동일하게 증상이 재현**됐다:
- `tab._canvas.get_circles()`가 Ctrl+클릭 직후 `[]`로 즉시 비워짐(기대: 원 2개 유지).
- `tab._btn_batch.isEnabled()`가 `False`로 전환(기대: 계속 `True`).
- `tab._image_path`가 이미지1에서 이미지2로 바뀜(기대: 이미지1 유지, Ctrl+클릭은 확장
  선택일 뿐 "미리보기 전환"이 아니어야 함).
- Shift 범위선택(이미지1 → 이미지3)도 동일하게 재현(`image_selected`가 이미지3에 대해
  잘못 emit됨, 최종 `selectedItems()`는 3개로 정상이지만 그 사이에 이미 잘못된 emit 발생).

### 근본 원인 규명 — 왜 1차 수정의 "검증 완료" 주장이 틀렸는가
`inference_image_list.py`의 `_on_current_item_changed()`에 추가된 가드(`if self._multi_select
and len(self._tree.selectedItems()) != 1: return`)는 **`selectedItems()`를 인위적으로
미리 세팅한 뒤 메서드를 직접 호출하는 헤드리스 테스트에서만 통과**하고, 실제 Qt 마우스
클릭 이벤트 시퀀스에서는 작동하지 않는다. `debug_timing.py`/`debug_timing2.py`로
`_on_current_item_changed`(소스에 임시 디버그 print 삽입 후 원상복구, `git status`로 무변경
확인)와 `currentItemChanged`/`itemSelectionChanged` raw 시그널 발화 순서를 직접 관찰한 결과:

```
RAW 시퀀스 (이미지1 선택된 상태에서 이미지2 Ctrl+클릭 시):
1) currentItemChanged 발화 — 이 시점 selectedItems() = [이미지1] (1개, 이미지2는 아직 미반영)
   → 가드 조건(len != 1)이 False → "정상 단일 선택"으로 오판 → image_selected(이미지2) 잘못 emit
2) (Qt 내부에서 Ctrl 토글 선택 커맨드 적용)
3) itemSelectionChanged 발화 — 이제야 selectedItems() = [이미지1, 이미지2] (2개, 뒤늦게 정확해짐)
```

Qt의 `QAbstractItemView` 마우스 클릭 처리는 `mousePressEvent` 안에서 (a) `currentIndex`를
먼저 바꿔 `currentItemChanged`를 동기 발화한 뒤에야 (b) 실제 선택 커맨드(Ctrl=Toggle,
Shift=Range)를 `selectionModel`에 적용하는 순서로 동작한다. 즉 `currentItemChanged` 핸들러
실행 시점엔 아직 이번 클릭의 선택 효과가 반영되지 않은 "직전" 상태만 관측 가능 — 가드가
검사하는 `len(selectedItems())`가 이 순간엔 항상 "이전 선택 개수"를 보게 돼, Ctrl/Shift로
선택을 2개 이상으로 늘리는 첫 클릭마다 매번 뚫린다(정확히 원래 버그가 발생하던 경로).
1차 수정 시도의 헤드리스 검증(QA.md 원문: "`_on_current_item_changed()`를 실제
`selectedItems()` 상태별로 직접 호출")은 이 인트라 이벤트 타이밍을 재현할 수 없는 방법이라
거짓 양성(false positive)이었다.

### 회귀 없음 확인 (변경 안 됨 — 코드 레벨 보장)
`inference_tab.py`는 `set_multi_select()`를 호출하지 않아 `_multi_select`가 항상 `False`이고,
가드 전체가 `self._multi_select and ...`로 게이팅돼 있어 이 조건이 거짓이면 가드 블록에
진입 자체를 안 한다 — 즉 SingleSelection 경로는 이번 수정 전후로 코드 실행 흐름이 100%
동일함을 코드 레벨로 보장. 실측으로도 `InferenceImageList(set_multi_select 미호출)`에서
`_multi_select is False`, 실제 클릭 시 `image_selected` 정상 발화(이미 선택된 항목을 다시
클릭하는 경우엔 애초에 Qt가 `currentItemChanged`를 발화하지 않는데 이는 이번 수정과 무관한
기존 Qt 동작이며 3b 검증 때도 동일하게 관찰됨).

### 시나리오 5(부분집합 배치 처리 실제 실행)는 별도로 미실행
원이 시나리오 1 단계에서 이미 사라지는 게 재현됐으므로, "이제 원이 안 사라지니 실제로
일괄 처리가 되는지" 확인하는 지시사항 5번은 전제(원 유지)가 성립하지 않아 의미가 없어
스킵 — 원 손실 버그부터 실제로 수정된 뒤 재확인 필요.

### 판정
**블로커 — BUG-022 수정 실패, 재현됨.** `QA.md`의 상태를 "수정함, 검증 필요"에서
**Open**으로 되돌리고, 근본 원인(`currentItemChanged`가 선택 커맨드 적용보다 먼저 동기
발화되는 Qt 내부 순서)과 1차 수정이 왜 헤드리스 테스트를 통과했는지, 수정 방향 후보
(예: `itemSelectionChanged` 기반으로 재설계, `QApplication.keyboardModifiers()`로 클릭
시점 모디파이어 직접 확인, `QTimer.singleShot(0, ...)`으로 선택 커맨드 적용 완료 후 재확인
등)를 상세히 기록. 리더에게: **1차 수정이 실제로 작동하지 않으므로 재구현 필요 — 이번엔
반드시 `QTest.mouseClick` + 실제 모디파이어로 재검증할 것을 구현 에이전트에게도 명시
권고.**

### 프로세스 정리
디버그 스크립트 실행 중 `inference_image_list.py`에 임시 print를 삽입했다가 즉시 백업본으로
복원(`git status --short`로 무변경 확인, `py_compile` 재확인). 스크래치 스크립트/합성
이미지는 전용 스크래치 디렉토리에만 생성. `tasklist`로 확인한 잔여 GUI 프로세스는 이전
세션들과 동일한 기존 창(PID 16488, 이번 세션이 새로 띄운 것 아님) 하나뿐 — 이번 세션은
전부 `Bash` 동기 실행으로 완료, 백그라운드 프로세스 0건.


---

## 2026-08-26 — BUG-022 2차 수정 독립 재검증: 완전 해결 확인 (커밋 `6695f77`+`7d8e406`, 검증 3번째 시도)

워크트리 `D:\segmentation model-zone-analysis-tab`(`feature/zone-analysis-tab` 브랜치). 리더가
구현 에이전트에게 맡긴 BUG-022(P1) 2차 수정 재검증. 1차 수정(`9b28987`)은 이전 세션(2026-08-26,
위 항목)에서 `QTest.mouseClick` 실측으로 재현 확인돼 Open으로 되돌아갔었다 — 이번이 3번째
독립 재현 시도. 구현자 로그(`docs/agents/implementation-log.md` "2026-08-26 — BUG-022 2차 수정")도
자체적으로 `QTest.mouseClick` + 실제 모디파이어로 확인했다고 주장해, 지시대로 **메서드 직접 호출이나
상태 사전 세팅 없이 반드시 진짜 마우스 클릭 이벤트를 실제 위젯 좌표에 재현**하는 방식으로
독립적으로 재확인했다.

### 방법
`C:\Users\Feel\anaconda3\python.exe`, `QT_QPA_PLATFORM=offscreen`. numpy/cv2/PIL/torch/
matplotlib 선행 임포트 후 PyQt6(기존 관례). `QMessageBox.*` no-op, `engine.run`/`engine.refilter`만
몽키패치(손계산 가능한 합성 `InferenceResult` 반환), `ZoneBatchResultDialog.__init__`을 감싸
`rows`를 캡처하고 `exec()`를 무력화(모달 회피). 전용 스크래치 디렉토리에 스크립트 1종
(`verify_bug022_v2.py`) + 합성 이미지 4장 작성, 43개 assertion 실행. 모든 목록 클릭은
`InferenceImageList._tree.visualItemRect(item).center()`로 실제 아이템 좌표를 구한 뒤
`QTest.mouseClick(tree.viewport(), LeftButton, modifier, pos)`로 진짜 마우스 이벤트를 뷰포트에
주입(모디파이어는 `Qt.KeyboardModifier.ControlModifier`/`ShiftModifier` 실제 값 사용, 메서드 직접
호출 0건). 원 정의도 `set_circles()` 같은 직접 API가 아니라 `ZoneCanvas`에 실제
`QTest.mousePress`→`mouseMove`→`mouseRelease` 드래그로 생성(BUG-018 검증 때 쓴 방식과 동일).

### 결과 — 원본 재현 시나리오, 재현 시도 전부 실패(=버그 해결 확인)
1. **`InferenceImageList` 단독**: 로드 직후 img1 auto-select(기존 Qt 동작) 확인 후, img2 단일
   클릭 → emit 1회. img3 실제 **Ctrl+클릭**(2개 선택) → `image_selected` emit **없음**(정상,
   수정 전엔 여기서 잘못 emit됐음), `selectedItems()` 정확히 2개. img4 실제 **Shift+클릭**(3개
   선택) → 역시 emit 없음. 모디파이어 없이 img1 단일 클릭 → 1개로 좁혀지며 emit 정확히 1회.
2. **`ZoneAnalysisTab` 원본 시나리오**: 이미지1 실제 단일클릭(선택 확정) → 캔버스에 실제 드래그로
   원 2개 정의(`get_circles()`==2, 배치 버튼 활성화) → 이미지2 실제 **Ctrl+클릭** → **원 2개
   그대로 유지**(수정 전엔 즉시 `[]`), **배치 버튼 계속 활성화**(수정 전엔 `False`),
   `tab._image_path`가 이미지1로 **유지**(수정 전엔 이미지2로 전환), `selected_paths()`가 정확히
   `[img_01.png, img_02.png]` 반환. **셋 다 원래 증상이 재현되지 않음.**
3. **Shift 범위선택(이미지1→이미지3)도 동일하게 원 유지** 확인.
4. **선택을 1개로 좁히면 정상 전환**: 다중 선택 상태에서 모디파이어 없이 이미지4를 클릭하면
   캔버스가 이미지4로 정상 전환되고 원이 클리어됨(이건 "새 이미지 로드"의 의도된 정상 동작,
   버그 아님) + `image_selected`가 **정확히 1회만** 발화(중복 emit 없음, 두 emit 경로가 겹치지
   않는다는 구현 로그 주장 확인).
5. **3b 배치 처리 실제 부분집합 실행을 이번에 처음으로 끝까지 확인**(1·2차 검증에서는 원 소실
   버그 때문에 전제가 성립하지 않아 스킵됐던 항목): 이미지1을 기준으로 원 2개 재정의 →
   `engine.run`/`engine.refilter` 몽키패치 후 실제 `▶ 추론 실행` 버튼 클릭(`QTest.mouseClick`)
   → `_last_result`/`_target_class_id`/`_target_classes` 자동 확정, 원 2개 여전히 유지 확인 →
   이미지2를 실제 Ctrl+클릭으로 부분집합 지정(배치 버튼 라벨 "(2장)"으로 갱신 확인) →
   `▶ 선택 이미지 일괄 처리` 버튼 실제 클릭 → `engine.run`이 **이미지2에 대해서만** 재호출됨
   (이미지1은 "현재 표시 중 + `_last_result` 존재" 캐시 재사용 경로를 실제로 탐, 호출 로그로
   확인) → `ZoneBatchResultDialog`에 캡처된 `rows`가 정확히 이미지1/이미지2 조합만 포함하고
   이미지3/이미지4는 아예 없음, 좌측 목록 `_status`에도 이미지3/이미지4는 항목 자체가 생기지
   않음(미처리) — "선택 이미지만 골라 일괄 처리"가 **실제로 부분집합에만 적용됨**을 실증.
6. **`inference_tab.py` 회귀 없음**: 별도 `InferenceTab` 인스턴스에서 `_multi_select is False`
   (기본 SingleSelection) 확인, 실제 클릭 시 `image_selected` 정상 발화, 검색 필터
   ("img_03"→1건, 해제→4건 복원, 디바운스 타이머 직접 트리거), `navigate(+1)`/`navigate(-1)`
   이전·다음 네비게이션 전부 정상.

총 43개 assertion 전부 PASS(실패 0건). 최초 작성한 baseline assertion 1건(로드 직후 이미 선택된
항목을 재클릭하면 Qt가 `currentItemChanged`를 재발화하지 않는 기존 Qt 동작을 "버그"로 잘못
기대해 FAIL로 나왔던 테스트 설계 실수)은 baseline을 다른 항목 클릭으로 조정해 재확인 후 제거 —
BUG-022 수정 자체와는 무관.

### 회귀/안전 확인
- `py_compile app/widgets/inference_image_list.py app/tabs/zone_analysis_tab.py
  app/tabs/inference_tab.py` 전부 통과.
- `git status --short` — 스크래치 디렉토리 밖 워크트리 변경 없음(디버그 코드 삽입/원복 없음,
  이번엔 소스 수정 자체가 필요 없었음).
- `tasklist`로 확인한 잔여 GUI 프로세스는 이전 세션들과 동일한 기존 창(PID 16488, 이번 세션이
  새로 띄운 것 아님) 하나뿐 — 이번 세션은 전부 `Bash` 동기 실행으로 완료, 백그라운드 프로세스
  0건, 좀비 프로세스 없음.
- 스크래치 스크립트/합성 이미지는 전용 세션 스크래치 디렉토리에만 생성, 저장소에는 포함하지
  않음.

### 판정
**통과 — BUG-022 완전 해결 확인(2차 수정 유효, 3번째 재검증 시도에서 처음으로 재현 실패).**
`QA.md`의 BUG-022를 Open 테이블에서 제거하고 Closed 테이블로 이동, `docs/roadmap.md`의 R-C 3b
항목을 "구현+독립검증 통과 — BUG-022(P1) 완전 해결 반영"으로 갱신.
- 리더에게: **BUG-022(P1) 최종 해결 확인. R-C 3b(폴더 일괄 처리) 전체 스코프 — 정확성(1차 검증
  96 assertion) + 다중 선택 상호작용(이번 43 assertion, 부분집합 배치 처리 최초 실증 포함) 둘 다
  통과. 3c(Excel 내보내기) 착수 가능.**


---

## 2026-08-26 — 존 분석 탭 R-C 3c(Excel 내보내기) 검증: 신규 기능 3건 스펙 전체 마지막 라운드, 통과

워크트리 `D:\segmentation model-zone-analysis-tab`(`feature/zone-analysis-tab` 브랜치).
리더가 맡긴 R-C 3c(일괄 처리 결과 Excel 내보내기, 커밋 `143c518`+`caef517`) 검증 —
스펙 [zone-analysis-tab-features-2026-08-26.md](../specs/zone-analysis-tab-features-2026-08-26.md)의
마지막 라운드. 레이아웃 뼈대+3a+3b(BUG-022 완전 해결 포함)는 최신 커밋 `02835c7`까지
전부 검증 통과 상태라 이번 라운드는 3c 신규 부분 + 회귀만 확인.

### 환경 확인 (구현자가 로컬에서 못 했던 부분)
구현자가 로컬 셸의 기본 `python`에 `cv2`/`openpyxl`이 없어 `zone_metrics.py`의
`__main__` self-check를 실행하지 못했다고 보고했음 — `C:\Users\Feel\anaconda3\python.exe`
(이전 라운드들에서 `python main.py` 검증에 실제로 쓰인 것과 동일 인터프리터)로 직접 확인:
- `python -m py_compile app/core/zone_metrics.py app/widgets/zone_batch_result_dialog.py
  app/tabs/zone_analysis_tab.py app/widgets/inference_image_list.py` 전부 통과.
- `python app/core/zone_metrics.py` (self-check) → `zone_metrics self-check OK`.
- `import cv2, openpyxl, PyQt6, torch` 전부 정상 임포트(`openpyxl 3.1.5`, `cv2 4.13.0`).
- `main.py`를 동일 인터프리터로 실제 기동(offscreen) — 전처리(`_preload_libs`) →
  `QApplication` → `ProjectStartDialog` 노출까지 크래시 없음(콘솔에 `cp949` 코덱으로
  한글 로그 문자열을 못 쓰는 로깅 인코딩 경고만 발생 — 이번 기능과 무관한 기존 환경
  이슈, Windows 콘솔 코드페이지 문제. 파일 로거는 영향 없음. 버그로 등록하지 않음).
  프로세스는 확인 직후 `taskkill`로 정리.

### 골든 패스 (전용 스크립트, `QTest` 실이벤트, 저장소에 포함 안 함)
`QT_QPA_PLATFORM=offscreen`, `numpy/cv2/PIL/torch/matplotlib` 선행 임포트 후 PyQt6(기존
관례). `QMessageBox.*` no-op로 교체하며 호출 기록, `engine.run`/`engine.refilter`와
`load_checkpoint_meta`/`load_model_from_ckpt`만 몽키패치(결정론적 합성 `InferenceResult`
— 40×40 합성 이미지, 중심 (20,20) 반지름 8px 원판을 클래스1로 심음), `ZoneBatchResultDialog.exec()`도
몽키패치해 모달을 가로채고 인스턴스를 캡처. 나머지 실제 프로덕션 코드
(`zone_metrics.zones_from_circles`/`zone_stats`, `ZoneAnalysisTab._on_batch_process`,
`ZoneBatchResultDialog._on_export`, `export_zone_percentages_to_excel`)는 몽키패치 없이
그대로 실행.

1. **체크포인트 열기 버튼(`QTest.mouseClick`)** → `_model`/`_ckpt_path` 준비 확인.
2. **이미지 열기 버튼(다중 파일 4장)** → `_img_list.count()==4`, 첫 이미지 자동 선택 확인.
3. **▶ 추론 실행 버튼 클릭** → `_last_result` 확정, 단일 클래스 자동 타겟 확정
   (`_target_class_id==1`).
4. 캔버스에 원 1개(r=12, 합성 클래스1 원판 r=8보다 크게) 설정 → 배치 버튼 활성화 확인.
5. **미선택 상태에서 `selected_paths()`가 전체 4장 반환**(3a에서 이미 확인된 관례) 확인.
6. **▶ 선택 이미지 일괄 처리 버튼 실클릭** → `ZoneBatchResultDialog` 캡처, `rows` 8행
   (이미지4 × 존2[중심부/바깥쪽]) 생성 확인. 각 행의 퍼센티지를 numpy 오라클
   (`(x-20)²+(y-20)²<=12²` 중심부 마스크 vs `<=8²` 클래스1 마스크의 교집합/면적비)과
   대조 — 전부 일치(`abs(diff) < 1e-6`). 화면 `QTableWidget`의 셀 텍스트도 `rows`와
   1:1 일치(이미지명/존이름 문자열, `f"{pct:.2f}"` 반올림 표시 형식까지).
7. **"Excel로 내보내기" 버튼 실클릭** — `QFileDialog.getSaveFileName`을 고정 경로
   반환으로 몽키패치(기존 관례). 저장된 xlsx를 `openpyxl.load_workbook()`으로 재오픈해
   시트명(`zones`), 헤더(`이미지파일명`/`존이름`/`타겟비율(%)`, 볼드 폰트) 확인 후
   데이터 8행 전부를 화면 `QTableWidget` 값과 셀 단위로 대조 — 문자열/반올림값까지
   완전 일치(`abs(diff) < 1e-9`). 완료 `QMessageBox.information` 호출 확인.
8. **저장 취소 시나리오**: `getSaveFileName`이 `("", "")` 반환하도록 재몽키패치 후 같은
   버튼 재클릭 — 크래시 없음, 추가 메시지박스 호출 없음(조용히 무시) 확인.

### 회귀 확인
- 원 개수를 2개로 바꾸면 `_zone_list.count()==3`(중심부/링1/바깥쪽)으로 즉시 갱신,
  1개로 되돌리면 `2`로 복귀 — 3b/R2~R3 존 재계산 경로 정상.
- **R-A(오프라인 원 검출 팝업)**: `CircleDetectPreviewDialog.exec()`를 몽키패치해 모달
  회피 후 툴바 버튼 실클릭 — 열림/닫힘 정상, 크래시 없음.
- **R-B(threshold)**: `_conf_slider.setValue(50)` 변경 시 `_on_target_changed()`가
  예외 없이 재필터링 완료(`_last_result` 유지) 확인.
- 이번 라운드는 3a/3b의 다중 선택·상태아이콘·해상도 방어 로직을 다시 파고들지 않음
  (이미 최신 커밋 `02835c7`까지 독립검증 통과 상태, 리더 지시대로 회귀만 간단 확인).

### 프로세스 정리
- 확인용 `main.py` 기동 프로세스(PID 21700, 이번 세션이 새로 띄운 것) `taskkill //F`로
  종료 확인. 검증 스크립트 자체는 동기 실행(`QApplication.exec()` 호출 없이 위젯
  구성/시그널만 사용)이라 백그라운드 프로세스 없음. `tasklist` 최종 확인 결과 이전
  세션들과 동일한 기존 창(PID 16488) 하나만 잔존 — 좀비 프로세스 없음.
- 스크래치 스크립트/합성 이미지/합성 xlsx는 전용 세션 스크래치 디렉토리에만 생성,
  저장소에는 포함하지 않음. `git status --short` — 워크트리 소스 변경 없음(문서 갱신
  제외).

### 판정
**통과 — R-C 3c(Excel 내보내기) 구현+검증 완료. 신규 기능 3건(요청1 오프라인 팝업/
요청2 폴더+일괄처리/요청3 threshold) 스펙 전체 완료.**
`docs/roadmap.md`의 R-C 3c 항목을 "검증 대기"에서 "구현+독립검증 통과"로 갱신하고
스펙 전체 완료를 명시. `QA.md`는 이번 라운드에서 신규 버그 발견 없음(갱신 없음).
- 리더에게: **존(Zone) 분석 탭 신규 기능 3건 스펙(zone-analysis-tab-features-2026-08-26.md)
  전체가 검증까지 완료됐습니다. 다음 작업 판단 바랍니다.**
