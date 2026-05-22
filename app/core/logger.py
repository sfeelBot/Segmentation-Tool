"""앱 전역 로깅 — 파일 회전 로그 + Qt 시그널 기반 UI 브리지."""
import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler

from PyQt6.QtCore import QObject, pyqtSignal

LOG_DIR = Path("data/logs")
LOG_FILE = LOG_DIR / "app.log"
ERROR_LOG_FILE = LOG_DIR / "errors.log"
MAX_BYTES = 2 * 1024 * 1024   # 2MB × 5
BACKUP_COUNT = 5


class _LogBridge(QObject):
    """파이썬 logging 이벤트를 Qt 시그널로 전달 (스레드 안전)."""
    log_received = pyqtSignal(str, str, str)   # level, logger_name, formatted_msg


bridge = _LogBridge()


class _UIHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            bridge.log_received.emit(
                record.levelname,
                record.name,
                self.format(record),
            )
        except Exception:
            pass


def setup_logging() -> None:
    """앱 시작 시 한 번 호출."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # 기존 핸들러 제거 — 재호출 시 중복 방지
    for h in list(root.handlers):
        root.removeHandler(h)

    file_fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-7s] %(name)s:%(lineno)d — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    ui_fmt = logging.Formatter("%(message)s")

    # 파일 1: app.log — 전체 로그 (DEBUG 포함)
    fh = RotatingFileHandler(
        LOG_FILE, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(file_fmt)
    root.addHandler(fh)

    # 파일 2: errors.log — 경고/오류만 별도 기록 (디버깅용)
    err_fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-7s] %(name)s:%(lineno)d\n"
        "  FILE  : %(pathname)s\n"
        "  FUNC  : %(funcName)s\n"
        "  MSG   : %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    eh = RotatingFileHandler(
        ERROR_LOG_FILE, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    eh.setLevel(logging.WARNING)
    eh.setFormatter(err_fmt)
    root.addHandler(eh)

    # 콘솔 (INFO+)
    try:
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.INFO)
        ch.setFormatter(file_fmt)
        root.addHandler(ch)
    except Exception:
        pass

    # UI 브리지 (INFO+)
    uh = _UIHandler()
    uh.setLevel(logging.INFO)
    uh.setFormatter(ui_fmt)
    root.addHandler(uh)

    # 잡히지 않은 예외 로깅 + 팝업
    def _excepthook(exc_type, exc_value, exc_tb):
        logging.getLogger("uncaught").error(
            "잡히지 않은 예외",
            exc_info=(exc_type, exc_value, exc_tb),
        )
        # GUI 팝업 (QApplication 이 살아있을 때만)
        try:
            import traceback
            from PyQt6.QtWidgets import QApplication, QMessageBox
            app = QApplication.instance()
            if app is not None:
                msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
                # paintEvent 등 GUI 이벤트 중에 모달을 직접 열면 위험 → 큐에 예약
                from PyQt6.QtCore import QTimer
                def _show():
                    dlg = QMessageBox()
                    dlg.setWindowTitle("❌  예기치 않은 오류 — 앱이 종료될 수 있습니다")
                    dlg.setText(
                        f"<b>{exc_type.__name__}: {exc_value}</b><br><br>"
                        "자세한 내용은 아래 또는 <code>data/logs/errors.log</code> 를 확인하세요."
                    )
                    dlg.setDetailedText(msg)
                    dlg.setIcon(QMessageBox.Icon.Critical)
                    dlg.exec()
                QTimer.singleShot(0, _show)
        except Exception:
            pass
        sys.__excepthook__(exc_type, exc_value, exc_tb)
    sys.excepthook = _excepthook

    # PyTorch 경고도 INFO 레벨로 기록
    logging.captureWarnings(True)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_file_path() -> Path:
    return LOG_FILE


def error_log_file_path() -> Path:
    return ERROR_LOG_FILE
