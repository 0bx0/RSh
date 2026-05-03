#!/usr/bin/env bash

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${CYAN}[rsh]${NC} $*"; }
ok()    { echo -e "${GREEN}[rsh]${NC} $*"; }
err()   { echo -e "${RED}[rsh]${NC} $*" >&2; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"


info "Checking Python version..."

PYTHON=""
for candidate in python3 python; do
    if command -v "$candidate" &>/dev/null; then
        version=$("$candidate" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || true)
        major=$("$candidate" -c "import sys; print(sys.version_info.major)" 2>/dev/null || echo 0)
        minor=$("$candidate" -c "import sys; print(sys.version_info.minor)" 2>/dev/null || echo 0)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 10 ]; then
            PYTHON="$candidate"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    err "Python 3.10+ is required but not found."
    err "Install it with: sudo apt install python3 python3-pip"
    exit 1
fi

ok "Found $PYTHON ($version)"


if ! "$PYTHON" -m pip --version &>/dev/null; then
    info "pip not found, attempting to install..."
    if command -v apt &>/dev/null; then
        sudo apt update && sudo apt install -y python3-pip
    elif command -v pacman &>/dev/null; then
        sudo pacman -S --noconfirm python-pip
    else
        err "pip not found and couldn't auto-install. Install pip manually."
        exit 1
    fi
fi


info "Installing RSh..."

cd "$SCRIPT_DIR"
"$PYTHON" -m pip install . --break-system-packages 2>/dev/null \
    || "$PYTHON" -m pip install .


if command -v rsh &>/dev/null; then
    ok "Installation complete!"
    echo ""
    echo -e "  ${BOLD}Run the shell:${NC}"
    echo -e "    ${CYAN}rsh${NC}"
    echo ""
    echo -e "  ${BOLD}With a workspace:${NC}"
    echo -e "    ${CYAN}rsh -w ~/your_ros2_ws${NC}"
    echo ""
    echo -e "  ${BOLD}Uninstall:${NC}"
    echo -e "    ${CYAN}pip uninstall rsh${NC}"
    echo ""
else
    RSH_PATH=$("$PYTHON" -c "import shutil; print(shutil.which('rsh') or '')" 2>/dev/null || true)
    if [ -n "$RSH_PATH" ]; then
        ok "Installed at: $RSH_PATH"
    else
        LOCAL_BIN="$HOME/.local/bin"
        if [ -f "$LOCAL_BIN/rsh" ]; then
            echo ""
            err "'rsh' was installed to $LOCAL_BIN but it's not on your PATH."
            echo -e "  Add this to your ${BOLD}~/.bashrc${NC}:"
            echo -e "    ${CYAN}export PATH=\"\$HOME/.local/bin:\$PATH\"${NC}"
            echo -e "  Then run: ${CYAN}source ~/.bashrc${NC}"
            echo ""
        else
            err "Installation succeeded but 'rsh' command not found on PATH."
            err "Try: $PYTHON -m rsh"
        fi
    fi
fi
