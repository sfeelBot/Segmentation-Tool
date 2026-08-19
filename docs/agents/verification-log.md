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
