# R 분석 탭 · 상/하부(Zone) 분석 탭 성능 개선 — 새 구조 설계

- 작성: 2026-11-12, 기획. **설계만 — 코드 수정 없음.** 다음 순서: 설계 검토 → 구현 → 구현 매칭률 기록(7절) → 검증.
- 대상: `feature/zone-analysis-tab` 워크트리(`D:\segmentation model-zone-analysis-tab`), 설계 시점 HEAD `df2fe39`. 아래 `파일:행`은 이 HEAD 기준(코드맵 문서의 `fd9ed94` 행 번호와 이 설계에서 쓰는 범위는 같음을 grep으로 확인).
- 입력: [perf-2026-11-11-r-codemap.md](perf-2026-11-11-r-codemap.md)(P-R1~P-R15), [perf-2026-11-11-zone-codemap.md](perf-2026-11-11-zone-codemap.md)(P-Z1~P-Z14).
- 기준선: 스크래치 `perf_2026_11_11/r_before.json`, `zone_before.json` (+ `.summary.md`).
- 사용자 요청: "R부, 상하부 쪽에서 사용하다 보면 느린 느낌이 많다."

## 1. 목표와 범위

### 1.1 목표
- 두 탭에서 사용자가 자주 하는 조작(편집 이미지 전환, Delete/Ctrl+Z, 스트로크 커밋, 불투명도, 조회 클릭, 설정 변경, 셀 전환)의 메인 스레드 멈춤을 **4000×3000·e30 기준 수 초 → 수백 ms 이하**로 줄인다(4절 목표 수치).
- **동작은 바꾸지 않는다.** 결과 마스크 픽셀, 면적·비율·블랍 통계, Excel/결과표 값, 세션 JSON·사이드카 파일 형식과 내용은 개선 전과 **완전히 같아야** 한다. 항목마다 동일성 확인 방법을 3절에 적었다.
- 최소 변경: 원인별 국소 수정 + 꼭 필요한 곳에만 캐시 1개씩. 새 의존성·새 모듈·새 추상화 없음. 안 쓰는 코드는 삭제.

### 1.2 범위
- 파일: `app/core/zone_metrics.py`(R·Zone 공용), `app/core/r_analysis_metrics.py`, `app/core/inference_engine.py`(Zone이 쓰는 부분만), `app/widgets/r_roi_canvas.py`, `app/widgets/zone_canvas.py`, `app/tabs/r_analysis_tab.py`, `app/tabs/zone_analysis_tab.py`, `app/widgets/r_settings_panel.py`(1줄 수준).
- 결과 동일성 셀프체크 스크립트 1개 신설(`scripts/check_perf_equivalence.py`, 5절).

### 1.3 범위 밖 (바꾸지 않음)
| 항목 | 이유 |
|---|---|
| 재추론 시 화면 이미지 편집 초기화 (BUG-065) | 사용자 결정 대기 — 동작 변경 |
| 임계값·타겟 클래스 변경 시 편집·Undo 초기화 정책 (P-Z6 부수 관찰, `ZoneCanvas.set_blob_data`) | 의도된 동작(정합성) — 성능 작업에서 건드리지 않음. D3 캐시는 이 초기화를 그대로 따라간다 |
| R 블랍 삭제의 bbox 방식 (BUG-063) | 사용자 결정 대기 — 세션 형식 변경 필요 |
| 모델 forward / 추론 워커 | 이번 요청의 지연 요소가 아님 |
| 자동 저장 JSON 크기 축소(indent 제거 등, P-R12) | 저장 파일 바이트가 바뀜 → "저장 파일 형식 불변" 원칙 위반 소지. 효과도 작음(보류, 3.2절) |
| 실제 디스플레이 합성 비용, 일괄 검출 워커 병렬화 | 미측정 — 근거 없이 설계하지 않음 |

## 2. 새 구조 개요

핵심은 세 가지다. ① 공용 편집 재생(`apply_manual_strokes`)을 스탬프 bbox 국소 연산으로 바꿔 재생 1회 비용 자체를 1/100 수준으로 만든다(D1). ② Zone은 "편집 상태 리비전" 하나를 키로 최종 마스크와 그 파생물(라벨맵·블랍표·색칠 레이어)을 캐시해 **한 조작 = 재생 최대 1회**로 만든다(D3·D4·D6). ③ 오버레이는 마스크가 바뀔 때만 다시 만들고, 불투명도는 R은 컬러 테이블 알파만, Zone은 캐시된 레이어 위 블렌드만 다시 한다(D4·D8).

### 2.1 공통 편집 재생
```
전: 스트로크마다 np.zeros(H×W) → 스탬프마다 disk_mask()가 H×W 배열 새로 할당 → 전체 프레임 OR → result[stroke_mask] = draw
후: 스트로크마다 스탬프 bbox 합집합(y0:y1, x0:x1) 계산 → 그 크기의 지역 배열에만 원 스탬프 OR → result[y0:y1, x0:x1][local] = draw
    (반환은 지금처럼 항상 새 배열 = mask.copy() 1회)
```

### 2.2 R 탭 — 조작별 흐름
| 조작 | 전 | 후 |
|---|---|---|
| 이미지 전환 | `set_state`(옛 이미지 검출 마스크로 전체 재생 + RGBA 생성) → `set_detected_mask`(전체 재생 + RGBA 생성) = 재생 2회·RGBA 2회 | `set_detected_mask(None)`(공짜) → `set_state`(마스크 없음 → 재생 없음) → `set_detected_mask(mask)` = 재생 1회(D1로 수십 ms)·Indexed8 래핑(≈0) |
| Delete / Ctrl+Z / 재검출 | 전체 재생(초 단위) + RGBA 생성 58 ms | 전체 재생(D1) + Indexed8 래핑 |
| 브러시 커밋 | 증분 재생(새 점마다 전체 프레임) + RGBA 생성 | 증분 재생(D1, ~1 ms) + Indexed8 래핑 |
| 불투명도 틱 | RGBA 전체 재생성 | 컬러 테이블 알파만 교체(D8) |
| 분모·스펙 변경 | 재검출 + 전체 재생 | 우측 패널만 갱신(D11) |
| 셀 전환 | 썸네일마다 원본 풀 디코드 | 축소 디코드 + (경로, 수정시각) 캐시(D10) |
| 세션 열기 | 로드 후 150 ms 뒤 불필요한 재검출 + 자동 저장 | 로드 끝에 디바운스 정지(D12) |

### 2.3 Zone 탭 — 조작별 흐름
캐시 키 `mask_key = (id(class_map), target_class_id, canvas.edit_revision())`. `edit_revision()`은 편집 상태가 바뀌는 4곳(+`set_state`)에서만 +1 되는 정수.

```
_ai_and_final_masks()        ← mask_key 같으면 캐시된 (ai, final) 반환, 다르면 apply_edits 1회 후 캐시 교체   [D3]
  ├ _final_labels()           ← mask_key 기준 compute_blob_labels(final) 캐시                                  [D6]
  ├ _compute_zone_blob_rows() ← (mask_key, circles_key) 기준 blob rows 캐시                                     [D6]
  └ _reblend_overlay()        ← 색칠 레이어: mask_key 기준 캐시 / 축소 원본: 이미지 경로 기준 캐시 /
                                최종 오버레이: (mask_key, opacity) 같으면 생략                                  [D4]
_current_zones()              ← (circles_key, shape) 기준 zones 캐시                                            [D15]
```

| 조작 | 전 (재생 / 오버레이 / 디스크 디코드) | 후 |
|---|---|---|
| 스트로크 커밋 / Ctrl+Z / 원 적용 | 3 / 1 / 1 | 1 / 레이어 재생성 1 + 블렌드 / 0 |
| 영역 삭제 클릭 | 4 / 1 / 1 | 2(캔버스 판정용 `edited_masks` 직접 호출 1 — 탭 캐시를 안 거침, D1로 수십 ms — + 삭제 후 1) / 1 / 0 |
| 편집 이미지 전환 | 4 + 지우개 재생 / 2 / 2 | 1 / 1 / 1(그 이미지 처음일 때만) |
| 불투명도 1단계 | 1 / 1 / 1 | 0 / 블렌드만 / 0 |
| 오버레이 다시 보이기(F) | 1 / 1 / 1 | 0 / 0(캐시 적중) / 0 |
| 조회 클릭(존) | 1 / 0 / 0 | 0(캐시된 final 조회) |
| 조회 클릭(블랍) | 1 + CC 2회 + 블랍표 | 0, 캐시된 라벨맵·블랍표 조회 |
| 현재 이미지 결과표 | 2 / 0 / 0 | 0(캐시) |
| 임계값·타겟 변경 / 추론 결과 표시 | refilter(디코드 + `ufunc.at` 블랍 통계 + 오버레이) + 합성 2회 | refilter(블랍 통계 bbox 국소, D7) + 합성 1회(두 번째는 캐시 적중) |

### 2.4 캐시 무효화 규칙 (한곳에 모음)
| 캐시 | 키 | 무효화 조건 | 크기 |
|---|---|---|---|
| Zone 최종 마스크 (D3) | `mask_key` | 키 불일치 = class_map 객체 교체(refilter·추론·이미지 전환) / 타겟 클래스 변경 / 편집 리비전 변경 | 1개(현재 이미지) |
| Zone 라벨맵·블랍표 (D6) | `mask_key` (+ `circles_key`) | 위와 같음 + 원 목록 변경 | 1개 |
| Zone 색칠 레이어 (D4) | `mask_key` (편집 없음일 땐 `(id(class_map), None, rev)`) | 위와 같음 | 1개 |
| Zone 축소 원본 (D4) | `(image_path, (w, h))` | 경로·축소 크기 불일치 | 1개 |
| Zone 최종 오버레이 (D4) | `(mask_key, opacity)` | 위 + 불투명도 변경 | 1개(`_last_result.overlay_image` 그대로 재사용) |
| Zone zones (D15) | `(circles 튜플, (h, w))` | 원 추가·삭제·이동·이름·숨김 변경(튜플 값 비교라 자동) | 1개 |
| R 썸네일 (D10) | `(path, mtime_ns)` | 파일 수정 시각 변경 | 무제한 dict(56 px 아이콘, 장당 ~12 KB) |
| R 마스크 (기존) | 기존 `_mask_cache_*` 그대로 | 기존 그대로 | — |

캐시에서 돌려주는 numpy 배열은 **읽기 전용**(`arr.setflags(write=False)`)으로 둔다. 호출부가 실수로 제자리 수정하면 즉시 `ValueError`가 나서 캐시 오염이 조용히 퍼지지 않는다.

## 3. 설계 항목

### 3.1 설계 항목 표

우선순위: **1** = 체감 큼 + 쉬움(먼저), **2** = 체감 큼 또는 중간 난이도, **3** = 체감 작음/정리.

| # | 해결 지연 요소 | 변경 내용 (파일·함수) | 결과 동일성 보장 방법 | 위험·주의 | 우선 |
|---|---|---|---|---|---|
| D1 | P-R1, P-R4, P-R9, P-Z1, P-Z10, P-Z14 (+P-R2·P-R7·P-Z2~7의 바닥 비용) | `zone_metrics.apply_manual_strokes` (zone_metrics.py:112-128): 스트로크마다 스탬프 bbox 합집합을 구하고(`disk_mask`와 같은 `floor(cx-r)`, `ceil(cx+r)+1`, 이미지 경계 클램프), 그 크기의 지역 bool 배열에 `(xx-cx)**2+(yy-cy)**2 <= r**2`를 OR한 뒤 `result[y0:y1, x0:x1][local] = draw`. `r < 0`·bbox 밖 스탬프는 지금처럼 무시. 반환은 지금처럼 `mask.copy()` 기반 새 배열. `disk_mask` 자체는 그대로(`zones_from_circles`가 전체 크기 결과를 씀). 호출부(`apply_edits` 2곳, R 캔버스 증분, `ZoneCanvas.apply_manual_strokes`) 무변경 | 구 함수를 `scripts/check_perf_equivalence.py`에 그대로 복사해 두고, 무작위 스트로크(그리기/지우기 섞임, 겹침, 이미지 경계 밖·부분 걸침, `r=0`, 소수 좌표, 빈 스트로크, 빈 목록) × 크기 3종에서 `np.array_equal(old, new)`. `zone_metrics.apply_edits`(removed_points·removed_blob_ids 포함)와 `r_analysis_metrics.apply_edits`(4/5-원소 삭제 영역)도 구·신 비교 | 비교식은 `disk_mask`와 **문자 그대로 같은 식**이어야 함(float 비교 경계 픽셀). 스트로크 하나가 이미지 전체를 덮는 극단 케이스는 지금과 같은 비용(회귀 아님) | 1 |
| D2 | P-R15, P-Z9 | 안 읽히는 상태 삭제. Zone `zone_canvas.py`: `_replay_erase_strokes`(:428-441), `_erase_mask_np`와 `_erase_stamp`(:344-359)의 기록, `erase_mask()`(:316-319), `_stroke_overlay`·`_ensure_stroke_overlay`·`_rasterize_stroke`·`_rebuild_stroke_overlay`(:389-426)와 그 호출부. R `r_roi_canvas.py`: `_replay_erase_strokes`(:486-495), `_erase_mask_np`·`_erase_stamp` 기록, `erase_mask()`(:179-181). **R의 `_stroke_overlay`는 남긴다**(검출 마스크가 없을 때 `_paint_committed_strokes`가 그림, :551-560) | 삭제 전 `app/`·`scripts/`·`tests/` 전체 grep으로 읽는 곳이 없음을 확인해 7절 근거에 남긴다(코드맵: 테스트 docstring 1곳만 언급). 스트로크 목록(`_erase_strokes`/`_current_stroke`) 자체와 미리보기는 유지 → 결과 마스크 무관 | 읽는 곳이 하나라도 나오면 그 항목은 삭제하지 말고 "부분"으로 기록. 세션/사이드카에 `erase_strokes`를 저장하는 키는 형식 유지를 위해 그대로 둔다 | 1 |
| D3 | P-Z2, P-Z7, P-Z10 (+P-Z3·P-Z5의 재생분) | `ZoneCanvas`에 `self._edit_rev: int` + `edit_revision()` 추가, 편집 상태를 바꾸는 곳에서 `+= 1`: `set_blob_data`(:266), `set_state`(:492-519, undo 포함), `_handle_blob_click`의 `_removed_points.append`(:548), `mouseReleaseEvent`의 `_manual_strokes.append`(:792). 구현 전 `self._manual_strokes`/`_removed_points`/`_removed_blob_ids`/`_blob_labels` 대입·변경을 다시 grep해 빠진 곳이 없게 할 것. 탭 `_ai_and_final_masks` (zone_analysis_tab.py:1297-1308)에 1칸 캐시: 키 `(id(self._last_result.class_map), self._target_class_id, self._canvas.edit_revision())`, 적중 시 저장된 `(ai, final)` 반환, 미스 시 지금 코드 그대로 계산 후 `setflags(write=False)`하고 저장. 키에 쓰는 class_map 객체는 캐시가 참조를 쥐어 `id` 재사용을 막는다 | 계산 경로는 지금 코드 그대로(캐시는 같은 입력의 결과를 보관할 뿐). 검증: 앱 수준 스냅샷(6.3절) — e30 상태에서 존 비율·블랍표·Excel 행이 개선 전과 동일. 추가로 셀프체크 스크립트가 offscreen 탭에서 커밋·삭제·Undo·전환을 섞어 돌리며 매 단계 캐시 결과와 `zone_metrics.apply_edits` 직접 호출 결과를 `array_equal` | **무효화 누락 = 낡은 결과 표시**가 최대 위험. `class_map`이 제자리 수정되는 곳이 없는지 grep(`class_map[` 대입, `+=`)으로 확인. 반환 배열 읽기 전용으로 바꾼 뒤 기존 테스트·골든 패스에서 `ValueError`가 나는 호출부가 있으면 그 호출부에서 `.copy()` | 1 |
| D4 | P-Z4, P-Z3·P-Z6·P-Z10의 합성분 | `inference_engine._colorize_and_blend` (:611-656)를 본문 순서 그대로 두 함수로 나눈다: `_colorize_layer(class_map, cls_map) -> (class_map_work, color_img, foreground, (w, h))`와 `_blend(orig_np, color_img, foreground, opacity, w, h) -> QImage`. `_colorize_and_blend`는 두 함수를 잇는 3줄짜리로 남겨 기존 호출부(`run`, `refilter`, `reblend`, `colorize_class_map`) 무변경. 탭 `_reblend_overlay` (:1238-1267)는 (a) `mask_key`가 같고 opacity도 같으면 아무것도 안 함(현재 `overlay_image` 유지), (b) `mask_key`만 같으면 캐시된 레이어로 `_blend`만, (c) 다르면 지금처럼 corrected class_map을 만들어 `_colorize_layer` 후 캐시. 축소 원본 `orig_np = np.array(Image.open(p).convert("RGB").resize((w, h), BILINEAR))`는 `(path, (w, h))` 1칸 캐시. `load_classes()`도 레이어 재생성 때만 | 셀프체크: 무작위 class_map(작은 크기 + 2048 초과 크기) × opacity 3종에서 구 `_colorize_and_blend` 결과와 신 `_blend(_colorize_layer(...))`의 `QImage` 바이트(`bits().asstring(...)`) 동일. 앱 수준: e30·opacity 0.5/0.3에서 `_last_result.overlay_image` 해시가 개선 전과 동일 | `_preview_cache`(BUG-040, 2048 `thumbnail`)는 **재사용하지 않는다** — `thumbnail()`과 `resize(BILINEAR)`는 픽셀이 다르다. `QImage(blended.tobytes(), ...)`의 버퍼 수명은 지금과 같게 유지. `inference_engine.py`는 main과 공유 파일 — 함수 분리는 main 쪽 `_colorize_and_blend`와 sync 충돌 가능(본문이 같으면 충돌 작음). 이미 에디션에만 있는 `colorize_class_map` 바로 옆에 둔다 | 1 |
| D5 | P-Z3 | `_on_target_changed`의 `self._show_overlay_state()` (zone_analysis_tab.py:1204)를 `if not self._suppress_recompute:`로 감싼다 — 이미지 전환 중에는 사이드카 복원 뒤 `_recompute_zones`가 어차피 첫 줄(:1463)에서 합성하므로 복원 전 합성 1회는 버려진다. 전환이 아닐 때(타겟 콤보·임계값 변경)는 지금처럼 돈다(그리고 :1211의 두 번째 합성은 D4 (a)로 공짜) | 동작 동일성: 전환 후 화면 오버레이가 사이드카 **있음/없음** 두 경우 모두 지금과 같은 최종 이미지인지 앱 수준 해시로 확인 | 사이드카 없음 경로의 `clear_circles()`(:863)가 `_recompute_zones`를 부르지 않는다면 오버레이가 안 그려진다 — 구현 전 시그널 경로 확인 필수. 안 부르면 :863 블록 뒤에 `self._show_overlay_state()` 1줄 추가 | 2 |
| D6 | P-Z5, P-Z7 | 블랍 조회 클릭 `_on_canvas_blob_clicked` (:1535-1563): `final_mask[y, x]` 판정은 D3 캐시로 즉시. `compute_blob_labels(final)`(:1544)과 `zone_blob_stats(...)`(:1553)는 매번 새로 하지 말고 `_compute_zone_blob_rows`(:1399-1411)가 만든 결과를 `(mask_key, circles_key)` 1칸 캐시로 공유, 라벨맵은 `mask_key` 1칸 캐시. `_on_export_single`(:1567-1584)도 같은 캐시를 탄다 | 클릭한 블랍의 bbox·픽셀 수·AI 점수 표시 문자열, 결과표 행이 개선 전과 동일(앱 수준 스냅샷). `zone_blob_stats`의 `blob_id`가 `compute_blob_labels`와 같은 라벨 체계라는 기존 가정(:1554)은 바꾸지 않음 | `circles_key`는 `circles_with_ids()` 튜플 전체(이름·숨김 포함) — 숨김 토글도 블랍표 zone 귀속은 같지만 단순하게 키에 포함 | 2 |
| D7 | P-Z6 | `inference_engine._compute_blobs_and_filter` (:518-588): `np.minimum.at`/`np.maximum.at`(:550-553, 전체 픽셀 산포)를 없애고, **채택된 블랍만** `stats`의 bbox로 `labels`·`confidence_map`을 잘라 `conf[lab == lbl]`의 min/max를 구한다(기각 블랍은 min/max를 안 쓴다). 평균·면적·기각 판정(`bincount`, `stats`)은 그대로 | 셀프체크: 무작위 raw_class_map·confidence_map(블랍 10·500개, 경계 걸침, 1픽셀 블랍) × 임계값 조합에서 구·신 반환 `(filtered, blobs)` 비교 — `np.array_equal(filtered)`, `blobs` 리스트의 dataclass `==`. float64 변환은 지금처럼 크롭에 적용(값 동일) | main과 공유 파일 — 같은 개선을 main에도 할지는 별도 결정(`docs/decisions-needed.md`에 추가). 링 모양처럼 bbox가 큰 블랍이 많으면 bbox 면적 합이 커질 수 있으나 상한은 블랍 수 × 전체 프레임이 아니라 실제 bbox 합 — 벤치 `_b500`로 확인 | 2 |
| D8 | P-R5, P-R6, P-R4 | `RRoiCanvas._rebuild_mask_image` (r_roi_canvas.py:528-537): RGBA 배열 생성 대신 `mask.view(np.uint8)`(C 연속 보장, 아니면 `np.ascontiguousarray`)을 `QImage(buf, w, h, w, Format_Indexed8)`로 무복사 래핑하고 `setColorTable([0, qRgba(*_COLOR_MASK[:3], alpha)])`. 래핑한 numpy 버퍼는 `self._mask_image_buf`로 참조 유지. `set_mask_opacity` (:183-188)는 `_rebuild_mask_image` 대신 컬러 테이블만 교체. `mask.any()` 판정은 `np.count_nonzero` 없이 지금처럼 유지(빈 마스크 → `None`) | 저장·면적과 무관(화면만). 화면 동일성: `canvas.grab()`을 fit·2배 확대·opacity 0/128/255에서 개선 전과 픽셀 비교 — **목표 완전 일치**. 차이가 나면(래스터 변환 반올림) 최대 차이와 위치를 7절에 적고 리더가 수용 여부 판단 | 캐시된 effective mask가 바뀌면 버퍼도 바뀌므로 `_rebuild_mask_image`는 마스크가 바뀔 때 그대로 호출(무효화 규칙 기존과 동일). `_COLOR_MASK`가 QColor인지 튜플인지 확인 후 `qRgba` 인자 맞출 것 | 1 |
| D9 | P-R2 | `RAnalysisTab._load_image` (r_analysis_tab.py:745-760): `blockSignals` 블록 안에서 `set_state` **앞에** `self._canvas.set_detected_mask(None)` 1줄 추가 — 그러면 `_restore_state`의 `_rebuild_mask_image`는 `effective_mask() is None`이라 재생 없이 끝나고, 재생은 뒤의 `set_detected_mask(mask)` 1회만 | 이미지별 `data["area"]`(:763)가 개선 전과 동일, 전환 후 `effective_mask()` 동일(앱 수준 스냅샷). `set_detected_mask(None)`이 하는 부수효과(선택·하이라이트 리셋, `mask_changed`)는 바로 뒤 `set_state`/`set_detected_mask`가 어차피 똑같이 하고 시그널은 막혀 있음 | `_restore_state`의 `_rebuild_stroke_overlay`(31 ms @4000)는 이 순서에선 검출 마스크가 None인 동안 돌아 그대로 남는다 — 지연 생성으로 바꾸려면 `_rasterize_stroke`/`_ensure_stroke_overlay`와 얽혀 위험해서 이번엔 안 함(3.2절 보류) | 1 |
| D10 | P-R3, P-R14 | `RAnalysisTab._refresh_thumb_strip` (:797-810): `QPixmap(str(p)).scaled(...)` 대신 `QImageReader(str(p))` → `reader.size()`로 가로세로비 유지한 56 px 크기 계산 → `setScaledSize` → `read()`. 결과 `QIcon`을 탭의 dict `_thumb_cache[(p, mtime_ns)]`에 저장해 재방문·폴더 가져오기 2회 구성(P-R14)은 디코드 0. 읽기 실패 시 지금처럼 빈 아이콘(=`QPixmap(path)` 실패와 같은 결과) | 결과 데이터 무관(화면 썸네일만). 썸네일 픽셀은 축소 알고리즘이 달라 **미세하게 달라질 수 있다**(동작 동일성 원칙의 "결과 픽셀"이 아님 — 7절에 명시). 크기·종횡비·순서·선택 상태는 동일해야 함 | `QPixmap(path)`의 EXIF 회전 처리와 같게: `QImageReader` 기본 `autoTransform` 값을 바꾸지 않는다(같은 Qt 경로). `mtime`은 `os.stat` 실패 시 캐시 안 함 | 1 |
| D11 | P-R7 | `RAnalysisTab._on_settings_changed` (:814-825): 갱신 전 `threshold`·`auto_detect` 값을 기억해 두고 **둘 중 하나라도 바뀐 경우에만** `_run_and_display_detection` 호출. 분모·스펙만 바뀌면 세션 값 저장·요약·우측 패널·버튼·자동 저장만 | 분모·스펙 변경 후 우측 패널 표 값·판정이 개선 전과 동일(앱 수준 스냅샷). 재검출을 건너뛰어도 검출 입력(이미지·ROI·threshold·auto_detect)이 그대로라 마스크가 같다 — `_compute_detected_mask`가 이 외의 세션 값을 읽는지 grep으로 확인 | `_compute_detected_mask`가 분모·스펙을 읽는다면 이 항목 취소 | 1 |
| D12 | P-R8 | `RAnalysisTab._load_session` (:596-599) 끝에서 설정 패널의 디바운스 타이머를 정지 — `RSettingsPanel`에 1줄 메서드(예: `cancel_pending()` → `self._debounce.stop()`) 추가 후 호출 | 세션 열기 직후 상태(마스크·면적·우측 패널)가 개선 전과 동일, 세션 파일이 열기만으로 다시 쓰이지 않음(수정 시각 불변) — 지금은 쓰지만 내용은 같았으므로 데이터 동일 | 로드 뒤 `settings_changed`에 의존해 갱신되던 UI(요약 라벨 등)가 있는지 확인 — 있으면 그 갱신을 로드 경로에서 직접 1회 호출 | 2 |
| D13 | P-R11 (+ Zone 존 통계 바닥 비용 일부) | bool 마스크의 `.sum()`을 `np.count_nonzero`로: `r_analysis_metrics.contour_area` (:107-108), `zone_metrics.zone_stats` (:180~)의 bool 면적 합. **bool 배열인 곳만**(정수 배열 `.sum()`은 의미가 다름) | 정수 결과 동일 — 셀프체크에서 무작위 bool 마스크로 `int(m.sum()) == np.count_nonzero(m)`, 앱 수준 스냅샷의 면적·비율 동일 | 입력이 bool이 아닌 경로(예: uint8 마스크)가 들어오는지 호출부 확인. 확실치 않으면 `np.count_nonzero(mask)`는 0이 아닌 개수라 0/1 uint8이면 같지만 0/255면 sum과 다름 → bool만 | 3 |
| D14 | P-Z11 | `_ZoneCircleLayoutWorker.run` (zone_analysis_tab.py:142-143): `Image.open(p).convert("RGB").size` → `Image.open(p).size` (헤더만) | `convert`는 크기를 바꾸지 않음 → 값 동일. 배치 결과 원 좌표가 개선 전과 동일 | 파일 핸들: `with Image.open(p) as im: im.size`로 닫기 | 3 |
| D15 | P-Z10 | 탭 `_current_zones` (:1374-1383)에 1칸 캐시: 키 `(tuple(circles_raw), (h, w))`. 원판 마스크(원마다 전체 프레임 `disk_mask`) 재계산을 원이 바뀔 때만 | 키가 값 비교라 원이 바뀌면 자동 미스. 존 비율·블랍표 동일(앱 수준 스냅샷). `Zone.mask` 배열 읽기 전용 처리 | `circles_with_ids()`가 리스트 안에 변경 가능한 객체를 주면 `tuple()`로 값 고정이 안 됨 — 원소가 튜플인지 확인 | 3 |

설계 항목 수: **15개 (D1~D15)**. 매칭률 분모에 들어간다(7절).

### 3.2 보류 항목 (이번 설계에서 다루지 않음 — 매칭률 분모에서 제외)

| 지연 요소 | 보류 이유 | 다시 볼 조건 |
|---|---|---|
| P-R9 일괄 검출 후 메인 스레드 재검출 | D1 적용 후 남는 메인 스레드 몫은 디코드 캐시 적중 + 검출 15 ms + 재생 수십 ms로 100 ms 안팎. 워커 결과 재사용은 워커→탭 데이터 경로를 새로 내야 해 비용 대비 효과 낮음 | `batch_cell_5img` e30 후측정이 목표(4절)를 넘으면 |
| P-R10 편집 뒤 첫 블랍 클릭 전체 라벨링 | 24 ms(4000) — 체감 하 | — |
| P-R12 자동 저장 직렬화 | 보통 8 ms, 최악 79 ms(4000). indent 제거는 저장 파일 바이트가 바뀜(형식 불변 원칙) | 사용자가 대형 세션 저장 끊김을 보고하면 워커 이동으로 |
| P-R13 / P-Z13 진행 중 획 미리보기 | offscreen 16 ms 미만, 실기 미측정 | 실기에서 끊김 보고 시 |
| P-R2의 `_rebuild_stroke_overlay` 지연 생성 (31 ms @4000) | 커밋 시 `_ensure_stroke_overlay`/`_rasterize_stroke`와 얽혀 지연 생성으로 바꾸면 스트로크 누락 회귀 위험 | `image_switch_list_*` 후측정이 목표를 넘으면 |
| R 이미지별 최종 마스크 LRU | D1로 재생 1회가 수십 ms가 되어 불필요 | — |
| P-Z6의 refilter 오버레이 생성 생략(약 140 ms @4000) | `refilter` 시그니처 변경(main 공유) + 오버레이가 숨김일 때 `overlay_image`가 None으로 남는 경로(결과 이미지 일괄 저장 등) 위험 | `conf_threshold_change` 후측정이 목표를 넘으면 |
| P-Z6 연속 드래그 중 워커 처리 | D7 후 1회 비용을 먼저 확인 | 위와 같음 |
| P-Z8 결과 이미지 일괄 저장 PNG 인코딩 | 50장 15 s는 **추정**(미측정). 워커 + 진행률 UI가 필요해 디자인 범위가 생김 | 별도 라운드(디자인 포함) |
| P-Z12 추론 전 미리보기 `Image.draft` | 95 ms(4000)·하, 미리보기 픽셀이 바뀜 | — |
| Zone 커밋 레이어의 축소-먼저 계산 (corrected class_map을 원본 해상도로 만들지 않고 NEAREST 축소 후 적용) | NEAREST 축소는 점별 연산과 교환 가능해 결과는 같게 만들 수 있지만 검증 부담이 큼 | `brush_commit` e30 후측정이 목표를 넘으면 |
| Zone 증분 재생(새 스트로크 1개만 덧적용, R 캔버스 방식) | D1 후 전체 재생도 수십~100 ms 예상. 삭제 지점 구간 분할과 얽혀 복잡 | 위와 같음 |

## 4. 목표 수치

메인 스레드 멈춤 중앙값(ms), `4000×3000 / 5472×3648`. 현재값은 `r_before.json` / `zone_before.json`(Zone은 블랍 ~10개 열). 목표는 단가 실측(R 코드맵 3.2절: 재생 3152 → 21 ms, RGBA 58 → 0.004 ms, 썸네일 79 → 20 ms/장)과 남는 고정 비용에서 잡은 **추정 목표**이며 설계 검토에서 조정 가능. 시나리오 이름은 벤치 출력 그대로.

### 4.1 R 탭 (`scripts/bench_r_tab.py`)
| 조작 | 시나리오 (편집) | 현재 4000 / 5472 | 목표 4000 / 5472 | 설계 항목 |
|---|---|---:|---:|---|
| 편집 이미지로 전환 | `image_switch_list_warm` (e30) | 4087 / 9756 | ≤ 150 / ≤ 250 | D1, D8, D9 |
| 편집 없는 이미지로 전환 | `image_switch_list_warm` (e0) | 145 / 229 | ≤ 60 / ≤ 90 | D8, D9 |
| 50장 셀로 전환 | `cell_switch_to_50img` (e0) | 3922 / 6484 | ≤ 1200 / ≤ 1800 (첫 방문 상한, 재방문은 ≤ 100) | D10 |
| 세션 열기 | `session_open` (e0) | 631 / 1103 | ≤ 250 / ≤ 400 | D8, D10, D12 |
| Delete | `delete_blob` (e30) | 2043 / 4889 | ≤ 100 / ≤ 150 | D1, D8 |
| Ctrl+Z | `undo_brush` (e30) | 2163 / 4891 | ≤ 100 / ≤ 150 | D1, D2, D8 |
| threshold 변경 | `threshold_change` (e30) | 2079 / 4901 | ≤ 120 / ≤ 180 | D1, D8 |
| 분모 변경 | `denominator_change` (e30) | 2013 / 4879 | ≤ 15 / ≤ 20 | D11 |
| 브러시 커밋 | `brush_commit` (e30) | 153 / 284 | ≤ 30 / ≤ 40 | D1, D8 |
| 불투명도 1틱 | `opacity_step` (e30) | 79 / 98 | ≤ 8 / ≤ 8 | D8 |
| 일괄 검출(편집 1장 포함) | `batch_cell_5img` (e30) | 4314 / 10085 | ≤ 500 / ≤ 800 | D1 |

### 4.2 Zone 탭 (`scripts/bench_zone_tab.py`)
| 조작 | 시나리오 (편집) | 현재 4000 / 5472 | 목표 4000 / 5472 | 설계 항목 |
|---|---|---:|---:|---|
| 영역 삭제 클릭 | `delete_blob` (e30) | 7201 / 15009 | ≤ 350 / ≤ 500 | D1, D3, D4, D15 |
| 편집 이미지로 전환 | `image_switch_list_warm` (e30) | 6049 / 12772 | ≤ 400 / ≤ 550 | D1, D2, D3, D4, D5 |
| 편집 없는 이미지로 전환 | `image_switch_list_warm` (e0) | 514 / 670 | ≤ 300 / ≤ 400 | D4, D5 |
| Ctrl+Z | `undo_brush` (e30) | 5907 / 12495 | ≤ 300 / ≤ 450 | D1, D2, D3, D4 |
| 브러시 커밋 | `brush_commit` (e30) | 5548 / 11677 | ≤ 300 / ≤ 450 | D1, D3, D4, D15 |
| 브러시 커밋(편집 없음) | `brush_commit` (e0) | 511 / 777 | ≤ 250 / ≤ 350 | D3, D4, D15 |
| 긴 획 커밋 | `brush_commit_long` (e0) | 1926 / 3248 | ≤ 300 / ≤ 450 | D1, D3, D4 |
| 불투명도 1단계 | `opacity_step` (e30) | 2071 / 3891 | ≤ 40 / ≤ 60 | D3, D4 |
| 오버레이 다시 보이기 | `overlay_toggle_on` (e30) | 1891 / 3919 | ≤ 20 / ≤ 30 | D3, D4 |
| 존 조회 클릭 | `zone_click_select` (e30) | 1697 / 3655 | ≤ 15 / ≤ 20 | D3 |
| 블랍 조회 클릭 | `blob_click_select` (e30) | 1931 / 3790 | ≤ 30 / ≤ 40 | D3, D6 |
| 현재 이미지 결과표 | `export_single_open` (e30) | 3500 / 7417 | ≤ 60 / ≤ 90 | D3, D6, D15 |
| AI 신뢰도 변경 | `conf_threshold_change` (e0) | 1212 / 1729 | ≤ 550 / ≤ 800 | D4, D7 |
| 전체 결과 보기(워커) | `view_all_results` (e30) | 1875 / 3942 | ≤ 400 / ≤ 600 | D1 |
| 배치 영역 적용(워커) | `batch_apply_circles` (e30) | 568 / 877 | ≤ 150 / ≤ 200 | D14 |

**회귀 감시**(목표 아님, 현재값 대비 +20% 이내 유지): 두 벤치의 드래그 프레임(`brush_move`, `pan_move`, `zoom_wheel`, `paint_repaint` 등)과 `autosave*`, `excel_export`, `save_all_images`, `_b500` 열 전체.

## 5. 구현 순서 (단계마다 커밋 가능)

각 단계 끝에 공통으로: ① `python scripts/check_perf_equivalence.py`(0 종료) ② 해당 탭 기존 셀프체크·테스트(`tests/` 중 해당 파일, 있는 경우) ③ 부분 벤치. 벤치에는 시나리오 필터가 없으므로 부분 실행 = 크기 1개·반복 1회:
```
set QT_QPA_PLATFORM=offscreen & set PYTHONPATH=D:\segmentation model-zone-analysis-tab
python scripts/bench_r_tab.py    --sizes 4000x3000 --repeat 1 --out r_stepN.json    --compare <스크래치>/perf_2026_11_11/r_before.json
python scripts/bench_zone_tab.py --sizes 4000x3000 --repeat 1 --blobs 10 --out zone_stepN.json --compare <스크래치>/perf_2026_11_11/zone_before.json
```
(`--compare`는 크기가 다른 열을 `-`로 둔다. 벤치 결과 JSON은 스크래치에 두고 커밋하지 않는다.)

| 단계 | 항목 | 커밋 메시지 예 | 단계별 확인 |
|---|---|---|---|
| 0 | `scripts/check_perf_equivalence.py` 신설 — **코드 수정 전에** 구 함수(`apply_manual_strokes`, 두 `apply_edits`, `_colorize_and_blend`, `_compute_blobs_and_filter`)를 스크립트 안에 그대로 복사해 "구" 기준으로 고정. 이 시점엔 구=신이라 통과해야 함 | `test: 성능 개선 결과 동일성 셀프체크 추가` | 스크립트 통과. 앱 수준 스냅샷 기준선 저장(6.3절) |
| 1 | D1, D13 (공용 core) | `perf: 편집 재생을 스탬프 bbox 국소 연산으로` | 셀프체크 통과 + R·Zone 두 벤치 부분 실행(`undo_brush`, `delete_blob`, `image_switch_list_warm` e30이 수 배 이상 감소) |
| 2 | D2 (두 캔버스 삭제) | `refactor: 안 읽히는 지우개 마스크·스트로크 오버레이 제거` | grep 근거 기록, Zone `undo_eraser`/`image_switch_list_warm` e30 감소, 지우개 미리보기 화면 정상 |
| 3 | D8, D9, D11, D12 (R 탭) | `perf: R 탭 마스크 오버레이 Indexed8 + 전환 재생 1회 + 설정 변경 재검출 축소` | R 벤치 부분 실행(`opacity_step`, `brush_commit`, `denominator_change`, `session_open`), `canvas.grab()` 비교 |
| 4 | D10 (R 썸네일) | `perf: R 탭 썸네일 축소 디코드 + 캐시` | `cell_switch_to_50img`, `import_folder` |
| 5 | D3, D6, D15 (Zone 마스크·파생 캐시) | `perf: Zone 탭 최종 마스크·블랍표·존 캐시` | 셀프체크의 캐시 시퀀스 검사, Zone 벤치 부분 실행(`zone_click_select`, `blob_click_select`, `export_single_open`) |
| 6 | D4, D5 (Zone 오버레이) | `perf: Zone 탭 오버레이 레이어 캐시 + 전환 중 합성 1회` | 오버레이 바이트 비교, `opacity_step`, `overlay_toggle_on`, `image_switch_list_warm` |
| 7 | D7, D14 | `perf: refilter 블랍 min/max bbox 국소 계산 + 배치 크기 헤더만 읽기` | 셀프체크, `conf_threshold_change`, `batch_apply_circles` |
| 8 | 버전·문서 | `docs: ...` | `release.ini` zone 버전 PATCH 올림(성능 개선·호환), `docs/CHANGELOG.md` 같은 태그 제목, `scripts/generate_version_info.py` 검증. 7절 매칭률 표 채움 |

구현자는 단계마다 7절 표의 해당 행을 채우고 `docs/agents/implementation-log.md`에 단계별 부분 벤치 수치를 남긴다.

## 6. 검증 계획

### 6.1 같은 벤치 전/후 비교
- 전체 실행(각 약 10분):
  ```
  python scripts/bench_r_tab.py    --out r_after.json    --compare <스크래치>/perf_2026_11_11/r_before.json
  python scripts/bench_zone_tab.py --out zone_after.json --compare <스크래치>/perf_2026_11_11/zone_before.json
  ```
  픽스처는 `--fixtures` 기본 폴더 캐시를 그대로 써 같은 입력. 결과 표를 7.2절 "목표 수치 달성률"에 옮긴다.
- 회귀 감시 시나리오(4절 끝)가 +20%를 넘으면 원인 확인 후 보고.

### 6.2 기능 회귀 (실제 UI 조작 — 주요 기능 라운드이므로 골든 패스 포함)
**R 탭**: 세션 열기 → 셀 전환(5장/50장) → 썸네일·목록·이전/다음 전환 → ROI 지정·이동·리사이즈 → threshold·분모·스펙·자동 검출 토글(분모·스펙만 바꿨을 때 표 값 갱신 확인) → 브러시/지우개 커밋 → 블랍 선택·Delete → Ctrl+Z 반복 → 불투명도 슬라이더·마스크 보이기 토글 → 검출 마스크가 없을 때(자동 검출 끔) 커밋 스트로크가 화면에 보이는지 → 일괄 검출 → 자동 저장 후 세션 재열기 시 편집·면적 동일 → 폴더 가져오기.
**Zone 탭**: 추론 → 결과 표시 → 타겟 클래스·AI 신뢰도·최소 픽셀 변경 → 원 설정 모달 적용 → 브러시/지우개 커밋 → 영역 삭제 클릭 → Ctrl+Z 반복 → 불투명도·F 토글 → 존/블랍 조회 클릭(정보 라벨·하이라이트) → 존 목록 이름 변경·숨김 → 이미지 전환(사이드카 있음/없음, 추론 전/후) → 현재 이미지 결과표 → 전체 결과 보기 → 배치 영역 적용 → 결과 이미지 일괄 저장 → Excel 내보내기 → 앱 재시작 후 사이드카 복원 동일.
**알려진 동작 유지 확인**: 임계값·타겟 변경 시 편집·Undo 초기화(P-Z6 메모)와 재추론 시 편집 초기화(BUG-065)는 **지금과 같게** 일어나야 한다(고치지 않음).

### 6.3 결과 동일성 비교
1. **함수 수준**: `scripts/check_perf_equivalence.py` (5절 단계 0) — 구·신 `np.array_equal` / QImage 바이트 / `blobs` dataclass 동일. 0 종료가 아니면 실패.
2. **앱 수준 스냅샷**: 검증자는 개선 전 커밋 `df2fe39`로 임시 워크트리(`git worktree add <스크래치>/wt_before df2fe39`)를 만들고, 같은 픽스처·같은 조작 순서(벤치의 e30 구성 재사용)로 아래 값을 JSON으로 뽑아 전/후 비교(스크립트는 스크래치에 둠, 커밋 안 함):
   - R: 이미지별 `data["area"]`, `effective_mask()`의 SHA-1, 우측 패널 표 문자열, 저장된 세션 JSON 바이트.
   - Zone: `_ai_and_final_masks()` 두 배열의 SHA-1, `_compute_zone_percentages()`, `_compute_zone_blob_rows()`, `_last_result.overlay_image` 바이트 SHA-1(opacity 0.5/0.3), 블랍 조회 정보 라벨 문자열, 사이드카 JSON 바이트, Excel 행.
   - 전부 완전 일치여야 함. 예외는 R 썸네일 픽셀(D10, 화면 전용)과 D8 화면 grab(완전 일치 목표, 어긋나면 수치 보고).
3. 임시 워크트리는 검증 후 `git worktree remove`.

## 7. 구현 매칭률 기록

구현자가 채우고, 검증자가 같은 표를 **독립 확인**해 "검증" 열을 채운다(구현자 기록과 다르면 검증자 판정을 우선하고 차이를 비고에 남김). 근거는 `파일:행`(구현 커밋 기준).

### 7.1 설계 항목별 매칭

| # | 상태 (구현/부분/미구현) | 구현 커밋 | 설계와 다른 점 | 근거 (파일:행) | 동일성 확인 결과 | 검증 (일치/불일치 + 메모) |
|---|---|---|---|---|---|---|
| D1 |  |  |  |  |  |  |
| D2 |  |  |  |  |  |  |
| D3 |  |  |  |  |  |  |
| D4 |  |  |  |  |  |  |
| D5 |  |  |  |  |  |  |
| D6 |  |  |  |  |  |  |
| D7 |  |  |  |  |  |  |
| D8 |  |  |  |  |  |  |
| D9 |  |  |  |  |  |  |
| D10 |  |  |  |  |  |  |
| D11 |  |  |  |  |  |  |
| D12 |  |  |  |  |  |  |
| D13 |  |  |  |  |  |  |
| D14 |  |  |  |  |  |  |
| D15 |  |  |  |  |  |  |

**판정 기준**
- 구현 = 3.1절 "변경 내용"을 모두 반영 + "결과 동일성 보장 방법"의 확인을 통과.
- 부분 = 일부만 반영했거나, 반영했지만 동일성 확인 일부가 미실시/불일치(이유를 "설계와 다른 점"에 적음).
- 미구현 = 손대지 않았거나 되돌림. 설계 검토(8절)에서 **취소**된 항목은 "취소"로 적고 분모에서 뺀다.

**매칭률 = (구현 수 + 0.5 × 부분 수) / (설계 항목 수 − 취소 수) × 100 %**
- 설계 항목 수 = 15 (D1~D15). 3.2절 **보류 항목은 처음부터 분모에 넣지 않는다.**
- 결과 동일성 확인이 불일치인 항목은 구현됐더라도 "부분"으로 센다.

| 구현 | 부분 | 미구현 | 취소 | 분모 | 매칭률 |
|---:|---:|---:|---:|---:|---:|
|  |  |  |  |  |  % |

### 7.2 목표 수치 달성률

4절 표의 각 행을 옮긴다. 후측정은 6.1절 전체 실행값(중앙값).

| 탭 | 시나리오 (편집) | 크기 | 현재 | 목표 | 후측정 | 달성 (O/X) | 비고 |
|---|---|---|---:|---:|---:|---|---|
| R | `image_switch_list_warm` (e30) | 4000 | 4087 | ≤ 150 |  |  |  |
| R | `image_switch_list_warm` (e30) | 5472 | 9756 | ≤ 250 |  |  |  |
| … | (4.1·4.2절의 나머지 행을 같은 형식으로, 크기별 1행) |  |  |  |  |  |  |

**목표 수치 달성률 = 달성(O) 행 수 / 전체 행 수 × 100 %** (4.1 + 4.2절 = 26개 조작 × 2 크기 = 52행). 회귀 감시 시나리오가 +20%를 넘은 개수도 따로 적는다: `회귀 n건`.

| 달성 행 | 전체 행 | 달성률 | 회귀 건수 |
|---:|---:|---:|---:|
|  | 52 |  % |  |

## 8. 설계 검토 반영 기록

*(다음 단계 설계 검토자가 작성한다. 형식: 지적 번호 / 대상 항목(D#·절) / 지적 내용 / 반영 결과(수정·취소·유지와 이유) / 반영 위치.)*

| # | 대상 | 지적 | 반영 결과 | 반영 위치 |
|---|---|---|---|---|
|  |  |  |  |  |
