"""Theme system for ThermoNAS GUI (light-only).

Originally extracted from main.py (Task B.3) with light + dark themes and a
runtime toggle. Per D-1 decision, dark theme + apply_theme() were removed —
the GUI is light-only. `_THEMES` is kept as a single-entry dict so existing
call sites that index `_THEMES['light']` keep working unchanged.
"""

# ── Theme colour definitions ──────────────────────────────────
_THEMES = {
    'light': dict(
        bg="#eaeaea", fg="#333333", val="#0066aa", warn="#cc4400",
        card_bg="#F7F8FA", card_border="#E0E0E0", card_shadow="rgba(0,0,0,40)",
        scroll_bg="#EDEEEF",
        inp_bg="rgba(255,255,255,220)", inp_fg="#1a1a2e", inp_border="#cccccc",
        frame_border="rgba(0,0,0,10)", frame_neutral="255,255,255,60",
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
        tab_on_bg="#4472c4", tab_on_fg="white", tab_on_border="#3a62a4",
        tab_off_bg="#d5d8dc", tab_off_fg="#1a1f24", tab_off_border="#b3b8bd",
        tab_off_hover="#bfc4c9",
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
    s['LBL'] = (f"color:{t['fg']}; font-size:10pt; font-weight:bold;"
                "border:none; background:transparent;")
    s['VAL'] = (f"color:{t['val']}; font-size:11pt; font-weight:bold;"
                "border:none; background:transparent;")
    s['VAL_WARN'] = (f"color:{t['warn']}; font-size:11pt; font-weight:bold;"
                     "border:none; background:transparent;")
    s['INP'] = (f"background:{t['inp_bg']}; color:{t['inp_fg']};"
                f"border:1px solid {t['inp_border']}; border-radius:4px;"
                "font-size:11pt; font-weight:bold; padding:4px 8px; min-width:60px;"
                f"selection-background-color:rgba(68,114,196,80);")
    s['INP_FOCUS'] = (f"border:2px solid rgba(68,114,196,180);")
    def _title(rgb, border):
        return (f"QLabel{{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
                f"stop:0 rgba({rgb},200), stop:1 rgba({rgb},160));"
                f"border:1px solid rgba({border},180);"
                "border-radius:6px; color:white; font-weight:bold; font-size:10pt;"
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
    _btn = ("border-radius:6px; color:white; font-weight:bold; font-size:9pt;"
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
    s['BTN_RUN']  = (f"QPushButton{{{_btn} font-size:12pt; padding:6px 16px;"
                     f"background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
                     f"stop:0 rgba({r},220), stop:1 rgba({r},185));"
                     f"border:1px solid rgba({b},180); border-radius:8px;}}"
                     f"QPushButton:hover{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
                     f"stop:0 rgba({r},245), stop:1 rgba({r},210));}}"
                     f"QPushButton:pressed{{background:rgba({r},255);}}")
    _ac = "80,80,80" if t is _THEMES['light'] else "200,200,200"
    s['COMBO'] = (
        f"QComboBox{{color:{t['inp_fg']}; background:{t['inp_bg']};"
        f"border:1px solid {t['inp_border']}; border-radius:4px;"
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
        "font-size:11pt; font-weight:bold;"
        f"selection-background-color:{t['combo_sel']};"
        f"border:1px solid {t['combo_border']};"
        "border-radius:4px; padding:2px; outline:none;}")
    return s
