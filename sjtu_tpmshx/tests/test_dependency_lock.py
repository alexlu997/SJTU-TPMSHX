"""The supported Mac/Windows environment must match the shared exact lock."""

from importlib import metadata
from pathlib import Path
import tomllib

from packaging.requirements import Requirement


_ROOT = Path(__file__).resolve().parents[2]


def test_declared_environment_is_fully_locked_and_installed():
    project = tomllib.loads((_ROOT / 'pyproject.toml').read_text())['project']
    declared = list(project['dependencies'])
    for group in ('gui', 'test', 'dev', 'tools'):
        declared.extend(project['optional-dependencies'][group])

    locked = {}
    for raw in (_ROOT / 'requirements-lock.txt').read_text().splitlines():
        raw = raw.strip()
        if not raw or raw.startswith('#'):
            continue
        req = Requirement(raw)
        if req.marker and not req.marker.evaluate():
            continue
        assert str(req.specifier).startswith('=='), raw
        locked[req.name.lower()] = req

    missing = sorted(
        req.name for raw in declared
        if (req := Requirement(raw)).name.lower() not in locked)
    assert not missing, f'declared dependencies missing from lock: {missing}'

    mismatched = []
    for req in locked.values():
        try:
            installed = metadata.version(req.name)
        except metadata.PackageNotFoundError:
            installed = 'MISSING'
        if installed not in req.specifier:
            mismatched.append(f'{req.name} {req.specifier} (installed {installed})')
    assert not mismatched, 'environment differs from lock: ' + ', '.join(mismatched)
