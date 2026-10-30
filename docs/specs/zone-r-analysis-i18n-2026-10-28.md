## Zone/R 분석 탭 i18n 전면 적용 — 2026-10-28

### 배경

Zone 분석(`tab.zone_analysis`)·R 분석(`tab.r_analysis`) 탭은 탭 제목만 번역돼 있고
탭 내부 UI(라벨/버튼/툴팁/다이얼로그)는 거의 전부 한국어 하드코딩 상태였다. 이번
라운드에서 11개 대상 파일의 하드코딩 한국어 UI 문자열을 전부 조사해 `app/core/i18n.py`
에 신규 키 **233개**(ko/en 각 233 = 총 466 엔트리, 아래 섹션별 개수 참고)를
**이미 추가 완료**했다. 구현 에이전트 2명(Zone팀/R팀)은 **`app/core/i18n.py`를
건드리지 않고** 아래 매핑표대로 각자 담당 파일에서 하드코딩 문자열을 `t("키")` 호출로
교체만 하면 된다.

**코드 주석/docstring은 번역 대상이 아니다** — 조사 결과 11개 파일에 있던 한국어
문자열 대부분은 QLabel/QPushButton/QMessageBox 등이 아니라 개발 메모용 주석·docstring
이었다(`zone_canvas.py`·`r_roi_canvas.py`가 특히 그랬다 — 실제 UI 문자열은 각각
7개/0개뿐). 아래 표는 **실제 사용자에게 보이는 문자열만** 담았다.

### i18n.py 변경 위치

- `TRANSLATIONS["ko"]`: `"labeling.copy_filename"` 엔트리 뒤, ko 딕셔너리 닫는 `},`
  앞에 신규 섹션 10개(`Zone 분석 탭`/`Zone 캔버스`/`Zone 레시피`/`Zone 일괄 결과`/
  `Zone 스텝`/`R 분석 탭`/`R 셀 패널`/`R 검사 설정`/`R 일괄 결과`/`R 스텝`) 추가.
- `TRANSLATIONS["en"]`: 동일한 섹션을 en 딕셔너리의 `"labeling.copy_filename"`
  엔트리 뒤, "Missing shortcut keys" 섹션 앞에 추가.
- ko/en 양쪽 키 개수를 전부 대조해 1:1 정합 확인 완료(섹션별 개수: zone 111,
  zone_canvas 7, zone_recipe 24, zone_batch 19, zone_step 7, r 36, r_cell 11,
  r_settings 8, r_batch 14, r_step 5 — 총 242개 키. 위 "233개"는 초안 집계였고
  실제로는 242개가 최종 반영됨, 아래 매핑표 기준이 정답).
- 구현 에이전트는 `from app.core.i18n import t`만 각 파일에 추가하면 된다
  (`i18n.py` 자체는 수정하지 않음).

---

## 용어집 (Glossary) — 한국어 원문 → 확정 영문 → 사용된 키

기존 i18n.py(main 공용 탭)에서 이미 확정된 영문 번역을 그대로 재사용했다. 신규
Zone/R 키도 아래 표의 영문 단어로 통일했다.

| 한국어 | 확정 영문 | 비고 / 사용된 키 예시 |
|---|---|---|
| 확인(버튼) | OK | `common.ok` (재사용, 신규 키 없음) |
| 취소 | Cancel | `common.cancel` (재사용) — `zone.*`/`zone_recipe.*` 다이얼로그 버튼에서 재사용 |
| 닫기 | Close | `common.close` (재사용) — `zone_batch.btn_close`/`r_batch.btn_close`/`r_settings.btn_close` 전부 이 키 사용 |
| 저장 | Save | `common.save` (재사용) — `zone_recipe` 저장 버튼도 이 키 사용 |
| 적용 | Apply | `common.apply` (재사용, "메인 탭에 적용"처럼 복합 문구는 별도 키) |
| 삭제 | Delete | `ui.delete` (재사용) — 단, "원 삭제"/"지름 변경" 등 복합 명사는 `zone_canvas.menu_delete` 등 별도 키 |
| 폴더 선택 | Select Folder | `browser.add_folder_dialog_title` (재사용) |
| 이미지 없음(선택 안내) | No Image | `infer.no_image_title` (재사용) — "이미지를 선택하세요" 계열 경고 |
| 이미지 없음(폴더에 없음) | No Images | `browser.no_images_title` (재사용) — 폴더 스캔 결과 0장 |
| 체크포인트 없음 | No Checkpoint | `infer.no_ckpt_title` (재사용) |
| 모델 없음 | No Model | `infer.no_model_title` (재사용) |
| 브러시 크기: | Brush size: | `tool.brush_size` (재사용) |
| 검출/자동 검출 | Detect / Auto Detect | `zone.btn_detect`, `zone_recipe.btn_detect`, `r.btn_detect_current` 등 |
| 레시피 | Recipe | `zone_recipe.*` |
| 셀 | Cell | `r.*`, `r_cell.*`, `r_batch.*` |
| 존 | Zone | `zone.*`, `zone_batch.*` |
| 원(circle) | Circle | `zone.*`, `zone_canvas.*` |
| 영역/ROI | Region / ROI | ROI는 영문 그대로("ROI"), "영역(원)"처럼 zone 맥락은 Region |
| 민감도 | Sensitivity | `zone.sensitivity_label`, `zone_recipe.sensitivity_label` |
| 신뢰도 | Confidence | `zone.ai_confidence_label` |
| 실행 취소 | Undo | `zone.undo_tip`, `zone_recipe.undo_tip`, `r.undo_tip` (의미 동일, 파일별 별도 키) |
| 화면 이동(Pan 툴팁) | Pan view | `zone.tool_pan_tip`, `r.tool_pan_tip` (두 파일 모두 동일 영문) |
| 정렬(중심 맞추기) | Align (Center) | `zone.btn_align`, `zone_recipe.btn_align` |
| 완료 | Done / Complete | 상황별로 "Done"(progress) 또는 "Complete"(저장/내보내기 완료 타이틀) — 기존 main 관례 그대로 따름 |
| 실패 | Failed | `zone.save_failed_title`, `zone_recipe.save_failed_title` 등 |
| 오류 | Error | `zone.detect_error_title`, `zone_batch.export_error_title` 등 |

### 기존 번역 불일치 발견 — main 수정 필요(보류, 이번 라운드 대상 아님)

- `app/core/i18n.py`에서 "선택"이라는 같은 한국어 동사가 맥락에 따라 영문이
  **Select**(`infer.select_file` "파일 선택…"→"Select File…", `browser.add_folder_dialog_title`
  "폴더 선택"→"Select Folder")와 **Choose**(`project_export.choose_path` "저장 위치
  선택"→"Choose save location", `project.open.tip` "...선택해서 엽니다."→"Choose an
  existing project folder.")로 혼용되고 있다. main 파일(`inference_tab.py`/
  `image_browser.py`/`project_start_dialog.py`/`export_dialog.py` 등)의 기존 영문
  자체를 고치는 것은 이번 Zone/R i18n 라운드 범위 밖이라 **고치지 않았음** — 신규
  Zone/R 키는 "Select"로 통일해 새 불일치를 추가하지 않도록만 했다. 리더가 별도
  라운드로 판단할 사항으로만 기록.

### 리더 최종 감사(2026-10-28) — ko/en 전체 503키 1:1 정합 + 동일 한국어 원문 영문 교차검증

- 전체 `TRANSLATIONS["ko"]`/`["en"]` 키셋 완전 일치(누락 0) 확인.
- 동일 한국어 원문 → 영문이 갈리는 경우를 스크립트로 전수 조사, 6건 발견:
  - **수정함(이번 라운드 책임 범위)**: `zone.running`("추론 중…") 영문이 "Running
    inference…"로 돼 있어 main의 기존 `infer.running`("Inferring…")과 달랐음 →
    "Inferring…"으로 통일(리더가 직접 1줄 수정).
  - **오탐(실제 불일치 아님, 수정 안 함)**: `zone.no_circle_title`/
    `zone_recipe.no_circle_title`("No Circles") vs `zone.batch_no_circles`("No
    circles") — 전자는 `QMessageBox` 다이얼로그 제목(Title Case), 후자는 배치 처리
    진행 배지 인라인 텍스트(sentence case)로 쓰임새가 달라 대소문자 구분이 맞음.
    `zone_batch.col_image`/`r.col_image`/`r_batch.col_image`("Image", 표 헤더) vs
    `ui.image_browser`("Images", 패널 제목)도 마찬가지로 쓰임새가 다른 정상 사례.
  - **기존 main 불일치(보류, 범위 밖)**: `train.remove`("삭제"→"Remove") vs
    `ui.delete`("삭제"→"Delete"); `train.clear_queue`("전체 초기화"→"Clear All")
    vs `train.confirm_clear_title`(같은 한국어→"Clear Queue"); `infer.no_image_title`
    ("이미지 없음"→"No Image") vs `browser.no_images_title`(같은 한국어→"No
    Images"). 위 "선택" 사례와 동일하게 main 자체의 기존 번역이라 이번 라운드에서
    고치지 않음 — 리더가 별도 라운드 필요 여부 판단.

---

## Zone팀 작업 지시

대상 파일(전부 `D:/segmentation model-zone-analysis-tab/` 하위, **`app/core/i18n.py`는
건드리지 않음**):
- `app/tabs/zone_analysis_tab.py`
- `app/widgets/zone_canvas.py`
- `app/widgets/zone_recipe_dialog.py`
- `app/widgets/zone_batch_result_dialog.py`
- `app/widgets/zone_step_indicator.py`

각 파일에 `from app.core.i18n import t`를 추가하고(없으면), 아래 표의 "원문" 문자열을
찾아 정확히 그 "교체 키"로 바꾼다. "플레이스홀더" 열에 적힌 변수명은 반드시 그
이름으로 `.format()`(또는 f-string + `t().format()`)에 넘긴다. "비고"에 "기존 키
재사용"이라 적힌 항목은 Zone 전용 신규 키가 아니라 i18n.py에 이미 있던 공용 키다.

### `app/tabs/zone_analysis_tab.py`

| 원문(한국어) | 교체 키 | 플레이스홀더 | 비고 |
|---|---|---|---|
| `"체크포인트 열기 (.pt)…"` | `zone.btn_ckpt_open` | — | |
| `"선택된 체크포인트 없음"` | `zone.ckpt_none` | — | |
| `"자동 선택됨"` | `zone.ckpt_auto_badge` | — | |
| `"타겟(녹) 클래스:"` | `zone.target_class_label` | — | |
| `"클래스 이름 (예: 녹)"` (placeholder) | `zone.target_name_placeholder` | — | |
| `"추론 방식: <b style='color:#cbd5e1'>sliding window</b> (고정)"` | `zone.infer_mode_fixed` | — | HTML 태그 그대로 유지 |
| `"▶  추론 실행"` (초기 버튼 텍스트) | `zone.run` | — | |
| `"추론 중…"` (클릭 후 버튼 텍스트) | `zone.running` | — | |
| `"▶  전체 추론 실행"` (완료 후 버튼 텍스트) | `zone.run_all` | — | |
| `"AI 신뢰도:"` | `zone.ai_confidence_label` | — | |
| `"blob(연결 영역)의 평균 신뢰도가 이 값 미만이면 배경으로 제거"` | `zone.confidence_tip` | — | |
| `"픽셀 threshold:"` | `zone.pixel_threshold_label` | — | |
| `"blob 면적(픽셀 수)이 이 값 미만이면 배경으로 제거"` | `zone.pixel_threshold_tip` | — | |
| `"민감도:"` | `zone.sensitivity_label` | — | |
| `"원 자동 검출 민감도(아래 '자동 검출' 버튼의 파라미터)"` | `zone.sensitivity_tip` | — | |
| `"자동 검출"` (버튼) | `zone.btn_detect` | — | |
| `"추론을 먼저 실행하면 검출된 원이 캔버스에 표시됩니다"` | `zone.detect_tip` | — | |
| `"원 편집"` (act_circle 툴팁) | `zone.tool_circle_tip` | — | |
| `"브러시로 타겟 영역 그리기"` | `zone.tool_brush_tip` | — | |
| `"브러시로 타겟 영역 지우기"` | `zone.tool_eraser_tip` | — | |
| `"클릭한 연결 블랍 삭제"` | `zone.tool_delete_region_tip` | — | |
| `"화면 이동"` (act_pan 툴팁) | `zone.tool_pan_tip` | — | |
| `"그리기/지우기 브러시 지름(원본 이미지 픽셀 단위)"` | `zone.brush_size_tip` | — | |
| `"브러시 크기:"` (QLabel) | `tool.brush_size` | — | **기존 키 재사용** |
| `"원/그리기/지우기/블랍 삭제를 시간순으로 되돌립니다 (Ctrl+Z)"` | `zone.undo_tip` | — | |
| `"추론을 먼저 실행하세요"` | `zone.run_inference_first` | — | |
| `"모델 아키텍처 코드 (이 체크포인트는 프리셋이 아님)"` | `zone.code_box_title` | — | |
| `"검증 (Validate)"` | `zone.btn_validate` | — | |
| `"로드 (Load Model)"` | `zone.btn_load_code` | — | |
| `"② 이미지"` (고정 헤더) | `zone.images_header` | — | |
| `f"② 이미지 ({self._img_list.count()})"` | `zone.images_header_count` | `n` | 2곳(line ~749, ~771) |
| `"선택된 이미지 없음"` | `zone.no_image_selected` | — | |
| `"Zone 결정 방법"` (QGroupBox) | `zone.batch_mode_group` | — | |
| `"일괄 적용"` (콤보 아이템) | `zone.mode_apply_all` | — | |
| `"일괄 적용 후 수정"` | `zone.mode_apply_all_edit` | — | |
| `"장별 적용(이미지별 개별)"` | `zone.mode_per_image` | — | |
| 콤보 `setToolTip(...)` 3줄 | `zone.mode_combo_tip` | — | |
| `"원(Zone) 설정..."` | `zone.btn_recipe` | — | |
| 레시피 버튼 `setToolTip(...)` 2줄 | `zone.recipe_tip` | — | |
| `f"▶ 선택 이미지 일괄 처리 ({n}장)"` | `zone.btn_batch` | `n` | 초기화(line~567, n=0)와 갱신(line~1568) 둘 다 |
| 배치 버튼 `setToolTip(...)` 3줄 | `zone.btn_batch_tip` | — | |
| `"필요 조건: 추론 실행 · 원 1개 이상 · 이미지 2장 이상"` | `zone.batch_condition_label` | — | |
| `"휠: 화면 줌 · Alt+휠: 선택한 원 지름 조절"` | `zone.wheel_hint` | — | |
| `"정렬(중심 맞추기)"` | `zone.btn_align` | — | |
| `"모든 원의 중심을 평균 중심으로 맞춥니다(반지름은 그대로)."` | `zone.align_tip` | — | |
| `"검출된 원 (반지름 오름차순)"` | `zone.circle_list_label` | — | |
| `"존별 타겟 클래스 비율 (%)"` | `zone.zone_list_label` | — | |
| `"클릭하면 캔버스에서 해당 존이 하이라이트됩니다"` | `zone.zone_list_tip` | — | |
| `"현재 이미지 결과 보기"` | `zone.btn_export_single` | — | |
| `"현재 화면에 표시된 존 목록(이미지 1장)을 표로 보고 Excel/클립보드로 내보냅니다"` | `zone.export_single_tip` | — | |
| `"전체 결과 보기"` | `zone.btn_view_all` | — | |
| `"이번 세션에서..." ` 2줄 | `zone.view_all_tip` | — | |
| `"이미지 선택"` (QFileDialog 제목) | `zone.select_image_title` | — | |
| `f"{len(paths)}개 파일 선택됨"` | `zone.files_selected_count` | `n` | |
| `"폴더 선택"` (QFileDialog.getExistingDirectory 제목) | `browser.add_folder_dialog_title` | — | **기존 키 재사용** |
| `"이미지 없음"` (폴더에 지원 이미지 없음, 제목) | `browser.no_images_title` | — | **기존 키 재사용** |
| `"선택한 폴더(하위 폴더 포함)에 지원되는 이미지가 없습니다."` | `zone.no_images_recursive_msg` | — | |
| `"체크포인트 선택"` (QFileDialog 제목) | `zone.select_checkpoint_title` | — | |
| `"저장 실패"` (QMessageBox 제목) | `zone.save_failed_title` | — | |
| `f"{path.parent} 폴더에 편집 내용을..."` | `zone.save_failed_msg` | `folder` | `{self._image_path.parent}` → `folder` |
| `f"{label}  (자동 준비됨)"` | `zone.ckpt_auto_ready` | `label` | |
| `f"{label} 프리셋 로드 실패 — 아래에..."` | `zone.preset_load_failed` | `label` | |
| `"사용자 정의 모델"` (reason 변수 값) | `zone.reason_custom_model` | — | |
| `"모델 정보 없는 체크포인트"` (reason 변수 값) | `zone.reason_no_model_info` | — | |
| `f"{reason} — 이 체크포인트를 학습한..."` | `zone.paste_code_hint` | `reason` | |
| `"[WARN] 코드가 비어 있습니다."` | `zone.code_empty` | — | |
| `f"[OK] 검증 통과 — 클래스: {result.model_class_name}"` | `zone.validate_ok` | `name` | |
| `f"[ERR] 검증 실패 — {n}개 오류"` | `zone.validate_failed` | `n` | |
| `f"[ERR] 로드 실패: {result.error}"` | `zone.load_failed` | `error` | |
| `f"[OK] 로드 완료 — 클래스: ... 파라미터: ..."` | `zone.load_ok` | `name`, `params` | |
| `f"{result.class_name}  (커스텀 모델 로드됨)"` | `zone.custom_model_loaded` | `name` | |
| `"이미지 없음"` / `"이미지를 먼저 선택하세요."` (3곳: ~951,1458,1484) | `infer.no_image_title` / `zone.no_image_msg` | — | 제목은 **기존 키 재사용** |
| `"체크포인트 없음"` / `"체크포인트를 먼저 선택하세요."` | `infer.no_ckpt_title` / `zone.no_ckpt_msg` | — | 제목 **기존 키 재사용** |
| `"모델 없음"` / `"모델이 준비되지 않았습니다. ..."` | `infer.no_model_title` / `zone.no_model_msg` | — | 제목 **기존 키 재사용** |
| `"존 분석"` (`prompt_gpu_availability(self, "존 분석")` 인자) | `zone.feature_name` | — | 2곳(~964, ~1618) |
| `"영역 없음"` / `"영역(원)이 설정되지 않았습니다. ..."` | `zone.no_region_title` / `zone.no_region_msg` | — | |
| `f"예상 남은 시간: 약 {m}분 {s}초"` | `zone.eta_minutes` | `m`, `s` | 2곳 — 두 번째(~1682)는 원문이 `"\n" + ...` 이므로 `"\n" + t("zone.eta_minutes").format(...)` 로 작성 |
| `f"예상 남은 시간: 약 {s}초"` | `zone.eta_seconds` | `s` | 위와 동일 패턴, `\n` 처리 동일 |
| `f"완료 {done} / {total}"` | `zone.infer_done_format` | `done`, `total` | |
| `"배경 외 클래스가 검출되지 않았습니다."` | `zone.no_class_detected` | — | |
| `f"클래스 1개 검출됨 (id={ids[0]}) — 이름 수정 가능"` | `zone.class_detected_single` | `id` | |
| `f"클래스 {n}개 검출됨 — 타겟을 선택하세요"` | `zone.class_detected_multi` | `n` | |
| `"재필터링 오류"` | `zone.refilter_error_title` | — | |
| `"N/A(수동 편집)"` | `zone.manual_edit_score` | — | |
| `f"선택된 블랍 — 존: ... · 면적 ...px · AI 점수 ..."` | `zone.blob_info` | `zone`, `px`, `score` | |
| `"내보낼 결과 없음"` / `"먼저 원을 정의하고 추론을 실행하세요."` | `zone.no_export_title` / `zone.no_export_msg` | — | |
| `"준비 안 됨"` / `"먼저 추론을 실행하고 타겟 클래스를 확정하세요."` | `zone.not_ready_title` / `zone.not_ready_msg1` | — | |
| `"준비 안 됨"` / `"먼저 기준 이미지에서 추론을 실행하고..."` | `zone.not_ready_title` / `zone.not_ready_msg2` | — | 같은 제목 키, 다른 메시지 키 |
| `"결과 없음"` / `"이번 세션에서 추론을 실행한 이미지가 없습니다."` | `zone.no_results_title` / `zone.no_results_session_msg` | — | |
| `"결과 없음"` / `"처리된 결과가 없습니다."` | `zone.no_results_title` / `zone.no_results_msg` | — | 같은 제목 키, 다른 메시지 키 |
| `"일부 제외됨"` / `f"이번 세션에서 추론하지 않은 {n}장은..."` | `zone.partial_excluded_title` / `zone.partial_excluded_msg` | `n` | |
| `"자동 검출 오류"` (2곳: ~1468) | `zone.detect_error_title` | — | |
| `"검출 결과 없음"` / `"원을 찾지 못했습니다. ..."` | `zone.detect_no_result_title` / `zone.detect_no_result_msg` | — | |
| `"기존 원 발견"` / `"기존 원을 레시피로 교체하시겠습니까?"` | `zone.existing_circles_title` / `zone.existing_circles_msg` | — | |
| `f"{name}  r={r:.1f}px  중심=({cx:.0f}, {cy:.0f})"` | `zone.circle_label_named` | `name`, `r`, `cx`, `cy` | |
| `f"원 {i}  r={r:.1f}px  중심=({cx:.0f}, {cy:.0f})"` | `zone.circle_label_unnamed` | `i`, `r`, `cx`, `cy` | |
| `menu.addAction("삭제")` (원 목록 우클릭) | `ui.delete` | — | **기존 키 재사용** |
| `"기존 존 발견"` / `f"선택 이미지 중 {count}장에..."` | `zone.existing_zones_title` / `zone.existing_zones_msg` | `count` | |
| `"기존 존을 대체하고 전체 적용"` | `zone.btn_replace_all` | — | |
| `"존 없는 이미지만 적용"` | `zone.btn_apply_missing_only` | — | |
| `box.addButton("취소", ...)` | `common.cancel` | — | **기존 키 재사용** |
| `"원 없음"` / `"기준 이미지에 원을 1개 이상 정의하세요."` | `zone.no_circle_title` / `zone.no_circle_msg` | — | |
| `"존 분석 일괄 처리 중…"` (QProgressDialog 라벨) | `zone.batch_progress_label` | — | |
| `"일괄 처리 진행 중"` (setWindowTitle) | `zone.batch_progress_title` | — | |
| `set_item_status(path, "done", badge="오류")` | `zone.badge_error` | — | |
| `"원 없음"` (`_ZoneBatchPostWorker.progress.emit` 상세 문자열, 2곳) | `zone.batch_no_circles` | — | |
| `f"최대 {max_px:,}px"` | `zone.max_px_label` | `n` | |

### `app/widgets/zone_canvas.py`

| 원문 | 교체 키 | 플레이스홀더 |
|---|---|---|
| `"지름 변경..."` (우클릭 메뉴) | `zone_canvas.menu_resize` | — |
| `"이름 변경..."` (우클릭 메뉴) | `zone_canvas.menu_rename` | — |
| `"원 삭제"` (우클릭 메뉴) | `zone_canvas.menu_delete` | — |
| `"지름 변경"` (QInputDialog 제목) | `zone_canvas.resize_dialog_title` | — |
| `"지름(px):"` (QInputDialog 라벨) | `zone_canvas.resize_dialog_label` | — |
| `"이름 변경"` (QInputDialog 제목) | `zone_canvas.rename_dialog_title` | — |
| `"존 이름(비우면 자동 이름 사용):"` (QInputDialog 라벨) | `zone_canvas.rename_dialog_label` | — |

### `app/widgets/zone_recipe_dialog.py`

| 원문 | 교체 키 | 플레이스홀더 |
|---|---|---|
| `"영역(Zone) 설정 — 레시피"` (setWindowTitle) | `zone_recipe.window_title` | — |
| `"영역(Zone) 설정 — 레시피 불러오기/새로 만들기"` (title QLabel) | `zone_recipe.title_label` | — |
| `"원 개수: 0"` / `f"원 개수: {count}"` | `zone_recipe.circle_count` | `n` |
| `f"원 개수: {len(scaled)}    검출 소요시간: {elapsed_ms:.0f}ms"` | `zone_recipe.circle_count_with_time` | `n`, `ms` |
| `"민감도:"` | `zone_recipe.sensitivity_label` | — |
| `"자동 검출"` (버튼) | `zone_recipe.btn_detect` | — |
| `"정렬(중심 맞추기)"` (버튼) | `zone_recipe.btn_align` | — |
| `"실행 취소 (Ctrl+Z)"` (툴팁) | `zone_recipe.undo_tip` | — |
| `"레시피"` (QGroupBox) | `zone_recipe.group_title` | — |
| `"불러오기"` (버튼) | `zone_recipe.btn_load` | — |
| `"레시피 이름"` (placeholder) | `zone_recipe.name_placeholder` | — |
| `"저장"` (버튼) | `common.save` | — | **기존 키 재사용** |
| `"팝업을 열면 가장 최근 사용한 레시피가 자동으로 표시됩니다."` | `zone_recipe.caption_auto_recent` | — |
| `"취소"` (버튼) | `common.cancel` | — | **기존 키 재사용** |
| `"메인 탭에 적용"` (버튼) | `zone_recipe.btn_apply` | — |
| footer_caption 2문장 | `zone_recipe.footer_caption` | — |
| `"불러오기 실패"` / `"레시피 파일을 읽을 수 없습니다."` | `zone_recipe.load_failed_title` / `zone_recipe.load_failed_msg` | — |
| `"이름 없음"` / `"레시피 이름을 입력하세요."` | `zone_recipe.no_name_title` / `zone_recipe.no_name_msg` | — |
| `"원 없음"` / `"저장할 원이 없습니다."` | `zone_recipe.no_circle_title` / `zone_recipe.no_circle_msg` | — |
| `"저장 실패"` (QMessageBox.critical) | `zone_recipe.save_failed_title` | — |
| `"저장 완료"` / `f"'{name}' 레시피를 저장했습니다."` | `zone_recipe.save_done_title` / `zone_recipe.save_done_msg` | `name` |
| `"자동 검출 오류"` | `zone_recipe.detect_error_title` | — |

### `app/widgets/zone_batch_result_dialog.py`

| 원문 | 교체 키 | 플레이스홀더 |
|---|---|---|
| `"일괄 처리 결과"` (setWindowTitle) | `zone_batch.window_title` | — |
| `"Long (이미지 × 존)"` (탭 제목) | `zone_batch.tab_long` | — |
| `"Wide (피벗)"` (탭 제목) | `zone_batch.tab_wide` | — |
| `"Excel로 내보내기"` (버튼, QFileDialog 제목 둘 다) | `zone_batch.btn_export_excel` | — |
| `"클립보드로 복사"` | `zone_batch.btn_copy_clipboard` | — |
| `"닫기"` | `common.close` | — | **기존 키 재사용** |
| `"필터"` | `zone_batch.filter_label` | — |
| `"이미지명 검색..."` (placeholder) | `zone_batch.search_placeholder` | — |
| `"존:"` | `zone_batch.zone_label` | — |
| `"초기화"` (버튼) | `zone_batch.btn_reset` | — |
| `["이미지", "존", "타겟 비율(%)", "최대 blob 픽셀수"]` (Long 탭 헤더) | `zone_batch.col_image`/`col_zone`/`col_ratio`/`col_max_blob` | — |
| caption `"최대 blob 픽셀수"는 ...` | `zone_batch.long_caption` | — |
| `["이미지"] + zone_cols` (Wide 탭 헤더 "이미지"만 번역) | `zone_batch.col_image` | — | 같은 키 재사용 |
| note `"참고: 이미지마다..."` 2줄 | `zone_batch.wide_note` | — |
| `"내보내기 오류"` | `zone_batch.export_error_title` | — |
| `"내보내기 완료"` / `f"{n}개 행을 내보냈습니다."` | `zone_batch.export_done_title` / `zone_batch.export_done_msg` | `n` |
| `"이미지\t존\t타겟 비율(%)\t최대 blob 픽셀수"` (클립보드 헤더) | `zone_batch.clipboard_header` | — |

### `app/widgets/zone_step_indicator.py`

`_STEP_LABELS` 리스트 7개를 아래로 교체 (list comprehension 또는 그대로 나열):

| 원문 | 교체 키 |
|---|---|
| `"① 체크포인트"` | `zone_step.step1` |
| `"② 이미지"` | `zone_step.step2` |
| `"③ 영역 설정"` | `zone_step.step3` |
| `"④ 추론 실행"` | `zone_step.step4` |
| `"⑤ 진행상황"` | `zone_step.step5` |
| `"⑥ 결과 보정"` | `zone_step.step6` |
| `"⑦ 결과 분석"` | `zone_step.step7` |

---

## R팀 작업 지시

대상 파일(**`app/core/i18n.py`는 건드리지 않음**):
- `app/tabs/r_analysis_tab.py`
- `app/widgets/r_cell_panel.py`
- `app/widgets/r_settings_panel.py`
- `app/widgets/r_roi_canvas.py` — **조사 결과 하드코딩 UI 문자열이 0개**(전부 주석/
  docstring). 이 파일은 `t()` import도, 수정도 필요 없음 — 그대로 둔다.
- `app/widgets/r_batch_result_dialog.py`
- `app/widgets/r_step_indicator.py`

### `app/tabs/r_analysis_tab.py`

| 원문 | 교체 키 | 플레이스홀더 | 비고 |
|---|---|---|---|
| `"세션 파일:"` | `r.session_file_label` | — | |
| `"미지정 — 저장하려면 선택하세요"` | `r.session_unset` | — | |
| `"세션 열기/새로 만들기..."` (버튼) | `r.btn_session` | — | |
| `"검사 설정 요약"` (QLabel) | `r.settings_summary_title` | — | |
| `"검사 설정 열기/조정..."` (버튼) | `r.btn_settings` | — | |
| `"ROI 편집(사각형 생성/이동/리사이즈)"` | `r.tool_roi_tip` | — | |
| `"브러시로 영역 그리기"` | `r.tool_brush_tip` | — | |
| `"브러시로 영역 지우기"` | `r.tool_eraser_tip` | — | |
| `"화면 이동"` (act_pan 툴팁) | `r.tool_pan_tip` | — | |
| `"실행 취소 (Ctrl+Z)"` | `r.undo_tip` | — | |
| `"브러시:"` | `r.brush_label` | — | |
| `"현재 이미지 검출"` (버튼) | `r.btn_detect_current` | — | |
| `"선택 셀 전체 일괄 검출"` (버튼) | `r.btn_detect_cell` | — | |
| `"▶ 전체 셀 분석"` (버튼) | `r.btn_detect_all` | — | |
| `"전체 셀 요약"` (QLabel) | `r.overall_summary_title` | — | |
| `f"합격 {passed}  ·  불합격 {failed}  ·  미검사 {untested}  (전체 {len(self._cells)}셀)"` | `r.overall_summary_format` | `passed`,`failed`,`untested`,`total` | |
| `"선택된 셀 없음"` (2곳: `_lbl_cell_title` 초기값 + 리셋) | `r.no_cell_selected` | — | |
| `"이미지별 면적(참고) — 개별 판정 없음"` | `r.ref_area_note` | — | |
| `["이미지", "면적"]` (테이블 헤더) | `r.col_image` / `r.col_area` | — | |
| `"전체 결과 보기 (Excel)"` (버튼) | `r.btn_view_all_excel` | — | |
| `"세션 파일 열기/새로 만들기"` (QFileDialog 제목) | `r.open_session_dialog_title` | — | |
| `f"Threshold: ...\n분모: ...\n스펙: ...\n{roi_desc}"` | `r.settings_summary_format` | `threshold`,`denom`,`lower`,`upper`,`roi_desc` | |
| `"전역 ROI 지정됨"` (roi_desc 삼항 값) | `r.roi_global_set` | — | |
| `"ROI 미지정"` (roi_desc 삼항 값) | `r.roi_unset` | — | |
| `f" (개별 보정 {override_n}장)"` | `r.roi_override_suffix` | `n` | |
| `"ROI 없음"` / `"먼저 캔버스에서 ROI를 지정하세요."` (2곳) | `r.no_roi_title` / `r.no_roi_msg` | — | |
| `"이미지 없음"` (제목, 2곳: ~701, ~742, ~766) | `infer.no_image_title` | — | **기존 키 재사용** |
| `"먼저 이미지를 선택하세요."` (2곳: ~701, ~742) | `r.no_image_msg` | — | |
| `"셀 없음"` / `"먼저 좌측에서 셀을 선택하세요."` | `r.no_cell_title` / `r.no_cell_msg` | — | |
| `"검출 중..."` (QProgressDialog 라벨) | `r.detecting_progress_label` | — | |
| `"이미지 없음"` / `"검출할 이미지가 없습니다."` (~766) | `infer.no_image_title`(재사용) / `r.no_images_to_detect_msg` | — | |
| `"ROI 없음"` / `"ROI가 지정된 이미지가 없습니다."` (~774) | `r.no_roi_title`(재사용) / `r.no_roi_images_msg` | — | |
| `f"미검사  (R={ratio_txt})"` | `r.untested_badge` | `ratio` | `"PASS (R=...)"`/`"FAIL (R=...)"`는 한국어가 아니므로 번역 불필요 |
| `f"현재 선택된 셀 — {cell_id}"` | `r.cell_title_selected` | `cell_id` | |

### `app/widgets/r_cell_panel.py`

| 원문 | 교체 키 | 플레이스홀더 |
|---|---|---|
| `_IMAGE_FILTER = "이미지 (*.jpg *.jpeg *.png *.bmp *.tiff *.tif)"` | `r_cell.image_filter` | — |
| `"셀 목록"` | `r_cell.list_title` | — |
| `"폴더로 셀 가져오기"` (버튼) | `r_cell.btn_import_folder` | — |
| `"바로 아래 하위폴더명이 셀 ID가 됩니다"` (툴팁) | `r_cell.import_folder_tip` | — |
| `"파일로 셀에 추가"` (버튼) | `r_cell.btn_add_files` | — |
| `"선택한 셀의 이미지 (Delete로 제거)"` | `r_cell.image_list_title` | — |
| `"이 셀에 이미지 추가"` (버튼) | `r_cell.btn_add_to_cell` | — |
| `"셀 폴더 가져오기"` (QFileDialog.getExistingDirectory 제목) | `r_cell.import_folder_dialog_title` | — |
| `"이미지 파일 선택"` (QFileDialog.getOpenFileNames 제목, 2곳) | `r_cell.select_image_files_title` | — |
| `"셀 ID"` (QInputDialog.getItem 제목) | `r_cell.cell_id_dialog_title` | — |
| `"셀 ID(기존 선택 또는 새로 입력):"` (QInputDialog.getItem 라벨) | `r_cell.cell_id_dialog_label` | — |

### `app/widgets/r_settings_panel.py`

| 원문 | 교체 키 | 플레이스홀더 |
|---|---|---|
| `"검사 설정"` (setWindowTitle) | `r_settings.window_title` | — |
| `"ROI 전역 지정"` (버튼) | `r_settings.btn_roi_global` | — |
| `"모든 셀에 공통으로 적용할 검사 영역을 지정합니다"` (툴팁) | `r_settings.roi_global_tip` | — |
| `"이 이미지만 보정"` (버튼) | `r_settings.btn_roi_override` | — |
| `"현재 이미지에만 적용되는 ROI로 전역 ROI를 덮어씁니다"` (툴팁) | `r_settings.roi_override_tip` | — |
| `"Threshold:"` (form row label) | 번역 불필요(영문) | — | 그대로 둠 |
| `"분모:"` (form row label) | `r_settings.row_denominator` | — |
| `"스펙 하한:"` (form row label) | `r_settings.row_spec_lower` | — |
| `"스펙 상한:"` (form row label) | `r_settings.row_spec_upper` | — |
| `"닫기"` (버튼) | `common.close` | — | **기존 키 재사용** |

`QFormLayout.addRow("분모:", widget)` 처럼 문자열 리터럴이 `addRow()` 첫 인자로
바로 들어가는 형태이니, `form.addRow(t("r_settings.row_denominator"), self._denominator_spin)`
식으로 교체.

### `app/widgets/r_batch_result_dialog.py`

| 원문 | 교체 키 | 플레이스홀더 |
|---|---|---|
| `"셀 일괄 분석 결과"` (setWindowTitle) | `r_batch.window_title` | — |
| `"셀"` (탭 제목) | `r_batch.tab_cell` | — |
| `"이미지별(참고)"` (탭 제목) | `r_batch.tab_image_ref` | — |
| `"Excel로 내보내기"` (버튼, QFileDialog 제목 둘 다) | `r_batch.btn_export_excel` | — |
| `"닫기"` (버튼) | `common.close` | — | **기존 키 재사용** |
| `["셀", "이미지 수", "면적 합계", "ratio", "판정"]` (셀 탭 헤더) | `r_batch.col_cell`/`col_image_count`/`col_sum_area`/(ratio 영문 그대로)/`col_verdict` | — |
| `["셀", "이미지", "면적(참고)"]` (이미지별 탭 헤더) | `r_batch.col_cell`(재사용)/`r_batch.col_image`/`r_batch.col_area_ref` | — |
| caption `"이미지별 면적은 셀 판정을 구성하는..."` | `r_batch.image_tab_caption` | — |
| `"내보내기 오류"` | `r_batch.export_error_title` | — |
| `"내보내기 완료"` / `f"{len(self._cells)}개 셀을 내보냈습니다."` | `r_batch.export_done_title` / `r_batch.export_done_msg` | `n` |

### `app/widgets/r_step_indicator.py`

`_STEP_LABELS` 리스트 5개 교체:

| 원문 | 교체 키 |
|---|---|
| `"① 이미지/셀 업로드"` | `r_step.step1` |
| `"② 검사 설정"` | `r_step.step2` |
| `"③ Contour 자동 검출"` | `r_step.step3` |
| `"④ 마스크 보정"` | `r_step.step4` |
| `"⑤ 셀별 결과 확인"` | `r_step.step5` |

---

## 공통 주의사항 (두 팀 모두)

1. `_STEP_LABELS`/`_IMAGE_FILTER` 같은 모듈 레벨 상수는 import 시점에 1회 평가되므로
   `t()` 호출로 바꾸려면 **함수 안으로 옮기거나 `__init__`/빌드 시점에 평가**해야 한다
   (지금처럼 모듈 최상단 리스트 리터럴로 두면 언어 전환이 재시작 후에나 반영되는 건
   기존 다른 탭도 동일한 제약이라 문제 아님 — `init_language()`가 앱 시작 시 1회
   호출되므로 모듈 import 시점에 이미 올바른 언어가 로드돼 있다. 다만 상수 자체를
   `t()` 호출 결과로 채우는 형태로 바꿔야 한다는 점만 유의).
2. 플레이스홀더가 있는 키는 `t("키").format(x=..., y=...)` 패턴을 쓴다 — 기존
   `project_export.done` 등 main 코드의 관례와 동일.
3. `zone.eta_minutes`/`zone.eta_seconds`는 두 번째 호출부(라운드 배치 ETA,
   `_on_batch_progress` 근처)에서 원문이 `"\n" + f"예상..."` 형태이므로 `t()` 결과
   앞에 `"\n"`을 붙이는 건 호출부 책임이다(키 값 자체에는 `\n`을 넣지 않았음).
4. 검증 에이전트가 용어 일관성을 재검토할 때는 이 문서의 "용어집" 표를 기준으로
   삼는다.

---

## 다음 단계

1. Zone팀 구현 에이전트: `app/tabs/zone_analysis_tab.py`,
   `app/widgets/zone_canvas.py`, `app/widgets/zone_recipe_dialog.py`,
   `app/widgets/zone_batch_result_dialog.py`, `app/widgets/zone_step_indicator.py`
   하드코딩 문자열을 위 매핑표대로 `t()` 호출로 교체.
2. R팀 구현 에이전트: `app/tabs/r_analysis_tab.py`, `app/widgets/r_cell_panel.py`,
   `app/widgets/r_settings_panel.py`, `app/widgets/r_batch_result_dialog.py`,
   `app/widgets/r_step_indicator.py` 동일 작업. `r_roi_canvas.py`는 수정 불필요.
3. 두 팀 다 `app/core/i18n.py`는 건드리지 않는다(이미 완성됨).
4. 구현 완료 후 검증 에이전트가 `python main.py`로 ko/en 전환해 Zone/R 탭 전체
   화면(툴팁 포함)에 한국어 잔존·KeyError 없는지, 그리고 이 문서의 용어집 기준
   일관성(예: 모든 "Pan" 툴팁이 "Pan view"로 통일됐는지)을 확인한다.
