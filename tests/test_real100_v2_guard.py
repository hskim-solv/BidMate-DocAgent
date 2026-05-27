from __future__ import annotations

import subprocess


def test_future_private_eval_work_uses_real100_v2_only() -> None:
    result = subprocess.run(
        ["python3", "scripts/check_real100_v2_only.py"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "real100_v2-only legacy guard passed" in result.stdout
