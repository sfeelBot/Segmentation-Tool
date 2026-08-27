# Main Overlay Agent Log

## 2026-08-28 — 추론 오버레이 배경 밝기 회귀 수정

- 상태: 완료
- `app/core/inference_engine.py::_colorize_and_blend()`에서 배경 클래스(`0`)는 원본 픽셀을 유지하고 전경에만 opacity를 적용했다.
- `tests/test_github_issue_23.py`에 배경 불변 및 전경 혼합값 회귀 테스트를 추가했다.
- 검증: `3 passed`, `git diff --check` 통과.
