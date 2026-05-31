"""Zoned-heterogeneous-TPMS panel handlers for ``Main_Menu``.

Extracted from the ``main`` god object: the per-region zone editor's
button/combo handlers (add/remove row & column, mode switch, 1-D init,
axis query) plus the zone-config builder. Every method is a thin delegator
to ``solvers.zone_editor`` — the real table/grid logic lives there and reads
the live window through ``self``. Moving these out of main.Main_Menu changes
no behaviour: ``zone_editor`` wires its buttons to ``window._zone_*`` and
those names still resolve on the window via the MRO.

Adopted via ``class Main_Menu(..., ZonePanelMixin, ..., QMainWindow)``.
No solver / numeric path. No module-level imports — every handler imports
its ``zone_editor`` callable lazily, exactly as the originals did.
"""

from __future__ import annotations


class ZonePanelMixin:
    """Zone-editor UI handlers (delegate to ``solvers.zone_editor``)."""

    def _zone_mode_changed(self, idx):
        from solvers.zone_editor import zone_mode_changed
        return zone_mode_changed(self, idx)

    def _zone_init_1d(self, n):
        from solvers.zone_editor import zone_init_1d
        return zone_init_1d(self, n)

    def _zone_add_row(self):
        from solvers.zone_editor import zone_add_row
        return zone_add_row(self)

    def _zone_remove_row(self):
        from solvers.zone_editor import zone_remove_row
        return zone_remove_row(self)

    def _zone_add_col(self):
        from solvers.zone_editor import zone_add_col
        return zone_add_col(self)

    def _zone_remove_col(self):
        from solvers.zone_editor import zone_remove_col
        return zone_remove_col(self)

    def _zone_axis(self):
        from solvers.zone_editor import zone_axis
        return zone_axis(self)

    def _build_zone_config(self):
        from solvers.zone_editor import build_zone_config
        return build_zone_config(self)
