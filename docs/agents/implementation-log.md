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
