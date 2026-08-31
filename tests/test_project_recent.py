from pathlib import Path

from app.core import i18n, project


def test_recent_skips_inaccessible_paths(monkeypatch, tmp_path) -> None:
    accessible = tmp_path / "project"
    accessible.mkdir()
    blocked = Path("blocked-project")
    monkeypatch.setattr(
        i18n, "load_settings",
        lambda: {"recent_projects": [str(blocked), str(accessible)]},
    )
    original_exists = Path.exists

    def fake_exists(path: Path) -> bool:
        if path == blocked:
            raise PermissionError("blocked")
        return original_exists(path)

    monkeypatch.setattr(Path, "exists", fake_exists)

    assert project.recent() == [accessible]


def test_name_follows_folder_after_external_rename(tmp_path) -> None:
    """폴더를 앱 밖에서 리네임해도 Project.name은 메타데이터가 아닌 실제
    폴더명을 즉시 반영해야 한다 (project.json의 name 필드는 무시)."""
    original = tmp_path / "Foo"
    original.mkdir()
    proj = project.Project(original)
    proj.save_metadata(name="Foo")
    assert proj.name == "Foo"

    renamed = tmp_path / "Bar"
    original.rename(renamed)
    reopened = project.Project(renamed)

    assert reopened.name == "Bar"
    # project.json의 name 필드 자체는 그대로 남아있어야 한다
    # (project_export._infer_base_name()의 import 폴더명 추론용).
    assert reopened._meta.get("name") == "Foo"
