"""Structural smoke for ``notebooks/embedding_finetune.ipynb`` (issue #435).

Executing the notebook end-to-end requires a GPU + 2 GB of model
downloads, so CI cannot run it. The cheap-and-valuable invariants
*are* worth pinning, though:

* the file is valid Jupyter JSON (nbformat 4.x);
* the cell sequence (markdown / code interleave) matches the expected
  skeleton — so a future contributor cannot silently delete a step;
* every code cell is syntactically valid Python after Jupyter line
  magics (``%pip``, ``%`` …) and shell escapes (``!``) are stripped;
* the notebook commits *empty* outputs (committed-with-outputs notebooks
  bloat git history and leak data).
* the HF token cell pulls from an env var — it never inlines a literal
  token by mistake.

If you find yourself adding more cells to the notebook, update
``EXPECTED_MARKDOWN_HEADINGS`` so this smoke catches accidental
deletions. Conversely, if a cell stops being useful, delete both the
notebook cell *and* its heading entry here.
"""

from __future__ import annotations

import ast
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NOTEBOOK = ROOT / "notebooks" / "embedding_finetune.ipynb"


# Headings that must appear in the notebook's markdown cells (substring
# match against the joined source). Order is enforced.
EXPECTED_MARKDOWN_HEADINGS = (
    "# BidMate Embedding LoRA Fine-tune",
    "## 1. 환경 설치",
    "## 2. GPU 확인",
    "## 3. 리포지토리 마운트",
    "## 4. 학습 데이터 생성",
    "## 5. 베이스 임베딩 로드",
    "## 6. LoRA 적용",
    "## 7. 학습 / 검증 데이터 로드",
    "## 8. 학습 전 베이스라인 측정",
    "## 9. 학습 — `MultipleNegativesRankingLoss`",
    "## 10. 학습 후 측정",
    "## 11. LoRA 어댑터 저장",
    "## 12. Hugging Face Hub 업로드",
    "## 13. (마지막) 데이터 누수 재검증",
)


def _load_notebook() -> dict:
    raw = NOTEBOOK.read_text(encoding="utf-8")
    return json.loads(raw)


def _cell_source(cell: dict) -> str:
    src = cell.get("source") or []
    if isinstance(src, str):
        return src
    return "".join(src)


def _strip_jupyter_magics(source: str) -> str:
    """Rewrite Jupyter line magics (``%pip ...``) and shell escapes
    (``!cmd``) so ``ast.parse`` accepts the cell.

    A magic line may have backslash-continuations across multiple lines
    (``%pip install -q \\``); the continuation lines look like plain
    indented strings but are part of the magic. We swallow the whole
    chain — replacing the leading line with ``pass`` and dropping the
    continuations — so the post-strip Python parses cleanly.

    These rewrites are valid only inside a notebook kernel — the smoke
    test cares about *Python-side* syntactic validity of the non-magic
    parts, not about magic-line acceptance."""
    out_lines: list[str] = []
    lines = source.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip()
        if stripped.startswith("%") or stripped.startswith("!"):
            indent = line[: len(line) - len(stripped)]
            out_lines.append(indent + "pass  # stripped magic/shell")
            # Swallow backslash-continued lines (whole magic command).
            while i < len(lines) and lines[i].rstrip().endswith("\\"):
                i += 1
            i += 1
        else:
            out_lines.append(line)
            i += 1
    return "\n".join(out_lines)


class NotebookStructureTest(unittest.TestCase):
    def setUp(self) -> None:
        self.nb = _load_notebook()

    def test_nbformat_version(self) -> None:
        self.assertEqual(self.nb.get("nbformat"), 4)
        self.assertGreaterEqual(self.nb.get("nbformat_minor", 0), 4)

    def test_has_kernelspec(self) -> None:
        metadata = self.nb.get("metadata", {})
        self.assertIn("kernelspec", metadata)
        self.assertEqual(metadata["kernelspec"].get("language"), "python")

    def test_cells_present_and_interleaved(self) -> None:
        cells = self.nb.get("cells", [])
        self.assertGreaterEqual(len(cells), 20, f"expected ≥ 20 cells, got {len(cells)}")
        code = sum(1 for c in cells if c.get("cell_type") == "code")
        md = sum(1 for c in cells if c.get("cell_type") == "markdown")
        self.assertGreaterEqual(code, 10, "notebook needs ≥ 10 code cells")
        self.assertGreaterEqual(md, 10, "notebook needs ≥ 10 markdown cells")

    def test_expected_headings_appear_in_order(self) -> None:
        md_sources = [_cell_source(c) for c in self.nb["cells"] if c.get("cell_type") == "markdown"]
        all_md = "\n".join(md_sources)
        last_pos = -1
        for heading in EXPECTED_MARKDOWN_HEADINGS:
            pos = all_md.find(heading)
            self.assertGreaterEqual(
                pos,
                0,
                f"missing expected heading in notebook: {heading!r}",
            )
            self.assertGreater(
                pos,
                last_pos,
                f"heading out of order: {heading!r} appears before a prior expected heading",
            )
            last_pos = pos


class CodeCellsSyntaxTest(unittest.TestCase):
    def test_every_code_cell_parses_after_magic_strip(self) -> None:
        nb = _load_notebook()
        failures: list[tuple[int, str]] = []
        for i, cell in enumerate(nb.get("cells", [])):
            if cell.get("cell_type") != "code":
                continue
            source = _strip_jupyter_magics(_cell_source(cell))
            try:
                ast.parse(source)
            except SyntaxError as exc:
                failures.append((i, str(exc)))
        self.assertFalse(
            failures,
            f"code cells with Python syntax errors after magic strip: {failures}",
        )

    def test_first_three_code_cells_run_offline(self) -> None:
        """Cells 1-3 (install / GPU probe / repo mount) are the bootstrap
        path. After stripping magics they must contain *only* well-known
        offline-safe constructs — no surprise runtime imports that would
        crash before the test even gets to start.

        Specifically: cell 1 is the pip-install magic (whole body is
        magic); cell 2 imports torch + asserts CUDA; cell 3 does path
        detection + git clone. After stripping, all three must AST-parse
        and use only stdlib + ``torch`` (cell 2) / ``subprocess`` /
        ``sys`` / ``pathlib`` (cell 3) — nothing more exotic."""
        nb = _load_notebook()
        code_cells = [c for c in nb["cells"] if c.get("cell_type") == "code"]
        self.assertGreaterEqual(len(code_cells), 3)
        first_three = code_cells[:3]

        allowed_imports = {
            "ast",
            "os",
            "sys",
            "subprocess",
            "pathlib",
            "torch",
        }
        for idx, cell in enumerate(first_three):
            stripped = _strip_jupyter_magics(_cell_source(cell))
            tree = ast.parse(stripped)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        root = alias.name.split(".", 1)[0]
                        self.assertIn(
                            root,
                            allowed_imports,
                            f"cell {idx + 1} imports unexpected module: {alias.name}",
                        )
                elif isinstance(node, ast.ImportFrom) and node.module:
                    root = node.module.split(".", 1)[0]
                    self.assertIn(
                        root,
                        allowed_imports,
                        f"cell {idx + 1} from-imports unexpected module: {node.module}",
                    )


class NotebookHygieneTest(unittest.TestCase):
    def test_committed_with_empty_outputs(self) -> None:
        """Committed-with-outputs notebooks bloat git history and can
        leak data (HF tokens, sample API responses). Enforce empty
        outputs at commit time."""
        nb = _load_notebook()
        offenders: list[int] = []
        for i, cell in enumerate(nb.get("cells", [])):
            if cell.get("cell_type") != "code":
                continue
            outputs = cell.get("outputs") or []
            if outputs:
                offenders.append(i)
            execution_count = cell.get("execution_count")
            if execution_count is not None:
                offenders.append(i)
        self.assertFalse(
            offenders,
            f"code cells must commit with empty outputs + null "
            f"execution_count; offenders: {offenders}",
        )

    def test_hf_token_pulled_from_env_not_inlined(self) -> None:
        """The HF Hub push cell must read ``HF_TOKEN`` from
        ``os.environ`` — *never* a literal ``hf_...`` string. A
        regex catches a typical accidental inline."""
        nb = _load_notebook()
        full_text = "\n".join(_cell_source(c) for c in nb["cells"])
        # Match an actual literal hf_ token, not the docstring mention
        literal_tokens = re.findall(r'["\']hf_[A-Za-z0-9]{20,}["\']', full_text)
        self.assertEqual(
            literal_tokens,
            [],
            f"literal HF tokens found in notebook: {literal_tokens}",
        )
        # Positive assertion: the env var is the source of truth.
        self.assertIn("os.environ", full_text)
        self.assertIn("HF_TOKEN", full_text)


if __name__ == "__main__":
    unittest.main()
