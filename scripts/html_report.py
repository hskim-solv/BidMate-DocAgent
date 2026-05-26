"""Small helpers for self-contained local HTML reports.

These helpers intentionally stay presentation-only: callers pass already
aggregate-safe values, and all public text cells are escaped at the boundary.
"""
from __future__ import annotations

from html import escape
from typing import Sequence


def html_text(value: object) -> str:
    """Escape text for HTML element content and attributes."""
    return escape(str(value), quote=True)


def _tone_class(tone: str) -> str:
    if tone in {"ok", "warn", "danger", "accent", "neutral"}:
        return tone
    return "neutral"


def render_badge(label: object, *, tone: str = "neutral") -> str:
    return (
        f'<span class="badge {_tone_class(tone)}">'
        f"{html_text(label)}</span>"
    )


def render_status_card(
    label: object,
    value: object,
    *,
    detail: object = "",
    tone: str = "neutral",
) -> str:
    detail_html = f"<small>{html_text(detail)}</small>" if detail else ""
    return (
        f'<article class="status-card {_tone_class(tone)}">'
        f"<span>{html_text(label)}</span>"
        f"<strong>{html_text(value)}</strong>"
        f"{detail_html}</article>"
    )


def render_table(
    headers: Sequence[object],
    rows: Sequence[Sequence[object]],
    *,
    empty_message: object = "No rows",
) -> str:
    header_html = "".join(f"<th>{html_text(header)}</th>" for header in headers)
    if not rows:
        body_html = (
            f'<tr><td class="empty" colspan="{len(headers)}">'
            f"{html_text(empty_message)}</td></tr>"
        )
    else:
        body_html = "\n".join(
            "<tr>"
            + "".join(f"<td>{html_text(cell)}</td>" for cell in row)
            + "</tr>"
            for row in rows
        )
    return (
        "<table>"
        f"<thead><tr>{header_html}</tr></thead>"
        f"<tbody>{body_html}</tbody>"
        "</table>"
    )


def render_document(
    *,
    title: object,
    subtitle: object,
    body: str,
    footer: object,
) -> str:
    """Wrap prebuilt report sections in a deterministic, dependency-free shell."""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html_text(title)}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --text: #1d2430;
      --muted: #5b6575;
      --line: #d9dee7;
      --ok: #176f4d;
      --warn: #986400;
      --danger: #b42318;
      --accent: #2459a7;
      --neutral: #667085;
      --table-stripe: #fbfcfe;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    main {{
      max-width: 1120px;
      margin: 0 auto;
      padding: 32px 20px 48px;
    }}
    header {{
      margin-bottom: 24px;
    }}
    h1, h2, h3, p {{ margin: 0; }}
    h1 {{ font-size: 30px; line-height: 1.15; }}
    h2 {{ font-size: 18px; margin-bottom: 12px; }}
    h3 {{ font-size: 16px; margin: 18px 0 8px; }}
    .subtitle {{ color: var(--muted); margin-top: 6px; max-width: 780px; }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 20px;
    }}
    .status-card, .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 1px 2px rgba(18, 24, 31, 0.04);
    }}
    .status-card {{
      min-height: 96px;
      padding: 14px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      border-top: 4px solid var(--neutral);
    }}
    .status-card span {{
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
    }}
    .status-card strong {{ font-size: 20px; overflow-wrap: anywhere; }}
    .status-card small {{ color: var(--muted); overflow-wrap: anywhere; }}
    .ok {{ border-top-color: var(--ok); }}
    .warn {{ border-top-color: var(--warn); }}
    .danger {{ border-top-color: var(--danger); }}
    .accent {{ border-top-color: var(--accent); }}
    .panel {{ padding: 18px; margin-bottom: 16px; }}
    table {{
      width: 100%;
      border-collapse: collapse;
    }}
    th, td {{
      text-align: left;
      border-top: 1px solid var(--line);
      padding: 10px 8px;
      vertical-align: top;
    }}
    tbody tr:nth-child(even) {{ background: var(--table-stripe); }}
    thead th {{
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
    }}
    code {{
      background: #eef1f5;
      border-radius: 5px;
      padding: 2px 5px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 0.92em;
    }}
    .badge {{
      display: inline-block;
      border: 1px solid var(--line);
      border-left: 4px solid var(--neutral);
      border-radius: 6px;
      padding: 3px 7px;
      background: #fff;
      white-space: nowrap;
    }}
    .badge.ok {{ border-left-color: var(--ok); }}
    .badge.warn {{ border-left-color: var(--warn); }}
    .badge.danger {{ border-left-color: var(--danger); }}
    .badge.accent {{ border-left-color: var(--accent); }}
    .empty {{ color: var(--muted); text-align: center; }}
    .note {{ color: var(--muted); margin-bottom: 12px; }}
    .stack {{
      display: grid;
      gap: 16px;
    }}
    footer {{ color: var(--muted); margin-top: 18px; font-size: 13px; }}
    @media (max-width: 900px) {{
      .grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    }}
    @media (max-width: 560px) {{
      main {{ padding: 22px 12px 36px; }}
      .grid {{ grid-template-columns: 1fr; }}
      th, td {{ padding: 8px 4px; }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>{html_text(title)}</h1>
      <p class="subtitle">{html_text(subtitle)}</p>
    </header>
    {body}
    <footer>{html_text(footer)}</footer>
  </main>
</body>
</html>
"""
