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
import sys
import unicodedata

import streamlit as st
import streamlit.components.v1 as components

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


# 스트림릿은 테마를 바꾸는 파이썬 API가 없습니다. 대신 스트림릿 자신이
# 고른 테마를 브라우저 localStorage 의 이 키에 넣어 두고 다음 접속 때 읽습니다.
# 같은 키에 값을 써 주고 새로고침하면, 우리 CSS만이 아니라 **표·입력칸 같은
# 스트림릿 기본 위젯까지** 전부 그 테마로 바뀝니다.
_THEME_KEY = "stActiveTheme-/-v2"
_THEME_VALS = {"auto": "System", "light": "Light", "dark": "Dark"}


def set_theme(choice: str) -> None:
    """'auto' | 'light' | 'dark' 로 바꾸고 새로고침합니다."""
    val = _THEME_VALS.get(choice, "System")
    components.html(
        "<script>try{"
        f"window.parent.localStorage.setItem('{_THEME_KEY}', JSON.stringify('{val}'));"
        "window.parent.location.reload();"
        "}catch(e){}</script>", height=0)


def theme_switch(container=None) -> None:
    """밝게 / 어둡게 / 자동 고르기.

    지금 적용된 테마가 무엇인지는 서버가 알 수 있지만(‘밝게’인지 ‘어둡게’인지),
    그것이 **직접 고른 것인지 시스템을 따라간 것인지는** 알 수 없습니다.
    그래서 고른 값을 보여주는 대신 **지금 보이는 화면**에 표시를 답니다.
    """
    c = container or st
    cur = "dark" if is_dark() else "light"
    opts = ["☀️ 밝게", "🌙 어둡게", "자동"]
    pick = c.radio("테마", opts, index=1 if cur == "dark" else 0,
                   horizontal=True, label_visibility="collapsed",
                   key="ui_theme_radio")
    # '자동'은 밝게/어둡게 중 하나로 풀리므로, 값만 비교하면 새로고침이
    # 끝없이 반복됩니다 → **직전에 고른 값과 달라졌을 때만** 적용합니다.
    # (새로고침하면 세션이 비므로 첫 화면에서는 아무 일도 하지 않습니다)
    prev = st.session_state.get("_theme_pick")
    st.session_state["_theme_pick"] = pick
    if prev is not None and pick != prev:
        set_theme("dark" if pick.startswith("🌙")
                  else "auto" if pick == "자동" else "light")
    c.caption("‘자동’은 폰·PC의 다크 모드 설정을 따라갑니다.")


def boot() -> None:
    """앱 시작 시 1회 — 기기·테마 결정 후 해당 CSS 주입."""
    if "ui_mode" not in st.session_state:
        st.session_state["ui_mode"] = "mobile" if _detect_mobile() else "pc"
    st.session_state["ui_theme"] = _detect_theme()
    _inject_css(st.session_state["ui_mode"], st.session_state["ui_theme"])


# ---------------------------------------------------------------------------
# 디자인 토큰
# ---------------------------------------------------------------------------
# 색이 '칙칙하다'는 건 대개 채도가 아니라 **대비가 없다**는 뜻입니다.
# 예전 토큰은 바탕(#f4f5f7)과 카드(#fff)가 거의 같은 밝기라 카드가 떠 보이지
# 않았고, 보조 글씨(#8a93a1)가 너무 옅어 화면 전체가 회색으로 읽혔습니다.
# · 바탕을 한 단계 내리고 살짝 파랗게 → 흰 카드가 떠 보입니다
# · 보조 글씨를 두 단계 진하게 → 읽히는 글자가 늘어납니다
# · 회색 톤을 전부 중립회색에서 **푸른 회색**으로 → 같은 명도라도 덜 탁합니다
_LIGHT = """
  --bg:#eaeef5;        --surface:#ffffff;     --surface-2:#f1f5fb;
  --line:#dbe2ed;      --line-soft:#e9eef6;
  --text:#101622;      --text-2:#48546a;      --text-3:#6f7b8e;
  --accent:#3355e0;    --accent-2:#e6ebfe;    --accent-ink:#2c47c7;
  --accent-soft:#c3cef6;
  --ok:#0a8f5f;        --ok-bg:rgba(10,143,95,.12);
  --warn:#bd6a00;      --warn-bg:rgba(189,106,0,.14);
  --bad:#d43a30;       --bad-bg:rgba(212,58,48,.12);
  --shadow-sm:0 1px 2px rgba(16,22,34,.06);
  --shadow-md:0 1px 2px rgba(16,22,34,.06), 0 12px 28px -18px rgba(16,22,34,.40);
"""
_DARK = """
  --bg:#0a0e16;        --surface:#161d29;     --surface-2:#1e2633;
  --line:#2a3342;      --line-soft:#222a37;
  --text:#eaeff7;      --text-2:#a6b1c2;      --text-3:#818d9f;
  --accent:#8aa4ff;    --accent-2:#1f2a4d;    --accent-ink:#b3c3ff;
  --accent-soft:#3b4870;
  --ok:#4ed3a1;        --ok-bg:rgba(78,211,161,.14);
  --warn:#eab05f;      --warn-bg:rgba(234,176,95,.16);
  --bad:#f77a72;       --bad-bg:rgba(247,122,114,.14);
  --shadow-sm:0 1px 2px rgba(0,0,0,.4);
  --shadow-md:0 1px 2px rgba(0,0,0,.4), 0 14px 30px -18px rgba(0,0,0,.95);
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
/* ⋮ 메뉴(#MainMenu)는 숨기지 않습니다 — 밝게/어둡게 테마를 바꾸는 곳이
   거기뿐이라, 숨기면 사용자가 테마를 바꿀 방법이 없어집니다. */
footer, header [data-testid="stDecoration"] { visibility:hidden; }
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

/* ── 스트림릿 기본 강조색(빨강) 덮기 ─────────────────
   config.toml 에 [theme] 를 두면 사용자가 고른 밝게/어둡게가 무시되므로
   거기서 primaryColor 를 못 씁니다. 대신 기본 빨강이 새어 나오는 위젯을
   여기서 강조색으로 칠합니다. */
[data-testid="stSlider"] [role="slider"],
[data-testid="stSlider"] div[style*="translate(-50%"] { background:var(--accent) !important; }
/* 채워진 구간은 인라인 그라데이션(빨강)이라 색을 덮어쓸 수 없습니다 —
   그 칸만 색상환을 돌려 강조색 계열로 옮깁니다. */
[data-testid="stSlider"] div[role="group"] > div > div:first-child {
  filter:hue-rotate(228deg) saturate(.95); }
[data-testid="stSlider"] [data-baseweb="slider"] > div > div > div:not([role="slider"]) {
  background:var(--accent) !important; }
[data-testid="stSliderThumbValue"], [data-testid="stSliderThumbValue"] * {
  color:var(--accent) !important; }
[data-testid="stSliderTickBarMin"], [data-testid="stSliderTickBarMax"] {
  color:var(--text-3) !important; }
[data-baseweb="checkbox"] span[data-checked="true"],
[data-testid="stCheckbox"] input:checked + div,
[data-testid="stToggle"] input:checked + div { background:var(--accent) !important; }
[data-testid="stProgress"] div[role="progressbar"] > div {
  background:var(--accent) !important; }
a, .stMarkdown a { color:var(--accent-ink) !important; }

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
/* 모든 타일에 색 띠를 둡니다 — 톤이 없는 타일까지 흰 상자로만 두면
   화면 전체가 회색으로 읽힙니다. 기본은 옅은 강조색, 상태가 있으면 그 색. */
.rl-tile::before { content:""; position:absolute; left:0; top:0; bottom:0; width:3px;
                   background:var(--accent-soft); }
.rl-tile.ok::before   { background:var(--ok); }
.rl-tile.warn::before { background:var(--warn); }
.rl-tile.bad::before  { background:var(--bad); }
.rl-tile.info::before { background:var(--accent); }
.rl-tile .l { display:flex; align-items:center; gap:6px; font-size:.72rem; font-weight:650;
              letter-spacing:.005em; color:var(--text-3);
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
           background:linear-gradient(118deg, var(--accent-2) 0%,
                                      var(--surface-2) 46%, var(--surface) 82%);
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

/* ── 알림 줄 (체크포인트) ───────────────────────────── */
.rl-alert { display:flex; gap:10px; align-items:flex-start; padding:10px 12px;
            border-radius:var(--r-sm); background:var(--surface-2);
            border-left:3px solid var(--text-3); margin-bottom:7px;
            font-size:.86rem; line-height:1.5; color:var(--text); }
.rl-alert:last-child { margin-bottom:0; }
.rl-alert.bad  { border-left-color:var(--bad); }
.rl-alert.warn { border-left-color:var(--warn); }
.rl-alert.info { border-left-color:var(--accent); }
.rl-alert .ic  { flex:0 0 auto; line-height:1.45; }

/* ── 존 막대 (bpm 축 위의 구간) ─────────────────────── */
/* 조각 사이는 테두리가 아니라 배경색 2px 틈으로 가릅니다 —
   테두리를 두르면 데이터가 아닌 잉크가 늘어납니다. */
.rl-zbar { display:flex; gap:2px; height:40px; }
.rl-zbar > div { display:flex; flex-direction:column; align-items:center;
                 justify-content:center; gap:1px; min-width:0; padding:0 2px;
                 border-radius:5px; overflow:hidden; }
.rl-zbar .zn, .rl-zbar .zr { white-space:nowrap; }
.rl-zbar > div:first-child { border-top-left-radius:11px;
                             border-bottom-left-radius:11px; }
.rl-zbar > div:last-child  { border-top-right-radius:11px;
                             border-bottom-right-radius:11px; }
.rl-zbar .zn { font-size:.68rem; font-weight:750; letter-spacing:-.01em; }
.rl-zbar .zr { font-size:.63rem; font-weight:600; opacity:.75;
               font-variant-numeric:tabular-nums; }
.rl-zends { display:flex; justify-content:space-between; margin-top:5px;
            font-size:.68rem; color:var(--text-3); font-variant-numeric:tabular-nums; }
</style>
"""

_PC = """
<style>
/* PC에서 한 화면에 더 많이 — 2단 카드 그리드가 좁아지지 않게 폭을 넓힙니다.
   (RUNALYZE처럼 숫자를 빽빽하게 보는 쪽에 맞춘 값입니다) */
.block-container { max-width:1440px; padding-left:2.1rem; padding-right:2.1rem; }
div[data-testid="stVerticalBlockBorderWrapper"] { padding:6px 8px; }
div[data-testid="stMetricValue"] { font-size:1.9rem !important; }
.stTabs [data-baseweb="tab"] { height:40px; font-size:.9rem; }
.rl-title { font-size:1.45rem; }

/* 표는 촘촘하게 — 한 화면에 몇 줄 더 들어옵니다 */
[data-testid="stDataFrame"] { font-size:.82rem; }
[data-testid="stDataFrame"] [role="columnheader"] { font-weight:650; }
</style>
"""

_MOBILE = """
<style>
.block-container { max-width:100%; padding:2.5rem .9rem 3.5rem; }
div[data-testid="stMetricValue"] { font-size:1.5rem !important; }
div[data-testid="stMetricLabel"] p { font-size:.66rem !important; }
div[data-testid="stHorizontalBlock"] { gap:.55rem !important; }

/* 좁은 화면에서도 한 줄로 유지할 묶음 — st.container(key="rl-row-…") 로 감싸면
   Streamlit이 자동으로 세로로 쌓는 것을 막습니다. ◀ 날짜 ▶ 처럼 셋이 한 벌일 때
   각각 한 줄씩 차지하면 화면의 절반을 먹어 버립니다. */
[class*="st-key-rlrow"] div[data-testid="stHorizontalBlock"] {
  flex-wrap:nowrap !important; gap:.4rem !important;
}
[class*="st-key-rlrow"] div[data-testid="stHorizontalBlock"]
  > div[data-testid="stColumn"] { min-width:0 !important; flex:1 1 0 !important; }
/* 화살표 칸만 좁게 — 가운데 입력칸이 남은 폭을 다 씁니다 */
[class*="st-key-rlrow_histnav"] div[data-testid="stHorizontalBlock"]
  > div[data-testid="stColumn"]:first-child,
[class*="st-key-rlrow_histnav"] div[data-testid="stHorizontalBlock"]
  > div[data-testid="stColumn"]:last-child { flex:0 0 46px !important; }
[class*="st-key-rlrow"] .stButton>button { padding:0 !important; }
/* 한 줄에 둘 이상 들어가면 칸이 좁습니다 — 숫자 입력의 +/− 단추를 숨겨
   입력칸이 폭을 다 쓰게 합니다. 모바일에서는 어차피 키보드로 칩니다. */
[class*="st-key-rlrow"] [data-testid="stNumberInputStepUp"],
[class*="st-key-rlrow"] [data-testid="stNumberInputStepDown"] { display:none !important; }
/* 좁은 칸에서 라벨이 두 줄로 접히면 높이가 어긋납니다 — 글자만 살짝 줄입니다 */
[class*="st-key-rlrow_auto"] [data-testid="stWidgetLabel"] p { font-size:.78rem; }

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


_NAV = """
<style>
/* ── 이동 줄 ────────────────────────────────────────────────────────────
   예전에는 항목마다 테두리 상자를 둘러서 '버튼이 잔뜩 놓인 줄'로 보였습니다.
   위 줄은 **한 덩어리 트랙 위에 고른 것만 떠 있는** 세그먼트로, 아래 줄은
   **밑줄 글자**로 바꿔 둘의 층위를 눈으로 구분되게 했습니다. */
[class*="st-key-rlnav-"] [role="radiogroup"] {
  flex-wrap:wrap; gap:2px;
}
[class*="st-key-rlnav-"] [data-testid="stWidgetLabel"] { display:none; }
[class*="st-key-rlnav-"] button[data-variant="segmented_control"] {
  border:none !important; background:transparent !important;
  box-shadow:none !important; color:var(--text-2) !important;
  border-radius:8px !important; font-weight:600 !important;
  letter-spacing:-.01em; transition:background .14s ease, color .14s ease;
}
[class*="st-key-rlnav-"] button[data-variant="segmented_control"]:hover {
  color:var(--text) !important; background:var(--line-soft) !important;
}

/* 위 줄 — 회색 트랙 위에 흰 칩이 하나 떠 있는 모양 */
[class*="st-key-rlnav-nav_sec"] [role="radiogroup"] {
  background:var(--surface-2); border:1px solid var(--line);
  border-radius:11px; padding:3px; gap:2px;
}
[class*="st-key-rlnav-nav_sec"] button[data-variant="segmented_control"] {
  font-size:.9rem !important; padding:.42rem .9rem !important;
}
[class*="st-key-rlnav-nav_sec"] button[aria-checked="true"] {
  background:var(--surface) !important; color:var(--text) !important;
  box-shadow:var(--shadow-sm) !important; font-weight:700 !important;
}

/* 아래 줄 — 테두리 없이 글자 + 밑줄 */
[class*="st-key-rlnav-nav_scr"] { margin:.35rem 0 .9rem; }
[class*="st-key-rlnav-nav_scr"] [role="radiogroup"] {
  gap:.2rem; border-bottom:1px solid var(--line); padding:0;
  width:100%; justify-content:flex-start;
}
[class*="st-key-rlnav-nav_scr"] button[data-variant="segmented_control"] {
  flex:0 0 auto !important;
  font-size:.83rem !important; padding:.4rem .7rem !important;
  border-radius:7px 7px 0 0 !important; margin-bottom:-1px;
  border-bottom:2px solid transparent !important;
}
[class*="st-key-rlnav-nav_scr"] button[aria-checked="true"] {
  color:var(--accent-ink) !important; font-weight:700 !important;
  background:transparent !important;
  border-bottom:2px solid var(--accent) !important;
}
[class*="st-key-rlnav-nav_scr"] button[aria-checked="true"]:hover {
  background:transparent !important;
}

/* 머리 줄의 화면/잠금 — 이동 줄과 같은 결로, 조용하게 */
[class*="st-key-rlhead"] .stButton>button,
[class*="st-key-rlhead"] [data-testid="stPopover"] button {
  background:transparent !important; border:1px solid var(--line) !important;
  box-shadow:none !important; color:var(--text-2) !important;
  font-size:.82rem !important; font-weight:600 !important;
  min-height:34px !important; border-radius:8px !important;
}
[class*="st-key-rlhead"] .stButton>button:hover,
[class*="st-key-rlhead"] [data-testid="stPopover"] button:hover {
  color:var(--text) !important; background:var(--surface-2) !important;
  border-color:var(--line) !important;
}

/* 저장 알림 띠 — 토스트는 몇 초면 사라져서 놓치기 쉽습니다.
   직접 닫거나 한참 지나야 없어지도록 화면 위쪽에 남겨 둡니다. */
.rl-flash {
  background:var(--ok-bg); border:none; border-left:3px solid var(--ok);
  border-radius:0 8px 8px 0; padding:.5rem .8rem;
  font-size:.86rem; font-weight:600; color:var(--text);
  display:flex; align-items:center; gap:.45rem;
}
.rl-flash .i { font-size:.95rem; opacity:.9; }
[class*="st-key-rlflash"] { margin-bottom:.6rem; }
[class*="st-key-rlflash"] div[data-testid="stHorizontalBlock"] {
  flex-wrap:nowrap !important; gap:.25rem !important; align-items:center;
}
[class*="st-key-rlflash"] div[data-testid="stColumn"]:last-child {
  flex:0 0 34px !important; min-width:0 !important;
}
[class*="st-key-rlflash"] .stButton>button {
  background:transparent !important; border:none !important;
  box-shadow:none !important; color:var(--text-3) !important;
  min-height:0 !important; padding:.15rem !important; font-size:.8rem !important;
}
[class*="st-key-rlflash"] .stButton>button:hover { color:var(--text) !important; }

/* 카드 아래 '자세히 →' — 버튼이지만 링크처럼 보이게 */
[class*="st-key-rl-cardlink"] .stButton > button {
  background:transparent !important; border:none !important;
  box-shadow:none !important; color:var(--text-3) !important;
  font-size:.78rem !important; font-weight:500 !important;
  justify-content:flex-end !important; padding:2px 2px !important;
  min-height:0 !important; text-align:right !important;
}
[class*="st-key-rl-cardlink"] .stButton > button:hover {
  color:var(--text) !important; background:transparent !important;
}
</style>
"""


def _inject_css(mode: str, theme: str) -> None:
    css = (_BASE.replace("__FONT__", _FONT)
                .replace("__TOKENS__", _DARK if theme == "dark" else _LIGHT))
    st.markdown(css, unsafe_allow_html=True)
    st.markdown(_MOBILE if mode == "mobile" else _PC, unsafe_allow_html=True)
    st.markdown(_NAV, unsafe_allow_html=True)


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


def alerts(items: list[dict]) -> None:
    """체크포인트 줄 — Streamlit 기본 경고 블록 대신 카드 디자인에 맞춘 줄로 그립니다.
    items = [{"level": "error|warning|info", "msg": "..."}, ...]"""
    tone = {"error": ("bad", "\u26a0\ufe0f"), "warning": ("warn", "\u26a0\ufe0f"),
            "info": ("info", "\u2139\ufe0f"), "success": ("info", "\u2705")}
    html = ""
    for a in items:
        t, ic = tone.get(str(a.get("level", "info")), ("info", "\u2139\ufe0f"))
        msg = str(a.get("msg", ""))
        # 메시지가 이미 그림문자로 시작하면(예: "👟 …") 아이콘을 또 붙이지 않습니다
        if msg[:1] and unicodedata.category(msg[0]) == "So":
            ic = ""
        html += (f"<div class='rl-alert {t}'>"
                 + (f"<span class='ic'>{ic}</span>" if ic else "")
                 + f"<span>{msg}</span></div>")
    st.markdown(html, unsafe_allow_html=True)


def item_list(items: list[tuple[str, str]]) -> None:
    st.markdown("".join(f"<div class='rl-item'><div class='t'>{t}</div>"
                        f"<div class='m'>{m}</div></div>" for t, m in items),
                unsafe_allow_html=True)


def _numtxt(v) -> str:
    """스파크라인 툴팁용 숫자 표기 — 불필요한 소수점 0은 떼어냅니다."""
    f = float(v)
    return f"{f:,.0f}" if abs(f - round(f)) < 1e-9 else f"{f:,.2f}".rstrip("0").rstrip(".")


def _spark_svg(vals, tone: str = "") -> str:
    """작은 추세선(스파크라인)을 인라인 SVG로. 값이 2개 미만이면 빈 문자열.

    vals 는 숫자 목록이거나 (라벨, 숫자) 쌍의 목록입니다. 쌍으로 주면 점마다
    투명한 판정 영역을 깔고 <title>을 달아서, 마우스를 올리거나 길게 누르면
    '날짜 · 값'이 뜹니다.
    """
    labels, pts = [], []
    try:
        for v in vals:
            if isinstance(v, (tuple, list)) and len(v) == 2:
                lab, num = v
            else:
                lab, num = None, v
            if num is None:
                continue
            num = float(num)
            if num != num:                      # NaN
                continue
            labels.append("" if lab is None else str(lab))
            pts.append(num)
    except (TypeError, ValueError):
        return ""
    if len(pts) < 2:
        return ""
    labels, pts = labels[-30:], pts[-30:]
    lo, hi = min(pts), max(pts)
    rng = (hi - lo) or 1.0
    w, h, pad = 100.0, 26.0, 3.0
    step = w / (len(pts) - 1)
    col = {"ok": "var(--ok)", "warn": "var(--warn)", "bad": "var(--bad)"}.get(
        tone, "var(--accent)")
    xs = [i * step for i in range(len(pts))]
    ys = [pad + (h - 2 * pad) * (1 - (v - lo) / rng) for v in pts]
    d = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    hit = ""
    if any(labels):
        half = step / 2
        for x, lab, v in zip(xs, labels, pts):
            t = f"{lab} · {_numtxt(v)}" if lab else _numtxt(v)
            hit += (f"<rect x='{max(0.0, x - half):.2f}' y='0' "
                    f"width='{min(step, w):.2f}' height='{h:.0f}' fill='transparent'>"
                    f"<title>{t}</title></rect>")
    return (f"<svg class='spark' viewBox='0 0 {w:.0f} {h:.0f}' preserveAspectRatio='none'>"
            f"<polyline points='{d}' fill='none' stroke='{col}' stroke-width='1.6' "
            f"stroke-linecap='round' stroke-linejoin='round' vector-effect='non-scaling-stroke'/>"
            f"<circle cx='{xs[-1]:.1f}' cy='{ys[-1]:.1f}' r='1.8' fill='{col}'/>"
            f"{hit}</svg>")


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
    모바일에서는 Streamlit이 좁은 컬럼을 **자동으로 세로 스택**합니다. 그래서
    n_mobile을 2로 줘도 그냥 두면 한 칸씩 내려갑니다 — keep_row=True 로 부르면
    st-key-rlrow 컨테이너로 감싸서(ui.py의 모바일 CSS) 한 줄을 유지합니다.
    나란히 두어야 하는 '수치 표시'는 metrics() 그리드를 쓰세요.
    호출부의 c[i % len(c)] 패턴 덕분에 항목이 남으면 같은 컬럼에 이어 쌓입니다."""
    n = n_mobile if is_mobile() else n_pc
    if keep_row and n > 1 and is_mobile():
        # 키는 호출한 줄 번호로 만듭니다 — 재실행해도 같은 키가 나와야 합니다
        try:
            line = sys._getframe(1).f_lineno
        except Exception:                                   # pragma: no cover
            line = 0
        with st.container(key=f"rlrow_auto{n}_{line}"):
            return st.columns(n)
    return st.columns(n)


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
