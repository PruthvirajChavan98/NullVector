#!/usr/bin/env bash
set -euo pipefail

echo "[preflight] checking codex CLI..."
# Non-interactive shells may not inherit the npm global bin path.
if ! command -v codex >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
  NPM_PREFIX="$(npm config get prefix 2>/dev/null || true)"
  if [[ -n "${NPM_PREFIX}" && -x "${NPM_PREFIX}/bin/codex" ]]; then
    export PATH="${NPM_PREFIX}/bin:${PATH}"
  fi
fi

if ! command -v codex >/dev/null 2>&1; then
  echo "ERROR: codex CLI is not installed or not on PATH."
  exit 1
fi

CODEX_BIN="$(command -v codex)"

echo "[preflight] checking MCP configuration..."
MCP_LIST="$("${CODEX_BIN}" mcp list 2>&1 || true)"
echo "$MCP_LIST"

if ! printf '%s\n' "$MCP_LIST" | grep -Eqi 'sequential[- ]?thinking|sequentialthinking'; then
  echo "ERROR: required MCP server 'sequential-thinking' is not configured."
  exit 1
fi

cat <<'MSG'
[preflight] NOTE:
- Repository policy requires sequential-thinking MCP for non-trivial tasks.
- Repository policy requires web search for latest/current/external information.
- If this Codex session does not have web search enabled, the agent must stop and report a blocker.
MSG

echo "[preflight] passed."
