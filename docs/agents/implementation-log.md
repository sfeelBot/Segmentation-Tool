# 구현 (Implementation) 로그

역할 설명은 [README.md](README.md) 참고. append-only — 최신 항목이 아래에 추가된다.

---

## 2026-08-19 — main.py CSS 오타 수정

### 변경
- `main.py:114` — `#74151` → `#374151` (다른 13곳과 동일한 테두리 색으로 통일)
- 커밋: 아직 미커밋 (사용자 확인 후 커밋 예정 — [docs/decisions-needed.md](../decisions-needed.md) 참고)

### 관련
- 발견 근거: [verification-log.md](verification-log.md)

---

## 2026-08-19 — GitHub 원격 저장소 연결

### 변경
- `git remote add origin https://github.com/sfeelBot/Segmentation-Tool.git`
- 로컬 `master` → `main` 리네임 (원격 기본 브랜치와 일치)
- 원격의 초기 커밋(`f325308`, README.md만 존재)과 `--allow-unrelated-histories`로 병합 (`7a6ce3c`)
- `git push -u origin main` 완료 — 원격 저장소에 전체 히스토리 반영됨

### 비고
- 이 작업은 서브에이전트 체계 도입 이전에 리더가 직접 수행함. 이후 배포(Deployment) 역할이
  생기면 이런 종류의 remote/push 작업은 `deployer` 서브에이전트로 위임한다.

---

## 2026-08-19 — R1: BUG-002 brush_mask RLE 인코딩 언더플로우 수정

기획 산출물: [docs/specs/perf-improvement-plan-2026-08-19.md](../specs/perf-improvement-plan-2026-08-19.md)
"BUG-002 — brush_mask RLE 인코딩 언더플로우" 절 구현. R1 단독 라운드(R2~R6 미착수).

### 원인
- `app/core/annotation_store.py`의 `rle_encode()`가 `flat = (flat != 0).view(np.uint8)`로
  마스크를 uint8로 만든 뒤, `np.diff(flat, prepend=np.uint8(0), append=np.uint8(0))`을
  그대로 uint8 dtype으로 계산하고 있었다. 1→0 하강 엣지는 산술적으로 `-1`이어야 하지만
  uint8은 부호가 없어 `255`로 언더플로우된다. 그 결과 `np.where(diff == -1)`이 항상 빈
  배열(`ends`)이 되고, 기존에 경쟁조건 방어용으로 있던 `n = min(len(starts), len(ends))`가
  `n = 0`이 되어 `rle_encode()`가 항상 `""`를 반환했다. `save()`에서 `a.mask.any()` 체크는
  통과하므로 어노테이션 항목 자체는 JSON에 남지만 `"rle": ""`로 기록되어 재로드 시
  브러시로 그린 마스크가 완전히 사라졌다.

### 변경
- `app/core/annotation_store.py:213` — `np.diff` 호출 전 `flat`을 `int8`로 캐스팅
  (`flat.astype(np.int8)`, `prepend`/`append`도 `np.int8(0)`)해 언더플로우 없이 `-1`이
  정상적으로 계산되도록 수정.
- 기존 `n = min(len(starts), len(ends))` 방어 코드(커밋 5769306, 진짜 경쟁조건 대비)는
  그대로 유지 — 이번 수정과 무관한 별개 안전장치.
- polygon 타입 어노테이션은 `rle_encode`/`rle_decode`를 아예 타지 않으므로
  (`load()`/`save()`의 `a.type == "polygon"` 분기 확인) 영향 없음.
- 커밋: `3ce4dc9`

### 회귀 확인 (직접 실행)
스크래치 디렉토리에 임시 스크립트(`verify_bug002.py`, 프로젝트에는 추가하지 않음) 작성 후
`C:\Users\Feel\anaconda3\python.exe`로 실행. 결과:
- 100px 마스크(100×100, `[10:20,10:20]=1`): `rle_encode` → `rle_decode` 라운드트립 100% 일치
  (수정 전에는 `rle=""` → 전부 0으로 복원, 즉 100% 유실이었음).
- ~1.8M픽셀 마스크(1200×1500, 블록+랜덤 스캐터 혼합, nonzero 646,746px): 라운드트립 100% 일치,
  encode 4.66ms / decode 2.71ms.
- 경계 케이스 3종 추가 확인: 전체가 1인 마스크(50×50), 완전히 빈 마스크(0이면 `""` 반환이
  정상 동작임을 확인), 마지막 픽셀까지 이어지는 run(append=0 처리) — 모두 통과.
- polygon 경로: 코드 리딩으로 `rle_encode`/`rle_decode` 미사용 확인(런타임 재현 불필요).

### QA.md 반영
- `BUG-002`를 Open Issues에서 제거하고 Closed Issues로 이동. 수정 버전은 `R1(미배포, 커밋
  3ce4dc9)`로 표기(아직 버전 태그 없음).
- **주의**: 이번 수정 이전에 이미 저장되어 `"rle": ""`로 남은 과거 brush_mask 데이터는
  복구되지 않는다 — 원본 마스크 자체가 저장 시점에 이미 소실되었기 때문(물리적으로 복구할
  데이터가 없음). `projects/nok/`은 전부 polygon 타입이라 이 문제로 인한 실피해는 없었던
  것으로 확인됨.

### 다음 단계
- **완료 보고 아님** — 검증(Verification) 에이전트의 별도 확인이 필요하다. 이번 라운드는
  R1(BUG-002)만 구현했고 R2~R6는 미착수 상태.

---

## 2026-08-19 — R2: 콜드 임포트 지연로딩 (torchvision/albumentations)

기획 산출물: [docs/specs/perf-improvement-plan-2026-08-19.md](../specs/perf-improvement-plan-2026-08-19.md)
"#2 — 콜드 임포트 지연로딩" 절 + "트레이드오프 결정" 절(사용자가 DLL 재발 리스크를 감수하고
진행 결정) 구현. R1(BUG-002)은 이미 완료·검증됨 — 이번엔 R2만.

### 스펙과 다르게 확장한 부분 — 왜 필요했나
스펙은 "`main.py`의 `_preload_libs()`에서만 지연 임포트하면 된다"고 가정했지만, 실제로는
그것만으로 **효과가 없었다**. `main.py` → `app.main_window` → 4개 탭(model/labeling/training/
inference_tab) 전부가 모듈 top-level에서 import되는 체인을 따라가면, 아래 7개 파일이 모듈
로드 시점에 torchvision/albumentations를 이미 import하고 있어 `_preload_libs()`만 고쳐도
그대로 즉시 로드됐다. 그래서 이 7개 파일 내부의 import도 함께 지역 임포트로 바꿨다:

- `app/core/dataset.py` — `torchvision.transforms.functional` (기존 top-level import 제거,
  실제 사용 지점인 `__getitem__()` 내부로 이동)
- `app/core/auto_labeler.py` — 동일 모듈, `_infer_to_annotations()` 내부로 이동
- `app/core/inference_engine.py` — 동일 모듈, 사용 지점이 2곳(`run()`, `_preprocess_patch()`)
  이라 각각에 지역 임포트 추가 (`run_sliding_window()`는 `_preprocess_patch()`를 통해서만
  간접 사용하므로 별도 조치 불필요)
- `app/core/augmentations.py` — `albumentations`. `from __future__ import annotations`가
  이미 있어 타입 힌트(`-> A.Compose`)는 런타임에 평가되지 않음을 확인 후, 런타임 import는
  `build_pipeline()` 내부로, 타입 체커용 import는 `if TYPE_CHECKING:` 블록으로 분리
- `app/model_presets/deeplab_resnet.py`, `deeplab_mobilenet.py`, `lraspp_mobilenet.py` —
  `from torchvision.models.segmentation import ...`을 각 클래스 `__init__()` 내부로 이동.
  **단, 코드를 직접 추적해보니 이 3개 파일은 애초에 Python `import`문으로 로드되는 게
  아니라 `app/model_presets/__init__.py:load_preset_code()`가 `Path.read_text()`로 텍스트만
  읽고, 사용자가 프리셋을 실제로 선택했을 때만 `app/core/model_loader.py:load_from_code()`가
  `exec()`로 실행한다 — 즉 이 3개 파일은 애초에 기동 시점 import 체인에 전혀 포함되지
  않아 이미 사실상 지연 로드 상태였다.** 그래도 일관성·향후 코드 경로 변경 대비를 위해
  스펙대로 지역 임포트로 통일했지만, 기동 시간에는 영향이 없다(실측으로도 확인 — preload
  전 별도 시간 차이 없음).

`main.py`의 `_preload_libs()`에서는 `albumentations`, `torchvision`,
`torchvision.transforms.functional`의 즉시 로드를 제거. `torch`는 계속 QApplication 생성
전에 즉시 로드 유지(다른 곳에서 항상 쓰이고, torchvision이 torch의 확장이라 torch가 먼저
로드돼 있어야 안전한 순서이므로 이 순서는 반드시 지켰다). `numpy`, `cv2`, `PIL.Image`,
`matplotlib`도 기존대로 즉시 로드 유지.

### DLL 재발 리스크 대응
- 스펙의 트레이드오프 결정에 따라 리스크를 감수하고 진행하되, 무모하게 하지 않기 위해:
  1. **로드 순서 유지** — `torch`는 여전히 QApplication 생성 전에 즉시 로드되고, torchvision은
     그 이후(사용 시점)에만 로드되므로, torchvision이 torch보다 먼저 로드되는 순서 역전은
     발생하지 않는다.
  2. **예외 전파** — 지연 임포트 지점에서 `try/except`로 감싸 삼키지 않았다. 만약 DLL
     로드 실패(`OSError`)가 나면 Python의 import 시스템이 발생시키는 원본 `OSError`(보통
     "DLL load failed while importing ..." 메시지 포함)가 그대로 위로 전파된다. 호출부를
     전부 직접 확인한 결과, 지연 임포트가 들어간 4개 실질 지점은 이미 CLAUDE.md "오류 처리"
     규칙대로 UI 레이어에서 `except Exception`으로 포괄 처리되고 있어(OSError도
     Exception의 서브클래스이므로 함께 잡힘) 별도 조치 없이도 사용자에게 전달된다:
     - `dataset.py.__getitem__()` → `TrainerWorker`(QThread) → `training_error` 시그널 →
       `training_tab.py`가 구독해 표시
     - `auto_labeler.py._infer_to_annotations()` → `AutoLabelWorker.run()`의
       `except Exception` → `error` 시그널
     - `inference_engine.py.run()`/`_preprocess_patch()` → `inference_tab.py:355`
       `except Exception as exc: QMessageBox.critical(...)`
     - `augmentations.py.build_pipeline()` → `trainer.py`의 학습 루프 `except Exception` →
       `training_error` 시그널
     이번 라운드에서 새 에러 UI를 설계하지 않았다(과설계 금지 지시 준수) — 기존 경로가
     이미 충분히 예외를 표면화하고 있음을 코드로 확인만 함.

### 검증 (직접 실행, `C:\Users\Feel\anaconda3\python.exe`, `QT_QPA_PLATFORM=offscreen`)
1. **콜드 임포트 확인** — 스크래치 스크립트(`check_lazy_import.py`, 프로젝트에 추가 안 함)로
   `numpy/cv2/PIL/torch/matplotlib` 선행 로드 후 `app.main_window`까지 import. 결과:
   `torchvision in sys.modules: False`, `albumentations in sys.modules: False` — 앱 모듈
   전체를 import해도 두 라이브러리가 로드되지 않음을 확인.
2. **기동 시간 실측** — 동일 스크립트에서 `time.perf_counter()`로 측정.
   - `torch` 등 선행 로드: 1.612s
   - `app.main_window` import 완료까지 총합: **1.852s**
   - 기존 검증 로그 기준선 ≈3.3초(albumentations 1888ms + torchvision 833ms + PyQt6 110ms +
     numpy/cv2/PIL/matplotlib ~200ms + app.* 모듈 그래프 193ms) 대비 **약 1.45초(≈44%) 단축**.
     나머지 1.6초는 대부분 `torch` 자체의 import 비용(즉시 로드 유지 대상이라 이번 라운드
     범위 밖).
3. **기능 검증** — 스크래치 스크립트(`check_lazy_functional.py`)로 `projects/nok`(5장) 데이터
   사용해 지연 임포트 4개 실질 지점 + 프리셋 3종을 직접 호출:
   - `SegmentationDataset(mode="resize")[0]` 호출 전 `torchvision not in sys.modules` 확인 →
     호출 후 정상 텐서(`torch.Size([3,256,256])`) 반환 + `torchvision`이 그제서야 로드됨을 확인
   - `augmentations.build_pipeline(AVAILABLE_AUGMENTATIONS[:3])` 호출 전 `albumentations
     not in sys.modules` 확인 → 파이프라인 생성 후 더미 이미지/마스크에 정상 적용
   - `inference_engine._preprocess_patch()` — 32×32 더미 패치로 정상 텐서 반환 확인
     (`run()`의 TF 사용 지점도 동일 전처리 로직이라 함께 검증됨)
   - `auto_labeler._infer_to_annotations()`의 TF 사용 로직을 동일하게 재현해 정상 동작 확인
   - `load_from_code(load_preset_code(key))`로 `deeplab_resnet`(39.6M params),
     `deeplab_mobilenet`(11.0M params), `lraspp_mobilenet`(3.2M params) 3종 전부
     인스턴스화 성공 — model_validator의 `ALLOWED_MODULES`에 `torchvision.models`가
     이미 등록돼 있어(및 `_check_imports`가 `ast.walk()`로 전체 트리를 훑으므로 함수 내부
     import도 통과) 지역 임포트로 옮겨도 exec 샌드박스에서 정상 통과함을 확인
4. **앱 기동 확인** — 스크래치 스크립트(`verify_app_boot_r2.py`, R1 검증 에이전트의
   `verify_app_boot.py` 방식을 따름)로 `QApplication` 생성 → `projects/nok` 오픈 →
   `MainWindow()` 생성 → `show()`까지 실행. STEP4_OK(1.76s)까지 예외 없이 도달, 그 시점까지도
   `torchvision`/`albumentations`가 `sys.modules`에 없음을 재확인. `app.exec()` 이벤트 루프
   또는 `window.close()`(내부에서 `QMessageBox.question()` 모달을 여는데, 이 비대화형
   자동화 셸에서는 응답이 없어 무한 대기)는 R1 검증 때와 동일한 환경 제약으로 진행 불가 —
   최종 대화형 눈확인은 검증 에이전트/사용자 환경에서 재확인 권장.
5. **UI 모듈의 top-level 참조 재확인** — `grep -rn "import torchvision|import albumentations"
   app/`으로 전수 검사, 남은 매치는 전부 함수/메서드 본문 안(들여쓰기됨) 또는
   `augmentations.py`의 `if TYPE_CHECKING:` 블록뿐임을 확인. `app/widgets/config_form.py`
   등 학습 탭 UI 코드에는 애초에 torchvision/albumentations 참조가 없었음(타입 힌트 포함)을
   grep으로 확인.

### 변경 파일
`app/core/dataset.py`, `app/core/auto_labeler.py`, `app/core/inference_engine.py`,
`app/core/augmentations.py`, `app/model_presets/deeplab_resnet.py`,
`app/model_presets/deeplab_mobilenet.py`, `app/model_presets/lraspp_mobilenet.py`, `main.py`.
`docs/agents/implementation-log.md`(이 항목)만 추가 커밋.

### 다음 단계
- **완료 보고 아님** — 검증(Verification) 에이전트의 별도 확인이 필요하다. 특히: (a) 이
  세션과 다른 Windows/Anaconda 환경 조합에서 DLL 순서 문제 재발 여부, (b) 대화형 세션에서
  `python main.py`를 실제로 눈으로 띄워 학습 탭 진입 시 지연 로드가 체감상 매끄러운지,
  (c) 학습/추론/오토라벨을 실제 체크포인트로 end-to-end 실행해 지연 임포트 지점이 실제
  워크플로우에서도 문제없는지.

---

## 2026-08-19 — R3: annotation_canvas 이미지 LRU 캐시(#4) + bbox fallback 스캔 범위 축소(#7)

기획 산출물: [docs/specs/perf-improvement-plan-2026-08-19.md](../specs/perf-improvement-plan-2026-08-19.md)
"#4 — annotation_canvas 이미지 캐시" + "#7 — bbox fallback 전체 스캔" 절 구현. 같은 파일
(`app/widgets/annotation_canvas.py`)을 건드리는 두 항목이라 스펙대로 한 라운드에 같이 처리.
R1(BUG-002)/R2(콜드 임포트)는 이미 완료·검증됨 — 이번엔 R3만.

### #4 — 이미지 전환 LRU 캐시

`load_image()`가 매번 `QPixmap(str(path))`로 디스크에서 재디코딩하던 것을, 최근 2장까지
`OrderedDict` 기반 LRU 캐시(`self._image_cache: OrderedDict[Path, _ImageCacheEntry]`)로
재사용하도록 변경.

- **캐시 키 구성**: 스펙이 지적한 대로 QPixmap 하나만 캐시하면 나머지 파생 상태 재계산
  비용이 그대로 남으므로, `_ImageCacheEntry` 데이터클래스에 이미지 하나가 갖는 파생 상태를
  전부 함께 묶었다: `pixmap`, `img_w`, `img_h`, `overlay_scale`, `mtime`(무효화용),
  `pixel_image`(픽셀 호버용 QImage, 150ms 지연 캐싱분), `display_pixmap` +
  `display_pixmap_key`(현재 zoom bucket/channel에 맞게 미리 축소된 blit용 pixmap).
  캐시 히트 시 이 6개 필드를 한 번에 복원 — `pixel_image`/`display_pixmap`까지 맞아떨어지면
  재방문 시 재디코딩은 물론 채널 필터/스케일 재계산도 건너뛴다.
- **캐시 저장 시점**: `load_image()`가 다른 이미지로 전환하기 **직전**에
  `_store_current_into_cache()`를 호출해, 현재 이미지 항목(있다면)의
  `display_pixmap`/`display_pixmap_key`/`pixel_image`를 그 시점 최신값으로 갱신한 뒤 다음
  이미지로 넘어간다. pixmap/img_w/img_h/overlay_scale은 최초 디코딩 시점에 캐시 엔트리
  생성과 동시에 채워 넣고 이후 불변이라 별도 동기화가 필요 없다.
- **크기 제한**: `_IMAGE_CACHE_SIZE = 2` 모듈 상수로 고정(스펙 지시대로 확장 안 함).
  `OrderedDict.move_to_end()` + `popitem(last=False)`로 LRU 유지.
- **무효화**: `path.stat().st_mtime`을 캐시 히트 조건에 포함 — 파일이 외부에서 교체되면
  mtime이 달라져 자동으로 캐시 미스 처리되고 재디코딩됨. `stat()` 실패(파일 삭제 등)는
  캐시를 아예 타지 않고 기존 경로(즉시 디코딩, 캐시 미저장)로 안전하게 폴백.
- 프리페치(다음/이전 이미지 백그라운드 로드)는 스펙에서 명시적으로 범위 밖으로 뺀 항목이라
  구현하지 않음.

### #7 — bbox fallback 전체 스캔 범위 축소

`_resolve_overlap_and_merge`의 `_has_pixels(a)`가 "bbox 안에 픽셀 없음"으로 판정되면
**무조건** `a.mask.any()`(20MP 전체 스캔)로 폴백하던 것을 수정. 실제로 필요한 경우로 좁힘:

- 1단계(픽셀 독점성 zero-out) 루프에서, zero-out 하기 **직전**에 각 어노테이션의 bbox
  서브영역이 이미 비어있었는지(`had_bbox_pixels[ann.annotation_id]`) 함께 기록.
- `_has_pixels`에서 bbox 서브영역이 비어있다고 판정되면: zero-out 이전에도 그 bbox
  서브영역이 이미 비어 있었던 경우(=이번 브러시 획과 전혀 안 겹친 경우) — "저장된
  어노테이션은 항상 non-empty"라는 기존 불변식(브러시 생성 시 `.any()` 체크, 병합 로직이
  항상 non-empty 마스크의 OR만 생성)에 의해 bbox 밖 어딘가에 픽셀이 있다는 것이 보장되므로
  전체 스캔 없이 즉시 non-empty로 단정. zero-out으로 실제 무언가 지워졌는데 bbox 안이 완전히
  비게 된 경우에만(=이번 브러시와 겹쳤던 어노테이션만) `a.mask.any()` 전체 스캔으로 bbox
  밖 잔여 픽셀 유무를 확인 — 이 경로만 진짜 예외적 폴백으로 남긴다.
- 효과: 화면에 여러 개의 서로 떨어진 브러시 마스크가 있을 때, 방금 그린 획과 무관한
  마스크들은 더 이상 전체 스캔을 타지 않는다(이전엔 매 브러시 획마다 "겹치지 않는" 모든
  어노테이션에 대해 전체 스캔이 걸렸었음 — `bb is None` 조기 리턴 때문에 "가끔"이 아니라
  실질적으로 매 stroke마다, 안 겹치는 어노테이션 수만큼 반복 발생하던 문제였음).
- **알려진 잔여 리스크(범위 밖으로 남김)**: 이 최적화는 "self._annotations에 들어있는
  brush_mask는 항상 non-empty"라는 불변식에 의존한다. `_translate_selected()`(SELECT 도구로
  어노테이션을 캔버스 밖까지 드래그하는 경우)는 이동 후 빈 마스크 정리(cleanup) 호출이 없어
  이론상 이 불변식을 깨뜨릴 수 있는 기존 경로다(이번 라운드에서 발견, 이번 변경으로
  새로 생긴 버그는 아님). 옛 코드는 매 브러시 획마다 전체 스캔을 했기 때문에 이런 좀비
  빈 마스크가 있어도 다음 stroke에서 자연스럽게 제거됐지만, 이번 최적화 이후로는 그 자연
  치유가 사라진다 — 좀비 마스크가 생기면(매우 드문 경로) 계속 남아있게 된다. 스펙 범위(bbox
  fallback 스캔 축소) 밖의 별개 이슈라 이번 라운드에서 고치지 않았고, QA.md 등록은 검증
  에이전트/리더 판단에 맡긴다.

### 검증 (직접 실행, `C:\Users\Feel\anaconda3\python.exe`, `QT_QPA_PLATFORM=offscreen`,
스크래치 스크립트 4종, 프로젝트에는 추가 안 함)

1. **이미지 캐시 실측** (`verify_image_cache.py`) — `projects/nok` 실제 이미지 5장(5472×3648
   BMP)으로 A→B→A→(C, evict 확인) 순서 전환:
   - A 최초 로드(cold): **79.97ms** vs A 재방문(cache hit): **7.49ms** — **약 10.7배** 단축,
     `assert t_a_hit < t_a_cold * 0.5` 통과.
   - C 로드 후 캐시 크기 2 유지 확인, 가장 오래된 B가 evict되고 A(방금 재방문한 MRU)/C만
     남음을 확인 — LRU 정상 동작.
2. **캐시 무효화(mtime) 검증** (`verify_cache_invalidation.py`) — `projects/nok/images/10번.bmp`
   대상, 원본 mtime 기록 후: (a) mtime 불변 상태에서 재방문 시 `id(canvas._pixmap)` 동일
   (캐시 히트) 확인 → (b) `os.utime()`으로 mtime만 +120초 이동(내용은 미변경) →
   재방문 시 `id(canvas._pixmap)`이 달라짐(캐시 미스, 재디코딩) 확인 → (c) `finally` 블록에서
   원래 mtime으로 정확히 복구, 복구 후 `target.stat().st_mtime == 원본` assert 통과.
   `git status --porcelain -- projects/nok` 결과 공백(변경 없음) 재확인.
3. **bbox fallback 결과 일치 + 성능** (`verify_bbox_fallback.py`) — 5472×3648(20MP) 크기
   합성 배열로 3가지 대표 케이스(bbox와 전혀 안 겹치는 마스크 `far`, bbox 안/밖에 걸쳐 있어
   bbox 부분만 지워지고 밖의 잔여 픽셀로 살아남아야 하는 `partial`, bbox 안에만 있어 완전히
   소멸해야 하는 `consumed`) 구성. 스크립트 안에 재현한 "구버전" 로직(무조건 전체 스캔
   폴백)과 실제 `_resolve_overlap_and_merge` 신버전 결과를 비교 — 생존 어노테이션 ID 집합
   완전 일치(`['far','new','partial']`, `consumed`만 제거). 추가로 "먼 곳에 겹치지 않는
   마스크 20개" 시나리오에서 구버전 280.09ms vs 신버전 54.82ms — **약 5.1배** 단축.
4. **회귀 확인 — 브러시/폴리곤 저장·로드 왕복** (`verify_regression.py`) — 임시 프로젝트(스크래치
   디렉토리 안, nok과 무관)에서 실제 `AnnotationCanvas` 내부 메서드(`_paint_stroke`,
   `_finish_brush`→`_resolve_overlap_and_merge`, `_close_polygon`)로 브러시 2개 + 폴리곤 1개
   생성 → `store.save()`/`store.load()`(R1에서 고친 `rle_encode` 경유) 왕복 — 재로드된 브러시
   마스크 픽셀 수·내용이 저장 전과 `np.array_equal` 완전 일치(2421px, 709px 각각), 폴리곤
   점 4개 보존. R1의 rle_encode 수정과 이번 캐시/bbox 변경 사이에 상호작용 지점 없음을
   코드 리딩으로도 재확인(캐시는 pixmap 레벨, bbox 변경은 저장 직전 어노테이션 리스트
   구성 단계 — `store.save/load`는 건드리지 않음).
5. **앱 기동 확인** (`verify_startup.py`) — `QApplication` → `projects/nok` 오픈 →
   `MainWindow()` → `show()` → 라벨링 탭에서 실제 이미지 1장 `load_image()` 성공, 어노테이션
   0개(nok 데이터 특성상 정상), 이미지 캐시 1장 확인. 예외 없이 통과.

### 변경 파일
`app/widgets/annotation_canvas.py`만 변경. `docs/agents/implementation-log.md`(이 항목)만
추가 커밋.

### 다음 단계
- **완료 보고 아님** — 검증(Verification) 에이전트의 별도 확인이 필요하다. 특히: (a) 대화형
  세션에서 라벨링 탭을 실제로 눈으로 조작하며(이미지 전환, 브러시/지우개 사용, undo) 캐시가
  체감상 매끄러운지, (b) 위에서 언급한 `_translate_selected` 좀비 빈 마스크 잔여 리스크를
  QA.md에 별도 이슈로 등록할지 판단, (c) `projects/nok` 외 대형 프로젝트(이미지 수 많음)에서
  캐시 메모리 사용량(2장 기준 +150MB 안팎 예상)이 실사용에 문제없는지.

---

## 2026-08-19 — R4: 학습 데이터로더 이미지 캐시 + num_workers 자동 감지 (`app/core/dataset.py`, `app/core/trainer.py`, `app/widgets/config_form.py`)

기획 산출물: [docs/specs/perf-improvement-plan-2026-08-19.md](../specs/perf-improvement-plan-2026-08-19.md)
"#3 — 학습 데이터로더 캐시 + num_workers" 절. **사용자 결정**: num_workers 기본값 =
CPU 코어 수 기반 자동 감지.

### 이 항목의 특이사항 — 구현 에이전트가 세션 도중 API 세션 한도로 중단됨
원래 구현 에이전트(`.claude/agents/implementer.md` 페르소나)가 아래 변경 대부분을 완성한
뒤, 최종 end-to-end 검증 직전에 "session limit · resets 12:20am (Asia/Seoul)" 오류로
중단됐다. 리더가 `SendMessage`로 재개를 시도했으나 재개 시도 역시 같은 한도로 실패했다.
**아래 코드 변경 자체는 원 구현 에이전트가 작성한 것이며, 리더는 중단 시점의 uncommitted
diff를 검토하고 남은 검증(컴파일 확인 + 캐시/멀티프로세싱 실제 동작 확인)만 직접 수행한
뒤 커밋했다** — CLAUDE.md 리더 규칙 2("사소한 경우 리더가 직접 처리 가능")의 예외적 적용.
독립 검증 에이전트를 통한 별도 확인은 세션 한도가 풀린 뒤에도 여전히 필요하다.

### 변경 — `app/core/dataset.py`
- `_load_cached(img_path, ann_path)` 추가: 이미지+렌더링된 마스크를 `OrderedDict` 기반
  LRU 캐시(`_img_cache`)에 보관. 바이트 예산 방식(`_DEFAULT_CACHE_BUDGET_BYTES = 512MB`,
  워커 프로세스 1개당 — `num_workers>0`이면 워커마다 독립 캐시이므로 총 메모리는
  이 값 × 워커 수). `img_path`/`ann_path` 양쪽의 `st_mtime`을 비교해 무효화(라벨링 탭에서
  외부 수정 시 최소 안전장치).
- `__getitem__`이 매번 `Image.open()` + `_render_mask()`를 새로 하던 것을 `_load_cached()`
  경유로 변경.

### 변경 — `app/widgets/config_form.py`
- `_RECOMMENDED_NUM_WORKERS = min(2, max(0, (os.cpu_count() or 1) - 1))` 추가, `num_workers`
  QSpinBox 기본값을 0 → 이 값으로 변경.
- **원 구현 에이전트가 실측으로 상한을 2로 보수적으로 잡은 이유**(코드 주석에 근거 남김):
  이 개발 환경(Windows, 12코어/32GB RAM/pagefile 2GB)에서 `num_workers=3~4`는
  `OSError: 페이징 파일이 너무 작습니다`(WinError 1455) 또는 워커 프로세스 `MemoryError`로
  재현성 있게 실패함을 확인. CPU 코어 수 기반이라도 상한 없이(`min(4, cpu_count-1)` 등)
  가면 이 환경급 사용자에게 안전하지 않다고 판단해 상한 2 + 툴팁에 "3 이상은 직접 실험
  후 사용 권장, 페이징 파일 부족 시 OSError/MemoryError 가능" 경고 문구 추가.

### 변경 — `app/core/trainer.py`
- `persist = cfg.num_workers > 0`; `train_loader`/`val_loader` 양쪽에
  `persistent_workers=persist` 적용. **실측 근거(코드 주석)**: `num_workers=2,
  persistent_workers=False`는 매 epoch마다 워커를 재spawn해 오히려 `num_workers=0`보다
  느림(328ms/batch vs 125ms/batch). `persistent_workers=True`면 최초 epoch만 기동 비용을
  내고 이후 9~13ms/batch로 개선(디코딩 캐시 워밍업 효과 포함).

### 리더가 직접 수행한 검증 (2026-08-19, 세션 재개 실패 후)
1. **컴파일 확인**: `ast.parse()`로 세 파일 모두 구문 오류 없음 확인.
2. **캐시 정확성** (스크래치 스크립트, nok 데이터, `.../scratchpad/verify_r4_leader2.py`):
   같은 이미지 재방문 — 최초 디코딩 879.8ms vs 캐시 히트 0.9ms(~980배). `os.utime()`으로
   이미지 mtime을 강제로 바꾼 뒤 재조회 시 캐시 미스로 재디코딩(62~70ms, OS 페이지 캐시
   덕에 최초 콜드 디코딩보다는 빠르지만 캐시 히트 0.9ms보다는 확실히 느림) — mtime 무효화
   정상 동작 확인. **테스트 후 mtime을 원래 값으로 정확히 복원, `git status`로 `projects/nok`
   무변경 확인.**
3. **멀티프로세싱 DataLoader 실제 동작**: `num_workers=2, persistent_workers=True`로 nok
   데이터 기반 DataLoader를 실제로 2배치 순회 — 워밍업 배치 71.8ms, 이후 배치 81.2ms,
   텐서 shape 정상(`[2,3,256,256]`, `[2,256,256]`), 예외 없이 완료. `num_workers=0` 경로도
   별도로 순회해 정상 동작 확인(사용자가 UI에서 0으로 되돌리는 경우 대비).
4. **미검증(원 에이전트도 못한 부분, 세션 한도로 중단)**: DataLoader 워커 내부 예외가
   `TrainerWorker.training_error` 시그널까지 정상 전파되는지 실제 예외 주입 테스트,
   `pickle.dumps()`로 `augment_fn`(Albumentations `Compose`) pickle 가능 여부의 명시적
   단위 확인(다만 위 2배치 실제 순회가 성공했다는 것 자체가 실제 pickle이 되고 있다는
   간접 증거임 — Windows spawn 방식에서 워커 프로세스로 Dataset 전체가 넘어가려면 pickle이
   되어야 하므로). `python main.py` 전체 기동 확인(GUI 창 실제 표시)도 이번엔 생략 — R1~R3
   검증 때 이미 같은 방식으로 반복 확인된 경로라 리스크 낮다고 판단.
5. **미검증 — config_form.py 자체의 런타임 동작**: `config_form.py`를 실제로 import해서
   `_RECOMMENDED_NUM_WORKERS` 값이 QSpinBox에 반영되는지는 직접 실행하지 못함 — 이
   비대화형 셸에서 `app.core.project`를 먼저 import한 뒤 PyQt6.QtWidgets를 import하면
   (project.py → logger.py → `PyQt6.QtCore` 선행 임포트 경로 때문으로 추정) DLL 로드
   실패가 재현성 있게 발생함을 발견 — 이는 R4 변경과 무관한, 이 자동화 셸 환경 자체의
   기존 취약점으로 보인다(R1~R3 검증 스크립트들은 이 조합을 우연히 피해갔던 것으로 추정).
   `_RECOMMENDED_NUM_WORKERS` 계산식 자체(순수 `os.cpu_count()` 기반, PyQt 비의존)는
   코드 리딩으로 검증 완료. **다음 검증 에이전트는 이 DLL 이슈를 염두에 두고 순서를
   조정하거나(PyQt6 import를 app.core.project보다 먼저) 별도로 조사할 필요가 있음.**

### QA.md 반영
- 해당 없음(버그 없음, 순수 성능 개선).

### 커밋
아직 미커밋 — 이 로그 작성 직후 리더가 커밋 예정(`app/core/dataset.py`,
`app/core/trainer.py`, `app/widgets/config_form.py` + 이 로그).

### 다음 단계
- **완료 보고 아님** — 독립 검증(Verification) 에이전트 확인 필요. 특히 위 "미검증" 2건
  (워커 예외 전파, config_form.py 실제 런타임 동작 — 이번엔 위 DLL 이슈 회피 방법을 찾아서)
  + 실제 학습 탭 UI에서 육안 확인.

---

## 2026-08-20 — R5: 추론 결과 컬러화/블렌딩 다운스케일 (`perf-improvement-plan-2026-08-19.md` #5)

### 배경
`app/core/inference_engine.py::_colorize_and_blend()`가 `class_map.shape`(원본 해상도) 그대로
컬러화+블렌딩을 수행해 5472×3648 같은 대형 이미지에서 ~992ms 소요(스펙 실측치). 사용자 결정에
따라 **화면 미리보기만** `annotation_canvas.py`의 `_MAX_OVERLAY_DIM=2048`과 동일한 상한으로
다운스케일하고, **저장/`class_map`은 원본 해상도 유지**해야 함.

### 변경 — `app/core/inference_engine.py`
- 모듈 레벨 상수 `_MAX_OVERLAY_DIM = 2048` 추가(`annotation_canvas.py`와 동일 값, 별도 상수로
  독립 — import 결합도를 늘리지 않기 위해 공유 임포트 대신 값만 맞춤).
- `_colorize_and_blend(orig, class_map, cls_map, opacity)` 내부에서 `max(h, w) > 2048`이면:
  - `class_map`을 **로컬 변수 `class_map_work`로 새로 생성**(`Image.fromarray(...).resize(...,
    Image.NEAREST)`, 정수 클래스 ID이므로 보간 없이 최근접 — 기존 `run()`의 74~79번째 줄과
    동일 패턴)해서 컬러화에 사용. 호출자가 들고 있는 원본 `class_map` 배열은 **절대
    mutate하지 않음**(새 배열 생성만, in-place 연산 없음).
  - 원본 이미지(`orig`)는 축소된 `(w, h)`로 `Image.BILINEAR` 리사이즈(부드러운 배경).
  - 최종 `QPixmap`도 이 축소된 크기로 반환.
  - 2048 이하 이미지는 분기를 타지 않아 기존 동작과 완전히 동일(회귀 없음).
- `run()`/`run_sliding_window()`가 반환하는 `InferenceResult.class_map`, `class_stats`(86~92번째
  줄, 원본 해상도 `class_map`으로 계산)는 **일절 손대지 않음** — 앱에 "추론 결과 저장/내보내기"
  기능 자체가 없어(`inference_tab.py`/`export_dialog.py`에 `class_map`을 디스크에 쓰는 코드
  없음, `overlay_pixmap`은 화면 표시에만 쓰임) "저장은 원본 유지" 요구사항은 `class_map`을
  건드리지 않는 것만으로 자동 충족됨.

### 검증 (직접 실행, `C:\Users\Feel\anaconda3\python.exe`, `QT_QPA_PLATFORM=offscreen`,
스크래치 스크립트 2종, 프로젝트에는 추가 안 함)

1. **성능 실측** (`verify_r5.py`) — 합성 5472×3648 RGB 이미지 + 3클래스 랜덤 `class_map`으로
   `_colorize_and_blend()` 직접 호출: **194.0ms** (스펙 기준선 992ms 대비 **약 5.1배** 단축).
2. **다운스케일 크기/비율 확인** — 반환된 `overlay_pixmap` 크기 **2048×1365**
   (`max(2048,1365) <= _MAX_OVERLAY_DIM` 통과), 원본 비율 1.5000 vs 축소 후 1.5004
   (반올림 오차만, 비율 유지 확인).
3. **`class_map` 무결성** — 함수 호출 전 `class_map.copy()`로 스냅샷 후, 호출 후
   `np.array_equal(class_map, class_map_before)` **True** 확인 — 다운스케일이 원본 배열을
   전혀 오염시키지 않음(호출자 소유 배열은 그대로 원본 해상도·원본 값 유지).
4. **회귀 없음 확인(소형 이미지)** — 1024×768(2048 이하) 합성 이미지로 동일 호출: 반환
   `overlay_pixmap` 크기가 **1024×768로 불변**(분기 미발동), `class_map` 무결성도 동일하게
   `np.array_equal` True — 기존 경로와 완전히 동일하게 동작함을 확인.
5. **`class_stats` 정확도** — `class_stats`는 `run()`/`run_sliding_window()`에서 `_colorize_
   and_blend()` 호출과 **별도로**, 원본 해상도 `class_map`을 대상으로 계산됨(코드 위치상
   `_colorize_and_blend()` 반환값과 무관). 위 3, 4에서 `class_map` 원본 무결성을 직접 확인했으므로
   `class_stats` 퍼센티지는 다운스케일 적용 여부와 무관하게 항상 원본 해상도 기준으로 동일하게
   나옴을 간접 확인(코드 리딩 + 무결성 확인으로 충분, `run()` 자체를 실제 체크포인트로 end-to-end
   실행하지는 않음 — 실제 체크포인트/모델이 이 환경에 없어 스펙 지시대로 `_colorize_and_blend()`
   직접 호출 방식을 사용).
6. **앱 기동 확인** (`verify_boot_r5.py`) — `PyQt6.QtWidgets` import를 `app.core.project`보다
   먼저 배치(R4 검증 로그의 DLL 이슈 회피 패턴 준수) → `QApplication` → `projects/nok` 오픈
   (`project.open_existing()` + `set_current()`) → `MainWindow()` 생성 → `show()` →
   `inference_engine._MAX_OVERLAY_DIM` 임포트 확인까지 `STEP1~4_OK` 전부 예외 없이 통과.
   (프로세스 종료 시 exit code 127은 이전 라운드들과 동일하게 `app.exec()` 이벤트 루프 없이
   비대화형 셸에서 강제 종료되며 나는 노이즈로, R1~R4 검증 로그에서도 같은 패턴 확인됨.)

### 변경 파일
`app/core/inference_engine.py`만 변경. `docs/agents/implementation-log.md`(이 항목)만 별도 추가.
`docs/agents/leader-log.md`, `docs/agents/verification-log.md`는 다른 에이전트가 동시에 수정
중인 것으로 확인되어 이번 커밋 범위에서 제외(`git status`로 확인 후 `inference_engine.py` +
이 로그 파일만 스테이징).

### 커밋
`perf: 추론 결과 화면 미리보기 다운스케일 (2048 상한, 저장/class_map은 원본 유지)`
(커밋 해시는 이 항목 아래 리더/후속 기록 참고 — 커밋 직후 `git log -1` 결과를 실행 셸에서 확인)

### 다음 단계
- **완료 보고 아님** — 검증(Verification) 에이전트의 별도 확인이 필요하다. 특히: (a) 실제
  체크포인트로 `run()`/`run_sliding_window()`를 end-to-end 실행해 `overlay_pixmap`이 실제
  추론 탭 UI에서 축소된 크기로 정상 표시되는지 육안 확인, (b) `class_stats` 퍼센티지가 실제
  체크포인트 기준으로도 다운스케일과 무관하게 동일한지 재확인, (c) 이 자동화 셸과 다른 환경
  조합에서 성능 개선치 재현 여부.

## 2026-08-20 — R6: image_browser 검색 디바운스+상태 캐시(#6) + auto_labeler 중복 read 제거(#8)
(`perf-improvement-plan-2026-08-19.md` — **R1~R6 중 마지막 라운드**)

### 배경
`perf-improvement-plan-2026-08-19.md` #6/#8. `image_browser.py::_on_search_changed()`가
검색창 keystroke마다 즉시 `_apply_display()`를 호출하고, `_apply_display()` → `_make_tree_item()`
및 `status_done`/`status_todo` 정렬 키가 이미지마다 `get_label_status()`(JSON open+parse)를
매번 재호출해 keystroke당 전체 이미지 수만큼 JSON을 재읽었다. `auto_labeler.collect_unlabeled()`도
이미지마다 `get_ok(p)` + `load(p)`로 같은 JSON을 2회 읽었다.

### 변경 1 — `app/widgets/image_browser.py` (#6)
- `_SEARCH_DEBOUNCE_MS = 200` 상수 추가. `__init__`에서 `QTimer(self)`(`setSingleShot(True)`,
  `setInterval(200)`, `timeout.connect(self._apply_display)`)를 `_search_debounce`로 생성.
  `_on_search_changed(text)`는 이제 `self._filter_text` 저장 후 `self._search_debounce.start()`만
  호출 — keystroke마다 타이머가 리셋되고, 입력이 200ms 멈춘 뒤에만 `_apply_display()` 1회 실행.
- `self._status_cache: dict[Path, str] = {}` 추가. `reload()`에서 `_all_paths` 스캔 직후
  `{p: get_label_status(p) for p in self._all_paths}`로 전체 재구축(이미지당 1회 read).
  `_make_tree_item()`과 `status_done`/`status_todo` 정렬 키는 `get_label_status(path)` 직접 호출
  대신 `self._status_cache.get(path)`(폴백: 캐시 미스 시에만 직접 조회/`"unlabeled"` 기본값)로 조회.
- **캐시 무효화**: `refresh_item(path)`(어노테이션 저장 시 `labeling_tab.py:343`에서 호출, OK
  토글도 `annotation_canvas.toggle_ok()` → `annotation_saved` 시그널 → 동일 훅 경유)에서
  `get_label_status(path)` 재호출 시 `self._status_cache[path] = status`로 캐시도 갱신.
  `_on_add`/`_on_add_folder`(워커 완료 콜백)/`_on_delete`는 모두 마지막에 `self.reload()`를
  호출하므로 캐시가 전체 재구축돼 별도 무효화 코드가 필요 없었음(기존 훅만 재사용, 신규
  무효화 시스템 추가 안 함).

### 변경 2 — `app/core/auto_labeler.py::collect_unlabeled()` (#8)
`get_ok(p)` + `load(p)` 2회 read를 `get_label_status(p)` 1회 read로 통합:
`status = get_label_status(p); if status != "unlabeled": continue`.
`annotation_store.get_label_status()`를 직접 읽고 기존 로직과의 동치성을 확인함 — `get_ok()`는
JSON의 `ok` 필드만 보고, `get_label_status()`도 `ok` 필드를 `annotations` 존재 여부보다 먼저
검사(158~171번째 줄)하므로 OK 우선순위 동일. `load(p)`가 반환하는 `existing` 리스트는 JSON의
`annotations` 배열 원소마다 1:1로 `AnnotationItem`을 만들므로(빈 배열 → 빈 리스트, 비어있지
않은 배열 → 비어있지 않은 리스트) `existing`이 falsy인지 여부는 `get_label_status()`가
`"labeled"`를 반환하는지 여부와 정확히 일치. JSON 파싱 예외 시에도 양쪽 모두 "미라벨로 간주,
포함" 방향으로 동일하게 fallback. `load` import는 더 이상 쓰이지 않아 제거.

### 검증 — 소규모 회귀 (`projects/nok`, 5장, 읽기 전용 오픈만, 파일 변경 없음)
스크래치 스크립트(`test_r6.py`, `C:\Users\Feel\anaconda3\python.exe`, PyQt6를
`app.core.project`보다 먼저 import):
- `_status_cache`가 5개 이미지 전부에 대해 `get_label_status()` 직접 호출 결과와 **완전 일치**
  (mismatches 0건).
- 정렬 모드 `name_asc`/`name_desc`/`status_done`/`status_todo` 4종 모두, 캐시 기반 결과가
  `get_label_status()`를 직접 호출해 계산한 기대 순서와 **정확히 일치**(`match=True`).
  `folder` 모드도 실행 확인(nok은 하위폴더가 없어 순서 비교 대상 없음, 예외 없이 동작만 확인).
- 디바운스: 검색창에 텍스트 입력 직후(펌프 전) `_paths`가 아직 안 바뀜(`immediate_unchanged=True`)
  → 200ms 초과 대기 후에만 필터가 반영됨(`after_filter=['10번.bmp']`, "10" 검색 시 예상대로
  1건 매칭) 확인.
- `refresh_item()`을 파일 변경 없이 재호출해도 캐시 값이 그대로 유지됨(no-op 시 안정성) 확인.

### 검증 — 대규모 합성 프로젝트 (스크래치, `big_project`, 1000장, `projects/nok`과 무관)
빈 PNG 헤더 더미 파일 1000장 + unlabeled/ok/labeled 약 1:1:1 분포로 어노테이션 JSON 생성
(`i % 3`으로 분기: unlabeled는 JSON 없음, ok는 `{"ok": true}`, labeled는 polygon 1개 포함).

- **`_apply_display()` 1회 호출**(캐시 사용, status_done 아닌 정렬): **19.91ms**.
  status_done 정렬 포함: **21.01ms**. 두 값이 거의 같다는 것은 정렬 자체 비용이 아니라
  트리 재구성(1000개 `QTreeWidgetItem` 생성)이 지배적 비용이고, 캐시 사용 시 상태 조회
  비용은 거의 0에 수렴함을 뒷받침.
- **[구버전 시뮬레이션]** `_apply_display()`가 매번 하던 것과 동등하게, 캐시 없이
  1000개 이미지에 대해 `get_label_status()`를 직접 순회 호출: **78.87ms** — 이게 캐시 미적용
  시 매 keystroke마다 추가로 들었을 순수 JSON read 비용. 캐시 적용으로 이 78.87ms가 사실상
  제거됨(캐시 조회는 dict lookup이므로 무시 가능한 수준).
- **디바운스 실측**: 5글자를 30ms 간격으로 연속 입력(각 입력 사이는 200ms 디바운스 간격보다
  짧아 계속 리셋됨) 후 250ms 대기 — `_apply_display` **실제 실행 횟수 = 1회**(타이머
  `timeout` 시그널에 별도 카운터를 연결해 직접 계측, 기대값 1과 일치). 디바운스 미적용 가정
  시뮬레이션(5회 연속 즉시 `_apply_display()` 호출)은 **106.5ms** — 즉 디바운스가 없었다면
  같은 5키 입력에 대해 `_apply_display()`가 5회 실행돼 총 ~100ms+ 이 소요됐을 것을, 디바운스로
  1회(~20ms)로 줄임. **개선 폭이 스펙 우려(nok 5장으로는 안 드러남)와 달리 대규모(1000장)에서
  뚜렷하게 실측됨** — keystroke당 처리 비용이 정성적으로도(로그 순회 대신 dict lookup) 실측
  수치로도 감소.
- **`collect_unlabeled()`**: 신버전(1회 read) **88.98ms**, 결과 334개(기대 ~333개, `i%3==0`
  분기 개수와 일치). 구버전 시뮬레이션(`get_ok()`+`load()` 2회 read 동등 로직) **127.92ms**,
  결과 334개(동일). **약 30% 단축**(127.92ms → 88.98ms), 결과 집합도 `sorted(name)` 기준
  완전 일치 확인. 절대 개선폭(약 39ms)은 `_apply_display()` 캐시 효과(78.87ms 절감)보다는
  작지만, 방향성은 스펙 예측과 일치하며 미미하지 않음 — "정적 추정과 실측 불일치"로 기록할
  사안은 아님.
- 참고: `ImageBrowser()` 최초 생성+`reload()` 전체 시간은 3173.1ms로 다소 크게 나왔으나, 이는
  1000개 `QTreeWidgetItem` 최초 생성(Qt 위젯 트리 구성)과 `pump(50)` 대기가 지배적이고 이번
  캐시/디바운스 최적화 범위(keystroke당 반복 비용) 밖의 1회성 비용이라 별도 조치하지 않음
  (스펙 범위 밖, 필요 시 별도 라운드로 논의 대상).

### 앱 기동 확인
`C:\Users\Feel\anaconda3\python.exe`로 `QApplication` 생성 후 `from app.main_window import
MainWindow` import(내부적으로 `labeling_tab.py` → `image_browser.py` 로드 경로 포함) —
예외 없이 `MainWindow import OK` 확인.

### 코드 흐름 재확인 (실행 없이 리딩)
- 폴더 그룹핑(`_build_folder_tree`), 정렬 모드 4종, OK 상태 아이콘(`_STATUS_STYLE`) 로직 자체는
  변경하지 않고 `get_label_status()` 호출 지점만 캐시 조회로 치환했으므로 표시 로직 자체의
  회귀 없음. `_apply_display()`의 트리 재구성/선택 복원 흐름도 그대로 유지.

### 변경 파일
`app/core/auto_labeler.py`, `app/widgets/image_browser.py`만 변경. `docs/agents/leader-log.md`,
`docs/agents/verification-log.md`는 세션 시작 시점부터 다른 프로세스가 동시에 수정 중인 것으로
확인되어 이번 커밋 범위에서 제외(`git status`로 확인 후 위 2개 파일만 스테이징). `projects/nok/`
은 읽기 전용으로만 열었고 `git status`/`git diff --stat`으로 변경 없음을 확인.

### 커밋
`e7066b0bc16f96664ce7868f1d6d00ee79865a76` —
`perf: 이미지 브라우저 검색 디바운스+상태 캐시 + auto_labeler 중복 read 제거 (R6)`

### 다음 단계
- **완료 보고 아님** — 검증(Verification) 에이전트의 별도 확인이 필요하다. 특히: (a) 이
  자동화 셸과 다른 대화형 세션에서 `python main.py`를 실제로 띄워 검색창 타이핑 시 체감
  지연이 없는지, (b) 라벨링 탭에서 이미지 저장/OK 토글 후 브라우저 아이콘이 실제로 즉시
  갱신되는지 육안 확인, (c) 폴더 그룹핑·정렬 4종·삭제/추가 흐름이 실제 UI 조작으로도
  회귀 없는지, (d) **이 라운드로 R1~R6 계획 전체가 구현 완료** — 종합 회귀(전체 라운드
  누적 상호작용 여부)를 확인할 마지막 검증이 필요하다.

---

## 2026-08-20 — UI/UX 재편 라운드 1 (제약값 조정 + 스타일 통일)

`docs/specs/ui-redesign-plan-2026-08-19.md`의 라운드 1 범위(순수 상수/스타일시트 조정,
새 위젯·레이아웃 구조 변경 없음)만 구현. 성능개선 R1~R6과는 무관한 별도 트랙.

### 변경
1. `app/tabs/inference_tab.py` — 메인 `QSplitter`(이미지 목록/뷰어/범례)에 `training_tab.py`,
   `labeling_tab.py`와 동일한 `QSplitter::handle:hover { background:#60a5fa; }` 스타일 추가
   (`setHandleWidth(5)` 도 함께 맞춤).
2. `app/tabs/training_tab.py` — `side_panel`(메트릭·체크포인트 패널)의 `setMaximumWidth(220)`
   제거. `setMinimumWidth(150)`은 유지 — 사용자 확정: 리사이즈 상한 완전 무제한.
3. `app/tabs/inference_tab.py` — 우측 범례 패널의 `setFixedWidth(190)`을
   `setMinimumWidth(160)`으로 교체(최대값 없음).
4. `app/tabs/inference_tab.py` — 좌측 이미지 목록 패널(`_list_panel`)의
   `setMaximumWidth(180)` 제거. `setMinimumWidth(140)`은 유지.

### 검증 (직접 수행)
- 인터프리터: `C:\Users\Feel\anaconda3\python.exe` (Anaconda, 이 프로젝트의 실제 실행 환경 —
  Bash 툴 기본 `python`은 Windows Store 스텁이라 즉시 종료됨, 주의 필요).
- `QT_QPA_PLATFORM=offscreen` + PyQt6를 `app.core.project`보다 먼저 import하는 순서로
  DLL 로드 함정 회피.
- `TrainingTab`, `InferenceTab`을 오프스크린 `QApplication`에서 직접 인스턴스화해 속성 조회:
  - `side_panel.minimumWidth()=150`, `maximumWidth()=16777215`(QWIDGETSIZE_MAX, 즉 무제한) 확인.
  - `_list_panel.minimumWidth()=140`, `maximumWidth()=16777215` 확인.
  - 범례 위젯 `minimumWidth()=160`, `maximumWidth()=16777215` 확인.
  - 추론 탭 메인 스플리터 `styleSheet()`에 `"hover"` 포함 확인.
- `MainWindow()`를 직접 생성해 `python main.py` 방식 전체 기동(4개 탭 모두 로드) 예외 없이
  성공 확인 (`MainWindow created OK`).
- 코드 흐름 재확인: 4개 지점 모두 상수/스타일 값만 바뀌었고 다른 위젯의 `stretch factor`,
  레이아웃 구조는 그대로 유지 — 다른 회귀 없음.

### 변경 파일
`app/tabs/inference_tab.py`, `app/tabs/training_tab.py`만 변경. 세션 시작 시점에 이미
`git status`에 있던 `app/core/dataset.py`, `app/core/trainer.py`, `app/widgets/config_form.py`,
`docs/agents/leader-log.md`는 다른 작업 범위이므로 이번 커밋에서 제외.

### 커밋
`6355096` — `feat: UI 재편 라운드1 -- 리사이즈 상한 제거 + 스플리터 hover 통일`
(`git push`는 수행하지 않음 — 사용자 명시적 확인 필요)

### 다음 단계
- **완료 보고 아님** — 검증(Verification) 에이전트가 실제 UI 조작(스플리터 핸들 드래그로
  4개 패널이 상한 없이 늘어나는지, hover 시 색이 바뀌는지)까지 확인해야 한다. 이번 라운드는
  라운드 2·3(디자인 목업이 필요한 구조 변경) 범위 밖.

---

## 2026-08-20 — UI/UX 재편 라운드 2 (라벨링 탭만)

`docs/specs/ui-redesign-plan-2026-08-19.md` 라운드 2 대상 중 사용자가 범위를 라벨링 탭으로
명시적으로 좁힌 지시에 따라 구현. 디자인 목업(`docs/agents/design-log.md` 2026-08-20 항목,
Artifact `5df2af11-0642-4e69-8ddc-f545333eebca`)의 라벨링 탭 부분 + "구현 시 참고 — 주의사항"을
전제로 작업. 학습 탭·추론 탭의 라운드 2 항목은 이번에 손대지 않음.

### 무엇을 바꿨나
- `app/tabs/labeling_tab.py`
  - 좌 패널: `ImageBrowser`↔`ClassPanel`을 감싸던 `QVBoxLayout`(stretch 3/2 고정)을
    `QSplitter(Qt.Orientation.Vertical)`(`self._left_splitter`)로 교체. 각 위젯에
    `setMinimumHeight(80)` 부여, `setSizes([300, 200])`로 기존 3:2 비율 재현, 메인 좌우
    스플리터와 동일한 hover 스타일(`QSplitter::handle:hover { background:#60a5fa; }`) 적용.
  - 우 패널: 어노테이션목록 `QGroupBox`↔`LogPanel`을 감싸던 `QVBoxLayout`(stretch 2/3 고정)을
    `QSplitter(Qt.Orientation.Vertical)`(`self._right_splitter`)로 교체. 동일하게
    `setMinimumHeight(80)`, `setSizes([200, 300])`(2:3 재현), hover 스타일 적용.
  - 바깥쪽 좌/우 메인 스플리터(`self._splitter`)와 전체화면 토글(`_on_toggle_fullscreen`)
    로직은 건드리지 않음 — 서브스플리터는 `_left_panel`/`_right_panel` *내부*에만 추가됐고,
    전체화면 토글은 그 바깥쪽 패널 자체를 `setVisible()`로 숨기고 메인 스플리터 크기만
    저장/복원하므로 구조적으로 서로 간섭하지 않음.
- `app/widgets/class_panel.py`: 내부 `QListWidget`의 `setMaximumHeight(200)` 상한 제거.
  design-log 주의사항대로 위 좌 패널 서브스플리터 전환과 **같은 커밋**에 포함.

### 검증 (직접 수행)
- 스크립트: `verify_labeling_tab.py`(스크래치 디렉토리) — `QT_QPA_PLATFORM=offscreen`,
  `PyQt6.QtWidgets`를 `app.core.project`보다 먼저 import(R4 검증 로그의 DLL 함정 회피 패턴
  준수). **주의**: Bash 툴 기본 `python`은 Windows Store 스텁이라 즉시 종료(exit 49,
  출력 "Python"만) — 반드시 `C:\Users\Feel\anaconda3\python.exe` 절대경로로 실행해야 함.
- `LabelingTab`을 오프스크린 `QApplication`에서 직접 생성해 확인:
  - `_left_splitter`/`_right_splitter` 모두 `QSplitter` 인스턴스, `orientation()`이
    `Qt.Orientation.Vertical` 확인.
  - `_left_splitter.sizes()` = `[532, 355]` → 비율 1.499 (목표 3:2=1.5, 오차 무시 가능).
  - `_right_splitter.sizes()` = `[355, 532]` → 비율 0.667 (목표 2:3=0.667, 정확히 일치).
  - `class_panel._list.maximumHeight()` = `16777215`(`QWIDGETSIZE_MAX`, 무제한) 확인 —
    상한 제거 성공.
  - **전체화면 토글 회귀 확인**: `_act_fullscreen.setChecked(True)` → `_left_panel`/
    `_right_panel` 모두 `isVisible()=False`. `setChecked(False)`로 복귀 → 둘 다
    `isVisible()=True`, 바깥쪽 메인 스플리터 `sizes()`가 토글 전후 `[230, 960, 200]`으로
    동일(정상 복원), **좌/우 서브스플리터의 `sizes()`도 토글 전후 완전히 동일**
    (`[532, 355]` / `[355, 532]`) — 서브스플리터가 전체화면 토글에 영향받지 않음을 확인.
- `python main.py` 방식 전체 기동 확인: `MainWindow()`를 오프스크린으로 직접 생성 →
  `MAIN_WINDOW_OK`(예외 없음, 라벨링 탭 포함 4개 탭 모두 로드 성공). 비대화형 셸에서
  `app.exec()` 이벤트 루프 없이 종료되며 발생하는 exit code 127은 R4/R5 검증 로그에서도
  동일하게 관찰된 노이즈로 판단, 실제 stdout 로그(`MAIN_WINDOW_OK`)로 성공 확인.
- 다른 라벨링 탭 기능(이미지 브라우저 검색/정렬, 클래스 추가/삭제, 캔버스 도구, 로그패널,
  단축키)은 코드 흐름상 이번 변경(레이아웃 컨테이너 교체)과 무관 — `_connect_signals()`,
  시그널 배선, `keyPressEvent` 등 로직 코드는 전혀 수정하지 않았으므로 회귀 없음 확인.

### 변경 파일
`app/tabs/labeling_tab.py`, `app/widgets/class_panel.py`만 변경. `git status`로 이 2개
파일 외 다른 변경 없음 확인(세션 시작 시점의 `dataset.py`/`trainer.py`/`config_form.py`/
`leader-log.md`는 이 세션 시작 전 이미 다른 경로로 커밋 완료된 상태였음 — 이번 작업과 무관).

### 커밋
`f086636` — `feat: UI 재편 라운드2 — 라벨링 탭 좌/우 서브스플리터 전환`
(`git push`는 수행하지 않음 — 사용자 명시적 확인 필요)

### 다음 단계
- **완료 보고 아님** — 검증(Verification) 에이전트가 실제 UI 조작(스플리터 핸들 드래그,
  8개 클래스 스크롤 없이 표시 등 목업 대비 육안 확인)까지 확인해야 한다.
- 학습 탭·추론 탭의 라운드 2 항목(큐 박스↔진행상태 서브스플리터, 상단↔메인뷰어 서브스플리터,
  추론 탭 이미지 목록 트리 교체)은 이번 범위 밖 — 별도 라운드로 남아있음.
