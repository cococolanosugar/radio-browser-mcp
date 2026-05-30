#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────
# radio-browser-mcp one-click installer (macOS / Linux)
# Installs the package + configures Claude Code settings
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETTINGS_FILE="$HOME/.claude/settings.json"
CLAUDE_JSON="$HOME/.claude.json"

echo -e "${CYAN}♫ radio-browser-mcp installer${NC}"
echo

# ─── Check Python ───────────────────────────────────────────────────────

PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        PYTHON="$cmd"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo -e "${RED}Error: Python not found${NC}"
    echo "Install Python 3.10+ first"
    exit 1
fi

PY_VER=$($PYTHON -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo -e "  Python:    ${GREEN}$PYTHON $PY_VER${NC}"

# ─── Install package ────────────────────────────────────────────────────

echo -e "\n${CYAN}Installing radio-browser-mcp...${NC}"

cd "$SCRIPT_DIR"

# Detect installer (pip)
INSTALLER=""
if command -v pip3 &>/dev/null; then
    INSTALLER="pip3"
elif command -v pip &>/dev/null; then
    INSTALLER="pip"
else
    INSTALLER="$PYTHON -m pip"
fi

echo -e "  Installer: ${GREEN}$INSTALLER${NC}"

# Install
if $INSTALLER install -e . --quiet 2>/dev/null; then
    echo -e "  ${GREEN}✓ Installed (editable)${NC}"
elif $INSTALLER install . --quiet 2>/dev/null; then
    echo -e "  ${GREEN}✓ Installed${NC}"
elif $INSTALLER install -e . --user --quiet 2>/dev/null; then
    echo -e "  ${GREEN}✓ Installed (user)${NC}"
else
    echo -e "${RED}Error: install failed${NC}"
    echo "Try: $PYTHON -m pip install -e $SCRIPT_DIR"
    exit 1
fi
CMD="radio-browser-mcp"

# Verify command exists
if ! command -v "$CMD" &>/dev/null 2>&1 && [ ! -x "$CMD" ]; then
    CMD="$PYTHON -m radio_browser_mcp.server"
    echo -e "  ${YELLOW}Note: using '$CMD'${NC}"
fi

# ─── Configure Claude Code ──────────────────────────────────────────────

echo -e "\n${CYAN}Configuring Claude Code...${NC}"

mkdir -p "$(dirname "$SETTINGS_FILE")"

$PYTHON << PYEOF
import json
import shutil
from pathlib import Path

settings_file = Path("$SETTINGS_FILE")
claude_json = Path("$CLAUDE_JSON")
cmd = "$CMD"

# Build env with PATH
env = {"PYTHONIOENCODING": "utf-8"}
mpv_bin = shutil.which("mpv")
if mpv_bin:
    import os
    mpv_dir = str(Path(mpv_bin).parent)
    env["PATH"] = mpv_dir + os.pathsep + os.environ.get("PATH", "")
    print(f"  ✓ mpv path: {mpv_dir}")

# Build MCP server entry
parts = cmd.split()
mcp_entry = {
    "type": "stdio",
    "command": parts[0],
    "args": parts[1:],
    "env": env
}

# --- MCP servers go in ~/.claude.json ---
if claude_json.exists():
    try:
        claude_data = json.loads(claude_json.read_text())
    except json.JSONDecodeError:
        claude_data = {}
else:
    claude_data = {}

claude_data.setdefault("mcpServers", {})["radio"] = mcp_entry

claude_json.write_text(json.dumps(claude_data, indent=2, ensure_ascii=False) + "\n")
print("  ✓ Updated " + str(claude_json) + " (mcpServers.radio)")

# --- statusLine goes in ~/.claude/settings.json ---
status_cmd = cmd + " --status"
if env.get("PATH"):
    status_cmd = f'PYTHONIOENCODING=utf-8 PATH="{env["PATH"]}" {cmd} --status'
else:
    status_cmd = f'PYTHONIOENCODING=utf-8 {cmd} --status'

if settings_file.exists():
    try:
        settings = json.loads(settings_file.read_text())
    except json.JSONDecodeError:
        settings = {}
else:
    settings = {}

settings["statusLine"] = {
    "type": "command",
    "command": status_cmd
}

settings_file.parent.mkdir(parents=True, exist_ok=True)
settings_file.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n")
print("  ✓ Updated " + str(settings_file) + " (statusLine)")

PYEOF

# --- Install skill file ---
SKILL_SRC="$SCRIPT_DIR/skill/radio-browser.md"
SKILL_DST="$HOME/.claude/skills/radio-browser/SKILL.md"
if [ -f "$SKILL_SRC" ]; then
    mkdir -p "$(dirname "$SKILL_DST")"
    cp "$SKILL_SRC" "$SKILL_DST"
    echo -e "  ${GREEN}✓ Installed skill: $SKILL_DST${NC}"
fi

# ─── Check ffmpeg ───────────────────────────────────────────────────────

echo -e "\n${CYAN}Checking dependencies...${NC}"

if command -v ffmpeg &>/dev/null; then
    echo -e "  ffmpeg:    ${GREEN}✓ $(which ffmpeg)${NC} (real spectrum)"
else
    echo -e "  ffmpeg:    ${YELLOW}✗ not found${NC} (animated fallback)"
    if [ "$(uname)" = "Darwin" ]; then
        echo -e "             Install: ${CYAN}brew install ffmpeg${NC}"
    else
        echo -e "             Install: ${CYAN}sudo apt install ffmpeg${NC}"
    fi
fi

# ─── Done ────────────────────────────────────────────────────────────────

echo
echo -e "${GREEN}✓ Setup complete!${NC}"
echo
echo -e "${CYAN}Next steps:${NC}"
echo "  1. Restart Claude Code"
echo "  2. Say 'play radio' or 'browse jazz stations' in Claude Code"
echo
echo -e "${CYAN}CLI usage:${NC}"
echo "  $CMD --browse"
echo "  $CMD --browse --tag jazz --limit 5"
echo "  $CMD --status"
echo "  $CMD --stop"
echo "  $CMD --check"
