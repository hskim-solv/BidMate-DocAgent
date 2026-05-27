from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_smoke_real_exposes_chunking_strategy_without_changing_default() -> None:
    script = (ROOT / "scripts" / "smoke_real.sh").read_text(encoding="utf-8")

    assert 'CHUNKING_STRATEGY="${CHUNKING_STRATEGY:-fixed}"' in script
    assert '--chunking_strategy "$CHUNKING_STRATEGY"' in script


def test_smoke_real_can_pass_hwp_pdf_artifact_dir_for_reuse() -> None:
    script = (ROOT / "scripts" / "smoke_real.sh").read_text(encoding="utf-8")

    assert 'HWP_PDF_ARTIFACT_DIR="${HWP_PDF_ARTIFACT_DIR:-}"' in script
    assert 'HWP_PDF_ARTIFACT_ARGS=(--hwp_pdf_artifact_dir "$HWP_PDF_ARTIFACT_DIR")' in script
    assert '"${HWP_PDF_ARTIFACT_ARGS[@]+"${HWP_PDF_ARTIFACT_ARGS[@]}"}"' in script


def test_makefile_has_isolated_page_aware_real_eval_target() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "real-eval-page-aware:" in makefile
    assert "CHUNKING_STRATEGY=section" in makefile
    assert "BIDMATE_HWP_PDF_ARTIFACT_REUSE=1" in makefile
    assert "REAL_EVAL_INDEX_DIR=data/index/real100_pageaware" in makefile


def test_legacy_real_eval_targets_are_disabled() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "real-eval:" in makefile
    assert "real-eval-minilm:" in makefile
    assert "real-eval-semantic:" in makefile
    assert "legacy real100/v1 make real-eval is disabled" in makefile
    assert "legacy real100_minilm/v1 target is disabled" in makefile
    assert "legacy real100_m3/v1 target is disabled" in makefile


def test_makefile_has_real100_v2_check_targets_without_rebuild() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "real-eval-v2-inventory:" in makefile
    assert "real-eval-v2-check:" in makefile
    assert "real-eval-v2-guard:" in makefile
    assert "REAL100_V2_CONFIG ?= data/private/real100_v2/real_config_v2.local.yaml" in makefile
    assert "REAL100_V2_INDEX_DIR ?= data/index/real100_v2" in makefile
    assert "REAL100_V2_REPORT_DIR ?= reports/real100_v2" in makefile
    assert "bash scripts/smoke_real.sh" not in makefile.split("real-eval-v2-check:", 1)[1].split("real-eval-v2-guard:", 1)[0]


def test_smoke_real_comment_separates_minilm_and_bge_m3_targets() -> None:
    script = (ROOT / "scripts" / "smoke_real.sh").read_text(encoding="utf-8")

    assert "`make real-eval-minilm` for the named MiniLM baseline" in script
    assert "`make real-eval-semantic` for the BGE-M3 comparison" in script
