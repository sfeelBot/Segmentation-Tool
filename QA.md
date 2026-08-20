# QA — 버그 및 VOC 추적

## Open Issues

| ID | 우선순위 | 설명 | 보고자 | 상태 |
|----|----------|------|--------|------|
| BUG-003 | P3 | `AnnotationCanvas._translate_selected()`(Select 도구로 어노테이션을 캔버스 밖까지 드래그) 후 마스크가 전량 0이 되어도 정리(cleanup)가 없어 `self._annotations`에 빈 brush_mask가 세션 동안 남을 수 있음. 저장 시 `annotation_store.save()`가 `a.mask.any()`로 걸러내 디스크에는 저장되지 않지만(데이터 유실·오염 없음), 라벨링 탭 어노테이션 목록 패널(`labeling_tab.py:_refresh_ann_list()`)에 렌더링되지 않는 유령 항목("#N [Mask] ...")이 다음 이미지 전환 전까지 표시될 수 있음 | R3 검증(verifier) | Open |
| BUG-004 | P3 | `auto_labeler.collect_unlabeled()`의 `get_label_status()` 1회 read 통합(R6)이 `get_ok()+load()` 2회 read 구버전과 100% 동치는 아님 — `annotations` 배열에 앱이 절대 생성하지 않는(=`save()`가 쓰지 않는) 미인식 `type` 값의 원소만 있는 손상/외부편집 JSON의 경우, 구버전은 `load()`가 해당 원소를 조용히 건너뛰어 결과 리스트가 비므로 "unlabeled"로 간주(자동 라벨링 대상에 포함)했지만 신버전은 `annotations` 배열 자체가 non-empty이므로 "labeled"로 간주(대상에서 제외). 정상 사용(앱이 직접 저장한 JSON)에서는 재현 불가 — 손으로 편집했거나 외부 도구가 만든 손상 파일에서만 발생. 부수 관찰: 최상위가 dict가 아닌(JSON 배열 등) 손상 파일에서는 구버전(`load()`가 `AttributeError`로 크래시)과 달리 신버전은 크래시 없이 "unlabeled"로 안전 처리 — 이 케이스는 오히려 신버전이 더 견고함 | R6 검증(verifier) | Open |

---

## Closed Issues

| ID | 수정 버전 | 설명 | 근본 원인 | 해결 방법 |
|----|-----------|------|-----------|-----------|
| BUG-001 | Phase 1 | `ImportError: DLL load failed while importing QtWidgets` — PyQt6 6.11.0 기동 불가 | PyQt6 6.8+ 가 Windows Anaconda(Python 3.13) 환경에서 DLL 프로시저 못 찾음 | PyQt6 6.7.1 고정 (`requirements.txt`); 6.8+ 설치 금지 |
| BUG-002 | R1(미배포, 커밋 예정) | `annotation_store.rle_encode()` — 모든 brush_mask 어노테이션이 저장 시 빈 RLE 문자열이 되어 전량 데이터 유실 (재현: `mask[10:20,10:20]=1` 인 100픽셀 마스크도 `rle_encode()` → `""`, 왕복 후 `rle_decode()` 결과 전부 0). `projects/nok/` 실데이터는 전부 polygon 타입이라 이 프로젝트에서는 아직 미발현. 폴리곤 어노테이션은 영향 없음(이 함수를 타지 않음). | `rle_encode()` 내부 `diff = np.diff(flat_uint8, prepend=0, append=0)` 가 `flat`의 uint8 dtype 을 그대로 유지해 1→0 하강 엣지(-1)가 부호없는 정수 언더플로우로 255 가 됨 → `np.where(diff == -1)` 이 항상 빈 배열 → `n = min(len(starts), len(ends)) = 0` → `return ""`. v1.6.0 초기 릴리즈부터 존재하던 결함으로 추정(커밋 43fad19), 이후 경쟁조건 방지 커밋(5769306)의 `n = min(...)` 방어 코드가 예외를 삼켜 증상을 더 눈에 띄지 않게 만듦. | `np.diff` 호출 전 `flat`을 `int8`로 캐스팅(`flat.astype(np.int8)`, prepend/append도 `np.int8(0)`)해 부호없는 언더플로우를 방지. 기존 `n = min(len(starts), len(ends))` 방어 코드(경쟁조건 대비)는 그대로 유지 — 별개 안전장치. 100px/~1.8Mpx 등 여러 마스크로 `rle_encode`→`rle_decode` 라운드트립 검증 완료. **주의**: 이 수정 이전에 이미 저장되어 `"rle": ""`로 남은 과거 brush_mask 데이터는 복구 불가(원본 마스크가 저장 시점에 이미 소실됨). |

---

## VOC (Voice of Customer)

사용자가 직접 제기한 요청·불편 사항.

| 날짜 | 요청 내용 | 결정 | 근거 |
|------|-----------|------|------|
| 2026-08-20 | [GitHub #1](https://github.com/sfeelBot/Segmentation-Tool/issues/1) "사용성 정리" ① 라벨링/추론 이미지 탭에 폴더 정보(최하위 폴더명) 표시 요청 | 수용 — 이미 진행 중인 UI/UX 재편 라운드 2에서 커버됨(라벨링 탭은 기존부터 폴더 트리 있음, 추론 탭은 라운드 2에서 트리형 폴더 그룹핑 신규 추가 예정) | `docs/specs/ui-redesign-plan-2026-08-19.md`, `docs/roadmap.md` "UI/UX 재편" 절 |
| 2026-08-20 | [GitHub #1](https://github.com/sfeelBot/Segmentation-Tool/issues/1) "사용성 정리" ② RTX 4500 Ada GPU인데 `torch 2.13.0+cpu`(CPU 전용)로 설치됨, torchvision 설치 실패 원인 문의, .exe 빌드 시 의존성 별도 설치 필요 여부 문의 | 원인 파악 완료 — `requirements.txt`에 CUDA index-url 안내가 없어 `pip install -r requirements.txt`를 먼저 실행하면 CPU 전용 빌드가 잡힘. `docs/USER_MANUAL.md`엔 이미 올바른 설치 순서(torch를 CUDA 빌드로 먼저 설치)가 있었으나 루트 `README.md`가 빈 플레이스홀더라 발견이 안 됨 | **즉시 수정**: `README.md`에 설치 가이드 추가(USER_MANUAL 링크 포함), `requirements.txt`에 경고 주석 추가, `USER_MANUAL.md` GPU 표에 RTX Ada 워크스테이션 계열 행 추가. .exe 빌드 의존성 별도 설치 문제는 CLAUDE.md상 PyInstaller 패키징이 범위 밖이라 별도 논의 필요 |
| 2026-08-20 | [GitHub #2](https://github.com/sfeelBot/Segmentation-Tool/issues/2) "프로젝트 내보내기 기능" ① 프로젝트를 클릭하면 자동으로 열리게 해달라 | **사용자 재확인으로 정정**: 앱 내부 최근 프로젝트 목록 얘기가 아니라 "전용 프로젝트 확장자를 만들어 OS 파일탐색기에서 더블클릭하면 앱이 바로 열리게" 해달라는 요청이었음. Windows 파일 연결은 보통 설치 프로그램이 등록하므로 exe 패키징(별도 "추후" 항목)에 하위 요구사항으로 편입 — 지금 스코프 아님 | `docs/roadmap.md` "exe 패키징 + Setup Guide" 절 |
| 2026-08-20 | [GitHub #2](https://github.com/sfeelBot/Segmentation-Tool/issues/2) "프로젝트 내보내기 기능" ② 프로젝트 전체를 내보내거나 하나의 파일로 통합하는 기능 요청 | 수용 — export(라운드 A: zip 패키징) + import(라운드 B: zip→프로젝트 복원) 둘 다 진행 확정. checkpoints 기본 미체크/user_models 기본 체크, import 이름 충돌 시 자동 리네임(덮어쓰기 금지) | `docs/specs/voc-github-issues-2026-08-20.md` |

---

## 이슈 작성 가이드

### Bug ID 형식
`BUG-{순번}` (예: `BUG-001`)

### 우선순위
- **P0** — 앱 크래시·데이터 손실
- **P1** — 핵심 기능 동작 불가
- **P2** — 기능 동작하나 불편함
- **P3** — 개선 사항·UX 요청

### Bug 항목 예시
```
| BUG-001 | P1 | 폴리곤 닫기 후 Undo가 동작하지 않음 | 사용자 VOC | 조사 중 |
```

### VOC 항목 예시
```
| 2025-01-15 | 브러시 크기 단축키 추가 요청 | 수용 — Phase 3에서 구현 | 사용성 향상 |
```
