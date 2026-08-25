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

---

## 2026-08-20 — GitHub #2 라운드 A(프로젝트 전체 내보내기, export)

스펙: [docs/specs/voc-github-issues-2026-08-20.md](../specs/voc-github-issues-2026-08-20.md)
"요청 2 — 라운드 A" 절. 라운드 B(import)는 이번 범위 밖 — A 검증 통과 후 별도 위임.

### 변경
- **신규** `app/core/project_export.py` — Qt 비의존 순수 로직. `collect_export_entries()`가
  `images/`(`.thumbs/` 캐시 디렉토리 제외)·`annotations/`·`classes.json`·`project.json`은
  항상, `checkpoints/`·`user_models/`는 옵션에 따라 (절대경로, zip arcname) 목록을 계산.
  `default_export_filename()`이 `{project_name}_{yyyymmdd}.zip` 생성. zip 루트에 각 폴더가
  그대로 위치하도록 arcname을 구성(추후 라운드 B가 압축 해제 결과를 곧바로 프로젝트 폴더로
  쓸 수 있게).
- **신규** `app/widgets/project_export_dialog.py` — `ProjectExportDialog(QDialog)` +
  `_ProjectExportWorker(QThread)`. 워커는 `image_browser.py`의 `_FolderImportWorker`와
  동일한 패턴(파일 수 기준 `progress(done,total,name)` 시그널, 완료/에러를
  `finished(ok:bool, message:str)` 하나로 통합)을 따름. `zipfile`(표준 라이브러리)만 사용,
  외부 의존성 추가 없음. 체크박스 기본값: `checkpoints/` 미체크·`user_models/` 체크(확정된
  사용자 결정 반영), `user_models/` 옆에 "커스텀 모델 코드는 가져오기 후 모델 탭에서 다시
  로드해야 합니다" 안내 문구 배치. 취소 버튼(진행 중 워커에 cancel 플래그 전달, 부분 zip
  파일 삭제) 및 `closeEvent`에서 실행 중 워커 정리 처리 추가. 프로젝트를 열지 않고도 쓸 수
  있도록 `Project(path)`를 직접 구성(`open_existing()`/`set_current()` 미사용 — 부수효과
  없음).
- `app/widgets/project_start_dialog.py` — 최근 프로젝트 목록에 우클릭 컨텍스트 메뉴
  ("📦 내보내기…") 추가. 존재하지 않는 경로 선택 시 경고 후 목록 갱신.
- `app/core/i18n.py` — `project_export.*` 키 셋(ko/en) 추가.

### 검증(직접 수행, 스크래치 디렉토리 사용)
1. 합성 테스트 프로젝트(`testproj`: 이미지 3장 + `.thumbs` 캐시 1장, annotations 1개,
   classes.json, project.json, 가짜 checkpoint `.pt`, 가짜 `user_models/*.py`) 생성 후
   `collect_export_entries()` 단위 확인 — 기본 옵션(ckpt=False/models=True)에서
   `checkpoints/`는 제외, `user_models/`는 포함, `.thumbs`는 완전히 제외됨을 확인.
   반대 옵션(ckpt=True/models=False)도 확인.
2. `_ProjectExportWorker`를 실제 `QApplication`+이벤트루프로 구동해 zip 생성 →
   `zipfile.ZipFile`로 열어 내용물 검증 — `.thumbs` 미포함, `checkpoints/` 체크 해제 시
   미포함/체크 시 포함, `user_models/` 기본 포함 모두 실측 확인.
3. 대용량 시나리오(빈 파일 500장) — `progress` 시그널 503회 emit 확인, `QTimer`가 워커
   실행 중에도 계속 틱을 쌓아 이벤트 루프가 블로킹되지 않음을 확인, zip 파일 수(503개) 일치.
4. 에러 케이스 2건: (a) 프로젝트 폴더가 사라진 경우 — `finished(False, "프로젝트 폴더를
   찾을 수 없습니다.")`, zip 파일 미생성 확인. (b) 쓰기 권한 없는 경로(`C:\Windows\System32\
   config\`) 저장 시도 — `PermissionError`가 `finished(False, msg)`로 정상 전파, 부분 zip
   미생성 확인.
5. `ProjectExportDialog` 실제 생성 — 체크박스 기본값(`checkpoints`=False, `user_models`=True)
   실측 확인.
6. `python main.py`와 동등한 절차(PyQt6 → `app.core.project` → `app.main_window.MainWindow`
   → `app.widgets.project_start_dialog.ProjectStartDialog` 순 import, 오프스크린 플랫폼)로
   기동 확인 — 예외 없음, 컨텍스트 메뉴 슬롯 연결 확인.
- 검증 스크립트: 스크래치 디렉토리 `verify_export.py`/`verify_export_large.py`(프로젝트
  저장소 밖, 커밋 대상 아님).

### 변경 파일
`app/core/project_export.py`(신규), `app/widgets/project_export_dialog.py`(신규),
`app/widgets/project_start_dialog.py`, `app/core/i18n.py`. `git status`로 이 4개 파일
외 다른 변경 없음 확인.

### 커밋
`911f85a` — `feat: 프로젝트 전체 내보내기(export) 기능 추가 — GitHub #2 라운드A`
(`git push`는 수행하지 않음 — 사용자 명시적 확인 필요)

### 다음 단계
- **완료 보고 아님** — 검증(Verification) 에이전트의 실제 UI 조작(우클릭 메뉴 → 다이얼로그
  → 저장 경로 선택 → 실행 → 진행률/완료 메시지 육안 확인) 확인이 남아있음. "주요 기능 추가"
  라운드이므로 골든 패스 수준 검증 필요.
- 검증 통과 시 스펙에 명시된 대로 라운드 B(프로젝트 가져오기, import)로 곧바로 이어짐.

---

## 2026-08-20 — 프로젝트 가져오기(import) 추가 — GitHub #2 라운드B (요청2 마지막 라운드)

`docs/specs/voc-github-issues-2026-08-20.md` "요청 2 · 라운드 B" 구현. **이 라운드가
GitHub #2 요청2(프로젝트 export/import)의 마지막 라운드다** — 라운드 A(export, 커밋
`911f85a`, 검증 통과 `d42fe46`) 다음 순서로 이어서 진행.

### 변경
- `app/core/project_export.py` (기존 export 로직에 이어 확장, 같은 파일 — export/import가
  같은 zip 포맷을 알아야 하므로 자연스럽게 한 파일에 배치):
  - `ProjectZipError`, `ProjectImportCancelled` 예외, `ProjectImportResult` 데이터클래스 추가.
  - `validate_project_zip(zf)` — `images/`, `annotations/`, `classes.json` 존재 확인
    (`project.json`은 `open_existing()`이 없어도 자동 생성 가능해 필수에서 제외).
  - `resolve_import_dir_name(dest_root, base_name)` — 충돌 시 `_imported`, `_imported_2`…
    순 증가, 기존 폴더 절대 덮어쓰지 않음(사용자 확정 정책 그대로 구현).
  - `_resolve_member_target(dest_dir, arcname)` — zip slip 방지: 절대경로/드라이브 문자/`..`
    상위 이동을 포함한 arcname을 `None`으로 판정해 호출측이 해당 항목만 건너뛰게 함(전체
    거부가 아니라 항목 단위 스킵 — 스펙이 허용한 두 방식 중 항목 스킵을 선택, `skipped` 카운트로
    사용자에게 안내).
  - `collect_import_plan(zf, dest_dir)` — `(ZipInfo, 안전한 해제 대상 경로)` 목록 + skip 개수.
  - `import_project_zip(zip_path, dest_root, progress_cb=None, should_cancel=None) ->
    ProjectImportResult` — `collect_export_entries()`가 만든 zip 구조의 역연산. 손상된
    zip(`BadZipFile`, `testzip()` 실패)과 필수 항목 누락은 `ProjectZipError`로 방어적 처리.
    실패/취소 시 이미 만든 대상 폴더를 `shutil.rmtree`로 롤백.
- `app/core/project.py` — `add_recent(path)` 공개 함수 추가. 기존 `_touch_recent()`와 달리
  `last_project`(마지막 열린 프로젝트, 앱 재시작 시 자동 복원용)는 건드리지 않음 — 가져오기는
  프로젝트를 "연" 것이 아니라 최근 목록에만 반영해야 하므로 부수효과를 분리.
- `app/widgets/project_import_dialog.py` (신규) — `ProjectImportDialog` + `_ProjectImportWorker
  (QThread)`. 라운드 A의 `_ProjectExportWorker`와 동일 패턴(진행률 시그널 + 성공여부 포함
  finished 시그널 하나). export 다이얼로그와 달리 옵션 체크박스가 없어(가져오기는 zip 내용을
  그대로 복원) 구조를 단순화 — 통합하지 않고 별도 파일로 분리(export/import 성격이 다르고
  워커 로직도 다름, 라운드 A와 같은 판단 기준 적용).
- `app/widgets/project_start_dialog.py` — 새 프로젝트/프로젝트 열기 버튼 아래 별도 줄에
  "📥 가져오기…" 버튼 추가. `QFileDialog.getOpenFileName`으로 zip 선택 → `ProjectImportDialog`
  실행 → 성공 시 `proj.add_recent()`로 최근 목록 반영 후 목록 갱신(자동으로 열지는 않음 —
  과설계 방지, 사용자가 필요하면 최근 목록에서 직접 열도록).
- `app/core/i18n.py` — `project_import.*` 키 셋(ko/en) 추가. 버전 호환성 경고 문구
  (`project_import.invalid_zip`, `.skipped_warning`)에 스펙이 요구한 "가져온 프로젝트에
  문제가 있을 수 있습니다" 수준 안내를 그대로 포함.

### 검증(직접 수행, 스크래치 디렉토리 사용)
스크립트: `C:\Users\Feel\AppData\Local\Temp\claude\d--segmentation-model\
56a2e70d-4430-40c3-96ed-f10c2f90fcf9\scratchpad\test_import.py` (저장소 밖, 커밋 대상 아님).
1. **왕복(round-trip) 테스트** — 합성 프로젝트(이미지 2장 중 1개는 하위폴더, `.thumbs` 캐시,
   annotations JSON, classes.json, checkpoint, user_models) 생성 → `collect_export_entries()`로
   실제 zip 생성 → 이번에 만든 `import_project_zip()`으로 가져오기. 이미지 바이트(sha256 일치),
   annotations/classes.json 내용 일치, checkpoint/user_models 포함 확인, `.thumbs` 캐시는
   내용이 이관되지 않음(빈 표준 폴더만 `ensure_dirs()`가 새로 생성) 확인. **통과**.
2. **이름 충돌 재현** — 대상 위치에 `CollisionProj` 폴더가 이미 있는 상태에서 같은 zip을 2회
   연속 가져오기 → 1차 `CollisionProj_imported`, 2차 `CollisionProj_imported_2`로 정확히 증가.
   기존 폴더의 sentinel 파일 내용 무변경, `images/` 등 프로젝트 구조가 전혀 생기지 않음(전혀
   건드려지지 않음) 확인. **통과**.
3. **zip slip 공격 재현** — `../../evil_outside.txt`, `../evil2.txt`를 포함한 악의적 zip을
   직접 제작해 가져오기 시도 → 두 항목 모두 skip(2/2), 나머지 정상 3개 항목은 정상 추출,
   대상 디렉토리 밖 어디에도(`scratchpad/`, 그 상위) 파일이 생성되지 않음 확인. **통과**.
4. **손상된 zip 재현** — (a) `images/`·`classes.json` 등 필수 항목이 전혀 없는 zip(무관한
   파일 하나만 포함) → `ProjectZipError`로 명확히 거부. (b) zip 형식이 아닌 순수 바이트 더미
   파일 → `zipfile.BadZipFile` → `ProjectZipError`로 변환되어 크래시 없이 거부. **통과**.
5. `python main.py` 기동 확인 — PyQt6 → `app.core.project` 순서 유지, `ProjectStartDialog`
   생성 시 `_btn_import` 존재 확인, 실제 앱 기동 시 예외 없음(콘솔의 cp949 로깅 인코딩 경고는
   `PYTHONIOENCODING=utf-8`에서는 발생하지 않는 기존 환경 이슈로, 이번 변경과 무관 — 앱 기동
   자체는 두 경우 모두 정상).
6. 라운드 A(export) 재확인 — `ProjectExportDialog`/`_ProjectExportWorker` import 및
   `ProjectStartDialog` 구성 시 export 버튼·컨텍스트 메뉴 정상 연결, 코드 변경 없음(라운드 B는
   같은 파일에 함수만 추가) 확인.

### 변경 파일
`app/core/project_export.py`, `app/core/project.py`, `app/widgets/project_start_dialog.py`,
`app/core/i18n.py`, `app/widgets/project_import_dialog.py`(신규). `git status`로 이 5개 파일
외 다른 변경 없음 확인(세션 시작 시 이미 존재하던 `dataset.py`/`trainer.py`/`config_form.py`/
`leader-log.md` 변경은 이번 작업과 무관 — 커밋에 포함하지 않음).

### 커밋
`4129f10` — `feat: 프로젝트 가져오기(import) 기능 추가 — GitHub #2 라운드B`
(`git push`는 수행하지 않음 — 사용자 명시적 확인 필요)

### 다음 단계
- **완료 보고 아님** — 검증(Verification) 에이전트의 실제 UI 조작(가져오기 버튼 클릭 → zip
  선택 → 다이얼로그 → 진행률/완료 메시지, 라운드 A로 실제 만든 zip으로 골든 패스 확인) 확인이
  남아있음. "주요 기능 추가" 라운드이므로 골든 패스 수준 검증 필요.
- 검증 통과 시 **GitHub #2 요청2(export/import)가 전부 완료** — `docs/roadmap.md` 갱신 필요.

---

## 2026-08-20 — 기능 아이콘 SVG화 확장판 (Artifact `7876ed3e` 실행 순서 1단계)

`docs/agents/design-log.md` "4탭 디자인 톤 홀리스틱 재검토" 항목이 승인한 통합 목업(Artifact
`7876ed3e-e6ef-4d8b-92cb-cd2fecf2d98a`) 7단계 중 1단계 — 기능 아이콘 19종 SVG화. 리더가
지정한 대상(A~E) 전부 처리.

### 변경 내용
- **`app/resources/icons/` 신설** — SVG 22개(`tool_polygon`/`tool_brush`/`tool_bucket`/
  `tool_eraser`/`tool_eraser_flood`/`tool_select`/`tool_pan`/`undo`/`trash`/`eye`/`check`/
  `sparkle`/`fullscreen`/`refresh`/`folder`/`broom`/`clipboard`/`status_dot`/`status_ring`/
  `status_done`/`status_error`/`status_square`). 전부 24×24 뷰박스, 스트로크
  1.6px(체크마크류만 1.8px), `stroke="currentColor"`(또는 `fill="currentColor"`) — 새 색상
  팔레트 도입 없음, 로드 시 문자열 치환으로 앱 표준값을 입힘. 22개 파일이지만 여러 UI
  지점에서 재사용(예: `folder.svg`는 main_window 프로젝트폴더열기 + log_panel 로그폴더열기
  2곳, `check.svg`는 라벨링 OK 버튼 + image_browser "ok" 상태기호 2곳, `status_ring`은
  image_browser "미작업" + training_progress_dialog "waiting" 2곳)해 지시사항의 "19종"
  범위를 커버.
- **`app/widgets/icons.py` (신규)** — `icon(name, color, size)`/`pixmap(name, color, size)`.
  SVG 텍스트에서 `currentColor`를 지정 색으로 치환 후 `QSvgRenderer`로 `QPixmap` 렌더링,
  `functools.lru_cache`로 (이름,색상,크기) 단위 캐시. QIcon을 다루므로 CLAUDE.md 규칙대로
  `app/core/`가 아닌 `app/widgets/`에 배치(Qt 의존 유틸은 widgets 인접 배치가 관례에 부합).
- **A. `labeling_tab.py` 툴바 13개** — `tool_action()`의 이모지 인자를 아이콘 이름으로 변경,
  `QAction(svg_icon(name), "", self)`로 재구성. 나머지 6개(실행취소/전체지우기/
  어노테이션표시/OK/자동라벨링/전체화면)도 동일 패턴. 툴바 스타일시트의 `font-size:16px`
  제거하고 `tb.setIconSize(QSize(20,20))`으로 대체 — 체크 상태 시각 구분(배경 `#1e3a5f`)은
  `main.py`의 기존 `QToolButton:checked` 규칙이 그대로 적용되므로 아이콘 자체 색상 스왑
  로직은 추가하지 않음(불필요한 복잡도 회피).
- **B. 아이콘 전용 버튼 5개** — `main_window.py`(새로고침/폴더열기), `log_panel.py`(정리/
  폴더), `settings_dialog.py`(클립보드) — `QPushButton("이모지")` → `QPushButton()` +
  `setIcon()`/`setIconSize()`. 텍스트가 없어지므로 `font-size` 스타일 제거.
- **C. `image_browser.py` 상태기호 3종** — 기존엔 `f"{sym}  {text}"` 형태로 유니코드 기호를
  텍스트에 직접 붙이던 방식(폰트 렌더링이라 굵기 제어 불가)을 `item.setIcon(0, ...)` +
  `item.setText(0, 텍스트만)`으로 전환해 실제 벡터 스트로크로 "선굵기 확대" 요구를 충족.
  색상도 목표값대로 `#6ddf6d`→`#10b981`(라벨완료), `#5ba8ff`→`#60a5fa`(OK, `check.svg`
  재사용), `#999999`→`#4b5563`(미작업) 교체. 범례 행도 `QLabel` 텍스트 기호 → 아이콘
  픽스맵 + 텍스트 라벨 조합으로 변경. `_tree.setIconSize(QSize(14,14))` 추가.
- **D. `training_progress_dialog.py` STATUS_ICON 5종** — `STATUS_ICON`(이모지 dict) →
  `STATUS_ICON_NAME`(SVG 이름 dict)으로 개명, `update_queue()`가 `QListWidgetItem(icon, text)`
  생성자로 아이콘+텍스트를 함께 넣도록 변경. **사이드이펙트 발견**: `app/tabs/training_tab.py`
  가 같은 모듈에서 `STATUS_ICON`을 직접 import해 자체 학습 큐 리스트(`_refresh_queue_list`)에
  동일 이모지를 쓰고 있었음 — 개명만 하면 `ImportError`가 나므로, "공유 심볼의 모든 호출부를
  먼저 grep한다" 원칙에 따라 `training_tab.py`도 함께 `STATUS_ICON_NAME` + `svg_icon()`으로
  전환(같은 라운드·같은 커밋에서 처리, 절반만 마이그레이션된 상태로 남기지 않음).
- **E. `log_panel.py` CRITICAL** — `LEVEL_ICON["CRITICAL"]`을 `"🚨"` → `"■"`(U+25A0) 텍스트
  문자로 교체. DEBUG/INFO/WARNING/ERROR와 동일하게 이 값은 QListWidgetItem 텍스트 안에 직접
  섞여 들어가는 인라인 문자라서 SVG/QIcon화가 불필요 — 나머지 4개와 같은 "플레인 유니코드
  기호" 방식을 그대로 따르는 것이 더 단순하고 일관적이라 판단(SVG로 만드는 대신 문자 1개
  치환으로 근본 원인인 "컬러 이모지 폰트" 문제 해결).

### 범위 밖 확인 (건드리지 않음)
`i18n.py`의 툴팁 텍스트 안 이모지(예: "📐 폴리곤 [Q]\n...")는 텍스트 문자열이지 버튼 아이콘이
아니므로 유지 — 지시사항의 "텍스트 변경 없음, 아이콘만 교체" 원칙 그대로. `model_tab.py`/
`auto_label_dialog.py`/`export_dialog.py`/`settings_dialog.py`의 탭제목·그룹박스·텍스트있는
버튼 이모지, `image_browser.py`의 폴더 헤더 `📁` 등은 "장식 이모지 제거"(다음 라운드) 대상이라
이번 라운드에서 제외.

### 검증(직접 수행, 스크래치 디렉토리 사용)
스크립트: `C:\Users\Feel\AppData\Local\Temp\claude\d--segmentation-model\
40989d09-9093-4389-bdea-4fb6757d53b9\scratchpad\smoke*.py` (저장소 밖, 커밋 대상 아님).
1. `py_compile`로 변경 파일 8개 전부 구문 오류 없음 확인.
2. `QT_QPA_PLATFORM=offscreen` 헤드리스 환경에서 SVG 22개 전부 `icon()`/`pixmap()`으로 렌더링
   — `isNull()` False 확인(전부 정상 렌더링).
3. 임시 프로젝트 생성 후 `MainWindow`/`ImageBrowser`/`TrainingProgressDialog`/`LogPanel`/
   `SettingsDialog`/`TrainingTab`/`LabelingTab` 전부 생성 — 예외 없이 통과.
4. `TrainingProgressDialog.update_queue()`에 waiting/running/done/error/stopped 5개 상태의
   가짜 Job을 넣어 호출 — 5개 아이템 모두 아이콘 `isNull()` False 확인.
5. 실제 이미지 파일 1개로 `ImageBrowser` 트리 아이템 생성 + `refresh_item()` 재호출 — 아이콘·
   텍스트 정상 갱신 확인.
6. `python main.py`를 통한 실제 GUI 기동/조작(라벨링 탭 툴바 클릭 등)은 미수행 — 검증
   에이전트가 실제 창을 띄워 확인 필요.

### 변경 파일
`app/resources/icons/*.svg`(신규 22개), `app/widgets/icons.py`(신규), `app/main_window.py`,
`app/tabs/labeling_tab.py`, `app/tabs/training_tab.py`, `app/widgets/image_browser.py`,
`app/widgets/log_panel.py`, `app/widgets/settings_dialog.py`,
`app/widgets/training_progress_dialog.py`. `git status`로 이 파일들 외 다른 변경 없음 확인
(세션 시작 시 이미 존재하던 `docs/agents/design-log.md`/`docs/agents/leader-log.md`/
`docs/roadmap.md`의 미커밋 변경은 이번 작업과 무관 — 커밋에 포함하지 않음).

### 커밋
`2ad0165` — `feat: 기능 아이콘 19종 SVG화 — 이모지 대신 QIcon/QSvgRenderer 라인 아이콘`
(`git push`는 수행하지 않음 — 사용자 명시적 확인 필요)

### 다음 단계
- **완료 보고 아님** — 검증 에이전트가 `python main.py`로 실제 창을 띄워 라벨링 탭 툴바 13개
  아이콘의 시각적 형태·체크 상태 배경, `main_window`/`log_panel`/`settings_dialog` 아이콘 전용
  버튼 클릭 동작, `image_browser` 상태기호 색상, 학습 큐(진행 다이얼로그 + 학습 탭 본문 둘 다)
  상태 아이콘, 로그 패널 CRITICAL 로그 표시를 확인해야 함. 이번 라운드는 리더가 "주요 기능
  추가"로 분류하지는 않았으나(순수 시각 교체, 로직 변경 없음) 19개 지점 전부를 실제로 눈으로
  확인하는 것이 안전.
- 통과 시 `docs/roadmap.md`의 "아이콘/이모지 → 미니멀 디자인" 항목 중 1단계 체크 표시, Artifact
  `7876ed3e` 실행 순서 2단계(장식 이모지 제거, `model_tab.py` 포함)로 진행 가능.

---

## 2026-08-20 — 장식 이모지 제거 라운드 마무리 (i18n.py + 폴더 트리 아이콘)

### 배경
이전 구현 에이전트가 "장식 이모지 제거" 라운드(승인된 통합 디자인 목업 7단계 실행안의
2단계, Artifact `7876ed3e`) 작업 중 API 세션 한도로 중단됨. 작업트리에 19개 파일의
미커밋 변경이 남아있었고, 리더가 `py_compile` + diff 검토로 문법 오류 없음·일관된 처리를
이미 확인한 상태에서 이어받음. 해당 19개 파일은 재작업하지 않고 그대로 유지.

### 이어서 수행한 작업
1. **`app/core/i18n.py` 전체** — ko/en 두 언어 딕셔너리(총 487→484줄) 전수 조사(정규식
   유니코드 범위 스캔: `\U0001F300-\U0001FAFF`, `\U00002300-\U000023FF`,
   `\U00002600-\U000027BF`, `\U0001F1E6-\U0001F1FF`, `\uFE0F`)로 96곳의 선행 이모지를
   찾아 제거, 텍스트는 그대로 보존. `▶`/`■`/`↺`/`↶` 같은 도형·화살표 기호는 이미 완료된
   다른 19개 파일에서도 손대지 않은 것을 diff로 확인 후 동일하게 유지(이 프로젝트에서는
   "이모지"로 취급하지 않는 기존 관례).
   - `menu.settings`("⚙️" 단독값)와 `menu.export`("📤" 단독값)는 텍스트가 아니라 버튼의
     유일한 표시 수단이라 단순 삭제 시 빈 버튼이 되는 회귀가 발생 — 두 키를 아예 삭제하고
     `app/main_window.py`의 해당 버튼을 `svg_icon()` 기반 QIcon 버튼으로 전환(기존
     `_btn_switch`/`_btn_open_folder`와 동일 패턴 재사용).
   - 이를 위해 `app/resources/icons/gear.svg`(설정, sliders 스타일), `export.svg`(내보내기,
     upload 스타일) 2개 신규 SVG 추가 — 기존 `icons.py` 로더(`currentColor` stroke 치환)
     그대로 사용.
2. **`app/widgets/image_browser.py` 폴더 트리 헤더 아이콘** — `_make_folder_item()`의
   `📁  {folder_name}  ({count})` 텍스트에서 이모지만 제거하고, 이미 존재하던
   `app/resources/icons/folder.svg`를 `svg_icon("folder", "#60a5fa", _STATUS_ICON_SIZE)`로
   렌더링해 `item.setIcon(0, ...)`로 부착(파일 아이템의 상태 아이콘과 동일한 14px 크기로
   통일). 관련 docstring의 `📁` 언급도 이모지만 제거.
3. **전체 재스캔** — `app/` 전체를 동일 정규식으로 재스캔해 누락분 발견 후 수정:
   - `i18n.py`의 `train.empty_queue_msg`(ko/en) — 문장 중간에 박혀있던 `➕` 리터럴
     2곳(선행 위치가 아니라 자동 스트립 스크립트가 못 잡은 부분, 수작업으로 제거).
   - `training_tab.py`의 학습 중지 상태 라벨 `⏸️` 접두 3곳(505/662/668번 줄) — 같은 파일의
     다른 상태 라벨(🎯/✅ 등)은 이미 이전 에이전트가 제거했는데 이 3곳만 누락됐던 것으로 보임.
   - 재스캔 후 남은 13곳은 전부 라운드 1에서 확정된 예외(로그레벨 기호 `⚠`/`✖`,
     `model_tab.py`의 `✓`/`✗` 검증 결과, `settings_dialog.py`의 국기 이모지·복사 확인 `✓`,
     `config_form.py`의 `⚠` 경고 접두)와 정확히 일치 — 추가 조치 없음.

### 검증(직접 수행)
- `py_compile`로 `app/` 전체 재귀 컴파일 — 오류 0건.
- `QT_QPA_PLATFORM=offscreen` 헤드리스 환경에서 `MainWindow()` 실제 생성 —
  `app/core/i18n.py`, `app/main_window.py`(신규 아이콘 버튼 포함), 4개 탭 전부를
  임포트·구성하며 예외 없이 통과 확인.
- `python main.py`를 통한 실제 GUI 조작(라벨링/학습/추론 탭 골든 패스)은 미수행 —
  검증 에이전트 확인 필요.

### 변경 파일 (총 22개, 커밋 `b33491d`)
`app/core/i18n.py`, `app/main_window.py`, `app/core/inference_engine.py`,
`app/core/logger.py`, `app/model_presets/__init__.py`, `app/tabs/inference_tab.py`,
`app/tabs/model_tab.py`, `app/tabs/training_tab.py`, `app/widgets/auto_label_dialog.py`,
`app/widgets/auto_label_preview_dialog.py`, `app/widgets/config_form.py`,
`app/widgets/export_dialog.py`, `app/widgets/image_browser.py`, `app/widgets/log_panel.py`,
`app/widgets/model_preset_dialog.py`, `app/widgets/project_export_dialog.py`,
`app/widgets/project_import_dialog.py`, `app/widgets/project_start_dialog.py`,
`app/widgets/settings_dialog.py`, `app/widgets/training_progress_dialog.py`(이상 19개는
이전 에이전트가 이미 수정한 것을 그대로 커밋에 포함), `app/resources/icons/gear.svg`(신규),
`app/resources/icons/export.svg`(신규).

### 커밋
`b33491d` — `feat: 장식 이모지 제거 라운드 마무리 — i18n.py 전체 + 폴더 트리 아이콘 SVG화`
(`git push`는 수행하지 않음 — 사용자 명시적 확인 필요)

### 다음 단계
- **완료 보고 아님** — 검증 에이전트가 `python main.py`로 실제 창을 띄워 4개 탭
  (모델/라벨링/학습/추론) 이름, 설정 다이얼로그, 프로젝트 내보내기/가져오기 다이얼로그,
  학습 큐·진행 다이얼로그, 상단 코너의 새 설정/내보내기 아이콘 버튼 클릭 동작,
  이미지 브라우저 폴더 트리 아이콘 표시를 실제로 확인해야 함. 이번 라운드는 순수 텍스트/
  아이콘 교체이나 버튼 2개를 아이콘 전용으로 전환하는 구조 변경이 포함되어 있어 클릭 동작
  실제 확인이 특히 중요.
- 통과 시 Artifact `7876ed3e` 7단계 실행안의 2단계(장식 이모지 제거) 완료 처리,
  `docs/roadmap.md`의 관련 항목 갱신.

---

## 2026-08-20 — model_tab.py 에디터/로그 팔레트 앱 표준화 (Artifact `7876ed3e` 3단계)

`docs/agents/design-log.md` "4탭 디자인 톤 홀리스틱 재검토" 발견 1번(심각도 높음) 대상.
`app/tabs/model_tab.py`의 코드 에디터·로그 패널이 GitHub 다크 테마 계열 별도 팔레트를
쓰던 것을 `main.py` 앱 표준 팔레트로 교체.

### 구조 판단
이 파일은 Python 구문 강조(`_PythonHighlighter`)가 필요해 다른 탭과 구조가 다르다는
정당한 이유가 있음 — 완전히 갈아엎지 않고 "배경/테두리/성공/실패/정보" 구조색은 표준
토큰으로 전량 교체하되, 구문 강조 5종(키워드/문자열/주석/숫자/torch·nn)은 카테고리
구분 기능 자체는 유지한 채 색상 값만 표준 팔레트 계열의 명도 변형으로 재매핑했다
(절충— CLAUDE.md 지시사항의 "표에 없는 세분화된 강조색은 표준 accent/텍스트 톤 범위
안에서 유사값" 허용 범위 활용).

### 색상 매핑표
| 용도 | 기존(GitHub 테마) | 신규(앱 표준) | 근거 |
|---|---|---|---|
| 에디터 배경 | `#0D1117` | `#111418` | 표준 입력창/에디터 배경(가장 어두움) |
| 로그 패널 배경 | `#0A0E14` | `#111418` | 위와 동일 토큰으로 통일(표에 별도 로그 배경 없음) |
| 에디터/로그 기본 텍스트 | `#D4D4D4`/`#C9D1D9` | `#e5e7eb` | 표준 기본 텍스트 |
| 검증/로드 성공 상태·`[OK]` 로그 | `#3fb950` | `#10b981` | 표준 성공색 |
| 검증/로드 실패 상태·`[ERR]` 로그 | `#f85149` | `#f87171` | 표준 에러색 |
| `[WARN]` 로그 | `#d29922` | `#fbbf24` | 표준 경고색 |
| `[INFO]` 로그 | `#79c0ff` | `#60a5fa` | 표준 accent |
| 구문 강조 — 키워드 | `#569CD6` | `#60a5fa` | accent |
| 구문 강조 — 문자열 | `#CE9178` | `#fbbf24` | 경고 톤(표 밖 세분화 — 문자열/경고 모두 amber 계열이라 색맹 접근성 측면 재검토 여지 있음, 급하지 않으면 유지) |
| 구문 강조 — 주석 | `#6A9955` | `#9ca3af` | 보조 텍스트(주석은 원래 저대비가 관례) |
| 구문 강조 — 숫자 | `#B5CEA8` | `#10b981` | 성공 톤 |
| 구문 강조 — torch/nn/F | `#4EC9B0` | `#34d399` | 성공 톤(밝은 명도 변형, `design-log.md` 팔레트 참조표에 이미 등재된 기존 확장 토큰) |

`background:#1e3a5f`(프리셋 버튼)·`background:#065f46`(로드 버튼)는 GitHub 테마가 아니라
`design-log.md` "팔레트 참조표"에 이미 등재된 앱 확장 톤이라 그대로 유지, 손대지 않음.

### 검증
`py -c "import ast; ast.parse(...)"`로 문법 확인 통과. 실제 GUI 렌더링(에디터 신택스
하이라이팅 가독성, 로그 패널 색상 대비 등)은 미확인 — 검증 에이전트가 `python main.py`로
모델 탭을 열어 코드 입력→검증→로드 골든 패스를 실제로 확인해야 함.

### 변경 파일
`app/tabs/model_tab.py`

### 커밋
`a8ac52d` — `refactor: model_tab.py 에디터/로그 팔레트를 앱 표준으로 정규화`
(`git push`는 수행하지 않음 — 사용자 명시적 확인 필요)

### 다음 단계
- **완료 보고 아님** — 검증 에이전트 확인 필요. 통과 시 Artifact `7876ed3e` 7단계

---

## 2026-08-20 — loss_chart.py matplotlib 배색을 앱 표준으로 정규화 (Artifact 4단계)

### 배경
`design-log.md` "4탭 디자인 톤 홀리스틱 재검토" 발견 2번 — `loss_chart.py`가 독자 팔레트
(`#1e1e1e`/`#2d2d2d`/`#4fc3f7`/`#ef9a9a` 등)를 정의해 주변 Qt UI 톤과 이질적이었음.
matplotlib은 Qt 스타일시트를 상속받지 못하므로 색상은 Python 코드에서 직접 지정해야 하는
기술적 한계는 그대로 두고, 하드코딩 값만 앱 표준 팔레트로 교체.

### 색상 매핑표
| 용도 | 기존 | 신규(앱 표준) | 근거 |
|---|---|---|---|
| Figure facecolor | `#1e1e1e` | `#111418` | 표준 배경(가장 어두움) |
| Axes facecolor(패널) | `#2d2d2d` | `#1f2329` | 표준 패널 배경 |
| Train loss 선 | `#4fc3f7` | `#60a5fa` | 표준 accent |
| Val loss 선 | `#ef9a9a` | `#f87171` | 표준 에러 계열 |
| 그리드 | `#3a3a3a` | `#374151` | 표준 테두리 |
| epoch 경계 세로선 | `#555555` | `#374151` | 표준 테두리(그리드와 통일) |
| 스파인(축 테두리) | `#555555` | `#374151` | 표준 테두리 |
| 축 라벨/제목 텍스트 | `#cccccc`/`#eeeeee` | `#e5e7eb` | 표준 기본 텍스트 |
| 눈금(tick) 텍스트 | `#cccccc` | `#9ca3af` | 표준 보조 텍스트로 세분화 |
| 범례 배경/테두리 | `#3a3a3a`(배경만) | 배경 `#1f2329` + 테두리 `#374151` | 패널 배경과 통일, 테두리 명시 추가 |

시리즈가 2개(train/val)뿐이라 `#34d399`/`#fbbf24` 등 확장 참조는 사용하지 않음 — 새 색상
추가 없이 지시된 매핑 범위 안에서만 교체.

### 검증
`ast.parse()`로 문법 확인 통과. 실제 GUI 렌더링(학습 탭 손실 그래프 시각 대비)은 미확인 —
검증 에이전트가 `python main.py`로 학습 탭을 열어 그래프가 실제로 앱 톤과 어울리는지
확인해야 함.

### 변경 파일
`app/widgets/loss_chart.py`

### 커밋
`e76361a` — `refactor: loss_chart.py matplotlib 배색을 앱 표준 팔레트로 정규화`
(`git push`는 수행하지 않음 — 사용자 명시적 확인 필요)

### 다음 단계
- **완료 보고 아님** — 검증 에이전트 확인 필요. 통과 시 Artifact `7876ed3e` 7단계 실행안
  중 5단계 이후로 진행 가능.

---

## 2026-08-20 — 학습 탭 큐 영역 서브스플리터 전환 (Artifact `7876ed3e` 5단계, 학습 탭 부분)

### 배경
`docs/agents/design-log.md` "2026-08-19 — UI/UX 재편 라운드 2 목업"과 "2026-08-20 — 4탭
디자인 톤 홀리스틱 재검토"(실행 순서 5단계: 학습 탭 큐 서브스플리터)에 따라, 사용자가 짚은
"큐 리스트를 레이아웃별로 움직일 수 없고 정보가 부족하다"는 불편을 해소.

### 변경
`app/tabs/training_tab.py` `_build_ui()`:
- 기존: `right_layout`(QVBoxLayout)에 CUDA 배너 → `queue_box`(큐 관리 QGroupBox, 내부
  `_queue_list.setMaximumHeight(140)` 고정) → 진행바 → 상태 행 → `h_splitter`(그래프+사이드
  패널)를 순서대로 addWidget/addLayout — 큐 리스트는 140px로 고정, 사용자가 리사이즈 불가.
- 변경 후: `queue_box`(큐 관리)와 `monitor_panel`(진행바+상태 행+기존 `h_splitter`)을 새
  `self._queue_splitter`(`QSplitter(Qt.Orientation.Vertical)`)의 두 pane으로 분리.
  라벨링 탭 라운드 2 구현(`app/tabs/labeling_tab.py`, 커밋 `f086636`)의 서브스플리터 패턴을
  그대로 재사용 — handle width 5, hover 색상 `#374151`→`#60a5fa`.
- `_queue_list.setMaximumHeight(140)` 제거 (대신 `queue_layout.addWidget(self._queue_list,
  stretch=1)`) — 스플리터 전환과 **같은 커밋**에서 함께 처리해 레이아웃 붕괴 방지.
- 초기 비율: `self._queue_splitter.setSizes([260, 10000])` — 기존 큐 박스의 자연스러운
  높이(약 260px: 이름/모델 추가 행 + 큐 목록 140px + 제어 버튼 행 + ETA 라벨 + 그룹박스
  여백)와 동일한 픽셀 비율로 지정, 나머지는 h_splitter 패턴(`[10000, 180]`)과 동일하게 큰
  값으로 확장 pane 표시. `setStretchFactor(0, 0)` / `setStretchFactor(1, 1)`로 창 리사이즈
  시에도 모니터링 영역이 우선 확장되도록 함(기존 stretch=1 동작 재현).
- `queue_box.setMinimumHeight(120)`, `monitor_panel.setMinimumHeight(150)` 추가 — 완전
  붕괴(0px) 방지.
- CUDA 배너, ETA 라벨, 3열 메트릭 테이블 등은 건드리지 않음 — 진행바/상태 행/`h_splitter`는
  `monitor_panel`이라는 새 컨테이너 QWidget으로 옮겨졌을 뿐 내부 구조·시그널 연결은 그대로.
- **범위 확인**: `app/tabs/inference_tab.py`는 다른 구현 에이전트가 동시 작업 중이라
  건드리지 않음.

### 검증
- `ast.parse()` 문법 확인 통과.
- `QT_QPA_PLATFORM=offscreen`으로 `TrainingTab()` 헤드리스 인스턴스화 성공 — 예외 없음.
  `_queue_splitter.sizes()` → `[120, 355]`(오프스크린 소형 창 기준, `setMinimumHeight`
  제약으로 인한 값), `_queue_list.maximumHeight()` → `16777215`(Qt 기본값, 고정 상한
  제거 확인).
- 실제 GUI에서 사람이 드래그해보는 리사이즈 동작, 실행 시 초기 비율이 이전과 시각적으로
  동일한지는 **미확인** — 검증 에이전트가 `python main.py`로 학습 탭을 열어
  (1) 앱 시작 직후 큐 영역 높이가 이전과 체감상 동일한지, (2) 핸들을 드래그해 큐 리스트를
  더 크게/작게 조절할 수 있는지, (3) 여러 작업을 큐에 추가했을 때 리스트가 확장된 영역에서
  스크롤 없이 더 많이 보이는지 확인 필요.

### 변경 파일
`app/tabs/training_tab.py`

### 커밋
`a32a8b5` — `feat: 학습 탭 큐 영역을 세로 서브스플리터로 전환 — 자유 리사이즈 지원`
(`git push`는 수행하지 않음 — 사용자 명시적 확인 필요)

### 다음 단계
- **완료 보고 아님** — 검증 에이전트의 실제 UI 조작 확인 필요 (리사이즈 동작, 초기 비율).
  통과 시 Artifact `7876ed3e` 5단계의 나머지 부분(추론 탭 서브스플리터·이미지 트리, 별도
  구현 에이전트 작업)과 합쳐 5단계 전체 완료 여부 판단.

---

## 2026-08-20 — 추론 탭 상단↔뷰어 서브스플리터 + 이미지 목록 신규 컴포넌트

Artifact `7876ed3e`(4탭 디자인 톤 홀리스틱 재검토) 5단계 실행안 중 추론 탭 부분 담당.
학습 탭(다른 구현 에이전트, 커밋 `a32a8b5`)과 동시 작업이라 `training_tab.py`는 건드리지
않음.

### 변경
1. **`app/tabs/inference_tab.py`**
   - 상단 영역(파일 컨트롤+추론 방식+체크포인트 테이블)을 `top_widget`으로 묶고, 기존
     가로 스플리터(목록|뷰어|범례)와 함께 `outer_splitter`(세로 `QSplitter`)에 배치.
     hover 색상은 라벨링 탭 서브스플리터(커밋 `f086636`)와 동일한 `#374151`→`#60a5fa`
     패턴(`_SPLITTER_STYLE` 상수로 통일).
   - `self._ckpt_table.setMaximumHeight(120)` 제거 — 서브스플리터 전환과 같은 커밋에서
     함께 처리(분리 시 레이아웃 붕괴 위험, 디자인 로그 "구현 시 참고" 절 지시대로).
   - `outer_splitter.setSizes([300, 10000])` — 라벨링 탭의 "230, 10000, 200" stretch
     트릭과 동일한 방식으로 메인 뷰어 영역이 대부분의 공간을 차지하도록 초기 비율 지정.
   - 기존 `QListWidget` 기반 `_img_list`(검색/정렬/폴더 기능 전무, 64px 썸네일 그리드)를
     `InferenceImageList`로 교체. `_load_paths`/`_on_list_row_changed`/`_make_thumb_icon`
     등 관련 로직을 `_on_select_file`/`_on_select_folder`/`_after_load`/
     `_on_image_selected`/`_update_nav_label`로 재작성, `navigate()` API로 이전/다음
     버튼 위임.
2. **신규 `app/widgets/inference_image_list.py` (`InferenceImageList`)**
   - `image_browser.py`의 `_make_tree_item`/`_make_folder_item` 패턴을 참고(재사용
     아님) — 추론 탭엔 라벨 상태 개념이 없어 상태 아이콘(●/✓/○) 없이 `UserRole`엔
     `Path`만 저장, 텍스트는 파일명만 표시. 미니 썸네일 절충안은 스코프를 최소로 유지하기
     위해 이번 라운드에서 보류(디자인 로그가 "가능한 절충"으로만 언급, 필수 아님).
   - 검색(`QLineEdit` + 200ms 디바운스), 정렬 콤보(파일명↑/파일명↓/최근 수정순/오래된
     수정순/폴더 — image_browser 참고하되 상태 정렬 2종은 대상이 없어 제외, 대신 날짜
     정렬 2종 추가), 폴더 트리(`QTreeWidget`, 접기/펼치기, hover `#1f2937`/선택
     `#1e3a5f` — image_browser와 동일 스타일시트 `_TREE_STYLE`).
   - **`load_folder(root)`**: `root.rglob("*")`로 하위 폴더를 **재귀적으로** 스캔해
     `SUPPORTED_EXTS` 이미지를 모두 수집. 정렬 모드가 "폴더"일 때 `_build_nested_tree()`가
     `path.relative_to(root).parts`의 다단계 구조를 그대로 재현(2단계 이상 중첩 폴더도
     각 레벨이 폴더 헤더 아이템으로 중첩 표시됨) — `image_browser.py`의 기존 폴더
     그룹핑(`reload()`가 `images_dir().glob(pat)` 비재귀 스캔만 하고 폴더 추가 경로도
     평탄 복사라 실제로는 트리거되지 않는 죽은 코드, QA.md BUG-005)과 달리 **실제
     추론 탭이 스캔하는 이미지 디렉터리(사용자가 "폴더 선택…"으로 지정한 임의의 폴더 —
     `project.images_dir()`와 무관)의 진짜 하위 폴더 구조가 트리에 반영됨을 재귀 스캔
     테스트로 직접 검증**(아래 검증 절 참고).
   - `load_files(paths)`: 파일 대화상자로 개별 선택된, 공통 루트가 없는 파일들 — 폴더
     그룹핑은 직속 부모 폴더명 기준 1단계만 적용(`_build_flat_group_tree`).
   - `navigate(step)`/`current_display_index()`/`current_path()`/`count()` 공개 API로
     `image_browser.ImageBrowser`와 유사한 인터페이스 제공, `image_selected` 시그널로
     선택 변경 통지.

### 검증 (구현 에이전트 자체 확인 — 검증 에이전트의 실제 UI 조작 확인 별도 필요)
- `ast.parse()` 문법 확인 통과 (두 파일).
- `QApplication` 하에서 `InferenceTab()`, `MainWindow()` 헤드리스 인스턴스화 성공 —
  예외 없음.
- `tempfile`로 `a.jpg`(루트) / `sub1/b.jpg` / `sub1/sub2/c.jpg`(2단계 중첩) /
  `sub3/d.png`를 만들고 `InferenceImageList.load_folder()` 호출 → 폴더 정렬 모드에서
  트리를 재귀 순회한 결과 `sub1(2)` 아래 `b.jpg`와 `sub2(1)` 아래 `c.jpg`, `sub3(1)`
  아래 `d.png`가 모두 나타남을 확인. `_path_to_item` 키 집합이 `_all_paths` 전체와
  정확히 일치함을 assert로 확인 — **4개 이미지 전부가 실제로 트리에서 도달 가능**
  (BUG-005 재발 없음).
- 검색 필터("app" 입력 시 2개 중 1개만 표시)와 `load_files()`(공통 루트 없는 2개
  파일 → flat-group 모드)와 `navigate(1)`(인덱스 0→1 이동) 각각 별도 스크립트로 확인.

### 검증 에이전트가 추가로 확인해야 할 지점
1. `python main.py`로 추론 탭을 열어 서브스플리터 핸들 드래그(상단↔메인 영역 리사이즈)가
   실제로 동작하는지, 앱 시작 직후 비율이 기존과 체감상 동일한지.
2. "폴더 선택…"으로 하위 폴더가 있는 실제 폴더를 선택 → 정렬 콤보를 "폴더"로 바꿔 트리
   접기/펼치기·이미지 선택이 실제 GUI에서 동작하는지.
3. 검색창에 파일명 일부 입력 시 실시간 필터링, 정렬 콤보 5종 전환, 이전/다음 버튼과
   트리 클릭 선택이 뷰어에 정확히 반영되는지.
4. 이미지 목록 패널 리사이즈(140px 이하로 줄지 않는지, 상한 없이 넓힐 수 있는지).

### 변경 파일
`app/tabs/inference_tab.py`, `app/widgets/inference_image_list.py` (신규)

### 커밋
`b09fb83` — `feat: 추론 탭 상단↔뷰어 서브스플리터 + 이미지 목록 검색/정렬/트리형 폴더`
(`git push`는 수행하지 않음 — 사용자 명시적 확인 필요)

### 다음 단계
- **완료 보고 아님** — 검증 에이전트의 실제 UI 조작 확인 필요. 통과 시 학습 탭 작업
  (커밋 `a32a8b5`)과 합쳐 Artifact `7876ed3e` 5단계 전체 완료 여부 판단.
  실행안의 3단계 완료 처리, `docs/roadmap.md` 갱신.

---

## 2026-08-20 — GitHub #6-A 어노테이션 오버레이 깜빡임(flicker) 수정

참고 스펙: [docs/specs/voc-github-issues-round2-2026-08-20.md](../specs/voc-github-issues-round2-2026-08-20.md)
"#6-A" 절. `#6-B`(개수 비례 지연, `_rebuild_overlay()`/`_refresh_ann_list()`의 O(n)
전체 재구축 구조)는 이번 라운드 범위 밖 — 손대지 않음.

### 원인 (기획 에이전트가 국소화한 대로 확인됨)
`app/widgets/annotation_canvas.py`의 `_invalidate_overlay()`가 오버레이(어노테이션
시각화 `QPixmap`)를 `self._overlay = None`으로 **즉시 동기 비운 뒤**, 실제 재생성은
백그라운드 `QThread`(`_OverlayWorker`)로 **비동기** 처리한다. 워커가 끝나 `_on_overlay_done()`
이 `self._overlay`를 교체하기 전까지의 모든 `paintEvent`는 `self._overlay is not None`
게이트(508행 근방)에 걸려 오버레이를 아예 그리지 않는다 — 이 구간에 발생하는 화면 갱신마다
어노테이션이 순간 사라졌다 다시 나타나는 것이 flicker의 정확한 메커니즘.

### 수정 내용
`app/widgets/annotation_canvas.py` 2곳만 수정:

1. **`_invalidate_overlay()`** — `self._overlay = None` 줄을 제거. 새 오버레이가
   준비될 때까지(`_on_overlay_done()`이 교체할 때까지) **이전(stale) 오버레이를 그대로
   유지**한다. 브러시/폴리곤/지우개/선택/undo 등 같은 이미지 내 편집은 `img_w`/`img_h`/
   `overlay_scale`이 바뀌지 않으므로 이전 프레임의 오버레이를 잠깐 더 보여줘도 좌표계가
   일치해 안전하다.
2. **`load_image()`** — `self._invalidate_overlay()` 호출 직전에 `self._overlay = None`을
   명시적으로 추가. 이미지 전환 시에는 직전 이미지의 오버레이가 **다른 크기/스케일**을
   가지므로(다른 이미지의 `img_w`/`img_h`/`overlay_scale`), 이를 그대로 유지하면
   `paintEvent`의 `drawPixmap` 소스 사각형이 새 오버레이 픽스맵 크기와 어긋나 잘못된
   위치/스케일로 겹쳐 보일 위험이 있어(옛 이미지 어노테이션이 새 이미지 위에 어긋나게 표시)
   이미지 전환 시에는 예외적으로 즉시 비우는 것을 유지했다(대신 flicker가 아니라 "잠깐
   빈 채로 있다가 채워짐" — 원래도 이미지 전환 직후엔 자연스러운 로딩 지연으로 인지되는
   범위).

`_rebuild_overlay()`(1379행, 실제로는 어디서도 호출되지 않는 미사용 함수 — 별도 조사 불필요,
이번 수정과 무관)와 `_OverlayWorker`/`paintEvent`의 오버레이 재구축 로직 자체(#6-B 영역)는
건드리지 않았다.

### 검증 에이전트 재현 시나리오 (스펙이 명시한 3가지 모두 확인 필요)
1. **연속 브러시 스트로크**: 라벨링 탭에서 브러시로 여러 번 연속으로 칠하기(스트로크마다
   `_finish_brush()` → `_invalidate_overlay()` 호출). 수정 전에는 매 스트로크 완료 시
   기존 어노테이션들이 순간 사라졌다 나타났고, 수정 후에는 사라짐 없이 매끄럽게 이어져야 함.
2. **연속 이미지 전환**: 어노테이션이 있는 이미지 여러 장을 빠르게 다음/이전으로 넘기기.
   전환 직후 짧게 빈 상태(오버레이 없음)로 보이는 것은 의도된 동작(위 2번 이유)이지만,
   **이전 이미지의 어노테이션이 새 이미지 위에 어긋나게 겹쳐 보이는 증상이 없어야** 함.
3. **채널 전환 직후 즉시 라벨링**: R/G/B 채널 토글 직후 바로 브러시/폴리곤 등으로 편집 —
   채널 필터 동기 계산(별개 지연 요인, 이번 수정 범위 아님)과 오버레이 재생성이 겹쳐도
   어노테이션이 통째로 사라지는 flicker는 없어야 함.

폴리곤 완성, 지우개, 선택 변경(리스트 패널 클릭 포함), undo, 전체 삭제, 붙여넣기 등
`_invalidate_overlay()`를 호출하는 나머지 15곳 이상도 모두 같은 이미지 내 편집이라 위
1번 시나리오와 동일한 메커니즘으로 개선됨 — 별도 시나리오 불필요.

### 변경 파일
`app/widgets/annotation_canvas.py` (2개 함수: `_invalidate_overlay()`, `load_image()`)

### 커밋
`6a823a5` — `fix: 어노테이션 오버레이 깜빡임 수정 — 재생성 중 이전 오버레이 유지 (GitHub #6-A)`
(`git push`는 수행하지 않음)

### 다음 단계
- **완료 보고 아님** — 검증 에이전트가 위 3가지 재현 시나리오를 실제 `python main.py` 구동으로
  확인해야 함. 동시에 다른 구현 에이전트가 `app/tabs/labeling_tab.py`(OK 팝업, 클립보드 복사,
  브러시 스핀박스 폭 — #7/#4/#3(a))를 작업 중이므로, 그 파일은 이번 커밋에 포함하지 않았음
  (git status 확인 결과 `app/tabs/labeling_tab.py`는 unstaged 변경 상태로 남아있었고 손대지
  않음).

---

## 2026-08-20 — GitHub #7(OK 확인 팝업) + #4(이미지명 클립보드 복사) + #3(a)/(b)(브러시 크기)

라운드2 스펙(`docs/specs/voc-github-issues-round2-2026-08-20.md`) "#3", "#4", "#7" 절 기준
구현. 동시에 다른 구현 에이전트가 `app/widgets/annotation_canvas.py`의
`_invalidate_overlay()`(#6-A 깜빡임 수정)를 작업 중이라는 지시에 따라 그 함수는 건드리지
않았음. `_invalidate_overlay()` 외의 같은 파일 다른 위치(브러시 크기 관련)는 이번 작업
범위상 필요해 수정했음.

### #7 — OK 처리 시 라벨 존재하면 확인 팝업
- `app/tabs/labeling_tab.py` `_on_toggle_ok()`: OK를 **켜는** 순간(끄는 경우는 무확인)이면서
  `self._canvas._annotations`가 비어있지 않으면 `QMessageBox.question()`으로 확인 —
  `_on_clear_all()`이 쓰던 동일 패턴 재사용. Yes → `clear_all_annotations()` 호출 후
  삭제를 즉시 디스크에 flush(`_save_timer` 있으면 `stop()` + `_do_save()` 직접 호출 — 안 그러면
  500ms 디바운스 창 동안 `store.set_ok()`가 아직 라벨이 남아있는 stale JSON을 먼저 읽어
  일시적으로 라벨+OK가 공존하는 상태가 될 수 있어, `load_image()`가 이미 쓰던 "타이머 stop 후
  직접 `_do_save()` 호출" 패턴을 그대로 재사용) → `toggle_ok()`. No/취소 → `_act_ok.setChecked(False)`로
  되돌리고 아무 것도 하지 않음(기존 `_on_toggle_ok`이 "이미지 미선택 시 되돌리기"에 쓰던 패턴과
  동일).
- i18n 키 추가(`app/core/i18n.py`, ko/en): `labeling.ok_clear_title`, `labeling.ok_clear_msg`.

### #4 — 라벨링/추론 탭 이미지명 클립보드 복사
- `app/widgets/settings_dialog.py`의 `svg_icon("clipboard")` + `QApplication.clipboard().setText(...)`
  패턴을 그대로 재사용.
- **라벨링 탭**: 상시 파일명 표시 UI가 없었으므로 스펙 제안대로 채널 토글 스트립
  (`_build_channel_strip()`)의 `addStretch()` 뒤에 파일명 라벨(`_lbl_filename`) + 16×16 플랫
  아이콘 버튼(`_btn_copy_filename`) 신설. `_on_image_selected()`/`_on_image_deleted()`에서
  텍스트 갱신.
- **추론 탭**: 기존 `_lbl_filename` 옆에 같은 패턴의 복사 버튼을 `QHBoxLayout`으로 감싸 추가.
  `_on_image_selected()`가 이미 `path.name`으로 라벨을 갱신하던 구조라 텍스트 갱신 로직은
  변경 없음, 버튼과 슬롯(`_on_copy_filename`)만 추가.
- i18n 키 추가(라벨링 탭만 — 추론 탭은 파일 전체가 i18n 미사용이라 기존 관례대로 하드코딩 유지):
  `labeling.copy_filename`.
- 오토라벨링 patch training 확인 질문은 스펙 문서에 이미 사실관계로 기록 완료 — 구현 불필요.

### #3(a) — 브러시 크기 입력창 잘림
- `app/tabs/labeling_tab.py` `_spin_brush.setFixedWidth(60)` → `setMinimumWidth(76)`로 변경.

### #3(b) — 브러시 크기 더블클릭 조절 (사용자 결정: 더블클릭만)
- `app/widgets/annotation_canvas.py`: 브러시 계열 도구(`TOOL_BRUSH`/`TOOL_BRUSH_FILL`/
  `TOOL_ERASER`/`TOOL_ERASER_FLOOD`)에서 캔버스 더블클릭 시 `QInputDialog.getInt()`로 브러시
  크기(1~200)를 바로 입력받는 가장 단순한 방식 채택 — 팝업 슬라이더 등 커스텀 위젯 없이
  1함수 분기로 처리(과설계 회피). `mouseDoubleClickEvent()`에 `TOOL_POLYGON` 분기 다음
  `elif`로 추가, 폴리곤 닫기 동작과 충돌 없음.
- 새 시그널 `brush_size_changed = pyqtSignal(int)` 추가, `set_brush_size()` 끝에서 emit —
  더블클릭 다이얼로그로 바뀐 크기든 툴바 스핀박스로 바뀐 크기든 값이 실제로 바뀔 때 한 곳에서만
  emit되므로 툴바 스핀박스(`labeling_tab.py`에서 `brush_size_changed.connect(self._spin_brush.setValue)`)와
  캔버스가 항상 동기화됨. `QSpinBox.setValue()`는 값이 같으면 `valueChanged`를 재발생시키지
  않으므로 스핀박스↔캔버스 상호 연결에 의한 무한 루프 없음(수동 확인: 코드 검토로 확정, Qt
  표준 동작).
- **동시성 메모**: 위 `annotation_canvas.py` 변경분은 같은 작업 디렉터리를 공유하던 다른 구현
  에이전트의 #6-A 커밋(`6a823a5`)에 함께 포함되어 커밋됨 — 그 에이전트가 손댄
  `_invalidate_overlay()`/`load_image()`와는 다른 위치(생성자 시그널 선언, `set_brush_size()`,
  `mouseDoubleClickEvent()`)라 코드 충돌은 없고, git diff로 대조해 두 변경이 모두 온전히
  반영됐음을 확인함. 다만 커밋 메시지에는 이 변경이 언급되지 않아 기록 목적상 여기 남김.

### 변경 파일
- `app/tabs/labeling_tab.py`
- `app/tabs/inference_tab.py`
- `app/core/i18n.py`
- `app/widgets/annotation_canvas.py` (커밋은 `6a823a5`에 포함 — 위 동시성 메모 참고)

### 커밋
- `29248fa` — `feat: OK 확인 팝업 + 이미지명 클립보드 복사 + 브러시 스핀박스 잘림 수정 (#7, #4, #3a/b)`
  (`app/tabs/labeling_tab.py`, `app/tabs/inference_tab.py`, `app/core/i18n.py`)
- `6a823a5`(다른 에이전트 커밋에 편입됨) — `app/widgets/annotation_canvas.py`의
  `brush_size_changed` 시그널 + 더블클릭 다이얼로그 부분
- `git push`는 수행하지 않음

### 검증 확인 (구현 단계 자체 스모크 테스트)
- `ast.parse()`로 4개 변경 파일 구문 오류 없음 확인
- `QApplication` 생성 후 `LabelingTab()`/`InferenceTab()` 인스턴스화 성공 확인(임포트·생성자
  예외 없음)
- `icon("clipboard")` 반환 아이콘이 null이 아님 확인

### 다음 단계
- **완료 보고 아님** — 검증 에이전트가 실제 `python main.py` 구동으로 아래를 확인해야 함:
  1. 라벨이 있는 이미지에서 OK 토글 → 확인 팝업 → Yes/No 각각 정상 동작(Yes: 라벨 삭제 후 OK,
     No: 되돌림), 라벨 없는 이미지는 무확인 즉시 OK, 이미 OK인 이미지 재클릭(끄기)도 무확인.
  2. 라벨링 탭 채널 스트립의 파일명 옆 복사 버튼, 추론 탭 파일명 옆 복사 버튼 각각 클립보드에
     정확한 파일명이 복사되는지.
  3. 브러시 크기 스핀박스에 3자리 값(예: 150) 입력 시 잘리지 않고 다 보이는지, 브러시/지우개
     도구에서 캔버스 더블클릭 시 크기 입력 다이얼로그가 뜨고 값 변경이 스핀박스에도 반영되는지.
  4. 동시 작업된 #6-A(flicker) 수정과의 회귀 여부(같은 파일이므로 브러시 스트로크 연속 편집 시
     더블클릭 다이얼로그 도입이 flicker 수정에 영향 없는지 함께 확인 권장).

---

## 2026-08-20 — BUG-012(P2)/BUG-013(P3) 수정

BUG-011(P1, 더블클릭 stray 어노테이션, `mouseDoubleClickEvent()`의 `self.undo()`)은 리더가
이미 수정 완료한 상태였고 이번 작업에서는 건드리지 않음(코드 확인만: `annotation_canvas.py:665`
에 `self.undo()` 존재).

### BUG-013 — 브러시 크기 다이얼로그 i18n 누락
- 근본 원인: `annotation_canvas.py`의 `mouseDoubleClickEvent()`가 `QInputDialog.getInt()`
  제목/라벨을 `t()`를 거치지 않고 한국어로 하드코딩. 같은 파일이 `app.core.i18n`을 아예
  import하지 않고 있었음.
- 수정:
  - `app/core/i18n.py` — ko/en 양쪽에 `tool.brush_size_dialog.title`/
    `tool.brush_size_dialog.label` 키 추가(기존 `tool.brush_size` 네이밍 컨벤션에 맞춤).
  - `app/widgets/annotation_canvas.py` — `from app.core.i18n import t` 추가, 다이얼로그
    호출부를 `t("tool.brush_size_dialog.title")`/`t("tool.brush_size_dialog.label")`로 교체.

### BUG-012 — OK 처리 후 사이드바 아이콘 stale
- 정확한 근본 원인(코드 라인 레벨): `app/tabs/labeling_tab.py`의 `_on_toggle_ok()`가
  "라벨 삭제→즉시 flush→OK 처리" 경로에서 **같은 어노테이션 JSON 파일에 두 개의 독립적인
  동시 writer**를 만듦.
  1. `clear_all_annotations()` 이후 `self._canvas._do_save()`(수정 전, 인자 없음) 호출 —
     `annotation_canvas.py`의 구 `_do_save()`(옛 1324행)가 **매번 새 daemon 스레드**로
     `store.save(path, [], w, h)`를 비동기 실행하고, 스레드 시작 직후 곧바로(스레드 완료를
     기다리지 않고) `annotation_saved.emit()`을 동기 발행.
  2. 그 직후 같은 함수 안에서 `self._canvas.toggle_ok()` 호출 — 이건 메인 스레드에서
     동기적으로 `store.get_ok()` → `store.set_ok()`(같은 JSON 파일 read-modify-write)를
     실행하고 다시 `annotation_saved.emit()`.
  - 두 writer(1의 백그라운드 스레드 vs 2의 메인 스레드)가 같은 파일에 순서 보장 없이 경쟁:
    OS 스레드 스케줄링에 따라 1의 백그라운드 쓰기가 2의 `set_ok()` 쓰기보다 **나중에** 끝나면,
    1이 자신이 스레드 시작 시점에 캡처했던(2의 `ok=True` 쓰기 이전일 수 있는) 상태로 파일을
    덮어써 최종 디스크 상태가 뒤바뀔 수 있음. `image_browser.refresh_item()`은
    `annotation_saved` 시그널을 받을 때만 `get_label_status()`로 디스크를 재조회해
    `_status_cache`에 캐싱하는데(코드 자체는 정상 — 매번 fresh read), 1·2 두 번의 emit 중
    **어느 시점의 디스크 상태를 읽었는지가 스레드 타이밍에 좌우**되어 최종 캐시가 실제
    최종 디스크 상태와 다르게 고정될 수 있음. 이후 다른 이미지로 전환했다가 복귀해도
    `refresh_item()`이 재호출되지 않아(재조회 트리거가 `annotation_saved` 뿐) stale 캐시가
    그대로 남음 — 검증 에이전트가 관찰한 증상(사이드바만 stale, 디스크/툴바는 항상 정확)과
    일치.
  - `image_browser.py`의 `refresh_item()`/`_status_cache` 자체는 디스크를 재조회하므로
    범인이 아님(검증 에이전트의 두 번째 가설은 기각) — 진짜 원인은 `annotation_canvas.py`
    `_do_save()`의 백그라운드 스레드와 `toggle_ok()`의 동기 쓰기가 같은 파일에 대해
    **동기화 없이 경쟁**하는 구조.
- 수정(가장 단순한 방법 — 새 스레드/락 없이 순서만 보장):
  - `app/widgets/annotation_canvas.py`의 `_do_save()`에 `sync: bool = False` 파라미터 추가.
    `sync=True`면 `threading.Thread` 없이 `store.save()`를 직접 동기 호출 — 이 호출이
    끝난 뒤에야 함수가 반환되므로 이어지는 `toggle_ok()`의 파일 접근과 순서가 보장됨.
    `sync=False`(기존 디바운스 저장·`load_image()`의 flush 등 다른 모든 호출부)는 기존과
    동일하게 비동기 유지 — 그쪽은 같은 파일에 대한 즉각적인 2차 writer가 없어 경쟁이 없음.
  - `app/tabs/labeling_tab.py`의 `_on_toggle_ok()`에서 `self._canvas._do_save()` →
    `self._canvas._do_save(sync=True)`로 변경.
  - `load_image()`(`annotation_canvas.py:268`)의 flush 호출은 손대지 않음 — 다른 이미지로
    전환하기 직전 1회성 flush라 동시 2차 writer가 없어 이 버그와 무관.

### 검증
- `python -m py_compile app/widgets/annotation_canvas.py app/tabs/labeling_tab.py app/core/i18n.py`
  통과.
- 커밋: `fix: BUG-012 사이드바 아이콘 stale 경쟁조건 수정 + BUG-013 브러시 크기 다이얼로그 i18n`
  (해시는 커밋 후 리더 보고에 기재)
- `git push`는 수행하지 않음

### 다음 단계 — 완료 보고 아님, 검증 에이전트 확인 필요
1. **BUG-012 재현 시나리오**: `python main.py` → 라벨 있는 이미지에서 OK 토글 → "예" →
   사이드바 체크마크 확인 → 다른 이미지 클릭 → 원래 이미지로 복귀 → 사이드바가 여전히
   체크마크인지(회귀분 빈 원으로 안 바뀌는지) 확인. 이 경쟁 조건은 타이밍 의존적이라 기존
   버그도 100% 매번 재현되진 않았을 수 있음 — 여러 번(5회 이상) 반복 토글/전환해서 확인 권장.
   동시에 `projects/*/annotations/*.json`의 `ok`/`annotations` 필드가 항상 정확한지도 함께
   확인.
2. **BUG-013 재현 시나리오**: 설정에서 언어를 English로 변경 후 재시작 → 라벨링 탭에서
   브러시/지우개 도구로 캔버스 더블클릭 → 다이얼로그 제목이 "Brush Size", 라벨이
   "Brush size (1~200)"로 뜨는지 확인(한국어 잔존 없음). 한국어 설정에서는 기존과 동일한
   한국어 문구인지도 함께 확인.
3. 두 수정 모두 `annotation_canvas.py`를 공유하므로 기존 골든 패스(브러시 페인트, undo,
   OK 토글, 더블클릭 브러시 크기 변경)에 회귀가 없는지 가볍게 스모크 확인 권장.

---

## 2026-08-20 — GitHub #6-B: 어노테이션 개수 증가 시 로딩 지연 최적화 (최우선, 사용자 "반드시 필요")

`docs/specs/voc-github-issues-round2-2026-08-20.md` "#6-B" 절. 원인은 기획 단계에서 이미
코드 레벨로 확정돼 있었음 — `labeling_tab.py::_refresh_ann_list()`와
`annotation_canvas.py::_OverlayWorker.run()`(스펙 문서가 언급한 `_rebuild_overlay()`는
실제로는 **호출되지 않는 죽은 코드**임을 확인 — `_OverlayWorker`가 도입되며 대체된 것으로
보이나 정리되지 않고 남아있음. 이번 라운드에서는 건드리지 않음, 스코프 밖).

### 벤치마크 방법론 (R6 관례 그대로 재사용)
`C:\Users\Feel\anaconda3\python.exe`로 실행하는 스크래치 스크립트
(`bench_6b.py`, projects_root 하위 `bench_6b_tmp` 임시 프로젝트 생성 후 실측, 실제
프로젝트 데이터 무변경). 대형 이미지 5472×3648(nok급) 가정, 어노테이션 n=50/100/200/500개
(약 1/3 polygon, 2/3 brush_mask — brush_mask는 이미지 전체 크기의 (H,W) uint8 배열에 150×150
사각형 스탬프).

1. `_refresh_ann_list`: n_base개가 이미 있는 상태에서 1개씩 20회 연속 추가 시 누적 소요시간
   (구버전 clear+전체재생성 인라인 시뮬레이션 vs 실제 `LabelingTab._refresh_ann_list()` 호출).
2. `_OverlayWorker.run()`: 어노테이션 n개에 대해 `run()` 1회 호출 소요시간(수정 전/후 실제
   함수 직접 호출, QThread.start() 대신 동기 호출로 순수 연산시간만 측정).

### 원인 진단 — 실측으로 확정
- `_refresh_ann_list()`는 매 호출마다 `QListWidget.clear()` 후 n개 `QListWidgetItem`을
  전부 재생성 — 메인 스레드 동기 실행이라 어노테이션이 많을수록 그대로 UI 정지로 체감.
- `_OverlayWorker.run()`은 `_invalidate_overlay()`가 호출될 때마다(편집 1회당 1번, 이미지
  전환 시 1번) 백그라운드 스레드에서 실행되지만, **brush_mask 어노테이션마다 이미지 전체
  크기(20MP급) 배열을 `cv2.resize`+`_draw_mask_on_painter`(np.empty(H,W,4) 할당)로 처리** —
  n=500에서 **3396ms**(패치 전 실측)까지 치솟음. 백그라운드 스레드라 메인 UI를 멈추진
  않지만, 방금 그린 어노테이션이 화면에 반영되기까지 초 단위 지연이 생겨 "느려짐"으로
  체감. 두 지점 다 "1개만 바뀌어도 전체를 처음부터 다시 만든다"는 동일 패턴.

### 수정 1 — `app/tabs/labeling_tab.py::_refresh_ann_list()`
`clear()`+전체 재생성 대신 **위치 기반 diff**로 전환:
1. 매번 새 목표 리스트(`target: list[(ann_id, text, color)]`)를 계산(이 부분 자체는 여전히
   O(n) 순수 Python 연산이지만 Qt 위젯 churn이 없어 매우 저렴).
2. `min(n_old, n_new)`까지 위치별로 기존 `QListWidgetItem`과 비교 — `UserRole` 데이터와
   텍스트가 동일하면 **건드리지 않음**(선택 상태도 그대로 유지됨, 기존 코드는 매번
   `clear()`로 선택 상태를 잃었음 — 부수적 개선), 다르면 `setText`/`setData`/색상만 갱신
   (아이템 재생성 없음).
3. `n_new > n_old`면 초과분만 `addItem()`, `n_old > n_new`면 꼬리부터 `takeItem()`.
4. 어노테이션 삽입/삭제가 리스트 중간에서 일어나면 이후 항목들의 클래스별 순번(`#1`,`#2`…)이
   밀려 텍스트가 달라지므로 그 구간은 여전히 `setText()`로 갱신되지만(번호 매기기 방식 자체의
   근본 특성, 이번 스코프에서 변경하지 않음), **위젯 재생성보다 훨씬 저렴**.

### 수정 2 — `app/widgets/annotation_canvas.py::_OverlayWorker.run()`
brush_mask 렌더링을 **bbox-crop** 방식으로 전환 — 어노테이션이 실제로 차지하는 영역만
잘라 resize/dilate/합성:
- 신규 헬퍼 `_mask_bbox(mask, margin=1)` — `cv2.boundingRect(mask)`로 바운딩 박스 계산 후
  이미지 경계로 클리핑, margin=1은 3×3 dilate(선택 시 테두리)가 원본 프레임 전체에서
  dilate했을 때와 동일한 결과를 내도록 확보.
  - **`np.where(mask != 0)` 대신 `cv2.boundingRect` 채택** — 처음엔 `np.where`로 구현했으나
    벤치마크 결과 **역효과**(n=50 기준 298ms→974ms, 3배 느려짐)를 실측으로 발견.
    별도 마이크로벤치(5472×3648 배열 30회 평균): `np.where` 29.2ms/call vs
    `cv2.boundingRect` 2.1ms/call(약 14배) — OpenCV 구현이 numpy 풀스캔보다 훨씬 빠름을
    확인 후 교체. **"벤치마크 없이 직관대로 구현했으면 성능을 악화시켰을 사례"** — 이번
    라운드에서 실측 우선 원칙이 실제로 버그를 잡은 경우로 기록.
- `ann.mask[y0:y1, x0:x1]`로 자른 `sub` 배열에 대해서만 `cv2.resize`/`_draw_mask_on_painter`
  /`cv2.dilate` 수행, `_draw_mask_on_painter(..., ox=x0, oy=y0)`(기존에도 있던 파라미터,
  브러시 레이어 그리기에서 이미 쓰이던 패턴 재사용)로 올바른 위치에 합성.
- `sc < 0.99`(다운스케일) 분기: crop을 독립적으로 resize하면 전체 프레임을 한 번에 resize할
  때와 경계에서 최대 1px 반올림 차이가 날 수 있음(NEAREST 리샘플링 특성상 crop-local
  인덱스와 global 인덱스의 반올림 지점이 어긋날 수 있어 수학적으로 불가피 — 코드 주석에
  기록). 오버레이는 편집 중 미리보기일 뿐 저장되는 마스크 데이터(RLE, `annotation_store.py`)는
  전혀 건드리지 않으므로 감수하기로 결정.
- 남은 한계는 `_OverlayWorker` 클래스 docstring에 `# ponytail:` 주석으로 명시: bbox 계산
  자체도 배열 1회 스캔(O(전체 이미지 크기))이라 여전히 어노테이션 n개에 비례해 늘어나는
  구조는 남아있음 — 다음 단계는 어노테이션별 렌더링 결과(bbox+ARGB 타일)를 캐싱하고 바뀐
  것만 다시 그리는 방식이나, `annotation_canvas.py`에 mask를 in-place로 수정하는 지점이
  여러 곳(`951`, `1047`, `1290`행 등)이라 캐시 무효화를 하나라도 놓치면 오래된 렌더링이
  조용히 남는 정합성 버그가 될 위험이 있어 이번 라운드에서는 보류(스펙 문서도 이 방향을
  "더 큰 리팩터, 구현 단계에서 저울질" 로 명시).

### 정확성 검증 — 픽셀 비교 self-check
`scratchpad/check_overlay_correctness.py`(PyQt6 `QImage`를 numpy로 변환해 비교):
- 기존(전체 프레임 resize) 렌더링 vs bbox-crop 렌더링을 4가지 마스크 형태(중앙 소형/좌상단
  경계 접촉/우하단 경계 접촉/가늘고 긴 형태) × sc(1.0, 0.374) × selected(False/True) =
  16가지 조합으로 비교.
- **sc=1.0(원본 해상도) 분기: 전 조합 bit-exact 일치**(리샘플링이 없어 crop 후 그대로 옮겨
  그리는 것과 동일해야 함 — 실제로 그렇게 확인됨).
- **sc<0.99(다운스케일) 분기**: 12개 조합 중 8개는 bit-exact, 4개(작은/경계 접촉 도형의
  selected 케이스 위주)는 경계에서 30~117px 차이 — 전부 "1px 팽창해도 서로를 완전히
  포함하는" 경계 1px 이내 근사임을 형태학적 팽창(`cv2.dilate`) 비교로 검증(대형 왜곡/구멍
  없음 확인). 전체 16/16 통과.

### 벤치마크 결과 (전/후)
`_refresh_ann_list` — n_base개 존재 + 1개씩 20회 추가 시 누적 소요:
| n_base | 전(clear+rebuild ×20) | 후(diff ×20) | 배율 |
|---|---|---|---|
| 50  |    9.7ms |   5.2ms | 1.8x |
| 100 |   21.8ms |   7.4ms | 2.9x |
| 200 |   54.6ms |  11.0ms | 4.9x |
| 500 |  200.1ms |  22.8ms | 8.6x |

`_OverlayWorker.run()` — 어노테이션 n개, 이미지 5472×3648:
| n | 전(전체 프레임) | 후(bbox-crop+boundingRect) | 배율 |
|---|---|---|---|
| 50  |  298.5ms |  148.7~156.6ms | ~2.0x |
| 100 |  653.5ms |  279.6~284.9ms | ~2.3x |
| 200 | 1252.0ms |  555.8~572.7ms | ~2.2x |
| 500 | 3396.3ms | 1599.4~1630.1ms | ~2.1x |
(오버레이는 재측정 시 5~10ms 편차 있음 — cold memory access 영향으로 추정, 배율은 실행마다
2.0~2.3x 범위에서 일관됨.)

### 앱 기동 확인 — 부분적, 환경 이슈로 완전 확인은 못함
`C:\Users\Feel\anaconda3\python.exe`에서 `from app.main_window import MainWindow` 단독
스크립트 실행 시 `app/widgets/icons.py`의 `from PyQt6.QtSvg import QSvgRenderer`에서
`ImportError: DLL load failed`(QtSvg DLL 로딩 실패) 발생. **`git stash`로 이번 변경분을
모두 제거한 클린 HEAD에서도 동일하게 재현** — 이번 수정과 무관한 기존 환경 문제로 확인
(원인 미상, 이번 스코프 밖). 반면 `bench_6b.py`(project 모듈을 먼저 import하는 다른 실행
순서)에서는 동일 anaconda 인터프리터로 `LabelingTab()` 인스턴스를 여러 번 실제로 생성해
문제없이 동작함을 여러 차례 확인함 — 실제 수정된 함수(`_refresh_ann_list`,
`_OverlayWorker.run()`)는 실제 클래스 인스턴스를 통해 반복 실행·검증됨. **다음 검증
에이전트는 반드시 실제 `python main.py`(또는 정상 동작하는 인터프리터)로 앱을 띄워
라벨링 탭 골든패스(브러시/폴리곤/지우개 편집, 이미지 전환, undo)를 직접 확인할 것** — 이번
세션은 그 확인을 완료하지 못했음.

### 변경 파일
`app/tabs/labeling_tab.py`, `app/widgets/annotation_canvas.py`만 변경. 같은 파일의 기존
GitHub #6-A(`_invalidate_overlay()` stale-overlay 유지, 커밋 `6a823a5`) 및 BUG-011/012
(`_do_save`/`_on_toggle_ok`, 커밋 `24e93c9`/`5d551c3`) 로직은 그대로 유지 — diff 확인 결과
해당 함수들은 이번 커밋에서 건드리지 않음.

### 커밋
`574fb3390...`(로컬 HEAD) — `perf: 어노테이션 개수 증가 시 로딩 지연 최적화 (GitHub #6-B)`

### 다음 단계 — 완료 보고 아님
검증(Verification) 에이전트 확인 필요:
1. **정상 동작하는 인터프리터로 `python main.py` 실행** — 위 QtSvg DLL 이슈가 재현되는
   환경이면 다른 인터프리터/환경으로 재시도할 것(이번 세션에서 근본 원인 미해결).
2. 라벨링 탭 골든패스: 브러시/폴리곤/지우개/선택 편집 각각 정상 동작·저장 확인, 특히
   브러시로 작은 스트로크 여러 번 연속 추가 시 오버레이가 매번 정확한 위치에 표시되는지
   (bbox-crop 합성 위치 오프셋 버그 없는지) 육안 확인.
3. 이미지 전환 시 어노테이션 목록·오버레이가 올바르게 갱신되는지(diff 로직이 이미지 전환
   케이스에서도 정상 동작하는지 — `_on_image_selected()`가 `_refresh_ann_list()`를 호출하는
   경로는 로직상 동일하게 diff를 타므로 특별 케이스 아님, 그래도 실동작 확인 권장).
4. 대규모 합성 프로젝트(어노테이션 200개 이상)에서 실제 체감 개선 확인 — 이번 벤치마크는
   순수 함수 호출 시간만 측정했고 실제 UI 조작 체감(특히 오버레이 스레드 완료까지의
   지연)은 아직 육안 확인 안 됨.
5. GitHub #6-A(오버레이 flicker) 회귀 없는지 — 같은 `_OverlayWorker.run()` 함수를 수정했으므로
   #6-A 검증 시나리오(연속 브러시 스트로크, 연속 이미지 전환, 채널 전환 직후 즉시 라벨링)
   재확인 권장.

---

## 2026-08-20 — GitHub #6-B 대규모 재검증: 500+/10,000+ 규모 벤치마크 (사용자 요청, 코드 변경 없음)

사용자가 "500개 이상으로 늘려줘. 이미지 개수가 만개 이상 이미지당 50개이상으로 가정하고"로
직전 GitHub #6-B 성능개선(커밋 `574fb33`/`5f13df4`, 검증 통과 `41eaf13`)의 재검증 규모 확대를
요청. 두 축으로 벤치마크만 수행 — **이번 라운드는 코드 변경 없음**(perf 커밋 없음, QA.md
업데이트만 `docs:` 커밋). 스크립트는 전부 스크래치 디렉토리에만 작성(프로젝트 미포함),
실행 후 생성 데이터 전부 삭제, `projects/nok` 등 실제 데이터 무변경 확인
(`git status --porcelain -- projects/nok` 공백).

### 실행 환경
`C:\Users\Feel\anaconda3\python.exe`, `QT_QPA_PLATFORM=offscreen`. 벤치마크 시작 시점
`psutil.virtual_memory()` 기준 가용 RAM 17.65GB/전체 33.95GB. C: 드라이브 여유공간이
20MB로 사실상 바닥(스크립트만 C: scratchpad에 작성, 대용량 합성 데이터는 D:
`\_scratch_axis2`에 생성 후 종료 시 삭제 — D: 여유 0.98GB 확인 후 진행).

### 축1 — 단일 이미지당 어노테이션 개수 500 이상 확장

`bench_axis1.py`(스크래치 전용). `LabelingTab()`을 실제로 생성해 `_refresh_ann_list()`/
`_OverlayWorker.run()`을 직접 호출(#6-B 원 구현/검증 관례와 동일 방식 — 파일 저장 없이
`canvas._annotations`를 직접 조작). 이미지 해상도는 nok급 5472×3648로 고정(실 카메라
파일 없이 크기만 재현), overlay_scale=min(1.0, 2048/5472)≈0.374.

**1a) `_refresh_ann_list()` — polygon-only(마스크 메모리 영향 없어 n을 8000까지 확장 가능),
n_base개 존재 + 1개씩 20회 연속 append 누적 시간:**

| n_base | 20회 누적 | avg/call | n 대비 배율(참고) |
|---|---|---|---|
| 500  |   26.5ms | 1.33ms | 기준 |
| 1000 |   52.0ms | 2.60ms | n 2배 → 시간 1.96배 |
| 2000 |  121.2ms | 6.06ms | n 2배 → 시간 2.33배 |
| 4000 |  236.8ms | 11.84ms | n 2배 → 시간 1.95배 |
| 8000 |  505.9ms | 25.29ms | n 2배 → 시간 2.14배 |

n=8000(#6-B 원 벤치마크 최대치의 16배)까지도 **선형에 준하는 스케일 유지**(2배 n마다
대략 2배 시간, 비선형 급증 없음). 이는 diff 알고리즘 자체가 아니라 매 호출마다
`self._canvas._annotations` 전체를 순회해 `target` 리스트(클래스별 순번 텍스트)를
Python 레벨에서 재계산하는 부분이 원래도 O(n)이기 때문 — diff 최적화(#6-B)는 "Qt
위젯 재생성" 비용만 없앴을 뿐 이 O(n) 자체를 없애지는 않는다는 것을 실측으로 재확인.
n=8000에서도 25ms/call 수준으로 체감상 여전히 즉각적이라 이번 라운드에서 추가 조치는
불필요로 판단(과설계 금지 원칙).

**1b) `_OverlayWorker.run()` — brush 2/3 비중(#6-B 원 벤치마크와 동일 구성, 150×150
스탬프), n을 500 이상으로 확장 시도:**

| n | brush개수 | 결과 |
|---|---|---|
| 500  | 334 | times=[1528.7, 743.3, 731.8]ms, avg≈1001ms (2회차부터 콜드 메모리 영향 빠짐) |
| 750  | 500 | **SKIP** — 예상 메모리 9.8GB, 가용 10.2GB (안전마진 1.6배 미달로 자동 스킵) |
| 1000 | 667 | **SKIP** — 예상 메모리 13.0GB |
| 1250 | 834 | **SKIP** — 예상 메모리 16.3GB |

5472×3648 brush_mask는 개당 dense (H,W) uint8 배열 ≈19MB(RLE는 저장 시에만 씀, 메모리
상주 시엔 항상 dense) — n=750만 돼도 brush 500개 × 19MB ≈9.5GB가 어노테이션 리스트
하나에 필요해, 이 축의 실질 한계는 **함수의 계산 복잡도가 아니라 시스템 메모리**임을
사전 가드(안전마진 1.6배)로 확인. 즉 "20MP 이미지에 브러시 750개 이상"은 이 사양(가용
RAM ~17GB)의 실사용자에게도 애초에 비현실적인 시나리오(다른 프로그램 없이도 앱 혼자
10GB+ 필요) — #6-B가 고친 두 함수의 결함이 아니라 `AnnotationItem.mask`가 항상
전체 해상도 dense 배열이라는 기존 데이터 구조 자체의 한계(QA.md BUG-014와 동일 근본
원인). **이번 라운드 범위 밖으로 판단, 코드 수정 없음** — 아래 QA.md BUG-014에 추가
근거만 기록.

**1c) `_OverlayWorker.run()` — brush 저비중(10%, 80×80 스탬프)으로 메모리 여유를
확보해 순수 루프 오버헤드의 선형성만 별도 확인:**

| n | brush개수 | avg |
|---|---|---|
| 1000 | 100 | 338.8ms |
| 2000 | 200 | 668.7ms (n 2배 → 시간 1.97배, 선형 유지) |
| 4000 | 400 | **크래시** — `numpy._core._exceptions._ArrayMemoryError: Unable to allocate 19.0 MiB`(사전 가드는 통과했으나 실제 할당 중 실패) |

n=4000 크래시는 사전 가드(`psutil.virtual_memory().available >= 예상치×1.6`)가
"통과"라고 판단한 뒤에 발생 — Windows의 커밋/페이징 한도가 `available` 물리 메모리
지표와 별개의 제약으로 작용함을 실측으로 재확인(QA.md BUG-014에 이미 같은 원인이
기록돼 있었고, 이번에 독립적으로 재현). n=1000→2000 구간까지는 순수 루프 오버헤드가
선형임을 확인했으므로 **1b/1c 모두 "함수 자체는 선형, 실제 한계는 메모리"라는 동일
결론**. 크래시 후 시스템 메모리는 정상 회수됨(`psutil` 재확인, 가용 17.43GB로 원복 —
OS/프로세스 손상 없음).

### 축2 — 10,000장 프로젝트, 이미지당 평균 50개 어노테이션

`gen_axis2.py`로 D:`\_scratch_axis2\proj`에 합성 프로젝트 생성(실행 후 삭제): 이미지
10,000장(128×128, 20장만 실제 디코딩 가능한 PNG — 나머지는 0바이트 placeholder, `glob()`
스캔 대상 확인 목적. 이미지 내용 자체는 스케일 테스트에 불필요하다는 사용자 지시에 따름),
그중 8,000장에 어노테이션 JSON(이미지당 50개, polygon 60%/brush_mask 40% 혼합, 실제
`rle_encode()` 사용) — unlabeled 2,000 / labeled 6,000 / ok 2,000. 생성 총 9.8초,
프로젝트 크기 147.4MB(D: 여유 0.98GB 내 충분히 수용).

`bench_axis2.py`(스크래치 전용) 결과:

| 측정 항목 | 결과 |
|---|---|
| `ImageBrowser()` 최초 생성(콜드, 프로세스 최초 실행) | **41,674ms**(약 41.7초) |
| `ImageBrowser()` 최초 생성(재실행, OS 파일캐시 워밍 상태) | **1,891ms** |
| `reload()` 단독 재호출(warm) | 1,932ms |
| 정렬모드 4~5종 각 `_apply_display()` | 450~797ms (표시 10,000개, 트리 재구성이 지배적) |
| 검색 filter='5' 단일 `_apply_display()` | 321~338ms (매치 3,439개) |
| 디바운스(7글자, 30ms 간격 연속입력) | 실제 실행 **1회**(기대값과 일치), 총 경과 658~674ms |
| `_on_image_selected()`(실제 이미지 전환, 어노테이션 50개) | 2.7~9.2ms |
| overlay 완료까지 총 대기시간 | 15.7~22.6ms |
| `_push_undo()`(n=50, 128×128 소형 마스크) | 1.0ms |

**최초 콜드 스캔(41.7초) vs 재실행(1.9초) — 21배 차이 원인 분석**: 같은 데이터를 같은
방식으로 두 번째 프로세스에서 읽었을 뿐인데 21배 차이가 나는 것은 코드 로직이 아니라
**OS 수준 파일 캐시(및/또는 최초 생성 직후 파일에 대한 Windows Defender 온-액세스
검사)**로 설명됨 — 8,000개 JSON(각 ~17KB, 총 136MB)을 프로세스 최초로 열 때 디스크
I/O(및 백신 스캔 가능성)가 지배적이고, 두 번째 실행부터는 OS 페이지 캐시에 이미 있어
거의 순수 CPU 비용(json.loads + status 판정)만 남음. **실사용에서 사용자가 10,000장
프로젝트를 처음 여는 순간 최대 수십 초 대기가 있을 수 있다는 뜻**이지만, 이는 애플리케이션
코드 결함이 아니라 디스크/백신 환경 요인이라 이번 라운드에서 조치하지 않음(원인 규명
이상으로 파고드는 것은 과설계 판단, 확신 없는 부분은 보고만). 재방문(reload)은 1.9초
수준으로 이후 정렬/검색 조작(0.3~0.8초/회)과 비슷한 자릿수.

**정렬/검색 0.3~0.8초/회 — R6가 이미 문서화한 패턴의 스케일 확장 확인**: R6 검증 로그가
"1000개 QTreeWidgetItem 최초 생성이 지배적 비용"이라 기록했던 것과 동일한 병목이
10,000개 규모로 커진 것으로, 디바운스(#6 원래 목표)는 여전히 정상 동작(연속 keystroke →
실행 1회)하지만 그 1회 실행 자체의 절대 비용이 0.5~0.8초로 커져 있음 — "즉각적"이라고
하기엔 사용자가 체감 가능한 지연이다. 다만 이번 사용자 요청 범위는 "#6-B 재검증"이고
이 병목은 `_apply_display()`/`QTreeWidget` 트리 재구성 쪽(#6/R6가 손댄 영역과 인접하지만
다른 함수)이라 **이번 라운드에서 코드 수정하지 않음** — 10,000장급 프로젝트에서 정렬/검색
반응성이 사용자에게 문제로 느껴진다면 별도 라운드(가상화된 트리뷰 또는 지연 렌더링 등)로
논의 필요하다고 보고만 함.

**이미지 전환(2.7~22.6ms)/`_push_undo`(1.0ms)는 10,000장·이미지당 50개 규모에서 전혀
문제없음** — #6-B가 고친 두 함수는 프로젝트 전체 이미지 수(10,000)와 무관하게(현재 열린
이미지 1장의 어노테이션 개수에만 비례) 동작하므로 예상대로 빠름. `_push_undo()`도 이 축
(128×128 소형 이미지, 50개)에서는 BUG-014가 재현되지 않음 — BUG-014는 이미지 해상도×
brush 개수에 좌우되지 큰 이미지 개수와는 무관하다는 것을 재확인(축1에서 별도로 재확인).

### 메모리 — "LabelingTab이 10,000장 프로젝트에서 500MB 쓴다"는 최초 관측을 직접 반증

`bench_axis2.py`에서 `LabelingTab()` 생성 직후 RSS가 562.7MB(기준선 37.8MB 대비 +525MB)로
관측돼 처음엔 "10,000장 프로젝트 메모리 비용이 상당하다"로 오판할 뻔했다. **이 결론이
틀렸다는 것을 단계별 계측(`app/tabs/labeling_tab.py`에 임시 `psutil` RSS 프린트를
삽입해 실행 후 `git checkout`으로 즉시 원복 — 최종 커밋에는 포함 안 됨)으로 직접
반증**:

- `QApplication` 생성 직후: 37.8MB
- `from app.tabs.labeling_tab import LabelingTab` **모듈 import만** (widget 생성 전): **526.6MB**
- `LabelingTab()` 실제 생성(10,000장 스캔+8,000개 JSON 상태캐시 포함): 562.7MB (델타 **+36.1MB**)

즉 500MB 가까운 메모리는 `LabelingTab` 클래스가 `AutoLabelDialog`를 import하고,
`AutoLabelDialog`가 `trainer.py`/`model_loader.py`/`inference_engine.py`/`auto_labeler.py`를
import하면서 각 파일 top-level의 `import torch`(CUDA 런타임 라이브러리 포함)가 트리거되는
**일회성 PyTorch 임포트 비용**이며(직접 `import torch`만 단독 실행해도 33.8MB→517.2MB로
거의 동일한 크기 확인), **프로젝트 이미지 수(10,000장)와는 완전히 무관**하다. 실제
프로젝트 규모(10,000장, status_cache 8,000개)가 순수하게 기여하는 메모리는 **약
36MB**뿐 — `ImageBrowser()` 단독 생성 실측(37.6MB→80.4MB, 약 43MB)과도 자릿수가
일치해 앞뒤가 맞는다. **최종 결론: 10,000장/이미지당 50개 규모에서 메모리 사용량은
문제없음** — 초기 오판(500MB)은 온전히 torch import 타이밍의 착시였다는 것을 실측으로
정정해 기록한다.

부수 발견(조치 안 함, 참고만): `torch`를 PyQt6 `QtSvg` 관련 모듈보다 먼저 명시적으로
import하면 이 환경에서 `ImportError: DLL load failed while importing QtSvg`가 재현성
있게 발생함(반대 순서, 즉 `QtSvg`가 먼저 로드되는 실제 앱의 import 순서에서는 미재현).
R2 구현 로그가 확인한 "torch가 torchvision보다 먼저 로드되면 안전"과는 별개로 "torch가
QtSvg보다 먼저 로드되면 위험할 수 있다"는 새로운 DLL 순서 조합 — 실제 `main.py`/
`labeling_tab.py`의 import 순서(ImageBrowser의 QtSvg 관련 import가 AutoLabelDialog의
torch 관련 import보다 코드상 먼저 옴)에서는 우연히 안전한 순서라 실사용 경로에는
영향 없음. 기존에 이미 문서화된 환경 취약점(#6-B 구현 로그의 QtSvg DLL 이슈)과 같은
계열로 판단, 이번 라운드 범위 밖 — 조치하지 않음.

### QA.md 반영
BUG-014에 이번 라운드의 재확인 근거(deepcopy 없이도 대형 brush_mask를 여러 개 리스트에
쌓기만 해도 동일 크래시 재현, `psutil` 가용 메모리 지표만으로는 예측 불가)를 추가.
새 이슈 등록은 없음(신규 회귀·버그 없음).

### 코드 변경
**없음.** 임시 디버그 프린트(`app/tabs/labeling_tab.py`, 메모리 계측용)는 실행 확인 후
`git checkout`으로 즉시 원복, 최종 `git status --porcelain` 클린 확인. 이번 커밋은
`QA.md`(BUG-014 보강)와 이 로그 항목만 포함.

### 정리
`D:\_scratch_axis2`, 스크래치 내 `axis1_proj` 전부 `rm -rf`로 삭제 완료. `projects/nok`
등 실제 프로젝트 데이터는 이번 라운드에서 전혀 열람하지 않음(생성한 합성 프로젝트만
사용) — `git status --porcelain -- projects/nok` 공백 확인.

### 다음 단계 — 완료 보고 아님
검증(Verification) 에이전트 확인 필요. 이번 라운드는 코드 변경이 없어 "회귀 검증"
대상은 아니지만, 아래는 검증 에이전트가 교차 확인하면 좋을 항목:
1. 축1/축2 벤치마크 수치가 다른 환경에서도 같은 방향(선형 스케일, 메모리가 진짜 한계)으로
   재현되는지.
2. 10,000장 프로젝트 정렬/검색 0.3~0.8초/회가 실사용에서 실제로 거슬리는 수준인지 육안
   판단(별도 개선 라운드 착수 여부는 사용자/리더 판단 필요 — 이번 라운드는 보고만 함).
3. QA.md BUG-014 보강 내용이 기존 기록과 모순 없는지 확인.

---

## 2026-08-21 — 디자인 7단계 실행안 중 ⑥ i18n 밖 3파일 en 전환 + ⑦ 팔레트 토큰 정규화

`docs/agents/design-log.md` "2026-08-20 — 4탭 디자인 톤 홀리스틱 재검토 완료" 항목의
"실행 순서 제안 7단계" 중 마지막 두 단계(6·7) 구현. 라운드 1~5(아이콘 SVG화/장식 이모지
제거/model_tab 팔레트/loss_chart 배색/학습·추론 서브스플리터)는 이미 완료+검증 완료 상태라
재작업하지 않음.

### ⑥ i18n 밖 3파일 en 전환
`app/widgets/image_browser.py`, `app/widgets/training_progress_dialog.py`,
`app/main_window.py` 3개 파일이 `app/core/i18n.py`의 `t()` 체계를 거치지 않고 직접
하드코딩하던 한국어 UI 문자열(버튼/라벨/툴팁/다이얼로그 타이틀·메시지)을 전부 `t()` 호출로
교체. `app/core/i18n.py`에 신규 키 **27개**를 ko/en 양쪽에 추가:
- `project.status_bar` (1개) — 상태바 "프로젝트: {name} ({path})"
- `browser.*` (22개) — 검색창 placeholder, 정렬 라벨·5개 정렬모드 라벨, 범례 3종
  (라벨링됨/OK/미라벨), 파일·폴더 추가 다이얼로그 타이틀, "이미지 없음" 타이틀/메시지,
  복사 중 진행 템플릿, 삭제 확인 타이틀·단일/다중 메시지·"…외 N개" 접미사, 가져오기 완료
  타이틀·메시지·중복 건너뜀 접미사
- `train_progress.*` (10개) — 다이얼로그 타이틀, 현재작업/ETA/큐 그룹박스 타이틀,
  이 작업·전체 큐 ETA 템플릿, 중지(현재/전체)·닫기 버튼, "모든 학습 완료"

`image_browser.py`의 `_SORT_MODES` 리스트(하드코딩 라벨 튜플)는 `_SORT_MODE_KEYS`
문자열 리스트로 바꾸고 `t(f"browser.sort.{mode_key}")`로 런타임 조회하도록 변경 —
`_on_sort_changed`의 인덱스 매핑도 함께 수정.

로그 메시지·주석·docstring 내 한국어는 대상이 아니므로 그대로 둠(각 파일에 grep
`[가-힣]`로 재확인, 남은 매치는 전부 주석/docstring뿐).

### ⑦ 팔레트 토큰 정규화 (발견 7·8, 저우선)
발견 6(`image_browser.py` 상태기호 색상)은 라운드 1에서 이미 `#10b981`/`#60a5fa`/
`#4b5563`로 정규화 완료 확인 — 재작업 없음.
- **발견 7**: `#888` → `#9ca3af` 2곳(`image_browser.py`의 `_lbl_status`,
  `labeling_tab.py`의 `_lbl_sel_hint`), `#ccc` → `#e5e7eb` 1곳
  (`training_progress_dialog.py`의 `_lbl_epoch`). `inference_tab.py`는 grep 결과
  이미 `#9ca3af`만 사용 중이라 변경 없음(확인만). `STATUS_COLOR`/`STATUS_ICON_SIZE`류
  딕셔너리에 남아있는 `#888888`/`#cccccc`(`training_progress_dialog.py`,
  `training_tab.py`)는 라운드 1에서 확정된 상태-범례 색(waiting/fallback grey)이라
  "이미 확정된 다른 라운드의 의도적 값"으로 판단해 건드리지 않음.
- **발견 8**: `training_tab.py`의 CUDA 배너 성공/실패 배경 `#0d1f0d`/`#1f0d0d`(팔레트
  밖 신규값)을 표준 그룹박스 배경 `#1f2329` + 좌측 3px 색상 보더(성공 `#10b981`, 실패
  `#f87171`)로 교체 — 새 색상 도입 없이 최소 침습으로 동일 시각 효과 유지.
  `cuda_diag_dialog.py`의 동일 배경값은 이번 지시 범위(training_tab.py의 CUDA
  배너만) 밖이라 손대지 않음.

### 검증
- `ast.parse()`로 수정한 6개 파일 전부 구문 오류 없음 확인.
- `QT_QPA_PLATFORM=offscreen` 환경에서 `app.core.i18n.t()` 포맷팅 결과(ko/en 양쪽)
  수동 확인, `ImageBrowser`/`TrainingProgressDialog` 실제 인스턴스 생성 + 대표 메서드
  (`set_current_job`/`update_epoch`/`set_done`) 호출까지 예외 없이 통과.
- `MainWindow` 전체 골든 패스(en 설정 시 실제 탭 전환/각 위젯 렌더링)와 CUDA 배너
  성공/실패 두 상태의 실제 시각 확인은 하지 않음 — 검증 에이전트 확인 필요.

### 커밋
- `96b829c` — feat: i18n 밖 3파일 en 전환 (+ image_browser.py `#888` 정규화 포함)
- `8f78f8a` — refactor: 팔레트 토큰 정규화 - 보조텍스트 색상 + CUDA 배너 (발견 7·8)

### 다음 단계 — 완료 보고 아님
검증(Verification) 에이전트가 다음을 확인해야 함:
1. 설정에서 언어를 en으로 바꾼 뒤 앱 재시작 시 `image_browser.py`/
   `training_progress_dialog.py`/`main_window.py` UI 텍스트가 실제로 영문으로
   표시되는지 (플레이스홀더, 정렬 콤보, 범례, 삭제/가져오기 다이얼로그, 학습 진행
   팝업 전부 포함).
2. CUDA 사용 가능/불가 두 상태에서 배너가 좌측 색상 보더로 정상 표시되는지
   (CUDA 미탑재 환경이면 "불가" 상태만이라도 확인).
3. `#888`→`#9ca3af`, `#ccc`→`#e5e7eb` 교체 지점이 다른 라벨(로그 패널 등)과
   시각적으로 부드럽게 어울리는지 육안 확인.

---

## 2026-08-21 — BUG-006 수정: 허용목록 밖 import 검증 오탐(false pass)

### 문제
`model_validator.validate()`가 `ALLOWED_MODULES`에 없는 모듈 import를 `[WARN]`
+ `result.ok=True`로만 처리해 검증 통과(초록 상태) + 로드 버튼 활성화까지
가지만, `model_loader.load_from_code()`의 `exec()` 샌드박스(`_make_safe_import`,
`_ALLOWED_ROOTS`)는 허용목록 밖 모듈이면 무조건 `ImportError`를 던져 로드가
항상 실패. 검증 결과와 로더 실제 동작이 불일치.

### 수정
- `app/core/model_validator.py` `_check_imports()` — `ast.Import`/`ast.ImportFrom`
  두 분기에서 허용목록 밖 모듈에 대해 `result.warnings.append(...)` →
  `result.errors.append(...)`로 변경. 메시지 문구는 그대로 유지.
- 로더 쪽 샌드박스 제약(보안 경계)은 건드리지 않음 — 검증기만 로더 동작에
  맞춤.
- `app/tabs/model_tab.py`는 이미 `result.ok`로 `_btn_load.setEnabled(...)`를
  제어하고 있어 별도 수정 불필요 — `ok=False` 전환만으로 로드 버튼이
  자연히 비활성화됨. 확인만 하고 코드는 변경하지 않음.
- `model_loader.py`의 `_ALLOWED_ROOTS`는 이미 `ALLOWED_MODULES`에서
  파생(`{m.split(".")[0] for m in ALLOWED_MODULES}`)되므로 두 목록이 항상
  동기화됨을 확인.

### 검증 (직접 실행, python 3.14)
`import random` + 유효한 `nn.Module` 서브클래스 코드로 `validate()` 호출:
```
ok= False
errors= ["Line 2: 'random' — 허용 목록에 없는 모듈입니다."]
warnings= []
```
`ok=False`이므로 `model_tab.py`의 `_on_validate()` else 분기(`_btn_load.setEnabled(False)`)를
타는 것을 코드 확인함 — 실제 UI 조작(에디터에 `import random` 입력 → 검증
버튼 클릭 → 로드 버튼 비활성화 + 빨간 "✗ 검증 실패" 라벨 확인)은 하지
않았음.

### 커밋
- `7e95ee0` — fix: 허용목록 밖 import를 WARN이 아닌 ERROR로 처리 (BUG-006)

### 다음 단계 — 완료 보고 아님
검증(Verification) 에이전트가 다음을 확인해야 함:
1. `python main.py` 실행 후 모델 탭에서 `import random`을 포함한 코드를
   붙여넣고 검증 버튼 클릭 시 상태 라벨이 빨간 "✗ 검증 실패"로 뜨고
   로드 버튼이 비활성화 상태를 유지하는지.
2. `import numpy`, `import torch.nn as nn` 등 허용목록 안 모듈만 사용하는
   기존 정상 코드가 여전히 통과(초록 라벨, 로드 버튼 활성화)하는지 —
   회귀 확인.
3. 허용목록 밖 import를 가진 코드로 실제 로드 버튼을 눌러도 이전처럼
   `ImportError`로 실패하던 경로가, 이제는 애초에 로드 버튼이
   비활성화되어 눌리지 않는지 (또는 강제로 활성화 우회 시도 없이 정상
   플로우로 확인).

---

## 2026-08-21 — BUG-009 (추론 탭 검색 필터 해제 시 카운터 미갱신) / BUG-010 (트리 펼침 화살표 미표시) 수정

### 대상 파일
- `app/tabs/inference_tab.py`
- `app/widgets/inference_image_list.py`

병렬 작업 중인 다른 구현 에이전트들이 담당한 `annotation_canvas.py` /
`labeling_tab.py` / `image_browser.py` / `model_validator.py`는 건드리지
않았다.

### BUG-009 — 원인
`InferenceImageList._apply_display()`는 필터/정렬이 바뀌어도 선택된
경로(`new_path`)가 이전(`cur_path`)과 동일하면 `image_selected` 시그널을
재발행하지 않는다. `inference_tab.py`의 `_update_nav_label()` 호출은
`image_selected` 수신 슬롯(`_on_image_selected`)과 `_after_load()` /
`_on_prev()` / `_on_next()`에만 연결돼 있어, "선택 이미지는 그대로인데
전체 개수만 바뀌는" 케이스(검색어 입력 후 지우기 등)를 놓쳐 "N / M"
표시가 갱신되지 않았다.

### BUG-009 — 수정
과설계 방지를 위해 새 getter 대신 시그널 하나만 추가:
- `InferenceImageList`에 `display_changed = pyqtSignal()` 추가.
- `_apply_display()` 마지막(선택 복원 후)에 선택 경로 변경 여부와 무관하게
  항상 `display_changed.emit()` 호출 — 필터/정렬/`load_folder`/
  `load_files`/`clear()` 등 표시 목록이 재구성되는 모든 경로를 한 곳에서
  커버.
- `inference_tab.py`에서 `self._img_list.display_changed.connect(self._update_nav_label)`
  한 줄 연결.

### BUG-010 — 원인
`inference_image_list.py`의 `_TREE_STYLE`(`image_browser.py`의 기존
스타일을 참고해 만든 사본)에 `QTreeWidget::branch { background: #111418; }`
규칙이 있어 Qt의 OS 기본 펼침/접힘 화살표 렌더링을 억제했다. 커스텀
화살표 이미지를 지정하지 않았기 때문에 화살표 자체가 사라진 것.

### BUG-010 — 수정
배경 지정이 다른 시각 효과와 결합돼 있지 않음을 확인 — `QTreeWidget::branch`
규칙 자체를 삭제해 Qt 기본 화살표 렌더링이 복원되도록 함(커스텀 화살표
아이콘 신규 제작 없음, 과설계 회피).

### 검증
- `python -c "import ast; ast.parse(...)"` 로 두 파일 구문 확인 — OK.
- `QApplication` 컨텍스트에서 `InferenceImageList()` 인스턴스화 + `display_changed`
  시그널 존재 확인 — OK.
- 실제 UI 조작(검색어 입력→삭제 후 카운터 확인, 트리에서 화살표 렌더링
  육안 확인)은 하지 않았음 — 검증 에이전트가 `python main.py`로 추론 탭에서
  폴더 로드 → 검색창에 텍스트 입력 → 지우기 → "N / M" 라벨이 즉시
  정정되는지, 하위 폴더가 있는 트리 항목 옆에 펼침/접힘 화살표가 보이는지
  확인해야 함.

### 커밋 — 주의 (git race)
편집 완료 시점에 병렬로 작업 중이던 다른 구현 에이전트가 같은 작업
디렉터리에서 `git commit`(전체 스테이징 포함 방식으로 추정)을 실행하면서,
당시 아직 커밋하지 않고 워킹 트리에 남아 있던 이 작업의 변경분
(`app/tabs/inference_tab.py`, `app/widgets/inference_image_list.py`)이
그 에이전트의 커밋에 함께 쓸려 들어갔다:

- 커밋 `251608e` — "fix: BUG-003/BUG-014 캔버스 유령 어노테이션·undo OOM
  크래시 수정" (다른 에이전트 작업). `git show 251608e -- app/tabs/inference_tab.py
  app/widgets/inference_image_list.py`로 diff를 대조해 BUG-009/BUG-010에
  의도한 변경 내용과 정확히 일치함을 확인했다.

이미 커밋된 내용을 다시 커밋할 수 없고(diff 없음), 병렬로 다른 에이전트가
아직 작업 중인 공유 워킹 트리에서 이 커밋을 amend/rebase하는 것은 더 큰
충돌 위험이 있어 시도하지 않았다. 코드 변경 자체는 완료·반영되어 있으며,
커밋 메시지가 BUG-009/BUG-010을 언급하지 않는 점만 이 로그로 보완한다.
리더는 필요 시 이 사실을 인지하고 커밋 히스토리 정리(예: 이후 별도
`docs:` 커밋으로 참조 남기기) 여부를 판단하면 된다.

### 다음 단계 — 완료 보고 아님
검증 에이전트가 `python main.py`로 추론 탭을 열어:
1. 폴더 로드 → 검색창에 임의 텍스트 입력(필터링 확인) → 지우기 → 하단
   "N / M" 카운터가 "다음" 버튼을 누르지 않아도 즉시 전체 개수로
   정정되는지.
2. 정렬 모드를 "폴더"로 바꿔 하위 폴더가 있는 트리에서 폴더 항목 좌측에
   펼침/접힘 화살표 인디케이터가 보이는지, 클릭으로 펼침/접힘이 되는지
   (더블클릭 없이).
를 실제 UI 조작으로 확인해야 완료로 간주할 수 있다.

---

## 2026-08-21 — BUG-005(P2) 처리: `image_browser.py` 폴더 그룹핑 죽은 코드 제거 + 문서 정정

### 배경
`docs/decisions-needed.md`에 등록돼 있던 BUG-005 처리 방향 3선택지 중, 리더가 "재귀
폴더 스캔 기능을 실제로 만드는 대신, 도달 불가능한 죽은 코드를 제거하고 관련 문서
주장을 정정"하는 방향으로 결정했다는 지시를 받아 진행. 근거: 진짜로 지원하려면
`app/core/dataset.py`의 학습 스캔 로직까지 함께 바꿔야 하는데, 2026-05-27 커밋
`00fd6779`가 `image_browser.py`를 의도적으로 비재귀로 맞춘 이유가 정확히 "학습 시
제외되는 이미지가 브라우저엔 보이는 불일치 방지"였음 — 별도 기능 개발이라 "버그 수정"
범위를 벗어난다고 판단.

### 확인 절차
1. `app/widgets/image_browser.py` 전체를 읽고 `_build_folder_tree`/`_make_folder_item`
   과 정렬모드 "folder"가 정확히 어디까지 걸쳐 있는지 파악.
2. 도달 가능한 다른 경로가 이 함수들에 의존하는지 확인 — `_apply_display()`가
   `self._sort_mode == "folder"`일 때만 `_build_folder_tree()`를 호출하고, 이
   sort_mode는 `_SORT_MODE_KEYS` 콤보에서만 설정 가능함을 확인. `reload()`는
   `images_dir().glob(pat)` 비재귀 스캔만, `_on_add()`/`_on_add_folder()`도 전부
   `images_dir()` 바로 아래로 평탄 복사만 하므로 `images_dir()` 하위에 서브폴더가
   생성될 방법 자체가 없음(BUG-005 원 보고와 동일하게 재확인).
3. **중요 — 별개 구현과의 혼동 방지**: `grep`으로 `_build_folder_tree`/`_make_folder_item`/
   `_get_folder_font`를 전체 검색한 결과 `app/widgets/inference_image_list.py`에도
   동일한 이름의 함수/전역이 존재함을 발견. 이쪽은 **별도 파일의 별도 구현**이며
   `rglob("*")`로 실제 재귀 스캔을 수행해(로드맵 라운드2 step5 로그·BUG-010 기록 확인)
   추론 탭에서 실사용 가능한 살아있는 기능임을 확인 — **image_browser.py 쪽만 삭제,
   inference_image_list.py는 손대지 않음**.
4. `browser.sort.folder` i18n 키(`app/core/i18n.py`)가 `image_browser.py`에서만
   참조됨을 grep으로 확인 후 ko/en 양쪽 삭제.

### 삭제/수정한 범위 (`app/widgets/image_browser.py`)
- `_build_folder_tree()` 메서드 전체 삭제 — `_apply_display()`에서만 호출되던 죽은 코드
- `_make_folder_item()` 메서드 전체 삭제 — `_build_folder_tree()`에서만 호출되던 죽은 코드
- `_get_folder_font()` 함수 + 모듈 전역 `_folder_font` 삭제 — `_make_folder_item()`에서만 사용
- `from collections import defaultdict` import 삭제 — `_build_folder_tree()`에서만 사용
- `from PyQt6.QtGui import QFont` import 삭제 — `_get_folder_font()`에서만 사용
- `_SORT_MODE_KEYS`에서 `"folder"` 제거 (콤보박스 "폴더" 옵션 자동 소멸)
- `_apply_display()`: `elif self._sort_mode == "folder": filtered.sort(...)` 정렬 분기와
  `if self._sort_mode == "folder": self._build_folder_tree(filtered) else: ...` 트리
  분기 삭제, 항상 평탄 렌더링 루프만 실행하도록 단순화
- `_select_by_index()`: `item.parent()`가 접힌 폴더면 자동 펼치던 로직 삭제(폴더 헤더
  자식이 더 이상 생성되지 않으므로 `item.parent()`가 항상 `None`) — 도달 불가능해진
  분기라 함께 정리, docstring도 "접힌 폴더는 자동 펼침" 문구 제거
- `refresh_item()`: `display = path.name if item.parent() is not None else
  self._rel_name(path)` → 항상 `self._rel_name(path)`로 단순화(같은 이유)
- `current_path()`/`navigate()`/`_get_item_path()`/`_on_delete()` docstring·주석에서
  "폴더 헤더" 관련 언급 제거(코드 동작은 변경 없음, 문구만 정정)

### 안전성 판단
- `_get_item_path()` 자체(None 반환 가능성 체크)는 유지 — 이 함수는 `self._tree.currentItem()`
  이 `None`일 수 있는 일반적인 경우를 위한 방어 코드이기도 해서 폴더 헤더 전용 로직이
  아님. 삭제하지 않음.
- `QTreeWidget::branch { background: ... }` 스타일(`_TREE_STYLE`)은 그대로 유지 — 트리
  위젯 자체(평탄 목록 렌더링)는 계속 쓰이므로 살아있는 코드.
- `svg_icon("folder", ...)` 아이콘 리소스 자체(`app/resources/icons/`, `icons.py`)는
  다른 곳(`main_window.py`, `log_panel.py`, `inference_image_list.py`)에서도 쓰이므로
  건드리지 않음 — `image_browser.py`의 `_make_folder_item()`이 사용하던 호출부만 그
  메서드와 함께 사라짐.
- `python -m py_compile app/widgets/image_browser.py app/core/i18n.py` 통과 확인.

### 문서 정정
- `QA.md`: BUG-005를 Open Issues 표에서 삭제하고 Closed Issues 표로 이동(근본원인/
  해결방법 기록), GitHub #1 VOC 응답 행을 "라벨링 탭은 폴더 그룹핑 미지원(단일 평탄
  목록) — 필요 시 별도 기능 요청으로 재논의"로 정정
- `docs/roadmap.md`: 라벨링 탭 "폴더 접기/펼치기 그룹 헤더" `[x]` 완료 표시를 `[ ]`
  미지원으로 정정(오기였음을 명시), 라운드2 로그의 "라벨링 탭 기존부터 지원" 문구와
  "GitHub 이슈 VOC" 절의 동일 문구를 함께 정정
- `docs/decisions-needed.md`: BUG-005 처리 방향 결정 완료로 해당 항목 전체 삭제(선택지
  1/2/3 중 사실상 "지금 별도 라운드로 고친다"의 변형 — 재귀 스캔 구현이 아니라 죽은
  코드 제거로 리더가 판단·확정)

### 커밋
- `5af01ed` — `refactor: BUG-005 처리 — image_browser.py 폴더 그룹핑 죽은 코드 제거 + 문서 정정`
  (`QA.md`, `app/core/i18n.py`, `app/widgets/image_browser.py`, `docs/decisions-needed.md`,
  `docs/roadmap.md` 5개 파일). push는 하지 않음.
- 커밋 시점에 작업 트리에 `app/tabs/inference_tab.py`/`app/widgets/inference_image_list.py`의
  다른 에이전트발 변경사항이 unstaged로 섞여 있었음 — 내 작업과 무관한 파일이라 `git add`
  대상에서 명시적으로 제외하고 위 5개 파일만 스테이징해 커밋. 커밋 직후 확인한 결과
  해당 두 파일은 이미 다른 에이전트가 별도 커밋(`251608e`)으로 반영을 마친 상태였고
  현재 작업 트리는 clean함(`git status --short` 빈 출력) — 파일 유실이나 누락 없음.

### 다음 단계 — 완료 보고 아님
검증 에이전트가 다음을 확인해야 완료로 간주할 수 있다:
1. `python main.py` 실행 → 라벨링 탭 이미지 브라우저 정렬 콤보에 "폴더" 옵션이 더 이상
   없는지(4개 옵션만: 파일명↑/파일명↓/완료↑/미완료↑).
2. 기존 정상 기능(검색, 나머지 3개 정렬 모드, 이미지 추가/삭제, OK/라벨 상태 아이콘,
   키보드 네비게이션) 회귀 없는지.
3. 추론 탭의 폴더 트리(`InferenceImageList`, 정렬모드 "폴더")는 이번 변경과 무관하게
   그대로 정상 동작하는지(회귀 확인 차원).

---

## 2026-08-21 — BUG-003/BUG-014 수정 (annotation_canvas.py)

### 변경
- `app/widgets/annotation_canvas.py`

**BUG-003 — Select 도구 드래그 후 유령 어노테이션**
- `_translate_selected(dx, dy)`: `warpAffine`로 이동을 적용한 직후, `brush_mask`
  타입 어노테이션 중 마스크가 전량 0이 된 것들의 `annotation_id`를 모아
  `self._annotations`에서 제거하고 `self._selected_ids`에서도 함께 제거.
  폴리곤 타입은 마스크가 없어 대상에서 제외(요구사항대로 무관).

**BUG-014 — 브러시 undo 스택 deepcopy OOM 크래시**
- `_push_undo()`의 `copy.deepcopy(self._annotations)` 호출을
  `try/except MemoryError`로 감쌈. 실패 시 `app.core.logger.get_logger(__name__)`로
  경고 로그를 남기고 `return` — 해당 undo 스텝은 스택에 추가하지 않고 건너뛰되,
  호출부(브러시/지우개 페인트 시작 로직)는 그대로 진행되어 사용자의 편집 자체는
  손실 없이 계속됨.
- numpy `_ArrayMemoryError`는 `MemoryError`의 서브클래스임을 실제 설치된 numpy
  2.4.4로 확인(`numpy._core._exceptions._ArrayMemoryError.__mro__`에 `MemoryError`
  포함) — 버전마다 경로가 다른(`numpy.core` vs `numpy._core`) private 모듈을
  별도 import할 필요 없이 표준 `MemoryError` 하나로 두 버전 모두 커버.

### 검증 (스크립트, `python main.py` 미실행 — 순수 로직 단위 검증)
- `_push_undo` 로직을 동일하게 재현해 `copy.deepcopy`를 `MemoryError`로 mock →
  예외가 앱을 죽이지 않고 `return`으로 빠져나가며 undo 스택이 비어있는 그대로
  유지됨을 확인.
- `_translate_selected` 로직을 재현해 마스크가 전량 0이 되도록 큰 폭(-10,-10)
  으로 이동 → 빈 마스크 어노테이션이 리스트와 선택 집합에서 모두 제거됨을 확인.
- `python -m py_compile app/widgets/annotation_canvas.py` 통과.

### 커밋
- `251608e` — `fix: BUG-003/BUG-014 캔버스 유령 어노테이션·undo OOM 크래시 수정`
  (`app/widgets/annotation_canvas.py`)
- **git race 발생·해결 기록**: `git add app/widgets/annotation_canvas.py`로 내 파일만
  스테이징했음에도, `git commit` 실행 시점에 동시 작업 중이던 다른 에이전트가
  거의 같은 순간 `app/tabs/inference_tab.py`/`app/widgets/inference_image_list.py`를
  스테이징해 인덱스에 함께 들어가 있었고, 이 두 파일이 내 커밋(`251608e`)에 의도치
  않게 함께 반영됨. 이후 `git reset --soft`로 되돌리려다 그 사이 또 다른 에이전트가
  `251608e` 위에 쌓은 커밋(`66efeaf`)까지 같이 떨어져 나갈 뻔한 상황을 reflog로
  즉시 발견해 `git reset --soft 66efeaf`로 원상 복구. 이후 해당 두 파일은 git
  히스토리를 재작성(rebase 등)하는 대신 — 지시받은 대로 그 파일들을 직접 건드리지
  않는 범위 내에서 — Edit 도구로 스크래치패드에 백업해둔 원래 WIP 내용과 diff가
  0임을 확인해 아무 손실 없이 원상태로 남겼음을 검증. 그 사이 BUG-009/BUG-010
  구현 에이전트도 같은 race를 독립적으로 발견해 `ba0d487` 커밋으로 "코드는 251608e에
  병합됨"을 기록함 — 두 기록이 서로 일치. 최종적으로 `git status`는 clean이며
  파일 유실 없음.

### 다음 단계 — 완료 보고 아님
검증 에이전트가 다음을 확인해야 완료로 간주할 수 있다:
1. `python main.py` 실행 → 라벨링 탭에서 Select 도구로 brush_mask 어노테이션을
   캔버스 밖까지 완전히 드래그한 뒤, 어노테이션 목록에 렌더링되지 않는 항목이
   남지 않는지(BUG-003 재현 시나리오).
2. (재현이 번거로우면 스킵 가능) 대형 이미지에 brush_mask 어노테이션을 대량으로
   쌓은 뒤 새 브러시 스트로크 시작 시 `MemoryError`가 실제로 발생하는 극단 상황을
   인위적으로 만들기 어려우므로, 코드 리뷰로 `try/except` 범위와 로그 메시지가
   요구사항과 일치하는지 확인.

---

## 2026-08-24 — Windows exe + Inno Setup 인스톨러 빌드 도구 (build.spec / setup.iss / build.bat)

### 배경
앱 기능이 아닌 빌드/배포 툴링 작업. 로컬에 이미 설치된 PyInstaller 6.20(`py -3`),
torch 2.11.0+cu128(CUDA 빌드), Inno Setup 6.7.3(ISCC.exe)을 그대로 사용해
onedir 패키징 + 설치 마법사를 만드는 것이 목표. 실제 빌드 실행/검증은 범위 밖 —
검증 서브에이전트가 별도로 수행.

### 조사 (구현 전 코드 리딩)
- `main.py`의 `_preload_libs()`가 `importlib.import_module()`로 numpy/cv2/PIL.Image/
  torch/matplotlib를 동적 로드 — PyInstaller 정적 분석이 못 잡는 유일한 지점.
- `app/core/dataset.py`, `inference_engine.py`, `auto_labeler.py`의 `torchvision...` 지연
  import와 `app/core/augmentations.py`의 `albumentations` 지연 import는 함수 내부에
  있어도 여전히 정적 `import` 문이라 PyInstaller가 자동 추적함 (importlib 동적 로드와
  달리 안전) — 확인 후 hiddenimports에 안전망으로만 추가, 필수는 아님.
- `pyinstaller-hooks-contrib`(로컬 설치됨, 2026.5)에 torch/torchvision/cv2 전용 hook이
  이미 있음을 확인 — 수동 `collect_dynamic_libs` 등 불필요.
- **`app/model_presets/__init__.py`의 `load_preset_code()`가 프리셋 `.py` 파일을
  `read_text()`로 텍스트로 읽음** — import가 아니라서 PyInstaller가 코드로 인식하지
  못하고, 데이터로도 안 넣으면 frozen 빌드에서 프리셋 드롭다운이 전부 빈 코드로
  나오는 실제 버그가 될 뻔함 → `datas`에 `app/model_presets` 명시적 포함.
- `app/widgets/icons.py`의 `_ICON_DIR`(`app/resources/icons/*.svg`)도 동일한 이유로
  `datas`에 포함.
- **PyInstaller onedir에서 `__file__`이 실제 파일이 없는 합성 경로를 가리키는지
  직접 실험으로 검증**: 스크래치패드에 미니 패키지를 만들어 `py -3 -m PyInstaller
  --onedir`로 빌드해 실행한 결과, frozen 상태에서 서브모듈의 `__file__`은
  `dist/<name>/_internal/pkg/sub.py`처럼 실제 존재하지 않는 경로를 가리키고,
  `Path(__file__).parent.parent...` 체이닝은 결국 실존하는 `_internal` 폴더로
  귀결됨을 확인. `main.py: ensure_data_dirs()`와 `app/core/project.py:
  get_projects_root()`가 이 패턴으로 데이터/프로젝트 루트를 계산하고 있어, 고치지
  않으면 사용자 데이터가 `_internal`(PyInstaller 내부 라이브러리 폴더) 안에
  생성되는 것 자체는 크래시는 아니지만 의미론적으로 잘못됨 — 지시받은 대로
  `getattr(sys, 'frozen', False)` 분기로 `sys.executable` 기준 경로를 쓰도록 최소
  수정. `icons.py`/`model_presets/__init__.py`는 같은 `__file__` 체이닝이지만
  datas 배치 위치와 자연스럽게 일치해 문제 없음을 확인하고 그대로 둠(ponytail).
- `app/core/logger.py`의 `LOG_DIR = Path("data/logs")`, `app/core/i18n.py`의
  `SETTINGS_FILE = Path("data/settings.json")`은 `__file__`이 아니라 CWD 기준이라
  코드 수정 대상은 아니지만, Inno Setup 바로가기에 `WorkingDir: {app}`을 명시해
  CWD가 항상 설치 폴더가 되도록 함으로써 실행 방식(더블클릭/시작 메뉴)에 관계없이
  일관되게 만듦.

### 변경 (코드)
- `main.py`: `ensure_data_dirs()` — frozen 시 `sys.executable` 기준으로 base 계산.
- `app/core/project.py`: `_app_root()` 헬퍼 추가(frozen 분기), `default_projects_root()`
  공개 함수로 분리, `get_projects_root()`가 이를 사용하도록 변경.
- `app/widgets/settings_dialog.py`: `_on_reset_projects_root()`가 `Path(__file__)`
  중복 계산 대신 `project.default_projects_root()`를 호출하도록 교체 (중복 로직
  제거 — 같은 버그를 두 곳에서 고칠 필요 없게 함).

### 신규 파일
- `build.spec` — PyInstaller onedir spec. `name="SegmentationModelUI"`,
  `console=False`(오류는 `data/logs/*.log` 파일 + `logger.py`의 GUI 예외 팝업으로
  추적 가능하므로 콘솔 불필요 확인됨), hiddenimports(위 조사 내용 반영),
  datas(`app/resources/icons`, `app/model_presets`).
- `installer/setup.iss` — Inno Setup 스크립트. `PrivilegesRequired=lowest` 채택
  (이유를 스크립트 내 주석으로 명시: `{autopf}`가 admin 권한 없이 쓰기 가능한
  `{localappdata}\Programs`로 자동 해석되는 Inno 6 "Auto" 상수 동작을 이용 — 앱이
  설치 폴더 밑에 `data/`·`projects/`를 직접 쓰기 때문에 Program Files에 admin
  설치하면 표준 사용자 실행 시 쓰기 권한 문제가 생길 수 있음). 시작 메뉴 바로가기
  기본 + 바탕화면 바로가기 선택적 체크박스, 설치 후 실행 옵션, 언인스톨러는 Inno
  Setup 기본 기능 그대로 사용(추가 코드 없음).
- `build.bat` — `build/`,`dist/` 정리 → `py -3 -m PyInstaller build.spec` →
  `ISCC.exe installer\setup.iss` 순차 실행, 각 단계 `if errorlevel 1 goto :error`로
  즉시 중단. 마지막에 `installer\output\*.exe`를 나열해 버전 번호를 하드코딩하지
  않고도 정확한 산출물 경로를 출력.

### 발견한 환경 이슈 (구현 범위 밖, 검증/사용자 확인 필요)
- **`albumentations`와 `opencv-python-headless`가 로컬 `py -3`/`py -3.12` 환경 어디에도
  설치돼 있지 않음** (`opencv-python`은 설치돼 있어 `cv2` import 자체는 됨).
  `requirements.txt`엔 있지만 실제 pip 환경엔 없는 상태 — 지금 상태로 `build.bat`을
  돌리면 `albumentations` hidden import를 못 찾는다는 경고까지는 나되 빌드 자체는
  계속되지만(hiddenimports 미해결은 경고 수준), 실행 시점에 학습 탭에서 증강
  파이프라인을 사용하면 `ModuleNotFoundError`가 날 가능성이 높음. 설치는 이번
  작업 범위(빌드 도구 3개) 밖이라 손대지 않았고, 검증 단계에서 확인 필요.

### 검증
- `py -3 -m py_compile build.spec` 통과 (문법 검증만 — PyInstaller 런타임 이름
  `Analysis`/`EXE`/`COLLECT` 해석은 실제 빌드 시에만 됨).
- `installer/setup.iss`는 `dist/SegmentationModelUI/`가 실존해야 ISCC 전체 컴파일이
  가능해 이번엔 문법 검토(수동)만 함 — 실제 `py -3 -m PyInstaller build.spec` 및
  `build.bat` 전체 실행은 지시대로 하지 않음.
- 별도 스크래치패드 미니 프로젝트로 PyInstaller onedir의 `__file__` 동작만 실측
  검증(위 조사 항목 참고) — 실제 앱 빌드는 아님.

### 커밋
- `f3c5377` — `feat: Windows exe + Inno Setup 인스톨러 빌드 도구 추가 (build.spec/setup.iss/build.bat)`

### 다음 단계 — 완료 보고 아님
검증 에이전트가 다음을 확인해야 완료로 간주할 수 있다:
1. `albumentations`, `opencv-python-headless` 설치 여부 확인(누락 시 사용자에게
   설치 필요 안내).
2. 프로젝트 루트에서 `build.bat` 실제 실행 → `dist/SegmentationModelUI/` 생성,
   `SegmentationModelUI.exe` 정상 기동(라벨링/학습/추론 탭 스모크 테스트) 확인.
3. `installer\output\SegmentationModelUI-Setup-*.exe` 실행 → 관리자 권한 프롬프트
   없이(설계대로 `PrivilegesRequired=lowest`) 설치되는지, 설치 후 `data/`·`projects/`
   폴더에 정상적으로 쓰기가 되는지(런타임에 이미지 추가·학습 실행 등) 확인.
4. 언인스톨 시 파일이 깨끗이 제거되는지 확인.
3. 기존 Select/브러시/지우개/undo 정상 동작(회귀) 확인.

## 2026-08-24 — "Vertex Frame" 로고 자산화 + 앱 전반 아이콘 적용

### 배경
사용자가 로고 디자인 3안 중 "Vertex Frame"(옵션 B)을 최종 확정. SVG 스펙을
그대로 자산 파일로 만들고 윈도우 아이콘·타이틀바·exe·설치 프로그램에 적용하는
작업.

### 변경 (자산)
- `app/resources/logo.svg` — 지시받은 SVG 그대로 저장 (색상·좌표 변경 없음).
  `app/resources/icons/`가 아니라 `resources/` 바로 아래 배치 — 브랜드 마크는
  `app/widgets/icons.py`의 `currentColor` 재색상 로직 대상이 아니라서 기존
  아이콘 세트와 물리적으로 분리해 혼동을 방지.
- `app/resources/app_icon.ico` — `scripts/gen_icon.py`로 생성한 멀티 해상도
  (16/32/48/256) ICO.

### 변경 (코드)
- `scripts/gen_icon.py` (신규, 1회성 생성 스크립트 — 재사용 스캐폴딩이 아니라
  로고가 바뀌면 재실행할 자산 생성 도구로 유지): `QSvgRenderer`로 256×256
  1장만 투명 배경 렌더링 후 Pillow `Image.save(..., format="ICO", sizes=[...])`
  로 각 크기 다운샘플링 — 처음엔 각 크기를 개별 렌더링해
  `append_images=`로 묶으려 했으나 이 Pillow 버전(12.1.1)에서 16×16 프레임
  1장만 저장되는 문제를 실측으로 확인(ICO 바이너리 헤더 직접 파싱해 entry
  count=1 확인)하고, 표준적인 "최대 해상도 1장 + sizes 다운샘플" 방식으로
  전환해 4개 프레임(count=4) 정상 생성 확인.
- `main.py`: `QApplication` 생성 직후 `app.setWindowIcon(QIcon(str(icon_path)))`
  추가. 경로는 `Path(__file__).resolve().parent / "app" / "resources" /
  "app_icon.ico"` — main.py가 프로젝트 루트에 있으므로 `ensure_data_dirs()`의
  `sys.frozen` 분기와 달리 여기선 `__file__` 체이닝만으로 충분(datas 배치
  위치와 일치 — `icons.py`의 `_ICON_DIR` 패턴과 동일 근거, 이전 라운드에서
  스크래치패드 실측으로 PyInstaller onedir의 `__file__`이 `_internal` 내
  실제 파일로 귀결됨을 확인해둔 것을 재사용). 파일 없을 때는 조용히 스킵
  (개발 환경에서 아이콘 생성 전에도 앱이 죽지 않도록).
  `app/main_window.py`는 건드리지 않음 — `QApplication.setWindowIcon()`이
  자체 아이콘 없는 모든 하위 윈도우의 기본값이 되므로 `MainWindow`에서
  중복 호출할 필요 없음.
- `build.spec`: `datas`에 `("app/resources/app_icon.ico", "app/resources")`
  추가(코드가 아니라 경로로 읽는 리소스라 명시 필요 — `icons.py`/
  `model_presets` 항목과 동일 이유), `EXE(...)` 호출에 `icon="app/resources/
  app_icon.ico"` 추가해 exe 자체 아이콘 지정.
- `installer/setup.iss`: `[Setup]`에 `SetupIconFile={#MyDistDir}\app\resources\
  app_icon.ico` 추가(인스톨러 자체의 아이콘 — `UninstallDisplayIcon`은 기존대로
  exe를 가리키므로 건드리지 않음).

### 검증
- `py -3 -m py_compile main.py app/main_window.py build.spec` 통과(문법 검증).
- ICO 바이너리 헤더를 직접 파싱해 16/32/48/256 4개 프레임이 모두 들어있음을
  확인.
- 지시대로 실제 앱 구동(타이틀바/작업표시줄에 아이콘이 보이는지)까지는
  검증하지 않음 — **별도 검증 서브에이전트 확인 필요**. 특히 실제
  `build.bat` 전체 실행(exe/설치 프로그램 아이콘 반영 여부)은 이번 라운드
  범위 밖.

### 만든/수정한 파일
- 신규: `app/resources/logo.svg`, `app/resources/app_icon.ico`,
  `scripts/gen_icon.py`
- 수정: `main.py`, `build.spec`, `installer/setup.iss`

---

## 2026-08-25 — GitHub #9: 팬 드래그 중 휠 줌 초점 어긋남 수정

### 배경
- 기획 결과: `docs/specs/voc-github-issues-round3-2026-08-25.md`.
- 원인: `AnnotationCanvas.mousePressEvent()`가 팬 드래그 시작 시
  `_pan_start_mouse`/`_pan_start_offset`를 한 번만 캡처하고, 이후
  `mouseMoveEvent()`는 항상 이 절대 기준값으로 `self._pan`을 재계산한다.
  드래그 도중 `wheelEvent()`가 커서 기준으로 `self._zoom`/`self._pan`을
  올바르게 갱신해도, 바로 다음 `mouseMoveEvent()`가 줌 이전 시점의 stale한
  기준값으로 덮어써 초점이 틀어졌다.

### 변경
- `app/widgets/annotation_canvas.py` `wheelEvent()` — `self._pan_active`가
  True일 때 줌 갱신 직후 `_pan_start_mouse`/`_pan_start_offset`도 새
  커서 위치/`self._pan`으로 함께 갱신하도록 3줄 추가. `_pan_active`가
  False일 때(다른 도구)는 기존 로직 그대로 — 회귀 없음.

### 검증
- `py tests/test_canvas_zoom_pan.py` — 신규 회귀 테스트, 통과 확인.
  수정 전 코드로 `git stash`해서 동일 테스트를 돌리면 `AssertionError`로
  실패하는 것도 확인함 (버그 재현 → 수정 후 통과 순서로 검증).
- 브러시/폴리곤/셀렉트 도구는 `_pan_active`가 항상 False라 이번 변경
  분기를 타지 않음 — 코드 레벨로 회귀 없음 확인.
- 실제 GUI 마우스 드래그+휠 조작 실측은 하지 않음 — **검증 서브에이전트
  확인 필요**.

### 만든/수정한 파일
- 수정: `app/widgets/annotation_canvas.py`
- 신규: `tests/test_canvas_zoom_pan.py`

---

## 2026-08-25 — 최신 논문/기업 공개 모델 프리셋 3종 추가 (SegFormer/SegNeXt/PIDNet)

### 배경
- 리더가 웹서치로 기획 조사, 사용자가 최종 확정: SegFormer, SegNeXt, PIDNet.
- 샌드박스 제약(허용 import: torch/torch.nn/torch.nn.functional/torch.nn.init,
  torchvision, numpy, math, typing, collections, functools, itertools 등,
  `einops`/`timm`/`transformers` 등 외부 라이브러리 금지) 안에서 순수
  `torch.nn` 프리미티브로 직접 구현.

### 변경
- `app/model_presets/segformer.py` (신규) — SegFormer (Xie et al., NeurIPS
  2021). MiT 계층적 트랜스포머 인코더 4단계(OverlapPatchEmbed →
  EfficientSelfAttention[SR ratio로 K/V 시퀀스 축소] → Mix-FFN[depthwise
  3x3 conv로 위치 인코딩 대체]) + all-MLP 디코더(각 스테이지를 공통 차원으로
  투영 → 1/4 해상도로 concat → fuse). MiT-B0 스케일을 채널
  [32,64,160,256]/depth [2,2,2,2]로 경량화. ≈3.71M 파라미터.
- `app/model_presets/segnext.py` (신규) — SegNeXt (Guo et al., NeurIPS
  2022). MSCAN 인코더 4단계, 각 블록은 depthwise 5x5 conv →
  1x7+7x1/1x11+11x1/1x21+21x1 스트립 conv 브랜치 합산 → 1x1 conv로
  attention weight 생성 → 입력에 elementwise 곱(MSCA) → conv 기반 FFN.
  원 논문의 Hamburger(행렬분해) 디코더는 구현하지 않고 마지막 3단계
  특징을 공통 채널로 투영·upsample·concat·conv하는 경량 디코더로
  단순화(docstring에 명시). ≈3.40M 파라미터.
- `app/model_presets/pidnet.py` (신규) — PIDNet (Xu et al., CVPR 2023).
  공유 stem(1/8 해상도) → P(Detail, 1/8 유지 residual block)/I(Context,
  1/16→1/32 다운샘플 + PPM)/D(Boundary, 1/8 얕은 conv) 3-브랜치.
  이 앱의 모델 계약이 `forward(x) -> Tensor` 단일 반환만 허용해 원 논문의
  boundary auxiliary loss/멀티 출력은 쓸 수 없으므로, D 브랜치는 최종
  반환값에 포함하지 않고 `sigmoid(D 특징 conv)`를 P/I 융합
  pixel-attention 게이트로만 내부 사용(docstring에 설계 결정 명시).
  ≈0.92M 파라미터.
  - 구현 중 발견: `_PPM`의 bin=1 풀링(출력 1x1) 뒤에 `BatchNorm2d`를 쓰면
    배치 크기 1 학습 시 "Expected more than 1 value per channel" 오류가
    남 (N*H*W=1). 배치/공간 크기에 무관한 `GroupNorm(1, C)`로 교체해 해결.
- `app/model_presets/__init__.py` — `PresetInfo` 3개 등록(기존 프리셋들
  뒤에 추가, key/title/tagline/use_case/params/pros/cons 필드 구성 동일
  패턴 유지). 총 프리셋 10개.

### 검증 (구현 단계 최소 검증 — 스크래치 스크립트, 저장소 미포함)
- 세 파일 모두 `app/core/model_validator.py`의 AST 검증(`validate()`)을
  실제로 통과함 확인 (허용 import만 사용, 금지 호출 없음, forward 있는
  nn.Module 서브클래스 존재).
- `app/core/model_loader.py`의 `load_from_code()`로 실제 로드 —
  마지막에 정의된 클래스(SegFormer/SegNeXt/PIDNet)가 정확히 선택됨
  확인(헬퍼 클래스는 모두 그 이전에 정의).
- `torch.randn(1, 3, 256, 256)` 더미 입력으로 forward pass:
  num_classes=2, 5 각각에서 출력 shape이 정확히
  `(1, num_classes, 256, 256)`임을 확인.
- `loss = out.mean(); loss.backward()`로 그래디언트 확인 — 모든 파라미터
  그래디언트에 NaN 없음, 정상적으로 흐름 확인 (`model.train()` 모드에서
  배치 크기 1로 실행해 PPM 수정 이후 정상 동작 재확인).
- `py -3 -m py_compile`로 4개 파일 문법 검증 통과.
- 커밋: `c9f49e6`

### 실제 파라미터 수 (기본 num_classes=2 기준)
| 모델 | 파라미터 수 |
|---|---|
| SegFormer | 3,714,658 (≈3.7M) |
| SegNeXt | 3,404,098 (≈3.4M) |
| PIDNet | 915,746 (≈0.9M) |

### 관련
- 이번 라운드는 구현만 수행. 모델 탭 드롭다운에서 실제로 선택되는지,
  라벨링→학습→추론 골든패스에서 세 모델이 실제로 학습·추론까지 도는지는
  **검증 서브에이전트 확인 필요** — 아직 완료로 간주하지 않음.

---

## 2026-08-25 — 어노테이션 가져오기(Import) 기능 추가

### 배경
`app/widgets/export_dialog.py`(어노테이션만 내보내기, JSON 포맷)의 짝이 되는
가져오기 기능이 없었음. 프로젝트 전체 zip 백업/복원
(`project_export_dialog.py`/`project_import_dialog.py`)과는 별개 기능.

### 변경
- `app/widgets/import_dialog.py` (신규) — `ImportAnnotationDialog(QDialog)`.
  - 입력 폴더 선택 (`classes.json` + `annotations/` 구조 기대, 없으면
    `import_ann.invalid_dir` 에러).
  - 충돌 정책 라디오: 덮어쓰기 / 기존 유지(건너뛰기). 로컬에 어노테이션이
    없는 이미지는 정책과 무관하게 가져옴.
  - "새 이미지도 함께 가져오기" 체크박스(기본 켜짐) — 켜져 있고
    `images/{파일명}`이 있을 때만 `_project.images_dir()`로 복사.
  - `classes.json` 병합: 로컬에 이미 있는 `class_id`는 유지(이름/색 보존),
    없는 것만 추가 후 `save_classes()`.
  - `annotations/*.json` 순회 — `coords=="relative"`면 polygon 점을
    현재 실제 이미지 크기(`PIL.Image.open`)로 절대화, `brush_mask`는
    RLE 디코드 후 크기가 다르면 `cv2.resize(..., cv2.INTER_NEAREST)`로
    맞춤.
  - 완료 후 결과 요약 메시지박스(가져옴/기존유지/이미지없음/새이미지/새클래스
    카운트), 진행바, `get_logger` 로깅.
- `app/main_window.py` — Export 버튼 옆에 Import 버튼 추가
  (`clipboard` 아이콘 재사용, 새 아이콘 안 만듦). `_on_open_import_ann()`
  슬롯에서 다이얼로그 실행, accept + 실제 변경 있으면
  `self._labeling_tab.reload_after_import()` 호출.
- `app/tabs/labeling_tab.py` — `reload_after_import()` 공개 메서드 추가
  (기존 `_on_auto_label()`의 현재 이미지 재로드 + `_image_browser.reload()`
  패턴 재사용).
- `app/core/i18n.py` — `import_ann.*`, `menu.import_ann.tip` 키를
  한국어/영어 둘 다 추가 (`project_import.*`와 네임스페이스 충돌 없음).

### 검증 (구현 단계)
- 문법 검증: `ast.parse()`로 4개 변경 파일 통과.
- 라운드트립 스크립트(스크래치패드, 저장소 밖)로 실제 실행 검증:
  - 임시 프로젝트 A에서 polygon(class 1) + brush_mask(class 2) 어노테이션
    2장 생성 → `ExportDialog._export_json(relative=True, include_images=True)`
    로 내보냄.
  - 임시 프로젝트 B(이미지 1장은 기존 어노테이션 있음, 이미지 1장은 없음)에
    SKIP 정책으로 가져오기 → 기존 어노테이션 유지 확인, 새 이미지는 복사되고
    brush_mask가 원본과 정확히 일치(`np.array_equal`) 확인, `class_id=2`
    (`extra`)가 새로 추가되고 로컬 `class_id=1`(`object`) 이름은 안 바뀜 확인.
  - 같은 프로젝트에 OVERWRITE 정책으로 재실행 → 기존 어노테이션이 가져온
    polygon 좌표로 정확히 교체됨 확인(절대좌표 역산 오차 1e-6 이내).
  - 새 프로젝트 C에서 export 당시(60×40)와 다른 크기(120×80)의 이미지에
    가져오기 → `cv2.resize` 리사이즈된 mask shape/내용 확인.
  - `ImportAnnotationDialog()`를 여러 번 인스턴스화해도 에러 없음
    (QMessageBox는 모킹해 모달 블로킹 회피, offscreen platform 사용).
- 실제 GUI 클릭(버튼 위치, 다이얼로그 레이아웃, 라벨링 탭 실시간 갱신)은
  검증 서브에이전트가 확인해야 함 — **아직 완료로 간주하지 않음**.

### 커밋
`2837c5c` — `feat: 어노테이션 가져오기(Import) 기능 추가`

### 관련
- YOLO/COCO 포맷 import는 스코프 밖(요청서 명시) — JSON 포맷만 지원.
- 새 SVG 아이콘을 만들지 않고 기존 `clipboard.svg` 재사용.

---

## 2026-08-25 — 추론 결과 AI score/픽셀 크기 threshold 필터 + blob별 Excel 내보내기

### 배경
사용자 요청: 추론할 때 AI 신뢰도 점수와 blob(연결 요소) 픽셀 크기 기준으로 threshold를
걸고, 각 blob별 통계를 Excel로 내보낼 수 있게 해달라. 리더가 사전에 코드를 조사해
설계(InferenceResult에 raw_class_map/confidence_map 보관 → 모델 재실행 없는
refilter()로 재필터링)를 확정해 구현 지시서로 전달.

### 변경
- `app/core/inference_engine.py`
  - 신규 dataclass `BlobStat`(blob_id, class_id, class_name, pixel_count,
    mean/min/max_confidence, centroid_x/y, bbox_x/y/w/h).
  - `InferenceResult`에 `raw_class_map`(필터 전 원본 argmax 클래스맵),
    `confidence_map`(픽셀별 최고 클래스 확률, float32), `blobs: list[BlobStat]` 필드 추가.
  - `run()`: `torch.softmax` + `probs.max(dim=1)`로 confidence까지 계산해 원본
    해상도로 BILINEAR 리사이즈(class_map은 기존대로 NEAREST). `min_confidence`,
    `min_pixel_size` 파라미터 추가.
  - `run_sliding_window()`: 이미 갖고 있던 `acc`/`counts`에서 `probs_avg.max(axis=0)`로
    confidence_map 계산(추가 forward pass 없음). 동일한 threshold 파라미터 추가.
  - 신규 `_compute_blobs_and_filter()`: 클래스별 `cv2.connectedComponentsWithStats`
    (connectivity=8, class_id==0 배경 제외)로 blob 분리, threshold 미달 blob은
    배경으로 되돌리고 blob 리스트에서 제외. blob_id는 이미지 전체 기준 1부터 순차 부여.
    최초 구현은 blob마다 `confidence_map[comp_mask]` 부울 인덱싱(O(H·W) per blob)이라
    blob이 많을 때(500개, 2000×3000 합성 테스트) 872ms까지 걸려 `np.bincount` +
    `np.minimum/maximum.at`로 라벨별 mean/min/max를 픽셀 1회 순회로 계산하도록
    최적화(552ms로 단축, 클래스 수에 비례할 뿐 blob 수와 무관 — 나머지는 cv2/컬러화
    자체 비용으로 스펙에서 명시한 "수백 ms" 범위 내).
  - 신규 `refilter(raw_class_map, confidence_map, image_path_or_pil, min_confidence,
    min_pixel_size, opacity) -> InferenceResult`: 모델 재실행 없이 순수 numpy/cv2/PIL
    연산만으로 필터+오버레이+class_stats 재계산 (코드 리뷰로 torch 참조 0건 확인).
  - 신규 `export_blobs_to_excel(rows, out_path)`: openpyxl로 (이미지파일명, BlobStat)
    목록을 xlsx 1개 시트에 저장, 헤더만 볼드.
- `app/tabs/inference_tab.py`
  - "최소 AI 점수"(QDoubleSpinBox, 0~100%) / "최소 픽셀 크기"(QSpinBox, 0~100000px)
    스핀박스 추가 → `valueChanged` 시 `_on_threshold_changed()`가 `engine.refilter()`
    호출(추론 전이면 no-op, 다음 실행 시 반영). "탐지된 blob 수: N개" 라벨 추가.
  - **기존 `_on_opacity_changed()` 버그 수정**: 기존엔 opacity만 바꿔도 `engine.run()`을
    통째로 재실행해 threshold=0으로 리셋되는 문제가 생길 뻔했음(신규 필터 기능과
    충돌) — `engine.refilter()`로 교체해 forward pass 없이, 현재 threshold를 유지한
    채 재합성하도록 수정. 부수적으로 opacity 슬라이더의 기존 성능 문제도 해결됨.
  - "Excel로 내보내기" 버튼(기존 `export.svg` 아이콘 재사용) 추가. 폴더 모드+이미지
    2장 이상이면 "현재 이미지만" vs "목록 전체 일괄 추론" QMessageBox 커스텀 버튼으로
    질의. 전체 선택 시 `QProgressDialog`(Qt 내장 위젯, 별도 다이얼로그 클래스 신설
    안 함)로 진행률 표시하며 순차 추론(현재 선택 이미지는 캐시된 `_last_result` 재사용).
    `openpyxl` 컬럼: 이미지파일명/blob_id/class_id/클래스명/픽셀수/평균·최소·최대
    신뢰도(%)/중심x·y/bbox_x·y·w·h.
- `app/widgets/inference_image_list.py`: 일괄 내보내기용 `paths()` 접근자 추가
  (현재 필터+정렬된 전체 경로 리스트 반환).
- `requirements.txt`: `openpyxl>=3.1.0` 추가, `py -3 -m pip install openpyxl`로 실제
  설치 확인(이미 3.1.5 설치돼 있었음).

### 검증 (구현 단계)
- `py_compile`로 3개 수정 파일 구문 확인.
- `_compute_blobs_and_filter()` 단위 테스트: 20×20 합성 class_map에 blob 3개(낮은
  신뢰도 1개, 작은 픽셀 1개, 정상 1개) 배치 → threshold 없이 3개 모두 탐지, 신뢰도
  0.5·픽셀 5 threshold 적용 시 정상 blob 1개만 남고 나머지는 배경(0)으로 전환됨을
  확인. 입력 `class_map` 배열이 mutate되지 않음(원본 유지)도 확인.
- 성능: `QApplication` 인스턴스 생성 후(QPixmap 생성에 필요) 2000×3000 합성 이미지 +
  500개 산개 blob(고의적 최악 케이스)로 `refilter()` 552ms, 30개 blob(현실적 케이스)도
  ~520ms — cv2 connectedComponents + bincount/ufunc.at 고정 비용이 클래스 수(3~4개)에
  비례하는 구조라 blob 개수와 무관. 요청서의 "이미지 크기에 따라 수백 ms 수준" 기준
  내에 있음.
- `inspect.getsource(engine.refilter)` AST에서 `torch` 참조 0건으로 forward pass
  없음을 코드 리뷰로 확인.
- `InferenceTab()` 위젯을 QApplication 하에서 직접 생성해 에러 없이 초기화되는지,
  `_on_threshold_changed()`/`_on_opacity_changed()`를 `_last_result=None` 상태로
  호출해도 예외 없이 no-op으로 처리되는지 확인.
- `export_blobs_to_excel()`로 3개 행(2개 이미지) 샘플 데이터를 xlsx로 저장한 뒤
  `openpyxl.load_workbook()`으로 재로드 — 헤더 14개 컬럼·볼드 서식·데이터 값(신뢰도
  0~1 → % 변환 등)이 모두 정확히 일치함을 확인.
- 실제 GUI 클릭(스핀박스 조작, Excel 버튼 클릭 후 다이얼로그 흐름, 폴더 모드 일괄
  추론 진행바)까지는 검증 서브에이전트가 이어서 확인해야 함 — **아직 완료로
  간주하지 않음**.

### 커밋
`b07c1dd` — `feat: 추론 결과 AI score/픽셀 크기 threshold 필터 + blob별 Excel 내보내기 추가`

### 관련
- 리더 사전 설계 지시서 준수: 다중 시트 분리, 커스텀 스타일링, YAML 설정 등 과한
  옵션은 추가하지 않음(ponytail 원칙).

---

## 2026-08-25 — 존(Zone) 분석 탭 라운드 1: 탭 스켈레톤 + 체크포인트 로드 + 추론

### 변경
- `app/tabs/zone_analysis_tab.py` 신설 — `ZoneAnalysisTab(QWidget)`. 이미지/체크포인트
  파일 직접 열기(`QFileDialog`, 프로젝트 시스템 미사용) + `load_checkpoint_meta()`로
  `model_source` 확인 → `preset:*`는 `load_model_from_ckpt()`로 자동 인스턴스화, 그 외는
  탭 안에 모델 코드 입력 박스를 노출해 `model_validator.validate()` +
  `model_loader.load_from_code()`로 Validate → Load 2단계(모델 탭과 동일 패턴). 스펙
  판단 3 지시대로 `model_loader.save_user_code()`는 호출하지 않음(디스크에 저장 안 함,
  세션 메모리에만 유지).
- `app/widgets/zone_canvas.py` 신설 — `ZoneCanvas(OverlayViewer)`. 라운드 1은 순수 뷰어
  (원 검출/편집 UI 없음) — `overlay_viewer.OverlayViewer`의 줌/팬 QPainter 패턴을 그대로
  상속 재사용. 라운드 2에서 원(circle) 오버레이·편집을 추가할 확장 지점으로 남겨둠.
- `app/core/inference_engine.py` — `run()`/`run_sliding_window()`/`refilter()` 3곳에
  `classes: list[ClassDef] | None = None` 선택 인자 추가(각 1~2줄). `None`이면 기존과
  동일하게 `load_classes()` 폴백. `inference_tab.py`(기존 4탭)는 이 인자를 넘기지 않으므로
  동작 변화 없음 — `grep`으로 `engine.run/run_sliding_window/refilter` 호출부가
  `inference_tab.py`와 신규 `zone_analysis_tab.py` 두 곳뿐임을 확인해 회귀 위험 배제.
- 타겟(녹) 클래스 즉석 구성(스펙 판단 4) — `classes=None`으로 1차 `engine.run()` 실행해
  `raw_class_map` 확보 → 배경(0) 제외 고유 클래스 id 집계 → 1개면 자동 선택 + 편집 가능
  `QLineEdit`(기본 이름 `class_1`), 2개 이상이면 `QComboBox` 드롭다운 → 선택/편집 변경 시
  `engine.refilter(classes=[...])`로 재컬러화. 색상은 `annotation_store.DEFAULT_PALETTE`를
  `class_id % len(DEFAULT_PALETTE)`로 인덱싱(`class_panel.py`의 기존 관례와 동일 방식).
- `app/main_window.py` — 5번째 탭으로 `ZoneAnalysisTab` 등록.
- `app/core/i18n.py` — `tab.zone_analysis` ko("존 분석")/en("Zone Analysis") 키 추가.

### 확인
- `py_compile`로 신규/수정 5개 파일 문법 오류 없음 확인.
- `grep`으로 `engine.run/run_sliding_window/refilter` 호출부가 `inference_tab.py`(인자
  미전달, 회귀 없음)와 `zone_analysis_tab.py`뿐임을 확인.
- 실제 `python main.py` GUI 구동(존 분석 탭 preset/커스텀 체크포인트 양쪽 골든패스)은
  아직 수행하지 않음 — 검증 서브에이전트가 이어서 확인해야 함, **아직 완료로 간주하지
  않음**.

### 커밋
- `13f2952` — `feat: 존 분석 탭 라운드 1 — 탭 스켈레톤+체크포인트 로드+추론`
- `2c7e031` — `docs: 존 분석 탭 스펙 2차 정정 반영 + 라운드 1 로드맵 갱신`
  (계획 에이전트가 이미 완료로 기록한 스펙 2차 정정 세션분을 함께 커밋 + `roadmap.md`
  R1 체크박스 완료 갱신)

### 관련
- 스펙: [docs/specs/zone-analysis-tab-2026-08-25.md](../specs/zone-analysis-tab-2026-08-25.md)
  판단 1/3/4, 데이터 흐름, 파일 구조 제안 절.
- 판단 2(원 검출/편집)는 이번 라운드 범위 밖 — `ZoneCanvas`는 원 그리기/편집 UI 없이
  오버레이 표시만 하는 순수 뷰어로 유지.

---

## 2026-08-25 — 어노테이션 삭제/내보내기/가져오기 성능 병목 수정

### 배경
사용자 리포트: "annotation 삭제할 때 속도가 느려. annotation 내보내기와 불러오기 할 때도
느리고 멈추는 듯한 느낌이 든다." 리더가 코드를 직접 조사해 근본 원인 3가지를 확정하고
구체적인 수정 지시를 내림.

### 원인 1 — `app/widgets/annotation_canvas.py::_push_undo()`
- 기존: `copy.deepcopy(self._annotations)`로 undo 스냅샷 생성.
- 변경: `_snapshot_annotations()` 신규 메서드 — `AnnotationItem`을 필드별로 직접
  재구성하며 `points`는 `list(a.points)`(튜플은 불변이라 얕은 복사로 충분), `mask`는
  `a.mask.copy()`(numpy 네이티브 복사)로 처리. `MemoryError` 폴백 로직은 그대로 유지.
- **회귀 확인**: `_apply_eraser`, `_resolve_overlap_and_merge`, `_flood_erase`,
  `_consolidate_class_region/_consolidate_class`, `_translate_selected` 등 `.mask`를
  in-place mutate하는 모든 지점을 grep으로 확인 — 전부 해당 스트로크/드래그 시작 시점의
  `_push_undo()`(mousePressEvent/mouseMoveEvent) 이후에만 실행되므로 스냅샷이 항상
  독립된 배열을 갖고 있어 안전함을 확인. `.points`를 in-place mutate(`points[i]=...`)하는
  코드는 없음(항상 리스트 재할당) — grep으로 확인, 추가 조치 불필요.
  cause 1 스코프 밖 발견 사항 없음(모든 mutate 지점이 push_undo 보호 하에 있었음).
- **벤치마크(사전 조사와 다른 실측 결과 — 반드시 리더에게 보고 필요)**: numpy 1.26+/2.x는
  `ndarray.__deepcopy__`를 C 레벨로 구현하고 있어 `copy.deepcopy`가 이미 memcpy 수준으로
  빠름. 실측(30개 브러시 마스크, 4000×6000): deepcopy 115ms vs 네이티브 스냅샷 99ms
  (~16% 개선). 30개×1000×1000: 5.9ms vs 5.1ms(~16%), 100개×1000×1000: 20.1ms vs
  19.1ms(~5%). 사전 가설("deepcopy가 pickle __reduce__ 경로를 타 numpy .copy()보다
  훨씬 느림")은 이 프로젝트의 numpy 버전(요구사항 `numpy>=1.26.0`)에서는 성립하지 않음 —
  그래도 변경 자체는 안전하고 소폭 빠르며 제네릭 dataclass deepcopy 오버헤드를 제거하므로
  그대로 반영함. 사용자가 체감한 "삭제 시 렉"의 실제 병목은 원인 3(전체 재스캔)이거나
  다른 경로(오버레이 rebuild 등)일 가능성이 높음 — 리더 판단 필요.
- 검증: `undo_selfcheck.py`(스크래치패드) — 브러시 마스크 5개로 삭제→undo 6회 반복,
  매번 `np.array_equal`로 픽셀 단위 완전 복원 확인 + 라이브 마스크 in-place mutate 후에도
  스냅샷이 영향받지 않음(별개 배열 객체) 확인. 전부 통과.

### 원인 2 — `export_dialog.py` / `import_dialog.py` 동기 실행
- `ExportWorker(QThread)` 신설(export_dialog.py) — `_export_json/_export_yolo/_export_coco`
  로직을 그대로(파일 I/O만) 워커로 이동, `self._progress.setValue()`/`self._lbl_status.setText()`
  호출을 `progress.emit(current, total, filename)`으로 교체. `finished(int count)`,
  `error(str message)` 시그널 추가. `ExportDialog._on_run()`은 pairs 빌드(기존 위치 유지)
  후 워커를 생성해 `.start()`만 호출(non-blocking), 진행바/상태라벨/완료 메시지박스는
  시그널 슬롯(`_on_worker_progress/_finished/_error`, 메인 스레드)에서 갱신. 실행 중
  `_btn_run`/`_btn_close` 비활성화.
- `ImportWorker(QThread)` 신설(import_dialog.py) — 이미지별 가져오기 루프를 동일 패턴으로
  이동. 클래스 병합(`_merge_classes()`)은 가벼운 1회성 작업이라 메인 스레드에서 미리
  실행한 뒤 결과(new_classes 개수)만 워커에 넘김(파일 I/O 루프 자체와는 무관, 스펙에
  명시된 "클래스 병합 + 이미지별 가져오기 루프를 워커로" 중 무거운 후자만 이동 —
  전자는 어차피 한 번의 JSON 읽기+쓰기라 블로킹 체감이 없음).
- 취소 기능은 스펙대로 추가하지 않음.
- **PyQt6 시그널 이름 주의사항 확인**: `QThread`의 내장 `finished` 시그널과 동일한 이름의
  커스텀 `pyqtSignal(int)`을 서브클래스에 선언해도(스펙에 명시된 이름 `finished(count)`)
  정상 동작함을 별도 스크립트로 검증(처음엔 이벤트 루프 미처리로 오작동처럼 보였으나
  `processEvents()`/`exec()`로 큐드 커넥션을 처리하면 정상 emit됨 — 오탐 확인).
- 검증: `export_import_selfcheck.py`(스크래치패드) — 임시 프로젝트 40장(라벨링 26장,
  polygon/brush_mask 혼합) 생성 → `ExportWorker`로 JSON 포맷 내보내기(실제 QThread
  `.start()` + `QEventLoop` 처리) → 결과 카운트/파일 수가 기존 동기 로직과 100% 일치
  확인 + 워커 실행 중 5ms 간격 `QTimer`가 7회 tick(메인 스레드가 블로킹되지 않음을 증명)
  → 내보낸 결과를 `ImportWorker`로 새 프로젝트에 가져오기 → imported=26, new_images=26
  일치 확인. YOLO/COCO 포맷은 로직을 그대로(변경 없이) 옮겼으므로 별도 자동 검증은
  생략 — 필요 시 검증 에이전트가 UI 골든패스로 추가 확인 권장.

### 원인 3 — `image_browser.py::_on_delete()`
- 확인 결과: `_on_delete()`가 삭제 후 정말 `reload()`(전체 재스캔, 이미지마다
  `get_label_status()` 디스크 I/O)를 호출하고 있었음 — 삭제 건수와 무관하게 전체
  이미지 수에 비례한 비용.
- 수정: 삭제된 경로만 `self._all_paths`/`self._status_cache`에서 제거한 뒤
  `self._apply_display()`(트리 위젯 갱신, 디스크 I/O 없음)만 호출하도록 변경.
  `image_deleted` 시그널 구독자(`labeling_tab.py::_on_image_deleted`)는 캔버스 상태만
  정리할 뿐 별도 reload를 트리거하지 않음을 grep으로 확인 — 부작용 없음.
- 검증: `browser_delete_selfcheck.py`(스크래치패드) — 20장 프로젝트에서 3장 선택 삭제 시
  `get_label_status` 호출 횟수 0회(패치로 카운팅), 남은 17장이 `_all_paths`/`_status_cache`/
  트리 위젯 모두에서 정확히 일치함을 확인. 통과.

### 파일
- `app/widgets/annotation_canvas.py`
- `app/widgets/export_dialog.py`
- `app/widgets/import_dialog.py`
- `app/widgets/image_browser.py`

### 커밋
- `46eb77b` — `perf: 어노테이션 삭제/내보내기/가져오기 성능 병목 수정`

### 확인 필요 (검증 서브에이전트에게)
- `python main.py` 실제 구동으로 라벨링 탭 골든패스(브러시 그리기→삭제→undo, 여러 장
  삭제) + 내보내기/가져오기 다이얼로그 실제 조작(진행바가 여러 단계로 갱신되는지,
  실행 중 메인 창이 여전히 반응하는지)까지 확인 필요 — 이번 구현 단계에서는 위젯을
  직접 인스턴스화한 스크립트 기반 자동 검증만 수행했고 `python main.py`로 GUI를
  띄워 수동 조작하지는 않았음. **아직 완료로 간주하지 않음**.
- 원인 1의 벤치마크가 사전 가설과 다르게 나온 점(개선폭 5~16%에 불과, 사용자가 체감한
  "삭제 시 렉"의 실제 원인은 다른 곳일 가능성)을 리더가 재검토할 필요가 있음.


## 2026-08-26 — 존(Zone) 분석 탭 라운드 2: 원(circle) 검출 파이프라인 + 수동 편집

### 배경
- 스펙: `docs/specs/zone-analysis-tab-2026-08-25.md` 판단 2(최종본) — Canny+findContours
  로 링 후보 컨투어를 뽑은 뒤 강건한(outlier-resistant) 원피팅으로 `(cx, cy, r)`을
  확정하는 파이프라인. 폴리곤/컨투어 저장은 폐기, 원(circle)이 정본.
- 리더 지시대로 2개 서브스텝(2a 헤드리스 스크립트 프로토타입 → 2b 위젯 구현) 순서로 진행.

### 2a — 헤드리스 파라미터 튜닝 (Qt 없음, 순수 OpenCV)
- `scripts/zone_circle_proto.py` 작성 — `projects/nok/images/{7~11}번.bmp`(junction 공유,
  읽기 전용) 5장을 `np.fromfile`+`cv2.imdecode`로 로드(Windows 비-ASCII 경로에서
  `cv2.imread`가 실패하는 문제 우회 — 앱 본체에서는 이 문제가 없음, `Image.open()` 이
  이미 유니코드 경로를 정상 처리하기 때문에 `zone_analysis_tab.py`는 PIL로 읽어 BGR로
  변환하는 방식을 씀).
- **1차 시도(파라미터 기본값)로는 원본 케이스 테두리·크림핑(가스켓) 링 등 바깥쪽 큰
  원이 전혀 검출되지 않는 문제 발견** — 디버그 스크립트(스크래치패드)로 원인 조사:
  `cv2.Canny` 출력에서 큰 원들의 에지가 글레어/그림자/미세 스크래치로 국소적으로
  끊겨 있어 `cv2.findContours`가 닫힌 루프가 아니라 여러 개의 열린 호(arc)로 쪼개
  잡음 → `circularity = 4π·area/perimeter²` 계산이 열린 호에 대해 크게 왜곡되어
  필터를 통과 못 함 (`cv2.contourArea`가 호를 직선으로 강제로 닫아 면적을 계산하기
  때문). 안쪽의 작은 원(원판 개구부 등)은 국소 왜곡이 적어 우연히 닫힌 루프로 잡혀
  검출되고 있었음.
- **해결**: Canny 직후, `findContours` 이전에 `cv2.morphologyEx(edges, MORPH_CLOSE,
  kernel, iterations=2)`를 추가해 국소 끊김을 이어붙임 — 커널 크기 9/15/21/25를
  실측 비교한 결과 15×15가 큰 원의 닫힘과 인접한 별개 링끼리의 과도한 병합 사이의
  균형점(21 이상부터 서로 다른 물리적 링이 하나로 뭉개지는 조짐 확인).
- 이 조치 후 5장 전부에서 4~5개의 동심원이 정상 검출됨(케이스 테두리, 크림핑/가스켓
  링, 원판 가장자리, 원판 개구부). 특히 8번/11번/9번 이미지에는 가스켓 링 부근에
  실제 황갈색 변색(녹 의심)이 육안으로 보이는데도, 피팅된 원이 해당 구간에서 실제
  원형 경계를 벗어나지 않음을 오버레이 이미지로 육안 확인 — **이번 2차 스펙 수정의
  핵심 확인 목표 충족**.
- 부수적으로 먼지/스크래치 등 잔 노이즈가 만드는 매우 작은 가짜 원이 1~2개씩 섞여
  나와 `min_area_frac`을 0.0008 → 0.003으로 상향(실측 최소 링도 면적비 4~5% 이상이라
  여유 있게 구분됨)해 제거.
- 9번 이미지는 원판 가장자리 링이 검출되지 않음(해당 구간 에지 손상이 더 심해 모폴로지
  CLOSE로도 못 이음) — v1은 자동 검출 실패 시 수동 추가로 보완하는 것을 전제로 하므로
  허용 범위로 판단, 추가 파라미터 완화는 하지 않음(YAGNI — 5장 중 1장의 1개 링만
  누락, 나머지는 전부 정상).
- **확정 기본 파라미터**(`app/core/circle_detector.py::DetectParams`): `canny_low=40,
  canny_high=120, circularity_min=0.55, circularity_max=1.35, min_area_frac=0.003,
  max_area_frac=0.98, min_contour_points=30, close_kernel_size=15, close_iterations=2,
  outlier_iterations=2, outlier_keep_frac=0.85, max_residual_ratio=0.12,
  merge_center_frac=0.02, merge_radius_frac=0.05`. 민감도 슬라이더(0~1)는
  `_params_for_sensitivity()`에서 `canny_low`(70→20)와 `circularity_min`(0.70→0.40)에만
  매핑 — 나머지는 v1에서 UI 노출하지 않음(스펙 "향후 확장 후보"와 일치).

### 2b — 위젯 구현
- `app/core/circle_detector.py` 신설 — `detect_circles(bgr_np, sensitivity, params=None)
  -> list[(cx,cy,r)]`, Kasa 대수적 최소자승 원피팅 + 잔차 상위 제외 재피팅(1~2회) +
  중복 후보 병합. `_MAX_DETECT_DIM=2048` 다운스케일 후 좌표 역산(`annotation_canvas.py`/
  `inference_engine.py`의 `_MAX_OVERLAY_DIM` 관례 재사용). `demo()` 자가 점검 포함 —
  합성 이미지에 링 둘레 일부만 반지름을 부풀린 "녹 침범" 모사 후 강건 피팅이 원래
  반지름을 복원하는지 assert로 확인(`python app/core/circle_detector.py`로 직접 실행 가능).
- `app/widgets/zone_canvas.py` 확장 — `ZoneCanvas(OverlayViewer)`에 원 렌더링(선택 시
  강조색) + 편집(중심 근처 드래그=이동, 테두리 근처 드래그=반지름 조절, 빈 곳
  드래그=신규 생성, Delete/우클릭 메뉴=삭제) 추가. 원 좌표는 항상 "원본 이미지 픽셀
  좌표"로 저장하고, 오버레이 픽스맵 스케일(`_MAX_OVERLAY_DIM`으로 다운스케일될 수
  있음)과 줌/팬을 모두 거쳐 화면에 투영하는 좌표 변환 헬퍼(`_orig_to_screen`/
  `_screen_to_orig`)를 추가 — 픽스맵 해상도와 원본 해상도가 다를 수 있다는 점을
  놓치지 않도록 명시적으로 분리.
- `app/tabs/zone_analysis_tab.py` — "자동 검출" 버튼 + 민감도 슬라이더(0~100%) +
  반지름 오름차순 원 목록 사이드 패널(`QSplitter`) 연결. 이미지 선택 시 `PIL.Image`로
  원본 크기를 읽어 `ZoneCanvas.set_image_size()`에 전달(체크포인트/추론과 무관하게
  이미지 선택 직후 바로 알 수 있는 값). 자동 검출은 PIL로 이미지를 열어 RGB→BGR
  변환 후 `detect_circles()` 호출(Windows 유니코드 경로 문제 없음). 목록↔캔버스 선택
  양방향 동기화(`circle_selected`/`circles_changed` 시그널, `blockSignals`로 순환 방지).

### 검증
- `python -m py_compile` 통과(`circle_detector.py`, `zone_canvas.py`,
  `zone_analysis_tab.py`, `scripts/zone_circle_proto.py`).
- `python app/core/circle_detector.py` 자가 점검(`demo()`) 통과.
- `QApplication` 하에 `ZoneAnalysisTab`/`ZoneCanvas` 직접 인스턴스화 + `set_circles`/
  `get_circles`/`circles_with_ids`/`select_circle`/`remove_selected` 왕복 스모크 테스트
  통과(스크래치패드 임시 스크립트, 저장소에는 없음).
- **`python main.py` 실제 GUI 구동으로 자동 검출 버튼/민감도 슬라이더 조작 + 원 드래그
  이동·반지름 조절·생성·삭제 왕복은 아직 하지 않았음 — 검증 서브에이전트 확인 필요.**
  특히 실제 이미지 로드 시 `set_image_size()`가 호출되는 시점(이미지 선택 직후)과
  오버레이 픽스맵이 설정되는 시점(추론 실행 후)이 분리되어 있어, 추론 실행 전에
  자동 검출을 누르면 캔버스에 표시할 배경 픽스맵이 없어 원이 그려지지 않는(그러나
  내부 데이터는 정상 보관되는) 상태가 될 수 있음 — 실사용 흐름상 문제 없는지
  실제 조작으로 확인 필요.

### 파일
- `app/core/circle_detector.py` (신규)
- `scripts/zone_circle_proto.py` (신규, 재현 가능한 튜닝 스크립트로 저장소에 유지)
- `app/widgets/zone_canvas.py`
- `app/tabs/zone_analysis_tab.py`

### 커밋
- `1815921` — `feat: 존 분석 원 검출 파이프라인(circle_detector) + 파라미터 튜닝 프로토타입`
- `b1f05bc` — `feat: 존 분석 캔버스에 원 자동 검출/수동 편집 UI 연결`

### 확인 필요 (검증 서브에이전트에게)
- 위 "검증" 절의 `python main.py` 실제 GUI 골든패스(자동 검출 + 수동 편집 4종 —
  이동/반지름 조절/생성/삭제) 확인 필수 — 구현 단계에서는 미수행.
- 이미지 선택 직후 vs 추론 실행 후 `set_image_size`/픽스맵 설정 시점 분리로 인한
  UX 흐름(추론 전 자동 검출 클릭 시 동작) 실제 확인.

---

## 2026-08-26 — 존(Zone) 분석 탭 라운드 3: 존 리스트 + 퍼센티지 계산

작업 지시: 리더가 `docs/specs/zone-analysis-tab-2026-08-25.md` "판단 2"(원 정렬 규칙)·
"존 계산 로직"(원판 마스크 집합 차집합)·"UX 흐름 상세 > 존 선택 및 네이밍"·"라운드
분할 제안 3번"에 따라 라운드 3 구현을 위임. 워크트리: `D:\segmentation model-zone-analysis-tab`
(브랜치 `feature/zone-analysis-tab`, `main`과 공유 금지).

### 변경
- `app/core/zone_metrics.py` 신설(Qt 의존성 없음, 순수 numpy):
  - `Circle(id, cx, cy, r)` / `Zone(index, name, mask)` 데이터클래스 — `zone_canvas.py`의
    기존 `_CircleItem` 필드 이름을 그대로 따름(일관성).
  - `_disk_mask(cx, cy, r, img_shape)` — `(x-cx)^2+(y-cy)^2<=r^2` 벡터화 거리식(`np.ogrid`)
    으로 원판 마스크 생성. `cv2.circle`/`fillPoly` 모두 아닌, 이미 원 방정식이 있으므로
    numpy만으로 더 단순한 쪽을 선택(스펙이 명시한 두 옵션 중 하나, YAGNI 상 cv2 불필요).
  - `zones_from_circles(circles, img_shape) -> list[Zone]` — 반지름 오름차순 정렬 후
    `Zone_center=mask(C_0)`, `Zone_i=mask(C_{i+1}) AND NOT mask(C_i)`(i=0..N-2),
    `Zone_outside=전체 AND NOT mask(C_{N-1})`. 이름: `중심부`/`링 k`/`바깥쪽`. 원 0개면
    빈 리스트 반환(존 개념 자체가 성립하지 않는 경우를 단순 처리).
  - `zone_stats(zone_mask, target_class_mask) -> float` — 존 면적 대비 (존 AND 타겟)
    픽셀 비율(%). 존 면적 0이면 0.0 반환(0-division 가드).
  - `if __name__ == "__main__"` self-check: 5×5 합성 이미지에 원 1개(cx=2,cy=2,r=1)를
    올려 마스크에 속하는 5개 픽셀 좌표를 직접 손계산 후 `assert`(픽셀 카운트 수작업
    검산 — 스펙의 라운드 3 검증 기준과 정확히 일치하는 형태), 원 2개 중첩 케이스에서
    "존 면적 합 = 전체 픽셀 수, 존끼리 겹침 없음" 파티션 불변식 assert, 원 0개 케이스도
    포함.
- `app/widgets/zone_canvas.py` 확장:
  - `zone_clicked(int)` 시그널 추가 — 기존 `mouseReleaseEvent`가 "빈 곳 클릭 후 드래그
    없이 놓으면(반지름이 `_MIN_CREATE_R_PX` 미만) 생성 취소" 처리를 이미 하고 있던
    지점을 그대로 활용: 그 클릭을 "존 선택 클릭"으로 재해석해 클릭 지점이 속한 존
    인덱스를 계산해 emit한다. 새 위젯/모드 추가 없이 기존 생성 취소 경로 재사용(라더:
    이미 있는 이벤트 흐름 재활용이 새 클릭 모드 구현보다 단순).
  - `_zone_index_at(x, y) -> int` — 원 포함 개수(`contained`)만 세어 `n - contained`로
    존 인덱스 산출(존 마스크 배열 생성 없이 기하 조건만으로 zone_metrics와 동일한
    인덱싱 규칙 재현 — nested 전제도 core 모듈과 동일하게 그대로 둠).
  - `set_highlighted_zone(int | None)` + `_paint_zone_highlight()` — 존 하이라이트를
    `QPainterPath`의 짝수-홀수(OddEven) 채우기 규칙으로 그린다(외부 원 경로 + 내부 원
    경로를 한 path에 추가하면 고리 모양이 자동으로 나옴). numpy 마스크를 QImage로
    변환해 그리는 방식은 채택하지 않음 — 존 경계가 정확히 원 경계이므로 기존 원
    렌더링에 쓰던 `_orig_to_screen()` 좌표 변환을 그대로 재사용하는 쪽이 대용량
    이미지(5472×3648)에서도 비트맵 왕복 없이 더 가볍고 코드도 짧음.
  - 원 목록이 바뀌는 지점(`clear_circles`/`set_circles`/`remove_selected`)마다
    `_highlighted_zone`을 `None`으로 리셋해 존 개수가 바뀐 뒤 stale 인덱스를 참조하지
    않도록 함.
- `app/tabs/zone_analysis_tab.py`:
  - 존 리스트 사이드 패널(`QListWidget`) 추가 — 항상 전체 존의 이름+퍼센티지를 함께
    표시(스펙 "리스트는 항상 전체 존의 퍼센티지를 한번에 보여준다"). 리스트 클릭 →
    `_on_zone_row_selected` → `canvas.set_highlighted_zone()`. 캔버스 빈 곳 클릭 →
    `zone_clicked` 시그널 → `_on_canvas_zone_clicked`가 리스트의 `currentRow`만 동기화
    (양방향, `blockSignals`로 순환 방지 — 라운드 2 원 목록 동기화와 동일 패턴).
  - `_recompute_zones()` — 캔버스의 `circles_with_ids()`(반지름 오름차순, id 포함)를
    `zone_metrics.Circle`로 변환 → `zones_from_circles()` → 각 존과
    `raw_class_map == target_class_id`(판단 4의 즉석 타겟 마스크, 필터링 없는 원본
    argmax) AND → `zone_stats()`로 퍼센티지 산출해 리스트 재구성. 원이 없거나 추론
    결과/타겟 클래스가 아직 없으면 리스트를 비움.
  - `_recompute_zones()` 호출 지점: `circles_changed`(원 추가/이동/크기조절/삭제마다),
    `_on_target_changed()` 끝(타겟 클래스 전환/이름 변경 재필터 후), 클래스가 검출되지
    않은 경우(`_setup_target_classes`의 `not ids` 분기) — 모두 "타겟 마스크 또는 원
    구성이 바뀔 수 있는 지점"이라는 공통 조건으로 한 함수에 모아 회귀 위험을 줄임.
  - `self._target_class_id` 인스턴스 변수 신설 — 기존에는 `_on_target_changed()`
    지역변수로만 있던 현재 타겟 id를 저장해 `_recompute_zones()`에서 재사용(공유
    상태를 signal 콜백 지역변수에서 인스턴스 상태로 승격한 유일한 구조 변경).

### 검증(구현 단계 — self-check + 정적 실행 확인만, GUI 골든패스는 검증 서브에이전트 몫)
- `py -3 app/core/zone_metrics.py` self-check 통과("zone_metrics self-check OK").
- `py -3 -m py_compile` 통과(`zone_metrics.py`, `zone_canvas.py`, `zone_analysis_tab.py`).
- `QApplication` 하 스모크 스크립트(스크래치패드, 저장소에는 없음): `ZoneCanvas`에 원
  2개(동심, r=20/50) 등록 → `_zone_index_at()`(기하 hit-test)와 `zones_from_circles()`
  (마스크 기반)가 3개 지점(중심부/링1/바깥쪽 각 1곳)에서 서로 일치함을 확인, 존별
  `zone_stats()` 산출값 확인, `select_circle`/`remove_selected`/`set_highlighted_zone`
  왕복 확인 — 전부 통과.
- `ZoneAnalysisTab()` 단독 인스턴스화(존 리스트 패널 포함) 성공 확인.
- **`python main.py` 실제 GUI 구동으로 존 리스트 표시/클릭↔캔버스 하이라이트 동기화/
  원 편집 시 실시간 재계산 확인은 아직 하지 않았음 — 검증 서브에이전트 확인 필요.**

### 파일
- `app/core/zone_metrics.py` (신규)
- `app/widgets/zone_canvas.py`
- `app/tabs/zone_analysis_tab.py`
- `docs/roadmap.md` (R3 항목 갱신)

### 커밋
- `d0fcfd9` — `feat: 존 분석 존별 퍼센티지 계산 + 존 리스트 패널 추가 (라운드 3)`

### 확인 필요 (검증 서브에이전트에게)
- `python main.py` 실제 GUI 골든패스: 자동 검출/수동 원 편집 후 존 리스트에 올바른
  개수·이름(중심부/링 N/바깥쪽)·퍼센티지가 표시되는지, 원 추가/이동/반지름조절/삭제
  각각에 실시간 재계산되는지, 타겟 클래스 전환 시 재계산되는지, 캔버스 빈 곳 클릭과
  리스트 클릭 양방향 하이라이트 동기화가 실제로 맞물리는지.
- 스펙이 명시한 "원이 서로 교차하는 비정상 입력"(nested 전제 위반) 케이스는 v1에서
  방지 로직이 없다는 점 — 검증 시 버그로 취급하지 말 것(스펙에 이미 명시된 의도적
  범위 제외, 재확인만 필요).
