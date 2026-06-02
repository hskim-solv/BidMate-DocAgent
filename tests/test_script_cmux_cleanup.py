"""Regression: scripts/cmux-cleanup.sh — cmux orphan workspace cleanup (issue #1795).

Pins the soft + 3-guard contract for the cmux tab cleanup helper, designed
symmetric to tests/test_hook_pre_push_worktree_hygiene.py (git is real, the
external CLI is faked). The fixtures mirror the REAL cmux 0.64 surface shapes
(captured live during the issue #1795 review), because the first cut used a
2-column `top` stub that could not exercise the column/parent parsing at all:

  - git worktree list comes from a REAL temp git repo with real `git worktree`
    checkouts (live + removed-→-gone), exactly like the worktree-hygiene tests.
  - `cmux top --all --processes --format tsv` rows are 7 tab-separated columns
    `CPU% \\t mem \\t count \\t TYPE \\t ID \\t PARENT \\t label`. A workspace's
    PID is the ID ($5) of a TYPE=process ($4) row whose PARENT ($6) is
    `surface:N`/`pane:N` (the surface/pane number equals the workspace number).
    `_top()` builds exactly those rows; non-process noise rows (whose mem/count
    integers must NEVER be harvested as PIDs) are added where it matters.
  - `cmux tree` puts the focus markers (`◀ active`, `◀ here`) on the pane/
    surface CHILD lines, not the parent `workspace workspace:N` line.
  - `cmux workspace list --id-format both` prints `[*] workspace:N <uuid>
    <title>`; `CMUX_WORKSPACE_ID` is the UUID (not the ref), so guard ① maps the
    uuid → ref via this list. `_ws_list()` builds that shape.
  - `cmux` and `lsof` are fake PATH/$CMUX_BIN stubs. `rpc workspace.close`
    APPENDS its argv to $CMUX_CLOSE_LOG — that capture is the close/non-close
    oracle. `lsof` maps `-p <pid>` → cwd via env (LSOF_PID_<pid>=<path>).

close is irreversible so every guard fails safe toward NOT closing; the dry-run
/ unknown-flag / internal-error cases all pin `exit 0`. A static source scan
(TestCmuxCleanupStatic) mirrors test_spawn_track_session_script.py.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "cmux-cleanup.sh"


def _source() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _code() -> str:
    """Source with full-line comments and blank lines stripped.

    Negative guards ("must NOT contain …") check the executable body, not the
    prose — comments intentionally name `set -e` and `/tmp/` to document the
    contracts, so a raw whole-file scan would false-positive on them.
    """
    return "\n".join(
        line
        for line in _source().splitlines()
        if line.strip() and not line.strip().startswith("#")
    )


class TestCmuxCleanupStatic(unittest.TestCase):
    def test_set_u_present(self) -> None:
        self.assertIn("set -u", _source())

    def test_no_set_e(self) -> None:
        # Soft contract: a mid-run failure must never abort (always exit 0).
        self.assertNotIn("set -e", _code())
        self.assertNotIn("set -euo", _code())

    def test_exit_zero_terminal_branch(self) -> None:
        # The final statement of the script is the soft `exit 0`.
        self.assertEqual("exit 0", _code().splitlines()[-1].strip())

    def test_self_skip_token_present(self) -> None:
        # Guard ①: the self-workspace env is consulted.
        self.assertIn("CMUX_WORKSPACE_ID", _source())

    def test_self_ref_resolution_present(self) -> None:
        # Guard ①: CMUX_WORKSPACE_ID may be a UUID, so the loop compares against
        # a resolved self_ref (not the raw env). Pin that the resolution exists.
        self.assertIn("self_ref", _code())

    def test_pid_parsing_is_column_exact(self) -> None:
        # CRITICAL guard: the PID harvest must match the parent column EXACTLY
        # (awk ==), never substring — else workspace:1 captures workspace:10's
        # rows. Pin the awk parse + the absence of the old substring glob.
        code = _code()
        self.assertIn("$4 == \"process\"", code)
        self.assertNotIn("workspace:[0-9]/ }", code)  # old single-digit glob gone

    def test_cmux_absolute_path_default(self) -> None:
        # Inherits the spawn helper's absolute-path default + env override.
        self.assertIn("/Applications/cmux.app/Contents/Resources/bin/cmux", _source())

    def test_close_only_outside_dry_run_branch(self) -> None:
        # `rpc workspace.close` must live in the else-branch of the dry-run
        # guard, never in the dry-run branch.
        src = _source()
        self.assertIn("workspace.close", src)
        self.assertEqual(1, src.count("rpc workspace.close"))
        close_idx = src.index("rpc workspace.close")
        before = src[:close_idx]
        self.assertIn("would close", before)
        self.assertIn('dry_run" -eq 1', before)
        self.assertGreater(before.rindex("else"), before.rindex("would close"))

    def test_no_fixed_tmp_redirect(self) -> None:
        # CLAUDE.md `## 금지`: never redirect to a global fixed /tmp/<name>.
        self.assertNotIn("/tmp/", _code())


class TestCmuxCleanupBehavior(unittest.TestCase):
    def setUp(self) -> None:
        # Real temp git repo (like the worktree-hygiene tests). Case #12 builds
        # its OWN symlink for the path-divergence check, so it does not depend
        # on the temp root being symlinked (it is on macOS /var/folders, but
        # not on Linux/CI).
        self._tmp = tempfile.mkdtemp(prefix="cmux-cleanup-")
        self.repo = Path(self._tmp) / "repo"
        self.repo.mkdir(parents=True)
        self._git("init", "-q")
        self._git("config", "user.email", "t@example.com")
        self._git("config", "user.name", "tester")
        self._git("config", "commit.gpgsign", "false")
        (self.repo / "README.md").write_text("base\n", encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-q", "-m", "base")
        self._git("branch", "-M", "main")

        self._bindir = Path(self._tmp) / "fakebin"
        self._bindir.mkdir(exist_ok=True)
        self._close_log = Path(self._tmp) / "close.log"
        # Per-PID cwd env injected into the fake lsof.
        self._lsof_env: dict[str, str] = {}

    def tearDown(self) -> None:
        self._git("worktree", "prune")
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _git(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args],
            cwd=str(cwd or self.repo),
            capture_output=True,
            text=True,
            check=False,
        )

    def _add_worktree(self, name: str, branch: str) -> Path:
        wt = Path(self._tmp) / name
        self._git("worktree", "add", "-b", branch, str(wt), "main")
        return wt

    def _worktree_path_for(self, raw: str) -> str | None:
        # The exact path `git worktree list --porcelain` prints for the
        # worktree whose realpath matches `raw` (git resolves symlinks, so this
        # may differ verbatim from the mkdtemp string — case #12 exercises that).
        want = os.path.realpath(raw)
        out = self._git("worktree", "list", "--porcelain").stdout
        for line in out.splitlines():
            if line.startswith("worktree "):
                p = line[len("worktree "):]
                if os.path.realpath(p) == want:
                    return p
        return None

    # --- fixture builders mirroring the real cmux surfaces -------------------
    def _top(self, procs: list[tuple[str, str]], *, noise: str = "") -> str:
        """Build a real-shape `cmux top` TSV.

        `procs` = [(ws_n, pid), …] → a TYPE=process row per PID whose PARENT is
        `surface:ws_n` (real format; the surface number == workspace number).
        `noise` is prepended verbatim — used to inject non-process rows whose
        mem/count integers must never be harvested as PIDs.
        """
        rows = list(noise.splitlines()) if noise else []
        for ws_n, pid in procs:
            # CPU% \t mem \t count \t TYPE \t ID \t PARENT \t label
            rows.append(f"0.7\t419350064\t1\tprocess\t{pid}\tsurface:{ws_n}\tclaude")
        return "\n".join(rows) + "\n"

    def _ws_list(self, ns: list[str], *, star: str | None = None) -> str:
        """`[*] workspace:N uuid-N Title-N` per row (matches --id-format both)."""
        rows = []
        for n in ns:
            mark = "*" if star == n else " "
            rows.append(f"{mark} workspace:{n} uuid-{n} Title-{n}")
        return "\n".join(rows) + "\n"

    def _stub(self, name: str, body: str) -> Path:
        p = self._bindir / name
        p.write_text(body, encoding="utf-8")
        p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return p

    def _write_fake_cmux(
        self,
        *,
        version_ok: bool = True,
        tree: str = "",
        ws_list: str = "",
        top: str = "",
    ) -> None:
        # `tree` / `workspace list` / `top` echo fixed fixtures via env so each
        # test controls the workspace set + markers + PID rows. `rpc
        # workspace.close` appends its full argv to $CMUX_CLOSE_LOG (the
        # close/non-close oracle) and exits per $CMUX_CLOSE_EXIT (default 0).
        ver = "exit 0" if version_ok else "exit 1"
        body = (
            "#!/bin/sh\n"
            'case "$1" in\n'
            f"  --version) {ver} ;;\n"
            '  tree) printf "%s" "$CMUX_TREE" ;;\n'
            '  workspace)\n'
            '    if [ "$2" = list ]; then printf "%s" "$CMUX_WS_LIST"; fi ;;\n'
            '  top) printf "%s" "$CMUX_TOP" ;;\n'
            '  rpc)\n'
            '    if [ "$2" = workspace.close ]; then\n'
            '      printf "%s\\n" "$*" >> "$CMUX_CLOSE_LOG"\n'
            '      exit "${CMUX_CLOSE_EXIT:-0}"\n'
            "    fi ;;\n"
            "esac\n"
            "exit 0\n"
        )
        self._stub("cmux", body)
        self._cmux_env = {
            "CMUX_TREE": tree,
            "CMUX_WS_LIST": ws_list,
            "CMUX_TOP": top,
            "CMUX_CLOSE_LOG": str(self._close_log),
        }

    def _write_fake_lsof(self) -> None:
        # Map `-p <pid>` → $LSOF_PID_<pid> as the `-Fn` cwd line (`n<path>`).
        # Missing/empty env → no output → caller sees "cwd unknown".
        body = (
            "#!/bin/sh\n"
            "pid=\n"
            "while [ $# -gt 0 ]; do\n"
            '  if [ "$1" = -p ]; then shift; pid="$1"; fi\n'
            "  shift\n"
            "done\n"
            'eval "cwd=\\${LSOF_PID_${pid}:-}"\n'
            'if [ -n "$cwd" ]; then\n'
            '  printf "p%s\\nfcwd\\nn%s\\n" "$pid" "$cwd"\n'
            "fi\n"
            "exit 0\n"
        )
        self._stub("lsof", body)

    def _set_pid_cwd(self, pid: str, cwd: str) -> None:
        self._lsof_env[f"LSOF_PID_{pid}"] = cwd

    def _run(
        self,
        *args: str,
        self_ws: str | None = None,
        close_exit: str = "0",
        cwd: Path | str | None = None,
    ) -> subprocess.CompletedProcess:
        self._write_fake_lsof()
        env = dict(os.environ)
        env["PATH"] = f"{self._bindir}{os.pathsep}{env['PATH']}"
        env["CMUX_BIN"] = str(self._bindir / "cmux")
        env["CMUX_CLOSE_EXIT"] = close_exit
        env.update(getattr(self, "_cmux_env", {}))
        env.update(self._lsof_env)
        if self_ws is None:
            env.pop("CMUX_WORKSPACE_ID", None)
        else:
            env["CMUX_WORKSPACE_ID"] = self_ws
        return subprocess.run(
            ["bash", str(SCRIPT), *args],
            cwd=str(cwd or self.repo),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def _close_log_text(self) -> str:
        return self._close_log.read_text(encoding="utf-8") if self._close_log.exists() else ""

    # --- #1 ---------------------------------------------------------------
    def test_cmux_absent_soft_skips(self) -> None:
        # CMUX_BIN points at a missing path, no cmux on the (real) PATH →
        # `--version` fails → immediate soft skip.
        self._write_fake_cmux()
        self._write_fake_lsof()
        env = dict(os.environ)
        env["CMUX_BIN"] = str(self._bindir / "nonexistent-cmux")
        env["CMUX_WORKSPACE_ID"] = "uuid-9"
        r = subprocess.run(
            ["bash", str(SCRIPT)],
            cwd=str(self.repo),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual("", self._close_log_text())
        self.assertIn("not available", r.stderr)

    # --- #2 (guard ①, UUID self) -----------------------------------------
    def test_self_workspace_never_closed_uuid(self) -> None:
        # CMUX_WORKSPACE_ID is the UUID (real cmux behavior). Even though ws2's
        # cwd is gone, mapping uuid-2 → workspace:2 must protect it.
        gone = self._add_worktree("wt2", "feat-2")
        gone_path = str(gone)
        self._git("worktree", "remove", "--force", gone_path)
        self._write_fake_cmux(
            tree="├── workspace workspace:2 \"T2\"\n",
            ws_list=self._ws_list(["2"]),
            top=self._top([("2", "2002")]),
        )
        self._set_pid_cwd("2002", gone_path)
        r = self._run(self_ws="uuid-2")  # UUID form, not workspace:2
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertNotIn("workspace:2", self._close_log_text())

    # --- #3 ---------------------------------------------------------------
    def test_self_unset_skips_all(self) -> None:
        gone = self._add_worktree("wt5", "feat-5")
        gone_path = str(gone)
        self._git("worktree", "remove", "--force", gone_path)
        self._write_fake_cmux(
            tree="├── workspace workspace:5 \"T5\"\n",
            ws_list=self._ws_list(["5"]),
            top=self._top([("5", "5005")]),
        )
        self._set_pid_cwd("5005", gone_path)
        r = self._run(self_ws=None)  # CMUX_WORKSPACE_ID unset
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual("", self._close_log_text())
        self.assertIn("CMUX_WORKSPACE_ID unset", r.stderr)

    # --- #3b (guard ①, unresolvable self → skip all) ----------------------
    def test_self_uuid_unresolvable_skips_all(self) -> None:
        # A UUID that is NOT in `workspace list` → we cannot self-exclude → the
        # safest action is to close nothing (a self-close is the worst outcome).
        gone = self._add_worktree("wt5", "feat-5")
        gone_path = str(gone)
        self._git("worktree", "remove", "--force", gone_path)
        self._write_fake_cmux(
            tree="├── workspace workspace:5 \"T5\"\n",
            ws_list=self._ws_list(["5"]),  # no uuid-absent row
            top=self._top([("5", "5005")]),
        )
        self._set_pid_cwd("5005", gone_path)
        r = self._run(self_ws="uuid-does-not-exist")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual("", self._close_log_text())
        self.assertIn("cannot resolve self workspace ref", r.stderr)

    # --- #4 (guard ②, ◀ here on a child surface line) ---------------------
    def test_active_marker_on_child_line_protected(self) -> None:
        # The focus marker sits on the surface CHILD line (real format); the
        # parent workspace line has none. ws1 must still be protected.
        gone = self._add_worktree("wt1", "feat-1")
        gone_path = str(gone)
        self._git("worktree", "remove", "--force", gone_path)
        tree = (
            "window window:1 [current] ◀ active\n"
            "├── workspace workspace:1 \"T1\"\n"
            "│   └── pane pane:1 [focused]\n"
            "│       └── surface surface:1 [terminal] \"T1\" [selected] ◀ here tty=ttys001\n"
            "├── workspace workspace:9 \"T9\"\n"
            "│   └── surface surface:9 [terminal] \"T9\" [selected] tty=ttys005\n"
        )
        self._write_fake_cmux(
            tree=tree,
            ws_list=self._ws_list(["1", "9"]),
            top=self._top([("1", "1001")]),
        )
        self._set_pid_cwd("1001", gone_path)
        r = self._run(self_ws="uuid-9")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertNotIn("workspace:1", self._close_log_text())

    # --- #5 (guard ②, `*` selected in workspace list) --------------------
    def test_selected_star_protected(self) -> None:
        # No tree focus markers; ws3 is the shown workspace (`* workspace:3`).
        gone = self._add_worktree("wt3", "feat-3")
        gone_path = str(gone)
        self._git("worktree", "remove", "--force", gone_path)
        self._write_fake_cmux(
            tree="├── workspace workspace:3 \"T3\"\n├── workspace workspace:9 \"T9\"\n",
            ws_list=self._ws_list(["3", "9"], star="3"),
            top=self._top([("3", "3003")]),
        )
        self._set_pid_cwd("3003", gone_path)
        r = self._run(self_ws="uuid-9")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertNotIn("workspace:3", self._close_log_text())

    # --- #6 ---------------------------------------------------------------
    def test_tree_parse_empty_skips_all(self) -> None:
        gone = self._add_worktree("wt8", "feat-8")
        gone_path = str(gone)
        self._git("worktree", "remove", "--force", gone_path)
        self._write_fake_cmux(
            tree="",  # empty tree output → active set unknown → skip all
            ws_list=self._ws_list(["8"]),
            top=self._top([("8", "8008")]),
        )
        self._set_pid_cwd("8008", gone_path)
        r = self._run(self_ws="uuid-9")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual("", self._close_log_text())
        self.assertIn("empty", r.stderr)

    # --- #7 ---------------------------------------------------------------
    def test_live_worktree_tab_protected(self) -> None:
        live = self._add_worktree("wt4", "feat-4")  # NOT removed → live
        self._write_fake_cmux(
            tree="├── workspace workspace:4 \"T4\"\n├── workspace workspace:9 \"T9\"\n",
            ws_list=self._ws_list(["4", "9"]),
            top=self._top([("4", "4004")]),
        )
        self._set_pid_cwd("4004", str(live))
        r = self._run(self_ws="uuid-9")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertNotIn("workspace:4", self._close_log_text())

    # --- #8 ---------------------------------------------------------------
    def test_orphan_only_closed(self) -> None:
        gone = self._add_worktree("wt5", "feat-5")
        gone_path = str(gone)
        self._git("worktree", "remove", "--force", gone_path)
        self._write_fake_cmux(
            tree="├── workspace workspace:5 \"T5\"\n├── workspace workspace:9 \"T9\"\n",
            ws_list=self._ws_list(["5", "9"]),
            top=self._top([("5", "5005")]),
        )
        self._set_pid_cwd("5005", gone_path)
        r = self._run(self_ws="uuid-9")
        self.assertEqual(0, r.returncode, r.stderr)
        log = self._close_log_text()
        self.assertIn("workspace:5", log)
        self.assertEqual(1, log.count("workspace.close"))

    # --- #9 ---------------------------------------------------------------
    def test_dry_run_never_calls_close(self) -> None:
        gone = self._add_worktree("wt5", "feat-5")
        gone_path = str(gone)
        self._git("worktree", "remove", "--force", gone_path)
        self._write_fake_cmux(
            tree="├── workspace workspace:5 \"T5\"\n├── workspace workspace:9 \"T9\"\n",
            ws_list=self._ws_list(["5", "9"]),
            top=self._top([("5", "5005")]),
        )
        self._set_pid_cwd("5005", gone_path)
        r = self._run("--dry-run", self_ws="uuid-9")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("would close workspace:5", r.stderr)
        self.assertEqual("", self._close_log_text())  # close NEVER called

    # --- #10 --------------------------------------------------------------
    def test_cwd_unknown_skips(self) -> None:
        # ws6 has a PID in `top`, but lsof returns nothing for it → cwd unknown.
        self._write_fake_cmux(
            tree="├── workspace workspace:6 \"T6\"\n├── workspace workspace:9 \"T9\"\n",
            ws_list=self._ws_list(["6", "9"]),
            top=self._top([("6", "6006")]),
        )
        # Intentionally do NOT set LSOF_PID_6006 → empty cwd.
        r = self._run(self_ws="uuid-9")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertNotIn("workspace:6", self._close_log_text())
        self.assertIn("cwd unknown", r.stderr)

    # --- #11 --------------------------------------------------------------
    def test_multi_pid_or_protection(self) -> None:
        live = self._add_worktree("wt7live", "feat-7-live")
        gone = self._add_worktree("wt7gone", "feat-7-gone")
        gone_path = str(gone)
        self._git("worktree", "remove", "--force", gone_path)
        self._write_fake_cmux(
            tree="├── workspace workspace:7 \"T7\"\n├── workspace workspace:9 \"T9\"\n",
            ws_list=self._ws_list(["7", "9"]),
            # Two process rows for ws7 (claude + a child), both parent surface:7.
            top=self._top([("7", "7001"), ("7", "7002")]),
        )
        self._set_pid_cwd("7001", str(live))  # one cwd is live
        self._set_pid_cwd("7002", gone_path)  # the other is gone
        r = self._run(self_ws="uuid-9")
        self.assertEqual(0, r.returncode, r.stderr)
        # OR protection: any live cwd protects the whole workspace.
        self.assertNotIn("workspace:7", self._close_log_text())

    # --- #12 (path normalization regression) ------------------------------
    def test_path_normalization_no_false_orphan(self) -> None:
        # A live worktree can surface under two textually-different paths that
        # resolve to the same dir: `git worktree list` realpath-resolves
        # symlinks (it stores the canonical path) while `lsof -d cwd` reports
        # whatever the process holds. macOS produces this implicitly (mkdtemp
        # under /var/folders, a /var → /private/var symlink); CI is Linux where
        # the temp root is NOT symlinked, so we construct the divergence
        # EXPLICITLY with our own symlink — otherwise the assertNotEqual below
        # is vacuous on Linux. Without normalizing BOTH sides the live worktree
        # is mis-flagged as orphan and irreversibly closed.
        live = self._add_worktree("wt12", "feat-12")
        git_reported = self._worktree_path_for(str(live))
        if git_reported is None:
            self.fail("git did not report the live worktree path")
        canonical = os.path.realpath(git_reported)
        # An alias prefix symlink → the same worktree under a different textual
        # path, guaranteed on any OS (not relying on a symlinked temp root).
        alias_root = Path(self._tmp) / "alias"
        if not alias_root.is_symlink():
            alias_root.symlink_to(os.path.dirname(canonical))
        lsof_cwd = str(alias_root / os.path.basename(canonical))
        self.assertNotEqual(
            canonical,
            lsof_cwd,
            "alias path must differ textually from the realpath'd worktree",
        )
        self.assertEqual(canonical, os.path.realpath(lsof_cwd))
        self._write_fake_cmux(
            tree="├── workspace workspace:12 \"T12\"\n├── workspace workspace:9 \"T9\"\n",
            ws_list=self._ws_list(["12", "9"]),
            top=self._top([("12", "1212")]),
        )
        self._set_pid_cwd("1212", lsof_cwd)
        r = self._run(self_ws="uuid-9")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertNotIn("workspace:12", self._close_log_text())

    # --- #13 --------------------------------------------------------------
    def test_soft_exit_zero_on_internal_error(self) -> None:
        gone = self._add_worktree("wt5", "feat-5")
        gone_path = str(gone)
        self._git("worktree", "remove", "--force", gone_path)
        self._write_fake_cmux(
            tree="├── workspace workspace:5 \"T5\"\n├── workspace workspace:9 \"T9\"\n",
            ws_list=self._ws_list(["5", "9"]),
            top=self._top([("5", "5005")]),
        )
        self._set_pid_cwd("5005", gone_path)
        # rpc workspace.close stub returns exit 1; the script must still exit 0.
        r = self._run(self_ws="uuid-9", close_exit="1")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("failed to close workspace:5", r.stderr)

    # --- #14 --------------------------------------------------------------
    def test_unknown_flag_is_soft(self) -> None:
        self._write_fake_cmux(
            tree="├── workspace workspace:9 \"T9\"\n",
            ws_list=self._ws_list(["9"]),
            top="",
        )
        r = self._run("--bogus", self_ws="uuid-9")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("unknown option", r.stderr)

    # --- #15 (CRITICAL regression: substring-colliding ws numbers) --------
    def test_substring_collision_independent_judgment(self) -> None:
        # workspace:1 (live) and workspace:10 (gone) coexist in `top`. The old
        # substring parser let `workspace:1` capture `workspace:10`'s row (and a
        # single-digit glob left a stray `0`), cross-contaminating the cwd set.
        # The column-exact parser (surface:1 ≠ surface:10) judges each alone:
        # ws1 protected (live), ws10 closed (gone) — nothing else.
        live = self._add_worktree("wt1", "feat-1")
        gone = self._add_worktree("wt10", "feat-10")
        gone_path = str(gone)
        self._git("worktree", "remove", "--force", gone_path)
        self._write_fake_cmux(
            tree="├── workspace workspace:1 \"T1\"\n"
            "├── workspace workspace:10 \"T10\"\n"
            "├── workspace workspace:9 \"T9\"\n",
            ws_list=self._ws_list(["1", "10", "9"]),
            top=self._top([("1", "1001"), ("10", "1010")]),
        )
        self._set_pid_cwd("1001", str(live))   # ws1 cwd live
        self._set_pid_cwd("1010", gone_path)   # ws10 cwd gone
        r = self._run(self_ws="uuid-9")
        self.assertEqual(0, r.returncode, r.stderr)
        log = self._close_log_text()
        self.assertNotIn("workspace:1\n", log)         # ws1 NOT closed
        self.assertNotIn('workspace:1"', log)          # (json form) ws1 NOT closed
        self.assertIn("workspace:10", log)             # ws10 closed
        self.assertEqual(1, log.count("workspace.close"))

    # --- #16 (CRITICAL regression: non-process integers never harvested) --
    def test_non_process_integer_columns_not_pids(self) -> None:
        # A workspace/surface NOISE row carries a large mem integer (499082552)
        # and a small count (7). The old whole-row tokenizer would harvest those
        # as PIDs; if such a bogus PID happened to resolve to a LIVE cwd it would
        # wrongly PROTECT a real orphan (and the gone-direction is a false-orphan
        # close). The column parser reads only process rows' ID column.
        gone = self._add_worktree("wt5", "feat-5")
        gone_path = str(gone)
        self._git("worktree", "remove", "--force", gone_path)
        live = self._add_worktree("wt5live", "feat-5-live")
        noise = (
            "0.7\t499082552\t7\tworkspace\tworkspace:5\twindow:1\tTitle-5\n"
            "0.7\t499082552\t7\tsurface\tsurface:5\tpane:5\tTitle-5\n"
        )
        self._write_fake_cmux(
            tree="├── workspace workspace:5 \"T5\"\n├── workspace workspace:9 \"T9\"\n",
            ws_list=self._ws_list(["5", "9"]),
            top=self._top([("5", "5005")], noise=noise),
        )
        self._set_pid_cwd("5005", gone_path)            # the REAL pid → gone
        self._set_pid_cwd("499082552", str(live))       # bogus "pid" → live trap
        self._set_pid_cwd("7", str(live))               # bogus "pid" → live trap
        r = self._run(self_ws="uuid-9")
        self.assertEqual(0, r.returncode, r.stderr)
        # Only the real process PID (gone) counts → ws5 IS the orphan, closed.
        self.assertIn("workspace:5", self._close_log_text())

    # --- #17 (HIGH regression: git worktree list failure → skip all) ------
    def test_git_worktree_list_failure_skips_all(self) -> None:
        # Run OUTSIDE any git repo: `git worktree list` fails/empties, so the
        # live set is unknown and every cwd would look gone → must skip all,
        # symmetric to the empty-`cmux tree` guard.
        nongit = Path(self._tmp) / "not-a-repo"
        nongit.mkdir()
        self._write_fake_cmux(
            tree="├── workspace workspace:5 \"T5\"\n├── workspace workspace:9 \"T9\"\n",
            ws_list=self._ws_list(["5", "9"]),
            top=self._top([("5", "5005")]),
        )
        self._set_pid_cwd("5005", str(nongit))
        r = self._run(self_ws="uuid-9", cwd=nongit)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual("", self._close_log_text())
        self.assertIn("git worktree list", r.stderr)

    # --- #18 (guard ③ -d: a present non-worktree dir is never an orphan) --
    def test_present_non_worktree_dir_protected(self) -> None:
        # A tab the user cd'd into a still-existing directory that is NOT a
        # worktree (e.g. ~). cwd exists → not an orphan → protected.
        present = Path(self._tmp) / "just-a-dir"
        present.mkdir()
        self._write_fake_cmux(
            tree="├── workspace workspace:5 \"T5\"\n├── workspace workspace:9 \"T9\"\n",
            ws_list=self._ws_list(["5", "9"]),
            top=self._top([("5", "5005")]),
        )
        self._set_pid_cwd("5005", str(present))
        r = self._run(self_ws="uuid-9")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertNotIn("workspace:5", self._close_log_text())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
