#!/usr/bin/env bash
set -euo pipefail

# minion-comms installer
# Usage: curl -sSL https://raw.githubusercontent.com/hungtrd/minion-commsv2/main/scripts/install.sh | bash

# ── Configuration ─────────────────────────────────────────────────────────────

REPO="https://github.com/hungtrd/minion-commsv2.git"
TOOL_NAME="minion"
RUNTIME_DIR="$HOME/.minion-comms"
DOCS_BASE_URL="https://raw.githubusercontent.com/hungtrd/minion-commsv2/main/docs"

# ── Output helpers ────────────────────────────────────────────────────────────

info()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok()    { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m==>\033[0m %s\n' "$*"; }
die()   { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

# ── Step 1: Install the package ───────────────────────────────────────────────

info "Installing ${TOOL_NAME}..."

if command -v pipx &>/dev/null; then
    info "Using pipx (isolated environment)"
    pipx install "git+${REPO}" --force 2>/dev/null \
        || pipx install "git+${REPO}" 2>/dev/null \
        || die "pipx install failed."
elif command -v uv &>/dev/null; then
    info "Using uv"
    uv tool install "git+${REPO}" --force 2>/dev/null \
        || uv tool install "git+${REPO}" 2>/dev/null \
        || die "uv tool install failed."
elif command -v pip &>/dev/null; then
    warn "pipx/uv not found — falling back to pip"
    pip install "git+${REPO}" --user --break-system-packages 2>/dev/null \
        || pip install "git+${REPO}" --user 2>/dev/null \
        || pip install "git+${REPO}" 2>/dev/null \
        || die "pip install failed. Install pipx: python3 -m pip install --user pipx"
else
    die "No Python package manager found. Install pipx: https://pipx.pypa.io"
fi

if ! command -v "${TOOL_NAME}" &>/dev/null; then
    warn "${TOOL_NAME} not found on PATH. Add ~/.local/bin to PATH:"
    warn '  export PATH="$HOME/.local/bin:$PATH"'
fi

# ── Step 2: Deploy protocol docs ─────────────────────────────────────────────

info "Deploying protocol docs to ${RUNTIME_DIR}/docs/..."

mkdir -p "${RUNTIME_DIR}/docs"

DOCS=(
    "protocol-common.md"
    "protocol-lead.md"
    "protocol-coder.md"
    "protocol-builder.md"
    "protocol-oracle.md"
    "protocol-recon.md"
)

for doc in "${DOCS[@]}"; do
    curl -sSfL "${DOCS_BASE_URL}/${doc}" -o "${RUNTIME_DIR}/docs/${doc}" \
        || warn "Failed to download ${doc}"
done

ok "Protocol docs deployed to ${RUNTIME_DIR}/docs/"

# ── Step 3: Configure MCP (optional wrapper) ─────────────────────────────────

if command -v claude &>/dev/null; then
    info "Configuring MCP via claude CLI..."
    if claude mcp list 2>/dev/null | grep -q "minion-comms"; then
        info "minion-comms already configured in Claude Code — skipping"
    else
        claude mcp add --scope user minion-comms -- minion mcp-serve 2>/dev/null \
            || warn "MCP auto-config failed. Run manually: claude mcp add --scope user minion-comms -- minion mcp-serve"
    fi
else
    add_mcp_entry() {
        local config="$1" name="$2" cmd="$3"
        shift 3
        local args=("$@")
        if [ -f "$config" ] && grep -q "\"${name}\"" "$config" 2>/dev/null; then
            info "${name} already in ${config} — skipping"
            return
        fi
        if command -v python3 &>/dev/null; then
            python3 -c "
import json, os, sys
p, n, c = sys.argv[1], sys.argv[2], sys.argv[3]
a = sys.argv[4:]
d = json.load(open(p)) if os.path.isfile(p) and os.path.getsize(p) > 0 else {}
d.setdefault('mcpServers', {})[n] = {'type': 'stdio', 'command': c, 'args': a}
json.dump(d, open(p, 'w'), indent=2)
" "$config" "$name" "$cmd" "${args[@]}"
            ok "Added ${name} to ${config}"
        elif command -v jq &>/dev/null; then
            if [ -f "$config" ] && [ -s "$config" ]; then
                jq --arg n "$name" --arg c "$cmd" --argjson a "$(printf '%s\n' "${args[@]}" | jq -R . | jq -s .)" \
                    '.mcpServers[$n] = {"type": "stdio", "command": $c, "args": $a}' \
                    "$config" > "${config}.tmp" && mv "${config}.tmp" "$config"
            else
                jq -n --arg n "$name" --arg c "$cmd" --argjson a "$(printf '%s\n' "${args[@]}" | jq -R . | jq -s .)" \
                    '{mcpServers: {($n): {type: "stdio", command: $c, args: $a}}}' > "$config"
            fi
            ok "Added ${name} to ${config}"
        else
            warn "Run: claude mcp add --scope user minion-comms -- minion mcp-serve"
        fi
    }

    add_mcp_entry "$HOME/.claude.json" "minion-comms" "minion" "mcp-serve"
fi

# ── Done ──────────────────────────────────────────────────────────────────────

echo ""
ok "${TOOL_NAME} installed!"
echo ""
echo "  CLI:          ${TOOL_NAME} --help"
echo "  Protocol docs: ${RUNTIME_DIR}/docs/"
echo ""
echo "  Quick start:"
echo "    export MINION_CLASS=lead"
echo "    ${TOOL_NAME} register --name gru --class lead"
echo "    ${TOOL_NAME} set-battle-plan --agent gru --plan 'Take over the world'"
echo ""
