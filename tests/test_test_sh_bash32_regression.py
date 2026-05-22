"""Regression: scripts/test.sh empty-array expansion crashes macOS bash 3.2 (issue #1179).

scripts/test.sh runs under `set -euo pipefail`, then expands four optional
flag arrays (XDIST/COV/SPLIT/STORE_DURATIONS) onto the pytest call. macOS
system bash (3.2.57) treats `"${ARR[@]}"` for an *empty* array as an
unbound-variable error under `set -u` and aborts before pytest runs. The fix
uses the bash-3.2-safe `"${ARR[@]+"${ARR[@]}"}"` idiom so empty arrays expand
to nothing. Linux CI (bash 4+/5) never reproduced the runtime crash.

Two complementary guards:
  1. Static: each optional array at the call site uses the `[@]+` idiom.
     Catches a revert to the bare form on any platform, including Linux CI
     where the runtime crash does not reproduce.
  2. Behavioral: scripts/test.sh, run with all four arrays forced empty (a
     stubbed `python` whose `import` probes all fail) and a stubbed `pytest`,
     reaches pytest and exits 0. On macOS /bin/bash 3.2 this is the actual
     crash scenario; on bash 4+ it confirms the end-to-end stub path.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).parents[1]
SCRIPT = REPO / "scripts" / "test.sh"
OPTIONAL_ARRAYS = ("XDIST_FLAGS", "COV_FLAGS", "SPLIT_FLAGS", "STORE_DURATIONS_FLAGS")


def _stub(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class TestTestShBash32(unittest.TestCase):
    def test_call_site_guards_each_optional_array(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")
        for name in OPTIONAL_ARRAYS:
            needle = "${" + name + "[@]+"
            self.assertIn(
                needle,
                text,
                f"{name} must use the bash-3.2 empty-safe expansion "
                f'"${{{name}[@]+"${{{name}[@]}}"}}" (issue #1179); a bare '
                f'"${{{name}[@]}}" crashes macOS bash 3.2 under set -u.',
            )

    def test_reaches_pytest_with_all_arrays_empty(self) -> None:
        tmp = tempfile.mkdtemp(prefix="test-sh-bash32-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        binp = Path(tmp)
        # `python` whose every `-c "import ..."` probe fails -> all 4 arrays empty.
        _stub(binp / "python", "#!/bin/sh\nexit 1\n")
        # `ruff` no-op so the top lint gate passes instantly.
        _stub(binp / "ruff", "#!/bin/sh\nexit 0\n")
        # `pytest` records that it was reached, then exits 0 (never runs the suite).
        _stub(binp / "pytest", '#!/bin/sh\necho "PYTEST_STUB_REACHED:$*"\nexit 0\n')

        env = dict(os.environ)
        env["PATH"] = f"{binp}{os.pathsep}{env['PATH']}"
        # Default local run leaves the shard/duration env vars unset.
        for var in (
            "BIDMATE_PYTEST_SPLITS",
            "BIDMATE_PYTEST_SHARD",
            "BIDMATE_PYTEST_STORE_DURATIONS",
        ):
            env.pop(var, None)

        # Prefer /bin/bash: on macOS it is the 3.2 build that reproduces the
        # crash. On Linux it is bash 4+/5 and the test still passes.
        bash = "/bin/bash" if Path("/bin/bash").exists() else "bash"
        r = subprocess.run(
            [bash, str(SCRIPT)],
            cwd=REPO,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            0, r.returncode, f"test.sh crashed before reaching pytest:\n{r.stderr}"
        )
        # All four arrays empty -> pytest invoked with just `-q`.
        self.assertIn(
            "PYTEST_STUB_REACHED:-q",
            r.stdout,
            f"test.sh did not reach pytest with empty arrays:\n"
            f"stdout={r.stdout!r}\nstderr={r.stderr!r}",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
