"""Human-friendly number formatters — SI prefixes, engineering notation.

Keeps callsites short: `si(192362, 'Pa') → '192.4 kPa'`.
"""
from __future__ import annotations

_SI_PREFIXES = [
    (1e12, 'T'), (1e9, 'G'), (1e6, 'M'),
    (1e3, 'k'),  (1.0, ''),   (1e-3, 'm'),
    (1e-6, 'μ'), (1e-9, 'n'),
]


def si(value, unit='', digits=3):
    """Format `value` with an SI prefix chosen to keep magnitude in [1, 1000).

    Bare unit if value is ~0 or not finite. Negative values handled.
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        return f"— {unit}".strip()
    if v != v or v == float('inf') or v == float('-inf'):  # NaN / Inf
        return f"— {unit}".strip()
    sign = '-' if v < 0 else ''
    a = abs(v)
    if a < 1e-15:
        return f"0 {unit}".strip()
    for mag, pref in _SI_PREFIXES:
        if a >= mag:
            scaled = a / mag
            if scaled >= 100:
                fmt = f"{scaled:.{max(0, digits - 3)}f}"
            elif scaled >= 10:
                fmt = f"{scaled:.{max(0, digits - 2)}f}"
            else:
                fmt = f"{scaled:.{max(0, digits - 1)}f}"
            return f"{sign}{fmt} {pref}{unit}".strip()
    return f"{v:.3g} {unit}".strip()


def pct(value, digits=1):
    """'+5.2%' / '-12.0%' / '0%' from a fraction (0.052 → '+5.2%')."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return '—'
    if abs(v) < 1e-5:
        return '0%'
    return f"{v * 100:+.{digits}f}%"


def duration(seconds):
    """'8.4s' / '2m15s' / '1h12m'."""
    try:
        s = float(seconds)
    except (TypeError, ValueError):
        return '—'
    if s < 60:
        return f"{s:.1f}s"
    if s < 3600:
        return f"{int(s // 60)}m{int(s % 60):02d}s"
    return f"{int(s // 3600)}h{int((s % 3600) // 60):02d}m"
