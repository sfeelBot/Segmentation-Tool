# 스파이크 (Spike) 로그

## 2026-11-11 — R 분석 탭 코드맵 + 지연 요소 실측 (시작)

- 상태: 진행중.
- 요청: "R부 사용 중 느린 느낌" — R 분석 탭의 조작별 호출 흐름(코드맵)을 만들고 느린 지점을 실측으로 특정. 설계·구현은 다음 단계(범위 밖), 앱 코드 수정 없음.
- 대상: `app/tabs/r_analysis_tab.py`, `app/widgets/r_roi_canvas.py`, `app/core/r_analysis_metrics.py`, `app/widgets/r_cell_panel.py`, `app/widgets/overlay_viewer.py`, `app/core/r_cell_store.py`, `app/widgets/inference_image_list.py`. 기준 커밋 `8deb1a4`(zone-v1.17.1).
- 계획: 재실행 가능한 벤치 `scripts/bench_r_tab.py`(offscreen, 실제 `RAnalysisTab` + QTest) → 이미지 3종 × 편집량 2종 × 셀 이미지 5/50장 측정 → `docs/specs/perf-2026-11-11-r-codemap.md`.

## 2026-11-11 — Zone(상/하부) 분석 탭 코드맵 + 지연 요소 실측 (시작)

- 상태: 진행중.
- 요청: "상하부 사용 중 느린 느낌" — Zone 분석 탭의 조작별 호출 흐름(코드맵)을 만들고 느린 지점을 실측으로 특정. 설계·구현은 다음 단계(범위 밖), 앱 코드 수정 없음.
- 대상: `app/tabs/zone_analysis_tab.py`, `app/widgets/zone_canvas.py`, `app/core/zone_metrics.py`, `app/core/zone_state_store.py`, `app/core/zone_recipe_store.py`, `app/widgets/zone_batch_result_dialog.py`, `app/widgets/zone_recipe_dialog.py`, `app/widgets/overlay_viewer.py`, `app/core/inference_engine.py`, `app/widgets/inference_image_list.py`. 기준 커밋 `fd9ed94`(zone-v1.18.0).
- 계획: 재실행 가능한 벤치 `scripts/bench_zone_tab.py`(offscreen, 실제 `ZoneAnalysisTab` + 가짜 추론 결과 주입 + QTest, R 탭 벤치와 같은 인자·JSON 형식) → 이미지 3종 × 편집량 2종 × 블랍 수 2종 측정 → `docs/specs/perf-2026-11-11-zone-codemap.md`.
- (진행 메모 1) 코드 읽기 완료 — 탭/캔버스/metrics/engine 호출 흐름 파악. 핵심 후보: (a) `_recompute_zones` 1회에 `apply_edits` 재생 3회(오버레이·비율·블랍표) + 삭제 클릭은 4회, (b) `apply_manual_strokes`/`disk_mask`가 스탬프마다 전체 프레임 할당, (c) `colorize_class_map`/`reblend`/`refilter`가 호출마다 원본 이미지를 디스크에서 다시 디코드, (d) `_on_target_changed`에서 오버레이 합성 3회, (e) 도구 없음 클릭마다 `_on_canvas_blob_clicked`가 재생+CC 2회, (f) 캔버스 `_erase_mask_np`/`_stroke_overlay`는 쓰기 전용(읽는 곳 없음). 다음: `scripts/bench_zone_tab.py` 작성(공용부는 `bench_r_tab`에서 import) → 실측.

## 2026-11-11 — R 분석 탭 코드맵 + 지연 요소 실측 (종료)

- 상태: 완료 (문서 마감은 2026-11-12). 코드 수정·커밋 없음.
- 산출물: `docs/specs/perf-2026-11-11-r-codemap.md`(요약 / 코드맵 / 측정 표 / P-R1~P-R15 / 측정 방법·한계), `scripts/bench_r_tab.py`(재실행 벤치, `--compare`로 전/후 비교, `--profile-dir`로 cProfile). 기준선 결과는 스크래치 `perf_2026_11_11/r_before.json`(240행, 측정 HEAD `fd9ed94`).
- 결과(4000×3000, 스트로크 30개 기준): 편집 이미지로 전환 4087 ms, 50장 셀 전환 3922 ms, Delete·Ctrl+Z·설정 변경 2013~2163 ms, 세션 열기 631 ms, 브러시 커밋 127~184 ms. 기존에 알려진 수치(2 s / 4 s / 129 ms / 60 ms / 23 ms) 모두 재현.
- 핵심 원인: (1) `zone_metrics.apply_manual_strokes`가 점마다 전체 프레임 연산(점당 1.7 ms) — bbox 국소 스탬프 프로토타입은 같은 결과로 3152 → 21 ms, (2) 이미지 전환 시 전체 재생 2회·분모/스펙/불투명도 변경에도 마스크 재생성 등 중복·과잉 무효화, (3) 썸네일·마스크 오버레이를 매번 원본 해상도로 메인 스레드에서 생성.
- 가설 중 기각: 드래그 중 프레임(ROI·브러시·팬·줌)은 offscreen 기준 2~4 ms로 문제없음, 우측 패널 갱신 1~5 ms, `_set_current_image` 재진입 없음.
- 못 잰 것: 실제 디스플레이 합성 비용(offscreen 한계), 콜드 디스크, 아주 긴 스트로크(P-R13)·지우개 재생(P-R15)·편집 있는 첫 이미지의 세션 열기(P-R8)는 추정.
- 주의: P-R1의 근본 수정 지점인 `app/core/zone_metrics.py`는 Zone 탭과 공용 — Zone 쪽 설계와 한 번에 맞출 것.
- (진행 메모 2) `scripts/bench_zone_tab.py` 작성(공용 측정 틀은 `bench_r_tab` import). 스모크 1회차: 영역 삭제 클릭 assert 실패 → 원인 확인 중.
- (진행 메모 3) 스모크 통과(1920x1200, 132행, 100s; 좌표 축별 스케일 수정). 본 측정 백그라운드 실행 → `perf_2026_11_11/zone_before.json`, 이어서 4000x3000 cProfile(`perf_2026_11_11/zone_prof/`).
- (진행 메모 4) 문서 `docs/specs/perf-2026-11-11-zone-codemap.md` 2절(코드맵) 작성 완료. 1·3·4·5절은 본 측정 결과 대기(1920 조합부터 진행 중).
- (진행 메모 5) 본 측정 완료: `zone_before.json` 396행, 2540s. cProfile 진행 중.
- (진행 메모 6) cProfile 완료(`perf_2026_11_11/zone_prof/`, 4000x3000). 문서 1·3·4·5절 작성 완료.

## 2026-11-11 — Zone(상/하부) 분석 탭 코드맵 + 지연 요소 실측 (종료)

- 상태: 완료. 앱 코드 수정·커밋 없음.
- 산출물: `docs/specs/perf-2026-11-11-zone-codemap.md`(요약·코드맵·측정 표·P-Z1~P-Z14·방법/한계), `scripts/bench_zone_tab.py`(신규, 미커밋 — R 벤치의 측정 틀 import, `--compare`로 전/후 비교), 스크래치 `perf_2026_11_11/zone_before.json`(396행) + `.summary.md` + `zone_prof/`.
- 핵심: 편집 재생(`zone_metrics.apply_manual_strokes`, 스탬프마다 전체 프레임 OR — R 탭 P-R1과 같은 함수)이 캐시 없이 조작당 3~4회 반복 → e30 기준 영역 삭제 825 / 7201 / 15009 ms, 편집 이미지 전환 774 / 6049 / 12772 ms, Ctrl+Z·스트로크 커밋 약 0.6 / 5.5~6.2 / 11.3~12.5 s. 오버레이 재합성은 호출마다 원본을 디스크에서 다시 디코드(편집 없어도 불투명도 1단계 209 ms @4000). 임계값·타겟 변경·추론 결과 표시 e0에서 1.2 / 1.7 s(@4000/5472). 지우개 마스크 재생(결과 미사용)이 전환·Undo마다 0.5~1.2 s.
- 미측정: 50장 이상 결과 이미지 저장, 레시피 다수 상태의 원 설정 모달, 수백 장 배치, 캐시 LRU 20 초과, 메모리.
