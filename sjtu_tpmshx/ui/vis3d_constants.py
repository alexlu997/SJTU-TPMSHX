"""vis3d_constants.py — shared constants + helpers for 3D visualisation.

Consolidates `FIELD_META` / `FIELD_ORDER` and the `vtkImplicitPlaneRepresentation`
cosmetic toning used by both the embedded `ui/panel_vis_3d.py` and the
standalone `ui/demo_vis_3d_interactive.py` so they stay in sync.
"""
from __future__ import annotations


# Display order + per-field rendering metadata.
# Matches 2D canvas convention (turbo for T/speed; coolwarm for solid; plasma for P).
# `Ta`/`vmag`/`P_kPa`/`L_mm` retained for backward compatibility with legacy
# callers (load_shanghai_demo, hover probe). The full 3D result now also feeds
# Tb / Ts / vmag_B / P_B_kPa when cross-flow fluid B has run.
FIELD_ORDER = [
    'Ta', 'Tb', 'Ts',
    'vmag', 'vmag_B',
    'P_kPa', 'P_B_kPa',
    'L_mm',
]
FIELD_META = {
    'Ta':      {'cmap': 'rainbow',  'title': 'T_a (K)',       'fmt': '%.1f',
                'label': 'Temperature A'},
    'Tb':      {'cmap': 'rainbow',  'title': 'T_b (K)',       'fmt': '%.1f',
                'label': 'Temperature B'},
    'Ts':      {'cmap': 'rainbow',  'title': 'T_s (K)',       'fmt': '%.1f',
                'label': 'Temperature Solid'},
    'vmag':    {'cmap': 'rainbow',  'title': 'speed A (m/s)', 'fmt': '%.2f',
                'label': 'Velocity A'},
    'vmag_B':  {'cmap': 'rainbow',  'title': 'speed B (m/s)', 'fmt': '%.2f',
                'label': 'Velocity B'},
    'P_kPa':   {'cmap': 'rainbow',  'title': 'P_A gauge (kPa)','fmt': '%.1f',
                'label': 'Pressure A'},
    'P_B_kPa': {'cmap': 'rainbow',  'title': 'P_B gauge (kPa)','fmt': '%.1f',
                'label': 'Pressure B'},
    'L_mm':    {'cmap': 'rainbow',  'title': 'L (mm)',         'fmt': '%.2f',
                'label': 'Design L'},
}


def tone_down_plane_widget(plotter, *,
                           slate=(0.30, 0.35, 0.40),
                           line_width=1.0, outline_opacity=0.45,
                           arrow_opacity=0.55):
    """Mute the `vtkImplicitPlaneWidget` cosmetics per Gemini review.

    - Hide the translucent plane handle (slice already renders the data).
    - Slate-grey outline + edges, half-opaque (not pitch-black, not bold).
    - Normal arrow half-opacity so data stays visually dominant.
    Robust against VTK API differences: every call is wrapped try/except.
    """
    try:
        widgets = list(getattr(plotter, 'plane_widgets', []))
    except Exception:
        return
    for w in widgets:
        try:
            rep = w.GetRepresentation()
        except Exception:
            continue
        _safe_setattr(rep, 'GetPlaneProperty', 'SetOpacity', 0.0)
        for g in ('GetOutlineProperty', 'GetEdgesProperty',
                  'GetSelectedOutlineProperty'):
            p = _safe_get(rep, g)
            if p is None:
                continue
            try:
                p.SetColor(*slate)
                p.SetLineWidth(line_width)
                p.SetOpacity(outline_opacity)
            except Exception:
                pass
        narrow = _safe_get(rep, 'GetNormalProperty')
        if narrow is not None:
            try:
                narrow.SetOpacity(arrow_opacity)
                narrow.SetColor(*slate)
            except Exception:
                pass


def _safe_get(rep, getter_name):
    getter = getattr(rep, getter_name, None)
    if getter is None:
        return None
    try:
        return getter()
    except Exception:
        return None


def _safe_setattr(rep, getter_name, setter_name, *args):
    prop = _safe_get(rep, getter_name)
    if prop is None:
        return
    setter = getattr(prop, setter_name, None)
    if setter is None:
        return
    try:
        setter(*args)
    except Exception:
        pass
