import sys
from pathlib import Path

# CUDA PyTorch must initialize before Qt in frozen Windows builds; otherwise
# c10.dll can fail with WinError 1114 even when every runtime DLL is bundled.
import torch  # noqa: F401

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QSplashScreen


# ── 무거운 라이브러리 선행 import ──────────────────────────────────────────────
# 일부 환경에서 DLL 로딩 순서·PATH 문제로 나중에 import 하면 에러가 날 수 있어서
# 메인 창 구성 전에 미리 로드한다. QApplication과 splash만 먼저 만들어 대기 상태를 표시한다.
#
# torchvision·albumentations는 여기서 빼고 실제 사용 시점(학습/추론/오토라벨 등,
# app/core/dataset.py·inference_engine.py·auto_labeler.py·augmentations.py·
# app/model_presets/*.py)에 지역 임포트로 지연 로드한다 — 콜드 기동 ~3.3초 중
# 대부분(albumentations 1.9s + torchvision 0.8s)을 절감. 단, torch는 항상 상시
# 사용되고 torchvision이 torch 확장이라 torch가 먼저 로드돼 있어야 안전하므로
# 계속 즉시 로드한다.

def _preload_libs(progress=None) -> None:
    """핵심 라이브러리를 앱 시작 시점에 미리 로드.
    importlib.import_module() 로 로컬 변수 없이 로드 → 린터 경고 없음."""
    import importlib

    for pkg in ("numpy", "cv2", "PIL.Image"):
        if progress:
            progress(f"{pkg} 준비 중…")
        try:
            importlib.import_module(pkg)
        except ImportError as e:
            _die(pkg, e)

    # PyTorch — DLL 로드 실패(OSError) 별도 처리. torchvision은 지연 로드하되,
    # torch는 그 전제(확장 모듈이 링크하는 베이스)이므로 항상 먼저 로드해 둔다.
    try:
        if progress:
            progress("AI 엔진 준비 중…")
        importlib.import_module("torch")
    except OSError as e:
        _die_dll(e)
    except ImportError as e:
        _die("torch", e)

    # matplotlib — Agg 백엔드 강제 (Qt 스레드 충돌 방지)
    try:
        if progress:
            progress("그래프 엔진 준비 중…")
        mpl = importlib.import_module("matplotlib")
        mpl.use("Agg")
    except ImportError as e:
        _die("matplotlib", e)


def _die(pkg: str, exc: Exception) -> None:
    print(f"[오류] '{pkg}' 패키지를 불러올 수 없습니다: {exc}", file=sys.stderr)
    print(f"  → pip install {pkg}", file=sys.stderr)
    sys.exit(1)


def _die_dll(exc: Exception) -> None:
    print(f"[오류] torch / torchvision DLL 로드 실패: {exc}", file=sys.stderr)
    print("  해결책:", file=sys.stderr)
    print("  1) Microsoft VC++ Redistributable 설치:", file=sys.stderr)
    print("     https://aka.ms/vs/17/release/vc_redist.x64.exe", file=sys.stderr)
    print("  2) PyTorch CUDA 빌드 재설치 (GPU 사용 시):", file=sys.stderr)
    print("     pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128", file=sys.stderr)
    print("  3) CPU 전용 빌드:", file=sys.stderr)
    print("     pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu", file=sys.stderr)
    sys.exit(1)


DATA_DIRS = ["data/images", "data/annotations", "data/checkpoints", "data/user_models"]


STYLESHEET = """
/* ── 전체 ─────────────────────────────────────────────────────────────── */
QWidget {
    background: #1a1d23;
    color: #e5e7eb;
    font-size: 13px;
}

/* ── 그룹 박스 ────────────────────────────────────────────────────────── */
QGroupBox {
    border: 1px solid #374151;
    border-radius: 8px;
    margin-top: 14px;
    padding-top: 10px;
    background: #1f2329;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 6px;
    color: #60a5fa;
    font-weight: bold;
}

/* ── 버튼 ─────────────────────────────────────────────────────────────── */
QPushButton {
    background: #2b313a;
    border: 1px solid #4b5563;
    border-radius: 5px;
    padding: 5px 12px;
    color: #e5e7eb;
}
QPushButton:hover {
    background: #374151;
    border-color: #60a5fa;
}
QPushButton:pressed {
    background: #1f2329;
}
QPushButton:disabled {
    color: #6b7280;
    background: #1f2329;
    border-color: #374151;
}

/* ── 입력 위젯 ────────────────────────────────────────────────────────── */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {
    background: #111418;
    border: 1px solid #374151;
    border-radius: 4px;
    padding: 4px 6px;
    color: #e5e7eb;
    selection-background-color: #1e3a5f;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus,
QPlainTextEdit:focus, QTextEdit:focus {
    border-color: #60a5fa;
}
QComboBox::drop-down {
    border: none;
    width: 18px;
}
QComboBox QAbstractItemView {
    background: #1f2329;
    border: 1px solid #4b5563;
    selection-background-color: #1e3a5f;
}

/* ── 체크박스 ─────────────────────────────────────────────────────────── */
QCheckBox {
    spacing: 6px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #4b5563;
    border-radius: 3px;
    background: #111418;
}
QCheckBox::indicator:checked {
    background: #10b981;
    border-color: #10b981;
}

/* ── 진행 바 ──────────────────────────────────────────────────────────── */
QProgressBar {
    border: 1px solid #374151;
    border-radius: 5px;
    background: #111418;
    text-align: center;
    height: 18px;
    color: #e5e7eb;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #10b981, stop:1 #34d399);
    border-radius: 4px;
}

/* ── 리스트 / 테이블 ──────────────────────────────────────────────────── */
QListWidget, QTableWidget, QTreeWidget {
    background: #111418;
    border: 1px solid #374151;
    border-radius: 6px;
    alternate-background-color: #15181d;
    gridline-color: #2a2f38;
}
QListWidget::item, QTableWidget::item {
    padding: 3px;
}
QListWidget::item:selected, QTableWidget::item:selected, QTreeWidget::item:selected {
    background: #1e3a5f;
    color: #ffffff;
}
QListWidget::item:hover:!selected, QTableWidget::item:hover:!selected {
    background: #1a1f27;
}
QHeaderView::section {
    background: #252a33;
    color: #cbd5e1;
    padding: 4px 8px;
    border: none;
    border-right: 1px solid #374151;
    border-bottom: 1px solid #374151;
    font-weight: bold;
}

/* ── 탭 ───────────────────────────────────────────────────────────────── */
QTabWidget::pane {
    border: 1px solid #374151;
    background: #1a1d23;
    border-top-left-radius: 0;
}
QTabBar::tab {
    padding: 8px 24px;
    background: #1f2329;
    border: 1px solid #374151;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    color: #9ca3af;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background: #1a1d23;
    color: #60a5fa;
    font-weight: bold;
    border-bottom: 2px solid #60a5fa;
}
QTabBar::tab:hover:!selected {
    background: #252a33;
    color: #e5e7eb;
}

/* ── 툴바 ─────────────────────────────────────────────────────────────── */
QToolBar {
    background: #1f2329;
    border: none;
    border-bottom: 1px solid #374151;
    spacing: 3px;
    padding: 4px;
}
QToolBar::separator {
    background: #374151;
    width: 1px;
    margin: 4px 4px;
}
QToolButton {
    padding: 5px 10px;
    border-radius: 4px;
    background: transparent;
    color: #cbd5e1;
}
QToolButton:hover {
    background: #374151;
    color: #ffffff;
}
QToolButton:checked {
    background: #1e3a5f;
    color: #60a5fa;
    font-weight: bold;
}
QToolButton:pressed {
    background: #111418;
}

/* ── 스크롤바 ─────────────────────────────────────────────────────────── */
QScrollBar:vertical {
    background: #1a1d23;
    width: 10px;
    border: none;
}
QScrollBar::handle:vertical {
    background: #4b5563;
    border-radius: 5px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background: #6b7280;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar:horizontal {
    background: #1a1d23;
    height: 10px;
    border: none;
}
QScrollBar::handle:horizontal {
    background: #4b5563;
    border-radius: 5px;
    min-width: 30px;
}
QScrollBar::handle:horizontal:hover {
    background: #6b7280;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}

/* ── 스플리터 / 상태바 ───────────────────────────────────────────────── */
QSplitter::handle {
    background: #374151;
}
QStatusBar {
    background: #1f2329;
    color: #9ca3af;
    border-top: 1px solid #374151;
}

/* ── 메뉴 / 다이얼로그 ───────────────────────────────────────────────── */
QMenu {
    background: #1f2329;
    border: 1px solid #4b5563;
    padding: 4px;
}
QMenu::item {
    padding: 5px 18px;
    border-radius: 3px;
}
QMenu::item:selected {
    background: #1e3a5f;
}
QDialog {
    background: #1a1d23;
}
QToolTip {
    background: #1f2329;
    color: #e5e7eb;
    border: 1px solid #60a5fa;
    border-radius: 4px;
    padding: 4px;
}
"""


def ensure_data_dirs() -> None:
    # PyInstaller onedir 번들에서는 __file__이 실제 파일이 없는 합성 경로
    # (_internal 내부)를 가리키므로 sys.executable 기준으로 잡는다.
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
    # 로그·설정만 글로벌, 프로젝트 단위 경로는 선택 후 생성됨
    for d in ("data/logs",):
        (base / d).mkdir(parents=True, exist_ok=True)


def _create_startup_splash() -> QSplashScreen:
    pixmap = QPixmap(460, 180)
    pixmap.fill(QColor("#1a1d23"))
    painter = QPainter(pixmap)
    painter.setPen(QColor("#60a5fa"))
    painter.setFont(QFont("Arial", 18, QFont.Weight.Bold))
    painter.drawText(28, 68, "Segmentation Model UI")
    painter.setPen(QColor("#9ca3af"))
    painter.setFont(QFont("Arial", 10))
    painter.drawText(29, 100, "AI 모델과 작업 환경을 준비하고 있습니다.")
    painter.end()
    splash = QSplashScreen(pixmap)
    splash.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
    return splash


def _show_startup_progress(app: QApplication, splash: QSplashScreen,
                           message: str) -> None:
    splash.showMessage(
        message,
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
        QColor("#e5e7eb"),
    )
    app.processEvents()


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Segmentation Model UI")
    splash = _create_startup_splash()
    splash.show()
    _show_startup_progress(app, splash, "기본 라이브러리 준비 중…")

    _preload_libs(lambda message: _show_startup_progress(app, splash, message))
    _show_startup_progress(app, splash, "사용자 환경 준비 중…")
    ensure_data_dirs()

    from app.core.logger import setup_logging, get_logger
    setup_logging()
    log = get_logger("main")
    log.info("===== Segmentation Model UI 시작 =====")

    try:
        from app.core.device_info import log_environment
        log_environment()
    except Exception as e:
        log.error(f"환경 정보 로깅 실패: {e!r}")

    from app.core.i18n import init_language
    init_language()

    app.setStyleSheet(STYLESHEET)

    from PyQt6.QtGui import QIcon
    # PyInstaller onedir 번들에서도 __file__ 체이닝이 datas 배치 위치와 일치해
    # 그대로 동작함 (app/widgets/icons.py의 _ICON_DIR과 동일한 근거 — 관련 검증은
    # docs/agents/implementation-log.md 참고).
    icon_path = Path(__file__).resolve().parent / "app" / "resources" / "app_icon.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    # ── 프로젝트 선택 루프 ───────────────────────────────────────────────────
    from app.widgets.project_start_dialog import ProjectStartDialog
    from PyQt6.QtWidgets import QDialog as _QDialog

    splash.close()
    app.processEvents()

    while True:
        start = ProjectStartDialog()
        if start.exec() != _QDialog.DialogCode.Accepted:
            log.info("프로젝트 선택 취소 — 종료합니다.")
            return

        splash.show()
        _show_startup_progress(app, splash, "프로젝트 화면 준비 중…")
        from app.main_window import MainWindow
        window = MainWindow()
        window.show()
        splash.finish(window)
        app.exec()

        if not getattr(window, "_switch_requested", False):
            break
        log.info("프로젝트 전환 요청 — 다이얼로그 재표시")


if __name__ == "__main__":
    main()
