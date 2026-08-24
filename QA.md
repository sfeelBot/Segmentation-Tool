# QA — 버그 및 VOC 추적

## Open Issues

| ID | 우선순위 | 설명 | 보고자 | 상태 |
|----|----------|------|--------|------|
| BUG-004 | P3 | `auto_labeler.collect_unlabeled()`의 `get_label_status()` 1회 read 통합(R6)이 `get_ok()+load()` 2회 read 구버전과 100% 동치는 아님 — `annotations` 배열에 앱이 절대 생성하지 않는(=`save()`가 쓰지 않는) 미인식 `type` 값의 원소만 있는 손상/외부편집 JSON의 경우, 구버전은 `load()`가 해당 원소를 조용히 건너뛰어 결과 리스트가 비므로 "unlabeled"로 간주(자동 라벨링 대상에 포함)했지만 신버전은 `annotations` 배열 자체가 non-empty이므로 "labeled"로 간주(대상에서 제외). 정상 사용(앱이 직접 저장한 JSON)에서는 재현 불가 — 손으로 편집했거나 외부 도구가 만든 손상 파일에서만 발생. 부수 관찰: 최상위가 dict가 아닌(JSON 배열 등) 손상 파일에서는 구버전(`load()`가 `AttributeError`로 크래시)과 달리 신버전은 크래시 없이 "unlabeled"로 안전 처리 — 이 케이스는 오히려 신버전이 더 견고함 | R6 검증(verifier) | Open |
| BUG-016 | P3 | Inno Setup 무인 제거(`unins000.exe /VERYSILENT /SUPPRESSMSGBOXES`) 후 설치 폴더(`{app}`)가 완전히 삭제되지 않고 `data\logs\` 하위 런타임 로그 파일이 남음(재현: 설치→exe 1회 실행(→`app.log` 생성)→무인 제거, 설치 디렉토리 자체와 `data\logs\` 잔존 확인) | 커밋 6cc8947 검증(verifier, D:\ 드라이브 실빌드) | Open |

---
