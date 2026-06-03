"""Regression: UserPromptSubmit delegation-gate hook (issue #1014, #1753).

Verifies the keyword-match / no-match contract for
``scripts/claude-hooks/userpromptsubmit-delegation-gate.sh``:

  - **Nudge path**: prompts containing non-trivial change-intent OR
    measurement/investigation/parallel keywords emit a nudge to stdout
    and exit 0.
  - **Pass-through path**: trivial prompts (single typo fix, yes/no,
    one-liner questions) produce no stdout and exit 0.
  - **Invariant**: hook never exits non-zero regardless of prompt content.
  - **Parallel text**: nudge output includes "병렬 spawn" guidance.

The hook is copied into a per-test temp REPO_ROOT so
``.hook-fires.log`` writes are isolated from the developer's machine.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).parents[1]
HOOK = REPO / "scripts" / "claude-hooks" / "userpromptsubmit-delegation-gate.sh"
GOVERNANCE = REPO / "scripts" / "_governance.py"

# Keyword groups for parameterised cases.
_GROUP_A_TRIGGERS = [
    # original code-change keywords (Group A)
    "이 코드를 리팩토링해줘",
    "새 기능을 구현해",
    "refactor this module",
    "implement the new feature",
    "다 고쳐줘",
    "전체 파일 수정해줘",
    "all files need updating",
    "새 기능 추가",
    "new feature request",
    "마이그레이션 진행",
    "migrate the data",
    "레거시 코드 처리",
    "legacy code cleanup",
    "아키텍처 변경",
    "architecture overhaul",
    "재설계 필요",
    "redesign this system",
]

_GROUP_B_TRIGGERS = [
    # measurement / investigation / parallel keywords (Group B — issue #1753)
    "성능 측정 해줘",
    "measure the latency",
    "진단 스크립트 작성",
    "diagnose the issue",
    "조사해줘",
    "investigate the failure",
    "분석 보고서 작성",
    "analyze the results",
    "벤치마크 실행",
    "benchmark this function",
    "평가 결과 확인",
    "eval the model",
    "여러 파일을 동시에",
    "multiple files at once",
    "병렬로 처리",
    "parallel processing",
    "동시에 실행",
    "concurrent execution",
    "several tasks",
    # issue #1761: \beval inclusion lock — evaluate/evaluation must still fire
    "evaluate the model",
    "evaluation framework",
    # issue #1761: analy[sz] recall — analysis (noun) / analyse (British) now covered
    "send me the analysis",
    "analyse the data",
]

_NON_TRIGGERS = [
    # trivial / yes-no / single-word — must NOT fire
    "ok",
    "네",
    "yes",
    "no",
    "감사합니다",
    "오타 고쳐줘",                    # typo fix only
    "이 변수명 바꿔줘",               # single rename
    "좋아",
    "이게 뭐야?",                      # pure question
    "what does this function do?",  # pure question
    "git status 알려줘",              # simple lookup
    "버전 확인해줘",
    # issue #1761: \beval word-boundary — retrieval/medieval substring must NOT fire
    "is retrieval hybrid by default?",
    "fix typo in retrieval docstring",
    "this is medieval history",
]


class TestDelegationGateHook(unittest.TestCase):
    """Keyword-match contract for the delegation-gate UserPromptSubmit hook."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._tmp_repo = Path(self._tmp) / "repo"
        (self._tmp_repo / ".claude").mkdir(parents=True)
        (self._tmp_repo / "scripts" / "claude-hooks").mkdir(parents=True)
        (self._tmp_repo / "scripts").mkdir(exist_ok=True)
        shutil.copy(HOOK, self._tmp_repo / "scripts" / "claude-hooks" / HOOK.name)
        shutil.copy(GOVERNANCE, self._tmp_repo / "scripts" / GOVERNANCE.name)
        self._hook = self._tmp_repo / "scripts" / "claude-hooks" / HOOK.name

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _run(self, prompt: str) -> subprocess.CompletedProcess:
        payload = json.dumps({"prompt": prompt})
        return subprocess.run(
            ["bash", str(self._hook)],
            input=payload, text=True,
            capture_output=True, check=False,
            cwd=str(self._tmp_repo),
        )

    def _assert_nudged(self, result: subprocess.CompletedProcess, prompt: str) -> None:
        self.assertEqual(result.returncode, 0, f"hook must exit 0 — prompt: {prompt!r}")
        self.assertIn(
            "agent-delegation-gate",
            result.stdout,
            f"expected nudge for prompt: {prompt!r}",
        )

    def _assert_no_nudge(self, result: subprocess.CompletedProcess, prompt: str) -> None:
        self.assertEqual(result.returncode, 0, f"hook must exit 0 — prompt: {prompt!r}")
        self.assertNotIn(
            "agent-delegation-gate",
            result.stdout,
            f"unexpected nudge for trivial prompt: {prompt!r}",
        )

    # ------------------------------------------------------------------
    # Group A: original code-change keywords
    # ------------------------------------------------------------------

    def test_group_a_triggers_nudge(self) -> None:
        """All original change-intent keywords should fire the nudge."""
        for prompt in _GROUP_A_TRIGGERS:
            with self.subTest(prompt=prompt):
                result = self._run(prompt)
                self._assert_nudged(result, prompt)

    # ------------------------------------------------------------------
    # Group B: measurement / investigation / parallel keywords (issue #1753)
    # ------------------------------------------------------------------

    def test_group_b_triggers_nudge(self) -> None:
        """Expanded measurement/investigation/parallel keywords should fire the nudge."""
        for prompt in _GROUP_B_TRIGGERS:
            with self.subTest(prompt=prompt):
                result = self._run(prompt)
                self._assert_nudged(result, prompt)

    # ------------------------------------------------------------------
    # Non-triggers: trivial / yes-no / simple questions
    # ------------------------------------------------------------------

    def test_trivial_prompts_no_nudge(self) -> None:
        """Trivial prompts must not trigger the nudge."""
        for prompt in _NON_TRIGGERS:
            with self.subTest(prompt=prompt):
                result = self._run(prompt)
                self._assert_no_nudge(result, prompt)

    # ------------------------------------------------------------------
    # Invariants
    # ------------------------------------------------------------------

    def test_exit_zero_always(self) -> None:
        """Hook must exit 0 for any input — nudge-only invariant."""
        for prompt in _GROUP_A_TRIGGERS + _GROUP_B_TRIGGERS + _NON_TRIGGERS:
            with self.subTest(prompt=prompt):
                result = self._run(prompt)
                self.assertEqual(result.returncode, 0)

    def test_nudge_includes_parallel_guidance(self) -> None:
        """Nudge text must include the parallel-spawn recommendation (issue #1753)."""
        result = self._run("병렬로 처리해줘")
        self.assertIn("병렬 spawn", result.stdout)
        self.assertIn("run_in_background", result.stdout)

    def test_nudge_includes_plan_and_explore(self) -> None:
        """Nudge text must still include Plan/Explore recommendations."""
        result = self._run("리팩토링해줘")
        self.assertIn("Plan subagent", result.stdout)
        self.assertIn("Explore subagent", result.stdout)

    def test_malformed_json_exits_zero(self) -> None:
        """Malformed JSON input must not crash the hook (exit 0, no nudge)."""
        malformed = subprocess.run(
            ["bash", str(self._hook)],
            input="not-json", text=True,
            capture_output=True, check=False,
            cwd=str(self._tmp_repo),
        )
        self.assertEqual(malformed.returncode, 0)

    def test_empty_input_exits_zero(self) -> None:
        """Empty stdin must exit 0 without nudge."""
        result = subprocess.run(
            ["bash", str(self._hook)],
            input="", text=True,
            capture_output=True, check=False,
            cwd=str(self._tmp_repo),
        )
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("agent-delegation-gate", result.stdout)


if __name__ == "__main__":
    unittest.main()
