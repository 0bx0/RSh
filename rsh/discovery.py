from __future__ import annotations
import logging
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional
log = logging.getLogger(__name__)

class PackageIndex:

    def __init__(self) -> None:
        self._packages: Dict[str, Path] = {}
        self._origins: Dict[str, str] = {}
        self._valid_workspaces: set[Path] = set()

    def index_installed(self) -> int:
        try:
            from ament_index_python.packages import get_packages_with_prefixes
        except ImportError:
            log.warning('ament_index_python not available - is ROS2 sourced in this environment?')
            return 0
        installed = get_packages_with_prefixes()
        count = 0
        for (pkg_name, prefix) in installed.items():
            ws = _prefix_to_workspace(prefix)
            self._packages[pkg_name] = ws
            if prefix.startswith('/opt/ros'):
                self._origins[pkg_name] = 'system'
            else:
                self._origins[pkg_name] = 'user'
            self._valid_workspaces.add(ws)
            count += 1
        log.info('Indexed %d installed packages (ament fast-path)', count)
        return count

    def index_workspace(self, workspace_root: Path | str) -> int:
        ws = Path(workspace_root).resolve()
        if not (ws / 'build').is_dir() or not (ws / 'install').is_dir() or (not (ws / 'log').is_dir()):
            log.debug('Workspace %s is missing build/install/log folders. Ignored.', ws)
            return 0
        install_dir = ws / 'install'
        count = 0
        for child in install_dir.iterdir():
            if child.is_dir() and (not child.name.startswith('.')):
                pkg_name = child.name
                if (child / 'share' / pkg_name).is_dir():
                    self._packages[pkg_name] = ws
                    self._origins[pkg_name] = 'user'
                    count += 1
                    log.debug('Found built package: %s in %s', pkg_name, ws)
        if count > 0:
            self._valid_workspaces.add(ws)
            log.info('Workspace scan: %d built packages in %s', count, ws)
        else:
            log.warning('Workspace %s contains no built ROS2 packages in install/ - discarded from index', ws)
        return count

    def register(self, package: str, workspace_root: Path | str) -> None:
        self._packages[package] = Path(workspace_root).resolve()
        self._origins[package] = 'user'

    def is_valid_workspace(self, workspace_root: Path | str) -> bool:
        return Path(workspace_root).resolve() in self._valid_workspaces

    def resolve(self, package: str) -> Optional[Path]:
        return self._packages.get(package)

    def get_origin(self, package: str) -> str:
        return self._origins.get(package, 'unknown')

    def list_packages(self, origin: Optional[str]=None) -> list[str]:
        if origin is None:
            return sorted(self._packages.keys())
        return sorted((pkg for (pkg, o) in self._origins.items() if o == origin))

    def __contains__(self, package: str) -> bool:
        return package in self._packages

    def __len__(self) -> int:
        return len(self._packages)

    def list_launch_files(self, package: str) -> List[str]:
        found: set[str] = set()
        try:
            result = subprocess.run(['ros2', 'pkg', 'prefix', package], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, timeout=5.0)
            if result.returncode == 0:
                prefix = Path(result.stdout.decode().strip())
                launch_dir = prefix / 'share' / package / 'launch'
                found.update(_scan_launch_dir(launch_dir))
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        ws = self._packages.get(package)
        if ws is not None:
            launch_dir = ws / 'install' / package / 'share' / package / 'launch'
            found.update(_scan_launch_dir(launch_dir))
        return sorted(found)
LAUNCH_EXTENSIONS = {'.launch.py', '.launch.xml', '.launch.yaml'}

def _parse_package_name(pkg_xml: Path) -> Optional[str]:
    try:
        tree = ET.parse(pkg_xml)
        name_el = tree.getroot().find('name')
        if name_el is not None and name_el.text:
            return name_el.text.strip()
    except ET.ParseError:
        log.debug('Malformed package.xml: %s', pkg_xml)
    return None

def _scan_launch_dir(directory: Path) -> List[str]:
    if not directory.is_dir():
        return []
    results: List[str] = []
    for f in directory.iterdir():
        if f.is_file() and any((f.name.endswith(ext) for ext in LAUNCH_EXTENSIONS)):
            results.append(f.name)
    return results

def _prefix_to_workspace(prefix: str) -> Path:
    p = Path(prefix)
    if p.parent.name == 'install':
        return p.parent.parent
    return p