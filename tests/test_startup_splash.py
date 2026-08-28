import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

import main


_APP = QApplication.instance() or QApplication([])


def test_startup_splash_shows_progress() -> None:
    splash = main._create_startup_splash()
    messages: list[str] = []
    splash.messageChanged.connect(messages.append)
    splash.show()

    main._show_startup_progress(_APP, splash, "AI 엔진 준비 중…")

    assert splash.isVisible()
    assert messages[-1] == "AI 엔진 준비 중…"
    splash.close()


def test_preload_reports_each_stage(monkeypatch) -> None:
    class MatplotlibStub:
        @staticmethod
        def use(_backend: str) -> None:
            pass

    monkeypatch.setattr(
        "importlib.import_module",
        lambda name: MatplotlibStub() if name == "matplotlib" else object(),
    )
    messages: list[str] = []

    main._preload_libs(messages.append)

    assert messages == [
        "numpy 준비 중…", "cv2 준비 중…", "PIL.Image 준비 중…",
        "AI 엔진 준비 중…", "그래프 엔진 준비 중…",
    ]
