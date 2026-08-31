# 존(Zone) 분석 탭 — 배치 모드 재설계 + 성능/CPU경고 개선 (2026-08-30 세션 요청)

전제: R1~R4·R-A~R-C·R3-1~R3-5·GitHub #13/#14·"오프라인 원 검출 테스트 삭제"까지 전부
완료된 상태(`docs/roadmap.md` "존(Zone) 분석 탭" 절 참고). 이번 세션 요청 2건(요청 A: Zone
결정 방법 3모드, 요청 B: 세션 이슈 3건)을 다룬다. 코드 근거는 `app/tabs/zone_analysis_tab.py`
(2026-08-30 기준 1013줄)·`app/widgets/zone_canvas.py`(734줄)·`app/core/zone_metrics.py`를
실제로 읽고 확인했다.

## 코드 대조 결과 — 로드맵 서술과 실제 코드 일치 확인

- `_chk_apply_all`(체크박스)/`_btn_batch`/`_on_batch_process()`의 `apply_to_all` 분기/
  `_scale_circles()` 헬퍼 — 로드맵 서술대로 전부 존재. **요청A 모드1("일괄 적용")은 이미
  구현돼 있음**, 재작업 불필요.
- `ZoneCanvas._manual_strokes`/`_undo_stack`/`get_circles()`/`circles_with_ids()`/
  `removed_blob_ids()`/`blob_labels()`/`apply_manual_strokes()` — 전부 로드맵 서술과 일치.
- `zone_analysis_tab.py`는 `app/core/device_info.prompt_gpu_availability()`를 **전혀
  import/호출하지 않음** — `inference_tab.py`(454행)/`training_tab.py`(460행)/
  `auto_label_dialog.py`(205행)와 달리 GPU 경고 없이 바로 추론 실행. 요청B-이슈3과 일치.
- `ZoneCanvas.paintEvent()` → `_paint_erase_preview()`가 `self._manual_strokes`(커밋된
  스트로크 전체 이력)를 매 호출마다 전체 순회 — `_erase_mask_np`(원본 해상도 bool 캐시)는
  실제 마스크 계산(`erase_mask()`/`apply_manual_strokes()`)에만 쓰이고 **화면 렌더링
  경로에는 전혀 관여하지 않음**을 코드로 확인. `mouseMoveEvent()`가 스트로크 드래그 중
  매번 `self.update()`를 호출하므로 스트로크가 쌓일수록(그린 만큼) 매 프레임 O(누적
  스탬프 수) 렌더링 — 요청B-이슈1 리더 진단과 정확히 일치.
- `_on_batch_process()`의 `target_mask = result.class_map == target_cid`는 **`removed_blob_ids`/
  `manual_strokes`를 전혀 반영하지 않음** — 배치 처리는 항상 "원본 추론 결과 그대로"만
  본다. 이는 요청A 설계가 반드시 고쳐야 할 지점(아래 "판단 3" 참고).
- **신규 발견 — `_on_batch_process()`의 숨은 비효율**: 대상 이미지가 `self._image_path`
  (현재 표시 중인 기준 이미지)와 다르면 무조건 `engine.run()`을 다시 호출한다.
  `self._results`(`_on_run()`이 목록 전체를 이미 추론해 채워둔 캐시)를 전혀 조회하지
  않고, 계산한 `result`도 `self._results`에 다시 써넣지 않는다(휘발). 이번 라운드에서
  "이미지 클릭 시 캐시 복원"을 구현하려면 **정확히 이 캐시 부재를 고쳐야** 하므로
  (아래 "판단 3" 참고) 별도 라운드 없이 R-ZONE-3에 편입한다.

## 요청 B — 세션 이슈 3건

### 이슈 1 (성능) — 원인 확정 + 해결 설계

**원인**: `paintEvent()` → `_paint_erase_preview()`가 매 프레임 `self._manual_strokes`
전체(그리기+지우기 스트로크 이력 전부)를 순회해 원을 다시 그린다. 커밋된 스트로크는
스트로크가 끝난 뒤로는 절대 바뀌지 않는데도 매번 처음부터 다시 그리므로, 스트로크가
쌓일수록(사용자가 그림을 그릴수록) 프레임당 비용이 선형으로 늘어나 체감 버벅임이 커진다.

**해결 — rasterize-on-commit 캐시**(`annotation_canvas.py`의 브러시 오버레이 캐싱과
동일 원칙, 그쪽은 `_overlay_pixmap`/`_overlay_dirty` 플래그로 전체 오버레이를 캐시하는
더 큰 범위였고 여기선 "수동 스트로크 레이어"만 좁게 캐시하면 됨):

1. 신규 필드 `self._stroke_overlay: QImage | None`(pixmap 좌표계, 즉 `self._pixmap`과
   동일 크기의 ARGB32_Premultiplied, 화면 zoom/pan 좌표 아님 — `_orig_to_screen()`이
   매번 zoom/pan을 계산하는 것과 달리 이 이미지는 pixmap 스케일까지만 미리 구워둔다).
2. `mouseReleaseEvent()`가 `self._manual_strokes.append(...)` 하는 바로 그 지점에서
   새로 커밋된 스트로크 1개만 `_rasterize_stroke(draw, stroke)`로 캐시 이미지에
   추가 드로우(스탬프 개수만큼 원 몇 개 — 저렴, 전체 재순회 아님).
3. `paintEvent()`(`_paint_erase_preview`)는 캐시가 있으면
   `p.save(); p.translate(self._pan); p.scale(self._zoom, self._zoom); p.drawImage(0, 0, self._stroke_overlay); p.restore()`
   1회 호출로 끝내고, **진행 중인 현재 스트로크(`self._current_stroke`, 점 개수가
   적음)만 기존 방식대로 매 프레임 직접 그린다** — 리더가 지시한 그대로.
4. 캐시 전체 재구성(`_rebuild_stroke_overlay()` — `self._manual_strokes`를 처음부터
   다시 그림)이 필요한 지점은 3곳뿐(전부 저빈도 이벤트, 성능 문제 없음):
   - `set_blob_data()`(타겟 클래스 전환 — 어차피 `_manual_strokes`를 통째로 비우므로
     캐시도 `None`으로 리셋)
   - `undo()`(스택 pop 후 `_manual_strokes`가 통째로 옛 스냅샷으로 교체되므로 재생 필요
     — `_replay_erase_strokes()`가 `_erase_mask_np`를 재생하는 것과 같은 패턴)
   - 신규 `set_state()`(아래 R-ZONE-3, 이미지 전환 캐시 복원 — 마찬가지로 전체 교체)
5. `self._pixmap`이 교체될 때(이미지 전환) 캐시 크기가 안 맞을 수 있으니
   `_rasterize_stroke`/`_rebuild_stroke_overlay` 진입 시 `self._pixmap.size()`와
   캐시 크기를 비교해 다르면 새로 만든다(별도 리사이즈 이벤트 배선 불필요 — 이미지
   전환은 항상 `set_blob_data(None, None)`을 거쳐 `_manual_strokes`가 비므로 자연히
   재생성됨).

**영향 파일**: `app/widgets/zone_canvas.py` 단독. 신규 파일 없음. `apply_manual_strokes()`/
`erase_mask()`/`_erase_mask_np`(마스크 계산 경로)는 전혀 손대지 않음 — 렌더링 경로만
분리.

### 이슈 2 — 요청A 설계로 통합 해결

아래 "요청 A" 절 참고. 별도 구현 불필요.

### 이슈 3 (CPU 추론 경고 누락) — 기존 함수 재사용, 신규 로직 없음

`app/core/device_info.prompt_gpu_availability(parent, context)`를 `zone_analysis_tab.py`에
import 후 2곳에 추가:

- `_on_run()` 최상단(모델/체크포인트 검증 통과 직후, 워커 시작 전) —
  `if not prompt_gpu_availability(self, "존 분석"): return`.
- `_on_batch_process()`도 (판단 3에서 확인하듯) 캐시에 없는 이미지에 대해
  `engine.run()`을 호출할 수 있으므로 동일하게 최상단에 추가 — 단, `_on_run()`을 먼저
  거치는 게 일반적인 사용 순서(배치 버튼 활성화 조건 자체가 "기준 이미지 추론 완료"를
  요구)라 실사용에서 이 경고가 뜰 일은 드물지만, 코드 경로 정합성을 위해 넣는다.

문구/UX는 기존 3곳(추론/학습/오토라벨링)과 동일하게 "존 분석"만 context로 넘겨
통일한다. "다시 묻지 않기" 옵션 등 신규 UX는 **추가하지 않음**(과설계 방지, 기존
3곳도 없는 기능을 이 탭에만 넣을 이유 없음 — 필요해지면 4곳 동시에 추가하는 별도
요청으로 다룰 것).

**영향 파일**: `app/tabs/zone_analysis_tab.py` 단독(import 1줄 + 호출 2곳).

## 요청 A — Zone 결정 방법 3모드 + 자동 저장

### 핵심 설계 결정

**저장 범위는 세션 메모리로 한정한다(디스크 영속화 아님)** — 아래 "결정 필요" 절 참고.

**신규 무거운 자료구조를 만들지 않는다** — `ZoneCanvas._push_undo()`가 이미 만들어 쓰는
경량 스냅샷 dict(`circles`/`removed_blob_ids`/`erase_strokes`/`manual_strokes`, 전부
좌표·id 리스트일 뿐 마스크 배열은 없음)를 **그대로** "이미지별 상태" 표현으로 재사용한다.

**`ZoneCanvas`에 신규 공개 API 2개만 추가**(둘 다 기존 undo 스냅샷 포맷 그대로 입출력):

```python
def get_state(self) -> dict:
    """현재 편집 상태 스냅샷 — _push_undo()와 완전히 동일한 경량 표현.
    호출부(탭)가 이미지 전환 시 세션 캐시에 저장하는 용도."""
    return {
        "circles": [(c.id, c.cx, c.cy, c.r) for c in self._circles],
        "removed_blob_ids": set(self._removed_blob_ids),
        "erase_strokes": list(self._erase_strokes),
        "manual_strokes": list(self._manual_strokes),
    }

def set_state(self, state: dict) -> None:
    """get_state()가 반환한 스냅샷을 복원 — undo() 본체와 동일 로직이지만
    스택에서 꺼내지 않고 외부 상태를 그대로 적용한다(undo 스택에 영향 없음)."""
    ...  # undo()의 "snap 적용" 부분(원 재구성 + _replay_erase_strokes +
         # _rebuild_stroke_overlay + circles_changed/circles_committed emit)을
         # 그대로 재사용 — undo()를 이 함수를 호출하도록 리팩터링해 중복 제거 권장
         # (동작 변화 없음, 순수 정리).
```

`undo()`는 `snap = self._undo_stack.pop()` 후 `self.set_state(snap)`을 호출하는 형태로
리팩터링하면 두 메서드의 복원 로직이 중복되지 않는다(구현 시 판단, 동작 동일).

### 3모드 UI

기존 `_chk_apply_all`(2-way 체크박스)를 **완전히 대체**하는 `QComboBox`(3-way) —
2-way를 3-way로 확장하면서 체크박스를 남겨두면 "체크 상태 2개 × 신규 항목"처럼 읽혀
혼란스럽다(리더가 언급한 "확장 vs 대체" 판단 — 대체가 더 단순하고 명확).

```python
self._mode_combo = QComboBox()
self._mode_combo.addItem("일괄 적용", "apply_all")
self._mode_combo.addItem("일괄 적용 후 수정", "apply_all_edit")
self._mode_combo.addItem("장별 적용(이미지별 개별)", "per_image")
# 기본값 = 기존 체크 상태(True)와 동일한 "apply_all"
```

`_batch_box`(QGroupBox) 제목을 "존 일괄 적용" → "Zone 결정 방법"으로 변경, 체크박스
행을 콤보박스 행으로 교체. 툴팁 3줄로 각 모드 설명(기존 체크박스 툴팁 2줄을 3줄로 확장).

라디오 버튼 3개 대신 콤보박스를 선택한 이유: 좌측 패널 폭이 180~260px로 좁게 고정돼
있어(`left.setMinimumWidth(180); setMaximumWidth(260)`) 라디오 3개 세로 배치보다
콤보박스 1줄이 공간 효율적이고, 기존 체크박스와 동일한 "1줄짜리 컨트롤" 자리를
그대로 대체할 수 있다.

### 모드별 동작 차이 — `_on_batch_process()`의 기존 `apply_to_all` 분기 그대로 재사용

```python
mode = self._mode_combo.currentData()
apply_to_all = mode != "per_image"   # apply_all·apply_all_edit 둘 다 스케일 적용, per_image만 개별 자동검출
```

기존 원 배치 로직(`_scale_circles()` vs 개별 `detect_circles()`)은 손대지 않는다 — 이미
정확히 이 두 갈래로 나�뉘어 있었다(로드맵 확인 완료).

### 판단 1 — "자동 저장"의 정확한 의미와 트리거 지점

라벨링 탭(`annotation_canvas.py`)의 패턴을 그대로 조사했다: `_save_timer`(500ms
디바운스 `QTimer`)가 편집마다 재시작되고, `load_image()`가 이미지 전환 시
`_save_timer.isActive()`면 타이머를 멈추고 `_do_save(sync=True)`로 **즉시 동기 flush**한
뒤 다음 이미지를 연다(디스크 쓰기 경쟁 방지, BUG-012 교훈).

**Zone 탭엔 디바운스가 필요 없다** — 라벨링 탭의 디바운스는 "디스크 I/O 빈도를
줄이기 위한 것"인데, Zone 탭은 디스크에 쓰지 않고 파이썬 dict에 대입만 하므로
비용이 사실상 0에 가깝다(원 3~5개 튜플 + 정수 집합 + 스트로크 좌표 리스트).
따라서 라벨링 탭처럼 "타이머 + 이미지 전환 시 flush" 2단계 대신, **이미지 전환
시점에만 1회 flush**하면 충분하다(디바운스 타이머 자체를 추가하지 않음 — YAGNI,
필요해지면 나중에 추가).

```python
def _on_list_image_selected(self, path: Path) -> None:
    if self._image_path is not None and self._image_path != path:
        self._image_states[self._image_path] = self._canvas.get_state()   # 자동 저장
    self._image_path = path
    ... (기존 이미지 로드 로직 그대로) ...
    if self._last_result is not None:
        self._setup_target_classes(self._last_result)   # 이 호출이 set_blob_data()를 거쳐
                                                          # circles/undo/manual_strokes를 초기화한다
    cached = self._image_states.get(path)
    if cached is not None:
        self._canvas.set_state(cached)   # 반드시 _setup_target_classes 이후에 호출
    else:
        self._canvas.clear_circles()     # 기존 동작 그대로(캐시 없으면 빈 캔버스)
```

**순서 주의(구현 시 반드시 지킬 것)**: `_setup_target_classes()` → 내부적으로
`_on_target_changed()` → `set_blob_data()`를 호출하는데, `set_blob_data()`는 원/블랍삭제
이력/수동스트로크/undo스택을 **전부 초기화**한다(타겟 클래스 전환 시 라벨 id가
달라지므로 기존 정책). 캐시 복원(`set_state()`)은 반드시 이 초기화 **이후**에 호출해야
`set_blob_data()`가 방금 복원한 상태를 다시 지워버리는 사고가 나지 않는다.

**저장 트리거를 "이미지 전환 시점" 하나로만 좁힌 근거**: 원 편집/블랍삭제/브러시
스트로크는 전부 `circles_changed`/`blob_deleted`/`erase_changed` 시그널로 표면화되므로,
더 안전하게 하려면 이 3개 시그널에도 즉시 flush를 걸 수 있다(비용은 여전히 무시할
수준). 다만 "이미지 전환 시에만 저장"으로도 데이터 유실 시나리오가 없음(같은 세션
안에서 캔버스 상태와 캐시는 항상 이미지 전환 순간에만 동기화되면 충분 — 앱 크래시
시 유실은 "세션 메모리"라는 저장 범위 결정 자체가 이미 내포한 리스크이지 이 트리거
설계의 결함이 아님). **구현 자유도로 남김** — 두 방식 다 스펙 위반 아님, 구현
에이전트가 더 단순한 쪽(전환 시 1회)을 기본으로 하되 회귀 없으면 무방.

### 판단 2 — 모드별 "새 이미지 첫 방문" 시 초기 상태

`_image_states`에 캐시가 없는 이미지를 처음 열면(배치를 아직 안 돌렸거나, 배치
대상에서 제외된 이미지) **모든 모드에서 동일하게 빈 캔버스로 시작**한다
(`clear_circles()`, 기존 동작 그대로) — "모드 2/3choose에서 최초 방문 시 자동으로
기준원을 즉석 스케일 적용"하는 기능은 **만들지 않는다**(YAGNI). 이유: 사용자 요청
원문이 "일괄 적용을 **먼저 하되**, 그 후 이미지별로 수정"이므로, 배치 버튼을 먼저
누르는 것이 모드 2/3의 전제 조건이다 — 배치 버튼이 곧 "각 이미지에 초기 원을
채워 넣는" 단계이지, 이미지 목록 클릭이 그 역할을 대신할 필요는 없다. 이렇게 하면
`_on_list_image_selected()`에 모드별 분기가 전혀 필요 없어져(캐시 유무만 확인) 코드가
단순해진다.

### 판단 3 — `_on_batch_process()` 필수 보강 (자동 저장이 실제로 동작하려면 선행돼야 함)

현재 `_on_batch_process()`는 계산한 `InferenceResult`를 버리고(`self._results`에 쓰지
않음), `removed_blob_ids`/`manual_strokes`도 반영하지 않는다. 두 가지 다 모드 2/3가
정상 동작하려면 반드시 고쳐야 하는 선행 조건이다(신규 기능이 아니라 기존 함수의
숨은 갭을 메우는 root-cause 보강):

```python
for i, img_path in enumerate(targets):
    ...
    if img_path in self._results:
        result = self._results[img_path]          # 이미 추론된 이미지는 재추론하지 않음(신규 발견 효율 개선)
    elif img_path == self._image_path and self._last_result is not None:
        result = self._last_result
    else:
        result = engine.run(...)                    # 기존 그대로
        self._results[img_path] = result             # ★ 신규 — 캐시에 반드시 저장
    h, w = result.raw_class_map.shape                 # ★ Image.open() 불필요(캐시 히트 시 파일 재오픈 안 함)

    ... circles 계산(기존 apply_to_all/개별 검출 분기 그대로) ...

    target_mask = result.class_map == target_cid
    if mode != "apply_all":                           # ★ 신규 — 모드 2/3만 캐시에 기록
        self._image_states[img_path] = {
            "circles": [(idx, cx, cy, r) for idx, (cx, cy, r) in enumerate(circles)],
            "removed_blob_ids": set(),
            "erase_strokes": [],
            "manual_strokes": [],
        }
    ... 존 계산/rows.append(...) 기존 그대로 ...
```

`self._results[img_path] = result`를 채워두면 이후 사용자가 목록에서 그 이미지를
클릭했을 때 `_on_list_image_selected()`의 `self._last_result = self._results.get(path)`
조회가 성공해 오버레이·타겟 클래스·블랍 라벨맵이 정상적으로 다시 구성된다(이게
안 되면 캐시된 원/편집을 복원해도 화면엔 아무 오버레이도 안 뜨는 반쪽짜리 기능이
된다) — **이 보강이 빠지면 모드 2/3 전체가 실질적으로 동작하지 않는다.**

### 판단 4 — 배치 리포트가 개별 수정을 반영하게 하기 (`zone_metrics.py` 순수 함수 추출)

`ZoneCanvas.apply_manual_strokes()`는 현재 인스턴스 메서드로 `self._manual_strokes`에
묶여 있어, 화면에 표시되지 않은(현재 캔버스에 없는) 다른 이미지의 캐시된 상태에는
적용할 수 없다. `zone_metrics.py`에 순수 함수로 승격한다(신규 로직 없음, 그대로 이동):

```python
# zone_metrics.py
def apply_manual_strokes(mask: np.ndarray, manual_strokes: list[tuple[bool, list[tuple[float, float, float]]]]) -> np.ndarray:
    """수동 그리기/지우기를 시간순으로 적용(마지막 스트로크 우선). disk_mask() 재사용."""
    result = mask.copy()
    for draw, stroke in manual_strokes:
        stroke_mask = np.zeros(mask.shape, dtype=bool)
        for cx, cy, r in stroke:
            stroke_mask |= disk_mask(cx, cy, r, mask.shape)
        result[stroke_mask] = draw
    return result
```

`ZoneCanvas.apply_manual_strokes()`는 `return zone_metrics.apply_manual_strokes(mask, self._manual_strokes)`
호출로 얇아지는 래퍼가 된다(현재 화면 캔버스 용도, API 이름/시그니처 불변 —
`zone_analysis_tab._current_target_mask()` 호출부 무변경).

`_on_batch_process()`가 (모드 2/3에서, 재방문해 사용자가 편집을 마친 이미지에 한해)
캐시된 `removed_blob_ids`/`manual_strokes`를 반영하려면:

```python
state = self._image_states.get(img_path)
if state is not None:
    if state["removed_blob_ids"]:
        labels, _ = compute_blob_labels(target_mask)
        target_mask = target_mask & ~np.isin(labels, list(state["removed_blob_ids"]))
    target_mask = zone_metrics.apply_manual_strokes(target_mask, state["manual_strokes"])
```

**주의**: 이 캐시 조회는 "이번 배치 실행 이전에 이미 사용자가 그 이미지를 열어 수정해둔
경우"에만 의미가 있다 — 방금 판단 3에서 이 배치 루프 자신이 막 채워넣은 신선한(원만
있고 편집 없는) 상태와 뒤섞이지 않도록, **원 계산(circles) 뒤 → state 갱신(판단3) 전에**
이 반영 코드를 넣어야 한다(즉 "이전 캐시를 읽어 마스크에 반영" → "새 circles로 캐시를
덮어쓰기"의 순서 — 판단3 코드블록에서 캐시 쓰기 줄보다 먼저 실행되도록 배치).

### 판단 5 — 알려진 한계(이번 라운드 범위 밖으로 명시)

- **타겟 클래스를 바꾸면 캐시된 블랍삭제/브러시 편집은 stale해질 수 있다** — 블랍
  라벨 id는 타겟 마스크에 종속적이라, 클래스 A로 편집해둔 `removed_blob_ids`를 클래스
  B 마스크에 그대로 적용하면 엉뚱한 픽셀이 제외될 수 있다. 원(circle) 캐시는 좌표
  기반이라 타겟 클래스와 무관해 안전하다. ponytail: 타겟 클래스를 자주 바꾸지 않는
  일반 워크플로우를 전제로 한 단순화 — 실사용에서 문제가 확인되면 타겟 클래스 변경
  시 `_image_states`의 `removed_blob_ids`/`manual_strokes`만 선택적으로 무효화(원은
  유지)하는 후속 보강을 추가한다.
- **모드 1("일괄 적용")에서도 사용자가 이미지를 열어 직접 원을 편집하면 그 편집은
  캐시·복원된다** — `_on_list_image_selected()`의 "이미지 전환 시 flush" 로직은 모드와
  무관하게 항상 동작한다(캐시 쓰기 자체를 모드로 막지 않음, 판단1 참고). 이는 스펙
  위반이 아니라 "편집한 내용은 절대 잃지 않는다"는 더 안전한 상위 원칙을 단순한
  코드로 구현한 결과다 — 다만 모드 1의 취지("순수 일괄 적용, 개별 수정 불필요")와는
  다소 어긋날 수 있어 명시해둔다. 엄격하게 막고 싶다면 `_on_list_image_selected()`의
  flush 줄에 `if mode != "apply_all"` 가드 1줄만 추가하면 되므로, 구현 시 리더/사용자
  선호에 따라 선택(기본안은 "항상 flush", 더 단순함).

## 결정 필요 — `docs/decisions-needed.md` 등록 대상

**저장 범위: 세션 메모리 vs 디스크 영속화.** 이 도구는 "완전 독립 도구"(프로젝트
시스템 미사용, 이미지·체크포인트를 임의 경로에서 직접 여는 방식) 원칙이 있어,
디스크에 저장한다면 프로젝트 디렉토리 같은 고정 위치가 없다 — 이미지 옆
사이드카(`{image_stem}.zone.json`) 또는 사용자가 지정하는 별도 폴더 중 하나를 새로
설계해야 하는 무거운 결정이다.

**기본안(권장)**: 이번 라운드는 **세션(앱 실행 중) 메모리 유지로 구현** —
`ZoneAnalysisTab._image_states: dict[Path, dict]`, 앱을 끄면 사라진다. 근거: (1) 사용자
원문 "다른 이미지로 넘어갈 때 자동 저장"은 "이미지 전환 중 잃지 않는다"는 워크플로우
불편 해소가 핵심이지 "앱을 재시작해도 남아있어야 한다"는 요구가 명시되지 않았다.
(2) 디스크 사이드카를 도입하면 "완전 독립 도구" 원칙과 파일 배치 정책을 새로 정의해야
해 이번 라운드 스코프가 크게 불어난다(YAGNI). (3) 세션 메모리만으로도 요청 A의 3
시나리오(모드1/2/3)와 요청B-이슈2(추론 결과 변경 후 이미지 전환 시 유실)가 전부
해결된다 — "저장 불가" 불만의 본질은 "전환하면 사라진다"이지 "앱 재시작 후에도
있어야 한다"가 아니라고 판단.

**디스크 영속화는 향후 확장 후보로 분리** — 실사용 중 "앱을 재시작했더니 그동안 한
편집이 다 날아갔다"는 불만이 실제로 접수되면 그때 사이드카 파일 설계(어디에/어떤
포맷으로 저장할지)를 별도 라운드로 논의한다.

## 라운드 분할 (의존관계 고려, 작게 쪼갬)

| 라운드 | 내용 | 파일 | 의존관계 |
|---|---|---|---|
| **R-ZONE-1** | 이슈1 — 브러시 스트로크 rasterize-on-commit 캐시 | `app/widgets/zone_canvas.py` | 없음, 최우선 권장(다른 라운드가 `zone_canvas.py`의 undo/manual_strokes 코드를 추가로 건드리므로 먼저 안정화) |
| **R-ZONE-2** | 이슈3 — GPU 미가용 경고(`prompt_gpu_availability`) 2곳 추가 | `app/tabs/zone_analysis_tab.py`(`_on_run`/`_on_batch_process`) | 없음, R-ZONE-1과 파일이 달라 병렬 가능 |
| **R-ZONE-3** | 요청A(3모드+자동저장) + 이슈2(통합 해결) — `get_state`/`set_state`(+undo 리팩터링), `zone_metrics.apply_manual_strokes()` 추출, 3-way 콤보, `_on_list_image_selected`/`_on_batch_process` 보강(캐시 필수 수정 포함) | `app/widgets/zone_canvas.py`, `app/core/zone_metrics.py`, `app/tabs/zone_analysis_tab.py` | R-ZONE-1 완료 후 착수 권장(`zone_canvas.py` 동일 파일, 스트로크 오버레이 캐시의 `_rebuild_stroke_overlay()`를 `set_state()`가 호출해야 하므로 순서상 R-ZONE-1의 API가 먼저 있어야 함) |

R-ZONE-2는 R-ZONE-1/3과 파일이 겹치지 않는 함수라 아무 때나 병렬 가능하지만, diff가
가장 작아 먼저 처리해도 무방(권장 순서: 1 → 2 → 3, 리더가 조율).

## 신규/수정 파일 요약

- 신규 파일: 없음.
- 수정: `app/widgets/zone_canvas.py`(R-ZONE-1: 스트로크 캐시, R-ZONE-3: `get_state`/
  `set_state`, `undo()` 리팩터링), `app/core/zone_metrics.py`(R-ZONE-3:
  `apply_manual_strokes()` 순수 함수 추가), `app/tabs/zone_analysis_tab.py`
  (R-ZONE-2: GPU 경고 2곳, R-ZONE-3: 3-way 콤보 UI + `_image_states` 캐시 +
  `_on_list_image_selected`/`_on_batch_process` 보강).
- 테스트: 기존 `tests/test_zone_github_13_14.py`(`_scale_circles` 관련) 회귀 확인 필요
  (R-ZONE-3가 `_on_batch_process`를 수정하므로). 신규 테스트는 구현 라운드에서
  `zone_metrics.py` self-check(`__main__` 블록)에 `apply_manual_strokes()` 케이스 1개
  추가 권장(관례상 매 신규 순수 함수마다 self-check 유지).
