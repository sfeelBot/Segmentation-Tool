# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir 빌드 spec — Segmentation Model UI.

빌드: py -3 -m PyInstaller build.spec  (또는 build.bat 사용)
산출물: dist/SegmentationModelUI/  (실행파일 + _internal/ 라이브러리)

onedir을 쓰는 이유: onefile은 매 실행마다 임시 폴더로 압축을 풀어 기동이
느리고, torch(CUDA 포함) 번들은 용량이 커서 그 비용이 특히 크다. 실행 속도를
우선하고 설치 폴더에 파일이 여러 개 있어도 무방하다는 결정에 따른 것.
"""

# ── hidden imports ──────────────────────────────────────────────────────────
# torch/torchvision/cv2는 pyinstaller-hooks-contrib이 자체 hook을 제공하고,
# PyQt6/matplotlib/PIL은 PyInstaller 내장 hook이 있어 정적 import만으로도
# 자동 추적되지만, main.py의 _preload_libs()가 importlib.import_module()로
# 동적 로드하는 항목(PyInstaller 정적 분석이 못 잡음)과 app/core/*, model_presets
# 의 지연 import 대상을 명시적으로 챙겨 안전망을 둔다.
hiddenimports = [
    # main.py _preload_libs() — importlib.import_module() 동적 로드 (정적 분석 불가)
    "numpy",
    "cv2",
    "PIL",
    "PIL.Image",
    "torch",
    "matplotlib",
    # app/core/dataset.py, inference_engine.py, auto_labeler.py 지연 import
    "torchvision",
    "torchvision.transforms.functional",
    # app/model_presets/deeplab_resnet.py, deeplab_mobilenet.py, lraspp_mobilenet.py 지연 import
    "torchvision.models.segmentation",
    # app/core/augmentations.py 지연 import (build 환경에 미설치 시 경고만 발생, 빌드는 계속됨)
    "albumentations",
    # app/widgets/loss_chart.py — FigureCanvasQTAgg 직접 사용 + main.py가 Agg로 use() 호출
    "matplotlib.backends.backend_agg",
    "matplotlib.backends.backend_qtagg",
    # PyQt6 — 전 탭·위젯에서 사용, QtSvg는 app/widgets/icons.py 아이콘 렌더링용
    "PyQt6.QtCore",
    "PyQt6.QtGui",
    "PyQt6.QtWidgets",
    "PyQt6.QtSvg",
]
# app/ 하위 모든 모듈은 main.py → app.main_window → 각 탭/위젯으로 정적 import
# 체인이 이어져 PyInstaller가 자동 추적한다 (app.* 를 문자열로 동적 import하는
# 곳이 없음을 확인함) — collect_submodules 등 추가 스캔은 불필요.

# ── data files ───────────────────────────────────────────────────────────────
datas = [
    # app/widgets/icons.py가 SVG를 런타임에 텍스트로 읽어 렌더링 (코드 추적 대상 아님)
    ("app/resources/icons", "app/resources/icons"),
    # main.py가 QIcon(str(...))로 경로째 읽음 — 코드 추적 대상 아니라 데이터로 포함
    ("app/resources/app_icon.ico", "app/resources"),
    # app/model_presets/__init__.py의 load_preset_code()가 .py를 텍스트로 읽음
    # (import가 아니라 read_text이므로 PyInstaller가 코드로 인식 못 함 — 데이터로도 포함 필요)
    ("app/model_presets", "app/model_presets"),
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SegmentationModelUI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,   # 창 모드 — 오류는 data/logs/*.log 파일 + GUI 팝업(logger.py)으로 추적 가능
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="app/resources/app_icon.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="SegmentationModelUI",
)
