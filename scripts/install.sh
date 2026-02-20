#!/usr/bin/env bash
set -euo pipefail

# minion-comms installer
# Usage: curl -sSL https://raw.githubusercontent.com/ai-janitor/minion-commsv2/main/scripts/install.sh | bash

# ── Configuration ─────────────────────────────────────────────────────────────

REPO="https://github.com/ai-janitor/minion-commsv2.git"
TOOL_NAME="minion"
RUNTIME_DIR="$HOME/.minion_work"
DOCS_BASE_URL="https://raw.githubusercontent.com/ai-janitor/minion-commsv2/main/docs"

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

# ── Step 2: Write discovery marker ───────────────────────────────────────────

mkdir -p "${RUNTIME_DIR}"

MINION_PATH="$(command -v "${TOOL_NAME}" 2>/dev/null || echo "unknown")"
MINION_VERSION="$("${TOOL_NAME}" --version 2>/dev/null | head -1 || echo "unknown")"
cat > "${RUNTIME_DIR}/INSTALLED" <<MARKER
cli=${MINION_PATH}
version=${MINION_VERSION}
docs=${RUNTIME_DIR}/docs/
installed=$(date -u +%Y-%m-%dT%H:%M:%SZ)
MARKER

ok "Discovery marker written to ${RUNTIME_DIR}/INSTALLED"

# ── Step 3: Deploy protocol docs ─────────────────────────────────────────────

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
