"""간단한 JSON 기반 다국어 지원 (한국어/영어)."""
import json
from pathlib import Path

SETTINGS_FILE = Path("data/settings.json")

TRANSLATIONS: dict[str, dict[str, str]] = {
    "ko": {
        # ── 탭 이름 ────────────────────────────────────────────────────────
        "tab.model":     "모델",
        "tab.labeling":  "라벨링",
        "tab.training":  "학습",
        "tab.inference": "추론",

        # ── 공통 ──────────────────────────────────────────────────────────
        "common.ok":     "확인",
        "common.cancel": "취소",
        "common.close":  "닫기",
        "common.save":   "저장",
        "common.apply":  "적용",
        "common.yes":    "예",
        "common.no":     "아니오",

        # ── 설정 ──────────────────────────────────────────────────────────
        "menu.settings.tip":           "설정 열기",
        "settings.title":              "설정",
        "settings.language":           "언어",
        "settings.language.hint":      "언어 변경은 앱을 재시작해야 적용됩니다.",
        "settings.restart_title":      "재시작 필요",
        "settings.restart_msg":        "언어 설정이 저장되었습니다.\n앱을 재시작하면 새 언어가 적용됩니다.",
        "settings.logs":               "로그",
        "settings.logs.hint":          "두 종류의 로그가 저장됩니다:\n• app.log — 모든 실행 기록 (DEBUG~ERROR)\n• errors.log — 경고·오류만 별도 기록 (빠른 디버깅용)",
        "settings.logs.all":           "전체 로그",
        "settings.logs.errors":        "경고·오류 전용",
        "settings.logs.open_folder":   "폴더 열기",
        "settings.logs.copy_path":     "경로 복사",
        "settings.logs.copied":        "경로가 클립보드에 복사되었습니다.",

        # ── 프로젝트 ──────────────────────────────────────────────────────
        "project.title":            "프로젝트",
        "project.welcome":          "프로젝트를 선택하거나 새로 만들어 시작하세요.",
        "project.new":              "새 프로젝트",
        "project.new.tip":          "새 프로젝트 폴더를 만들어 이미지·어노테이션·체크포인트를 격리합니다.",
        "project.open":             "프로젝트 열기",
        "project.open.tip":         "기존 프로젝트 폴더를 선택해서 엽니다.",
        "project.recent":           "최근 프로젝트",
        "project.recent.empty":     "아직 사용한 프로젝트가 없습니다.",
        "project.new.prompt":       "새 프로젝트 이름을 입력하세요:",
        "project.new.error":        "프로젝트 생성 실패",
        "project.open.error":       "프로젝트 열기 실패",
        "project.current":          "현재 프로젝트",
        "project.switch":           "프로젝트 전환…",
        "project.switch.tip":       "앱을 다시 시작 없이 다른 프로젝트로 전환합니다.",
        "project.open_folder":      "프로젝트 폴더 열기",
        "menu.project":             "프로젝트",
        "menu.project.tip":         "현재 프로젝트: {name}",

        # ── 프로젝트 내보내기 ─────────────────────────────────────────────
        "project_export.action":          "내보내기…",
        "project_export.action.tip":      "프로젝트 전체를 zip 파일로 백업합니다 (프로젝트를 열지 않아도 됩니다).",
        "project_export.title":           "프로젝트 내보내기",
        "project_export.always_included": "항상 포함: images, annotations, classes.json, project.json",
        "project_export.include_ckpt":    "checkpoints/ 포함 (용량 큼)",
        "project_export.include_models":  "user_models/ 포함 (커스텀 모델 코드)",
        "project_export.models_hint":     "커스텀 모델 코드는 가져오기 후 모델 탭에서 다시 로드해야 합니다.",
        "project_export.choose_path":     "저장 위치 선택",
        "project_export.output":          "저장 경로",
        "project_export.run":             "▶  내보내기 시작",
        "project_export.choose_first":    "저장 위치를 먼저 선택하세요.",
        "project_export.running":         "압축 중…",
        "project_export.done":            "완료 — {n}개 파일을 내보냈습니다.\n{path}",
        "project_export.failed":          "내보내기 실패",
        "project_export.cancelled":       "취소됨",
        "project_export.cancel":          "취소",
        "project_export.project_missing": "프로젝트 폴더를 찾을 수 없습니다.",

        # ── 프로젝트 가져오기 ─────────────────────────────────────────────
        "project_import.action":          "가져오기…",
        "project_import.action.tip":      "zip 백업 파일에서 프로젝트를 복원합니다.",
        "project_import.choose_zip":      "가져올 zip 파일 선택",
        "project_import.title":           "프로젝트 가져오기",
        "project_import.dest_root":       "저장 위치",
        "project_import.hint":            "같은 이름의 프로젝트가 이미 있으면 기존 프로젝트는 건드리지 않고 '_imported' 이름으로 저장됩니다.",
        "project_import.run":             "▶  가져오기 시작",
        "project_import.cancel":          "취소",
        "project_import.cancelled":       "취소됨",
        "project_import.failed":          "가져오기 실패",
        "project_import.zip_missing":     "zip 파일을 찾을 수 없습니다.",
        "project_import.done":            "완료 — '{name}' 프로젝트로 저장되었습니다. ({n}개 파일)",
        "project_import.skipped_warning": "안전하지 않은 경로 {n}개 항목은 건너뛰었습니다. 가져온 프로젝트에 문제가 있을 수 있습니다.",
        "project_import.invalid_zip":     "가져온 zip 파일에 문제가 있어 프로젝트를 열 수 없습니다: {reason}\n가져온 프로젝트에 문제가 있을 수 있습니다.",

        # ── 단축키 ────────────────────────────────────────────────────────
        "settings.shortcuts":          "단축키",
        "settings.shortcuts.hint":     "라벨링 탭에서 사용할 수 있는 주요 단축키 모음.",
        "sc.polygon":          "폴리곤 도구",
        "sc.brush":            "브러시 도구",
        "sc.brush_fill":       "윤곽 채우기 도구",
        "sc.eraser":           "지우개 도구",
        "sc.eraser_flood":     "연결 지우개",
        "sc.select":           "선택 / 이동 도구",
        "sc.pan":              "이동(Pan) 도구",
        "sc.ok_toggle":        "OK 표시 / 해제 (어노테이션 없어도 검수 완료)",
        "sc.ann_visible":      "어노테이션 표시/숨김",
        "sc.copy_prev":        "이전 이미지의 어노테이션 복사",
        "sc.prev_image":       "이전 이미지로 이동",
        "sc.next_image":       "다음 이미지로 이동",
        "sc.fullscreen":       "좌·우 패널 숨김 / 복원",
        "sc.undo":             "실행 취소",
        "sc.delete":           "선택된 어노테이션 삭제",
        "sc.space_pan":        "Space 누른 상태 드래그 — 일시 이동",
        "sc.rmb_pan":          "우클릭 드래그 — 캔버스 이동",
        "sc.wheel_zoom":       "마우스 휠 — 줌인/아웃",
        "sc.brush_smaller":    "브러시 크기 감소",
        "sc.brush_bigger":     "브러시 크기 증가",
        "sc.polygon_close":    "폴리곤 닫기 (그리는 중)",
        "sc.cancel":           "취소 / 선택 해제",
        "sc.move_drag":        "선택한 어노테이션을 클릭 → 드래그로 이동",
        "sc.channel_orig":     "원본 채널 (컬러)",
        "sc.channel_r":        "R 채널 그레이스케일",
        "sc.channel_g":        "G 채널 그레이스케일",
        "sc.channel_b":        "B 채널 그레이스케일",

        # ── 내보내기 ─────────────────────────────────────────────────────
        "export.title":                "라벨링 데이터 내보내기",
        "menu.export.tip":              "라벨링된 이미지와 어노테이션을 내보내기",
        "export.labeled_only":         "어노테이션이 있는 이미지만 포함",
        "export.include_images":       "이미지 파일도 함께 복사",
        "export.relative_coords":      "상대 좌표(0~1 정규화)로 저장",
        "export.relative_coords.hint": "모든 좌표를 이미지 크기 대비 0~1 로 정규화해서 이미지 해상도에 독립적으로 저장합니다.",
        "export.format":               "포맷",
        "export.run":                  "▶  내보내기 시작",
        "export.choose_dir":           "내보낼 폴더 선택",
        "export.no_data":              "내보낼 라벨링 데이터가 없습니다.",
        "export.done":                 "완료 — {n}개 이미지를 내보냈습니다.",
        "export.failed":               "내보내기 실패",

        # ── 라벨링 툴바 (툴팁) ──────────────────────────────────────────────
        "tool.polygon.tip":       "폴리곤 [Q]\n클릭해 꼭짓점을 추가하고 더블클릭으로 닫습니다.",
        "tool.brush.tip":          "브러시 [W]\n드래그로 픽셀을 칠합니다.\n같은 클래스끼리 연결되면 자동 병합됩니다.",
        "tool.brush_fill.tip":    "윤곽 채우기 [E]\n윤곽선을 그리면 닫힌 내부가 자동으로 채워집니다.\n시작점·끝점은 자동 연결됩니다.",
        "tool.eraser.tip":         "지우개 [R]\n드래그한 픽셀 영역만 지웁니다.\n폴리곤도 지울 수 있습니다.",
        "tool.eraser_flood.tip":  "연결 지우개 [D]\n클릭한 픽셀과 연결된 같은 클래스 영역 전체를 삭제합니다.",
        "tool.select.tip":         "선택 [A]\n드래그로 어노테이션을 선택합니다.\n선택 후 클래스 패널을 클릭해 클래스를 변경할 수 있습니다.",
        "tool.pan.tip":            "이동 [S]\n드래그로 캔버스를 이동합니다.\n스페이스바를 누른 상태에서도 가능합니다.",

        # ── 라벨링 기타 ────────────────────────────────────────────────────
        "tool.brush_size":   "브러시 크기:",
        "tool.undo.tip":      "↶ 실행 취소 (Ctrl+Z)",
        "tool.clear.tip":     "현재 이미지의 모든 어노테이션 삭제",
        "tool.ok.tip":         "어노테이션이 없어도 검수 완료(OK) 로 표시\n다시 클릭하면 해제",
        "tool.auto.tip":       "학습된 모델로 미라벨 이미지 자동 어노테이션",
        "tool.fullscreen.tip": "좌·우 패널을 숨겨 이미지를 크게 보기 [T]",

        # ── 학습 탭 ───────────────────────────────────────────────────────
        "train.queue":            "학습 큐",
        "train.job_name":         "작업 이름:",
        "train.model_label":      "모델:",
        "train.add":              "큐에 추가",
        "train.run_all":          "▶  모두 실행",
        "train.stop":             "■  중지",
        "train.progress_window":  "진행 창",
        "train.remove":           "삭제",
        "train.clear_queue":      "전체 초기화",
        "train.total_eta":        "전체 예상 시간: —",
        "train.waiting":          "대기 중",
        "train.chart_title":      "손실 그래프",
        "train.metrics_title":    "Epoch 메트릭",
        "train.ckpt_title":       "저장된 체크포인트",
        "train.col_epoch":        "Epoch",
        "train.col_val":          "Val",
        "train.col_iou":          "IoU",
        "train.confirm_clear":    "큐가 실행 중입니다. 먼저 중지하세요.",
        "train.confirm_clear_title": "전체 초기화",
        "train.confirm_clear_msg": "큐의 모든 작업을 삭제하시겠습니까?",
        "train.empty_queue_msg":  "'큐에 추가' 로 먼저 학습 작업을 추가하세요.",
        "train.empty_queue_title": "큐 비어있음",
        "train.no_model_msg":     "Model 탭에서 모델을 먼저 로드하세요.",
        "train.no_model_title":   "모델 없음",

        # ── 설정 폼 ───────────────────────────────────────────────────────
        "cfg.data":               "데이터",
        "cfg.img_w":              "이미지 너비 (px)",
        "cfg.img_h":              "이미지 높이 (px)",
        "cfg.val_split":          "Val 비율",
        "cfg.workers":            "DataLoader Workers",
        "cfg.training":           "학습",
        "cfg.ckpt_every":         "체크포인트 주기 (epoch)",
        "cfg.optimizer_group":    "옵티마이저",
        "cfg.momentum_label":     "Momentum (SGD only)",
        "cfg.misc":               "손실 함수 / 장치",
        "cfg.sampling":           "이미지 샘플링",
        "cfg.sampling_mode":      "샘플링 모드",
        "cfg.patches_per_img":    "이미지당 패치 수",
        "cfg.defect_prob":        "결함 우선 확률",
        "cfg.auto_calc":          "자동 계산",

        # ── 추론 탭 ───────────────────────────────────────────────────────
        "infer.select_file":      "파일 선택…",
        "infer.select_folder":    "폴더 선택…",
        "infer.run":              "▶  추론 실행",
        "infer.running":          "추론 중…",
        "infer.ckpt_header":      "체크포인트 선택",
        "infer.refresh":          "↺ 새로고침",
        "infer.mode_label":       "추론 방식:",
        "infer.overlap_label":    "오버랩:",
        "infer.image_list":       "이미지 목록",
        "infer.legend":           "클래스 범례",
        "infer.no_model_msg":     "이 체크포인트는 Model 탭에서 직접 로드한 아키텍처로 학습됐습니다.\nModel 탭에서 같은 모델 코드를 로드한 뒤 다시 시도하세요.",
        "infer.no_image_msg":     "이미지를 선택하세요.",
        "infer.no_ckpt_msg":      "학습을 완료하거나 체크포인트를 선택하세요.",
        "infer.no_model_title":   "모델 없음",
        "infer.no_image_title":   "이미지 없음",
        "infer.no_ckpt_title":    "체크포인트 없음",
        "infer.col_file":         "파일명",
        "infer.col_model":        "모델",
        "infer.col_iou":          "IoU",

        # ── 공통 UI ───────────────────────────────────────────────────────
        "ui.close_confirm_title": "종료 확인",
        "ui.close_confirm_msg":   "앱을 종료하시겠습니까?",
        "ui.image_browser":       "이미지",
        "ui.add_file":            "파일",
        "ui.add_file.tip":        "이미지 파일 선택해서 추가",
        "ui.add_folder":          "폴더",
        "ui.add_folder.tip":      "폴더 내 이미지 전체 추가",
        "ui.delete":              "삭제",
        "ui.delete.tip":          "선택 이미지 삭제",

        # ── 라벨링 탭 ─────────────────────────────────────────────────────
        "labeling.ann_list":      "어노테이션 목록",
        "labeling.sel_hint":      "선택 후 클래스 패널에서\n클래스 변경 가능",
        "labeling.ch_orig":       "원본",
        "labeling.ch_r":          "R",
        "labeling.ch_g":          "G",
        "labeling.ch_b":          "B",
        "labeling.ch_orig.tip":   "원본 이미지",
        "labeling.ch_r.tip":      "Red 채널만 표시",
        "labeling.ch_g.tip":      "Green 채널만 표시",
        "labeling.ch_b.tip":      "Blue 채널만 표시",
        "labeling.clear_title":   "전체 삭제",
        "labeling.clear_msg":     "현재 이미지의 모든 어노테이션을 삭제하시겠습니까?",
    },

    "en": {
        # ── Tabs ──────────────────────────────────────────────────────────
        "tab.model":     "Model",
        "tab.labeling":  "Labeling",
        "tab.training":  "Training",
        "tab.inference": "Inference",

        # ── Common ────────────────────────────────────────────────────────
        "common.ok":     "OK",
        "common.cancel": "Cancel",
        "common.close":  "Close",
        "common.save":   "Save",
        "common.apply":  "Apply",
        "common.yes":    "Yes",
        "common.no":     "No",

        # ── Settings ──────────────────────────────────────────────────────
        "menu.settings.tip":           "Open settings",
        "settings.title":              "Settings",
        "settings.language":           "Language",
        "settings.language.hint":      "Language changes require an app restart.",
        "settings.restart_title":      "Restart Required",
        "settings.restart_msg":        "Language setting saved.\nRestart the app to apply the new language.",
        "settings.logs":               "Logs",
        "settings.logs.hint":          "Two log files are kept:\n• app.log — full activity log (DEBUG~ERROR)\n• errors.log — warnings & errors only (quick debugging)",
        "settings.logs.all":           "All logs",
        "settings.logs.errors":        "Warnings & errors only",
        "settings.logs.open_folder":   "Open folder",
        "settings.logs.copy_path":     "Copy path",
        "settings.logs.copied":        "Path copied to clipboard.",

        # ── Project ──────────────────────────────────────────────────────
        "project.title":            "Project",
        "project.welcome":          "Select a project or create a new one to start.",
        "project.new":              "New project",
        "project.new.tip":          "Create a new project folder to isolate images / annotations / checkpoints.",
        "project.open":             "Open project",
        "project.open.tip":         "Choose an existing project folder.",
        "project.recent":           "Recent projects",
        "project.recent.empty":     "No projects opened yet.",
        "project.new.prompt":       "Enter a name for the new project:",
        "project.new.error":        "Failed to create project",
        "project.open.error":       "Failed to open project",
        "project.current":          "Current project",
        "project.switch":           "Switch project…",
        "project.switch.tip":       "Switch to another project without restarting the app.",
        "project.open_folder":      "Open project folder",
        "menu.project":             "Project",
        "menu.project.tip":         "Current project: {name}",

        # ── Project export ───────────────────────────────────────────────
        "project_export.action":          "Export…",
        "project_export.action.tip":      "Back up the whole project as a zip file (no need to open it first).",
        "project_export.title":           "Export project",
        "project_export.always_included": "Always included: images, annotations, classes.json, project.json",
        "project_export.include_ckpt":    "Include checkpoints/ (large)",
        "project_export.include_models":  "Include user_models/ (custom model code)",
        "project_export.models_hint":     "Custom model code must be reloaded in the Model tab after importing.",
        "project_export.choose_path":     "Choose save location",
        "project_export.output":          "Output path",
        "project_export.run":             "▶  Start export",
        "project_export.choose_first":    "Please choose a save location first.",
        "project_export.running":         "Compressing…",
        "project_export.done":            "Done — exported {n} files.\n{path}",
        "project_export.failed":          "Export failed",
        "project_export.cancelled":       "Cancelled",
        "project_export.cancel":          "Cancel",
        "project_export.project_missing": "Project folder not found.",

        # ── Project import ───────────────────────────────────────────────
        "project_import.action":          "Import…",
        "project_import.action.tip":      "Restore a project from a zip backup file.",
        "project_import.choose_zip":      "Choose zip file to import",
        "project_import.title":           "Import project",
        "project_import.dest_root":       "Destination",
        "project_import.hint":            "If a project with the same name already exists, it is left untouched and the imported one is saved as '_imported'.",
        "project_import.run":             "▶  Start import",
        "project_import.cancel":          "Cancel",
        "project_import.cancelled":       "Cancelled",
        "project_import.failed":          "Import failed",
        "project_import.zip_missing":     "Zip file not found.",
        "project_import.done":            "Done — saved as project '{name}'. ({n} files)",
        "project_import.skipped_warning": "Skipped {n} unsafe path entries. The imported project may have issues.",
        "project_import.invalid_zip":     "The imported zip file has a problem and could not be opened: {reason}\nThe imported project may have issues.",

        # ── Shortcuts ────────────────────────────────────────────────────
        "settings.shortcuts":          "Shortcuts",
        "settings.shortcuts.hint":     "Keyboard shortcuts available in the Labeling tab.",
        "sc.polygon":          "Polygon tool",
        "sc.brush":            "Brush tool",
        "sc.brush_fill":       "Fill-brush tool",
        "sc.eraser":           "Eraser tool",
        "sc.select":           "Select / move tool",
        "sc.pan":              "Pan tool",
        "sc.fullscreen":       "Hide / show side panels",
        "sc.undo":             "Undo",
        "sc.copy_prev":        "Copy previous image's annotations",
        "sc.delete":           "Delete selected annotations",
        "sc.space_pan":        "Hold Space + drag — pan",
        "sc.rmb_pan":          "Right-drag — pan canvas",
        "sc.wheel_zoom":       "Mouse wheel — zoom in/out",
        "sc.brush_smaller":    "Decrease brush size",
        "sc.brush_bigger":     "Increase brush size",
        "sc.polygon_close":    "Close polygon (while drawing)",
        "sc.cancel":           "Cancel / deselect",
        "sc.move_drag":        "Click a selected annotation → drag to move",
        "sc.prev_image":       "Previous image",
        "sc.next_image":       "Next image",
        "sc.ann_visible":      "Show/hide annotations",
        "sc.channel_orig":     "Original (color)",
        "sc.channel_r":        "R channel grayscale",
        "sc.channel_g":        "G channel grayscale",
        "sc.channel_b":        "B channel grayscale",

        # ── Export ───────────────────────────────────────────────────────
        "export.title":                "Export labeled data",
        "menu.export.tip":              "Export labeled images and annotations",
        "export.labeled_only":         "Include only images with annotations",
        "export.include_images":       "Also copy image files",
        "export.relative_coords":      "Save as normalized coordinates (0~1)",
        "export.relative_coords.hint": "All coordinates are normalized by image size so the data is resolution-independent.",
        "export.format":               "Format",
        "export.run":                  "▶  Start export",
        "export.choose_dir":           "Select export folder",
        "export.no_data":              "No labeled data to export.",
        "export.done":                 "Done — exported {n} images.",
        "export.failed":               "Export failed",

        # ── Labeling toolbar tooltips ─────────────────────────────────────
        "tool.polygon.tip":       "Polygon [P]\nClick to add vertices, double-click to close.",
        "tool.brush.tip":          "Brush [B]\nDrag to paint pixels.\nConnected regions of the same class merge automatically.",
        "tool.brush_fill.tip":    "Fill Brush [F]\nDraw an outline and the enclosed area is filled automatically.\nStart/end points are auto-connected.",
        "tool.eraser.tip":         "Eraser [E]\nErases only the pixels you drag over.\nWorks on polygons too.",
        "tool.eraser_flood.tip":  "Connected Eraser\nClick a pixel — all 4-connected pixels of the same class are removed.",
        "tool.select.tip":         "Select [S]\nDrag to select annotations.\nClick a class in the class panel to change their class.",
        "tool.pan.tip":            "Pan [H]\nDrag to pan the canvas.\nAlso works while holding the Space key.",

        # ── Labeling misc ─────────────────────────────────────────────────
        "tool.brush_size":   "Brush size:",
        "tool.undo.tip":      "↶ Undo (Ctrl+Z)",
        "tool.clear.tip":     "Delete all annotations on the current image",
        "tool.ok.tip":         "Mark as reviewed (OK) even without annotations\nClick again to unmark",
        "tool.auto.tip":       "Auto-annotate unlabeled images with the trained model",
        "tool.fullscreen.tip": "Hide side panels to maximize the canvas [T]",

        # ── Training tab ──────────────────────────────────────────────────
        "train.queue":            "Training Queue",
        "train.job_name":         "Job name:",
        "train.model_label":      "Model:",
        "train.add":              "Add to Queue",
        "train.run_all":          "▶  Run All",
        "train.stop":             "■  Stop",
        "train.progress_window":  "Progress",
        "train.remove":           "Remove",
        "train.clear_queue":      "Clear All",
        "train.total_eta":        "Total ETA: —",
        "train.waiting":          "Idle",
        "train.chart_title":      "Loss Chart",
        "train.metrics_title":    "Epoch Metrics",
        "train.ckpt_title":       "Saved Checkpoints",
        "train.col_epoch":        "Ep",
        "train.col_val":          "Val",
        "train.col_iou":          "IoU",
        "train.confirm_clear":    "Queue is running. Stop it first.",
        "train.confirm_clear_title": "Clear Queue",
        "train.confirm_clear_msg": "Delete all jobs in the queue?",
        "train.empty_queue_msg":  "Use 'Add to Queue' to add training jobs.",
        "train.empty_queue_title": "Queue Empty",
        "train.no_model_msg":     "Please load a model in the Model tab first.",
        "train.no_model_title":   "No Model",

        # ── Config form ───────────────────────────────────────────────────
        "cfg.data":               "Data",
        "cfg.img_w":              "Image Width (px)",
        "cfg.img_h":              "Image Height (px)",
        "cfg.val_split":          "Val Split",
        "cfg.workers":            "DataLoader Workers",
        "cfg.training":           "Training",
        "cfg.ckpt_every":         "Checkpoint Interval (epoch)",
        "cfg.optimizer_group":    "Optimizer",
        "cfg.momentum_label":     "Momentum (SGD only)",
        "cfg.misc":               "Loss / Device",
        "cfg.sampling":           "Image Sampling",
        "cfg.sampling_mode":      "Sampling Mode",
        "cfg.patches_per_img":    "Patches per Image",
        "cfg.defect_prob":        "Defect Priority Prob",
        "cfg.auto_calc":          "Auto",

        # ── Inference tab ─────────────────────────────────────────────────
        "infer.select_file":      "Select File…",
        "infer.select_folder":    "Select Folder…",
        "infer.run":              "▶  Run Inference",
        "infer.running":          "Inferring…",
        "infer.ckpt_header":      "Select Checkpoint",
        "infer.refresh":          "↺ Refresh",
        "infer.mode_label":       "Mode:",
        "infer.overlap_label":    "Overlap:",
        "infer.image_list":       "Image List",
        "infer.legend":           "Class Legend",
        "infer.no_model_msg":     "This checkpoint was trained with a manually loaded model.\nLoad the same model code in the Model tab and try again.",
        "infer.no_image_msg":     "Please select an image.",
        "infer.no_ckpt_msg":      "Complete training or select a checkpoint.",
        "infer.no_model_title":   "No Model",
        "infer.no_image_title":   "No Image",
        "infer.no_ckpt_title":    "No Checkpoint",
        "infer.col_file":         "File",
        "infer.col_model":        "Model",
        "infer.col_iou":          "IoU",

        # ── Common UI ─────────────────────────────────────────────────────
        "ui.close_confirm_title": "Quit",
        "ui.close_confirm_msg":   "Are you sure you want to quit?",
        "ui.image_browser":       "Images",
        "ui.add_file":            "File",
        "ui.add_file.tip":        "Add image files",
        "ui.add_folder":          "Folder",
        "ui.add_folder.tip":      "Add all images in a folder",
        "ui.delete":              "Delete",
        "ui.delete.tip":          "Delete selected images",

        # ── Labeling tab ──────────────────────────────────────────────────
        "labeling.ann_list":      "Annotation List",
        "labeling.sel_hint":      "Select, then click a class\nin the class panel to change",
        "labeling.ch_orig":       "Orig",
        "labeling.ch_r":          "R",
        "labeling.ch_g":          "G",
        "labeling.ch_b":          "B",
        "labeling.ch_orig.tip":   "Original image",
        "labeling.ch_r.tip":      "Red channel only",
        "labeling.ch_g.tip":      "Green channel only",
        "labeling.ch_b.tip":      "Blue channel only",
        "labeling.clear_title":   "Clear All",
        "labeling.clear_msg":     "Delete all annotations on the current image?",

        # ── Missing shortcut keys (English) ──────────────────────────────
        "sc.eraser_flood":     "Connected eraser",
        "sc.ok_toggle":        "Toggle OK (reviewed with no annotations)",
    },
}

_current_lang = "ko"


def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_settings(data: dict) -> None:
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing = load_settings()
    existing.update(data)
    SETTINGS_FILE.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def init_language() -> None:
    """앱 시작 시 settings.json 에서 언어 로드."""
    s = load_settings()
    lang = s.get("language", "ko")
    set_language(lang)


def get_language() -> str:
    return _current_lang


def set_language(lang: str) -> None:
    global _current_lang
    if lang in TRANSLATIONS:
        _current_lang = lang


def t(key: str, default: str = "") -> str:
    """번역된 문자열을 돌려준다. 없으면 default 또는 key 자체 반환."""
    tr = TRANSLATIONS.get(_current_lang, {})
    return tr.get(key, default or key)
