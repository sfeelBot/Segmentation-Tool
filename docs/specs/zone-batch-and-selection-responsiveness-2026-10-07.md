# 상/하부 분석 탭 — 일괄 적용 응답없음 + 이미지 선택 딜레이 (2026-10-07 VOC)

## 사용자 요구사항

> "상/하부 분석탭에서 영역 지정 후 일괄 적용 시 응답없음 버그가 간헐적으로 발생하고,
> 이미지 선택할 때마다 딜레이가 있어. 이 문제를 해결해주고 검증 에이전트는 조금더
> 여러가지 테스트를 마친다음 사용자가 불편사항이 없도록 검증할 수 있도록 해줘."

두 가지 독립적인 성능 문제. 둘 다 `app/tabs/zone_analysis_tab.py` 안에 있지만 서로
다른 함수 영역이다. 리더가 사전 코드 조사로 원인을 1차 특정해 넘겨줬고, 이번 기획
세션에서 실제 코드(`engine.refilter`/`_compute_blobs_and_filter`/`_colorize_and_blend`)
와 기존 스펙(GH#32, R-ZONE-3)의 실측 벤치마크를 대조해 근거를 보강했다. 기능 변경은
없다 — 3가지 배치 모드, 사이드카 자동 저장, 취소 버튼, 진행률 표시, 결과 다이얼로그
전부 그대로 유지.

## 문제 1 — 이미지 선택 시 딜레이

### 확정 원인

`_on_list_image_selected()`(`zone_analysis_tab.py:671`)가 캐시된 추론 결과
(`self._results.get(path)`)가 있는 이미지를 클릭하면 매번
`_setup_target_classes()`(917) → `_on_target_changed()`(962)를 호출하고, 이 함수가
**메인 스레드에서 매번 처음부터** 다음을 재계산한다:

1. `engine.refilter(raw_class_map, confidence_map, self._image_path, ...)`
   (`inference_engine.py:251`) 내부에서:
   - `Image.open(str(image_path)).convert("RGB")` — **원본 이미지를 디스크에서
     다시 디코딩**한다. GH#32 스펙 실측: 5,472×3,648 BMP PIL RGB decode
     105.3~120.1ms(`docs/specs/zone-github-32-batch-bottleneck-2026-08-31.md` "장별
     적용의 원본 재개방" 절). 같은 해상도라 이미지 선택 경로에도 그대로 적용된다.
   - `_compute_blobs_and_filter()`(`inference_engine.py:476`) — non-background
     클래스마다 원본 해상도 `cv2.connectedComponentsWithStats()` 1회(현재 탭은
     배경+타겟 1개뿐이라 보통 1회, 그래도 원본 해상도 전체).
   - `_colorize_and_blend()`(569) — `_MAX_OVERLAY_DIM` 다운스케일이 이미 적용돼
     있어(R5, 2026-08-19) 이 부분 자체는 상대적으로 가볍다.
2. `compute_blob_labels(target_mask)`(`zone_metrics.py:112`, 원본 해상도
   `cv2.connectedComponentsWithStats`) — **1번의 `_compute_blobs_and_filter()`와
   별개로 한 번 더** 같은 종류의 연결요소 분석을 돌린다(블랍 클릭삭제/Excel 집계용
   라벨맵이 필요해서 별도 호출하는 것이지만, 결과적으로 같은 이미지에 대해 cv2
   connected-components를 두 번 수행하는 중복이다).
3. `_recompute_zones()`(1181) → `_compute_zone_percentages()`/
   `_compute_zone_blob_rows()` 각각이 `zones_from_circles()`를 **따로** 호출(중복)
   + `zone_stats()`/`zone_blob_stats()`. GH#32 스펙 실측: 원 3개·존 4개 기준
   `zones_from_circles`+존 4개 `zone_stats` 합계 218.4~235.2ms.

같은 이미지를 다시 클릭할 때마다(타겟 클래스·threshold·원이 전혀 안 바뀌었어도)
위 3단계 전부를 처음부터 다시 돈다 — 디스크 재디코딩 + cv2 connected-components
중복 호출 + zones_from_circles 중복 호출까지 겹쳐, 대형 이미지에서는 눈에 보이는
딜레이(수백 ms~1초 이상)가 된다.

### 수정 방향 — 캐싱 (스레딩 불필요)

리더 가설대로 **캐싱만으로 충분**하다고 판단한다. 스레딩이 필요 없는 이유:

- 이 경로는 "같은 입력에 대해 똑같은 출력을 반복 계산"하는 순수 캐시 미스 문제다 —
  계산 자체를 다른 스레드로 옮겨도 똑같이 반복 계산하면서 단지 메인 스레드를
  블로킹하지 않을 뿐이고(체감 끊김은 줄어도 CPU/디스크 낭비와 지연 자체는 남음),
  캐싱하면 반복 계산 자체가 사라져 더 근본적이고 더 적은 코드로 해결된다(YAGNI
  관점에서 "계산을 안 하는 것"이 "계산을 비동기로 미루는 것"보다 항상 우선).
- 타겟 클래스/threshold는 일반 워크플로우에서 자주 바뀌지 않는다(한 체크포인트로
  죽 훑어보는 게 기본 사용 패턴) — 캐시 적중률이 높을 것으로 예상된다.

**설계**: `ZoneAnalysisTab.__init__`에 신규 필드
`self._target_cache: dict[Path, tuple[tuple, InferenceResult, np.ndarray, np.ndarray]]`
(키=이미지 경로, 값=`((target_cid, min_confidence, min_pixel_size), 리필터링된
InferenceResult, blob_labels, blob_stats)`). `_on_target_changed()`를 다음처럼 바꾼다:

```python
def _on_target_changed(self) -> None:
    if self._last_result is None or not self._detected_ids:
        return
    cid, name = ...  # 기존 그대로(단일/다중 분기)
    classes = [...]  # 기존 그대로
    self._target_classes = classes
    min_confidence = self._conf_slider.value() / 100.0
    min_pixel_size = self._min_px_spin.value()
    cache_key = (cid, min_confidence, min_pixel_size)
    cached = self._target_cache.get(self._image_path)
    try:
        if cached is not None and cached[0] == cache_key:
            _, result, labels, stats = cached            # ★ 캐시 적중 — refilter/compute_blob_labels 스킵
        else:
            result = engine.refilter(
                self._last_result.raw_class_map, self._last_result.confidence_map,
                self._image_path, min_confidence=min_confidence,
                min_pixel_size=min_pixel_size, opacity=0.5, classes=classes,
            )
            target_mask = result.class_map == cid
            labels, stats, _ = compute_blob_labels(target_mask)
            self._target_cache[self._image_path] = (cache_key, result, labels, stats)  # ★ 신규 — 다음 재방문을 위해 저장
        self._last_result = result
        self._target_class_id = cid
        self._show_overlay_state()
        self._canvas.set_blob_data(labels, stats)
        ... (이하 기존 그대로: highlight 초기화, 액션 활성화, _update_undo_button_state, _recompute_zones)
    except Exception as exc:
        log.exception("존 분석 타겟 클래스 재필터링 실패")
        QMessageBox.critical(self, "재필터링 오류", str(exc))
```

`self._last_result.raw_class_map`/`.confidence_map`은 `_on_list_image_selected()`가
`self._last_result = self._results.get(path)`(추론 당시의 원본, threshold 미적용
raw 결과)로 미리 세팅해두므로 캐시 적중/미스와 무관하게 항상 올바른 입력 소스다
(`engine.refilter()`가 반환하는 `InferenceResult.raw_class_map`도 입력을 그대로
보존하므로 이미 캐시된 결과를 재사용해도 다음 refilter의 입력이 깨지지 않는다).

**무효화 지점** (전부 기존에 이미 있는 "결과를 지우는" 지점에 한 줄 추가하는 수준):

- `_on_run()`(839행대) — `self._results.clear()` 바로 옆에
  `self._target_cache.clear()` 추가(새 추론 전체 세션이므로 이전 캐시는 전부
  무의미).
- `_on_images_removed()`(650행대) — `self._results.pop(p, None)` 옆에
  `self._target_cache.pop(p, None)` 추가.
- 타겟 클래스/threshold가 바뀌면 `cache_key`가 달라지므로 **자동으로** 캐시 미스가
  나 재계산되고(새 키로 다시 저장됨), 옛 키 캐시는 그대로 남아도 동작 정확성에
  영향 없음(다음에 그 조합으로 돌아오면 다시 적중) — 별도 무효화 코드 불필요.

**남는 비용(의도적으로 수정 범위 밖)**: 캐시 적중 시에도 `_recompute_zones()`(원
목록 렌더/하이라이트 복원에 필요, 매번 호출 자체는 스킵 불가)는 여전히
`zones_from_circles()`를 2번 중복 호출한다(`_compute_zone_percentages()`/
`_compute_zone_blob_rows()` 각자 호출). 이건 캐시 적중 후에도 남는 상대적으로 가벼운
잔여 비용(실측 218ms 수준, GH#32 스펙)이다. 이번 라운드는 "디스크 재디코딩 +
cv2 connected-components 중복 호출"이라는 더 큰 비용(이게 체감 딜레이의 주원인으로
추정)만 없애는 것으로 범위를 좁힌다(YAGNI) — 1차 적용 후 실측해도 체감 딜레이가
남아있으면, `zones_from_circles()` 중복 호출 통합(헬퍼 하나로 합쳐 1번만 계산)을
2차로 추가할 수 있다(별도 라운드 불필요할 만큼 작은 추가 diff).

### 영향 파일

`app/tabs/zone_analysis_tab.py` 단독(`__init__`/`_on_target_changed`/`_on_run`/
`_on_images_removed`). 신규 파일 없음, `zone_metrics.py`/`inference_engine.py`
무변경.

## 문제 2 — 일괄 적용 간헐적 응답없음

### 확정 원인

`_ZoneBatchWorker`(98행대, QThread)는 BUG-030 수정(QA.md Closed)으로 이미 CUDA
추론만 워커 스레드에서 수행하도록 격리돼 있다 — `engine.prepare_inference()` 1회 +
`engine.run_sliding_window(..., prepared=prepared)`만 워커 안에서 실행하고, 결과를
`image_inferred` 시그널로 메인 스레드에 넘긴다.

문제는 그 수신 슬롯 `_on_batch_image_inferred()`(1537행대, **메인 스레드**)가 이미지
1장당 다음을 **동기로** 수행한다는 것:

- (per_image 모드만) `Image.open(str(path))` 재디코딩 + `detect_circles()`.
- `zstate.load_state(path)`(사이드카 조회).
- `_compute_zone_rows()`(158행대) — `compute_blob_labels()`(cv2
  connectedComponentsWithStats, 원본 해상도) + `zones_from_circles()` +
  `zone_stats()`(존 개수만큼) + `zone_blob_stats()`.
- `zstate.save_state()`(사이드카 디스크 쓰기).

`QProgressDialog.setValue()`가 내부적으로 `processEvents()`를 호출해 큐에 쌓인 이벤트
일부를 펌핑하긴 하지만, 그건 이미지 N과 N+1 **사이**에만 기회가 생기는 것이고, 이미지
1장 안의 실제 cv2/numpy 계산 구간 자체는 여전히 메인 스레드를 통째로 점유한다. GH#32
스펙 실측(캐시 적중 상태, 원 3개·존 4개 기준)으로 `zones_from_circles`+`zone_stats`만
해도 장당 약 218~235ms, `compute_blob_labels`(동일 해상도 cv2 connected-components)
+`zone_blob_stats`까지 합치면 이보다 더 크다 — 이미지 해상도가 크거나 블랍이 많은
장이 섞이면 그 한 장의 블로킹 구간이 수백 ms~1초 이상으로 길어져 Windows가 "응답
없음"으로 표시할 수 있다. 장마다 걸리는 시간이 다르므로(블랍 수·존 개수·per_image
모드의 원검출 성공/실패에 따라) "간헐적"으로 느껴진다는 사용자 표현과 일치한다.

### BUG-030 제약 재확인 — 두 번째 워커 스레드는 안전한가

QA.md BUG-030 전문을 직접 읽고 재확인했다: 격리된 크래시 트리거는 정확히
**"① 다른 스레드에서의 실제 CUDA 추론 직후, ② 바로 같은 스레드 안에서 cv2
(`compute_blob_labels`=`cv2.connectedComponentsWithStats`) 무거운 후처리를 이어서
실행하는 조합"**이다(QA.md BUG-030 "근본 원인" 칸: "다른 스레드의 실 CUDA 추론 직후
같은 스레드에서 cv2 후처리"가 유일한 트리거, 3개 격리 실험으로 결정적으로 좁혔다고
명시). 즉 트리거 조건은 **"CUDA와 cv2가 같은 스레드에 있는가"**이고, "CUDA를 호출한
스레드와 cv2를 호출한 스레드가 서로 다른 스레드인가"는 트리거와 무관하다 — 오히려
현재의 안전한 구조(워커=CUDA만, 메인 스레드=cv2)가 "다른 두 스레드"라는 점에서 이미
이 가설을 실증하고 있다(메인 스레드도 cv2 호출 시점엔 자신이 직접 CUDA를 호출한
적이 없는 "CUDA 비호출 스레드"라는 점은 동일).

따라서 **cv2 후처리를 메인 스레드에서 "또 다른" 전용 QThread(CUDA를 전혀 호출하지
않는 스레드)로 옮기는 것은 BUG-030 트리거 조건을 만들지 않는다** — 그 스레드는
`engine.prepare_inference`/`engine.run_sliding_window`를 절대 호출하지 않고 순수
cv2/numpy/디스크 I/O만 수행하면 된다. 이는 리더의 가설과 일치하며, 기존 수정이
남긴 교훈(worker는 반드시 "하나의 책무"만 가져야 한다)과도 정합적이다.

### 설계 — 전용 후처리 QThread (producer-consumer, 큐 기반)

`QTimer.singleShot(0, ...)`로 메인 스레드 이벤트 루프에 양보하며 처리하는 방식은
**기각**한다 — 이미지 1장의 cv2 계산 자체가 이미 300ms~1초 이상 걸리는 단일
블로킹 단위이므로(위 실측), 이미지 "사이"에서만 양보해봐야 이미지 "안"에서의
블로킹은 그대로 남는다. 실제로 메인 스레드를 비우려면 그 계산을 **진짜 다른
스레드**로 옮겨야 한다(GH#32 스펙의 기존 수용 기준 "GUI 이벤트 무응답 구간이 200ms를
넘지 않는다"를 이번 라운드도 그대로 승계해 지킨다).

신규 클래스 `_ZoneBatchPostWorker(QThread)`(`zone_analysis_tab.py`, 기존
`_ZoneInferenceWorker`/`_ZoneBatchWorker`와 같은 파일에 공존 — 이 탭의 기존 관례가
워커 클래스를 탭 파일에 직접 둔다, 신규 파일 불필요):

```python
class _ZoneBatchPostWorker(QThread):
    """`_ZoneBatchWorker`가 넘긴 raw InferenceResult를 받아 cv2/numpy 존·블랍
    후처리 + 사이드카 저장을 전담하는 두 번째 워커. CUDA를 절대 호출하지 않는다
    (BUG-030 제약 — "CUDA 직후 같은 스레드 cv2"만 위험하므로, 이 스레드는 애초에
    CUDA를 호출하지 않아 그 조합 자체가 성립하지 않는다)."""
    row_computed = pyqtSignal(object, object, object, int, int)  # path, rows, blob_rows, done, total
    progress = pyqtSignal(object, str, object, int, int)

    def __init__(self, mode, circles_ref, ref_size, sensitivity, target_cid) -> None:
        super().__init__()
        self._queue: queue.Queue = queue.Queue()
        self._mode = mode
        self._circles_ref = circles_ref
        self._ref_size = ref_size
        self._sensitivity = sensitivity
        self._target_cid = target_cid

    def enqueue(self, path: Path, result: InferenceResult, done: int, total: int) -> None:
        self._queue.put((path, result, done, total))

    def close(self) -> None:
        self._queue.put(None)   # sentinel — 더 들어올 항목이 없음을 알림

    def run(self) -> None:
        while True:
            item = self._queue.get()
            if item is None or self.isInterruptionRequested():
                break
            path, result, done, total = item
            try:
                # 기존 _on_batch_image_inferred() 본문(1537행대)을 그대로 이전:
                # per_image 모드 재디코딩+detect_circles, zstate.load_state,
                # _compute_zone_rows(), zstate.save_state() — UI 위젯은 절대
                # 건드리지 않고(QThread 규약), rows/blob_rows/상태만 계산.
                ...
                self.row_computed.emit(path, rows, blob_rows, done, total)
            except Exception as exc:
                self.progress.emit(path, "error", str(exc), done, total)
```

**흐름**:

1. `_on_batch_process()`가 `_ZoneBatchWorker`(CUDA 전용, 기존 그대로)와
   `_ZoneBatchPostWorker`(신규, cv2 전용)를 **둘 다** 생성하고 둘 다 `.start()`한다.
2. `_ZoneBatchWorker.image_inferred` 시그널의 연결 대상을 메인 스레드의
   `_on_batch_image_inferred()`(무거운 계산) 대신 **가벼운 중계 슬롯**
   `_on_batch_image_ready()`로 바꾼다 — 이 슬롯은 `self._post_worker.enqueue(path,
   result, done, total)` 한 줄만 하고 즉시 반환한다(메인 스레드 블로킹 없음).
3. `_ZoneBatchWorker.finished`가 오면 `self._post_worker.close()`를 호출해 더 이상
   들어올 항목이 없음을 알린다(CUDA가 다 끝났다는 뜻, 큐에 남은 항목은 계속
   처리됨).
4. `_ZoneBatchPostWorker.row_computed` 시그널은 메인 스레드의 (기존
   `_on_batch_image_inferred()`에서 떼어낸) **UI 갱신만 담당하는 축소판**
   `_on_batch_row_computed()`로 연결 — `self._results[path]=result`,
   `self._batch_rows.extend(rows)`, `self._img_list.set_item_status(...)`,
   진행률 다이얼로그 갱신. 이 부분은 전부 가벼운 dict/list 연산+Qt 위젯 호출이라
   메인 스레드에서 수행해도 문제없다(BUG-030 제약은 cv2 계산에만 적용되지, dict에
   `append`하는 것과는 무관).
5. `_ZoneBatchPostWorker.finished`(큐가 다 비고 sentinel까지 처리됨)가 와야
   `_on_batch_finished()`(진행 다이얼로그 닫기 + 결과 다이얼로그 오픈)를 호출한다
   — **`_ZoneBatchWorker.finished`가 아니라 `_ZoneBatchPostWorker.finished`를
   기준으로 삼아야 한다**(CUDA가 먼저 끝나도 cv2 후처리 큐가 아직 남아있을 수
   있으므로, 기존 BUG-030 수정이 "`QThread.finished`는 큐드 시그널 처리 후 도착"
   원칙을 썼던 것과 같은 이유로 최종 완료 판정은 더 늦게 끝나는 쪽을 기준으로 함).

**취소**: `QProgressDialog.canceled`가 현재 `self._batch_worker.requestInterruption`
하나에만 연결돼 있는데, 두 워커 모두에 연결해야 한다
(`self._post_worker.requestInterruption` 추가) — CUDA 워커가 멈춰도 cv2 워커가 큐에
쌓인 나머지 항목을 계속 처리하면 "취소"가 사용자 기대보다 늦게 끝난다. `_queue.get()`이
블로킹 호출이라 `isInterruptionRequested()`를 큐가 빈 상태에서 즉시 체크하지 못하는
문제는, `close()`가 CUDA 종료 시 반드시 sentinel(`None`)을 넣어주므로 cv2 워커가
무한 대기하지 않는다(취소 시에도 `_ZoneBatchWorker.finished`는 정상 발화하므로
`close()` 호출 경로는 취소 여부와 무관하게 항상 실행됨 — 추가 배선 불필요).

**순서 보존**: 큐는 FIFO이고 CUDA 워커가 `enqueue()` 순서대로(이미지 리스트 순서)
항목을 넣으므로, cv2 워커도 같은 순서로 처리해 `self._batch_rows`/사이드카 쓰기
순서가 기존과 동일하게 유지된다(동시성 레이스 없음 — cv2 워커는 단일 스레드에서
한 번에 하나씩만 처리).

**메모리**: 기존에도 CUDA 결과(raw `InferenceResult`)가 큐/변수에 잠깐 머무는 구조
자체는 그대로다(GH#32 스펙이 이미 "`_results`를 무제한 보관하지 않는다"는 별도
결정을 내려뒀고 이번 라운드가 그 결정을 뒤집지 않음) — 큐 깊이가 "CUDA가 cv2보다
빠른 경우"에만 늘어날 수 있는데, 일반적으로 모델 forward pass(수백 ms~수 초, GPU 포함)가
cv2 후처리(수백 ms)보다 느리거나 비슷한 수준이라 큐가 무한정 쌓일 위험은 낮다(실측
없이 가정이므로, 검증 시 대량 이미지 배치에서 큐 깊이/메모리를 관찰 항목으로 포함).

### 영향 파일

`app/tabs/zone_analysis_tab.py` 단독 — `_ZoneBatchWorker`는 변경 없음(이미 CUDA
전용), 신규 `_ZoneBatchPostWorker` 클래스 추가, `_on_batch_process()`(두 워커
생성/연결/시작), `_on_batch_image_inferred()`의 본문을 `_ZoneBatchPostWorker.run()`
안으로 이전(메인 스레드엔 가벼운 `_on_batch_row_computed()`만 남김), `_on_batch_finished()`
트리거를 `_post_worker.finished`로 변경. `app/core/zone_metrics.py`/
`app/core/zone_state_store.py`/`app/core/inference_engine.py` 무변경(순수 함수
재사용만, 어느 스레드에서 호출하든 동일하게 동작).

## 라운드 분할

두 문제 모두 같은 파일(`app/tabs/zone_analysis_tab.py`) 안이지만 **서로 다른 함수
영역**이다. 진짜 동시 편집(같은 파일에 두 에이전트가 동시에 diff)은 병합 충돌
위험이 있으므로, 완전한 동시 병렬보다 **순차 진행을 권장**한다 — 다만 구현
착수 전 리뷰/승인은 병렬로 진행 가능.

| 라운드 | 내용 | 영향 범위(파일 내 함수) | 리스크 | 선행조건 |
|---|---|---|---|---|
| **R-PERF-1** | 문제1 — 타겟/threshold 캐시(`_target_cache`) | `__init__`, `_on_target_changed`, `_on_run`, `_on_images_removed` | 낮음 — 순수 추가(캐시 미스 시 기존 동작과 100% 동일), 롤백 쉬움 | 없음, 먼저 진행 권장(작고 안전, 사용자가 체감하는 두 불편 중 더 자주 겪는 쪽) |
| **R-PERF-2** | 문제2 — 배치 cv2 후처리 전용 QThread 분리 | 신규 `_ZoneBatchPostWorker` 클래스, `_on_batch_process`, `_on_batch_image_inferred`→`_on_batch_row_computed`로 축소, `_on_batch_finished` | 중간 — 스레드 생명주기/취소/순서 보존을 새로 검증해야 함, BUG-030 재발 여부가 핵심 검증 대상 | R-PERF-1 완료 후 착수(같은 파일 diff 충돌 방지 — 기능적 의존관계는 없음, 순서는 병합 편의 때문) |

두 라운드 모두 완료 후 `tests/test_zone_batch_worker.py`(배치 워커 전면 영향,
반드시 갱신 필요 — 두 워커 분리에 맞춰 CUDA 전용/cv2 전용 각각 단위 테스트 +
`row_computed` 시그널 경로 통합 테스트)와 `tests/test_zone_state_persistence.py`
(사이드카 쓰기 순서/내용 회귀 확인) 재실행.

## 검증 시나리오 체크리스트 (검증 에이전트용 — "여러 가지 테스트를 마친 다음" 요청 반영)

### R-PERF-1 (선택 딜레이 캐시)

1. 같은 이미지를 3회 이상 연속 재클릭 — 2번째부터 `engine.refilter()`/
   `compute_blob_labels()`가 호출되지 않는지 확인(mock/spy 또는 `cProfile`로 확인),
   체감 지연이 1회차보다 유의미하게 짧아지는지 wall-clock으로 측정.
2. A→B→A→B 왕복(2장 교차) — 각 이미지 처음 방문 시에만 재계산, 두 번째부터는
   캐시 적중.
3. 타겟 클래스가 2개 이상인 체크포인트에서 콤보박스로 전환 후 같은 이미지를
   재방문 — 전환 전/후 각각 올바른 cid로 캐시가 분리 저장되는지(클래스 A로 봤다가
   B로 전환 후 다시 A로 돌아와도 섞이지 않고 A의 캐시가 그대로 유효한지).
4. confidence 슬라이더/픽셀크기 스핀박스를 바꾼 뒤 같은 이미지 재방문 — 새 threshold
   조합으로 캐시 미스 후 올바르게 재계산되는지, 이전 threshold로 되돌리면 다시
   캐시 적중하는지.
5. "▶ 전체 추론 실행" 재실행(새 세션) — 이전 캐시가 전부 지워지고 새 raw 결과
   기준으로 재계산되는지(오래된 캐시가 새 추론 결과와 섞이지 않는지, 특히 같은
   이미지 경로를 재사용하는 경우).
6. 이미지 목록에서 이미지 삭제 → 같은 경로로 새 이미지를 다시 추가(동일 파일명
   재사용 등 엣지케이스) 시 옛 캐시가 남아 있지 않은지.
7. 소량(5장 이하)·대량(50장+, 가능하면 100장+) 이미지 세트 각각에서 리스트를 쭉
   훑어 내리는 실사용 패턴 재현 — 체감 지연 비교(수정 전/후).
8. 해상도 비교 — `projects/nok` 류 대형(5472×3648) + 소형(예: 1024×768 합성) 둘 다
   테스트해 개선 효과가 해상도에 비례하는지 확인.
9. 기존 BUG-028(타겟 전환 재필터링 오류)·오버레이 F키 토글 회귀 없는지 재확인(캐시
   경로가 `_show_overlay_state()` 호출 흐름을 바꾸지 않았는지).

### R-PERF-2 (배치 응답없음)

10. 배치 모드 3종(일괄 적용/일괄 적용 후 수정/장별 적용) 각각 실행 — 결과
    다이얼로그 행 개수·존 퍼센티지·사이드카 내용이 수정 전과 동일한지(골든 기준값
    확보해 diff).
11. 배치 처리 도중 진행 다이얼로그를 **실제로 드래그해서 창을 이동**시켜봐서 창이
    멈추지 않고 즉시 반응하는지(응답없음 표시가 뜨는지 OS 레벨로 확인 — Windows
    "응답 없음" 타이틀바 변화 관찰, 또는 `QElapsedTimer`로 이벤트 루프 왕복시간
    측정).
12. 대량(50장+, 가능하면 100장+) 배치 — 전체 처리 중 최대 단일 블로킹 구간이
    200ms를 넘지 않는지(기존 GH#32 수용 기준 그대로 재사용) 실측.
13. 처리 도중 **취소 버튼 실제 클릭** — (a) CUDA 워커 작업 중 취소, (b) cv2 큐에
    항목이 쌓여 처리 중일 때 취소, 두 타이밍 모두에서 신속히 멈추고 그때까지 완료된
    결과만으로 결과 다이얼로그가 정상 열리는지.
14. 배치 중 임의 이미지에서 추론 또는 후처리 예외를 강제 주입 — 해당 이미지만
    "오류" 배지로 표시되고 나머지 이미지 처리는 계속되는지(기존 동작 유지 확인).
15. 기존 Zone 혼재 경고(`_confirm_existing_zones`, 3개 선택지: 전체 대체/존 없는
    이미지만/취소) 각각 배치 실행 후에도 정상 동작하는지(이번 수정과 직접 관련
    없지만 같은 함수 근처라 회귀 확인).
16. **BUG-030 재발 여부 — 최우선 검증**: 실 체크포인트+실 CUDA 환경에서 2장
    이상(가능하면 과거 크래시 재현 조건과 동일하게) 배치 처리를 반복 실행해
    `STATUS_STACK_BUFFER_OVERRUN`/`0xC0000409` 하드크래시가 재현되지 않는지 확인.
    가능하면 기존 재현 스크립트(`repro_batch_real_platform.py`, git 이력 참고)를
    새 2-워커 구조에 맞게 재사용해 "CLOSED OK" 확인.
17. 사이드카 저장 순서/내용 — 배치 완료 후 각 이미지의 `.zone.json`을 열어
    circles/removed_blob_ids/manual_strokes가 수정 전과 바이트 단위로 동일한지(큐
    기반 처리로 순서가 꼬이지 않았는지).
18. "전체 결과 보기"(8번 기능, BUG-036 관련) — 배치 처리 후 활성/비활성 이미지가
    섞인 상태에서 다이얼로그가 크래시 없이 정상 생성되는지 재확인(회귀 없음).
19. CPU 전용(GPU 없는) 환경에서도 배치가 정상 동작하는지(새 cv2 워커 스레드가
    CUDA 유무와 무관하게 항상 안전해야 함 — `prompt_gpu_availability` 경고 포함).
20. 메모리 관찰 — 50장+ 배치 처리 중 `_ZoneBatchPostWorker` 큐 깊이가 무한정
    쌓이지 않는지(작업 관리자/`psutil`로 RSS 추세 관찰, 급격한 증가가 없는지).

## 신규/수정 파일 요약

- 수정: `app/tabs/zone_analysis_tab.py`(R-PERF-1, R-PERF-2 둘 다 — 서로 다른 함수
  영역, 순차 진행 권장).
- 수정(테스트): `tests/test_zone_batch_worker.py`(R-PERF-2 — 2-워커 분리에 맞춰
  전면 갱신), `tests/test_zone_state_persistence.py`(사이드카 순서 회귀 확인 추가).
- 신규 파일 없음. `app/core/zone_metrics.py`/`app/core/zone_state_store.py`/
  `app/core/inference_engine.py`는 순수 함수만 재사용하므로 무변경.
