# Changelog — Segmentation Model UI

버전 구분 기준: 사용자 요청 단위로 묶어 릴리즈.  
main 형식: `[vX.Y.Z] YYYY-MM-DD`, zone 형식: `[zone-vX.Y.Z] YYYY-MM-DD`.

---

## [zone-v1.10.0] 2026-10-28

사용자 요청: (1) "브러시로 그린 것도 검출 결과와 동일하게(불투명도 포함) 화면에
보이게, Top/Bottom도 동일하게" — 브러시는 검출 결과를 수정하는 도구이지 별도
레이어가 아니라는 원칙 확인. (2) "R 검사 세팅에 자동 검출 on/off 추가, 꺼지면
ROI 지정 없이 브러시로 그린 영역만 사용".

### 수정
- 브러시로 수정한 결과가 검출 결과와 별도 색(파란/회색)으로 덧칠돼 보이던 버그
  수정 — 커밋 후엔 검출 결과와 완전히 동일한 레이어 하나로만 보이도록 변경.
  - R분석(`r_roi_canvas.py`): 커밋된 전체 스트로크 래스터(`_stroke_overlay`)는
    검출 마스크(`effective_mask()`)가 없을 때만 그리고, 있으면 초록 마스크
    레이어 하나로 통일. 드래그 중(커밋 전) 스트로크는 그대로 파란/회색 미리보기.
  - 존분석(`zone_canvas.py`/`zone_analysis_tab.py`/`inference_engine.py`): 신규
    `engine.colorize_class_map()`(임의 class_map을 직접 컬러화, `InferenceResult`
    불필요)을 추가하고, `_reblend_overlay()`가 브러시로 지운/그린 영역을
    `class_map` 사본에 반영(지우기→배경 0, 그리기→타겟 클래스 id)한 뒤 다시
    컬러화하도록 변경 — 원본 `class_map`은 변형하지 않음. 커밋된 스트로크의
    파란/회색 덧칠(`_paint_erase_preview`)은 제거하고 드래그 중 스트로크만
    유지. 재합성은 `_recompute_zones()`(브러시 커밋/Undo/블랍삭제 공유 funnel)
    와 타겟 클래스 전환 시점에 호출.

### 추가
- R분석 탭: 검사 설정에 "자동 검출 사용" 체크박스 추가(기본 켜짐, 하위호환).
  꺼면 ROI를 지정하지 않아도 되고, 검출 버튼 3개(현재/셀/전체)는 비활성화되며
  브러시로 그린 영역만으로 면적이 계산된다 — 이전엔 ROI/검출 결과가 없으면
  `effective_mask()`가 `None`을 반환해 브러시만으로는 면적을 절대 만들 수
  없던 버그를 함께 고쳤다(`_compute_detected_mask()`가 빈 numpy bool 마스크를
  반환하도록 통일, `None`과의 구분이 핵심). `app/core/i18n.py`에
  `r_settings.auto_detect_checkbox`/`r_settings.auto_detect_off_suffix`
  신규 키(ko/en).

---

## [zone-v1.9.0] 2026-10-28

사용자 요청: 존분석/R분석 탭의 검출 결과 오버레이가 고정 불투명도라 라벨링/보정
중 조절이 안 되던 것을, main 추론 탭(`OverlayViewerPanel`)과 동일한 패턴의
슬라이더로 조절 가능하게 변경.

### 추가
- `app/core/i18n.py`에 `common.overlay_opacity_label` 신규 키(ko/en) — 두 탭이
  동일 문구를 공유(라벨마다 별도 키를 만들지 않음).
- 존분석 탭: 캔버스 상단 툴바 바로 아래에 불투명도 슬라이더(0~100%, 기본 50%)
  행 추가. 값 변경 시 75ms 디바운스 후 `inference_engine.reblend()`로 모델
  재실행 없이 오버레이만 재합성(main 추론 탭 opacity 패턴과 동일). 슬라이더
  값은 이미지 전환/재추론에도 유지된다(`_show_overlay_state()` 호출마다 항상
  현재 슬라이더 opacity로 재합성).
- R분석 탭: `RRoiCanvas.set_mask_opacity()`/`mask_opacity()` 추가 — 고정
  alpha(90/255)였던 검출 마스크 오버레이를 캔버스 좌측 하단 플로팅 슬라이더
  (기본 35%, 90/255에 해당)로 조절. 메모리의 numpy 마스크만 재합성해 디바운스
  불필요.
- 라벨링/존분석/R분석 탭 공통: 선택된 도구를 알아보기 쉽게 툴바 버튼
  `:checked` 상태에 활성 강조 색(`#1e3a5f` 배경 + `#60a5fa` 테두리/글자) 적용.
- R분석 탭: ROI 편집 툴바 아이콘을 화살표 모양(`tool_select`)에서 사각형
  아웃라인(`tool_rect`, 신규 SVG)으로 교체 — 영역이 사각형임을 더 명확히 표시.
- R분석 탭: 라벨링 탭과 동일한 패턴으로 검출 결과(마스크) show/hide 토글 추가
  (눈 아이콘, `[F]` 단축키). `app/widgets/r_roi_canvas.py`에
  `overlay_toggle_requested` 시그널 + `set_mask_overlay_visible()` 추가 —
  화면 표시 여부만 끄고 마스크 데이터/boundary 편집·면적 계산은 그대로 동작.
  `app/core/i18n.py`에 `r.overlay_visible_tip` 신규 키(ko/en).

---

## [zone-v1.8.0] 2026-10-28

사용자 요청: 존분석("TOP/BOTTOM ANALYSIS")/R분석 탭에 영어(en) 언어 지원 적용
— 탭 제목만 번역돼 있던 것을 탭 내부 전체(버튼/라벨/툴팁/다이얼로그)로 확장,
같은 한국어 문구가 탭마다 다르게 번역되지 않도록 전체 탭 기준 용어 일관성도
감사.

### 추가
- `app/core/i18n.py`에 `zone.*`/`zone_canvas.*`/`zone_recipe.*`/`zone_batch.*`/
  `zone_step.*`/`r.*`/`r_cell.*`/`r_settings.*`/`r_batch.*`/`r_step.*` 신규 키
  242개(ko/en) 추가.
- 11개 파일(`zone_analysis_tab.py`/`zone_canvas.py`/`zone_recipe_dialog.py`/
  `zone_batch_result_dialog.py`/`zone_step_indicator.py`/`r_analysis_tab.py`/
  `r_cell_panel.py`/`r_settings_panel.py`/`r_batch_result_dialog.py`/
  `r_step_indicator.py`, `r_roi_canvas.py`는 UI 문자열 없어 변경 없음)의
  하드코딩 한국어 UI 문자열을 `t()` 호출로 교체.

### 수정
- `zone.running` 영문을 main의 기존 `infer.running`과 통일("Inferring…").
- **BUG-046**: 공용 `InferenceImageList` 위젯(`editable=False`)의 제목 라벨/
  검색창 placeholder/정렬 라벨이 `t()`를 거치지 않고 한국어로 하드코딩돼
  있던 것을 기존 키 재사용으로 수정 — 존/R분석 탭(및 추론 탭)의 이미지 목록
  패널도 영어 설정에서 정상 표시됨.

### 참고
- main 공용 탭(라벨링/추론/학습/모델)의 기존 영문 번역 자체에 내부 불일치
  4건(선택→Select/Choose 등)을 발견했으나 이번 라운드 범위 밖 — main
  `docs/decisions-needed.md`에 등록.

---

## [zone-v1.7.0] 2026-10-28

사용자 요청: 존분석/R분석 탭의 이미지 목록에서 Shift(범위)/Ctrl(개별) 다중선택 +
Delete 일괄 제거가 두 탭에서 동일하게 동작하도록.

### 변경
- R분석 탭 "선택한 셀의 이미지" 목록(`RCellPanel._image_list`)에
  `set_multi_select(True)` 적용 — Zone 탭(`ZoneAnalysisTab._img_list`)과
  동일하게 Shift 범위선택/Ctrl 개별선택 + Delete 일괄 제거(목록에서만 제거,
  원본 파일 보존) 지원. Zone 탭은 이미 동일 기능이 있어 변경 없음(확인만).

---

## [zone-v1.6.3] 2026-10-27

사용자 요청: main v1.11.0(공유 위젯 추출: view_transform/brush_toolbar/
inference_image_list)을 sync 브랜치+PR로 반영하고, Zone/R분석 탭의 편집
툴바(브러시/지우개/영역삭제/pan/undo/브러시크기)를 공유 `BrushToolbar`로
교체.

### 변경
- main sync 반영(`view_transform.py` 공용 좌표변환, `inference_image_list.py`
  통합, `image_browser.py` 제거) — "양쪽 다 살리기"로 append-only 문서 충돌
  해결, 기능 동작 변경 없음.
- Zone/R분석 탭 편집 툴바를 `app/widgets/brush_toolbar.py` 공용
  컨트롤러로 교체. 아이콘 순서·단축키·동작은 그대로 유지, R분석 탭
  undo가 버튼에서 액션(단축키 대응)으로 UI 위치 소폭 변경.
- `main_base_tag`를 `v1.11.0`, `main_base_commit`을 `7bd280e3`로 갱신.

---

## [zone-v1.6.2] 2026-10-27

### 성능
- "R 분석" 탭 브러시 보정 시 메인스레드 블로킹 기하급수적 증가 수정. 스트로크를
  커밋할 때마다 누적된 모든 manual_strokes를 처음부터 재생하던 것을 증분 캐시
  (`RRoiCanvas.effective_mask()`)로 바꿔 매 커밋 상수 시간으로 개선 + `zone_metrics.
  disk_mask()`를 바운딩박스 기반으로 최적화(반환값 수학적으로 동일, Zone 탭 55개
  UI 테스트로 회귀 없음 확인). 4000×3000 이미지·반경15px 브러시·30스트로크 기준
  스트로크 #30 14.5초→34ms(428배), 30개 누적 191.5초→1.0초.
- "R 분석" 탭 대형 이미지 전환 시 이중 디코드(`cv2.imread`+`QPixmap` 별도 디코드)
  제거 + LRU 캐시(8장, Zone 탭 R-PERF-1과 동일 관례) 추가. 4000×3000 기준
  전환 286~538ms→69.8ms(cold)/11~12ms(warm, 캐시 적중).
- 사용자가 요청한 추가 사용성 UI 검증(엣지케이스/파괴적 조작/반복 조작) 중
  실측 프로파일링으로 발견, 수정+독립 재검증(Zone 탭 회귀 없음, 증분 캐시
  결과가 전체 재생 결과와 완전 일치) 통과.

## [zone-v1.6.1] 2026-10-26

### 수정
- BUG-045(P1): "R 분석" 탭 배치 검출 버튼(현재 이미지/선택 셀 전체/전체 셀 분석)을
  처리 중 재클릭하면 `_detect_worker`가 새 인스턴스로 교체돼 기존 QThread 참조가
  끊기고 두 워커가 동시에 같은 이미지를 처리해 크래시하는 문제. `_run_batch_detect()`
  시작부에 재진입 가드 추가 + 배치 진행 중 검출 버튼 3개 비활성화(완료 시 복구).
  추가 사용성 검증(엣지케이스/파괴적 조작/반복 조작)에서 발견, 수정+독립 재검증 통과.

## [zone-v1.6.0] 2026-10-26

### 추가
- "R 분석" 신규 탭 — 존(Zone) 분석 탭과 나란히 쓰이는 사각형 ROI+threshold 기반
  contour 면적 측정 도구. 핵심은 여러 이미지를 "셀(cell)" 단위로 묶어 관리하고,
  셀 내 이미지 면적 합계를 분자로 `R_cell = sum(area)/분모`를 셀당 1회만 계산해
  스펙 상/하한과 비교한 합/불 판정을 낸다(이미지별 개별 판정 없음).
  - 폴더 일괄 업로드(하위폴더명=셀 ID) / 파일 단위로 특정 셀에 추가, 셀 선택 후
    이미지 삭제·추가.
  - 검사 설정 팝업: 사각형 ROI(전역 1회 지정 + 이미지별 보정), threshold 슬라이더,
    분모·스펙 상/하한 입력.
  - Contour 자동 검출(현재 이미지 / 선택 셀 전체 / 전체 셀 일괄), 브러시 그리기·
    지우기 + undo로 마스크 수동 보정.
  - 좌1:중3:우1 레이아웃, 캔버스 위 역할별 플로팅 오버레이(편집 도구/검출 실행/
    이미지 탐색), 선택된 셀에 종속된 결과 블록 + 전체 셀 요약 + Excel 내보내기.
  - 신규: `app/tabs/r_analysis_tab.py`, `app/core/r_analysis_metrics.py`,
    `app/core/r_cell_store.py`, `app/widgets/r_roi_canvas.py`,
    `app/widgets/r_cell_panel.py`, `app/widgets/r_settings_panel.py`,
    `app/widgets/r_step_indicator.py`, `app/widgets/r_batch_result_dialog.py`.
  - 기획: [docs/specs/r-analysis-tab-2026-10-26.md](specs/r-analysis-tab-2026-10-26.md).
    디자인 Artifact 4라운드 반복 후 사용자 최종 승인, 구현 2라운드(core+widgets →
    탭 조립/등록) + 검증 과정에서 BUG-043(P0, 세션 "새로 만들기" 시 데이터 손실)/
    BUG-044(P1, 캔버스 오버레이 겹침으로 Undo 클릭 불가) 발견·수정·재검증 Closed.

## [zone-v1.5.2] 2026-10-07

Main 기준: v1.10.4 이후 main 1.10.5 / ba8bf5e

### 수정
- R-PERF-1: 상/하부 분석 탭에서 캐시된 이미지를 재선택할 때마다 `engine.refilter()`
  (디스크 재디코딩 포함)와 `compute_blob_labels()`(cv2 connected-components)를
  매번 처음부터 재계산하던 딜레이를 수정. `(target_cid, min_confidence,
  min_pixel_size)` 키 기반 캐시(`_target_cache`)를 추가해 같은 조합으로 같은
  이미지를 재방문하면 재계산을 스킵하도록 변경(기능 변경 없음, 캐시 미스 시 동작
  동일). 전체 추론 재실행/이미지 삭제 시 캐시 무효화.
- R-PERF-2: 상/하부 분석 탭 일괄 처리 중 간헐적 "응답없음"을 수정. 배치 cv2/numpy
  존·블랍 후처리(`compute_blob_labels`+`zones_from_circles`+`zone_stats`+
  `zone_blob_stats`)와 사이드카 저장을 메인 스레드에서 동기 실행하던 것을, 전용
  QThread `_ZoneBatchPostWorker`(producer-consumer 큐 기반, CUDA 비호출)로 분리.
  `_ZoneBatchWorker`(CUDA 추론 전용)는 결과를 가벼운 중계 슬롯으로 큐에 넘기기만
  하고 즉시 반환, 무거운 계산은 두 번째 워커가 전담해 메인 스레드 블로킹을 없앰.
  최종 완료 판정은 더 늦게 끝나는 `_ZoneBatchPostWorker.finished` 기준으로 변경,
  취소 시 두 워커 모두 `requestInterruption`. BUG-030(다른 스레드의 실 CUDA
  추론 직후 같은 스레드 cv2 후처리가 트리거) 재발 조건 불성립 확인(두 번째 워커는
  CUDA를 전혀 호출하지 않음). 기능 변경 없음(배치 모드 3종/사이드카 자동 저장/
  진행률/결과 다이얼로그 전부 동일).
- BUG-037/038(R-PERF-2 회귀): 일괄 처리 취소 직후 바로 재시작하면 아직 살아 있던
  옛 CUDA 워커의 지연 신호가 새 배치에 섞여 같은 이미지가 중복 처리되던 문제와,
  취소 시 미완료 이미지의 목록 아이콘이 "처리 중"으로 영구히 남던 문제를 수정.
  `_on_batch_image_ready`/`_on_batch_row_computed`/`_on_batch_progress`가
  `self.sender()`로 발신자가 현재 활성 워커인지 확인해 옛 배치의 지연 신호를
  무시하고, `_on_batch_finished`가 미완료 대상의 상태를 `pending`으로 리셋.
- BUG-039(R-PERF-1 후속): `_target_cache`에 상한이 없어 대형 이미지를 수십 장
  훑으면 메모리가 수 GB까지 늘어날 수 있던 문제를 수정. `OrderedDict` 기반 LRU
  (상한 20, 적중 시 `move_to_end`)로 변경.

### 성능
- BUG-040(R-PERF-1 후속): `_target_cache` 적중 상태에서도 대형 이미지 선택이
  여전히 느리던 잔여 지연을 수정. (1) 이미지 전환 시 `_setup_target_classes()`→
  `_on_target_changed()`가 트리거하는 `_recompute_zones()`와, 곧바로 뒤따르는
  `ZoneCanvas.set_state()`(사이드카 복원)가 다시 트리거하는 `_recompute_zones()`가
  중복 실행되며 전자의 결과가 그대로 버려지던 것을 `_suppress_recompute` 플래그로
  억제해 최종 1회만 계산하도록 변경. (2) `_compute_zone_percentages()`/
  `_compute_zone_blob_rows()`가 각자 `zones_from_circles()`를 호출해 한 번의
  재계산에 4회(2함수 × 중복 트리거 2회) 호출되던 것을, 신규 헬퍼 `_current_zones()`로
  1회만 계산해 양쪽이 공유하도록 리팩터링(`_recompute_zones()`/`_on_export_single()`
  양쪽 호출부 적용). (3) `_setup_target_classes()`의 `detected_ids` 계산을
  `set(raw_class_map.ravel().tolist())`에서 `np.unique(raw_class_map)`로 교체해
  numpy 배열 전체를 python list/set으로 변환하는 비용을 제거. 기능 변경 없음(존
  퍼센티지/블랍 집계·오버레이·undo 스택 결과 전부 동일, 회귀 테스트 166건 통과).
  합성 5472×3648 입력(캐시 적중, cProfile) 계측: 재선택 소요시간 약 1795.7ms →
  약 749.8ms(약 58% 감소, `_recompute_zones` 중복 실행 제거 + `zones_from_circles`
  호출 24회→6회(disk_mask 기준) 감소). 실 GPU+실 체크포인트 독립 검증(2026-10-07):
  5472px 선택 지연 921ms→462ms(약 50% 감소), 2048px도 171ms→100ms, 결과 정합성
  골든 비교(대형 37건+소형 27건) diff 0건. 남은 ~0.46초는 체감 가능한 수준이라
  BUG-040은 P3 Open으로 유지(추가 개선 방향은 QA.md 참고).

### 기타
- `scripts/generate_version_info.py`의 `_git()`이 `subprocess.run()`에 `stdin`을
  지정하지 않아 일부 에이전트 셸 환경에서 `tests/test_build_release.py`가 간헐적으로
  `OSError: WinError 6`로 실패하던 문제 수정(`stdin=subprocess.DEVNULL` 추가). 앱
  동작과 무관, 테스트 환경 안정성만 개선.

---

## [zone-v1.5.1] 2026-10-02

Main 기준: v1.10.4 이후 main 1.10.5 / ba8bf5e

### 수정
- 상/하부 분석 탭을 확정 디자인 Artifact에 맞춰 비주얼 조정(기능 변경 없음): 7단계
  진행 안내 스텝 인디케이터 신설, 체크포인트 카드형 UI + 자동선택 배지, 편집 툴바를
  캔버스 전용 헤더로 이동, 좌측 이미지 목록에 상시 삭제 아이콘, 우측 존 비율 색상바,
  레시피·결과분석·진행상황 팝업 스타일 정비.

---

## [zone-v1.5.0] 2026-10-01

Main 기준: v1.10.4 이후 main 1.10.5 / ba8bf5e

### 추가
- 존 분석 탭을 "상/하부 분석"으로 명칭 변경, 탭 순서를 맨 앞으로 이동.
- 추론 탭에서 마지막 선택한 체크포인트를 상/하부 분석 탭이 자동 승계해 기본값으로 제안.
- 이미지 업로드 시 기존 목록에 이어서 추가(append)하고, 개별 이미지를 "목록에서 제거"
  (원본 파일은 보존)하는 기능.
- 영역(zone) 설정을 일괄적용 전용 레시피 팝업으로 재편 — 자동검출, 수동편집, 레시피
  저장·불러오기, 최근 레시피 자동 로드를 지원.
- 원 중심 정렬 버튼, 방향키 이동(1px/Shift 10px), 마우스 휠 지름 조절(5px/Shift 20px).
- 영역 설정을 추론 실행 전에도 할 수 있도록 활성화 조건 분리(브러시 보정 도구만 추론
  후 활성화 유지).
- 결과 분석 테이블에 "최대 blob 픽셀수" 열 추가, 같은 이미지의 존별 행을 그룹화 표시,
  이미지명/존 필터 바, 클립보드 복사(TSV) 기능.
- 체크포인트(.pt) 파일명에 학습 시작 날짜 포함.

### 수정
- 추론 방식을 sliding window로 고정(resize/sliding window 선택 UI 제거)하면서, 배치
  처리가 지금까지 선택과 무관하게 항상 resize 방식만 쓰던 숨은 버그를 함께 수정.
- BUG-035(GitHub 없음, P3): 상/하부 분석 탭이 기본 탭으로 뜨는 상태에서 앱 기동 직후
  체크포인트 자동 선택이 반영되지 않던 문제 수정.

---

## [zone-v1.4.0] 2026-08-31

Main 기준: v1.10.4 이후 main 1.10.5 / ba8bf5e

### 추가
- Zone 결정 방법을 일괄 적용, 일괄 적용 후 수정, 장별 적용의 3모드로 제공.
- 이미지별 원·블랍 삭제·브러시 편집 상태를 `.zone.json` 사이드카에 자동 저장하고
  이미지 재진입과 앱 재시작 후 복원.
- 기존 Zone이 있는 배치 대상은 전체 대체, Zone 없는 이미지만 적용, 취소 중 선택.

### 개선
- Zone 일괄 처리를 백그라운드 스레드로 이동하고 준비된 추론 컨텍스트를 배치당 한 번만
  생성해 재사용.
- 배치 전용 대형 추론 결과를 즉시 해제해 20MP 다중 이미지 처리의 메모리 누적 제거.
- 수동 브러시 스트로크를 rasterize-on-commit 캐시로 렌더링해 편집 응답성 개선.
- CPU 추론 시 GPU 사용 가능 여부를 단일 추론과 배치 처리 전에 안내.

### 빌드
- Zone installer 및 EXE 버전을 `1.4.0`으로 갱신.
- installer 출력 파일명: `SegmentationModelUIZone-Setup-1.4.0.exe`.

---

## [zone-v1.3.1] 2026-08-28

Main 기준: v1.9.0 이후 빌드 수정 c984f7e 선택 동기화

### 수정
- Python 3.12 installer 빌드에서 `c10.dll` WinError 1114를 일으킨 PyTorch wheel 대신
  검증된 PyTorch 2.7.1 cu128과 torchvision 0.22.1 조합으로 고정.
- 빌드 의존성 설치와 버전 검사를 통합해 다른 빌드 PC에서도 같은 CUDA 런타임을 패키징.

### 빌드
- zone installer 및 EXE 버전을 `1.3.1`로 갱신.

---

## [zone-v1.3.0] 2026-08-28

### 추가
- Zone 분석 VOC 편집을 원 편집, 브러시 그리기, 브러시 지우기, 연결 블랍 삭제,
  화면 이동, Undo의 라벨링 스타일 배타 툴바로 통합.
- 수동 그리기·지우기를 시간순으로 적용해 마지막 스트로크가 우선하며 혼합 Undo 지원.

### 변경
- 학습은 기존 patch training(`random_crop`) 기본값을 유지하고, 추론과 Zone 분석의
  기본 추론 방식을 `sliding_window`로 변경.

---

## [zone-v1.2.4] 2026-08-28

Main 기준: v1.9.0 이후 1.10.4 커밋 / 15c2282

### 수정
- 기존 `build\venv`가 Python 3.12가 아니거나 Python 실행 파일이 손상된 경우 자동 삭제 후 재생성.
- 의존성 설치 후에도 정확한 Python 3.12인지 재검증해 잘못된 환경의 빌드 진행 차단.

### 빌드
- zone installer 및 EXE 버전을 `1.2.4`로 갱신.

---

## [zone-v1.2.3] 2026-08-28

Main 기준: v1.9.0 이후 1.10.3 커밋 / 1518c01

### 수정
- 일반 PowerShell/CMD에서 `build\venv`를 자동 생성하고 CUDA PyTorch, 런타임 패키지,
  PyInstaller를 최초 1회 설치한 뒤 재사용.
- 사용자가 conda 또는 venv를 직접 활성화하지 않아도 zone installer를 빌드하도록 변경.

### 빌드
- zone installer 및 EXE 버전을 `1.2.3`으로 갱신.

---

## [zone-v1.2.2] 2026-08-28

Main 기준: v1.9.0 이후 1.10.2 커밋 / ac83412

### 수정
- GitHub #27: 일반 PowerShell/CMD에서 `WindowsApps\\python.exe` 실행 별칭을
  빌드 Python으로 오인하지 않도록 수정.
- 가상환경 활성화 없이 Windows Python Launcher의 시스템 Python 3.12를 우선 사용.

### 빌드
- zone installer 및 EXE 버전을 `1.2.2`로 갱신.

---

## [zone-v1.2.1] 2026-08-28

Main 기준: v1.9.0 이후 1.10.1 커밋 / 69af9f7

### 수정
- 빌드 전 전체 오프라인 런타임 패키지를 검사하고 동일한 Python으로 PyInstaller를 실행.
- 다른 Qt binding과 불필요한 Anaconda 개발 패키지 수집을 제외.
- Windows 설치본에서 CUDA Torch를 PyQt6보다 먼저 초기화해 `c10.dll` WinError 1114 방지.

### 빌드
- zone installer 및 EXE 버전을 `1.2.1`로 갱신.

---

## [zone-v1.2.0] 2026-08-28

Main 기준: v1.9.0 이후 1.10.0 대상 커밋 (94a74f9)

### 추가
- main의 GitHub #23 전체 이미지 비동기 추론, Best Model 및 학습 지표/그래프 저장 반영.
- zone 전체 이미지 비동기 추론과 resize/sliding-window 선택, `F` 오버레이 전환.
- installer 실행 직후 로딩 단계를 표시하는 시작 splash 화면.

### 수정 및 성능
- 추론·zone 오버레이 배경 밝기 유지.
- threshold 디바운스, 원 편집 완료 시 1회 존 계산, 줌·팬 보존과 대형 미리보기 복사 제거.
- 접근할 수 없는 최근 프로젝트 경로가 시작 창을 막지 않도록 안전 처리.

### 빌드
- zone installer 및 EXE 버전을 `1.2.0`으로 갱신.

---

## 동기화 준비 2026-08-28

Main 기준: v1.9.0 + 8 commits (434b169)

- GitHub #23 전체 이미지 비동기 추론, Best Model 및 학습 지표/그래프 저장 반영.
- 추론 오버레이 배경 밝기 유지와 슬라이더·줌/팬 UI 병목 개선 반영.
- zone 전용 전체 이미지/sliding-window 추론과 원·threshold 성능 개선은 그대로 유지.

---

## [zone-v1.1.0] 2026-08-27

Main 기준: v1.9.0 + 4 commits (450f520)

### 추가
- 라벨링 탭에서 여러 이미지를 선택해 한 번에 양품화하는 main 공통 기능.
- 원 우클릭 지름 변경, 신규 원의 중심 공유와 좌표 스케일링 경로 통합 (GitHub #13).
- 이미지 선택 즉시 원본 미리보기와 `픽셀 threshold` 명칭 제공 (GitHub #14).
- 기존 라벨 경계 채우기, 도구 타입과 무관한 동일 클래스 병합, 파일명 복사와
  내보내기 잠금 재시도 등 main 공통 개선 (GitHub #12, #15, #16, #17).
- 오토라벨링 원본 해상도 패치 추론, 학습 데이터 변경 잠금·병목 개선, 학습 설정
  휠 변경 차단과 학습 큐 중지 응답 개선.

### 빌드
- zone 버전을 `1.1.0`으로 갱신하고 main과 분리된 제품명·EXE·설치 폴더·AppId 및
  `zone-vX.Y.Z` 태그 체계를 유지.
- 동기화된 최신 main 기능 기준을 `v1.9.0 + 4 commits` / `450f520`으로 명시.

---

## [zone-v1.0.0] 2026-08-27

Main 기준: v1.8.0 + 19 commits (09933fd)

### 추가
- 존 분석 전용 탭과 원 검출·수동 편집·존별 통계·Excel 내보내기.
- main과 독립된 제품명, EXE, 설치 폴더, installer 파일명 및 Inno Setup AppId.
- main의 라벨링 이미지 다중선택 일괄 양품화 기능.

### 빌드
- `release.ini`에서 zone 버전과 제품 정보를 단일 관리.
- Windows EXE `FileVersion`/`ProductVersion`과 installer 버전을 자동 생성.
- zone 태그는 main의 `vX.Y.Z`와 구분되는 `zone-vX.Y.Z` 체계 사용.

---

## [v1.10.5] 2026-08-28

### 수정
- Python 3.12 빌드 환경에서 최신 CUDA PyTorch wheel의 `c10.dll`이 WinError 1114로
  초기화되지 않아 installer 빌드가 중단되던 문제 수정.
- Windows/Python 3.12/RTX 50 계열을 지원하는 검증 조합인 PyTorch 2.7.1 cu128과
  torchvision 0.22.1로 installer 런타임을 고정.
- 빌드 의존성 설치를 한 번의 해석 과정으로 통합해 torch/torchvision 호환 조합 유지.

### 빌드
- installer 및 EXE 버전을 `1.10.5`로 갱신.

---

## [v1.12.0] 2026-10-28

사용자 요청: 학습 진행 다이얼로그의 "멈춘 것처럼 보이는" 준비 구간(디바이스 선택
~ optimizer 구성) 가시화(`docs/specs/training-progress-and-stop-fix-2026-10-28.md`
작업 B/C). 작업 A(중지 버그 수정)는 이전 라운드(v1.11.1 이후 커밋 0be9c31/0d1c834)에서
이미 완료됨.

### 추가
- `app/core/trainer.py` — `TrainerWorker`에 `stage_changed(str)` 시그널 추가. `_train()`
  준비 단계 6곳(`device`/`dataset_train`/`dataset_val`/`dataloader`/`model_to_device`/
  `optimizer`) 진입 직전 emit, 각 단계 종료 시 `time.perf_counter()` 기반 경과시간을
  `log.info()`로 기록(작업 C — 느린 구간 측정 가능하게 만듦, 알고리즘 개선은 범위 밖).
- `app/widgets/training_progress_dialog.py` — 학습 큐(`q_box`) 바로 아래 준비 단계
  로그용 컴팩트 `QListWidget`(높이 상한 90px) 추가. `set_current_job()` 시 clear,
  신규 `append_stage(key)`로 `"[idx/6] {label}"` 형식 한 줄 append.
- `app/tabs/training_tab.py` — `_run_next_job()`에서 `stage_changed` 연결(신규
  `_on_stage_changed` 슬롯 → 다이얼로그 `append_stage` 호출), `_retire_trainer()`
  disconnect 목록에도 포함(stale-signal 방지).
- `app/core/i18n.py` — `train_progress.stage.*` ko/en 6쌍 신규(라벨만 번역,
  `"[idx/6]"` 포맷은 코드에서 조립).

### 변경
- `app/widgets/config_form.py` — 학습 설정 기본값 변경(사용자 요청). DataLoader
  `num_workers` 기본값을 CPU 코어 기반 자동 감지(상한 2) 대신 `0`(메인
  프로세스만 사용, 워커 기동 비용 없음)으로 고정. LR 스케쥴러 기본 선택을
  "없음" 대신 `ReduceLROnPlateau`(val loss 정체 시 자동 감소)로 변경
  (`findData("plateau")`로 `_SCHEDS` 순서 변경에도 안전하게 조회).

---

## [v1.11.1] 2026-10-28

사용자 요청: 존/R분석 탭 i18n 라운드(에디션 브랜치) 검증 중 발견된 공용
`InferenceImageList` 위젯의 영문 미지원(BUG-033)을 main에도 독립 적용.

### 수정
- `app/widgets/inference_image_list.py` — `editable=False`(추론 탭 기본값)일 때
  제목 라벨/검색창 placeholder/정렬 라벨이 `t()`를 거치지 않고 한국어로
  하드코딩돼 있던 것을 기존 `infer.image_list`/`browser.search_placeholder`/
  `browser.sort_label` 키 재사용으로 수정. 신규 번역 키 추가 없음.

---

## [v1.11.0] 2026-10-27

사용자 요청: 라벨링 탭의 툴바/뷰어(pan·zoom)/이미지 리스트를 재사용 가능한
공유 위젯으로 추출해 추론 탭(+차후 존분석/R분석 탭)에도 적용(`docs/specs/
shared-widgets-toolbar-viewer-imagelist-2026-10-27.md`, main 브랜치 1단계).

### 추가
- `app/widgets/view_transform.py` 신규 — `AnnotationCanvas`/`OverlayViewer`의
  wheel-zoom·fit-view·pan-drag·canvas→image 좌표변환 공식을 상태 없는 공용
  함수로 추출(완전 동일했던 복붙 중복 제거). GitHub #9 드래그 중 휠 줌 보강
  블록은 그대로 보존.
- `app/widgets/brush_toolbar.py` 신규 — 브러시/지우개/영역삭제/pan/undo/
  브러시크기를 라벨링 탭(+차후 존분석/R분석 탭) 공용 컨트롤러로 추출. 기존
  툴바 아이콘 순서(폴리곤/브러시/채움/지우개/영역삭제/select/pan, 단축키
  Q/W/E/R/D/A/S 1:1 공간 대응)는 완전히 그대로 유지.
- `app/widgets/inference_image_list.py`에 `show_status_icons`/`editable`
  생성자 플래그 추가 — 라벨링 탭 이미지 리스트가 상태 아이콘(●/✓/○)·범례·
  파일/폴더 추가·다중삭제·mutation guard·Ctrl+C 파일명 복사를 모두 지원하게
  됨(추론 탭은 기존 기본값 경로라 동작 무변경). 정렬 모드가 `status_done`/
  `status_todo` 포함 총 7종으로 확장.

### 변경
- 라벨링 탭 이미지 리스트가 `images/` 하위 폴더를 재귀 스캔한다(이전엔 최상위
  1단계만 스캔 — BUG-005로 죽어있던 폴더 그룹핑의 개선, 데이터 손실 없음).

### 제거
- `app/widgets/image_browser.py` 제거(`inference_image_list.py`로 완전 통합).

---

## [v1.10.5] 2026-08-28

### 수정
- Python 3.12 빌드 환경에서 최신 CUDA PyTorch wheel의 `c10.dll`이 WinError 1114로
  초기화되지 않아 installer 빌드가 중단되던 문제 수정.
- Windows/Python 3.12/RTX 50 계열을 지원하는 검증 조합인 PyTorch 2.7.1 cu128과
  torchvision 0.22.1로 installer 런타임을 고정.
- 빌드 의존성 설치를 한 번의 해석 과정으로 통합해 torch/torchvision 호환 조합 유지.

### 빌드
- installer 및 EXE 버전을 `1.10.5`로 갱신.

---

## [v1.10.4] 2026-08-28

### 수정
- 기존 `build\venv`가 Python 3.12가 아니거나 Python 실행 파일이 손상된 경우 자동 삭제 후 재생성.
- 의존성 설치 후 최종 검사에서도 Python 3.12를 다시 확인해 잘못된 환경의 빌드 진행 차단.

### 빌드
- installer 및 EXE 버전을 `1.10.4`로 갱신.

---

## [v1.10.3] 2026-08-28

### 수정
- 새 Python 3.12에 PyQt6 등 빌드 패키지가 없어 `build.bat`가 즉시 종료되던 문제 수정.
- 일반 PowerShell/CMD 실행 시 `build\venv`를 자동 생성하고 CUDA PyTorch, 런타임 패키지,
  PyInstaller를 최초 1회 설치한 뒤 이후 빌드에서 재사용.
- 사용자가 conda 또는 venv를 직접 활성화할 필요가 없도록 빌드 환경을 스크립트 내부에서 관리.

### 빌드
- installer 및 EXE 버전을 `1.10.3`으로 갱신.

---

## [v1.10.2] 2026-08-28

### 수정
- GitHub #27: 일반 PowerShell/CMD에서 `build.bat` 실행 시 Microsoft Store용
  `WindowsApps\\python.exe` 별칭을 실제 Python으로 오인하던 문제 수정.
- 가상환경 활성화 없이 `py -3.12`로 등록된 시스템 Python 3.12를 우선 선택하고,
  실패 시에도 `WindowsApps` 별칭은 후보에서 제외.
- 필수 패키지가 없으면 선택된 Python에 실행할 정확한 pip 명령을 안내.

### 빌드
- installer 및 EXE 버전을 `1.10.2`로 갱신.

---

## [v1.10.1] 2026-08-28

### 수정
- `build.bat`이 프로젝트 의존성이 없는 다른 Python을 선택해 설치판에서
  `ModuleNotFoundError: No module named 'PyQt6'`가 발생할 수 있던 문제 수정.
- 선택한 단일 Python에서 PyQt6·PyInstaller를 먼저 검증하고 메타데이터 생성과
  PyInstaller 빌드까지 같은 인터프리터만 사용.
- Anaconda의 간접 의존성이 PyQt5/PySide를 함께 수집하지 않도록 PyQt6 외 Qt 바인딩 제외.
- PyQt6·PyTorch·torchvision·OpenCV·NumPy·Pillow·Albumentations·openpyxl·matplotlib을
  빌드 전에 모두 검사해, 오프라인 설치본에서 필수 패키지가 누락되는 불완전한 빌드를 차단.
- Windows 독립 실행본에서 Qt가 CUDA Torch보다 먼저 초기화되어 `c10.dll` WinError 1114가
  발생하지 않도록 Torch를 PyQt6보다 먼저 로드.

### 빌드
- installer 및 EXE 버전을 `1.10.1`로 갱신.

---

## [v1.10.0] 2026-08-28

### 추가
- GitHub #23 전체 이미지 비동기 추론과 즉시 진행률 표시.
- 최고 IoU Best Model과 epoch별 train/val loss·IoU JSON/PNG 자동 저장.
- 추론 결과 원본/오버레이 `F` 전환.
- 설치판 실행 직후 준비 상태와 현재 로딩 단계를 표시하는 시작 splash 화면.

### 수정 및 성능
- 오버레이 불투명도가 배경 밝기를 바꾸지 않도록 전경에만 혼합 적용.
- 슬라이더 입력 디바운스, 오버레이 재블렌딩, 줌·팬 보존과 대형 결과 메모리 복사 축소.
- 접근할 수 없는 최근 프로젝트 경로 때문에 시작 창이 열리지 않는 문제 수정.

### 빌드
- installer 및 EXE 버전을 `1.10.0`으로 갱신.

---

## [v1.9.0] 2026-08-27

### 추가
- 추론 결과에 AI score·픽셀 threshold를 제공하고 blob별 결과를 Excel로 내보내는 기능.
- 라벨링 목록에서 선택한 이미지 파일명을 `Ctrl+C`로 복사하는 기능 (GitHub #17).
- 기존 라벨을 경계로 사용하는 브러시 채우기와 도구 타입과 무관한 동일 클래스 병합
  (GitHub #15, #12).
- 라벨링 탭에서 여러 이미지를 선택해 한 번에 양품화하는 일괄 처리 기능.

### 수정 및 성능
- 첫 이미지 자동 로드 문제(BUG-017), annotation 삭제·가져오기·내보내기 병목과
  내보내기 메모리 부족 문제를 개선.
- 사용 중인 내보내기 파일의 잠금이 풀릴 때까지 재시도하도록 처리 (GitHub #16).

### 빌드
- `release.ini`를 버전·제품 정보의 단일 기준으로 사용하고 Windows EXE 및 installer
  버전 메타데이터를 자동 생성·검증.

---

## [v1.8.0] 2026-08-25

### 사용자 요청
> "v1.7.0 이후 13커밋이 쌓였다. 새 버전으로 태깅하고, exe/installer를 처음부터 다시
> 빌드해서 GitHub Release로 업데이트해줘."

### 추가
- **어노테이션 가져오기(Import)**: 내보내기(export)의 짝 기능. 이미지 목록에서 기존
  어노테이션과 충돌 시 덮어쓰기/기존 유지 정책을 선택해 가져올 수 있음
- **SegFormer / SegNeXt / PIDNet 모델 프리셋**: 모델 탭 프리셋 팝업에 최신 논문·주요
  기업 공개 세그멘테이션 아키텍처 3종 추가

### 수정
- 팬 드래그 중 휠 줌 시 초점이 어긋나던 문제 수정 (GitHub #9)
- 지우개 브러시 실시간 프리뷰 색상을 빨강 대신 중립 회색으로 변경 (칠하기 색과 혼동 방지)
- 브러시 채우기 시 시작·끝점 강제 연결 제거 (의도치 않은 폐곡선 생성 방지)

### 기술
- `installer/setup.iss`: `MyAppVersion "1.8.0"`
- `app/widgets/import_dialog.py`(신규): 가져오기 다이얼로그 (충돌 정책 선택 포함)
- `app/model_presets/`(신규 패키지): `segformer.py` / `segnext.py` / `pidnet.py` 프리셋 정의

---

## [v1.7.0] 2026-08-24

### 사용자 요청
> "github에 installer 빌드된 것까지 포함해서 올려줘."

v1.6.0 이후 161커밋 동안 버전 태깅이 누락된 채 기능 추가·GitHub 이슈 대응·성능
개선·UI 재편이 누적됐다. 이번 릴리즈는 그 전체를 하나의 배포 단위로 묶어 정식
버전을 매기고, 처음으로 Windows 설치 프로그램(exe installer)을 제공한다.

### 추가
- **Windows exe + Inno Setup 인스톨러**: `build.spec`(PyInstaller onedir) +
  `installer/setup.iss`(Inno Setup) + `build.bat` 원클릭 빌드 스크립트. per-user
  설치(관리자 권한 불필요), 앱 로고("Vertex Frame") 아이콘을 exe/설치 프로그램에 적용
- **프로젝트 내보내기/가져오기** (GitHub #2): 프로젝트 전체(이미지·어노테이션·체크포인트·
  classes.json)를 zip으로 내보내고 되가져오기
- **UI 재편**: 라벨링/학습/추론 탭에 자유 리사이즈 서브스플리터 적용, 학습 탭 큐 영역·
  추론 탭 이미지 목록(검색/정렬/트리형 폴더) 개편
- **LR 스케줄러 9종**, **CUDA 종합 진단 팝업**, 단축키 왼손 QWER 재배치, 폴더 접기/펼치기
  그룹 헤더, 앱 종료 전 확인 팝업, RGB 채널별 그레이스케일 뷰어 등 다수 UX 개선
- **디자인 톤 정리**: 장식 이모지 제거 → 기능 아이콘 19종 SVG/QIcon화, i18n 전체 영어
  전환, matplotlib 손실 그래프·모델 탭 에디터 팔레트를 앱 표준 배색으로 정규화

### 수정 (성능)
- 어노테이션 개수 증가 시 로딩 지연 8.6×/2.1× 개선(GitHub #6-B), 오버레이 재생성 중
  깜빡임 제거(#6-A), 학습 데이터로더 이미지 캐시 + `num_workers` 자동 감지,
  추론 결과 미리보기 다운스케일, 이미지 브라우저 검색 디바운스, 앱 기동 시
  torchvision/albumentations 지연 임포트로 콜드 스타트 단축
- `rle_encode` 언더플로우로 인한 데이터 유실(BUG-002), 캔버스 유령 어노테이션·undo
  OOM 크래시(BUG-003/014), 서브스플리터 접힘·아이콘 stale 경쟁조건·브러시 크기
  다이얼로그 stray 어노테이션 등 버그 다수 수정 (BUG-005~015)
- `build.bat` 한글 텍스트 인코딩 깨짐(`chcp 65001`로도 못 잡던 파싱 오류) → ASCII 전환,
  `SetupIconFile` 경로를 dist 레이아웃 대신 소스 저장소 기준으로 고정

### 기술
- `installer/setup.iss`: `MyAppVersion "1.7.0"`, `PrivilegesRequired=lowest`,
  `SetupIconFile=..\app\resources\app_icon.ico`
- `app/resources/app_icon.ico` 신규 자산 (앱/exe/설치 프로그램 공용 아이콘)

---

## [v1.6.0] 2026-05-16

### 사용자 요청
> "첫번째 도구에서 선이 연결되는걸 찾는게 어려워. 적당히 합쳐질 것 같으면 합쳐질 수 있도록 해줘. UI 상에서 원의 테두리가 흰색으로 칠해진다거나 하는 방식으로 구별해줘. RGB를 분리해서 볼 수 있도록 해줘 — 이미지 뷰어 밑에 UI를 분리해서 만들어줘. 마우스가 올라가있는 부분의 pixel 값들도 옆에다가 label로 표시해줘."

### 추가
- **폴리곤 Snap-to-Close**: 첫 꼭짓점 15px 이내 접근 시 흰 원 + 반투명 내부 표시 → 클릭으로 즉시 닫기 (더블클릭 불필요)
- **채널 분리 뷰어**: 캔버스 하단 20px 스트립에 [원본] [R] [G] [B] 토글 버튼
- **픽셀 값 표시**: 마우스 위치의 `x,y  R:255  G:128  B:0` 실시간 표시 (스트립 우측)

### 기술
- `annotation_canvas.py`: `_poly_snap` 상태, `_SNAP_PX=15`, `pixel_hovered` 시그널, `set_channel()`, `_apply_channel_filter()`, `_cache_pixel_image()`
- `labeling_tab.py`: `_build_channel_strip()`, `_on_pixel_hovered()`, `QButtonGroup` 채널 뮤텍스

---

## [v1.5.0] 2026-05-16

### 사용자 요청
> "annotation 있는 이미지를 불러올 때 되게 느려."  
> "annotation 처음 그릴때는 속도가 괜찮은데 하나 그리고 나서부터 되게 느려."

### 수정 (성능)
- **`rle_encode` Python 루프 → numpy 벡터화**: 2000만 픽셀 순회 제거 → `np.diff + np.where` 수 ms
- **저장 백그라운드 스레드**: `_do_save` 에서 `rle_encode` 를 `threading.Thread(daemon=True)` 로 분리
- **오버레이 백그라운드 빌드**: `_OverlayWorker(QThread)` — 이미지 즉시 표시, 오버레이 비동기 교체

---

## [v1.4.0] 2026-05-16

### 사용자 요청
> "이미지 로드할때부터 엄청 느려. 여전히 너무 느려. 어디서 병목이 생기는지 확인할 수 있도록 log 를 만들어줘."  
> "perf log 기반으로 다시 최적화해줘."

### 추가
- **PerfProfiler** (`app/core/perf_logger.py`): 30프레임마다 단계별 avg/max ms 리포트 → `data/logs/perf.log`
- **Bbox 기반 마스크 연산**: `_resolve_overlap_and_merge`, `_consolidate_class_region` — 전체 20MP 대신 칠한 bbox 영역만 처리 (500× 빠름)
- **`_flood_erase` bbox 최적화**: connectedComponents 를 non-zero bbox 로 제한

### 수정 (성능)
- `_apply_eraser`: bbox 단락 평가로 빈 마스크 검사 개선
- `change_selected_class`: 선택 어노테이션 union bbox 기준 통합

---

## [v1.3.0] 2026-05-04

### 사용자 요청
> "라벨링할 때 엄청 버벅이고 있어. 이미지가 20MP 카메라로 찍은 거라 5000×4000 정도야."

### 추가 / 수정 (성능)
- **Display Pixmap 캐시**: zoom 버킷별 pre-scaled pixmap → 25× 작아진 blit 비용
- **Overlay 해상도 캡 (`MAX_OVERLAY_DIM=2048`)**: 80MB ARGB32 → 13MB (6× 감소)
- **Pan/Zoom 30Hz 쓰로틀**: `_schedule_repaint()` — mousemove마다 update() 방지
- **Smooth 백그라운드 스케일** (`_SmoothScaleWorker`): idle 후 고품질 보간을 비블로킹으로

---

## [v1.2.0] 2026-05-04

### 사용자 요청
> "추론에서 무조건 모델을 업로드해야 하는 것 같아. 체크포인트를 선택하면 학습할 때 사용했던 모델로만 돌릴 수 있게 해줘."

### 수정
- 체크포인트 선택 즉시 `config.model_source` 읽어 모델 자동 인스턴스화
- 추론 탭 체크포인트 테이블에 "모델" 컬럼 추가
- 체크포인트 메타에 `model_source` 저장 (trainer)

### 사용자 요청
> "학습할 때 AI 모델을 선택할 수 있도록 변경해줘. AI 모델 프리셋 부분 추가하는 건 따로 팝업을 띄우는 식으로 바꿔줘."

### 추가
- **`ModelPresetDialog`** 팝업: 7종 프리셋 목록 + 설명 + 에디터 불러오기
- **학습 탭 모델 선택**: 큐 작업별 모델 드롭다운 (현재 로드 or 프리셋)

### 사용자 요청
> "학습 창에서 손실 그래프 크기를 키워줘. Y축으로 키우라는 이야기야. EPOCH 메트릭과 체크포인트는 최소한으로 옆에다가 작게 만들거나 삭제해."

### 수정
- 손실 그래프 / 메트릭·체크포인트 수평 분할 (QSplitter)
- 메트릭 3열(Ep/Val/IoU), 10px 소형 폰트

---

## [v1.1.0] 2026-05-04

### 사용자 요청
> "학습할 때 PATCH TRAINING 이면 EPOCH 이랑 다르게 샘플링 이미지는 많아서 LOSS 들이 더 많이 나오지 않아? 이걸 시간 순서대로 TRAIN, VAL LOSS 그래프에 더 실시간으로 그려질 수 있게 하면 좋을 것 같은데."

### 추가
- **배치 레벨 실시간 Train Loss**: `training_started(total_batches)` 시그널 → 분수 epoch 좌표
- **EMA 스무딩** (α=0.08): 노이즈 많은 배치 loss 부드럽게
- **Step 카운터**: `Step N / M · ETA HH:MM` 스텝 기반 정확한 ETA
- **Epoch 경계 점선**: 그래프에 epoch 구분선 자동 추가

### 사용자 요청
> "현재 이미지에서의 라벨링 데이터를 볼 수 있는 리스트창을 하나 추가해주고 그 리스트에서 선택 시 해당 라벨링 데이터가 표시될 수 있게 해줘."  
> "같은 class라도 다른 곳에 있으면 따로 표시해줘."

### 추가
- 어노테이션 목록 패널 (오른쪽 180px): `#순번 [타입] 클래스명 @(cx,cy) · 면적px`
- 목록↔캔버스 양방향 선택 동기화

---

## [v1.0.0] 2026-04-19  (초기 완성 버전)

### 사용자 요청
> "PyTorch 세그멘테이션 모델을 위한 로컬 데스크탑 GUI. 라벨링 → 학습 → 추론 전 과정."

### 구현된 전체 기능

#### 🗂 프로젝트 시스템
- 시작 다이얼로그: 새 프로젝트 / 기존 열기 / 최근 목록
- 프로젝트별 격리: images / annotations / checkpoints / user_models / classes.json
- 전환 버튼 🔄, 폴더 열기 📁, 저장 경로 설정 (설정 탭)

#### 🎨 라벨링 탭
- 도구: 📐폴리곤 / 🖌브러시 / 🪣윤곽채우기 / 🧹지우개 / 🧲연결지우개 / 🔲선택 / ✋이동
- 브러시 픽셀 독점성 + 같은 클래스 연결 자동 병합
- 선택 도구: 단일클릭 / Shift다중 / 드래그범위 / 이동(드래그)
- 이미지 목록: 리스트뷰 ●라벨됨 ✓OK ○미라벨, 다중선택 Del 삭제
- ✅ OK 표시 / N 이전 이미지 어노테이션 복사
- ↑↓ 이미지 이동, Tab 패널 숨김
- 어노테이션 목록 패널 / 로그 패널

#### 🎯 학습 탭
- 다중 작업 큐 (이름 설정, 작업별 모델 선택)
- 실시간 손실 그래프 (배치 레벨 EMA + Epoch Val)
- Step 카운터 + 스텝 기반 ETA
- 진행 팝업 (비모달)
- 자동 patches_per_image 계산 버튼 🔄

#### 🔍 추론 탭
- resize / sliding_window 모드, 오버랩 설정
- 체크포인트 선택 시 모델 자동 결정
- 투명도 슬라이더, 클래스 범례

#### 🧠 모델 탭
- AST 샌드박스 검증 + 제한적 exec
- 📚 프리셋 팝업 (7종: U-Net / U-Net++ / Attention U-Net / DeepLabV3 계열 / FPN-SegNet)

#### ✨ 오토 라벨링
- 빠른 학습 + 오토 라벨링 (고정 30 epochs, 결함 우선 샘플링)
- 미리보기 팝업 → 합치기 확인 후 저장

#### ⚙️ 설정
- 언어 (한국어 / English)
- 단축키 테이블
- 로그 경로 (app.log / errors.log / perf.log)
- 프로젝트 저장 경로

#### 📤 내보내기
- JSON (상대좌표) / YOLO-seg / COCO 포맷

#### 🔧 성능 / 안정성
- GPU 사용 불가 시 팝업 (CPU 진행 여부)
- AMP CC<7.0 자동 비활성화
- Maxwell/Pascal GPU 경고
- 배경 overlay/smooth 스케일 (비블로킹)
- Bbox 기반 마스크 연산

---

## 버전 관리 정책

```
vMAJOR.MINOR.PATCH
  MAJOR: 핵심 아키텍처 변경 (프로젝트 시스템, 학습 파이프라인 등)
  MINOR: 기능 추가 (새 도구, 탭, 다이얼로그)
  PATCH: 버그 수정, 성능 개선, UI 조정
```

### 브랜치 전략 (권장)
```
main        — 안정 버전 (릴리즈 태그)
dev         — 개발 통합
feature/*   — 개별 기능
hotfix/*    — 긴급 수정
```

### 커밋 메시지 형식
```
feat: 새 기능 요약
fix:  버그 수정 요약
perf: 성능 개선
docs: 문서만 변경
refactor: 기능 변경 없는 코드 정리
```
