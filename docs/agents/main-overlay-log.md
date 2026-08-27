# Main Overlay Agent Log

## 2026-08-28 — 추론 오버레이 배경 밝기 회귀 수정

- 상태: 완료
- `app/core/inference_engine.py::_colorize_and_blend()`에서 배경 클래스(`0`)는 원본 픽셀을 유지하고 전경에만 opacity를 적용했다.
- `tests/test_github_issue_23.py`에 배경 불변 및 전경 혼합값 회귀 테스트를 추가했다.
- 검증: `3 passed`, `git diff --check` 통과.

## 2026-08-28 — 추론 탭 UI 병목 계측 및 수정

- 상태: 완료
- 이벤트 경로: opacity/threshold signal → UI 스레드 `refilter()` → 전체 해상도 blob 통계 및 오버레이 생성 → `set_pixmap()`의 fit 초기화.
- opacity는 필터 결과 재사용(`reblend`), opacity/threshold 입력은 single-shot timer로 병합, 같은 이미지 갱신은 줌/패닝을 유지하도록 최소 수정했다.
- 2000×1500 계측: 357.3ms → 210.9ms, slider 20 tick당 실행 20회 → 1회.
- 결과 캐시는 이미지 전환 및 threshold 재조정 기능에 필요해 유지하되, reject가 없을 때 `raw_class_map`과 같은 `class_map`의 중복 복사는 생략했다(20MP int64 기준 이미지당 약 160MB 절감). 모델 선택 탭 분리는 roadmap 향후 과제로 남겼다.
- 검증: 관련 테스트 7건, `py_compile`, `git diff --check` 통과.
