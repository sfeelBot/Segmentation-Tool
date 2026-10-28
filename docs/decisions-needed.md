# 사용자 결정 대기 목록

살아있는 목록. 실제 **결정**이 나오면 해당 항목을 즉시 삭제한다(근거는 관련 로그/문서에
이미 남으므로 삭제해도 이력은 보존됨). "추후 논의/보류"라는 답만 받은 경우는 삭제하지 않고
"보류된 항목" 절로 옮겨 계속 유지한다.

## 결정 대기

- **main 기존 영문 번역 내부 불일치 4건** — 2026-10-28 존/R분석 탭 i18n 라운드에서
  전체 `app/core/i18n.py` 용어 일관성 감사 중 발견(이번 라운드 범위 밖이라 수정 안
  함): 같은 한국어 원문이 키마다 다른 영문으로 번역됨 — ① "선택" → `infer.select_file`
  "Select File…" vs `project_export.choose_path` "Choose save location" (Select/Choose
  혼용), ② "삭제" → `ui.delete` "Delete" vs `train.remove` "Remove", ③ "전체 초기화" →
  `train.clear_queue` "Clear All" vs `train.confirm_clear_title` "Clear Queue", ④
  "이미지 없음" → `infer.no_image_title` "No Image" vs `browser.no_images_title` "No
  Images". main에서 이 영문 문구들을 통일할지(통일 시 어느 쪽을 표준으로 할지) 사용자
  결정 필요. 상세: 에디션 워크트리의
  `docs/specs/zone-r-analysis-i18n-2026-10-28.md`(`D:/segmentation model-zone-analysis-tab/`)
  "리더 최종 감사" 절(별도 저장소 경로라 직접 링크 불가).

*(GitHub #22 "installer로 설치 시 기존 버전 있는지 체크 필요" — 2026-08-29 사용자 결정
완료: 확인 후 구버전 자동 제거+재설치, BUG-016(무인 제거 후 잔존파일)도 같이 고치기로
결정. 상세: [docs/specs/github-issue-22-and-16-followup-2026-08-29.md](specs/github-issue-22-and-16-followup-2026-08-29.md)
"GitHub #22" 절)*

*(GitHub #15/#12 라운드4 결정 2026-08-27 완료 — 아래 "완료된 결정" 절 참고)*

*(GitHub #2 관련 3건은 2026-08-20 사용자 확인 완료. 요청1은 exe 패키징 항목으로
편입, 요청2는 라운드 A+B 함께 진행 확정. 결과는
[docs/specs/voc-github-issues-2026-08-20.md](specs/voc-github-issues-2026-08-20.md)
"사용자 결정 — 전부 완료" 절에 기록됨)*

## 보류된 항목

- **GitHub #5 "모델 탭 변경"** — 2026-08-20 사용자 결정: **보류(탭 구조 유지)**. 모델 탭을
  독립 탭에서 학습 탭 안 "+" 버튼→모달로 바꾸는 요청이었으나, `loaded_model`을 학습/
  라벨링(오토라벨링)/추론 3개 탭이 교차 참조해 파급이 크고 탭 기반 UI 설계 원칙과도
  충돌해 지금은 진행하지 않기로 함. 다른 우선순위 작업 먼저 진행. 상세:
  [docs/specs/voc-github-issues-round2-2026-08-20.md](specs/voc-github-issues-round2-2026-08-20.md)
  "#5" 절.
