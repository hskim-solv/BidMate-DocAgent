import importlib.util
import subprocess
from argparse import Namespace
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts/claude-hooks/_ship_run.py"
spec = importlib.util.spec_from_file_location("ship_run", MODULE_PATH)
ship_run = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(ship_run)


def _args(**overrides: str) -> Namespace:
    values = dict(ttl="2h", real_eval="auto", draft="false", dry_run="0", cross_owner="", stacked="", use_existing_arm="0")
    values.update(overrides)
    return Namespace(**values)


def test_is_truthy_accepts_documented_ack_values() -> None:
    assert [ship_run.is_truthy(v) for v in ["1", "TRUE", " yes ", "ack", "0", ""]] == [True, True, True, True, False, False]


def test_run_ship_refuses_existing_arm_without_dispatch(tmp_path: Path, capsys) -> None:
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude/.ship-armed").write_text("armed\n")
    calls = []

    def runner(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=f"{tmp_path}\n")

    assert ship_run.run_ship(_args(), runner=runner) == 1
    assert calls == [["git", "rev-parse", "--show-toplevel"]]
    assert "already exists" in capsys.readouterr().err


def test_run_ship_can_dispatch_existing_arm_without_rearming(tmp_path: Path) -> None:
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude/.ship-armed").write_text("armed\n")
    calls = []

    def runner(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == "git":
            return subprocess.CompletedProcess(cmd, 0, stdout=f"{tmp_path}\n")
        return subprocess.CompletedProcess(cmd, 7)

    assert ship_run.run_ship(_args(use_existing_arm="1"), runner=runner) == 7
    assert [cmd[0] for cmd in calls] == ["git", "bash"]
