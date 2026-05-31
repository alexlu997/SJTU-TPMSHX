"""UI behaviour mixins extracted from the ``Main_Menu`` god object.

Each mixin is a cohesive slice of ``main.Main_Menu`` that depends only on
``self`` (the live window) at call time, never on ``main`` module globals at
import time. This keeps the import graph acyclic (``main`` -> ``ui.mixins.*``,
never back) so mixins can be unit-tested against a lightweight fake window.

Adoption: ``class Main_Menu(RunHistoryMixin, ..., QMainWindow)``.
"""

from ui.mixins.run_history import RunHistoryMixin
from ui.mixins.dialogs import DialogsMixin
from ui.mixins.zone_panel import ZonePanelMixin

__all__ = ["RunHistoryMixin", "DialogsMixin", "ZonePanelMixin"]
