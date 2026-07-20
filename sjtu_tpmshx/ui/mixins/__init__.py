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
from ui.mixins.optimize_ui import OptimizeUIMixin
from ui.mixins.tab_view import TabViewMixin
from ui.mixins.ui_builder import UIBuilderMixin
from ui.mixins.fluid_input import FluidInputMixin
from ui.mixins.run_controller import RunControllerMixin
from ui.mixins.run_results import RunResultsMixin
from ui.mixins.appearance import AppearanceMixin
from ui.mixins.session_presets import SessionPresetsMixin
from ui.mixins.shortcuts import ShortcutsMixin
from ui.mixins.io_actions import IOActionsMixin
from ui.mixins.result_bridge import ResultBridgeMixin

__all__ = ["RunHistoryMixin", "DialogsMixin", "ZonePanelMixin", "OptimizeUIMixin", "TabViewMixin", "UIBuilderMixin", "FluidInputMixin", "RunControllerMixin", "RunResultsMixin", "AppearanceMixin", "SessionPresetsMixin", "ShortcutsMixin", "IOActionsMixin", "ResultBridgeMixin"]
