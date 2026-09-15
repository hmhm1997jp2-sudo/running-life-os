"""
Running Life OS - 디자인 시스템 (ui.py)
=======================================
PC / 모바일 레이아웃 분기, 테마, 공통 UI 컴포넌트.

  - 기기 감지 : User-Agent 자동 판별 + 헤더의 수동 전환
  - 테마 감지 : Streamlit이 실제로 쓰는 테마(밝게/어둡게)를 읽어 CSS를 맞춤
                → 위젯은 밝은데 배경만 어두워지는 어긋남이 없음
  - PC 모드   : 다단 그리드, 넓은 차트, 표 중심
  - 모바일    : 1단 스택, 큰 탭 타깃, 표 대신 카드 리스트, 수치는 전용 그리드

app.py 에서:
    import ui
    ui.boot()                # CSS 주입 + 모드 결정 (가장 먼저 1회)
    if ui.is_mobile(): ...
"""

from __future__ import annotations

import re
import streamlit as st

# ---------------------------------------------------------------------------
# 기기 / 테마 감지
# ---------------------------------------------------------------------------
_MOBILE_UA = re.compile(
    r"Android|iPhone|iPad|iPod|IEMobile|Opera Mini|Mobile Safari|Silk", re.I)


def _detect_mobile() -> bool:
    try:
        return bool(_MOBILE_UA.search(st.context.headers.get("User-Agent", "") or ""))
    except Exception:
        return False


def _detect_theme() -> str:
    """Streamlit이 실제 적용 중인 테마를 읽는다 ('light' | 'dark')."""
    try:
        t = getattr(st.context, "theme", None)
        val = getattr(t, "type", None) if t is not None else None
        if str(val).lower() in ("dark", "light"):
            return str(val).lower()
    except Exception:
        pass
    return "light"


def is_mobile() -> bool:
    return st.session_state.get("ui_mode", "pc") == "mobile"


def is_dark() -> bool:
    return st.session_state.get("ui_theme", "light") == "dark"


def mode_switch(container=None) -> None:
    """PC / 모바일 수동 전환."""
    c = container or st
    cur = st.session_state.get("ui_mode", "pc")
    choice = c.radio("화면 모드", ["💻 PC", "📱 모바일"],
                     index=0 if cur == "pc" else 1, horizontal=True,
                     label_visibility="collapsed", key="ui_mode_radio")
    new = "mobile" if choice.startswith("📱") else "pc"
    if new != cur:
        st.session_state["ui_mode"] = new
        st.rerun()


def boot() -> None:
    """앱 시작 시 1회 — 기기·테마 결정 후 해당 CSS 주입."""
    if "ui_mode" not in st.session_state:
        st.session_state["ui_mode"] = "mobile" if _detect_mobile() else "pc"
    st.session_state["ui_theme"] = _detect_theme()
    _inject_css(st.session_state["ui_mode"], st.session_state["ui_theme"])


# ---------------------------------------------------------------------------
# 디자인 토큰
# ---------------------------------------------------------------------------
_LIGHT = """
  --bg:#f4f5f7;        --surface:#ffffff;     --surface-2:#f8f9fb;
  --line:#e6e8ec;      --line-soft:#f0f1f4;
  --text:#14181f;      --text-2:#5b6472;      --text-3:#8a93a1;
  --accent:#3b5bdb;    --accent-2:#eef1fd;    --accent-ink:#3b5bdb;
  --ok:#0d8a5f;        --ok-bg:rgba(13,138,95,.10);
  --warn:#b2670a;      --warn-bg:rgba(178,103,10,.12);
  --bad:#cc3b34;       --bad-bg:rgba(204,59,52,.10);
  --shadow-sm:0 1px 2px rgba(20,24,31,.05);
  --shadow-md:0 1px 2px rgba(20,24,31,.05), 0 10px 26px -20px rgba(20,24,31,.45);
"""
_DARK = """
  --bg:#0d1016;        --surface:#151a23;     --surface-2:#1b212c;
  --line:#252c39;      --line-soft:#1e2531;
  --text:#e8ecf3;      --text-2:#9aa4b4;      --text-3:#6e7787;
  --accent:#8aa4ff;    --accent-2:#1c2340;    --accent-ink:#a9bcff;
  --ok:#4ec99a;        --ok-bg:rgba(78,201,154,.12);
  --warn:#e0a75a;      --warn-bg:rgba(224,167,90,.14);
  --bad:#f1736c;       --bad-bg:rgba(241,115,108,.12);
  --shadow-sm:0 1px 2px rgba(0,0,0,.35);
  --shadow-md:0 1px 2px rgba(0,0,0,.35), 0 12px 28px -20px rgba(0,0,0,.9);
"""

_FONT = """
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css');
"""

_BASE = """
<style>
__FONT__
:root {
__TOKENS__
  --r-sm:10px; --r-md:14px; --r-lg:18px;
  --font: "Pretendard Variable", Pretendard, -apple-system, BlinkMacSystemFont,
          "Apple SD Gothic Neo", "Segoe UI", Roboto, "Malgun Gothic", sans-serif;
}

/* ── 바탕 ───────────────────────────────────────────── */
html, body, .stApp, [class*="st-"], button, input, textarea, select {
  font-family: var(--font) !important;
  -webkit-font-smoothing:antialiased; -moz-osx-font-smoothing:grayscale;
}
/* Streamlit 아이콘(Material Symbols)은 폰트 강제에서 제외 — 안 하면 "expand_more" 같은
   글자가 그대로 보입니다 */
span[data-testid="stIconMaterial"], .material-symbols-rounded, .material-symbols-outlined,
[class*="material-symbols"], [data-testid="stExpanderToggleIcon"] {
  font-family:"Material Symbols Rounded","Material Symbols Outlined" !important;
}
.stApp { background: var(--bg); color: var(--text); }
#MainMenu, footer, header [data-testid="stDecoration"] { visibility:hidden; }
[data-testid="stToolbar"] { right:.4rem; }
.block-container { padding-top:3.1rem; padding-bottom:5rem; }

/* 스크롤바 */
::-webkit-scrollbar { width:10px; height:10px; }
::-webkit-scrollbar-thumb { background:var(--line); border-radius:99px;
                            border:3px solid transparent; background-clip:content-box; }
::-webkit-scrollbar-thumb:hover { background:var(--text-3); background-clip:content-box; }
::-webkit-scrollbar-track { background:transparent; }

/* ── 카드 (st.container(border=True)) ───────────────── */
div[data-testid="stVerticalBlockBorderWrapper"] {
  background:var(--surface);
  border:1px solid var(--line) !important;
  border-radius:var(--r-lg) !important;
  box-shadow:var(--shadow-md);
}
/* 중첩 카드는 톤을 낮춰 계층을 만든다 */
div[data-testid="stVerticalBlockBorderWrapper"]
  div[data-testid="stVerticalBlockBorderWrapper"] {
  background:var(--surface-2); box-shadow:none;
}

/* ── 메트릭 ─────────────────────────────────────────── */
div[data-testid="stMetric"] { padding:2px 0; background:transparent; }
div[data-testid="stMetricLabel"] p {
  font-size:.72rem !important; font-weight:600 !important;
  letter-spacing:.06em !important; text-transform:uppercase;
  color:var(--text-3) !important;
}
div[data-testid="stMetricValue"] {
  font-weight:700 !important; letter-spacing:-.025em;
  color:var(--text) !important;
  font-variant-numeric:tabular-nums; font-feature-settings:"tnum" 1;
}
div[data-testid="stMetricDelta"] { font-size:.76rem !important; font-weight:600 !important; }

/* ── 탭 (세그먼티드 컨트롤 스타일) ──────────────────── */
.stTabs [data-baseweb="tab-list"] {
  gap:3px; background:var(--surface-2); padding:4px;
  border:1px solid var(--line); border-radius:var(--r-md);
  overflow-x:auto; scrollbar-width:none;
}
.stTabs [data-baseweb="tab-list"]::-webkit-scrollbar { display:none; }
.stTabs [data-baseweb="tab"] {
  border-radius:var(--r-sm); font-weight:600; color:var(--text-2);
  padding:0 14px; white-space:nowrap; background:transparent;
  transition:background .14s ease, color .14s ease;
}
.stTabs [data-baseweb="tab"]:hover { color:var(--text); }
.stTabs [aria-selected="true"] {
  background:var(--surface) !important; color:var(--accent-ink) !important;
  box-shadow:var(--shadow-sm);
}
.stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] { display:none; }

/* ── 버튼 ───────────────────────────────────────────── */
.stButton>button, .stDownloadButton>button, .stFormSubmitButton>button {
  border-radius:var(--r-sm) !important; font-weight:600 !important;
  border:1px solid var(--line) !important; background:var(--surface) !important;
  color:var(--text) !important; box-shadow:var(--shadow-sm);
  transition:transform .12s ease, box-shadow .12s ease, background .12s ease;
}
.stButton>button:hover, .stDownloadButton>button:hover, .stFormSubmitButton>button:hover {
  transform:translateY(-1px); box-shadow:var(--shadow-md);
}
.stButton>button:active, .stFormSubmitButton>button:active { transform:translateY(0); }
.stButton>button[kind="primary"], .stFormSubmitButton>button[kind="primary"],
.stFormSubmitButton>button[kind="primaryFormSubmit"],
.stDownloadButton>button[kind="primary"] {
  background:var(--accent) !important; color:#fff !important;
  border-color:transparent !important; box-shadow:var(--shadow-md);
}
.stButton>button[kind="primary"]:hover, .stFormSubmitButton>button[kind="primary"]:hover,
.stFormSubmitButton>button[kind="primaryFormSubmit"]:hover { filter:brightness(1.06); }

/* ── 입력 ───────────────────────────────────────────── */
.stTextInput input, .stNumberInput input, .stDateInput input, .stTextArea textarea,
div[data-baseweb="select"]>div, div[data-baseweb="input"] {
  border-radius:var(--r-sm) !important; border-color:var(--line) !important;
  background:var(--surface) !important;
}
.stTextInput input:focus, .stNumberInput input:focus, .stTextArea textarea:focus {
  border-color:var(--accent) !important; box-shadow:0 0 0 3px var(--accent-2) !important;
}
label p { font-weight:600 !important; color:var(--text-2) !important; font-size:.82rem !important; }

/* ── expander ──────────────────────────────────────── */
details[data-testid="stExpander"], .stExpander {
  border:1px solid var(--line) !important; border-radius:var(--r-md) !important;
  background:var(--surface-2) !important; box-shadow:none !important;
}
.stExpander summary p { font-weight:600 !important; color:var(--text) !important; }

/* ── 표 ─────────────────────────────────────────────── */
[data-testid="stDataFrame"] { border-radius:var(--r-md); overflow:hidden;
                              border:1px solid var(--line); }

/* ── 차트 텍스트를 테마색으로 ──────────────────────── */
.vega-embed text, .stVegaLiteChart text { fill:var(--text-2) !important; }
.vega-embed .role-axis-domain, .vega-embed .role-axis-tick { stroke:var(--line) !important; }
.vega-embed .role-axis-grid line { stroke:var(--line-soft) !important; }

/* ── 알림 박스 ─────────────────────────────────────── */
div[data-testid="stAlert"] { border-radius:var(--r-md); border:1px solid var(--line); }

/* ── 커스텀 조각 ───────────────────────────────────── */
.rl-title { font-size:1.3rem; font-weight:700; letter-spacing:-.03em;
            color:var(--text); margin:0; line-height:1.25; }
.rl-sub   { color:var(--text-3); font-size:.83rem; margin:3px 0 0; line-height:1.5; }
.rl-head  { font-size:.94rem; font-weight:700; color:var(--text); letter-spacing:-.01em;
            margin:0 0 10px; display:flex; align-items:center; gap:7px; }

.rl-pill  { display:inline-block; padding:3px 10px; border-radius:999px;
            font-size:.73rem; font-weight:650; letter-spacing:-.005em;
            background:var(--surface-2); color:var(--text-2);
            border:1px solid var(--line); }
.rl-pill.ok   { background:var(--ok-bg);   color:var(--ok);   border-color:transparent; }
.rl-pill.warn { background:var(--warn-bg); color:var(--warn); border-color:transparent; }
.rl-pill.bad  { background:var(--bad-bg);  color:var(--bad);  border-color:transparent; }
.rl-pill.info { background:var(--accent-2); color:var(--accent-ink); border-color:transparent; }

.rl-row { display:flex; justify-content:space-between; align-items:baseline; gap:12px;
          padding:9px 0; border-bottom:1px solid var(--line-soft); }
.rl-row:last-child { border-bottom:none; }
.rl-row .k { color:var(--text-3); font-size:.82rem; }
.rl-row .v { font-weight:650; font-variant-numeric:tabular-nums; color:var(--text);
             text-align:right; }

.rl-item { padding:11px 0; border-bottom:1px solid var(--line-soft); }
.rl-item:last-child { border-bottom:none; }
.rl-item .t { font-weight:650; color:var(--text); font-size:.91rem; letter-spacing:-.01em; }
.rl-item .m { color:var(--text-3); font-size:.78rem; margin-top:3px;
              font-variant-numeric:tabular-nums; }

.rl-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:15px 12px; }
.rl-grid.c3 { grid-template-columns:repeat(3,minmax(0,1fr)); }
.rl-mt .l { font-size:.68rem; font-weight:600; letter-spacing:.06em; text-transform:uppercase;
            color:var(--text-3); }
.rl-mt .v { font-size:1.5rem; font-weight:700; letter-spacing:-.03em; line-height:1.22;
            color:var(--text); font-variant-numeric:tabular-nums; }
.rl-mt .d { font-size:.73rem; font-weight:600; color:var(--text-3); margin-top:2px; }

.rl-bar { height:6px; background:var(--line-soft); border-radius:99px;
          overflow:hidden; margin-top:9px; }
.rl-bar > i { display:block; height:100%; border-radius:99px; background:var(--accent);
              transition:width .5s cubic-bezier(.22,1,.36,1); }
.rl-bar > i.warn { background:var(--warn); }
.rl-bar > i.bad  { background:var(--bad); }

/* ── 벤토 타일 (대시보드) ───────────────────────────── */
.rl-tiles { display:grid; grid-template-columns:repeat(4,minmax(0,1fr));
            gap:12px; margin:2px 0 6px; }
.rl-tiles.c3 { grid-template-columns:repeat(3,minmax(0,1fr)); }
.rl-tiles.c2 { grid-template-columns:repeat(2,minmax(0,1fr)); }
.rl-tile { position:relative; overflow:hidden; background:var(--surface);
           border:1px solid var(--line); border-radius:var(--r-md);
           padding:13px 15px 12px; box-shadow:var(--shadow-sm);
           transition:transform .16s cubic-bezier(.22,1,.36,1), box-shadow .16s,
                      border-color .16s; }
.rl-tile:hover { transform:translateY(-2px); box-shadow:var(--shadow-md);
                 border-color:var(--text-3); }
.rl-tile::before { content:""; position:absolute; left:0; top:0; bottom:0; width:3px;
                   background:transparent; }
.rl-tile.ok::before   { background:var(--ok); }
.rl-tile.warn::before { background:var(--warn); }
.rl-tile.bad::before  { background:var(--bad); }
.rl-tile.info::before { background:var(--accent); }
.rl-tile .l { display:flex; align-items:center; gap:6px; font-size:.67rem; font-weight:600;
              letter-spacing:.06em; text-transform:uppercase; color:var(--text-3);
              white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.rl-tile .v { font-size:1.6rem; font-weight:750; letter-spacing:-.03em; line-height:1.2;
              margin-top:7px; color:var(--text); font-variant-numeric:tabular-nums; }
.rl-tile .v u { text-decoration:none; font-size:.78rem; font-weight:600;
                color:var(--text-3); margin-left:3px; }
.rl-tile .d { font-size:.73rem; font-weight:600; color:var(--text-3); margin-top:3px;
              white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.rl-tile .d.up { color:var(--ok); } .rl-tile .d.down { color:var(--bad); }
.rl-tile svg.spark { display:block; margin-top:8px; width:100%; height:26px; }

/* ── 히어로 (오늘 상태) ─────────────────────────────── */
.rl-hero { border:1px solid var(--line); border-radius:var(--r-lg); padding:18px 20px 16px;
           background:linear-gradient(135deg, var(--accent-2) 0%, var(--surface) 62%);
           box-shadow:var(--shadow-sm); margin-bottom:4px; }
.rl-hero .t { font-size:2.05rem; font-weight:780; letter-spacing:-.035em; line-height:1.1; }
.rl-hero .s { color:var(--text-2); font-size:.86rem; margin:6px 0 0; line-height:1.55; }
.rl-hero .k { display:flex; flex-wrap:wrap; gap:6px 18px; margin-top:12px; }
.rl-hero .k b { font-variant-numeric:tabular-nums; font-weight:700; color:var(--text); }
.rl-hero .k span { font-size:.8rem; color:var(--text-3); }

@media (max-width:640px) {
  .rl-tiles, .rl-tiles.c3 { grid-template-columns:repeat(2,minmax(0,1fr)); gap:9px; }
  .rl-tile { padding:11px 12px 10px; border-radius:var(--r-sm); }
  .rl-tile .v { font-size:1.32rem; }
  .rl-hero .t { font-size:1.6rem; }
}

.rl-divider { height:1px; background:var(--line); margin:26px 0 18px; border:0; }

/* ── 심박존 비교 표 ─────────────────────────────────── */
.rl-ztable { width:100%; border-collapse:collapse; font-variant-numeric:tabular-nums; }
.rl-ztable th {
  font-size:.68rem; font-weight:600; letter-spacing:.07em; text-transform:uppercase;
  color:var(--text-3); padding:0 0 9px; text-align:right; white-space:nowrap;
}
.rl-ztable th:first-child { text-align:left; }
.rl-ztable td {
  padding:10px 0; border-top:1px solid var(--line-soft);
  text-align:right; font-weight:650; color:var(--text); font-size:.9rem; white-space:nowrap;
}
.rl-ztable td:first-child {
  text-align:left; font-weight:600; color:var(--text-2); font-size:.86rem;
  padding-right:14px; width:38%;
}
.rl-ztable td + td { padding-left:14px; }
.rl-ztable .prim { color:var(--text); }
.rl-ztable .sec  { color:var(--text-3); font-weight:600; }
.rl-zdot { width:9px; height:9px; border-radius:3px; display:inline-block;
           margin-right:9px; vertical-align:middle; }

/* ── 존 막대 (bpm 축 위의 구간) ─────────────────────── */
.rl-zbar { display:flex; height:44px; border-radius:12px; overflow:hidden;
           border:1px solid var(--line); }
.rl-zbar > div { display:flex; flex-direction:column; align-items:center;
                 justify-content:center; gap:1px; min-width:0; padding:0 2px; }
.rl-zbar .zn { font-size:.68rem; font-weight:750; letter-spacing:-.01em; }
.rl-zbar .zr { font-size:.63rem; font-weight:600; opacity:.75;
               font-variant-numeric:tabular-nums; }
.rl-zends { display:flex; justify-content:space-between; margin-top:5px;
            font-size:.68rem; color:var(--text-3); font-variant-numeric:tabular-nums; }
</style>
"""

_PC = """
<style>
.block-container { max-width:1240px; padding-left:2.4rem; padding-right:2.4rem; }
div[data-testid="stVerticalBlockBorderWrapper"] { padding:6px 8px; }
div[data-testid="stMetricValue"] { font-size:1.9rem !important; }
.stTabs [data-baseweb="tab"] { height:40px; font-size:.9rem; }
.rl-title { font-size:1.45rem; }
</style>
"""

_MOBILE = """
<style>
.block-container { max-width:100%; padding:2.5rem .9rem 3.5rem; }
div[data-testid="stMetricValue"] { font-size:1.5rem !important; }
div[data-testid="stMetricLabel"] p { font-size:.66rem !important; }
div[data-testid="stHorizontalBlock"] { gap:.55rem !important; }

/* 손가락 타깃 */
.stTabs [data-baseweb="tab"] { height:44px; font-size:.85rem; padding:0 13px; }
.stButton>button, .stFormSubmitButton>button, .stDownloadButton>button {
  min-height:46px !important; font-size:.95rem !important;
}
.stTextInput input, .stNumberInput input, .stDateInput input {
  min-height:44px !important; font-size:16px !important;   /* iOS 자동 확대 방지 */
}
.rl-title { font-size:1.16rem; }
.rl-sub { font-size:.77rem; }
[data-testid="stDataFrame"] { font-size:.79rem; }
</style>
"""


def _inject_css(mode: str, theme: str) -> None:
    css = (_BASE.replace("__FONT__", _FONT)
                .replace("__TOKENS__", _DARK if theme == "dark" else _LIGHT))
    st.markdown(css, unsafe_allow_html=True)
    st.markdown(_MOBILE if mode == "mobile" else _PC, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# 컴포넌트
# ---------------------------------------------------------------------------
def card(key: str | None = None):
    """테두리 카드 컨테이너. `with ui.card("이름"):` 로 사용."""
    try:
        return st.container(border=True, key=key)
    except TypeError:
        return st.container(border=True)


def head(text: str, sub: str | None = None) -> None:
    html = f"<p class='rl-head'>{text}</p>"
    if sub:
        html += f"<p class='rl-sub' style='margin:-8px 0 10px'>{sub}</p>"
    st.markdown(html, unsafe_allow_html=True)


def pill(text: str, tone: str = "") -> str:
    return f"<span class='rl-pill {tone}'>{text}</span>"


def rows(pairs: list[tuple[str, str]]) -> None:
    st.markdown("".join(f"<div class='rl-row'><span class='k'>{k}</span>"
                        f"<span class='v'>{v}</span></div>" for k, v in pairs),
                unsafe_allow_html=True)


def bar(pct: float, tone: str = "") -> None:
    p = max(0.0, min(100.0, float(pct)))
    st.markdown(f"<div class='rl-bar'><i class='{tone}' style='width:{p:.1f}%'></i></div>",
                unsafe_allow_html=True)


def item_list(items: list[tuple[str, str]]) -> None:
    st.markdown("".join(f"<div class='rl-item'><div class='t'>{t}</div>"
                        f"<div class='m'>{m}</div></div>" for t, m in items),
                unsafe_allow_html=True)


def _spark_svg(vals, tone: str = "") -> str:
    """작은 추세선(스파크라인)을 인라인 SVG로. 값이 2개 미만이면 빈 문자열."""
    try:
        pts = [float(v) for v in vals if v is not None and float(v) == float(v)]
    except (TypeError, ValueError):
        return ""
    if len(pts) < 2:
        return ""
    pts = pts[-30:]
    lo, hi = min(pts), max(pts)
    rng = (hi - lo) or 1.0
    w, h, pad = 100.0, 26.0, 3.0
    step = w / (len(pts) - 1)
    col = {"ok": "var(--ok)", "warn": "var(--warn)", "bad": "var(--bad)"}.get(
        tone, "var(--accent)")
    d = " ".join(f"{i * step:.1f},{pad + (h - 2 * pad) * (1 - (v - lo) / rng):.1f}"
                 for i, v in enumerate(pts))
    last_x, last_y = d.split(" ")[-1].split(",")
    return (f"<svg class='spark' viewBox='0 0 {w:.0f} {h:.0f}' preserveAspectRatio='none'>"
            f"<polyline points='{d}' fill='none' stroke='{col}' stroke-width='1.6' "
            f"stroke-linecap='round' stroke-linejoin='round' vector-effect='non-scaling-stroke'/>"
            f"<circle cx='{last_x}' cy='{last_y}' r='1.8' fill='{col}'/></svg>")


def tiles(items, per_row_pc: int = 4) -> None:
    """벤토형 지표 타일 묶음.
    items = [{"label", "value", "unit"?, "sub"?, "tone"?, "spark"?}, ...]
      tone : "" | "ok" | "warn" | "bad" | "info"  (왼쪽 악센트 바 색)
      sub  : '+3.2' 처럼 +/- 로 시작하면 증감색이 붙습니다
    """
    cells = ""
    for it in items:
        tone = str(it.get("tone") or "")
        unit = it.get("unit")
        sub = it.get("sub")
        dcls = ""
        if isinstance(sub, str) and sub[:1] in "+-↑↓":
            dcls = " up" if sub[:1] in "+↑" else " down"
        cells += (
            f"<div class='rl-tile {tone}'>"
            f"<div class='l'>{it.get('label','')}</div>"
            f"<div class='v'>{it.get('value','—')}"
            + (f"<u>{unit}</u>" if unit else "") + "</div>"
            + (f"<div class='d{dcls}'>{sub}</div>" if sub else "")
            + _spark_svg(it.get("spark") or [], tone)
            + "</div>")
    klass = "rl-tiles" + (" c3" if per_row_pc == 3 else " c2" if per_row_pc == 2 else "")
    st.markdown(f"<div class='{klass}'>{cells}</div>", unsafe_allow_html=True)


def hero(title: str, badge_html: str = "", sub: str = "", facts=None) -> None:
    """맨 위 '오늘 상태' 큰 카드. facts = [(라벨, 값), ...]"""
    f = "".join(f"<span>{k} <b>{v}</b></span>" for k, v in (facts or []))
    st.markdown(
        f"<div class='rl-hero'><div style='display:flex;align-items:center;"
        f"gap:12px;flex-wrap:wrap'><span class='t'>{title}</span>{badge_html}</div>"
        + (f"<p class='s'>{sub}</p>" if sub else "")
        + (f"<div class='k'>{f}</div>" if f else "")
        + "</div>", unsafe_allow_html=True)


def divider() -> None:
    st.markdown("<hr class='rl-divider'>", unsafe_allow_html=True)


def tone_for(level: str) -> str:
    return {"error": "bad", "warning": "warn", "info": "info", "success": "ok"}.get(level, "")


def chart_height(pc: int = 280, mobile: int = 210) -> int:
    return mobile if is_mobile() else pc


def cols(n_pc: int, n_mobile: int = 1, keep_row: bool = False):
    """PC/모바일 컬럼 수 분기.
    모바일에서는 Streamlit이 좁은 컬럼을 자동으로 세로 스택하므로 항상 n_mobile을 씁니다.
    나란히 두어야 하는 수치는 metrics() 그리드를 사용하세요.
    호출부의 c[i % len(c)] 패턴 덕분에 항목이 남으면 같은 컬럼에 이어 쌓입니다."""
    return st.columns(n_mobile if is_mobile() else n_pc)


def metrics(items, per_row_pc: int | None = None, per_row_mobile: int = 2) -> None:
    """수치 카드 묶음. items = [(라벨, 값, 보조설명 or None), ...]
    PC는 st.metric, 모바일은 CSS 그리드로 2~3단을 유지합니다."""
    items = [(l, v, d) for l, v, d in items]
    if is_mobile():
        cells = ""
        for l, v, d in items:
            dd = f"<div class='d'>{d}</div>" if d not in (None, "") else ""
            cells += f"<div class='rl-mt'><div class='l'>{l}</div><div class='v'>{v}</div>{dd}</div>"
        klass = "rl-grid c3" if per_row_mobile == 3 else "rl-grid"
        st.markdown(f"<div class='{klass}'>{cells}</div>", unsafe_allow_html=True)
    else:
        cs = st.columns(per_row_pc or len(items))
        for i, (l, v, d) in enumerate(items):
            c = cs[i % len(cs)]
            # 실제 증감(+/-)만 st.metric 델타로, 설명 문구는 회색 캡션으로
            if isinstance(d, str) and d[:1] in "+-":
                c.metric(l, v, d)
            else:
                c.metric(l, v)
                if d not in (None, ""):
                    c.markdown(f"<span class='rl-sub' style='font-size:.75rem;"
                               f"display:block;margin-top:-10px'>{d}</span>",
                               unsafe_allow_html=True)
