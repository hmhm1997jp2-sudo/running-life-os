"""
Running Life OS — 개인 러닝 관리·분석 시스템
============================================
필요 파일 : app.py / ui.py / db.py / analytics.py / requirements.txt
저장소    : Google Sheets (st.secrets 설정 시) 또는 로컬 엑셀 (자동 대체)
"""

import hashlib
import inspect
import re
import uuid
from datetime import datetime, timedelta, date, time as dtime

import numpy as np
import pandas as pd
import unicodedata

import streamlit as st

st.set_page_config(page_title="Running Life OS", page_icon="🏃",
                   layout="wide", initial_sidebar_state="collapsed")

import altair as alt
import ui
import db
import analytics as ana

# ── 파일 버전 불일치 방지 ──────────────────────────────────────────────
# app.py 만 올리고 나머지를 빠뜨리면 AttributeError 가 납니다.
# 원인을 바로 알 수 있도록 시작 시점에 검사합니다.
# 파일 버전 불일치 가드 — app.py가 실제로 쓰는 이름을 전부 확인합니다.
# (목록 갱신: python tools/refresh_required.py 또는 app.py의 ana./db./ui. 사용처를 재수집)
_REQUIRED = {
    "analytics.py": (ana, ["BELOW_Z1", "LAP_ROLES", "PRIMARY_BENEFIT", "PR_CATEGORIES",
                           "TRAINING_STATUS", "TRAINING_STATUS_KR", "WATCH_MODEL",
                           "ZONE_MODELS", "age_from_birth", "assign_zones", "bpm_to_pct",
                           "build_alerts", "classify_laps", "daily_load_series", "decoupling",
                           "decoupling_verdict", "detect_prs", "effective_load_ratio",
                           "effective_vo2max", "efficiency_factor", "endurance_meta",
                           "garmin_alerts", "garmin_race_predictions", "garmin_vs_computed",
                           "has_watch_zones", "hill_meta", "intensity_distribution",
                           "interval_shape", "lap_role_summary", "latest_garmin",
                           "load_focus", "load_ratio_meta", "load_summary", "pace_str",
                           "parse_time_str", "parse_zone_pcts", "predict_time",
                           "preferred_zone_model", "prepare_workouts", "profile_changes",
                           "profile_history", "race_plan", "readiness_factors",
                           "readiness_meta", "recovery_meta", "recovery_remaining",
                           "resolve_lthr", "set_watch_zones", "shoe_mileage", "stage_to_role",
                           "status_meta", "time_str", "training_paces",
                           "vdot_from_performance", "weekly_summary", "zone_bounds",
                           "zone_history", "zone_pace_trend", "zone_segments", "zone_table"]),
    "ui.py":        (ui, ["bar", "boot", "card", "chart_height", "cols", "head", "hero",
                          "is_dark", "is_mobile", "item_list", "metrics", "mode_switch",
                          "pill", "rows", "tiles"]),
    "db.py":        (db, ["append_rows", "backend_name", "diagnose", "export_excel_bytes",
                          "get_athlete", "init_db", "load_data", "repair", "repair_preview",
                          "reset_db", "save_athlete", "upsert_row", "write_sheet"]),
}
_stale = [(f, [a for a in attrs if not hasattr(m, a)]) for f, (m, attrs) in _REQUIRED.items()
          if [a for a in attrs if not hasattr(m, a)]]
# 스키마에 있어야 하는 컬럼 (함수 이름만으로는 잡히지 않는 버전 차이)
_need_cols = {"Laps": ["LapRole", "GapPaceSec"], "Athlete": ["RunZonePct"],
              "Workouts": ["GapPaceSec"],
              "DailyStatus": ["RecoveryUntil", "SleepHistory", "StressHistory",
                              "EntryKind", "ChronicLoad"],
              "Shoes": ["InitialAsOf"]}
_miss_cols = [f"{sh}.{c}" for sh, cs in _need_cols.items()
              for c in cs if c not in getattr(db, "SCHEMA", {}).get(sh, [])]
if _miss_cols:
    _stale.append(("db.py", [f"스키마 컬럼 {c}" for c in _miss_cols]))
if _stale:
    st.error("⚠️ 파일 버전이 서로 맞지 않습니다.")
    for f, miss in _stale:
        st.write(f"**{f}** — 없는 항목: `{', '.join(miss)}`")

    # 원인을 찍어서 보여줍니다.
    # 파일에는 최신 내용이 들어 있는데 이 화면이 나온다면, 새로 올린 파일이 아니라
    # '서버 메모리에 남아 있는 예전 파일'을 읽고 있는 것입니다(= 앱 재시작 필요).
    import os as _os
    import time as _time
    st.markdown("**지금 앱이 실제로 읽고 있는 파일**")
    _rows = []
    for _f, (_m, _attrs) in _REQUIRED.items():
        _path = getattr(_m, "__file__", "?")
        try:
            _mt = _time.strftime("%m/%d %H:%M", _time.localtime(_os.path.getmtime(_path)))
            _sz = f"{_os.path.getsize(_path):,} B"
        except Exception:
            _mt, _sz = "?", "?"
        _rows.append(f"- `{_path}` · 파일 시각 {_mt} · {_sz}")
    st.markdown("\n".join(_rows))
    st.info(
        "**파일 시각이 방금 올린 시각과 같은데도** 이 화면이 나오면, 파일은 맞고 "
        "서버가 예전 내용을 그대로 쥐고 있는 것입니다. Streamlit Cloud 화면 오른쪽 "
        "아래 **Manage app → ⋮ → Reboot app** 으로 앱을 한 번 재시작해 주세요.\n\n"
        "파일 시각이 옛날이면 그 파일이 저장소에 반영되지 않은 것입니다 — "
        "GitHub에서 해당 파일을 열어 내용을 확인해 주세요.")
    st.stop()

ui.boot()


# ═══════════════════════════════════════════════════════════════════════════
# 차트 공통 스타일 — 모든 Altair 차트에 한 번에 적용됩니다.
#   · 테두리·눈금선 제거, 가로 점선 그리드만 남김 (요즘 대시보드 스타일)
#   · Pretendard 적용, 막대 모서리 둥글게, 범례는 위쪽 가로 배치
# ═══════════════════════════════════════════════════════════════════════════
CHART_FONT = ('"Pretendard Variable", Pretendard, -apple-system, "Segoe UI", '
              'Roboto, "Malgun Gothic", sans-serif')

# ── 색 팔레트 ────────────────────────────────────────────────────────────
# 검증된 8색 카테고리 팔레트. 라이트/다크는 '같은 8가지 색을 각 배경에 맞춰
# 다시 고른 것'이며, 색각 이상(적록·청황) 구분과 배경 대비를 스크립트로
# 검증해 통과한 조합입니다. 순서를 바꾸거나 9번째 색을 만들어 쓰지 않습니다.
_PALETTE_LIGHT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100",
                  "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
_PALETTE_DARK = ["#3987e5", "#d95926", "#199e70", "#c98500",
                 "#d55181", "#008300", "#9085e9", "#e66767"]

# 심박존 5색 — 차가움→뜨거움으로 읽히는 '의미 있는 열 스케일'.
# 존 이름과 bpm이 항상 옆에 붙으므로 색만으로 정보를 나르지 않습니다.
# Z1(가장 낮음) → Z5(가장 높음)로 갈수록 차갑다 → 뜨겁다로 읽히게 한 순서 램프입니다.
# 존 이름과 bpm이 항상 옆에 붙으므로 색만으로 정보를 나르지 않습니다.
_ZONES_LIGHT = ["#9ec5f4", "#2a78d6", "#1baf7a", "#eda100", "#d94a4a"]
_ZONES_DARK = ["#5598e7", "#256abf", "#199e70", "#c98500", "#d94a4a"]

# 차트 크롬(배경·눈금·글자) — 배경 한 단계 위의 헤어라인만 남깁니다.
_CHROME_LIGHT = {"surface": "#ffffff", "grid": "#e9ebef", "axis": "#d7dbe2",
                 "muted": "#7c8698", "ink": "#14181f"}
_CHROME_DARK = {"surface": "#151a23", "grid": "#252c39", "axis": "#2f3847",
                "muted": "#8590a3", "ink": "#e8ecf3"}


def viz_colors() -> dict:
    """현재 테마에 맞는 차트 색 묶음. 스크립트 재실행마다 새로 계산됩니다."""
    dark = ui.is_dark()
    pal = _PALETTE_DARK if dark else _PALETTE_LIGHT
    ch = dict(_CHROME_DARK if dark else _CHROME_LIGHT)
    ch.update({
        "palette": pal, "zones": _ZONES_DARK if dark else _ZONES_LIGHT,
        "primary": pal[0], "accent": pal[1], "teal": pal[2], "amber": pal[3],
        "pink": pal[4], "green": pal[5], "violet": pal[6], "red": pal[7],
        # 순차(연속) 스케일 — 한 가지 색의 밝기 변화만 씁니다
        "seq": ["#e8f0fc", pal[0]] if not dark else ["#1b2536", pal[0]],
        "pale": "#eef1f7" if not dark else "#1b2230",
        "slate": "#8590a3",
    })
    return ch


C = viz_colors()
CHART_PALETTE = C["palette"]


def ramp(n: int, lo: str = None, hi: str = None) -> list[str]:
    """lo → hi 로 이어지는 n개 색(한 가지 색의 밝기 변화). 기본은 순차 스케일."""
    lo = lo or C["seq"][0]
    hi = hi or C["seq"][1]

    def _rgb(h):
        h = h.lstrip("#")
        return [int(h[i:i + 2], 16) for i in (0, 2, 4)]
    a, b = _rgb(lo), _rgb(hi)
    if n <= 1:
        return [hi]
    return ["#%02x%02x%02x" % tuple(
        round(a[k] + (b[k] - a[k]) * i / (n - 1)) for k in range(3))
        for i in range(n)]


def STATUS_COLORS() -> list[str]:
    """트레이닝 상태 8단계 — 나쁨 / 주의 / 중립 / 좋음 네 묶음으로만 칠합니다.
    Y축에 상태 이름이 이미 적혀 있어서 색이 여덟 가지일 필요가 없고,
    비슷한 초록 두 개(유지·생산적)는 오히려 구분이 안 됐습니다."""
    bad, warn, calm, good = C["red"], C["amber"], C["primary"], C["green"]
    return [bad, bad, warn, warn, calm, calm, good, good]


def chart_theme():
    """모든 Altair 차트 공통 스타일.
    · 테두리·축선·눈금 제거, 가로 실선 헤어라인 그리드만 (점선은 노이즈)
    · 선 2px, 점 8px에 배경색 링, 막대는 끝만 둥글게 + 두께 제한
    · 면(area)은 10% 워시 — 큰 색면은 만들지 않습니다
    """
    c = viz_colors()
    return {"config": {
        "font": CHART_FONT,
        "background": "transparent",
        "view": {"stroke": None},
        "padding": {"left": 2, "right": 8, "top": 6, "bottom": 2},
        "axis": {"labelFont": CHART_FONT, "titleFont": CHART_FONT,
                 "labelColor": c["muted"], "titleColor": c["muted"],
                 "labelFontSize": 11, "titleFontSize": 11, "titleFontWeight": 500,
                 "domain": False, "ticks": False, "labelPadding": 8, "titlePadding": 12,
                 "gridColor": c["grid"], "gridWidth": 1, "gridOpacity": 1,
                 "labelOverlap": "greedy"},
        "axisX": {"grid": False},
        "legend": {"labelFont": CHART_FONT, "titleFont": CHART_FONT,
                   "labelColor": c["muted"], "titleColor": c["muted"],
                   "labelFontSize": 11, "titleFontSize": 11,
                   "symbolType": "stroke", "symbolStrokeWidth": 3, "symbolSize": 90,
                   "orient": "top", "direction": "horizontal",
                   "offset": 6, "padding": 0, "titlePadding": 0, "labelOffset": 4},
        "bar": {"cornerRadiusEnd": 4, "continuousBandSize": 16},
        "scale": {"bandPaddingInner": 0.3},
        "line": {"strokeWidth": 2, "strokeCap": "round", "strokeJoin": "round"},
        "point": {"size": 64, "filled": True,
                  "stroke": c["surface"], "strokeWidth": 2},
        "circle": {"stroke": c["surface"], "strokeWidth": 1.5},
        "area": {"line": False, "opacity": 0.10},
        "rule": {"strokeWidth": 1.4},
        "text": {"font": CHART_FONT, "fontSize": 11, "color": c["muted"]},
        "title": {"font": CHART_FONT, "fontSize": 13, "anchor": "start",
                  "color": c["ink"], "fontWeight": 600, "offset": 8},
        "range": {"category": c["palette"]},
    }}


try:                                     # Altair 5.5+
    alt.theme.register("running_life_os", enable=True)(chart_theme)
except Exception:                        # 구버전 호환
    try:
        alt.themes.register("running_life_os", chart_theme)
        alt.themes.enable("running_life_os")
    except Exception:
        pass

WORKOUT_TYPES = ["Easy", "Recovery", "LSD", "Tempo", "Threshold",
                 "Interval", "Sprint", "Race", "Cross Training"]
SURFACES = ["로드", "트랙", "트레드밀", "트레일", "기타"]

# 러닝화 용도 — 복수 선택 (한 켤레가 여러 역할을 겸하는 경우가 많음)
SHOE_CATEGORIES = [
    "데일리 트레이너",   # 매일 신는 기본 쿠션화
    "롱런 / LSD",        # 장거리용 쿠션·안정성
    "회복 (맥스쿠션)",    # 리커버리런 전용, 두꺼운 쿠션
    "템포 / 업템포",      # 빠른 지속주
    "인터벌 / 스피드",    # 짧고 빠른 반복, 가벼움
    "레이스 (카본)",      # 대회용 카본 플레이트
    "트레일",
    "트레드밀",
    "워킹 / 일상",
]


def cat_list(v) -> list[str]:
    """쉼표로 저장된 용도 문자열 → 리스트"""
    return [c.strip() for c in str(v or "").split(",") if c.strip()]


# ═══════════════════════════════════════════════════════════════════════════
# 공통 유틸
# ═══════════════════════════════════════════════════════════════════════════
def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def src_key(d: str, dist: float, dur: float) -> str:
    return hashlib.md5(f"{str(d)[:10]}|{round(float(dist),2)}|{round(float(dur),1)}"
                       .encode()).hexdigest()[:16]


def fnum(v, default=0.0) -> float:
    try:
        f = float(v)
        return default if not np.isfinite(f) else f
    except (TypeError, ValueError):
        return default


# ═══════════════════════════════════════════════════════════════════════════
# 공용 레코드 수정 / 삭제기
#   fields: (컬럼, 타입, 라벨, 옵션) 리스트
#   타입   : text | area | num | numopt(0이면 빈칸 저장) | date | select
# ═══════════════════════════════════════════════════════════════════════════
def set_cells(df: pd.DataFrame, idx, values: dict) -> None:
    """한 행(idx)의 여러 칸을 채웁니다.

    값을 비웠을 때 숫자 열에 빈 문자열('')이 들어가는데, pandas 3.0부터는 이런
    대입을 조용히 받아주지 않고 TypeError를 냅니다. 들어갈 수 없는 값이면
    그 열을 object로 한 단계 올린 뒤 넣습니다. 다시 불러올 때 db가 숫자 열을
    다시 숫자로 바꾸므로(빈 값은 NaN), 저장 형식은 그대로 유지됩니다.
    """
    for col, v in values.items():
        if col not in df.columns:
            df[col] = ""
        try:
            df.loc[idx, col] = v
        except (TypeError, ValueError):
            df[col] = df[col].astype(object)
            df.loc[idx, col] = v


def record_editor(sheet: str, id_col: str, label_fn, fields, key: str,
                  derive=None, title: str = "✏️ 수정 / 삭제",
                  row_filter=None, empty_msg: str | None = None,
                  default_open: bool = False, note: str | None = None) -> None:
    df = db.load_data(sheet)          # 저장/삭제는 항상 전체 df 기준 (다른 행 유실 방지)
    if df.empty:
        return
    view = df if row_filter is None else row_filter(df)
    if view.empty:
        if empty_msg:
            with ui.card(f"ed_{key}"):
                st.caption(empty_msg)
        return
    with ui.card(f"ed_{key}"):
        # 저장 직후에도 펼쳐진 상태를 유지 (매번 다시 여는 번거로움 방지)
        with st.expander(title, expanded=st.session_state.get(f"exp_{key}", default_open)):
            if note:
                st.caption(note)
            # 목록은 '넣은 순서'가 아니라 '날짜 최신순'이어야 찾기 쉽습니다.
            # 날짜 칸은 fields 에서 type 이 'date' 인 것을 자동으로 씁니다.
            _dcol = next((c for c, t, *_ in fields if t == "date"), None)
            _v = view.copy()
            if _dcol and _dcol in _v.columns:
                _v["_ord"] = pd.to_datetime(_v[_dcol], errors="coerce")
                _v = _v.sort_values("_ord", ascending=False, kind="stable",
                                    na_position="last")
            else:
                _v = _v.iloc[::-1]

            # 기록이 쌓이면 목록이 끝없이 길어집니다 → 기본은 최근 것만.
            _RECENT = 40
            _all = st.checkbox(
                f"예전 기록까지 모두 보기 (전체 {len(_v)}건)", key=f"allrows_{key}",
                help="기본은 최근 40건만 보여줍니다. 목록에 직접 입력하면 검색도 됩니다.") \
                if len(_v) > _RECENT else True
            _shown = _v if _all else _v.head(_RECENT)

            opts, seen = {}, set()
            for _, r in _shown.iterrows():
                lab = label_fn(r)
                while lab in seen:          # 같은 라벨이 있으면 구분자 추가
                    lab += " "
                seen.add(lab)
                opts[lab] = r[id_col]
            pick = st.selectbox(
                "대상 선택", list(opts), key=f"sel_{key}",
                help="칸을 클릭하고 날짜를 입력하면 그 날짜만 걸러집니다.")
            rid = opts[pick]
            match = df[df[id_col].astype(str) == str(rid)]
            if match.empty:
                st.caption("대상을 찾지 못했습니다.")
                return
            row = match.iloc[0]

            # Streamlit은 key가 같으면 이전 입력값을 유지합니다.
            # 대상을 바꿨을 때 값이 안 바뀌는 문제를 막으려면 key에 레코드 ID를 넣어야 합니다.
            wk = f"{key}_{str(rid).replace(' ', '_')}"
            with st.form(f"form_{wk}"):
                vals = {}
                cs = ui.cols(2, 1)
                for i, (col, typ, label, opt) in enumerate(fields):
                    c = cs[i % len(cs)] if typ != "area" else st
                    cur = row.get(col, "")
                    if typ in ("num", "numopt"):
                        # %g → 162.00이 아니라 162로, 85.5는 85.5 그대로 보입니다.
                        # 네 번째 항목에 숫자를 주면 그게 +/- 버튼의 증감 단위가 됩니다
                        # (가민 피트니스 나이처럼 0.5 단위인 값 때문에).
                        _step = float(opt) if isinstance(opt, (int, float)) else 1.0
                        vals[col] = c.number_input(label, value=fnum(cur), step=_step,
                                                   format="%g", key=f"{wk}_{col}")
                    elif typ == "date":
                        # 빈 칸/NaT는 예외를 내지 않고 NaT를 돌려주므로 따로 걸러야
                        # 합니다 (그대로 넘기면 date_input이 터집니다).
                        dv = pd.to_datetime(cur, errors="coerce")
                        dv = dv.date() if pd.notna(dv) else date.today()
                        vals[col] = c.date_input(label, dv, key=f"{wk}_{col}")
                    elif typ == "select":
                        lst = list(opt or [])
                        idx = lst.index(str(cur)) if str(cur) in lst else 0
                        vals[col] = c.selectbox(label, lst, index=idx, key=f"{wk}_{col}")
                    elif typ == "multi":
                        lst = list(opt or [])
                        pre = [x for x in cat_list(cur) if x in lst]
                        vals[col] = c.multiselect(label, lst, default=pre, key=f"{wk}_{col}")
                    elif typ == "area":
                        vals[col] = st.text_area(label, str(cur or ""), height=90,
                                                 key=f"{wk}_{col}")
                    else:
                        vals[col] = c.text_input(label, str(cur or ""), key=f"{wk}_{col}")

                confirm = st.checkbox("🗑️ 삭제하려면 먼저 체크하세요", key=f"del_{wk}")
                if ui.is_mobile():
                    save = st.form_submit_button("💾 저장", width="stretch", type="primary")
                    dele = st.form_submit_button("🗑️ 삭제", width="stretch")
                else:
                    q1, q2 = st.columns(2)
                    save = q1.form_submit_button("💾 저장", width="stretch", type="primary")
                    dele = q2.form_submit_button("🗑️ 삭제", width="stretch")

                if save:
                    out = {}
                    for (col, typ, _l, _o) in fields:
                        v = vals[col]
                        if typ == "date":
                            out[col] = v.strftime("%Y-%m-%d")
                        elif typ == "multi":
                            out[col] = ", ".join(v)
                        elif typ == "numopt":
                            out[col] = "" if fnum(v) == 0 else v
                        else:
                            out[col] = v
                    if derive:
                        out.update(derive(out))
                    idx = df[id_col].astype(str) == str(rid)
                    set_cells(df, idx, out)
                    db.write_sheet(sheet, df)
                    st.session_state[f"exp_{key}"] = True
                    st.success("수정 완료")
                    st.rerun()

                if dele:
                    if not confirm:
                        st.error("삭제하려면 위의 확인 체크박스를 먼저 선택하세요.")
                    else:
                        db.write_sheet(sheet, df[df[id_col].astype(str) != str(rid)])
                        st.session_state[f"exp_{key}"] = False
                        st.warning("삭제 완료")
                        st.rerun()


# ── Metrics 시트는 두 종류의 행을 함께 담습니다 ───────────────────────────
#   ① 프로필 기준값 행 : LTHR·심박·체중 — 분석의 "기준"이라 과거 계산까지 바뀝니다
#   ② 가민 측정 기록 행 : VO2max·Endurance·Hill·Load Focus·예측 — 그냥 추이만 봅니다
# 각 탭의 수정/삭제 목록은 '그 탭이 다루는 값이 들어있는 행'만 보여줍니다.
METRIC_MEASURE_COLS = ["VO2Max", "FitnessAge", "EnduranceScore", "HillScore",
                       "FocusAnaerobic", "FocusHighAerobic", "FocusLowAerobic",
                       "Pred5K", "Pred10K", "PredHalf", "PredFull", "LTPace"]
METRIC_PROFILE_COLS = ["LTHR", "HRRest", "HRMax", "WeightKg", "BodyFatPct"]
PROFILE_ROW_NOTE = "프로필 변경"


_BLANKS = ["", "nan", "none", "nat", "<na>", "0", "0.0", "-", "—"]


def vtxt(v, fmt: str = "{}", dash: str = "—") -> str:
    """표시용 — 빈 값/NaN/0이면 대시."""
    if v is None:
        return dash
    sv = str(v).strip().lower()
    if sv in _BLANKS:
        return dash
    try:
        return fmt.format(float(v))
    except (ValueError, TypeError):
        return str(v)



def _has_any(df: pd.DataFrame, cols: list[str]) -> pd.Series:
    """지정한 컬럼 중 실제 값이 들어있는 행 = True.
    주의: pandas의 .str 접근자는 NaN을 그대로 통과시키므로 반드시 fillna 해야 합니다."""
    out = pd.Series(False, index=df.index)
    for c in cols:
        if c in df.columns:
            v = df[c].astype(str).str.strip().str.lower().fillna("")
            out |= ~v.isin(_BLANKS)
    return out


def has_measure_values(df: pd.DataFrame) -> pd.Series:
    """가민 측정값(VO2max·점수·예측 등)이 들어있는 행."""
    return _has_any(df, METRIC_MEASURE_COLS) if not df.empty else pd.Series(dtype=bool)


def has_profile_values(df: pd.DataFrame) -> pd.Series:
    """기준값(LTHR·심박·체중·체지방)이 들어있는 행 — 프로필 이력에 반영되는 행.
    예전에 가민 탭에서 함께 입력한 행도 여기 포함됩니다(실제로 이력에 쓰이니까)."""
    if df.empty:
        return pd.Series(dtype=bool)
    note = (df["Notes"].astype(str).str.strip().fillna("") if "Notes" in df.columns
            else pd.Series("", index=df.index))
    return _has_any(df, METRIC_PROFILE_COLS) | note.eq(PROFILE_ROW_NOTE)


def only_profile_rows(df: pd.DataFrame) -> pd.DataFrame:
    return df[has_profile_values(df)]


def only_measure_rows(df: pd.DataFrame) -> pd.DataFrame:
    return df[has_measure_values(df)]


# 날짜 축 — 하루보다 촘촘한 눈금('12 PM')이나 같은 날짜 반복이 생기지 않게 합니다.
# 차트 기간 선택 (None = 전체)
RANGE_DAYS = {"2주": 14, "1개월": 30, "3개월": 90, "6개월": 180, "1년": 365, "전체": None}


# 가민 '트레이닝 준비 상태' 화면의 최근 수면·스트레스 판정 문구
SLEEP_HIST_OPTS = ["(미입력)", "좋음", "보통", "나쁨"]
STRESS_HIST_OPTS = ["(미입력)", "낮음", "보통", "높음", "매우 높음"]

WD_KR = ["월", "화", "수", "목", "금", "토", "일"]

DAILY_TIMING_HELP = """
가민 일일 지표는 **하나의 시점에 찍히는 값이 아닙니다.** 크게 두 묶음입니다.

**🌅 아침에 정해지는 값** — 밤사이 수면·HRV로 계산되고, 그날 하루는 거의 고정입니다.
기상 직후에 보세요.

| 지표 | 성격 |
|---|---|
| Training Readiness | 아침에 한 번 산출. 낮에는 서서히 내려갑니다 |
| Body Battery | 자는 동안 충전 · 깨어 있는 동안 소모 → **기상 직후가 그날 최고값** |
| HRV (ms) · HRV 상태 | 밤사이 평균. 하루 동안 고정 |
| 수면 점수 · 안정시 심박 | 그날 아침에 확정 |

**🏃 훈련 뒤에 바뀌는 값** — 그날 훈련이 반영돼야 의미가 있습니다. 훈련을 마친 뒤에 보세요.

| 지표 | 성격 |
|---|---|
| Training Status | 활동이 끝나면 갱신 |
| 단기 부하 · 만성 부하 · 부하 비율 | 단기 부하는 최근 **7일 누적(가중 합)**, 만성 부하는 **28일** 기준. 훈련 직후에 올라갑니다 |
| 주간 고강도 분 | 이번 주 누적 — 주중에 계속 늘어납니다 |

**⏳ 회복 시간은 따로입니다** — 훈련이 끝난 순간부터 **계속 줄어드는 카운트다운**입니다.
아침 7시에 본 20시간과 밤 10시에 본 5시간은 같은 상태를 다르게 말한 것뿐입니다.
(수면이 나쁘거나 스트레스가 크면 가민이 중간에 조금 늘리기도 합니다.)

그래서 이 앱은 **본 시각을 함께 저장하고, 대시보드에서는 '지금 기준 남은 시간'으로 다시
계산해서** 보여줍니다. 몇 시에 넣든 대시보드 숫자는 같은 뜻이 됩니다.

**🔋 준비 상태(Readiness)를 만드는 여섯 요인** — 시계 ‘트레이닝 준비 상태 → 요인’과 같습니다.
수면 점수(지난밤) · 회복 시간 · HRV 상태 · 단기 부하 · **최근 수면 점수(3일)** ·
**최근 스트레스(3일)**. 뒤 두 개는 아침 체크인 창에 있습니다.

**성격이 사실 세 가지입니다**

| 종류 | 예 | 언제 넣나 |
|---|---|---|
| ① 밤사이 확정 | Readiness · 수면 점수 · HRV · 최근 수면 · 최근 스트레스 · 안정시 심박 · Body Battery | 아침 한 번 |
| ② 훈련해야 갱신 | Training Status · 주간 고강도 분 | 훈련 후 |
| ③ **본 시점의 값** | 단기 부하 · 만성 부하 · 회복 시간 | 볼 때마다 |

③은 계속 움직입니다. 단기 부하는 최근 7일을 **누적(가중 합)**한 값이라 훈련이
들어오면 올라가고 쉬면 조금씩 내려갑니다(평균이 아닙니다). 회복 시간은 훈련 종료부터 줄어드는 카운트다운이고요.
그래서 **아침 창과 훈련 후 창 양쪽에 있습니다** — 같은 값을 다른 시점에 본 것이고,
앱은 **나중에 본 쪽**을 씁니다(본 시각까지 비교합니다).

**권장 방식 — 창이 둘로 나뉘어 있습니다**

1. **🌅 아침 체크인** — 기상 직후 한 번. 준비 상태 화면에 보이는 대로 다 넣으면 됩니다.
2. **🏃 훈련 후 체크인** — 훈련한 날만. 훈련 종료 시각과 함께 부하 쪽을 한 번 더.

같은 날 같은 창에 다시 넣으면 **줄이 쌓이지 않고 그 줄이 갱신**됩니다. 비워 둔 칸은
앞서 넣은 값을 지우지 않으니, 생각날 때 일부만 채워 넣어도 됩니다.

매일 두 번 넣기 번거로우면 **아침 한 번만** 넣으셔도 됩니다. 그러면 부하 쪽 숫자가
하루 늦게 반영될 뿐, 추세를 보는 데는 문제없습니다.
"""

INTENSITY_HELP = """
**저·중·고강도 묶음** — 저강도 = **Z1~Z2**, 중강도 = **Z3~Z4**, 고강도 = **Z5** 입니다.
(‘📈 계산 통계’ 탭에서는 같은 것을 LT1/LT2 기준으로 부릅니다.)

**80/20 (양극화 훈련)** — 전체 훈련 시간의 **80% 이상을 저강도**로, 나머지를 확실한
고강도로 채우는 방식입니다. 대부분의 러너가 ‘애매하게 빠른’ 중강도에 시간을 너무
많이 쓰는데, 이러면 피로는 쌓이면서 효과는 적습니다.

**판정 기준**

| 조건 | 판정 |
|---|---|
| 저강도 78% 이상 · 중강도 12% 이하 | ✅ 폴라라이즈드 |
| 고강도 20% 이상 | 🚨 고강도 편중 |
| 중강도 25% 이상 | ⚠️ 회색지대 과다 |
| 저강도 78% 이상 | 피라미드형 |
| 저강도 65% 이상 | 무난 |
| 그 외 | ⚠️ 저강도 부족 |

위에서부터 먼저 걸리는 것 하나만 표시합니다.

**주의** — 존은 **세션 평균 심박**으로 판정합니다. 강약이 섞인 인터벌은 실제보다
중간 존으로 뭉뚱그려지므로, 중강도가 실제보다 부풀려 보일 수 있습니다.
랩이 저장된 훈련은 랩 단위로 판정하니 ‘📥 CSV 가져오기’로 활동 상세 CSV를 넣을수록
정확해집니다.
"""

DECOUPLING_HELP = """
**심박 디커플링 (Pa:HR)** — 훈련 **전반부와 후반부**의 ‘페이스 대비 심박 효율’을
비교한 값입니다. 후반부 효율이 얼마나 떨어졌는지를 %로 나타냅니다.

- 같은 페이스인데 후반에 **심박이 올라갔거나**, 같은 심박인데 후반에 **느려졌으면** ＋
- 후반이 더 효율적이었으면 －

**읽는 법**

- **＋5% 이내** — 유산소 지구력이 그 강도를 감당하고 있습니다. 좋은 신호입니다.
- **＋5 ~ 10%** — 경계. 그 페이스가 아직 살짝 버겁다는 뜻입니다.
- **＋10% 초과** — 지구력 부족, 초반 오버페이스, 더위·탈수·연료 부족 중 하나입니다.
  롱런에서 자주 나오면 **초반을 더 천천히** 가는 게 정답입니다.
- **－(마이너스)** — 후반이 더 좋았다는 뜻. 워밍업이 부족했거나 네거티브 스플릿입니다.

**주의** — LSD·이지런처럼 **강도가 일정한 훈련**에서만 의미가 있습니다.
인터벌처럼 강약이 반복되면 해석이 어렵고, 언덕·더위·바람도 값을 키웁니다.
"""


def period_range(anchor_day, unit: str):
    """기준 날짜가 속한 기간의 (시작일, 종료일). '전체'면 (None, None)."""
    if unit == "전체" or anchor_day is None:
        return None, None
    if unit == "월":
        start = anchor_day.replace(day=1)
        nxt = (start + timedelta(days=32)).replace(day=1)
        return start, nxt - timedelta(days=1)
    start = anchor_day - timedelta(days=anchor_day.weekday())   # 월요일
    return start, start + timedelta(days=6)


def period_shift(anchor_day, unit: str, n: int):
    """기준 날짜를 한 기간 앞/뒤로 옮깁니다."""
    if unit == "월":
        first = anchor_day.replace(day=1)
        for _ in range(abs(n)):
            first = ((first + timedelta(days=32)).replace(day=1) if n > 0
                     else (first - timedelta(days=1)).replace(day=1))
        return first
    return anchor_day + timedelta(days=7 * n)


def _span_days(sr) -> int:
    """날짜 시리즈가 걸쳐 있는 일수 (눈금 간격 결정용)."""
    try:
        d = pd.to_datetime(pd.Series(sr), errors="coerce").dropna()
        return int((d.max() - d.min()).days) + 1 if len(d) > 1 else 1
    except Exception:
        return 30


def _call_supported(fn, *args, **kwargs):
    """Streamlit 버전마다 받는 인자가 달라서, 그 함수가 실제로 받는 것만 넘깁니다.
    (배포 환경의 버전이 낮아 TypeError가 나는 것을 막습니다.)"""
    try:
        allowed = set(inspect.signature(fn).parameters)
    except (TypeError, ValueError):
        allowed = None
    if allowed is not None:
        kwargs = {k: v for k, v in kwargs.items() if k in allowed}
    return fn(*args, **kwargs)


def seg(label, options, key, default=None, help=None, collapsed=True):
    """세그먼트 컨트롤(Streamlit 1.40+). 없는 버전이면 가로 라디오로 대체합니다.
    항상 하나가 선택돼 있도록, 선택이 풀리면 기본값으로 되돌립니다."""
    opts = list(options)
    dv = default if default in opts else opts[0]
    vis = "collapsed" if collapsed else "visible"
    fn = getattr(st, "segmented_control", None)
    if fn is not None:
        try:
            v = _call_supported(fn, label, opts, default=dv, key=key, help=help,
                                label_visibility=vis)
            return v if v in opts else dv
        except Exception:
            pass                      # 아래 라디오로 대체
    return _call_supported(st.radio, label, opts, index=opts.index(dv),
                           horizontal=True, key=key + "_r", help=help,
                           label_visibility=vis)


X_HIDDEN = alt.Axis(labels=False, title=None, grid=False, domain=False, ticks=False)


def panel_title(label: str):
    """작은 그래프 칸의 이름표. 세로로 눕힌 Y축 제목은 읽기 어렵고 가로 폭만
    잡아먹어서, 칸 위에 가로로 한 줄 올립니다."""
    return alt.TitleParams(label, fontSize=11, fontWeight=600,
                           color=C["muted"], anchor="start", offset=2)


def dual_small_multiples(df, datecol, pairs, span, h_pc=96, h_mb=80):
    """단위가 다른 두 지표를 '위아래 작은 그래프' 두 칸으로. 날짜 축은 공유합니다.
    pairs = [(컬럼, 표시이름, 색, 숫자형식), ...]"""
    xax = date_axis(span)
    charts = []
    for i, (col, label, color, fmt) in enumerate(pairs):
        sub = df[[datecol, col]].dropna()
        if sub.empty:
            continue
        charts.append(alt.Chart(sub).mark_line(color=color, point=True).encode(
            x=alt.X(f"{datecol}:T", title=None,
                    axis=xax if i == len(pairs) - 1 else X_HIDDEN),
            y=alt.Y(f"{col}:Q", title=None, scale=alt.Scale(zero=False),
                    axis=alt.Axis(format=fmt, tickCount=3)),
            tooltip=[alt.Tooltip(f"{datecol}:T", title="날짜", format="%Y-%m-%d"),
                     alt.Tooltip(f"{col}:Q", title=label, format=fmt)]
        ).properties(height=ui.chart_height(h_pc, h_mb),
                     title=panel_title(label)))
    return charts or None


def stacked_charts(charts, gap=6):
    """위아래로 이어지는 작은 그래프들을 그립니다.
    Vega의 vconcat은 컨테이너 폭에 맞춰지지 않아(autosize 미지원) 카드 밖으로
    삐져나옵니다. 그래서 각각을 따로 그리고 사이 여백만 CSS로 줄입니다."""
    for i, c in enumerate(charts):
        if i:
            st.markdown(f"<div style='height:{gap}px'></div>", unsafe_allow_html=True)
        st.altair_chart(c, width="stretch")


def date_axis(n_days: int, title=None):
    """구간 길이에 맞춰 날짜 눈금 형식·간격을 고릅니다.
    tickMinStep은 시간 축에서 무시되는 경우가 있어 tickCount에 '일/주/월' 간격을
    직접 지정합니다. 이렇게 해야 '09/14, 09/14, 09/15'처럼 같은 날짜가 두 번
    찍히는 일이 없습니다."""
    n = max(int(n_days or 1), 1)
    if n <= 45:                       # 일 단위
        step = max(1, round(n / 12))
        return alt.Axis(title=title, format="%m/%d",
                        tickCount={"interval": "day", "step": step})
    if n <= 180:                      # 주 단위
        step = max(1, round(n / 7 / 12))
        return alt.Axis(title=title, format="%m/%d",
                        tickCount={"interval": "week", "step": step})
    if n <= 400:                      # 월 단위
        return alt.Axis(title=title, format="%Y/%m",
                        tickCount={"interval": "month", "step": 1})
    return alt.Axis(title=title, format="%Y/%m",
                    tickCount={"interval": "month", "step": 3})


RACE_DIST_KM = {"5km": 5.0, "10km": 10.0, "Half Marathon": 21.0975, "Full Marathon": 42.195}


# 존 색상 — 모든 차트에서 동일하게 유지 (Z1 연회색 → Z5 빨강)
ZONE_COLORS = C["zones"]      # 존 색은 테마에 맞춰 위에서 계산됩니다


def grid_at(cols, i: int, n: int):
    """n개 항목을 cols에 넣을 때, 모바일에서 세로로 쌓여도 순서가 유지되도록
    '열 우선'으로 칸을 고릅니다. Streamlit은 좁은 화면에서 컬럼을 통째로 위아래로
    쌓기 때문에, 흔한 i % len(cols) 방식은 Z1·Z4·Z2·Z5처럼 순서를 뒤섞습니다."""
    k = max(len(cols), 1)
    per = -(-n // k)                      # 올림 나눗셈
    return cols[min(i // per, k - 1)]


_ALERT_TONE = {"error": ("bad", "\u26a0\ufe0f"), "warning": ("warn", "\u26a0\ufe0f"),
               "info": ("info", "\u2139\ufe0f"), "success": ("info", "\u2705")}
_ALERT_COLOR = {"bad": "var(--bad)", "warn": "var(--warn)", "info": "var(--accent)"}


def render_alerts(items) -> None:
    """체크포인트 줄.

    ui.py 에 alerts()가 있으면 그걸 쓰고, 없으면(= ui.py 가 예전 버전이면)
    같은 모양을 여기서 직접 그립니다. 보기용 도우미 하나 때문에 앱 전체가
    멈추면 곤란하니, 이런 것은 '없으면 대신 그리는' 쪽으로 둡니다.
    """
    fn = getattr(ui, "alerts", None)
    if callable(fn):
        fn(items)
        return
    html = ""
    for a in items:
        t, ic = _ALERT_TONE.get(str(a.get("level", "info")), ("info", "\u2139\ufe0f"))
        msg = str(a.get("msg", ""))
        if msg[:1] and unicodedata.category(msg[0]) == "So":
            ic = ""
        html += (
            "<div style='display:flex;gap:10px;align-items:flex-start;"
            "padding:10px 12px;border-radius:10px;background:var(--surface-2);"
            f"border-left:3px solid {_ALERT_COLOR[t]};margin-bottom:7px;"
            "font-size:.86rem;line-height:1.5;color:var(--text)'>"
            + (f"<span style='line-height:1.45'>{ic}</span>" if ic else "")
            + f"<span>{msg}</span></div>")
    st.markdown(html, unsafe_allow_html=True)


def dday_tag(days) -> str:
    """한국식 D-day 표기. 남은 날은 D-41, 당일은 D-DAY, 지난 날은 '41일 지남'.
    (D+는 '지났다'는 뜻이라 남은 날에 쓰면 반대로 읽힙니다.)"""
    if days is None:
        return "—"
    d = int(days)
    return "D-DAY" if d == 0 else (f"D-{d}" if d > 0 else f"{-d}일 지남")


def tier_help_html(meta: dict, intro: str, note: str) -> str:
    """등급표 + 내 등급 하이라이트. Endurance / Hill 공용."""
    rows = ""
    for i, (name, kr, lo, hi) in enumerate(meta["bands"]):
        if lo is None:
            rng = f"~ {hi:,}"
        elif hi is None:
            rng = f"{lo:,} ~"
        else:
            rng = f"{lo:,} ~ {hi:,}"
        mine = (i == meta["index"])
        style = ("background:rgba(37,99,235,.14);font-weight:700;border-radius:6px"
                 if mine else "")
        mark = " ◀ 현재" if mine else ""
        rows += (f"<div class='rl-row' style='{style}'>"
                 f"<span class='k'>{kr} <span style='opacity:.55'>{name}</span>{mark}</span>"
                 f"<span class='v'>{rng}</span></div>")
    nxt = (f"<p class='rl-sub' style='margin:8px 0 0'>{meta['next_text']}</p>"
           if meta.get("next_text") else "")
    return (f"<div style='max-width:420px'>{intro}"
            f"<p class='rl-sub' style='margin:10px 0 6px'>"
            f"<b>{meta['bracket']}</b> · {note}</p>{rows}{nxt}</div>")


def zone_order(model: str) -> list[str]:
    return [n for n, _, _ in ana.ZONE_MODELS[model]] + [ana.BELOW_Z1]


def zone_scale(model: str):
    return alt.Scale(domain=zone_order(model), range=ZONE_COLORS + [C["pale"]])


def zone_bar_html(bounds, model: str) -> str:
    """bpm 축 위에 존 구간을 비율대로 그린 막대."""
    if not bounds:
        return ""
    lo0, hi0 = bounds[0][1], bounds[-1][2]
    span = max(hi0 - lo0, 1)
    seg = ""
    narrow = 13 if ui.is_mobile() else 8      # 이 폭보다 좁으면 bpm 숫자를 뺍니다
    tiny = 7 if ui.is_mobile() else 4.5       # 더 좁으면 이름도 뺍니다
    for i, (n, lo, hi) in enumerate(bounds):
        w = (hi - lo) / span * 100
        short = n.split()[0]
        # 칸에 안 들어가는 글자는 접거나 자르지 않고 아예 뺍니다.
        # 어차피 바로 아래 표에 존별 bpm이 모두 나옵니다.
        inner = ""
        if w >= tiny:
            inner += f"<span class='zn'>{short}</span>"
        if w >= narrow:
            inner += f"<span class='zr'>{lo:.0f}–{hi:.0f}</span>"
        seg += (f"<div title='{short} {lo:.0f}–{hi:.0f} bpm' "
                f"style='flex:0 0 {w:.2f}%;background:{ZONE_COLORS[i]};"
                f"color:{'#132030' if i in (0, 3) else '#ffffff'}'>"
                f"{inner}</div>")
    return (f"<div class='rl-zbar'>{seg}</div>"
            f"<div class='rl-zends'><span>{lo0:.0f} bpm</span>"
            f"<span>{hi0:.0f} bpm</span></div>")


def zone_compare_html(lthr, hr_rest, hr_max) -> str:
    """세 기준의 존 경계를 한 표로. 행=존, 열=기준."""
    models = list(ana.ZONE_MODELS)
    cols = {m: ana.zone_bounds(m, lthr, hr_rest, hr_max) for m in models}
    prim_m = ana.preferred_zone_model()
    if not cols.get(prim_m):
        return ""
    head = "".join(f"<th>{m}</th>" for m in models)
    body = ""
    for i in range(5):
        name = cols[prim_m][i][0]
        cells = ""
        for m in models:
            b = cols[m]
            klass = "prim" if m == prim_m else "sec"
            cells += (f"<td class='{klass}'>{b[i][1]:.0f}–{b[i][2]:.0f}</td>"
                      if b else f"<td class='sec'>—</td>")
        body += (f"<tr><td><span class='rl-zdot' style='background:{ZONE_COLORS[i]}'></span>"
                 f"{name}</td>{cells}</tr>")
    return f"<table class='rl-ztable'><tr><th>존</th>{head}</tr>{body}</table>"


def zone_model_picker(key: str) -> str:
    """심박존 기준 선택 (세션 공통)."""
    cur = st.session_state.get("zone_model", ana.preferred_zone_model())
    models = list(ana.ZONE_MODELS)
    pick = seg("존 기준", models, f"zm_{key}", cur, collapsed=False,
               help="⌚ 시계 러닝 존 = 가민 활동별(러닝) 심박존을 그대로 옮긴 값 · "
                    "%LTHR = 가민 기본 젖산역치 기준 · %HRmax = 최대심박 기준 · "
                    "%HRR = 심박 여유율(Karvonen)")
    st.session_state["zone_model"] = pick
    return pick


# ═══════════════════════════════════════════════════════════════════════════
# 로그인
# ═══════════════════════════════════════════════════════════════════════════
def secret(key: str, default=None):
    """secrets.toml 이 아예 없어도 예외 없이 동작."""
    try:
        return st.secrets[key]
    except Exception:
        return default


def auto_login_key() -> str | None:
    """Secrets의 AUTO_LOGIN_KEY — 없으면 자동 로그인 비활성."""
    k = secret("AUTO_LOGIN_KEY")
    return str(k) if k not in (None, "") else None


def logout() -> None:
    """로그아웃 — 세션과 URL 토큰을 함께 지웁니다."""
    st.session_state["auth"] = False
    try:
        st.query_params.clear()
    except Exception:
        pass
    st.rerun()


def check_password() -> bool:
    if st.session_state.get("auth"):
        return True

    # URL에 ?k=<AUTO_LOGIN_KEY> 가 붙어 있으면 비밀번호 없이 통과 (북마크용)
    ak = auto_login_key()
    if ak:
        try:
            if st.query_params.get("k") == ak:
                st.session_state["auth"] = True
                return True
        except Exception:
            pass

    real_pw = secret("APP_PASSWORD")
    pw_set = real_pw is not None
    _, mid, _ = st.columns([1, 2, 1]) if not ui.is_mobile() else (None, st.container(), None)
    with mid:
        with ui.card():
            st.markdown("<p class='rl-title'>🏃 Running Life OS</p>"
                        "<p class='rl-sub'>개인 러닝 관리 시스템 — 비밀번호를 입력하세요.</p>",
                        unsafe_allow_html=True)
            st.write("")
            pw = st.text_input("비밀번호", type="password", label_visibility="collapsed",
                               placeholder="Password")
            if st.button("입장", width="stretch", type="primary"):
                ok = (pw == real_pw) if pw_set else (pw == "running")
                if ok:
                    st.session_state["auth"] = True
                    st.rerun()
                st.error("비밀번호가 올바르지 않습니다.")
            if not pw_set:
                st.caption("⚠️ Secrets에 `APP_PASSWORD`가 없습니다. 임시 비밀번호: `running`")
    return False


if not check_password():
    st.stop()

db.init_db()
ATH = db.get_athlete()
HR_REST, HR_MAX = fnum(ATH.get("HRRest"), 55), fnum(ATH.get("HRMax"), 190)
LTHR = fnum(ATH.get("LTHR"), 0) or None
SEX = str(ATH.get("Sex", "M")) or "M"
# 프로필 이력의 '기본값'(가장 오래된 시점 이전에 적용할 값)
PROFILE_NOW = {"LTHR": LTHR, "HRRest": HR_REST, "HRMax": HR_MAX,
               "WeightKg": fnum(ATH.get("CurrentWeightKg"), 0) or None}


def _last_bodyfat() -> float:
    """체지방률은 Athlete 시트에 없으므로 Metrics의 가장 최근 값을 기본값으로 씁니다."""
    try:
        dm = db.load_data("Metrics")
        if dm.empty or "BodyFatPct" not in dm.columns:
            return 0.0
        d = dm.copy()
        d["_d"] = pd.to_datetime(d["MetricDate"], errors="coerce")
        d["_v"] = pd.to_numeric(d["BodyFatPct"], errors="coerce")
        d = d.dropna(subset=["_v"]).sort_values("_d")
        d = d[d["_v"] > 0]
        return float(d["_v"].iloc[-1]) if not d.empty else 0.0
    except Exception:
        return 0.0


LAST_BODYFAT = _last_bodyfat()
AGE = ana.age_from_birth(ATH.get("BirthDate"))   # 미입력이면 NaN (기본 21~39 기준)

# 가민 '스포츠 심박존(러닝)'이 입력돼 있으면 존 기준 목록 맨 앞에 등록합니다.
ana.set_watch_zones(ATH.get("RunZonePct"))
if ana.has_watch_zones() and "zone_model" not in st.session_state:
    st.session_state["zone_model"] = ana.WATCH_MODEL


# ═══════════════════════════════════════════════════════════════════════════
# 헤더
# ═══════════════════════════════════════════════════════════════════════════
if ui.is_mobile():
    st.markdown("<p class='rl-title'>🏃 Running Life OS</p>"
                f"<p class='rl-sub'>{db.backend_name()} · HR {HR_REST:.0f}–{HR_MAX:.0f}</p>",
                unsafe_allow_html=True)
    # 탭에도 '⚙️ 설정'이 있어서 이름이 겹치면 헷갈립니다 — 여긴 화면/잠금 전용
    with st.popover("⚙️ 화면", width="stretch"):
        ui.mode_switch()
        if st.button("🔒 잠금", width="stretch"):
            logout()
else:
    h1, h2, h3 = st.columns([7, 1.1, 1.1])
    h1.markdown("<p class='rl-title'>🏃 Running Life OS</p>"
                f"<p class='rl-sub'>{db.backend_name()} 연결됨 · "
                f"HR {HR_REST:.0f}–{HR_MAX:.0f} bpm</p>", unsafe_allow_html=True)
    # 화면 모드는 한 번 정하면 거의 안 바꾸는 값이라, 매 화면 위쪽을 차지하지 않도록
    # 팝오버 안으로 넣었습니다.
    with h2.popover("⚙️ 화면"):
        ui.mode_switch()
    if h3.button("🔒 잠금", width="stretch"):
        logout()

st.write("")


# 훈련 입력 폼에서 쓰는 선택지 — 탭 밖에서 한 번만 만들어 둡니다.
df_proj = db.load_data("Projects")
df_shoes = db.load_data("Shoes")
proj_opts = {"(없음)": ""} | {r["ProjectName"]: r["ProjectID"] for _, r in df_proj.iterrows()}
shoe_opts = {"(없음)": ""}
for _, r in df_shoes.iterrows():
    if str(r.get("Status", "")).upper() == "RETIRED":
        continue
    cats = cat_list(r.get("Category"))
    lab = f"{r['ShoeName']}" + (f" — {' / '.join(cats[:2])}" if cats else "")
    shoe_opts[lab] = r["ShoeID"]

# 모바일에서도 이름은 남깁니다 — 그림문자만 있으면 무슨 탭인지 알 수 없습니다.
# (탭 줄은 가로 스크롤되므로 글자가 들어가도 레이아웃이 깨지지 않습니다)
TAB_LABELS = (["🏠 오늘", "✍️ 기록", "📊 분석", "🎯 목표", "⚙️ 설정"] if ui.is_mobile()
              else ["🏠 오늘", "✍️ 기록", "📊 분석", "🎯 목표", "⚙️ 설정"])
tab_today, tab_log, tab_ana, tab_goal, tab_set = st.tabs(TAB_LABELS)


# ═════════════════════════════════════════════════════════════════════════
# TAB 1 · 오늘 — 지금 상태 한눈에
# ═════════════════════════════════════════════════════════════════════════
with tab_today:
    df_w = db.load_data("Workouts")
    df_daily = db.load_data("DailyStatus")
    df_metrics = db.load_data("Metrics")
    df_proj = db.load_data("Projects")
    df_shoes = db.load_data("Shoes")

    # 가민이 1차 지표 — 사용자가 Connect에서 보고 입력한 값을 그대로 씁니다.
    G = ana.latest_garmin(df_daily, df_metrics)

    # 계산 지표는 보조 — 기록으로부터 직접 산출 (교차검증용)
    daily = ana.daily_load_series(df_w, HR_REST, HR_MAX, SEX,
                                  hist=ana.profile_history(df_metrics, PROFILE_NOW))
    summary = ana.load_summary(daily)
    weekly = ana.weekly_summary(df_w)
    ZM = st.session_state.get("zone_model", ana.preferred_zone_model())
    P_HIST = ana.profile_history(df_metrics, PROFILE_NOW)
    _seg, _ = ana.zone_segments(df_w, db.load_data("Laps"))
    zoned = ana.assign_zones(_seg, ZM, P_HIST)
    inten = ana.intensity_distribution(zoned, ZM)
    evo2 = ana.effective_vo2max(df_w, HR_REST, HR_MAX)

    def gv(key, fmt="{}", suffix="", dash="—"):
        """가민 값 표시 — 미입력이면 —"""
        v = G.get(key)
        if v is None or str(v).strip() == "":
            return dash
        if isinstance(v, float) and not np.isfinite(v):
            return dash
        try:
            return fmt.format(v) + suffix
        except (ValueError, TypeError):
            return str(v) + suffix

    def gdate(key):
        d = G.get(key + "_date")
        return f"{d:%m/%d} 입력" if d is not None and pd.notna(d) else "미입력"

    TODAY = pd.Timestamp.now().normalize()

    def gage(key):
        """이 값이 며칠 전 것인지. 값이 없으면 None."""
        d = G.get(key + "_date")
        if d is None or pd.isna(d):
            return None
        return int((TODAY - pd.Timestamp(d).normalize()).days)

    def aged(key, sub=None, tone="", stale=3):
        """값의 나이를 보조설명에 붙이고, 오래됐으면 톤을 '주의'로.
        지표마다 입력 주기가 달라서 어떤 값은 오늘 것, 어떤 값은 며칠 전 것입니다.
        그걸 숨기면 옛날 값을 오늘 상태로 오해하게 됩니다."""
        n = gage(key)
        if n is None:
            return sub, tone
        mark = "" if n <= 0 else ("어제" if n == 1 else f"{n}일 전")
        if mark:
            sub = f"{sub} · {mark}" if sub else mark
            if n >= stale and tone == "":
                tone = "warn"
        return sub, tone

    def seen_at(keys):
        """이 묶음의 값들을 '언제 본 것'인지 — 날짜만이 아니라 시각까지.
        단기 부하·회복 시간처럼 볼 때마다 달라지는 값은 시각이 있어야 뜻이 통합니다."""
        ts = [pd.Timestamp(G.get(k + "_at")) for k in keys
              if G.get(k + "_at") is not None and pd.notna(G.get(k + "_at"))]
        if not ts:
            return "미입력"
        hi = max(ts)
        same_day = hi.normalize() == TODAY
        when = "오늘" if same_day else f"{hi:%m/%d}"
        return (f"{when} {hi:%H:%M} 기준" if (hi.hour or hi.minute)
                else f"{when} 입력")

    def date_span(keys):
        """한 묶음의 값들이 언제 들어왔는지 — 전부 같은 날이면 한 날짜만."""
        ds = [pd.Timestamp(G.get(k + "_date")).normalize() for k in keys
              if G.get(k + "_date") is not None and pd.notna(G.get(k + "_date"))]
        if not ds:
            return "미입력"
        lo, hi = min(ds), max(ds)
        return (f"{hi:%m/%d} 입력" if lo == hi
                else f"{lo:%m/%d} ~ {hi:%m/%d} 입력")

    def hist_series(df, datecol, col, n=30):
        """타일 스파크라인용 (날짜, 값) 목록 — 점마다 툴팁을 달기 위해 날짜도 함께."""
        if df is None or df.empty or col not in df.columns:
            return []
        t = df[[datecol, col]].copy()
        t[datecol] = pd.to_datetime(t[datecol], errors="coerce")
        t[col] = pd.to_numeric(t[col], errors="coerce")
        t = t.dropna().sort_values(datecol).tail(n)
        return [(d.strftime("%m/%d"), float(v)) for d, v in zip(t[datecol], t[col])]

    def section(label: str, right: str = ""):
        st.markdown(
            f"<div style='display:flex;justify-content:space-between;align-items:baseline;"
            f"margin:18px 2px 8px'><span style='font-size:.72rem;font-weight:700;"
            f"letter-spacing:.08em;text-transform:uppercase;color:var(--text-3)'>{label}</span>"
            f"<span style='font-size:.72rem;color:var(--text-3)'>{right}</span></div>",
            unsafe_allow_html=True)

    # ─────────────────────────────────────────────────────────────────
    # 히어로 — 오늘 상태
    # ─────────────────────────────────────────────────────────────────
    tone, kr, desc = ana.status_meta(G.get("TrainingStatus"))
    # 설명이 "생산적 — ..." 처럼 상태 이름으로 시작하면, 큰 제목과 겹치니 앞부분을 뗍니다
    if desc.startswith(f"{kr} — "):
        desc = desc[len(kr) + 3:]
    _lr_val, _lr_src = ana.effective_load_ratio(G)
    lr_tone, lr_txt = ana.load_ratio_meta(_lr_val)
    # 회복 시간은 계속 줄어드는 값이라, 입력 시각을 기준으로 '지금 남은 시간'을 다시 계산
    rc_left, rc_raw, rc_until, rc_live = ana.recovery_remaining(G)
    rc_tone, rc_txt = ana.recovery_meta(rc_left)
    if rc_live:
        rc_txt = (f"{rc_txt} · {rc_until} 완료 예상" if np.isfinite(rc_left) and rc_left > 0
                  else "회복 완료")
    hrv_status = str(G.get("HRVStatus") or "")
    hrv_tone = {"Balanced": "ok", "Unbalanced": "warn",
                "Low": "bad", "Poor": "bad"}.get(hrv_status, "")

    ui.hero(
        kr,
        ui.pill(str(G.get("TrainingStatus") or "No Status"), tone),
        desc,
        facts=[("TSB 폼", summary["tsb"] if summary else "—"),
               ("회복", f"{rc_left:.0f}h" if np.isfinite(rc_left) else "—"),
               ("안정시 심박", gv("RestingHR", "{:.0f}", " bpm")),
               ("입력한 날", gdate("TrainingStatus").replace(" 입력", ""))])

    alerts = ana.garmin_alerts(G) + ana.build_alerts(df_w, df_shoes, daily, weekly, inten)
    if alerts:
        with ui.card("alerts"):
            ui.head("🔔 오늘의 체크포인트")
            render_alerts(alerts[:6])

    # ─────────────────────────────────────────────────────────────────
    # 이번 주 — 가장 자주 보게 되는 숫자라 맨 위에 둡니다
    # (가민이 주는 값이 아니라 '내가 넣은 훈련 기록'을 그대로 더한 값)
    # ─────────────────────────────────────────────────────────────────
    _wk_start = (TODAY - pd.Timedelta(days=int(TODAY.dayofweek))).normalize()
    _wk_key = _wk_start.strftime("%Y-%m-%d")
    _left = 6 - int(TODAY.dayofweek)          # 오늘 빼고 이번 주에 남은 날
    _cur = (weekly.loc[_wk_key] if (not weekly.empty and _wk_key in weekly.index)
            else None)
    _wk_spark = ([(pd.Timestamp(i).strftime("%m/%d"), float(v))
                  for i, v in weekly["Distance"].tail(12).items()]
                 if not weekly.empty else [])

    def _wk(col, default=0.0):
        if _cur is None:
            return default
        v = pd.to_numeric(_cur.get(col), errors="coerce")
        return float(v) if np.isfinite(v) else default

    # 진행 중인 주를 '끝난 주'와 통째로 비교하면 항상 폭락한 것처럼 보입니다.
    # 그래서 주가 끝나기 전에는 지난주의 '같은 요일까지 누적'과 견줍니다.
    _pw_start = _wk_start - pd.Timedelta(days=7)
    _dw = ana.prepare_workouts(df_w)
    if not _dw.empty:
        _pw = _dw[(_dw["WorkoutDate"] >= _pw_start)
                  & (_dw["WorkoutDate"] < _wk_start)]
        _pw_same = _pw[(_pw["WorkoutDate"] - _pw_start).dt.days <= int(TODAY.dayofweek)]
        _prev_full = float(_pw["DistanceKm"].sum())
        _prev_same = float(_pw_same["DistanceKm"].sum())
    else:
        _prev_full = _prev_same = 0.0

    _base = _prev_full if _left <= 0 else _prev_same
    _base_txt = "지난주" if _left <= 0 else "지난주 같은 요일까지"
    if _base > 0:
        _wow = (_wk("Distance") - _base) / _base * 100
        # 모바일 타일은 두 칸 그리드라 긴 문구가 잘립니다 — 짧은 쪽을 씁니다
        _short = "지난주" if _left <= 0 else "같은 요일까지"
        _wow_sub = (f"{_short} {_wow:+.0f}%" if ui.is_mobile()
                    else f"{_base_txt} {_base:.1f}km 대비 {_wow:+.0f}%")
        # 증가율 경고(10% 룰)는 주가 끝났을 때만 — 주중 숫자는 아직 미완성이라서
        _wow_tone = ("warn" if (_left <= 0 and _wow > 10) else "")
    elif _wk("Distance") > 0:
        _wow_sub, _wow_tone = f"{_base_txt} 기록 없음", ""
    else:
        _wow_sub, _wow_tone = None, ""

    section("이번 주 · 내가 넣은 기록",
            f"{_wk_start:%m/%d} 시작 · " +
            ("마지막 날" if _left == 0 else f"{_left}일 남음"))
    ui.tiles([
        {"label": "이번 주 거리", "value": f"{_wk('Distance'):.1f}", "unit": "km",
         "sub": _wow_sub, "tone": _wow_tone, "spark": _wk_spark},
        {"label": "훈련 횟수", "value": f"{_wk('Runs'):.0f}", "unit": "회",
         "sub": (f"평균 {_wk('Distance') / max(_wk('Runs'), 1):.1f}km"
                 if _wk("Runs") else "아직 없음")},
        {"label": "가장 긴 런", "value": f"{_wk('LongRun'):.1f}", "unit": "km",
         "sub": (f"주간 거리의 {_wk('LongRun') / _wk('Distance') * 100:.0f}%"
                 if _wk("Distance") > 0 else None)},
        {"label": "이번 주 시간", "value": ana.time_str(_wk("Minutes") * 60),
         "sub": (f"평균 {ana.pace_str(_wk('Minutes') * 60 / _wk('Distance'))}"
                 if _wk("Distance") > 0 else None)},
    ])

    # ─────────────────────────────────────────────────────────────────
    # 타일 — 부하 / 컨디션 / 기량
    # ─────────────────────────────────────────────────────────────────
    _load_keys = ["AcuteLoad", "LoadRatio", "RecoveryTimeHr", "IntensityMinutes"]
    section("가민 · 트레이닝 부하 (본 시점의 값)", seen_at(_load_keys))
    _ch_v = pd.to_numeric(G.get("ChronicLoad"), errors="coerce")
    _al_s, _al_t = aged("AcuteLoad",
                        (f"만성 {_ch_v:,.0f}" if np.isfinite(_ch_v) and _ch_v > 0
                         else None))
    if _lr_src == "계산":
        # 계산값은 급성·만성을 본 시점의 값이라 '며칠 전' 표시가 따로 필요 없습니다
        _lr_s, _lr_t = "급성÷만성", lr_tone
    elif _lr_src == "만성 부하 필요":
        _lr_s, _lr_t = "만성 부하를 넣으면 계산됩니다", "warn"
    else:
        _lr_s, _lr_t = aged("LoadRatio", lr_txt, lr_tone)
    _rc_s, _rc_t = (rc_txt, rc_tone) if rc_live else aged("RecoveryTimeHr", rc_txt, rc_tone)
    _im_s, _im_t = aged("IntensityMinutes")
    ui.tiles([
        {"label": "단기 부하 (7일 누적)", "value": gv("AcuteLoad", "{:,.0f}"),
         "sub": _al_s, "tone": _al_t,
         "spark": hist_series(df_daily, "StatusDate", "AcuteLoad")},
        {"label": "부하 비율", "value": (f"{_lr_val:.2f}" if np.isfinite(_lr_val) else "—"),
         "sub": _lr_s, "tone": _lr_t,
         "spark": hist_series(df_daily, "StatusDate", "LoadRatio")},
        {"label": "회복 시간" + (" (지금 기준)" if rc_live else ""),
         "value": f"{rc_left:.0f}" if np.isfinite(rc_left) else "—", "unit": "시간",
         "sub": _rc_s, "tone": _rc_t,
         "spark": hist_series(df_daily, "StatusDate", "RecoveryTimeHr")},
        {"label": "주간 고강도", "value": gv("IntensityMinutes", "{:,.0f}"), "unit": "분",
         "sub": _im_s, "tone": _im_t,
         "spark": hist_series(df_daily, "StatusDate", "IntensityMinutes")},
    ])

    # 컨디션은 '그날 아침' 값이라 하루만 지나도 오늘 상태가 아닙니다 → 1일부터 표시
    _cond_keys = ["BodyBattery", "TrainingReadiness", "HRVms", "SleepScore"]
    section("가민 · 컨디션 (기상 직후 값)", date_span(_cond_keys))
    _bb_s, _bb_t = aged("BodyBattery", stale=1)
    _tr_s, _tr_t = aged("TrainingReadiness", stale=1)
    _hv_s, _hv_t = aged("HRVms", hrv_status or None, hrv_tone, stale=1)
    _sl_s, _sl_t = aged("SleepScore", stale=1)
    ui.tiles([
        {"label": "Body Battery", "value": gv("BodyBattery", "{:.0f}"),
         "sub": _bb_s, "tone": _bb_t,
         "spark": hist_series(df_daily, "StatusDate", "BodyBattery")},
        {"label": "Readiness", "value": gv("TrainingReadiness", "{:.0f}"),
         "sub": _tr_s, "tone": _tr_t,
         "spark": hist_series(df_daily, "StatusDate", "TrainingReadiness")},
        {"label": "HRV", "value": gv("HRVms", "{:.0f}"), "unit": "ms",
         "sub": _hv_s, "tone": _hv_t,
         "spark": hist_series(df_daily, "StatusDate", "HRVms")},
        {"label": "수면 점수", "value": gv("SleepScore", "{:.0f}"),
         "sub": _sl_s, "tone": _sl_t,
         "spark": hist_series(df_daily, "StatusDate", "SleepScore")},
    ])
    if any(gage(k) is not None and gage(k) >= 1 for k in _cond_keys):
        st.caption("⚠️ 컨디션 값은 **그날 아침** 기준입니다. 날짜가 지난 값은 오늘 상태가 "
                   "아니니, ‘✍️ 기록 → ⌚ 가민 일일’에서 오늘 값을 넣어주세요.")
    st.caption("타일 안의 작은 선은 **최근 30회 입력분**입니다 (마우스를 올리면 날짜별 값). "
               "더 긴 추세는 ‘📊 분석 → ⌚ 가민 추이’ 탭에서 기간을 골라 보세요.")

    # ── 트레이닝 준비 상태 요인 — 시계의 '요인' 화면과 같은 순서 ──────────
    _rd_tone, _rd_kr = ana.readiness_meta(G.get("TrainingReadiness"))
    _factors = ana.readiness_factors(G)
    if any(f["state"] != "—" for f in _factors):
        with ui.card("rdy"):
            ui.head("🔋 트레이닝 준비 상태 요인",
                    "시계의 ‘요인’ 화면과 같은 항목입니다 — 어떤 것이 점수를 "
                    "끌어내리고 있는지 한눈에 보려고 둡니다")
            _rows = ""
            for f in _factors:
                _dot = {"ok": "var(--ok)", "warn": "var(--warn)",
                        "bad": "var(--bad)"}.get(f["tone"], "var(--text-3)")
                _rows += (
                    "<div class='rl-row'>"
                    f"<span class='k'>{f['name']}"
                    + (f" <b style='color:var(--text-2)'>{f['value']}</b>"
                       if f["value"] else "")
                    + f" <span style='opacity:.65'>· {f['note']}</span></span>"
                    f"<span class='v'>{f['state']}"
                    f"<span style='display:inline-block;width:8px;height:8px;"
                    f"border-radius:50%;background:{_dot};margin-left:7px;"
                    f"vertical-align:middle'></span></span></div>")
            st.markdown(
                f"<div class='rl-row' style='border-bottom:none'>"
                f"<span class='k'>준비 상태 점수</span>"
                f"<span class='v' style='font-size:1.15rem'>"
                f"{gv('TrainingReadiness', '{:.0f}')} "
                f"{ui.pill(_rd_kr, _rd_tone)}</span></div>" + _rows,
                unsafe_allow_html=True)
            if any(f["state"] == "—" for f in _factors):
                st.caption("‘—’ 는 아직 안 넣은 항목입니다 — "
                           "‘✍️ 기록 → ⌚ 가민 일일 → 🌅 아침 체크인’에서 채우면 "
                           "여기가 시계 화면과 똑같아집니다.")

    em = ana.endurance_meta(G.get("EnduranceScore"), AGE, SEX)
    hm = ana.hill_meta(G.get("HillScore"))
    lt_txt = str(G.get("LTPace") or "")
    # 기량 지표는 주 1회 갱신이라 며칠 지난 것이 정상 → 14일부터 표시
    _fit_keys = ["VO2Max", "FitnessAge", "EnduranceScore", "HillScore"]
    section("가민 · 기량", date_span(_fit_keys))
    _v_s, _v_t = aged("VO2Max", (f"젖산역치 {lt_txt}" if lt_txt else None), stale=14)
    _fa_s, _fa_t = aged("FitnessAge", stale=14)
    _en_s, _en_t = aged("EnduranceScore", em["kr"], em["tone"], stale=14)
    _hl_s, _hl_t = aged("HillScore", hm["kr"], hm["tone"], stale=14)
    ui.tiles([
        {"label": "VO₂max", "value": gv("VO2Max", "{:.1f}"),
         "sub": _v_s, "tone": _v_t,
         "spark": hist_series(df_metrics, "MetricDate", "VO2Max")},
        {"label": "피트니스 나이", "value": gv("FitnessAge", "{:g}"), "unit": "세",
         "sub": _fa_s, "tone": _fa_t,
         "spark": hist_series(df_metrics, "MetricDate", "FitnessAge")},
        {"label": "Endurance", "value": gv("EnduranceScore", "{:,.0f}"),
         "sub": _en_s, "tone": _en_t,
         "spark": hist_series(df_metrics, "MetricDate", "EnduranceScore")},
        {"label": "Hill Score", "value": gv("HillScore", "{:.0f}"),
         "sub": _hl_s, "tone": _hl_t,
         "spark": hist_series(df_metrics, "MetricDate", "HillScore")},
    ])
    # 버튼을 각자 설명하는 타일 바로 아래에 둡니다 (3번째·4번째 칸)
    pop = ui.cols(4, 1)
    with pop[2 % len(pop)].popover("ℹ️ Endurance 등급"):
        st.markdown(tier_help_html(
            em,
            "<b>Endurance Score (지구력 점수)</b> — 심박이 기록된 모든 활동을 "
            "누적해서 <i>장시간 버티는 능력</i>을 점수로 매긴 값입니다. "
            "VO₂max가 ‘엔진 크기’라면 이건 ‘연료탱크’에 가깝습니다. "
            "롱런·저강도 볼륨을 꾸준히 쌓으면 올라가고, 며칠 쉬어도 "
            "잘 안 떨어집니다.",
            "등급 기준이 나이대·성별마다 다릅니다."), unsafe_allow_html=True)
    with pop[3 % len(pop)].popover("ℹ️ Hill Score 등급"):
        st.markdown(tier_help_html(
            hm,
            "<b>Hill Score (언덕 점수)</b> — <i>오르막 달리기 능력</i>을 1~100으로 "
            "매긴 값입니다. <b>경사 2% 이상</b> 구간이 있는 야외 러닝/걷기/하이킹만 "
            "집계되고, 최근 2개월 훈련 이력과 VO₂max 추정치를 씁니다. "
            "평지나 트레드밀 위주로 뛰면 아예 안 뜨거나 한참 뒤에 생깁니다.",
            "나이·성별 구분 없이 같은 기준입니다."), unsafe_allow_html=True)

    # ─────────────────────────────────────────────────────────────────
    # 가민 · Load Focus / 레이스 예측
    # ─────────────────────────────────────────────────────────────────
    d2 = ui.cols(2, 1)
    with d2[0]:
        with ui.card("gfocus"):
            ui.head("🎚️ 가민 Load Focus", "최근 4주 부하의 성격 분포")
            fo = ana.load_focus(G)
            if fo:
                labels_fo = [("무산소", "anaerobic", C["accent"]),
                             ("고강도 유산소", "high_aerobic", C["amber"]),
                             ("저강도 유산소", "low_aerobic", C["primary"])]
                for name, key, color in labels_fo:
                    p = fo["pct"][key]
                    raw = fo["raw"][key]
                    st.markdown(
                        f"<div class='rl-row'><span class='k'>{name}</span>"
                        f"<span class='v'>{'' if not np.isfinite(raw) else f'{raw:.0f}'} "
                        f"<span style='color:var(--rl-muted);font-weight:500'>({p}%)</span></span></div>"
                        f"<div class='rl-bar'><i style='width:{p}%;background:{color}'></i></div>",
                        unsafe_allow_html=True)
                st.markdown("<div style='height:10px'></div>" +
                            ui.pill(fo["verdict"], "ok" if fo["balanced"] else "warn"),
                            unsafe_allow_html=True)
            else:
                st.caption("‘✍️ 기록 → 📈 가민 측정’에서 Load Focus 3개 값을 입력하세요.")

    with d2[1 % len(d2)]:
        with ui.card("gpred"):
            ui.head("🏁 가민 레이스 예측", gdate("Pred10K"))
            preds = ana.garmin_race_predictions(G)
            if any(v != "—" for _, v in preds):
                ui.rows(preds)
            else:
                st.caption("Garmin Connect의 레이스 예측 시간을 주간 지표에 입력하세요.")

    # ─────────────────────────────────────────────────────────────────
    # 계산 지표 (보조) — 기록으로부터 직접 산출
    # ─────────────────────────────────────────────────────────────────
    st.markdown("<div style='height:6px'></div>"
                "<p class='rl-sub' style='margin:18px 0 8px'>— 아래는 가민이 준 값이 아니라, "
                "입력된 훈련 기록으로 <b>이 앱이 직접 계산한</b> 보조 지표입니다 —</p>",
                unsafe_allow_html=True)

    with ui.card("calc"):
        ui.head("📐 계산 지표 (보조)", "TRIMP 기반 부하 모델 · 가민 수치와 별개입니다")
        if summary:
            acwr = summary.get("acwr")
            _dtail = daily.tail(30)
            _dlab = [pd.Timestamp(i).strftime("%m/%d") for i in _dtail.index]

            def _sp(colname):
                return (list(zip(_dlab, _dtail[colname])) if colname in _dtail else [])
            ui.tiles([
                {"label": "CTL 체력", "value": summary["ctl"], "tone": "info",
                 "sub": (f"{summary['ctl_ramp_7d']:+.1f} / 7일"
                         if summary.get("ctl_ramp_7d") else None),
                 "spark": _sp("CTL")},
                {"label": "ATL 피로", "value": summary["atl"],
                 "spark": _sp("ATL")},
                {"label": "TSB 폼", "value": summary["tsb"], "sub": summary["form_text"],
                 "tone": ("warn" if fnum(summary["tsb"]) < -30 else
                          "ok" if fnum(summary["tsb"]) > 0 else ""),
                 "spark": _sp("TSB")},
                {"label": "ACWR", "value": f"{acwr:.2f}" if acwr else "—",
                 "sub": summary["risk_text"],
                 "tone": ("bad" if acwr and acwr > 1.5 else
                          "warn" if acwr and acwr < 0.8 else "ok" if acwr else "")},
            ])
            with st.expander("❓ 용어 설명 — CTL · ATL · TSB · ACWR"):
                st.markdown(
                    "모두 **TRIMP**(훈련 시간 × 심박 강도로 매기는 1회 훈련 부하 점수)를 "
                    "바탕으로 계산합니다. 단위가 없는 **상대값**이라 남과 비교하는 숫자가 "
                    "아니라 **내 추세**를 보는 숫자입니다.\n\n"
                    "- **CTL (체력)** — 최근 **42일** 부하의 가중 평균. 천천히 오르고 천천히 "
                    "내립니다. 그동안 쌓아온 **기초 체력**이라고 보면 됩니다. 주당 5~8% 정도 "
                    "올리는 게 안전합니다.\n"
                    "- **ATL (피로)** — 최근 **7일** 부하의 가중 평균. 빨리 오르고 빨리 "
                    "빠집니다. **지금 몸에 남은 피로**입니다.\n"
                    "- **TSB (폼) = CTL − ATL** — 오늘의 **컨디션**. "
                    "값이 양수(**＋**)면 몸이 가볍고(회복됨), 음수(**－**)면 무겁습니다. "
                    "−10 ~ −30은 한창 훈련 중인 정상 구간, −30 아래는 과부하 신호, "
                    "대회 당일은 **＋5 ~ ＋15 사이**가 이상적입니다.\n"
                    "- ⚠️ **가민의 ‘단기 부하’와 여기 ATL은 다른 값**입니다. 가민은 "
                    "최근 7일 부하를 **누적(합)**한 값이고, ATL은 같은 7일을 **가중 "
                    "평균**한 값이라 숫자 크기 자체가 다릅니다. 서로 비교하지 마세요.\n"
                    "- **ACWR = 최근 7일 부하 ÷ 최근 28일 주간 평균 부하** — "
                    "부하를 **얼마나 갑자기 늘렸는지**. **0.8 ~ 1.3**이 권장 구간이고, "
                    "**1.5 이상**이면 부상 위험이 뚜렷하게 올라갑니다. "
                    "0.8 미만은 훈련량이 줄고 있다는 뜻(테이퍼링이면 정상).\n\n"
                    "기록이 4주 이상 쌓여야 숫자가 의미를 갖습니다. "
                    "초반에 CTL이 0점대인 건 아직 데이터가 적어서입니다.")
            with st.expander("🔍 가민 값과 비교해 보기"):
                prs = ana.detect_prs(df_w, df_laps=db.load_data("Laps"))
                vdot = np.nan
                for nm, dd_ in ana.PR_CATEGORIES:
                    r_ = prs[prs["Category"] == nm]
                    if not r_.empty and r_.iloc[0]["TimeOrDist"] != "-":
                        sec_ = ana.parse_time_str(r_.iloc[0]["TimeOrDist"])
                        if np.isfinite(sec_):
                            v_ = ana.vdot_from_performance(dd_, sec_ / 60)
                            vdot = v_ if not np.isfinite(vdot) else max(vdot, v_)
                cmp_rows = ana.garmin_vs_computed(G, summary, evo2, vdot)
                if cmp_rows:
                    st.dataframe(pd.DataFrame(cmp_rows)[["항목", "가민", "계산", "차이"]],
                                 width="stretch", hide_index=True)
                    for r_ in cmp_rows:
                        st.caption(f"· {r_['항목']} — {r_['note']}")
                else:
                    st.caption("비교할 값이 아직 없습니다.")
        else:
            st.caption("훈련 기록이 쌓이면 표시됩니다.")

    with ui.card("curve"):
        ui.head("📉 계산 부하 곡선", "CTL(체력) / ATL(피로) / TSB(폼)")
        rsel = seg("기간", list(RANGE_DAYS), "curve_range", "3개월")
        rn = RANGE_DAYS[rsel]
        show = (daily if rn is None else daily.tail(rn)).reset_index(names="Date")
        if show["CTL"].sum() > 0:
            # 축이 두 개인 그래프는 쓰지 않습니다 — 두 축의 눈금을 어떻게 맞추느냐에
            # 따라 없던 상관관계가 보이기 때문입니다. 단위가 다른 TSB는 같은 날짜
            # 축을 공유하는 별도의 아래 칸으로 분리했습니다.
            xax = date_axis(len(show))
            long = show.melt("Date", ["CTL", "ATL"], var_name="지표", value_name="값")
            tip_d = alt.Tooltip("Date:T", title="날짜", format="%Y-%m-%d")
            top = alt.Chart(long).mark_line().encode(
                x=alt.X("Date:T", title=None, axis=X_HIDDEN),
                y=alt.Y("값:Q", title=None, scale=alt.Scale(zero=False)),
                color=alt.Color("지표:N", title=None, scale=alt.Scale(
                    domain=["CTL", "ATL"],
                    range=[C["primary"], C["accent"]])),
                tooltip=[tip_d, alt.Tooltip("지표:N", title="지표"),
                         alt.Tooltip("값:Q", title="값", format=".1f")]
            ).properties(height=ui.chart_height(210, 160),
                         title=panel_title("부하 (CTL · ATL)"))

            # TSB는 부호가 의미의 전부입니다(+ 회복됨 / − 피로 앞섬).
            # 한 색으로 칠하면 그 구분이 사라지므로 0을 기준으로 위아래를 나눠 칠합니다.
            tsb = show[["Date", "TSB", "CTL", "ATL"]].copy()
            tsb["양"] = tsb["TSB"].clip(lower=0)
            tsb["음"] = tsb["TSB"].clip(upper=0)
            _bx = alt.X("Date:T", title=None, axis=xax)
            _btip = [tip_d, alt.Tooltip("TSB:Q", title="TSB 폼", format=".1f"),
                     alt.Tooltip("CTL:Q", title="CTL 체력", format=".1f"),
                     alt.Tooltip("ATL:Q", title="ATL 피로", format=".1f")]
            _pos = alt.Chart(tsb).mark_area(color=C["primary"], opacity=.18).encode(
                x=_bx, y=alt.Y("양:Q", title=None, axis=alt.Axis(tickCount=3)),
                tooltip=_btip)
            _neg = alt.Chart(tsb).mark_area(color=C["red"], opacity=.18).encode(
                x=_bx, y=alt.Y("음:Q", title=None), tooltip=_btip)
            _ln = alt.Chart(tsb).mark_line(color=C["muted"], strokeWidth=1.4).encode(
                x=_bx, y=alt.Y("TSB:Q", title=None), tooltip=_btip)
            zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(
                color=C["muted"], strokeWidth=1).encode(y="y:Q")
            bot = (_pos + _neg + zero + _ln).properties(
                height=ui.chart_height(104, 88), title=panel_title("TSB 폼 (0 기준)"))
            stacked_charts([top, bot])
        else:
            st.caption("훈련 기록을 입력하면 곡선이 그려집니다.")
        with st.expander("❓ 이 그래프 읽는 법"):
            st.markdown(
                "- **위 칸** — 파란 선 = CTL(체력), 주황 선 = ATL(피로). 같은 축이라 "
                "두 선의 높낮이를 그대로 비교하면 됩니다.\n"
                "- **아래 칸** — TSB(폼). 단위가 달라서 칸을 나눴고, 날짜 축은 위와 "
                "같습니다. 가로선이 0이고, 위로 나오면 회복된 상태, 아래면 피로가 "
                "앞선 상태입니다.\n\n"
                "**이렇게 보면 됩니다**\n\n"
                "- 파란 선이 **완만히 우상향**하면서 주황 선이 그 위아래로 **출렁이는 모양**이 "
                "가장 이상적입니다 — 무리하게 올리지 않으면서 자극은 주고 있다는 뜻입니다.\n"
                "- 주황 선이 파란 선보다 **한참 위에 오래 머물면** 피로가 계속 쌓이는 중입니다. "
                "회복 주간을 넣을 시점입니다.\n"
                "- 파란 선이 **계속 내려가면** 체력이 빠지는 중입니다(휴식기·부상 후에는 정상).\n"
                "- 대회 2~3주 전부터는 주황 선만 내려서 **면(TSB)을 0 위로 올리는 것**이 "
                "테이퍼링입니다.")

    # ─────────────────────────────────────────────────────────────────
    b = ui.cols(2, 1)
    with b[0]:
        with ui.card("proj"):
            ui.head("🎯 진행 중 프로젝트", "진행 중 + 예정된 것까지")
            act = (df_proj[df_proj["Status"].isin(["ACTIVE", "PLANNED"])]
                   if not df_proj.empty else pd.DataFrame())
            if not act.empty:
                for _, p in act.iterrows():
                    dd = None
                    try:
                        dd = (pd.to_datetime(p["TargetDate"]).date() - date.today()).days
                    except Exception:
                        pass
                    st.markdown(f"<div class='rl-item'><div class='t'>{p['ProjectName']} "
                                f"{ui.pill(dday_tag(dd), 'warn' if (dd is not None and dd < 30) else 'info')}</div>"
                                f"<div class='m'>목표 {p.get('GoalValue','—')} · 기한 {p.get('TargetDate','—')}</div></div>",
                                unsafe_allow_html=True)
                    # 기간이 얼마나 지났는지 — 날짜만 적어두면 감이 안 옵니다
                    try:
                        _s = pd.to_datetime(p["StartDate"]).date()
                        _t = pd.to_datetime(p["TargetDate"]).date()
                        _span = max((_t - _s).days, 1)
                        _pct = min(max((date.today() - _s).days / _span, 0.0), 1.0) * 100
                        st.markdown(
                            f"<div class='rl-row'><span class='k'>기간 진행</span>"
                            f"<span class='v'>{_pct:.0f}%</span></div>",
                            unsafe_allow_html=True)
                        ui.bar(_pct, "warn" if _pct > 85 else "")
                    except Exception:
                        pass
            else:
                st.caption("활성 프로젝트가 없습니다. ‘🎯 목표’ 탭에서 등록하세요.")

    with b[1 % len(b)]:
        with ui.card("recent"):
            ui.head("📋 최근 훈련")
            if not df_w.empty:
                d = ana.prepare_workouts(df_w).tail(5).iloc[::-1]
                ui.item_list([
                    (f"{r.WorkoutType} · {r.DistanceKm:.2f} km",
                     f"{r.WorkoutDate:%Y-%m-%d} · {ana.pace_str(r.PaceSec)} · "
                     f"{int(r.AvgHeartRate) if r.AvgHeartRate > 0 else '—'} bpm")
                    for r in d.itertuples()])
            else:
                st.caption("기록된 훈련이 없습니다.")


# ═════════════════════════════════════════════════════════════════════════
# TAB 2 · 기록 — 넣는 곳
# ═════════════════════════════════════════════════════════════════════════
with tab_log:
    labels = (["➕ 훈련", "📥 CSV", "⌚ 일일", "📈 측정"] if ui.is_mobile()
              else ["➕ 훈련 입력", "📥 CSV 가져오기", "⌚ 가민 일일",
                    "📈 가민 측정"])
    s_new, s_imp, a2, a3 = st.tabs(labels)

    # ── 2-1 훈련 입력 ───────────────────────────────────────────────────────────
    with s_new:
        with ui.card("newrun"):
            ui.head("➕ 훈련 기록 추가")
            with st.form("f_new_workout", clear_on_submit=True):
                a = ui.cols(3, 1, keep_row=True)
                w_date = a[0].date_input("날짜", date.today())
                w_type = a[1 % len(a)].selectbox("유형", WORKOUT_TYPES)
                w_proj = a[2 % len(a)].selectbox("프로젝트", list(proj_opts))

                b_ = ui.cols(3, 1, keep_row=True)
                w_dist = b_[0].number_input("거리 (km)", 0.0, 300.0, 8.0, 0.01, format="%.2f")
                w_min = b_[1 % len(b_)].number_input("시간 (분)", 0.0, 1500.0, 50.0, 0.5)
                w_hr = b_[2 % len(b_)].number_input("평균 심박", 0, 250, 0)

                c_ = ui.cols(4, 1, keep_row=True)
                w_hrmax = c_[0].number_input("최고 심박", 0, 250, 0)
                w_elev = c_[1 % len(c_)].number_input("상승고도 (m)", 0, 5000, 0)
                w_temp = c_[2 % len(c_)].number_input("기온 (°C)", -30.0, 50.0, 20.0, 0.5)
                w_cad = c_[3 % len(c_)].number_input("케이던스", 0, 250, 0)

                d_ = ui.cols(3, 1, keep_row=True)
                w_shoe = d_[0].selectbox("러닝화", list(shoe_opts))
                w_surf = d_[1 % len(d_)].selectbox("노면", SURFACES)
                w_rpe = d_[2 % len(d_)].slider("RPE (체감강도)", 1, 10, 5)

                st.markdown("<p class='rl-sub' style='margin:10px 0 2px'>가민 트레이닝 효과 (선택)</p>",
                            unsafe_allow_html=True)
                te = ui.cols(3, 1, keep_row=True)
                w_ate = te[0].number_input("유산소 TE", 0.0, 5.0, 0.0, 0.1)
                w_nte = te[1 % len(te)].number_input("무산소 TE", 0.0, 5.0, 0.0, 0.1)
                w_pb = te[2 % len(te)].selectbox("Primary Benefit", ana.PRIMARY_BENEFIT)

                e_ = ui.cols(2, 1, keep_row=True)
                w_leg = e_[0].slider("다리 피로", 1, 10, 3)
                w_car = e_[1 % len(e_)].slider("심폐 피로", 1, 10, 3)
                w_note = st.text_area("메모", height=70, placeholder="코스, 컨디션, 특이사항…")

                if w_dist > 0 and w_min > 0:
                    st.caption(f"→ 예상 페이스 **{ana.pace_str(w_min * 60 / w_dist)}** · "
                               f"평균 속도 {w_dist / (w_min/60):.2f} km/h")

                if st.form_submit_button("💾 저장", width="stretch", type="primary"):
                    if w_dist <= 0 or w_min <= 0:
                        st.error("거리와 시간을 입력하세요.")
                    else:
                        row = {
                            "WorkoutID": new_id("WO"), "ProjectID": proj_opts[w_proj],
                            "WorkoutDate": w_date.strftime("%Y-%m-%d"), "WorkoutType": w_type,
                            "DistanceKm": round(w_dist, 2), "DurationMinutes": round(w_min, 1),
                            "PaceSec": round(w_min * 60 / w_dist, 1),
                            "AvgHeartRate": w_hr or "", "MaxHeartRate": w_hrmax or "",
                            "AvgCadence": w_cad or "", "ElevationGainM": w_elev,
                            "Temperature": w_temp, "Surface": w_surf,
                            "ShoeID": shoe_opts[w_shoe],
                            "AerobicTE": w_ate or "", "AnaerobicTE": w_nte or "",
                            "PrimaryBenefit": w_pb, "RPE": w_rpe,
                            "LegFatigue": w_leg, "CardioFatigue": w_car, "Notes": w_note,
                            "SourceKey": src_key(w_date, w_dist, w_min),
                        }
                        db.append_rows("Workouts", pd.DataFrame([row]))
                        st.success(f"저장 완료 — {w_dist:.2f}km / {ana.pace_str(w_min*60/w_dist)}")
                        st.rerun()

    # ── 2-2 CSV 가져오기 ────────────────────────────────────────────────────────
    with s_imp:
        # 가민 CSV 컬럼명 → 앱 필드
        GARMIN_MAP = {
            "DistanceKm":      ["거리 km", "거리", "distance"],
            "DurationMinutes": ["시간", "time"],
            "AvgHeartRate":    ["평균 심박 bpm", "평균 심박수", "평균 심박", "avg hr"],
            "MaxHeartRate":    ["최대심박 bpm", "최대 심박수", "최대심박", "max hr"],
            "AvgPower":        ["평균 파워 w", "평균 파워", "avg power"],
            "AvgCadence":      ["평균 달리기 케이던스", "평균 달리기 케이던스 보/분",
                                "평균 케이던스", "avg run cadence"],
            "ElevGainM":       ["총 상승 m", "총 상승", "상승"],
            "ElevLossM":       ["총 하강 m", "총 하강", "하강"],
            "AvgGCTms":        ["평균 지면 접촉 시간", "평균 지면 접촉 시간 ms", "지면 접촉"],
            "AvgStrideM":      ["평균 보폭 m", "평균 보폭"],
            "AvgVertOscCm":    ["평균 수직 진동 cm", "수직 진동"],
            "AvgVertRatioPct": ["평균 수직 비율 %", "수직 비율"],
            "Calories":        ["칼로리 c", "칼로리", "calories"],
            "TempC":           ["평균 온도", "온도", "temperature"],
            # ── 아래는 가민 활동 상세 CSV에만 있는 항목 ──────────────────
            "GapPaceSec":      ["평균 gap", "gap", "grade adjusted pace"],
            "NormPower":       ["normalized power® (np®)", "normalized power",
                                "np", "정규화 파워"],
            "AvgWkg":          ["평균 w/kg", "avg w/kg"],
            "MaxPower":        ["최대 파워", "max power"],
            "MaxWkg":          ["최대 w/kg", "max w/kg"],
            "MaxPaceSec":      ["최대 페이스", "best pace", "max pace"],
            "MaxCadence":      ["최고 달리기 케이던스", "최대 케이던스",
                                "max run cadence"],
            "MovingMinutes":   ["이동 시간", "moving time"],
            "MovingPaceSec":   ["평균 이동 페이스", "avg moving pace"],
        }
        # 값의 종류: 'dur'=시:분:초→분, 'pace'=분:초→초/km, 그 외는 숫자
        GARMIN_KIND = {"DurationMinutes": "dur", "MovingMinutes": "dur",
                       "GapPaceSec": "pace", "MaxPaceSec": "pace",
                       "MovingPaceSec": "pace"}
        SUMMARY_LABELS = {"요약", "summary", "합계", "total", "전체"}

        def pick(cand, keys):
            """정확히 일치하는 이름 우선 ('시간'이 '누적 시간'보다 먼저)."""
            low = {str(c).strip().lower(): c for c in cand}
            for k in keys:
                if k.lower() in low:
                    return low[k.lower()]
            for k in keys:
                for c in cand:
                    if k.lower() in str(c).strip().lower():
                        return c
            return None

        def gnum(v):
            """가민 CSV의 '--' 같은 빈 값을 안전하게 처리."""
            t = str(v).strip().replace(",", "")
            if t in ("", "--", "-", "nan", "None"):
                return np.nan
            try:
                f = float(t)
                return f if np.isfinite(f) else np.nan
            except ValueError:
                return np.nan

        def gpace(v):
            """'6:05' / '4:58.3' → 초/km. 페이스 칸은 분:초 입니다."""
            m = gdur(v)
            return round(m * 60, 1) if np.isfinite(m) else np.nan

        def gdur(v):
            """'5:48.4' / '49:16' / '1:02:33' → 분"""
            t = str(v).strip()
            if t in ("", "--", "-"):
                return np.nan
            if ":" in t:
                try:
                    p = [float(x) for x in t.split(":")]
                except ValueError:
                    return np.nan
                return p[0] * 60 + p[1] + p[2] / 60 if len(p) == 3 else p[0] + p[1] / 60
            return gnum(t)

        with ui.card("imp"):
            ui.head("📥 Garmin CSV 가져오기",
                    "활동 목록(여러 훈련)과 활동 상세(한 훈련의 랩) 모두 지원합니다")
            up = st.file_uploader("파일", type=["csv", "xlsx"], label_visibility="collapsed")

            if up is None:
                ui.rows([
                    ("활동 목록", "Connect → 활동 → 목록 상단 내보내기 · 여러 훈련을 한 번에"),
                    ("활동 상세(랩)", "Connect → 활동 하나 → 랩 표 내보내기 · 구간·러닝 다이나믹스 포함"),
                ])
                st.caption("상세(랩) 파일에는 날짜가 없으므로 화면에서 직접 지정합니다. "
                           "맨 아래 ‘요약’ 행이 있으면 그것을 훈련 1건의 합계로 씁니다.")
            else:
                raw = pd.DataFrame()
                for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
                    try:
                        up.seek(0)
                        raw = (pd.read_csv(up, encoding=enc)
                               if up.name.lower().endswith(".csv") else pd.read_excel(up))
                        break
                    except Exception:
                        continue
                if raw.empty:
                    st.error("파일을 읽지 못했습니다. CSV 인코딩을 확인해 주세요.")

                if not raw.empty:
                    cand = list(raw.columns)
                    col = {k: pick(cand, v) for k, v in GARMIN_MAP.items()}
                    date_col = pick(cand, ["날짜", "date", "활동 날짜", "시작 시간"])
                    lapcol0 = pick(cand, ["랩", "lap", "구간"])
                    is_lap = bool(lapcol0) and not date_col

                    _kinds = ["랩(구간) — 훈련 1건", "활동 목록 — 여러 훈련"]
                    kind = seg("파일 종류", _kinds, "imp_kind",
                               _kinds[0] if is_lap else _kinds[1], collapsed=False)
                    st.dataframe(raw.head(4), width="stretch")
                    if len(raw) > 4:
                        st.caption(f"↑ 전체 **{len(raw)}행** 중 앞 4행만 미리보기입니다. "
                                   "합산은 전체 행 기준으로 계산됩니다.")

                    found = [k for k, v in col.items() if v]
                    st.caption("자동 인식: " + ", ".join(
                        f"{col[k]}" for k in ["DistanceKm", "DurationMinutes", "AvgHeartRate",
                                              "AvgCadence", "TempC"] if col.get(k)))
                    with st.expander("컬럼 연결 직접 지정"):
                        for k in ["DistanceKm", "DurationMinutes", "AvgHeartRate", "MaxHeartRate"]:
                            opts = ["(없음)"] + cand
                            cur = col.get(k)
                            col[k] = st.selectbox(
                                k, opts, index=opts.index(cur) if cur in cand else 0,
                                key=f"imp_col_{k}")
                            if col[k] == "(없음)":
                                col[k] = None

                    unit = st.selectbox("거리 단위", ["km", "m", "mile"], key="imp_unit")
                    mult = {"km": 1.0, "m": 0.001, "mile": 1.609344}[unit]

                    def rowvals(r):
                        out = {}
                        for k, c in col.items():
                            if not c:
                                continue
                            kind = GARMIN_KIND.get(k)
                            out[k] = (gdur(r[c]) if kind == "dur" else
                                      gpace(r[c]) if kind == "pace" else gnum(r[c]))
                        out["DistanceKm"] = out.get("DistanceKm", np.nan) * mult
                        return out

                    # ══════════════════ 랩(구간) 파일 ══════════════════
                    if kind.startswith("랩"):
                        lapcol = pick(cand, ["랩", "lap", "구간"]) or cand[0]
                        stagecol = pick(cand, ["단계 유형", "단계유형", "stage type",
                                               "intervals type"])
                        intvcol = pick(cand, ["인터벌", "interval"])

                        def _txt(r, c):
                            return "" if not c else str(r.get(c, "")).strip()

                        def _lapno(v):
                            """'3' → 3 · '3 - 6'(구간 합계) 나 '--' → None"""
                            m = re.fullmatch(r"\s*([0-9]+)(\.0)?\s*", str(v))
                            return int(m.group(1)) if m else None

                        # 요약 행: 랩 또는 인터벌 칸이 '요약/합계/--'
                        def _is_sum_row(r):
                            for c in (lapcol, intvcol):
                                t = _txt(r, c).lower()
                                if t in SUMMARY_LABELS or t == "--":
                                    return True
                            return False

                        is_sum = raw.apply(_is_sum_row, axis=1)
                        summary_row = raw[is_sum].iloc[0] if is_sum.any() else None
                        nos = raw[lapcol].apply(_lapno)
                        # '1 - 2' 같은 구간 합계 행은 개별 랩과 중복이므로 제외
                        n_group = int(((~is_sum) & nos.isna()).sum())
                        lap_rows = raw[(~is_sum) & nos.notna()]
                        seq_no = False
                        if lap_rows.empty:            # 랩 번호가 없는 형식이면 순번 부여
                            lap_rows, n_group, seq_no = raw[~is_sum], 0, True

                        # 가민 '단계 유형'이 여러 종류면 그대로 역할로 씁니다
                        stages = ({str(v).strip() for v in lap_rows[stagecol].dropna()}
                                  if stagecol else set())
                        use_stage = len(stages) > 1

                        laps = []
                        for i, (_, r) in enumerate(lap_rows.iterrows()):
                            v = rowvals(r)
                            d_, t_ = v.get("DistanceKm", np.nan), v.get("DurationMinutes", np.nan)
                            if not (np.isfinite(d_) and d_ > 0 and np.isfinite(t_) and t_ > 0):
                                continue
                            v["LapNo"] = (i + 1) if seq_no else _lapno(r[lapcol])
                            v["PaceSec"] = round(t_ * 60 / d_, 1)
                            v["LapRole"] = (ana.stage_to_role(_txt(r, stagecol))
                                            if use_stage else "")
                            laps.append(v)
                        L = pd.DataFrame(laps)

                        if L.empty:
                            st.warning("거리·시간을 읽지 못했습니다. 컬럼 연결을 확인하세요.")
                        else:
                            def agg(field, how="wmean"):
                                if summary_row is not None and col.get(field):
                                    kind = GARMIN_KIND.get(field)
                                    v = (gdur(summary_row[col[field]]) if kind == "dur"
                                         else gpace(summary_row[col[field]]) if kind == "pace"
                                         else gnum(summary_row[col[field]]))
                                    if np.isfinite(v):
                                        return v * (mult if field == "DistanceKm" else 1)
                                if field not in L.columns:
                                    return np.nan
                                s_ = L[field].dropna()
                                if s_.empty:
                                    return np.nan
                                if how == "sum":
                                    return float(s_.sum())
                                if how == "max":
                                    return float(s_.max())
                                if how == "min":            # 페이스는 작을수록 빠름
                                    return float(s_.min())
                                w = L.loc[s_.index, "DurationMinutes"]
                                return float((s_ * w).sum() / w.sum()) if w.sum() else float(s_.mean())

                            tot_d = agg("DistanceKm", "sum")
                            tot_m = agg("DurationMinutes", "sum")
                            hr = agg("AvgHeartRate")
                            hrx = agg("MaxHeartRate", "max")
                            cad = agg("AvgCadence")
                            pw = agg("AvgPower")
                            up_m = agg("ElevGainM", "sum")
                            kcal = agg("Calories", "sum")
                            tmp = agg("TempC")
                            gct = agg("AvgGCTms")
                            stride = agg("AvgStrideM")
                            vosc = agg("AvgVertOscCm")
                            vrat = agg("AvgVertRatioPct")
                            down_m = agg("ElevLossM", "sum")
                            gap = agg("GapPaceSec")
                            npw = agg("NormPower")
                            pmax = agg("MaxPaceSec", "min")
                            cmax = agg("MaxCadence", "max")
                            mov_m = agg("MovingMinutes", "sum")

                            st.markdown(
                                f"**합산 결과** — 유효 랩 **{len(L)}개**를 훈련 1건으로 저장합니다"
                                + (" *(합계는 CSV의 ‘요약’ 행 사용)*" if summary_row is not None
                                   else " *(랩을 직접 더함)*"))
                            if n_group:
                                st.caption(f"‘1 - 2’처럼 여러 랩을 묶은 **구간 합계 행 {n_group}개**는 "
                                           "개별 랩과 중복이라 제외했습니다.")
                            if "LapRole" in L.columns and L["LapRole"].astype(str).str.len().sum():
                                st.caption("CSV의 **단계 유형**(워밍업/러닝/쿨다운)을 랩 역할로 "
                                           "그대로 가져왔습니다 — 추측하지 않습니다.")
                            ui.metrics([
                                ("총 거리", f"{tot_d:.2f} km", None),
                                ("총 시간", ana.time_str(tot_m * 60), None),
                                ("평균 페이스", ana.pace_str(tot_m * 60 / tot_d) if tot_d > 0 else "—", None),
                                ("평균 심박", f"{hr:.0f}" if np.isfinite(hr) else "—",
                                 f"최고 {hrx:.0f}" if np.isfinite(hrx) else None),
                            ], per_row_pc=4)
                            extra = [x for x in [
                                f"랩 {len(L)}개",
                                f"케이던스 {cad:.0f}" if np.isfinite(cad) else "",
                                f"보폭 {stride:.2f}m" if np.isfinite(stride) else "",
                                f"접지 {gct:.0f}ms" if np.isfinite(gct) else "",
                                f"수직진동 {vosc:.1f}cm" if np.isfinite(vosc) else "",
                                f"상승 {up_m:.0f}m" if np.isfinite(up_m) else "",
                                f"{tmp:.1f}°C" if np.isfinite(tmp) else "",
                                f"{kcal:.0f}kcal" if np.isfinite(kcal) else "",
                                f"GAP {ana.pace_str(gap)}" if np.isfinite(gap) else "",
                                f"NP {npw:.0f}W" if np.isfinite(npw) else "",
                                f"최고 케이던스 {cmax:.0f}" if np.isfinite(cmax) else "",
                                f"이동 {ana.time_str(mov_m * 60)}" if np.isfinite(mov_m) else "",
                            ] if x]
                            st.caption(" · ".join(extra))
                            with st.expander(f"저장될 랩 {len(L)}개 전체 보기"):
                                prev = pd.DataFrame({
                                    "랩": L["LapNo"],
                                    "역할": L.get("LapRole", ""),
                                    "거리(km)": L["DistanceKm"].round(2),
                                    "시간": L["DurationMinutes"].apply(
                                        lambda v: ana.time_str(v * 60)),
                                    "페이스": L["PaceSec"].apply(ana.pace_str),
                                    "평균심박": L.get("AvgHeartRate"),
                                })
                                st.dataframe(prev, width="stretch", hide_index=True)
                                skipped = len(lap_rows) - len(L)
                                if skipped > 0:
                                    st.caption(f"거리·시간이 없거나 0인 자투리 랩 {skipped}개는 "
                                               "제외했습니다.")

                            st.divider()
                            st.markdown("**CSV에 없는 항목** — 직접 입력하세요.")
                            d1 = ui.cols(3, 1, keep_row=True)
                            w_date = d1[0].date_input("훈련 날짜 *", date.today(), key="imp_date")
                            w_type2 = d1[1 % len(d1)].selectbox("유형 *", WORKOUT_TYPES, key="imp_type")
                            proj_i = d1[2 % len(d1)].selectbox("프로젝트", list(proj_opts), key="imp_proj")
                            d2 = ui.cols(3, 1, keep_row=True)
                            shoe_i = d2[0].selectbox("러닝화", list(shoe_opts), key="imp_shoe")
                            surf_i = d2[1 % len(d2)].selectbox("노면", SURFACES, key="imp_surf")
                            rpe_i = d2[2 % len(d2)].slider("RPE (체감강도)", 1, 10, 5, key="imp_rpe")

                            st.markdown("<p class='rl-sub' style='margin:12px 0 2px'>"
                                        "가민 트레이닝 효과 · 컨디션 (선택)</p>",
                                        unsafe_allow_html=True)
                            d3 = ui.cols(3, 1, keep_row=True)
                            ate_i = d3[0].number_input("유산소 TE", 0.0, 5.0, 0.0, 0.1, key="imp_ate")
                            nte_i = d3[1 % len(d3)].number_input("무산소 TE", 0.0, 5.0, 0.0, 0.1,
                                                                 key="imp_nte")
                            pb_i = d3[2 % len(d3)].selectbox("Primary Benefit", ana.PRIMARY_BENEFIT,
                                                             key="imp_pb")
                            d4 = ui.cols(3, 1, keep_row=True)
                            leg_i = d4[0].slider("다리 피로", 1, 10, 3, key="imp_leg")
                            car_i = d4[1 % len(d4)].slider("심폐 피로", 1, 10, 3, key="imp_car")
                            temp_ovr = d4[2 % len(d4)].number_input(
                                "기온 (°C)", -30.0, 50.0,
                                float(tmp) if np.isfinite(tmp) else 20.0, 0.5, key="imp_temp",
                                help="가민 손목 온도는 체온 영향으로 실제 기온보다 높게 나옵니다. "
                                     "날씨 보정을 쓰려면 실제 기온으로 고치세요.")
                            note_i = st.text_input("메모", "", key="imp_note")

                            if st.button("훈련 1건 + 랩으로 저장", width="stretch", type="primary"):
                                exist = set(db.load_data("Workouts")["SourceKey"].astype(str))
                                key = src_key(w_date, tot_d, tot_m)
                                if key in exist:
                                    st.warning("같은 날짜·거리·시간의 훈련이 이미 있습니다.")
                                else:
                                    def opt(v, nd=0):
                                        return round(v, nd) if np.isfinite(v) else ""
                                    wid = new_id("WO")
                                    db.append_rows("Workouts", pd.DataFrame([{
                                        "WorkoutID": wid, "ProjectID": proj_opts[proj_i],
                                        "WorkoutDate": w_date.strftime("%Y-%m-%d"),
                                        "WorkoutType": w_type2,
                                        "DistanceKm": round(tot_d, 2),
                                        "DurationMinutes": round(tot_m, 1),
                                        "PaceSec": round(tot_m * 60 / tot_d, 1) if tot_d > 0 else "",
                                        "AvgHeartRate": opt(hr), "MaxHeartRate": opt(hrx),
                                        "AvgPower": opt(pw), "AvgCadence": opt(cad),
                                        "ElevationGainM": opt(up_m),
                                        "Temperature": temp_ovr, "Surface": surf_i,
                                        "ShoeID": shoe_opts[shoe_i],
                                        "Calories": opt(kcal), "AvgGCTms": opt(gct),
                                        "AvgStrideM": opt(stride, 2), "AvgVertOscCm": opt(vosc, 1),
                                        "AvgVertRatioPct": opt(vrat, 1),
                                        "ElevLossM": opt(down_m), "GapPaceSec": opt(gap, 1),
                                        "NormPower": opt(npw), "MaxPaceSec": opt(pmax, 1),
                                        "MaxCadence": opt(cmax),
                                        "MovingMinutes": opt(mov_m, 1),
                                        "AerobicTE": ate_i or "", "AnaerobicTE": nte_i or "",
                                        "PrimaryBenefit": pb_i,
                                        "RPE": rpe_i, "LegFatigue": leg_i, "CardioFatigue": car_i,
                                        "Notes": note_i or "랩 CSV 가져오기",
                                        "SourceKey": key}]))
                                    L2 = L.copy()
                                    L2["CumMinutes"] = L2["DurationMinutes"].cumsum().round(2)
                                    L2["WorkoutDate"] = w_date.strftime("%Y-%m-%d")
                                    L2["WorkoutType"] = w_type2
                                    L2.insert(0, "WorkoutID", wid)
                                    L2.insert(0, "LapID",
                                              [f"LAP-{wid[-8:]}-{i+1:02d}" for i in range(len(L2))])
                                    db.append_rows("Laps", L2.round(3))
                                    st.success(f"저장 완료 — {tot_d:.2f}km · 랩 {len(L2)}개")
                                    st.rerun()

                    # ══════════════════ 활동 목록 파일 ══════════════════
                    else:
                        st.divider()
                        opts_d = ["(직접 지정)"] + cand
                        date_sel = st.selectbox(
                            "날짜 컬럼", opts_d,
                            index=opts_d.index(date_col) if date_col in cand else 0,
                            key="imp_datecol")
                        fixed_date = None
                        if date_sel == "(직접 지정)":
                            st.warning("날짜 컬럼이 없습니다. 모든 행에 적용할 날짜를 고르세요.")
                            fixed_date = st.date_input("적용 날짜", date.today(), key="imp_fixdate")
                        st.markdown("**CSV에 없는 항목** — 모든 행에 같은 값으로 들어갑니다. "
                                    "개별 값은 저장 후 ‘훈련 이력 → 수정’에서 고치세요.")
                        a1 = ui.cols(4, 1, keep_row=True)
                        w_type2 = a1[0].selectbox("기본 훈련 유형", WORKOUT_TYPES, key="imp_type2")
                        proj_i = a1[1 % len(a1)].selectbox("프로젝트", list(proj_opts), key="imp_proj2")
                        shoe_i2 = a1[2 % len(a1)].selectbox("러닝화", list(shoe_opts), key="imp_shoe2")
                        surf_i2 = a1[3 % len(a1)].selectbox("노면", SURFACES, key="imp_surf2")

                        if st.button("데이터베이스에 저장", width="stretch", type="primary"):
                            exist = set(db.load_data("Workouts")["SourceKey"].astype(str))
                            rows, dup, skip = [], 0, 0
                            for _, r in raw.iterrows():
                                v = rowvals(r)
                                d_, t_ = v.get("DistanceKm", np.nan), v.get("DurationMinutes", np.nan)
                                if not (np.isfinite(d_) and d_ > 0 and np.isfinite(t_) and t_ > 0):
                                    skip += 1
                                    continue
                                if date_sel == "(직접 지정)":
                                    dt = (fixed_date or date.today()).strftime("%Y-%m-%d")
                                else:
                                    try:
                                        dt = pd.to_datetime(r[date_sel]).strftime("%Y-%m-%d")
                                    except Exception:
                                        skip += 1
                                        continue
                                key = src_key(dt, d_, t_)
                                if key in exist:
                                    dup += 1
                                    continue
                                exist.add(key)
                                row = {"WorkoutID": new_id("WO"), "ProjectID": proj_opts[proj_i],
                                       "WorkoutDate": dt, "WorkoutType": w_type2,
                                       "DistanceKm": round(d_, 2), "DurationMinutes": round(t_, 1),
                                       "PaceSec": round(t_ * 60 / d_, 1),
                                       "ShoeID": shoe_opts[shoe_i2], "Surface": surf_i2,
                                       "Notes": "Garmin 가져오기", "SourceKey": key}
                                for k in ["AvgHeartRate", "MaxHeartRate", "AvgPower", "AvgCadence",
                                          "Calories", "AvgGCTms", "AvgStrideM",
                                          "AvgVertOscCm", "AvgVertRatioPct"]:
                                    val = v.get(k, np.nan)
                                    if np.isfinite(val):
                                        row[k] = round(val, 2)
                                if np.isfinite(v.get("TempC", np.nan)):
                                    row["Temperature"] = round(v["TempC"], 1)
                                if np.isfinite(v.get("ElevGainM", np.nan)):
                                    row["ElevationGainM"] = round(v["ElevGainM"])
                                rows.append(row)
                            if rows:
                                db.append_rows("Workouts", pd.DataFrame(rows))
                            st.success(f"{len(rows)}건 추가 · 중복 {dup}건 · 건너뜀 {skip}건")
                            st.rerun()

    # ── 2-3 가민 일일 지표 ────────────────────────────────────────────────────────
    with a2:
        with ui.card("gdaily"):
            ui.head("⌚ 가민 일일 지표", "Garmin Connect에서 보고 그대로 옮겨 적으세요")
            st.caption("가민 값은 **한 시점에 다 찍히지 않습니다.** 아침에 확정되는 값과 "
                       "훈련이 끝나야 갱신되는 값이 섞여 있어서, 넣는 창을 둘로 나눴습니다. "
                       "각 창은 자기 시각만 물어봅니다.")
            _kind = seg("무엇을 넣나요", ["🌅 아침 체크인", "🏃 훈련 후 체크인"],
                        "gd_kind", collapsed=False,
                        help="아침 값은 하루에 한 번 확정되고, 훈련 값은 훈련이 끝나야 "
                             "갱신됩니다. 같은 날 같은 창에 다시 넣으면 줄이 쌓이지 않고 "
                             "그 줄이 갱신됩니다.")
            _morning = _kind.startswith("🌅")

            if _morning:
                # ── 🌅 아침 ──────────────────────────────────────────────
                with st.form("f_daily_am", clear_on_submit=True):
                    st.caption("가민 **‘트레이닝 준비 상태’ 화면 그대로** 옮겨 적는 창입니다. "
                               "위쪽은 밤사이 계산돼 그날 고정인 값이고, 아래쪽 세 개는 "
                               "그 화면에 함께 떠 있는 ‘지금 보이는’ 값입니다.")
                    m0 = ui.cols(2, 1, keep_row=True)
                    dd_ = m0[0].date_input("날짜", date.today(), key="am_date")
                    mhour = m0[1 % len(m0)].number_input(
                        "기상 시각 (시)", 0, 23, 7, 1, key="am_hour", format="%d",
                        help="가민 준비 상태 화면의 ‘…에 업데이트됨 · 기상 후’ 시각을 "
                             "넣으면 가장 정확합니다.")
                    m1 = ui.cols(4, 2, keep_row=True)
                    tr = grid_at(m1, 0, 4).number_input(
                        "Readiness", 0, 100, 0, key="am_tr",
                        help="트레이닝 준비 상태 점수. 아침에 산출됩니다.")
                    bb = grid_at(m1, 1, 4).number_input(
                        "Body Battery", 0, 100, 0, key="am_bb",
                        help="자는 동안 충전됩니다 — 기상 직후가 그날 최고값.")
                    hrvms = grid_at(m1, 2, 4).number_input(
                        "HRV (ms)", 0, 250, 0, key="am_hrv",
                        help="밤사이 평균. 하루 동안 고정입니다.")
                    hrv = grid_at(m1, 3, 4).selectbox(
                        "HRV 상태", ["Balanced", "Unbalanced", "Low", "Poor", "No Status"],
                        key="am_hrvs")
                    m2 = ui.cols(4, 2, keep_row=True)
                    slp = grid_at(m2, 0, 4).number_input("수면 점수", 0, 100, 0, key="am_slp")
                    rhr = grid_at(m2, 1, 4).number_input("안정시 심박", 0, 120, 0, key="am_rhr")
                    slh = grid_at(m2, 2, 4).selectbox(
                        "최근 수면 점수", SLEEP_HIST_OPTS, key="am_slh",
                        help="가민 준비 상태 화면의 ‘최근 수면 점수’(최근 3일) 판정.")
                    sth = grid_at(m2, 3, 4).selectbox(
                        "최근 스트레스", STRESS_HIST_OPTS, key="am_sth",
                        help="가민 준비 상태 화면의 ‘최근 스트레스’(최근 3일) 판정.")
                    st.markdown(
                        "<p class='rl-sub' style='margin:12px 0 2px'>📌 같은 화면에 함께 "
                        "떠 있는 값 — <b>‘지금 보이는’ 값</b>이라 아침에는 어제까지가 "
                        "반영돼 있습니다. 보이는 대로 넣으면 됩니다</p>",
                        unsafe_allow_html=True)
                    m3 = ui.cols(3, 2, keep_row=True)
                    a_ac = grid_at(m3, 0, 3).number_input(
                        "단기 부하 (급성)", 0, 3000, 0, key="am_acute",
                        help="최근 7일 운동 부하의 **누적(가중 합)**입니다 — 평균이 "
                             "아닙니다. 훈련이 들어오면 올라가고 쉬면 조금씩 내려갑니다.")
                    a_ch = grid_at(m3, 1, 3).number_input(
                        "만성 부하", 0, 3000, 0, key="am_chronic",
                        help="최근 28일 기준의 장기 부하. ‘부하 비율’ 화면 위에 "
                             "급성과 나란히 떠 있습니다. 넣어두면 **부하 비율은 "
                             "자동으로 계산**됩니다.")
                    a_rec = grid_at(m3, 2, 3).number_input(
                        "회복 시간 (h)", 0, 200, 0, key="am_rec",
                        help="아침에 본 값이면 기상 시각 기준으로 줄어듭니다.")
                    a_lr = round(a_ac / a_ch, 3) if (a_ac and a_ch) else 0
                    nt = st.text_input("메모", "", key="am_note")
                    if st.form_submit_button("저장", width="stretch", type="primary"):
                        _at = datetime.combine(dd_, dtime(int(mhour), 0))
                        _am_until = ((_at + timedelta(hours=float(a_rec))).strftime(
                            "%Y-%m-%d %H:%M") if a_rec else "")
                        r = db.upsert_row(
                            "DailyStatus",
                            {"StatusDate": dd_.strftime("%Y-%m-%d"), "EntryKind": "아침"},
                            {"StatusID": new_id("DS"),
                             "TrainingReadiness": tr or "", "BodyBattery": bb or "",
                             "HRVStatus": hrv, "HRVms": hrvms or "",
                             "SleepScore": slp or "", "RestingHR": rhr or "",
                             "SleepHistory": "" if slh == "(미입력)" else slh,
                             "StressHistory": "" if sth == "(미입력)" else sth,
                             "AcuteLoad": a_ac or "", "ChronicLoad": a_ch or "",
                             "LoadRatio": a_lr or "",
                             "RecoveryTimeHr": a_rec or "",
                             "RecoveryUntil": _am_until,
                             "Notes": nt,
                             "MeasuredAt": f"{_at:%Y-%m-%d %H:%M} (기상 직후)"})
                        st.success("오늘 아침 값 " + ("갱신" if r == "updated" else "저장") + " 완료")
                        st.rerun()
            else:
                # ── 🏃 훈련 후 ───────────────────────────────────────────
                with st.form("f_daily_pm", clear_on_submit=True):
                    st.caption("**그날 훈련이 반영된 뒤** 읽어야 맞는 값들입니다. "
                               "단기 부하·회복 시간은 아침 창에도 있는데, 같은 값을 "
                               "**다른 시점에 본 것**이라 그렇습니다 — 나중에 본 쪽이 "
                               "대시보드에 쓰입니다. 훈련 종료 시각을 함께 넣으면 "
                               "회복 시간을 ‘지금 기준 남은 시간’으로 되돌려 보여줍니다.")
                    p0 = ui.cols(2, 1, keep_row=True)
                    dd_ = p0[0].date_input("날짜", date.today(), key="pm_date")
                    mhour = p0[1 % len(p0)].number_input(
                        "훈련 종료 시각 (시)", 0, 23, datetime.now().hour, 1,
                        key="pm_hour", format="%d",
                        help="회복 시간을 ‘지금 기준 남은 시간’으로 되돌릴 때 씁니다. "
                             "시 단위면 충분합니다.")
                    ts = st.selectbox(
                        "Training Status", list(ana.TRAINING_STATUS.keys()),
                        index=list(ana.TRAINING_STATUS).index("Productive"),
                        format_func=lambda k: f"{ana.TRAINING_STATUS_KR[k]} ({k})",
                        key="pm_ts", help="훈련이 끝나야 갱신됩니다.")
                    p1 = ui.cols(4, 2, keep_row=True)
                    acute = grid_at(p1, 0, 4).number_input(
                        "단기 부하 (급성)", 0, 3000, 0, key="pm_acute",
                        help="최근 7일 운동 부하의 **누적(가중 합)** — 평균이 아닙니다.")
                    chron = grid_at(p1, 1, 4).number_input(
                        "만성 부하", 0, 3000, 0, key="pm_chronic",
                        help="최근 28일 기준의 장기 부하. 넣어두면 부하 비율은 "
                             "자동으로 계산됩니다.")
                    rec = grid_at(p1, 2, 4).number_input(
                        "회복 시간 (h)", 0, 200, 0, key="pm_rec")
                    im = grid_at(p1, 3, 4).number_input(
                        "고강도 분 (주간)", 0, 1000, 0, key="pm_im",
                        help="이번 주 누적이라 주중에 계속 늘어납니다.")
                    ratio = round(acute / chron, 3) if (acute and chron) else 0
                    nt = st.text_input("메모", "", key="pm_note")
                    if st.form_submit_button("저장", width="stretch", type="primary"):
                        _at = datetime.combine(dd_, dtime(int(mhour), 0))
                        _until = ((_at + timedelta(hours=float(rec))).strftime("%Y-%m-%d %H:%M")
                                  if rec else "")
                        r = db.upsert_row(
                            "DailyStatus",
                            {"StatusDate": dd_.strftime("%Y-%m-%d"), "EntryKind": "훈련 후"},
                            {"StatusID": new_id("DS"), "TrainingStatus": ts,
                             "AcuteLoad": acute or "", "ChronicLoad": chron or "",
                             "LoadRatio": ratio or "",
                             "RecoveryTimeHr": rec or "", "IntensityMinutes": im or "",
                             "Notes": nt,
                             "MeasuredAt": f"{_at:%Y-%m-%d %H:%M} (훈련 직후)",
                             "RecoveryUntil": _until})
                        st.success("훈련 후 값 " + ("갱신" if r == "updated" else "저장") + " 완료")
                        st.rerun()

            st.caption("비워 둔 항목(0)은 저장되지 않고, 이미 넣어둔 값도 지워지지 않습니다. "
                       "매일 전부 채울 필요 없습니다 — 대시보드는 항목별로 가장 최근에 "
                       "입력된 값을 씁니다.")
            with st.expander("❓ 입력 시점 가이드 — 어떤 값을 언제 봐야 하나"):
                st.markdown(DAILY_TIMING_HELP)

        df_daily = db.load_data("DailyStatus")
        if not df_daily.empty:
            with ui.card("dtrend"):
                ui.head("최근 추이")
                dv = df_daily.tail(60).copy()
                dv["StatusDate"] = pd.to_datetime(dv["StatusDate"], errors="coerce")
                _dt = dual_small_multiples(
                    dv, "StatusDate",
                    [("BodyBattery", "Body Battery", C["primary"], ",d"),
                     ("TrainingReadiness", "Readiness", C["teal"], ",d"),
                     ("HRVms", "HRV (ms)", C["accent"], ",d")],
                    _span_days(dv["StatusDate"]), h_pc=84, h_mb=70)
                if _dt is not None:
                    stacked_charts(_dt)
                else:
                    st.caption("데이터 없음")

        record_editor(
            "DailyStatus", "StatusID",
            lambda r: (f"{str(r['StatusDate'])[:10]}"
                       f" · {r.get('EntryKind','') or '기타'}"
                       f" · {r.get('TrainingStatus','') or r.get('HRVStatus','') or '—'}"),
            [("StatusDate", "date", "날짜", None),
             ("TrainingStatus", "select", "Training Status", list(ana.TRAINING_STATUS)),
             ("AcuteLoad", "numopt", "단기 부하 (급성)", None),
             ("ChronicLoad", "numopt", "만성 부하", None),
             ("LoadRatio", "numopt", "부하 비율 (급성·만성 넣으면 자동)", None),
             ("RecoveryTimeHr", "numopt", "회복 시간 (h)", None),
             ("TrainingReadiness", "numopt", "Readiness", None),
             ("BodyBattery", "numopt", "Body Battery", None),
             ("HRVms", "numopt", "HRV (ms)", None),
             ("HRVStatus", "select", "HRV 상태",
              ["Balanced", "Unbalanced", "Low", "Poor", "No Status"]),
             ("SleepScore", "numopt", "수면 점수", None),
             ("RestingHR", "numopt", "안정시 심박", None),
             ("IntensityMinutes", "numopt", "고강도 분", None),
             ("SleepHistory", "select", "최근 수면 점수", SLEEP_HIST_OPTS),
             ("StressHistory", "select", "최근 스트레스", STRESS_HIST_OPTS),
             ("Notes", "area", "메모", None)],
            key="daily",
            # 급성·만성이 둘 다 있으면 비율은 저장할 때 다시 계산합니다.
            # (직접 넣은 값이 있어도 계산값이 더 정확해서 덮어씁니다)
            derive=lambda v: ({"LoadRatio": round(fnum(v.get("AcuteLoad"))
                                                  / fnum(v.get("ChronicLoad")), 3)}
                              if fnum(v.get("AcuteLoad")) > 0
                              and fnum(v.get("ChronicLoad")) > 0 else {}))

    # ── 2-4 가민 측정 기록 ────────────────────────────────────────────────────────
    with a3:
        with ui.card("gweekly"):
            ui.head("📈 가민 측정 기록",
                    "Connect → 통계/성과 에서 주 1회만 확인하면 됩니다 · "
                    "기록해서 추이만 보는 값이라 지워도 다른 계산에는 영향이 없습니다")
            with st.form("f_metric", clear_on_submit=True):
                md_ = st.date_input("측정일", date.today())

                st.markdown("<p class='rl-sub' style='margin:10px 0 2px'>기량</p>",
                            unsafe_allow_html=True)
                r1 = ui.cols(4, 1, keep_row=True)
                mv = r1[0].number_input("VO₂max", 0.0, 90.0, 0.0, 0.5, format="%g")
                # 가민 피트니스 나이는 0.5세 단위입니다 (예: 38.5)
                fa = r1[1 % len(r1)].number_input("피트니스 나이", 0.0, 100.0, 0.0, 0.5,
                                                  format="%g")
                es = r1[2 % len(r1)].number_input(
                    "Endurance Score", 0, 12000, 0,
                    help="장시간 운동을 버티는 능력 점수(대략 0~25,000). "
                         "시계: 위/아래 버튼으로 글랜스 넘기기 → Endurance Score. "
                         "안 보이면 설정 → 모양(Appearance) → 글랜스 → 추가에서 켜세요. "
                         "Connect 앱: 성과 통계 → 지구력 점수. 모르면 0으로 두세요.")
                hs = r1[3 % len(r1)].number_input(
                    "Hill Score", 0, 100, 0,
                    help="오르막 달리기 능력 점수(1~100). 경사 2% 이상 구간이 있는 야외 러닝이 "
                         "쌓여야 표시됩니다. 시계: 글랜스 → Hill Score "
                         "(설정 → 모양 → 글랜스 → 추가). 모르면 0으로 두세요.")

                st.markdown("<p class='rl-sub' style='margin:10px 0 2px'>Load Focus (최근 4주 부하)</p>",
                            unsafe_allow_html=True)
                r2 = ui.cols(3, 1, keep_row=True)
                fan = r2[0].number_input("무산소", 0, 2000, 0)
                fhi = r2[1 % len(r2)].number_input("고강도 유산소", 0, 2000, 0)
                flo = r2[2 % len(r2)].number_input("저강도 유산소", 0, 5000, 0)

                st.markdown("<p class='rl-sub' style='margin:10px 0 2px'>가민 레이스 예측</p>",
                            unsafe_allow_html=True)
                r3 = ui.cols(4, 1, keep_row=True)
                p5 = r3[0].text_input("5K", "", placeholder="21:30")
                p10 = r3[1 % len(r3)].text_input("10K", "", placeholder="44:58")
                ph = r3[2 % len(r3)].text_input("Half", "", placeholder="1:39:20")
                pf = r3[3 % len(r3)].text_input("Full", "", placeholder="3:29:41")

                st.markdown("<p class='rl-sub' style='margin:10px 0 2px'>젖산역치</p>",
                            unsafe_allow_html=True)
                r4 = ui.cols(2, 1, keep_row=True)
                mlp = r4[0].text_input("LT 페이스", "", placeholder="4:50",
                                       help="가민이 감지한 젖산역치 페이스. 기록용입니다.")
                st.caption("⚠️ **LTHR·체중·체지방률은 여기서 입력하지 않습니다.** "
                           "이 값들은 심박존과 훈련 부하를 과거까지 다시 계산하는 **기준값**이라 "
                           "‘👤 프로필 & 기준값’ 탭에서 **적용일과 함께** 저장해야 합니다. "
                           "가민이 새 LTHR을 알려줬다면 그쪽에서 갱신하세요.")

                if st.form_submit_button("저장", width="stretch", type="primary"):
                    db.append_rows("Metrics", pd.DataFrame([{
                        "MetricID": new_id("MET"), "MetricDate": md_.strftime("%Y-%m-%d"),
                        "VO2Max": mv or "", "FitnessAge": fa or "",
                        "EnduranceScore": es or "", "HillScore": hs or "",
                        "FocusAnaerobic": fan or "", "FocusHighAerobic": fhi or "",
                        "FocusLowAerobic": flo or "",
                        "Pred5K": p5, "Pred10K": p10, "PredHalf": ph, "PredFull": pf,
                        "LTPace": mlp, "LTHR": "", "LTPower": "",
                        "WeightKg": "", "BodyFatPct": "", "Notes": ""}]))
                    st.success("저장 완료")
                    st.rerun()

        dm = db.load_data("Metrics")
        if not dm.empty:
            dm["MetricDate"] = pd.to_datetime(dm["MetricDate"], errors="coerce")
            mc = ui.cols(2, 1)
            # (컬럼, 제목, 축 숫자 포맷, 눈금 최소 간격)
            dm = only_measure_rows(dm)
            charts = [("VO2Max", "VO₂max", ".1f", 0.1),
                      ("EnduranceScore", "Endurance Score", ",d", 1),
                      ("HillScore", "Hill Score", ",d", 1),
                      ("FitnessAge", "피트니스 나이", "g", 0.5)]
            for i, (col, title, fmt, step) in enumerate(charts):
                sub = dm[["MetricDate", col]].dropna()
                with mc[i % len(mc)]:
                    with ui.card(f"mt{i}"):
                        ui.head(title)
                        if not sub.empty:
                            st.altair_chart(alt.Chart(sub).mark_line(
                                point=True, strokeWidth=2.5, color=C["primary"]).encode(
                                x=alt.X("MetricDate:T", title=None, axis=date_axis(_span_days(sub["MetricDate"]))),
                                y=alt.Y(f"{col}:Q", title=None,
                                        scale=alt.Scale(zero=False),
                                        axis=alt.Axis(format=fmt, tickMinStep=step)),
                                tooltip=[alt.Tooltip("MetricDate:T", title="측정일"),
                                         alt.Tooltip(f"{col}:Q", title=title, format=fmt)]
                            ).properties(height=ui.chart_height(190, 170)), width="stretch")
                        else:
                            st.caption("데이터 없음")

        record_editor(
            "Metrics", "MetricID",
            lambda r: f"{str(r['MetricDate'])[:10]} · VO₂max {vtxt(r.get('VO2Max'), '{:.1f}')}",
            [("MetricDate", "date", "측정일", None),
             ("VO2Max", "numopt", "VO₂max", None),
             ("FitnessAge", "numopt", "피트니스 나이", 0.5),
             ("EnduranceScore", "numopt", "Endurance Score", None),
             ("HillScore", "numopt", "Hill Score", None),
             ("FocusAnaerobic", "numopt", "Focus 무산소", None),
             ("FocusHighAerobic", "numopt", "Focus 고강도 유산소", None),
             ("FocusLowAerobic", "numopt", "Focus 저강도 유산소", None),
             ("Pred5K", "text", "예측 5K", None),
             ("Pred10K", "text", "예측 10K", None),
             ("PredHalf", "text", "예측 Half", None),
             ("PredFull", "text", "예측 Full", None),
             ("LTPace", "text", "LT 페이스", None),
             ("Notes", "area", "메모", None)],
            key="metric", title="✏️ 측정 기록 수정 / 삭제",
            row_filter=only_measure_rows,
            note="LTHR·체중·체지방률은 ‘👤 프로필 & 기준값’ 탭의 "
                 "**기준값 이력 수정 / 삭제**에서 고칩니다.",
            empty_msg="아직 가민 측정 기록이 없습니다.")


# ═════════════════════════════════════════════════════════════════════════
# TAB 3 · 분석 — 보는 곳
# ═════════════════════════════════════════════════════════════════════════
with tab_ana:
    labels = (["📋 이력", "⌚ 가민", "🎚️ 존", "📈 통계", "🔮 예측"] if ui.is_mobile()
              else ["📋 훈련 이력", "⌚ 가민 추이", "🎚️ 심박존",
                    "📈 계산 통계", "🔮 기량 예측"])
    s_hist, s_garmin, s_zone, s_stat, s_pred = st.tabs(labels)

    # ── 3-1 훈련 이력 ───────────────────────────────────────────────────────────
    with s_hist:
        df_w = db.load_data("Workouts")
        d = ana.prepare_workouts(df_w)

        # ---- 기간 선택 (기본: 이번 주) --------------------------------------
        with ui.card("period"):
            ui.head("🗓️ 기간", "기본은 주 단위입니다 — 날짜를 바꾸면 그 주 전체가 나옵니다")
            _mob = ui.is_mobile()
            # PC는 한 줄에 [단위][◀][기준 날짜][▶][프로젝트][유형].
            # 화살표는 좁은 칸에 넣어 작게 두고, 라벨이 없는 만큼 위 여백으로
            # 옆 입력칸과 높이를 맞춥니다. (모바일은 한 단으로 쌓습니다)
            if _mob:
                _c = [st] * 6
            else:
                _c = st.columns([1.0, 0.34, 1.2, 0.34, 1.35, 1.35])

            punit = _c[0].selectbox("단위", ["주", "월", "전체"], key="hist_unit")
            _slot = _c[2].container()      # 날짜 자리를 먼저 잡아둡니다

            if punit != "전체":
                # 버튼은 date_input보다 먼저 '실행'되어야 세션 값을 바꿀 수 있습니다.
                # (자리는 위에서 잡아뒀으니 화면 순서는 날짜가 가운데로 갑니다)
                for _cell, _lab, _n, _key, _tip in (
                        (_c[1], "◀", -1, "hist_prev", "이전 기간"),
                        (_c[3], "▶", +1, "hist_next", "다음 기간")):
                    if not _mob:
                        _cell.markdown("<div style='height:28px'></div>",
                                       unsafe_allow_html=True)
                    if _cell.button(_lab if not _mob else f"{_lab} {_tip}",
                                    width="stretch", key=_key, help=_tip):
                        st.session_state["hist_date"] = period_shift(
                            st.session_state.get("hist_date", date.today()), punit, _n)
                        st.rerun()
                with _slot:
                    anchor = st.date_input(
                        "기준 날짜", st.session_state.get("hist_date", date.today()),
                        key="hist_date")
            else:
                anchor = date.today()
            p_start, p_end = period_range(anchor, punit)

            sel_p = _c[4].selectbox("프로젝트", ["전체"] + list(proj_opts)[1:], key="hist_p")
            sel_t = _c[5].selectbox("유형", ["전체"] + WORKOUT_TYPES, key="hist_t")

            if p_start is None:
                st.caption("전체 기간의 기록을 봅니다.")
            else:
                st.markdown(
                    f"<p class='rl-sub' style='margin:8px 0 0'>"
                    f"<b>{p_start:%Y-%m-%d}({WD_KR[p_start.weekday()]})"
                    f" ~ {p_end:%Y-%m-%d}({WD_KR[p_end.weekday()]})</b>"
                    f" · {(p_end - p_start).days + 1}일</p>", unsafe_allow_html=True)

        def in_period(df, a, b):
            if df.empty or a is None:
                return df
            return df[(df["WorkoutDate"] >= pd.Timestamp(a)) &
                      (df["WorkoutDate"] <= pd.Timestamp(b) + pd.Timedelta(days=1)
                       - pd.Timedelta(seconds=1))]

        def apply_filters(df):
            if df.empty:
                return df
            if sel_p != "전체":
                df = df[df["ProjectID"].astype(str) == proj_opts[sel_p]]
            if sel_t != "전체":
                df = df[df["WorkoutType"] == sel_t]
            return df

        view = apply_filters(in_period(d, p_start, p_end))
        # 직전 같은 길이의 기간 — 증감 비교용
        if p_start is None:
            prev_view = d.iloc[0:0]
        else:
            span = (p_end - p_start).days + 1
            prev_view = apply_filters(in_period(
                d, p_start - timedelta(days=span), p_start - timedelta(days=1)))

        # ---- 기간 요약 ------------------------------------------------------
        with ui.card("histsum"):
            if view.empty:
                st.caption("이 기간에는 기록이 없습니다. 위에서 날짜나 단위를 바꿔보세요.")
            else:
                def vs(diff, unit, nd=1, more="많음", less="적음"):
                    """지난 기간과의 차이를 말로 씁니다.
                    '+/-'로 시작하면 타일이 빨강·초록을 입히는데, 훈련량이 줄어든 게
                    나쁜 것도 아니고 페이스가 줄어든 건 오히려 빨라진 것이라
                    색으로 좋고 나쁨을 말하지 않습니다."""
                    if prev_view.empty or p_start is None:
                        return None
                    if abs(diff) < 10 ** (-nd):
                        return "지난 기간과 같음"
                    return (f"지난 기간보다 {abs(diff):.{nd}f}{unit} "
                            f"{more if diff > 0 else less}")

                tot_km = float(view["DistanceKm"].sum())
                tot_min = float(view["DurationMinutes"].sum())
                p_km = float(prev_view["DistanceKm"].sum()) if not prev_view.empty else 0.0
                p_min = float(prev_view["DurationMinutes"].sum()) if not prev_view.empty else 0.0
                hr_v = view.loc[view["AvgHeartRate"] > 0, "AvgHeartRate"]
                _pace = tot_min * 60 / max(tot_km, .001)
                _ppace = (p_min * 60 / p_km) if p_km > 0 else None

                # 대시보드와 같은 타일로 통일 — 값 크기·간격·여백이 같아집니다
                ui.tiles([
                    {"label": "훈련 횟수", "value": f"{len(view)}", "unit": "회",
                     "sub": vs(len(view) - len(prev_view), "회", 0)},
                    {"label": "총 거리", "value": f"{tot_km:.1f}", "unit": "km",
                     "sub": vs(tot_km - p_km, "km")},
                    {"label": "총 시간", "value": ana.time_str(tot_min * 60),
                     "sub": vs((tot_min - p_min) / 60, "시간")},
                    {"label": "평균 페이스", "value": ana.pace_str(_pace),
                     "sub": (vs(_pace - _ppace, "초/km", 0, more="느림", less="빠름")
                             if _ppace else None)},
                ])
                _foot = []
                if not hr_v.empty:
                    _foot.append(f"평균 심박 **{hr_v.mean():.0f} bpm**")
                if p_start is not None and not prev_view.empty:
                    _foot.append(
                        f"‘지난 기간’은 **직전 {(p_end - p_start).days + 1}일"
                        f"({p_start - timedelta(days=(p_end - p_start).days + 1):%m/%d}"
                        f" ~ {p_start - timedelta(days=1):%m/%d})**")
                if _foot:
                    st.caption(" · ".join(_foot))

        # ---- 유형별 통계 ----------------------------------------------------
        if not view.empty:
            with ui.card("histtype"):
                ui.head("📊 유형별 통계", f"이 기간 훈련 {len(view)}회의 성격 분포")
                g = view.groupby("WorkoutType", dropna=False)
                t = pd.DataFrame({
                    "유형": g.size().index,
                    "횟수": g.size().values,
                    "_km": g["DistanceKm"].sum().values,
                    "_min": g["DurationMinutes"].sum().values,
                })
                hr_by = g.apply(lambda x: x.loc[x["AvgHeartRate"] > 0, "AvgHeartRate"].mean(),
                                include_groups=False)
                t["_hr"] = [hr_by.get(v, np.nan) for v in t["유형"]]
                t = t.sort_values("_km", ascending=False).reset_index(drop=True)
                tot_km2 = max(float(t["_km"].sum()), .001)
                disp = pd.DataFrame({
                    "유형": t["유형"],
                    "횟수": t["횟수"],
                    "거리(km)": t["_km"].round(2),
                    "비중": (t["_km"] / tot_km2 * 100).round(1).astype(str) + "%",
                    "시간": t["_min"].apply(lambda v: ana.time_str(v * 60)),
                    "평균 페이스": (t["_min"] * 60 / t["_km"].clip(lower=.001)).apply(ana.pace_str),
                    "평균 심박": t["_hr"].apply(lambda v: f"{v:.0f}" if np.isfinite(v) else "—"),
                })
                if ui.is_mobile():
                    ui.item_list([
                        (f"{r['유형']} · {r['거리(km)']}km ({r['비중']})",
                         f"{r['횟수']}회 · {r['시간']} · {r['평균 페이스']} · {r['평균 심박']}bpm")
                        for _, r in disp.iterrows()])
                else:
                    st.dataframe(disp, width="stretch", hide_index=True)
                if len(t) > 1:
                    st.altair_chart(alt.Chart(t).mark_bar().encode(
                        y=alt.Y("유형:N", sort="-x", title=None),
                        x=alt.X("_km:Q", title="거리 (km)"),
                        color=alt.Color("유형:N", legend=None,
                                        scale=alt.Scale(range=CHART_PALETTE)),
                        tooltip=[alt.Tooltip("유형"), alt.Tooltip("_km:Q", title="거리(km)",
                                                                  format=".2f"),
                                 alt.Tooltip("횟수:Q")]
                    ).properties(height=ui.chart_height(28 * len(t) + 40,
                                                        26 * len(t) + 40)), width="stretch")

        # ---- 기록 목록 (클릭하면 아래에 상세) --------------------------------
        sel_wid = None
        if not view.empty:
            with ui.card("histlist"):
                ui.head("📋 기록", "한 줄을 선택하면 아래에 그 훈련의 상세가 나옵니다")
                vlist = view.iloc[::-1].reset_index(drop=True)
                if ui.is_mobile():
                    wopts = {f"{r.WorkoutDate:%m/%d} · {r.WorkoutType} · "
                             f"{r.DistanceKm:.2f}km": r.WorkoutID
                             for r in vlist.itertuples()}
                    wpick = st.selectbox("훈련 선택", list(wopts), key="hist_pick")
                    sel_wid = wopts[wpick]
                    ui.item_list([
                        (f"{r.WorkoutType} · {r.DistanceKm:.2f} km",
                         f"{r.WorkoutDate:%m/%d} · {ana.pace_str(r.PaceSec)} · "
                         f"{int(r.AvgHeartRate) if r.AvgHeartRate > 0 else '—'}bpm")
                        for r in vlist.itertuples()])
                else:
                    show = vlist[["WorkoutDate", "WorkoutType", "DistanceKm",
                                  "DurationMinutes", "AvgHeartRate", "Surface", "Notes"]].copy()
                    show.insert(4, "페이스", vlist["PaceSec"].apply(ana.pace_str))
                    show.columns = ["날짜", "유형", "거리(km)", "시간(분)", "페이스",
                                    "평균심박", "노면", "메모"]
                    ev = st.dataframe(
                        show, width="stretch", hide_index=True,
                        on_select="rerun", selection_mode="single-row", key="hist_tbl",
                        column_config={"날짜": st.column_config.DateColumn(format="YYYY-MM-DD")})
                    rows = list(getattr(ev, "selection", {}).get("rows", []))
                    if rows and rows[0] < len(vlist):
                        sel_wid = vlist.iloc[rows[0]]["WorkoutID"]
                    else:
                        st.caption("↑ 표에서 한 줄을 클릭하세요. (가장 왼쪽 빈 칸을 누르면 선택됩니다)")

        # ---- 선택한 훈련 상세 ------------------------------------------------
        if sel_wid is not None:
            wsel = d[d["WorkoutID"].astype(str) == str(sel_wid)]
            if not wsel.empty:
                W = wsel.iloc[0]
                with ui.card("wdetail"):
                    ui.head(f"🔍 {W['WorkoutDate']:%Y-%m-%d} · {W['WorkoutType']}",
                            str(W.get("Notes") or ""))
                    ui.metrics([
                        ("거리", f"{W['DistanceKm']:.2f} km", None),
                        ("시간", ana.time_str(W["DurationMinutes"] * 60), None),
                        ("평균 페이스", ana.pace_str(W["PaceSec"]), None),
                        ("평균 심박", f"{W['AvgHeartRate']:.0f}" if W["AvgHeartRate"] > 0 else "—",
                         f"최고 {fnum(W.get('MaxHeartRate')):.0f}"
                         if fnum(W.get("MaxHeartRate")) > 0 else None),
                    ], per_row_pc=4)
                    sub = [x for x in [
                        f"케이던스 {fnum(W.get('AvgCadence')):.0f}"
                        if fnum(W.get("AvgCadence")) > 0 else "",
                        f"보폭 {fnum(W.get('AvgStrideM')):.2f}m"
                        if fnum(W.get("AvgStrideM")) > 0 else "",
                        f"접지 {fnum(W.get('AvgGCTms')):.0f}ms"
                        if fnum(W.get("AvgGCTms")) > 0 else "",
                        f"상승 {fnum(W.get('ElevationGainM')):.0f}m"
                        if fnum(W.get("ElevationGainM")) > 0 else "",
                        f"{fnum(W.get('Temperature')):.1f}°C"
                        if fnum(W.get("Temperature")) != 0 else "",
                        f"RPE {fnum(W.get('RPE')):.0f}" if fnum(W.get("RPE")) > 0 else "",
                        str(W.get("Surface") or ""),
                    ] if x]
                    if sub:
                        st.caption(" · ".join(sub))

                    df_laps = db.load_data("Laps")
                    LL = (df_laps[df_laps["WorkoutID"].astype(str) == str(sel_wid)].copy()
                          if not df_laps.empty else pd.DataFrame())
                    if LL.empty:
                        st.caption("이 훈련에는 저장된 랩이 없습니다. "
                                   "‘📥 CSV 가져오기’에서 활동 상세 CSV를 넣으면 구간별로 보입니다.")
                    else:
                        CL = ana.classify_laps(LL)
                        lap_km = float(pd.to_numeric(CL["DistanceKm"],
                                                     errors="coerce").sum())
                        w_km = float(W["DistanceKm"])
                        if w_km > 0 and abs(lap_km - w_km) / w_km > 0.05:
                            st.warning(f"⚠️ 랩 합계({lap_km:.2f}km)가 훈련 거리"
                                       f"({w_km:.2f}km)와 다릅니다. "
                                       "가져오기가 잘못됐을 수 있으니 확인해 주세요.")
                        shape = ana.interval_shape(CL)
                        dcp = ana.decoupling(CL[CL["역할"] != "자투리"])
                        dtone, dtxt = ana.decoupling_verdict(dcp)
                        st.markdown(
                            f"<div style='margin:10px 0 0'>{ui.pill(shape, 'info')} "
                            + (ui.pill(f"심박 디커플링 {dcp:+.1f}%", dtone)
                               if np.isfinite(dcp) else "")
                            + f"</div><p class='rl-sub' style='margin-top:-4px'>{dtxt}</p>",
                            unsafe_allow_html=True)
                        with st.expander("❓ 심박 디커플링이 뭔가요"):
                            st.markdown(DECOUPLING_HELP)

                        rs = ana.lap_role_summary(CL)
                        if not rs.empty and len(rs) > 1:
                            st.markdown("<p class='rl-sub' style='margin:10px 0 2px'>"
                                        "<b>역할별 요약</b> — 인터벌·템포런은 이 표의 "
                                        "‘반복’ 행이 실제 훈련 강도입니다</p>",
                                        unsafe_allow_html=True)
                            st.dataframe(rs, width="stretch", hide_index=True)

                        CL = CL.sort_values("LapNo")
                        show_l = pd.DataFrame({
                            "랩": CL["LapNo"].astype(int),
                            "역할": CL["역할"],
                            "거리(km)": CL["DistanceKm"].map(lambda v: f"{fnum(v):.2f}"),
                            "시간": CL["DurationMinutes"].apply(lambda v: ana.time_str(v * 60)),
                            "페이스": CL["PaceSec"].apply(ana.pace_str),
                            "평균심박": CL["AvgHeartRate"].map(lambda v: vtxt(v, "{:.0f}")),
                            "최대심박": CL["MaxHeartRate"].map(lambda v: vtxt(v, "{:.0f}")),
                            "케이던스": CL["AvgCadence"].map(lambda v: vtxt(v, "{:.0f}")),
                            "보폭(m)": CL["AvgStrideM"].map(lambda v: vtxt(v, "{:.2f}")),
                        })
                        if ui.is_mobile():
                            ui.item_list([
                                (f"랩 {int(r['랩'])} · {r['역할']} · {r['페이스']}",
                                 f"{r['거리(km)']}km · {r['시간']} · {r['평균심박']}bpm")
                                for _, r in show_l.iterrows()])
                        else:
                            st.dataframe(show_l, width="stretch", hide_index=True)

                        # CSV에서 가져온 나머지 랩 항목 — 기본은 접어둡니다
                        _extra = [
                            ("GAP(경사보정)", "GapPaceSec", "pace"),
                            ("최대 페이스", "MaxPaceSec", "pace"),
                            ("최고 케이던스", "MaxCadence", "{:.0f}"),
                            ("접지(ms)", "AvgGCTms", "{:.0f}"),
                            ("수직진동(cm)", "AvgVertOscCm", "{:.1f}"),
                            ("수직비율(%)", "AvgVertRatioPct", "{:.1f}"),
                            ("파워(W)", "AvgPower", "{:.0f}"),
                            ("NP(W)", "NormPower", "{:.0f}"),
                            ("W/kg", "AvgWkg", "{:.2f}"),
                            ("최대파워(W)", "MaxPower", "{:.0f}"),
                            ("상승(m)", "ElevGainM", "{:.0f}"),
                            ("하강(m)", "ElevLossM", "{:.0f}"),
                            ("칼로리", "Calories", "{:.0f}"),
                            ("온도(°C)", "TempC", "{:.1f}"),
                            ("이동시간", "MovingMinutes", "dur"),
                            ("이동페이스", "MovingPaceSec", "pace"),
                        ]
                        _have = [(lab, cc, f) for lab, cc, f in _extra
                                 if cc in CL.columns
                                 and pd.to_numeric(CL[cc], errors="coerce").fillna(0).abs().sum() > 0]
                        if _have:
                            with st.expander(f"📋 랩별 전체 지표 {len(_have)}개 더 보기"):
                                _wide = {"랩": CL["LapNo"].astype(int)}
                                for lab, cc, f in _have:
                                    if f == "pace":
                                        _wide[lab] = CL[cc].map(
                                            lambda v: ana.pace_str(fnum(v)) if fnum(v) > 0 else "—")
                                    elif f == "dur":
                                        _wide[lab] = CL[cc].map(
                                            lambda v: ana.time_str(fnum(v) * 60) if fnum(v) > 0 else "—")
                                    else:
                                        _wide[lab] = CL[cc].map(lambda v, _f=f: vtxt(v, _f))
                                st.dataframe(pd.DataFrame(_wide), width="stretch",
                                             hide_index=True)
                                st.caption("가민 활동 상세 CSV에 들어 있는 랩 항목을 그대로 "
                                           "저장합니다. 값이 하나도 없는 항목은 표시하지 않습니다.")

                        lp = CL[(CL["PaceSec"] > 0) & (CL["역할"] != "자투리")].copy()
                        if len(lp) > 1:
                            lp["페이스"] = lp["PaceSec"].apply(ana.pace_str)
                            mm_ss = ("floor(datum.value/60) + ':' + "
                                     "(datum.value%60 < 10 ? '0' : '') + "
                                     "format(round(datum.value%60), 'd')")
                            bars = alt.Chart(lp).mark_bar().encode(
                                x=alt.X("LapNo:O", title="랩",
                                        axis=alt.Axis(labelAngle=0)),
                                y=alt.Y("PaceSec:Q", title="페이스 (짧을수록 빠름)",
                                        scale=alt.Scale(zero=False, nice=True),
                                        axis=alt.Axis(labelExpr=mm_ss)),
                                color=alt.Color("역할:N", title=None, scale=alt.Scale(
                                    domain=ana.LAP_ROLES,
                                    range=[C["slate"], C["accent"], C["teal"],
                                           C["violet"], C["primary"], C["pale"]])),
                                tooltip=[alt.Tooltip("LapNo", title="랩"),
                                         alt.Tooltip("역할"),
                                         alt.Tooltip("페이스"),
                                         alt.Tooltip("DistanceKm", title="거리(km)"),
                                         alt.Tooltip("AvgHeartRate", title="평균심박")])
                            avg = alt.Chart(lp).mark_rule(
                                strokeDash=[5, 4], color=C["slate"]).encode(
                                y=alt.Y("mean(PaceSec):Q"),
                                tooltip=[alt.Tooltip("mean(PaceSec):Q", title="평균 페이스(초/km)",
                                                     format=".0f")])
                            st.altair_chart((bars + avg).properties(
                                height=ui.chart_height(230, 200)), width="stretch")
                            st.caption("점선 = 이 훈련의 평균 페이스 · "
                                       "막대가 낮을수록 빠른 구간입니다.")

        if not view.empty:
            with ui.card("edit"):
                ui.head("✏️ 수정 / 삭제")
                opts = {f"{r.WorkoutDate:%Y-%m-%d} · {r.WorkoutType} · {r.DistanceKm:.2f}km": r.WorkoutID
                        for r in view.iloc[::-1].itertuples()}
                pick = st.selectbox("대상", list(opts), key="edit_pick")
                wid = opts[pick]
                row = df_w[df_w["WorkoutID"] == wid].iloc[0]
                with st.form("f_edit"):
                    g = ui.cols(3, 1, keep_row=True)
                    e_date = g[0].date_input("날짜", pd.to_datetime(row["WorkoutDate"]).date())
                    e_type = g[1 % len(g)].selectbox("유형", WORKOUT_TYPES,
                                                     index=WORKOUT_TYPES.index(row["WorkoutType"])
                                                     if row["WorkoutType"] in WORKOUT_TYPES else 0)
                    e_shoe = g[2 % len(g)].selectbox(
                        "러닝화", list(shoe_opts),
                        index=list(shoe_opts.values()).index(row["ShoeID"])
                        if row.get("ShoeID") in shoe_opts.values() else 0)
                    h = ui.cols(3, 1, keep_row=True)
                    e_dist = h[0].number_input("거리(km)", 0.0, 300.0, fnum(row["DistanceKm"]), 0.01)
                    e_min = h[1 % len(h)].number_input("시간(분)", 0.0, 1500.0, fnum(row["DurationMinutes"]), 0.5)
                    e_hr = h[2 % len(h)].number_input("평균심박", 0, 250, int(fnum(row["AvgHeartRate"])))
                    e_note = st.text_area("메모", str(row.get("Notes", "") or ""), height=70)

                    q = ui.cols(2, 2, keep_row=True)
                    if q[0].form_submit_button("💾 수정 저장", width="stretch", type="primary"):
                        idx = df_w["WorkoutID"] == wid
                        set_cells(df_w, idx, {
                            "WorkoutDate": e_date.strftime("%Y-%m-%d"),
                            "WorkoutType": e_type, "DistanceKm": e_dist,
                            "DurationMinutes": e_min, "AvgHeartRate": e_hr,
                            "ShoeID": shoe_opts[e_shoe], "Notes": e_note,
                            "PaceSec": (round(e_min * 60 / e_dist, 1)
                                        if e_dist > 0 else "")})
                        db.write_sheet("Workouts", df_w)
                        st.success("수정 완료")
                        st.rerun()
                    if q[1].form_submit_button("🗑️ 삭제", width="stretch"):
                        db.write_sheet("Workouts", df_w[df_w["WorkoutID"] != wid])
                        st.warning("삭제 완료")
                        st.rerun()

    # ── 3-2 가민 추이 (가민이 준 값 그대로) ─────────────────────────────────────────────
    with s_garmin:
        gd = db.load_data("DailyStatus")
        gm = db.load_data("Metrics")
        gw = ana.prepare_workouts(db.load_data("Workouts"))

        if gd.empty and gm.empty:
            st.info("‘✍️ 기록 → ⌚ 가민 일일 / 📈 가민 측정’에서 값을 입력하면 여기에 추이가 그려집니다.")
        else:
            with ui.card("gperiod"):
                ui.head("📅 기간", "대시보드 타일은 최근 값만 보여줍니다 — "
                                 "전체 추세는 이 탭에서 봅니다")
                g_sel = seg("기간", list(RANGE_DAYS), "garmin_range", "3개월")
                g_n = RANGE_DAYS[g_sel]
                if g_n is None:
                    st.caption("전체 기간의 입력 기록을 봅니다.")
                else:
                    st.caption(f"최근 {g_n}일 · 입력된 날만 점으로 찍힙니다.")

            def _clip(df, datecol):
                """선택한 기간으로 자릅니다."""
                if df.empty or g_n is None:
                    return df
                cut = pd.Timestamp.now().normalize() - pd.Timedelta(days=g_n - 1)
                return df[df[datecol] >= cut]

            if not gd.empty:
                gdv = gd.copy()
                gdv["StatusDate"] = pd.to_datetime(gdv["StatusDate"], errors="coerce")
                gdv = gdv.dropna(subset=["StatusDate"]).sort_values("StatusDate")
                gdv = _clip(gdv, "StatusDate")

                with ui.card("gts"):
                    ui.head("⌚ 트레이닝 상태 타임라인", "가민이 판정한 상태의 변화")
                    tl = gdv[gdv["TrainingStatus"].astype(str).str.strip() != ""].copy()
                    if not tl.empty:
                        tl["상태"] = tl["TrainingStatus"].map(
                            lambda x: ana.TRAINING_STATUS_KR.get(str(x), str(x)))
                        order = ["무리한 훈련", "과훈련", "비생산적", "트레이닝 부족",
                                 "회복", "유지", "생산적", "피킹"]
                        st.altair_chart(alt.Chart(tl).mark_circle(size=110, opacity=.85).encode(
                            x=alt.X("StatusDate:T", title=None, axis=date_axis(_span_days(tl["StatusDate"]))),
                            y=alt.Y("상태:N", sort=order, title=None),
                            color=alt.Color("상태:N", sort=order, legend=None,
                                            scale=alt.Scale(domain=order,
                                                            range=STATUS_COLORS())),
                            tooltip=[alt.Tooltip("StatusDate:T", title="날짜", format="%Y-%m-%d"),
                                     alt.Tooltip("상태:N", title="상태")]
                        ).properties(height=ui.chart_height(220, 200)), width="stretch")
                    else:
                        st.caption("Training Status 입력 기록이 없습니다.")

                with ui.card("gload"):
                    ui.head("📊 가민 부하 추이",
                            "위 = 단기 부하(7일 누적), 아래 = 부하 비율 · 날짜 축 공유")
                    ld = gdv[["StatusDate", "AcuteLoad", "LoadRatio"]].dropna(how="all",
                                                                             subset=["AcuteLoad", "LoadRatio"])
                    if not ld.empty:
                        # 단위가 다른 두 지표는 축을 겹치지 않고 위아래로 나눕니다
                        _lx = date_axis(_span_days(ld["StatusDate"]))
                        _lt = [alt.Tooltip("StatusDate:T", title="날짜", format="%Y-%m-%d"),
                               alt.Tooltip("AcuteLoad:Q", title="단기 부하", format=",d"),
                               alt.Tooltip("LoadRatio:Q", title="부하 비율", format=".2f")]
                        bars = alt.Chart(ld).mark_bar(color=C["primary"]).encode(
                            x=alt.X("StatusDate:T", title=None, axis=X_HIDDEN),
                            y=alt.Y("AcuteLoad:Q", title=None,
                                    axis=alt.Axis(format=",d", tickMinStep=1)),
                            tooltip=_lt).properties(height=ui.chart_height(180, 145),
                                                    title=panel_title("단기 부하 (최근 7일 누적)"))
                        band = alt.Chart(pd.DataFrame({"lo": [0.8], "hi": [1.4]})).mark_rect(
                            opacity=.10, color=C["teal"]).encode(y="lo:Q", y2="hi:Q")
                        ln = alt.Chart(ld).mark_line(color=C["accent"], point=True).encode(
                            x=alt.X("StatusDate:T", title=None, axis=_lx),
                            y=alt.Y("LoadRatio:Q", title=None,
                                    scale=alt.Scale(zero=False),
                                    axis=alt.Axis(format=".2f")),
                            tooltip=_lt).properties(height=ui.chart_height(110, 92))
                        stacked_charts([bars, (band + ln).properties(
                            title=panel_title("부하 비율 (최적 0.8~1.4)"))])
                        st.caption("초록 띠 = 부하 비율 최적 구간(0.8~1.4)")
                    else:
                        st.caption("단기 부하 / 부하 비율 입력 기록이 없습니다.")

                gg = ui.cols(2, 1)
                with gg[0]:
                    with ui.card("ghrv"):
                        ui.head("💓 HRV · 안정시 심박")
                        _hv = dual_small_multiples(
                            gdv, "StatusDate",
                            [("HRVms", "HRV (ms)", C["primary"], ",d"),
                             ("RestingHR", "안정시 심박 (bpm)", C["accent"], ",d")],
                            _span_days(gdv["StatusDate"]))
                        if _hv is not None:
                            stacked_charts(_hv)
                        else:
                            st.caption("데이터 없음")
                with gg[1 % len(gg)]:
                    with ui.card("grec"):
                        ui.head("😴 회복 시간 · 수면")
                        _rv = dual_small_multiples(
                            gdv, "StatusDate",
                            [("RecoveryTimeHr", "회복 시간 (h)", C["primary"], ",d"),
                             ("SleepScore", "수면 점수", C["teal"], ",d")],
                            _span_days(gdv["StatusDate"]))
                        if _rv is not None:
                            stacked_charts(_rv)
                        else:
                            st.caption("데이터 없음")

            if not gm.empty:
                gmv = gm.copy()
                gmv["MetricDate"] = pd.to_datetime(gmv["MetricDate"], errors="coerce")
                gmv = gmv.dropna(subset=["MetricDate"]).sort_values("MetricDate")
                gmv = _clip(gmv, "MetricDate")

                with ui.card("gfocustrend"):
                    ui.head("🎚️ Load Focus 추이", "부하 성격의 구성이 어떻게 변해왔는지")
                    fo = gmv.melt("MetricDate",
                                  ["FocusAnaerobic", "FocusHighAerobic", "FocusLowAerobic"],
                                  var_name="구분", value_name="부하").dropna()
                    if not fo.empty:
                        name_map = {"FocusAnaerobic": "무산소",
                                    "FocusHighAerobic": "고강도 유산소",
                                    "FocusLowAerobic": "저강도 유산소"}
                        fo["구분"] = fo["구분"].map(name_map)
                        fo["측정일"] = fo["MetricDate"].dt.strftime("%Y-%m-%d")
                        st.altair_chart(alt.Chart(fo).mark_bar(size=22).encode(
                            x=alt.X("측정일:O", title=None,
                                    axis=alt.Axis(labelAngle=-45, labelLimit=80)),
                            y=alt.Y("부하:Q", stack="normalize", title="비중",
                                    axis=alt.Axis(format="%")),
                            color=alt.Color("구분:N", title=None, scale=alt.Scale(
                                domain=["무산소", "고강도 유산소", "저강도 유산소"],
                                range=[C["accent"], C["amber"], C["primary"]])),
                            tooltip=[alt.Tooltip("측정일:O", title="측정일"),
                                     alt.Tooltip("구분:N", title="구분"),
                                     alt.Tooltip("부하:Q", title="부하", format=",d")]
                        ).properties(height=ui.chart_height(260, 220)), width="stretch")
                    else:
                        st.caption("Load Focus 입력 기록이 없습니다.")

                with ui.card("gscore"):
                    ui.head("🏅 가민 기량 점수 추이", "각 지표는 단위가 달라 따로 그립니다")
                    score_cols = [("VO2Max", "VO₂max", C["primary"], ".1f", 0.1),
                                  ("EnduranceScore", "Endurance Score", C["teal"], ",d", 1),
                                  ("HillScore", "Hill Score", C["accent"], ",d", 1),
                                  ("FitnessAge", "피트니스 나이", C["violet"], "g", 0.5)]
                    sc_cols = ui.cols(2, 1)
                    for i, (col, title, color, fmt, step) in enumerate(score_cols):
                        sub = gmv[["MetricDate", col]].dropna()
                        with sc_cols[i % len(sc_cols)]:
                            st.markdown(f"<p class='rl-sub' style='margin:8px 0 -6px'>{title}</p>",
                                        unsafe_allow_html=True)
                            if not sub.empty:
                                st.altair_chart(alt.Chart(sub).mark_line(
                                    point=True, strokeWidth=2.5, color=color).encode(
                                    x=alt.X("MetricDate:T", title=None,
                                            axis=date_axis(_span_days(gmv["MetricDate"]))),
                                    y=alt.Y(f"{col}:Q", title=None,
                                            scale=alt.Scale(zero=False),
                                            axis=alt.Axis(format=fmt, tickMinStep=step)),
                                    tooltip=[alt.Tooltip("MetricDate:T", title="측정일"),
                                             alt.Tooltip(f"{col}:Q", title=title, format=fmt)]
                                ).properties(height=ui.chart_height(170, 150)), width="stretch")
                            else:
                                st.caption("데이터 없음")

            # 훈련별 Training Effect
            if not gw.empty and "AerobicTE" in gw.columns:
                te = gw[["WorkoutDate", "WorkoutType", "AerobicTE", "AnaerobicTE"]].copy()
                te["AerobicTE"] = pd.to_numeric(te["AerobicTE"], errors="coerce")
                te["AnaerobicTE"] = pd.to_numeric(te["AnaerobicTE"], errors="coerce")
                te = te.dropna(subset=["AerobicTE", "AnaerobicTE"], how="all")
                if not te.empty:
                    with ui.card("gte"):
                        ui.head("⚡ 훈련별 Training Effect", "가로=유산소, 세로=무산소 (가민 0~5.0)")
                        st.altair_chart(alt.Chart(te).mark_circle(size=100, opacity=.65).encode(
                            x=alt.X("AerobicTE:Q", title="유산소 TE",
                                    scale=alt.Scale(domain=[0, 5])),
                            y=alt.Y("AnaerobicTE:Q", title="무산소 TE",
                                    scale=alt.Scale(domain=[0, 5])),
                            color=alt.Color("WorkoutType:N", title=None),
                            tooltip=[alt.Tooltip("WorkoutDate:T", title="날짜", format="%Y-%m-%d"),
                                     alt.Tooltip("WorkoutType:N", title="유형"),
                                     alt.Tooltip("AerobicTE:Q", title="유산소 TE", format=".1f"),
                                     alt.Tooltip("AnaerobicTE:Q", title="무산소 TE", format=".1f")]
                        ).properties(height=ui.chart_height(300, 260)), width="stretch")

    # ── 3-3 심박존 분석 ──────────────────────────────────────────────────────────
    with s_zone:
        df_w = db.load_data("Workouts")
        df_met = db.load_data("Metrics")
        hist = ana.profile_history(df_met, PROFILE_NOW)
        cur_lthr = float(hist["LTHR"].iloc[-1]) if not hist.empty else ana.resolve_lthr(LTHR, HR_MAX)

        with ui.card("zpick"):
            ui.head("🎚️ 존 기준", "고른 기준이 대시보드 강도 분포에도 함께 적용됩니다")
            ZM = zone_model_picker("zone")
            zp = ui.cols(2, 1, keep_row=True)
            days_z = zp[0].selectbox("분석 기간", [30, 90, 180, 365],
                                     index=1, format_func=lambda x: f"최근 {x}일", key="zdays")
            wk_z = zp[1 % len(zp)].selectbox("주간 추이 범위", [8, 16, 26, 52],
                                             index=1, format_func=lambda x: f"{x}주", key="zwk")
            bounds = ana.zone_bounds(ZM, cur_lthr, HR_REST, HR_MAX)
            if bounds:
                basis = (f"LTHR {cur_lthr:.0f} bpm" if ZM == "%LTHR"
                         else (f"최대 {HR_MAX:.0f} bpm" if ZM == "%HRmax"
                               else f"{HR_REST:.0f}–{HR_MAX:.0f} bpm"))
                st.markdown("<div style='height:6px'></div>" + zone_bar_html(bounds, ZM) +
                            f"<p class='rl-sub' style='margin-top:10px'>기준: {basis}</p>",
                            unsafe_allow_html=True)
            else:
                st.warning("프로필에서 최대 심박(과 LTHR)을 먼저 입력하세요.")

        zseg, seg_stats = ana.zone_segments(df_w, db.load_data("Laps"))
        zoned = ana.assign_zones(zseg, ZM, hist)
        if seg_stats.get("lap_workouts"):
            st.caption(
                f"🔁 랩이 있는 훈련 {seg_stats['lap_workouts']}건은 **랩 단위**로 존을 매깁니다"
                f"(구간 {seg_stats['lap_segments']}개). 나머지 "
                f"{seg_stats['total_workouts'] - seg_stats['lap_workouts']}건은 세션 평균 심박 기준입니다 — "
                "인터벌처럼 강약이 섞인 훈련은 랩이 있어야 정확합니다.")

        chg = ana.profile_changes(hist)
        if not chg.empty:
            with ui.card("zlthr"):
                ui.head("🧪 적용된 프로필", "훈련 시점마다 그때의 값으로 존을 매깁니다")
                ui.rows([(f"{r.Date:%Y-%m-%d} 이후",
                          f"LTHR {r.LTHR:.0f} · 최대 {r.HRMax:.0f} · 안정시 {r.HRRest:.0f}")
                         for r in chg.itertuples()])

        tbl = ana.zone_table(zoned, bounds, days_z, ZM)
        if tbl.empty:
            st.info("심박이 기록된 훈련이 아직 없습니다.")
        else:
            with ui.card("ztbl"):
                ui.head(f"📋 존별 상세 (최근 {days_z}일)")
                if ui.is_mobile():
                    ui.item_list([(f"{r['존']} — {r['비중(%)']}%",
                                   f"{r['심박(bpm)']} bpm · {r['시간']} · {r['거리(km)']}km · "
                                   f"{r['평균 페이스']}") for _, r in tbl.iterrows()])
                else:
                    st.dataframe(tbl, width="stretch", hide_index=True)

            zc = ui.cols(2, 1)
            with zc[0]:
                with ui.card("zbar"):
                    ui.head("⏱️ 존별 시간 비중")
                    _zb = alt.Chart(tbl).encode(
                        y=alt.Y("존:N", sort=None, title=None),
                        x=alt.X("비중(%):Q", title=None, axis=None,
                                scale=alt.Scale(nice=False)),
                        tooltip=[alt.Tooltip("존:N", title="존"), alt.Tooltip("시간:N", title="시간"),
                                 alt.Tooltip("비중(%):Q", title="비중(%)", format=".1f"),
                                 alt.Tooltip("거리(km):Q", title="거리(km)", format=".2f"),
                                 alt.Tooltip("평균 페이스:N", title="평균 페이스")])
                    st.altair_chart(
                        (_zb.mark_bar(height=14).encode(
                            color=alt.Color("존:N", sort=zone_order(ZM), legend=None,
                                            scale=zone_scale(ZM)))
                         + _zb.mark_text(align="left", dx=6, fontSize=11, fontWeight=600,
                                         color=C["muted"]).encode(
                             text=alt.Text("비중(%):Q", format=".1f")))
                        .properties(height=ui.chart_height(220, 200)), width="stretch")
                    inten_z = ana.intensity_distribution(zoned, ZM, days_z)
                    if inten_z:
                        p = inten_z["polarized_pct"]
                        ui.rows([("저강도 (Z1~Z2)", f"{p['low']}%"),
                                 ("중강도 (Z3~Z4)", f"{p['mid']}%"),
                                 ("고강도 (Z5)", f"{p['high']}%")])
                        st.markdown(ui.pill(inten_z["verdict"],
                                            inten_z.get("verdict_tone", "")),
                                    unsafe_allow_html=True)
                        with st.expander("❓ 이 판정은 어떻게 나오나요"):
                            st.markdown(INTENSITY_HELP)

            with zc[1 % len(zc)]:
                with ui.card("zdist"):
                    ui.head("🏃 존별 누적 거리")
                    st.altair_chart(alt.Chart(tbl).mark_arc(innerRadius=58, padAngle=0.012).encode(
                        theta=alt.Theta("거리(km):Q"),
                        color=alt.Color("존:N", sort=zone_order(ZM), title=None,
                                        scale=zone_scale(ZM)),
                        tooltip=[alt.Tooltip("존:N", title="존"),
                                 alt.Tooltip("거리(km):Q", title="거리(km)", format=".2f"),
                                 alt.Tooltip("세션:Q", title="세션", format=",d")]
                    ).properties(height=ui.chart_height(240, 220)), width="stretch")

            with ui.card("zhist"):
                ui.head("📅 주간 존 분포 추이", "막대 하나가 한 주 · 색이 존")
                zh = ana.zone_history(zoned, wk_z)
                if not zh.empty:
                    zh = zh.copy()
                    # '2026-06-01' → '06/01' (기울이지 않아야 읽힙니다)
                    zh["주라벨"] = zh["주"].astype(str).str.slice(5).str.replace(
                        "-", "/", regex=False)
                    _worder = list(dict.fromkeys(zh["주라벨"]))
                    st.altair_chart(alt.Chart(zh).mark_bar().encode(
                        x=alt.X("주라벨:O", title=None, sort=_worder,
                                axis=alt.Axis(labelAngle=0, labelOverlap="greedy")),
                        y=alt.Y("분:Q", title="분", stack="normalize",
                                axis=alt.Axis(format="%")),
                        color=alt.Color("존:N", sort=zone_order(ZM), title=None,
                                        scale=zone_scale(ZM)),
                        tooltip=[alt.Tooltip("주:O", title="주"), alt.Tooltip("존:N", title="존"),
                                 alt.Tooltip("분:Q", title="분", format=".0f")]
                    ).properties(height=ui.chart_height(280, 240)), width="stretch")
                else:
                    st.caption("데이터 없음")

            with ui.card("ztrend"):
                ui.head("📈 특정 존의 페이스 추이",
                        "같은 존 심박에서 페이스가 빨라지면 기량이 올라간 것입니다")
                zone_opts = tbl["존"].tolist()
                pick_z = st.selectbox("존 선택", zone_opts,
                                      index=min(1, len(zone_opts) - 1), key="ztrend_pick")
                tr = ana.zone_pace_trend(zoned, pick_z, 365)
                if tr.empty or len(tr) < 2:
                    st.caption("해당 존의 기록이 부족합니다.")
                else:
                    pts = alt.Chart(tr).mark_circle(size=70, opacity=.5,
                                                    color=C["primary"]).encode(
                        x=alt.X("WorkoutDate:T", title=None,
                                axis=date_axis(_span_days(tr["WorkoutDate"]))),
                        y=alt.Y("페이스(분/km):Q", scale=alt.Scale(zero=False, reverse=True)),
                        size=alt.Size("DistanceKm:Q", legend=None),
                        tooltip=[alt.Tooltip("WorkoutDate:T", title="날짜", format="%Y-%m-%d"),
                                 alt.Tooltip("페이스(분/km):Q", title="페이스", format=".2f"),
                                 alt.Tooltip("AvgHeartRate:Q", title="평균 심박", format=",d")])
                    ln = alt.Chart(tr).mark_line(color=C["accent"], strokeWidth=2.5).encode(
                        x="WorkoutDate:T",
                        y=alt.Y("추세:Q", scale=alt.Scale(zero=False, reverse=True)),
                        tooltip=[alt.Tooltip("WorkoutDate:T", title="날짜", format="%Y-%m-%d"),
                                 alt.Tooltip("추세:Q", title="추세(분/km)", format=".2f")])
                    st.altair_chart((pts + ln).properties(
                        height=ui.chart_height(280, 240)), width="stretch")

        st.caption("※ 세션 평균 심박으로 존을 판정합니다. 강약이 섞인 인터벌은 실제보다 "
                   "중간 존으로 뭉뚱그려집니다 — 존별 정확도를 높이려면 .fit 파일 연동이 필요합니다.")

    # ── 3-4 계산 통계 ───────────────────────────────────────────────────────────
    with s_stat:
        df_w = db.load_data("Workouts")
        d = ana.prepare_workouts(df_w)
        if d.empty:
            st.info("분석할 데이터가 없습니다.")
        else:
            wk = ana.weekly_summary(df_w, 20)
            st.caption("이 탭의 수치는 모두 **입력된 훈련 기록으로 직접 계산한 값**입니다. "
                       "가민이 제공한 값은 ‘⌚ 가민 추이’ 탭에 있습니다.")

            with ui.card("wk"):
                ui.head("📅 주간 훈련량", "막대=주간 거리, 선=4주 이동평균 · ⚠️는 10% 룰 초과")
                wdf = wk.reset_index(names="주")
                wdf["주"] = wdf["주"].str.slice(0, 10)
                wdf["주라벨"] = wdf["주"].str.slice(5).str.replace("-", "/", regex=False)
                _worder2 = list(wdf["주라벨"])
                # 아직 끝나지 않은 이번 주는 완료된 주와 같은 무게로 그리면
                # '거리가 폭락한 주'처럼 보입니다 — 흐리게 칠하고 툴팁에 표시합니다.
                _this_wk = (pd.Timestamp.now().normalize()
                            - pd.Timedelta(days=int(pd.Timestamp.now().dayofweek))
                            ).strftime("%Y-%m-%d")
                wdf["상태"] = np.where(wdf["주"] == _this_wk, "진행 중", "완료")
                _wx = alt.X("주라벨:O", title=None, sort=_worder2,
                            axis=alt.Axis(labelAngle=0, labelOverlap="greedy"))
                # 주 수가 적을 때 화면 폭을 다 쓰면 막대가 허공에 뜬 것처럼 보입니다.
                # 한 주 = 고정 폭으로 두고 필요한 만큼만 넓어지게 합니다.
                _wstep = 30 if ui.is_mobile() else 42
                bars = alt.Chart(wdf).mark_bar(color=C["primary"], size=20).encode(
                    x=_wx,
                    y=alt.Y("Distance:Q", title="km"),
                    opacity=alt.Opacity("상태:N", legend=None,
                                        scale=alt.Scale(domain=["완료", "진행 중"],
                                                        range=[0.92, 0.32])),
                    tooltip=[alt.Tooltip("주:O", title="주"),
                             alt.Tooltip("상태:N", title="상태"),
                             alt.Tooltip("Distance:Q", title="거리(km)", format=".1f"),
                             alt.Tooltip("Runs:Q", title="횟수", format=",d"),
                             alt.Tooltip("LongRun:Q", title="롱런(km)", format=".1f"),
                             alt.Tooltip("AvgPaceStr:N", title="평균 페이스"),
                             alt.Tooltip("WoW%:Q", title="전주대비(%)", format=".1f")])
                ma = alt.Chart(wdf).mark_line(color=C["accent"], point=True).encode(
                    x=_wx, y=alt.Y("MA4:Q", title=None),
                    tooltip=[alt.Tooltip("주:O", title="주"),
                             alt.Tooltip("MA4:Q", title="4주 평균(km)", format=".1f")])
                st.altair_chart((bars + ma).properties(
                    width=alt.Step(_wstep), height=ui.chart_height(300, 240)),
                    width="content")
                if not ui.is_mobile():
                    st.dataframe(wk[["Distance", "Runs", "LongRun", "AvgPaceStr", "WoW%", "Ramp_Flag"]]
                                 .rename(columns={"Distance": "거리(km)", "Runs": "횟수",
                                                  "LongRun": "롱런(km)", "AvgPaceStr": "평균페이스",
                                                  "WoW%": "전주대비(%)", "Ramp_Flag": "경고"}),
                                 width="stretch")

            g = ui.cols(2, 1)
            with g[0]:
                with ui.card("zone"):
                    ui.head("🎚️ 강도 분포 (최근 90일)",
                            "자세한 존 분석은 ‘🎚️ 심박존’ 탭에서")
                    _zm = st.session_state.get("zone_model", ana.preferred_zone_model())
                    _sg, _ = ana.zone_segments(df_w, db.load_data("Laps"))
                    _zd = ana.assign_zones(
                        _sg, _zm, ana.profile_history(db.load_data("Metrics"), PROFILE_NOW))
                    if inten := ana.intensity_distribution(_zd, _zm):
                        zd = pd.DataFrame({"존": list(inten["zone_pct"]),
                                           "비율": list(inten["zone_pct"].values())})
                        _base = alt.Chart(zd).encode(
                            y=alt.Y("존:N", sort=None, title=None),
                            x=alt.X("비율:Q", title=None,
                                    axis=None, scale=alt.Scale(nice=False)),
                            tooltip=[alt.Tooltip("존:N", title="존"),
                                     alt.Tooltip("비율:Q", title="비중(%)", format=".1f")])
                        st.altair_chart(
                            (_base.mark_bar(height=14).encode(
                                color=alt.Color("존:N", legend=None, sort=zone_order(_zm),
                                                scale=zone_scale(_zm)))
                             + _base.mark_text(align="left", dx=6, fontSize=11,
                                               fontWeight=600, color=C["slate"]).encode(
                                 text=alt.Text("비율:Q", format=".1f"))
                             ).properties(height=ui.chart_height(200, 180)),
                            width="stretch")
                        p = inten["polarized_pct"]
                        ui.rows([("저강도 (LT1 미만)", f"{p['low']}%"),
                                 ("중강도 (회색지대)", f"{p['mid']}%"),
                                 ("고강도 (LT2 이상)", f"{p['high']}%")])
                        st.markdown(ui.pill(inten["verdict"],
                                            inten.get("verdict_tone", "")),
                                    unsafe_allow_html=True)
                    else:
                        st.caption("심박 데이터가 있는 기록이 필요합니다.")
                    with st.expander("❓ 저·중·고강도가 뭔가요"):
                        st.markdown(
                            "- **LT1 / LT2** — 몸이 힘들어지는 두 개의 문턱입니다. "
                            "**LT1**은 ‘대화가 슬슬 끊기기 시작하는’ 지점, "
                            "**LT2**는 젖산역치(LTHR) 근처로 ‘오래 못 버티는’ 지점입니다.\n"
                            "- **저강도** = LT1 미만(Z1~Z2) · **중강도** = 그 사이 회색지대(Z3) · "
                            "**고강도** = LT2 이상(Z4~Z5)\n\n"
                            "**80/20 (양극화 훈련)** — 전체 훈련 시간의 **80% 이상을 저강도**로, "
                            "나머지를 확실한 고강도로 채우는 방식입니다. 대부분의 러너가 "
                            "‘애매하게 빠른’ 중강도에 시간을 너무 많이 쓰는데, 이러면 피로는 "
                            "쌓이면서 효과는 적습니다. 저강도 비율이 **78% 이상**이면 "
                            "초록 배지가 뜹니다.")

            with g[1 % len(g)]:
                with ui.card("effi"):
                    ef = ana.efficiency_factor(df_w)
                    ui.head("💓 러닝 이코노미 (EF)",
                            "이지런 속도÷심박 — 우상향이면 개선"
                            + (" · 주황 선은 4회 이동평균" if len(ef) >= 6
                               else " · 이지런 6회부터 추세선이 그려집니다"))
                    # 점이 몇 개 없을 때 '4회 이동평균'은 점과 따로 노는 선처럼
                    # 보일 뿐 뜻이 없습니다 → 충분히 쌓인 뒤에만 그립니다.
                    _ef_ma = len(ef) >= 6
                    if not ef.empty:
                        st.altair_chart(alt.Chart(ef).mark_circle(size=80, opacity=.85,
                                                                  color=C["primary"]).encode(
                            # 좌우 끝 점이 축에 걸려 잘리면 '선만 있고 점이 없는' 것처럼
                            # 보입니다 → 양옆에 여백(padding)을 둡니다.
                            x=alt.X("WorkoutDate:T", title=None,
                                    scale=alt.Scale(padding=18),
                                    axis=date_axis(_span_days(ef["WorkoutDate"]))),
                            y=alt.Y("EF:Q", title=None,
                                    scale=alt.Scale(zero=False, padding=10)),
                            tooltip=[alt.Tooltip("WorkoutDate:T", title="날짜", format="%Y-%m-%d"),
                                     alt.Tooltip("EF:Q", title="EF", format=".3f")])
                            .properties(height=ui.chart_height(200, 180),
                                        title=panel_title("EF (속도 ÷ 심박)"))
                            + (alt.Chart(ef).mark_line(color=C["accent"], strokeWidth=2.5)
                               .encode(x="WorkoutDate:T", y="EF_MA4:Q",
                                       tooltip=[alt.Tooltip("WorkoutDate:T", title="날짜",
                                                            format="%Y-%m-%d"),
                                                alt.Tooltip("EF_MA4:Q", title="4회 평균 EF",
                                                            format=".3f")])
                               if _ef_ma else
                               alt.Chart(ef).mark_point(opacity=0).encode(
                                   x="WorkoutDate:T", y="EF:Q")),
                            width="stretch")
                    else:
                        st.caption("이지런(Easy/Recovery/LSD) 기록이 필요합니다.")
                    with st.expander("❓ EF가 뭔가요"):
                        st.markdown(
                            "**EF (Efficiency Factor, 러닝 이코노미)** = **속도 ÷ 평균 심박**.\n\n"
                            "같은 심박으로 더 빨리 달릴 수 있게 되면 값이 커집니다. "
                            "즉 **숫자가 클수록, 선이 우상향할수록 좋아지는 중**입니다.\n\n"
                            "- 강도에 따라 크게 흔들리기 때문에 **이지런(Easy/Recovery/LSD)만** "
                            "골라서 계산합니다.\n"
                            "- 절대값은 사람마다 달라서 비교 의미가 없습니다. "
                            "**내 선의 방향**만 보세요. 주황 선은 4회 이동평균입니다.\n"
                            "- 더위·언덕·수면 부족에도 떨어지니, 한두 점이 아니라 "
                            "**몇 주 흐름**으로 판단하세요.")

            with ui.card("scatter"):
                ui.head("🫀 페이스 대비 심박",
                        "오른쪽으로 갈수록 빠른 페이스 — <b>오른쪽 아래</b>로 모일수록 "
                        "같은 심박으로 더 빨리 뛰는 것(기량 향상)")
                sc = d[(d["AvgHeartRate"] > 0) & (d["PaceSec"].notna())].copy()
                if not sc.empty:
                    sc["월"] = sc["WorkoutDate"].dt.to_period("M").astype(str)
                    sc["페이스(분/km)"] = sc["PaceSec"] / 60
                    _one_month = sc["월"].nunique() <= 1
                    st.altair_chart(alt.Chart(sc).mark_circle(size=80, opacity=.6).encode(
                        # 6.38 같은 '소수 분'은 6분 38초로 오해하기 딱 좋습니다 →
                        # 눈금을 m:ss 로 바꿔 씁니다. 오른쪽이 빠른 쪽(reverse).
                        x=alt.X("페이스(분/km):Q", title="페이스 (빠름 →)",
                                scale=alt.Scale(zero=False, reverse=True, padding=16),
                                axis=alt.Axis(
                                    tickCount=6,
                                    labelExpr=("format(floor(datum.value), 'd') + ':' + "
                                               "(round((datum.value % 1) * 60) < 10 ? '0' : '') + "
                                               "format(round((datum.value % 1) * 60), 'd')"))),
                        y=alt.Y("AvgHeartRate:Q", title="평균 심박", scale=alt.Scale(zero=False),
                            axis=alt.Axis(format=",d", tickMinStep=1)),
                        # 한 달치뿐이면 범례가 한 칸짜리라 자리만 차지합니다
                        color=(alt.value(C["primary"]) if _one_month else
                               alt.Color("월:N", title=None,
                                         scale=alt.Scale(range=ramp(sc["월"].nunique())))),
                        size=alt.Size("DistanceKm:Q", legend=None),
                        tooltip=[alt.Tooltip("WorkoutDate:T", title="날짜", format="%Y-%m-%d"),
                                 alt.Tooltip("WorkoutType:N", title="유형"),
                                 alt.Tooltip("DistanceKm:Q", title="거리(km)", format=".2f"),
                                 alt.Tooltip("AvgHeartRate:Q", title="평균 심박", format=",d")])
                        .properties(height=ui.chart_height(320, 260)), width="stretch")

            with ui.card("cal"):
                ui.head("🗓️ 훈련 달력", "진할수록 긴 거리")
                dl = ana.daily_load_series(df_w, HR_REST, HR_MAX, SEX).tail(
                    119 if ui.is_mobile() else 245).reset_index(names="Date")
                dl["요일"] = dl["Date"].dt.dayofweek
                dl["주차"] = ((dl["Date"] - dl["Date"].min()).dt.days // 7)
                dl["요일명"] = dl["요일"].map({0: "월", 1: "화", 2: "수", 3: "목",
                                            4: "금", 5: "토", 6: "일"})
                # 칸 크기를 '한 칸 = 몇 px'로 고정합니다. 화면 폭에 맞춰 늘리면
                # 데이터가 2주치뿐일 때 칸 하나가 400px짜리 막대가 돼 버립니다.
                _cell = 15 if ui.is_mobile() else 17
                st.altair_chart(alt.Chart(dl).mark_rect(cornerRadius=2, stroke=C["surface"],
                                                        strokeWidth=2).encode(
                    x=alt.X("주차:O", axis=None),
                    y=alt.Y("요일명:N", sort=["월", "화", "수", "목", "금", "토", "일"], title=None),
                    color=alt.Color("DistanceKm:Q", legend=None,
                                   scale=alt.Scale(range=[C["pale"], C["primary"]])),
                    tooltip=[alt.Tooltip("Date:T", title="날짜", format="%Y-%m-%d"),
                             alt.Tooltip("DistanceKm:Q", title="거리(km)", format=".1f")])
                    .properties(width=alt.Step(_cell), height=alt.Step(_cell)),
                    width="content")

            k = ui.cols(2, 1)
            with k[0]:
                with ui.card("bytype"):
                    ui.head("🏃 유형별 거리")
                    t = d.groupby("WorkoutType", as_index=False)["DistanceKm"].sum()
                    _tb = alt.Chart(t).encode(
                        y=alt.Y("WorkoutType:N", sort="-x", title=None),
                        x=alt.X("DistanceKm:Q", title=None, axis=None),
                        tooltip=[alt.Tooltip("WorkoutType:N", title="유형"),
                                 alt.Tooltip("DistanceKm:Q", title="거리(km)", format=".1f")])
                    st.altair_chart(
                        (_tb.mark_bar(color=C["primary"], height=16)
                         + _tb.mark_text(align="left", dx=6, fontSize=11, fontWeight=600,
                                         color=C["muted"]).encode(
                             text=alt.Text("DistanceKm:Q", format=".1f")))
                        .properties(height=ui.chart_height(220, 200)), width="stretch")
            with k[1 % len(k)]:
                with ui.card("bymonth"):
                    ui.head("📆 월별 누적 거리")
                    mm = d.copy()
                    mm["월"] = mm["WorkoutDate"].dt.to_period("M").astype(str)
                    mv = mm.groupby("월", as_index=False)["DistanceKm"].sum()
                    # 라벨은 '26/03'처럼 짧게 — 기울이지 않아야 읽기 쉽습니다
                    mv["라벨"] = mv["월"].str.slice(2).str.replace("-", "/", regex=False)
                    _mb = alt.Chart(mv).encode(
                        x=alt.X("라벨:O", title=None, sort=list(mv["라벨"]),
                                axis=alt.Axis(labelAngle=0)),
                        y=alt.Y("DistanceKm:Q", title="km"),
                        tooltip=[alt.Tooltip("월:N", title="월"),
                                 alt.Tooltip("DistanceKm:Q", title="거리(km)", format=".1f")])
                    st.altair_chart(
                        (_mb.mark_bar(color=C["primary"], size=22)
                         + _mb.mark_text(dy=-8, fontSize=10, fontWeight=600,
                                         color=C["muted"]).encode(
                             text=alt.Text("DistanceKm:Q", format=".0f")))
                        .properties(width=alt.Step(40),
                                    height=ui.chart_height(220, 200)), width="content")

    # ── 3-5 기량 예측 ───────────────────────────────────────────────────────────
    with s_pred:
        df_w = db.load_data("Workouts")
        with ui.card("vdot"):
            ui.head("🔮 VDOT 기반 기량 예측", "최근 최고 기록 또는 직접 입력한 기록으로 계산")
            src = seg("기준 기록", ["기록에서 자동 추출", "직접 입력"], "vdot_src")
            vdot = np.nan
            if src == "직접 입력":
                v = ui.cols(3, 1, keep_row=True)
                bd = v[0].number_input("거리 (km)", 0.4, 100.0, 10.0, 0.1)
                bm = v[1 % len(v)].number_input("기록 (분)", 1.0, 600.0, 50.0, 0.1)
                vdot = ana.vdot_from_performance(bd, bm)
                v[2 % len(v)].metric("VDOT", f"{vdot:.1f}" if np.isfinite(vdot) else "—")
            else:
                prs = ana.detect_prs(df_w, df_laps=db.load_data("Laps"))
                cands = []
                for name, dist in ana.PR_CATEGORIES:
                    row = prs[prs["Category"] == name]
                    if not row.empty and row.iloc[0]["TimeOrDist"] != "-":
                        t = row.iloc[0]["TimeOrDist"]
                        parts = [float(x) for x in t.split(":")]
                        sec = parts[0] * 3600 + parts[1] * 60 + parts[2] if len(parts) == 3 \
                            else parts[0] * 60 + parts[1]
                        cands.append((name, dist, sec, ana.vdot_from_performance(dist, sec / 60)))
                if cands:
                    best = max(cands, key=lambda x: x[3])
                    vdot = best[3]
                    st.caption(f"기준: **{best[0]} {ana.time_str(best[2])}** (자동 선택)")
                    st.metric("VDOT", f"{vdot:.1f}")
                else:
                    st.info("5K 이상 기록이 쌓이면 자동으로 계산됩니다. ‘직접 입력’을 써보세요.")

            if np.isfinite(vdot) and vdot > 0:
                st.divider()
                pc = ui.cols(2, 1)
                with pc[0]:
                    ui.head("🎯 훈련 페이스 존 (Daniels)")
                    tp = ana.training_paces(vdot)
                    ui.rows([(k_, ana.pace_str(v_)) for k_, v_ in tp.items()])
                with pc[1 % len(pc)]:
                    ui.head("🏁 거리별 등가 기록 예측")
                    ui.rows([(n, ana.time_str(ana.predict_time(vdot, dd)))
                             for n, dd in ana.PR_CATEGORIES])
                st.caption("예측치는 해당 거리에 맞는 훈련이 되어 있다는 전제입니다. "
                           "마라톤은 특히 롱런 축적에 따라 편차가 큽니다.")


# ═════════════════════════════════════════════════════════════════════════
# TAB 4 · 목표 — 향하는 곳
# ═════════════════════════════════════════════════════════════════════════
with tab_goal:
    labels = (["🎯 프로젝트", "🏁 대회", "🏆 기록", "👟 러닝화"] if ui.is_mobile()
              else ["🎯 프로젝트", "🏁 대회", "🏆 개인 기록", "👟 러닝화"])
    g1, g3, g4, g2 = st.tabs(labels)

    # ── 4-1 프로젝트 ────────────────────────────────────────────────────────────
    with g1:
        df_proj = db.load_data("Projects")
        with ui.card("plist"):
            ui.head("🎯 프로젝트")
            if not df_proj.empty:
                _today = pd.Timestamp.now().normalize()
                for _, p in df_proj.iterrows():
                    tone = {"ACTIVE": "ok", "PLANNED": "info", "COMPLETED": "warn"}.get(
                        str(p["Status"]).upper(), "info")
                    # 남은 날짜와 기간 진행률 — 목표일만 적어두면 감이 안 오니 함께 보여줍니다
                    _sd = pd.to_datetime(p.get("StartDate"), errors="coerce")
                    _td = pd.to_datetime(p.get("TargetDate"), errors="coerce")
                    extra = ""
                    if pd.notna(_td):
                        left = int((_td.normalize() - _today).days)
                        dday = ("D-DAY" if left == 0 else
                                (f"D-{left}" if left > 0 else f"{-left}일 지남"))
                        extra = f" · <b>{dday}</b>"
                        if pd.notna(_sd) and _td > _sd:
                            done = (_today - _sd).days / max((_td - _sd).days, 1)
                            done = min(max(done, 0.0), 1.0)
                            extra += f" · 기간 {done * 100:.0f}% 경과"
                    st.markdown(f"<div class='rl-item'><div class='t'>{p['ProjectName']} "
                                f"{ui.pill(p['Status'], tone)}</div>"
                                f"<div class='m'>목표 {p.get('GoalValue','—')} · "
                                f"{p.get('StartDate','—')} → {p.get('TargetDate','—')}"
                                f"{extra}</div></div>",
                                unsafe_allow_html=True)
            else:
                st.caption("등록된 프로젝트가 없습니다.")

        with ui.card("padd"):
            with st.expander("➕ 새 프로젝트"):
                with st.form("f_proj", clear_on_submit=True):
                    pn = st.text_input("프로젝트명", "Road to 10K Sub-50")
                    pv = st.text_input("목표", "10km 49:59")
                    pp = ui.cols(2, 2, keep_row=True)
                    ps = pp[0].date_input("시작", date.today())
                    pt = pp[1].date_input("목표일", date.today() + timedelta(days=90))
                    pstat = st.selectbox("상태", ["ACTIVE", "PLANNED", "COMPLETED"])
                    if st.form_submit_button("생성", width="stretch", type="primary"):
                        db.append_rows("Projects", pd.DataFrame([{
                            "ProjectID": new_id("PRJ"), "ProjectName": pn, "Status": pstat,
                            "GoalType": "Time Trial", "GoalValue": pv,
                            "StartDate": ps.strftime("%Y-%m-%d"),
                            "TargetDate": pt.strftime("%Y-%m-%d"), "Description": ""}]))
                        st.success("생성 완료")
                        st.rerun()

        record_editor(
            "Projects", "ProjectID",
            lambda r: f"{r['ProjectName']} · {r['Status']}",
            [("ProjectName", "text", "프로젝트명", None),
             ("Status", "select", "상태", ["ACTIVE", "PLANNED", "COMPLETED", "PAUSED"]),
             ("GoalValue", "text", "목표", None),
             ("GoalType", "text", "목표 유형", None),
             ("StartDate", "date", "시작일", None),
             ("TargetDate", "date", "목표일", None),
             ("Description", "area", "설명", None)],
            key="proj")

    # ── 4-2 대회 ──────────────────────────────────────────────────────────────
    with g3:
        df_races = db.load_data("Races")
        df_w = db.load_data("Workouts")
        daily = ana.daily_load_series(df_w, HR_REST, HR_MAX, SEX)

        with ui.card("radd"):
            with st.expander("➕ 대회 등록"):
                with st.form("f_race", clear_on_submit=True):
                    rn = st.text_input("대회명")
                    rr = ui.cols(2, 2, keep_row=True)
                    rd = rr[0].selectbox("종목", ["5km", "10km", "Half Marathon", "Full Marathon"])
                    rdate = rr[1].date_input("날짜", date.today() + timedelta(days=60))
                    rg = st.text_input("목표 기록 (예: 1:45:00)", "")
                    if st.form_submit_button("등록", width="stretch", type="primary"):
                        dmap = {"5km": 5.0, "10km": 10.0,
                                "Half Marathon": 21.0975, "Full Marathon": 42.195}
                        db.append_rows("Races", pd.DataFrame([{
                            "RaceID": new_id("RACE"), "ProjectID": "",
                            "RaceDate": rdate.strftime("%Y-%m-%d"), "RaceName": rn,
                            "Distance": rd, "DistanceKm": dmap[rd], "GoalTime": rg,
                            "ActualTime": "", "ShoeID": "", "ResultStatus": "PLANNED",
                            "Notes": ""}]))
                        st.success("등록 완료")
                        st.rerun()

        if df_races.empty:
            st.caption("등록된 대회가 없습니다.")
        else:
            prs = ana.detect_prs(df_w, df_laps=db.load_data("Laps"))
            vdot = np.nan
            for name, dist in ana.PR_CATEGORIES:
                row = prs[prs["Category"] == name]
                if not row.empty and row.iloc[0]["TimeOrDist"] != "-":
                    p = [float(x) for x in row.iloc[0]["TimeOrDist"].split(":")]
                    sec = p[0] * 3600 + p[1] * 60 + p[2] if len(p) == 3 else p[0] * 60 + p[1]
                    v = ana.vdot_from_performance(dist, sec / 60)
                    vdot = v if not np.isfinite(vdot) else max(vdot, v)

            for i, (_, r) in enumerate(df_races.iterrows()):
                with ui.card(f"race{i}"):
                    try:
                        rdt = pd.to_datetime(r["RaceDate"])
                        dist_km = fnum(r.get("DistanceKm"), 10.0) or 10.0
                        goal = r.get("GoalTime", "")
                        gsec = None
                        if goal and ":" in str(goal):
                            gp = [float(x) for x in str(goal).split(":")]
                            gsec = gp[0] * 3600 + gp[1] * 60 + (gp[2] if len(gp) == 3 else 0)
                        plan = ana.race_plan(vdot, dist_km, gsec, rdt, daily)
                    except Exception:
                        plan = {}
                    dday = plan.get("dday")
                    dtag = dday_tag(dday)
                    dtone = "bad" if (dday is not None and dday <= 14) else "warn"
                    st.markdown(f"<div class='t' style='font-weight:700'>🏁 {r['RaceName']} "
                                f"{ui.pill(dtag, dtone)}</div>"
                                f"<div class='m'>{r['RaceDate']} · {r['Distance']}</div>",
                                unsafe_allow_html=True)
                    if plan:
                        ui.rows([("현재 기량 예상 기록", plan.get("predicted_str", "—")),
                                 ("목표", str(r.get("GoalTime") or "—")),
                                 ("갭", plan.get("gap_str", "—")),
                                 ("현재 단계", plan.get("phase", "—")),
                                 ("테이퍼 시작", plan.get("taper_start", "—"))])

        record_editor(
            "Races", "RaceID",
            lambda r: f"{r['RaceDate']} · {r['RaceName']} ({r.get('Distance','')})",
            [("RaceName", "text", "대회명", None),
             ("Distance", "select", "종목", list(RACE_DIST_KM)),
             ("RaceDate", "date", "날짜", None),
             ("GoalTime", "text", "목표 기록", None),
             ("ActualTime", "text", "실제 기록", None),
             ("ResultStatus", "select", "결과", ["PLANNED", "COMPLETED", "DNF", "DNS"]),
             ("Notes", "area", "메모", None)],
            key="race",
            derive=lambda v: {"DistanceKm": RACE_DIST_KM.get(v.get("Distance"), "")})

    # ── 4-3 개인 기록 ───────────────────────────────────────────────────────────
    with g4:
        df_w = db.load_data("Workouts")
        with ui.card("pr"):
            ui.head("🏆 개인 최고 기록",
                    "훈련 전체 기록 + 훈련 안의 가장 빠른 구간 중 좋은 쪽")
            prs = ana.detect_prs(df_w, df_laps=db.load_data("Laps"))
            if ui.is_mobile():
                ui.item_list([(f"{r.Category} — {r.TimeOrDist}",
                               f"{r.AchievedDate} · {r.PaceStr} · {r.Workout} · {r.Source}"
                               + (f" · {r.Note}" if r.Note else ""))
                              for r in prs.itertuples()])
            else:
                # '출처'와 '구간'은 늘 짝으로 읽는 값이라 한 칸으로 합쳤습니다.
                # 나눠두면 마지막 열이 화면 밖으로 잘렸습니다.
                _p = prs.copy()
                _src = _p["Source"].astype(str)
                _note = _p["Note"].astype(str).fillna("")
                # '구간 6랩'과 '랩 1~6'은 같은 말이라 하나로 줄입니다 — 길면 열이 잘립니다
                _p["근거"] = np.where(
                    _src.str.startswith("구간"),
                    "🔁 " + np.where(_note != "", _note, _src),
                    _src)
                st.dataframe(_p.rename(columns={
                    "Category": "종목", "TimeOrDist": "기록", "AchievedDate": "달성일",
                    "PaceStr": "페이스", "Workout": "어느 훈련에서"})[
                    ["종목", "기록", "달성일", "페이스", "어느 훈련에서", "근거"]],
                    width="stretch", hide_index=True)
            with st.expander("❓ ‘출처’가 뭔가요"):
                st.markdown(
                    "1km 기록을 세우려고 1km만 따로 뛸 필요는 없습니다. "
                    "저장된 **랩을 이어 붙여** 그 훈련 안에서 가장 빠른 연속 구간을 찾아 "
                    "기록으로 인정합니다.\n\n"
                    "- **훈련 전체** — 훈련 거리가 목표와 ±3% 안에 드는 기록\n"
                    "- **구간 N랩** — 훈련 안의 가장 빠른 연속 N개 랩. "
                    "**어느 훈련에서**·**달성일**·**구간**(예: `랩 3~8`)을 함께 적어두니 "
                    "훈련 이력에서 그 날짜를 눌러 원본 랩을 바로 확인할 수 있습니다\n"
                    "- 구간 거리가 목표와 딱 맞지 않으면 시간을 비례 환산하고 "
                    "**비고**에 실제 구간 거리를 적습니다 (예: 5.2km 구간 → 5km 환산). "
                    "목표의 1.25배를 넘는 구간은 오차가 커서 쓰지 않습니다.\n\n"
                    "랩이 저장된 훈련에서만 잡히니, ‘📥 CSV 가져오기’로 **활동 상세 CSV**를 "
                    "넣을수록 정확해집니다.")
            _seq = []
            for _n, _d in ana.PR_CATEGORIES:
                _r = prs[prs["Category"] == _n]
                if not _r.empty and _r.iloc[0]["TimeOrDist"] != "-":
                    _s = ana.parse_time_str(_r.iloc[0]["TimeOrDist"])
                    if np.isfinite(_s):
                        _seq.append((_n, _s / _d))
            _inv = [(a, b) for (a, pa), (b, pb) in zip(_seq, _seq[1:]) if pa > pb + 1]
            if _inv:
                st.info("ℹ️ **" + _inv[0][0] + "** 기록이 **" + _inv[0][1] +
                        "** 보다 느리게 보입니다. 계산이 틀린 게 아니라 "
                        "**랩이 저장된 훈련이 아직 적어서**입니다 — 짧은 거리는 랩 구간에서만 "
                        "찾는데, 그 훈련들이 마침 이지런이면 이렇게 나옵니다. "
                        "‘📥 CSV 가져오기’로 활동 상세 CSV를 넣을수록 정확해집니다.")
            st.caption("※ 최대노력이 아닌 훈련도 포함될 수 있습니다. 레이스 기록은 ‘🏁 대회’ 탭에서 따로 관리하세요.")

    # ── 4-4 러닝화 ─────────────────────────────────────────────────────────────
    with g2:
        df_shoes = db.load_data("Shoes")
        df_w = db.load_data("Workouts")
        d = ana.prepare_workouts(df_w)

        with ui.card("sadd"):
            with st.expander("➕ 러닝화 등록"):
                with st.form("f_shoe", clear_on_submit=True):
                    sn = st.text_input("이름", "Nike Zoom Fly 6")
                    sbrand = st.text_input("브랜드", "Nike")
                    scat = st.multiselect("용도 (복수 선택)", SHOE_CATEGORIES,
                                          default=["데일리 트레이너"],
                                          help="한 켤레가 여러 역할을 겸하면 모두 고르세요")
                    sd_ = ui.cols(3, 2, keep_row=True)
                    sinit = grid_at(sd_, 0, 3).number_input(
                        "기존 누적 (km)", 0.0, 2000.0, 0.0, 1.0,
                        help="앱을 쓰기 전까지 이미 신은 거리.")
                    sasof = grid_at(sd_, 1, 3).date_input(
                        "기존 누적 기준일", date.today(), key="shoe_asof",
                        help="위 '기존 누적'이 **언제까지**를 더한 값인지. "
                             "이 날짜 다음 날부터의 훈련만 누적에 더해지므로, "
                             "나중에 예전 기록을 넣어도 거리가 두 번 세어지지 않습니다.")
                    starg = grid_at(sd_, 2, 3).number_input(
                        "목표 수명 (km)", 100.0, 2000.0, 600.0, 50.0)
                    if st.form_submit_button("등록", width="stretch", type="primary"):
                        db.append_rows("Shoes", pd.DataFrame([{
                            "ShoeID": new_id("SHOE"), "ShoeName": sn, "Brand": sbrand,
                            "PurchaseDate": date.today().strftime("%Y-%m-%d"),
                            "InitialDistanceKm": sinit, "TargetDistanceKm": starg,
                            "Status": "ACTIVE", "Category": ", ".join(scat), "Notes": "",
                            "InitialAsOf": sasof.strftime("%Y-%m-%d")}]))
                        st.success("등록 완료")
                        st.rerun()

        if df_shoes.empty:
            st.caption("등록된 러닝화가 없습니다.")
        else:
            sc = ui.cols(2, 1)
            for i, (_, s) in enumerate(df_shoes.iterrows()):
                with sc[i % len(sc)]:
                    with ui.card(f"shoe{i}"):
                        used = ana.shoe_mileage(s, d)
                        targ = fnum(s.get("TargetDistanceKm"), 600.0) or 600.0
                        pct = min(100.0, used / targ * 100)
                        tone = "bad" if pct >= 100 else ("warn" if pct >= 85 else "")
                        cats = cat_list(s.get("Category"))
                        badges = "".join(ui.pill(c, "info") for c in cats)
                        st.markdown(f"<div class='t' style='font-weight:700'>👟 {s['ShoeName']}</div>"
                                    f"<div class='m'>{s.get('Brand','')} · {s.get('Status','')}</div>"
                                    f"<div style='display:flex;flex-wrap:wrap;gap:5px;margin-top:7px'>"
                                    f"{badges}</div>", unsafe_allow_html=True)
                        ui.bar(pct, tone)
                        used_w = d[d["ShoeID"].astype(str) == str(s["ShoeID"])] \
                            if "ShoeID" in d.columns else pd.DataFrame()
                        if not used_w.empty:
                            km = float(used_w["DistanceKm"].sum())
                            mins = float(used_w["DurationMinutes"].sum())
                            top = used_w["WorkoutType"].mode()
                            st.markdown(
                                f"<div class='m'>{len(used_w)}회 · 평균 "
                                f"{ana.pace_str(mins * 60 / km) if km > 0 else '-'} · 주 용도 "
                                f"{top.iloc[0] if not top.empty else '-'}</div>",
                                unsafe_allow_html=True)
                        st.markdown(f"<div class='rl-row'><span class='k'>누적</span>"
                                    f"<span class='v'>{used:.0f} / {targ:.0f} km "
                                    f"({pct:.0f}%)</span></div>", unsafe_allow_html=True)
                        if pct >= 85:
                            st.markdown(ui.pill("교체 시점 도달" if pct >= 100 else "교체 준비",
                                                tone or "warn"), unsafe_allow_html=True)

        record_editor(
            "Shoes", "ShoeID",
            lambda r: f"{r['ShoeName']} ({r.get('Brand','')}) · {r.get('Status','')}",
            [("ShoeName", "text", "이름", None),
             ("Brand", "text", "브랜드", None),
             ("Category", "multi", "용도 (복수 선택)", SHOE_CATEGORIES),
             ("Status", "select", "상태", ["ACTIVE", "NEW", "RETIRED"]),
             ("InitialDistanceKm", "num", "기존 누적 (km)", None),
             ("InitialAsOf", "date", "기존 누적 기준일", None),
             ("TargetDistanceKm", "num", "목표 수명 (km)", None),
             ("PurchaseDate", "date", "구입일", None),
             ("Notes", "area", "메모", None)],
            key="shoe")


# ═════════════════════════════════════════════════════════════════════════
# TAB 5 · 설정 — 기준값과 뒷정리
# ═════════════════════════════════════════════════════════════════════════
with tab_set:
    labels = (["👤 프로필", "🤖 코치 노트", "💾 백업"] if ui.is_mobile()
              else ["👤 프로필 & 기준값", "🤖 코치 노트", "💾 백업 & 도구"])
    a1, a4, a5 = st.tabs(labels)

    # ── 5-1 프로필 & 기준값 ───────────────────────────────────────────────────────
    with a1:
        with ui.card("prof"):
            ui.head("👤 프로필 & 기준값",
                    "심박·체중은 <b>모든 분석의 기준</b>입니다 — 바꾸면 그 시점부터 "
                    "심박존·훈련 부하가 다시 계산됩니다")
            st.caption("아래 칸에는 **현재 값**이 채워져 있습니다. 고쳐서 저장하면 그게 수정이고, "
                       "값이 실제로 달라졌을 때만 **적용일** 날짜로 이력이 한 줄 쌓입니다. "
                       "쌓인 이력은 이 아래 **기준값 이력 수정 / 삭제**에서 고치거나 지웁니다.")
            with st.form("f_ath"):
                eff = st.date_input("적용일", date.today(), key="prof_eff",
                                    help="이 날짜부터 아래 값이 적용됩니다. "
                                         "이전 훈련은 그 전 값으로 계산됩니다.")
                p1 = ui.cols(4, 1, keep_row=True)
                a_name = p1[0].text_input("이름", str(ATH.get("Name", "")))
                a_sex = p1[1 % len(p1)].selectbox("성별", ["M", "F"],
                                                  index=0 if SEX.upper().startswith("M") else 1)
                a_h = p1[2 % len(p1)].number_input("키 (cm)", 100, 230, int(fnum(ATH.get("HeightCm"), 175)))
                _by0 = ana.age_from_birth(ATH.get("BirthDate"))
                a_by = p1[3 % len(p1)].number_input(
                    "출생연도", 1930, date.today().year - 10,
                    int(date.today().year - _by0) if np.isfinite(_by0) else 1985,
                    help="Endurance Score 등급은 나이대별 기준이 달라서 필요합니다.")
                p2 = ui.cols(3, 1, keep_row=True)
                a_rest = p2[0].number_input("안정시 심박", 30, 100, int(HR_REST))
                a_max = p2[1 % len(p2)].number_input("최대 심박", 120, 230, int(HR_MAX))
                a_lt = p2[2 % len(p2)].number_input("젖산역치 심박 (LTHR)", 0, 230,
                                                    int(LTHR or round(HR_REST + .85 * (HR_MAX - HR_REST))))
                p3 = ui.cols(3, 1, keep_row=True)
                a_w = p3[0].number_input("현재 체중 (kg)", 30.0, 200.0,
                                         fnum(ATH.get("CurrentWeightKg"), 70.0), 0.1)
                a_sw = p3[1 % len(p3)].number_input("시작 체중 (kg)", 30.0, 250.0,
                                                    fnum(ATH.get("StartWeightKg"), 70.0), 0.1)
                a_bf = p3[2 % len(p3)].number_input(
                    "체지방률 (%)", 0.0, 60.0, fnum(LAST_BODYFAT, 0.0), 0.1,
                    help="모르면 0으로 두세요. 0이면 기록하지 않습니다.")
                if st.form_submit_button("저장", width="stretch", type="primary"):
                    db.save_athlete({"Name": a_name, "Sex": a_sex, "HeightCm": a_h,
                                     "BirthDate": f"{int(a_by)}-01-01",
                                     "HRRest": a_rest, "HRMax": a_max, "LTHR": a_lt,
                                     "CurrentWeightKg": a_w, "StartWeightKg": a_sw})
                    # 수치가 바뀐 경우에만 변경 이력 한 줄 추가
                    prev = {"HRRest": HR_REST, "HRMax": HR_MAX,
                            "LTHR": ana.resolve_lthr(LTHR, HR_MAX),
                            "WeightKg": fnum(ATH.get("CurrentWeightKg"), 0),
                            "BodyFatPct": fnum(LAST_BODYFAT, 0)}
                    now = {"HRRest": a_rest, "HRMax": a_max, "LTHR": a_lt,
                           "WeightKg": a_w, "BodyFatPct": a_bf}
                    if any(abs(fnum(now[k]) - fnum(prev.get(k))) > 0.001 for k in now):
                        db.append_rows("Metrics", pd.DataFrame([{
                            "MetricID": new_id("MET"),
                            "MetricDate": eff.strftime("%Y-%m-%d"),
                            "HRRest": a_rest, "HRMax": a_max, "LTHR": a_lt,
                            "WeightKg": a_w, "BodyFatPct": a_bf or "",
                            "Notes": PROFILE_ROW_NOTE}]))
                        st.success(f"저장 완료 — {eff:%Y-%m-%d}부터 적용되는 변경 이력을 남겼습니다")
                    else:
                        st.success("저장 완료")
                    st.rerun()
        df_metrics_p = db.load_data("Metrics")
        hist_p = ana.profile_history(df_metrics_p, PROFILE_NOW)
        cur_lthr = float(hist_p["LTHR"].iloc[-1]) if not hist_p.empty else ana.resolve_lthr(LTHR, HR_MAX)

        with ui.card("watchzone"):
            ui.head("⌚ 시계 러닝 존 (스포츠 심박존)",
                    "가민은 활동별로 심박존을 따로 둘 수 있습니다 — 러닝 존을 여기에 옮기면 "
                    "앱 판정이 시계와 똑같아집니다")
            _cur_pct = ana.parse_zone_pcts(ATH.get("RunZonePct")) or [67, 78, 88, 93, 98, 113]
            _way = seg("입력 방식", ["%LTHR 로 입력", "bpm 으로 입력"], "wz_way",
                       collapsed=False,
                       help="시계 설정 화면에 보이는 그대로 넣으면 됩니다. "
                            "bpm으로 넣어도 현재 LTHR 기준 %로 바꿔 저장하므로, "
                            "나중에 LTHR이 바뀌면 존도 같이 움직입니다.")
            _labels = ["Z1 시작", "Z2 시작", "Z3 시작", "Z4 시작", "Z5 시작", "Z5 끝"]
            with st.form("f_watchzone"):
                if _way.startswith("%"):
                    wcs = ui.cols(6, 3, keep_row=True)
                    vals_in = [grid_at(wcs, i, 6).number_input(
                        _labels[i], 30.0, 160.0, float(_cur_pct[i]), 0.5,
                        format="%g", key=f"wz_p{i}") for i in range(6)]
                    new_pct = list(vals_in)
                else:
                    _bpm_def = [round(cur_lthr * p / 100) for p in _cur_pct]
                    wcs = ui.cols(6, 3, keep_row=True)
                    vals_in = [grid_at(wcs, i, 6).number_input(
                        _labels[i], 50, 230, int(_bpm_def[i]), 1, key=f"wz_b{i}")
                        for i in range(6)]
                    new_pct = ana.bpm_to_pct(vals_in, cur_lthr)
                    st.caption(f"현재 LTHR **{cur_lthr:.0f} bpm** 기준으로 %로 바꿔 저장합니다.")
                wb = ui.cols(2, 1, keep_row=True)
                if wb[0].form_submit_button("저장", width="stretch", type="primary"):
                    if ana.parse_zone_pcts(new_pct):
                        db.save_athlete({"RunZonePct": ",".join(
                            f"{v:g}" for v in new_pct)})
                        st.success("저장 완료 — 존 기준 목록에 ‘⌚ 시계 러닝 존’이 추가됩니다")
                        st.rerun()
                    else:
                        st.error("값이 순서대로 커지도록 넣어주세요 (Z1 시작 < Z2 시작 < … < Z5 끝).")
                if wb[1 % len(wb)].form_submit_button("지우기", width="stretch"):
                    db.save_athlete({"RunZonePct": ""})
                    st.session_state.pop("zone_model", None)
                    st.warning("시계 존을 지웠습니다 — 기본 %LTHR 기준으로 돌아갑니다.")
                    st.rerun()
            if ana.has_watch_zones():
                _wb = ana.zone_bounds(ana.WATCH_MODEL, cur_lthr, HR_REST, HR_MAX)
                ui.rows([(n, f"{lo:.0f}–{hi:.0f} bpm") for n, lo, hi in _wb])
                st.caption("시계 설정 경로: **설정 → 사용자 프로필 → 심박수 및 파워 존 → "
                           "심박수 → 스포츠 심박수 → 러닝**")
            else:
                st.caption("아직 등록된 시계 러닝 존이 없습니다. 시계에서 "
                           "**설정 → 사용자 프로필 → 심박수 및 파워 존 → 심박수 → "
                           "스포츠 심박수 → 러닝**을 열어 보이는 값을 그대로 넣으세요.")

        with ui.card("zonetbl"):
            ui.head("🎚️ 심박존",
                    f"LTHR {cur_lthr:.0f} bpm · 안정시 {HR_REST:.0f} · 최대 {HR_MAX:.0f} bpm")
            lthr_bounds = ana.zone_bounds("%LTHR", cur_lthr, HR_REST, HR_MAX)
            if lthr_bounds:
                st.markdown(zone_bar_html(lthr_bounds, "%LTHR"), unsafe_allow_html=True)
                st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
                if ui.is_mobile():
                    ui.rows([(f"{n}", f"{lo:.0f}–{hi:.0f} bpm") for n, lo, hi in lthr_bounds])
                    with st.expander("다른 기준과 비교"):
                        st.markdown(zone_compare_html(cur_lthr, HR_REST, HR_MAX),
                                    unsafe_allow_html=True)
                else:
                    st.markdown(zone_compare_html(cur_lthr, HR_REST, HR_MAX),
                                unsafe_allow_html=True)
                st.caption("막대와 굵은 숫자는 시계와 같은 **%LTHR** 기준입니다. "
                           "앱 전체에 적용할 기준은 ‘📊 분석 → 🎚️ 심박존’ 탭에서 바꿉니다.")
            else:
                st.caption("최대 심박과 LTHR을 먼저 입력하세요.")

        with ui.card("profhist"):
            ui.head("🗓️ 프로필 변경 이력",
                    "체중·심박·LTHR이 바뀐 시점 — 과거 훈련은 그때 값으로 계산됩니다")
            chg_p = ana.profile_changes(hist_p)
            if chg_p.empty:
                st.caption("아직 변경 이력이 없습니다. 위에서 **적용일**과 함께 저장하면 "
                           "이 목록에 쌓이고, 심박존·훈련 부하가 시점별로 다시 계산됩니다.")
            else:
                if ui.is_mobile():
                    ui.item_list([
                        (f"{r.Date:%Y-%m-%d}",
                         f"LTHR {r.LTHR:.0f} · 최대 {r.HRMax:.0f} · 안정시 {r.HRRest:.0f}"
                         + (f" · {r.WeightKg:.1f}kg" if pd.notna(r.WeightKg) else ""))
                        for r in chg_p.iloc[::-1].itertuples()])
                else:
                    disp = chg_p.iloc[::-1].copy()
                    disp["적용일"] = disp["Date"].dt.strftime("%Y-%m-%d")
                    disp = disp.rename(columns={"LTHR": "LTHR", "HRRest": "안정시",
                                                "HRMax": "최대", "WeightKg": "체중(kg)",
                                                "BodyFatPct": "체지방(%)"})
                    st.dataframe(disp[["적용일", "LTHR", "안정시", "최대", "체중(kg)", "체지방(%)"]],
                                 width="stretch", hide_index=True)
                st.caption("잘못 입력한 이력은 아래 **✏️ 기준값 이력 수정 / 삭제**에서 고칩니다.")

        record_editor(
            "Metrics", "MetricID",
            lambda r: (f"{str(r['MetricDate'])[:10]} · LTHR {vtxt(r.get('LTHR'), '{:.0f}')}"
                       f" · 체중 {vtxt(r.get('WeightKg'), '{:.1f}')}kg"),
            [("MetricDate", "date", "적용일", None),
             ("LTHR", "numopt", "LTHR", None),
             ("HRRest", "numopt", "안정시 심박", None),
             ("HRMax", "numopt", "최대 심박", None),
             ("WeightKg", "numopt", "체중 (kg)", None),
             ("BodyFatPct", "numopt", "체지방률 (%)", None),
             ("Notes", "area", "메모", None)],
            key="profmet", title="✏️ 기준값 이력 수정 / 삭제",
            row_filter=only_profile_rows, default_open=True,
            note="위 표의 각 줄을 여기서 고치거나 지웁니다. "
                 "예전에 ‘📈 가민 측정’ 탭에서 LTHR·체중을 함께 입력한 줄도 "
                 "이력에 쓰이므로 여기 같이 나옵니다 — 그 줄을 삭제하면 같은 줄의 "
                 "가민 값(VO₂max 등)도 함께 사라집니다.",
            empty_msg="아직 기준값 이력이 없습니다. 위에서 적용일과 함께 저장하면 생깁니다.")

        if not chg_p.empty:
            pc = ui.cols(2, 1)
            prof_charts = [("WeightKg", "체중 (kg)", C["primary"], ".1f", 0.1),
                           ("LTHR", "LTHR (bpm)", C["accent"], ",d", 1)]
            for i, (col, title, color, fmt, step) in enumerate(prof_charts):
                sub = chg_p[["Date", col]].dropna()
                sub = sub[pd.to_numeric(sub[col], errors="coerce") > 0]
                with pc[i % len(pc)]:
                    with ui.card(f"pf{i}"):
                        ui.head(title)
                        if not sub.empty:
                            st.altair_chart(alt.Chart(sub).mark_line(
                                point=True, strokeWidth=2.5, color=color).encode(
                                x=alt.X("Date:T", title=None, axis=date_axis(_span_days(sub["Date"]))),
                                y=alt.Y(f"{col}:Q", title=None,
                                        scale=alt.Scale(zero=False),
                                        axis=alt.Axis(format=fmt, tickMinStep=step)),
                                tooltip=[alt.Tooltip("Date:T", title="적용일"),
                                         alt.Tooltip(f"{col}:Q", title=title, format=fmt)]
                            ).properties(height=ui.chart_height(190, 170)), width="stretch")
                        else:
                            st.caption("데이터 없음")

    # ── 5-2 코치 노트 ───────────────────────────────────────────────────────────
    with a4:
        df_notes = db.load_data("CoachNotes")
        with ui.card("note"):
            ui.head("🤖 코치 노트")
            with st.expander("➕ 노트 작성"):
                with st.form("f_note", clear_on_submit=True):
                    cat = st.selectbox("분류", ["Weekly", "Monthly", "Race", "Injury", "General"])
                    txt = st.text_area("내용", height=130)
                    if st.form_submit_button("저장", width="stretch", type="primary"):
                        db.append_rows("CoachNotes", pd.DataFrame([{
                            "NoteID": new_id("NOTE"), "ProjectID": "",
                            "NoteDate": date.today().strftime("%Y-%m-%d"),
                            "Category": cat, "NoteText": txt}]))
                        st.success("저장 완료")
                        st.rerun()
            if not df_notes.empty:
                for _, n in df_notes.iloc[::-1].head(20).iterrows():
                    st.markdown(f"<div class='rl-item'><div class='t'>{n['NoteDate']} "
                                f"{ui.pill(n['Category'])}</div>"
                                f"<div class='m' style='white-space:pre-wrap'>{n['NoteText']}</div></div>",
                                unsafe_allow_html=True)
            else:
                st.caption("작성된 노트가 없습니다.")

        record_editor(
            "CoachNotes", "NoteID",
            lambda r: f"{r['NoteDate']} · {r['Category']} · {str(r['NoteText'])[:24]}",
            [("NoteDate", "date", "날짜", None),
             ("Category", "select", "분류",
              ["Weekly", "Monthly", "Race", "Injury", "General"]),
             ("NoteText", "area", "내용", None)],
            key="note")

    # ── 5-3 백업 & 도구 ─────────────────────────────────────────────────────────
    with a5:
        with ui.card("autologin"):
            ui.head("🔗 자동 로그인 링크", "이 링크를 북마크하면 비밀번호를 다시 묻지 않습니다")
            ak = auto_login_key()
            if not ak:
                st.info("Secrets에 `AUTO_LOGIN_KEY = \"아무_긴_문자열\"` 한 줄을 추가하면 "
                        "여기에 북마크용 링크가 만들어집니다.")
            else:
                host = ""
                try:
                    host = st.context.headers.get("Host", "") or ""
                except Exception:
                    pass
                base = f"https://{host}" if host and "localhost" not in host else \
                    st.text_input("앱 주소", "https://내앱이름.streamlit.app",
                                  help="주소창의 앱 URL을 붙여넣으세요")
                link = f"{base.rstrip('/')}/?k={ak}"
                st.code(link, language=None)
                st.caption("⚠️ 이 링크를 아는 사람은 누구나 비밀번호 없이 들어옵니다. "
                           "메신저·메일로 보내지 마시고, 새어나갔다 싶으면 Secrets의 "
                           "`AUTO_LOGIN_KEY` 값만 바꾸면 즉시 무효가 됩니다.")

        with ui.card("repair"):
            ui.head("🩹 데이터 정합성 점검",
                    "컬럼이 늘어나면서 예전 기록의 값이 옆 칸으로 밀렸는지 확인합니다")
            if st.button("점검 실행", width="stretch", key="diag_btn"):
                st.session_state["_diag"] = {
                    n: db.diagnose(n) for n in
                    ["Workouts", "Metrics", "DailyStatus", "Laps"]}
            diag = st.session_state.get("_diag")
            if diag:
                st.dataframe(pd.DataFrame([{
                    "시트": n, "행": d.get("rows", 0),
                    "의심 행": d.get("misaligned", 0),
                    "헤더": "정상" if d.get("header_ok") else "불일치",
                    "상태": "✅ 정상" if d.get("ok") else "⚠️ 확인 필요",
                } for n, d in diag.items()]), width="stretch", hide_index=True)

                bad = {n: d for n, d in diag.items() if d.get("suspects")}
                if not bad:
                    st.success("밀린 기록이 발견되지 않았습니다.")
                else:
                    tgt = st.selectbox("교정할 시트", list(bad), key="rep_sheet")
                    lens = list(bad[tgt]["suspects"])
                    ln = st.selectbox(
                        "예전 컬럼 수", lens, key="rep_len",
                        format_func=lambda v: f"{v}열 기준으로 저장된 것으로 보임 "
                                              f"({bad[tgt]['suspects'][v]}행)")
                    try:
                        before, after = db.repair_preview(tgt, ln)
                        st.markdown("**지금 해석 (잘못됨)**")
                        st.dataframe(before, width="stretch", hide_index=True)
                        st.markdown("**교정 후 해석**")
                        st.dataframe(after, width="stretch", hide_index=True)
                    except Exception as e:
                        st.warning(f"미리보기를 만들지 못했습니다: {e}")
                    st.caption("값 자체는 바꾸지 않고 ‘어느 컬럼인지’만 바로잡습니다. "
                               "적용 전에 아래 **백업**을 한 번 내려받아 두세요.")
                    okw = st.text_input("확인을 위해 `REPAIR` 입력", key="rep_txt")
                    if st.button("교정 적용", width="stretch", type="primary",
                                 disabled=(okw != "REPAIR"), key="rep_btn"):
                        r = db.repair(tgt, ln)
                        st.session_state.pop("_diag", None)
                        st.success(f"{tgt} {r['rows']}행 교정 완료")
                        st.rerun()

        with ui.card("backup"):
            ui.head("💾 백업", f"현재 저장소: {db.backend_name()}")
            st.download_button("전체 데이터 엑셀로 내려받기", db.export_excel_bytes(),
                               file_name=f"RunningLifeOS_Backup_{date.today():%Y%m%d}.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               width="stretch")
        with ui.card("reset"):
            ui.head("🚨 초기화")
            st.warning("모든 훈련 기록이 삭제됩니다. 되돌릴 수 없습니다.")
            confirm = st.text_input("확인을 위해 `RESET` 을 입력하세요", key="reset_txt")
            if st.button("데이터베이스 초기화", width="stretch",
                         disabled=(confirm != "RESET")):
                db.reset_db()
                st.success("초기화 완료")
                st.rerun()
