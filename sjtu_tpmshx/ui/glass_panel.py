"""Background image generator for the dark glassmorphism theme.

Exposes `generate_blurred_bg(width, height)` which produces a static,
pre-blurred gradient + grain QPixmap used as the main window's palette
brush. A previous `GlassPanel` widget was removed — no translucent
paintEvent is needed once the window background carries the mood.
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QColor, QLinearGradient, QRadialGradient


def generate_blurred_bg(width=1920, height=1080):
    """Generate a static pre-blurred gradient image for dark theme background.

    Returns QPixmap. Called once at app startup; cached as window background.
    Base: diagonal gradient from #08090A → #0D1526 → #08090A.
    Overlay: soft colored glow orbs + film-grain noise (Linear / Arc / Raycast
    aesthetic — research-tool seriousness without flat OLED black).
    """
    from PySide6.QtGui import QPixmap, QImage
    from PySide6.QtCore import QPoint

    img = QImage(width, height, QImage.Format.Format_RGB32)
    painter = QPainter(img)

    # Diagonal base — 4-stop, cooler mid so the panel chrome reads as
    # floating over depth rather than a flat OLED black.
    grad = QLinearGradient(QPoint(0, 0), QPoint(width, height))
    grad.setColorAt(0.0, QColor('#070809'))
    grad.setColorAt(0.42, QColor('#0C1322'))
    grad.setColorAt(0.64, QColor('#0B0F1A'))
    grad.setColorAt(1.0, QColor('#070809'))
    painter.fillRect(img.rect(), grad)

    # Soft colored glow orbs — radial falloff (no hard ellipse edge), two
    # cool hues for a richer-but-restrained depth. Alphas stay ≤16/255.
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    for cx, cy, r, rgb, alpha in [
        (0.18, 0.22, 520, (59, 130, 246), 16),   # blue, top-left
        (0.82, 0.30, 460, (99, 102, 241), 12),    # indigo, top-right
        (0.62, 0.78, 600, (45, 130, 170), 10),    # cool teal, lower
    ]:
        ox, oy = cx * width, cy * height
        rg = QRadialGradient(ox, oy, r)
        rg.setColorAt(0.0, QColor(rgb[0], rgb[1], rgb[2], alpha))
        rg.setColorAt(1.0, QColor(rgb[0], rgb[1], rgb[2], 0))
        painter.setBrush(rg)
        painter.drawEllipse(int(ox - r), int(oy - r), r * 2, r * 2)

    # Vignette — transparent center, gentle darken at the corners so the
    # eye settles on the central viewport. Very low alpha; pure focus aid.
    vig = QRadialGradient(width * 0.5, height * 0.42, max(width, height) * 0.78)
    vig.setColorAt(0.0, QColor(0, 0, 0, 0))
    vig.setColorAt(0.72, QColor(0, 0, 0, 0))
    vig.setColorAt(1.0, QColor(0, 0, 0, 55))
    painter.setBrush(vig)
    painter.drawRect(img.rect())
    painter.end()

    # Film-grain noise overlay. Generated once, blended at ~4% opacity —
    # enough to break up the flat gradient without competing with UI.
    # Uses numpy + direct QImage bit-twiddling to avoid drawing 2M dots.
    try:
        import numpy as _np
        rng = _np.random.default_rng(42)
        # Coarse 3× downscaled noise then nearest-upsample for a softer,
        # film-stock grain rather than TV static.
        nw, nh = width // 3, height // 3
        noise = rng.integers(0, 12, size=(nh, nw), dtype=_np.uint8)
        noise_up = _np.repeat(_np.repeat(noise, 3, axis=0), 3, axis=1)
        # Clip to exact size (repeat may over-shoot)
        noise_up = noise_up[:height, :width]

        ptr = img.bits()
        arr = _np.frombuffer(ptr, dtype=_np.uint8).reshape(height, width, 4)
        # BGRA on Windows. Add noise to R, G, B channels equally for gray
        # grain. Clip to 255.
        grain = noise_up.astype(_np.int16)
        for ch in (0, 1, 2):
            arr[:, :, ch] = _np.clip(
                arr[:, :, ch].astype(_np.int16) + grain, 0, 255
            ).astype(_np.uint8)
    except Exception:
        pass  # grain is cosmetic; skip on numpy-less builds

    return QPixmap.fromImage(img)
