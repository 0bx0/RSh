# RSh (ROS2 Shell) — Contributors Guide

Welcome to the internal architecture guide for **RSh**. This document explains how the pieces of the REPL fit together, the underlying process-management mechanics, and how to extend the tool.

## Architecture Overview

RSh is designed as a monolithic Python application split into highly cohesive, single-responsibility modules. The core challenge of RSh is maintaining an interactive shell environment while seamlessly jumping between different, deeply-nested ROS2 workspaces without leaking environment variables or locking up the terminal.

### 1. Frontend & Routing (`rsh/repl.py`)
The frontend is built on [`prompt_toolkit`](https://python-prompt-toolkit.readthedocs.io/).
- **`PromptSession`**: Handles the actual REPL loop, terminal UI (bottom toolbar, path-aware prompt), and command history (`~/.rsh_history`).
- **`RshCompleter`**: Implements 3-level dynamic tab-completion. It hooks into the backend modules to suggest commands → packages → executables/topics/launch files.
- **`ReplState`**: A central data class that holds the session's active state, including the `PackageIndex`, executable/launch caches, and the `active_workspace` tracking.
- **Router**: The `_handle_*` functions parse raw user input and route it to the appropriate backend modules. Unrecognized commands fallback to a raw `bash -c` subprocess execution.

### 2. State & Discovery (`rsh/discovery.py`)
Solves the problem of knowing where packages live without explicitly sourcing them first.
- **`PackageIndex`**: Maintains an in-memory hash map of `{package_name: workspace_root_path}`.
- **`index_workspace`**: When RSh enters a workspace, it scans the `<workspace_root>/install/` directory. If it finds built packages, they are indexed. 
- **Active Workspace Tracking**: Instead of requiring global `-w` flags, RSh watches directory movements (`cd`) and tries to locate the root of the workspace. This is tracked in `ReplState.active_workspace`.

### 3. Environment Engine (`rsh/environment.py`)
The most complex and critical piece of the puzzle. Traditional ROS2 wrappers run `bash -c "source setup.bash && ros2 run ..."`. This creates massive overhead and traps the REPL inside sub-shells.

**How RSh does it:**
1. RSh runs `bash -c "source <workspace>/install/setup.bash && env -0"`.
2. It captures the raw, null-terminated environment variables *after* sourcing.
3. It computes the delta (what changed between the base Python `os.environ` and the sourced shell).
4. It injects those changes directly into the current, living Python process (`os.environ.update()`).

This makes sourcing instant and allows the REPL to maintain one persistent process.

### 4. Execution & Signal Engine (`rsh/executor.py`)
Manages `colcon build`, `ros2 run`, and `ros2 launch`.

- **Fail-safe Rooting**: If a user runs `build` deep inside a `src/` sub-directory, the executor walks up the tree to find the workspace root before executing `colcon build`.
- **Process Group Isolation**: If you run a ROS2 node and hit `Ctrl+C` (SIGINT), the Linux kernel normally sends that signal to *every* process attached to the terminal—killing RSh instantly. 
  - To prevent this, RSh spawns child nodes in their own Process Group (`os.setpgrp`). 
  - RSh overrides the default Python `SIGINT` handler. When `Ctrl+C` is pressed, RSh catches it and forwards `os.killpg(child_pgid, SIGINT)` to the active node, safely terminating it while keeping the REPL alive.

### 5. ROS2 Tooling (`rsh/ros2_tools.py`)
A lightweight wrapper around standard `ros2` CLI commands (`ros2 topic list`, `ros2 node info`, `ros2 pkg search`). Output is captured, cleaned up, and rendered using `prompt_toolkit` HTML formatted tables.

---

## Extension Guide

### Adding a New Command
1. **Define the Router Logic**: Open `rsh/repl.py` and create a `_handle_mycmd(args, state)` function.
2. **Register the Command**: Add your command and its help text to the `COMMANDS` dictionary at the top of `repl.py`. This automatically enables tab-completion for it.
3. **Route the Command**: In the `main()` while loop, add your command to the `if/elif` block.
   ```python
   elif cmd == "mycmd": _handle_mycmd(args, state)
   ```

### Updating the UI
RSh relies heavily on Nerd Fonts. If you want to add new icons or UI elements, look at:
- `_make_prompt(state)`: Controls the `rsh ~/path ❯` line.
- `_toolbar(state)`: Controls the bottom status bar.
- Use `print_formatted_text(HTML("<ansi...></ansi...>"))` for rich console output instead of raw ANSI escape codes.

### Re-compiling the Package Locally
When testing your changes, uninstall the existing binary and install the local source:
```bash
pip uninstall rsh -y
pip install .
```
Or use an editable install:
```bash
pip install -e .
```
