from __future__ import annotations
import logging, os, shlex, shutil, subprocess
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from prompt_toolkit import PromptSession, print_formatted_text
from prompt_toolkit.completion import CompleteEvent, Completer, Completion, PathCompleter
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style
from rsh.config import get_default_workspaces, load_config
from rsh.discovery import PackageIndex
from rsh.environment import EnvironmentExtractionError, source_workspace
from rsh.executor import BuildError, build_and_launch, build_and_run, colcon_build, colcon_build_all, install_sigint_handler, launch_node, restore_default_sigint_handler, run_node
from rsh import ros2_tools
log = logging.getLogger(__name__)
_NF_PKG = '\uf487'
_NF_DIR = '\uf07b'
_NF_NODE = '\uf1b2'
_NF_TOPIC = '\uf7e4'
_NF_GIT = '\ue725'
_NF_GEAR = '\uf013'
_NF_EXIT = '\uf52b'
_NF_SHELL = '\ue795'
_NF_SRCH = '\uf422'
RSH_STYLE = Style.from_dict({'prompt.path': 'ansibrightblue', 'prompt.arrow': 'ansicyan bold', 'prompt.name': 'ansimagenta bold', 'toolbar': 'bg:#1e1e2e #cdd6f4', 'toolbar.key': '#89b4fa bold', 'toolbar.sep': '#45475a', 'toolbar.val': '#a6e3a1', 'error': 'ansired bold'})
COMMANDS: Dict[str, str] = {'run': f'{_NF_NODE} Build + run a node          (run <pkg> <exec> [args...])', 'launch': f'{_NF_NODE} Build + launch              (launch <pkg> <file> [args...])', 'build': f'{_NF_GEAR} Build a package             (build <pkg>)', 'unbuild': f'{_NF_GEAR} Delete package build        (unbuild <pkg>)', 'create': f'{_NF_PKG} Create a ROS2 package       (create <pkg_name>)', 'source': f'{_NF_SHELL} Source a workspace          (source <path>)', 'ls': f'{_NF_DIR} List directory contents      (ls [path])', 'cd': f'{_NF_DIR} Change directory             (cd <path>)', 'pkgs': f'{_NF_PKG} List packages                (pkgs [--src|--system|--user])', 'topics': f'{_NF_TOPIC} List active topics', 'nodes': f'{_NF_NODE} List active nodes', 'hz': f'{_NF_TOPIC} Show topic frequency        (hz <topic>)', 'echo': f'{_NF_TOPIC} Echo topic messages         (echo <topic>)', 'info': f'{_NF_SRCH} Show topic/node info        (info <topic|node>)', 'services': f'{_NF_GEAR} List active services', 'params': f'{_NF_GEAR} List parameters             (params [node])', 'search': f'{_NF_SRCH} Search pkgs/nodes/topics    (search <query>)', 'clean': f'{_NF_GEAR} Remove build artifacts      (clean [pkg] or clean --all)', 'help': f'{_NF_SHELL} Show available commands', 'exit': f'{_NF_EXIT} Exit RSh'}
_PKG_COMMANDS = {'run', 'build', 'launch', 'clean', 'unbuild'}

class _ExecutableCache:

    def __init__(self):
        self._cache: Dict[str, List[str]] = {}

    def get(self, pkg: str) -> List[str]:
        if pkg not in self._cache:
            self._cache[pkg] = ros2_tools.pkg_executables(pkg)
        return self._cache[pkg]

    def invalidate(self, pkg: Optional[str]=None):
        if pkg is None:
            self._cache.clear()
        else:
            self._cache.pop(pkg, None)

class _LaunchFileCache:

    def __init__(self, index: PackageIndex):
        self._index = index
        self._cache: Dict[str, List[str]] = {}

    def get(self, pkg: str) -> List[str]:
        if pkg not in self._cache:
            self._cache[pkg] = self._index.list_launch_files(pkg)
        return self._cache[pkg]

    def invalidate(self, pkg: Optional[str]=None):
        if pkg is None:
            self._cache.clear()
        else:
            self._cache.pop(pkg, None)

class ReplState:

    def __init__(self, index: PackageIndex):
        self.index = index
        self.exe_cache = _ExecutableCache()
        self.launch_cache = _LaunchFileCache(index)
        self.active_workspace: Optional[Path] = None
        self.workspace_locked: bool = False

class RshCompleter(Completer):

    def __init__(self, state: ReplState):
        self.state = state
        self.dir_completer = PathCompleter(only_directories=True, expanduser=True)
        self.file_completer = PathCompleter(only_directories=False, expanduser=True)

    def get_completions(self, document: Document, complete_event: CompleteEvent) -> Iterable[Completion]:
        text = document.text_before_cursor.lstrip()
        parts = text.split()
        if text.endswith(' '):
            parts.append('')
            
        if len(parts) <= 1:
            prefix = parts[0] if parts else ''
            for (cmd, helptext) in COMMANDS.items():
                if cmd.startswith(prefix):
                    yield Completion(cmd, start_position=-len(prefix), display_meta=helptext)
            
            # Allow fallback bash completions (like ./script.py)
            if prefix and not prefix.isalpha():
                yield from self.file_completer.get_completions(Document(prefix), complete_event)
            return

        cmd = parts[0]

        if len(parts) == 2 and cmd in _PKG_COMMANDS:
            prefix = parts[1]
            for pkg in self.state.index.list_packages():
                if pkg.startswith(prefix):
                    yield Completion(pkg, start_position=-len(prefix))
            return
            
        if len(parts) == 3 and cmd == 'run':
            prefix = parts[2]
            for exe in self.state.exe_cache.get(parts[1]):
                if exe.startswith(prefix):
                    yield Completion(exe, start_position=-len(prefix))
            return
            
        if len(parts) == 3 and cmd == 'launch':
            prefix = parts[2]
            for lf in self.state.launch_cache.get(parts[1]):
                if lf.startswith(prefix):
                    yield Completion(lf, start_position=-len(prefix))
            return
            
        if len(parts) == 2 and cmd in ('hz', 'echo', 'info'):
            prefix = parts[1]
            for t in ros2_tools.topic_list():
                if t.startswith(prefix):
                    yield Completion(t, start_position=-len(prefix))
            return
            
        if cmd in ('cd', 'ls', 'workspace', 'source'):
            yield from self.dir_completer.get_completions(Document(parts[-1]), complete_event)
            return
            
        # Fallback: complete files/directories for arguments
        yield from self.file_completer.get_completions(Document(parts[-1]), complete_event)

def _make_prompt(state: ReplState) -> HTML:
    cwd = os.getcwd()
    home = str(Path.home())
    display = cwd.replace(home, "~", 1) if cwd.startswith(home) else cwd
    
    ws_display = ""
    if state.active_workspace:
        ws_path = str(state.active_workspace)
        ws_str = ws_path.replace(home, "~", 1) if ws_path.startswith(home) else ws_path
        lock = "\uf023 " if state.workspace_locked else ""
        ws_display = f" <ansigray>· ws: {lock}</ansigray><ansigreen>{ws_str}</ansigreen>"

    return HTML(
        f"\n<ansigray>╭─ {_NF_SHELL} rsh · {_NF_DIR} {display}{ws_display}</ansigray>\n"
        f"<ansigray>╰─ #</ansigray> "
    )

def _toolbar(state: ReplState) -> HTML:
    cwd = os.getcwd()
    home = str(Path.home())
    display = cwd.replace(home, '~', 1) if cwd.startswith(home) else cwd
    return HTML(f'<toolbar>  <toolbar.key>{_NF_SHELL} RSh</toolbar.key> <toolbar.sep>│</toolbar.sep> <toolbar.val>{_NF_PKG} {len(state.index)} pkgs</toolbar.val> <toolbar.sep>│</toolbar.sep> <toolbar.val>{_NF_DIR} {display}</toolbar.val> <toolbar.sep>│</toolbar.sep> <toolbar.key>^C</toolbar.key> stop  <toolbar.key>^D</toolbar.key> exit  </toolbar>')

def _print_table(headers: List[str], rows: List[List[str]]) -> None:
    if not rows:
        print('  (no results)')
        return
    cols = len(headers)
    widths = [len(h) for h in headers]
    for row in rows:
        for i in range(cols):
            widths[i] = max(widths[i], len(row[i]) if i < len(row) else 0)
    sep = '+' + '+'.join(('-' * (w + 2) for w in widths)) + '+'

    def fmt_row(r):
        return '| ' + ' | '.join(((r[i] if i < len(r) else '').ljust(widths[i]) for i in range(cols))) + ' |'
    print(sep)
    print(fmt_row(headers))
    print(sep)
    for row in rows:
        print(fmt_row(row))
    print(sep)

def _print_columns(items: List[str], term_width: int) -> None:
    if not items:
        return
    max_len = max((len(s) for s in items)) + 2
    n_cols = max(1, term_width // max_len)
    for (i, item) in enumerate(items):
        end = '\n' if (i + 1) % n_cols == 0 else ''
        print(f'{item:<{max_len}}', end=end)
    if len(items) % n_cols != 0:
        print()

def _print_build_error(exc: BuildError) -> None:
    print(f"\033[91m[ERR]\033[0m BUILD FAILED: {exc}")
    if exc.stderr and exc.stderr.strip():
        print('─── stderr ───')
        for line in exc.stderr.strip().splitlines()[-30:]:
            print(f'  {line}')
        print('─' * 14)

def _auto_index_workspace(directory: Path, state: ReplState) -> int:
    """If *directory* is within a colcon workspace, track it and index it."""
    ws = _find_workspace_root(directory)
    if not state.workspace_locked:
        if ws is not None and state.active_workspace != ws:
            state.active_workspace = ws
            print(f"  \u2728 Active workspace set to: {ws}")

    if ws is not None:
        already_known = state.index.is_valid_workspace(ws)
        count = state.index.index_workspace(ws)
        if count > 0 and not already_known:
            print(f"  {_NF_PKG} Auto-indexed {count} built package(s) from {ws}")
        return count
    return 0

from prompt_toolkit import prompt

def _ask_confirmation(message: str) -> bool:
    try:
        ans = prompt(HTML(f"  <ansicyan>[?]</ansicyan> {message} [y/N] "))
        return ans.strip().lower() in ('y', 'yes')
    except (KeyboardInterrupt, EOFError):
        return False
def _find_workspace_root(start_dir: Path) -> Optional[Path]:
    curr = start_dir.resolve()
    for _ in range(5):
        if (curr / 'src').is_dir():
            return curr
        if curr.parent == curr:
            break
        curr = curr.parent
    return None

def _try_resolve_with_fallback(pkg: str, state: ReplState) -> Optional[Path]:
    ws = state.index.resolve(pkg)
    if ws is not None:
        return ws
    _auto_index_workspace(Path.cwd(), state)
    return state.index.resolve(pkg)

def _handle_run(args, state: ReplState):
    if len(args) < 2:
        print('Usage: run <package> <executable> [--ros-args -p key:=val ...]')
        return
    (pkg, exe) = (args[0], args[1])
    remaining = args[2:]
    (extra_args, ros_args) = ([], [])
    if '--ros-args' in remaining:
        i = remaining.index('--ros-args')
        (extra_args, ros_args) = (remaining[:i], remaining[i + 1:])
    else:
        extra_args = remaining
    ws = _try_resolve_with_fallback(pkg, state)
    origin = state.index.get_origin(pkg)
    active_ws = state.active_workspace or _find_workspace_root(Path.cwd())
    if ws is None or origin == 'system':
        msg = f" [96m[INFO][0m  Running system package '{pkg}'." if origin == 'system' else f" [93m[WARN][0m  Package '{pkg}' not in index. Running without build."
        print(msg)
        run_node(pkg, exe, ros_args=ros_args or None, extra_args=extra_args or None)
        return
        
    if active_ws and ws != active_ws:
        print(f" [93m[WARN][0m  Package '{pkg}' belongs to a different workspace: {ws}")
        if not _ask_confirmation(f"Build '{pkg}' in ({ws}) before running?"):
            if _ask_confirmation(f"Skip build and run existing binary?"):
                run_node(pkg, exe, ros_args=ros_args or None, extra_args=extra_args or None)
            return

    try:
        rc = build_and_run(pkg, exe, ws, ros_args=ros_args or None, extra_args=extra_args or None)
        state.exe_cache.invalidate(pkg)
        if rc != 0:
            print(f' [93m[WARN][0m  Node exited with code {rc}')
    except BuildError as e:
        if e.stderr and 'was not found' in e.stderr:
            print(f" [93m[WARN][0m  Source for '{pkg}' not found in {ws}. Running existing binary.")
            run_node(pkg, exe, ros_args=ros_args or None, extra_args=extra_args or None)
        else:
            _print_build_error(e)
    except EnvironmentExtractionError as e:
        print(f'[91m[ERR][0m  Environment error: {e}')
    except FileNotFoundError as e:
        print(f'[91m[ERR][0m  {e}')

def _handle_launch(args, state: ReplState):
    if len(args) < 2:
        print('Usage: launch <package> <launch_file> [key:=value ...]')
        return
    (pkg, lf) = (args[0], args[1])
    la = args[2:] or None
    ws = _try_resolve_with_fallback(pkg, state)
    origin = state.index.get_origin(pkg)
    active_ws = state.active_workspace or _find_workspace_root(Path.cwd())
    if ws is None or origin == 'system':
        msg = f" [96m[INFO][0m  Running system package '{pkg}'." if origin == 'system' else f" [93m[WARN][0m  Package '{pkg}' not in index. Running without build."
        print(msg)
        run_node(pkg, exe, ros_args=ros_args or None, extra_args=extra_args or None)
        return
        
    if active_ws and ws != active_ws:
        print(f" [93m[WARN][0m  Package '{pkg}' belongs to a different workspace: {ws}")
        if not _ask_confirmation(f"Build '{pkg}' in ({ws}) before running?"):
            if _ask_confirmation(f"Skip build and run existing binary?"):
                run_node(pkg, exe, ros_args=ros_args or None, extra_args=extra_args or None)
            return

    try:
        rc = build_and_run(pkg, exe, ws, ros_args=ros_args or None, extra_args=extra_args or None)
        state.exe_cache.invalidate(pkg)
        if rc != 0:
            print(f' [93m[WARN][0m  Node exited with code {rc}')
    except BuildError as e:
        if e.stderr and 'was not found' in e.stderr:
            print(f" [93m[WARN][0m  Source for '{pkg}' not found in {ws}. Running existing binary.")
            run_node(pkg, exe, ros_args=ros_args or None, extra_args=extra_args or None)
        else:
            _print_build_error(e)
    except EnvironmentExtractionError as e:
        print(f'[91m[ERR][0m  Environment error: {e}')
    except FileNotFoundError as e:
        print(f'[91m[ERR][0m  {e}')

def _handle_create(args, state: ReplState):
    if not args:
        print("Usage: create <package_name> [--build-type ament_python|ament_cmake] [other args...]")
        return
    ws = state.active_workspace or _find_workspace_root(Path.cwd())
    if not ws:
        print("[91m[ERR][0m  Cannot create package: no active workspace set or found.")
        return
    src_dir = ws / 'src'
    if not src_dir.is_dir():
        print(f"[91m[ERR][0m  Cannot find 'src' directory in active workspace ({ws}).")
        return
        
    pkg_name = args[0]
    extra_args = args[1:]
    cmd = ['ros2', 'pkg', 'create', pkg_name] + extra_args
    print(f"  [96m[INFO][0m Creating package '{pkg_name}' in {src_dir}...")
    result = subprocess.run(cmd, cwd=str(src_dir))
    if result.returncode != 0:
        print(f"[91m[ERR][0m  Failed to create package '{pkg_name}'.")
        return
        
    print(f"[92m[OK][0m  Package '{pkg_name}' created successfully. Building...")
    try:
        colcon_build(pkg_name, ws)
        state.exe_cache.invalidate(pkg_name)
        state.launch_cache.invalidate(pkg_name)
        try:
            source_workspace(ws)
            state.index.index_workspace(ws)
            print(f"[92m[OK][0m  Built and indexed '{pkg_name}'")
        except Exception as e:
            print(f"[93m[WARN][0m  Failed to source new package: {e}")
    except BuildError as e:
        _print_build_error(e)

def _handle_unbuild(args, state: ReplState):
    if not args:
        print("Usage: unbuild <package_name>")
        return
    pkg = args[0]
    ws = state.active_workspace or _find_workspace_root(Path.cwd())
    if not ws:
        print(" \033[91m[ERR]\033[0m  Cannot unbuild: No active workspace found.")
        return
        
    build_dir = ws / 'build' / pkg
    install_dir = ws / 'install' / pkg
    if not build_dir.exists() and not install_dir.exists():
        print(f" \033[93m[WARN]\033[0m  Build artifacts for '{pkg}' not found in {ws}.")
        return
        
    if _ask_confirmation(f"Permanently delete build/install artifacts for '{pkg}' in {ws}?"):
        import shutil
        if build_dir.exists():
            shutil.rmtree(build_dir, ignore_errors=True)
        if install_dir.exists():
            shutil.rmtree(install_dir, ignore_errors=True)
        print(f" \033[92m[OK]\033[0m  Deleted build artifacts for '{pkg}'.")
        state.exe_cache.invalidate(pkg)
        state.launch_cache.invalidate(pkg)
        state.index.index_workspace(ws)
    else:
        print("  Unbuild aborted.")

def _handle_build(args, state: ReplState):
    ws = None
    pkg = None
    extra = None
    active_ws = state.active_workspace or _find_workspace_root(Path.cwd())
    
    if not args:
        ws = active_ws
        if not ws:
            print(f" [91m[ERR][0m  Cannot find workspace root. Please 'cd' into a workspace or pass a package name.")
            return
    else:
        pkg = args[0]
        extra = args[1:] or None
        ws = _try_resolve_with_fallback(pkg, state)
        if ws is None:
            ws = active_ws
            if not ws:
                print(f" [91m[ERR][0m  Package '{pkg}' not found in index, and not in a workspace.")
                return
            print(f'   [96m[INFO][0m  Package not in index, but running build from fallback root: {ws}')
        else:
            if active_ws and ws != active_ws:
                print(f" [93m[WARN][0m  Package '{pkg}' belongs to a different workspace: {ws}")
                if not _ask_confirmation(f"Build '{pkg}' in its home workspace ({ws})?"):
                    print(" [91m[ERR][0m  Build aborted.")
                    return
    try:
        if pkg:
            colcon_build(pkg, ws, extra_args=extra)
            state.exe_cache.invalidate(pkg)
            state.launch_cache.invalidate(pkg)
            try:
                source_workspace(ws)
                print(f"[92m[OK][0m  Built '{pkg}' in {ws} and re-sourced")
                state.index.index_workspace(ws)
            except (FileNotFoundError, EnvironmentExtractionError) as e:
                print(f"[93m[WARN][0m  Built '{pkg}' in {ws}, but re-source failed: {e}")
        else:
            colcon_build_all(ws, extra_args=extra)
            state.exe_cache.invalidate()
            state.launch_cache.invalidate()
            try:
                source_workspace(ws)
                print(f"[92m[OK][0m  Built all packages in '{ws}' and re-sourced")
                state.index.index_workspace(ws)
            except (FileNotFoundError, EnvironmentExtractionError) as e:
                print(f"[93m[WARN][0m  Built all packages in '{ws}', but re-source failed: {e}")
    except BuildError as e:
        if pkg and e.stderr and 'was not found' in e.stderr:
            print(f" \033[93m[WARN]\033[0m  Package '{pkg}' source not found in {ws}. Build skipped (assumed binary installation).")
        else:
            _print_build_error(e)

def _handle_source(args, state: ReplState):
    if not args:
        print('Usage: source <workspace_root_path>')
        return
    ws = Path(args[0]).expanduser().resolve()
    try:
        (added, mod, rem) = source_workspace(ws)
        state.index.index_workspace(ws)
        print(f'[92m[OK][0m  Sourced {ws}\n   env: +{len(added)}  Δ{len(mod)}  −{len(rem)}')
    except (FileNotFoundError, EnvironmentExtractionError) as e:
        print(f'[91m[ERR][0m  {e}')

def _handle_cd(args, state: ReplState):
    target = Path.home() if not args else Path(args[0]).expanduser().resolve()
    if not target.is_dir():
        print(f'[91m[ERR][0m  Not a directory: {target}')
        return
    os.chdir(target)
    _auto_index_workspace(target, state)

def _handle_workspace(args, state: ReplState):
    if not args:
        print(f'Usage: workspace <path|dynamic>')
        ws = state.active_workspace
        mode = 'Locked' if state.workspace_locked else 'Dynamic'
        print(f'Current: {ws} ({mode})')
        return
    if args[0] == 'dynamic':
        state.workspace_locked = False
        print(f'   Workspace mode set to: Dynamic')
        _auto_index_workspace(Path.cwd(), state)
        return
    target = Path(args[0]).expanduser().resolve()
    if not target.is_dir() or not (target / 'src').is_dir():
        print(f'[91m[ERR][0m  Not a valid workspace (missing src/): {target}')
        return
    state.active_workspace = target
    state.workspace_locked = True
    print(f'  \uf023 Workspace locked to: {target}')
    state.index.index_workspace(target)

def _handle_ls(args):
    target = Path(args[0]).expanduser().resolve() if args else Path.cwd()
    if not target.is_dir():
        print(f'[91m[ERR][0m  Not a directory: {target}')
        return
    entries = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    if not entries:
        print('  (empty directory)')
        return
    items = []
    for e in entries:
        if e.name.startswith('.'):
            continue
        icon = _NF_DIR if e.is_dir() else '\uf15b'
        items.append(f"{icon} {e.name}{('/' if e.is_dir() else '')}")
    cols = shutil.get_terminal_size((80, 24)).columns
    _print_columns(items, cols)

def _handle_pkgs(args, state: ReplState):
    origin = None
    if '--src' in args:
        origin = 'src'
    elif '--system' in args:
        origin = 'system'
    elif '--user' in args:
        origin = 'user'
        
    query = None
    for arg in args:
        if not arg.startswith('--') and arg != 'search':
            query = arg
            break
            
    pkgs = state.index.list_packages(origin=origin)
    if query:
        pkgs = [p for p in pkgs if query.lower() in p.lower()]
        
    if not pkgs:
        label = f' ({origin})' if origin else ''
        print(f"  (no{label} packages indexed - try 'source <workspace>')")
        return
    origin_icons = {'system': '\uf487', 'src': '\ue5fb', 'user': '\uf007'}
    rows = []
    for p in pkgs:
        o = state.index.get_origin(p)
        ws = state.index.resolve(p)
        ws_str = str(ws) if ws else ''
        home = str(Path.home())
        if ws_str.startswith(home):
            ws_str = ws_str.replace(home, '~', 1)
        icon = origin_icons.get(o, ' ')
        rows.append([f'{icon} {p}', o, ws_str])
    _print_table(['Package', 'Origin', 'Workspace'], rows)
    print(f'  Total: {len(pkgs)} packages')

def _handle_topics(args):
    query = next((a for a in args if a != 'search'), None)
    topics = ros2_tools.topic_list()
    if query:
        topics = [t for t in topics if query.lower() in t.lower()]
    if not topics:
        print('  (no active topics)')
        return
    rows = [[t] for t in topics]
    _print_table(['Topic'], rows)

def _handle_nodes(args):
    query = next((a for a in args if a != 'search'), None)
    nodes = ros2_tools.node_list()
    if query:
        nodes = [n for n in nodes if query.lower() in n.lower()]
    if not nodes:
        print('  (no active nodes)')
        return
    rows = [[n] for n in nodes]
    _print_table(['Node'], rows)

def _handle_hz(args):
    if not args:
        print('Usage: hz <topic>')
        return
    print(f'  Measuring frequency on {args[0]}... (Ctrl+C to stop)')
    ros2_tools.topic_hz(args[0])

def _handle_echo(args):
    if not args:
        print('Usage: echo <topic>')
        return
    print(f'  Echoing {args[0]}... (Ctrl+C to stop)')
    ros2_tools.topic_echo(args[0])

def _handle_info(args):
    if not args:
        print('Usage: info <topic|node>')
        return
    name = args[0]
    result = ros2_tools.topic_info(name)
    if result:
        print(result)
        return
    result = ros2_tools.node_info(name)
    if result:
        print(result)
        return
    print(f"  No info found for '{name}'")

def _handle_services(args):
    query = next((a for a in args if a != 'search'), None)
    svcs = ros2_tools.service_list()
    if query:
        svcs = [s for s in svcs if query.lower() in s.lower()]
    if not svcs:
        print('  (no active services)')
        return
    rows = [[s] for s in svcs]
    _print_table(['Service'], rows)

def _handle_params(args):
    node = args[0] if args else None
    result = ros2_tools.param_list(node)
    if result:
        print(result)
    else:
        print('  (no parameters found)')

def _handle_search(args, state: ReplState):
    if not args:
        print('Usage: search <query>')
        return
        
    if len(args) >= 2:
        sub = args[0]
        sub_args = args[1:]
        if sub in ('pkgs', 'pkg', 'package', 'packages'):
            _handle_pkgs(['search'] + sub_args, state)
            return
        elif sub in ('nodes', 'node'):
            _handle_nodes(['search'] + sub_args)
            return
        elif sub in ('topics', 'topic'):
            _handle_topics(['search'] + sub_args)
            return
        elif sub in ('services', 'service'):
            _handle_services(['search'] + sub_args)
            return
            
    query = args[0]
    print(f"\n  {_NF_SRCH} Searching for '{query}'...\n")
    results = ros2_tools.search_all(query)
    local_pkgs = [p for p in state.index.list_packages() if query.lower() in p.lower()]
    if local_pkgs:
        for p in local_pkgs:
            if p not in results['packages']:
                results['packages'].append(p)
        results['packages'].sort()
    total = sum((len(v) for v in results.values()))
    if total == 0:
        print(f"  No results for '{query}'")
        return
    if results['packages']:
        print(f"  {_NF_PKG} Packages ({len(results['packages'])})")
        _print_table(['Package'], [[p] for p in results['packages']])
    if results['nodes']:
        print(f"\n  {_NF_NODE} Nodes ({len(results['nodes'])})")
        _print_table(['Node'], [[n] for n in results['nodes']])
    if results['topics']:
        print(f"\n  {_NF_TOPIC} Topics ({len(results['topics'])})")
        _print_table(['Topic'], [[t] for t in results['topics']])
    if results['services']:
        print(f"\n  {_NF_GEAR} Services ({len(results['services'])})")
        _print_table(['Service'], [[s] for s in results['services']])
    print(f'\n  Total: {total} results')

def _handle_clean(args, state: ReplState):
    if args and args[0] not in ('--all',):
        pkg = args[0]
        ws = state.index.resolve(pkg)
        if ws is None:
            print(f"[91m[ERR][0m  Package '{pkg}' not in index.")
            return
        removed = []
        for sub in ('build', 'install'):
            t = ws / sub / pkg
            if t.is_dir():
                shutil.rmtree(t)
                removed.append(f'{sub}/{pkg}')
        print(f"[92m[OK][0m  Cleaned: {', '.join(removed)}" if removed else f"  (nothing to clean for '{pkg}')")
    else:
        ws = Path.cwd()
        removed = []
        for d in ('build', 'install', 'log'):
            t = ws / d
            if t.is_dir():
                shutil.rmtree(t)
                removed.append(d)
        print(f"[92m[OK][0m  Cleaned: {', '.join(removed)}" if removed else '  (nothing to clean)')

def _handle_help():
    print(f'\n  {_NF_SHELL} RSh - Available Commands\n')
    max_cmd = max((len(c) for c in COMMANDS))
    for (cmd, desc) in COMMANDS.items():
        print(f'  {cmd:<{max_cmd + 2}} {desc}')
    print()

def main(*, workspace: Optional[str]=None, log_level: str='WARNING'):
    logging.basicConfig(level=getattr(logging, log_level.upper(), logging.WARNING), format='%(name)s: %(message)s')
    config = load_config()
    index = PackageIndex()
    state = ReplState(index)
    index.index_installed()
    workspaces: List[Path] = []
    if workspace:
        workspaces.append(Path(workspace).expanduser().resolve())
    workspaces.extend(get_default_workspaces(config))
    seen: set[Path] = set()
    workspaces = [ws for ws in workspaces if ws not in seen and (not seen.add(ws))]
    for ws in workspaces:
        try:
            source_workspace(ws)
            index.index_workspace(ws)
            print(f'[92m[OK][0m  Workspace sourced: {ws}')
        except (FileNotFoundError, EnvironmentExtractionError) as e:
            print(f'[93m[WARN][0m  Could not source workspace: {e}')
            index.index_workspace(ws)
    _auto_index_workspace(Path.cwd(), state)
    install_sigint_handler()
    session = PromptSession(history=FileHistory(str(Path.home() / '.rsh_history')), completer=RshCompleter(state), complete_while_typing=False, style=RSH_STYLE, bottom_toolbar=lambda : _toolbar(state))
    src_count = len(index.list_packages(origin='src'))
    sys_count = len(index.list_packages(origin='system'))
    print(f"\n ▌ {_NF_SHELL}  RSh - ROS2 Shell v1.0.0\n ▌ Type 'help' or press Tab\n ▌ ^C stops nodes · ^D exits\n")
    while True:
        try:
            raw = session.prompt(_make_prompt(state))
        except KeyboardInterrupt:
            continue
        except EOFError:
            break
        raw = raw.strip()
        if not raw:
            continue
        print()
        try:
            tokens = shlex.split(raw)
        except ValueError as e:
            print(f'[91m[ERR][0m  Parse error: {e}')
            continue
        cmd = tokens[0].lower()
        args = tokens[1:]
        if cmd == 'run':
            _handle_run(args, state)
        elif cmd == 'launch':
            _handle_launch(args, state)
        elif cmd == 'create':
            _handle_create(args, state)
        elif cmd == 'unbuild':
            _handle_unbuild(args, state)
        elif cmd == 'build':
            _handle_build(args, state)
        elif cmd == 'source':
            _handle_source(args, state)
        elif cmd == 'cd':
            _handle_cd(args, state)
        elif cmd == 'ls':
            _handle_ls(args)
        elif cmd == 'workspace':
            _handle_workspace(args, state)
        elif cmd in ('pkgs', 'pkg'):
            _handle_pkgs(args, state)
        elif cmd in ('topics', 'topic'):
            _handle_topics(args)
        elif cmd in ('nodes', 'node'):
            _handle_nodes(args)
        elif cmd == 'hz':
            _handle_hz(args)
        elif cmd == 'echo':
            _handle_echo(args)
        elif cmd == 'info':
            _handle_info(args)
        elif cmd in ('services', 'service'):
            _handle_services(args)
        elif cmd in ('params', 'param'):
            _handle_params(args)
        elif cmd == 'search':
            _handle_search(args, state)
        elif cmd == 'clean':
            _handle_clean(args, state)
        elif cmd == 'help':
            _handle_help()
        elif cmd in ('exit', 'quit', 'q'):
            break
        else:
            try:
                subprocess.run(['bash', '-c', raw])
            except KeyboardInterrupt:
                print()
    restore_default_sigint_handler()
    print('Exiting RSH...')