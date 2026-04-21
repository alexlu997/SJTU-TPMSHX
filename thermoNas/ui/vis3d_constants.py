"""vis3d_constants.py — shared constants + helpers for 3D visualisation.

Consolidates `FIELD_META` / `FIELD_ORDER` and the `vtkImplicitPlaneRepresentation`
cosmetic toning used by both the embedded `ui/panel_vis_3d.py` and the
standalone `ui/demo_vis_3d_interactive.py` so they stay in sync.
"""
from __future__ import annotations


# Display order + per-field rendering metadata.
# Matches 2D canvas convention (turbo for T/speed/P; cividis for design field).
FIELD_ORDER = ['Ta', 'vmag', 'P_kPa', 'L_mm']
FIELD_META = {
    'Ta':    {'cmap': 'turbo',   'title': 'T_a (K)',       'fmt': '%.1f',
              'label': 'Temperature'},
    'vmag':  {'cmap': 'turbo',   'title': 'speed (m/s)',   'fmt': '%.1f',
              'label': 'Speed'},
    'P_kPa': {'cmap': 'turbo',   'title': 'P gauge (kPa)', 'fmt': '%.1f',
              'label': 'Pressure'},
    'L_mm':  {'cmap': 'cividis', 'title': 'L (mm)',        'fmt': '%.2f',
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
