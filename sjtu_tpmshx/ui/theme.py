"""Theme system for SJTU-TPMSHX GUI (light-only)."""

# ── Shared sizing constants ─────────────────────────────────
FONT_HEADER = 11       # pt — header bar title
FONT_LABEL = 10        # pt — section labels, input labels
FONT_INPUT = 11        # pt — text input fields, combos
FONT_TAB = 9           # pt — tab buttons
FONT_BTN = 9           # pt — action buttons (TPMS, Auto-fill)
FONT_BTN_RUN = 12      # pt — primary Compute button
FONT_STATUS = 9        # pt — status bar text

BTN_H_PRIMARY = 32     # px — header buttons (Compute, Reset)
BTN_H_SECONDARY = 28   # px — tab buttons, toolbar actions
BTN_H_SMALL = 26       # px — TPMS compute, Auto-fill, Preview

RADIUS_BTN = 6         # px — buttons
RADIUS_CARD = 8        # px — canvas cards
RADIUS_INPUT = 6       # px — text inputs, combos
RADIUS_TAB = 14        # px — tab capsule buttons
RADIUS_HEADER = 8      # px — header bar

# ── Theme colour definitions ──────────────────────────────────
_THEMES = {
    'light': dict(
        bg="#f5f6f8", fg="#333333", val="#0066aa", warn="#cc4400",
        card_bg="#ffffff", card_border="#e8eaed", card_shadow="rgba(0,0,0,15)",
        scroll_bg="#f0f1f3",
        inp_bg="#ffffff", inp_fg="#1a1a2e", inp_border="#d1d5db",
        frame_border="rgba(0,0,0,0.04)", frame_neutral="255,255,255,60",
        frame_hot="197,90,17,12", frame_cold="46,117,182,12",
        t_neutral=("68,114,196","100,150,220"),
        t_hot=("197,90,17","230,130,60"),
        t_cold=("46,117,182","80,150,220"),
        btn_tpms=("68,114,196","100,150,220"),
        btn_run=("84,130,53","120,170,80"),
        combo_list_bg="#ffffff", combo_list_fg="#333333",
        combo_sel="rgba(68,114,196,100)", combo_border="rgba(0,0,0,20)",
        fig_bg="#ffffff", ax_bg="#ffffff",
        ax_text="#333333", ax_spine="#cccccc", zone_line="#666666",
        zone_fill="#4472c4", poly_fill="#e8e8e8", splitter="rgba(0,0,0,25)",
        hdr_bg="#4472c4", hdr_fg="white",
        tab_on_bg="#2c5282", tab_on_fg="white", tab_on_border="#2c5282",
        tab_off_bg="transparent", tab_off_fg="#6b7280", tab_off_border="#d1d5db",
        tab_off_hover="#eef0f3",
        prog_bg="rgba(0,0,0,15)", prog_border="rgba(0,0,0,20)",
        slider_groove="rgba(0,0,0,30)", slider_handle="rgba(0,0,0,120)",
        slider_sub="rgba(68,114,196,120)",
    ),
}


def _build_styles():
    """Build all Qt stylesheet tokens for the light theme."""
    t = _THEMES['light']
    s = {}
    s['BG'] = t['bg']
    s['LBL'] = (f"color:{t['fg']}; font-size:{FONT_LABEL}pt; font-weight:bold;"
                "border:none; background:transparent;")
    s['VAL'] = (f"color:{t['val']}; font-size:{FONT_INPUT}pt; font-weight:bold;"
                "border:none; background:transparent;")
    s['VAL_WARN'] = (f"color:{t['warn']}; font-size:{FONT_INPUT}pt; font-weight:bold;"
                     "border:none; background:transparent;")
    s['INP'] = (f"background:{t['inp_bg']}; color:{t['inp_fg']};"
                f"border:1px solid {t['inp_border']}; border-radius:{RADIUS_INPUT}px;"
                f"font-size:{FONT_INPUT}pt; font-weight:bold; padding:4px 8px; min-width:60px;"
                f"selection-background-color:rgba(68,114,196,80);")
    s['INP_FOCUS'] = (f"border:2px solid rgba(68,114,196,180);")
    def _title(rgb, border):
        return (f"QLabel{{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
                f"stop:0 rgba({rgb},200), stop:1 rgba({rgb},160));"
                f"border:1px solid rgba({border},180);"
                f"border-radius:6px; color:white; font-weight:bold; font-size:{FONT_LABEL}pt;"
                "padding:5px 0; letter-spacing:0.5px;}")
    def _frame(rgba):
        return (f"QFrame{{background:rgba({rgba}); border:1px solid {t['frame_border']};"
                f"border-radius:8px; padding:3px;}}")
    s['T_NEUTRAL'] = _title(*t['t_neutral'])
    s['T_HOT']     = _title(*t['t_hot'])
    s['T_COLD']    = _title(*t['t_cold'])
    s['F_NEUTRAL'] = _frame(t['frame_neutral'])
    s['F_HOT']     = _frame(t['frame_hot'])
    s['F_COLD']    = _frame(t['frame_cold'])
    _btn = (f"border-radius:{RADIUS_BTN}px; color:white; font-weight:bold; font-size:{FONT_BTN}pt;"
            "padding:4px 10px;")
    def _btn_style(rgb, brd):
        return (f"QPushButton{{{_btn}"
                f"background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
                f"stop:0 rgba({rgb},210), stop:1 rgba({rgb},180));"
                f"border:1px solid rgba({brd},160);}}"
                f"QPushButton:hover{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
                f"stop:0 rgba({rgb},235), stop:1 rgba({rgb},205));}}"
                f"QPushButton:pressed{{background:rgba({rgb},250);"
                f"border:1px solid rgba({brd},220);}}")
    s['BTN_HOT']  = _btn_style(*t['t_hot'])
    s['BTN_COLD'] = _btn_style(*t['t_cold'])
    s['BTN_TPMS'] = _btn_style(*t['btn_tpms'])
    r, b = t['btn_run']
    s['BTN_RUN']  = (f"QPushButton{{{_btn} font-size:{FONT_BTN_RUN}pt; padding:6px 16px;"
                     f"background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
                     f"stop:0 rgba({r},220), stop:1 rgba({r},185));"
                     f"border:1px solid rgba({b},180); border-radius:{RADIUS_CARD}px;}}"
                     f"QPushButton:hover{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
                     f"stop:0 rgba({r},245), stop:1 rgba({r},210));}}"
                     f"QPushButton:pressed{{background:rgba({r},255);}}")
    _ac = "80,80,80"
    s['COMBO'] = (
        f"QComboBox{{color:{t['inp_fg']}; background:{t['inp_bg']};"
        f"border:1px solid {t['inp_border']}; border-radius:{RADIUS_INPUT}px;"
        "font-size:11pt; font-weight:bold; padding:3px 24px 3px 6px;}"
        f"QComboBox:hover{{border:2px solid rgba(68,114,196,180);}}"
        f"QComboBox::drop-down{{subcontrol-origin:padding; subcontrol-position:top right;"
        f"width:22px; border-left:1px solid {t['inp_border']};"
        "border-top-right-radius:4px; border-bottom-right-radius:4px;"
        f"background:rgba({_ac},30);}}"
        f"QComboBox::down-arrow{{"
        f"border-left:5px solid transparent; border-right:5px solid transparent;"
        f"border-top:6px solid rgba({_ac},200);"
        "width:0; height:0;}"
        f"QComboBox QAbstractItemView{{"
        f"background:{t['combo_list_bg']}; color:{t['combo_list_fg']};"
        f"font-size:{FONT_INPUT}pt; font-weight:bold;"
        f"selection-background-color:{t['combo_sel']};"
        f"border:1px solid {t['combo_border']};"
        "border-radius:4px; padding:2px; outline:none;}")
    return s
