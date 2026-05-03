# RSh - ROS2 Shell

An interactive REPL that eliminates `build → source → run` friction for ROS2 workspaces.

Stop typing `colcon build && source install/setup.bash && ros2 run ...` - just type `run my_pkg my_node`.

> **Note:** RSh uses [Nerd Font](https://www.nerdfonts.com/) glyphs in the prompt and status bar. Install a Nerd Font patched terminal font for the best experience.

## Features

- **One-command workflow** - `run pkg node` builds, sources, and runs automatically
- **Launch file support** - `launch pkg bringup.launch.py use_sim:=true`
- **Tab completion** - commands → packages → executables/launch files/topics
- **Safe Ctrl+C** - forwards SIGINT to child nodes, REPL stays alive
- **ROS2 debugging** - `topics`, `nodes`, `hz`, `echo`, `info`, `search` built in
- **Package browser** - `pkgs --src` / `--system` / `--user` with formatted tables
- **Global search** - `search camera` finds matching packages, nodes, topics, services
- **Per-package clean** - `clean my_pkg` wipes only that package's build artifacts
- **Persistent config** - auto-sources your workspaces on startup via `~/.config/rsh/config.json`

## Install

```bash
git clone https://github.com/zerobx0/RosSh.git
cd RosSh
chmod +x install.sh
./install.sh
```

Or manually:

```bash
pip install .
```

## Usage

```bash
# Start the shell
rsh

# Start with a workspace pre-sourced
rsh -w ~/my_ros2_ws
```

### Commands

| Command | Description | Example |
|---------|-------------|---------|
| `run` | Build + source + run a node | `run demo_nodes_cpp talker` |
| `launch` | Build + source + launch | `launch nav2_bringup bringup.launch.py` |
| `build` | Build a package | `build my_pkg` |
| `source` | Source a workspace | `source ~/ros2_ws` |
| `ls` | List directory contents | `ls` or `ls ~/ros2_ws/src` |
| `cd` | Change directory | `cd ~/ros2_ws` |
| `pkgs` | List packages (filterable) | `pkgs --src` / `--system` / `--user` |
| `topics` | List active ROS2 topics | `topics` |
| `nodes` | List active ROS2 nodes | `nodes` |
| `hz` | Show topic publish rate | `hz /scan` |
| `echo` | Echo topic messages | `echo /cmd_vel` |
| `info` | Show topic/node details | `info /odom` |
| `services` | List active services | `services` |
| `params` | List parameters | `params /my_node` |
| `search` | Search across everything | `search camera` |
| `clean` | Remove build artifacts | `clean my_pkg` or `clean --all` |
| `help` | Show all commands | `help` |
| `exit` | Exit the shell | `exit` or `Ctrl+D` |

### ROS2 Arguments

Pass `--ros-args` just like the normal CLI:

```
rsh ~/ros2_ws
 ❯ run my_pkg my_node --ros-args -p frequency:=10.0 --remap /input:=/sensor
```

Launch file arguments:

```
 ❯ launch my_pkg bringup.launch.py use_sim:=true rviz:=false
```

### Searching

The `search` command queries packages, nodes, topics, and services simultaneously:

```
 ❯ search camera
```

Produces a formatted table showing all matches across all categories.

## Configuration

On first run, RSh creates `~/.config/rsh/config.json`:

```json
{
  "version": 1,
  "default_workspaces": [],
  "symlink_install": true,
  "build_timeout": 300
}
```

Add your workspaces to `default_workspaces` to auto-source them on startup:

```json
{
  "default_workspaces": [
    "~/ros2_ws",
    "~/nav_ws"
  ]
}
```

## Requirements

- Python 3.10+
- ROS2 Humble (or compatible distro)
- A [Nerd Font](https://www.nerdfonts.com/) for terminal icons
- Ubuntu / Arch Linux

## Uninstall

```bash
pip uninstall rsh
```

## License

MIT
