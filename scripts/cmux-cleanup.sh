#!/usr/bin/env bash
# cmux orphan workspace (tab) cleanup — close cmux workspaces whose worktree is
# gone (issue #1795, plan docs/plans/cmux-workspace-cleanup.md).
#
# Symmetric to .githooks/_pre-push-worktree-hygiene.sh (worktree hygiene, ADR
# 0096). worktree hygiene cleans the local worktree + branch; this cleans the
# cmux workspace (tab) that maps 1:1 to a worktree. When the worktree is gone
# (merged → ADR 0096 removed it) the tab is left behind and orphans accumulate.
#
# Runnable standalone:
#
#     bash scripts/cmux-cleanup.sh --dry-run    # candidates only, never closes
#     bash scripts/cmux-cleanup.sh              # actually close orphan tabs
#
# orphan判정 = "workspace 의 cwd 가 현존 git worktree 목록에 없다". The merge
# decision is NOT re-implemented — it is delegated to worktree presence
# (transitive trust of worktree hygiene's 4-signal merge confirmation).
#
# Three guards, all fail-safe toward NOT closing (close is irreversible — the
# tab + scrollback are permanently destroyed; information不足 always → skip):
#   ① self-skip       the running session's own workspace ($CMUX_WORKSPACE_ID).
#   ② active/focus    `cmux tree` markers active / [selected] / ◀here.
#   ③ live worktree   the workspace's cwd is still in `git worktree list`.
#
# Soft contract (like the pre-push sub-hooks): `set -u` but NOT `set -e`, and
# every branch ends in `exit 0`. This never blocks a session or a push.
#
# bash 3.2 compatible (macOS default): no associative arrays.

set -u

dry_run=0

for arg in "$@"; do
  case "$arg" in
    --dry-run) dry_run=1 ;;
    -h|--help)
      cat <<'EOF'
Usage:
  bash scripts/cmux-cleanup.sh --dry-run   # print orphan candidates only
  bash scripts/cmux-cleanup.sh             # close orphan cmux workspaces

Closes cmux workspaces (tabs) whose cwd is no longer a live git worktree
(merged → ADR 0096 removed the worktree, the tab was left behind). close is
irreversible (tab + scrollback gone), so run --dry-run first. Three guards
protect live work: self-skip, active/focus, and live-worktree. Any information
gap → skip (never close). Soft-warn only: exit 0 always.
EOF
      exit 0
      ;;
    *)
      printf 'cmux cleanup: unknown option: %s\n' "$arg" >&2
      ;;
  esac
done

# --- Step 1: cmux detect (soft skip) ---------------------------------------
# Resolve CMUX_BIN exactly like scripts/spawn_track_session.sh: env override >
# macOS app-bundle absolute path default. A bare `cmux` is not on PATH in
# subprocess / eval contexts (issue #1767 실측); tests override with a stub.
CMUX_BIN="${CMUX_BIN:-/Applications/cmux.app/Contents/Resources/bin/cmux}"

# `--version` non-zero (or binary missing) → cmux absent / headless (CI) → skip.
if ! "$CMUX_BIN" --version >/dev/null 2>&1; then
  printf 'cmux cleanup: cmux not available (%s) — skip.\n' "$CMUX_BIN" >&2
  exit 0
fi

# --- Step 2: self workspace (guard ①) --------------------------------------
# The current session's own workspace must never be a candidate. If unknown
# (run outside cmux, or env missing inside cmux) we cannot exclude ourselves,
# so conservatively skip everything (close is irreversible).
self_ws="${CMUX_WORKSPACE_ID:-}"
if [[ -z "$self_ws" ]]; then
  printf 'cmux cleanup: CMUX_WORKSPACE_ID unset — skip all (cannot self-exclude).\n' >&2
  exit 0
fi

# --- Step 3: active / focus workspaces (guard ②) ---------------------------
# `cmux tree` marks the focused / selected / here workspace. Collect every ref
# carrying one of those markers into protected_active. If the tree output is
# empty or unparseable we do not know what is active, so skip everything.
tree_out=$("$CMUX_BIN" tree 2>/dev/null || true)
if [[ -z "${tree_out//[$' \t\n']/}" ]]; then
  printf 'cmux cleanup: empty `cmux tree` output — skip all (active set unknown).\n' >&2
  exit 0
fi

# `cmux tree` puts the focus markers (`◀ active`, `◀ here`) on the pane/surface
# CHILD lines, not on the parent `workspace workspace:N` line — and the surface/
# pane number equals the workspace number (live 실측, issue #1795). So match any
# marked line, pull its (workspace|surface|pane):N token, and normalize it to
# workspace:N. We deliberately do NOT treat `[selected]`/`[focused]` as active:
# every pane carries them, so they would protect every workspace. The currently
# shown workspace (`*` in `workspace list`) is folded in as a marker in Step 5.
protected_active=$(printf '%s\n' "$tree_out" \
  | grep -E '◀[[:space:]]*(active|here)' \
  | grep -oE '(workspace|surface|pane):[0-9]+' \
  | sed -E 's/^(surface|pane):/workspace:/' \
  | sort -u)

# --- Step 4: live worktrees (guard ③ basis) --------------------------------
# `git worktree list --porcelain` → set of absolute paths, NORMALIZED. The
# normalization (symlink resolve + trailing-slash strip) must match the lsof
# cwd normalization below or a live tab is mis-flagged as orphan (the #1 cause
# of false-orphan → irreversible close). See _norm_path.
_norm_path() {
  # Resolve symlinks (/private/var ↔ /var on macOS) and strip a trailing slash.
  # Pure-shell fallback (strip trailing slash) if the path cannot be resolved
  # so a missing dir (a *gone* worktree's cwd) still normalizes consistently.
  local p="$1"
  local resolved=""
  if resolved=$(cd "$p" 2>/dev/null && pwd -P 2>/dev/null); then
    printf '%s' "$resolved"
    return 0
  fi
  # Path does not exist (gone worktree) — best-effort: resolve the deepest
  # existing parent, then re-append the missing tail, so a gone cwd under
  # /var/... and a live worktree under /var/... normalize the same way.
  local tail=""
  local cur="$p"
  while [[ -n "$cur" && "$cur" != "/" && "$cur" != "." ]]; do
    if resolved=$(cd "$cur" 2>/dev/null && pwd -P 2>/dev/null); then
      if [[ -n "$tail" ]]; then
        printf '%s/%s' "$resolved" "$tail"
      else
        printf '%s' "$resolved"
      fi
      return 0
    fi
    tail="${cur##*/}${tail:+/}${tail}"
    cur="${cur%/*}"
  done
  # Nothing resolvable — just strip a trailing slash.
  printf '%s' "${p%/}"
}

wt_porcelain=$(git worktree list --porcelain 2>/dev/null)
wt_rc=$?
# git absent / cwd not a repo / permission → non-zero or empty. We then cannot
# know which cwds are live worktrees, so EVERY cwd would look gone and every tab
# would be a false-orphan. Skip all — symmetric to the empty-`cmux tree` skip
# above (guard ③ fail-safe: 정보부족=보호). In normal `make cmux-cleanup` runs
# this never triggers (the repo always has at least the main worktree).
if [[ "$wt_rc" -ne 0 || -z "${wt_porcelain//[$' \t\n']/}" ]]; then
  printf 'cmux cleanup: `git worktree list` empty/failed — skip all (live set unknown).\n' >&2
  exit 0
fi

live_worktrees=""
while IFS= read -r line; do
  case "$line" in
    "worktree "*)
      wt_path="${line#worktree }"
      live_worktrees="${live_worktrees}$(_norm_path "$wt_path")"$'\n'
      ;;
  esac
done <<< "$wt_porcelain"

_is_live_worktree() {
  # 0 if the normalized cwd matches a normalized live worktree path.
  local cwd="$1"
  local wt
  while IFS= read -r wt; do
    [[ -n "$wt" ]] || continue
    [[ "$cwd" == "$wt" ]] && return 0
  done <<< "$live_worktrees"
  return 1
}

# --- Step 5: workspace → cwd mapping ---------------------------------------
# `cmux workspace list --id-format both` enumerates (ref, uuid, title).
# `cmux top --all --processes --format tsv` exposes each workspace's child PIDs.
# `lsof -a -p <pid> -d cwd -Fn` → the cwd; the `n`-prefixed line is the path.
ws_list=$("$CMUX_BIN" workspace list --id-format both 2>/dev/null || true)
top_out=$("$CMUX_BIN" top --all --processes --format tsv 2>/dev/null || true)

# Every workspace ref we know about, from the workspace list.
all_refs=$(printf '%s\n' "$ws_list" | grep -oE 'workspace:[0-9]+' | sort -u)

# Resolve OUR OWN workspace ref (guard ①). CMUX_WORKSPACE_ID may be a
# `workspace:N` ref OR a UUID — cmux 0.64 sets it to the UUID (live 실측, issue
# #1795). `workspace list --id-format both` prints `[*] workspace:N <uuid>
# <title> [markers]`, so when we hold a UUID we map it back to its ref by
# finding the row that contains the UUID. If we cannot resolve our own ref we
# cannot self-exclude → skip everything (self-close is the worst irreversible
# outcome; better to do nothing).
case "$self_ws" in
  workspace:*) self_ref="$self_ws" ;;
  *) self_ref=$(printf '%s\n' "$ws_list" | awk -v u="$self_ws" '
       # Match the UUID as a WHOLE TOKEN ($i == u), not a substring, so it is
       # never confused with a UUID embedded in another tab title. Print the
       # workspace:N ref found on the matched row.
       { has = 0; ref = ""
         for (i = 1; i <= NF; i++) {
           if ($i == u) has = 1
           if ($i ~ /^workspace:[0-9]+$/) ref = $i
         }
         if (has && ref != "") { print ref; exit }
       }
     ') ;;
esac
if [[ -z "$self_ref" ]]; then
  printf 'cmux cleanup: cannot resolve self workspace ref (CMUX_WORKSPACE_ID=%s) — skip all.\n' "$self_ws" >&2
  exit 0
fi

# The currently-shown workspace is marked `* workspace:N` in `workspace list`.
# Fold it into the active set (guard ②): the user is looking at it even when
# `cmux tree` carries no focus marker on its line.
selected_ref=$(printf '%s\n' "$ws_list" | awk '
  /^[[:space:]]*\*/ { for (i = 1; i <= NF; i++) if ($i ~ /^workspace:[0-9]+$/) { print $i; exit } }
')
if [[ -n "$selected_ref" ]]; then
  protected_active=$(printf '%s\n%s\n' "$protected_active" "$selected_ref" \
    | grep -E '^workspace:[0-9]+$' | sort -u)
fi

_pids_for_ws() {
  # Emit (newline-separated) the child PIDs that belong to this workspace ref.
  #
  # `cmux top --all --processes --format tsv` rows are 7 tab-separated columns:
  #   CPU% \t mem \t count \t TYPE \t ID \t PARENT \t label
  # A workspace's process is a TYPE=process row whose PARENT is the workspace's
  # surface:N or pane:N — and the surface/pane number equals the workspace
  # number (`surface:11` belongs to `workspace:11`). We therefore:
  #   • match the PARENT column by EXACT equality (==), not substring — so ref
  #     `workspace:1` can never capture `workspace:10`/`:11`… rows (the CRITICAL
  #     false-orphan vector: substring + single-digit glob cross-harvesting
  #     another workspace's PID, issue #1795 review);
  #   • read the PID only from the ID column ($5) of a process row — never from
  #     the mem ($2) / count ($3) columns, whose large/small integers would
  #     otherwise be mis-read as PIDs and resolve to unrelated processes' cwds.
  local ref="$1"
  local n="${ref#workspace:}"
  printf '%s\n' "$top_out" | awk -F'\t' \
    -v sp="surface:${n}" -v pn="pane:${n}" '
      $4 == "process" && ($6 == sp || $6 == pn) && $5 ~ /^[0-9]+$/ { print $5 }
    '
}

_pid_cwd() {
  # Resolve a PID's cwd via lsof -Fn; the path is the `n`-prefixed field line.
  # Empty (no such pid / permission) → caller treats as "cwd unknown".
  local pid="$1"
  lsof -a -p "$pid" -d cwd -Fn 2>/dev/null \
    | grep '^n' \
    | head -n1 \
    | sed 's/^n//'
}

# --- Step 6 + 7: combine guards, then dry-run / close ----------------------
closed=0
candidates=0

for ref in $all_refs; do
  # Guard ①: never the running session's own workspace (self_ref resolved from
  # CMUX_WORKSPACE_ID — possibly a UUID — in Step 5).
  [[ "$ref" == "$self_ref" ]] && continue
  # Guard ②: never an active / focused / selected workspace.
  if printf '%s\n' "$protected_active" | grep -qx "$ref"; then
    continue
  fi

  # Guard ③: resolve every child PID's cwd. Protect (skip) if ANY cwd is a live
  # worktree (conservative OR). Track whether we learned at least one cwd.
  knew_cwd=0
  protected_live=0
  gone_cwd=""
  for pid in $(_pids_for_ws "$ref"); do
    cwd=$(_pid_cwd "$pid")
    [[ -n "$cwd" ]] || continue
    knew_cwd=1
    ncwd=$(_norm_path "$cwd")
    # Protect if the cwd is a live worktree OR still exists as a directory.
    # An orphan is a worktree whose directory was REMOVED (merged → ADR 0096
    # deleted it). A cwd that still exists — a live worktree, a non-worktree tab
    # the user cd'd into (e.g. ~), or an lsof-reported stale-but-present path —
    # is never an orphan, so a present directory always protects.
    if _is_live_worktree "$ncwd" || [[ -d "$ncwd" ]]; then
      protected_live=1
      break
    fi
    gone_cwd="$ncwd"
  done

  # cwd unknown (no PID / lsof empty) → skip (guard ③ boundary 1: 정보부족=보호).
  if [[ "$knew_cwd" -eq 0 ]]; then
    printf 'cmux cleanup: %s cwd unknown — skip (no orphan judgment).\n' "$ref" >&2
    continue
  fi
  # Any live cwd → the tab's work is alive → protect.
  [[ "$protected_live" -eq 1 ]] && continue

  # Survived all three guards: every known cwd is gone → genuine orphan.
  candidates=$((candidates + 1))
  if [[ "$dry_run" -eq 1 ]]; then
    printf 'cmux cleanup: would close %s (cwd %s)\n' "$ref" "${gone_cwd:-?}" >&2
  else
    payload=$(printf '{"workspace_id":"%s"}' "$ref")
    if "$CMUX_BIN" rpc workspace.close "$payload" >/dev/null 2>&1; then
      closed=$((closed + 1))
      printf 'cmux cleanup: closed %s (cwd %s)\n' "$ref" "${gone_cwd:-?}" >&2
    else
      printf 'cmux cleanup: failed to close %s (continuing)\n' "$ref" >&2
    fi
  fi
done

if [[ "$dry_run" -eq 1 ]]; then
  printf 'cmux cleanup: %d orphan workspace(s) would be closed (dry-run).\n' "$candidates" >&2
else
  printf 'cmux cleanup: closed %d orphan workspace(s).\n' "$closed" >&2
fi

exit 0
