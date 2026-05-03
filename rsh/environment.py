from __future__ import annotations
import logging
import os
import subprocess
from pathlib import Path
from typing import Dict, Optional, Set, Tuple
log = logging.getLogger(__name__)

def extract_and_inject(setup_script: Path | str, *, timeout: float=30.0, shell: str='/bin/bash') -> Tuple[Dict[str, str], Dict[str, str], Set[str]]:
    setup_script = Path(setup_script).resolve()
    if not setup_script.is_file():
        raise FileNotFoundError(f'Setup script not found: {setup_script}')
    log.info('Extracting environment from: %s', setup_script)
    pre_env = dict(os.environ)
    cmd = f"set -a && source '{setup_script}' > /dev/null 2>&1 && env -0"
    try:
        result = subprocess.run([shell, '-c', cmd], stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, timeout=timeout, env=dict(os.environ))
    except subprocess.TimeoutExpired as exc:
        raise EnvironmentExtractionError(f"Sourcing '{setup_script}' timed out after {timeout}s") from exc
    if result.returncode != 0:
        stderr_tail = result.stderr.decode(errors='replace')[-500:]
        raise EnvironmentExtractionError(f"Sourcing '{setup_script}' failed (rc={result.returncode}):\n{stderr_tail}")
    post_env = _parse_env_null(result.stdout)
    (added, modified, removed) = _diff_env(pre_env, post_env)
    for (key, value) in added.items():
        os.environ[key] = value
    for (key, value) in modified.items():
        os.environ[key] = value
    for key in removed:
        os.environ.pop(key, None)
    log.info('Environment injected - %d added, %d modified, %d removed', len(added), len(modified), len(removed))
    return (added, modified, removed)

def source_workspace(workspace_root: Path | str, *, timeout: float=30.0) -> Tuple[Dict[str, str], Dict[str, str], Set[str]]:
    ws = Path(workspace_root).resolve()
    setup = ws / 'install' / 'setup.bash'
    if not setup.is_file():
        raise FileNotFoundError(f'Workspace has no install/setup.bash - has it been built?\n  Expected: {setup}')
    return extract_and_inject(setup, timeout=timeout)

def _parse_env_null(raw: bytes) -> Dict[str, str]:
    env: Dict[str, str] = {}
    for entry in raw.split(b'\x00'):
        if not entry:
            continue
        decoded = entry.decode(errors='replace')
        eq_idx = decoded.find('=')
        if eq_idx == -1:
            log.debug('Skipping malformed env entry: %r', decoded[:80])
            continue
        key = decoded[:eq_idx]
        value = decoded[eq_idx + 1:]
        env[key] = value
    return env

def _diff_env(before: Dict[str, str], after: Dict[str, str]) -> Tuple[Dict[str, str], Dict[str, str], Set[str]]:
    added: Dict[str, str] = {}
    modified: Dict[str, str] = {}
    for (key, value) in after.items():
        if key not in before:
            added[key] = value
        elif before[key] != value:
            modified[key] = value
    removed = set(before.keys()) - set(after.keys())
    return (added, modified, removed)

class EnvironmentExtractionError(RuntimeError):
    pass