from __future__ import annotations
import subprocess
from typing import Dict, List, Optional, Tuple

def _run_ros2(*args: str, timeout: float=5.0) -> Optional[str]:
    try:
        result = subprocess.run(['ros2', *args], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, timeout=timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.decode(errors='replace')

def topic_list() -> List[str]:
    out = _run_ros2('topic', 'list')
    if not out:
        return []
    return sorted((line.strip() for line in out.splitlines() if line.strip()))

def topic_info(topic: str) -> Optional[str]:
    return _run_ros2('topic', 'info', topic, '-v')

def topic_hz(topic: str) -> None:
    import os
    from rsh.executor import _active_child, _terminate_child
    import rsh.executor as _ex
    try:
        _ex._active_child = subprocess.Popen(['ros2', 'topic', 'hz', topic], preexec_fn=os.setpgrp)
        _ex._active_child.wait()
    except KeyboardInterrupt:
        if _ex._active_child:
            _terminate_child(_ex._active_child)
    finally:
        _ex._active_child = None

def topic_echo(topic: str, msg_type: Optional[str]=None) -> None:
    import os
    from rsh.executor import _terminate_child
    import rsh.executor as _ex
    cmd = ['ros2', 'topic', 'echo', topic]
    if msg_type:
        cmd.extend(['--msg-type', msg_type])
    try:
        _ex._active_child = subprocess.Popen(cmd, preexec_fn=os.setpgrp)
        _ex._active_child.wait()
    except KeyboardInterrupt:
        if _ex._active_child:
            _terminate_child(_ex._active_child)
    finally:
        _ex._active_child = None

def node_list() -> List[str]:
    out = _run_ros2('node', 'list')
    if not out:
        return []
    return sorted((line.strip() for line in out.splitlines() if line.strip()))

def node_info(node: str) -> Optional[str]:
    return _run_ros2('node', 'info', node)

def service_list() -> List[str]:
    out = _run_ros2('service', 'list')
    if not out:
        return []
    return sorted((line.strip() for line in out.splitlines() if line.strip()))

def param_list(node: Optional[str]=None) -> Optional[str]:
    args = ['param', 'list']
    if node:
        args.append(node)
    return _run_ros2(*args)

def param_get(node: str, param: str) -> Optional[str]:
    return _run_ros2('param', 'get', node, param)

def interface_show(msg_type: str) -> Optional[str]:
    return _run_ros2('interface', 'show', msg_type)

def pkg_executables(package: str) -> List[str]:
    out = _run_ros2('pkg', 'executables', package)
    if not out:
        return []
    exes = []
    for line in out.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2:
            exes.append(parts[1])
    return sorted(exes)

def search_all(query: str) -> Dict[str, List[str]]:
    results: Dict[str, List[str]] = {'packages': [], 'nodes': [], 'topics': [], 'services': []}
    q = query.lower()
    out = _run_ros2('pkg', 'list')
    if out:
        results['packages'] = sorted((p.strip() for p in out.splitlines() if q in p.strip().lower()))
    for n in node_list():
        if q in n.lower():
            results['nodes'].append(n)
    for t in topic_list():
        if q in t.lower():
            results['topics'].append(t)
    for s in service_list():
        if q in s.lower():
            results['services'].append(s)
    return results