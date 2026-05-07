"""SessionManager — file-based session + preset persistence with versioning.

Phase 2 of 2026-05-06 main.py refactor (audit fix #4). Aggregates the IO
that was previously inlined in Main_Menu:

    Main_Menu method                  SessionManager method
    ──────────────────────────        ─────────────────────────────
    self._session_path(ws)            sm.session_path(ws)
    self._save_session()              sm.save_session(payload, ws)
    self._restore_session()           sm.load_session(ws)
    self._user_presets_path()         sm.presets_path()
    self._load_user_presets()         sm.load_user_presets()
    self._save_user_presets(presets)  sm.save_user_presets(presets)

File locations (unchanged from legacy):
    sjtu_tpmshx/.last_session.json        ← workspace A
    sjtu_tpmshx/.last_session_B.json      ← workspace B
    sjtu_tpmshx/.last_session_C.json      ← workspace C
    sjtu_tpmshx/.user_presets.json        ← named preset library
    sjtu_tpmshx/.workspace                ← single-char active workspace marker

Schema version (NEW)
--------------------
All session/preset payloads now include `schema_version` (currently 1).
Older files without the field are treated as v0 and silently migrated on
load (no field changes yet — version stamp is forward-compat only).

Future-proofing
---------------
`base_dir` is configurable. Default = package directory (legacy compat).
Future change: pass `~/.sjtu_tpmshx/` for multi-worktree isolation or
PyInstaller .exe packaging — single line override, no API change.

Phase 2 of 2026-05-06 plan #4 refactor.
See vault/reports/refactor/2026-05-06-main-py-refactor-plan-CN.md.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QObject, Signal


SCHEMA_VERSION = 1


class SessionManager(QObject):
    """Disk persistence for session state, user presets, and active workspace.

    Construct with no args to get the legacy package-dir layout:
        sm = SessionManager()              # base_dir = sjtu_tpmshx/
        sm = SessionManager(parent=window) # Qt parent for cleanup

    Or override base_dir for testing / future home-dir migration:
        sm = SessionManager(base_dir=tmp_path)

    Signals
    -------
    session_loaded(str workspace, dict payload)
        Emitted on successful load_session.
    session_saved(str workspace)
        Emitted on successful save_session.
    presets_changed()
        Emitted on save_user_presets (caller should rebuild combo).
    workspace_changed(str new_ws)
        Emitted on set_active_workspace.
    """

    SCHEMA_VERSION = SCHEMA_VERSION
    VALID_WORKSPACES = ('A', 'B', 'C')

    session_loaded = Signal(str, dict)
    session_saved = Signal(str)
    presets_changed = Signal()
    workspace_changed = Signal(str)

    def __init__(self, base_dir: Optional[os.PathLike] = None,
                 parent: Optional[QObject] = None):
        super().__init__(parent)
        if base_dir is None:
            # Default to package directory (legacy: sjtu_tpmshx/)
            base_dir = Path(__file__).resolve().parents[1]
        self._base = Path(base_dir)

    # ------------------------------------------------------------------ paths

    @property
    def base_dir(self) -> Path:
        return self._base

    def session_path(self, workspace: str = 'A') -> Path:
        """Path to .last_session_<ws>.json. Workspace A keeps legacy filename."""
        if workspace not in self.VALID_WORKSPACES:
            raise ValueError(
                f"unknown workspace: {workspace!r} "
                f"(expected one of {self.VALID_WORKSPACES})")
        if workspace == 'A':
            return self._base / '.last_session.json'
        return self._base / f'.last_session_{workspace}.json'

    def presets_path(self) -> Path:
        return self._base / '.user_presets.json'

    def workspace_marker_path(self) -> Path:
        return self._base / '.workspace'

    # ------------------------------------------------------------------ session

    def load_session(self, workspace: str = 'A') -> Optional[Dict[str, Any]]:
        """Return parsed session payload or None if file missing/malformed.

        Auto-migrates pre-v1 files (no schema_version field) on read by
        injecting `schema_version: 0` so caller can route by version.
        """
        path = self.session_path(workspace)
        if not path.exists():
            return None
        try:
            with open(path, 'r', encoding='utf-8') as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        # Schema migration: legacy files missing the field → v0
        payload.setdefault('schema_version', 0)
        # Future: payload = self._migrate(payload) ...
        self.session_loaded.emit(workspace, payload)
        return payload

    def save_session(self, payload: Dict[str, Any],
                     workspace: str = 'A') -> bool:
        """Write payload to disk. Returns True on success, False on IO error.

        Adds schema_version stamp before writing.
        """
        if not isinstance(payload, dict):
            raise TypeError(f"payload must be dict, got {type(payload).__name__}")
        out = dict(payload)
        out['schema_version'] = SCHEMA_VERSION
        path = self.session_path(workspace)
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(out, f, indent=2)
            self.session_saved.emit(workspace)
            return True
        except OSError:
            return False

    # ------------------------------------------------------------------ presets

    def load_user_presets(self) -> List[Dict[str, Any]]:
        """Return list of saved presets (possibly empty)."""
        path = self.presets_path()
        if not path.exists():
            return []
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return []
            presets = data.get('presets', [])
            return list(presets) if isinstance(presets, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def save_user_presets(self, presets: List[Dict[str, Any]]) -> bool:
        """Persist preset list. Returns True on success."""
        if not isinstance(presets, list):
            raise TypeError(
                f"presets must be list, got {type(presets).__name__}")
        try:
            with open(self.presets_path(), 'w', encoding='utf-8') as f:
                json.dump({'schema_version': SCHEMA_VERSION,
                           'presets': presets}, f, indent=2)
            self.presets_changed.emit()
            return True
        except OSError:
            return False

    # ------------------------------------------------------------------ workspace

    def get_active_workspace(self) -> str:
        """Read .workspace marker. Returns 'A' if missing/malformed."""
        path = self.workspace_marker_path()
        if not path.exists():
            return 'A'
        try:
            content = path.read_text(encoding='utf-8').strip().upper()
        except OSError:
            return 'A'
        return content if content in self.VALID_WORKSPACES else 'A'

    def set_active_workspace(self, workspace: str) -> bool:
        """Persist active workspace marker. Returns True on success."""
        if workspace not in self.VALID_WORKSPACES:
            raise ValueError(
                f"unknown workspace: {workspace!r} "
                f"(expected one of {self.VALID_WORKSPACES})")
        try:
            self.workspace_marker_path().write_text(
                workspace, encoding='utf-8')
            self.workspace_changed.emit(workspace)
            return True
        except OSError:
            return False

    # ------------------------------------------------------------------ misc

    def __repr__(self) -> str:
        return (f'<SessionManager base={self._base} '
                f'active_ws={self.get_active_workspace()} '
                f'schema_v{SCHEMA_VERSION}>')
