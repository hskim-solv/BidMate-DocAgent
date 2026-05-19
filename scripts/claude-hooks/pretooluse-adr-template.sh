#!/usr/bin/env bash
# Claude Code PreToolUse hook for BidMate-DocAgent — ADR Verification template.
#
# Registered in `.claude/settings.json` with matcher `Edit|MultiEdit|Write`.
# Fires before Claude writes/edits a file. Refuses Write calls that create
# a *new* ADR file (``docs/adr/<NNNN>-*.md``) whose payload does not include
# the ``## Verification`` H2 section + at least one
# ``<!-- verifies-key: path:key -->`` marker.
#
# Why this exists (issue #826 Hook C / #866):
#   - ``scripts/_governance.py::lint_adr_verification`` already blocks the
#     same shape at pre-commit. But by the time pre-commit fires, the ADR
#     draft is fully written. The reject costs one round-trip + manual
#     re-edit + re-stage.
#   - This PreToolUse hook short-circuits at *write time* with the
#     template body inlined in stderr, so Claude amends in the same
#     turn it created the file.
#
# Scope (intentional narrowness):
#   - Only fires on Write payloads whose ``file_path`` matches the ADR
#     filename pattern AND whose target file does NOT yet exist (i.e.
#     genuine new ADRs, not edits to existing ones).
#   - Existing ADRs are grandfathered by the same convention as the
#     pre-commit lint (``--diff-filter=A`` only).
#   - Edit / MultiEdit on existing files: pass through. The pre-commit
#     lint is still the authoritative gate.
#
# Behavior:
#   - exit 0  : safe / not applicable / fail-open
#   - exit 2  : refuse the Write, print template + rationale to stderr
#
# Hook input (stdin, JSON):
#   { "tool_name": "Write",
#     "tool_input": { "file_path": "...", "content": "..." }, ... }

set -u

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

input=$(cat)

# Parse tool_name + file_path + content in one python pass so we don't
# pay JSON-decode three times. Empty defaults short-circuit downstream
# without error handling boilerplate.
parsed=$(printf '%s' "$input" | python3 -c '
import json, sys
try:
    d = json.loads(sys.stdin.read())
except Exception:
    sys.exit(0)
tool = d.get("tool_name", "")
ti = d.get("tool_input", {}) or {}
fp = ti.get("file_path", "") or ""
content = ti.get("content", "") or ""
# Print fp on line 1, tool on line 2, content length on line 3, then content.
# Content can have newlines, so put it last and pass through verbatim.
print(fp)
print(tool)
print(len(content))
sys.stdout.write(content)
' 2>/dev/null)

file_path=$(printf '%s' "$parsed" | sed -n '1p')
tool_name=$(printf '%s' "$parsed" | sed -n '2p')

# Fast path: not a Write tool — Edit / MultiEdit on existing files are
# the pre-commit lint's domain.
if [[ "$tool_name" != "Write" ]]; then
  exit 0
fi

# Fast path: not an ADR filename. Match either an absolute path containing
# ``docs/adr/<NNNN>-*.md`` or a repo-relative path starting with
# ``docs/adr/...``. The 4-digit prefix mirrors the established ADR
# numbering (``docs/adr/_template.md`` is intentionally excluded by the
# ``[0-9]{4}`` requirement).
if ! [[ "$file_path" =~ docs/adr/[0-9]{4}-[a-z0-9-]+\.md$ ]]; then
  exit 0
fi

# Fast path: file already exists → it's an edit/rewrite of an existing
# ADR. Out of scope (grandfathered, like the pre-commit lint).
if [[ -e "$file_path" ]]; then
  exit 0
fi

# Extract the content payload from the parsed multi-line blob. The first
# 3 lines are metadata; the rest is the file content.
content=$(printf '%s' "$parsed" | tail -n +4)

# Required markers (mirrors scripts/_governance.py::lint_adr_verification
# regexes verbatim — keep them in sync if either changes). We reuse the
# Python re module here so the whitespace tolerance is identical to the
# pre-commit lint (grep -E and the governance regex don't quite agree on
# ``[[:space:]]`` around the path:key separator).
checks=$(printf '%s' "$content" | python3 -c '
import re, sys
text = sys.stdin.read()
section_re = re.compile(r"^##\s+Verification\s*$", re.MULTILINE)
marker_re = re.compile(
    r"<!--\s*verifies-key:\s*([^\s:][^:]*?)\s*:\s*([^\s>][^>]*?)\s*-->"
)
print("section=" + ("yes" if section_re.search(text) else "no"))
print("marker=" + ("yes" if marker_re.search(text) else "no"))
' 2>/dev/null)

has_section="no"
has_marker="no"
case "$checks" in
  *"section=yes"*) has_section="yes" ;;
esac
case "$checks" in
  *"marker=yes"*) has_marker="yes" ;;
esac

if [[ "$has_section" == "yes" && "$has_marker" == "yes" ]]; then
  exit 0
fi

# Render block reason for the .hook-fires.log row.
missing=""
[[ "$has_section" == "no" ]] && missing="section"
[[ "$has_marker" == "no" ]] && missing="${missing:+${missing},}marker"

adr_basename=$(basename "$file_path")
# v2-5field telemetry (ADR 0060).
python3 "$REPO_ROOT/scripts/_governance.py" --emit-fire \
  --outcome blocked --hook adr-template --category missing-verification \
  --path "$adr_basename" --extra "missing=$missing" 2>/dev/null || true

cat >&2 <<EOF
⛔ Refusing Write of new ADR \`$adr_basename\`: missing Verification surface.

    Missing: $missing
    Required (mirrors scripts/_governance.py::lint_adr_verification):

      ## Verification

      <!-- verifies-key: <relative-path>:<key-substring> -->

    Why: ADRs without a machine-checkable claim degrade into Decision
    Theatre — the commitment is written down, then nothing measures
    whether it held. The marker creates a two-way circuit: the pre-commit
    lint walks each marker and confirms the key substring exists in the
    referenced file. Add the marker BEFORE this Write or the pre-commit
    lint will reject on commit anyway (with one extra round-trip).

    Examples of valid markers (existing accepted ADRs):

      <!-- verifies-key: scripts/_governance.py:LOAD_BEARING_PATHS -->
      <!-- verifies-key: rag_indexing.py:def write_index_json -->
      <!-- verifies-key: tests/test_governance.py:test_no_unlinked_adr_files_on_disk -->

    Template: docs/adr/_template.md
    Policy: ADR Verification surface (issue #793 B3 fix).
    Bypass: this is a PreToolUse hook — re-run Write with the surface
            included. If you genuinely have no machine-checkable claim,
            mark the ADR ``Status: Proposed (plan-only)`` and add a
            marker pointing at the plan document itself.
EOF
exit 2
