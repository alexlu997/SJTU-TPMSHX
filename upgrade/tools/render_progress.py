# -*- coding: utf-8 -*-
"""升级循环进度页渲染器（2026-07-20，应 Alex 要求）。

把 upgrade/ 的四个状态文件（STATE / ROADMAP / PROGRESS / DECISIONS-NEEDED）
渲染成一张自包含 HTML 进度页，版式沿用 reports/sco2_exp/sco2_exp_vs_cfd.v2.html
的"瑞士网格编辑风"（纯白底、黑标尺、瑞士红单强调）。

用法（仓库根）::

    python upgrade/tools/render_progress.py            # → upgrade/progress.html
    python upgrade/tools/render_progress.py --out X.html

无第三方依赖；数据即状态文件本身——本脚本只做解析与排版，不产生新事实。
循环每轮收尾时重渲一次（PROTOCOL §9），页面始终反映最新迭代。
"""
from __future__ import annotations

import argparse
import html
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent          # upgrade/tools
_UPG = _TOOLS.parent                              # upgrade/
_REPO = _UPG.parent                               # repo root


# ── 解析层 ────────────────────────────────────────────────────────────────

def _read(name: str) -> str:
    return (_UPG / name).read_text(encoding='utf-8')


def parse_state() -> dict:
    d = {}
    for m in re.finditer(r'^- (\w+): (.+)$', _read('STATE.md'), re.M):
        d[m.group(1)] = m.group(2).strip()
    m = re.search(r'^- 基点：(.+)$', _read('STATE.md'), re.M)
    d['base'] = m.group(1).strip() if m else '—'
    return d


def parse_roadmap() -> list[dict]:
    """→ [{title, items:[{mark,text,sub:[...]}, ...]}, ...]（含收尾节）。"""
    phases, cur, item = [], None, None
    for ln in _read('ROADMAP.md').splitlines():
        m = re.match(r'^## (Phase \d+.+|收尾（.+)$', ln)
        if m:
            cur = {'title': m.group(1).rstrip('）') + ('）' if '（' in m.group(1) and not m.group(1).endswith('）') else ''),
                   'items': [], 'candidate': '候选池' in m.group(1)}
            phases.append(cur)
            item = None
            continue
        if cur is None:
            continue
        m = re.match(r'^- \[([x~ ])\] (.+)$', ln)
        if m:
            item = {'mark': m.group(1), 'text': m.group(2), 'sub': []}
            cur['items'].append(item)
            continue
        m = re.match(r'^  - \[([x~ ])\] (.+)$', ln)
        if m and item is not None:
            item['sub'].append({'mark': m.group(1), 'text': m.group(2)})
            continue
        if item is not None and re.match(r'^\s{2,}\S', ln):
            tgt = item['sub'][-1] if item['sub'] else item
            tgt['text'] += ' ' + ln.strip()
    return phases


def parse_progress() -> list[dict]:
    """→ [{num, date, title, bullets:[...]}, ...] 按文件顺序（新在前）。"""
    entries = []
    cur = None
    for ln in _read('PROGRESS.md').splitlines():
        m = re.match(r'^## iter (\d+[a-z]?) · ([0-9-]+) · (.+)$', ln)
        if m:
            cur = {'num': m.group(1), 'date': m.group(2),
                   'title': m.group(3).strip(), 'bullets': []}
            entries.append(cur)
            continue
        if cur is None:
            continue
        if re.match(r'^- ', ln):
            cur['bullets'].append(ln[2:].strip())
        elif re.match(r'^\s{2,}\S', ln) and cur['bullets']:
            cur['bullets'][-1] += ' ' + ln.strip()
    return entries


def parse_decisions() -> list[dict]:
    out = []
    txt = _read('DECISIONS-NEEDED.md')
    blocks = re.split(r'^## ', txt, flags=re.M)[1:]
    for b in blocks:
        head, _, body = b.partition('\n')
        m = re.match(r'(D\d+) · ([0-9-]+) · \[([^\]]+)\] (.+)$', head.strip())
        if not m:
            continue
        rec = re.search(r'\*\*循环的建议\*\*：(.+)$', body, re.M)
        st = re.search(r'\*\*状态\*\*：(.+)$', body, re.M)
        out.append({'id': m.group(1), 'date': m.group(2), 'tag': m.group(3),
                    'title': m.group(4).strip(),
                    'rec': rec.group(1).strip() if rec else '',
                    'status': st.group(1).strip() if st else m.group(3)})
    return out


def git_facts() -> dict:
    def _run(*args):
        try:
            r = subprocess.run(['git', *args], cwd=str(_REPO), timeout=15,
                               capture_output=True, text=True, encoding='utf-8')
            return r.stdout.strip() if r.returncode == 0 else ''
        except Exception:
            return ''
    return {
        'branch': _run('rev-parse', '--abbrev-ref', 'HEAD') or '—',
        'head': _run('rev-parse', '--short', 'HEAD') or '—',
        'n_ahead': _run('rev-list', '--count', 'master..HEAD') or '—',
        'head_date': (_run('log', '-1', '--format=%cd', '--date=format:%Y-%m-%d %H:%M') or '—'),
    }


def latest_gate_evidence(entries: list[dict]) -> str:
    """从最新往旧扫 PROGRESS 正文，找最近一次套件计数证据。"""
    pat = re.compile(r'(?:suite|套件)\s*([0-9]{3,4})(?:\+([0-9]+))?\s*(?:绿|passed)')
    for e in entries:
        for b in e['bullets']:
            m = pat.search(b)
            if m:
                extra = f'+{m.group(2)}' if m.group(2) else ''
                return f"{m.group(1)}{extra} 绿（iter {e['num']}）"
    return '—'


# ── 渲染层 ────────────────────────────────────────────────────────────────

def _fmt(s: str) -> str:
    """转义后恢复 `code` / **b**；行内保持原文其余符号。"""
    s = html.escape(s, quote=False)
    s = re.sub(r'`([^`]+)`', r'<code>\1</code>', s)
    s = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', s)
    return s


_MARK = {'x': ('done', '✓ 完成'), '~': ('prog', '⟳ 进行中'), ' ': ('todo', '待办')}


def render(out_path: Path) -> None:
    state = parse_state()
    phases = parse_roadmap()
    iters = parse_progress()
    decisions = parse_decisions()
    g = git_facts()
    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    gate = latest_gate_evidence(iters)
    n_pending = sum(1 for d in decisions if '待决' in d['status'])

    done_all = sum(1 for p in phases for i in p['items']
                   if i['mark'] == 'x' and not p.get('candidate'))
    tot_all = sum(len(p['items']) for p in phases if not p.get('candidate'))

    # 02 路线图
    ph_html = []
    for k, p in enumerate(phases):
        cand = p.get('candidate', False)
        done = sum(1 for i in p['items'] if i['mark'] == 'x')
        tot = len(p['items'])
        pct = int(round(100 * done / tot)) if tot else 0
        rows = []
        for it in p['items']:
            cls, lab = ('todo', '候选') if cand else _MARK[it['mark']]
            first = re.split(r'[：:]', it['text'], 1)[0]
            rest = it['text'][len(first):].lstrip('：:').strip()
            if len(rest) > 150:
                rest = rest[:150] + '…'
            sub = ''
            if it['sub']:
                li = ''.join(
                    f"<li><span class='chip {_MARK[s['mark']][0]}'>{_MARK[s['mark']][1]}</span> "
                    f"{_fmt(s['text'][:130] + ('…' if len(s['text']) > 130 else ''))}</li>"
                    for s in it['sub'])
                sub = f"<ul class='subitems'>{li}</ul>"
            rows.append(
                f"<tr><td class='pid'>{_fmt(first)}</td>"
                f"<td class='pst'><span class='chip {cls}'>{lab}</span></td>"
                f"<td>{_fmt(rest)}{sub}</td></tr>")
        meter = (f"<span class='ph-n'>未章程化 · 收尾时挑选</span>" if cand else
                 f"<span class='ph-n'>{done}/{tot}</span>"
                 f"<span class='bar'><span class='fill' style='width:{pct}%'></span></span>")
        ph_html.append(
            f"<div class='phase rv'><div class='ph-head'><h3>{_fmt(p['title'])}</h3>"
            f"<div class='ph-meter'>{meter}</div></div>"
            f"<table class='spec ptable'><thead><tr><th style='width:96px'>条目</th>"
            f"<th style='width:92px'>状态</th><th>内容</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div>")

    # 03 时间线
    it_html = []
    for e in iters:
        title = _fmt(re.sub(r'\s*✅\s*', ' ', e['title']).strip())
        lis = ''.join(f'<li>{_fmt(b)}</li>' for b in e['bullets'])
        docs_only = ('docs-only' in e['title']) or ('盘点' in e['title']) or ('评估' in e['title'])
        it_html.append(
            f"<div class='iter rv{' code' if not docs_only else ''}'>"
            f"<div class='ino'><span class='n'>{e['num']}</span>"
            f"<span class='idate'>{e['date']}</span></div>"
            f"<div class='ibody'><h3>{title}</h3><ul>{lis}</ul></div></div>")

    # 04 待决
    dec_html = []
    for d in decisions:
        open_ = '待决' in d['status']
        cls = 'open' if open_ else 'closed'
        rec = f"<div class='drec'><span class='k'>循环建议</span>{_fmt(d['rec'])}</div>" if d['rec'] and open_ else ''
        st = f"<div class='drec'><span class='k'>状态</span>{_fmt(d['status'])}</div>" if not open_ else ''
        dec_html.append(
            f"<div class='dcard {cls} rv'><div class='dhead'>"
            f"<span class='did'>{d['id']}</span>"
            f"<span class='chip {'prog' if open_ else 'done'}'>{'待 Alex 决策' if open_ else '已决'}</span>"
            f"<span class='ddate'>{d['date']}</span></div>"
            f"<div class='dtitle'>{_fmt(d['title'])}</div>{rec}{st}</div>")

    in_prog = state.get('in_progress', '无')
    doc = f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SJTU-TPMSHX 升级循环 · 迭代进度</title>
<style>
:root {{
  /* 瑞士网格编辑风——版式令牌与 sco2_exp_vs_cfd.v2.html 同源 */
  --paper:#FFFFFF; --ink:#141414; --red:#E2001A;
  --g50:#FAFAF9; --g100:#F4F3F0; --g200:#E7E5DF; --g300:#CFCBC2;
  --g500:#78746C; --g700:#3E3C37;
  --head:"Microsoft YaHei","Segoe UI",sans-serif;
  --body:"Microsoft YaHei","Segoe UI",system-ui,sans-serif;
  --mono:Consolas,"Cascadia Mono",ui-monospace,monospace;
  --measure:46em;
}}
* {{ box-sizing:border-box; }}
html {{ scroll-behavior:smooth; }}
body {{ margin:0; background:var(--paper); color:var(--ink);
       font-family:var(--body); font-size:16px; line-height:1.65;
       -webkit-font-smoothing:antialiased; }}
::selection {{ background:var(--red); color:#fff; }}
a {{ color:inherit; }}
code {{ font-family:var(--mono); font-size:.86em; background:var(--g100); padding:1px 5px; }}
.progress {{ position:fixed; top:0; left:0; right:0; height:2.5px; z-index:70;
            background:var(--red); transform-origin:0 50%; transform:scaleX(0); }}
.minibar {{ position:fixed; top:0; left:0; right:0; z-index:60; height:54px;
           display:flex; align-items:center; gap:28px; padding:0 44px;
           background:rgba(255,255,255,.94); border-bottom:1px solid var(--g200);
           transform:translateY(-100%); transition:transform .35s cubic-bezier(.2,.65,.25,1); }}
.minibar.on {{ transform:none; }}
.minibar .mt {{ font-family:var(--mono); font-size:11px; letter-spacing:.08em;
               color:var(--g500); white-space:nowrap; }}
.minibar nav {{ display:flex; gap:2px; margin-left:auto; }}
.minibar nav a {{ font-family:var(--head); font-weight:700; font-size:12.5px;
                 color:var(--g500); text-decoration:none; padding:6px 10px;
                 border-bottom:2px solid transparent; transition:.2s; }}
.minibar nav a:hover {{ color:var(--ink); }}
.minibar nav a.active {{ color:var(--ink); border-bottom-color:var(--red); }}
@media (max-width:900px){{ .minibar{{padding:0 18px}} .minibar .mt{{display:none}} }}
.wrap {{ max-width:1180px; margin:0 auto; padding:0 44px 110px; }}
@media (max-width:640px){{ .wrap{{ padding:0 20px 80px; }} }}
.masthead {{ padding:76px 0 0; }}
.eyebrow {{ font-family:var(--mono); font-size:11.5px; letter-spacing:.1em;
           color:var(--g500); display:flex; align-items:center; gap:12px; margin-bottom:26px; }}
.eyebrow::before {{ content:""; width:30px; height:3px; background:var(--red); }}
h1 {{ font-family:var(--head); font-weight:700; margin:0;
     font-size:clamp(36px,5.4vw,60px); line-height:1.08; letter-spacing:-.015em;
     max-width:24ch; text-wrap:balance; }}
h1 em {{ font-style:normal; color:var(--red); }}
.intro {{ font-size:15.5px; color:var(--g700); max-width:var(--measure); margin:24px 0 0; }}
.facts {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr));
         border-top:2.5px solid var(--ink); margin-top:46px; }}
.facts .row {{ padding:14px 18px 12px 0; }}
.facts .row + .row {{ border-left:1px solid var(--g200); padding-left:18px; }}
.facts .k {{ display:block; font-family:var(--mono); font-size:10.5px;
            letter-spacing:.07em; color:var(--g500); margin-bottom:4px; }}
.facts .v {{ font-size:14px; font-variant-numeric:tabular-nums; }}
.facts .v b {{ color:var(--red); font-weight:700; }}
@media (max-width:640px){{
  .facts{{ grid-template-columns:1fr 1fr; }}
  .facts .row + .row{{ border-left:none; padding-left:0; }}
  .facts .row:nth-child(even){{ border-left:1px solid var(--g200); padding-left:18px; }} }}
.tocpage {{ margin-top:84px; }}
.tocpage .lab {{ font-family:var(--mono); font-size:11px; letter-spacing:.1em;
                color:var(--g500); margin-bottom:6px; }}
.tocpage ol {{ list-style:none; margin:0; padding:0; border-bottom:1px solid var(--g200); }}
.tocpage li {{ border-top:1px solid var(--g200); }}
.tocpage li:first-child {{ border-top:2.5px solid var(--ink); }}
.tocpage a {{ display:grid; grid-template-columns:70px 1fr 30px; gap:18px;
             align-items:baseline; padding:20px 0; text-decoration:none; }}
.tocpage .n {{ font-family:var(--mono); font-size:13px; color:var(--red); }}
.tocpage .t {{ font-family:var(--head); font-weight:700; font-size:22px;
              transition:transform .25s cubic-bezier(.2,.65,.25,1); display:block; }}
.tocpage .tdesc {{ display:block; font-size:12.5px; color:var(--g500); margin-top:3px; }}
.tocpage .arr {{ color:var(--g300); font-size:18px; justify-self:end; transition:.25s; }}
.tocpage a:hover .t {{ transform:translateX(8px); }}
.tocpage a:hover .arr {{ color:var(--red); transform:translateX(4px); }}
@media (max-width:640px){{ .tocpage a{{ grid-template-columns:48px 1fr 24px; padding:14px 0; }}
  .tocpage .t{{ font-size:17px; }} }}
section {{ margin-top:110px; scroll-margin-top:76px; }}
.sec-head {{ display:flex; align-items:baseline; gap:26px;
            border-bottom:2.5px solid var(--ink); padding-bottom:16px; margin-bottom:30px; }}
.sec-head .idx {{ font-family:var(--head); font-weight:700;
                 font-size:clamp(64px,8vw,96px); line-height:.8; color:var(--g200);
                 letter-spacing:-.04em; user-select:none; }}
.sec-head h2 {{ font-family:var(--head); font-weight:700; font-size:26px; margin:0; }}
.sec-intro {{ font-size:15px; color:var(--g700); max-width:var(--measure); margin:-8px 0 36px; }}
.speclist {{ border-top:2px solid var(--ink); margin:26px 0 18px; }}
.speclist .srow {{ display:grid; grid-template-columns:112px 1fr; gap:26px;
                  padding:15px 0; border-bottom:1px solid var(--g200); }}
.speclist .srow:last-child {{ border-bottom:none; }}
.speclist .sk {{ font-family:var(--mono); font-size:11px; color:var(--red);
                letter-spacing:.05em; padding-top:2px; }}
.speclist .sv {{ font-size:14px; color:var(--g700); }}
@media (max-width:560px){{ .speclist .srow{{ grid-template-columns:1fr; gap:4px; }} }}
.callout {{ border-left:4px solid var(--red); background:var(--g50);
           padding:14px 18px; margin-top:14px; font-size:13.5px;
           color:var(--g700); max-width:var(--measure); }}
.callout b {{ color:var(--ink); }}
table.spec {{ width:100%; border-collapse:collapse; font-size:13.5px; margin:0; }}
.spec th {{ text-align:left; font-family:var(--mono); font-size:11px;
           color:var(--g500); font-weight:400; padding:8px 14px 8px 0;
           border-bottom:1.5px solid var(--ink); }}
.spec td {{ padding:11px 14px 11px 0; border-bottom:1px solid var(--g200); vertical-align:top; }}
.spec tr:hover td {{ background:var(--g50); }}
.chip {{ display:inline-block; font-family:var(--mono); font-size:10.5px;
        letter-spacing:.04em; padding:2px 8px; white-space:nowrap; }}
.chip.done {{ background:var(--ink); color:#fff; }}
.chip.prog {{ background:var(--red); color:#fff; }}
.chip.todo {{ background:var(--g100); color:var(--g500); border:1px solid var(--g200); }}
.phase {{ margin-bottom:44px; }}
.ph-head {{ display:flex; align-items:baseline; gap:22px; margin-bottom:10px; }}
.ph-head h3 {{ font-family:var(--head); font-size:17px; margin:0; }}
.ph-meter {{ display:flex; align-items:center; gap:10px; margin-left:auto; min-width:210px; }}
.ph-n {{ font-family:var(--mono); font-size:11.5px; color:var(--g500); }}
.bar {{ flex:1; height:6px; background:var(--g100); position:relative; }}
.bar .fill {{ position:absolute; inset:0 auto 0 0; background:var(--ink); }}
.ptable td.pid {{ font-family:var(--mono); font-size:12px; white-space:nowrap; color:var(--ink); font-weight:700; }}
.ptable td {{ font-size:13px; color:var(--g700); }}
ul.subitems {{ margin:8px 0 0; padding-left:2px; list-style:none; }}
ul.subitems li {{ margin-top:6px; font-size:12.5px; }}
.iters {{ border-top:2.5px solid var(--ink); }}
.iter {{ display:grid; grid-template-columns:120px 1fr; gap:26px;
        padding:24px 0 20px; border-bottom:1px solid var(--g200); }}
.iter .ino .n {{ display:block; font-family:var(--head); font-weight:700;
                font-size:44px; line-height:.9; color:var(--g200); letter-spacing:-.03em; }}
.iter.code .ino .n {{ color:var(--red); }}
.iter .idate {{ display:block; font-family:var(--mono); font-size:10.5px;
               color:var(--g500); margin-top:8px; letter-spacing:.05em; }}
.iter h3 {{ font-family:var(--head); font-size:15.5px; margin:2px 0 10px; }}
.iter ul {{ margin:0; padding-left:18px; }}
.iter li {{ font-size:13px; color:var(--g700); margin-top:5px; }}
@media (max-width:640px){{ .iter{{ grid-template-columns:1fr; gap:8px; }}
  .iter .ino {{ display:flex; align-items:baseline; gap:12px; }} .iter .ino .n{{font-size:30px}} }}
.leg {{ font-family:var(--mono); font-size:11px; color:var(--g500); margin:0 0 14px; }}
.leg .sw {{ display:inline-block; width:9px; height:9px; margin:0 4px 0 14px; vertical-align:baseline; }}
.dcard {{ border-top:2px solid var(--ink); padding:16px 0 18px; }}
.dcard + .dcard {{ border-top:1px solid var(--g200); }}
.dcard.open .did {{ color:var(--red); }}
.dhead {{ display:flex; align-items:center; gap:14px; }}
.did {{ font-family:var(--head); font-weight:700; font-size:22px; }}
.ddate {{ font-family:var(--mono); font-size:11px; color:var(--g500); margin-left:auto; }}
.dtitle {{ font-size:14.5px; font-weight:700; margin-top:10px; max-width:var(--measure); }}
.drec {{ font-size:13px; color:var(--g700); margin-top:8px; max-width:var(--measure); }}
.drec .k {{ font-family:var(--mono); font-size:10.5px; color:var(--red); margin-right:10px; }}
footer {{ margin-top:110px; border-top:2.5px solid var(--ink); padding-top:18px;
         font-family:var(--mono); font-size:11px; color:var(--g500); line-height:2; }}
.rv {{ opacity:0; transform:translateY(14px);
      transition:opacity .6s cubic-bezier(.16,.68,.3,1), transform .6s cubic-bezier(.16,.68,.3,1); }}
.rv.in {{ opacity:1; transform:none; }}
@media (prefers-reduced-motion: reduce) {{ .rv {{ opacity:1; transform:none; transition:none; }} }}
</style></head><body>
<div class="progress" aria-hidden="true"></div>
<div class="minibar"><span class="mt">SJTU-TPMSHX · 升级循环进度 · {now}</span><nav>
<a href="#s1">当前状态</a><a href="#s2">路线图</a><a href="#s3">迭代时间线</a><a href="#s4">待决事项</a></nav></div>
<div class="wrap">
<header class="masthead">
  <div class="eyebrow">SJTU-TPMSHX · UPGRADE LOOP · 生成于 {now}</div>
  <h1>升级循环推进到<em>第 {state.get('iteration', '—')} 轮</em></h1>
  <p class="intro">自迭代升级循环的实时进度页：当前做到哪一步、每一轮具体做了什么、哪些事项在等
  Alex 拍板。数据直接解析自 <code>upgrade/</code> 状态文件与 git，本页由
  <code>upgrade/tools/render_progress.py</code> 重渲，不手工维护。</p>
  <div class="facts"><div class="row"><span class="k">当前迭代</span>
      <span class="v"><b>iter {state.get('iteration', '—')}</b> 已完结</span></div>
    <div class="row"><span class="k">路线图完成度</span>
      <span class="v"><b>{done_all}</b> / {tot_all} 项</span></div>
    <div class="row"><span class="k">分支 · 领先 master</span>
      <span class="v"><code>{g['branch']}</code> · <b>{g['n_ahead']}</b> commits</span></div>
    <div class="row"><span class="k">HEAD</span>
      <span class="v"><code>{g['head']}</code> · {g['head_date']}</span></div>
    <div class="row"><span class="k">最近门禁</span>
      <span class="v">套件 {gate} · golden 位同</span></div>
    <div class="row"><span class="k">待 Alex 决策</span>
      <span class="v"><b>{n_pending}</b> 项</span></div></div>
</header>
<nav class="tocpage" aria-label="目录">
  <div class="lab">目录 · CONTENTS</div>
  <ol>
  <li><a href="#s1"><span class="n">01</span><span class="td"><span class="t">当前状态</span><span class="tdesc">循环游标：在做什么、下一项是什么、定时器与边界</span></span><span class="arr">→</span></a></li>
  <li><a href="#s2"><span class="n">02</span><span class="td"><span class="t">路线图</span><span class="tdesc">Phase 0–4 全部条目与完成度，含每项的一句话结论</span></span><span class="arr">→</span></a></li>
  <li><a href="#s3"><span class="n">03</span><span class="td"><span class="t">迭代时间线</span><span class="tdesc">每一轮做了什么、验证证据、教训——新的在前</span></span><span class="arr">→</span></a></li>
  <li><a href="#s4"><span class="n">04</span><span class="td"><span class="t">待决事项</span><span class="tdesc">等 Alex 拍板的 D 条目与循环建议</span></span><span class="arr">→</span></a></li>
  </ol>
</nav>
<section id="s1">
  <div class="sec-head rv"><span class="idx">01</span><h2>当前状态</h2></div>
  <p class="sec-intro rv">循环游标来自 <code>upgrade/STATE.md</code>——每轮开工第一笔、收尾最后一笔都写它。</p>
  <div class="speclist rv">
    <div class="srow"><div class="sk">进行中</div><div class="sv">{_fmt(in_prog)}</div></div>
    <div class="srow"><div class="sk">下一项</div><div class="sv">{_fmt(state.get('next', '—'))}</div></div>
    <div class="srow"><div class="sk">定时器</div><div class="sv">cron <code>{state.get('cron_spec', '—').strip('`')}</code>（每 15 分钟检查一次）· 布防 {_fmt(state.get('armed_at', '—'))}</div></div>
    <div class="srow"><div class="sk">基点</div><div class="sv">{_fmt(state.get('base', '—'))}</div></div>
  </div>
  <div class="callout rv">循环铁律：<b>绝不 push</b>；<b>绝不写主检出</b> <code>E:\\LWH\\SJTU-TPMSHX</code>；
  vault 只读；一轮只做一项；代码改动必过全套件门（数值路径另加 golden 位同门）；
  数值/物理政策变更一律先立 D 条目等 Alex 决策。</div>
</section>
<section id="s2">
  <div class="sec-head rv"><span class="idx">02</span><h2>路线图</h2></div>
  <p class="sec-intro rv">解析自 <code>upgrade/ROADMAP.md</code>。黑 = 完成，红 = 进行中，灰 = 待办；
  每项保留原文的一句话结论（含验证证据与提交哈希）。</p>
  {''.join(ph_html)}
</section>
<section id="s3">
  <div class="sec-head rv"><span class="idx">03</span><h2>迭代时间线</h2></div>
  <p class="sec-intro rv">解析自 <code>upgrade/PROGRESS.md</code>，新的在前。这里是"中间每一轮具体做了什么"
  的完整记录：做了什么 / 验证证据 / 教训与下一步。</p>
  <p class="leg rv">迭代号<span class="sw" style="background:var(--red)"></span>红 = 动了代码（过全门）
  <span class="sw" style="background:var(--g200)"></span>灰 = 盘点 / 评估 / 文档轮</p>
  <div class="iters">
  {''.join(it_html)}
  </div>
</section>
<section id="s4">
  <div class="sec-head rv"><span class="idx">04</span><h2>待决事项</h2></div>
  <p class="sec-intro rv">解析自 <code>upgrade/DECISIONS-NEEDED.md</code>——循环无权自决的数值 / 物理
  政策变更都停在这里等拍板；已决条目留档。</p>
  {''.join(dec_html)}
</section>
<footer>
  SJTU-TPMSHX 升级循环 · 本页生成于 {now} · 重渲：仓库根运行
  <code>python upgrade/tools/render_progress.py</code><br>
  数据源：upgrade/STATE.md · ROADMAP.md · PROGRESS.md · DECISIONS-NEEDED.md · git（只读，不产生新事实）
</footer>
</div>
<script>
(() => {{
  const $  = (s, c=document) => c.querySelector(s);
  const $$ = (s, c=document) => [...c.querySelectorAll(s)];
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const rio = new IntersectionObserver(es => es.forEach(e => {{
    if (e.isIntersecting) {{ e.target.classList.add('in'); rio.unobserve(e.target); }}
  }}), {{threshold:.08, rootMargin:'0px 0px -4% 0px'}});
  $$('.rv').forEach(el => reduced ? el.classList.add('in') : rio.observe(el));
  const prog = $('.progress'), mini = $('.minibar'), tocp = $('.tocpage');
  let ticking = false;
  const onScroll = () => {{
    if (ticking) return; ticking = true;
    requestAnimationFrame(() => {{
      const h = document.documentElement;
      prog.style.transform = `scaleX(${{h.scrollTop / (h.scrollHeight - h.clientHeight || 1)}})`;
      if (tocp) mini.classList.toggle('on', tocp.getBoundingClientRect().bottom < 0);
      ticking = false;
    }});
  }};
  addEventListener('scroll', onScroll, {{passive:true}}); onScroll();
  const spy = new IntersectionObserver(es => es.forEach(e => {{
    const a = $(`.minibar nav a[href="#${{e.target.id}}"]`);
    if (a) a.classList.toggle('active', e.isIntersecting);
  }}), {{rootMargin:'-40% 0px -55% 0px'}});
  $$('section[id]').forEach(s => spy.observe(s));
  addEventListener('keydown', e => {{
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
    if (e.ctrlKey || e.metaKey || e.altKey || e.shiftKey) return;
    const secs = $$('section[id]');
    const y = scrollY + 90;
    let idx = -1;
    secs.forEach((s, i) => {{ if (s.offsetTop <= y) idx = i; }});
    idx += e.key === 'ArrowRight' ? 1 : -1;
    if (idx < 0 || idx >= secs.length) return;
    e.preventDefault();
    secs[idx].scrollIntoView({{behavior: reduced ? 'auto' : 'smooth'}});
  }});
}})();
</script>
</body></html>"""
    out_path.write_text(doc, encoding='utf-8')
    print(f"rendered {out_path}  ({out_path.stat().st_size:,} bytes; "
          f"{len(iters)} iters, {len(phases)} phases, {len(decisions)} decisions)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='渲染升级循环进度页')
    ap.add_argument('--out', default=str(_UPG / 'progress.html'))
    args = ap.parse_args(argv)
    render(Path(args.out))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
