import configparser
import importlib.util
import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "generate_version_info.py"
SPEC = importlib.util.spec_from_file_location("generate_version_info", SCRIPT)
generator = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(generator)


def test_build_script_uses_one_validated_python() -> None:
    script = (ROOT / "build.bat").read_text(encoding="ascii")
    assert "sys.version_info[:2] == (3, 12)" in script
    assert (
        "import PyQt6, PyInstaller, torch, torchvision, cv2, numpy, PIL, "
        "albumentations, openpyxl, matplotlib"
    ) in script
    assert '"%BUILD_PYTHON%" scripts\\generate_version_info.py' in script
    assert '"%BUILD_PYTHON%" -m PyInstaller build.spec' in script
    assert "py -3 -m" not in script
    assert "py -3.12 -c" in script
    assert 'findstr /i /v "WindowsApps"' in script
    assert 'set "BUILD_VENV=%ROOT%build\\venv"' in script
    assert '"%SYSTEM_PYTHON%" -m venv "%BUILD_VENV%"' in script
    assert (
        '"%BUILD_PYTHON%" -m pip install -r requirements.txt PyInstaller '
        "--extra-index-url https://download.pytorch.org/whl/cu128"
    ) in script
    assert 'rmdir /s /q "%BUILD_VENV%"' in script
    assert 'if not exist "%BUILD_VENV%\\Scripts\\python.exe"' in script
    assert 'if exist "%BUILD_VENV%" (' in script
    assert script.count("sys.version_info[:2] == (3, 12)") >= 4


def test_build_script_preserves_unrelated_build_artifacts() -> None:
    script = (ROOT / "build.bat").read_text(encoding="ascii")
    assert "if exist build rmdir /s /q build" not in script
    assert "build\\build" in script


def test_installer_build_uses_tested_cuda_torch_pair() -> None:
    script = (ROOT / "build.bat").read_text(encoding="ascii")
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "torch==2.7.1" in requirements
    assert "torchvision==0.22.1" in requirements
    assert "version('torch').startswith('2.7.1')" in script
    assert "version('torchvision').startswith('0.22.1')" in script


def test_requirements_txt_is_ascii_only() -> None:
    # GitHub #31: pip's auto_decode() falls back to the OS locale codepage
    # (e.g. cp949 on Korean Windows) when a requirements file has no BOM or
    # encoding declaration, so any non-ASCII byte crashes the build on
    # non-English-locale Windows.
    data = (ROOT / "requirements.txt").read_bytes()
    assert all(byte < 128 for byte in data)
    data.decode("cp949")


def test_build_spec_excludes_other_qt_bindings() -> None:
    spec = (ROOT / "build.spec").read_text(encoding="utf-8")
    for package in ("PyQt5", "PySide2", "PySide6", "IPython", "pytest", "sphinx"):
        assert f'"{package}"' in spec


def test_build_spec_limits_matplotlib_to_app_backends() -> None:
    spec = (ROOT / "build.spec").read_text(encoding="utf-8")
    assert 'hooksconfig={"matplotlib": {"backends": ["Agg", "QtAgg"]}}' in spec


def write_release(path: Path, **overrides: str) -> None:
    values = {
        "version": "1.8.0",
        "tag_prefix": "v",
        "product_name": "Segmentation Model UI",
        "product_slug": "SegmentationModelUI",
        "exe_name": "SegmentationModelUI",
        "publisher": "Segmentation Model UI",
        "app_id": "03C2678A-B979-4B99-A68B-842EA853D667",
    }
    values.update(overrides)
    parser = configparser.ConfigParser()
    parser["release"] = values
    with path.open("w", encoding="utf-8") as stream:
        parser.write(stream)


def test_repository_release_matches_changelog_and_renders_metadata():
    release = generator.load_release()
    generator.validate_changelog(release["version"], release["tag_prefix"])
    version_info = generator.render_version_info(release)
    inno = generator.render_inno_defines(release)
    version_tuple = ", ".join((*release["version"].split("."), "0"))
    assert f"filevers=({version_tuple})" in version_info
    assert f'{release["exe_name"]}.exe' in version_info
    assert f'#define MyAppVersion "{release["version"]}"' in inno
    assert f'#define MyAppId "{release["app_id"]}"' in inno


@pytest.mark.parametrize("version", ["v1.8.0", "1.8", "01.8.0", "1.8.0-beta"])
def test_rejects_invalid_version(tmp_path: Path, version: str):
    release_file = tmp_path / "release.ini"
    write_release(release_file, version=version)
    with pytest.raises(ValueError, match="SemVer"):
        generator.load_release(release_file)


def test_rejects_missing_required_key(tmp_path: Path):
    release_file = tmp_path / "release.ini"
    write_release(release_file, publisher="")
    with pytest.raises(ValueError, match="publisher"):
        generator.load_release(release_file)


def test_rejects_invalid_guid(tmp_path: Path):
    release_file = tmp_path / "release.ini"
    write_release(release_file, app_id="not-a-guid")
    with pytest.raises(ValueError, match="GUID"):
        generator.load_release(release_file)


@pytest.mark.parametrize("key", ["product_name", "publisher"])
@pytest.mark.parametrize("character", ["\n", "\r", "\x00", "\x1f", "\x7f"])
def test_rejects_control_characters_in_generated_strings(
    tmp_path: Path, key: str, character: str
):
    release_file = tmp_path / "release.ini"
    write_release(release_file, **{key: f"unsafe{character}value"})
    with pytest.raises((ValueError, configparser.Error), match="control|parsing|line"):
        generator.load_release(release_file)


def test_rejects_changelog_version_mismatch(tmp_path: Path):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("# Changelog\n\n## [v1.7.0] 2026-01-01\n", encoding="utf-8")
    with pytest.raises(ValueError, match="does not match"):
        generator.validate_changelog("1.8.0", "v", changelog)


def test_changelog_uses_configured_tag_prefix(tmp_path: Path):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("# Changelog\n\n## [zone-v1.8.0] 2026-01-01\n", encoding="utf-8")
    generator.validate_changelog("1.8.0", "zone-v", changelog)


def test_installer_checks_for_existing_install_before_setup():
    # GitHub #22: 기존 버전 감지 -> 안내 후 동의 시 자동 제거 -> 재설치 진행.
    setup_text = (ROOT / "installer" / "setup.iss").read_text(encoding="utf-8")
    assert "function InitializeSetup(): Boolean" in setup_text
    assert "RegQueryStringValue(HKA," in setup_text
    assert "HKLM" not in setup_text
    assert "HKCU" not in setup_text
    assert "DisplayVersion" in setup_text
    assert "UninstallString" in setup_text
    assert "/VERYSILENT /SUPPRESSMSGBOXES" in setup_text
    assert "ewWaitUntilTerminated" in setup_text


def test_uninstall_reg_key_matches_actual_windows_uninstall_key_format():
    # BUG-030: GetUninstallRegKey()가 SetupSetting("AppId")로 값을 가져오면 [Setup]의
    # AppId={{{#MyAppId}} 표현식을 Inno가 "{{" -> "{" 로 이스케이프 해제하기 *이전의*
    # 원시 텍스트("{{GUID}", 중괄호 2개)를 반환해, 실제 언인스톨 레지스트리 키
    # ("{GUID}_is1", 중괄호 1개)와 영원히 불일치했다(기존 버전 감지가 항상 실패).
    # 문자열 존재 여부만 보던 기존 테스트는 이 실제 값 불일치를 잡지 못했으므로,
    # ISPP 매크로 치환을 그대로 재현해 최종 레지스트리 키 문자열까지 검증한다.
    setup_text = (ROOT / "installer" / "setup.iss").read_text(encoding="utf-8")
    assert 'SetupSetting("AppId")' not in setup_text

    match = re.search(
        r"function GetUninstallRegKey\(\): String;.*?Result := '([^']+)';",
        setup_text,
        re.DOTALL,
    )
    assert match, "GetUninstallRegKey()의 Result 리터럴을 찾지 못함"
    template = match.group(1)

    release = generator.load_release()
    resolved = template.replace("{#MyAppId}", release["app_id"])
    assert resolved == (
        "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\"
        f"{{{release['app_id']}}}_is1"
    )


def test_installer_removes_runtime_logs_on_uninstall():
    # BUG-016: 무인 제거 후 data\logs\ 하위 런타임 로그 파일이 남는 문제.
    setup_text = (ROOT / "installer" / "setup.iss").read_text(encoding="utf-8")
    assert "[UninstallDelete]" in setup_text
    assert 'Type: filesandordirs; Name: "{app}\\data\\logs"' in setup_text


def test_build_files_consume_generated_metadata():
    spec_text = (ROOT / "build.spec").read_text(encoding="utf-8")
    setup_text = (ROOT / "installer" / "setup.iss").read_text(encoding="utf-8")
    batch_text = (ROOT / "build.bat").read_text(encoding="ascii")
    assert "name=exe_name" in spec_text
    assert "version=version_info" in spec_text
    assert '#include "..\\build\\release-defines.iss"' in setup_text
    assert "scripts\\generate_version_info.py" in batch_text
    assert all(ord(character) < 128 for character in batch_text)
