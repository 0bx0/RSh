from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Any, Dict, List
log = logging.getLogger(__name__)
CONFIG_DIR = Path.home() / '.config' / 'rsh'
CONFIG_FILE = CONFIG_DIR / 'config.json'
_DEFAULTS: Dict[str, Any] = {'version': 1, 'default_workspaces': [], 'symlink_install': True, 'build_timeout': 300}

def load_config(path: Path | str | None=None) -> Dict[str, Any]:
    config_path = Path(path) if path else CONFIG_FILE
    if config_path.is_file():
        try:
            with config_path.open('r') as f:
                user_config = json.load(f)
            log.debug('Loaded config from %s', config_path)
        except (json.JSONDecodeError, OSError) as exc:
            log.warning('Corrupt config at %s - using defaults: %s', config_path, exc)
            user_config = {}
    else:
        user_config = {}
        _write_config(_DEFAULTS, config_path)
        log.info('Created default config at %s', config_path)
    merged = {**_DEFAULTS, **user_config}
    return merged

def save_config(config: Dict[str, Any], path: Path | str | None=None) -> None:
    config_path = Path(path) if path else CONFIG_FILE
    _write_config(config, config_path)
    log.debug('Saved config to %s', config_path)

def get_default_workspaces(config: Dict[str, Any]) -> List[Path]:
    raw: List[str] = config.get('default_workspaces', [])
    return [Path(p).expanduser().resolve() for p in raw if p]

def _write_config(config: Dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w') as f:
        json.dump(config, f, indent=2)
        f.write('\n')