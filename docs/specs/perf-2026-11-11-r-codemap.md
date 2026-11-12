# R 분석 탭 성능 조사 — 코드맵 + 지연 요소 (개선 전 기준선)

- 작성: 2026-11-11~12, 스파이크(선행 조사). **조사·실측만 — 코드 수정 없음.** 설계는 이 문서의 P-R# 목록을 입력으로 다음 단계에서 한다.
- 대상: `feature/zone-analysis-tab` 워크트리, 측정 시점 HEAD `fd9ed94` (R 탭 관련 파일은 `8deb1a4`와 동일, `zone_metrics.py`만 +107행). 아래 `파일:행`은 이 HEAD 기준.
- 사용자 요청: "R부 사용하다 보면 느린 느낌이 많다."
- 벤치: `scripts/bench_r_tab.py` (재실행 가능, 시나리오 이름·JSON 형식 고정 → 개선 후 `--compare`로 전/후 비교).

## 1. 요약

**가장 느린 조작 5개** (메인 스레드가 멈추는 시간, 중앙값 ms. 이미지 크기 1920×1200 / 4000×3000 / 5472×3648. `e30` = 그 이미지에 브러시 스트로크 30개 + 블랍 삭제 3개가 있는 상태)

| # | 조작 | 1920 | 4000 | 5472 | 원인(P-R#) |
|---|---|---:|---:|---:|---|
| 1 | 편집이 있는 이미지로 전환 (e30) | 363 | **4087** | **9756** | 스트로크 전체 재생 ×2 (P-R1, P-R2) |
| 2 | 이미지 50장짜리 셀로 전환 | 804 | **3922** | **6484** | 썸네일 스트립이 원본을 전부 풀 디코드 (P-R3) |
| 3 | Delete · Ctrl+Z · threshold/분모/스펙 변경 · 자동 검출 토글 · 현재 이미지 검출 (e30) | 162~209 | **2013~2163** | **4833~4954** | 스트로크 전체 재생 ×1 (P-R1, P-R7) |
| 4 | 세션 열기 (셀 5장+50장, 편집 없음) | 117 | 631 | 1103 | 썸네일(P-R3) + 중복 마스크 이미지 생성(P-R2) + 불필요한 재검출(P-R8) |
| 5 | 브러시·지우개 스트로크 커밋 (놓을 때마다) | 22~28 | 127~184 | 268~284 | 점당 전체 프레임 연산(P-R1) + RGBA 마스크 이미지 전체 재생성(P-R6) |

참고: 일괄 검출은 워커 스레드라 UI는 살아 있지만(최대 멈춤 16/80/120 ms), **편집된 이미지가 1장이라도 섞이면** 5장 셀이 422 / 4314 / 10085 ms로 늘고 그중 절반은 끝난 뒤 메인 스레드 멈춤이다(P-R9).

**핵심 원인 3가지**

1. `zone_metrics.apply_manual_strokes`가 스트로크 **점 1개마다** 이미지 전체 크기 배열을 새로 만들고 전체 프레임 OR를 한다(점당 0.45 / 1.7 / 3.0 ms). 캐시가 무효화되는 모든 조작(Delete, Ctrl+Z, 이미지 전환, 검출 마스크 교체)이 이 전체 재생을 탄다. → 1~3위·5위의 주범.
2. 같은 무거운 일을 한 조작 안에서 두 번 하거나(이미지 전환 = 전체 재생 2회, 폴더 가져오기 = 썸네일 2회), 마스크와 무관한 변경(분모·스펙, 불투명도)에도 마스크를 다시 만든다(과잉 무효화).
3. 썸네일·마스크 오버레이 이미지를 매번 원본 해상도로, 메인 스레드에서, 캐시 없이 만든다.

**문제 아닌 것으로 확인**: 드래그 중 프레임(ROI 이동/리사이즈, 브러시 이동, 팬, 줌)은 offscreen 기준 2~4 ms/프레임으로 16 ms를 넘지 않는다. 우측 패널·표 갱신도 1~5 ms. (단, 실제 디스플레이 합성 비용은 미측정 — 5절.)

기존 검증에서 알려진 수치(4000×3000, 스트로크 30개) 재확인: Delete·Ctrl+Z 약 2 s → **2043 / 2035 ms**, 편집 이미지 전환 약 4 s → **4087 ms**, 브러시 커밋 129 ms → **127~184 ms**, 불투명도 60 ms → **57~79 ms**, 편집 후 첫 블랍 클릭 23 ms → **24~25 ms**. 모두 재현.

## 2. 코드맵

표기: `T` = `app/tabs/r_analysis_tab.py`, `C` = `app/widgets/r_roi_canvas.py`, `OV` = `app/widgets/overlay_viewer.py`, `M` = `app/core/r_analysis_metrics.py`, `Z` = `app/core/zone_metrics.py`, `CP` = `app/widgets/r_cell_panel.py`, `IL` = `app/widgets/inference_image_list.py`, `SP` = `app/widgets/r_settings_panel.py`, `ST` = `app/core/r_cell_store.py`.
**[무거움]** = 이미지 전체 크기에 비례하는 연산, **[중복]** = 한 조작에서 같은 무거운 호출이 2회 이상, **[과잉]** = 결과가 안 바뀌는데 다시 계산. 모든 경로는 일괄 검출 워커를 빼고 **메인 스레드**.

### 2.1 공통 무거운 블록 (여러 조작이 공유)

```
[A] C._rebuild_mask_image (C:528-537)                      ← 마스크가 바뀌는 모든 조작의 종착점
    ├─ C.effective_mask (C:199-229)
    │    ├─ 캐시 적중(검출 마스크 동일 + 스트로크 수 동일) → 그대로 반환
    │    ├─ 증분: 스트로크만 늘었으면 Z.apply_manual_strokes(캐시, 새 스트로크) (C:219)   [무거움: 새 점마다 전체 프레임]
    │    └─ 전체 재생: M.apply_edits(검출, 전체 스트로크, 삭제 영역) (C:224 → M:50-72)     [무거움: 전체 점 × 전체 프레임]
    │         └─ Z.apply_manual_strokes (Z:112-128)
    │              ├─ mask.copy()
    │              └─ 스트로크마다: np.zeros(전체) → 점마다 `stroke_mask |= Z.disk_mask(...)` (Z:42, 전체 크기 배열 새로 할당)
    │                             → result[stroke_mask] = draw
    └─ RGBA 오버레이 생성: mask.any → np.zeros((H,W,4)) → rgba[mask]=색+알파 → QImage(RGBA8888).copy()   [무거움: 8/58/93 ms]

[B] C._invalidate_mask_cache (C:231-234) → 다음 effective_mask가 "전체 재생"이 된다.
    호출처: set_detected_mask (C:163-177) · _delete_selected_blob (C:281-299) · _restore_state (C:332-358)

[C] T._on_canvas_edited (T:541-554)                         ← erase_changed / blob_deleted 시그널 (T:238-241)
    ├─ canvas.get_state → 이미지 데이터에 스트로크·삭제 영역 저장
    ├─ canvas.effective_mask() (캐시 적중) → M.contour_area = mask.sum() (M:107-108)        [무거움: 1/6/10 ms]
    ├─ T._refresh_right_panel (T:980-982) → _refresh_overall_summary (T:984-999, 셀마다 CP.set_cell_status 선형 탐색)
    │                                      → _refresh_current_cell_block (T:1001-1028, 현재 셀 표 전체 재작성)
    ├─ T._refresh_step_indicator (T:1037-1052, 전체 이미지 데이터 순회)
    └─ T._schedule_autosave (T:637) → 500 ms 뒤 [E]

[D] T._run_and_display_detection (T:875-883)
    ├─ T._cv2_imread_cached (T:653-666, LRU 8장) → 미스면 M.imread_unicode (M:26-31)       [무거움: 6/43/55 ms]
    ├─ T._compute_detected_mask (T:675-684) → M.detect_contour_mask (M:75-104)              [무거움: 4/15/24 ms]
    ├─ canvas.set_detected_mask (C:163-177) → [B] → [A] **전체 재생**
    └─ canvas.effective_mask → M.contour_area

[E] T._do_save (T:614-635)                                  ← 자동 저장 타이머(단발 500 ms, T:152-155)
    ├─ T._sync_canvas_state_to_data (T:640)
    ├─ 전체 셀·전체 이미지의 스트로크를 담은 payload 구성
    └─ ST.save (ST:42-45) → json.dumps(indent=2) → file_io.atomic_write(임시 파일 + fsync + os.replace)   [파일 I/O]
```

### 2.2 조작별 흐름

```
세션 열기        T._on_open_session (T:558-575, QFileDialog) → T._load_session (T:577-612)
                 ├─ ST.load (ST:22-39) → _image_data_map 재구성
                 ├─ 설정 다이얼로그 setter 5개 (T:596-600) → SP 디바운스 타이머(150 ms) 시작              [과잉 → P-R8]
                 ├─ canvas.clear → CP.set_cells (T:606) → 첫 셀 자동 선택 → "셀 전환" 흐름 전체
                 ├─ 요약·우측 패널·단계 표시 갱신
                 └─ (150 ms 뒤) SP.settings_changed → T._on_settings_changed → [D] 재검출 + 자동 저장 예약 [과잉]

셀 전환          CP._cell_list.currentItemChanged → CP._on_cell_selected (CP:185-190)
                 ├─ IL.load_files (IL:318-331) → IL._apply_display (IL:838-913): 트리 재구성, 첫 이미지 자동 선택
                 │    └─ image_selected emit (IL:909-911) → T._set_current_image → "이미지 전환" 흐름
                 └─ cell_selected emit → T._on_cell_selected (T:688-693)
                      ├─ T._refresh_thumb_strip (T:797-810): 셀의 모든 이미지에 QPixmap(path).scaled(56,56)  [무거움: 원본 풀 디코드 × 장수]
                      └─ T._refresh_right_panel

폴더 가져오기     CP._on_import_folder (CP:102-123) → 셀 선택(위 흐름, 썸네일 1회) → cells_changed
                 → T._on_cells_changed (T:695-702) → T._refresh_thumb_strip **한 번 더**                    [중복]

이미지 전환       목록 클릭: IL.image_selected → CP.image_selected → T._set_current_image (T:207-208)
                 썸네일 클릭: _thumb_strip.itemClicked (T:250-252) / 이전·다음: T._navigate (T:775-784)
                 → T._set_current_image (T:724-730)
                    ├─ T._load_image (T:732-764)
                    │    ├─ _sync_canvas_state_to_data · _cv2_imread_cached · _bgr_to_qpixmap (T:72-79, QImage.copy)  [무거움: 2/10/16 ms]
                    │    ├─ canvas.set_state (T:749) → C._restore_state (C:332-358)
                    │    │    ├─ [B] → C._replay_erase_strokes (C:486-495) — 로드 때는 erase_strokes=[] (T:751)라 무동작
                    │    │    ├─ C._rebuild_stroke_overlay (C:519-524, 전체 스트로크 재래스터 — 검출 마스크가 있으면 화면에 안 쓰임) [과잉]
                    │    │    └─ [A] **전체 재생 1회째 — 이전 이미지의 검출 마스크에 새 스트로크를 적용(버려지는 계산)**       [중복][과잉]
                    │    ├─ T._compute_detected_mask (T:757) → M.detect_contour_mask
                    │    ├─ canvas.set_detected_mask (T:758) → [B] → [A] **전체 재생 2회째**                          [중복]
                    │    └─ effective_mask + contour_area (T:762-763)
                    ├─ CP.select_image · T._select_thumb (선형 탐색) · T._update_nav_label
                    └─ T._refresh_right_panel

ROI 생성/이동/리사이즈
                 드래그 중: C.mouseMoveEvent (C:660-681) → _update_move/_update_resize → update() + roi_changed
                           → T._update_undo_button_state (T:538)                        가벼움(프레임 2~4 ms)
                 놓을 때:   C.mouseReleaseEvent (C:683-750) → roi_changed, roi_committed(연결된 슬롯 없음)   가벼움
                 적용:      "ROI 전역/개별 지정" 버튼 → T._on_roi_global_requested (T:827-838) / _on_roi_override_requested (T:840-853) → [D]

브러시·지우개     누를 때:   C.mousePressEvent (C:615-658) → _push_undo → _erase_paint_stroke
                 이동 1회:  C.mouseMoveEvent → C._erase_paint_stroke (C:465-484, bbox 스탬프) → update()
                           → paintEvent에서 C._paint_current_stroke (C:562-573, 진행 중 스트로크의 **모든 점**을 매 프레임 다시 그림)
                 커밋:      C.mouseReleaseEvent (C:683-750) → 스트로크 추가 → C._rasterize_stroke (C:505-517)
                           → [A] (증분 경로, C:701) → erase_changed → [C]

블랍 클릭 선택    C.mouseReleaseEvent (클릭 판정, C:719/737) → C._blob_label_at (C:253-262)
                 → C._ensure_blob_labels (C:239-251): 마스크가 바뀐 뒤 첫 클릭이면 Z.compute_blob_labels (Z:189,
                   cv2.connectedComponentsWithStats 전체 프레임)                         [무거움: 4/18/33 ms, 이후 클릭은 캐시]
                 → C._select_blob (C:264-273) → update()

Delete           C.keyPressEvent (C:752-766) → C._delete_selected_blob (C:281-299)
                 → _push_undo → 삭제 영역 추가 → [B] → [A] **전체 재생** → blob_deleted → [C]

Ctrl+Z           C.keyPressEvent / undo 버튼 (T:332) → C.undo (C:309-312) → C._restore_state (C:332-358)
                 → [B] → _replay_erase_strokes (지우개 점마다 전체 프레임 OR, P-R15) → _rebuild_stroke_overlay → [A] **전체 재생**
                 → roi_changed · erase_changed → [C]

설정 변경         threshold 슬라이더 / 분모 / 스펙 상·하한 → SP._debounce(150 ms, SP:17, 27-34) → settings_changed
                 자동 검출 체크박스 → SP._on_auto_detect_toggled (SP:100-103) → 즉시 settings_changed
                 → T._on_settings_changed (T:814-825): **어떤 값이 바뀌었든** [D] 실행                    [과잉: 분모·스펙은 마스크와 무관]
                   → 요약·우측 패널 갱신 → 자동 저장 예약

불투명도 슬라이더  valueChanged (T:408) → T._on_mask_opacity_changed (T:412-416, 디바운스 없음)
                 → C.set_mask_opacity (C:183-188) → [A]의 RGBA 생성 부분을 **틱마다** 다시                 [과잉]

보이기/숨기기     T._act_overlay_visible.toggled (T:321) / F 키 → C.set_mask_overlay_visible (C:190-194) → update()만   가벼움

줌(휠)·팬        OV.wheelEvent (OV:79-83) → view_transform.wheel_zoom → update() / OV.mouseMoveEvent (OV:85-112) → pan_drag → update()

paintEvent 1회   C.paintEvent (C:602-611)
                 ├─ OV.paintEvent (OV:59-75): fillRect → 원본 해상도 QPixmap을 축소해 drawPixmap
                 ├─ C._paint_mask_overlay (C:539-549): 원본 해상도 RGBA8888 QImage를 축소해 drawImage
                 ├─ C._paint_strokes (C:575-583) → _paint_committed_strokes / _paint_current_stroke
                 └─ C._paint_roi (C:585-598)

일괄 검출         버튼 (T:346-362) → T._on_detect_cell (T:894-898) / _on_detect_all (T:900-902) → T._run_batch_detect (T:904-934)
                 └─ [워커 스레드] _RDetectWorker.run (T:114-134): 이미지마다 imread_unicode → detect_contour_mask
                      → M.apply_edits(**전체 재생**) → contour_area → image_done
                 → T._on_batch_detect_finished (T:951-960, 메인 스레드): 현재 이미지에 [D]를 **다시** 실행     [중복]
                 현재 이미지만: T._on_detect_current (T:885-892) → [D]

자동 저장         [E] — 편집·설정 변경 500 ms 뒤 메인 스레드에서 세션 전체를 다시 쓴다.

우측 패널·표 갱신  [C]의 _refresh_right_panel / _refresh_step_indicator — 편집·전환·검출마다 1회씩(중복 호출 없음 확인).
```

## 3. 측정 표

중앙값 ms (반복 3회 이상, 드래그류는 move 20~33회). 창 1920×1040(캔버스 1276×826), 픽스처 JPEG(q92), 셀 A 5장 / 셀 B 50장. `e0` = 편집 없음, `e30` = 스트로크 30개(브러시 40px, 누적 점 375 / 1160 / 1652개) + 삭제 3개. 원본 JSON(함수별 호출 수·시간 포함)은 5절 경로.

시나리오 이름 풀이: `cell_switch_to_Nimg` = N장짜리 셀로 전환 · `image_switch_list_warm/cold` = 목록 클릭 전환(디코드 캐시 적중/미스) · `image_switch_away` = 편집 있는 이미지에서 편집 없는 이미지로 · `*_move` / `roi_move` / `pan_move` = 드래그 중 mouseMove 1회(그리기 포함) · `brush_move_long_first20/last20` = move 150회짜리 한 스트로크의 처음/마지막 20회 · `brush_commit_build30` = e30을 만들며 쌓은 30회 커밋 · `blob_click_first/second` = 편집 직후 첫 클릭/그다음 클릭 · `delete_blob_kept` = 삭제가 1→3개째 누적될 때 · `threshold_change`·`denominator_change` = 디바운스 150 ms 대기 제외, 핸들러만 · `paint_repaint` = `repaint()` 1회 · `autosave` = `_do_save` 1회 · `autosave_50img_edited` = 50장 모두 스트로크 30개(세션 JSON 2.8 / 8.2 / 11.7 MB) · `batch_*` = 버튼 클릭부터 끝난 뒤 화면 갱신까지 · `*_100cells` = 셀 100개×5장(64×64) 세션.

| 시나리오 | 편집 | 1920x1200 | 4000x3000 | 5472x3648 | 100cells |
|---|---|---:|---:|---:|---:|
| session_open | e0 | 116.7 | 631.0 | 1103.3 | - |
| import_folder | e0 | 97.7 | 479.9 | 732.9 | - |
| cell_switch_to_50img | e0 | 803.8 | 3921.9 | 6483.5 | - |
| right_panel_refresh | e0 | 2.0 | 1.3 | 1.2 | - |
| cell_switch_to_5img | e0 | 102.0 | 420.7 | 670.0 | - |
| roi_create_move | e0 | 1.4 | 1.7 | 2.0 | - |
| roi_create_release | e0 | 1.7 | 1.9 | 2.3 | - |
| roi_global_apply | e0 | 23.6 | 78.7 | 123.7 | - |
| image_switch_list_warm | e0 | 33.2 | 145.0 | 228.8 | - |
| image_switch_list_cold | e0 | 39.0 | 178.6 | 286.3 | - |
| image_switch_thumb | e0 | 34.5 | 146.4 | 236.0 | - |
| image_switch_nav | e0 | 33.3 | 153.7 | 229.5 | - |
| paint_repaint | e0 | 2.1 | 3.2 | 2.5 | - |
| paint_repaint_mask_hidden | e0 | 1.3 | 2.1 | 1.7 | - |
| overlay_toggle | e0 | 1.9 | 2.7 | 2.6 | - |
| opacity_step | e0 | 12.3 | 56.6 | 88.0 | - |
| roi_move | e0 | 2.2 | 2.5 | 2.8 | - |
| roi_move_release | e0 | 2.3 | 2.6 | 2.9 | - |
| roi_resize | e0 | 2.2 | 2.8 | 2.6 | - |
| roi_resize_release | e0 | 1.9 | 2.5 | 2.7 | - |
| zoom_wheel | e0 | 2.0 | 2.5 | 2.6 | - |
| pan_move | e0 | 2.1 | 2.7 | 2.8 | - |
| brush_move | e0 | 2.4 | 3.0 | 3.1 | - |
| brush_commit | e0 | 22.3 | 163.5 | 279.9 | - |
| undo_brush | e0 | 16.1 | 66.2 | 102.9 | - |
| eraser_move | e0 | 2.4 | 2.8 | 3.1 | - |
| eraser_commit | e0 | 22.9 | 159.8 | 272.6 | - |
| undo_eraser | e0 | 16.6 | 66.9 | 104.7 | - |
| brush_move_long_first20 | e0 | 2.5 | 2.8 | 3.1 | - |
| brush_move_long_last20 | e0 | 5.4 | 3.6 | 4.2 | - |
| blob_click_first | e0 | 7.6 | 25.1 | 37.4 | - |
| blob_click_second | e0 | 2.3 | 3.5 | 3.3 | - |
| delete_blob | e0 | 16.5 | 70.9 | 120.8 | - |
| undo_delete | e0 | 16.0 | 74.2 | 104.3 | - |
| threshold_change | e0 | 19.6 | 91.9 | 129.7 | - |
| denominator_change | e0 | 19.4 | 80.3 | 128.3 | - |
| auto_detect_off | e0 | 6.3 | 26.0 | 24.6 | - |
| auto_detect_on | e0 | 20.5 | 89.4 | 134.1 | - |
| detect_current | e0 | 20.6 | 80.7 | 156.5 | - |
| autosave | e0 | 6.9 | 7.5 | 8.2 | - |
| batch_cell_5img | e0 | 96.2 | 396.2 | 607.2 | - |
| batch_all_55img | e0 | 703.5 | 3451.8 | 5329.3 | - |
| brush_move_build30 | e0→e30 | 2.8 | 3.2 | 3.2 | - |
| brush_commit_build30 | e0→e30 | 26.1 | 183.8 | 269.4 | - |
| paint_repaint | e30 | 3.0 | 3.7 | 2.9 | - |
| paint_repaint_mask_hidden | e30 | 2.1 | 3.0 | 1.8 | - |
| overlay_toggle | e30 | 2.9 | 3.7 | 2.2 | - |
| opacity_step | e30 | 16.9 | 79.3 | 98.0 | - |
| roi_move | e30 | 2.2 | 3.2 | 2.9 | - |
| roi_move_release | e30 | 2.0 | 3.6 | 2.7 | - |
| roi_resize | e30 | 2.2 | 3.3 | 2.8 | - |
| roi_resize_release | e30 | 2.1 | 3.3 | 3.0 | - |
| zoom_wheel | e30 | 2.2 | 3.5 | 2.7 | - |
| pan_move | e30 | 2.1 | 3.0 | 2.7 | - |
| brush_move | e30 | 2.6 | 3.2 | 3.2 | - |
| brush_commit | e30 | 26.9 | 152.8 | 284.3 | - |
| undo_brush | e30 | 180.6 | 2162.6 | 4891.4 | - |
| eraser_move | e30 | 2.9 | 2.8 | 3.1 | - |
| eraser_commit | e30 | 28.3 | 126.7 | 267.5 | - |
| undo_eraser | e30 | 208.8 | 2077.1 | 4954.0 | - |
| brush_move_long_first20 | e30 | 3.3 | 3.1 | 3.1 | - |
| brush_move_long_last20 | e30 | 8.3 | 4.1 | 4.2 | - |
| blob_click_first | e30 | 7.9 | 23.7 | 37.2 | - |
| blob_click_second | e30 | 2.4 | 2.9 | 3.5 | - |
| delete_blob | e30 | 167.8 | 2043.4 | 4889.4 | - |
| undo_delete | e30 | 176.6 | 2035.4 | 4907.8 | - |
| threshold_change | e30 | 190.2 | 2079.4 | 4901.0 | - |
| denominator_change | e30 | 174.0 | 2012.8 | 4878.9 | - |
| auto_detect_off | e30 | 162.3 | 2013.5 | 4833.2 | - |
| auto_detect_on | e30 | 172.0 | 2016.4 | 4914.0 | - |
| detect_current | e30 | 183.5 | 2013.4 | 4922.9 | - |
| autosave | e30 | 7.4 | 8.5 | 9.7 | - |
| delete_blob_kept | e30 | 167.0 | 2031.7 | 4850.0 | - |
| image_switch_list_warm | e30 | 362.8 | 4087.1 | 9755.5 | - |
| image_switch_list_cold | e30 | 396.7 | 4139.4 | 9839.5 | - |
| image_switch_away | e30 | 34.6 | 145.6 | 229.2 | - |
| paint_repaint | e30+del3 | 2.9 | 2.3 | 2.7 | - |
| batch_cell_5img | e30 | 422.2 | 4313.7 | 10084.5 | - |
| autosave_50img_edited | e30 | 30.2 | 78.8 | 115.2 | - |
| session_open_100cells | e0 | - | - | - | 25.9 |
| right_panel_refresh_100cells | e0 | - | - | - | 4.9 |
| autosave_100cells | e0 | - | - | - | 7.8 |

### 3.1 함수별 분해 (4000×3000, 조작 1회 평균, 계측 래퍼의 포함 시간)

| 조작 | 합계 | 분해 (호출 수 × / ms) |
|---|---:|---|
| 이미지 전환 e30 | 4087 | `_rebuild_mask_image` 2× / 4058 → `apply_edits` 2× / 3943 (`apply_manual_strokes` 4×, `disk_mask` 2320×), `_rebuild_stroke_overlay` 1× / 31, `detect_contour_mask` 15, `_bgr_to_qpixmap` 10 |
| 이미지 전환 e0 | 145 | `_rebuild_mask_image` **2×** / 110, `detect_contour_mask` 15, `_bgr_to_qpixmap` 10, `contour_area` 6 (cold면 + `imread_unicode` 34) |
| 셀 전환 50장 | 3922 | `_refresh_thumb_strip` 1× / 3992 (장당 80 ms), 첫 이미지 로드 36 |
| 세션 열기 | 631 | `_refresh_thumb_strip` 407(5장), `_load_image` 125, 디바운스발 `_run_and_display_detection` 78; `_rebuild_mask_image` **3×**, `detect_contour_mask` **2×** |
| 폴더 가져오기 | 480 | `_refresh_thumb_strip` **2×** / 415 |
| Ctrl+Z e30 | 2163 | `_rebuild_mask_image` 1× / 2185 → `apply_manual_strokes` 2125 (`disk_mask` 1160×), `_rebuild_stroke_overlay` 35, `contour_area` 6 |
| Delete e30 | 2043 | `_rebuild_mask_image` 1× / 2023 → `apply_edits` 1968 |
| threshold 변경 e30 | 2079 | `_run_and_display_detection` 2075 → `_rebuild_mask_image` 2054 (`apply_edits` 1996), `detect_contour_mask` 14 |
| 분모 변경 e30 | 2013 | threshold 변경과 동일 경로(재검출 + 전체 재생) |
| 브러시 커밋 e0 | 164 | `_rebuild_mask_image` 150 = 증분 `apply_manual_strokes` 93(새 점 37개) + RGBA 생성 약 57; `_rasterize_stroke` 7, `contour_area` 6.5 |
| Ctrl+Z e0 | 66 | `_rebuild_mask_image` 53(RGBA 생성), `contour_area` 6 |
| 불투명도 1틱 | 57 (e30: 79) | `_rebuild_mask_image` 53 (e30: 74) |
| 첫 블랍 클릭 | 25 | `compute_blob_labels` 18 |
| 일괄 5장 e30 | 4314 | 워커 `apply_edits` 약 1970 + 종료 후 메인 `_run_and_display_detection` 2044 |
| 일괄 55장 e0 | 3452 | 워커: `imread_unicode` 55× / 1934, `detect_contour_mask` 847, `contour_area` 347; 메인 재검출 79 |
| 자동 저장 50장×30스트로크 | 79 | `r_store.save` 77 |

### 3.2 구성 요소 단가 (마이크로 벤치, ms)

| 연산 | 1920×1200 | 4000×3000 | 5472×3648 |
|---|---:|---:|---:|
| `apply_manual_strokes` 스트로크 30개·1170점 (현재) | 474 | 3152 | 5835 |
| 같은 입력, bbox 국소 스탬프 프로토타입 (결과 픽셀 완전 동일 확인) | 19 | 21 | 19 |
| RGBA8888 오버레이 생성 (zeros + 색 대입 + copy) | 7.9 | 58 | 93 |
| 마스크를 Indexed8 QImage로 무복사 래핑 (색·알파는 컬러 테이블) | 0.002 | 0.004 | 0.002 |
| 축소 그리기 1회: RGBA8888 / Indexed8 | 0.23 / 1.06 | 0.33 / 1.09 | 0.36 / 1.16 |
| `mask.sum()` / `np.count_nonzero(mask)` | 1.1 / 0.04 | 5.9 / 0.29 | 10.3 / 0.46 |
| `connectedComponentsWithStats` | 3.6 | 20 | 33 |
| 썸네일 1장: 현재 `QPixmap(path).scaled` | (16)* | 79 | 121 |
| 썸네일 1장: `QImageReader.setScaledSize` / cv2 `IMREAD_REDUCED_COLOR_8` | 3.4 / 3.1 | 20 / 18 | 32 / 28 |

\* 1920×1200은 `QPixmap(path)`가 QPixmapCache(기본 10 MB)에 들어가 반복 측정이 0.4 ms로 나온다. 16 ms는 탭 벤치의 셀 전환(804 ms / 50장)에서 역산.

전체 재생의 점당 비용(1.7 ms @4000)은 `disk_mask` 함수 자체(0.08 ms)가 아니라, 그 함수가 돌려준 **갓 할당된 전체 크기 배열을 `|=`로 처음 읽을 때** 생긴다(12 MB 지연 할당의 페이지 폴트 + 전체 프레임 스캔). 그래서 프로파일러에서는 `disk_mask`가 아니라 `apply_manual_strokes` 자체 시간으로 잡힌다.

### 3.3 cProfile (4000×3000, 누적 시간 상위)

`--profile-dir`로 뽑은 조작 1회의 함수별 시간(ms; cum = 하위 호출 포함, self = 함수 자체). 벤치·Qt 이벤트 전달 프레임은 뺐다. 프로파일러 오버헤드가 있어 합계는 3절 표와 조금 다르다.

```
# session_open e0 4000x3000 — 584.3 ms (프로파일러 오버헤드 포함)
       499 cum       0 self         1  r_analysis_tab.py:577(_load_session)
       491 cum       0 self         1  r_cell_panel.py:75(set_cells)
       491 cum       0 self         1  r_cell_panel.py:192(_refresh_cell_list)
       490 cum       0 self         1  {built-in method setCurrentRow}
       490 cum       0 self         1  r_cell_panel.py:185(_on_cell_selected)
       490 cum       0 self      11/5  {method 'emit' of 'PyQt6.QtCore.pyqtBoundSignal' objects}
       373 cum       0 self         1  r_analysis_tab.py:688(_on_cell_selected)
       372 cum     364 self         1  r_analysis_tab.py:797(_refresh_thumb_strip)
       117 cum       0 self         1  inference_image_list.py:318(load_files)
# cell_switch_to_50img e0 4000x3000 — 3756.4 ms (프로파일러 오버헤드 포함)
      3749 cum       0 self         1  r_cell_panel.py:207(_select_cell)
      3749 cum       0 self       2/1  {built-in method setCurrentItem}
      3749 cum       0 self         1  r_cell_panel.py:185(_on_cell_selected)
      3748 cum       0 self       9/3  {method 'emit' of 'PyQt6.QtCore.pyqtBoundSignal' objects}
      3695 cum       0 self         1  r_analysis_tab.py:688(_on_cell_selected)
      3694 cum    3610 self         1  r_analysis_tab.py:797(_refresh_thumb_strip)
        83 cum      83 self        50  {built-in method scaled}
        54 cum       0 self         1  inference_image_list.py:318(load_files)
        54 cum       0 self         1  inference_image_list.py:838(_apply_display)
# image_switch_list_warm e30 4000x3000 — 5117.3 ms (프로파일러 오버헤드 포함)
      5113 cum       0 self         1  inference_image_list.py:616(_on_selection_changed_multi)
      5113 cum       0 self       7/1  {method 'emit' of 'PyQt6.QtCore.pyqtBoundSignal' objects}
      5113 cum       0 self         1  r_analysis_tab.py:724(_set_current_image)
      5112 cum       0 self         1  r_analysis_tab.py:732(_load_image)
      5036 cum      98 self         2  r_roi_canvas.py:528(_rebuild_mask_image)
      4919 cum       1 self         3  r_roi_canvas.py:199(effective_mask)
      4918 cum      10 self         2  r_analysis_metrics.py:50(apply_edits)
      4908 cum    4698 self         4  zone_metrics.py:112(apply_manual_strokes)
      2979 cum       0 self         1  r_roi_canvas.py:322(set_state)
# undo_brush e30 4000x3000 — 2037.5 ms (프로파일러 오버헤드 포함)
      2033 cum       0 self         2  r_roi_canvas.py:752(keyPressEvent)
      2033 cum       0 self         1  r_roi_canvas.py:309(undo)
      2033 cum       2 self         1  r_roi_canvas.py:332(_restore_state)
      1995 cum      46 self         1  r_roi_canvas.py:528(_rebuild_mask_image)
      1940 cum       0 self         2  r_roi_canvas.py:199(effective_mask)
      1940 cum       0 self         1  r_analysis_metrics.py:50(apply_edits)
      1940 cum    1846 self         1  zone_metrics.py:112(apply_manual_strokes)
        92 cum      59 self      1160  zone_metrics.py:42(disk_mask)
        28 cum       1 self         1  r_roi_canvas.py:519(_rebuild_stroke_overlay)
# threshold_change e30 4000x3000 — 2005.5 ms (프로파일러 오버헤드 포함)
      2001 cum       0 self       2/1  {method 'emit' of 'PyQt6.QtCore.pyqtBoundSignal' objects}
      2001 cum       0 self         1  r_analysis_tab.py:814(_on_settings_changed)
      2000 cum       0 self         1  r_analysis_tab.py:875(_run_and_display_detection)
      1981 cum       2 self         1  r_roi_canvas.py:163(set_detected_mask)
      1978 cum      46 self         1  r_roi_canvas.py:528(_rebuild_mask_image)
      1924 cum       0 self         2  r_roi_canvas.py:199(effective_mask)
      1924 cum       0 self         1  r_analysis_metrics.py:50(apply_edits)
      1924 cum    1831 self         1  zone_metrics.py:112(apply_manual_strokes)
        91 cum      59 self      1160  zone_metrics.py:42(disk_mask)
# brush_commit e30 4000x3000 — 128.8 ms (프로파일러 오버헤드 포함)
       114 cum      46 self         1  r_roi_canvas.py:528(_rebuild_mask_image)
        60 cum       1 self         2  r_roi_canvas.py:199(effective_mask)
        59 cum      55 self         1  zone_metrics.py:112(apply_manual_strokes)
         8 cum       8 self         1  {built-in method copy}
         7 cum       0 self         2  {method 'emit' of 'PyQt6.QtCore.pyqtBoundSignal' objects}
         7 cum       0 self         1  r_analysis_tab.py:541(_on_canvas_edited)
         6 cum       6 self         2  {method 'reduce' of 'numpy.ufunc' objects}
         6 cum       0 self         1  r_analysis_metrics.py:107(contour_area)
         6 cum       0 self         1  {method 'sum' of 'numpy.ndarray' objects}
# opacity_step e30 4000x3000 — 61.6 ms (프로파일러 오버헤드 포함)
        58 cum       0 self         1  {built-in method setValue}
        58 cum       0 self         1  r_analysis_tab.py:412(_on_mask_opacity_changed)
        58 cum       2 self         1  r_roi_canvas.py:183(set_mask_opacity)
        55 cum      46 self         1  r_roi_canvas.py:528(_rebuild_mask_image)
         9 cum       9 self         1  {built-in method copy}
         2 cum       0 self         1  r_roi_canvas.py:602(paintEvent)
         1 cum       0 self         1  overlay_viewer.py:59(paintEvent)
         1 cum       1 self         1  {built-in method drawPixmap}
         1 cum       0 self         1  r_roi_canvas.py:539(_paint_mask_overlay)
# autosave_50img_edited e30 4000x3000 — 82.8 ms (프로파일러 오버헤드 포함)
        83 cum       0 self         1  r_analysis_tab.py:614(_do_save)
        82 cum       0 self         1  r_cell_store.py:42(save)
        82 cum       0 self         1  file_io.py:36(atomic_write)
        62 cum       0 self         1  __init__.py:185(dumps)
        62 cum       0 self         1  encoder.py:185(encode)
        62 cum      62 self         1  encoder.py:207(iterencode)
        11 cum       0 self         1  __init__.py:799(write_text)
        10 cum      10 self         1  {method 'write' of '_io.TextIOWrapper' objects}
         6 cum       6 self         2  {built-in method nt.open}
```

읽는 법: 전체 재생류는 시간이 `apply_manual_strokes`의 **self**에 몰려 있다(numpy 연산자 `|=`·불리언 대입은 함수 호출이 아니라 self로 잡힘). 썸네일은 `_refresh_thumb_strip` self 3610 ms가 `QPixmap(path)` 생성자(디코드)이고 `scaled`는 83 ms뿐 — 축소가 아니라 **디코드**가 비용이다. 이미지 전환 e30에서 `set_state` 누적 2979 ms가 버려지는 첫 번째 재생이다(P-R2). 자동 저장은 `json.dumps` 62 ms + 쓰기 10 ms로, fsync보다 직렬화가 크다.

## 4. 지연 요소 목록

체감 영향: **상** = 한 번에 0.5 s 이상 멈춤 또는 매우 자주 100 ms 이상, **중** = 100 ms 안팎이거나 연속 조작이 끊김, **하** = 수십 ms 이하 또는 드문 경우. 측정값은 1920 / 4000 / 5472 순(ms).

### P-R1 — 스트로크 전체 재생이 점마다 전체 프레임 연산 (상)
- 조작: Delete, Ctrl+Z, 이미지 전환, threshold·분모·스펙 변경, 자동 검출 토글, 현재 이미지 검출, ROI 지정, 일괄 검출 — 편집이 있는 이미지에서.
- 측정(e30): Delete 168 / 2043 / 4889, Ctrl+Z 181 / 2163 / 4891. 점당 0.45 / 1.7 / 3.0 ms.
- 원인: `Z.apply_manual_strokes` (zone_metrics.py:112-128) + `Z.disk_mask` (:42). 호출 경로 `M.apply_edits` (r_analysis_metrics.py:50-72) ← `C.effective_mask` (r_roi_canvas.py:224).
- 왜 느린가: 반지름 20px 원 하나를 찍는 데 이미지 전체 크기 배열을 새로 할당하고 전체 프레임 OR를 한다. 비용이 (점 개수 × 이미지 픽셀 수)에 비례해, 스트로크를 쌓을수록·이미지가 클수록 계속 느려진다.
- 개선 방향 후보: 원의 bbox 안에서만 스탬프(프로토타입 실측 3152 → 21 ms, 결과 동일). `zone_metrics.py`는 Zone 탭과 공용이므로 한 곳을 고치면 양쪽에 적용된다. 이것만으로 아래 P-R2·4·7·9의 대부분이 같이 풀린다.

### P-R2 — 이미지 전환 시 전체 재생·마스크 이미지 생성 2회 (상)
- 조작: 목록 클릭 / 썸네일 클릭 / 이전·다음.
- 측정: e30 363 / 4087 / 9756, e0 33 / 145 / 229 (e0에서도 `_rebuild_mask_image` 2회가 145 중 110).
- 원인: `T._load_image` (r_analysis_tab.py:732-764)가 `set_state` (:749) → `C._restore_state` (r_roi_canvas.py:332-358) 다음에 `set_detected_mask` (:758)를 부른다.
- 왜 느린가: 첫 번째 재생은 **이전 이미지의 검출 마스크**에 새 이미지의 스트로크를 적용한 것으로, 곧바로 버려진다. `_rebuild_stroke_overlay` (:519-524, 31 ms)도 검출 마스크가 있으면 화면에 쓰이지 않는다.
- 개선 방향 후보: 검출 마스크와 편집 상태를 한 번에 넣고 재생·이미지 생성은 1회만. 이미지별 최종 마스크 LRU 캐시로 재방문은 재생 없이.

### P-R3 — 썸네일 스트립이 원본을 동기 풀 디코드 (상)
- 조작: 셀 전환, 세션 열기, 폴더 가져오기, 셀 추가·삭제.
- 측정: 50장 셀 804 / 3922 / 6484, 5장 셀 102 / 421 / 670, 세션 열기 117 / 631 / 1103. 장당 16 / 80 / 130 ms.
- 원인: `T._refresh_thumb_strip` (r_analysis_tab.py:797-810) — 이미지마다 `QPixmap(str(p)).scaled(56, 56)`.
- 왜 느린가: 56px 썸네일을 얻으려고 원본 전체를 디코드하고, 메인 스레드에서, 셀의 모든 이미지에 대해, 캐시 없이 매번 한다. 장수에 정비례.
- 개선 방향 후보: 축소 디코드(`QImageReader.setScaledSize` 실측 79 → 20 ms/장) + 경로·수정시각 키 캐시 + 화면에 보이는 것만 또는 백그라운드로 채우기.

### P-R4 — 브러시·지우개 커밋마다 100 ms 이상 (상)
- 조작: 스트로크를 놓을 때마다.
- 측정: 브러시 22~27 / 153~184 / 269~284, 지우개 23~28 / 127~160 / 268~273.
- 원인: `C.mouseReleaseEvent` (r_roi_canvas.py:701) → `_rebuild_mask_image` (:528-537).
- 왜 느린가: 증분 경로인데도 새 점 37개가 각각 전체 프레임 연산(93 ms, P-R1) + 스트로크가 닿지 않은 곳까지 RGBA 이미지를 통째로 다시 만든다(57 ms, P-R6).
- 개선 방향 후보: P-R1 적용 시 증분 부분은 1 ms대. 오버레이는 바뀐 사각형만 갱신하거나 P-R6 방식으로.

### P-R5 — 불투명도 슬라이더가 틱마다 마스크 이미지 재생성 (중)
- 측정: 12~17 / 57~79 / 88~98 ms per 틱 → 4000에서 드래그 시 약 13~17 fps.
- 원인: `C.set_mask_opacity` (r_roi_canvas.py:183-188) → `_rebuild_mask_image`. 디바운스 없음 (r_analysis_tab.py:408-416).
- 왜 느린가: 마스크 내용은 그대로인데 알파만 바꾸려고 H×W×4 배열을 새로 채운다.
- 개선 방향 후보: 그릴 때 `painter.setOpacity` 또는 컬러 테이블 알파만 교체 — 이미지 재생성 0.

### P-R6 — 마스크 오버레이를 매번 원본 해상도 RGBA로 전체 재생성 (중)
- 조작: 마스크가 바뀌는 모든 조작의 바닥 비용(편집이 없어도).
- 측정(e0): Ctrl+Z 16 / 66 / 103, Delete 17 / 71 / 121, threshold 20 / 92 / 130, ROI 전역 지정 24 / 79 / 124, 현재 검출 21 / 81 / 157. 그중 RGBA 생성이 8 / 58 / 93.
- 원인: `C._rebuild_mask_image` (r_roi_canvas.py:528-537).
- 왜 느린가: `np.zeros((H,W,4))` + 불리언 인덱싱 대입 + `QImage.copy()` — 48 MB(4000) / 80 MB(5472)를 매번 쓴다.
- 개선 방향 후보: bool 마스크를 Indexed8 QImage로 무복사 래핑(생성 0.004 ms, 그리기 +0.8 ms) — 색·불투명도는 컬러 테이블.

### P-R7 — 마스크와 무관한 설정 변경에도 재검출 + 전체 재생 (중, 편집 있으면 상)
- 조작: 분모, 스펙 상·하한 변경(자동 검출 끄기 포함).
- 측정: 분모 변경 e0 19 / 80 / 128, e30 174 / 2013 / 4879.
- 원인: `T._on_settings_changed` (r_analysis_tab.py:814-825)가 무엇이 바뀌었는지 보지 않고 항상 `_run_and_display_detection` 호출.
- 왜 느린가: 분모·스펙은 표의 숫자/판정만 바꾸는데 검출과 스트로크 재생을 다시 한다.
- 개선 방향 후보: threshold·자동 검출·ROI가 바뀐 경우에만 재검출, 나머지는 우측 패널만 갱신.

### P-R8 — 세션을 연 직후 불필요한 재검출 + 자동 저장 (중)
- 측정: 세션 열기 631(4000) 중 78 ms. 1920에서는 로드가 150 ms 안에 끝나 측정 구간 밖에서 발생.
- 원인: `T._load_session` (r_analysis_tab.py:596-599)의 setter들이 `SP._debounce`(150 ms)를 시작 → 뒤늦게 `settings_changed` → `_on_settings_changed`.
- 왜 느린가: 방금 로드·검출한 첫 이미지를 한 번 더 검출하고, 아무것도 안 바꿨는데 세션 파일을 다시 쓴다.
- **추정**: 첫 이미지에 편집이 있으면 전체 재생이 1회 더 붙는다(4000·e30 기준 +2 s, 즉 열자마자 약 6 s) — 이 조합은 직접 재지 않았다.
- 개선 방향 후보: 로드 중 setter 시그널 차단 또는 디바운스 정지.

### P-R9 — 일괄 검출: 편집된 이미지 재생 + 끝난 뒤 메인 스레드 재검출 (중)
- 측정: 5장 셀 e0 96 / 396 / 607 → 편집 1장 포함 422 / 4314 / 10085. 55장 e0 704 / 3452 / 5329(장당 13 / 63 / 97, UI 최대 멈춤 16 / 80 / 120).
- 원인: `_RDetectWorker.run` (r_analysis_tab.py:114-134)의 `apply_edits` + `T._on_batch_detect_finished` (:951-960)의 `_run_and_display_detection`.
- 왜 느린가: 워커가 방금 계산한 현재 이미지를 메인 스레드가 처음부터 다시 계산한다(편집 있으면 2 s 멈춤). 편집 없는 경우는 디코드가 지배적(55장 중 1934 ms).
- 개선 방향 후보: P-R1 + 현재 이미지는 워커 결과 재사용. 디코드는 워커 병렬화 여지(미측정).

### P-R10 — 편집 뒤 첫 블랍 클릭에서 전체 라벨링 (하)
- 측정: 첫 클릭 8 / 24~25 / 37, 그다음 클릭 2 / 3 / 3.
- 원인: `C._ensure_blob_labels` (r_roi_canvas.py:239-251) → `Z.compute_blob_labels` (zone_metrics.py:189).
- 왜 느린가: 마스크가 바뀔 때마다 전체 프레임 connected components. 100 ms 미만이라 단독으로는 체감이 작다.
- 개선 방향 후보: ROI 영역만 라벨링하거나 그대로 둔다.

### P-R11 — 면적 계산이 `mask.sum()` (하)
- 측정: 1.1 / 5.9 / 10.3 ms, 편집·전환·검출마다 1~2회 (`np.count_nonzero`는 0.04 / 0.29 / 0.46).
- 원인: `M.contour_area` (r_analysis_metrics.py:107-108). 일괄 55장에서는 합계 347 ms(4000).
- 개선 방향 후보: `np.count_nonzero`로 교체(한 줄).

### P-R12 — 자동 저장이 메인 스레드에서 세션 전체를 다시 씀 (하, 세션이 크면 중)
- 측정: 보통 7 / 8 / 10, 50장 모두 스트로크 30개면 30 / 79 / 115 (JSON 2.8 / 8.2 / 11.7 MB).
- 원인: `T._do_save` (r_analysis_tab.py:614-635) → `ST.save` (r_cell_store.py:42-45, `indent=2` + fsync).
- 왜 느린가: 한 이미지만 바뀌어도 전체 이미지의 모든 스트로크 점을 직렬화한다. 편집 500 ms 뒤에 돌아 다음 스트로크 도중에 끼어든다.
- 개선 방향 후보: indent 제거·좌표 반올림으로 크기 축소, 또는 직렬화·쓰기를 워커로.

### P-R13 — 진행 중 스트로크 미리보기가 점 개수에 비례 (하, 추정)
- 측정: move 150회 스트로크의 처음 20회 → 마지막 20회: 2.5 → 5.4 / 2.8 → 3.6 / 3.1 → 4.2 (e30: 3.3 → 8.3 @1920).
- 원인: `C._paint_current_stroke` (r_roi_canvas.py:562-573) — 프레임마다 진행 중 스트로크의 모든 점을 다시 그림.
- **추정**: 선형 외삽하면 확대 상태에서 아주 긴 스트로크(move 500~1000회)일 때 16 ms/프레임을 넘는다. 그 길이는 직접 재지 않았다.
- 개선 방향 후보: 새 점만 오버레이 이미지에 누적해 그리기.

### P-R14 — 폴더 가져오기에서 썸네일 스트립 2회 구성 (하)
- 측정: 98 / 480 / 733, `_refresh_thumb_strip` 2회가 79 / 415 / 631.
- 원인: `CP._on_import_folder` (r_cell_panel.py:102-123)가 셀을 선택(1회)한 뒤 `cells_changed` → `T._on_cells_changed` (r_analysis_tab.py:695-702)에서 한 번 더.
- 개선 방향 후보: P-R3의 캐시가 있으면 자연히 해소. 없으면 같은 셀이면 재구성 생략.

### P-R15 — Ctrl+Z 때 지우개 스트로크 전체 프레임 재생 (미측정, 추정)
- 조작: 이미지를 연 뒤 지우개 스트로크를 1개 이상 그린 상태에서의 Ctrl+Z (이미지 전환 때는 `erase_strokes: []`로 로드되어 해당 없음 — r_analysis_tab.py:751).
- 원인: `C._replay_erase_strokes` (r_roi_canvas.py:486-495) — 지우개 점마다 `mask |= Z.disk_mask(...)` (P-R1과 같은 패턴). 결과를 읽는 `erase_mask()` (:179)는 `app/` 안에 호출처가 없다(코드 주석도 "레거시 필드").
- **추정**: 남아 있는 지우개 점당 P-R1과 같은 단가(1.7 ms @4000)가 Ctrl+Z에 추가된다. 벤치는 지우개 스트로크를 그리자마자 되돌려서 이 비용이 0으로 측정됐다.
- 개선 방향 후보: 사용처가 없으면 제거, 있으면 bbox 스탬프(`_erase_stamp`, :445-458)를 재사용.

## 5. 측정 방법·한계

- 실행: `QT_QPA_PLATFORM=offscreen`, 실제 `RAnalysisTab`을 띄우고 QTest로 마우스·키 이벤트를 넣거나 버튼·슬라이더를 조작. 시간은 `perf_counter`로 "조작 + `processEvents`(그리기 포함)"까지. 중앙값.
- 함수별 분해는 런타임 계측 래퍼(호출 수 + 포함 시간)로, 앱 코드는 건드리지 않았다. 호출 수가 많은 `disk_mask`(수천 회)에는 래퍼 오버헤드가 조금 섞인다.
- 환경: Ryzen 5 7500F, RAM 32 GB, Windows 11, Python 3.14.2 / PyQt6 6.11.0 / OpenCV 5.0.0 / numpy 2.4.4 (정확한 값은 결과 JSON `meta`).
- 재실행:
  ```
  set QT_QPA_PLATFORM=offscreen & set PYTHONPATH=<워크트리>
  python scripts/bench_r_tab.py --out r_after.json --compare r_before.json     (약 10분)
  python scripts/bench_r_tab.py --sizes 4000x3000 --repeat 1 --profile-dir prof/   (cProfile 덤프)
  ```
  픽스처는 `--fixtures` 폴더에 캐시되어 전/후가 같은 입력을 쓴다. 기준선 결과: `r_before.json`(+ `r_before.summary.md`), 마이크로 벤치 `micro.py` / `micro.txt`, cProfile 덤프 `prof/` — 모두 스크래치 `perf_2026_11_11/`.

**한계 / 못 잰 것**

1. **실제 화면 출력 비용**: offscreen은 래스터 엔진까지만 돈다. GPU 합성·백킹 스토어 플러시·고DPI 배율·모니터 주사율 대기는 포함되지 않는다. 드래그 프레임 2~4 ms는 하한값이며, 실기에서 16 ms를 넘는지는 미확인(P-R 번호를 주지 않은 이유).
2. **마우스 입력 빈도**: QTest 합성 이벤트는 move 1회 = 처리 1회다. 실제 OS는 이벤트를 압축·누적하므로 커밋 지연 중 쌓이는 입력 등은 재현되지 않는다.
3. **콜드 디스크**: 같은 파일을 반복해 읽어 OS 파일 캐시가 데워진 상태다. HDD·네트워크 드라이브의 첫 로드는 더 느리다. 픽스처는 JPEG만(PNG/BMP는 `--ext`로 가능하나 돌리지 않음), 50장이 같은 내용의 사본이다.
4. **디바운스 대기**(150 ms)와 **QFileDialog** 시간은 제외했다. threshold 슬라이더를 끄는 동안의 체감은 "150 ms + 표의 값"이다.
5. 직접 재지 않고 추정으로 적은 것: P-R8의 편집 있는 첫 이미지 조합, P-R13의 아주 긴 스트로크, P-R15 전체.
6. 창 리사이즈(`_position_overlays`), 메모리 사용량, 일괄 검출 워커 병렬화 여지는 재지 않았다.
7. 편집량은 e0 / e30 두 점뿐이다. P-R1은 점 개수에 선형이므로 스트로크 100개면 e30의 약 3배로 본다(추정).
8. `import_folder`와 `batch_all_55img`는 1회 측정(반복 없음)이다.
