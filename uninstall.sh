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

info "Checking Python version..."

PYTHON=""
if command -v python3 &>/dev/null; then
    PYTHON="python3"
elif command -v python &>/dev/null; then
    PYTHON="python"
else
    err "Python 3 is required but not found."
    exit 1
fi

info "Using $PYTHON"

info "Uninstalling RSh..."
if "$PYTHON" -m pip uninstall -y rsh; then
    ok "RSh has been successfully uninstalled."
    info "Note: You may need to run 'hash -r' to clear your terminal cache if you see 'No such file or directory' when typing rsh."
    
    # Optional cleanup of config and history
    if [ -d "$HOME/.config/rsh" ] || [ -f "$HOME/.rsh_history" ]; then
        read -p "  [?] Do you want to remove your RSh configuration and history (~/.config/rsh, ~/.rsh_history)? [y/N] " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            if [ -d "$HOME/.config/rsh" ]; then
                rm -rf "$HOME/.config/rsh"
                info "Removed configuration directory ~/.config/rsh"
            fi
            if [ -f "$HOME/.rsh_history" ]; then
                rm "$HOME/.rsh_history"
                info "Removed history file ~/.rsh_history"
            fi
        fi
    fi
else
    err "Failed to uninstall RSh or RSh is not installed."
    exit 1
fi
