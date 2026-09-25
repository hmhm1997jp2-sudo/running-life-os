"""
Running Life OS — 개인 러닝 관리·분석 시스템
============================================
필요 파일 : app.py / ui.py / db.py / analytics.py / requirements.txt
저장소    : Google Sheets (st.secrets 설정 시) 또는 로컬 엑셀 (자동 대체)
"""

import hashlib
import math
import os
import zoneinfo
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
    "analytics.py": (ana, ["BELOW_Z1", "FORM_METRICS", "LAP_ROLES", "LAP_SUMMARY_FMT",
                           "PRIMARY_BENEFIT", "PR_CATEGORIES",
                           "RACE_PRED_COLS", "STATUS_GROUP", "TRAINING_STATUS",
                           "TRAINING_STATUS_KR", "TREND_DEFAULT", "TREND_LABEL",
                           "HRV_TONE_ORDER", "WATCH_MODEL", "ZONE_MODELS",
                           "BODY_LABEL", "BODY_META", "BODY_SOURCES",
                           "INJURY_SITES", "INJURY_SIDES", "INJURY_STATUS",
                           "INJURY_CAUSES", "prepare_injury", "active_injuries",
                           "injury_alerts", "injury_spans", "injury_label",
                           "severity_meta",
                           "add_intensity_rolling", "watch_intensity", "parse_zone_sec", "fit_match", "fit_plan", "fit_read", "fit_rescale", "fit_type_hint",
                           "FIT_BENEFIT", "decoupling_verdict",
                           "age_from_birth", "assign_zones", "body_available",
                           "body_summary", "bpm_to_pct", "build_alerts",
                           "classify_laps", "daily_load_series", "decoupling",
                           "decoupling_verdict", "detect_prs", "effective_load_ratio",
                           "effective_vo2max", "efficiency_factor", "endurance_meta",
                           "fix_race_pred", "form_summary", "form_trend",
                           "WORKOUT_TREND_METRICS", "WORKOUT_TREND_META",
                           "WORKOUT_TREND_LABEL", "WORKOUT_TREND_DEFAULT",
                           "workout_trend", "workout_trend_available",
                           "monotony_meta", "strain_meta",
                           "garmin_alerts", "garmin_race_predictions",
                           "garmin_vs_computed", "has_watch_zones", "hill_meta",
                           "intensity_distribution", "interval_shape", "lap_role_summary",
                           "lap_wmean",
                           "latest_garmin", "load_focus", "merge_daily_rows", "load_ratio_meta", "load_summary",
                           "pace_str", "parse_time_str", "parse_zone_pcts", "predict_time",
                           "last_monday", "prepare_body",
                           "preferred_zone_model", "prepare_workouts", "profile_changes",
                           "profile_history", "race_plan", "race_pred_summary",
                           "race_pred_trend", "readiness_factors", "readiness_meta",
                           "garmin_vdot", "vdot_table", "vdot_pick",
                           "recovery_meta", "recovery_remaining", "resolve_lthr",
                           "set_watch_zones", "shoe_mileage", "stage_to_role", "status_meta",
                           "time_str", "training_paces", "trend_available", "trend_panels",
                           "vdot_from_performance",
                           "weekly_summary", "zone_bounds", "zone_history", "zone_pace_trend",
                           "zone_segments", "zone_table"]),
    "ui.py":        (ui, ["bar", "boot", "card", "chart_height", "cols", "head", "hero",
                          "is_dark", "is_mobile", "item_list", "metrics", "mode_switch",
                          "pill", "rows", "tiles"]),
    "db.py":        (db, ["append_rows", "backend_name", "diagnose", "export_excel_bytes",
                          "get_athlete", "init_db", "load_data", "repair", "repair_preview",
                          "reset_db", "restore_excel", "restore_preview", "read_backup", "save_athlete", "update_row", "delete_row", "upsert_row", "write_sheet"]),
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


# ── 시간대 ─────────────────────────────────────────────────────────────────
# 서버(스트림릿 클라우드)는 UTC로 돕니다. 그대로 두면 한국 시간으로 자정~아침
# 사이에 **날짜가 하루 어긋나고**, '회복 시간 남은 양'도 9시간씩 틀립니다.
# secrets.toml 의 APP_TZ 로 바꿀 수 있고, 없으면 서울 기준입니다.
def app_tz() -> zoneinfo.ZoneInfo:
    name = None
    try:
        name = st.secrets.get("APP_TZ")
    except Exception:
        pass
    name = name or os.environ.get("APP_TZ") or "Asia/Seoul"
    try:
        return zoneinfo.ZoneInfo(str(name))
    except Exception:
        return zoneinfo.ZoneInfo("Asia/Seoul")


def now_local() -> pd.Timestamp:
    """지금 시각 (내 시간대, tz 정보는 떼고). 앱 안의 모든 '지금'은 이걸 씁니다."""
    return pd.Timestamp(datetime.now(app_tz()).replace(tzinfo=None))


def today_local() -> date:
    return now_local().date()


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
                 "Interval", "Sprint", "Time Trial", "Race", "Cross Training"]
SURFACES = ["로드", "트랙", "트레드밀", "트레일", "기타"]

# 유형 이름만 봐서는 뜻을 알기 어렵습니다 — 고르는 화면과 차트 옆에 같이 붙입니다
WORKOUT_TYPE_MD = ("\n".join(f"- **{t}** ({z}) — {desc}"
                             for t, desc, z in ana.WORKOUT_TYPE_HELP)
                   + "\n\n괄호 안은 대략의 심박존입니다(‘추이 → 심박존’ 화면 기준). "
                     "이 앱은 **Easy · Recovery · LSD**를 묶어 ‘이지런’으로 보고, "
                     "러닝 이코노미(EF)처럼 강도에 민감한 계산은 이지런만 골라서 합니다.")

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


def flash(msg: str, icon: str = "✅") -> None:
    """저장 직후 알림. st.success() 를 쓰고 바로 st.rerun() 을 하면 그 메시지가
    **화면에 뜨기도 전에** 사라집니다(다시 그리면서 버려집니다). 그래서 문구를
    session_state 에 담아 두고, 다음 실행 맨 위에서 토스트로 한 번 띄웁니다.
    토스트는 화면 구석에 고정이라 폼 아래까지 스크롤해 있어도 보입니다."""
    st.session_state["_flash"] = (str(msg), icon)


def show_flash() -> None:
    """flash() 로 담아 둔 알림이 있으면 띄우고 지웁니다 — 실행당 한 번."""
    f = st.session_state.pop("_flash", None)
    if f:
        try:
            st.toast(f[0], icon=f[1])
        except Exception:                                   # pragma: no cover
            st.success(f[0])


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
                  default_open: bool = False, note: str | None = None,
                  preview=None) -> None:
    """preview(vals) -> str : 저장 버튼 위에 보여줄 한 줄.
    자동으로 계산되는 값(예: 부하 비율)을 저장 전에 확인시키는 용도입니다."""
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
                        dv = dv.date() if pd.notna(dv) else today_local()
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

                if preview:
                    _pv = preview(vals)
                    if _pv:
                        st.caption(_pv)
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
                    # 한 줄만 고칩니다 — 시트를 통째로 다시 쓰지 않습니다
                    db.update_row(sheet, id_col, rid, out)
                    st.session_state[f"exp_{key}"] = True
                    flash("수정 완료")
                    st.rerun()

                if dele:
                    if not confirm:
                        st.error("삭제하려면 위의 확인 체크박스를 먼저 선택하세요.")
                    else:
                        db.delete_row(sheet, id_col, rid)
                        st.session_state[f"exp_{key}"] = False
                        flash("삭제 완료", icon="⚠️")
                        st.rerun()


# ── Metrics 시트는 두 종류의 행을 함께 담습니다 ───────────────────────────
#   ① 프로필 기준값 행 : LTHR·심박·체중 — 분석의 "기준"이라 과거 계산까지 바뀝니다
#   ② 가민 측정 기록 행 : VO2max·Endurance·Hill·Load Focus·예측 — 그냥 추이만 봅니다
# 각 탭의 수정/삭제 목록은 '그 탭이 다루는 값이 들어있는 행'만 보여줍니다.
METRIC_MEASURE_COLS = ["VO2Max", "FitnessAge", "EnduranceScore", "HillScore",
                       "FocusAnaerobic", "FocusHighAerobic", "FocusLowAerobic",
                       "Pred5K", "Pred10K", "PredHalf", "PredFull", "LTPace",
                       "RzTSB", "RzMarathonShape", "RzEffVO2max"]
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
    예전에 가민 화면에서 함께 입력한 행도 여기 포함됩니다(실제로 이력에 쓰이니까)."""
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

STATUS_HELP = """
**둘 다 좋은 상태입니다.** 가민은 이 값들을 등급으로 매기지 않습니다 — *지금 어떤
국면인가*를 말해줄 뿐입니다.

| 상태 | 가민의 정의 | 언제 이게 맞는 상태인가 |
|---|---|---|
| **생산적** | 지금 부하가 기량을 올리는 방향으로 작용 중 | 볼륨을 쌓는 빌드업 시기 |
| **유지** | 지금 부하로 현재 기량을 지키기에 충분 | 시즌 중 유지기, 바쁜 시기, 테이퍼 초반 |
| **회복** | 부하를 낮춰 몸이 회복하는 중 | 힘든 주 다음, 의도한 리커버리 주 |
| **피킹** | 레이스에 딱 맞는 컨디션 | 대회 직전 테이퍼 끝물 |

**‘생산적’이 계속 이어지는 게 정답이 아닙니다.** 계속 밀어붙이면 결국
*비생산적*이나 *과훈련*으로 넘어갑니다. 빌드업 → 유지/회복 → 피킹으로
오르내리는 게 정상적인 흐름입니다.

**정말 살펴봐야 하는 것은 이쪽입니다.**

- **비생산적** — 부하는 충분한데 **기량이 떨어지는 중**. 수면·영양·스트레스, 또는
  훈련 강도 배분을 봐야 합니다. 이게 제일 중요한 신호입니다.
- **트레이닝 부족** — 한 주 이상 평소보다 훨씬 적게 훈련. 의도한 휴식이면 괜찮습니다.
- **부하 과다(Strained)** — 회복 대비 부하가 큼. 힘든 훈련이나 대회 뒤에는
  **정상적으로 나타납니다**. 며칠 이어지면 그때 줄이세요.
- **과훈련** — 부하가 너무 높아 역효과. 쉬어야 합니다.

위 타임라인의 **세로 위치는 부하의 크기 순서**이고, **색은 ‘지금 뭔가 해야 하나’**만
나타냅니다. 위에 있다고 좋은 게 아닙니다.
"""

DAILY_TIMING_HELP = """
**결론부터** — 가민 ‘트레이닝 준비 상태’ 화면을 **하루 한 번** 그대로 옮겨 적으면 됩니다.
화면 왼쪽 위 **‘…에 업데이트됨’ 시각**을 `기준 시간`에 같이 적어 주세요.

**하루 동안 실제로 움직이는 건 두 개뿐입니다**

| 지표 | 하루 동안 |
|---|---|
| **회복 시간** | 훈련 종료부터 줄어드는 **카운트다운** |
| **단기 부하** | 훈련이 들어오면 올라가고, 쉬면 조금씩 내려갑니다 |
| Readiness · Body Battery · HRV · 수면 점수 · 안정시 심박 · 최근 수면 · 최근 스트레스 | 밤사이 계산돼 **그날 고정** |
| 만성 부하 · Training Status | 하루 단위로만 바뀝니다 |
| **고강도 분** | **어제 하루치**만 적으면 7일 누적은 앱이 굴려서 계산합니다 |

그래서 아침에 한 번만 적어도 놓치는 게 거의 없습니다. 움직이는 두 개도 `기준 시간`을
함께 저장해 두면, 대시보드가 **회복 시간을 ‘지금 기준 남은 시간’으로 다시 계산**해서
보여줍니다. 몇 시에 넣든 대시보드 숫자는 같은 뜻이 됩니다.

**🔋 준비 상태(Readiness)를 만드는 여섯 요인** — 시계 ‘트레이닝 준비 상태 → 요인’과 같습니다.
수면 점수(지난밤) · 회복 시간 · HRV 상태 · 단기 부하 · **최근 수면 점수(3일)** ·
**최근 스트레스(3일)**. 여섯 개 모두 이 창에 있습니다.

**부하 세 가지는 이렇게 다릅니다**

| 이름 | 뜻 | 어디에 넣나 |
|---|---|---|
| **운동 부하** | 훈련 **한 건**에 매겨지는 점수 | 훈련 입력 / CSV 가져오기 |
| **단기 부하 (급성)** | 최근 **7일 누적**(가중 합) — 평균이 아닙니다 | 아침 체크인 |
| **만성 부하** | **평소 한 주치**(4주 평균). 급성과 같은 저울 위의 값이라 비율이 1 근처에서 뜻을 갖습니다 | 아침 체크인 |

**넣는 곳은 두 군데입니다**

1. **🌅 아침 체크인** — 하루 한 번. 준비 상태 화면에 보이는 대로 다 넣으면 됩니다.
2. **🏃 훈련 기록** — 훈련을 넣을 때 그 활동의 **운동 부하**를 같이 넣습니다.
   날짜별로 더해지면 가민 ‘운동 부하’ 막대 그래프와 같은 그림이 됩니다.

같은 날 다시 넣으면 **줄이 쌓이지 않고 그 줄이 갱신**됩니다. 비워 둔 칸은
앞서 넣은 값을 지우지 않으니, 생각날 때 일부만 채워 넣어도 됩니다.
"""

VDOT_HELP = """
**VDOT은 추세 지표가 아닙니다.** 가민 VO₂max처럼 매일 조금씩 움직이는 값이 아니라,
**최대노력 기록 한 건**을 Daniels & Gilbert 공식에 넣어 나오는 값입니다.
기준 기록이 그대로면 VDOT도 그대로입니다.

**몇 주째 안 바뀐다면 둘 중 하나입니다**

1. **새 최대노력 기록이 없다** — 가장 흔한 경우입니다. 이지런만 쌓이면 기준 기록이
   갱신되지 않으니 VDOT도 멈춰 있습니다.
2. **기준 기록이 최대노력이 아니다** — 이 앱은 훈련 *안의 가장 빠른 구간*도
   기록 후보로 봅니다. 편하게 달린 이지런의 5km 구간이 후보로 잡히면,
   전력의 80%쯤으로 달린 기록에서 VDOT을 내게 되어 **실제보다 한참 낮게** 나옵니다.

그래서 위 표에 **최대노력 여부**를 붙였습니다. Race·Interval·Threshold·Tempo만
전력에 가까운 훈련으로 보고, Easy·LSD·Recovery에서 나온 구간은 ‘—’로 표시합니다.
1km는 유산소 기량 추정에 잘 안 맞아서 제외합니다(5km 이상 권장).

**가민 예측과 비교하세요** — 가민의 레이스 예측을 거꾸로 돌리면 VDOT이 나옵니다.
우리 값이 가민보다 **3 이상 낮으면** 대개 전력 기록이 없다는 뜻입니다.

**제대로 맞추는 법** — 6~8주에 한 번 **5km나 10km 타임트라이얼**을 넣으세요.
워밍업 뒤 그 거리를 전력으로 달리고 기록하면, 그 한 건이 VDOT·훈련 페이스 존·
거리별 예측을 전부 현재 기량으로 다시 맞춰 줍니다.
"""

INJURY_HELP = """
**통증은 기억이 왜곡되는 대표적인 항목입니다.** "그때쯤 무릎이 좀 그랬는데"는
몇 주만 지나도 날짜가 흐려지고, 그러면 **무엇 때문이었는지**를 영영 알 수 없습니다.

적어두면 이런 게 보입니다.

- **부하를 올린 직후**에 통증이 오는 패턴인지 — 아래 그래프에서 주간 거리가
  뛴 다음 주에 붉은 띠가 오는지 보세요. 반복되면 10% 룰을 다시 봐야 합니다.
- **같은 부위가 반복**되는지 — 같은 곳이 서너 번 나오면 일시적인 게 아니라
  폼·근력·신발 쪽 문제일 가능성이 큽니다.
- **신발과 겹치는지** — 러닝화를 바꾼 시점과 통증 시작이 겹치는 일이 흔합니다.

**강도는 '뛸 수 있는가'로 매기세요**

| 강도 | 기준 |
|---|---|
| 1~2 | 신경 쓰이는 정도 |
| 3~4 | 뛰면 느껴지지만 지장 없음 |
| 5~6 | 페이스가 떨어짐 |
| 7~8 | 뛰기 어려움 |
| 9~10 | 일상에서도 아픔 |

**진행 중인 통증은 ‘🏠 오늘’ 체크포인트에 뜹니다.** 나으면 끝난 날을 채우고
상태를 ‘회복됨’으로 바꿔 주세요.

이 기록은 **판단을 돕는 메모이지 진단이 아닙니다.** 5 이상이 2주 넘게
이어지거나 일상에서도 아프면 전문가를 만나 보시는 편이 낫습니다.
"""

BODY_HELP = """
**재는 조건이 값보다 중요합니다.** 체중은 하루 사이에도 1kg 안팎이 움직이는데
대부분 수분입니다. 매주 **같은 요일 · 기상 직후 · 화장실 다녀온 뒤 · 같은 옷차림**으로
재면 그 흔들림이 빠지고 진짜 흐름만 남습니다.

**러너가 볼 만한 것**

| 지표 | 왜 보나 |
|---|---|
| **체중** | 그 자체로는 좋고 나쁨이 없습니다. 훈련량이 늘 때 **빠르게 빠지면** 에너지가 부족하다는 신호일 수 있습니다 |
| **체지방률** | 체중이 그대로여도 내려가면 근육이 늘고 지방이 준 것 |
| **골격근량** | 훈련량을 늘리는 동안 **유지되거나 느는 것**이 잘 가고 있다는 뜻. 체중과 같이 떨어지면 먹는 양을 돌아볼 때 |
| **체지방량 (kg)** | 체지방률은 근육량 변화에도 흔들립니다. 절대량과 같이 보면 ‘근육이 는 건지 지방이 준 건지’가 갈립니다 |
| **내장지방 레벨** | 인바디 기준 **10 미만이 표준 범위** |

**러닝과 같이 보기** — ‘📈 추이 → ⌚ 가민 추이 → 최근 추이 한눈에’에서
**체중 · 체지방률 · 골격근량**을 고르면 HRV·부하·페이스와 **같은 날짜 축**에
나란히 놓입니다. 체중이 내려가는 동안 EF가 같이 올라가는지, 아니면 HRV와
수면 점수가 같이 나빠지는지가 한눈에 보입니다.

체중을 줄이는 것이 늘 빨라지는 길은 아닙니다. 훈련량이 많은 시기에 체중과
골격근량이 **같이** 내려가고 안정시 심박이 올라간다면, 그건 감량이 아니라
회복이 모자란 쪽에 가깝습니다.
"""

MONOTONY_HELP = """
**단조로움(Monotony)** — 최근 7일의 **일별 부하 평균 ÷ 표준편차**입니다.
매일 비슷한 강도로만 달리면 표준편차가 작아져 값이 커집니다.
Foster의 기준으로 **1.5 미만이 좋고, 2.0을 넘으면 문제**로 봅니다.

거리가 같아도 배치에 따라 값이 달라집니다.

| 한 주 배치 | 단조로움 |
|---|---|
| 매일 10km씩 7일 | 아주 높음 — 표준편차가 0에 가까움 |
| 힘든 날 · 쉬운 날 · 완전 휴식이 섞인 7일 | 낮음 |

같은 훈련량이라도 **쉬는 날 없이 고르게** 달리면 몸이 회복할 창이 없어서,
부상과 정체로 이어지기 쉽습니다. 값이 높으면 훈련을 줄이기보다
**쉬운 날을 더 쉽게, 완전 휴식일을 하루** 넣는 쪽이 보통 맞습니다.

**스트레인(Strain)** = 그 주의 **총 부하 × 단조로움**. 많이 달렸는데 강약도 없으면
곱해져서 크게 뜁니다. 사람마다 감당 범위가 달라 **절대 기준선은 두지 않고**,
재흠 님의 **최근 4주 평균과 견줘서** 높다/평소다로 말합니다.

두 값 모두 가민이 주지 않는 지표이고, 우리가 **이미 가진 일별 부하(심박·시간 기반
TRIMP)** 로 직접 계산합니다 — RUNALYZE에서 따로 옮겨 적을 필요가 없습니다.
"""

RUNALYZE_HELP = """
가민과 RUNALYZE는 같은 활동을 보고도 **다른 것을 계산합니다.** 겹치는 값
(VO₂max, 부하 비율, 러닝 다이나믹스)은 굳이 두 번 적을 필요가 없고, 아래 셋만
가민에 없거나 방식이 달라서 따로 적어 둘 값어치가 있습니다.

| 지표 | 무엇을 말해주나 | 가민에 없는 이유 |
|---|---|---|
| **TSB (폼)** | 체력(CTL) − 피로(ATL). **양수 = 피로가 빠진 상태**, 음수 = 부하가 쌓인 상태. 대회 2~3주 전 테이퍼링에서 이게 올라오는지를 봅니다 | 가민 ‘부하 비율’은 *과했나*만 말하고, *지금 폼이 올라왔나*는 말해주지 않습니다 |
| **Marathon Shape** | 최근 6개월 **주간 거리(2/3) + 롱런 길이(1/3)** 로 매기는 지구력 준비도. 기준선은 **10K 17% · 하프 42.5% · 풀 100%** | 가민에는 같은 개념이 없습니다 |
| **Effective VO₂max** | 심박·페이스 관계에 **본인 최고 기록으로 보정**을 건 값 | 가민 VO₂max와 산출 방식이 달라, 둘이 갈리면 한쪽이 더위·컨디션에 흔들린 것으로 읽을 수 있습니다 |

**단조로움(Monotony)·스트레인(Strain)은 옮겨 적지 않아도 됩니다** — 우리가 이미
가진 일별 부하로 직접 계산해서 ‘📈 계산 통계’에 그립니다.

다른 칸과 마찬가지로 **0은 ‘미입력’**으로 봅니다. TSB가 정확히 0인 날은 드물지만,
그럴 때는 0.1처럼 아주 가까운 값으로 넣거나 아래 수정 목록에서 고치세요.
"""

INTENSITY_HELP = """
**저·중·고강도 묶음** — 저강도 = **Z1~Z2**, 중강도 = **Z3~Z4**, 고강도 = **Z5** 입니다.
(‘📈 계산 통계’ 화면에서는 같은 것을 LT1/LT2 기준으로 부릅니다.)

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


CUSTOM_RANGE = "직접 지정"


def range_picker(key: str, default: str = "3개월", label: str = "기간"):
    """‘최근 N일’ 버튼 + <직접 지정> 날짜 범위. 모든 추이 화면이 같은 것을 씁니다.

    반환: (시작일, 종료일, 설명문) — 둘 다 None 이면 전체 기간입니다.
    """
    sel = seg(label, list(RANGE_DAYS) + [CUSTOM_RANGE], key + "_sel", default)
    today = today_local()
    if sel == CUSTOM_RANGE:
        _d0 = st.session_state.get(key + "_rng") or (today - timedelta(days=89), today)
        try:
            picked = st.date_input("시작 ~ 끝", _d0, key=key + "_rng",
                                   label_visibility="collapsed",
                                   help="시작일과 종료일을 차례로 고르세요.")
        except Exception:
            picked = (today - timedelta(days=89), today)
        # 끝 날짜를 아직 안 고르면 튜플 길이가 1입니다 — 그때는 시작일만 씁니다
        if isinstance(picked, (tuple, list)):
            s = picked[0] if picked else today - timedelta(days=89)
            e = picked[1] if len(picked) > 1 else today
        else:
            s, e = picked, today
        if s > e:
            s, e = e, s
        return (pd.Timestamp(s), pd.Timestamp(e),
                f"{s:%Y-%m-%d} ~ {e:%Y-%m-%d} · {(e - s).days + 1}일")
    n = RANGE_DAYS[sel]
    if n is None:
        return None, None, "전체 기간"
    s = today - timedelta(days=n - 1)
    return pd.Timestamp(s), pd.Timestamp(today), f"최근 {n}일 ({s:%Y-%m-%d} ~)"


def clip_range(df, datecol, start, end):
    """고른 기간으로 자릅니다. start/end 가 None 이면 그대로 둡니다."""
    if df is None or df.empty or datecol not in df.columns:
        return df
    d = df.copy()
    d[datecol] = pd.to_datetime(d[datecol], errors="coerce")
    d = d.dropna(subset=[datecol])
    if start is not None:
        d = d[d[datecol] >= start]
    if end is not None:
        d = d[d[datecol] <= end + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)]
    return d


X_HIDDEN = alt.Axis(labels=False, title=None, grid=False, domain=False, ticks=False)


def panel_title(label: str):
    """작은 그래프 칸의 이름표. 세로로 눕힌 Y축 제목은 읽기 어렵고 가로 폭만
    잡아먹어서, 칸 위에 가로로 한 줄 올립니다."""
    return alt.TitleParams(label, fontSize=11, fontWeight=600,
                           color=C["muted"], anchor="start", offset=2)


def _pyfmt(fmt: str) -> str:
    """Vega 형식 문자열을 파이썬 format()이 받을 수 있게 바꿉니다.
    Vega의 ',d'는 정수 서식이라 파이썬에서 float에 쓰면 터집니다 → ',.0f'."""
    f = str(fmt or "")
    if f.endswith("d"):
        return f[:-1] + ".0f"
    return f or ".2f"


def _tick_step(fmt: str):
    """'.1f' → 0.1. 눈금 간격을 표시 자릿수보다 잘게 두면 8.25가 8.3으로 반올림돼
    '8.3, 8.3'처럼 같은 눈금이 두 번 찍힙니다."""
    m = re.match(r"^[,]?\.(\d+)f$", str(fmt or ""))
    return 10 ** -int(m.group(1)) if m else None


def dual_small_multiples(df, datecol, pairs, span, h_pc=96, h_mb=80):
    """단위가 다른 여러 지표를 '위아래 작은 그래프'로. 날짜 축은 맨 아래만 씁니다.
    pairs = [(컬럼, 표시이름, 색, 숫자형식), ...]"""
    xax = date_axis(span)
    usable = [(c, lab, col, fmt) for c, lab, col, fmt in pairs
              if c in df.columns and not df[[datecol, c]].dropna().empty]
    charts = []
    for i, (col, label, color, fmt) in enumerate(usable):
        sub = df[[datecol, col]].dropna()
        step = _tick_step(fmt)
        charts.append(alt.Chart(sub).mark_line(color=color, point=True).encode(
            # 축은 '마지막으로 실제로 그려지는' 칸에만 — 빈 칸을 건너뛰고 세야
            # 날짜 눈금이 통째로 사라지는 일이 없습니다.
            x=alt.X(f"{datecol}:T", title=None,
                    scale=alt.Scale(padding=14),
                    axis=xax if i == len(usable) - 1 else X_HIDDEN),
            y=alt.Y(f"{col}:Q", title=None,
                    scale=alt.Scale(zero=False, padding=8),
                    axis=alt.Axis(format=fmt, tickCount=3,
                                  **({"tickMinStep": step} if step else {}))),
            tooltip=[alt.Tooltip(f"{datecol}:T", title="날짜", format="%Y-%m-%d"),
                     alt.Tooltip(f"{col}:Q", title=label, format=fmt)]
        ).properties(height=ui.chart_height(h_pc, h_mb),
                     title=panel_title(label)))
    return charts or None


def garmin_trend_charts(panels, h_pc=112, h_mb=94):
    """가민 Connect의 ‘최근 추이’처럼, 지표마다 한 칸씩 위아래로 세우고
    날짜 축은 맨 아래 한 번만 그립니다. 단위가 달라도 서로 비교하기 쉽습니다.

    칸마다 날짜 범위가 다르면(일일 지표는 매일, 측정값은 가끔) 세로로 읽을 때
    같은 가로 위치가 다른 날이 됩니다 → x축 범위를 전부 똑같이 고정합니다."""
    _all = pd.concat([p["data"]["날짜"] for p in panels], ignore_index=True)
    lo, hi = _all.min(), _all.max()
    span = max((hi - lo).days, 1)
    xsc = alt.Scale(domain=[lo.strftime("%Y-%m-%d"), hi.strftime("%Y-%m-%d")],
                    padding=14)
    xax = date_axis(span)
    charts = []
    for i, p in enumerate(panels):
        d, mark, fmt = p["data"], p["mark"], p["fmt"]
        step = _tick_step(fmt)
        x = alt.X("날짜:T", title=None, scale=xsc,
                  axis=xax if i == len(panels) - 1 else X_HIDDEN)
        ysc = alt.Scale(zero=(mark == "bar"), padding=8,
                        **({"domain": list(p["domain"])} if p["domain"] else {}))
        y = alt.Y("값:Q", title=None, scale=ysc,
                  axis=alt.Axis(format=fmt, tickCount=3,
                                **({"tickMinStep": step} if step else {})))
        tip = [alt.Tooltip("날짜:T", title="날짜", format="%Y-%m-%d"),
               alt.Tooltip("계열:N", title="구분"),
               alt.Tooltip("값:Q", title=p["label"], format=fmt)]
        base = alt.Chart(d)

        if p["key"] == "hrv":
            # 가민처럼 상태별로 점 색을 달리합니다. 가민이 쓰는 회색 '기준 범위'
            # 띠는 우리가 받아 적는 값이 아니라서 그리지 않습니다.
            _sd = [s for s in ana.HRV_TONE_ORDER if (d["상태"] == s).any()]
            _smap = {"균형 잡힘": C["teal"], "불균형": C["amber"],
                     "낮음": C["red"], "나쁨": C["red"], "상태 없음": C["slate"]}
            col = (alt.value(C["primary"]) if len(_sd) <= 1 else
                   alt.Color("상태:N", title=None,
                             scale=alt.Scale(domain=_sd,
                                             range=[_smap[s] for s in _sd]),
                             legend=alt.Legend(orient="top", direction="horizontal",
                                               symbolType="circle", symbolSize=90)))
            ch = (base.mark_line(color=C["pale"], strokeWidth=1.3,
                                 opacity=.8).encode(x=x, y=y)
                  + base.mark_point(size=80, filled=True, opacity=.95).encode(
                      x=x, y=y, color=col, tooltip=tip + [alt.Tooltip("상태:N")]))
        elif p["multi"]:
            _dom = list(dict.fromkeys(d["계열"]))
            ch = base.mark_line(point=True, strokeWidth=2).encode(
                x=x, y=y,
                color=alt.Color("계열:N", title=None,
                                scale=alt.Scale(domain=_dom,
                                                range=[C["primary"], C["amber"]]),
                                legend=alt.Legend(orient="top", direction="horizontal",
                                                  symbolType="circle", symbolSize=90)),
                tooltip=tip)
        elif mark == "bar":
            ch = base.mark_bar(color=C["primary"], size=14).encode(x=x, y=y, tooltip=tip)
        else:
            ch = base.mark_line(color=C["primary"], point=True,
                                strokeWidth=2).encode(x=x, y=y, tooltip=tip)

        if p["key"] == "ratio":
            # 가민의 초록 '최적 범위'와 같은 뜻입니다
            band = alt.Chart(pd.DataFrame({"lo": [0.8], "hi": [1.4]})).mark_rect(
                opacity=.12, color=C["teal"]).encode(y=alt.Y("lo:Q", scale=ysc), y2="hi:Q")
            ch = band + ch
        elif p["key"] == "rztsb":
            # TSB는 0을 기준으로 위(신선함)/아래(부하 축적)가 갈립니다
            zero = alt.Chart(pd.DataFrame({"y": [0.0]})).mark_rule(
                color=C["slate"], strokeDash=[4, 4]).encode(y=alt.Y("y:Q", scale=ysc))
            ch = zero + ch

        charts.append(ch.properties(height=ui.chart_height(h_pc, h_mb),
                                    title=panel_title(p["label"])))
    return charts or None


MMSS_EXPR = ("floor(datum.value/60) + ':' + "
             "(datum.value%60 < 10 ? '0' : '') + "
             "format(round(datum.value%60), 'd')")


def workout_trend_charts(wt, keys, multi=True, ma_label="4주", show_avg=True,
                         show_trend=True, h_pc=124, h_mb=104):
    """훈련 한 건 = 점 하나. 지표마다 한 칸씩 위아래로, 날짜 축은 맨 아래만.

    선은 최대 세 개입니다 — 먹색 = 이동평균, 회색 파선 = 이 기간 전체 평균,
    주황 = 선형 추세(뜻이 있는 지표만, analytics.TREND_LINE_OK).
    """
    if wt is None or wt.empty or not keys:
        return None
    xax = date_axis(_span_days(wt["WorkoutDate"]))
    # 칸마다 값이 있는 날짜가 다릅니다(폼 지표는 가끔만 기록됨). x 범위를 고정하지
    # 않으면 칸마다 축이 달라져서, 세로로 읽을 때 같은 가로 위치가 다른 날이 됩니다.
    _lo, _hi = wt["WorkoutDate"].min(), wt["WorkoutDate"].max()
    xsc = alt.Scale(domain=[_lo.strftime("%Y-%m-%d"), _hi.strftime("%Y-%m-%d")],
                    padding=16)
    _tdom = [t for t in WORKOUT_TYPES if (wt["WorkoutType"] == t).any()]
    charts = []
    for i, col in enumerate(keys):
        name, unit, fmt, _good, _desc = ana.WORKOUT_TREND_META[col]
        _cols = ["WorkoutDate", "WorkoutType", col] + [
            c for c in (f"{col}_MA", f"{col}_AV", f"{col}_TR") if c in wt.columns]
        sub = wt[_cols].dropna(subset=[col])
        if sub.empty:
            continue
        is_pace = fmt == "pace"
        nfmt = ".0f" if is_pace else fmt
        ysc = alt.Scale(zero=False, padding=10, reverse=is_pace)
        yax = (alt.Axis(labelExpr=MMSS_EXPR, tickCount=4) if is_pace else
               alt.Axis(format=fmt, tickCount=3,
                        **({"tickMinStep": _tick_step(fmt)} if _tick_step(fmt) else {})))
        x = alt.X("WorkoutDate:T", title=None, scale=xsc,
                  axis=xax if i == len(keys) - 1 else X_HIDDEN)
        y = alt.Y(f"{col}:Q", title=None, scale=ysc, axis=yax)
        tip = [alt.Tooltip("WorkoutDate:T", title="날짜", format="%Y-%m-%d"),
               alt.Tooltip("WorkoutType:N", title="유형"),
               alt.Tooltip(f"{col}:Q", title=name, format=nfmt)]
        # 유형이 여럿일 때만 색으로 구분합니다 — 하나면 범례가 자리만 차지합니다.
        # 여기서는 '어느 유형인지 구분'이 목적이라 밝기 단계(ramp)가 아니라
        # 서로 다른 색을 씁니다 — 작은 칸에서 같은 계열 3단계는 구분이 안 됩니다
        colr = (alt.Color("WorkoutType:N", title=None,
                          scale=alt.Scale(domain=_tdom,
                                          range=CHART_PALETTE[:len(_tdom)]),
                          legend=(alt.Legend(orient="top", direction="horizontal",
                                             symbolType="circle", symbolSize=90)
                                  if i == 0 else None))
                if (multi and len(_tdom) > 1) else alt.value(C["primary"]))

        layers = []

        def _line(c, color, dash=None, w=2.2, title=""):
            if c not in sub.columns or sub[c].notna().sum() < 2:
                return None
            mk = dict(color=color, strokeWidth=w, opacity=.95)
            if dash:
                mk["strokeDash"] = dash
            return alt.Chart(sub.dropna(subset=[c])).mark_line(**mk).encode(
                x=x, y=alt.Y(f"{c}:Q", title=None, scale=ysc, axis=yax),
                tooltip=[alt.Tooltip("WorkoutDate:T", title="날짜", format="%Y-%m-%d"),
                         alt.Tooltip(f"{c}:Q", title=title, format=nfmt)])

        if show_avg:
            layers.append(_line(f"{col}_AV", C["slate"], [5, 4], 1.6, "기간 평균"))
        if show_trend and col in ana.TREND_LINE_OK:
            layers.append(_line(f"{col}_TR", C["accent"], None, 2.0, "추세"))
        if ma_label and ma_label != "없음":
            # 이동평균선은 유형 색과 겹치면 안 됩니다 — 먹색 한 가지로 고정합니다
            layers.append(_line(f"{col}_MA", C["ink"], None, 2.2,
                                f"{ma_label} 이동평균"))
        layers = [l for l in layers if l is not None]
        pts = alt.Chart(sub).mark_point(size=70, filled=True, opacity=.8).encode(
            x=x, y=y, color=colr, tooltip=tip)

        title = f"{name} ({unit})" if unit else name
        if is_pace:
            title += " — 위가 빠름"
        _chg = (pd.to_numeric(sub.get(f"{col}_TR"), errors="coerce").dropna()
                if show_trend and f"{col}_TR" in sub.columns else pd.Series(dtype=float))
        if len(_chg) >= 2:
            _d = float(_chg.iloc[-1] - _chg.iloc[0])
            _ds = f"{_d:+{_pyfmt(nfmt)}}"
            # '+0' 처럼 반올림해서 0이 되는 변화는 숫자보다 말이 정확합니다
            title += (" · 추세 거의 없음" if float(_ds.replace(",", "")) == 0
                      else f" · 추세 {_ds}")
        ch = layers[0] if layers else pts
        for l in layers[1:]:
            ch = ch + l
        charts.append((ch + pts if layers else pts).properties(
            height=ui.chart_height(h_pc, h_mb), title=panel_title(title)))
    return charts or None


# ── 가민 시계처럼 생긴 반원 게이지 ─────────────────────────────────────────
# Altair 대신 SVG로 직접 그립니다 — 가운데 숫자, 띠 색, 표식 위치를 정확히
# 잡을 수 있고 테마 색을 그대로 쓸 수 있습니다.
GAUGE_START, GAUGE_SWEEP = -120.0, 240.0      # 아래쪽 120°는 비워 둡니다

# 준비 상태 띠 — 가민 등급 구간(1~24 나쁨 / 25~49 낮음 / 50~74 중간 /
# 75~94 높음 / 95~100 최상)을 그대로 씁니다. 색은 이 앱의 상태 색과 맞춥니다.
READINESS_BANDS = [(0, 25, C["red"]), (25, 50, C["amber"]), (50, 75, C["slate"]),
                   (75, 95, C["primary"]), (95, 100, C["teal"])]

# 부하 비율 띠 — 가민 설명서 구간(0.8 미만 낮음 / 0.8~1.4 최적 /
# 1.5~1.9 높음 / 2.0 이상 매우 높음). 2.5 이상은 눈금 끝에 붙습니다.
LOAD_RATIO_MAX = 2.5
LOAD_RATIO_BANDS = [(0.0, 0.8, C["slate"]), (0.8, 1.5, C["teal"]),
                    (1.5, 2.0, C["amber"]), (2.0, LOAD_RATIO_MAX, C["red"])]


def _gauge_xy(v: float, r: float, cx: float = 100.0, cy: float = 100.0,
              lo: float = 0.0, hi: float = 100.0):
    frac = 0.0 if hi <= lo else (max(min(v, hi), lo) - lo) / (hi - lo)
    a = math.radians(GAUGE_START + frac * GAUGE_SWEEP)
    return cx + r * math.sin(a), cy - r * math.cos(a)


def _gauge_arc(v0: float, v1: float, r: float, color: str, w: float,
               lo: float = 0.0, hi: float = 100.0) -> str:
    if v1 <= v0:
        return ""
    x0, y0 = _gauge_xy(v0, r, lo=lo, hi=hi)
    x1, y1 = _gauge_xy(v1, r, lo=lo, hi=hi)
    span = 0.0 if hi <= lo else (v1 - v0) / (hi - lo) * GAUGE_SWEEP
    large = 1 if span > 180 else 0
    return (f"<path d='M {x0:.2f} {y0:.2f} A {r} {r} 0 {large} 1 {x1:.2f} {y1:.2f}' "
            f"fill='none' stroke='{color}' stroke-width='{w}' stroke-linecap='round'/>")


def gauge_svg(score, bands, center_sub: str = "", unit: str = "",
              size: int = 210, lo: float = 0.0, hi: float = 100.0,
              fmt: str = "{:,.0f}", ticks=None,
              track: str = "", progress: str = "") -> str:
    """게이지 하나. bands = [(하한, 상한, 색), ...] · score 위치에 표식 하나.

    lo~hi 로 눈금 범위를 바꿀 수 있습니다 (기본 0~100). track/progress 색을 주면
    **진행 아크**(연한 바탕 위에 lo→score 만 칠하기)로 그립니다 — 회복 시간처럼
    등급이 아니라 남은 양을 보여 줄 때 씁니다. ticks = [(값, 라벨), ...].
    """
    v = fnum(score, float("nan"))
    r, w = 80.0, 15.0
    arcs = ""
    if track:
        arcs += _gauge_arc(lo, hi, r, track, w, lo, hi)
    arcs += "".join(_gauge_arc(b0, b1, r, col, w, lo, hi) for b0, b1, col in bands)
    if progress and np.isfinite(v) and v > lo:
        arcs += _gauge_arc(lo, v, r, progress, w, lo, hi)
    mark = ""
    if np.isfinite(v):
        mx, my = _gauge_xy(v, r, lo=lo, hi=hi)
        mark = (f"<circle cx='{mx:.2f}' cy='{my:.2f}' r='9' "
                f"fill='var(--surface)' stroke='var(--text)' stroke-width='3'/>")
        try:
            big = fmt.format(v)
        except (ValueError, TypeError):
            big = str(v)
    else:
        big = "—"
    tk = ""
    for tv, tl in (ticks or []):
        tx, ty = _gauge_xy(tv, r - 20, lo=lo, hi=hi)
        tk += (f"<text x='{tx:.1f}' y='{ty + 4:.1f}' text-anchor='middle' "
               f"style='font-size:11px;fill:var(--text-3)'>{tl}</text>")
    return (
        f"<div style='display:flex;justify-content:center'>"
        f"<svg viewBox='0 0 200 185' "
        f"style='width:100%;max-width:{size}px;height:auto' "
        f"role='img' aria-label='게이지 {big}'>"
        f"{arcs}{mark}{tk}"
        f"<text x='100' y='104' text-anchor='middle' "
        f"style='font-size:44px;font-weight:700;fill:var(--text)'>{big}</text>"
        f"<text x='100' y='126' text-anchor='middle' "
        f"style='font-size:13px;fill:var(--text-3)'>{unit}</text>"
        f"<text x='100' y='152' text-anchor='middle' "
        f"style='font-size:15px;font-weight:600;fill:var(--text-2)'>{center_sub}</text>"
        f"</svg></div>")


_LINK_N = [0]


def card_link(path: str, tabs=None, hint: str = "자세히", go=None) -> None:
    """카드 아래 '자세히 →' 한 줄 — 누르면 그 화면으로 갑니다.

    go = (섹션키, 화면키). 예전에는 st.tabs 를 파이썬에서 못 바꿔서 작은
    iframe 안의 스크립트가 부모 문서의 탭 버튼을 대신 눌렀습니다. 이동을
    세그먼트로 바꾼 뒤로는 그냥 버튼 하나면 됩니다.
    tabs 는 옛 호출부 호환용이고 쓰지 않습니다.
    """
    if not go:
        st.markdown(
            f"<p class='rl-sub' style='margin:8px 0 0;text-align:right'>"
            f"{hint} → <b>{path}</b></p>", unsafe_allow_html=True)
        return
    _LINK_N[0] += 1
    with st.container(key=f"rl-cardlink-{_LINK_N[0]}"):
        if st.button(f"{hint} → {path}  ↗", key=f"cl{_LINK_N[0]}",
                     width="stretch"):
            nav_go(*go)


def factor_rows_html(factors) -> str:
    """준비 상태 요인 목록 — 이름 · 값 · 상태 + 색점."""
    out = ""
    for f in factors:
        dot = {"ok": "var(--ok)", "warn": "var(--warn)",
               "bad": "var(--bad)"}.get(f["tone"], "var(--text-3)")
        out += ("<div class='rl-row'>"
                f"<span class='k'>{f['name']}"
                + (f" <b style='color:var(--text-2)'>{f['value']}</b>"
                   if f["value"] else "")
                + f" <span style='opacity:.65'>· {f['note']}</span></span>"
                f"<span class='v'>{f['state']}"
                f"<span style='display:inline-block;width:8px;height:8px;"
                f"border-radius:50%;background:{dot};margin-left:7px;"
                f"vertical-align:middle'></span></span></div>")
    return out


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
    """n개 항목을 cols에 순서대로 넣습니다 — 왼쪽에서 오른쪽, 그 다음 줄.

    예전에는 '열 우선'이었습니다. Streamlit이 좁은 화면에서 컬럼을 통째로
    위아래로 쌓아 버려서, 행 우선으로 넣으면 순서가 뒤섞였기 때문입니다.
    지금은 ui.cols(..., keep_row=True) 가 모바일에서도 한 줄을 유지하므로
    (ui.py의 st-key-rlrow CSS) 읽는 순서 그대로 행 우선이 맞습니다.
    n 은 호출부 호환을 위해 남겨 둡니다.
    """
    k = max(len(cols), 1)
    return cols[i % k]


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
        st.caption("**밝게 / 어둡게는 기기 설정을 따라갑니다.** 폰의 다크 모드를 "
                   "켜면 이 앱도 어두워집니다.")
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
        st.caption("**밝게 / 어둡게는 기기 설정을 그대로 따라갑니다.** 폰·PC의 "
                   "다크 모드를 켜면 이 앱도 같이 어두워집니다 (앱 안에 고르는 "
                   "칸은 없습니다).")
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


# ── 이동 — 탭 대신 세그먼트 한 줄 ───────────────────────────────────────────
# st.tabs 는 **안 보는 탭의 내용까지 전부 실행**합니다. 화면이 18개, 카드가
# 70개가 넘으면 클릭 한 번에 그 전부를 다시 계산하느라 몇 초씩 걸립니다.
# 세그먼트로 바꾸면 고른 화면만 실행되고, 덤으로 파이썬에서 선택을 바꿀 수
# 있어 카드 아래 '자세히 →'가 우회 없이 정확하게 이동합니다.
#
# 묶는 기준은 '데이터 출처'가 아니라 **무엇을 알고 싶은가**입니다. 그리고
# 입력은 한곳에 모으지 않고 **그 값을 보는 화면**에 붙였습니다 — 체중은 몸,
# 훈련은 훈련, 아침 가민 값은 오늘.
SECTIONS = ["today", "train", "trend", "body", "goal", "settings"]
SEC_LABEL = {"today": ("🏠 오늘", "🏠 오늘"), "train": ("🏃 훈련", "🏃 훈련"),
             "trend": ("📈 추이", "📈 추이"), "body": ("❤️ 몸", "❤️ 몸"),
             "goal": ("🎯 목표", "🎯 목표"), "settings": ("⚙️ 설정", "⚙️ 설정")}
# 화면: (키, PC 이름, 모바일 이름)
SCREENS = {
    "today": [("summary", "🏠 요약", "🏠 요약"),
              ("morning", "⌚ 아침 입력", "⌚ 아침")],
    "train": [("hist", "📋 훈련 이력", "📋 이력"),
              ("new", "➕ 훈련 입력", "➕ 입력"),
              ("imp", "📥 파일 가져오기", "📥 파일")],
    "trend": [("garmin", "⌚ 가민 추이", "⌚ 가민"),
              ("stat", "📈 계산 통계", "📈 통계"),
              ("zone", "🎚️ 심박존", "🎚️ 존")],
    "body": [("body", "⚖️ 체중 · 부상", "⚖️ 체중"),
             ("measure", "📈 가민 측정", "📈 측정")],
    "goal": [("proj", "🎯 프로젝트", "🎯 프로젝트"),
             ("race", "🏁 대회", "🏁 대회"),
             ("pred", "🔮 기량 예측", "🔮 예측"),
             ("pr", "🏆 개인 기록", "🏆 기록")],
    "settings": [("prof", "👤 프로필 & 기준값", "👤 프로필"),
                 ("shoe", "👟 러닝화", "👟 러닝화"),
                 ("coach", "🤖 코치 노트", "🤖 코치"),
                 ("backup", "💾 백업 & 도구", "💾 백업")],
}


def nav_pick(key: str, options: list[str], labels: dict) -> str:
    """세그먼트 한 줄. 위젯 키에 판 번호를 붙여 둡니다 — 스트림릿은 위젯이
    만들어진 뒤에는 그 키의 session_state 를 못 바꾸기 때문에, 프로그램에서
    화면을 옮기려면 위젯을 새로 만들어야 합니다(nav_go)."""
    cur = st.session_state.get(key)
    if cur not in options:
        cur = options[0]
    ver = st.session_state.get(key + "__v", 0)
    with st.container(key=f"rlnav-{key}"):
        v = st.segmented_control("이동", options, default=cur, key=f"{key}__w{ver}",
                                 format_func=lambda k: labels[k],
                                 label_visibility="collapsed", width="stretch")
    v = v if v in options else cur          # 같은 칸을 다시 누르면 None 이 옵니다
    st.session_state[key] = v
    return v


def nav_go(sec: str, scr: str | None = None) -> None:
    """카드 아래 '자세히 →' 에서 화면을 옮깁니다."""
    st.session_state["nav_sec"] = sec
    st.session_state["nav_sec__v"] = st.session_state.get("nav_sec__v", 0) + 1
    if scr:
        k = f"nav_scr_{sec}"
        st.session_state[k] = scr
        st.session_state[k + "__v"] = st.session_state.get(k + "__v", 0) + 1
    st.session_state["_scroll_top"] = True
    st.rerun()


def scroll_top_once() -> None:
    """화면을 옮긴 직후 한 번만 맨 위로. 스트림릿은 다시 그려도 스크롤 위치를
    그대로 두기 때문에, 링크로 건너뛰면 엉뚱한 중간부터 보입니다."""
    if not st.session_state.pop("_scroll_top", False):
        return
    import streamlit.components.v1 as _c
    # 다시 그리는 중에 한 번 부르면 아래 내용이 늘어나며 위치가 밀립니다 —
    # 몇 번 나눠서 올려 둡니다.
    _c.html("<script>(function(){function up(){try{"
            "window.parent.scrollTo({top:0,behavior:'instant'});}catch(e){}}"
            "up();[60,200,500,900].forEach(t=>setTimeout(up,t));})();</script>",
            height=0)


scroll_top_once()
_mb = ui.is_mobile()
SEC = nav_pick("nav_sec", SECTIONS, {k: v[1 if _mb else 0]
                                     for k, v in SEC_LABEL.items()})
_scr_defs = SCREENS[SEC]
SCR = nav_pick(f"nav_scr_{SEC}", [k for k, _p, _m in _scr_defs],
               {k: (m if _mb else p) for k, p, m in _scr_defs})


# 저장 직후의 알림 — 쓰기 → st.rerun() 을 거쳐 여기서 한 번 띄웁니다
show_flash()


# ═════════════════════════════════════════════════════════════════════════
# TAB 1 · 오늘 — 지금 상태 한눈에
# ═════════════════════════════════════════════════════════════════════════


# ═════════════════════════════════════════════════════════════════════════
# 오늘 · 요약 — 지금 상태 한눈에
# ═════════════════════════════════════════════════════════════════════════
if SEC == "today" and SCR == "summary":
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

    TODAY = now_local().normalize()

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
    rc_left, rc_raw, rc_until, rc_live = ana.recovery_remaining(G, now_local())
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

    # ── 오늘의 준비 상태 — 시계 화면처럼 게이지 하나로 ────────────────────
    _rd_tone, _rd_kr = ana.readiness_meta(G.get("TrainingReadiness"))
    _factors = ana.readiness_factors(G)
    alerts = (ana.injury_alerts(ana.prepare_injury(db.load_data("Injury")))
              + ana.garmin_alerts(G)
              + ana.build_alerts(df_w, df_shoes, daily, weekly, inten))

    _top = ui.cols(2, 1)
    with _top[0]:
        with ui.card("rdy"):
            ui.head("🔋 트레이닝 준비 상태",
                    "시계의 ‘요인’ 화면과 같습니다")
            st.markdown(
                gauge_svg((G.get("TrainingReadiness")
                           if fnum(G.get("TrainingReadiness")) > 0 else None),
                          READINESS_BANDS, center_sub=_rd_kr, unit="/ 100")
                + factor_rows_html(_factors), unsafe_allow_html=True)
            _miss = [f for f in _factors if f["state"] == "—"]
            if _miss:
                st.caption(f"‘—’ {len(_miss)}개는 아직 안 넣은 항목입니다 — "
                           "‘🏠 오늘 → ⌚ 아침 입력’에서 채우면 시계 화면과 "
                           "똑같아집니다.")
    with _top[1 % len(_top)]:
        with ui.card("alerts"):
            ui.head("🔔 오늘의 체크포인트",
                    "지금 신경 쓸 것만 — 없으면 그대로 가면 됩니다")
            if alerts:
                render_alerts(alerts[:7])
            else:
                st.markdown(
                    "<div style='padding:22px 4px;text-align:center;"
                    "color:var(--text-3)'>👍 특별히 걸리는 것이 없습니다</div>",
                    unsafe_allow_html=True)

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

    # ─────────────────────────────────────────────────────────────────
    # 홈 카드 그리드 — PC 2단, 모바일 1단 (가민 Connect 웹과 같은 구성)
    # 예전에는 네 묶음이 전체 폭 타일 띠로 세로로 길게 늘어져 있었습니다.
    # ─────────────────────────────────────────────────────────────────
    _g1 = ui.cols(2, 1)
    with _g1[0]:
        with ui.card("wkcard"):
            ui.head("🏃 이번 주 · 내가 넣은 기록",
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
            ], per_row_pc=2)
            card_link("🏃 훈련 · 📋 훈련 이력", go=("train", "hist"))


    with _g1[1 % len(_g1)]:
        with ui.card("loadcard"):
            # ─────────────────────────────────────────────────────────────────
            # 타일 — 부하 / 컨디션 / 기량
            # ─────────────────────────────────────────────────────────────────
            _load_keys = ["AcuteLoad", "LoadRatio", "RecoveryTimeHr",
                          "IntensityMinutesDay"]
            # 주간 고강도는 '당일' 입력을 7일 굴려 우리가 계산합니다
            _int = ana.add_intensity_rolling(
                df_daily.assign(
                    StatusDate=pd.to_datetime(df_daily["StatusDate"], errors="coerce")
                ).sort_values("StatusDate")
                if not df_daily.empty else df_daily)
            _int7_pts = (hist_series(_int, "StatusDate", "IntensityMin7")
                         if (_int is not None and not _int.empty) else [])
            _int7_v = float(_int7_pts[-1][1]) if _int7_pts else np.nan
            ui.head("📊 가민 · 트레이닝 부하", "본 시점의 값 · " + seen_at(_load_keys))
            _ch_v = pd.to_numeric(G.get("ChronicLoad"), errors="coerce")
            _al_s, _al_t = aged("AcuteLoad",
                                (f"만성 {_ch_v:,.0f}" if np.isfinite(_ch_v) and _ch_v > 0
                                 else None))
            if _lr_src == "계산":
                # 계산값은 급성·만성을 본 시점의 값이라 '며칠 전' 표시가 따로 필요 없습니다
                _lr_s, _lr_t = "급성 ÷ 만성으로 계산", lr_tone
            elif _lr_src == "만성 부하 필요":
                _lr_s, _lr_t = "만성 부하를 넣으면 계산됩니다", "warn"
            else:
                # 게이지 가운데가 이미 판정을 보여 주니 아래에는 '언제 본 값'만
                _lr_s, _lr_t = aged("LoadRatio", None, lr_tone)
            # 판정 뒤에 붙는 설명("낮음 — 단기 부하가 …")은 게이지 아래로 내립니다
            _lr_why = lr_txt.split(" — ")[1] if " — " in lr_txt else ""
            _lr_s = " · ".join(x for x in (_lr_why, _lr_s) if x)
            _rc_s, _rc_t = (((rc_until + " 완료 예상")
                             if (rc_until and np.isfinite(rc_left) and rc_left > 0)
                             else ""), rc_tone) \
                if rc_live else aged("RecoveryTimeHr", None, rc_tone)
            _im_s, _im_t = aged("IntensityMinutesDay")

            # ── 게이지 두 개 — 시계의 ‘부하 비율’·‘회복 시간’ 화면과 같은 모양 ──
            _gsz = 150 if ui.is_mobile() else 186
            with st.container(key="rlrow_loadgauge"):
                _gg = st.columns(2)
                with _gg[0]:
                    st.markdown(
                        f"<p class='rl-sub' style='margin:0;text-align:center'>"
                        f"부하 비율</p>"
                        + gauge_svg(_lr_val, LOAD_RATIO_BANDS,
                                    center_sub=lr_txt.split(" — ")[0],
                                    unit="급성 ÷ 만성", size=_gsz,
                                    lo=0.0, hi=LOAD_RATIO_MAX, fmt="{:.2f}")
                        + f"<p class='rl-sub' style='margin:-6px 0 0;text-align:center'>"
                          f"{_lr_s or ''}</p>", unsafe_allow_html=True)
                with _gg[1 % len(_gg)]:
                    # 회복 시간은 등급이 아니라 **남은 양**이라 띠 대신 진행 아크입니다
                    _rc_hi = max(12.0, float(np.nanmax([rc_raw if np.isfinite(rc_raw) else 0,
                                                        rc_left if np.isfinite(rc_left) else 0,
                                                        24.0])))
                    st.markdown(
                        f"<p class='rl-sub' style='margin:0;text-align:center'>"
                        f"회복 시간{' (지금 기준)' if rc_live else ''}</p>"
                        + gauge_svg(rc_left, [], center_sub=rc_txt.split(" · ")[0],
                                    unit="시간 남음", size=_gsz,
                                    lo=0.0, hi=_rc_hi,
                                    # 남은 시간이 0이면 빈 링이 아니라 '다 찼다'로
                                    # 보이게 전체를 초록으로 칠합니다 — 회복 완료
                                    track=(C["teal"] if (np.isfinite(rc_left)
                                                         and rc_left <= 0)
                                           else C["pale"]),
                                    progress={"ok": C["teal"], "warn": C["amber"],
                                              "bad": C["red"]}.get(rc_tone, C["slate"]))
                        + f"<p class='rl-sub' style='margin:-6px 0 0;text-align:center'>"
                          f"{_rc_s or ''}</p>", unsafe_allow_html=True)

            ui.tiles([
                {"label": "단기 부하 (7일 누적)", "value": gv("AcuteLoad", "{:,.0f}"),
                 "sub": _al_s, "tone": _al_t,
                 "spark": hist_series(df_daily, "StatusDate", "AcuteLoad")},
                {"label": "고강도 (최근 7일)",
                 "value": f"{_int7_v:,.0f}" if np.isfinite(_int7_v) else "—",
                 "unit": "분",
                 "sub": (f"당일 {gv('IntensityMinutesDay', '{:,.0f}')}분 · {_im_s}"
                         if gv("IntensityMinutesDay", "{:,.0f}") != "—" and _im_s
                         else f"당일 {gv('IntensityMinutesDay', '{:,.0f}')}분"
                         if gv("IntensityMinutesDay", "{:,.0f}") != "—"
                         else "‘당일 고강도 분’을 넣으면 계산됩니다"),
                 "tone": _im_t,
                 "spark": _int7_pts},
            ], per_row_pc=2)
            card_link("📈 추이 · ⌚ 가민 추이", go=("trend", "garmin"))

    _g2 = ui.cols(2, 1)
    with _g2[0]:
        with ui.card("condcard"):
            # 컨디션은 '그날 아침' 값이라 하루만 지나도 오늘 상태가 아닙니다 → 1일부터 표시
            _cond_keys = ["BodyBattery", "TrainingReadiness", "HRVms", "SleepScore"]
            ui.head("🌙 가민 · 컨디션", "밤사이 확정되는 값 · " + date_span(_cond_keys))
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
            ], per_row_pc=2)
            if any(gage(k) is not None and gage(k) >= 1 for k in _cond_keys):
                st.caption("⚠️ 컨디션 값은 **그날 아침** 기준입니다. 날짜가 지난 값은 오늘 상태가 "
                           "아니니, ‘🏠 오늘 → ⌚ 아침 입력’에서 오늘 값을 넣어주세요.")
            st.caption("타일 안의 작은 선은 **최근 30회 입력분**입니다 (마우스를 올리면 날짜별 값).")
            card_link("📈 추이 · ⌚ 가민 추이", go=("trend", "garmin"))


    with _g2[1 % len(_g2)]:
        with ui.card("fitcard"):
            em = ana.endurance_meta(G.get("EnduranceScore"), AGE, SEX)
            hm = ana.hill_meta(G.get("HillScore"))
            lt_txt = str(G.get("LTPace") or "")
            # 기량 지표는 주 1회 갱신이라 며칠 지난 것이 정상 → 14일부터 표시
            _fit_keys = ["VO2Max", "FitnessAge", "EnduranceScore", "HillScore"]
            ui.head("🏅 가민 · 기량", date_span(_fit_keys))
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
            ], per_row_pc=2)
            # 버튼을 각자 설명하는 타일 바로 아래에 둡니다 (3번째·4번째 칸)
            pop = ui.cols(2, 1)
            with pop[0].popover("ℹ️ Endurance 등급"):
                st.markdown(tier_help_html(
                    em,
                    "<b>Endurance Score (지구력 점수)</b> — 심박이 기록된 모든 활동을 "
                    "누적해서 <i>장시간 버티는 능력</i>을 점수로 매긴 값입니다. "
                    "VO₂max가 ‘엔진 크기’라면 이건 ‘연료탱크’에 가깝습니다. "
                    "롱런·저강도 볼륨을 꾸준히 쌓으면 올라가고, 며칠 쉬어도 "
                    "잘 안 떨어집니다.",
                    "등급 기준이 나이대·성별마다 다릅니다."), unsafe_allow_html=True)
            with pop[1 % len(pop)].popover("ℹ️ Hill Score 등급"):
                st.markdown(tier_help_html(
                    hm,
                    "<b>Hill Score (언덕 점수)</b> — <i>오르막 달리기 능력</i>을 1~100으로 "
                    "매긴 값입니다. <b>경사 2% 이상</b> 구간이 있는 야외 러닝/걷기/하이킹만 "
                    "집계되고, 최근 2개월 훈련 이력과 VO₂max 추정치를 씁니다. "
                    "평지나 트레드밀 위주로 뛰면 아예 안 뜨거나 한참 뒤에 생깁니다.",
                    "나이·성별 구분 없이 같은 기준입니다."), unsafe_allow_html=True)
            card_link("📈 추이 · ⌚ 가민 추이", go=("trend", "garmin"))

    # ── 몸 — 체중·체성분 (러닝 기반 건강관리) ────────────────────────────
    _bd_home = ana.prepare_body(db.load_data("Body"))
    _bs_home = ana.body_summary(_bd_home) if not _bd_home.empty else pd.DataFrame()
    _g3 = ui.cols(2, 1)
    with _g3[0]:
        with ui.card("bodycard"):
            if _bd_home.empty:
                ui.head("⚖️ 몸", "체중·체성분")
                st.caption("‘❤️ 몸 → ⚖️ 체중 · 부상’에서 첫 측정을 넣으면 "
                           "여기에 최근 값과 변화가 보입니다. "
                           "매주 같은 요일·같은 조건에 재는 것이 핵심입니다.")
            else:
                _blast = _bd_home.iloc[-1]
                ui.head("⚖️ 몸", f"{_bd_home['MeasureDate'].iloc[-1]:%Y-%m-%d} 측정 · "
                                f"{_blast.get('Source') or '—'}")

                def _btile(col):
                    name, unit, fmt, good, _d = ana.BODY_META[col]
                    s_ = _bd_home[col].dropna() if col in _bd_home.columns \
                        else pd.Series(dtype=float)
                    if s_.empty:
                        return None
                    prev = s_.iloc[-5:-1]
                    dv = float(s_.iloc[-1] - prev.mean()) if len(prev) else np.nan
                    sub = (None if not np.isfinite(dv) else
                           f"{dv:+{_pyfmt(fmt)}} (이전 {len(prev)}회 평균 대비)")
                    tone = ("" if (good == 0 or not np.isfinite(dv) or dv == 0)
                            else ("ok" if dv * good > 0 else "warn"))
                    return {"label": name, "value": format(float(s_.iloc[-1]), fmt),
                            "unit": unit or None, "sub": sub, "tone": tone,
                            "spark": [float(x) for x in s_.tail(30)]}

                _bt = [t for t in (_btile("WeightKg"), _btile("BodyFatPct"),
                                   _btile("SkeletalMuscleKg"), _btile("BodyFatKg"))
                       if t]
                if _bt:
                    ui.tiles(_bt, per_row_pc=2)
                card_link("❤️ 몸 · ⚖️ 체중 · 부상", go=("body", "body"))
    with _g3[1 % len(_g3)]:
        with ui.card("gpred"):
            ui.head("🏁 가민 레이스 예측", gdate("Pred10K"))
            preds = ana.garmin_race_predictions(G)
            if any(v != "—" for _, v in preds):
                ui.rows(preds)
            else:
                st.caption("Garmin Connect의 레이스 예측 시간을 "
                           "‘❤️ 몸 → 📈 가민 측정’에 입력하세요.")
            card_link("📈 추이 · ⌚ 가민 추이", go=("trend", "garmin"))

    # ─────────────────────────────────────────────────────────────────
    # 가민 · Load Focus (레이스 예측은 위 '몸' 카드 옆으로 옮겼습니다)
    # ─────────────────────────────────────────────────────────────────
    if True:
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
                st.caption("‘❤️ 몸 → 📈 가민 측정’에서 Load Focus 3개 값을 입력하세요.")

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
                    "- **가민 만성 부하** — ‘평소 한 주치 부하’입니다(4주 평균). "
                    "28일치 합이 아니라 급성과 같은 저울 위의 값이라, "
                    "**급성 ÷ 만성 = 1**이면 이번 주가 평소만큼, "
                    "**1.2**면 20% 무겁다는 뜻입니다.\n"
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
        _cs, _ce, _ctxt = range_picker("curve_range", "3개월")
        show = clip_range(daily.reset_index(names="Date"), "Date", _cs, _ce)
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
                        dd = (pd.to_datetime(p["TargetDate"]).date() - today_local()).days
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
                        _pct = min(max((today_local() - _s).days / _span, 0.0), 1.0) * 100
                        st.markdown(
                            f"<div class='rl-row'><span class='k'>기간 진행</span>"
                            f"<span class='v'>{_pct:.0f}%</span></div>",
                            unsafe_allow_html=True)
                        ui.bar(_pct, "warn" if _pct > 85 else "")
                    except Exception:
                        pass
            else:
                st.caption("활성 프로젝트가 없습니다. ‘🎯 목표’ 화면에서 등록하세요.")

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
# 오늘 · morning
# ═════════════════════════════════════════════════════════════════════════
if SEC == "today":
    if SCR == "morning":
        with ui.card("gdaily"):
            ui.head("⌚ 가민 일일 지표", "Garmin Connect에서 보고 그대로 옮겨 적으세요")
            st.caption("가민 ‘트레이닝 준비 상태’ 화면을 그대로 옮겨 적고, 그 화면 "
                       "왼쪽 위의 **‘…에 업데이트됨’ 시각**을 `기준 시간`에 적으면 "
                       "됩니다. 훈련마다 붙는 **운동 부하**는 여기가 아니라 "
                       "‘➕ 훈련 입력 / 📥 파일 가져오기’에서 넣습니다.")
            # 하루에 두 번 넣게 되는 경우가 있습니다 — 아침에 적어 두고, 오후에
            # 훈련을 하면 **회복 시간과 단기 부하만** 달라집니다. 그때 폼 전체를
            # 다시 채우게 하면 아침에 적은 값을 덮어쓸 위험만 커집니다.
            _when = st.radio(
                "언제 넣나요", ["🌅 아침 (전체)", "🏃 훈련 뒤 (바뀐 것만)"],
                horizontal=True, key="am_when", label_visibility="collapsed")
            _pm = _when.startswith("🏃")
            if _pm:
                st.info("훈련을 하면 **회복 시간과 단기 부하**가 달라집니다 — 그것만 "
                        "다시 넣으세요. 아침에 적은 Readiness·HRV·수면·안정시 심박은 "
                        "**그대로 남습니다**(줄이 새로 생기지 않고 그 줄만 고쳐집니다). "
                        "`기준 시간`은 **지금 가민 화면에 떠 있는 시각**으로 두세요.")
            with st.form("f_daily_am", clear_on_submit=True):
                m0 = ui.cols(2, 1, keep_row=True)
                dd_ = m0[0].date_input("날짜", today_local(), key="am_date")
                # 훈련 뒤에 넣을 때 7시로 두면 회복 카운트다운이 통째로 어긋납니다
                _mt_def = (now_local().replace(second=0, microsecond=0).time()
                           if _pm else dtime(7, 0))
                mtime = m0[1 % len(m0)].time_input(
                    "기준 시간", _mt_def, step=300,
                    key=("am_time_pm" if _pm else "am_time"),
                    help="가민 ‘트레이닝 준비 상태’ 화면 왼쪽 위의 "
                         "‘…에 업데이트됨’ 시각을 그대로 넣으세요. "
                         "회복 시간을 ‘지금 기준 남은 시간’으로 되돌릴 때 씁니다.")
                # 밤사이 확정돼 그날 고정인 값들 — 훈련 뒤 모드에서는 안 보입니다
                tr = hrvms = slp = rhr = 0
                hrv = "Balanced"
                slh = sth = "(미입력)"
                if _pm:
                    bb = st.number_input(
                        "Body Battery (지금)", 0, 100, 0, key="am_bb",
                        help="훈련을 하면 줄어듭니다. 안 봤으면 0으로 두세요.")
                else:
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
                        "HRV 상태",
                        ["Balanced", "Unbalanced", "Low", "Poor", "No Status"],
                        key="am_hrvs")
                    m2 = ui.cols(4, 2, keep_row=True)
                    slp = grid_at(m2, 0, 4).number_input("수면 점수", 0, 100, 0,
                                                         key="am_slp")
                    rhr = grid_at(m2, 1, 4).number_input("안정시 심박", 0, 120, 0,
                                                         key="am_rhr")
                    slh = grid_at(m2, 2, 4).selectbox(
                        "최근 수면 점수", SLEEP_HIST_OPTS, key="am_slh",
                        help="가민 준비 상태 화면의 ‘최근 수면 점수’(최근 3일) 판정.")
                    sth = grid_at(m2, 3, 4).selectbox(
                        "최근 스트레스", STRESS_HIST_OPTS, key="am_sth",
                        help="가민 준비 상태 화면의 ‘최근 스트레스’(최근 3일) 판정.")
                    st.markdown(
                        "<p class='rl-sub' style='margin:12px 0 2px'>📌 같은 화면에 "
                        "함께 떠 있는 값 — 하루 동안 <b>움직이는 건 회복 시간과 "
                        "단기 부하</b> 둘뿐입니다. 위 <code>기준 시간</code> 시점에 "
                        "보이는 대로 넣으면 됩니다</p>",
                        unsafe_allow_html=True)
                m3 = ui.cols(4, 2, keep_row=True)
                a_ac = grid_at(m3, 0, 4).number_input(
                    "단기 부하 (급성)", 0, 3000, 0, key="am_acute",
                    help="최근 7일 운동 부하의 **누적(가중 합)**입니다 — 평균이 "
                         "아닙니다. 훈련이 들어오면 올라가고 쉬면 조금씩 내려갑니다. "
                         "**기준 시간에 보이는 값**을 그대로 넣으세요.")
                a_ch = grid_at(m3, 1, 4).number_input(
                    "만성 부하", 0, 3000, 0, key="am_chronic",
                    help="**평소 한 주치 부하**입니다 — 28일치를 다 더한 값이 "
                         "아니라 한 주 단위로 환산한 평균이라, 급성과 비슷한 "
                         "크기로 나옵니다. 넣어두면 부하 비율이 자동 계산됩니다.")
                a_rec = grid_at(m3, 2, 4).number_input(
                    "회복 시간 (h)", 0, 200, 0, key="am_rec",
                    help="훈련 종료부터 줄어드는 카운트다운입니다. 위 기준 시간부터 "
                         "이만큼 남았다고 보고, 대시보드에서는 ‘지금 기준 남은 시간’으로 "
                         "다시 계산해 보여줍니다.")
                a_im = (0 if _pm else grid_at(m3, 3, 4).number_input(
                    "고강도 분 (당일)", 0, 500, 0, key="am_im",
                    help="**어제 하루치**를 넣으세요. 주간 누적은 이 값을 7일 굴려 "
                         "앱이 계산합니다 — 가민의 주간 값은 롤링 7일이라 매일 "
                         "달라져서, 그걸 받아 적으면 추이가 읽히지 않습니다."))
                _ts_opts = ["(그대로 두기)"] + list(ana.TRAINING_STATUS.keys())
                ts = st.selectbox(
                    "Training Status", _ts_opts,
                    format_func=lambda k: (k if k == "(그대로 두기)" else
                                           f"{ana.TRAINING_STATUS_KR[k]} ({k})"),
                    key="am_ts",
                    help="어제 훈련까지 반영된 판정이 아침 화면에 떠 있습니다. "
                         "안 바뀌었으면 ‘그대로 두기’로 두세요.")
                a_lr = round(a_ac / a_ch, 3) if (a_ac and a_ch) else 0
                nt = st.text_input("메모", "", key="am_note")
                if st.form_submit_button("저장", width="stretch", type="primary"):
                    _at = datetime.combine(dd_, mtime)
                    _am_until = ((_at + timedelta(hours=float(a_rec))).strftime(
                        "%Y-%m-%d %H:%M") if a_rec else "")
                    # 움직이는 값 — 아침이든 훈련 뒤든 항상 보냅니다
                    _vals = {
                        "StatusID": new_id("DS"),
                        "EntryKind": "훈련 뒤" if _pm else "아침",
                        "TrainingStatus": "" if ts == "(그대로 두기)" else ts,
                        "BodyBattery": bb or "",
                        "AcuteLoad": a_ac or "", "ChronicLoad": a_ch or "",
                        "LoadRatio": a_lr or "",
                        "RecoveryTimeHr": a_rec or "",
                        "IntensityMinutesDay": a_im or "",
                        "RecoveryUntil": _am_until,
                        "Notes": nt,
                        "MeasuredAt": f"{_at:%Y-%m-%d %H:%M} (가민 업데이트 기준)"}
                    if not _pm:
                        # 밤사이 확정되는 값 — 아침에만 보냅니다
                        _vals.update({
                            "TrainingReadiness": tr or "",
                            "HRVStatus": hrv, "HRVms": hrvms or "",
                            "SleepScore": slp or "", "RestingHR": rhr or "",
                            "SleepHistory": "" if slh == "(미입력)" else slh,
                            "StressHistory": "" if sth == "(미입력)" else sth})
                    r = db.upsert_row(
                        "DailyStatus",
                        {"StatusDate": dd_.strftime("%Y-%m-%d")}, _vals)
                    flash(("훈련 뒤 값 " if _pm else "오늘 값 ")
                          + ("갱신" if r == "updated" else "저장") + " 완료")
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
             ("RecoveryTimeHr", "numopt", "회복 시간 (h)", None),
             ("TrainingReadiness", "numopt", "Readiness", None),
             ("BodyBattery", "numopt", "Body Battery", None),
             ("HRVms", "numopt", "HRV (ms)", None),
             ("HRVStatus", "select", "HRV 상태",
              ["Balanced", "Unbalanced", "Low", "Poor", "No Status"]),
             ("SleepScore", "numopt", "수면 점수", None),
             ("RestingHR", "numopt", "안정시 심박", None),
             ("IntensityMinutesDay", "numopt", "고강도 분 (당일)", None),
             ("IntensityMinutes", "numopt", "고강도 분 (가민 주간·예전 입력)", None),
             ("SleepHistory", "select", "최근 수면 점수", SLEEP_HIST_OPTS),
             ("StressHistory", "select", "최근 스트레스", STRESS_HIST_OPTS),
             ("Notes", "area", "메모", None)],
            key="daily",
            # 급성·만성이 둘 다 있으면 비율은 저장할 때 다시 계산합니다.
            # (직접 넣은 값이 있어도 계산값이 더 정확해서 덮어씁니다)
            derive=lambda v: ({"LoadRatio": round(fnum(v.get("AcuteLoad"))
                                                  / fnum(v.get("ChronicLoad")), 3)}
                              if fnum(v.get("AcuteLoad")) > 0
                              and fnum(v.get("ChronicLoad")) > 0 else {}),
            # 폼 안이라 방금 친 숫자는 저장을 눌러야 반영됩니다 — 아래 문구는
            # '지금 저장돼 있는 값' 기준이라고 못 박아 둡니다
            preview=lambda v: (
                f"지금 저장된 값 기준 부하 비율 "
                f"**{fnum(v.get('AcuteLoad')) / fnum(v.get('ChronicLoad')):.2f}** "
                f"— 급성 ÷ 만성으로, 저장을 누를 때 새로 계산됩니다"
                if fnum(v.get("AcuteLoad")) > 0 and fnum(v.get("ChronicLoad")) > 0
                else "만성 부하를 넣으면 부하 비율이 자동으로 계산됩니다"))

        # ── 하루 두 줄 합치기 — 아침/훈련 후로 나뉘어 있던 시절의 잔재 ──
        _dd = db.load_data("DailyStatus")
        if not _dd.empty and "StatusDate" in _dd.columns:
            _key = _dd["StatusDate"].astype(str).str.strip().str.slice(0, 10)
            _dupe_days = sorted(_key[_key.ne("") & _key.duplicated(keep=False)].unique())
            if _dupe_days:
                with ui.card("dailydupe"):
                    ui.head("🧹 하루 두 줄 합치기",
                            f"같은 날에 줄이 둘 이상인 날이 <b>{len(_dupe_days)}일</b> 있습니다")
                    st.caption("예전에 ‘아침 체크인’과 ‘훈련 후 체크인’으로 나뉘어 "
                               "있던 때 생긴 줄입니다. 추이 차트에 하루 두 점으로 "
                               "찍힙니다. 합치면 **항목마다 나중에 본 값**을 남기고 "
                               "빈 칸은 다른 줄의 값으로 채웁니다 — 값이 사라지지 "
                               "않습니다.")
                    st.caption("대상: " + ", ".join(_dupe_days[:8])
                               + (f" 외 {len(_dupe_days) - 8}일" if len(_dupe_days) > 8
                                  else ""))
                    if st.button(f"🧹 {len(_dupe_days)}일 합치기", width="stretch",
                                 key="daily_dupe_go"):
                        _merged = ana.merge_daily_rows(_dd)
                        db.write_sheet("DailyStatus", _merged)
                        flash(f"{len(_dd) - len(_merged)}줄을 합쳤습니다.")
                        st.rerun()


# ═════════════════════════════════════════════════════════════════════════
# 훈련 · hist
# ═════════════════════════════════════════════════════════════════════════
if SEC == "train":
    if SCR == "hist":
        df_w = db.load_data("Workouts")
        d = ana.prepare_workouts(df_w)

        # ---- 기간 선택 (기본: 이번 주) --------------------------------------
        with ui.card("period"):
            ui.head("🗓️ 기간", "주 · 월은 ◀ ▶ 로 넘기고, "
                             "<b>직접 지정</b>이면 시작~끝 날짜를 고릅니다")
            _mob = ui.is_mobile()
            _UNITS = ["주", "월", CUSTOM_RANGE, "전체"]
            # 칸 너비는 고른 단위에 따라 달라집니다(‘직접 지정’은 넓은 칸 하나).
            # 위젯을 만들기 전에 지난번 선택을 읽어 배치를 먼저 정합니다.
            _pu = st.session_state.get("hist_unit", "주")
            if _pu not in _UNITS:
                _pu = "주"
            if _mob:
                _c = None                       # 모바일은 줄을 나눠 씁니다
            elif _pu == CUSTOM_RANGE:
                _c = st.columns([0.95, 2.0, 1.25, 1.25])
                _ui, _fi = 0, (2, 3)
            elif _pu == "전체":
                _c = st.columns([0.95, 1.25, 1.25])
                _ui, _fi = 0, (1, 2)
            else:
                _c = st.columns([0.95, 0.3, 1.15, 0.3, 1.25, 1.25])
                _ui, _fi = 0, (4, 5)

            punit = (st if _mob else _c[_ui]).selectbox("단위", _UNITS,
                                                        key="hist_unit")

            if punit == CUSTOM_RANGE:
                _cell = st if _mob else _c[1]
                _d0 = st.session_state.get("hist_rng") or (
                    today_local() - timedelta(days=13), today_local())
                _picked = _cell.date_input("시작 ~ 끝", _d0, key="hist_rng")
                if isinstance(_picked, (tuple, list)):
                    p_start = _picked[0] if _picked else _d0[0]
                    # 끝 날짜를 아직 안 고른 사이에도 화면이 깨지지 않게 합니다
                    p_end = _picked[1] if len(_picked) > 1 else p_start
                else:
                    p_start = p_end = _picked
                if p_start > p_end:
                    p_start, p_end = p_end, p_start
            elif punit == "전체":
                p_start = p_end = None
            else:
                # [◀][기준 날짜][▶]를 모바일에서도 한 줄에 — 화살표는 좁게.
                # (Streamlit은 좁은 화면에서 컬럼을 세로로 쌓아서, ui.py의
                #  'rlrow' CSS로 이 묶음만 가로 유지시킵니다)
                if _mob:
                    _nav_box = st.container(key="rlrow_histnav")
                    with _nav_box:
                        _row = st.columns([0.3, 1.0, 0.3])
                else:
                    _row = None
                _cells = tuple(_row) if _mob else (_c[1], _c[2], _c[3])
                _slot = _cells[1].container()      # 날짜 자리를 먼저 잡아둡니다
                # 버튼은 date_input보다 먼저 '실행'되어야 세션 값을 바꿀 수 있습니다
                for _cell, _lab, _n, _key, _tip in (
                        (_cells[0], "◀", -1, "hist_prev", "이전 기간"),
                        (_cells[2], "▶", +1, "hist_next", "다음 기간")):
                    _cell.markdown("<div style='height:28px'></div>",
                                   unsafe_allow_html=True)
                    if _cell.button(_lab, width="stretch", key=_key, help=_tip):
                        st.session_state["hist_date"] = period_shift(
                            st.session_state.get("hist_date", today_local()), punit, _n)
                        st.rerun()
                with _slot:
                    anchor = st.date_input(
                        "기준 날짜", st.session_state.get("hist_date", today_local()),
                        key="hist_date")
                p_start, p_end = period_range(anchor, punit)

            if _mob:
                with st.container(key="rlrow_histfilter"):
                    _f = st.columns(2)
            else:
                _f = (_c[_fi[0]], _c[_fi[1]])
            sel_p = _f[0].selectbox("프로젝트", ["전체"] + list(proj_opts)[1:],
                                    key="hist_p")
            sel_t = _f[1].selectbox("유형", ["전체"] + WORKOUT_TYPES, key="hist_t")

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
                        f"운동 부하 {fnum(W.get('TrainingLoad')):.0f}"
                        if fnum(W.get("TrainingLoad")) > 0 else "",
                        f"케이던스 {fnum(W.get('AvgCadence')):.0f}"
                        if fnum(W.get("AvgCadence")) > 0 else "",
                        f"보폭 {fnum(W.get('AvgStrideM')):.2f}m"
                        if fnum(W.get("AvgStrideM")) > 0 else "",
                        f"접지 {fnum(W.get('AvgGCTms')):.0f}ms"
                        if fnum(W.get("AvgGCTms")) > 0 else "",
                        f"수직진동 {fnum(W.get('AvgVertOscCm')):.1f}cm"
                        if fnum(W.get("AvgVertOscCm")) > 0 else "",
                        f"수직비율 {fnum(W.get('AvgVertRatioPct')):.1f}%"
                        if fnum(W.get("AvgVertRatioPct")) > 0 else "",
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
                        if not rs.empty:
                            st.markdown(
                                "<p class='rl-sub' style='margin:10px 0 2px'>"
                                "<b>구간 평균</b> — 시간으로 가중한 평균입니다. "
                                "인터벌·템포런은 ‘반복’ 줄이 실제 훈련 강도이고, "
                                "‘전체’ 줄이 이 훈련의 평균입니다</p>",
                                unsafe_allow_html=True)
                            st.dataframe(
                                rs, width="stretch", hide_index=True,
                                column_config={
                                    k: st.column_config.NumberColumn(k, format=v)
                                    for k, v in ana.LAP_SUMMARY_FMT.items()
                                    if k in rs.columns})

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
                        # 러닝 폼 3종 — 값이 있을 때만 열을 붙입니다 (없으면 —만 늘어남)
                        for _lab, _c, _f in (("접지(ms)", "AvgGCTms", "{:.0f}"),
                                             ("수직진동(cm)", "AvgVertOscCm", "{:.1f}"),
                                             ("수직비율(%)", "AvgVertRatioPct", "{:.1f}")):
                            if (_c in CL.columns and pd.to_numeric(
                                    CL[_c], errors="coerce").fillna(0).abs().sum() > 0):
                                show_l[_lab] = CL[_c].map(lambda v, _ff=_f: vtxt(v, _ff))
                        if ui.is_mobile():
                            ui.item_list([
                                (f"랩 {int(r['랩'])} · {r['역할']} · {r['페이스']}",
                                 " · ".join([f"{r['거리(km)']}km", r["시간"],
                                             f"{r['평균심박']}bpm"]
                                            + ([f"수직비율 {r['수직비율(%)']}%"]
                                               if "수직비율(%)" in show_l.columns else [])))
                                for _, r in show_l.iterrows()])
                        else:
                            st.dataframe(show_l, width="stretch", hide_index=True)

                        # CSV에서 가져온 나머지 랩 항목 — 기본은 접어둡니다
                        _extra = [
                            ("GAP(경사보정)", "GapPaceSec", "pace"),
                            ("최대 페이스", "MaxPaceSec", "pace"),
                            ("최고 케이던스", "MaxCadence", "{:.0f}"),
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
                                _wdf = pd.DataFrame(_wide).astype(str)
                                # 맨 아래 평균 줄 — 시간으로 가중한 평균입니다
                                _avg = {"랩": "평균"}
                                for lab, cc, f in _have:
                                    m = ana.lap_wmean(CL, cc)
                                    _avg[lab] = ("—" if not np.isfinite(m) else
                                                 ana.pace_str(m) if f == "pace" else
                                                 ana.time_str(m * 60) if f == "dur" else
                                                 f.format(m))
                                _wdf.loc[len(_wdf)] = [_avg.get(c, "—") for c in _wdf.columns]
                                st.dataframe(_wdf, width="stretch", hide_index=True)
                                st.caption("가민 활동 상세 CSV에 들어 있는 랩 항목을 그대로 "
                                           "저장합니다. 값이 하나도 없는 항목은 표시하지 않습니다. "
                                           "맨 아랫줄은 시간으로 가중한 평균입니다.")

                        lp = CL[(CL["PaceSec"] > 0) & (CL["역할"] != "자투리")].copy()
                        if len(lp) > 1:
                            lp["페이스"] = lp["PaceSec"].apply(ana.pace_str)
                            mm_ss = ("floor(datum.value/60) + ':' + "
                                     "(datum.value%60 < 10 ? '0' : '') + "
                                     "format(round(datum.value%60), 'd')")
                            # 막대는 언제나 0부터 그려집니다. 페이스는 0:00이 기준이
                            # 아니어서, 막대로 그리면 5:00과 6:00이 거의 같아 보입니다
                            # → 점과 선으로 바꾸고 축을 뒤집어 '위쪽 = 빠름'으로.
                            _roles = [r for r in ana.LAP_ROLES
                                      if (lp["역할"] == r).any()]
                            _rmap = dict(zip(ana.LAP_ROLES,
                                             [C["slate"], C["accent"], C["teal"],
                                              C["violet"], C["primary"], C["pale"]]))
                            # 역할이 하나뿐이면(예: 지속주) 범례는 정보가 없습니다
                            _col = (alt.value(_rmap.get(_roles[0], C["primary"]))
                                    if len(_roles) <= 1 else
                                    alt.Color("역할:N", title=None,
                                              scale=alt.Scale(
                                                  domain=_roles,
                                                  range=[_rmap[r] for r in _roles]),
                                              legend=alt.Legend(orient="top",
                                                                direction="horizontal",
                                                                symbolType="circle",
                                                                symbolSize=90)))
                            _ysc = alt.Scale(zero=False, nice=True,
                                             reverse=True, padding=12)
                            # 세로로 눕힌 축 제목은 좁은 칸에서 글자가 세로로
                            # 쪼개져 읽히지 않습니다 → 차트 위 가로 한 줄로.
                            _y = alt.Y("PaceSec:Q", title=None,
                                       scale=_ysc,
                                       axis=alt.Axis(labelExpr=mm_ss, tickCount=5))
                            _x = alt.X("LapNo:O", title="랩",
                                       axis=alt.Axis(labelAngle=0),
                                       scale=alt.Scale(padding=10))
                            base = alt.Chart(lp)
                            line = base.mark_line(color=C["pale"], strokeWidth=1.5,
                                                  opacity=.8).encode(x=_x, y=_y)
                            pts = base.mark_point(size=110, filled=True,
                                                  opacity=.95).encode(
                                x=_x, y=_y, color=_col,
                                tooltip=[alt.Tooltip("LapNo", title="랩"),
                                         alt.Tooltip("역할"),
                                         alt.Tooltip("페이스"),
                                         alt.Tooltip("DistanceKm", title="거리(km)",
                                                     format=".2f"),
                                         alt.Tooltip("AvgHeartRate", title="평균심박",
                                                     format=",d")])
                            avg = base.mark_rule(strokeDash=[5, 4],
                                                 color=C["slate"]).encode(
                                y=alt.Y("mean(PaceSec):Q", scale=_ysc),
                                tooltip=[alt.Tooltip("mean(PaceSec):Q",
                                                     title="평균 페이스(초/km)",
                                                     format=".0f")])
                            st.altair_chart((line + avg + pts).properties(
                                height=ui.chart_height(240, 210),
                                title=panel_title("랩별 페이스 (위로 갈수록 빠름)")),
                                width="stretch")
                            st.caption("점선 = 이 훈련의 평균 페이스 · "
                                       "점이 위에 있을수록 빠른 구간입니다."
                                       + ("" if len(_roles) > 1 else
                                          f" (이 훈련은 전 구간이 ‘{_roles[0]}’입니다)"))

        if not view.empty:
            with ui.card("edit"):
                ui.head("✏️ 수정 / 삭제")
                opts = {f"{r.WorkoutDate:%Y-%m-%d} · {r.WorkoutType} · {r.DistanceKm:.2f}km": r.WorkoutID
                        for r in view.iloc[::-1].itertuples()}
                # 위 표에서 고른 훈련을 그대로 이어서 엽니다. 목록(기간·필터)이나
                # 표의 선택이 바뀌면 key가 바뀌어 예전 선택이 남아 있지 않습니다.
                _names = list(opts)
                _defi = next((i for i, k in enumerate(_names)
                              if str(opts[k]) == str(sel_wid)), 0)
                _pkey = "edit_pick_" + hashlib.md5(
                    ("|".join(_names) + f"@{sel_wid}").encode()).hexdigest()[:10]
                pick = st.selectbox("대상", _names, index=_defi, key=_pkey)
                wid = opts[pick]
                row = df_w[df_w["WorkoutID"] == wid].iloc[0]
                # 고른 값이 목록에 없을 때(예: 지워진 러닝화)를 대비한 index 계산
                def _idx_of(options: dict, value, default=0) -> int:
                    v = str(value or "")
                    return next((i for i, k in enumerate(options)
                                 if str(options[k]) == v), default)

                with st.form("f_edit"):
                    g = ui.cols(3, 1, keep_row=True)
                    e_date = g[0].date_input("날짜", pd.to_datetime(row["WorkoutDate"]).date())
                    e_type = g[1 % len(g)].selectbox("유형", WORKOUT_TYPES,
                                                     index=WORKOUT_TYPES.index(row["WorkoutType"])
                                                     if row["WorkoutType"] in WORKOUT_TYPES else 0)
                    e_proj = g[2 % len(g)].selectbox(
                        "프로젝트", list(proj_opts),
                        index=_idx_of(proj_opts, row.get("ProjectID")))

                    h = ui.cols(3, 1, keep_row=True)
                    e_dist = h[0].number_input("거리(km)", 0.0, 300.0, fnum(row["DistanceKm"]),
                                               0.01, format="%.2f")
                    e_min = h[1 % len(h)].number_input("시간(분)", 0.0, 1500.0,
                                                       fnum(row["DurationMinutes"]), 0.5)
                    e_hr = h[2 % len(h)].number_input("평균심박", 0, 250,
                                                      int(fnum(row.get("AvgHeartRate"))))

                    i_ = ui.cols(4, 1, keep_row=True)
                    e_hrmax = i_[0].number_input("최고심박", 0, 250,
                                                 int(fnum(row.get("MaxHeartRate"))))
                    e_elev = i_[1 % len(i_)].number_input("상승고도(m)", 0, 5000,
                                                          int(fnum(row.get("ElevationGainM"))))
                    e_temp = i_[2 % len(i_)].number_input("기온(°C)", -30.0, 50.0,
                                                          fnum(row.get("Temperature")), 0.5)
                    e_cad = i_[3 % len(i_)].number_input("케이던스", 0, 250,
                                                         int(fnum(row.get("AvgCadence"))))

                    j_ = ui.cols(3, 1, keep_row=True)
                    e_shoe = j_[0].selectbox(
                        "러닝화", list(shoe_opts),
                        index=_idx_of(shoe_opts, row.get("ShoeID")))
                    e_surf = j_[1 % len(j_)].selectbox(
                        "노면", SURFACES,
                        index=SURFACES.index(row["Surface"])
                        if row.get("Surface") in SURFACES else 0)
                    e_rpe = j_[2 % len(j_)].number_input(
                        "RPE (체감강도)", 0, 10, int(fnum(row.get("RPE"))),
                        help="0이면 입력하지 않은 것으로 둡니다")

                    with st.expander("가민 트레이닝 효과 · 운동 부하 · 피로도 (선택)"):
                        k_ = ui.cols(4, 1, keep_row=True)
                        e_ate = k_[0].number_input("유산소 TE", 0.0, 5.0,
                                                   fnum(row.get("AerobicTE")), 0.1)
                        e_nte = k_[1 % len(k_)].number_input("무산소 TE", 0.0, 5.0,
                                                             fnum(row.get("AnaerobicTE")), 0.1)
                        e_pb = k_[2 % len(k_)].selectbox(
                            "Primary Benefit", ana.PRIMARY_BENEFIT,
                            index=ana.PRIMARY_BENEFIT.index(row["PrimaryBenefit"])
                            if row.get("PrimaryBenefit") in ana.PRIMARY_BENEFIT else 0)
                        e_load = k_[3 % len(k_)].number_input(
                            "운동 부하", 0, 1000, int(fnum(row.get("TrainingLoad"))),
                            help="가민 활동 상세의 ‘운동 부하(Training Load)’")
                        l_ = ui.cols(2, 1, keep_row=True)
                        e_leg = l_[0].number_input("다리 피로", 0, 10,
                                                   int(fnum(row.get("LegFatigue"))))
                        e_car = l_[1 % len(l_)].number_input("심폐 피로", 0, 10,
                                                             int(fnum(row.get("CardioFatigue"))))

                    e_note = st.text_area("메모", str(row.get("Notes", "") or ""), height=70)

                    q = ui.cols(2, 2, keep_row=True)
                    if q[0].form_submit_button("💾 수정 저장", width="stretch", type="primary"):
                        idx = df_w["WorkoutID"] == wid
                        set_cells(df_w, idx, {
                            "WorkoutDate": e_date.strftime("%Y-%m-%d"),
                            "WorkoutType": e_type, "ProjectID": proj_opts[e_proj],
                            "DistanceKm": e_dist,
                            "DurationMinutes": e_min, "AvgHeartRate": e_hr,
                            "MaxHeartRate": e_hrmax, "ElevationGainM": e_elev,
                            "Temperature": e_temp, "AvgCadence": e_cad,
                            "ShoeID": shoe_opts[e_shoe], "Surface": e_surf,
                            "RPE": e_rpe, "AerobicTE": e_ate, "AnaerobicTE": e_nte,
                            "PrimaryBenefit": e_pb, "TrainingLoad": e_load,
                            "LegFatigue": e_leg,
                            "CardioFatigue": e_car, "Notes": e_note,
                            "PaceSec": (round(e_min * 60 / e_dist, 1)
                                        if e_dist > 0 else "")})
                        db.write_sheet("Workouts", df_w)
                        flash("수정 완료")
                        st.rerun()
                    if q[1].form_submit_button("🗑️ 삭제", width="stretch"):
                        db.write_sheet("Workouts", df_w[df_w["WorkoutID"] != wid])
                        flash("삭제 완료", icon="⚠️")
                        st.rerun()

                # ---- 프로젝트만 여러 건 한꺼번에 -----------------------------
                # CSV로 가져온 기록은 프로젝트가 비어 있습니다. 한 건씩 고치면
                # 끝이 없어서, 조건에 맞는 기록을 골라 한 번에 넣습니다.
                if len(proj_opts) > 1:
                    with st.expander("📁 프로젝트 한꺼번에 지정"):
                        _pid_txt = (df_w["ProjectID"].astype(str).str.strip()
                                    .replace({"nan": "", "None": "", "<NA>": ""}))
                        _blank = df_w[_pid_txt == ""]
                        _in_view = df_w[df_w["WorkoutID"].isin(view["WorkoutID"])]
                        _scopes = {
                            f"프로젝트가 비어 있는 훈련 전체 ({len(_blank)}건)": _blank,
                            f"지금 보고 있는 기간의 훈련 전체 ({len(_in_view)}건)": _in_view,
                        }
                        bs = ui.cols(2, 1, keep_row=True)
                        b_scope = bs[0].selectbox("대상", list(_scopes), key="bulk_scope")
                        b_proj = bs[1 % len(bs)].selectbox(
                            "넣을 프로젝트", [k for k in proj_opts if k != "(없음)"],
                            key="bulk_proj")
                        _tgt = _scopes[b_scope]
                        if _tgt.empty:
                            st.caption("해당하는 훈련이 없습니다.")
                        else:
                            _d0 = pd.to_datetime(_tgt["WorkoutDate"], errors="coerce")
                            st.caption(f"{len(_tgt)}건 · "
                                       f"{_d0.min():%Y-%m-%d} ~ {_d0.max():%Y-%m-%d} 의 "
                                       f"프로젝트를 **{b_proj}** 로 바꿉니다. "
                                       "이미 다른 프로젝트가 들어 있던 기록도 덮어씁니다.")
                            if st.button(f"📁 {len(_tgt)}건에 지정", key="bulk_go",
                                         width="stretch"):
                                set_cells(df_w, df_w["WorkoutID"].isin(_tgt["WorkoutID"]),
                                          {"ProjectID": proj_opts[b_proj]})
                                db.write_sheet("Workouts", df_w)
                                flash(f"{len(_tgt)}건에 ‘{b_proj}’ 를 넣었습니다.")
                                st.rerun()


# ═════════════════════════════════════════════════════════════════════════
# 훈련 · new
# ═════════════════════════════════════════════════════════════════════════
if SEC == "train":
    if SCR == "new":
        with ui.card("newrun"):
            ui.head("➕ 훈련 기록 추가")
            with st.form("f_new_workout", clear_on_submit=True):
                a = ui.cols(3, 1, keep_row=True)
                w_date = a[0].date_input("날짜", today_local())
                w_type = a[1 % len(a)].selectbox("유형", WORKOUT_TYPES)
                w_proj = a[2 % len(a)].selectbox("프로젝트", list(proj_opts))
                with st.expander("❓ 훈련 유형이 각각 뭔가요"):
                    st.markdown(WORKOUT_TYPE_MD)

                b_ = ui.cols(3, 2, keep_row=True)
                w_dist = b_[0].number_input("거리 (km)", 0.0, 300.0, 8.0, 0.01, format="%.2f")
                w_min = b_[1 % len(b_)].number_input("시간 (분)", 0.0, 1500.0, 50.0, 0.5)
                w_hr = b_[2 % len(b_)].number_input("평균 심박", 0, 250, 0)

                c_ = ui.cols(4, 2, keep_row=True)
                w_hrmax = c_[0].number_input("최고 심박", 0, 250, 0)
                w_elev = c_[1 % len(c_)].number_input("상승고도 (m)", 0, 5000, 0)
                w_temp = c_[2 % len(c_)].number_input("기온 (°C)", -30.0, 50.0, 20.0, 0.5)
                w_cad = c_[3 % len(c_)].number_input("케이던스", 0, 250, 0)

                d_ = ui.cols(3, 1, keep_row=True)
                w_shoe = d_[0].selectbox("러닝화", list(shoe_opts))
                w_surf = d_[1 % len(d_)].selectbox("노면", SURFACES)
                w_rpe = d_[2 % len(d_)].slider("RPE (체감강도)", 1, 10, 5)

                st.markdown("<p class='rl-sub' style='margin:10px 0 2px'>"
                            "가민 트레이닝 효과 · <b>운동 부하</b> (선택)</p>",
                            unsafe_allow_html=True)
                te = ui.cols(4, 2, keep_row=True)
                w_ate = te[0].number_input("유산소 TE", 0.0, 5.0, 0.0, 0.1)
                w_nte = te[1 % len(te)].number_input("무산소 TE", 0.0, 5.0, 0.0, 0.1)
                w_pb = te[2 % len(te)].selectbox("Primary Benefit", ana.PRIMARY_BENEFIT)
                w_load = te[3 % len(te)].number_input(
                    "운동 부하", 0, 1000, 0,
                    help="가민 활동 상세의 ‘운동 부하(Training Load)’입니다. "
                         "날짜별로 더해서 ‘가민 추이 → 일일 운동 부하’ 막대로 보여줍니다.")

                e_ = ui.cols(2, 1, keep_row=True)
                w_leg = e_[0].slider("다리 피로", 1, 10, 3)
                w_car = e_[1 % len(e_)].slider("심폐 피로", 1, 10, 3)
                w_note = st.text_area("메모", height=70, placeholder="코스, 컨디션, 특이사항…")

                # 폼 안의 값은 저장을 눌러야 파이썬으로 넘어옵니다. 그래서 여기에
                # 페이스를 미리 계산해 두면 **방금 친 숫자가 아니라 직전 값**이
                # 보입니다(8km/50분 → 6:15 처럼). 저장 직후 알림에서 실제 거리와
                # 페이스를 확인시키는 쪽이 맞습니다.
                st.caption("거리와 시간을 넣고 저장하면 페이스가 계산됩니다.")

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
                            "PrimaryBenefit": w_pb, "TrainingLoad": w_load or "",
                            "RPE": w_rpe,
                            "LegFatigue": w_leg, "CardioFatigue": w_car, "Notes": w_note,
                            "SourceKey": src_key(w_date, w_dist, w_min),
                        }
                        db.append_rows("Workouts", pd.DataFrame([row]))
                        flash(f"저장 완료 — {w_dist:.2f}km / {ana.pace_str(w_min*60/w_dist)}")
                        st.rerun()


# ═════════════════════════════════════════════════════════════════════════
# 훈련 · imp
# ═════════════════════════════════════════════════════════════════════════
if SEC == "train":
    if SCR == "imp":
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
            # 가민 활동 목록 CSV의 '운동 부하' — 날짜별로 더해 일일 부하로 씁니다
            "TrainingLoad":    ["운동 부하", "훈련 부하", "트레이닝 부하",
                                "training load"],
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

        # ── .fit 가져오기 — 시계가 쓴 원본 ────────────────────────────────
        with ui.card("fitimp"):
            ui.head("⌚ 가민 .fit 파일 가져오기",
                    "시계가 직접 쓴 원본입니다 — <b>눈으로 옮겨 적을 게 "
                    "거의 없습니다</b>")
            st.caption("받는 곳: **Garmin Connect 웹 → 활동 하나 열기 → "
                       "우상단 ⚙ → 원본 파일 내보내기** → 받은 zip 안의 "
                       "`*_ACTIVITY.fit`. 여러 개를 한 번에 올려도 됩니다.")
            fups = st.file_uploader("fit 파일", type=["fit"], key="fitup",
                                    accept_multiple_files=True,
                                    label_visibility="collapsed")
            if not fups:
                ui.rows([
                    ("자동으로 들어오는 것",
                     "거리 · 시간 · 심박 · 케이던스 · 상승고도 · 기온 · "
                     "유산소/무산소 TE · <b>운동 부하</b> · 주요 효과 · "
                     "접지/수직진동/수직비율/보폭 · 파워 · 시계에서 매긴 RPE"),
                    ("랩", "랩마다 같은 값 전부 + <b>시계가 붙인 구간 역할</b>"
                           "(워밍업/반복/회복/쿨다운)"),
                    ("1초 기록으로 계산", "심박 디커플링 · 전후반 폼 변화"),
                    ("안 들어오는 것",
                     "Readiness · Body Battery · HRV · 수면 — 활동 파일에 "
                     "없습니다. ‘🏠 오늘 → ⌚ 아침 입력’에서 넣으세요."),
                ])
            else:
                _fres, _ferr = [], []
                for _f in fups:
                    try:
                        _fres.append(ana.fit_read(_f.getvalue(), _f.name))
                    except Exception as _e:                # noqa: BLE001
                        _ferr.append(f"{_f.name} — {_e}")
                for _m in _ferr:
                    st.error(_m)
                _fres = [r for r in _fres if r.get("workout", {}).get("WorkoutDate")]
                if not _fres:
                    st.warning("읽을 수 있는 활동이 없습니다.")
                else:
                    _wall = db.load_data("Workouts")
                    _match = [ana.fit_match(r["workout"], _wall) for r in _fres]
                    _MODES = ["새로 추가", "빈 칸만 채우기", "시계 값으로 교체", "건너뛰기"]
                    _tbl = []
                    for _i, _r in enumerate(_fres):
                        _w, _m = _r["workout"], _match[_i]
                        _cur_t = (str(_m["row"].get("WorkoutType", ""))
                                  if _m["row"] is not None else "")
                        _tbl.append({
                            "처리": ("새로 추가" if _m["status"] == "new" else
                                    "건너뛰기" if _m["status"] == "many" else
                                    "빈 칸만 채우기"),
                            "날짜": _w["WorkoutDate"],
                            "유형": _w["WorkoutType"],
                            "거리(km)": float(_w["DistanceKm"]),
                            "시간(분)": round(float(_w["DurationMinutes"]), 1),
                            "심박": _w["AvgHeartRate"] or "",
                            "부하": _w["TrainingLoad"] or "",
                            "주요 효과": _w["PrimaryBenefit"] or "",
                            "랩": len(_r["laps"]),
                            "맞춘 기록": _m["why"] + (
                                f" · 지금 유형 {_cur_t}" if _cur_t
                                and _cur_t != _w["WorkoutType"] else ""),
                        })
                    _fdf = pd.DataFrame(_tbl)
                    st.caption(
                        "**처리** 칸에서 파일마다 무엇을 할지 고릅니다.  \n"
                        "· **새로 추가** — 새 훈련으로 넣습니다  \n"
                        "· **빈 칸만 채우기** — 이미 있는 훈련의 **비어 있는 칸만** "
                        "채웁니다. 적어 둔 값은 그대로 둡니다  \n"
                        "· **시계 값으로 교체** — 손으로 어림잡아 넣은 거리·시간·"
                        "심박까지 **시계 값으로 고칩니다**. 프로젝트·러닝화·메모·"
                        "피로도는 어느 모드에서도 건드리지 않습니다  \n"
                        "같은 날 비슷한 기록이 둘 이상이면 **건너뛰기**로 둡니다 — "
                        "어느 것인지 앱이 정하지 않습니다.  \n"
                        "**거리(km)** 칸은 고칠 수 있습니다(트레드밀 보정). 고치면 "
                        "랩 거리와 페이스도 같은 비율로 맞춰 넣습니다."
                    )
                    _fed = st.data_editor(
                        _fdf, hide_index=True, width="stretch", key="fited",
                        column_config={
                            "처리": st.column_config.SelectboxColumn(
                                "처리", options=_MODES, width="medium"),
                            "유형": st.column_config.SelectboxColumn(
                                "유형", options=WORKOUT_TYPES, width="small"),
                            "거리(km)": st.column_config.NumberColumn(
                                "거리(km)", min_value=0.0, max_value=300.0,
                                step=0.01, format="%.2f"),
                        },
                        disabled=["날짜", "시간(분)", "심박", "부하", "주요 효과",
                                  "랩", "맞춘 기록"])

                    _fc = ui.cols(3, 1, keep_row=True)
                    _fproj = _fc[0].selectbox("프로젝트 (새로 추가할 때만)",
                                              list(proj_opts), key="fit_proj")
                    _fshoe = _fc[1 % len(_fc)].selectbox("러닝화 (새로 추가할 때만)",
                                                         list(shoe_opts), key="fit_shoe")
                    _fnote = _fc[2 % len(_fc)].text_input("메모 (새로 추가할 때만)", "",
                                                          key="fit_note")

                    # ── 미리보기 — 무엇이 바뀌는지 저장 전에 그대로 보여 줍니다 ──
                    for _i, _r in enumerate(_fres):
                        _w, _m = _r["workout"], _match[_i]
                        _row = _fed.iloc[_i]
                        _mode = str(_row["처리"])
                        with st.expander(f"🔎 {_w['WorkoutDate']} · "
                                         f"{_w['DistanceKm']:.2f}km · {_mode}"):
                            if _mode in ("빈 칸만 채우기", "시계 값으로 교체") \
                                    and _m["row"] is not None:
                                _pl = ana.fit_plan(
                                    _w, _m["row"],
                                    "fill" if _mode == "빈 칸만 채우기" else "replace",
                                    wtype=str(_row["유형"]))
                                _cg = _pl["changes"]
                                if _cg.empty:
                                    st.caption("바뀌는 칸이 없습니다.")
                                else:
                                    _nch = int((_cg["결과"] == "바꿈").sum())
                                    st.markdown(
                                        f"**{len(_cg)}칸** 손댑니다 — 채움 "
                                        f"{len(_cg) - _nch} · **덮어씀 {_nch}**")
                                    st.dataframe(_cg, hide_index=True, width="stretch")
                            elif _mode == "건너뛰기":
                                st.caption(_m["why"] or "건너뜁니다.")
                            for _msg in _r["warnings"]:
                                st.info(_msg)
                            _d = _r["decoupling"]
                            if np.isfinite(_d):
                                _t, _v = ana.decoupling_verdict(_d)
                                st.markdown(
                                    ui.pill(f"심박 디커플링 {_d:+.1f}% — {_v}", _t),
                                    unsafe_allow_html=True)
                            if _r["form"]:
                                st.markdown("<p class='rl-sub' style='margin:10px 0 2px'>"
                                            "전반 → 후반</p>", unsafe_allow_html=True)
                                ui.rows([(_k, f"{_a:,.1f} → {_b:,.1f}")
                                         for _k, (_a, _b) in _r["form"].items()])
                            if len(_r["laps"]):
                                st.dataframe(
                                    _r["laps"].drop(columns=["_trigger"], errors="ignore"),
                                    hide_index=True, width="stretch")
                            _z = _r.get("zones") or {}
                            if _z.get("bounds"):
                                st.caption("시계가 쓰던 심박존 경계 "
                                           f"{_z['bounds']} · LTHR {_z.get('lthr')} · "
                                           f"최대 {_z.get('max')} · 안정시 {_z.get('rest')}")

                    # 무엇을 덮어쓰게 되는지 **펼쳐 보지 않아도** 알 수 있게
                    # 미리 세어 둡니다 — 저장 버튼에 그대로 적습니다.
                    _cnt = {"새로": 0, "채움": 0, "덮어씀": 0, "건너뜀": 0}
                    _over = []
                    for _i, _r in enumerate(_fres):
                        _row = _fed.iloc[_i]
                        _mo = str(_row["처리"])
                        if _mo == "건너뛰기":
                            _cnt["건너뜀"] += 1
                            continue
                        if _mo == "새로 추가":
                            _cnt["새로"] += 1
                            continue
                        if _match[_i]["row"] is None:
                            _cnt["건너뜀"] += 1
                            continue
                        _pl0 = ana.fit_plan(
                            _r["workout"], _match[_i]["row"],
                            "fill" if _mo == "빈 칸만 채우기" else "replace",
                            wtype=str(_row["유형"]))
                        _c0 = _pl0["changes"]
                        _nb = int((_c0["결과"] == "바꿈").sum()) if len(_c0) else 0
                        _cnt["채움"] += (len(_c0) - _nb)
                        _cnt["덮어씀"] += _nb
                        if _nb:
                            _over.append(f"{_r['workout']['WorkoutDate']} "
                                         f"{_nb}칸")
                    if _cnt["덮어씀"]:
                        st.warning(
                            f"⚠️ **이미 적혀 있는 값 {_cnt['덮어씀']}칸을 "
                            f"덮어씁니다** ({' · '.join(_over)}). 어느 칸이 어떻게 "
                            "바뀌는지는 위의 🔎 를 펼쳐 보세요. 되돌리려면 아래 "
                            "백업을 먼저 받아 두셔야 합니다.")
                    st.download_button(
                        "⬇️ 지금 상태 백업 받기 (엑셀)", db.export_excel_bytes(),
                        file_name=f"running-life-os-backup-{today_local():%Y%m%d}.xlsx",
                        mime=("application/vnd.openxmlformats-officedocument"
                              ".spreadsheetml.sheet"),
                        width="stretch", key="fitbak")

                    _blabel = " · ".join(
                        [x for x in (f"새로 {_cnt['새로']}건" if _cnt["새로"] else "",
                                     f"빈 칸 {_cnt['채움']}칸" if _cnt["채움"] else "",
                                     f"⚠️ 덮어씀 {_cnt['덮어씀']}칸"
                                     if _cnt["덮어씀"] else "",
                                     f"건너뜀 {_cnt['건너뜀']}건"
                                     if _cnt["건너뜀"] else "") if x]) or "할 일 없음"
                    if st.button(f"💾 적용 — {_blabel}", width="stretch",
                                 type="primary", key="fitsave"):
                        _n = _filled = _repl = _skip = 0
                        for _i, _r in enumerate(_fres):
                            _row = _fed.iloc[_i]
                            _mode = str(_row["처리"])
                            if _mode == "건너뛰기":
                                _skip += 1
                                continue
                            _rr = ana.fit_rescale(_r, float(_row["거리(km)"]))
                            _w = _rr["workout"]
                            _m = _match[_i]
                            _wtype = str(_row["유형"])

                            if _mode == "새로 추가":
                                _wid = new_id("WO")
                                _out = {kk: vv for kk, vv in _w.items()
                                        if not kk.startswith("_")}
                                _out.update({
                                    "WorkoutID": _wid, "ProjectID": proj_opts[_fproj],
                                    "ShoeID": shoe_opts[_fshoe], "WorkoutType": _wtype,
                                    "Notes": _fnote or f"fit 가져오기 ({_r.get('name', '')})",
                                    "SourceKey": src_key(_w["WorkoutDate"],
                                                         _w["DistanceKm"],
                                                         _w["DurationMinutes"])})
                                db.append_rows("Workouts", pd.DataFrame([_out]))
                                _n += 1
                            else:
                                if _m["row"] is None:
                                    _skip += 1
                                    continue
                                _wid = str(_m["row"]["WorkoutID"])
                                _pl = ana.fit_plan(
                                    _w, _m["row"],
                                    "fill" if _mode == "빈 칸만 채우기" else "replace",
                                    wtype=_wtype)
                                _vals = dict(_pl["values"])
                                if _vals:
                                    # 거리·시간이 바뀌면 중복 판정 키도 다시 만듭니다
                                    _vals["SourceKey"] = src_key(
                                        _vals.get("WorkoutDate", _m["row"].get("WorkoutDate")),
                                        _vals.get("DistanceKm",
                                                  _m["row"].get("DistanceKm")),
                                        _vals.get("DurationMinutes",
                                                  _m["row"].get("DurationMinutes")))
                                    db.update_row("Workouts", "WorkoutID", _wid, _vals)
                                if _mode == "빈 칸만 채우기":
                                    _filled += 1
                                else:
                                    _repl += 1

                            # 랩 — 이미 있으면 건드리지 않습니다
                            _Lo = db.load_data("Laps")
                            _has = (not _Lo.empty
                                    and (_Lo["WorkoutID"].astype(str) == _wid).any())
                            _L = _rr["laps"]
                            if not _has and _L is not None and len(_L):
                                _L = _L.drop(columns=["_trigger"], errors="ignore").copy()
                                _L["WorkoutDate"] = _w["WorkoutDate"]
                                _L["WorkoutType"] = _wtype
                                _L.insert(0, "WorkoutID", _wid)
                                _L.insert(0, "LapID", [f"LAP-{_wid[-8:]}-{j+1:02d}"
                                                       for j in range(len(_L))])
                                db.append_rows("Laps", _L)

                        _parts = [x for x in (f"{_n}건 새로 추가" if _n else "",
                                              f"{_filled}건 빈 칸 채움" if _filled else "",
                                              f"{_repl}건 교체" if _repl else "",
                                              f"{_skip}건 건너뜀" if _skip else "") if x]
                        if _n or _filled or _repl:
                            flash(" · ".join(_parts))
                            st.rerun()
                        else:
                            st.warning("적용할 것이 없습니다. " + " · ".join(_parts))


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
                            w_date = d1[0].date_input("훈련 날짜 *", today_local(), key="imp_date")
                            w_type2 = d1[1 % len(d1)].selectbox("유형 *", WORKOUT_TYPES, key="imp_type")
                            proj_i = d1[2 % len(d1)].selectbox("프로젝트", list(proj_opts), key="imp_proj")
                            d2 = ui.cols(3, 1, keep_row=True)
                            shoe_i = d2[0].selectbox("러닝화", list(shoe_opts), key="imp_shoe")
                            surf_i = d2[1 % len(d2)].selectbox("노면", SURFACES, key="imp_surf")
                            rpe_i = d2[2 % len(d2)].slider("RPE (체감강도)", 1, 10, 5, key="imp_rpe")

                            st.markdown("<p class='rl-sub' style='margin:12px 0 2px'>"
                                        "가민 트레이닝 효과 · <b>운동 부하</b> · 컨디션 (선택)</p>",
                                        unsafe_allow_html=True)
                            d3 = ui.cols(4, 1, keep_row=True)
                            ate_i = d3[0].number_input("유산소 TE", 0.0, 5.0, 0.0, 0.1, key="imp_ate")
                            nte_i = d3[1 % len(d3)].number_input("무산소 TE", 0.0, 5.0, 0.0, 0.1,
                                                                 key="imp_nte")
                            pb_i = d3[2 % len(d3)].selectbox("Primary Benefit", ana.PRIMARY_BENEFIT,
                                                             key="imp_pb")
                            load_i = d3[3 % len(d3)].number_input(
                                "운동 부하", 0, 1000, 0, key="imp_load",
                                help="랩 CSV에는 들어 있지 않습니다 — 가민 활동 화면의 "
                                     "‘운동 부하’를 보고 넣어 주세요.")
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
                                        "PrimaryBenefit": pb_i, "TrainingLoad": load_i or "",
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
                                    flash(f"저장 완료 — {tot_d:.2f}km · 랩 {len(L2)}개")
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
                            fixed_date = st.date_input("적용 날짜", today_local(), key="imp_fixdate")
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
                                    dt = (fixed_date or today_local()).strftime("%Y-%m-%d")
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
                                          "AvgVertOscCm", "AvgVertRatioPct",
                                          "TrainingLoad"]:
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
                            flash(f"{len(rows)}건 추가 · 중복 {dup}건 · 건너뜀 {skip}건")
                            st.rerun()


# ═════════════════════════════════════════════════════════════════════════
# 추이 · garmin
# ═════════════════════════════════════════════════════════════════════════
if SEC == "trend":
    if SCR == "garmin":
        gd = db.load_data("DailyStatus")
        gm = db.load_data("Metrics")
        gw = ana.prepare_workouts(db.load_data("Workouts"))

        _has_load = (not gw.empty and "TrainingLoad" in gw.columns
                     and pd.to_numeric(gw["TrainingLoad"], errors="coerce").gt(0).any())
        _has_body = not db.load_data("Body").empty
        if gd.empty and gm.empty and not _has_load and not _has_body:
            st.info("‘🏠 오늘 → ⌚ 아침 입력 / 📈 가민 측정’에서 값을 입력하면 여기에 추이가 그려집니다.")
        else:
            with ui.card("gperiod"):
                ui.head("📅 기간", "대시보드 타일은 최근 값만 보여줍니다 — "
                                 "전체 추세는 이 화면에서 봅니다")
                g_s, g_e, g_txt = range_picker("garmin_range", "3개월")
                st.caption(f"{g_txt} · 입력된 날만 점으로 찍힙니다.")

            def _clip(df, datecol):
                """선택한 기간으로 자릅니다."""
                return clip_range(df, datecol, g_s, g_e)

            def _prep(df, datecol):
                """날짜를 만들고 기간으로 자릅니다."""
                if df is None or df.empty or datecol not in df.columns:
                    return df if df is not None else pd.DataFrame()
                o = df.copy()
                o[datecol] = pd.to_datetime(o[datecol], errors="coerce")
                return _clip(o.dropna(subset=[datecol]).sort_values(datecol), datecol)

            # 7일 누적은 **자르기 전** 전체에서 굴려야 기간 첫 주가 맞습니다
            gdv = _prep(ana.add_intensity_rolling(gd), "StatusDate")
            gmv = _prep(gm, "MetricDate")

            # ── 최근 추이 한눈에 — 일일 지표·측정값을 한 날짜 축에 세웁니다 ──
            with ui.card("gtrend"):
                ui.head("📉 최근 추이 한눈에",
                        "옮겨 적은 값을 <b>같은 날짜 축</b> 위에 한 칸씩 세웁니다 — "
                        "가민 Connect의 ‘최근 추이’와 같은 방식 · "
                        "RUNALYZE 값도 목록에 함께 있습니다")
                # 훈련은 하루에 여러 건이라 analytics 쪽에서 날짜별로 더합니다
                _gwv = _clip(gw, "WorkoutDate")
                _gbv = _clip(ana.prepare_body(db.load_data("Body")), "MeasureDate")
                _av = ana.trend_available(gdv, gmv, _gwv, _gbv)
                if not _av:
                    st.caption("‘🏠 오늘 → ⌚ 아침 입력 / 📈 가민 측정’에 값을 넣으면 "
                               "여기에 추이가 그려집니다.")
                else:
                    _def = [k for k in ana.TREND_DEFAULT if k in _av] or _av[:3]
                    _pick = st.multiselect(
                        "볼 지표 — 고른 순서가 아니라 아래 순서대로 쌓입니다",
                        _av, default=_def,
                        format_func=lambda k: ana.TREND_LABEL[k], key="gtrend_pick")
                    # 값이 하나도 없는 지표는 목록에 안 나옵니다 → 왜 없는지 알려줍니다
                    if "dayload" not in _av:
                        st.info("‘일일 운동 부하’는 아직 목록에 없습니다 — 훈련에 "
                                "**운동 부하**를 하나라도 넣으면 생깁니다. "
                                "‘🏃 훈련 → ➕ 훈련 입력’의 *가민 트레이닝 효과 · 운동 부하* "
                                "줄, 또는 ‘📋 훈련 이력 → ✏️ 수정 / 삭제’의 "
                                "*가민 트레이닝 효과 · 운동 부하 · 피로도* 접힌 칸에 있습니다. "
                                "가민 **활동 목록 CSV**를 넣으면 자동으로 들어옵니다.")
                    _pan = ana.trend_panels(gdv, gmv, [k for k in _av if k in _pick],
                                            workouts=_gwv, body=_gbv)
                    if not _pan:
                        st.caption("지표를 하나 이상 골라주세요.")
                    else:
                        _ch = garmin_trend_charts(_pan)
                        if _ch:
                            stacked_charts(_ch)
                        _tips = ["입력한 날만 점으로 찍힙니다"]
                        if any(p["key"] == "dayload" for p in _pan):
                            _tips.append("‘일일 운동 부하’ = 그날 훈련들의 운동 부하 합 "
                                         "(훈련 입력 / CSV에서 들어옵니다)")
                        if any(p["key"] == "ratio" for p in _pan):
                            _tips.append("‘부하 비율’의 초록 띠 = 가민 최적 구간(0.8~1.4)")
                        if any(p["key"] == "hrv" for p in _pan):
                            _tips.append("HRV 점 색은 가민이 준 상태 그대로입니다 "
                                         "(가민의 회색 ‘기준 범위’ 띠는 우리가 "
                                         "받아 적는 값이 아니라 그리지 않습니다)")
                        if any(p["key"] == "rztsb" for p in _pan):
                            _tips.append("TSB 점선 = 0 · 위쪽이 피로가 빠진 상태입니다")
                        st.caption(" · ".join(_tips))

            if not gdv.empty:
                with ui.card("gts"):
                    ui.head("⌚ 트레이닝 상태 타임라인",
                            "가민이 판정한 <b>국면</b>의 변화 · <b>아래로 갈수록 "
                            "부하가 큽니다</b> — 잘하고 못하고의 순서가 아닙니다")
                    tl = gdv[gdv["TrainingStatus"].astype(str).str.strip() != ""].copy()
                    if not tl.empty:
                        tl["상태"] = tl["TrainingStatus"].map(
                            lambda x: ana.TRAINING_STATUS_KR.get(str(x), str(x)))
                        # 세로축은 '부하가 적음 → 많음' 순서입니다.
                        # 예전에는 '나쁨 → 좋음'처럼 늘어놓아서, 유지가 생산적보다
                        # 못한 상태인 것처럼 읽혔습니다. 가민은 둘을 등급으로
                        # 나누지 않습니다.
                        order = ["트레이닝 부족", "회복", "피킹", "유지",
                                 "생산적", "비생산적", "부하 과다", "과훈련"]
                        tl["구분"] = tl["상태"].map(ana.STATUS_GROUP).fillna("정상 진행")
                        _gdom = ["정상 진행", "살펴볼 것", "줄여야 할 것"]
                        st.altair_chart(alt.Chart(tl).mark_circle(size=110, opacity=.85).encode(
                            x=alt.X("StatusDate:T", title=None, axis=date_axis(_span_days(tl["StatusDate"]))),
                            y=alt.Y("상태:N", sort=order, title=None),
                            # 색은 '지금 뭔가 해야 하나'만 나타냅니다
                            color=alt.Color("구분:N", title=None,
                                            scale=alt.Scale(domain=_gdom,
                                                            range=[C["primary"], C["amber"],
                                                                   C["red"]]),
                                            # 범례 표식을 점 모양으로 — 차트의 마크와
                                            # 같은 모양이어야 바로 연결됩니다
                                            legend=alt.Legend(orient="top",
                                                              symbolType="circle",
                                                              symbolSize=90)),
                            tooltip=[alt.Tooltip("StatusDate:T", title="날짜", format="%Y-%m-%d"),
                                     alt.Tooltip("상태:N", title="상태"),
                                     alt.Tooltip("구분:N", title="구분")]
                        ).properties(height=ui.chart_height(230, 210)), width="stretch")
                        with st.expander("❓ ‘생산적’과 ‘유지’ 중 뭐가 좋은 건가요"):
                            st.markdown(STATUS_HELP)
                    else:
                        st.caption("Training Status 입력 기록이 없습니다.")

            if not gmv.empty:

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

                # ── 레이스 예측 추이 ──────────────────────────────────
                _pt = ana.race_pred_trend(gmv)
                if not _pt.empty:
                    with ui.card("gpredtr"):
                        ui.head("🏁 레이스 예측 추이",
                                "완주 시간은 종목마다 크기가 너무 달라 한 축에 못 "
                                "올립니다 → <b>km당 페이스</b>로 바꿔 함께 그립니다 · "
                                "<b>위로 갈수록 빠름</b>")
                        _pord = [n for _, n, _ in ana.RACE_PRED_COLS]
                        _ptip = [alt.Tooltip("MetricDate:T", title="측정일",
                                             format="%Y-%m-%d"),
                                 alt.Tooltip("종목:N"),
                                 alt.Tooltip("표시:N", title="예상 기록"),
                                 alt.Tooltip("페이스:N", title="페이스")]
                        _pt2 = _pt.copy()
                        _pt2["표시"] = _pt2["Seconds"].map(ana.time_str)
                        _pt2["페이스"] = _pt2["PaceSec"].map(ana.pace_str)
                        _pbase = alt.Chart(_pt2).encode(
                            x=alt.X("MetricDate:T", title=None,
                                    scale=alt.Scale(padding=16),
                                    axis=date_axis(_span_days(_pt2["MetricDate"]))),
                            # 빠른 쪽이 위로 오도록 뒤집고, 눈금은 분:초로
                            y=alt.Y("PaceSec:Q", title=None,
                                    scale=alt.Scale(zero=False, reverse=True,
                                                    padding=14),
                                    axis=alt.Axis(
                                        tickCount=6,
                                        labelExpr=(
                                            "format(floor(datum.value / 60), 'd') + ':' + "
                                            "(datum.value % 60 < 10 ? '0' : '') + "
                                            "format(round(datum.value % 60), 'd')"))),
                            color=alt.Color("종목:N", title=None, sort=_pord,
                                            scale=alt.Scale(domain=_pord,
                                                            range=CHART_PALETTE[:4]),
                                            legend=alt.Legend(orient="top",
                                                              symbolType="circle",
                                                              symbolSize=90)),
                            tooltip=_ptip)
                        st.altair_chart(
                            (_pbase.mark_line(strokeWidth=2)
                             + _pbase.mark_point(size=70, filled=True))
                            .properties(height=ui.chart_height(300, 250),
                                        title=panel_title("페이스 (분:초/km) · 위 = 빠름")),
                            width="stretch")
                        _ps = ana.race_pred_summary(_pt)
                        if not _ps.empty:
                            st.dataframe(_ps, width="stretch", hide_index=True)
                            st.caption("‘변화’는 이 기간 **처음 값 → 마지막 값**입니다. "
                                       "**−** 가 빨라진 것입니다. 기간은 위에서 바꿉니다.")

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
                        # 범례는 기본이 가나다순이라 Easy·Interval·LSD…처럼 섞입니다
                        # → 강도 순(WORKOUT_TYPES)으로, 있는 유형만 세웁니다
                        _tdom = [t for t in WORKOUT_TYPES
                                 if (te["WorkoutType"] == t).any()]
                        _tdom += [t for t in te["WorkoutType"].dropna().unique()
                                  if t not in _tdom]
                        st.altair_chart(alt.Chart(te).mark_circle(size=100, opacity=.65).encode(
                            x=alt.X("AerobicTE:Q", title="유산소 TE",
                                    scale=alt.Scale(domain=[0, 5])),
                            # 세로 축 제목은 글자가 세로로 쪼개져 읽히지 않습니다
                            # → 카드 부제('세로=무산소')가 대신합니다
                            y=alt.Y("AnaerobicTE:Q", title=None,
                                    scale=alt.Scale(domain=[0, 5])),
                            color=alt.Color(
                                "WorkoutType:N", title=None,
                                # ramp의 첫 칸은 거의 흰색이라 흰 배경에서 안 보입니다
                                # → 한 칸 더 만들어 가장 옅은 색을 버립니다
                                scale=alt.Scale(domain=_tdom,
                                                range=ramp(len(_tdom) + 1)[1:]),
                                legend=alt.Legend(orient="top", direction="horizontal",
                                                  symbolType="circle", symbolSize=110)),
                            tooltip=[alt.Tooltip("WorkoutDate:T", title="날짜", format="%Y-%m-%d"),
                                     alt.Tooltip("WorkoutType:N", title="유형"),
                                     alt.Tooltip("AerobicTE:Q", title="유산소 TE", format=".1f"),
                                     alt.Tooltip("AnaerobicTE:Q", title="무산소 TE", format=".1f")]
                        ).properties(height=ui.chart_height(300, 260)), width="stretch")
                        st.caption("범례는 약한 강도 → 강한 강도 순이고, "
                                   "색이 진할수록 강한 유형입니다.")
                        with st.expander("❓ 훈련 유형이 각각 뭔가요"):
                            st.markdown(WORKOUT_TYPE_MD)


# ═════════════════════════════════════════════════════════════════════════
# 추이 · stat
# ═════════════════════════════════════════════════════════════════════════
if SEC == "trend":
    if SCR == "stat":
        df_w = db.load_data("Workouts")
        d = ana.prepare_workouts(df_w)
        if d.empty:
            st.info("분석할 데이터가 없습니다.")
        else:
            wk = ana.weekly_summary(df_w, 20)
            st.caption("이 화면의 수치는 모두 **입력된 훈련 기록으로 직접 계산한 값**입니다. "
                       "가민이 제공한 값은 ‘⌚ 가민 추이’ 화면에 있습니다.")

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

            with ui.card("mono"):
                ui.head("🔁 단조로움 · 스트레인",
                        "매일 비슷하게만 달리고 있지 않은지 — <b>강약 대비</b>를 봅니다")
                _mn_s, _mn_e, _mn_txt = range_picker("mono_range", "3개월")
                _dl = ana.daily_load_series(
                    df_w, HR_REST, HR_MAX, SEX,
                    hist=ana.profile_history(db.load_data("Metrics"), PROFILE_NOW))
                _ms = clip_range(_dl.reset_index(names="날짜"), "날짜", _mn_s, _mn_e)
                _ms = _ms.dropna(subset=["Monotony"])
                if _ms.empty:
                    st.caption("7일 이상 훈련 기록이 쌓이면 계산됩니다.")
                else:
                    _mv = float(_ms["Monotony"].iloc[-1])
                    _mtone, _mtxt = ana.monotony_meta(_mv)
                    _stone, _stxt = ana.strain_meta(_dl["Strain"])
                    ui.metrics([
                        ("단조로움 (Monotony)", f"{_mv:.2f}", "1.5 미만이 좋은 범위"),
                        ("스트레인 (Strain)",
                         f"{float(_ms['Strain'].iloc[-1]):,.0f}", "주간 부하 × 단조로움"),
                    ], per_row_pc=2)
                    st.markdown(
                        "<div style='margin:6px 0 2px'>"
                        + ui.pill(f"단조로움 — {_mtxt}", _mtone) + " "
                        + ui.pill(f"스트레인 — {_stxt}", _stone) + "</div>",
                        unsafe_allow_html=True)
                    _mx = date_axis(_span_days(_ms["날짜"]))
                    _band = alt.Chart(pd.DataFrame({"lo": [0.0], "hi": [1.5]})).mark_rect(
                        opacity=.12, color=C["teal"]).encode(y="lo:Q", y2="hi:Q")
                    _mline = alt.Chart(_ms).mark_line(
                        color=C["primary"], strokeWidth=2).encode(
                        x=alt.X("날짜:T", title=None, axis=X_HIDDEN,
                                scale=alt.Scale(padding=12)),
                        y=alt.Y("Monotony:Q", title=None,
                                scale=alt.Scale(zero=False, padding=8),
                                axis=alt.Axis(format=".1f", tickCount=3)),
                        tooltip=[alt.Tooltip("날짜:T", title="날짜", format="%Y-%m-%d"),
                                 alt.Tooltip("Monotony:Q", title="단조로움", format=".2f")])
                    _sline = alt.Chart(_ms).mark_line(
                        color=C["violet"], strokeWidth=2).encode(
                        x=alt.X("날짜:T", title=None, axis=_mx,
                                scale=alt.Scale(padding=12)),
                        y=alt.Y("Strain:Q", title=None,
                                scale=alt.Scale(zero=False, padding=8),
                                axis=alt.Axis(format=",d", tickCount=3)),
                        tooltip=[alt.Tooltip("날짜:T", title="날짜", format="%Y-%m-%d"),
                                 alt.Tooltip("Strain:Q", title="스트레인", format=",d")])
                    stacked_charts([
                        (_band + _mline).properties(
                            height=ui.chart_height(120, 100),
                            title=panel_title("단조로움 — 초록 띠(1.5 미만)가 좋은 범위")),
                        _sline.properties(height=ui.chart_height(120, 100),
                                          title=panel_title("스트레인 (주간 부하 × 단조로움)"))])
                with st.expander("❓ 단조로움과 스트레인이 뭔가요"):
                    st.markdown(MONOTONY_HELP)

            g = ui.cols(2, 1)
            with g[0]:
                with ui.card("zone"):
                    ui.head("🎚️ 강도 분포 (최근 90일)",
                            "자세한 존 분석은 ‘🎚️ 심박존’ 화면에서")
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
                        st.caption("위 숫자는 훈련의 **평균 심박**으로 존을 하나 "
                                   "골라 낸 어림값입니다 — 강약이 섞인 인터벌이 "
                                   "통째로 중간 존에 들어갑니다.")
                        # .fit 으로 넣은 훈련은 시계가 존별로 직접 잰 시간이 있습니다
                        _wi = ana.watch_intensity(df_w, 90)
                        if _wi:
                            st.markdown(
                                "<p class='rl-sub' style='margin:14px 0 2px'>"
                                "⌚ <b>시계 실측</b> — .fit 으로 넣은 훈련만 "
                                f"({_wi['n']}/{_wi['n_total']}건)</p>",
                                unsafe_allow_html=True)
                            ui.rows([("저강도 (Z1~Z2)", f"{_wi['low']}%"),
                                     ("중강도 (Z3~Z4)", f"{_wi['mid']}%"),
                                     ("고강도 (Z5)", f"{_wi['high']}%")]
                                    + [(f"— {k}", f"{v:,.0f}분")
                                       for k, v in _wi["minutes"].items() if v > 0])
                            st.caption("시계가 초보다 촘촘하게 재서 존별로 더해 둔 "
                                       "**실제 시간**입니다. 훈련 안에서 존을 "
                                       "오간 것까지 그대로 반영됩니다 — "
                                       "Garmin Connect 화면과 같은 값입니다. "
                                       "**.fit 으로 넣은 훈련이 쌓일수록 이쪽이 "
                                       "맞습니다.**")
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
                        # 세로 축 제목은 글자가 세로로 쪼개져 읽히지 않습니다 → 위 한 줄로
                        y=alt.Y("AvgHeartRate:Q", title=None, scale=alt.Scale(zero=False),
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
                        .properties(height=ui.chart_height(320, 260),
                                    title=panel_title("세로 = 평균 심박 (bpm)")),
                        width="stretch")

            with ui.card("wtrend"):
                ui.head("📈 지표 추이",
                        "훈련 <b>한 건이 점 하나</b> · 기간과 유형을 좁혀서 봅니다 — "
                        "같은 종류의 훈련끼리 비교해야 뜻이 있습니다")
                _wr = ui.cols(2, 1, keep_row=True)
                with _wr[0]:
                    _wt_s, _wt_e, _wt_txt = range_picker("wt_range", "6개월")
                _types_all = [t for t in WORKOUT_TYPES if (df_w["WorkoutType"] == t).any()]
                _tsel = _wr[1 % len(_wr)].multiselect(
                    "훈련 유형 (비우면 전체)", _types_all, default=[], key="wt_types",
                    help="하나만 고르면 ‘같은 종류의 훈련이 어떻게 변해왔나’가 되고, "
                         "비워 두면 전체 흐름이 됩니다.")
                # 보조선 설정 — 한 줄에 셋
                _lr = ui.cols(3, 1, keep_row=True)
                _ma_lab = _lr[0].selectbox(
                    "이동평균", list(ana.MA_WINDOWS), index=2, key="wt_ma",
                    help="‘몇 회’가 아니라 **며칠**로 셉니다. 훈련 빈도가 주마다 "
                         "달라서 ‘4회 평균’은 어떤 주엔 사흘치, 어떤 주엔 2주치가 "
                         "돼 버립니다.")
                _show_avg = _lr[1 % len(_lr)].checkbox(
                    "기간 평균선", value=True, key="wt_avg",
                    help="고른 기간 전체의 평균 — 회색 가로 파선")
                _show_tr = _lr[2 % len(_lr)].checkbox(
                    "추세선", value=True, key="wt_trend",
                    help="이 기간의 직선 추세 — 주황. 거리·상승고도·TE처럼 "
                         "그날 훈련 설계로 정해지는 값에는 그리지 않습니다.")
                _wt = ana.workout_trend(df_w, db.load_data("Laps"),
                                        start=_wt_s, end=_wt_e,
                                        types=_tsel or None,
                                        ma_days=ana.MA_WINDOWS[_ma_lab])
                _wav = ana.workout_trend_available(_wt)
                if not _wav:
                    st.caption("이 조건에 맞는 훈련이 없습니다. 기간이나 유형을 바꿔보세요.")
                else:
                    _wdef = [k for k in ana.WORKOUT_TREND_DEFAULT if k in _wav] or _wav[:3]
                    _wpick = st.multiselect(
                        "볼 지표 — 고른 순서가 아니라 아래 순서대로 쌓입니다",
                        _wav, default=_wdef,
                        format_func=lambda k: ana.WORKOUT_TREND_LABEL[k],
                        key="wt_pick")
                    _wkeys = [k for k in _wav if k in _wpick]
                    if not _wkeys:
                        st.caption("지표를 하나 이상 골라주세요.")
                    else:
                        _wch = workout_trend_charts(
                            _wt, _wkeys, multi=len(_tsel) != 1,
                            ma_label=_ma_lab, show_avg=_show_avg,
                            show_trend=_show_tr)
                        if _wch:
                            stacked_charts(_wch)
                        _leg = ["점 = 훈련 한 건"]
                        if _ma_lab != "없음":
                            _leg.append(f"<b>먹색</b> = {_ma_lab} 이동평균")
                        if _show_avg:
                            _leg.append("<b>회색 파선</b> = 기간 평균")
                        if _show_tr:
                            _leg.append("<b>주황</b> = 추세")
                        st.markdown(
                            "<p class='rl-sub' style='margin:2px 0 0'>"
                            + " · ".join(_leg)
                            + f" · {len(_wt)}건"
                            + (f" · {', '.join(_tsel)}" if _tsel else " · 전체 유형")
                            + " · 페이스는 위쪽이 빠릅니다</p>",
                            unsafe_allow_html=True)
                with st.expander("❓ 각 지표가 무슨 뜻인가요"):
                    st.markdown("\n\n".join(
                        f"**{ana.WORKOUT_TREND_LABEL[c]}** — {desc}"
                        for c, _n, _u, _f, _g, desc in ana.WORKOUT_TREND_METRICS))
                    st.markdown(
                        "\n\n---\n\n**읽는 요령** — 폼·페이스 지표는 "
                        "**페이스가 빨라지면 저절로 좋아집니다.** 그래서 유형을 섞어 보면 "
                        "‘그날 무슨 훈련을 했나’만 보입니다. 유형을 **하나로 좁히고**, "
                        "한두 점이 아니라 **몇 주 흐름**으로 판단하세요.\n\n"
                        "**세 선의 차이** — 이동평균은 *최근 N일이 어떤가*, "
                        "기간 평균은 *이 기간의 기준선*, 추세선은 *기간 전체가 "
                        "어느 방향인가*를 말합니다. 추세선은 **직선 하나**라서 "
                        "중간의 굴곡(부상·더위·대회)을 지워 버립니다 — 방향만 "
                        "보고, 이유는 이동평균에서 찾으세요.\n\n"
                        "추세선은 " + ", ".join(
                            n for c, n, *_ in ana.WORKOUT_TREND_METRICS
                            if c in ana.TREND_LINE_OK)
                        + " 에만 그립니다. 거리·시간·상승고도·TE·운동 부하는 "
                        "그날 훈련을 어떻게 짰느냐로 정해지는 값이라 직선을 "
                        "그으면 뜻이 없습니다.")

            with ui.card("cal"):
                ui.head("🗓️ 훈련 달력", "진할수록 긴 거리")
                dl = ana.daily_load_series(df_w, HR_REST, HR_MAX, SEX).tail(
                    119 if ui.is_mobile() else 245).reset_index(names="Date")
                dl["요일"] = dl["Date"].dt.dayofweek
                # 주 번호는 **그 주의 월요일**을 기준으로 세야 합니다.
                # 첫 날짜에서부터 7일씩 끊으면(예전 방식) 시작일이 수요일일 때
                # 같은 달력 주의 월·화가 다음 칸으로 밀려 한 주씩 어긋납니다.
                _anchor = (dl["Date"].min()
                           - pd.Timedelta(days=int(dl["Date"].min().dayofweek)))
                dl["주차"] = ((dl["Date"] - _anchor).dt.days // 7)
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


# ═════════════════════════════════════════════════════════════════════════
# 추이 · zone
# ═════════════════════════════════════════════════════════════════════════
if SEC == "trend":
    if SCR == "zone":
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
                # 심박 기준값이 실제로 바뀐 시점만 — 같은 값이 반복되면 접습니다
                _hr3 = ["LTHR", "HRMax", "HRRest"]
                _c2 = chg[["Date"] + _hr3].copy()
                _same = _c2[_hr3].round(3).eq(_c2[_hr3].round(3).shift()).all(axis=1)
                if len(_same):
                    _same.iloc[0] = False
                _c2 = _c2[~_same]
                ui.rows([(f"{r.Date:%Y-%m-%d} 이후",
                          f"LTHR {r.LTHR:.0f} · 최대 {r.HRMax:.0f} · 안정시 {r.HRRest:.0f}")
                         for r in _c2.itertuples()])
                _dupe = len(chg) - len(_c2)
                if _dupe:
                    st.caption(f"심박 기준값이 그대로인 줄 {_dupe}개는 접었습니다 — "
                               "‘⚙️ 설정 → 기준값 이력 수정 / 삭제’ 아래의 "
                               "**중복 이력 정리**로 아예 지울 수 있습니다.")

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


# ═════════════════════════════════════════════════════════════════════════
# 몸 · body
# ═════════════════════════════════════════════════════════════════════════
if SEC == "body":
    if SCR == "body":
        df_w = db.load_data("Workouts")   # 부상 시기와 주간 훈련량을 겹쳐 보려고
        with ui.card("bodyin"):
            ui.head("⚖️ 체중 · 체성분",
                    "매주 같은 요일·같은 조건에 재면 흐름이 보입니다 — "
                    "인바디를 봤을 땐 아래 칸을 함께 채우세요")
            with st.form("f_body", clear_on_submit=True):
                b0 = ui.cols(3, 1, keep_row=True)
                b_date = b0[0].date_input("측정일", ana.last_monday(), key="bd_date",
                                          help="기본값은 이번 주 월요일입니다.")
                b_w = b0[1 % len(b0)].number_input(
                    "체중 (kg)", 0.0, 200.0, 0.0, 0.1, format="%g", key="bd_w",
                    help="기상 직후, 화장실 다녀온 뒤, 같은 옷차림으로 재면 "
                         "주마다 비교가 됩니다.")
                b_bf = b0[2 % len(b0)].number_input(
                    "체지방률 (%)", 0.0, 60.0, 0.0, 0.1, format="%g", key="bd_bf",
                    help="체중계에 나오면 여기 넣고, 없으면 0으로 두세요.")
                with st.expander("🧬 인바디 측정값 (봤을 때만)"):
                    c1 = ui.cols(4, 2, keep_row=True)
                    b_mus = grid_at(c1, 0, 4).number_input(
                        "골격근량 (kg)", 0.0, 100.0, 0.0, 0.1, format="%g", key="bd_mus")
                    b_fat = grid_at(c1, 1, 4).number_input(
                        "체지방량 (kg)", 0.0, 100.0, 0.0, 0.1, format="%g", key="bd_fat")
                    b_bmi = grid_at(c1, 2, 4).number_input(
                        "BMI", 0.0, 60.0, 0.0, 0.1, format="%g", key="bd_bmi")
                    b_vis = grid_at(c1, 3, 4).number_input(
                        "내장지방 레벨", 0, 30, 0, key="bd_vis",
                        help="인바디 기준 10 미만이 표준 범위입니다.")
                    c2 = ui.cols(4, 2, keep_row=True)
                    b_wat = grid_at(c2, 0, 4).number_input(
                        "체수분 (L)", 0.0, 100.0, 0.0, 0.1, format="%g", key="bd_wat")
                    b_pro = grid_at(c2, 1, 4).number_input(
                        "단백질 (kg)", 0.0, 40.0, 0.0, 0.1, format="%g", key="bd_pro")
                    b_min = grid_at(c2, 2, 4).number_input(
                        "무기질 (kg)", 0.0, 10.0, 0.0, 0.01, format="%g", key="bd_min")
                    b_bmr = grid_at(c2, 3, 4).number_input(
                        "기초대사량 (kcal)", 0, 5000, 0, key="bd_bmr")
                b_note = st.text_input("메모", "", key="bd_note",
                                       placeholder="측정 조건, 컨디션 등")
                if st.form_submit_button("저장", width="stretch", type="primary"):
                    _inbody = any([b_mus, b_fat, b_bmi, b_vis, b_wat,
                                   b_pro, b_min, b_bmr])
                    if not b_w and not _inbody:
                        st.error("체중이나 인바디 값 중 하나는 넣어야 합니다.")
                    else:
                        r = db.upsert_row(
                            "Body", {"MeasureDate": b_date.strftime("%Y-%m-%d")},
                            {"BodyID": new_id("BD"),
                             "Source": "인바디" if _inbody else "체중계",
                             "WeightKg": b_w or "", "BodyFatPct": b_bf or "",
                             "SkeletalMuscleKg": b_mus or "", "BodyFatKg": b_fat or "",
                             "BMI": b_bmi or "", "VisceralFatLevel": b_vis or "",
                             "BodyWaterL": b_wat or "", "ProteinKg": b_pro or "",
                             "MineralKg": b_min or "", "BMR": b_bmr or "",
                             "Notes": b_note})
                        # 프로필의 '현재 체중'도 같이 맞춰 둡니다 (이력은 이 시트가 원본)
                        if b_w:
                            db.save_athlete({"CurrentWeightKg": b_w})
                        st.success("체중 기록 "
                                   + ("갱신" if r == "updated" else "저장") + " 완료")
                        st.rerun()
            st.caption("같은 날 다시 저장하면 줄이 쌓이지 않고 그 줄이 갱신됩니다 · "
                       "비워 둔 항목(0)은 저장되지 않습니다.")
            with st.expander("❓ 어떤 값을 봐야 하나요"):
                st.markdown(BODY_HELP)

        _bd = ana.prepare_body(db.load_data("Body"))
        if _bd.empty:
            st.caption("아직 기록이 없습니다. 위에서 첫 측정을 넣어보세요.")
        else:
            with ui.card("bodytr"):
                ui.head("📉 체중 · 체성분 추이",
                        "같은 날짜 축 위에 세웁니다 — 러닝 지표와 함께 보려면 "
                        "‘📈 추이 → ⌚ 가민 추이 → 최근 추이 한눈에’에서 고르세요")
                _bs = ana.body_summary(_bd)
                if not _bs.empty:
                    st.dataframe(_bs, width="stretch", hide_index=True)
                    st.caption("👍 = 좋아지는 방향 · 👀 = 반대 방향 · "
                               "체중과 BMI는 좋고 나쁨을 따지지 않습니다.")
                _bcore = ["WeightKg", "BodyFatPct", "SkeletalMuscleKg", "BodyFatKg"]
                _ball = st.checkbox("체성분 항목 전부 보기", value=False, key="body_all",
                                    help="기본은 체중·체지방률·골격근량·체지방량 네 개입니다.")
                _bav = [c for c in ana.body_available(_bd)
                        if _ball or c in _bcore]
                _bcolor = [C["primary"], C["accent"], C["teal"], C["violet"],
                           C["slate"], C["pink"], C["green"], C["amber"],
                           C["red"], C["muted"]]
                _bpairs = [(c, ana.BODY_LABEL[c], _bcolor[i % len(_bcolor)],
                            ana.BODY_META[c][2])
                           for i, c in enumerate(_bav)]
                _bch = dual_small_multiples(_bd, "MeasureDate", _bpairs,
                                            _span_days(_bd["MeasureDate"]),
                                            h_pc=100, h_mb=86)
                if _bch:
                    stacked_charts(_bch)

        record_editor(
            "Body", "BodyID",
            lambda r: (f"{str(r['MeasureDate'])[:10]} · {r.get('Source', '') or '—'}"
                       f" · {vtxt(r.get('WeightKg'), '{:.1f}')}kg"),
            [("MeasureDate", "date", "측정일", None),
             ("Source", "select", "출처", ana.BODY_SOURCES),
             ("WeightKg", "numopt", "체중 (kg)", 0.1),
             ("BodyFatPct", "numopt", "체지방률 (%)", 0.1),
             ("SkeletalMuscleKg", "numopt", "골격근량 (kg)", 0.1),
             ("BodyFatKg", "numopt", "체지방량 (kg)", 0.1),
             ("BMI", "numopt", "BMI", 0.1),
             ("VisceralFatLevel", "numopt", "내장지방 레벨", None),
             ("BodyWaterL", "numopt", "체수분 (L)", 0.1),
             ("ProteinKg", "numopt", "단백질 (kg)", 0.1),
             ("MineralKg", "numopt", "무기질 (kg)", 0.01),
             ("BMR", "numopt", "기초대사량 (kcal)", None),
             ("Notes", "area", "메모", None)],
            key="body", title="✏️ 체중 기록 수정 / 삭제",
            empty_msg="아직 체중 기록이 없습니다.")

        # ── 부상 · 통증 ────────────────────────────────────────────────
        st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
        with ui.card("injin"):
            ui.head("🩹 부상 · 통증 기록",
                    "한 줄 = 한 번의 통증 · 끝난 날을 비워 두면 <b>진행 중</b>입니다")
            with st.form("f_injury", clear_on_submit=True):
                i0 = ui.cols(4, 2, keep_row=True)
                i_start = grid_at(i0, 0, 4).date_input("시작일", today_local(),
                                                       key="ij_start")
                i_site = grid_at(i0, 1, 4).selectbox("부위", ana.INJURY_SITES,
                                                     key="ij_site")
                i_side = grid_at(i0, 2, 4).selectbox("좌우", ana.INJURY_SIDES,
                                                     key="ij_side")
                i_sev = grid_at(i0, 3, 4).slider(
                    "강도", 1, 10, 3, key="ij_sev",
                    help="1~2 신경 쓰이는 정도 · 3~4 뛰면 느껴지지만 지장 없음 · "
                         "5~6 페이스가 떨어짐 · 7~8 뛰기 어려움 · "
                         "9~10 일상에서도 아픔")
                i1 = ui.cols(3, 1, keep_row=True)
                i_status = i1[0].selectbox("상태", ana.INJURY_STATUS, key="ij_status")
                i_cause = i1[1 % len(i1)].selectbox("짐작되는 원인",
                                                    ana.INJURY_CAUSES, key="ij_cause")
                i_end = i1[2 % len(i1)].date_input(
                    "끝난 날 (선택)", value=None, key="ij_end",
                    help="아직 진행 중이면 비워 두세요.")
                i_note = st.text_input("메모", "", key="ij_note",
                                       placeholder="언제 아픈지, 무엇을 했는지 등")
                if st.form_submit_button("저장", width="stretch", type="primary"):
                    db.append_rows("Injury", pd.DataFrame([{
                        "InjuryID": new_id("IJ"),
                        "StartDate": i_start.strftime("%Y-%m-%d"),
                        "EndDate": i_end.strftime("%Y-%m-%d") if i_end else "",
                        "Site": i_site, "Side": i_side, "Severity": i_sev,
                        "Status": i_status, "Cause": i_cause, "Notes": i_note}]))
                    flash("저장 완료")
                    st.rerun()
            with st.expander("❓ 왜 따로 적어두나요"):
                st.markdown(INJURY_HELP)

        _ij = ana.prepare_injury(db.load_data("Injury"))
        if not _ij.empty:
            with ui.card("injlist"):
                _act = ana.active_injuries(_ij)
                ui.head("📋 부상 이력",
                        (f"진행 중 <b>{len(_act)}건</b>" if len(_act)
                         else "지금 진행 중인 것은 없습니다"))
                _rows = []
                for _, r in _ij.iterrows():
                    _tone, _lab = ana.severity_meta(r.get("Severity"))
                    _per = (f"{r['StartDate']:%Y-%m-%d} ~ "
                            + ("진행 중" if r["_open"] else f"{r['_end']:%Y-%m-%d}")
                            + f" · {int(r['_days'])}일")
                    _rows.append((f"{ana.injury_label(r)}"
                                  + (" " + ui.pill("진행 중", "bad") if r["_open"]
                                     else ""),
                                  f"<span style='font-weight:500;color:var(--text-3)'>"
                                  f"{_per} · {r.get('Cause') or '원인 모름'}</span>"))
                ui.rows(_rows)
                st.caption("강도 기준 — 1~2 신경 쓰이는 정도 · 3~4 지장 없음 · "
                           "5~6 페이스 저하 · 7~8 뛰기 어려움 · 9~10 일상에서도 아픔")

            # 훈련량 위에 부상 구간을 겹쳐 봅니다
            _wk_i = ana.weekly_summary(df_w, 40)
            if not _wk_i.empty:
                with ui.card("injchart"):
                    ui.head("📉 훈련량과 부상 시기",
                            "막대 = 주간 거리 · 붉은 띠 = 통증이 있던 기간")
                    _wi = _wk_i.reset_index(names="주")
                    _wi["주"] = pd.to_datetime(_wi["주"].astype(str).str.slice(0, 10))
                    _lo, _hi = _wi["주"].min(), _wi["주"].max() + pd.Timedelta(days=6)
                    _sp = ana.injury_spans(_ij, _lo, _hi)
                    _bars = alt.Chart(_wi).mark_bar(color=C["primary"], size=14).encode(
                        x=alt.X("주:T", title=None,
                                axis=date_axis(_span_days(_wi["주"]))),
                        y=alt.Y("Distance:Q", title="주간 거리 (km)"),
                        tooltip=[alt.Tooltip("주:T", title="주", format="%Y-%m-%d"),
                                 alt.Tooltip("Distance:Q", title="거리(km)",
                                             format=".1f")])
                    if not _sp.empty:
                        _band = alt.Chart(_sp).mark_rect(
                            opacity=.16, color=C["red"]).encode(
                            x="시작:T", x2="끝:T",
                            tooltip=[alt.Tooltip("부상:N"),
                                     alt.Tooltip("시작:T", title="시작",
                                                 format="%Y-%m-%d"),
                                     alt.Tooltip("끝:T", title="끝",
                                                 format="%Y-%m-%d")])
                        _ch = _band + _bars
                    else:
                        _ch = _bars
                    st.altair_chart(_ch.properties(
                        height=ui.chart_height(260, 210)), width="stretch")
                    st.caption("부하가 올라간 직후에 붉은 띠가 오는 패턴이 반복되면, "
                               "주간 증가율(10% 룰)을 다시 볼 때입니다.")

        record_editor(
            "Injury", "InjuryID",
            lambda r: (f"{str(r['StartDate'])[:10]} · {r.get('Site') or '—'}"
                       f" · {vtxt(r.get('Severity'), '{:.0f}')}/10"),
            [("StartDate", "date", "시작일", None),
             ("EndDate", "date", "끝난 날", None),
             ("Site", "select", "부위", ana.INJURY_SITES),
             ("Side", "select", "좌우", ana.INJURY_SIDES),
             ("Severity", "numopt", "강도 (1~10)", None),
             ("Status", "select", "상태", ana.INJURY_STATUS),
             ("Cause", "select", "짐작되는 원인", ana.INJURY_CAUSES),
             ("Notes", "area", "메모", None)],
            key="injury", title="✏️ 부상 기록 수정 / 삭제",
            note="회복됐으면 **끝난 날**을 채우고 상태를 ‘회복됨’으로 바꾸세요 — "
                 "그래야 ‘오늘의 체크포인트’에서 사라집니다.",
            empty_msg="아직 부상 기록이 없습니다.")


# ═════════════════════════════════════════════════════════════════════════
# 몸 · measure
# ═════════════════════════════════════════════════════════════════════════
if SEC == "body":
    if SCR == "measure":
        with ui.card("gweekly"):
            ui.head("📈 가민 측정 기록",
                    "Connect → 통계/성과 에서 주 1회만 확인하면 됩니다 · "
                    "기록해서 추이만 보는 값이라 지워도 다른 계산에는 영향이 없습니다")
            with st.form("f_metric", clear_on_submit=True):
                md_ = st.date_input("측정일", today_local())

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
                           "‘👤 프로필 & 기준값’ 화면에서 **적용일과 함께** 저장해야 합니다. "
                           "가민이 새 LTHR을 알려줬다면 그쪽에서 갱신하세요.")

                if st.form_submit_button("저장", width="stretch", type="primary"):
                    db.append_rows("Metrics", pd.DataFrame([{
                        "MetricID": new_id("MET"), "MetricDate": md_.strftime("%Y-%m-%d"),
                        "VO2Max": mv or "", "FitnessAge": fa or "",
                        "EnduranceScore": es or "", "HillScore": hs or "",
                        "FocusAnaerobic": fan or "", "FocusHighAerobic": fhi or "",
                        "FocusLowAerobic": flo or "",
                        # 예전에 '48:28:00'처럼 잘못 저장된 값이 다시 들어오는 것을 막습니다
                        "Pred5K": ana.fix_race_pred(p5, "Pred5K"),
                        "Pred10K": ana.fix_race_pred(p10, "Pred10K"),
                        "PredHalf": ana.fix_race_pred(ph, "PredHalf"),
                        "PredFull": ana.fix_race_pred(pf, "PredFull"),
                        "LTPace": mlp, "LTHR": "", "LTPower": "",
                        "WeightKg": "", "BodyFatPct": "", "Notes": ""}]))
                    flash("저장 완료")
                    st.rerun()

        # ── RUNALYZE — 가민이 주지 않는 세 가지 ────────────────────────────
        with ui.card("rzin"):
            ui.head("🧪 RUNALYZE 지표",
                    "가민에 <b>없는</b> 값만 옮겨 적습니다 · 주 1회면 충분합니다")
            with st.form("f_runalyze", clear_on_submit=True):
                rz0 = ui.cols(4, 1, keep_row=True)
                rz_date = rz0[0].date_input("측정일", today_local(), key="rz_date")
                rz_tsb = rz0[1 % len(rz0)].number_input(
                    "TSB (폼)", -100.0, 100.0, 0.0, 0.1, format="%g", key="rz_tsb",
                    help="Training Stress Balance = CTL − ATL. 양수면 피로가 빠져 "
                         "‘신선한’ 상태, 음수면 부하가 쌓인 상태입니다. "
                         "RUNALYZE 대시보드의 Fitness/Fatigue 패널에 있습니다.")
                rz_ms = rz0[2 % len(rz0)].number_input(
                    "Marathon Shape (%)", 0.0, 200.0, 0.0, 0.5, format="%g", key="rz_ms",
                    help="최근 6개월 주간 거리(2/3)와 롱런 길이(1/3)로 매기는 "
                         "지구력 준비도. 기준선은 10K 17% · 하프 42.5% · 풀 100% 입니다.")
                rz_vo = rz0[3 % len(rz0)].number_input(
                    "Effective VO₂max", 0.0, 90.0, 0.0, 0.1, format="%g", key="rz_vo",
                    help="심박·페이스 관계에 본인 최고 기록으로 보정을 건 값이라 "
                         "가민 VO₂max와 계산 방식이 다릅니다. 둘을 같이 보면 "
                         "한쪽이 더위·컨디션에 흔들렸는지 가려집니다.")
                if st.form_submit_button("저장", width="stretch", type="primary"):
                    if not any([rz_tsb, rz_ms, rz_vo]):
                        st.error("값을 하나 이상 넣으세요.")
                    else:
                        db.append_rows("Metrics", pd.DataFrame([{
                            "MetricID": new_id("MET"),
                            "MetricDate": rz_date.strftime("%Y-%m-%d"),
                            "RzTSB": rz_tsb if rz_tsb else "",
                            "RzMarathonShape": rz_ms or "",
                            "RzEffVO2max": rz_vo or "",
                            "Notes": "RUNALYZE"}]))
                        flash("저장 완료")
                        st.rerun()
            with st.expander("❓ 이 세 개를 왜 따로 넣나요"):
                st.markdown(RUNALYZE_HELP)

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
             ("RzTSB", "numopt", "RUNALYZE TSB", 0.1),
             ("RzMarathonShape", "numopt", "RUNALYZE Marathon Shape (%)", 0.5),
             ("RzEffVO2max", "numopt", "RUNALYZE Effective VO₂max", 0.1),
             ("Notes", "area", "메모", None)],
            key="metric", title="✏️ 측정 기록 수정 / 삭제",
            derive=lambda v: {k: ana.fix_race_pred(v.get(k), k)
                              for k in ("Pred5K", "Pred10K", "PredHalf", "PredFull")
                              if str(v.get(k) or "").strip()},
            row_filter=only_measure_rows,
            note="LTHR·체중·체지방률은 ‘👤 프로필 & 기준값’ 탭의 "
                 "**기준값 이력 수정 / 삭제**에서 고칩니다.",
            empty_msg="아직 가민 측정 기록이 없습니다.")


# ═════════════════════════════════════════════════════════════════════════
# 목표 · proj
# ═════════════════════════════════════════════════════════════════════════
if SEC == "goal":
    if SCR == "proj":
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
                    ps = pp[0].date_input("시작", today_local())
                    pt = pp[1].date_input("목표일", today_local() + timedelta(days=90))
                    pstat = st.selectbox("상태", ["ACTIVE", "PLANNED", "COMPLETED"])
                    if st.form_submit_button("생성", width="stretch", type="primary"):
                        db.append_rows("Projects", pd.DataFrame([{
                            "ProjectID": new_id("PRJ"), "ProjectName": pn, "Status": pstat,
                            "GoalType": "Time Trial", "GoalValue": pv,
                            "StartDate": ps.strftime("%Y-%m-%d"),
                            "TargetDate": pt.strftime("%Y-%m-%d"), "Description": ""}]))
                        flash("생성 완료")
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


# ═════════════════════════════════════════════════════════════════════════
# 목표 · race
# ═════════════════════════════════════════════════════════════════════════
if SEC == "goal":
    if SCR == "race":
        df_races = db.load_data("Races")
        df_w = db.load_data("Workouts")
        daily = ana.daily_load_series(df_w, HR_REST, HR_MAX, SEX)

        with ui.card("radd"):
            with st.expander("➕ 대회 등록"):
                with st.form("f_race", clear_on_submit=True):
                    rn = st.text_input("대회명")
                    rr = ui.cols(2, 2, keep_row=True)
                    rd = rr[0].selectbox("종목", ["5km", "10km", "Half Marathon", "Full Marathon"])
                    rdate = rr[1].date_input("날짜", today_local() + timedelta(days=60))
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
                        flash("등록 완료")
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


# ═════════════════════════════════════════════════════════════════════════
# 목표 · pred
# ═════════════════════════════════════════════════════════════════════════
if SEC == "goal":
    if SCR == "pred":
        df_w = db.load_data("Workouts")
        # 가민 레이스 예측으로 VDOT을 역산할 때 씁니다
        G = ana.latest_garmin(db.load_data("DailyStatus"), db.load_data("Metrics"))
        with ui.card("vdot"):
            ui.head("🔮 VDOT 기반 기량 예측",
                    "VDOT은 <b>최대노력 기록 한 건</b>에서 나오는 값입니다 — "
                    "무엇을 기준으로 삼았는지가 결과를 좌우합니다")
            _vr = ui.cols(2, 1, keep_row=True)
            src = _vr[0].selectbox(
                "기준 기록", ["기록에서 자동 선택", "후보에서 직접 고르기", "직접 입력"],
                key="vdot_src")
            _vwin = _vr[1 % len(_vr)].selectbox(
                "찾는 기간", ["최근 6주", "최근 3개월", "최근 6개월", "전체"],
                index=1, key="vdot_days",
                help="오래된 기록으로 계산하면 '지금 기량'이 아니라 "
                     "'그때 기량'이 나옵니다.")
            _days = {"최근 6주": 42, "최근 3개월": 90,
                     "최근 6개월": 180, "전체": None}[_vwin]
            vdot = np.nan
            _pick = {}

            if src == "직접 입력":
                v = ui.cols(3, 1, keep_row=True)
                bd = v[0].number_input("거리 (km)", 0.4, 100.0, 10.0, 0.1)
                bm = v[1 % len(v)].number_input("기록 (분)", 1.0, 600.0, 50.0, 0.1)
                vdot = ana.vdot_from_performance(bd, bm)
                v[2 % len(v)].metric("VDOT", f"{vdot:.1f}" if np.isfinite(vdot) else "—")
                st.caption("전력으로 달린 기록(대회·타임트라이얼)을 넣어야 맞습니다.")
            else:
                _vt = ana.vdot_table(df_w, db.load_data("Laps"), days=_days)
                if _vt.empty:
                    st.info("이 기간에 5km 이상 기록이 없습니다. 기간을 넓히거나 "
                            "‘직접 입력’을 써보세요.")
                else:
                    _show = _vt[["종목", "기록", "날짜", "페이스", "유형",
                                 "VDOT", "최대노력", "사유"]]
                    st.dataframe(_show, width="stretch", hide_index=True)
                    if src == "후보에서 직접 고르기":
                        _opts = {f"{r['종목']} {r['기록']} ({r['날짜']}, {r['유형']}) "
                                 f"→ VDOT {r['VDOT']:.1f}": i
                                 for i, r in _vt.iterrows()}
                        _sel = st.selectbox("기준으로 쓸 기록", list(_opts), key="vdot_row")
                        _row = _vt.loc[_opts[_sel]]
                        vdot = float(_row["VDOT"])
                        _pick = {"hard": bool(_row["_hard"]), "why": _row["사유"],
                                 "category": _row["종목"], "time": _row["기록"],
                                 "date": _row["날짜"]}
                    else:
                        _pick = ana.vdot_pick(_vt)
                        vdot = _pick.get("vdot", np.nan)
                    if np.isfinite(vdot):
                        st.metric("VDOT", f"{vdot:.1f}",
                                  help="Daniels & Gilbert 공식")
                        st.caption(f"기준: **{_pick.get('category')} "
                                   f"{_pick.get('time')}** ({_pick.get('date')})")
                        if not _pick.get("hard"):
                            st.warning(
                                f"⚠️ 이 기록은 **최대노력이 아닙니다** — "
                                f"{_pick.get('why')}. 전력이 아닌 기록에서 뽑은 "
                                "VDOT은 **실제 기량보다 낮게** 나옵니다. "
                                "아래 가민 예측과 비교해 보세요.")
                        elif (_pick.get("age_days") or 0) > 56:
                            st.warning(
                                f"⚠️ 기준 기록이 **{_pick['age_days']}일 전**입니다. "
                                "그 사이 기량이 달라졌을 수 있으니 "
                                "타임트라이얼을 한 번 넣어보세요.")

            # ── 가민 예측으로 역산한 VDOT — 교차검증 ──────────────────────
            _gv = ana.garmin_vdot(G)
            if not _gv.empty:
                with st.expander("⌚ 가민 레이스 예측으로 역산한 VDOT (교차검증)",
                                 expanded=bool(np.isfinite(vdot)
                                               and not _pick.get("hard", True))):
                    st.dataframe(_gv, width="stretch", hide_index=True)
                    _gmed = float(_gv["VDOT"].median())
                    st.caption(f"중앙값 **{_gmed:.1f}** — 가민 예측은 "
                               "‘전력으로 뛰면 이 정도’라는 값이라, 최대노력 기록이 "
                               "없을 때 **현실적인 상한**으로 볼 수 있습니다.")
                    if np.isfinite(vdot):
                        _gap = _gmed - vdot
                        if abs(_gap) >= 3:
                            st.info(
                                f"두 값이 **{abs(_gap):.1f} 차이**납니다"
                                f"({'가민이 높음' if _gap > 0 else '우리 쪽이 높음'}). "
                                "보통은 **전력으로 달린 기록이 없어서** 생깁니다 — "
                                "5km나 10km를 한 번 전력으로 뛰어 기록을 넣으면 "
                                "두 값이 가까워집니다.")

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
            with st.expander("❓ VDOT이 몇 주째 그대로인 이유"):
                st.markdown(VDOT_HELP)


# ═════════════════════════════════════════════════════════════════════════
# 목표 · pr
# ═════════════════════════════════════════════════════════════════════════
if SEC == "goal":
    if SCR == "pr":
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
            st.caption("※ 최대노력이 아닌 훈련도 포함될 수 있습니다. 레이스 기록은 ‘🏁 대회’ 화면에서 따로 관리하세요.")


# ═════════════════════════════════════════════════════════════════════════
# 설정 · prof
# ═════════════════════════════════════════════════════════════════════════
if SEC == "settings":
    if SCR == "prof":
        with ui.card("prof"):
            ui.head("👤 프로필 & 기준값",
                    "심박·체중은 <b>모든 분석의 기준</b>입니다 — 바꾸면 그 시점부터 "
                    "심박존·훈련 부하가 다시 계산됩니다")
            st.caption("아래 칸에는 **현재 값**이 채워져 있습니다. 고쳐서 저장하면 그게 수정이고, "
                       "값이 실제로 달라졌을 때만 **적용일** 날짜로 이력이 한 줄 쌓입니다. "
                       "쌓인 이력은 이 아래 **기준값 이력 수정 / 삭제**에서 고치거나 지웁니다.")
            with st.form("f_ath"):
                eff = st.date_input("적용일", today_local(), key="prof_eff",
                                    help="이 날짜부터 아래 값이 적용됩니다. "
                                         "이전 훈련은 그 전 값으로 계산됩니다.")
                p1 = ui.cols(4, 1, keep_row=True)
                a_name = p1[0].text_input("이름", str(ATH.get("Name", "")))
                a_sex = p1[1 % len(p1)].selectbox("성별", ["M", "F"],
                                                  index=0 if SEX.upper().startswith("M") else 1)
                a_h = p1[2 % len(p1)].number_input("키 (cm)", 100, 230, int(fnum(ATH.get("HeightCm"), 175)))
                _by0 = ana.age_from_birth(ATH.get("BirthDate"))
                a_by = p1[3 % len(p1)].number_input(
                    "출생연도", 1930, today_local().year - 10,
                    int(today_local().year - _by0) if np.isfinite(_by0) else 1985,
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
                    help="여기 값은 표시용입니다. 주기적인 측정 이력은 "
                         "‘❤️ 몸 → ⚖️ 체중 · 부상’에 쌓입니다.")
                st.caption("⚖️ **체중·체지방률의 이력**은 여기가 아니라 "
                           "‘❤️ 몸 → ⚖️ 체중 · 부상’ 화면에 쌓입니다. "
                           "이 칸은 현재 값 표시용이고, 아래 **변경 이력은 "
                           "심박 기준값(안정시·최대·LTHR)이 바뀔 때만** 남습니다.")
                if st.form_submit_button("저장", width="stretch", type="primary"):
                    db.save_athlete({"Name": a_name, "Sex": a_sex, "HeightCm": a_h,
                                     "BirthDate": f"{int(a_by)}-01-01",
                                     "HRRest": a_rest, "HRMax": a_max, "LTHR": a_lt,
                                     "CurrentWeightKg": a_w, "StartWeightKg": a_sw})
                    # 수치가 바뀐 경우에만 변경 이력 한 줄 추가.
                    # 비교 대상은 '적용일 시점에 실제로 적용되던 값'입니다 —
                    # 현재 프로필과 비교하면 같은 값이 계속 한 줄씩 쌓입니다.
                    _hb = ana.profile_history(db.load_data("Metrics"), PROFILE_NOW)
                    _hb = _hb[_hb["Date"] <= pd.Timestamp(eff)]
                    _base = (_hb.iloc[-1] if not _hb.empty else {})
                    prev = {k: fnum(_base.get(k) if hasattr(_base, "get")
                                    else np.nan, 0)
                            for k in ("HRRest", "HRMax", "LTHR", "WeightKg",
                                      "BodyFatPct")}
                    now = {"HRRest": a_rest, "HRMax": a_max, "LTHR": a_lt,
                           "WeightKg": a_w, "BodyFatPct": a_bf}
                    # 체지방률을 0(미입력)으로 둔 채 저장했다고 예전 값을 '바뀐 것'
                    # 으로 보지 않습니다
                    # 이력 줄은 **심박 기준값(안정시·최대·LTHR)이 바뀔 때만**
                    # 남깁니다. 체중·체지방률은 매주 재는 값이라 여기에 쌓으면
                    # '적용된 프로필'이 같은 심박 값으로 수십 줄이 됩니다 —
                    # 그 이력은 '⚖️ 체중 · 체성분' 화면(Body 시트)이 갖습니다.
                    _cmp = ["HRRest", "HRMax", "LTHR"]
                    if any(abs(fnum(now[k]) - fnum(prev.get(k))) > 0.001 for k in _cmp):
                        db.append_rows("Metrics", pd.DataFrame([{
                            "MetricID": new_id("MET"),
                            "MetricDate": eff.strftime("%Y-%m-%d"),
                            "HRRest": a_rest, "HRMax": a_max, "LTHR": a_lt,
                            "Notes": PROFILE_ROW_NOTE}]))
                        st.success(f"저장 완료 — {eff:%Y-%m-%d}부터 적용되는 "
                                   "심박 기준값 변경 이력을 남겼습니다")
                    else:
                        flash("저장 완료")
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
                        flash("저장 완료 — 존 기준 목록에 ‘⌚ 시계 러닝 존’이 추가됩니다")
                        st.rerun()
                    else:
                        st.error("값이 순서대로 커지도록 넣어주세요 (Z1 시작 < Z2 시작 < … < Z5 끝).")
                if wb[1 % len(wb)].form_submit_button("지우기", width="stretch"):
                    db.save_athlete({"RunZonePct": ""})
                    st.session_state.pop("zone_model", None)
                    flash("시계 존을 지웠습니다 — 기본 %LTHR 기준으로 돌아갑니다.", icon="⚠️")
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
                           "앱 전체에 적용할 기준은 ‘📈 추이 → 🎚️ 심박존’ 화면에서 바꿉니다.")
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
                 "예전에 ‘📈 가민 측정’ 화면에서 LTHR·체중을 함께 입력한 줄도 "
                 "이력에 쓰이므로 여기 같이 나옵니다 — 그 줄을 삭제하면 같은 줄의 "
                 "가민 값(VO₂max 등)도 함께 사라집니다.",
            empty_msg="아직 기준값 이력이 없습니다. 위에서 적용일과 함께 저장하면 생깁니다.")

        # ── 중복 이력 정리 — 심박 기준값이 그대로인 '프로필 변경' 줄 지우기 ──
        _dfm = db.load_data("Metrics")
        _pf = only_profile_rows(_dfm).copy()
        _dupe_ids = []
        if not _pf.empty:
            _pf["_d"] = pd.to_datetime(_pf["MetricDate"], errors="coerce")
            _pf = _pf.dropna(subset=["_d"]).sort_values("_d")
            _hr3 = ["HRRest", "HRMax", "LTHR"]
            _prev = None
            for _, _r in _pf.iterrows():
                _cur = tuple(round(fnum(_r.get(k)), 3) for k in _hr3)
                # 가민 측정값이 같이 들어 있는 줄은 지우면 다른 값도 날아갑니다
                _pure = (str(_r.get("Notes") or "").strip() == PROFILE_ROW_NOTE
                         and not bool(has_measure_values(pd.DataFrame([_r])).iloc[0]))
                if _prev is not None and _cur == _prev and _pure:
                    _dupe_ids.append(str(_r["MetricID"]))
                else:
                    _prev = _cur
        if _dupe_ids:
            with ui.card("profdupe"):
                ui.head("🧹 중복 이력 정리",
                        f"심박 기준값이 <b>그대로인</b> ‘프로필 변경’ 줄이 "
                        f"{len(_dupe_ids)}개 있습니다")
                st.caption("저장 버튼을 누를 때마다 같은 값이 한 줄씩 쌓인 것들입니다. "
                           "지워도 존·부하 계산 결과는 달라지지 않습니다 "
                           "(어차피 같은 값이라서요). 가민 측정값이 함께 들어 있는 "
                           "줄은 대상에서 빼 뒀습니다.")
                if st.button(f"🧹 {len(_dupe_ids)}줄 지우기", width="stretch",
                             key="prof_dupe_go"):
                    db.write_sheet("Metrics",
                                   _dfm[~_dfm["MetricID"].astype(str).isin(_dupe_ids)])
                    flash(f"{len(_dupe_ids)}줄을 지웠습니다.")
                    st.rerun()

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


# ═════════════════════════════════════════════════════════════════════════
# 설정 · shoe
# ═════════════════════════════════════════════════════════════════════════
if SEC == "settings":
    if SCR == "shoe":
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
                        "기존 누적 기준일", today_local(), key="shoe_asof",
                        help="위 '기존 누적'이 **언제까지**를 더한 값인지. "
                             "이 날짜 다음 날부터의 훈련만 누적에 더해지므로, "
                             "나중에 예전 기록을 넣어도 거리가 두 번 세어지지 않습니다.")
                    starg = grid_at(sd_, 2, 3).number_input(
                        "목표 수명 (km)", 100.0, 2000.0, 600.0, 50.0)
                    if st.form_submit_button("등록", width="stretch", type="primary"):
                        db.append_rows("Shoes", pd.DataFrame([{
                            "ShoeID": new_id("SHOE"), "ShoeName": sn, "Brand": sbrand,
                            "PurchaseDate": today_local().strftime("%Y-%m-%d"),
                            "InitialDistanceKm": sinit, "TargetDistanceKm": starg,
                            "Status": "ACTIVE", "Category": ", ".join(scat), "Notes": "",
                            "InitialAsOf": sasof.strftime("%Y-%m-%d")}]))
                        flash("등록 완료")
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
# 설정 · coach
# ═════════════════════════════════════════════════════════════════════════
if SEC == "settings":
    if SCR == "coach":
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
                            "NoteDate": today_local().strftime("%Y-%m-%d"),
                            "Category": cat, "NoteText": txt}]))
                        flash("저장 완료")
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


# ═════════════════════════════════════════════════════════════════════════
# 설정 · backup
# ═════════════════════════════════════════════════════════════════════════
if SEC == "settings":
    if SCR == "backup":
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
                        flash(f"{tgt} {r['rows']}행 교정 완료")
                        st.rerun()

        with ui.card("backup"):
            ui.head("💾 백업", f"현재 저장소: {db.backend_name()}")
            st.download_button("전체 데이터 엑셀로 내려받기", db.export_excel_bytes(),
                               file_name=f"RunningLifeOS_Backup_{today_local():%Y%m%d}.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               width="stretch")
            st.caption(".fit 을 ‘시계 값으로 교체’로 넣기 전처럼 **되돌릴 수 없는 일**을 "
                       "하기 전에 한 번 받아 두세요. 되돌리는 건 바로 아래 칸입니다.")

        with ui.card("restore"):
            ui.head("↩️ 백업에서 되돌리기",
                    "받아 둔 백업 파일로 <b>그때 상태로</b> 돌립니다")
            st.caption("여기서 고른 시트는 **통째로 백업 내용으로 바뀝니다** — "
                       "그 뒤에 넣은 기록은 사라집니다. 지금 상태가 아깝다면 "
                       "위에서 먼저 내려받으세요.")
            _rup = st.file_uploader("백업 엑셀", type=["xlsx"], key="restup",
                                    label_visibility="collapsed")
            if _rup is None:
                st.caption("이 앱의 ‘전체 데이터 엑셀로 내려받기’로 받은 파일만 "
                           "읽습니다. 예전 백업이라 칸이 몇 개 없어도 괜찮습니다 — "
                           "없는 칸은 빈 칸으로 둡니다.")
            else:
                try:
                    _rdata = _rup.getvalue()
                    _rpv = db.restore_preview(_rdata)
                except Exception as _e:                    # noqa: BLE001
                    st.error(f"백업 파일을 읽지 못했습니다 — {_e}")
                    _rpv = None
                if _rpv is not None:
                    st.dataframe(_rpv, hide_index=True, width="stretch")
                    _has = [r["시트"] for _, r in _rpv.iterrows()
                            if r["백업"] != "(없음)"]
                    _pick = st.multiselect(
                        "되돌릴 시트", _has, default=_has, key="rest_sheets",
                        help="일부만 고를 수 있습니다. 예를 들어 훈련 기록만 "
                             "되돌리고 프로필·러닝화는 지금 것을 두려면 "
                             "Workouts·Laps 만 고르세요.")
                    _lose = [r["시트"] for _, r in _rpv.iterrows()
                             if r["시트"] in _pick and isinstance(r["백업"], (int, float))
                             and r["백업"] < r["지금"]]
                    if _lose:
                        st.warning("백업보다 지금 줄이 더 많은 시트가 있습니다 — "
                                   f"**{', '.join(_lose)}**. 되돌리면 그 사이에 "
                                   "넣은 기록이 사라집니다.")
                    st.download_button(
                        "⬇️ 되돌리기 전에 지금 상태 먼저 받기",
                        db.export_excel_bytes(),
                        file_name=f"RunningLifeOS_BeforeRestore_{today_local():%Y%m%d}.xlsx",
                        mime=("application/vnd.openxmlformats-officedocument"
                              ".spreadsheetml.sheet"),
                        width="stretch", key="rest_bak")
                    _rok = st.text_input("확인을 위해 `RESTORE` 를 입력하세요",
                                         key="rest_txt")
                    if st.button("↩️ 백업으로 되돌리기", width="stretch",
                                 type="primary", key="rest_btn",
                                 disabled=(_rok != "RESTORE" or not _pick)):
                        try:
                            _done = db.restore_excel(_rdata, _pick)
                            flash(f"{len(_done)}개 시트 되돌림 "
                                  f"({sum(_done.values())}줄)")
                            st.rerun()
                        except Exception as _e:            # noqa: BLE001
                            st.error(f"되돌리지 못했습니다 — {_e}")
        with ui.card("reset"):
            ui.head("🚨 초기화")
            st.warning("모든 훈련 기록이 삭제됩니다. 되돌릴 수 없습니다.")
            confirm = st.text_input("확인을 위해 `RESET` 을 입력하세요", key="reset_txt")
            if st.button("데이터베이스 초기화", width="stretch",
                         disabled=(confirm != "RESET")):
                db.reset_db()
                flash("초기화 완료")
                st.rerun()
