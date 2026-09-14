"""
Running Life OS - 디자인 시스템 (ui.py)
=======================================
PC / 모바일 레이아웃 분기와 공통 UI 컴포넌트를 담당합니다.

  - 기기 감지 : User-Agent 자동 판별 + 헤더의 수동 전환 토글
  - PC 모드   : 다단 그리드, 넓은 차트, 표(dataframe) 중심
  - 모바일    : 1단 스택, 큰 탭 타깃, 표 대신 카드 리스트, 축약 라벨

app.py 에서:
    import ui
    ui.boot()                     # CSS 주입 + 모드 결정 (가장 먼저 1회)
    if ui.is_mobile(): ...
"""

from __future__ import annotations

import re
import streamlit as st

ACCENT = "#2563eb"

# ---------------------------------------------------------------------------
# 기기 모드
# ---------------------------------------------------------------------------
_MOBILE_UA = re.compile(r"Android|iPhone|iPad|iPod|IEMobile|Opera Mini|Mobile Safari|Silk", re.I)


def _detect_mobile() -> bool:
    try:
        ua = st.context.headers.get("User-Agent", "") or ""
    except Exception:
        return False
    return bool(_MOBILE_UA.search(ua))


def is_mobile() -> bool:
    return st.session_state.get("ui_mode", "pc") == "mobile"


def mode_switch(container=None) -> None:
    """헤더에 놓는 PC/모바일 수동 전환."""
    c = container or st
    cur = st.session_state.get("ui_mode", "pc")
    choice = c.radio(
        "화면 모드", ["💻 PC", "📱 모바일"],
        index=0 if cur == "pc" else 1,
        horizontal=True, label_visibility="collapsed", key="ui_mode_radio",
    )
    new = "mobile" if choice.startswith("📱") else "pc"
    if new != cur:
        st.session_state["ui_mode"] = new
        st.rerun()


def boot() -> None:
    """앱 시작 시 1회 — 모드 결정 후 해당 CSS 주입."""
    if "ui_mode" not in st.session_state:
        st.session_state["ui_mode"] = "mobile" if _detect_mobile() else "pc"
    _inject_css(st.session_state["ui_mode"])


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------
_BASE_CSS = """
<style>
:root {
  --rl-accent:#2563eb; --rl-accent-soft:#eff6ff;
  --rl-bg:#f6f7f9;  --rl-surface:#ffffff;
  --rl-text:#0f172a; --rl-muted:#64748b; --rl-line:#e5e7eb;
  --rl-ok:#059669;  --rl-warn:#d97706; --rl-bad:#dc2626;
  --rl-radius:16px;
}
@media (prefers-color-scheme: dark) {
  :root {
    --rl-accent:#60a5fa; --rl-accent-soft:#1e293b;
    --rl-bg:#0b1120; --rl-surface:#111827;
    --rl-text:#e2e8f0; --rl-muted:#94a3b8; --rl-line:#1f2937;
  }
}

/* ── 바탕 ─────────────────────────────────────────── */
.stApp { background: var(--rl-bg); }
#MainMenu, footer, header [data-testid="stDecoration"] { visibility:hidden; }
.block-container { padding-top:3.2rem; padding-bottom:4rem; }

html, body, [class*="css"] {
  font-feature-settings:"tnum" 1, "cv01" 1;
  -webkit-font-smoothing:antialiased;
}

/* ── 카드 (st.container(border=True)) ─────────────── */
div[data-testid="stVerticalBlockBorderWrapper"] {
  background: var(--rl-surface);
  border:1px solid var(--rl-line) !important;
  border-radius: var(--rl-radius) !important;
  box-shadow: 0 1px 2px rgba(15,23,42,.04), 0 8px 24px -16px rgba(15,23,42,.18);
  transition: box-shadow .18s ease, transform .18s ease;
}
div[data-testid="stVerticalBlockBorderWrapper"]:hover {
  box-shadow: 0 1px 2px rgba(15,23,42,.05), 0 14px 32px -18px rgba(15,23,42,.28);
}

/* ── 메트릭 ───────────────────────────────────────── */
div[data-testid="stMetric"] { padding:2px 0; }
div[data-testid="stMetricLabel"] p {
  font-size:.78rem !important; font-weight:600 !important;
  letter-spacing:.02em; color:var(--rl-muted) !important; text-transform:uppercase;
}
div[data-testid="stMetricValue"] {
  font-weight:700 !important; letter-spacing:-.02em;
  color:var(--rl-text) !important; font-variant-numeric:tabular-nums;
}
div[data-testid="stMetricDelta"] { font-size:.78rem !important; font-weight:600 !important; }

/* ── 탭 ───────────────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] {
  gap:4px; background:var(--rl-surface); padding:5px;
  border:1px solid var(--rl-line); border-radius:14px;
  overflow-x:auto; scrollbar-width:none;
}
.stTabs [data-baseweb="tab-list"]::-webkit-scrollbar { display:none; }
.stTabs [data-baseweb="tab"] {
  border-radius:10px; font-weight:600; color:var(--rl-muted);
  padding:0 14px; white-space:nowrap; background:transparent;
}
.stTabs [aria-selected="true"] {
  background:var(--rl-accent-soft) !important; color:var(--rl-accent) !important;
}
.stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] { display:none; }

/* ── 버튼 / 입력 ──────────────────────────────────── */
.stButton>button, .stDownloadButton>button, .stFormSubmitButton>button {
  border-radius:11px !important; font-weight:600 !important;
  border:1px solid var(--rl-line) !important; transition:all .15s ease;
}
.stButton>button[kind="primary"], .stFormSubmitButton>button {
  background:var(--rl-accent) !important; color:#fff !important; border-color:transparent !important;
}
.stButton>button:hover, .stFormSubmitButton>button:hover { transform:translateY(-1px); }
.stTextInput input, .stNumberInput input, .stDateInput input,
.stTextArea textarea, div[data-baseweb="select"]>div {
  border-radius:11px !important;
}

/* ── 커스텀 조각 ──────────────────────────────────── */
.rl-title { font-size:1.35rem; font-weight:750; letter-spacing:-.02em;
            color:var(--rl-text); margin:0; }
.rl-sub   { color:var(--rl-muted); font-size:.84rem; margin:2px 0 0; }
.rl-head  { font-size:.95rem; font-weight:700; color:var(--rl-text);
            margin:0 0 10px; display:flex; align-items:center; gap:7px; }
.rl-pill  { display:inline-block; padding:3px 10px; border-radius:999px;
            font-size:.74rem; font-weight:700; letter-spacing:.01em; }
.rl-pill.ok   { background:rgba(5,150,105,.12);  color:var(--rl-ok); }
.rl-pill.warn { background:rgba(217,119,6,.14);  color:var(--rl-warn); }
.rl-pill.bad  { background:rgba(220,38,38,.12);  color:var(--rl-bad); }
.rl-pill.info { background:var(--rl-accent-soft); color:var(--rl-accent); }

.rl-row { display:flex; justify-content:space-between; align-items:baseline;
          padding:9px 0; border-bottom:1px solid var(--rl-line); }
.rl-row:last-child { border-bottom:none; }
.rl-row .k { color:var(--rl-muted); font-size:.83rem; }
.rl-row .v { font-weight:650; font-variant-numeric:tabular-nums; color:var(--rl-text); }

.rl-item { padding:11px 0; border-bottom:1px solid var(--rl-line); }
.rl-item:last-child { border-bottom:none; }
.rl-item .t { font-weight:650; color:var(--rl-text); font-size:.92rem; }
.rl-item .m { color:var(--rl-muted); font-size:.79rem; margin-top:3px;
              font-variant-numeric:tabular-nums; }

.rl-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px 10px; }
.rl-grid.c3 { grid-template-columns:repeat(3,minmax(0,1fr)); }
.rl-mt .l { font-size:.7rem; font-weight:600; letter-spacing:.02em; text-transform:uppercase;
            color:var(--rl-muted); }
.rl-mt .v { font-size:1.5rem; font-weight:700; letter-spacing:-.02em; line-height:1.25;
            color:var(--rl-text); font-variant-numeric:tabular-nums; }
.rl-mt .d { font-size:.74rem; font-weight:600; color:var(--rl-muted); margin-top:1px; }

.rl-bar { height:7px; background:var(--rl-line); border-radius:99px; overflow:hidden; margin-top:8px; }
.rl-bar > i { display:block; height:100%; border-radius:99px; background:var(--rl-accent); }
.rl-bar > i.warn { background:var(--rl-warn); }
.rl-bar > i.bad  { background:var(--rl-bad); }
</style>
"""

_PC_CSS = """
<style>
.block-container { max-width:1280px; padding-left:2.2rem; padding-right:2.2rem; }
div[data-testid="stVerticalBlockBorderWrapper"] { padding:4px 6px; }
div[data-testid="stMetricValue"] { font-size:1.95rem !important; }
.stTabs [data-baseweb="tab"] { height:42px; font-size:.92rem; }
.rl-title { font-size:1.5rem; }
</style>
"""

_MOBILE_CSS = """
<style>
.block-container { max-width:100%; padding-left:.85rem; padding-right:.85rem;
                   padding-top:2.6rem; padding-bottom:3rem; }
div[data-testid="stMetricValue"] { font-size:1.55rem !important; }
div[data-testid="stMetricLabel"] p { font-size:.7rem !important; }

/* 손가락 타깃 확대 */
.stTabs [data-baseweb="tab"] { height:46px; font-size:.86rem; padding:0 12px; }
.stButton>button, .stFormSubmitButton>button { min-height:46px !important; font-size:.95rem !important; }
.stTextInput input, .stNumberInput input, .stDateInput input { min-height:44px !important; font-size:16px !important; }

div[data-testid="stHorizontalBlock"] { gap:.55rem !important; }
/* 모드 전환 라디오 축소 */
div[data-testid="stRadio"] label p { font-size:.8rem !important; }

.rl-title { font-size:1.18rem; }
.rl-sub { font-size:.78rem; }
[data-testid="stDataFrame"] { font-size:.8rem; }
</style>
"""


def _inject_css(mode: str) -> None:
    st.markdown(_BASE_CSS, unsafe_allow_html=True)
    st.markdown(_MOBILE_CSS if mode == "mobile" else _PC_CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# 컴포넌트
# ---------------------------------------------------------------------------
def card(key: str | None = None):
    """테두리 카드 컨테이너. `with ui.card():` 로 사용."""
    try:
        return st.container(border=True, key=key)
    except TypeError:
        return st.container(border=True)


def head(text: str, sub: str | None = None) -> None:
    st.markdown(f"<p class='rl-head'>{text}</p>"
                + (f"<p class='rl-sub' style='margin-top:-8px'>{sub}</p>" if sub else ""),
                unsafe_allow_html=True)


def pill(text: str, tone: str = "info") -> str:
    return f"<span class='rl-pill {tone}'>{text}</span>"


def rows(pairs: list[tuple[str, str]]) -> None:
    html = "".join(f"<div class='rl-row'><span class='k'>{k}</span>"
                   f"<span class='v'>{v}</span></div>" for k, v in pairs)
    st.markdown(html, unsafe_allow_html=True)


def bar(pct: float, tone: str = "") -> None:
    p = max(0.0, min(100.0, float(pct)))
    st.markdown(f"<div class='rl-bar'><i class='{tone}' style='width:{p:.1f}%'></i></div>",
                unsafe_allow_html=True)


def item_list(items: list[tuple[str, str]]) -> None:
    """모바일용 카드 리스트 (제목, 보조설명)."""
    html = "".join(f"<div class='rl-item'><div class='t'>{t}</div>"
                   f"<div class='m'>{m}</div></div>" for t, m in items)
    st.markdown(html, unsafe_allow_html=True)


def tone_for(level: str) -> str:
    return {"error": "bad", "warning": "warn", "info": "info", "success": "ok"}.get(level, "info")


def chart_height(pc: int = 280, mobile: int = 210) -> int:
    return mobile if is_mobile() else pc


def cols(n_pc: int, n_mobile: int = 1, keep_row: bool = False):
    """PC/모바일 컬럼 수 분기.
    모바일에서는 Streamlit이 좁은 폭의 컬럼을 자동으로 세로 스택하므로 항상 n_mobile을 씁니다.
    모바일에서도 나란히 두어야 하는 수치는 metrics() 그리드를 사용하세요.
    호출부의 c[i % len(c)] 패턴 덕분에 항목이 남으면 같은 컬럼에 이어서 쌓입니다."""
    return st.columns(n_mobile if is_mobile() else n_pc)


def metrics(items, per_row_pc: int | None = None, per_row_mobile: int = 2) -> None:
    """수치 카드 묶음. items = [(라벨, 값, 델타 or None), ...]
    PC는 st.metric, 모바일은 CSS 그리드로 렌더해 좁은 화면에서도 2~3단을 유지합니다."""
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
            # 실제 증감(+/-)만 st.metric 델타(화살표·색)로, 설명 문구는 회색 캡션으로
            if isinstance(d, str) and d[:1] in "+-":
                c.metric(l, v, d)
            else:
                c.metric(l, v)
                if d not in (None, ""):
                    c.markdown(f"<span class='rl-sub' style='font-size:.76rem;"
                               f"display:block;margin-top:-8px'>{d}</span>",
                               unsafe_allow_html=True)
