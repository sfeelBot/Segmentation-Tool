import configparser
import importlib.util
import subprocess
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
        "main_base_tag": "v1.8.0",
        "main_base_commit": "fc9deecab27258adec8bc469a124cb8a0665a064",
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


@pytest.mark.parametrize("tag", ["1.8.0", "v1.8", "v01.8.0", "zone-v1.8.0"])
def test_rejects_invalid_main_base_tag(tmp_path: Path, tag: str):
    release_file = tmp_path / "release.ini"
    write_release(release_file, main_base_tag=tag)
    with pytest.raises(ValueError, match="main_base_tag"):
        generator.load_release(release_file)


@pytest.mark.parametrize("commit", ["fc9deec", "g" * 40, "a" * 39, "a" * 41])
def test_rejects_invalid_main_base_commit(tmp_path: Path, commit: str):
    release_file = tmp_path / "release.ini"
    write_release(release_file, main_base_commit=commit)
    with pytest.raises(ValueError, match="main_base_commit"):
        generator.load_release(release_file)


def test_repository_main_base_is_a_valid_ancestor():
    release = generator.load_release()
    generator.validate_main_base_repository(release)


def test_repository_rejects_nonexistent_main_base_commit(tmp_path: Path, monkeypatch):
    (tmp_path / ".git").mkdir()
    release = generator.load_release()
    monkeypatch.setattr(generator.shutil, "which", lambda _name: "git")
    monkeypatch.setattr(
        generator,
        "_git",
        lambda _root, *args: subprocess.CompletedProcess(args, 1, "", "missing"),
    )
    with pytest.raises(ValueError, match="main_base_commit does not exist"):
        generator.validate_main_base_repository(release, tmp_path)


def test_repository_rejects_nonexistent_main_base_tag(tmp_path: Path, monkeypatch):
    (tmp_path / ".git").mkdir()
    release = generator.load_release()
    monkeypatch.setattr(generator.shutil, "which", lambda _name: "git")

    def fake_git(_root: Path, *args: str):
        returncode = 1 if args[:2] == ("rev-parse", "--verify") else 0
        return subprocess.CompletedProcess(args, returncode, "", "")

    monkeypatch.setattr(generator, "_git", fake_git)
    with pytest.raises(ValueError, match="main_base_tag does not exist"):
        generator.validate_main_base_repository(release, tmp_path)


def test_repository_rejects_non_ancestor_main_base(tmp_path: Path, monkeypatch):
    (tmp_path / ".git").mkdir()
    release = generator.load_release()
    monkeypatch.setattr(generator.shutil, "which", lambda _name: "git")

    def fake_git(_root: Path, *args: str):
        returncode = 1 if args[:2] == ("merge-base", "--is-ancestor") else 0
        return subprocess.CompletedProcess(args, returncode, "tag-commit\n", "")

    monkeypatch.setattr(generator, "_git", fake_git)
    with pytest.raises(ValueError, match="ancestor of the current HEAD"):
        generator.validate_main_base_repository(release, tmp_path)


def test_source_zip_without_git_metadata_uses_format_validation_only(
    tmp_path: Path, monkeypatch
):
    release_file = tmp_path / "release.ini"
    write_release(release_file)
    monkeypatch.setattr(
        generator,
        "_git",
        lambda *_args: pytest.fail("Git must not be called without .git metadata"),
    )
    assert generator.load_release(release_file)["main_base_tag"] == "v1.8.0"


def test_git_command_scopes_safe_directory_to_repository(tmp_path: Path, monkeypatch):
    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(generator.subprocess, "run", fake_run)
    generator._git(tmp_path, "status", "--short")
    assert captured["argv"][:4] == [
        "git",
        "-c",
        f"safe.directory={tmp_path.as_posix()}",
        "-C",
    ]
    assert captured["argv"][4:] == [str(tmp_path), "status", "--short"]
    assert captured["kwargs"]["check"] is False


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


def test_build_files_consume_generated_metadata():
    spec_text = (ROOT / "build.spec").read_text(encoding="utf-8")
    setup_text = (ROOT / "installer" / "setup.iss").read_text(encoding="utf-8")
    batch_text = (ROOT / "build.bat").read_text(encoding="ascii")
    assert "name=exe_name" in spec_text
    assert "version=version_info" in spec_text
    assert '#include "..\\build\\release-defines.iss"' in setup_text
    assert "scripts\\generate_version_info.py" in batch_text
    assert all(ord(character) < 128 for character in batch_text)
