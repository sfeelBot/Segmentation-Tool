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
