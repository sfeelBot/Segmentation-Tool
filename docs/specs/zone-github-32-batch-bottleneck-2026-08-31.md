# GitHub #32 — Zone 영역 일괄 적용 병목 실측 및 최소 수정안 (2026-08-31)

## 요구사항과 재현 데이터

- 이슈 원문: **"영역 일괄적용 시 병목이 너무 심함"**.
- 추측을 피하기 위해 `ZoneAnalysisTab._on_batch_process()`의 실제 호출 순서를 끝까지
  추적하고, 저장소의 `projects/nok/images` BMP 5장(각 59,885,622 bytes,
  5,472×3,648 RGB) 및 같은 해상도의 합성 타겟 마스크로 계측했다.
- 환경: Windows, `C:\Users\Feel\anaconda3\python.exe`, CPU 경로. 벽시계는
  `perf_counter`, CPU 시간은 `process_time`, RSS 피크는 `psutil` 1ms 샘플링,
  함수별 시간은 `cProfile`을 사용했다. 각 측정은 GC 후 2~3회 반복했다.

## 실제 실행 경로

`_on_batch_process()`는 **메인 GUI 스레드에서** 선택 이미지를 직렬 순회한다.

1. `QApplication.processEvents()`를 이미지 시작 전에 한 번 호출
2. `_results` 캐시 조회
3. 미적중이면 `engine.run()`
   - `prepared`를 넘기지 않으므로 `prepare_inference()` → `torch.load()` →
     `model.load_state_dict()` → `model.to(...).eval()`을 **이미지마다 반복**
   - 이미지 decode/resize → model forward → 원본 해상도 class/confidence map 생성
   - 연결요소 분석 → 원본 해상도 컬러 오버레이 생성
   - 완성된 `InferenceResult`를 `_results`에 계속 보관
4. 장별 적용 모드면 같은 원본 BMP를 다시 열어 RGB→BGR 복사 후 `detect_circles()`
5. 사이드카 load 및 수동 편집 반영
6. `zones_from_circles()`가 원 개수만큼 원본 해상도 bool 마스크를 한꺼번에 생성
7. 각 존마다 `zone_stats()`가 면적/교집합을 다시 전수 합산
8. 상태 배지 갱신 후 다음 이미지

따라서 `processEvents()`는 단계 3~7이 끝날 때까지 다시 호출되지 않는다. 한 장의
추론·원 검출·존 계산 전체가 하나의 GUI 무응답 구간이다.

## 실측 결과

### 캐시 적중 후 Zone 계산만 수행

5,472×3,648, 원 3개(존 4개):

| 구간 | wall time | CPU time | RSS 순간 증가 |
|---|---:|---:|---:|
| `zones_from_circles` + 존 4개 `zone_stats` | 218.4 / 233.5 / 235.2ms | 234.4 / 250.0 / 234.4ms | 209.6 / 208.5 / 208.8MiB |
| `zones_from_circles`만(cProfile) | 117ms | - | - |
| └ `disk_mask` 3회 | 103ms | - | - |
| `zone_stats` 4회(cProfile) | 93ms | - | - |
| └ numpy `sum` 8회 | 79ms | - | - |

캐시가 완전히 차 있어도 5장은 약 1.1초 동안 이 작업을 메인 스레드에서 수행한다.
원 수와 이미지 수에 선형 비례한다.

### 장별 적용의 원본 재개방

| 구간 | wall time | CPU time | RSS 순간 증가 |
|---|---:|---:|---:|
| 실제 BMP PIL RGB decode | 105.3~120.1ms | 109.4~125.0ms | 261.3~266.7MiB |
| decode + BGR copy + `detect_circles` | 210.0~213.5ms | 250.0~390.6ms | 264.0~264.3MiB |

장별 적용은 추론이 이미 끝난 이미지에서도 존 계산과 합쳐 장당 약 0.44초의 GUI
무응답 구간이 생긴다(5장 약 2.2초, 추론 시간 제외).

### 추론 결과 캐시의 메모리 규모

`InferenceResult`의 numpy 배열만 이미지당
`class_map(int64) + raw_class_map(int64) + confidence_map(float32)` =
399,237,120 bytes(380.7MiB)다. RGB 크기와 같은 QPixmap 저장공간을 4 bytes/pixel로
계산하면 약 76.1MiB가 추가되어 **이미지당 약 456.9MiB, 5장 약 2.23GiB**다.
Python 객체/블랍 목록은 이 추산에서 제외했으므로 실제 상한은 더 크다. R-ZONE-3의
무제한 `_results` 보관은 대형 원본 배치에서 메모리 압박·paging 위험을 만든다.

### 체크포인트 반복 준비

실제 체크포인트가 저장소에 없어 95.4MiB 합성 state dict로 I/O/가중치 복사 비용만
분리 측정했다. 5회 반복 준비는 0.178초, 한 번 준비 후 5회 재사용은 0.040초였다
(4.45배). 실제 총 추론 시간은 모델/GPU에 따라 달라지지만, 현재 Zone 경로가
`prepared` 인자를 누락해 이미지 수만큼 확정적으로 반복하는 구조적 낭비는
`inference_tab._InferenceWorker`와 `engine.prepare_inference()`의 기존 해결 패턴으로
제거할 수 있다.

## 근본 원인(우선순위)

1. **P0 UX:** `_on_batch_process()` 전체가 GUI 스레드에서 실행된다. 느린 작업이
   worker/QThread 경계 밖이므로 앱이 멈춘 것처럼 보인다.
2. **P0 메모리:** 원본 해상도 `InferenceResult`를 무제한 dict에 보관한다. `nok`
   5장만으로 계산상 2.23GiB 이상이다.
3. **P1 반복 작업:** 캐시 미적중마다 체크포인트/가중치를 다시 준비한다. 이미 있는
   `prepare_inference()`/`prepared` 경로를 사용하지 않는다.
4. **P1 메모리/CPU:** `zones_from_circles()`가 모든 원판/존 마스크를 동시에 만들고
   `zone_stats()`가 존마다 배열을 재주사한다. `nok` 한 장/원 3개에서 0.23초와
   약 209MiB 순간 증가가 실측됐다.
5. **P2 장별 모드:** 추론 과정에서 이미 연 원본을 활용하지 못하고 배치 단계에서
   같은 BMP를 다시 decode/copy한다.

## 최소 수정안

### 1차 — 반드시 적용

- `app/tabs/zone_analysis_tab.py`에 기존 `_ZoneInferenceWorker`와 같은 QThread 규약을
  따르는 배치 worker를 둔다. worker는 순수 데이터(rows, 상태, 오류, 진행률)만 signal로
  보내고 widget/`QPixmap`/목록 상태 변경은 GUI 슬롯에서만 한다.
- worker 시작 시 `engine.prepare_inference(model, checkpoint)`를 **한 번** 호출하고,
  모든 `engine.run(..., prepared=prepared)`에 재사용한다. 별도 캐시·새 dependency는
  만들지 않는다.
- 취소는 이미지 경계에서 확인한다. 현재도 이미지 내부 중단은 지원하지 않으므로
  의미를 바꾸지 않는다.
- `_results`는 무제한 보관하지 않는다. 현재 화면 결과와 기존에 사용자가 명시적으로
  추론한 결과만 유지하고, 배치 전용 결과는 rows/사이드카 계산 후 해제한다. 이미지
  재방문 시 필요하면 기존 worker 경로로 다시 추론한다. 2GiB 이상 상주보다 예측 가능한
  재계산이 안전하다.

### 2차 — 1차 후에도 처리량 기준 미달일 때만 적용

- `zone_metrics`에 배치 전용 경량 통계 helper를 추가해 원판/존 마스크 전체 목록을
  반환하지 않고 `disk_mask()`와 `zone_stats()`를 순차 재사용한다. 단, 현재
  `disk_mask()` 자체의 float64 broadcast 임시배열이 RSS 피크 대부분이라 단순 streaming
  프로토타입은 206~229MiB로 유의미하게 줄지 않았다. 따라서 1차 수정에 섞지 않는다.
- `disk_mask()`의 float32/out-buffer 또는 OpenCV raster 방식은 기존 경계 픽셀 의미를
  독립 오라클로 완전 일치 검증한 뒤에만 고려한다. 실험 float32 버전은 wall
  166.8~195.3ms, RSS 133.3~152.7MiB였지만 제품 로직 변경 근거로는 아직 부족하다.

## 수용 기준

1. 실제 `projects/nok` 5장으로 배치 중 창 이동/취소 클릭/진행률 repaint가 가능하고,
   GUI 이벤트 무응답 구간이 200ms를 넘지 않는다(모델 호출 자체는 worker 내부).
2. 캐시 미적중 N장 배치에서 `prepare_inference()` 호출은 정확히 1회이고 각 run은 같은
   `prepared` 객체를 받는다.
3. 5,472×3,648 5장 배치 후 `_results`에 배치 전용 5개가 누적되지 않으며, RSS가
   이미지당 약 457MiB씩 선형 증가하지 않는다. 완료 후 RSS 피크/잔존값을 로그에 기록한다.
4. 일괄 적용/일괄 적용 후 수정/장별 적용의 circles 선택, 사이드카 저장, 기존 수동
   편집 반영, 결과 rows/배지는 현행과 동일하다.
5. 이미지 경계 취소 후 완료된 이미지 결과만 남고 앱이 종료/재실행 가능하다.
6. worker 예외는 해당 이미지 오류 상태와 로그로 전달되며 다음 이미지를 계속 처리한다.

## 영향 파일과 검증

- 필수: `app/tabs/zone_analysis_tab.py`
- 테스트: 기존 `tests/test_zone_state_persistence.py`, 신규 GitHub #32 worker 단위 테스트
- 조건부 2차: `app/core/zone_metrics.py`
- 실제 GUI 검증: `python main.py`로 `nok` 5장, 세 모드 각각 실행; wall/CPU/RSS,
  이벤트 응답성, 취소, 완료 후 재실행을 관찰한다.

