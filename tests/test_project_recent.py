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
