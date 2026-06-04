import importlib.util
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts/claude-hooks/_ship_private_preserve.py"
spec = importlib.util.spec_from_file_location("ship_private_preserve", MODULE_PATH)
ship_private_preserve = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(ship_private_preserve)


def test_safe_relative_path_rejects_escape_paths() -> None:
    assert ship_private_preserve._safe_relative_path("reports/real100_v2/out.json") == Path("reports/real100_v2/out.json")
    with pytest.raises(ValueError):
        ship_private_preserve._safe_relative_path("/tmp/out.json")
    with pytest.raises(ValueError):
        ship_private_preserve._safe_relative_path("reports/../secret.json")


def test_records_parses_space_and_tab_status_lines() -> None:
    assert list(ship_private_preserve._records(["?? reports/a.json\n", "M \treports/b.json\n", "\n"])) == [
        ("??", "reports/a.json"),
        ("M ", "reports/b.json"),
    ]


def test_preserve_one_dry_run_uses_conflict_destination_without_moving(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    preserve_root = tmp_path / "preserve"
    source = repo_root / "reports/real100_v2/out.json"
    dest = preserve_root / "reports/real100_v2/out.json"
    source.parent.mkdir(parents=True)
    dest.parent.mkdir(parents=True)
    source.write_text("new\n")
    dest.write_text("old\n")

    message = ship_private_preserve.preserve_one(
        repo_root=repo_root,
        preserve_root=preserve_root,
        status="??",
        relpath="reports/real100_v2/out.json",
        dry_run=True,
    )

    assert message.startswith("dry-run move reports/real100_v2/out.json -> ")
    assert ".ship-preserved-" in message
    assert source.read_text() == "new\n"
    assert dest.read_text() == "old\n"
