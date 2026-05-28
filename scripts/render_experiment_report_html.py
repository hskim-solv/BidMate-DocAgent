"""Auto-render experiment-result HTML pairs alongside aggregate/markdown reports.

CLI surface (issue #1661):

    python3 scripts/render_experiment_report_html.py --auto-scan
    python3 scripts/render_experiment_report_html.py --input reports/real100_v2/baseline.aggregate.json
    python3 scripts/render_experiment_report_html.py --check --auto-scan --quiet

Boundary: aggregate-only. Denylist (filename / path / JSON keys / values) is
delegated to scripts/_governance.py so the gate matches the existing ADR 0005
pre-commit scanner exactly. No raw_results.json, no data_list*.csv,
no data/private/**, no PHASE4_PRIVATE_KEYS, no PRIVATE_REDACTED_FORBIDDEN_KEYS,
no Hangul values in eval aggregates.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

# Reuse: presentation-only HTML helpers (zero deps, escapes at boundary).
from html_report import (  # noqa: E402  (sys.path injection above)
    html_text,
    render_badge,
    render_document,
    render_status_card,
    render_table,
)

# Reuse: same boundary functions the pre-commit ADR 0005 scanner uses.
import _governance as _gov  # noqa: E402

ALLOW_AGGREGATE_SUFFIX = ".aggregate.json"
ALLOW_EVAL_SUMMARY = "eval_summary.json"
ALLOW_REPORT_MD = "REPORT.md"

DENY_FILENAMES = frozenset({"raw_results.json"})
DENY_FILENAME_PREFIXES = ("data_list",)
DENY_PATH_SEGMENTS = ("data/private/", "outputs/")

VALUE_TRUNCATE_CHARS = 2000
MAX_INPUT_BYTES = 5 * 1024 * 1024  # 5 MB skip gate
HUMAN_KEY_BLOCKLIST = frozenset(
    {
        # Defensive extra layer above _governance.PRIVATE_REDACTED_FORBIDDEN_KEYS:
        # any of these in a top-level aggregate JSON means the value almost
        # certainly leaks private RFP content rather than aggregate metrics.
        "chunk_text",
        "raw_text",
        "answer_text",
    }
)

EXIT_OK = 0
EXIT_STALE = 1  # used only by --check to mark "needs render"
EXIT_DENIED = 2
EXIT_BAD_INPUT = 3


# ---------------------------------------------------------------------------
# Discovery + stale detection


def _iter_candidates(reports_root: Path) -> Iterable[Path]:
    """Yield every allowlisted experiment artifact under reports/."""
    if not reports_root.is_dir():
        return
    for path in reports_root.rglob("*"):
        if not path.is_file():
            continue
        if _is_denied_path(path):
            continue
        if path.name.endswith(ALLOW_AGGREGATE_SUFFIX):
            yield path
        elif path.name == ALLOW_EVAL_SUMMARY:
            yield path
        elif path.name == ALLOW_REPORT_MD and "retrieval" in path.parts:
            yield path


def _is_denied_path(path: Path) -> bool:
    name = path.name
    if name in DENY_FILENAMES:
        return True
    if any(name.startswith(prefix) for prefix in DENY_FILENAME_PREFIXES):
        return True
    posix = path.as_posix()
    return any(seg in posix for seg in DENY_PATH_SEGMENTS)


def _paired_html(input_path: Path) -> Path:
    if input_path.name.endswith(ALLOW_AGGREGATE_SUFFIX):
        stem = input_path.name[: -len(".json")]
        return input_path.with_name(f"{stem}.html")
    if input_path.name == ALLOW_EVAL_SUMMARY:
        return input_path.with_name("eval_summary.html")
    if input_path.name == ALLOW_REPORT_MD:
        return input_path.with_name("REPORT.html")
    return input_path.with_suffix(".html")


def stale_pairs(reports_root: Path) -> list[Path]:
    """Return inputs whose paired .html is missing or older than the source."""
    out: list[Path] = []
    for src in _iter_candidates(reports_root):
        dst = _paired_html(src)
        if not dst.exists() or dst.stat().st_mtime < src.stat().st_mtime:
            out.append(src)
    return sorted(out)


# ---------------------------------------------------------------------------
# Boundary checks (delegated to _governance.py)


def _violates_boundary(input_path: Path, payload: object) -> str | None:
    """Return None if safe, otherwise a short reason string.

    Scoping mirrors scripts/_governance.py exactly so we never raise a
    false-positive that the pre-commit ADR 0005 scanner wouldn't also raise:

    - filename/path denylist applies everywhere
    - HUMAN_KEY_BLOCKLIST (chunk_text / raw_text / answer_text) applies
      everywhere — these never belong in an aggregate
    - find_private_keys (PHASE4_PRIVATE_KEYS) applies only under
      reports/retrieval/phase4*
    - find_eval_private_text (Hangul / colon-keys) applies only under
      EVAL_PRIVACY_ARTIFACT_GLOBS (reports/retrieval, real100, real100_v2)
    - find_redacted_summary_forbidden_fields applies only to the single
      redacted summary path, which is NOT in our allowlist anyway
    """
    if _is_denied_path(input_path):
        return f"denied filename/path: {input_path.name}"
    if not isinstance(payload, dict):
        return None
    for key in payload:
        if key in HUMAN_KEY_BLOCKLIST:
            return f"top-level key '{key}' suggests raw content, not aggregate"
    posix = input_path.as_posix()
    if "reports/retrieval/phase4" in posix:
        phase4_hits = _gov.find_private_keys(payload)
        if phase4_hits:
            return f"PHASE4_PRIVATE_KEYS hit: {sorted(phase4_hits)}"
    if any(g in posix for g in _gov.EVAL_PRIVACY_ARTIFACT_GLOBS):
        private_text = _gov.find_eval_private_text(payload)
        if private_text:
            return f"eval-privacy text hit: {sorted(private_text)}"
    return None


# ---------------------------------------------------------------------------
# Rendering


def _truncate(value: object) -> str:
    s = str(value)
    if len(s) > VALUE_TRUNCATE_CHARS:
        return s[:VALUE_TRUNCATE_CHARS] + f"… [truncated {len(s)} chars]"
    return s


def _tone_for_metric(name: str, mean: float) -> str:
    name_l = name.lower()
    if "accuracy" in name_l or "recall" in name_l or "precision" in name_l:
        if mean >= 0.7:
            return "ok"
        if mean >= 0.4:
            return "warn"
        return "danger"
    return "neutral"


def _render_ci_table(ci: dict) -> str:
    rows = []
    for metric, stats in sorted(ci.items()):
        if not isinstance(stats, dict):
            continue
        mean = stats.get("mean")
        lo = stats.get("ci_lo")
        hi = stats.get("ci_hi")
        n = stats.get("n")
        mean_str = f"{mean:.4f}" if isinstance(mean, (int, float)) else _truncate(mean)
        ci_str = (
            f"[{lo:.4f}, {hi:.4f}]"
            if isinstance(lo, (int, float)) and isinstance(hi, (int, float))
            else "—"
        )
        tone = _tone_for_metric(metric, mean) if isinstance(mean, (int, float)) else "neutral"
        rows.append((metric, render_badge(mean_str, tone=tone), ci_str, n if n is not None else "—"))
    return render_table(
        ["metric", "mean", "95% CI", "n"],
        [(html_text(r[0]), r[1], html_text(r[2]), html_text(r[3])) for r in rows],
        empty_message="no CI block",
    )


def _render_kv_grid(d: dict) -> str:
    cards: list[str] = []
    for key, value in d.items():
        if isinstance(value, (dict, list)):
            continue
        cards.append(render_status_card(key, _truncate(value)))
    if not cards:
        return ""
    return f'<section class="panel"><div class="grid">{"".join(cards)}</div></section>'


def _render_generic_table(d: dict) -> str:
    rows = [(html_text(k), html_text(_truncate(v))) for k, v in sorted(d.items())]
    return render_table(["key", "value"], rows, empty_message="empty")


def _render_aggregate_body(payload: dict) -> str:
    sections: list[str] = []

    # Top-level scalars (e.g. ablation_full mean values).
    sections.append(_render_kv_grid(payload))

    for key in sorted(payload):
        value = payload[key]
        if not isinstance(value, dict):
            continue
        if key == "ci":
            sections.append('<section class="panel"><h2>CI (95%)</h2>')
            sections.append(_render_ci_table(value))
            sections.append("</section>")
            continue
        scalars = {k: v for k, v in value.items() if not isinstance(v, (dict, list))}
        nested_ci = value.get("ci") if isinstance(value.get("ci"), dict) else None
        nested_outcomes = (
            value.get("abstention_outcomes")
            if isinstance(value.get("abstention_outcomes"), dict)
            else None
        )
        sections.append(f'<section class="panel"><h2>{html_text(key)}</h2>')
        if scalars:
            sections.append(_render_kv_grid(scalars))
        if nested_outcomes:
            sections.append("<h3>abstention outcomes</h3>")
            sections.append(_render_generic_table(nested_outcomes))
        if nested_ci:
            sections.append("<h3>CI (95%)</h3>")
            sections.append(_render_ci_table(nested_ci))
        sections.append("</section>")

    return "\n".join(s for s in sections if s)


def _render_markdown_body(text: str) -> tuple[str, str]:
    """Return (title, body_html). Plaintext-escape; no library."""
    title = "REPORT.md"
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            title = stripped[2:].strip() or title
            break
    return title, (
        '<section class="panel">'
        f'<pre class="markdown" style="white-space:pre-wrap;overflow-wrap:anywhere;'
        f'font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;'
        f'font-size:13px;">{html_text(text)}</pre>'
        "</section>"
    )


def _rel_path(p: Path) -> Path:
    try:
        return p.relative_to(REPO_ROOT) if p.is_absolute() else p
    except ValueError:
        return p


def render_html(input_path: Path) -> str:
    if input_path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError(f"input exceeds {MAX_INPUT_BYTES} bytes: {input_path}")
    footer = (
        f"rendered {_dt.datetime.now(_dt.timezone.utc).isoformat(timespec='seconds')} "
        f"by scripts/render_experiment_report_html.py — aggregate-only (ADR 0005)"
    )
    subtitle = f"source: {_rel_path(input_path)}"
    if input_path.suffix == ".json":
        payload = json.loads(input_path.read_text(encoding="utf-8"))
        violation = _violates_boundary(input_path, payload)
        if violation:
            raise PermissionError(violation)
        if not isinstance(payload, dict):
            raise ValueError(f"top-level JSON must be dict, got {type(payload).__name__}")
        body = _render_aggregate_body(payload)
        return render_document(
            title=f"{input_path.name}",
            subtitle=subtitle,
            body=body,
            footer=footer,
        )
    text = input_path.read_text(encoding="utf-8")
    title, body = _render_markdown_body(text)
    return render_document(
        title=title,
        subtitle=subtitle,
        body=body,
        footer=footer,
    )


def _atomic_write(dst: Path, content: str) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".html-render-", dir=str(dst.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp, dst)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# CLI


def _render_one(input_path: Path, *, quiet: bool) -> int:
    try:
        html = render_html(input_path)
    except PermissionError as exc:
        print(f"DENIED {input_path}: {exc}", file=sys.stderr)
        return EXIT_DENIED
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"SKIP {input_path}: {exc}", file=sys.stderr)
        return EXIT_BAD_INPUT
    dst = _paired_html(input_path)
    _atomic_write(dst, html)
    if not quiet:
        print(f"rendered {_rel_path(dst)}")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="Single allowlisted artifact")
    parser.add_argument(
        "--auto-scan",
        action="store_true",
        help="Walk reports/ and render every stale or missing pair",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero (1) if any pair is stale; do not render",
    )
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument(
        "--reports-root", type=Path, default=REPO_ROOT / "reports",
        help="Override reports root (mainly for tests)",
    )
    args = parser.parse_args(argv)

    if not args.input and not args.auto_scan:
        parser.error("one of --input or --auto-scan is required")

    if args.input:
        if not args.input.exists():
            print(f"input not found: {args.input}", file=sys.stderr)
            return EXIT_BAD_INPUT
        if _is_denied_path(args.input):
            print(
                f"DENIED {args.input}: filename/path denied by ADR 0005 boundary",
                file=sys.stderr,
            )
            return EXIT_DENIED
        return _render_one(args.input, quiet=args.quiet)

    stale = stale_pairs(args.reports_root)
    if args.check:
        if stale:
            if not args.quiet:
                print(f"{len(stale)} stale HTML pair(s)")
                for src in stale:
                    print(f"  stale: {_rel_path(src)}")
            return EXIT_STALE
        if not args.quiet:
            print("0 stale HTML pairs")
        return EXIT_OK

    if not stale:
        if not args.quiet:
            print("0 stale HTML pairs — nothing to render")
        return EXIT_OK

    rendered = 0
    failed = 0
    for src in stale:
        rc = _render_one(src, quiet=True)
        if rc == EXIT_OK:
            rendered += 1
        else:
            failed += 1
    summary = f"rendered {rendered} HTML reports"
    if failed:
        summary += f" ({failed} failed — see stderr)"
    if not args.quiet:
        print(summary)
    return EXIT_OK if failed == 0 else EXIT_BAD_INPUT


if __name__ == "__main__":
    sys.exit(main())
