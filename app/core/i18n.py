"""간단한 JSON 기반 다국어 지원 (한국어/영어)."""
import json
from pathlib import Path

SETTINGS_FILE = Path("data/settings.json")

TRANSLATIONS: dict[str, dict[str, str]] = {
    "ko": {
        # ── 탭 이름 ────────────────────────────────────────────────────────
        "tab.model":     "🧠  모델",
        "tab.labeling":  "🎨  라벨링",
        "tab.training":  "🎯  학습",
        "tab.inference": "🔍  추론",

        # ── 공통 ──────────────────────────────────────────────────────────
        "common.ok":     "확인",
        "common.cancel": "취소",
        "common.close":  "닫기",
        "common.save":   "저장",
        "common.apply":  "적용",
        "common.yes":    "예",
        "common.no":     "아니오",

        # ── 설정 ──────────────────────────────────────────────────────────
        "menu.settings":              "⚙️",
        "menu.settings.tip":           "설정 열기",
        "settings.title":              "⚙️  설정",
        "settings.language":           "🌐  언어",
        "settings.language.hint":      "언어 변경은 앱을 재시작해야 적용됩니다.",
        "settings.restart_title":      "재시작 필요",
        "settings.restart_msg":        "언어 설정이 저장되었습니다.\n앱을 재시작하면 새 언어가 적용됩니다.",
        "settings.logs":               "📝  로그",
        "settings.logs.hint":          "두 종류의 로그가 저장됩니다:\n• app.log — 모든 실행 기록 (DEBUG~ERROR)\n• errors.log — 경고·오류만 별도 기록 (빠른 디버깅용)",
        "settings.logs.all":           "전체 로그",
        "settings.logs.errors":        "⚠️ 경고·오류 전용",
        "settings.logs.open_folder":   "📂  폴더 열기",
        "settings.logs.copy_path":     "📋  경로 복사",
        "settings.logs.copied":        "경로가 클립보드에 복사되었습니다.",

        # ── 프로젝트 ──────────────────────────────────────────────────────
        "project.title":            "🗂  프로젝트",
        "project.welcome":          "프로젝트를 선택하거나 새로 만들어 시작하세요.",
        "project.new":              "🎯  새 프로젝트",
        "project.new.tip":          "새 프로젝트 폴더를 만들어 이미지·어노테이션·체크포인트를 격리합니다.",
        "project.open":             "📂  프로젝트 열기",
        "project.open.tip":         "기존 프로젝트 폴더를 선택해서 엽니다.",
        "project.recent":           "최근 프로젝트",
        "project.recent.empty":     "아직 사용한 프로젝트가 없습니다.",
        "project.new.prompt":       "새 프로젝트 이름을 입력하세요:",
        "project.new.error":        "프로젝트 생성 실패",
        "project.open.error":       "프로젝트 열기 실패",
        "project.current":          "현재 프로젝트",
        "project.switch":           "🔄  프로젝트 전환…",
        "project.switch.tip":       "앱을 다시 시작 없이 다른 프로젝트로 전환합니다.",
        "project.open_folder":      "📁  프로젝트 폴더 열기",
        "menu.project":             "🗂  프로젝트",
        "menu.project.tip":         "현재 프로젝트: {name}",

        # ── 단축키 ────────────────────────────────────────────────────────
        "settings.shortcuts":          "⌨️  단축키",
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
        "export.title":                "📤  라벨링 데이터 내보내기",
        "menu.export":                 "📤",
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
        "tool.polygon.tip":       "📐 폴리곤 [Q]\n클릭해 꼭짓점을 추가하고 더블클릭으로 닫습니다.",
        "tool.brush.tip":          "🖌 브러시 [W]\n드래그로 픽셀을 칠합니다.\n같은 클래스끼리 연결되면 자동 병합됩니다.",
        "tool.brush_fill.tip":    "🪣 윤곽 채우기 [E]\n윤곽선을 그리면 닫힌 내부가 자동으로 채워집니다.\n시작점·끝점은 자동 연결됩니다.",
        "tool.eraser.tip":         "🧹 지우개 [R]\n드래그한 픽셀 영역만 지웁니다.\n폴리곤도 지울 수 있습니다.",
        "tool.eraser_flood.tip":  "🧲 연결 지우개 [D]\n클릭한 픽셀과 연결된 같은 클래스 영역 전체를 삭제합니다.",
        "tool.select.tip":         "🔲 선택 [A]\n드래그로 어노테이션을 선택합니다.\n선택 후 클래스 패널을 클릭해 클래스를 변경할 수 있습니다.",
        "tool.pan.tip":            "✋ 이동 [S]\n드래그로 캔버스를 이동합니다.\n스페이스바를 누른 상태에서도 가능합니다.",

        # ── 라벨링 기타 ────────────────────────────────────────────────────
        "tool.brush_size":   "브러시 크기:",
        "tool.undo.tip":      "↶ 실행 취소 (Ctrl+Z)",
        "tool.clear.tip":     "🗑 현재 이미지의 모든 어노테이션 삭제",
        "tool.ok.tip":         "✓ 어노테이션이 없어도 검수 완료(OK) 로 표시\n다시 클릭하면 해제",
        "tool.auto.tip":       "✨ 학습된 모델로 미라벨 이미지 자동 어노테이션",
        "tool.fullscreen.tip": "🔳 좌·우 패널을 숨겨 이미지를 크게 보기 [Tab]",
    },

    "en": {
        # ── Tabs ──────────────────────────────────────────────────────────
        "tab.model":     "🧠  Model",
        "tab.labeling":  "🎨  Labeling",
        "tab.training":  "🎯  Training",
        "tab.inference": "🔍  Inference",

        # ── Common ────────────────────────────────────────────────────────
        "common.ok":     "OK",
        "common.cancel": "Cancel",
        "common.close":  "Close",
        "common.save":   "Save",
        "common.apply":  "Apply",
        "common.yes":    "Yes",
        "common.no":     "No",

        # ── Settings ──────────────────────────────────────────────────────
        "menu.settings":              "⚙️",
        "menu.settings.tip":           "Open settings",
        "settings.title":              "⚙️  Settings",
        "settings.language":           "🌐  Language",
        "settings.language.hint":      "Language changes require an app restart.",
        "settings.restart_title":      "Restart Required",
        "settings.restart_msg":        "Language setting saved.\nRestart the app to apply the new language.",
        "settings.logs":               "📝  Logs",
        "settings.logs.hint":          "Two log files are kept:\n• app.log — full activity log (DEBUG~ERROR)\n• errors.log — warnings & errors only (quick debugging)",
        "settings.logs.all":           "All logs",
        "settings.logs.errors":        "⚠️ Warnings & errors only",
        "settings.logs.open_folder":   "📂  Open folder",
        "settings.logs.copy_path":     "📋  Copy path",
        "settings.logs.copied":        "Path copied to clipboard.",

        # ── Project ──────────────────────────────────────────────────────
        "project.title":            "🗂  Project",
        "project.welcome":          "Select a project or create a new one to start.",
        "project.new":              "🎯  New project",
        "project.new.tip":          "Create a new project folder to isolate images / annotations / checkpoints.",
        "project.open":             "📂  Open project",
        "project.open.tip":         "Choose an existing project folder.",
        "project.recent":           "Recent projects",
        "project.recent.empty":     "No projects opened yet.",
        "project.new.prompt":       "Enter a name for the new project:",
        "project.new.error":        "Failed to create project",
        "project.open.error":       "Failed to open project",
        "project.current":          "Current project",
        "project.switch":           "🔄  Switch project…",
        "project.switch.tip":       "Switch to another project without restarting the app.",
        "project.open_folder":      "📁  Open project folder",
        "menu.project":             "🗂  Project",
        "menu.project.tip":         "Current project: {name}",

        # ── Shortcuts ────────────────────────────────────────────────────
        "settings.shortcuts":          "⌨️  Shortcuts",
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
        "export.title":                "📤  Export labeled data",
        "menu.export":                 "📤",
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
        "tool.polygon.tip":       "📐 Polygon [P]\nClick to add vertices, double-click to close.",
        "tool.brush.tip":          "🖌 Brush [B]\nDrag to paint pixels.\nConnected regions of the same class merge automatically.",
        "tool.brush_fill.tip":    "🪣 Fill Brush [F]\nDraw an outline and the enclosed area is filled automatically.\nStart/end points are auto-connected.",
        "tool.eraser.tip":         "🧹 Eraser [E]\nErases only the pixels you drag over.\nWorks on polygons too.",
        "tool.eraser_flood.tip":  "🧲 Connected Eraser\nClick a pixel — all 4-connected pixels of the same class are removed.",
        "tool.select.tip":         "🔲 Select [S]\nDrag to select annotations.\nClick a class in the class panel to change their class.",
        "tool.pan.tip":            "✋ Pan [H]\nDrag to pan the canvas.\nAlso works while holding the Space key.",

        # ── Labeling misc ─────────────────────────────────────────────────
        "tool.brush_size":   "Brush size:",
        "tool.undo.tip":      "↶ Undo (Ctrl+Z)",
        "tool.clear.tip":     "🗑 Delete all annotations on the current image",
        "tool.ok.tip":         "✓ Mark as reviewed (OK) even without annotations\nClick again to unmark",
        "tool.auto.tip":       "✨ Auto-annotate unlabeled images with the trained model",
        "tool.fullscreen.tip": "🔳 Hide side panels to maximize the canvas [Tab]",
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
