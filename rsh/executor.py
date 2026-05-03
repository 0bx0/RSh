from __future__ import annotations
import logging
import os
import signal
import subprocess
from pathlib import Path
from typing import List, Optional
log = logging.getLogger(__name__)
_active_child: Optional[subprocess.Popen] = None

def _sigint_handler(signum: int, frame) -> None:
    global _active_child
    if _active_child is not None and _active_child.poll() is None:
        pgid = os.getpgid(_active_child.pid)
        log.debug('Forwarding SIGINT to child PID %d (pgid %d)', _active_child.pid, pgid)
        try:
            os.killpg(pgid, signal.SIGINT)
        except ProcessLookupError:
            pass
        return
    raise KeyboardInterrupt

def install_sigint_handler() -> None:
    signal.signal(signal.SIGINT, _sigint_handler)
    log.debug('Custom SIGINT handler installed')

def restore_default_sigint_handler() -> None:
    signal.signal(signal.SIGINT, signal.SIG_DFL)

class BuildError(RuntimeError):

    def __init__(self, message: str, *, stderr: str='', returncode: int=1):
        super().__init__(message)
        self.stderr = stderr
        self.returncode = returncode

def colcon_build(package: str, workspace_root: Path | str, *, symlink_install: bool=True, extra_args: Optional[List[str]]=None, timeout: float=300.0) -> subprocess.CompletedProcess:
    ws = Path(workspace_root).resolve()
    cmd: List[str] = ['colcon', 'build', '--packages-up-to', package]
    if symlink_install:
        cmd.append('--symlink-install')
    if extra_args:
        cmd.extend(extra_args)
    log.info("Building '%s' in %s", package, ws)
    result = subprocess.run(cmd, cwd=str(ws), timeout=timeout, stderr=subprocess.PIPE)
    if result.returncode != 0:
        stderr_text = result.stderr.decode(errors='replace')[-2000:]
        if 'was not found' in stderr_text and '--packages-up-to' in cmd:
            log.warning("Package '%s' not found in src, assuming binary installation.", package)
            return result
        raise BuildError(f"colcon build failed for '{package}' (rc={result.returncode})", stderr=stderr_text, returncode=result.returncode)
    log.info("Build succeeded for '%s'", package)
    return result

def colcon_build_all(workspace_root: Path | str, *, symlink_install: bool=True, extra_args: Optional[List[str]]=None, timeout: float=600.0) -> subprocess.CompletedProcess:
    ws = Path(workspace_root).resolve()
    cmd: List[str] = ['colcon', 'build', '--continue-on-error']
    if symlink_install:
        cmd.append('--symlink-install')
    if extra_args:
        cmd.extend(extra_args)
    log.info('Building all packages in %s', ws)
    result = subprocess.run(cmd, cwd=str(ws), timeout=timeout, stderr=subprocess.PIPE)
    if result.returncode != 0:
        stderr_text = result.stderr.decode(errors='replace')[-2000:]
        raise BuildError(f'Workspace build completed with errors (rc={result.returncode})', stderr=stderr_text, returncode=result.returncode)
    log.info('Workspace build succeeded')
    return result

def run_node(package: str, executable: str, *, ros_args: Optional[List[str]]=None, extra_args: Optional[List[str]]=None, workspace_root: Optional[Path | str]=None) -> int:
    global _active_child
    cmd: List[str] = ['ros2', 'run', package, executable]
    if extra_args:
        cmd.extend(extra_args)
    if ros_args:
        cmd.append('--ros-args')
        cmd.extend(ros_args)
    cwd = str(Path(workspace_root).resolve()) if workspace_root else None
    log.info('Launching: %s', ' '.join(cmd))
    _active_child = subprocess.Popen(cmd, cwd=cwd, preexec_fn=os.setpgrp)
    log.debug('Child PID=%d  PGID=%d', _active_child.pid, os.getpgid(_active_child.pid))
    try:
        _active_child.wait()
    except KeyboardInterrupt:
        _terminate_child(_active_child)
    rc = _active_child.returncode
    _active_child = None
    if rc < 0:
        sig = _signal_name(-rc)
        log.info('Node terminated by %s', sig)
    else:
        log.info('Node exited with code %d', rc)
    return rc

def launch_node(package: str, launch_file: str, *, launch_args: Optional[List[str]]=None, workspace_root: Optional[Path | str]=None) -> int:
    global _active_child
    cmd: List[str] = ['ros2', 'launch', package, launch_file]
    if launch_args:
        cmd.extend(launch_args)
    cwd = str(Path(workspace_root).resolve()) if workspace_root else None
    log.info('Launching: %s', ' '.join(cmd))
    _active_child = subprocess.Popen(cmd, cwd=cwd, preexec_fn=os.setpgrp)
    log.debug('Child PID=%d  PGID=%d', _active_child.pid, os.getpgid(_active_child.pid))
    try:
        _active_child.wait()
    except KeyboardInterrupt:
        _terminate_child(_active_child)
    rc = _active_child.returncode
    _active_child = None
    if rc < 0:
        sig = _signal_name(-rc)
        log.info('Launch terminated by %s', sig)
    else:
        log.info('Launch exited with code %d', rc)
    return rc

def build_and_run(package: str, executable: str, workspace_root: Path | str, *, ros_args: Optional[List[str]]=None, extra_args: Optional[List[str]]=None, symlink_install: bool=True, build_timeout: float=300.0) -> int:
    from rsh.environment import source_workspace
    ws = Path(workspace_root).resolve()
    colcon_build(package, ws, symlink_install=symlink_install, timeout=build_timeout)
    source_workspace(ws)
    return run_node(package, executable, ros_args=ros_args, extra_args=extra_args, workspace_root=ws)

def build_and_launch(package: str, launch_file: str, workspace_root: Path | str, *, launch_args: Optional[List[str]]=None, symlink_install: bool=True, build_timeout: float=300.0) -> int:
    from rsh.environment import source_workspace
    ws = Path(workspace_root).resolve()
    colcon_build(package, ws, symlink_install=symlink_install, timeout=build_timeout)
    source_workspace(ws)
    return launch_node(package, launch_file, launch_args=launch_args, workspace_root=ws)

def _terminate_child(child: subprocess.Popen) -> None:
    try:
        pgid = os.getpgid(child.pid)
        os.killpg(pgid, signal.SIGINT)
        try:
            child.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            log.warning('Child PID %d stuck; sending SIGKILL', child.pid)
            os.killpg(pgid, signal.SIGKILL)
            child.wait(timeout=5.0)
    except ProcessLookupError:
        pass

def _signal_name(signum: int) -> str:
    try:
        return signal.Signals(signum).name
    except (ValueError, AttributeError):
        return str(signum)