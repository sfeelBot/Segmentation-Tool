# 상/하부(Zone) 분석 탭 성능 조사 — 코드맵 + 지연 요소 (개선 전 기준선)

- 작성: 2026-11-11~12, 스파이크(선행 조사). **조사·실측만 — 코드 수정 없음.** 설계는 이 문서의 P-Z# 목록을 입력으로 다음 단계에서 한다.
- 대상: `feature/zone-analysis-tab` 워크트리, 측정 시점 HEAD `fd9ed94` (zone-v1.18.0). 아래 `파일:행`은 이 HEAD 기준.
- 사용자 요청: "상하부 쪽에서 사용하다 보면 느린 느낌이 많다."
- 벤치: `scripts/bench_zone_tab.py` (재실행 가능, 시나리오 이름·JSON 형식 고정, 인자·출력은 `bench_r_tab.py`와 같음 → 개선 후 `--compare`로 전/후 비교). R 탭 문서 [perf-2026-11-11-r-codemap.md](perf-2026-11-11-r-codemap.md)와 절 구성을 맞췄다.

## 1. 요약

**가장 느린 조작 5개** (메인 스레드가 멈추는 시간, 중앙값 ms. 이미지 1920×1200 / 4000×3000 / 5472×3648, 블랍 ~10개. `e30` = 그 이미지에 스트로크 30개(그리기 20 + 지우기 10) + 영역 삭제 3개가 있는 상태. 블랍 ~500개여도 ±10% 안쪽으로 같음)

| # | 조작 | 1920 | 4000 | 5472 | 원인(P-Z#) |
|---|---|---:|---:|---:|---|
| 1 | 영역 삭제 클릭 (e30) | 825 | **7201** | **15009** | 편집 재생 4회 (P-Z1, P-Z2) |
| 2 | 편집이 있는 이미지로 전환 (e30, 캐시 적중 / 미스) | 774 / 950 | **6049 / 7007** | **12772 / 14180** | 편집 재생 4회 + 오버레이 2회 + 결과를 안 쓰는 지우개 재생 (P-Z1, P-Z3, P-Z9) |
| 3 | Ctrl+Z (브러시·지우개·삭제 되돌리기, e30) | 673~701 | **5907~6217** | **12495~12547** | 편집 재생 3회 + 결과를 안 쓰는 지우개 재생 (P-Z1, P-Z2, P-Z9) |
| 4 | 브러시·지우개 스트로크 커밋 / 원 설정 적용 / 우측 패널 갱신 (e30) | 601~650 | **5442~5604** | **11290~11718** | 편집 재생 3회 (P-Z1, P-Z2) |
| 5 | 현재 이미지 결과표 열기 · 불투명도 1단계 · 오버레이 다시 보이기 · 조회 클릭(존/블랍) (e30) | 171~357 | **1697~3500** | **3655~7417** | 편집 재생 1~2회 (P-Z1, P-Z4, P-Z5, P-Z7) |

편집이 없어도(`e0`) 느린 것: AI 신뢰도·최소 픽셀·타겟 클래스 변경 1회 / 추론 결과 표시 / 처음 보는 추론 이미지로 전환 = 329~374 / **1168~1413** / **1717~1976** ms (P-Z6), 브러시 커밋 108 / 511 / 777 ms (P-Z10), 불투명도 1단계 70 / 209 / 255 ms (P-Z4).

**핵심 원인 3가지**

1. `zone_metrics.apply_manual_strokes`가 스트로크 **스탬프 1개마다** 이미지 전체 크기 bool 배열과 전체 프레임 OR를 한다(스탬프당 약 0.38 / 1.66 / 2.83 ms). e30은 스탬프 450 / 1020 / 1290개라 **편집 재생 1회 = 0.17 / 1.7 / 3.65 s**. R 탭 P-R1과 같은 함수(공용)다.
2. 그 재생 결과를 캐시하지 않고 한 조작 안에서 여러 번 다시 한다 — 우측 패널 갱신 1회 = 재생 3회(오버레이·비율·블랍표), 영역 삭제 = 4회, 편집 이미지 전환 = 4회 + 오버레이 2회. 불투명도·오버레이 보이기·존 클릭처럼 마스크와 무관한 조작도 재생을 1회씩 한다(과잉 무효화).
3. 오버레이 재합성이 매번 **원본 파일을 디스크에서 다시 풀 디코드**하고(34 / 57 ms @4000/5472) 원본 해상도 class_map을 복사·축소·블렌드한다(편집 없어도 1회 180~250 ms). 임계값 변경·추론 결과 표시는 이 합성을 3번(그중 1번은 바로 버려짐) + `refilter`의 블랍 통계(`np.minimum.at`) 480~800 ms.

**문제 아닌 것으로 확인**: 드래그 중 프레임(브러시·지우개 move, 팬, 줌 휠, paintEvent)은 offscreen 기준 0.7~1.9 ms로 16 ms를 넘지 않는다(1920 이미지에서 300 move짜리 긴 획 끝부분만 6.5 ms). 존 목록 행 선택 1~2 ms, 원 설정 모달 열기 3 ms, 사이드카 자동 저장 1.4~5.7 ms, 엑셀 내보내기 14~66 ms. 블랍 수(10 ↔ 500)에 따른 차이는 대부분 ±10% 이내.

기존 검증 수치(4000×3000, 스트로크 30개) 재확인: 스트로크 커밋 5403 → **5548 ms**, 불투명도/보이기 1929 → **1891~2071 ms**, 영역 삭제 클릭 7039 → **7201 ms**.

## 2. 코드맵

표기: `T` = `app/tabs/zone_analysis_tab.py`, `C` = `app/widgets/zone_canvas.py`, `OV` = `app/widgets/overlay_viewer.py`, `Z` = `app/core/zone_metrics.py`, `E` = `app/core/inference_engine.py`, `ST` = `app/core/zone_state_store.py`, `IL` = `app/widgets/inference_image_list.py`, `RD` = `app/widgets/zone_recipe_dialog.py`, `BD` = `app/widgets/zone_batch_result_dialog.py`.
**[무거움]** = 이미지 전체 크기에 비례하는 연산, **[중복]** = 한 조작에서 같은 무거운 호출이 2회 이상, **[과잉]** = 결과가 안 바뀌는데 다시 계산, **[디스크]** = 원본 이미지 파일을 다시 읽어 풀 디코드. 워커 스레드라고 적힌 것 외에는 전부 **메인 스레드**(UI 멈춤)다.

### 2.1 공통 무거운 블록 (여러 조작이 공유)

```
[R] 편집 재생  T._ai_and_final_masks (T:1297-1308)
      └ C.edited_masks (C:330-337)
          └ Z.apply_edits (Z:131-177)                                   [무거움]
              ├ np.isin(labels, removed_blob_ids)                         (전체 프레임)
              ├ Z.apply_manual_strokes (Z:112-128)  ← 삭제 지점마다 구간을 나눠 여러 번 호출
              │    스트로크마다 np.zeros(전체) + 스탬프(점)마다 Z.disk_mask (Z:42-66)
              │    = 스탬프마다 전체 프레임 bool 할당 + 전체 프레임 OR        [무거움 × 스탬프 수]
              └ 삭제 지점마다 cv2.floodFill (Z:173)
    결과 캐시 없음 — 같은 편집 상태라도 호출할 때마다 처음부터 다시 재생한다.

[O] 오버레이 재합성  T._show_overlay_state (T:1229-1236)
      └ T._reblend_overlay (T:1238-1267)
          ├ [R] 1회
          ├ class_map.copy() + 전체 프레임 boolean 대입 2회                 [무거움]
          └ E.colorize_class_map (E:320-337)  (편집 없으면 E.reblend E:300-317)
              ├ Image.open(원본).convert("RGB")                            [디스크][무거움]
              ├ load_classes()  (프로젝트 classes.json 읽기)
              └ E._colorize_and_blend (E:611-656): class_map→uint8→PIL NEAREST 축소(≤2048),
                 클래스별 색 채우기, 원본 BILINEAR 축소, float 블렌드, QImage 생성
      └ QPixmap.fromImage + C.set_pixmap(preserve_view=True)

[P] 우측 패널(존 목록) 갱신  T._recompute_zones (T:1457-1504)
      ├ [O] 1회                       ← [R] 1회 포함
      ├ T._current_zones → Z.zones_from_circles (Z:88-109): 원마다 Z.disk_mask 전체 프레임
      ├ T._compute_zone_percentages (T:1385-1397) → _current_target_mask → [R] 1회      [중복]
      ├ T._compute_zone_blob_rows (T:1399-1411) → [R] 1회 + Z.zone_blob_stats (Z:221-278)   [중복]
      │    (zone_blob_stats = connected components + bincount + 블랍×존 Python 루프)
      └ QListWidget.clear() + 존마다 T._make_zone_row_widget (T:1413-1455) 위젯 새로 생성
    → [P] 1회 = 편집 재생 3회 + 원본 디스크 디코드 1회.
```

기존 캐시가 덮는 범위:

| 캐시 | 위치 | 덮는 것 | 못 덮는 것 |
|---|---|---|---|
| `_preview_cache` (BUG-040) | T:262-278, T:811-826 | 이미지 전환 시 원본 디코드·2048 축소·QPixmap 생성(최대 20장) | 오버레이 합성 쪽의 원본 디코드([O]는 매번 디스크에서 다시 읽음) |
| `_target_cache` (R-PERF-1) | T:1167-1197 | 같은 (클래스, 신뢰도, 최소 픽셀)로 돌아올 때 `refilter` + 블랍 라벨링 | 이미지당 키 1개라 임계값을 바꾸면 매번 미스. 편집 재생([R])·오버레이([O])·우측 패널([P])은 캐시 대상 아님 |
| `_detected_ids_cache` | T:1088-1145 | 이미지 전환 시 클래스 콤보 구성용 `np.unique` | — |
| `_suppress_recompute` (BUG-040) | T:851-856, T:1458 | 전환 중 `set_state` 복원 전의 `_recompute_zones` 1회 | 같은 구간의 `_show_overlay_state` 1회(T:1204)는 그대로 돈다 → 전환마다 [O] 2회 |

### 2.2 조작별 흐름

**이미지 전환 (목록 클릭)** — Zone 탭은 이전/다음 버튼·단축키가 연결돼 있지 않다(목록은 다중 선택 모드라 1장만 선택됐을 때만 전환).
```
IL._on_selection_changed_multi (IL:616) → image_selected → T._on_list_image_selected (T:797-863)
  ├ 저장 타이머가 돌고 있으면 T._flush_state (T:865-880) 동기 저장(json + fsync)
  ├ _preview_cache 미스: Image.open+convert+thumbnail(2048) + _rgb_to_qpixmap        [디스크][무거움]
  ├ C.set_blob_data(None, None), T._set_tool
  ├ 추론 결과 있음: T._setup_target_classes (T:1088-1145) → T._on_target_changed (T:1147-1214)
  │    ├ _target_cache 적중(같은 임계값) → refilter 스킵
  │    ├ C.set_blob_data(labels, stats)
  │    ├ [O] 1회                                         [중복: 아래 set_state 뒤에 또 함]
  │    └ T._recompute_zones → _suppress_recompute로 스킵
  └ ST.load_state(path) → C.set_state (C:492-519)
       ├ C._replay_erase_strokes (C:428-441): 지우개 스탬프마다 disk_mask 전체 프레임 → _erase_mask_np  [과잉: 아무도 안 읽음]
       ├ C._rebuild_stroke_overlay (C:418-426)                                                      [과잉: 아무도 안 그림]
       └ circles_changed + circles_committed → T._recompute_zones → [P] 1회 (= [O] + [R]×3)
  → 편집 있는 이미지로 전환 = [O] 2회(디스크 디코드 2회) + [R] 4회.
```

**"현재 이미지만 추론" → 결과 수신 후 표시** (forward는 `_ZoneInferenceWorker` 워커, 범위 밖)
```
T._run_inference (T:1003-1058): _results/_target_cache/_detected_ids_cache에서 해당 경로 제거
워커 → result_ready → T._on_inference_result (T:1060-1074) → T._setup_target_classes
  ├ np.unique(class_map) (캐시 미스)                                            [무거움]
  └ T._on_target_changed
       ├ E.refilter (E:254-297): 원본 디코드 [디스크], E._compute_blobs_and_filter
       │   (클래스마다 CC8 + np.minimum.at/maximum.at 전체 픽셀 + 블랍 Python 루프 + np.isin),
       │   E._colorize_and_blend로 오버레이 생성                                  [과잉: 바로 아래에서 버려짐]
       ├ class_map == cid → Z.compute_blob_labels (CC4)                         [무거움]
       ├ C.set_blob_data → [O] 1회 → T._recompute_zones → [P]([O] 1회 더)          [중복]
  → 결과 1장 표시에 원본 디코드 3회, 오버레이 합성 3회.
```

**타겟 클래스 변경 / AI 신뢰도·최소 픽셀 변경** — 슬라이더·스핀은 150 ms 디바운스(`_threshold_timer`) 뒤 위와 같은 `T._on_target_changed` 전체. 값이 바뀌면 `_target_cache` 키가 달라 항상 refilter. `C.set_blob_data`가 **수동 편집(스트로크·삭제)과 Undo 스택을 지운다**(의도된 동작으로 주석에 적혀 있음).

**브러시 그리기·지우기**
```
mousePress (C:679-744): C._push_undo → C._erase_paint_stroke
mouseMove 1회 (C:746-779): C._erase_paint_stroke (C:366-387) — 반지름 40% 간격으로 스탬프 보간,
     스탬프마다 C._erase_stamp (C:344-359): bbox 국소 갱신이라 가벼움(단 _erase_mask_np는 [과잉])
     + update() → C.paintEvent (C:615-638) → C._paint_current_stroke (C:662-675):
       진행 중 획의 **모든 스탬프**를 매 프레임 다시 그림 (획이 길수록 프레임이 느려짐)
mouseRelease = 스트로크 커밋 (C:788-800): _manual_strokes에 추가, C._rasterize_stroke (C:401-416, [과잉]),
     erase_changed → T._recompute_zones → [P] (= [O] + [R]×3), _save_timer.start
```

**영역 삭제 클릭** (`TOOL_ERASER_FLOOD`)
```
C.mousePressEvent → C._handle_blob_click (C:533-550): C.edited_masks([R]) 로 클릭 지점 판정
  → _removed_points 추가 → blob_deleted → T._on_blob_deleted (T:1313-1320) → T._recompute_zones [P]
  → [R] 4회 + [O] 1회. 삭제 지점이 n개면 [R] 1회 안에서 apply_manual_strokes가 n+1 구간으로 나뉘어 돈다.
```

**조회 클릭(도구 없음) — 블랍 선택 / 존 선택**
```
C.mouseReleaseEvent 조회 경로 (C:804-829)
  ├ blob_clicked는 **항상** emit → T._on_canvas_blob_clicked (T:1535-1563)
  │    ├ [R] 1회 (클릭이 마스크 밖이어도 먼저 재생부터 한다)                       [과잉]
  │    └ 마스크 위면 Z.compute_blob_labels(final) + Z.zones_from_circles + Z.zone_blob_stats(CC 1회 더)
  └ 원 안이면 C.set_highlighted_zone + zone_clicked → T._on_canvas_zone_clicked (목록 행 선택만, 가벼움)
  → 존만 고르려는 클릭도 편집이 있으면 [R] 1회만큼 멈춘다.
우측 존 목록 행 클릭: T._on_zone_row_selected (T:1511) → C.set_highlighted_zone (QPainterPath, 가벼움)
```

**Ctrl+Z** — `C.keyPressEvent` (C:870-905) / 툴바 → `C.undo` (C:521-531) → `C.set_state` → `_replay_erase_strokes`·`_rebuild_stroke_overlay`([과잉]) + `circles_committed` → [P]. 원 편집 Undo·브러시 Undo·삭제 Undo 모두 같은 경로.

**불투명도 슬라이더 / 오버레이 보이기·숨기기(F)**
```
슬라이더 → T._on_overlay_opacity_changed (T:1269-1272) → 75 ms 디바운스 → T._show_overlay_state → [O]
보이기(F / 눈 아이콘) → T._set_overlay_visible (T:1219-1227) → [O]; 숨기기는 원본 pixmap만 다시 붙임(가벼움)
  → 투명도만 바꾸는데도 편집 재생 [R] + 원본 디스크 디코드 + 색칠을 처음부터.                [과잉]
```

**줌·팬·paintEvent** — `OV.wheelEvent`(OV:79-83)·팬(OV:85-112)은 변환만 바꾸고 `update()`. `C.paintEvent` = `OV.paintEvent`(OV:59-75, ≤2048 pixmap 1장 drawPixmap) + 원/존 하이라이트 경로 + 진행 중 획. 이미지 크기와 무관.

**원 설정(레시피) 모달 열기·적용**
```
열기: T._on_open_recipe_dialog (T:1681-1694) → RD.__init__: 자체 ZoneCanvas + 미리보기 pixmap(≤2048),
      RD._refresh_recipe_list (RD:184-188) 저장된 레시피 파일 전부 load (레시피 수에 비례)
적용: Z.scale_circles → C.set_circles (C:173-190) → circles_changed + circles_committed → [P]
원 이동/크기 확정(메인 캔버스는 편집 비활성 — 모달 안에서만 편집)도 circles_committed → [P].
```

**배치 "영역 적용"** — `T._on_batch_process` (T:1777-1819): **메인 스레드에서** 대상 전체의 `ST.load_state`(사이드카 JSON) → 기존 존 확인 모달 → `_ZoneCircleLayoutWorker` (T:135-156, 워커): 이미지마다 `Image.open(...).convert("RGB").size` — 주석은 "헤더만"이라 하지만 `convert`가 **풀 디코드**를 한다 [디스크][과잉] → 원 스케일 → `ST.save_state`. 진행 신호마다 `T._on_batch_progress` (T:1821-1854)가 목록 아이콘 갱신.

**"전체 결과 보기" / 현재 이미지 결과표 / 엑셀**
```
전체 결과 보기 T._on_view_all_results (T:1586-1617): T._flush_state → _ZoneViewAllWorker (T:180-207, 워커):
   이미지마다 _compute_zone_rows (T:218-247) = apply_edits + zones_from_circles + zone_stats + zone_blob_stats
   → T._on_view_all_ready → BD 생성(셀마다 QTableWidgetItem, BD:162/220)
현재 이미지 결과표 T._on_export_single (T:1567-1584): 메인 스레드에서 [R] 2회(비율·블랍표) + zone_blob_stats → BD
엑셀 BD._on_export (BD:255-270) → export_zone_percentages_to_excel (openpyxl, 메인 스레드)
결과 이미지 일괄 저장 T._on_save_all_images (T:1650-1677): 추론된 이미지마다 overlay_image.save(PNG) 메인 스레드
```

**사이드카 자동 저장** — 편집 시그널마다 `_save_timer`(500 ms) 재시작 → `T._flush_state` → `ST.save_state` (임시 파일 + `json.dump` + `os.fsync` + `os.replace`). 편집량에 비례하는 JSON 크기, 메인 스레드.

## 3. 측정 표

중앙값 ms (반복 3회, 드래그류는 move 7~20회, 긴 획은 300 move, 배치는 1회). 창 1920×1040(캔버스 1516×767), 픽스처 JPEG(q92, 383 / 1840 / 3190 KB), 목록 12장(추론 결과는 2장에만 주입). 열 이름 `WxH` = 블랍 ~10개, `WxH_b500` = 블랍 ~500개(60×60 격자). `e0` = 편집 없음, `e30` = 스트로크 30 + 영역 삭제 3, `build` = e0에서 e30을 쌓는 동안의 개별 조작. 원본 JSON: 스크래치 `perf_2026_11_11/zone_before.json` (396행, 조작마다 `breakdown`에 함수별 호출 수·포함 시간).

시나리오 이름 풀이: `image_switch_noresult_*` = 추론 전 이미지 전환(미리보기 캐시 미스/적중) · `image_switch_list_warm/cold` = 추론된 이미지로 목록 클릭 전환(`_target_cache`·`_preview_cache` 적중/미스 — cold는 "추론 후 처음 보는 이미지"와 같음) · `image_switch_away` = 편집 직후(저장 타이머 대기 중) 편집 없는 이미지로 떠나기 · `infer_result_display` = 현재 이미지 추론 결과 수신 → 표시 · `zone_click_select` / `blob_click_select` = 도구 없음 상태의 조회 클릭(마스크 밖 존 / 블랍 위) · `zone_row_select` = 우측 존 목록 행 클릭 · `opacity_step` = 불투명도 슬라이더 1단계(75 ms 디바운스 제외) · `recompute_zones` = 원 확정(`circles_committed`) 시 우측 패널 갱신 · `recipe_apply` = 원 설정 모달 "적용"(`set_circles`) · `conf_threshold_change`/`min_px_change` = 150 ms 디바운스 제외 · `export_single_open` = "현재 이미지 결과표" · `view_all_results` = "전체 결과 보기"(워커 포함, 표 준비까지 벽시계) · `batch_apply_circles` = 12장 영역 적용(워커 대기 포함).

| 시나리오 | 편집 | 1920x1200 | 1920x1200_b500 | 4000x3000 | 4000x3000_b500 | 5472x3648 | 5472x3648_b500 |
|---|---|---:|---:|---:|---:|---:|---:|
| image_switch_noresult_cold | e0 | 15.5 | 15.8 | 95.2 | 96.3 | 134.7 | 138.4 |
| image_switch_noresult_warm | e0 | 2.1 | 2.7 | 1.9 | 1.9 | 2.0 | 2.3 |
| infer_result_display | e0 | 344.3 | 366.2 | 1167.8 | 1227.3 | 1716.9 | 1764.7 |
| paint_repaint | e0 | 0.7 | 0.7 | 0.7 | 0.6 | 0.7 | 1.7 |
| zoom_wheel | e0 | 1.0 | 1.0 | 0.9 | 1.0 | 0.9 | 1.8 |
| pan_move | e0 | 0.7 | 0.8 | 0.8 | 0.7 | 0.8 | 0.9 |
| zone_click_select | e0 | 2.4 | 2.6 | 8.1 | 8.0 | 11.0 | 12.8 |
| blob_click_select | e0 | 17.7 | 23.2 | 97.7 | 96.3 | 127.3 | 158.7 |
| zone_row_select | e0 | 1.4 | 1.4 | 1.1 | 1.2 | 1.3 | 1.6 |
| opacity_step | e0 | 69.8 | 87.1 | 209.4 | 222.8 | 254.9 | 283.5 |
| overlay_toggle_off | e0 | 2.9 | 2.8 | 3.5 | 3.5 | 3.2 | 3.7 |
| overlay_toggle_on | e0 | 75.6 | 84.6 | 209.4 | 230.5 | 257.8 | 280.9 |
| recompute_zones | e0 | 92.7 | 106.2 | 303.9 | 336.3 | 411.0 | 452.1 |
| recipe_apply | e0 | 90.0 | 106.2 | 300.6 | 338.2 | 411.2 | 449.7 |
| brush_move | e0 | 1.2 | 1.1 | 1.0 | 0.9 | 1.0 | 1.0 |
| brush_commit | e0 | 108.1 | 125.8 | 511.2 | 511.9 | 776.9 | 836.4 |
| undo_brush | e0 | 90.4 | 108.1 | 314.5 | 332.7 | 419.2 | 458.4 |
| eraser_move | e0 | 1.2 | 1.2 | 1.0 | 0.9 | 1.0 | 0.9 |
| eraser_commit | e0 | 107.7 | 130.4 | 549.8 | 519.0 | 778.7 | 821.6 |
| undo_eraser | e0 | 89.3 | 107.9 | 350.5 | 329.6 | 410.5 | 452.2 |
| delete_blob | e0 | 101.5 | 110.5 | 336.0 | 350.9 | 436.7 | 490.4 |
| undo_delete | e0 | 96.5 | 109.8 | 315.3 | 335.7 | 406.8 | 453.6 |
| autosave_flush | e0 | 1.5 | 1.6 | 1.4 | 1.4 | 1.4 | 1.4 |
| export_single_open | e0 | 24.5 | 27.2 | 103.5 | 109.8 | 160.8 | 175.9 |
| view_all_results | e0 | 48.8 | 60.0 | 206.3 | 219.9 | 314.5 | 364.9 |
| image_switch_list_warm | e0 | 162.8 | 197.8 | 514.1 | 577.1 | 670.3 | 740.3 |
| image_switch_list_cold | e0 | 347.6 | 390.2 | 1413.1 | 1415.5 | 1975.6 | 2084.6 |
| image_switch_away | e0 | 162.2 | 198.1 | 503.6 | 570.7 | 678.2 | 732.8 |
| target_class_change | e0 | 337.6 | 368.5 | 1188.3 | 1254.9 | 1723.7 | 1810.1 |
| conf_threshold_change | e0 | 328.5 | 360.3 | 1212.2 | 1257.9 | 1729.0 | 1837.6 |
| min_px_change | e0 | 373.8 | 365.2 | 1218.8 | 1263.2 | 1761.0 | 1843.6 |
| brush_move_long_first20 | e0 | 1.2 | 1.2 | 0.8 | 0.8 | 0.8 | 0.8 |
| brush_move_long_last20 | e0 | 6.5 | 6.6 | 1.8 | 1.9 | 1.9 | 1.9 |
| brush_commit_long | e0 | 463.7 | 459.6 | 1925.7 | 1958.4 | 3248.2 | 3325.8 |
| stroke_commit_build_first5 | build | 158.7 | 191.3 | 854.7 | 832.1 | 1508.2 | 1551.5 |
| stroke_commit_build_last5 | build | 644.3 | 638.2 | 5122.3 | 4999.1 | 10596.7 | 10607.2 |
| delete_blob_build | build | 810.0 | 856.4 | 7285.0 | 7032.5 | 14973.4 | 14978.9 |
| paint_repaint | e30 | 0.7 | 0.8 | 0.7 | 0.7 | 0.7 | 0.7 |
| zoom_wheel | e30 | 0.9 | 0.9 | 1.0 | 0.9 | 0.9 | 0.9 |
| pan_move | e30 | 0.8 | 0.7 | 0.7 | 0.7 | 0.7 | 0.8 |
| zone_click_select | e30 | 170.6 | 171.4 | 1696.6 | 1673.7 | 3655.4 | 3660.2 |
| blob_click_select | e30 | 196.2 | 208.9 | 1930.8 | 1774.6 | 3789.8 | 3767.9 |
| zone_row_select | e30 | 1.6 | 1.6 | 1.8 | 1.2 | 1.6 | 1.5 |
| opacity_step | e30 | 245.6 | 270.0 | 2071.4 | 1886.9 | 3891.0 | 3921.6 |
| overlay_toggle_off | e30 | 2.9 | 3.0 | 3.1 | 3.2 | 3.2 | 3.1 |
| overlay_toggle_on | e30 | 241.9 | 289.4 | 1891.3 | 1879.9 | 3919.1 | 3886.8 |
| recompute_zones | e30 | 601.1 | 639.2 | 5603.9 | 5358.7 | 11290.1 | 11357.1 |
| recipe_apply | e30 | 649.8 | 624.9 | 5442.2 | 5335.3 | 11323.7 | 11365.8 |
| brush_move | e30 | 1.2 | 1.3 | 1.0 | 0.9 | 1.2 | 1.0 |
| brush_commit | e30 | 622.5 | 659.2 | 5548.0 | 5556.4 | 11676.7 | 11718.1 |
| undo_brush | e30 | 690.8 | 692.0 | 5906.8 | 5895.5 | 12495.3 | 12544.8 |
| eraser_move | e30 | 1.1 | 1.3 | 1.0 | 1.0 | 1.0 | 1.1 |
| eraser_commit | e30 | 649.2 | 652.5 | 5480.4 | 5516.7 | 11711.4 | 11660.0 |
| undo_eraser | e30 | 672.8 | 697.9 | 6216.5 | 5913.0 | 12524.5 | 12542.8 |
| delete_blob | e30 | 824.6 | 818.3 | 7200.7 | 7066.2 | 15009.4 | 15074.7 |
| undo_delete | e30 | 688.2 | 701.0 | 6022.0 | 5899.5 | 12547.1 | 12562.1 |
| autosave_flush | e30 | 2.8 | 2.5 | 4.7 | 4.4 | 5.7 | 5.4 |
| export_single_open | e30 | 357.3 | 391.2 | 3500.3 | 3434.9 | 7416.8 | 7458.6 |
| view_all_results | e30 | 246.6 | 252.2 | 1875.2 | 1898.6 | 3941.8 | 3972.7 |
| image_switch_list_warm | e30 | 773.8 | 852.9 | 6049.1 | 6127.1 | 12771.9 | 12848.8 |
| image_switch_list_cold | e30 | 950.0 | 983.2 | 7007.3 | 7034.2 | 14179.6 | 14123.4 |
| image_switch_away | e30 | 163.2 | 193.0 | 519.1 | 572.5 | 682.8 | 730.9 |
| recipe_open | e30 | 2.5 | 3.6 | 2.5 | 2.9 | 2.9 | 3.2 |
| excel_export | e30 | 15.0 | 59.5 | 14.1 | 65.8 | 14.1 | 60.5 |
| save_all_images | e30 | 603.2 | 598.5 | 718.1 | 718.7 | 643.6 | 635.4 |
| batch_apply_circles | e30 | 187.1 | 133.9 | 568.0 | 501.2 | 877.1 | 783.1 |

### 3.1 함수별 분해 (4000×3000, 조작 1회 평균, 계측 래퍼의 포함 시간)

| 조작 | 총 ms | 주요 내역 (호출 수 × / 포함 ms) |
|---|---:|---|
| delete_blob e30 | 7201 | `edited_masks` 4× / 6937 (`apply_manual_strokes` 8×) · `_recompute_zones` 1× / 5503 · `_show_overlay_state` 1× / 1975 |
| image_switch_list_warm e30 | 6049 | `set_state` 1× / 5845 · `apply_edits` 4× / 5013 · `_show_overlay_state` 2× / 2100 · `_replay_erase_strokes` 1× / 523 (결과 미사용) · 원본 디코드 2× / 72 |
| image_switch_list_cold e30 | 7007 | 위 + `refilter` 1× / 683 (`_compute_blobs_and_filter` 482) · 원본 디코드 4× / 143 |
| undo_brush e30 | 5907 | `apply_edits` 3× · `_replay_erase_strokes` 1× / 560 (결과 미사용) · `_rebuild_stroke_overlay` 14 |
| brush_commit e30 | 5548 | `_recompute_zones` 1× / 5528 = `_ai_and_final_masks` 3× / 5243 (`_show_overlay_state` 1939 · `_compute_zone_blob_rows` 1808 · `_compute_zone_percentages` 1766) |
| export_single_open e30 | 3500 | `_ai_and_final_masks` 2× / 3400 · `zone_blob_stats` 40 · `zone_stats` 28 |
| opacity_step e30 | 2071 | `_ai_and_final_masks` 1× / 1846 · `colorize_class_map` 1× / 185 |
| zone_click_select e30 | 1697 | `_on_canvas_blob_clicked` → `_ai_and_final_masks` 1× / 1738 (마스크 밖 클릭이라 그 뒤는 바로 반환) |
| brush_commit e0 | 511 | `_recompute_zones` 498 = `_show_overlay_state` 272 + 스트로크 1개 재생 3× / 189 |
| opacity_step e0 | 209 | `colorize_class_map` 179 = 원본 디코드 34 + `_colorize_and_blend` 141 (PIL resize 2× 52) |
| conf_threshold_change e0 | 1212 | `refilter` 681 (`_compute_blobs_and_filter` 479) · `_colorize_and_blend` 3× / 423 (그중 refilter 안의 1회는 결과를 버림) · `_recompute_zones` 298 |
| infer_result_display e0 | 1168 | `refilter` 700 · `_colorize_and_blend` 3× / 419 · 원본 디코드 3× / 101 · `_recompute_zones` 200 |
| image_switch_list_warm e0 | 514 | `_show_overlay_state` 2× / 423 (원본 디코드 2× / 70) |
| image_switch_noresult_cold e0 | 95 | PIL `thumbnail` 50 · 디코드 33 · QPixmap 3 |
| batch_apply_circles e30 | 568 | (워커) 원본 풀 디코드 12× / 431 · `save_state` 12× / 31 · (메인) `load_state` 24× / 10 |

스탬프당 재생 단가(편집 재생 1회 ÷ 스탬프 수, `zone_click_select e30` 기준): 0.38 / 1.66 / 2.83 ms. 그중 `disk_mask` 자체는 0.08 ms/스탬프(4000) — `np.zeros`는 지연 할당이라 싸고, 비용은 **전체 프레임 `stroke_mask |=` OR**에 있다. bbox 국소 스탬프로 바꾸면 결과가 동일하면서 3152 → 21 ms가 되는 것을 R 탭 스파이크가 같은 함수로 이미 실측했다(R 문서 3.2).

### 3.2 cProfile (4000×3000, 누적 시간 상위)

`--profile-dir`로 4000×3000 / 블랍 ~10 / 반복 1회에서 주요 시나리오를 덤프했다(스크래치 `perf_2026_11_11/zone_prof/4000x3000_<시나리오>_<편집>.txt`). 상위 함수는 3.1의 계측 래퍼 분해와 같은 순서로 나온다. 예:

```
# infer_result_display e0 4000x3000 — 1190.8 ms
  1.115  T:1147 _on_target_changed
  0.683  E:254  refilter
  0.478  E:518  _compute_blobs_and_filter
  0.416  E:611  _colorize_and_blend   (3회)
  0.410  T:1229 _show_overlay_state    (2회)
  0.352  E:320  colorize_class_map     (2회)
  0.203  T:1457 _recompute_zones
# opacity_step e0 4000x3000 — 207.1 ms
  0.198  T:1238 _reblend_overlay
  0.174  E:320  colorize_class_map
  0.137  E:611  _colorize_and_blend
  0.051  PIL Image.resize (2회)
  0.033  PIL Image.convert (원본 디코드)
```

## 4. 지연 요소 목록

체감 영향: **상** = 한 번에 0.5 s 이상 멈춤 또는 매우 자주 100 ms 이상, **중** = 100 ms 안팎이거나 연속 조작이 끊김, **하** = 수십 ms 이하 또는 드문 경우. 측정값은 1920 / 4000 / 5472 순(ms), 블랍 ~10개.

### P-Z1 — 편집 재생이 스탬프마다 전체 프레임 연산 (상)
- 조작: 편집이 있는 이미지에서의 거의 모든 조작 — 스트로크 커밋, 영역 삭제, Ctrl+Z, 이미지 전환, 불투명도, 오버레이 보이기, 조회 클릭, 결과표, 전체 결과 보기, 원 적용.
- 측정: 편집 재생 1회(e30) = 약 170 / 1700 / 3650 ms, 스탬프당 0.38 / 1.66 / 2.83 ms. 스트로크를 쌓을수록 커밋이 느려짐(1~5번째 159 / 855 / 1508 → 26~30번째 644 / 5122 / 10597). 긴 획 1개(move 300)만으로도 커밋 464 / 1926 / 3248.
- 원인: `Z.apply_manual_strokes` (zone_metrics.py:112-128) + `Z.disk_mask` (:42-66). 호출 경로 `Z.apply_edits` (:131-177) ← `C.edited_masks` (zone_canvas.py:330-337) ← `T._ai_and_final_masks` (zone_analysis_tab.py:1297-1308).
- 왜 느린가: 반지름 20 px 원 하나를 찍는 데 이미지 전체 크기 bool 배열을 만들고 전체 프레임 OR를 한다. 비용이 (스탬프 수 × 이미지 픽셀 수)에 비례.
- 개선 방향 후보: 원의 bbox 안에서만 스탬프(R 스파이크 프로토타입 3152 → 21 ms, 결과 동일). R 탭과 공용 함수라 한 번 고치면 양쪽에 적용. 이것만으로 P-Z2~5·7·14의 대부분이 같이 줄어든다.

### P-Z2 — 한 조작 안에서 편집 재생을 3~4번 반복, 결과 캐시 없음 (상)
- 조작: 스트로크 커밋, Ctrl+Z, 원 적용·확정(우측 패널 갱신) = 재생 3회, 영역 삭제 클릭 = 4회.
- 측정(e30): 커밋 623 / 5548 / 11677, Ctrl+Z 673~701 / 5907~6217 / 12495~12547, 삭제 825 / 7201 / 15009, 원 적용 650 / 5442 / 11324.
- 원인: `T._recompute_zones` (T:1457-1504)가 `_show_overlay_state`(T:1229) → `_reblend_overlay`(T:1251), `_compute_zone_percentages`(T:1385-1397), `_compute_zone_blob_rows`(T:1399-1411)에서 각각 `_ai_and_final_masks()`를 새로 부른다. 삭제는 `C._handle_blob_click` (C:544)의 판정용 재생이 1회 더.
- 왜 느린가: 편집 상태가 같아도 최종 마스크를 매번 처음부터 다시 만든다(BUG-040 B는 `zones_from_circles`만 공유하게 했고 마스크는 공유하지 않음). 삭제 지점이 있으면 재생 1회 안에서도 `apply_manual_strokes`가 구간별로 나뉘어 돈다.
- 개선 방향 후보: 캔버스 편집 상태 버전(카운터)을 키로 `(ai_mask, final_mask)`를 1개 캐시해 조작당 1회만 계산. 더 나아가 스트로크 커밋은 이전 최종 마스크에 새 스트로크 1개만 증분 적용.

### P-Z3 — 이미지 전환 시 오버레이 2회 + 재생 4회 (상)
- 조작: 목록에서 추론된 이미지 클릭.
- 측정: e0 163 / 514 / 670 (캐시 적중), e30 774 / 6049 / 12772 (적중) · 950 / 7007 / 14180 (미스).
- 원인: `T._on_list_image_selected` (T:797-863) → `_setup_target_classes` → `_on_target_changed`의 `_show_overlay_state` (T:1204) 1회, 그 뒤 `C.set_state` (C:492-519)가 `circles_committed`를 내 `_recompute_zones` [P] 1회 더. `_suppress_recompute` (BUG-040)는 첫 `_recompute_zones`만 막고 T:1204의 합성은 막지 않는다.
- 왜 느린가: 사이드카 복원 전 상태로 한 번, 복원 후 상태로 한 번 — 첫 합성은 곧바로 덮인다. 복원 후 [P]가 재생 3회.
- 개선 방향 후보: 전환 중엔 `_show_overlay_state`도 억제하고 `set_state` 뒤 1회만 합성(+ P-Z2 캐시로 재생 1회).

### P-Z4 — 오버레이 재합성이 매번 원본 디코드 + 원본 해상도 처리 + 재생 (상, 편집 없으면 중)
- 조작: 불투명도 슬라이더(75 ms 디바운스마다 1회), 오버레이 다시 보이기(F), 그리고 [O]를 포함하는 모든 조작.
- 측정: 불투명도 1단계 e0 70 / 209 / 255, e30 246 / 2071 / 3891. 보이기 e0 76 / 209 / 258, e30 242 / 1891 / 3919. 그중 원본 디코드 34(4000) / 57(5472) ms, `_colorize_and_blend` 141(4000).
- 원인: `T._reblend_overlay` (T:1238-1267) → `E.colorize_class_map` (E:320-337) / `E.reblend` (E:300-317)가 호출마다 `Image.open(...).convert("RGB")` + `load_classes()`; `E._colorize_and_blend` (E:611-656)가 원본 해상도 class_map을 uint8 변환·축소, 원본을 BILINEAR 축소, float 블렌드. 재생([R])도 매번.
- 왜 느린가: 투명도는 최종 블렌드 계수만 바뀌는데 디코드·축소·마스크 재생·색칠을 처음부터 다시 한다(과잉 무효화). 미리보기 캐시(`_preview_cache`, 이미 2048로 축소된 원본)가 있는데 쓰지 않는다.
- 개선 방향 후보: 축소된 원본(미리보기)과 축소된 색칠 레이어를 캐시해 불투명도 변경은 블렌드만(수 ms 예상). 마스크가 바뀔 때만 색칠 레이어 갱신.

### P-Z5 — 조회 클릭(도구 없음)이 존 선택에도 블랍 계산부터 함 (상, 편집 없으면 하~중)
- 조작: 캔버스 클릭으로 존/블랍 선택.
- 측정: 존 클릭 e0 2.4 / 8.1 / 11.0, e30 171 / 1697 / 3655. 블랍 클릭 e0 18 / 98 / 127, e30 196 / 1931 / 3790.
- 원인: `C.mouseReleaseEvent` 조회 경로 (C:804-829)가 `blob_clicked`를 항상 emit → `T._on_canvas_blob_clicked` (T:1535-1563)가 먼저 `_ai_and_final_masks()` 재생, 마스크 위면 `compute_blob_labels(final)` + `zones_from_circles` + `zone_blob_stats`(CC 1회 더).
- 왜 느린가: 마스크 밖(존만 고르려는) 클릭도 재생 1회를 다 하고 나서야 "마스크 아님"을 안다. 블랍 1개 정보를 위해 전체 프레임 라벨링 2회 + 전 블랍×존 통계.
- 개선 방향 후보: P-Z2 캐시된 최종 마스크·라벨맵 재사용, 클릭한 라벨 1개의 통계만 계산(라벨 bbox 안에서).

### P-Z6 — 임계값·타겟 클래스 변경 / 추론 결과 표시 / 처음 보는 추론 이미지 전환 (상)
- 조작: AI 신뢰도 슬라이더·최소 픽셀 스핀(150 ms 디바운스마다), 타겟 클래스 콤보, 추론 결과 수신, `_target_cache` 미스 전환.
- 측정(e0): 신뢰도 1회 329 / 1212 / 1729, 최소 픽셀 374 / 1219 / 1761, 타겟 338 / 1188 / 1724, 결과 표시 344 / 1168 / 1717, cold 전환 348 / 1413 / 1976.
- 원인: `T._on_target_changed` (T:1147-1214) → `E.refilter` (E:254-297: 원본 디코드 + `E._compute_blobs_and_filter` (E:518-588, 클래스마다 CC8 + 전체 픽셀 `np.minimum.at`/`np.maximum.at` + 블랍 Python 루프 + `np.isin`) + 오버레이 합성) → `Z.compute_blob_labels` (CC4) → T:1204 [O] → `_recompute_zones` [P]([O] 1회 더).
- 왜 느린가: refilter가 만든 오버레이는 곧바로 `_reblend_overlay`가 덮어 버려지고(합성 3회 중 1회 낭비), 원본 디코드 3회. bbox 계산을 `ufunc.at`(느린 산포 연산)으로 전체 픽셀에 한다 — CC가 이미 주는 stats(bbox·면적)를 쓰면 필요 없음. `_target_cache`는 이미지당 키 1개라 슬라이더를 움직이는 동안 매번 미스.
- 개선 방향 후보: CC stats로 bbox 대체, refilter에서 오버레이 생성 생략(탭이 어차피 다시 합성), 합성 1회로 통합. 드래그 중 연속 변경은 워커로 빼거나 슬라이더 놓을 때만 적용.
- 부수 관찰(성능 아님, 사용자 결정이 필요할 수 있음): 임계값·타겟 변경 시 `C.set_blob_data`가 그 이미지의 수동 편집과 Undo 스택을 지운다(T:1186-1189 주석상 의도). 그래서 이 조작들은 e0에서만 측정했다.

### P-Z7 — "현재 이미지 결과표"가 메인 스레드에서 재생 2회 (중, 편집 많으면 상)
- 측정: e0 25 / 104 / 161, e30 357 / 3500 / 7417.
- 원인: `T._on_export_single` (T:1567-1584) → `_compute_zone_percentages` + `_compute_zone_blob_rows` 각각 `_ai_and_final_masks()`.
- 왜 느린가: P-Z2와 같은 중복 재생. "전체 결과 보기"는 워커로 옮겼지만(2026-10-30) 단일 결과표는 메인 스레드 그대로.
- 개선 방향 후보: P-Z2 캐시 공유(재생 0~1회). 우측 패널이 이미 계산한 비율·블랍표를 그대로 재사용.

### P-Z8 — 결과 이미지 일괄 저장이 메인 스레드 PNG 인코딩 (중, 추정치 포함)
- 측정: 추론된 2장 저장 603 / 718 / 644 ms(오버레이는 ≤2048이라 이미지 크기와 거의 무관, 장당 약 300 ms). 50장이면 약 15 s 멈춤으로 **추정**(미측정).
- 원인: `T._on_save_all_images` (T:1650-1677) 루프에서 `QImage.save(png)`.
- 개선 방향 후보: 워커(QThread)로 옮기고 진행률 표시, 또는 PNG 압축 레벨 낮추기.

### P-Z9 — 아무도 읽지 않는 지우개 마스크·스트로크 오버레이를 계속 갱신 (중)
- 측정: `C._replay_erase_strokes` — 이미지 전환·Ctrl+Z(e30, 지우개 스트로크 10개)마다 523~560(4000) / 1165~1177(5472) ms. `_rebuild_stroke_overlay`·`_rasterize_stroke` 6~15 ms. mouseMove마다의 `_erase_mask_np` 갱신은 국소라 미미.
- 원인: `C._replay_erase_strokes` (C:428-441, 지우개 스탬프마다 전체 프레임 `disk_mask`), `C._rebuild_stroke_overlay` (C:418-426), `C._rasterize_stroke` (C:401-416). `_erase_mask_np`·`_stroke_overlay`·`erase_mask()`는 `app/` 전체에서 읽는 곳이 없다(paintEvent도 그리지 않음).
- 왜 느린가: 예전 구조의 잔재 — 결과를 버리는 전체 프레임 연산.
- 개선 방향 후보: 해당 상태와 갱신 코드 삭제(테스트 docstring 1곳만 언급). 순수 삭제라 위험이 낮다.

### P-Z10 — 편집 없는 상태의 스트로크 커밋·Ctrl+Z·삭제도 300 ms 이상 (중)
- 측정(e0): 커밋 108 / 511 / 777, Ctrl+Z 90 / 315 / 419, 삭제 102 / 336 / 437, 원 확정 93 / 304 / 411.
- 원인: P-Z4의 합성(180~250 ms) + 우측 패널의 `zone_stats`·`zone_blob_stats`·`zones_from_circles`(원마다 전체 프레임 `disk_mask`) 약 100 ms. 커밋은 새 스트로크 1개 재생 3회(약 190 ms @4000)가 더해짐.
- 개선 방향 후보: P-Z1·2·4가 풀리면 대부분 사라짐. 남는 존 통계는 원 bbox 안에서만 계산하거나 존 마스크를 원이 바뀔 때만 캐시.

### P-Z11 — 배치 "영역 적용"이 이미지마다 원본 풀 디코드 (하 — 워커라 UI는 살아 있음)
- 측정: 12장 187 / 568 / 877 ms(벽시계), 그중 워커의 디코드 431(4000) / 715(5472) ms. 메인 스레드 몫은 대상 사이드카 `load_state` 24회 약 10 ms.
- 원인: `_ZoneCircleLayoutWorker.run` (T:142-143) `Image.open(...).convert("RGB").size` — 주석은 "헤더만"이지만 `convert`가 전체 디코드. 크기만 필요.
- 개선 방향 후보: `Image.open(p).size`(헤더만 읽음)로 교체. 수백 장 배치에서 차이가 커진다(4000×3000 장당 약 36 ms → 1 ms 미만, 추정).

### P-Z12 — 추론 전 이미지 전환의 미리보기 생성 (하)
- 측정: 캐시 미스 16 / 95 / 135 ms (그중 PIL `thumbnail` 50, 디코드 33 @4000), 적중 2 ms.
- 원인: `T._on_list_image_selected` (T:811-826) `Image.open+convert+thumbnail(BILINEAR)`.
- 개선 방향 후보: `Image.draft()`(JPEG DCT 축소 디코드)로 디코드·축소를 한 번에, 또는 인접 이미지 미리 디코드.

### P-Z13 — 진행 중 획 미리보기가 스탬프 개수에 비례 (하)
- 측정: 긴 획(move 300)의 처음 20 move 1.2 / 0.8 / 0.8 → 마지막 20 move 6.5 / 1.8 / 1.9 ms. 16 ms 미만.
- 원인: `C._paint_current_stroke` (C:662-675)가 매 프레임 진행 중 획의 모든 스탬프를 다시 그림.
- 개선 방향 후보: 지금은 손댈 필요 없음. 실제 디스플레이에서 끊김이 보고되면 QPainterPath 누적이나 오프스크린 버퍼로.

### P-Z14 — "전체 결과 보기" 대기 시간이 편집 재생에 비례 (하 — 워커)
- 측정: 추론 2장 e0 49 / 206 / 315, e30 247 / 1875 / 3942 ms (클릭 ~ 표 준비 벽시계, UI는 진행 대화상자로 살아 있음).
- 원인: `_ZoneViewAllWorker.run` (T:180-207) → `_compute_zone_rows` (T:218-247) → `Z.apply_edits` (P-Z1).
- 개선 방향 후보: P-Z1로 같이 해결.

## 5. 측정 방법·한계

- 실행: `QT_QPA_PLATFORM=offscreen`, `SEG_DATA_DIR`=스크래치 임시 폴더, Windows 11 / Python 3.14.2 / PyQt6 6.11.0 / numpy 2.4.4 / OpenCV 5.0.0 / Pillow 12.1.1, 창 1920×1040. 전체 2540 s. 재실행: `python scripts/bench_zone_tab.py --out zone_after.json --compare zone_before.json` (인자 `--sizes --blobs --repeat --batch-repeat --images --ext --window --fixtures --compare --profile-dir`).
- 시간 = 조작 함수 + `processEvents` 3회(그리기 포함)의 벽시계. 함수별 분해는 계측 래퍼(포함 시간이라 중첩끼리 겹침). cProfile은 별도 실행(래퍼 없음, 반복 1회).
- 추론 forward는 범위 밖 — 합성한 `InferenceResult`(class_map int64, 신뢰도 0.9 균일)를 `_on_inference_result`로 주입. 실제 모델 출력은 블랍 모양이 불규칙해 CC·통계 비용이 조금 다를 수 있다. "현재 이미지만 추론" 버튼 클릭 자체(모델 로드·워커 시작)는 측정하지 않았다.
- 디바운스 대기(임계값 150 ms, 불투명도 75 ms, 자동 저장 500 ms)는 빼고, 타이머가 부르는 처리만 직접 실행해 쟀다. 실사용에서 슬라이더를 끄는 동안은 디바운스마다 이 비용이 반복된다.
- offscreen 래스터라 실제 디스플레이 합성·GPU 드라이버 비용은 없다 — 드래그 프레임 수치는 하한으로 봐야 한다.
- 같은 PC에서 R 탭 스파이크·검증 에이전트가 동시에 돌던 구간이 있어 절대값에 ±10% 정도 흔들림이 있을 수 있다(반복 간 min~max 폭은 대부분 5% 이내).
- 측정 못 한 것: 결과 이미지 50장 이상 일괄 저장(2장으로 장당 비용만), 원 설정 모달 안에서의 원 드래그·저장된 레시피가 많은 상태(레시피 0개로만 측정), 수백 장 배치, 추론 결과가 20장 넘게 쌓여 캐시(LRU 20)가 밀려나는 경우, 메모리 사용량.
- 편집량 e30의 구성: 스트로크 30개(8점 × 40 px 간격, 브러시 40 px, 그리기 20 + 지우기 10) + 영역 삭제 3개, 스탬프 수 450 / 1020 / 1290(이미지가 클수록 같은 제스처라도 원본 px 간격이 커서 스탬프가 많아짐). 좌표는 4000×3000 기준을 축별로 스케일.
- 원시 데이터: 스크래치 `perf_2026_11_11/zone_before.json`, `zone_before.summary.md`, `zone_bd_4000.txt`(함수별 분해 발췌), `zone_prof/`(cProfile).
