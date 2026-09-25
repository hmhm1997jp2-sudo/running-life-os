"""
Running Life OS - Analytics Engine v2
=====================================
app.py 에서 `import analytics as ana` 로 사용.
streamlit 의존성 없음 (순수 pandas/numpy) → 단위 테스트 가능.

핵심 개선점
  1) CTL/ATL/TSB : '최근 N개 세션 평균' → '일별 시계열 + 휴식일 0 채움 + 지수가중(42/7일)'
  2) ACWR        : 부상 위험 지표 (급성:만성 부하비) 추가
  3) 강도 분포   : HR 존 5단계 + 폴라라이즈드 80/20 준수율
  4) VDOT/Daniels: 훈련 페이스 존 자동 산출 + 거리별 등가 레이스 타임 예측
  5) EF/디커플링 : 러닝 이코노미 추세 (같은 페이스에서 심박이 내려가는가)
  6) 날씨 보정   : 기온 기반 페이스 보정 (Temperature 컬럼 활용)
  7) 자동 PR 탐지 + 경고(Alert) 엔진
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from datetime import datetime, timedelta, date

# ---------------------------------------------------------------------------
# 0. 공통 유틸
# ---------------------------------------------------------------------------

EASY_TYPES = {"Easy", "Recovery", "LSD", "Long Run"}

# 훈련 유형 설명 — 입력할 때와 차트 범례에서 같은 문장을 씁니다.
# (유형, 한 줄 뜻, 심박존/강도 감각)
WORKOUT_TYPE_HELP = [
    ("Recovery", "회복 조깅 — 힘든 훈련 다음 날 아주 천천히. "
                 "빠르게 뛰면 회복이라는 목적 자체가 없어집니다", "Z1"),
    ("Easy", "이지런 — 옆 사람과 대화가 되는 속도. "
             "주간 훈련량의 70~80%를 여기에 씁니다", "Z2"),
    ("LSD", "Long Slow Distance — 이지런 속도로 길게(보통 90분 이상). "
            "지구력의 토대를 만드는 장거리", "Z2"),
    ("Tempo", "템포런 — ‘편하게 힘든’ 속도로 20~40분 쭉. "
              "마라톤 페이스 언저리입니다", "Z3~Z4"),
    ("Threshold", "젖산역치 훈련 — 1시간쯤 버틸 수 있는 최대 속도. "
                  "보통 8~20분씩 끊어서 반복합니다", "Z4"),
    ("Interval", "인터벌 — 3~5분 빠르게 달리고 회복을 반복. "
                 "최대산소섭취량(VO2max)을 올리는 훈련", "Z5"),
    ("Sprint", "스프린트 — 10~30초 전력 질주 + 충분한 휴식. "
               "근신경과 파워를 건드립니다", "무산소"),
    ("Time Trial", "타임트라이얼 — 대회는 아니지만 **그 거리를 전력으로** 달린 기록. "
                   "VDOT과 훈련 페이스 존을 현재 기량으로 다시 맞추는 기준이 됩니다 "
                   "(6~8주에 한 번, 5km나 10km 권장)", "전력"),
    ("Race", "대회 — 실제 대회이거나 대회처럼 전력으로 달린 기록", "전력"),
    ("Cross Training", "크로스 트레이닝 — 자전거·수영·근력 등 달리기 외 운동", "—"),
]
QUALITY_TYPES = {"Threshold", "Interval", "Sprint", "Race", "Tempo"}


def _num(v, default=0.0) -> float:
    try:
        f = float(v)
        return default if (np.isnan(f) or np.isinf(f)) else f
    except (TypeError, ValueError):
        return default


def pace_str(sec_per_km: float) -> str:
    """초/km → 'M:SS/km'"""
    if not np.isfinite(sec_per_km) or sec_per_km <= 0:
        return "-"
    m, s = divmod(int(round(sec_per_km)), 60)
    return f"{m}:{s:02d}/km"


def time_str(seconds: float) -> str:
    """초 → 'H:MM:SS' 또는 'M:SS'"""
    if not np.isfinite(seconds) or seconds <= 0:
        return "-"
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def prepare_workouts(df: pd.DataFrame) -> pd.DataFrame:
    """Workouts 시트 정규화 — 파생 컬럼(PaceSec, SpeedMMin, TRIMP 등) 생성."""
    if df is None or df.empty:
        return pd.DataFrame(
            columns=["WorkoutDate", "DistanceKm", "DurationMinutes",
                     "AvgHeartRate", "PaceSec", "SpeedMMin", "WorkoutType"]
        )
    d = df.copy()
    d["WorkoutDate"] = pd.to_datetime(d["WorkoutDate"], errors="coerce")
    d = d.dropna(subset=["WorkoutDate"]).sort_values("WorkoutDate")

    for c, default in [("DistanceKm", 0.0), ("DurationMinutes", 0.0),
                       ("AvgHeartRate", 0.0), ("Temperature", np.nan), ("RPE", np.nan)]:
        if c not in d.columns:
            d[c] = default
        d[c] = pd.to_numeric(d[c], errors="coerce")

    d["DistanceKm"] = d["DistanceKm"].fillna(0.0)
    d["DurationMinutes"] = d["DurationMinutes"].fillna(0.0)

    ok = (d["DistanceKm"] > 0) & (d["DurationMinutes"] > 0)
    d["PaceSec"] = np.where(ok, d["DurationMinutes"] * 60.0 / d["DistanceKm"].replace(0, np.nan), np.nan)
    d["SpeedMMin"] = np.where(ok, d["DistanceKm"] * 1000.0 / d["DurationMinutes"].replace(0, np.nan), np.nan)
    if "WorkoutType" not in d.columns:
        d["WorkoutType"] = "Easy"
    d["WorkoutType"] = d["WorkoutType"].fillna("Easy").astype(str)
    return d


# ---------------------------------------------------------------------------
# 1. 부하(Load) 모델 — TRIMP / CTL / ATL / TSB / ACWR
# ---------------------------------------------------------------------------

def trimp_row(duration_min: float, avg_hr: float, hr_rest: float, hr_max: float,
              rpe: float = np.nan, sex: str = "M") -> float:
    """
    Banister TRIMP. 심박이 있으면 심박 기반, 없으면 sRPE(RPE×분)로 대체.
    """
    duration_min = _num(duration_min)
    if duration_min <= 0:
        return 0.0
    avg_hr = _num(avg_hr)
    if avg_hr > hr_rest and hr_max > hr_rest:
        hrr = np.clip((avg_hr - hr_rest) / (hr_max - hr_rest), 0.0, 1.0)
        k = 1.92 if sex.upper().startswith("M") else 1.67
        return float(duration_min * hrr * 0.64 * np.exp(k * hrr))
    if np.isfinite(_num(rpe, np.nan)):          # sRPE fallback (Foster)
        return float(duration_min * _num(rpe) / 10.0 * 55.0)
    return float(duration_min * 3.0)            # 최후 fallback (easy 가정)


def daily_load_series(df_work: pd.DataFrame, hr_rest: float, hr_max: float,
                      sex: str = "M", end_date: datetime | None = None,
                      hist: pd.DataFrame | None = None) -> pd.DataFrame:
    """
    일 단위 TRIMP 시계열. 훈련 없는 날은 0으로 채운다 (← 기존 코드의 핵심 오류 지점).
    반환: index=날짜, columns=[TRIMP, DistanceKm, CTL, ATL, TSB, ACWR, Monotony, Strain]
    """
    d = prepare_workouts(df_work)
    end = pd.Timestamp(end_date or datetime.now()).normalize()

    if d.empty:
        idx = pd.date_range(end - timedelta(days=180), end, freq="D")
        return pd.DataFrame(
            {"TRIMP": 0.0, "DistanceKm": 0.0, "CTL": 0.0, "ATL": 0.0,
             "TSB": 0.0, "ACWR": np.nan, "Monotony": np.nan, "Strain": np.nan},
            index=idx,
        )

    # 프로필 이력이 있으면 훈련 시점의 안정/최대 심박으로 TRIMP 계산
    if hist is not None and not hist.empty:
        d = _asof(d.sort_values("WorkoutDate").copy(), hist)
        d["TRIMP"] = [
            trimp_row(r.DurationMinutes, r.AvgHeartRate,
                      _num(getattr(r, "HRRestUsed", np.nan), hr_rest) or hr_rest,
                      _num(getattr(r, "HRMaxUsed", np.nan), hr_max) or hr_max,
                      getattr(r, "RPE", np.nan), sex)
            for r in d.itertuples()
        ]
    else:
        d["TRIMP"] = [
            trimp_row(r.DurationMinutes, r.AvgHeartRate, hr_rest, hr_max,
                      getattr(r, "RPE", np.nan), sex)
            for r in d.itertuples()
        ]
    d["Day"] = d["WorkoutDate"].dt.normalize()
    daily = d.groupby("Day").agg(TRIMP=("TRIMP", "sum"), DistanceKm=("DistanceKm", "sum"))

    start = daily.index.min()   # 첫 훈련일부터 (앞쪽 빈 구간이 차트를 망치지 않도록)
    idx = pd.date_range(start, end, freq="D")
    daily = daily.reindex(idx, fill_value=0.0)

    # 지수가중 이동평균 (Banister impulse-response)
    ctl, atl = [], []
    c = a = 0.0
    for t in daily["TRIMP"].values:
        c += (t - c) / 42.0
        a += (t - a) / 7.0
        ctl.append(c)
        atl.append(a)
    daily["CTL"] = ctl                       # Fitness
    daily["ATL"] = atl                       # Fatigue
    daily["TSB"] = daily["CTL"] - daily["ATL"]   # Form

    # ACWR (rolling coupled) — 7일 합 / (28일 합 ÷ 4)
    acute = daily["TRIMP"].rolling(7, min_periods=1).sum()
    chronic = daily["TRIMP"].rolling(28, min_periods=7).sum() / 4.0
    daily["ACWR"] = np.where(chronic > 0, acute / chronic, np.nan)

    # 단조로움(Monotony) & 스트레인 (Foster) — 훈련 다양성 지표
    mean7 = daily["TRIMP"].rolling(7, min_periods=7).mean()
    std7 = daily["TRIMP"].rolling(7, min_periods=7).std()
    daily["Monotony"] = np.where(std7 > 0, mean7 / std7, np.nan)
    daily["Strain"] = daily["TRIMP"].rolling(7, min_periods=7).sum() * daily["Monotony"]
    return daily


def load_summary(daily: pd.DataFrame) -> dict:
    """오늘 기준 부하 상태 + 해석 문구."""
    if daily.empty:
        return {}
    last = daily.iloc[-1]
    tsb = float(last["TSB"])
    acwr = float(last["ACWR"]) if np.isfinite(last["ACWR"]) else np.nan

    if tsb > 15:      form = "휴식 충분 / 레이스 준비 완료"
    elif tsb > 5:     form = "신선함 (Fresh)"
    elif tsb > -10:   form = "정상 훈련 구간"
    elif tsb > -25:   form = "과부하 축적 중"
    else:             form = "⚠️ 위험 — 회복 필요"

    if not np.isfinite(acwr):    risk = "데이터 부족"
    elif acwr < 0.8:             risk = "디트레이닝 구간 (부하 부족)"
    elif acwr <= 1.3:            risk = "✅ 안전 구간 (Sweet Spot)"
    elif acwr <= 1.5:            risk = "⚠️ 주의 — 증가 속도 빠름"
    else:                        risk = "🚨 고위험 — 부상 위험 급증"

    return {
        "ctl": round(float(last["CTL"]), 1),
        "atl": round(float(last["ATL"]), 1),
        "tsb": round(tsb, 1),
        "acwr": round(acwr, 2) if np.isfinite(acwr) else None,
        "monotony": round(float(last["Monotony"]), 2) if np.isfinite(last["Monotony"]) else None,
        "form_text": form,
        "risk_text": risk,
        "ctl_ramp_7d": round(float(last["CTL"] - daily["CTL"].iloc[-8]), 1) if len(daily) > 8 else None,
    }


# ---------------------------------------------------------------------------
# 2. 심박존 — 기준 3종(%LTHR / %HRmax / %HRR) + 시점별 LTHR 반영
#
#    핵심: 젖산역치(LTHR)는 시간이 지나며 바뀝니다. 그래서 존을 '지금 LTHR'로
#    일괄 계산하지 않고, 각 훈련 시점에 유효했던 LTHR로 그 훈련의 존을 매깁니다.
#    (Metrics 시트에 기록된 LTHR 이력을 as-of 조인)
# ---------------------------------------------------------------------------

ZONE_MODELS: dict[str, list[tuple[str, float, float]]] = {
    # 가민 시계의 젖산역치 기반 설정과 동일
    "%LTHR": [
        ("Z1 워밍업", 0.67, 0.78),
        ("Z2 쉬움",   0.78, 0.88),
        ("Z3 유산소", 0.88, 0.93),
        ("Z4 한계치", 0.93, 0.98),
        ("Z5 최대",   0.98, 1.13),
    ],
    "%HRmax": [
        ("Z1 매우 가벼움", 0.50, 0.60),
        ("Z2 가벼움",      0.60, 0.70),
        ("Z3 중간",        0.70, 0.80),
        ("Z4 힘듦",        0.80, 0.90),
        ("Z5 최대",        0.90, 1.05),
    ],
    "%HRR": [   # Karvonen (심박 여유율)
        ("Z1 회복",   0.50, 0.60),
        ("Z2 유산소", 0.60, 0.70),
        ("Z3 템포",   0.70, 0.80),
        ("Z4 역치",   0.80, 0.90),
        ("Z5 VO2max", 0.90, 1.05),
    ],
}
DEFAULT_ZONE_MODEL = "%LTHR"
BELOW_Z1 = "존 미만"
ZONE_NAMES = lambda model: [n for n, _, _ in ZONE_MODELS[model]]

# 가민 시계는 활동별(러닝/사이클/…)로 따로 심박존을 둘 수 있고, 러닝 존은
# 기본 존과 다르게(보통 조금 높게) 잡히는 경우가 많습니다.
# 시계에 설정된 러닝 존을 그대로 등록해서 앱 판정을 시계와 맞춥니다.
WATCH_MODEL = "⌚ 시계 러닝 존"
_LTHR_BASED = ("%LTHR", WATCH_MODEL)


def parse_zone_pcts(text) -> list[float]:
    """'68,80,89,94,99,114' 또는 [68, 80, …] → [68.0, …].
    형식이 맞지 않으면 빈 목록."""
    if text is None:
        return []
    try:
        if isinstance(text, (list, tuple)):
            v = [float(x) for x in text]
        else:
            v = [float(x) for x in str(text).replace(" ", "").split(",") if x != ""]
    except (TypeError, ValueError):
        return []
    if len(v) != 6 or any(v[i] >= v[i + 1] for i in range(5)) or v[0] <= 0:
        return []
    return v


def set_watch_zones(pcts) -> bool:
    """시계 러닝 존 경계(%LTHR, 6개 · 오름차순)를 등록. 성공하면 True."""
    v = parse_zone_pcts(pcts)
    if not v:
        clear_watch_zones()
        return False
    names = [n for n, _, _ in ZONE_MODELS["%LTHR"]]
    spec = [(names[i], v[i] / 100.0, v[i + 1] / 100.0) for i in range(5)]
    # 시계 값을 맨 앞에 둬서 기본으로 보이게 합니다.
    rest = {k: val for k, val in ZONE_MODELS.items() if k != WATCH_MODEL}
    ZONE_MODELS.clear()
    ZONE_MODELS[WATCH_MODEL] = spec
    ZONE_MODELS.update(rest)
    return True


def clear_watch_zones() -> None:
    ZONE_MODELS.pop(WATCH_MODEL, None)


def has_watch_zones() -> bool:
    return WATCH_MODEL in ZONE_MODELS


def preferred_zone_model() -> str:
    """시계 존이 등록돼 있으면 그것을, 아니면 %LTHR을 기본으로."""
    return WATCH_MODEL if has_watch_zones() else DEFAULT_ZONE_MODEL


def bpm_to_pct(bpm_list, lthr) -> list[float]:
    """시계에 표시된 bpm 경계 → %LTHR. LTHR이 바뀌어도 따라가도록."""
    base = _num(lthr, 0.0)
    if base <= 0:
        return []
    try:
        return [round(float(b) / base * 100, 1) for b in bpm_list]
    except (TypeError, ValueError):
        return []


def resolve_lthr(lthr=None, hr_max=None) -> float:
    """LTHR 확정값. 미입력이면 최대심박의 90%로 추정."""
    v = _num(lthr, 0.0)
    if v > 0:
        return v
    hm = _num(hr_max, 0.0)
    return hm * 0.90 if hm > 0 else 0.0


def zone_bounds(model: str = DEFAULT_ZONE_MODEL, lthr=None,
                hr_rest=None, hr_max=None) -> list[tuple[str, float, float]]:
    """특정 시점 기준의 5존 경계(bpm). 화면에 '현재 존표'를 보여줄 때 사용."""
    spec = ZONE_MODELS.get(model, ZONE_MODELS[DEFAULT_ZONE_MODEL])
    hr_max, hr_rest = _num(hr_max, 0.0), _num(hr_rest, 0.0)
    if model in _LTHR_BASED:
        base = resolve_lthr(lthr, hr_max)
        return [(n, base * lo, base * hi) for n, lo, hi in spec] if base > 0 else []
    if model == "%HRmax":
        return [(n, hr_max * lo, hr_max * hi) for n, lo, hi in spec] if hr_max > 0 else []
    if hr_max <= 0 or hr_max <= hr_rest:
        return []
    rng = hr_max - hr_rest
    return [(n, hr_rest + rng * lo, hr_rest + rng * hi) for n, lo, hi in spec]


PROFILE_FIELDS = ["LTHR", "HRRest", "HRMax", "WeightKg", "BodyFatPct"]


def profile_history(df_metrics: pd.DataFrame, current: dict | None = None) -> pd.DataFrame:
    """
    프로필 변경 이력 → [Date, LTHR, HRRest, HRMax, WeightKg, BodyFatPct].

    Metrics 시트에 날짜와 함께 남긴 값들을 모아 시점별 스냅샷을 만듭니다.
    각 항목은 마지막으로 기록된 값이 다음 기록 전까지 유지(ffill)됩니다.
    기록이 없는 항목은 current(현재 프로필)로 채웁니다.
    """
    cur = dict(current or {})
    rows = pd.DataFrame(columns=["Date"] + PROFILE_FIELDS)

    if df_metrics is not None and not df_metrics.empty and "MetricDate" in df_metrics.columns:
        m = df_metrics.copy()
        m["Date"] = pd.to_datetime(m["MetricDate"], errors="coerce")
        for f in PROFILE_FIELDS:
            m[f] = pd.to_numeric(m.get(f), errors="coerce") if f in m.columns else np.nan
            m.loc[m[f] <= 0, f] = np.nan
        m = m.dropna(subset=["Date"]).sort_values("Date")
        m = m[["Date"] + PROFILE_FIELDS]
        # 같은 날 여러 행이면 마지막 값 우선
        m = m.groupby("Date", as_index=False).last()
        if not m[PROFILE_FIELDS].notna().any().any():
            m = m.iloc[0:0]
        rows = m

    # 맨 앞에 '기본값' 한 줄을 깔아 첫 기록 이전 훈련도 값을 갖게 한다
    base = {"Date": pd.Timestamp("2000-01-01")}
    for f in PROFILE_FIELDS:
        v = _num(cur.get(f), np.nan)
        base[f] = v if np.isfinite(v) and v > 0 else np.nan
    if not np.isfinite(_num(base.get("LTHR"), np.nan)):
        base["LTHR"] = resolve_lthr(None, cur.get("HRMax"))

    rows = pd.concat([pd.DataFrame([base]), rows], ignore_index=True).sort_values("Date")
    rows[PROFILE_FIELDS] = rows[PROFILE_FIELDS].ffill().bfill()
    rows = rows.reset_index(drop=True)

    # 값이 하나도 안 바뀐 줄은 이력이 아닙니다 — ffill 뒤에 앞줄과 똑같아진
    # 줄을 접습니다. (예전에는 저장 버튼을 누를 때마다 같은 값이 한 줄씩
    # 쌓여서 '적용된 프로필'이 같은 숫자로 수십 줄이 됐습니다)
    if len(rows) > 1:
        same = (rows[PROFILE_FIELDS]
                .round(4)
                .eq(rows[PROFILE_FIELDS].round(4).shift())
                .all(axis=1))
        same.iloc[0] = False                    # 첫 줄은 항상 남깁니다
        rows = rows[~same].reset_index(drop=True)
    return rows


def profile_changes(hist: pd.DataFrame) -> pd.DataFrame:
    """화면에 보여줄 '실제로 바뀐 시점'만 추린 이력 (기본값 줄 제외)."""
    if hist is None or hist.empty:
        return pd.DataFrame()
    h = hist[hist["Date"] > pd.Timestamp("2000-01-02")].copy()
    if h.empty:
        return h
    keep = h[PROFILE_FIELDS].ne(h[PROFILE_FIELDS].shift()).any(axis=1)
    return h[keep]


def lthr_history(df_metrics: pd.DataFrame, current_lthr=None, hr_max=None) -> pd.DataFrame:
    """(하위 호환) LTHR 이력만 필요한 곳에서 사용."""
    h = profile_history(df_metrics, {"LTHR": current_lthr, "HRMax": hr_max})
    return h[["Date", "LTHR"]]


def _asof(df_work: pd.DataFrame, hist: pd.DataFrame) -> pd.DataFrame:
    """훈련 날짜에 그 시점의 프로필 값을 붙인다."""
    if hist is None or hist.empty:
        for f in PROFILE_FIELDS:
            df_work[f + "Used"] = np.nan
        return df_work
    h = hist.rename(columns={f: f + "Used" for f in PROFILE_FIELDS}).sort_values("Date")
    out = pd.merge_asof(df_work.sort_values("WorkoutDate"), h,
                        left_on="WorkoutDate", right_on="Date", direction="backward")
    for f in PROFILE_FIELDS:
        col = f + "Used"
        if col in out.columns:
            out[col] = out[col].fillna(float(h[col].iloc[0]) if pd.notna(h[col].iloc[0]) else np.nan)
    return out.drop(columns=["Date"], errors="ignore")


def assign_zones(df_work: pd.DataFrame, model: str = DEFAULT_ZONE_MODEL,
                 hist: pd.DataFrame | None = None,
                 hr_rest=None, hr_max=None) -> pd.DataFrame:
    """
    각 훈련에 '그 시점 프로필' 기준의 존을 붙입니다.
    세 기준(%LTHR / %HRmax / %HRR) 모두 그 시점의 LTHR·최대·안정시 심박을 씁니다.
    추가 컬럼: LTHRUsed, HRRestUsed, HRMaxUsed, 존
    """
    d = prepare_workouts(df_work)
    if d.empty:
        return d.assign(LTHRUsed=np.nan, HRRestUsed=np.nan, HRMaxUsed=np.nan,
                        존=pd.Series(dtype=str))
    if hist is None or hist.empty:
        hist = profile_history(None, {"LTHR": None, "HRRest": hr_rest, "HRMax": hr_max})
    d = _asof(d.sort_values("WorkoutDate").copy(), hist)

    spec = ZONE_MODELS.get(model, ZONE_MODELS[DEFAULT_ZONE_MODEL])

    def _zone(hr, lthr_u, rest_u, max_u):
        hr = _num(hr, 0.0)
        if hr <= 0:
            return BELOW_Z1
        if model in _LTHR_BASED:
            base = _num(lthr_u, 0.0) or resolve_lthr(None, max_u)
            if base <= 0:
                return BELOW_Z1
            pcts = [(n, lo, hi) for n, lo, hi in spec]
            p = hr / base
        elif model == "%HRmax":
            mx = _num(max_u, 0.0)
            if mx <= 0:
                return BELOW_Z1
            pcts, p = spec, hr / mx
        else:                                   # %HRR
            mx, rs = _num(max_u, 0.0), _num(rest_u, 0.0)
            if mx <= rs or mx <= 0:
                return BELOW_Z1
            pcts, p = spec, (hr - rs) / (mx - rs)
        for n, lo, hi in pcts:
            if lo <= p < hi:
                return n
        return spec[-1][0] if p >= spec[-1][2] else BELOW_Z1

    d["존"] = [_zone(hr, l, r, m) for hr, l, r, m in
               zip(d["AvgHeartRate"], d.get("LTHRUsed", np.nan),
                   d.get("HRRestUsed", np.nan), d.get("HRMaxUsed", np.nan))]
    return d


def zone_of(bpm: float, bounds: list) -> str:
    """심박(bpm) → 존 이름 (고정 경계용)."""
    if not bounds or not np.isfinite(_num(bpm, np.nan)) or bpm <= 0:
        return BELOW_Z1
    for name, lo, hi in bounds:
        if lo <= bpm < hi:
            return name
    return bounds[-1][0] if bpm >= bounds[-1][2] else BELOW_Z1


def _recent(zoned: pd.DataFrame, days: int) -> pd.DataFrame:
    if zoned is None or zoned.empty:
        return pd.DataFrame()
    cut = pd.Timestamp(datetime.now()).normalize() - timedelta(days=days)
    return zoned[(zoned["WorkoutDate"] >= cut) & (zoned["AvgHeartRate"] > 0)
                 & (zoned["DurationMinutes"] > 0)]


def intensity_distribution(zoned: pd.DataFrame, model: str = DEFAULT_ZONE_MODEL,
                           days: int = 90) -> dict:
    """
    최근 N일 강도 분포 + 폴라라이즈드(저/중/고) 판정.
    저강도 = Z1~Z2, 중강도 = Z3~Z4, 고강도 = Z5.
    주의: 세션 '평균' 심박으로 판정하므로 강약이 섞인 인터벌은 실제보다
          중간 존으로 뭉뚱그려집니다(.fit 스트림이 있어야 정확해집니다).
    """
    d = _recent(zoned, days)
    if d.empty:
        return {}
    names = ZONE_NAMES(model)
    dist = {n: 0.0 for n in names + [BELOW_Z1]}
    for z, m in zip(d["존"], d["DurationMinutes"]):
        dist[z] = dist.get(z, 0.0) + float(m)
    dist = {k: v for k, v in dist.items() if v > 0}
    total = sum(dist.values())

    low = sum(v for k, v in dist.items() if k in (BELOW_Z1, names[0], names[1]))
    mid = sum(v for k, v in dist.items() if k in (names[2], names[3]))
    high = sum(v for k, v in dist.items() if k == names[4])
    tot = low + mid + high
    pol = {k: (round(v / tot * 100, 1) if tot else 0.0)
           for k, v in [("low", low), ("mid", mid), ("high", high)]}

    # 판정은 '무엇이 가장 많이 어긋났는지'로 결정합니다.
    # (예전 코드는 저강도가 낮기만 하면 고강도가 5%여도 '고강도 편중'이라고 했습니다)
    if tot == 0:
        verdict, vtone = "데이터 부족", ""
    elif pol["low"] >= 78 and pol["mid"] <= 12:
        verdict, vtone = "✅ 폴라라이즈드 (80/20 준수)", "ok"
    elif pol["high"] >= 20:
        verdict, vtone = "🚨 고강도 편중 — 이지런 비중을 늘릴 것", "bad"
    elif pol["mid"] >= 25:
        verdict, vtone = ("⚠️ 회색지대(Gray Zone) 과다 — 이지런은 더 느리게, "
                          "포인트 훈련은 더 확실하게"), "warn"
    elif pol["low"] >= 78:
        verdict, vtone = "피라미드형 — 중강도 비중이 조금 높습니다", "ok"
    elif pol["low"] >= 65:
        verdict, vtone = "무난 — 저강도를 조금 더 늘리면 좋습니다", "warn"
    else:
        verdict, vtone = "⚠️ 저강도 부족 — 이지런 비중을 늘릴 것", "warn"

    return {
        "model": model,
        "zone_minutes": {k: round(v, 1) for k, v in dist.items()},
        "zone_pct": {k: (round(v / total * 100, 1) if total else 0.0)
                     for k, v in dist.items()},
        "polarized_pct": pol, "verdict": verdict, "verdict_tone": vtone,
        "total_minutes": round(tot, 1),
    }


def zone_table(zoned: pd.DataFrame, bounds: list, days: int = 90,
               model: str = DEFAULT_ZONE_MODEL) -> pd.DataFrame:
    """존별 상세 — 심박 범위, 세션 수, 시간, 비중, 거리, 평균 페이스."""
    d = _recent(zoned, days)
    if d.empty:
        return pd.DataFrame()
    rng = {n: f"{lo:.0f}–{hi:.0f}" for n, lo, hi in bounds}
    if bounds:
        rng[BELOW_Z1] = f"< {bounds[0][1]:.0f}"
    tot_min = float(d["DurationMinutes"].sum())
    rows = []
    for name in ZONE_NAMES(model) + [BELOW_Z1]:
        sub = d[d["존"] == name]
        if sub.empty:
            continue
        mins = float(sub["DurationMinutes"].sum())
        dist = float(sub["DistanceKm"].sum())
        rows.append({
            "존": name,
            "심박(bpm)": rng.get(name, "-"),
            "세션": int(len(sub)),
            "시간": time_str(mins * 60),
            "비중(%)": round(mins / tot_min * 100, 1) if tot_min else 0.0,
            "거리(km)": round(dist, 1),
            "평균 페이스": pace_str(mins * 60 / dist) if dist > 0 else "-",
            "평균 심박": int(round(sub["AvgHeartRate"].mean())),
        })
    return pd.DataFrame(rows)


def zone_history(zoned: pd.DataFrame, weeks: int = 16) -> pd.DataFrame:
    """주간 존별 훈련 시간 (긴 형식) — 누적 막대용."""
    if zoned is None or zoned.empty:
        return pd.DataFrame(columns=["주", "존", "분"])
    d = zoned[(zoned["AvgHeartRate"] > 0) & (zoned["DurationMinutes"] > 0)].copy()
    if d.empty:
        return pd.DataFrame(columns=["주", "존", "분"])
    d["주"] = d["WorkoutDate"].dt.to_period("W-SUN").apply(
        lambda p: p.start_time.strftime("%Y-%m-%d"))
    g = (d.groupby(["주", "존"], as_index=False)["DurationMinutes"].sum()
           .rename(columns={"DurationMinutes": "분"}))
    keep = sorted(g["주"].unique())[-weeks:]
    return g[g["주"].isin(keep)]


def zone_pace_trend(zoned: pd.DataFrame, zone_name: str, days: int = 365) -> pd.DataFrame:
    """특정 존의 페이스 추이 — 같은 존 심박에서 점점 빨라지는지 확인."""
    d = _recent(zoned, days)
    if d.empty:
        return pd.DataFrame()
    sub = d[(d["존"] == zone_name) & d["PaceSec"].notna()][
        ["WorkoutDate", "PaceSec", "AvgHeartRate", "DistanceKm"]].copy()
    if sub.empty:
        return sub
    sub["페이스(분/km)"] = sub["PaceSec"] / 60.0
    sub["추세"] = sub["페이스(분/km)"].rolling(4, min_periods=1).mean()
    return sub


# ---------------------------------------------------------------------------
# 3. 유산소 기량 — VDOT / Effective VO2max / 등가 레이스 예측
# ---------------------------------------------------------------------------

def _vo2_from_speed(v_m_min: float) -> float:
    return -4.60 + 0.182258 * v_m_min + 0.000104 * v_m_min ** 2


def _speed_from_vo2(vo2: float) -> float:
    a, b, c = 0.000104, 0.182258, -(4.60 + vo2)
    return (-b + np.sqrt(b * b - 4 * a * c)) / (2 * a)


def _pct_max(t_min: float) -> float:
    return 0.8 + 0.1894393 * np.exp(-0.012778 * t_min) + 0.2989558 * np.exp(-0.1932605 * t_min)


def vdot_from_performance(distance_km: float, duration_min: float) -> float:
    """Daniels & Gilbert VDOT — 최대노력 기록 1건에서 산출."""
    if distance_km <= 0 or duration_min <= 0:
        return np.nan
    v = distance_km * 1000.0 / duration_min
    return _vo2_from_speed(v) / _pct_max(duration_min)


def predict_time(vdot: float, distance_km: float) -> float:
    """VDOT → 해당 거리 등가 기록(초). 이분법으로 역산 (Riegel보다 정확)."""
    if not np.isfinite(vdot) or vdot <= 0 or distance_km <= 0:
        return np.nan
    lo, hi = 1.0, 600.0                     # 분
    for _ in range(80):
        mid = (lo + hi) / 2
        v = distance_km * 1000.0 / mid
        if _vo2_from_speed(v) / _pct_max(mid) > vdot:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2 * 60.0


def riegel(t1_sec: float, d1_km: float, d2_km: float, exp: float = 1.06) -> float:
    """Riegel 공식 예측(초) — 교차검증용."""
    if t1_sec <= 0 or d1_km <= 0:
        return np.nan
    return t1_sec * (d2_km / d1_km) ** exp


def training_paces(vdot: float) -> dict:
    """VDOT → Daniels 훈련 페이스 존 (초/km)."""
    if not np.isfinite(vdot) or vdot <= 0:
        return {}
    pct = {"Easy(하한)": 0.62, "Easy(상한)": 0.74, "Marathon": 0.84,
           "Threshold": 0.88, "Interval": 0.98, "Repetition": 1.06}
    out = {}
    for k, p in pct.items():
        v = _speed_from_vo2(vdot * p)        # m/min
        out[k] = 60_000.0 / v if v > 0 else np.nan   # 초/km
    return out


def effective_vo2max(df_work: pd.DataFrame, hr_rest: float, hr_max: float,
                     days: int = 60) -> dict:
    """
    Runalyze 스타일 Effective VO2max.
    기존 코드 대비 개선: ① 짧은/이상 세션 제외 ② 최근 N일만 ③ 시간가중 평균.
    """
    d = prepare_workouts(df_work)
    if d.empty:
        return {"value": None, "n": 0, "trend": None}
    cutoff = pd.Timestamp(datetime.now()).normalize() - timedelta(days=days)
    m = d[(d["WorkoutDate"] >= cutoff) & (d["DistanceKm"] >= 3.0) &
          (d["DurationMinutes"] >= 12.0) & (d["AvgHeartRate"] > hr_rest + 20)]
    if m.empty:
        return {"value": None, "n": 0, "trend": None}

    vals, wts = [], []
    for r in m.itertuples():
        hrr = np.clip((r.AvgHeartRate - hr_rest) / (hr_max - hr_rest), 0.35, 1.0)
        vo2 = _vo2_from_speed(r.SpeedMMin) / _pct_max(r.DurationMinutes)
        vals.append(vo2 / hrr)
        wts.append(r.DurationMinutes)        # 긴 세션에 더 큰 가중치

    vals, wts = np.array(vals), np.array(wts)
    value = float(np.average(vals, weights=wts))

    prev = d[(d["WorkoutDate"] < cutoff) & (d["WorkoutDate"] >= cutoff - timedelta(days=days)) &
             (d["DistanceKm"] >= 3.0) & (d["AvgHeartRate"] > hr_rest + 20)]
    trend = None
    if not prev.empty:
        pv = [
            _vo2_from_speed(r.SpeedMMin) / _pct_max(r.DurationMinutes) /
            np.clip((r.AvgHeartRate - hr_rest) / (hr_max - hr_rest), 0.35, 1.0)
            for r in prev.itertuples()
        ]
        trend = round(value - float(np.mean(pv)), 1)
    return {"value": round(value, 1), "n": int(len(vals)), "trend": trend}


def efficiency_factor(df_work: pd.DataFrame, days: int = 180) -> pd.DataFrame:
    """
    EF = 속도(m/min) / 평균심박. 이지런만 대상 — 우상향이면 러닝 이코노미 개선.
    """
    d = prepare_workouts(df_work)
    if d.empty:
        return pd.DataFrame(columns=["WorkoutDate", "EF", "EF_MA4"])
    cutoff = pd.Timestamp(datetime.now()).normalize() - timedelta(days=days)
    e = d[(d["WorkoutDate"] >= cutoff) & (d["AvgHeartRate"] > 0) &
          (d["DistanceKm"] >= 4.0) & (d["WorkoutType"].isin(EASY_TYPES))].copy()
    if e.empty:
        return pd.DataFrame(columns=["WorkoutDate", "EF", "EF_MA4"])
    e["EF"] = e["SpeedMMin"] / e["AvgHeartRate"]
    e["EF_MA4"] = e["EF"].rolling(4, min_periods=1).mean()
    return e[["WorkoutDate", "EF", "EF_MA4"]]


# ── 러닝 폼(러닝 다이나믹스) 지표 ────────────────────────────────────────────
# (컬럼, 이름, 단위, 숫자형식, 좋은 방향) — 좋은 방향: -1 낮을수록 / +1 높을수록
#  / 0 좋고 나쁨을 말할 수 없음(페이스에 따라 당연히 달라지는 값)
FORM_METRICS = [
    ("AvgVertRatioPct", "수직 비율", "%",   ".1f", -1),
    ("AvgGCTms",        "접지 시간", "ms",  ".0f", -1),
    ("AvgVertOscCm",    "수직 진동", "cm",  ".1f", -1),
    ("AvgCadence",      "케이던스",  "spm", ".0f", +1),
    ("AvgStrideM",      "보폭",      "m",   ".2f",  0),
]

FORM_META = {c: (name, unit, fmt, good) for c, name, unit, fmt, good in FORM_METRICS}


# ── '최근 추이 한눈에' — 가민 Connect 처럼 한 날짜 축에 세워 보는 지표들 ──────
# (키, 표시이름, 출처("daily"|"metric"), 컬럼들, 마크, 숫자형식, 축 고정범위)
TREND_METRICS = [
    ("dayload",   "일일 운동 부하",   "workout", ["TrainingLoad"],     "bar",  ",d", None),
    ("load",      "누적 부하",        "daily",  ["AcuteLoad", "ChronicLoad"],
     "line",  ",d",  None),
    ("ratio",     "부하 비율",        "daily",  ["LoadRatio"],        "line", ".2f", None),
    ("ready",     "트레이닝 준비도",  "daily",  ["TrainingReadiness"], "line", ",d", (0, 100)),
    ("battery",   "바디 배터리",      "daily",  ["BodyBattery"],      "line", ",d", (0, 100)),
    ("hrv",       "HRV (ms)",         "daily",  ["HRVms"],            "point", ",d", None),
    ("rhr",       "안정시 심박 (bpm)", "daily", ["RestingHR"],        "line", ",d", None),
    ("sleep",     "수면 점수",        "daily",  ["SleepScore"],       "line", ",d", (0, 100)),
    ("recovery",  "회복 시간 (h)",    "daily",  ["RecoveryTimeHr"],   "bar",  ",d", None),
    ("int_day",   "고강도 분 (당일)",  "daily",  ["IntensityMinutesDay"], "bar", ",d", None),
    ("int7",      "고강도 분 (7일 누적)", "daily", ["IntensityMin7"],   "line", ",d", None),
    ("intensity", "고강도 분 (가민 주간·예전 입력)", "daily", ["IntensityMinutes"],
     "bar",  ",d", None),
    ("vo2",       "VO₂max",           "metric", ["VO2Max"],           "line", ".1f", None),
    ("fitage",    "피트니스 나이",    "metric", ["FitnessAge"],       "line", ".1f", None),
    ("endurance", "Endurance Score",  "metric", ["EnduranceScore"],   "line", ",d", None),
    ("hill",      "Hill Score",       "metric", ["HillScore"],        "line", ",d", None),
    # RUNALYZE — 가민에 없는 값
    ("rztsb",     "TSB · 폼 (런얼라이즈)",        "metric", ["RzTSB"],
     "line", ".1f", None),
    ("rzshape",   "Marathon Shape (런얼라이즈)",  "metric", ["RzMarathonShape"],
     "line", ".1f", None),
    ("rzvo2",     "Effective VO₂max (런얼라이즈)", "metric", ["RzEffVO2max"],
     "line", ".1f", None),
    # 몸 — 러닝 지표와 같은 날짜 축에 올려 두면 서로 영향을 주는 게 보입니다
    ("weight",    "체중 (kg)",        "body", ["WeightKg"],         "line", ".1f", None),
    ("bodyfat",   "체지방률 (%)",     "body", ["BodyFatPct"],       "line", ".1f", None),
    ("muscle",    "골격근량 (kg)",    "body", ["SkeletalMuscleKg"], "line", ".1f", None),
]
TREND_LABEL = {k: lab for k, lab, *_ in TREND_METRICS}
TREND_DEFAULT = ["dayload", "load", "ratio", "hrv"]

# 여러 줄이 한 칸에 들어가는 지표의 줄 이름
TREND_SERIES_KR = {"AcuteLoad": "급성 (최근 7일)", "ChronicLoad": "만성 (최근 28일)"}

# 음수가 정상인 지표 — '0보다 큰 값이 있나'로 판단하면 안 됩니다
TREND_SIGNED = {"RzTSB"}

# ── 체중 · 체성분 ───────────────────────────────────────────────────────────
# (컬럼, 이름, 단위, 형식, 좋은 방향, 설명) — 좋은 방향 0 = 좋고 나쁨을 말하지 않음
BODY_METRICS = [
    ("WeightKg", "체중", "kg", ".1f", 0,
     "매주 **같은 요일·같은 시간·같은 조건**(기상 직후, 화장실 다녀온 뒤)에 재야 "
     "비교가 됩니다. 하루 사이 1kg 안팎은 수분이라 흐름만 보세요."),
    ("BodyFatPct", "체지방률", "%", ".1f", -1,
     "체중이 그대로여도 이 값이 내려가면 근육이 늘고 지방이 준 것입니다. "
     "러너에게는 체중 숫자보다 이쪽이 더 많은 걸 말해 줍니다."),
    ("SkeletalMuscleKg", "골격근량", "kg", ".1f", +1,
     "인바디의 골격근량. 훈련량을 늘리는 동안 이 값이 **유지되거나 늘면** "
     "잘 가고 있는 것이고, 체중과 같이 떨어지면 에너지가 부족하다는 신호입니다."),
    ("BodyFatKg", "체지방량", "kg", ".1f", -1,
     "체지방의 절대량. 체지방률은 근육량 변화에도 흔들려서, 둘을 같이 보면 "
     "‘근육이 는 건지 지방이 준 건지’가 갈립니다."),
    ("BMI", "BMI", "", ".1f", 0,
     "키 대비 체중. 근육량을 구분하지 못해서 러너에게는 참고 수준입니다."),
    ("BodyWaterL", "체수분", "L", ".1f", 0,
     "몸 전체의 수분량. 더운 시기나 긴 훈련 뒤에 눈에 띄게 줄기도 합니다."),
    ("ProteinKg", "단백질", "kg", ".1f", 0, "인바디의 단백질량(근육의 재료)."),
    ("MineralKg", "무기질", "kg", ".2f", 0, "뼈와 체액의 무기질량."),
    ("VisceralFatLevel", "내장지방 레벨", "", ".0f", -1,
     "내장지방 수준(보통 1~20). 인바디 기준 **10 미만이 표준 범위**입니다."),
    ("BMR", "기초대사량", "kcal", ",.0f", 0,
     "가만히 있어도 쓰는 열량. 근육이 늘면 같이 올라갑니다."),
]
BODY_META = {c: (n, u, f, g, d) for c, n, u, f, g, d in BODY_METRICS}
BODY_LABEL = {c: (f"{n} ({u})" if u else n) for c, n, u, *_ in BODY_METRICS}
BODY_SOURCES = ["체중계", "인바디"]


def prepare_body(df_body: pd.DataFrame, days: int | None = None) -> pd.DataFrame:
    """체중·체성분 기록을 날짜순으로 정리합니다. 0은 '미입력'으로 봅니다."""
    if df_body is None or df_body.empty or "MeasureDate" not in df_body.columns:
        return pd.DataFrame()
    b = df_body.copy()
    b["MeasureDate"] = pd.to_datetime(b["MeasureDate"], errors="coerce")
    b = b.dropna(subset=["MeasureDate"]).sort_values("MeasureDate")
    for col, *_ in BODY_METRICS:
        if col in b.columns:
            v = pd.to_numeric(b[col], errors="coerce")
            b[col] = v.where(v > 0)
    if days:
        cutoff = pd.Timestamp(datetime.now()).normalize() - timedelta(days=days - 1)
        b = b[b["MeasureDate"] >= cutoff]
    return b.reset_index(drop=True)


def body_available(bd: pd.DataFrame) -> list[str]:
    if bd is None or bd.empty:
        return []
    return [c for c, *_ in BODY_METRICS
            if c in bd.columns and bd[c].notna().sum() > 0]


def body_summary(bd: pd.DataFrame, recent: int = 4) -> pd.DataFrame:
    """최근 값과 그 이전 평균을 견준 한 장짜리 표."""
    if bd is None or bd.empty:
        return pd.DataFrame()
    rows = []
    for col, name, unit, fmt, good, _desc in BODY_METRICS:
        if col not in bd.columns:
            continue
        s = bd[col].dropna()
        if s.empty:
            continue
        cur = float(s.iloc[-1])
        prev = s.iloc[-(recent + 1):-1]
        d = cur - float(prev.mean()) if len(prev) else np.nan
        rows.append({
            "지표": f"{name} ({unit})" if unit else name,
            "최근 값": format(cur, fmt),
            # 지표마다 기록 수가 달라서, 열 이름에 횟수를 넣으면 열이 따로 생깁니다
            "이전 평균": format(float(prev.mean()), fmt) if len(prev) else "—",
            "변화": ("—" if not np.isfinite(d) else
                    f"{d:+{fmt}}" + ("" if good == 0 else
                                     (" 👍" if d * good > 0 else " 👀"))),
            "측정": f"{len(s)}회",
        })
    return pd.DataFrame(rows)


# ── 부상 · 통증 ─────────────────────────────────────────────────────────────
INJURY_SITES = ["무릎", "아킬레스건", "발목", "족저근막/발바닥", "정강이(정강이통)",
                "종아리", "햄스트링", "허벅지 앞(대퇴사두)", "고관절/엉덩이",
                "허리", "엉덩정강근막(IT밴드)", "발가락/발등", "기타"]
INJURY_SIDES = ["해당 없음", "왼쪽", "오른쪽", "양쪽"]
INJURY_STATUS = ["진행 중", "관리 중", "회복됨"]
INJURY_CAUSES = ["모름", "부하 급증", "과사용(누적)", "신발", "노면/언덕",
                 "넘어짐·사고", "복귀 직후", "기타"]
# 강도 — 러너가 실제로 쓰는 기준으로 말을 붙입니다
SEVERITY_KR = {1: "신경 쓰이는 정도", 2: "신경 쓰이는 정도",
               3: "뛰면 느껴지지만 지장 없음", 4: "뛰면 느껴지지만 지장 없음",
               5: "페이스가 떨어짐", 6: "페이스가 떨어짐",
               7: "뛰기 어려움", 8: "뛰기 어려움",
               9: "일상에서도 아픔", 10: "일상에서도 아픔"}


def severity_meta(v) -> tuple[str, str]:
    x = _num(v, np.nan)
    if not np.isfinite(x) or x <= 0:
        return "", "—"
    lab = SEVERITY_KR.get(int(round(x)), "")
    tone = "ok" if x <= 2 else "warn" if x <= 5 else "bad"
    return tone, lab


def prepare_injury(df_inj: pd.DataFrame) -> pd.DataFrame:
    """부상 기록 정리 — 날짜 파싱, 진행 중 판단, 지속 일수."""
    if df_inj is None or df_inj.empty or "StartDate" not in df_inj.columns:
        return pd.DataFrame()
    d = df_inj.copy()
    d["StartDate"] = pd.to_datetime(d["StartDate"], errors="coerce")
    d["EndDate"] = pd.to_datetime(d.get("EndDate"), errors="coerce")
    d = d.dropna(subset=["StartDate"]).sort_values("StartDate", ascending=False)
    if d.empty:
        return d
    d["Severity"] = pd.to_numeric(d.get("Severity"), errors="coerce")
    today = pd.Timestamp(datetime.now()).normalize()
    d["_open"] = d["EndDate"].isna() & (d.get("Status", "").astype(str) != "회복됨")
    d["_end"] = d["EndDate"].fillna(today)
    d["_days"] = (d["_end"] - d["StartDate"]).dt.days + 1
    return d.reset_index(drop=True)


def active_injuries(inj: pd.DataFrame) -> pd.DataFrame:
    """아직 안 끝난 것만."""
    if inj is None or inj.empty or "_open" not in inj.columns:
        return pd.DataFrame()
    return inj[inj["_open"]]


def injury_label(row) -> str:
    """'왼쪽 무릎 · 5/10' 한 줄."""
    site = str(row.get("Site") or "부위 미상")
    side = str(row.get("Side") or "")
    side = "" if side in ("", "해당 없음", "nan") else side + " "
    sev = _num(row.get("Severity"), np.nan)
    tail = f" · {sev:.0f}/10" if np.isfinite(sev) and sev > 0 else ""
    return f"{side}{site}{tail}"


def injury_alerts(inj: pd.DataFrame) -> list[dict]:
    """진행 중인 부상을 오늘의 체크포인트에 올립니다."""
    act = active_injuries(inj)
    if act is None or act.empty:
        return []
    # 같은 부위·좌우를 여러 줄로 적어 두면 체크포인트가 같은 말을 반복합니다.
    # 가장 아픈(= Severity 가 큰) 한 줄만 올립니다.
    if {"Site", "Side"} <= set(act.columns):
        act = (act.assign(_s=pd.to_numeric(act.get("Severity"), errors="coerce")
                          .fillna(0))
               .sort_values("_s", ascending=False)
               .drop_duplicates(subset=["Site", "Side"], keep="first"))
    out = []
    for _, r in act.iterrows():
        sev = _num(r.get("Severity"), 0)
        out.append({
            "level": "error" if sev >= 7 else "warning",
            "msg": (f"🩹 {injury_label(r)} — {int(_num(r.get('_days'), 0))}일째. "
                    + ("훈련보다 회복이 먼저입니다." if sev >= 7
                       else "강도를 올리기 전에 상태를 먼저 보세요.")),
        })
    return out


def injury_spans(inj: pd.DataFrame, lo=None, hi=None) -> pd.DataFrame:
    """차트에 음영으로 겹칠 구간 — [시작, 끝, 라벨, 강도]."""
    if inj is None or inj.empty:
        return pd.DataFrame()
    d = inj.copy()
    rows = []
    for _, r in d.iterrows():
        s, e = r["StartDate"], r["_end"]
        if lo is not None and e < pd.Timestamp(lo):
            continue
        if hi is not None and s > pd.Timestamp(hi):
            continue
        rows.append({"시작": max(s, pd.Timestamp(lo)) if lo is not None else s,
                     "끝": min(e, pd.Timestamp(hi)) if hi is not None else e,
                     "부상": injury_label(r),
                     "강도": _num(r.get("Severity"), np.nan)})
    return pd.DataFrame(rows)


def last_monday(today: date | None = None) -> date:
    """가장 가까운 지난 월요일 (오늘이 월요일이면 오늘)."""
    t = today or datetime.now().date()
    return t - timedelta(days=t.weekday())

_HRV_KR = {"Balanced": "균형 잡힘", "Unbalanced": "불균형",
           "Low": "낮음", "Poor": "나쁨", "No Status": "상태 없음"}
HRV_TONE_ORDER = ["균형 잡힘", "불균형", "낮음", "나쁨", "상태 없음"]


_TREND_DATE = {"daily": "StatusDate", "metric": "MetricDate", "workout": "WorkoutDate"}


def _trend_vals(s: pd.Series, col: str) -> pd.Series:
    """0은 '미입력'으로 봅니다 — 단, 음수가 정상인 지표(TSB)는 0만 뺍니다."""
    v = pd.to_numeric(s, errors="coerce")
    return v.where(v != 0) if col in TREND_SIGNED else v.where(v > 0)


def _trend_frame(src, daily, metric, workouts, body=None):
    """출처별 표 + 날짜 컬럼. 훈련은 하루에 여러 건이라 날짜별로 더합니다."""
    if src == "daily":
        return daily, "StatusDate"
    if src == "metric":
        return metric, "MetricDate"
    if src == "body":
        return (body if body is not None else pd.DataFrame()), "MeasureDate"
    if workouts is None or workouts.empty or "TrainingLoad" not in workouts.columns:
        return pd.DataFrame(), "WorkoutDate"
    w = workouts.copy()
    w["WorkoutDate"] = pd.to_datetime(w["WorkoutDate"], errors="coerce")
    w["TrainingLoad"] = pd.to_numeric(w["TrainingLoad"], errors="coerce")
    w = w.dropna(subset=["WorkoutDate"])
    w = w[w["TrainingLoad"] > 0]
    if w.empty:
        return pd.DataFrame(), "WorkoutDate"
    g = (w.groupby(w["WorkoutDate"].dt.normalize())["TrainingLoad"]
         .sum().reset_index())
    return g, "WorkoutDate"


def _trend_src(key, daily, metric, workouts, body=None):
    for k, lab, src, cols, mark, fmt, dom in TREND_METRICS:
        if k != key:
            continue
        df, dcol = _trend_frame(src, daily, metric, workouts, body)
        return lab, df, dcol, cols, mark, fmt, dom
    return None


def trend_available(daily: pd.DataFrame, metric: pd.DataFrame,
                    workouts: pd.DataFrame = None,
                    body: pd.DataFrame = None) -> list[str]:
    """실제로 값이 들어 있는 지표 키만 골라 돌려줍니다."""
    out = []
    for k, _lab, src, cols, *_ in TREND_METRICS:
        df, _dcol = _trend_frame(src, daily, metric, workouts, body)
        if df is None or df.empty:
            continue
        if any(c in df.columns and _trend_vals(df[c], c).notna().sum() > 0
               for c in cols):
            out.append(k)
    return out


def trend_panels(daily: pd.DataFrame, metric: pd.DataFrame, keys,
                 workouts: pd.DataFrame = None,
                 body: pd.DataFrame = None) -> list[dict]:
    """고른 지표를 한 날짜 축에 세우기 좋은 형태로 정리합니다.

    반환: [{key, label, mark, fmt, domain, multi, data}] —
    data 는 [날짜, 계열, 값, 상태] 형태의 긴 표입니다."""
    panels = []
    for key in keys:
        got = _trend_src(key, daily, metric, workouts, body)
        if not got:
            continue
        lab, df, dcol, cols, mark, fmt, dom = got
        if df is None or df.empty or dcol not in df.columns:
            continue
        rows = []
        for c in cols:
            if c not in df.columns:
                continue
            sub = pd.DataFrame({"날짜": pd.to_datetime(df[dcol], errors="coerce"),
                                "계열": TREND_SERIES_KR.get(c, lab),
                                "값": _trend_vals(df[c], c)})
            if key == "hrv" and "HRVStatus" in df.columns:
                sub["상태"] = df["HRVStatus"].map(
                    lambda x: _HRV_KR.get(str(x).strip(), "상태 없음")).values
            else:
                sub["상태"] = ""
            rows.append(sub.dropna(subset=["날짜", "값"]))
        data = (pd.concat(rows, ignore_index=True).sort_values("날짜")
                if rows else pd.DataFrame())
        if data.empty:
            continue
        panels.append({"key": key, "label": lab, "mark": mark, "fmt": fmt,
                       "domain": dom, "multi": data["계열"].nunique() > 1,
                       "data": data})
    return panels

# 러닝 다이나믹스 3종 — 가슴 스트랩·러닝 다이나믹스 팟이 있어야 기록됩니다
DYNAMICS_COLS = ("AvgVertRatioPct", "AvgGCTms", "AvgVertOscCm")


def form_trend(df_work: pd.DataFrame, days: int = 365,
               limit: int = 40) -> pd.DataFrame:
    """훈련별 러닝 폼 지표. 값이 하나라도 있는 훈련만, 있는 열만 돌려줍니다.

    다이나믹스 3종이 기록된 훈련이 하나라도 있으면 **그 훈련만** 남깁니다.
    케이던스는 시계만으로도 매번 기록돼서, 섞어 두면 점 몇 개짜리 다이나믹스
    그래프 옆에 수백 점짜리 케이던스 그래프가 붙어 비교가 안 됩니다.
    같은 폼 지표라도 페이스가 다르면 값이 달라지므로 PaceSec도 같이 담습니다."""
    d = prepare_workouts(df_work)
    if d.empty:
        return pd.DataFrame()
    cutoff = pd.Timestamp(datetime.now()).normalize() - timedelta(days=days)
    d = d[d["WorkoutDate"] >= cutoff].copy()
    have = []
    for col, *_ in FORM_METRICS:
        if col not in d.columns:
            continue
        v = pd.to_numeric(d[col], errors="coerce")
        if (v > 0).sum() >= 1:
            d[col] = v.where(v > 0)
            have.append(col)
    if not have:
        return pd.DataFrame()
    dyn = [c for c in DYNAMICS_COLS if c in have]
    mask = d[dyn].notna().any(axis=1) if dyn else d[have].notna().any(axis=1)
    keep = ["WorkoutDate", "WorkoutType", "DistanceKm", "PaceSec"] + have
    out = d.loc[mask, [c for c in keep if c in d.columns]].copy()
    return out.sort_values("WorkoutDate").tail(max(int(limit), 2))


# ── 훈련별 지표 추이 ────────────────────────────────────────────────────────
# (컬럼, 이름, 단위, 형식, 좋은 방향(-1 낮을수록 / +1 높을수록 / 0 판단 안 함), 설명)
# 형식 'pace' 는 초/km 를 m:ss 로 그립니다(축을 뒤집어 위쪽이 빠름).
WORKOUT_TREND_METRICS = [
    ("PaceSec", "페이스", "/km", "pace", -1,
     "훈련 전체의 평균 페이스. **유형을 하나로 좁혀서** 봐야 뜻이 있습니다 — "
     "이지런과 인터벌을 섞으면 그날 무슨 훈련을 했는지만 보입니다."),
    ("AvgHeartRate", "평균 심박", "bpm", ",d", -1,
     "같은 유형·같은 페이스에서 심박이 내려가면 좋아지는 중입니다. "
     "더위·수면 부족·카페인에도 올라가니 한두 번으로 판단하지 마세요."),
    ("EF", "EF (속도 ÷ 심박)", "", ".3f", +1,
     "러닝 이코노미. **같은 심박으로 더 빨리** 달릴수록 커집니다. "
     "절대값은 사람마다 달라 비교 의미가 없고, 내 선의 방향만 봅니다."),
    ("Decoupling", "심박 디커플링", "%", ".1f", -1,
     "전반 대비 후반의 ‘속도÷심박’ 저하율. 낮을수록 후반까지 페이스를 버틴 것이고, "
     "5% 미만이면 양호합니다. **랩이 4개 이상 저장된 훈련**만 계산됩니다."),
    ("TrainingLoad", "운동 부하", "", ",d", 0,
     "가민이 그 활동에 매긴 점수. 높고 낮음이 좋고 나쁨은 아니고, "
     "주간 배치(강-약-강)가 잘 되고 있는지를 봅니다."),
    ("AerobicTE", "유산소 TE", "", ".1f", 0,
     "그 훈련이 유산소 능력에 준 자극(0~5). 매번 4~5면 과부하, 매번 1~2면 자극 부족입니다."),
    ("AnaerobicTE", "무산소 TE", "", ".1f", 0,
     "무산소 자극(0~5). 스피드 훈련을 하지 않으면 계속 0에 가깝습니다."),
    ("AvgCadence", "케이던스", "spm", ",d", +1,
     "분당 걸음 수. 보통 높을수록 착지 충격이 분산되지만, 무리해서 올릴 값은 아닙니다. "
     "페이스가 빨라지면 저절로 올라갑니다."),
    ("AvgStrideM", "보폭", "m", ".2f", 0,
     "한 걸음의 거리. 빨리 달리면 늘어납니다 — 좋고 나쁨이 아니라 "
     "**같은 페이스에서** 어떻게 변했는지를 보세요."),
    ("AvgGCTms", "접지 시간", "ms", ",d", -1,
     "발이 땅에 닿아 있는 시간. 짧을수록 탄력적이지만, 느리게 달리면 당연히 길어집니다."),
    ("AvgVertOscCm", "수직 진동", "cm", ".1f", -1,
     "달리면서 위아래로 튄 폭. 단독으로 보기보다 **수직 비율**로 보세요."),
    ("AvgVertRatioPct", "수직 비율", "%", ".1f", -1,
     "수직 진동 ÷ 보폭. 앞으로 간 거리 대비 위로 튄 정도라 **낮을수록 경제적**입니다. "
     "키·페이스 차이를 흡수해서, 폼 지표 중에서는 훈련끼리 비교하기 가장 좋습니다. "
     "가민 기준 6% 아래면 매우 좋음, 8% 부근이 보통입니다."),
    ("GctDriftPct", "후반 접지 변화", "%", ".1f", -1,
     "훈련 **후반의 접지 시간이 전반보다 몇 % 늘었는지**. 지치면 발이 땅에 "
     "더 오래 머뭅니다 — 커질수록 후반에 자세가 무너진 것입니다. "
     "디커플링과 짝지어 보면 원인이 갈립니다: 접지는 그대로인데 심박만 "
     "올랐다면 심혈관 드리프트, 접지까지 늘었다면 근지구력 쪽입니다. "
     "**.fit 파일로 넣은 훈련만** 계산됩니다(1초 기록이 있어야 합니다)."),
    ("RPE", "RPE (체감 강도)", "", ".1f", 0,
     "1~10 주관적 강도. 심박은 그대로인데 RPE만 계속 올라가면 "
     "누적 피로나 컨디션 저하를 의심할 만합니다."),
    ("DistanceKm", "거리", "km", ".2f", 0, "한 번에 달린 거리."),
    ("DurationMinutes", "시간", "분", ".0f", 0, "한 번에 달린 시간."),
    ("ElevationGainM", "상승고도", "m", ",d", 0,
     "누적 상승. 페이스나 심박이 갑자기 나빠 보이는 날은 여기를 같이 보세요."),
]
# 추세선(직선)을 그을 만한 지표 — '몇 주에 걸쳐 좋아지고 있나'를 묻는 게
# 말이 되는 값들입니다. 거리·시간·상승고도·TE·운동 부하는 그날 어떤 훈련을
# 했느냐(코스·계획)로 정해지는 값이라 직선을 그으면 뜻이 없습니다.
TREND_LINE_OK = {"PaceSec", "AvgHeartRate", "EF", "Decoupling", "GctDriftPct",
                 "AvgCadence",
                 "AvgStrideM", "AvgGCTms", "AvgVertOscCm", "AvgVertRatioPct", "RPE"}

# 이동평균 창 — '몇 회'가 아니라 '며칠'로 셉니다. 훈련 빈도가 주마다 달라서
# '4회'는 어떤 주엔 사흘치, 어떤 주엔 2주치가 됩니다.
MA_WINDOWS = {"없음": None, "2주": 14, "4주": 28, "8주": 56, "12주": 84}

WORKOUT_TREND_META = {c: (name, unit, fmt, good, desc)
                      for c, name, unit, fmt, good, desc in WORKOUT_TREND_METRICS}
WORKOUT_TREND_LABEL = {c: (f"{name} ({unit})" if unit else name)
                       for c, name, unit, *_ in WORKOUT_TREND_METRICS}
WORKOUT_TREND_DEFAULT = ["PaceSec", "AvgHeartRate", "EF", "AvgVertRatioPct"]


def workout_trend(df_work: pd.DataFrame, df_laps: pd.DataFrame = None,
                  days: int | None = None, types=None, ma_days: int | None = 28,
                  start=None, end=None) -> pd.DataFrame:
    """훈련 한 건 = 한 점. 기간·유형으로 거른 뒤 지표별 보조선을 붙여 돌려줍니다.

    붙는 열은 셋입니다.
      <컬럼>_MA — **며칠짜리** 이동평균(기본 28일). '몇 회'로 세면 훈련 빈도가
                  주마다 달라 어떤 주는 사흘치, 어떤 주는 2주치가 됩니다.
      <컬럼>_AV — 이 기간 전체 평균 (가로 직선)
      <컬럼>_TR — 이 기간의 선형 추세 (TREND_LINE_OK 에 있는 지표만)

    모두 **거르고 남은 것들**로 계산합니다. 유형을 하나로 좁히면 '같은 종류의
    훈련이 어떻게 변해왔나'가 되고, 섞어 보면 전체 흐름이 됩니다."""
    d = prepare_workouts(df_work)
    if d.empty:
        return pd.DataFrame()
    # start/end 가 있으면 그쪽이 우선 (직접 지정한 기간)
    if start is not None or end is not None:
        if start is not None:
            d = d[d["WorkoutDate"] >= pd.Timestamp(start)]
        if end is not None:
            d = d[d["WorkoutDate"] <= pd.Timestamp(end)
                  + timedelta(days=1) - timedelta(seconds=1)]
    elif days:
        cutoff = pd.Timestamp(datetime.now()).normalize() - timedelta(days=days - 1)
        d = d[d["WorkoutDate"] >= cutoff]
    if types:
        d = d[d["WorkoutType"].isin(list(types))]
    if d.empty:
        return pd.DataFrame()
    d = d.sort_values("WorkoutDate").copy()

    # EF — 이지런만 쓰는 efficiency_factor()와 달리, 여기서는 고른 유형 그대로 계산합니다
    hr = pd.to_numeric(d.get("AvgHeartRate"), errors="coerce")
    d["EF"] = np.where(hr > 0, d["SpeedMMin"] / hr, np.nan)

    # 디커플링 — .fit 으로 넣은 훈련은 **1초 기록으로 잰 값**이 이미 들어 있습니다.
    # 없을 때만 랩으로 어림합니다(랩이 4개 이상이어야 계산됩니다).
    if df_laps is not None and not df_laps.empty and "WorkoutID" in df_laps.columns:
        dec = {str(wid): decoupling(g)
               for wid, g in df_laps.groupby(df_laps["WorkoutID"].astype(str))}
        d["Decoupling"] = d["WorkoutID"].astype(str).map(dec)
    else:
        d["Decoupling"] = np.nan
    if "DecouplingPct" in d.columns:
        _exact = pd.to_numeric(d["DecouplingPct"], errors="coerce")
        d["Decoupling"] = _exact.where(_exact.notna(), d["Decoupling"])
        # .fit 으로 넣었는데 값이 비어 있으면 '일부러 안 낸 것'입니다
        # (구간이 나뉜 훈련 — 재면 피로가 아니라 훈련 설계가 찍힙니다).
        # 그런 훈련에 랩 어림값을 대신 채우면 오해를 부릅니다.
        if "WatchZoneSec" in d.columns:
            _from_fit = d["WatchZoneSec"].apply(lambda v: len(parse_zone_sec(v)) > 0)
            d.loc[_from_fit & _exact.isna(), "Decoupling"] = np.nan

    keep = ["WorkoutDate", "WorkoutType", "WorkoutID"]
    _days = (d["WorkoutDate"] - d["WorkoutDate"].min()).dt.total_seconds() / 86400.0
    for col, *_ in WORKOUT_TREND_METRICS:
        if col not in d.columns:
            continue
        v = pd.to_numeric(d[col], errors="coerce")
        # 디커플링·접지 변화는 음수가 정상입니다(0을 미입력으로 보면 안 됩니다)
        v = v if col in ("Decoupling", "GctDriftPct") else v.where(v > 0)
        if v.notna().sum() == 0:
            continue
        d[col] = v
        # 날짜 기준 이동평균 — 쉬는 기간이 있어도 '최근 N일'의 뜻이 유지됩니다
        if ma_days:
            d[f"{col}_MA"] = (v.set_axis(d["WorkoutDate"])
                              .rolling(f"{int(ma_days)}D", min_periods=2)
                              .mean().to_numpy())
        else:
            d[f"{col}_MA"] = np.nan
        d[f"{col}_AV"] = float(v.mean()) if v.notna().any() else np.nan
        d[f"{col}_TR"] = np.nan
        if col in TREND_LINE_OK:
            m = v.notna()
            if int(m.sum()) >= 4 and _days[m].nunique() >= 2:
                sl, ic = np.polyfit(_days[m].to_numpy(float), v[m].to_numpy(float), 1)
                d[f"{col}_TR"] = ic + sl * _days.to_numpy(float)
        keep += [col, f"{col}_MA", f"{col}_AV", f"{col}_TR"]
    return d[keep].reset_index(drop=True)


def workout_trend_stats(wt: pd.DataFrame, keys) -> dict:
    """지표별 요약 — 평균, 이 기간 동안의 추세 변화량, 표본 수."""
    out = {}
    if wt is None or wt.empty:
        return out
    for col in keys:
        if col not in wt.columns:
            continue
        v = pd.to_numeric(wt[col], errors="coerce")
        if v.notna().sum() == 0:
            continue
        tr = pd.to_numeric(wt.get(f"{col}_TR"), errors="coerce")
        chg = (float(tr.dropna().iloc[-1] - tr.dropna().iloc[0])
               if tr is not None and tr.notna().sum() >= 2 else np.nan)
        out[col] = {"mean": float(v.mean()), "n": int(v.notna().sum()),
                    "change": chg}
    return out


def workout_trend_available(wt: pd.DataFrame) -> list[str]:
    """실제로 값이 들어 있는 지표만."""
    if wt is None or wt.empty:
        return []
    return [c for c, *_ in WORKOUT_TREND_METRICS if c in wt.columns]


# ── 단조로움(Monotony) · 스트레인(Strain) ──────────────────────────────────
# Foster: 주간 일별 부하의 평균 ÷ 표준편차. 매일 똑같이 달리면 커집니다.
def monotony_meta(v) -> tuple[str, str]:
    x = _num(v, np.nan)
    if not np.isfinite(x):
        return "info", "7일이 모여야 계산됩니다"
    if x < 1.5:
        return "ok", "강약 대비가 충분합니다"
    if x < 2.0:
        return "warn", "조금 단조롭습니다 — 쉬운 날을 더 쉽게"
    return "bad", "매일 비슷하게 달리고 있습니다 — 완전 휴식일이나 아주 쉬운 날을 넣으세요"


def strain_meta(series: pd.Series, lookback: int = 28) -> tuple[str, str]:
    """스트레인은 사람마다 절대 기준이 달라, **내 최근 평균과 견줘서** 말합니다."""
    s = pd.to_numeric(series, errors="coerce").dropna()
    if s.empty:
        return "info", "7일이 모여야 계산됩니다"
    cur = float(s.iloc[-1])
    base = s.iloc[-(lookback + 1):-1]
    if len(base) < 7 or float(base.mean()) <= 0:
        return "info", "비교할 지난 기록이 아직 부족합니다"
    r = cur / float(base.mean())
    if r >= 1.5:
        return "bad", f"최근 {len(base)}일 평균의 {r:.1f}배 — 부하와 단조로움이 함께 높습니다"
    if r >= 1.2:
        return "warn", f"최근 {len(base)}일 평균의 {r:.1f}배 — 올라가는 중입니다"
    return "ok", f"최근 {len(base)}일 평균의 {r:.1f}배 — 평소 범위입니다"


def form_summary(ft: pd.DataFrame, recent: int = 5) -> pd.DataFrame:
    """최근 n회 평균과 그 이전 평균을 비교한 한 장짜리 표."""
    if ft is None or ft.empty:
        return pd.DataFrame()
    rows = []
    for col, name, unit, fmt, good in FORM_METRICS:
        if col not in ft.columns:
            continue
        s = pd.to_numeric(ft[col], errors="coerce").dropna()
        if s.empty:
            continue
        cur = s.tail(recent)
        prev = s.iloc[:-len(cur)] if len(s) > len(cur) else pd.Series(dtype=float)
        d = (float(cur.mean()) - float(prev.mean())) if len(prev) else np.nan
        # 지표마다 기록 수가 다릅니다(케이던스는 매번, 러닝 다이나믹스는 가끔).
        # 열 이름에 횟수를 넣으면 지표마다 열이 따로 생기므로 '표본' 열로 뺍니다.
        rows.append({
            "지표": f"{name} ({unit})",
            "최근 값": format(float(s.iloc[-1]), fmt),
            "최근 평균": format(float(cur.mean()), fmt),
            "이전 평균": format(float(prev.mean()), fmt) if len(prev) else "—",
            "변화": ("—" if not np.isfinite(d) else
                    ("→ 변화 없음" if abs(d) < 10 ** -int(fmt[1]) / 2 else
                     f"{d:+{fmt}}" + ("" if good == 0 else
                                          (" 👍" if d * good > 0 else " 👀")))),
            "표본": f"{len(s)}회",
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 4. 날씨 보정 페이스
# ---------------------------------------------------------------------------

_TEMP_TABLE = [(10, 0.0), (15, 1.5), (20, 3.0), (25, 5.5), (30, 8.5), (35, 12.0)]


def temp_penalty_pct(temp_c: float) -> float:
    """기온에 따른 페이스 손실률(%) — 10°C 이하 0%."""
    t = _num(temp_c, np.nan)
    if not np.isfinite(t) or t <= 10:
        return 0.0
    xs = [x for x, _ in _TEMP_TABLE]
    ys = [y for _, y in _TEMP_TABLE]
    return float(np.interp(t, xs, ys))


def weather_adjusted_pace(df_work: pd.DataFrame) -> pd.DataFrame:
    """기온 보정 페이스(초/km) 컬럼 추가 — 여름 훈련 저평가 방지."""
    d = prepare_workouts(df_work)
    if d.empty:
        return d
    d["TempPenaltyPct"] = d["Temperature"].apply(temp_penalty_pct)
    d["AdjPaceSec"] = d["PaceSec"] / (1 + d["TempPenaltyPct"] / 100.0)
    return d


# ---------------------------------------------------------------------------
# 5. 자동 PR 탐지 & 주간 요약
# ---------------------------------------------------------------------------

PR_CATEGORIES = [("1km", 1.0), ("5km", 5.0), ("10km", 10.0),
                 ("Half Marathon", 21.0975), ("Full Marathon", 42.195)]


def lap_best_efforts(df_laps: pd.DataFrame, categories=None,
                     max_over: float = 0.25) -> dict:
    """저장된 랩을 이어 붙여 거리별 최고 구간 기록을 찾습니다.

    1km만 따로 뛰지 않아도, 예를 들어 10km 훈련 안의 가장 빠른 연속 1km를
    그 거리의 기록으로 인정합니다. 창(window) 거리가 목표보다 길면 시간을
    비례 축소해 환산합니다(창이 목표의 1+max_over 배를 넘으면 버립니다).

    반환: {종목: {"sec", "date", "workout_id", "km", "laps", "exact"}}
    """
    cats = categories or PR_CATEGORIES
    out: dict = {}
    if df_laps is None or df_laps.empty:
        return out
    d = df_laps.copy()
    for c in ("DistanceKm", "DurationMinutes", "LapNo"):
        d[c] = pd.to_numeric(d.get(c), errors="coerce")
    d["WorkoutDate"] = pd.to_datetime(d.get("WorkoutDate"), errors="coerce")
    d = d[(d["DistanceKm"] > 0) & (d["DurationMinutes"] > 0)]
    if d.empty:
        return out

    for wid, g in d.groupby("WorkoutID"):
        g = g.sort_values("LapNo")
        km = g["DistanceKm"].to_numpy(dtype=float)
        mn = g["DurationMinutes"].to_numpy(dtype=float)
        nos = g["LapNo"].to_numpy()
        wdate = g["WorkoutDate"].max()
        n = len(km)
        for name, target in cats:
            if km.sum() < target * 0.999:
                continue
            best = None
            j, dsum, tsum = 0, 0.0, 0.0        # 두 포인터: [i, j) 창
            for i in range(n):
                while j < n and dsum < target - 1e-9:
                    dsum += km[j]
                    tsum += mn[j]
                    j += 1
                if dsum >= target - 1e-9 and dsum <= target * (1 + max_over):
                    sec = tsum * 60.0 * (target / dsum)
                    if best is None or sec < best[0]:
                        best = (sec, dsum, j - i, i, j - 1)
                dsum -= km[i]                   # 시작점을 한 칸 뒤로
                tsum -= mn[i]
            if best is None:
                continue
            sec, actual, nlaps, i0, i1 = best
            cur = out.get(name)
            if cur is None or sec < cur["sec"]:
                def _n(v):
                    try:
                        return int(float(v))
                    except (TypeError, ValueError):
                        return None
                out[name] = {"sec": float(sec), "date": wdate, "workout_id": wid,
                             "km": float(actual), "laps": int(nlaps),
                             "lap_from": _n(nos[i0]), "lap_to": _n(nos[i1]),
                             "exact": abs(actual - target) <= target * 0.02}
    return out


def detect_prs(df_work: pd.DataFrame, tol: float = 0.03,
               df_laps: pd.DataFrame = None) -> pd.DataFrame:
    """거리별 최고 기록 자동 추출.
    · 훈련 전체 거리가 목표와 ±3% 안에 드는 기록
    · (df_laps가 있으면) 훈련 안의 가장 빠른 연속 구간 — 1km만 따로 뛸 필요 없음
    둘 중 빠른 쪽을 채택하고 어디서 나온 기록인지 함께 돌려줍니다."""
    d = prepare_workouts(df_work)
    laps_best = lap_best_efforts(df_laps) if df_laps is not None else {}

    def _wlabel(row=None, wid=None):
        """기록이 나온 훈련을 '유형 7.36km'처럼 한 줄로."""
        r = row
        if r is None and wid is not None and not d.empty:
            m = d[d["WorkoutID"].astype(str) == str(wid)]
            r = m.iloc[0] if not m.empty else None
        if r is None:
            return "—"
        return f"{r.get('WorkoutType', '') or '훈련'} {_num(r.get('DistanceKm'), 0):.2f}km"

    rows = []
    for name, dist in PR_CATEGORIES:
        cand = []                          # (초, 날짜, 출처, 훈련, 메모)
        if not d.empty:
            c = d[(d["DistanceKm"] >= dist * (1 - tol)) & (d["DistanceKm"] <= dist * (1 + tol))]
            if not c.empty:
                c = c.assign(NormSec=c["DurationMinutes"] * 60.0 * (dist / c["DistanceKm"]))
                b = c.loc[c["NormSec"].idxmin()]
                cand.append((float(b["NormSec"]), b["WorkoutDate"], "훈련 전체",
                             _wlabel(row=b), ""))
        lb = laps_best.get(name)
        if lb is not None and pd.notna(lb["date"]):
            rng = (f"랩 {lb['lap_from']}~{lb['lap_to']}"
                   if lb.get("lap_from") is not None and lb["lap_from"] != lb["lap_to"]
                   else (f"랩 {lb['lap_from']}" if lb.get("lap_from") is not None else ""))
            note = " · ".join([x for x in
                               [rng, "" if lb["exact"] else f"{lb['km']:.2f}km 환산"] if x])
            cand.append((lb["sec"], lb["date"], f"구간 {lb['laps']}랩",
                         _wlabel(wid=lb["workout_id"]), note))
        if not cand:
            rows.append({"Category": name, "TimeOrDist": "-", "AchievedDate": "-",
                         "PaceStr": "-", "Source": "-", "Workout": "-", "Note": ""})
            continue
        sec, dt, src, wlab, note = min(cand, key=lambda x: x[0])
        rows.append({
            "Category": name,
            "TimeOrDist": time_str(sec),
            "AchievedDate": pd.Timestamp(dt).strftime("%Y-%m-%d"),
            "PaceStr": pace_str(sec / dist),
            "Source": src,
            "Workout": wlab,
            "Note": note,
            # VDOT 판정에 쓰려고 원본 수치를 함께 남깁니다
            "_sec": float(sec), "_dist": float(dist),
            "_date": pd.Timestamp(dt),
            "_type": str(wlab).split(" ")[0] if wlab else "",
        })
    if not d.empty:
        lr = d.loc[d["DistanceKm"].idxmax()]
        rows.append({"Category": "Longest Run", "TimeOrDist": f"{lr['DistanceKm']:.2f} km",
                     "AchievedDate": lr["WorkoutDate"].strftime("%Y-%m-%d"),
                     "PaceStr": pace_str(_num(lr["PaceSec"], np.nan)),
                     "Source": "훈련 전체", "Workout": _wlabel(row=lr), "Note": ""})
    return pd.DataFrame(rows)


# VDOT은 '최대노력 기록 한 건'에서 나오는 값입니다. 이지런 중간의 빠른 구간처럼
# 전력이 아닌 기록에서 뽑으면 실제 기량보다 한참 낮게 나옵니다.
HARD_TYPES = {"Race", "Time Trial", "Interval", "Threshold", "Tempo"}


def vdot_table(df_work: pd.DataFrame, df_laps: pd.DataFrame = None,
               days: int | None = 180, lthr: float | None = None) -> pd.DataFrame:
    """VDOT 후보 — 기간 안의 거리별 최고 기록마다 VDOT과 '최대노력인가' 판정.

    반환 컬럼: 종목 · 기록 · 날짜 · 페이스 · 유형 · VDOT · 최대노력 · 사유
    '최대노력'이 False인 기록으로 계산한 VDOT은 **실제보다 낮게** 나옵니다.
    """
    d = prepare_workouts(df_work)
    if d.empty:
        return pd.DataFrame()
    if days:
        cutoff = pd.Timestamp(datetime.now()).normalize() - timedelta(days=days - 1)
        d = d[d["WorkoutDate"] >= cutoff]
        if df_laps is not None and not df_laps.empty and "WorkoutID" in df_laps.columns:
            ids = set(d["WorkoutID"].astype(str))
            df_laps = df_laps[df_laps["WorkoutID"].astype(str).isin(ids)]
    if d.empty:
        return pd.DataFrame()

    prs = detect_prs(d, df_laps=df_laps)
    if prs.empty:
        return pd.DataFrame()
    hr_by_type = d.set_index(d["WorkoutID"].astype(str))["AvgHeartRate"].to_dict()
    rows = []
    for _, r in prs.iterrows():
        if r["Category"] == "Longest Run" or r["TimeOrDist"] == "-":
            continue
        sec, dist = _num(r.get("_sec"), np.nan), _num(r.get("_dist"), np.nan)
        if not (np.isfinite(sec) and np.isfinite(dist) and sec > 0 and dist > 0):
            continue
        v = vdot_from_performance(dist, sec / 60.0)
        wtype = str(r.get("_type") or "")
        hard = wtype in HARD_TYPES
        why = (f"{wtype} — 전력에 가까운 훈련" if hard else
               f"{wtype} — 최대노력이 아닙니다" if wtype else "유형을 알 수 없습니다")
        # 아주 짧은 구간(1km)은 유산소 기량 추정에 잘 맞지 않습니다
        if dist < 3.0:
            hard = False
            why = "1km는 VDOT 추정에 잘 맞지 않습니다 (5km 이상 권장)"
        rows.append({"종목": r["Category"], "기록": r["TimeOrDist"],
                     "날짜": r["AchievedDate"], "페이스": r["PaceStr"],
                     "유형": wtype or "—", "VDOT": round(float(v), 1)
                     if np.isfinite(v) else np.nan,
                     "최대노력": "✅" if hard else "—", "_hard": bool(hard),
                     "_date": r.get("_date"), "사유": why})
    out = pd.DataFrame(rows)
    return out.sort_values("VDOT", ascending=False).reset_index(drop=True) \
        if not out.empty else out


def vdot_pick(tbl: pd.DataFrame) -> dict:
    """후보 표에서 기준 하나를 고릅니다 — 최대노력 기록 우선, 없으면 최고 VDOT."""
    if tbl is None or tbl.empty:
        return {}
    hard = tbl[tbl["_hard"]]
    src = hard if not hard.empty else tbl
    row = src.loc[src["VDOT"].idxmax()]
    age = ((pd.Timestamp(datetime.now()).normalize()
            - pd.Timestamp(row["_date"])).days
           if pd.notna(row.get("_date")) else np.nan)
    return {"vdot": float(row["VDOT"]), "category": row["종목"],
            "time": row["기록"], "date": row["날짜"], "type": row["유형"],
            "hard": bool(row["_hard"]), "why": row["사유"],
            "age_days": int(age) if np.isfinite(age) else None}


def garmin_vdot(g: dict) -> pd.DataFrame:
    """가민 레이스 예측을 거꾸로 돌려 VDOT을 냅니다 — 교차검증용.

    가민 예측은 '그 거리를 전력으로 뛰면 이 정도'라는 값이라, 최대노력 기록이
    없을 때 VDOT의 현실적인 상한을 가늠하는 데 씁니다."""
    rows = []
    for key, label, dist in RACE_PRED_COLS:
        sec = parse_time_str(g.get(key))
        if not np.isfinite(sec) or sec <= 0:
            continue
        v = vdot_from_performance(dist, sec / 60.0)
        if np.isfinite(v):
            rows.append({"종목": label, "가민 예측": time_str(sec),
                         "VDOT": round(float(v), 1)})
    return pd.DataFrame(rows)


def weekly_summary(df_work: pd.DataFrame, weeks: int = 16) -> pd.DataFrame:
    """주간(월~일) 요약 — 거리/시간/횟수/롱런/평균페이스/전주 대비 증가율."""
    d = prepare_workouts(df_work)
    if d.empty:
        return pd.DataFrame()
    d["Week"] = d["WorkoutDate"].dt.to_period("W-SUN")
    g = d.groupby("Week").agg(
        Distance=("DistanceKm", "sum"),
        Minutes=("DurationMinutes", "sum"),
        Runs=("DistanceKm", "count"),
        LongRun=("DistanceKm", "max"),
    )
    full = pd.period_range(d["Week"].min(), d["Week"].max(), freq="W-SUN")
    g = g.reindex(full, fill_value=0.0)
    g["AvgPace"] = np.where(g["Distance"] > 0,
                            g["Minutes"] * 60.0 / g["Distance"].replace(0, np.nan), np.nan)
    g["AvgPaceStr"] = g["AvgPace"].apply(pace_str)
    g["WoW%"] = g["Distance"].pct_change().replace([np.inf, -np.inf], np.nan) * 100
    g["Ramp_Flag"] = np.where(g["WoW%"] > 10, "⚠️ 10% 룰 초과", "")
    g["MA4"] = g["Distance"].rolling(4, min_periods=1).mean()
    g.index = [p.start_time.strftime("%Y-%m-%d") for p in g.index]   # 주 시작일 표기
    return g.tail(weeks).round(1)


# ---------------------------------------------------------------------------
# 6. 경고(Alert) 엔진
# ---------------------------------------------------------------------------

def build_alerts(df_work: pd.DataFrame, df_shoes: pd.DataFrame,
                 daily: pd.DataFrame, weekly: pd.DataFrame,
                 intensity: dict) -> list[dict]:
    """대시보드 상단에 띄울 실행 가능한 경고 목록."""
    alerts = []
    if not daily.empty:
        last = daily.iloc[-1]
        acwr = float(last["ACWR"]) if np.isfinite(last["ACWR"]) else np.nan
        if np.isfinite(acwr) and acwr > 1.5:
            alerts.append({"level": "error",
                           "msg": f"ACWR {acwr:.2f} — 급성 부하 급증. 이번 주 볼륨 20~30% 감량 권장."})
        elif np.isfinite(acwr) and acwr > 1.3:
            alerts.append({"level": "warning", "msg": f"ACWR {acwr:.2f} — 증가 속도 주의."})
        if float(last["TSB"]) < -25:
            alerts.append({"level": "warning",
                           "msg": f"TSB {last['TSB']:.1f} — 피로 과다 축적. 회복주 편성 검토."})
        if np.isfinite(_num(last.get("Monotony"), np.nan)) and float(last["Monotony"]) > 2.0:
            alerts.append({"level": "info",
                           "msg": "훈련 단조로움(Monotony) 높음 — 강약 대비를 키울 것."})

    if weekly is not None and not weekly.empty and len(weekly) >= 2:
        w = weekly.iloc[-1]
        if np.isfinite(_num(w.get("WoW%"), np.nan)) and float(w["WoW%"]) > 10:
            alerts.append({"level": "warning",
                           "msg": f"주간 거리 전주 대비 +{float(w['WoW%']):.0f}% — 10% 룰 초과."})

    if intensity and intensity.get("polarized_pct"):
        low = intensity["polarized_pct"]["low"]
        if low < 75 and intensity.get("total_minutes", 0) > 300:
            alerts.append({"level": "warning",
                           "msg": f"저강도 비중 {low}% — 80/20 미달. 이지런을 늘릴 것."})

    # 신발 마모
    d = prepare_workouts(df_work)
    if df_shoes is not None and not df_shoes.empty and "ShoeID" in d.columns:
        for _, s in df_shoes.iterrows():
            if str(s.get("Status", "")).upper() == "RETIRED":
                continue
            sid = s.get("ShoeID")
            used = shoe_mileage(s, d)
            target = _num(s.get("TargetDistanceKm"), 600.0) or 600.0
            pct = used / target * 100
            if pct >= 100:
                alerts.append({"level": "error",
                               "msg": f"👟 {s.get('ShoeName', sid)} 수명 초과 ({used:.0f}/{target:.0f}km) — 교체."})
            elif pct >= 85:
                alerts.append({"level": "warning",
                               "msg": f"👟 {s.get('ShoeName', sid)} 수명 {pct:.0f}% — 교체 준비."})

    # 공백기
    if not d.empty:
        gap = (pd.Timestamp(datetime.now()).normalize() - d["WorkoutDate"].max()).days
        if gap >= 7:
            alerts.append({"level": "info", "msg": f"마지막 훈련 이후 {gap}일 경과 — 기록 누락 여부 확인."})
    return alerts


# ---------------------------------------------------------------------------
# 7. 레이스 D-day 플래너
# ---------------------------------------------------------------------------

def race_plan(vdot: float, race_distance_km: float, goal_time_sec: float | None,
              race_date: datetime, daily: pd.DataFrame) -> dict:
    """목표 레이스까지 남은 기간 + 현재 기량 대비 목표 갭 + 테이퍼 시점."""
    today = pd.Timestamp(datetime.now()).normalize()
    dday = (pd.Timestamp(race_date).normalize() - today).days
    pred = predict_time(vdot, race_distance_km)
    out = {
        "dday": dday,
        "predicted_sec": pred,
        "predicted_str": time_str(pred),
        "taper_start": (pd.Timestamp(race_date).normalize() - timedelta(days=14)).strftime("%Y-%m-%d"),
        "phase": "테이퍼" if 0 <= dday <= 14 else ("피크 빌드" if dday <= 42 else "베이스 빌드"),
    }
    if goal_time_sec and np.isfinite(pred):
        gap = pred - goal_time_sec
        out["gap_sec"] = gap
        out["gap_str"] = ("목표 대비 " + ("부족 " if gap > 0 else "여유 ") + time_str(abs(gap)))
        out["required_vdot"] = round(vdot_from_performance(race_distance_km, goal_time_sec / 60.0), 1)
    if not daily.empty and dday > 0:
        out["ctl_now"] = round(float(daily["CTL"].iloc[-1]), 1)
    return out


# ---------------------------------------------------------------------------
# 8. 가민(Garmin) 지표 — 이 앱의 1차 지표
#    아래 함수들은 사용자가 Garmin Connect에서 보고 입력한 값을 그대로 해석합니다.
#    계산으로 만들어내지 않습니다 (계산값은 위쪽 1~7절, 교차검증용).
# ---------------------------------------------------------------------------

# 가민 설명서의 정의를 그대로 옮긴 것입니다.
# ※ 이 값들은 '등급'이 아니라 '지금 어떤 국면인가'입니다. 생산적이 유지보다
#    좋은 것이 아니고, 무엇을 하려는 시기냐에 따라 맞는 상태가 다릅니다.
TRAINING_STATUS = {
    "Peaking":      ("ok",   "피킹 — 레이스에 딱 맞는 컨디션. 부하를 줄인 덕에 "
                             "그동안의 훈련 효과가 다 올라온 상태입니다"),
    "Productive":   ("ok",   "생산적 — 지금 부하가 기량을 올리는 방향으로 "
                             "작용하고 있습니다"),
    "Maintaining":  ("ok",   "유지 — 지금 부하로 현재 기량을 지키기에 충분합니다. "
                             "더 올리려면 볼륨을 늘리거나 훈련에 변화를 주세요"),
    "Recovery":     ("ok",   "회복 — 부하를 낮춰 몸이 회복하는 중입니다. "
                             "힘든 시기가 이어질 때 꼭 필요한 구간입니다"),
    "Unproductive": ("warn", "비생산적 — 부하는 충분한데 기량이 떨어지고 있습니다. "
                             "수면·영양·스트레스를 함께 보세요"),
    "Detraining":   ("warn", "트레이닝 부족 — 한 주 이상 평소보다 훨씬 적게 "
                             "훈련했습니다"),
    "Overreaching": ("bad",  "과훈련 — 부하가 너무 높아 오히려 역효과입니다. "
                             "쉬어야 합니다"),
    "Strained":     ("warn", "부하 과다 — 회복 대비 부하가 큽니다. 힘든 훈련이나 "
                             "큰 대회 뒤에는 정상적으로 나타납니다"),
    "No Status":    ("info", "상태 없음 — 2주 이상의 기록이 더 필요합니다"),
}
TRAINING_STATUS_KR = {
    "Peaking": "피킹", "Productive": "생산적", "Maintaining": "유지",
    "Recovery": "회복", "Unproductive": "비생산적", "Detraining": "트레이닝 부족",
    "Overreaching": "과훈련", "Strained": "부하 과다", "No Status": "상태 없음",
}
PRIMARY_BENEFIT = ["", "Recovery", "Base", "Tempo", "Threshold", "VO2max", "Anaerobic", "Sprint"]


def parse_time_str(s) -> float:
    """'3:29:41' / '44:58' → 초. 비어 있으면 nan."""
    if s is None:
        return np.nan
    t = str(s).strip()
    if not t or ":" not in t:
        return np.nan
    try:
        p = [float(x) for x in t.split(":")]
    except ValueError:
        return np.nan
    if len(p) == 3:
        return p[0] * 3600 + p[1] * 60 + p[2]
    if len(p) == 2:
        return p[0] * 60 + p[1]
    return np.nan


def _measured_ts(df: pd.DataFrame, date_col: str) -> pd.Series:
    """'언제 본 값인가'를 시각까지 포함해 돌려줍니다.
    MeasuredAt('2026-09-20 07:51 (가민 업데이트 기준)')이 있으면 그 시각을,
    없으면 그 날 00:00을 씁니다. 회복 시간을 '지금 기준 남은 시간'으로 되돌리거나,
    같은 날 줄이 둘 이상일 때 어느 쪽이 더 나중인지 가리는 데 씁니다."""
    base = pd.to_datetime(df[date_col], errors="coerce")
    if "MeasuredAt" not in df.columns:
        return base
    txt = df["MeasuredAt"].astype(str).str.extract(
        r"(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2})", expand=False)
    exact = pd.to_datetime(txt, errors="coerce")
    return exact.fillna(base)


def add_intensity_rolling(gdv: pd.DataFrame,
                          date_col: str = "StatusDate") -> pd.DataFrame:
    """‘당일 고강도 분’에서 **최근 7일 누적**과 **이번 주(월~일) 누적**을 만듭니다.

    가민 시계의 주간 고강도는 롤링 7일이라 매일 값이 달라집니다. 그걸 매일
    받아 적으면 요일 효과 때문에 추이가 읽히지 않습니다 — 그래서 **당일 값만
    적고 누적은 여기서 계산**합니다. 당일 값이 없는 날은 0으로 봅니다.
    """
    if gdv is None or gdv.empty or date_col not in gdv.columns:
        return gdv
    d = gdv.copy()
    if "IntensityMinutesDay" not in d.columns:
        d["IntensityMin7"] = np.nan
        d["IntensityMinWeek"] = np.nan
        return d
    d[date_col] = pd.to_datetime(d[date_col], errors="coerce")
    v = pd.to_numeric(d["IntensityMinutesDay"], errors="coerce")
    if v.notna().sum() == 0:
        d["IntensityMin7"] = np.nan
        d["IntensityMinWeek"] = np.nan
        return d
    day = (d[[date_col]].assign(v=v).dropna(subset=[date_col])
           .groupby(date_col, as_index=True)["v"].max())
    full = day.reindex(pd.date_range(day.index.min(), day.index.max(), freq="D"))
    filled = full.fillna(0.0)
    roll7 = filled.rolling(7, min_periods=1).sum()
    wk = filled.groupby(filled.index.to_period("W-SUN")).cumsum()
    # 값을 한 번도 안 넣은 날은 누적도 비워 둡니다 (0으로 오해하지 않게)
    seen = full.notna().cumsum() > 0
    d["IntensityMin7"] = d[date_col].map(roll7.where(seen))
    d["IntensityMinWeek"] = d[date_col].map(wk.where(seen))
    return d


def merge_daily_rows(df_daily: pd.DataFrame) -> pd.DataFrame:
    """같은 날짜의 여러 줄을 한 줄로 합칩니다.

    항목마다 **본 시각(MeasuredAt)이 가장 나중인 값**을 남기고, 그 줄에서 비어
    있으면 같은 날의 다른 줄 값으로 채웁니다. 어떤 값도 사라지지 않습니다.
    (아침/훈련 후 체크인이 따로였던 시절에 하루 두 줄이 생겼습니다)
    """
    if df_daily is None or df_daily.empty or "StatusDate" not in df_daily.columns:
        return df_daily
    d = df_daily.copy()
    d["_day"] = d["StatusDate"].astype(str).str.strip().str.slice(0, 10)
    d["_ts"] = _measured_ts(d, "StatusDate")
    d = d.sort_values(["_day", "_ts"], kind="stable")

    def _blank(v):
        return (v is None or (not isinstance(v, str) and pd.isna(v))
                or str(v).strip() in ("", "nan", "None", "NaT", "<NA>", "—"))

    out = []
    for day, g in d.groupby("_day", sort=True):
        if day == "":
            out.extend(g.to_dict("records"))
            continue
        base = g.iloc[-1].to_dict()              # 가장 나중에 본 줄이 기준
        for _, r in g.iloc[::-1].iterrows():     # 나중 → 먼저 순으로 빈 칸 채우기
            for k, v in r.items():
                if _blank(base.get(k)) and not _blank(v):
                    base[k] = v
        out.append(base)
    res = pd.DataFrame(out).drop(columns=["_day", "_ts"], errors="ignore")
    if "StatusDate" in res.columns:
        res = res.sort_values("StatusDate", kind="stable")
    return res.reset_index(drop=True)


def _latest(df: pd.DataFrame, date_col: str, field: str):
    """해당 컬럼에서 값이 있는 가장 최근 행의 (값, 날짜)."""
    if df is None or df.empty or field not in df.columns:
        return None, None, None
    d = df.copy()
    d["_ts"] = _measured_ts(d, date_col)
    d[date_col] = pd.to_datetime(d[date_col], errors="coerce")
    d = d.dropna(subset=[date_col]).sort_values(["_ts", date_col], kind="stable")
    vals = d[field]
    # '—'/'-' 는 '값 없음'입니다. 예전에 빈 칸을 '—'로 저장한 줄이 있어서,
    # 그 줄이 '가장 최근 값'으로 잡혀 진짜 값을 가리는 일이 있었습니다.
    _txt = vals.astype(str).str.strip()
    mask = vals.notna() & ~_txt.isin(["", "—", "-", "nan", "None", "<NA>"])
    if not mask.any():
        return None, None, None
    row = d[mask].iloc[-1]
    return row[field], row[date_col], row["_ts"]


def latest_garmin(df_daily: pd.DataFrame, df_metrics: pd.DataFrame) -> dict:
    """가민 일일/주간 지표에서 '가장 최근에 입력된 값'을 필드별로 모읍니다.
    필드마다 입력 주기가 다르므로 행 단위가 아니라 컬럼 단위로 최신값을 찾습니다."""
    out = {}
    daily_fields = ["TrainingStatus", "AcuteLoad", "ChronicLoad", "LoadRatio",
                    "RecoveryTimeHr",
                    "TrainingReadiness", "BodyBattery", "HRVStatus", "HRVms",
                    "SleepScore", "RestingHR", "IntensityMinutes",
                    "IntensityMinutesDay",
                    "MeasuredAt", "RecoveryUntil",
                    "SleepHistory", "StressHistory"]
    weekly_fields = ["VO2Max", "FitnessAge", "EnduranceScore", "HillScore",
                     "FocusAnaerobic", "FocusHighAerobic", "FocusLowAerobic",
                     "Pred5K", "Pred10K", "PredHalf", "PredFull",
                     "LTPace", "LTHR", "WeightKg", "BodyFatPct"]
    for f in daily_fields:
        v, dt, ts = _latest(df_daily, "StatusDate", f)
        out[f], out[f + "_date"], out[f + "_at"] = v, dt, ts
    for f in weekly_fields:
        v, dt, ts = _latest(df_metrics, "MetricDate", f)
        out[f], out[f + "_date"], out[f + "_at"] = v, dt, ts
    return out


# 가민 '트레이닝 준비 상태' 점수 구간 (Forerunner/fenix 사용설명서 기준)
READINESS_TIERS = [(95, "최상", "ok"), (75, "높음", "ok"), (50, "중간", "info"),
                   (25, "낮음", "warn"), (1, "나쁨", "bad")]


def readiness_meta(score) -> tuple[str, str]:
    """Training Readiness 점수 → (톤, 등급 한글). 시계에 뜨는 등급과 같습니다."""
    v = _num(score, np.nan)
    if not np.isfinite(v) or v <= 0:
        return "", "미입력"
    for lo, kr, tone in READINESS_TIERS:
        if v >= lo:
            return tone, kr
    return "bad", "나쁨"


# 가민이 준비 상태를 계산할 때 쓰는 여섯 가지 요인
_HIST_TONE = {"좋음": "ok", "낮음": "ok", "균형 잡힘": "ok", "최적": "ok",
              "낮은 필요성": "ok", "보통": "warn", "높음": "warn",
              "중간 필요성": "warn", "나쁨": "bad", "매우 높음": "bad",
              "높은 필요성": "bad", "불균형": "warn"}


def readiness_factors(g: dict) -> list[dict]:
    """시계의 '요인' 목록과 같은 순서로 (이름, 값, 상태, 톤)을 만들어 줍니다.
    입력하지 않은 항목은 값 자리에 '—'가 들어갑니다."""
    def num(k, fmt="{:.0f}", suffix=""):
        v = _num(g.get(k), np.nan)
        return (fmt.format(v) + suffix) if np.isfinite(v) and v > 0 else "—"

    hrv_kr = {"Balanced": "균형 잡힘", "Unbalanced": "불균형",
              "Low": "낮음", "Poor": "나쁨"}.get(str(g.get("HRVStatus") or ""), "")
    rec_h = _num(g.get("RecoveryTimeHr"), np.nan)
    rec_state = ("" if not np.isfinite(rec_h) else
                 "낮은 필요성" if rec_h <= 12 else
                 "중간 필요성" if rec_h <= 36 else "높은 필요성")
    _, lr_txt = load_ratio_meta(effective_load_ratio(g)[0])
    lr_state = (lr_txt.split(" —")[0]
                if np.isfinite(effective_load_ratio(g)[0]) else "")
    slp = _num(g.get("SleepScore"), np.nan)
    slp_state = ("" if not np.isfinite(slp) or slp <= 0 else
                 "좋음" if slp >= 80 else "보통" if slp >= 60 else "나쁨")

    _ch = _num(g.get("ChronicLoad"), np.nan)
    _ac_note = ("최근 7일 누적" if not np.isfinite(_ch) or _ch <= 0
                else f"최근 7일 누적 · 만성 {_ch:,.0f}")
    rows = [("수면 점수", num("SleepScore"), slp_state, "지난밤"),
            ("회복 시간", num("RecoveryTimeHr", "{:.0f}", "h"), rec_state, "지금 기준"),
            ("HRV 상태", num("HRVms", "{:.0f}", " ms"), hrv_kr, "밤사이 평균"),
            ("단기 부하", num("AcuteLoad", "{:,.0f}"), lr_state, _ac_note),
            ("최근 수면 점수", "", str(g.get("SleepHistory") or ""), "최근 3일"),
            ("최근 스트레스", "", str(g.get("StressHistory") or ""), "최근 3일")]
    out = []
    for name, val, state, note in rows:
        out.append({"name": name, "value": val or "", "state": state or "—",
                    "tone": _HIST_TONE.get(state, ""), "note": note})
    return out


def shoe_mileage(shoe: dict | pd.Series, df_prepared: pd.DataFrame) -> float:
    """러닝화 누적 거리 = 기존 누적 + (기준일 이후) 이 신발로 뛴 거리.

    '기존 누적'은 앱을 쓰기 전까지 이미 신은 거리입니다. 기준일(InitialAsOf)이
    있으면 그날까지는 기존 누적에 이미 포함된 것으로 보고, **그 다음 날부터**의
    훈련만 더합니다. 그래야 나중에 예전 기록을 넣어도 두 번 세어지지 않습니다.
    기준일이 비어 있으면 예전처럼 전체를 더합니다.
    """
    base = _num(shoe.get("InitialDistanceKm"), 0.0)
    if df_prepared is None or df_prepared.empty or "ShoeID" not in df_prepared.columns:
        return float(base if np.isfinite(base) else 0.0)
    m = df_prepared["ShoeID"].astype(str) == str(shoe.get("ShoeID"))
    asof = pd.to_datetime(shoe.get("InitialAsOf"), errors="coerce")
    if pd.notna(asof):
        m &= df_prepared["WorkoutDate"] > asof
    ran = float(df_prepared.loc[m, "DistanceKm"].sum())
    return float((base if np.isfinite(base) else 0.0) + ran)


# 색을 칠할 때 쓰는 묶음 — '좋다/나쁘다'가 아니라 '지금 뭘 해야 하나'입니다.
STATUS_GROUP = {
    "피킹": "정상 진행", "생산적": "정상 진행", "유지": "정상 진행", "회복": "정상 진행",
    "비생산적": "살펴볼 것", "트레이닝 부족": "살펴볼 것", "부하 과다": "살펴볼 것",
    "과훈련": "줄여야 할 것",
    "상태 없음": "정상 진행",
}


def status_meta(status) -> tuple[str, str, str]:
    """Training Status → (톤, 한글명, 설명)"""
    s = str(status or "").strip()
    tone, desc = TRAINING_STATUS.get(s, ("info", "가민에서 확인한 값을 입력하세요"))
    return tone, TRAINING_STATUS_KR.get(s, s or "—"), desc


def effective_load_ratio(g: dict) -> tuple[float, str]:
    """부하 비율 = 급성 ÷ 만성.

    두 값을 다 받아 두면 직접 계산합니다. 시계 화면은 비율을 소수 한 자리로
    반올림해 보여주므로(624/712 = 0.88 → '0.8'), 계산한 값이 더 정확합니다.
    만성 부하가 없으면 입력해 둔 비율을 그대로 씁니다.
    반환: (비율, "계산" | "입력" | "")
    """
    ac = _num(g.get("AcuteLoad"), np.nan)
    ch = _num(g.get("ChronicLoad"), np.nan)
    if np.isfinite(ac) and np.isfinite(ch) and ch > 0:
        return ac / ch, "계산"
    # 저장된 비율이 지금 보는 '급성 부하'보다 오래된 것이면 쓰지 않습니다.
    # (예전 날짜의 1.43을 오늘 값인 것처럼 보여주면 안 됩니다)
    r = _num(g.get("LoadRatio"), np.nan)
    r_at, a_at = g.get("LoadRatio_at"), g.get("AcuteLoad_at")
    if np.isfinite(r) and r_at is not None and a_at is not None:
        try:
            if pd.Timestamp(r_at) < pd.Timestamp(a_at):
                return np.nan, "만성 부하 필요"
        except Exception:
            pass
    return (r, "입력") if np.isfinite(r) else (np.nan, "")


def load_ratio_meta(ratio) -> tuple[str, str]:
    """가민 부하 비율(급성 ÷ 만성) 해석 — 시계 설명서의 구간을 그대로 씁니다.
    0.8 미만 낮음 · 0.8~1.4 최적 · 1.5~1.9 높음 · 2.0 이상 매우 높음."""
    r = _num(ratio, np.nan)
    if not np.isfinite(r):
        return "info", "미입력"
    if r < 0.8:
        return "warn", "낮음 — 단기 부하가 평소보다 적음"
    if r < 1.5:
        return "ok", "최적"
    if r < 2.0:
        return "warn", "높음 — 늘리는 속도 주의"
    return "bad", "매우 높음 — 회복 우선"


def recovery_remaining(g: dict, now=None):
    """회복 시간은 훈련 종료 시점부터 계속 줄어드는 카운트다운입니다.
    입력할 때 함께 저장한 '회복 완료 예상 시각'으로 **지금 기준 남은 시간**을 다시
    계산합니다. 완료 시각이 없으면(예전 기록) 입력값을 그대로 돌려줍니다.

    반환: (남은시간h, 원래입력값h, 완료시각텍스트, 재계산했는지)
    """
    raw = _num(g.get("RecoveryTimeHr"), np.nan)
    until = str(g.get("RecoveryUntil") or "").strip()
    if not until:
        return raw, raw, "", False
    try:
        u = pd.to_datetime(until, errors="coerce")
        if pd.isna(u):
            return raw, raw, "", False
    except Exception:
        return raw, raw, "", False
    ref = pd.Timestamp(now) if now is not None else pd.Timestamp.now()
    left = max(0.0, (u - ref).total_seconds() / 3600.0)
    return left, raw, u.strftime("%m/%d %H:%M"), True


def recovery_meta(hours) -> tuple[str, str]:
    h = _num(hours, np.nan)
    if not np.isfinite(h):
        return "info", "미입력"
    if h < 12:
        return "ok", "고강도 훈련 가능"
    if h < 36:
        return "warn", "가벼운 훈련만"
    return "bad", "휴식 권장"


def load_focus(g: dict) -> dict:
    """가민 Load Focus(무산소 / 고강도 유산소 / 저강도 유산소) 분해."""
    an = _num(g.get("FocusAnaerobic"), np.nan)
    hi = _num(g.get("FocusHighAerobic"), np.nan)
    lo = _num(g.get("FocusLowAerobic"), np.nan)
    vals = [v for v in (an, hi, lo) if np.isfinite(v)]
    if not vals or sum(vals) <= 0:
        return {}
    tot = sum(v for v in (an, hi, lo) if np.isfinite(v))
    pct = {k: (round(v / tot * 100, 1) if np.isfinite(v) else 0.0)
           for k, v in [("anaerobic", an), ("high_aerobic", hi), ("low_aerobic", lo)]}

    msgs = []
    if pct["anaerobic"] < 5:
        msgs.append("무산소 부족 — 스프린트/짧은 인터벌 추가")
    if pct["high_aerobic"] < 10:
        msgs.append("고강도 유산소 부족 — 템포/역치 훈련 추가")
    if pct["low_aerobic"] < 50:
        msgs.append("저강도 유산소 부족 — 이지런 비중 확대")
    verdict = "✅ 균형 잡힘" if not msgs else " · ".join(msgs)
    return {"raw": {"anaerobic": an, "high_aerobic": hi, "low_aerobic": lo},
            "pct": pct, "verdict": verdict, "balanced": not msgs}


# ── Endurance Score / Hill Score 등급 ────────────────────────────────────
# 출처: Garmin Forerunner 965 사용설명서 "Endurance Score Ratings" (Firstbeat Analytics)
# 아래 숫자는 각 등급의 '시작값'(하한)입니다. 성별·나이대에 따라 기준이 다릅니다.
ENDURANCE_TIERS = ["Recreational", "Intermediate", "Trained", "Well Trained",
                   "Expert", "Superior", "Elite"]
ENDURANCE_TIERS_KR = {
    "Recreational": "레크리에이션", "Intermediate": "중급", "Trained": "훈련됨",
    "Well Trained": "잘 훈련됨", "Expert": "엑스퍼트", "Superior": "수준급",
    "Elite": "엘리트"}

# (나이 하한, [Intermediate, Trained, Well Trained, Expert, Superior, Elite 시작값])
_ENDURANCE_CUTS = {
    "M": [(18, [5000, 5700, 6300, 7000, 7600, 8300]),
          (21, [5100, 5800, 6600, 7300, 8100, 8800]),
          (40, [5100, 5800, 6500, 7200, 7900, 8600]),
          (45, [5000, 5700, 6400, 7000, 7700, 8400]),
          (50, [4900, 5500, 6100, 6800, 7400, 8000]),
          (55, [4600, 5100, 5700, 6200, 6800, 7300]),
          (60, [4300, 4800, 5300, 5700, 6200, 6700]),
          (65, [4100, 4500, 4900, 5400, 5800, 6200]),
          (70, [3800, 4200, 4600, 4900, 5300, 5700]),
          (75, [3600, 3900, 4300, 4600, 5000, 5300]),
          (80, [3300, 3600, 4000, 4300, 4700, 5000])],
    "F": [(18, [4600, 5100, 5500, 6000, 6400, 6900]),
          (21, [4700, 5200, 5700, 6300, 6800, 7300]),
          (40, [4700, 5200, 5700, 6200, 6700, 7200]),
          (45, [4600, 5100, 5600, 6100, 6600, 7100]),
          (50, [4500, 5000, 5400, 5900, 6300, 6800]),
          (55, [4300, 4700, 5100, 5600, 6000, 6400]),
          (60, [4100, 4500, 4900, 5300, 5700, 6100]),
          (65, [3800, 4200, 4600, 4900, 5300, 5700]),
          (70, [3700, 4100, 4400, 4800, 5100, 5500]),
          (75, [3500, 3800, 4200, 4500, 4900, 5200]),
          (80, [3200, 3500, 3800, 4100, 4400, 4700])]}

_ENDURANCE_BRACKET_LABEL = {18: "18–20", 21: "21–39", 40: "40–44", 45: "45–49",
                            50: "50–54", 55: "55–59", 60: "60–64", 65: "65–69",
                            70: "70–74", 75: "75–80", 80: "80+"}

# Hill Score는 나이·성별 구분 없이 1~100 고정 구간입니다.
HILL_TIERS = [(1, "Recreational", "레크리에이션"), (25, "Challenger", "챌린저"),
              (50, "Trained", "훈련됨"), (70, "Skilled", "숙련"),
              (85, "Expert", "엑스퍼트"), (95, "Elite", "엘리트")]

_TIER_TONE = ["", "", "info", "info", "ok", "ok", "ok"]


def _endurance_bracket(sex: str, age) -> tuple[int, list[int]]:
    tbl = _ENDURANCE_CUTS.get(str(sex or "M").upper()[:1], _ENDURANCE_CUTS["M"])
    a = _num(age, np.nan)
    if not np.isfinite(a):
        a = 39.0                      # 나이 미입력이면 21~39 기준으로 봅니다
    lo, cuts = tbl[0]
    for age_lo, c in tbl:
        if a >= age_lo:
            lo, cuts = age_lo, c
    return lo, cuts


def endurance_meta(score, age=None, sex: str = "M") -> dict:
    """Endurance Score 등급 + 해당 성별·나이대의 전체 구간표."""
    lo, cuts = _endurance_bracket(sex, age)
    bands = []                        # [(등급, 한글, 시작값, 끝값 or None)]
    for i, name in enumerate(ENDURANCE_TIERS):
        start = None if i == 0 else cuts[i - 1]
        end = cuts[i] - 1 if i < len(cuts) else None
        bands.append((name, ENDURANCE_TIERS_KR[name], start, end))
    s = _num(score, np.nan)
    idx = None
    if np.isfinite(s) and s > 0:
        idx = 0
        for i, c in enumerate(cuts):
            if s >= c:
                idx = i + 1
    nxt = ""
    if idx is not None and idx < len(cuts):
        nxt = (f"다음 등급({ENDURANCE_TIERS_KR[ENDURANCE_TIERS[idx + 1]]})까지 "
               f"{cuts[idx] - s:,.0f}점")
    return {"tier": ENDURANCE_TIERS[idx] if idx is not None else "—",
            "kr": ENDURANCE_TIERS_KR[ENDURANCE_TIERS[idx]] if idx is not None else "—",
            "tone": _TIER_TONE[idx] if idx is not None else "",
            "index": idx, "bands": bands, "next_text": nxt,
            "bracket": f"{'남성' if str(sex or 'M').upper().startswith('M') else '여성'} "
                       f"{_ENDURANCE_BRACKET_LABEL.get(lo, '')}세 기준"}


def hill_meta(score) -> dict:
    """Hill Score 등급 + 전체 구간표 (나이·성별 무관)."""
    bands = []
    for i, (start, name, kr) in enumerate(HILL_TIERS):
        end = HILL_TIERS[i + 1][0] - 1 if i + 1 < len(HILL_TIERS) else 100
        bands.append((name, kr, start, end))
    s = _num(score, np.nan)
    idx = None
    if np.isfinite(s) and s > 0:
        idx = 0
        for i, (start, _n, _k) in enumerate(HILL_TIERS):
            if s >= start:
                idx = i
    nxt = ""
    if idx is not None and idx + 1 < len(HILL_TIERS):
        nxt = f"다음 등급({HILL_TIERS[idx + 1][2]})까지 {HILL_TIERS[idx + 1][0] - s:.0f}점"
    return {"tier": HILL_TIERS[idx][1] if idx is not None else "—",
            "kr": HILL_TIERS[idx][2] if idx is not None else "—",
            "tone": _TIER_TONE[idx] if idx is not None else "",
            "index": idx, "bands": bands, "next_text": nxt,
            "bracket": "1~100점 척도"}


def endurance_tier(score, age=None, sex: str = "M") -> str:
    """이전 버전 호환용 — 등급 이름만 돌려줍니다."""
    return endurance_meta(score, age, sex)["tier"]


def age_from_birth(birth) -> float:
    """생년월일(또는 연도)에서 만 나이. 알 수 없으면 NaN."""
    if birth is None or str(birth).strip() == "":
        return float("nan")
    try:
        b = pd.to_datetime(str(birth), errors="coerce")
        if pd.isna(b):
            y = float(str(birth).strip()[:4])
            return float(date.today().year - y)
        t = date.today()
        return float(t.year - b.year - ((t.month, t.day) < (b.month, b.day)))
    except Exception:
        return float("nan")


# 종목별로 '말이 되는' 최대 기록(시간). 이보다 크면 잘못 저장된 값으로 봅니다.
_PRED_MAX_H = {"Pred5K": 1.5, "Pred10K": 3.0, "PredHalf": 6.0, "PredFull": 12.0}


def fix_race_pred(txt, key: str) -> str:
    """구글 시트가 시간으로 오해해 저장한 예측 기록을 되돌립니다.

    '48:28'(48분 28초)을 시트가 48시간 28분으로 읽어 '48:28:00'으로 저장하는
    일이 있었습니다. 종목별 상식 범위를 넘으면 맨 뒤 칸을 떼고 다시 읽습니다.
    (10km 48시간은 있을 수 없으니 48:28 = 48분 28초로 봅니다.)
    """
    t = str(txt or "").strip()
    if not t or t in ("—", "-"):
        # 빈 칸은 '값 없음'이어야 합니다. 예전에는 '—'를 저장해서, 그 줄이
        # '가장 최근 값'으로 잡혀 진짜 예측 기록을 가려 버렸습니다.
        return ""
    parts = t.split(":")
    if len(parts) < 2:
        return t
    try:
        nums = [float(x) for x in parts]
    except ValueError:
        return t
    hours = (nums[0] + nums[1] / 60 + (nums[2] / 3600 if len(nums) > 2 else 0)
             if len(nums) >= 3 else nums[0] / 60 + nums[1] / 3600)
    cap = _PRED_MAX_H.get(key, 12.0)
    if hours <= cap:
        return t
    # 맨 뒤 칸을 떼고(보통 ':00') 다시 읽어 봅니다
    if len(parts) >= 3 and float(parts[-1]) == 0:
        shorter = ":".join(parts[:-1])
        n2 = [float(x) for x in parts[:-1]]
        if (n2[0] / 60 + n2[1] / 3600) <= cap:
            return shorter
    return t


def garmin_race_predictions(g: dict) -> list[tuple[str, str]]:
    return [(n, fix_race_pred(g.get(k), k)) for n, k in
            [("5km", "Pred5K"), ("10km", "Pred10K"),
             ("Half Marathon", "PredHalf"), ("Full Marathon", "PredFull")]]


RACE_PRED_COLS = [("Pred5K", "5K", 5.0), ("Pred10K", "10K", 10.0),
                  ("PredHalf", "하프", 21.0975), ("PredFull", "풀", 42.195)]


def race_pred_trend(df_metrics: pd.DataFrame) -> pd.DataFrame:
    """가민 레이스 예측의 시간 흐름.

    종목마다 완주 시간의 크기가 완전히 달라(22분 vs 4시간) 한 축에 같이 그릴 수
    없습니다. 그래서 가민처럼 **km당 페이스**로 바꿔 한 축에 올립니다.
    반환 컬럼: MetricDate · 종목 · 거리km · Seconds(완주초) · PaceSec(초/km)
    """
    cols = ["MetricDate"] + [c for c, _, _ in RACE_PRED_COLS]
    if df_metrics is None or df_metrics.empty:
        return pd.DataFrame(columns=["MetricDate", "종목", "거리km", "Seconds", "PaceSec"])
    d = df_metrics.reindex(columns=cols).copy()
    d["MetricDate"] = pd.to_datetime(d["MetricDate"], errors="coerce")
    d = d.dropna(subset=["MetricDate"]).sort_values("MetricDate")
    rows = []
    for _, r in d.iterrows():
        for col, name, km in RACE_PRED_COLS:
            sec = parse_time_str(fix_race_pred(r.get(col), col))
            if not np.isfinite(sec) or sec <= 0:
                continue
            rows.append({"MetricDate": r["MetricDate"], "종목": name, "거리km": km,
                         "Seconds": sec, "PaceSec": sec / km})
    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(columns=["MetricDate", "종목", "거리km", "Seconds", "PaceSec"])
    # 같은 날 여러 번 넣었으면 마지막 것만
    return (out.sort_values("MetricDate")
               .drop_duplicates(subset=["MetricDate", "종목"], keep="last")
               .reset_index(drop=True))


def race_pred_summary(trend: pd.DataFrame) -> pd.DataFrame:
    """종목별 '처음 → 마지막' 변화 표. 기간 안에서 얼마나 좋아졌는지."""
    if trend is None or trend.empty:
        return pd.DataFrame()
    rows = []
    for _, name, _km in RACE_PRED_COLS:
        t = trend[trend["종목"] == name]
        if t.empty:
            continue
        first, last = t.iloc[0], t.iloc[-1]
        diff = last["Seconds"] - first["Seconds"]
        rows.append({
            "종목": name,
            "기간 시작": time_str(first["Seconds"]),
            "최근": time_str(last["Seconds"]),
            "변화": ("—" if len(t) < 2 else
                     f"{'-' if diff < 0 else '+'}{time_str(abs(diff))}"),
            "최근 페이스": pace_str(last["PaceSec"]),
        })
    return pd.DataFrame(rows)


def garmin_vs_computed(g: dict, summary: dict, evo2: dict, vdot: float) -> list[dict]:
    """가민이 준 값과 이 앱이 기록으로 계산한 값을 나란히 비교.
    둘이 크게 어긋나면 입력 오류이거나 훈련 성격이 한쪽에 치우쳤다는 신호입니다."""
    rows = []

    gv = _num(g.get("VO2Max"), np.nan)
    cv = _num(evo2.get("value"), np.nan) if evo2 else np.nan
    if np.isfinite(gv) or np.isfinite(cv):
        diff = (cv - gv) if (np.isfinite(gv) and np.isfinite(cv)) else np.nan
        rows.append({
            "항목": "VO₂max",
            "가민": f"{gv:.0f}" if np.isfinite(gv) else "—",
            "계산": f"{cv:.1f}" if np.isfinite(cv) else "—",
            "차이": f"{diff:+.1f}" if np.isfinite(diff) else "—",
            "note": "계산값은 심박 여유율 기준이라 이지런 위주면 낮게 나옵니다.",
        })

    gr = _num(g.get("LoadRatio"), np.nan)
    ca = summary.get("acwr") if summary else None
    if np.isfinite(gr) or ca is not None:
        rows.append({
            "항목": "급성:만성 부하비",
            "가민": f"{gr:.2f}" if np.isfinite(gr) else "—",
            "계산": f"{ca:.2f}" if ca is not None else "—",
            "차이": f"{(ca - gr):+.2f}" if (ca is not None and np.isfinite(gr)) else "—",
            "note": "가민은 자체 부하 단위, 계산값은 TRIMP 기준이라 절대값보다 추세를 보세요.",
        })

    gp = parse_time_str(g.get("Pred10K"))
    cp = predict_time(vdot, 10.0) if np.isfinite(vdot) else np.nan
    if np.isfinite(gp) or np.isfinite(cp):
        rows.append({
            "항목": "10K 예상 기록",
            "가민": time_str(gp) if np.isfinite(gp) else "—",
            "계산": time_str(cp) if np.isfinite(cp) else "—",
            "차이": (f"{(cp - gp):+.0f}초" if (np.isfinite(gp) and np.isfinite(cp)) else "—"),
            "note": "계산값은 실제 최고 기록 기반, 가민은 추정 기반입니다.",
        })
    return rows


def garmin_alerts(g: dict) -> list[dict]:
    """가민 지표만으로 만드는 경고 (계산 지표 경고와 별개)."""
    out = []
    tone, kr, desc = status_meta(g.get("TrainingStatus"))
    if tone == "bad":
        out.append({"level": "error", "msg": f"가민 트레이닝 상태 «{kr}» — {desc}"})
    elif tone == "warn":
        out.append({"level": "warning", "msg": f"가민 트레이닝 상태 «{kr}» — {desc}"})

    rt, rtxt = recovery_meta(g.get("RecoveryTimeHr"))
    if rt == "bad":
        out.append({"level": "warning",
                    "msg": f"회복 시간 {_num(g.get('RecoveryTimeHr')):.0f}시간 남음 — {rtxt}"})

    lt, ltxt = load_ratio_meta(g.get("LoadRatio"))
    if lt == "bad":
        out.append({"level": "error", "msg": f"가민 부하비 {_num(g.get('LoadRatio')):.2f} — {ltxt}"})
    elif lt == "warn":
        out.append({"level": "info", "msg": f"가민 부하비 {_num(g.get('LoadRatio')):.2f} — {ltxt}"})

    hrv = str(g.get("HRVStatus") or "")
    if hrv in ("Low", "Poor"):
        out.append({"level": "warning", "msg": f"HRV 상태 «{hrv}» — 수면과 스트레스를 먼저 점검하세요."})

    fo = load_focus(g)
    if fo and not fo.get("balanced"):
        out.append({"level": "info", "msg": f"가민 Load Focus — {fo['verdict']}"})
    return out


# ---------------------------------------------------------------------------
# 9. 랩(구간) 기반 분석
#    세션 '평균' 심박 하나로 존을 매기면 인터벌이 중간 존으로 뭉개집니다.
#    랩이 있는 훈련은 랩 단위로 존을 매겨 정확도를 크게 올립니다.
# ---------------------------------------------------------------------------

def laps_with_context(df_laps: pd.DataFrame, df_work: pd.DataFrame) -> pd.DataFrame:
    """랩에 훈련 날짜/유형을 붙인다 (Laps 시트에 이미 있으면 그대로 사용)."""
    if df_laps is None or df_laps.empty:
        return pd.DataFrame()
    L = df_laps.copy()
    need = ("WorkoutDate" not in L.columns) or \
           (pd.to_datetime(L.get("WorkoutDate"), errors="coerce").isna().all())
    if need and df_work is not None and not df_work.empty:
        w = df_work[["WorkoutID", "WorkoutDate", "WorkoutType"]].copy()
        L = L.drop(columns=[c for c in ("WorkoutDate", "WorkoutType") if c in L.columns],
                   errors="ignore")
        L = L.merge(w, on="WorkoutID", how="left")
    L["WorkoutDate"] = pd.to_datetime(L.get("WorkoutDate"), errors="coerce")
    for c in ("DistanceKm", "DurationMinutes", "AvgHeartRate", "PaceSec"):
        L[c] = pd.to_numeric(L.get(c), errors="coerce")
    if "WorkoutType" not in L.columns:
        L["WorkoutType"] = "Easy"
    return L.dropna(subset=["WorkoutDate"])


def zone_segments(df_work: pd.DataFrame, df_laps: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """
    존 계산에 쓸 '구간' 목록을 만든다.
      · 랩이 있는 훈련 → 랩 하나하나를 구간으로
      · 랩이 없는 훈련 → 훈련 전체를 하나의 구간으로
    반환: (구간 DataFrame, 통계 dict)
    """
    W = prepare_workouts(df_work)
    L = laps_with_context(df_laps, df_work)
    if W.empty:
        return W, {"lap_workouts": 0, "total_workouts": 0, "lap_segments": 0}

    lap_ids = set(L["WorkoutID"].astype(str)) if not L.empty else set()
    plain = W[~W["WorkoutID"].astype(str).isin(lap_ids)] if "WorkoutID" in W.columns else W

    parts = [plain[["WorkoutDate", "WorkoutType", "DistanceKm",
                    "DurationMinutes", "AvgHeartRate", "PaceSec"]]]
    if not L.empty:
        parts.append(L[["WorkoutDate", "WorkoutType", "DistanceKm",
                        "DurationMinutes", "AvgHeartRate", "PaceSec"]])
    seg = pd.concat(parts, ignore_index=True).sort_values("WorkoutDate")
    stats = {"lap_workouts": len(lap_ids),
             "total_workouts": int(W["WorkoutID"].nunique()) if "WorkoutID" in W.columns else len(W),
             "lap_segments": int(len(L))}
    return seg.reset_index(drop=True), stats


def decoupling(lap_rows: pd.DataFrame) -> float:
    """
    심박 디커플링 (Pa:HR) — 전반/후반의 '속도÷심박' 비교.
    양수가 클수록 후반에 같은 페이스를 더 높은 심박으로 버틴 것 = 지구력 부족.
    일반적으로 5% 미만이면 양호.
    """
    if lap_rows is None or lap_rows.empty or len(lap_rows) < 4:
        return np.nan
    d = lap_rows.copy()
    for c in ("DistanceKm", "DurationMinutes", "AvgHeartRate"):
        d[c] = pd.to_numeric(d.get(c), errors="coerce")
    d = d[(d["DistanceKm"] > 0) & (d["DurationMinutes"] > 0) & (d["AvgHeartRate"] > 0)]
    if len(d) < 4:
        return np.nan
    d = d.sort_values("LapNo") if "LapNo" in d.columns else d
    half = len(d) // 2
    def ef(part):
        spd = part["DistanceKm"].sum() * 1000.0 / part["DurationMinutes"].sum()
        hr = (part["AvgHeartRate"] * part["DurationMinutes"]).sum() / part["DurationMinutes"].sum()
        return spd / hr if hr > 0 else np.nan
    e1, e2 = ef(d.iloc[:half]), ef(d.iloc[half:])
    if not (np.isfinite(e1) and np.isfinite(e2)) or e1 <= 0:
        return np.nan
    return float((e1 - e2) / e1 * 100.0)


def decoupling_verdict(pct: float) -> tuple[str, str]:
    if not np.isfinite(pct):
        return "info", "랩이 4개 이상이어야 계산됩니다"
    if pct < 0:
        return "ok", "후반에 오히려 효율이 좋아짐 (네거티브 스플릿)"
    if pct < 5:
        return "ok", "양호 — 지구력이 페이스를 버팀"
    if pct < 10:
        return "warn", "보통 — 후반에 심박이 올라감"
    return "bad", "큼 — 지구력 부족 또는 과한 초반 페이스"


# ---------------------------------------------------------------------------
# 10. 랩 역할 분류 — 워밍업 / 반복(본 구간) / 회복 / 쿨다운
#     인터벌·템포런은 세션 평균이 무의미합니다. 본 구간만 따로 봐야 합니다.
# ---------------------------------------------------------------------------

LAP_ROLES = ["워밍업", "반복", "회복", "쿨다운", "지속주", "자투리"]

# 가민 CSV의 '단계 유형' → 이 앱의 랩 역할
_STAGE_ROLE = {
    "워밍업": "워밍업", "웜업": "워밍업", "warmup": "워밍업", "warm up": "워밍업",
    "러닝": "반복", "run": "반복", "인터벌": "반복", "interval": "반복",
    "활성": "반복", "active": "반복", "반복": "반복",
    "회복": "회복", "리커버리": "회복", "recovery": "회복",
    "휴식": "회복", "rest": "회복", "recover": "회복",
    "쿨다운": "쿨다운", "쿨 다운": "쿨다운", "cooldown": "쿨다운", "cool down": "쿨다운",
}


def stage_to_role(stage) -> str:
    """가민 '단계 유형' 문자열을 랩 역할로. 모르는 값이면 빈 문자열."""
    t = str(stage or "").strip().lower()
    return _STAGE_ROLE.get(t, "")


def classify_laps(lap_rows: pd.DataFrame, fast_ratio: float = 1.06) -> pd.DataFrame:
    """
    랩을 역할별로 나눕니다.
      · 세션 중간값보다 fast_ratio 이상 빠르고 충분히 긴 랩 → 반복(본 구간)
      · 앞쪽의 느린 연속 구간 → 워밍업 / 뒤쪽 → 쿨다운 / 반복 사이 → 회복
      · 속도 편차가 작거나 빠른 랩이 없으면 → 전부 지속주
      · 아주 짧은 자투리 랩(오토랩 찌꺼기)은 '자투리'로 빼고 판단에서 제외
    반환: 입력 + '역할' 컬럼
    """
    if lap_rows is None or lap_rows.empty:
        return pd.DataFrame()
    d = lap_rows.copy()
    for c in ("DistanceKm", "DurationMinutes", "AvgHeartRate", "LapNo"):
        d[c] = pd.to_numeric(d.get(c), errors="coerce")
    d = d[(d["DistanceKm"] > 0) & (d["DurationMinutes"] > 0)]
    if d.empty:
        return d.assign(역할=pd.Series(dtype=str))
    d = (d.sort_values("LapNo") if d["LapNo"].notna().any() else d).reset_index(drop=True)

    # 자투리 랩 제외 (거리 50m 미만 또는 30초 미만)
    trivial = (d["DistanceKm"] < 0.05) | (d["DurationMinutes"] < 0.5)
    core = d[~trivial]
    d["역할"] = ""
    d.loc[trivial, "역할"] = "자투리"

    # 가민이 알려준 단계 유형(LapRole)이 저장돼 있으면 추측하지 않고 그대로 씁니다
    if "LapRole" in d.columns:
        saved = d["LapRole"].map(lambda v: _STAGE_ROLE.get(str(v).strip().lower(),
                                                           str(v).strip()
                                                           if str(v).strip() in LAP_ROLES
                                                           else ""))
        if saved.replace("", pd.NA).notna().sum() >= max(2, int(len(d) * 0.5)):
            d.loc[(d["역할"] == "") & saved.ne(""), "역할"] = saved
            d.loc[d["역할"] == "", "역할"] = "지속주"
            return d
    if core.empty:
        d.loc[d["역할"] == "", "역할"] = "지속주"
        return d

    spd = core["DistanceKm"] * 1000.0 / core["DurationMinutes"]      # m/min
    med = float(spd.median())
    cv = float(spd.std() / spd.mean()) if len(spd) > 1 and spd.mean() > 0 else 0.0

    fast_mask = (spd >= med * fast_ratio) & (core["DurationMinutes"] >= 0.75)
    fast_min = float(core.loc[fast_mask, "DurationMinutes"].sum())
    total_min = float(core["DurationMinutes"].sum())

    # 균일한 러닝(속도 편차 4% 미만) 이거나, 빠른 구간이 전체의 5% 미만이면 지속주
    if cv < 0.04 or fast_mask.sum() == 0 or (total_min > 0 and fast_min / total_min < 0.05):
        d.loc[d["역할"] == "", "역할"] = "지속주"
        return d

    idx = list(core.index)
    flags = fast_mask.tolist()
    roles = {i: "회복" for i in idx}
    for i, f in zip(idx, flags):
        if f:
            roles[i] = "반복"
    first_fast = flags.index(True)
    last_fast = len(flags) - 1 - flags[::-1].index(True)
    for i in idx[:first_fast]:
        roles[i] = "워밍업"
    for i in idx[last_fast + 1:]:
        roles[i] = "쿨다운"
    for i, r in roles.items():
        d.loc[i, "역할"] = r
    return d


# 랩 요약표에 함께 보여줄 평균 지표 — (컬럼, 표시이름, 소수 자릿수)
# 있는 항목만 열이 생깁니다. 값이 하나도 없으면 열 자체를 만들지 않습니다.
_LAP_AVG_COLS = [
    ("AvgHeartRate",   "평균 심박",     0),
    ("MaxHeartRate",   "최대 심박",     0),
    ("AvgCadence",     "케이던스",      0),
    ("AvgStrideM",     "보폭(m)",       2),
    ("AvgGCTms",       "접지(ms)",      0),
    ("AvgVertOscCm",   "수직진동(cm)",  1),
    ("AvgVertRatioPct", "수직비율(%)",  1),
    ("AvgPower",       "파워(W)",       0),
]


def _wmean(sub: pd.DataFrame, col: str, wcol: str = "DurationMinutes") -> float:
    """시간으로 가중한 평균. 랩 길이가 제각각이라 단순 평균은 짧은 랩을
    과대평가합니다. 0 이나 빈 값은 '측정 안 됨'으로 보고 빼고 셉니다."""
    if col not in sub.columns:
        return np.nan
    v = pd.to_numeric(sub[col], errors="coerce")
    w = pd.to_numeric(sub.get(wcol), errors="coerce")
    m = v.notna() & (v > 0) & w.notna() & (w > 0)
    if not m.any():
        return np.nan
    return float((v[m] * w[m]).sum() / w[m].sum())


lap_wmean = _wmean          # 화면 쪽에서도 같은 평균을 쓰도록 공개 이름 하나

# 요약표 숫자 형식 — st.dataframe 은 1.0 을 '1' 로 줄여 버려서 자릿수를 지정합니다
LAP_SUMMARY_FMT = {"거리(km)": "%.2f",
                   **{lab: (f"%.{nd}f" if nd else "%d")
                      for _c, lab, nd in _LAP_AVG_COLS}}


def _role_row(label: str, sub: pd.DataFrame, cols) -> dict:
    dist = float(pd.to_numeric(sub["DistanceKm"], errors="coerce").sum())
    mins = float(pd.to_numeric(sub["DurationMinutes"], errors="coerce").sum())
    row = {
        "역할": label, "랩": int(len(sub)),
        "거리(km)": round(dist, 2),
        "시간": time_str(mins * 60),
        "평균 페이스": pace_str(mins * 60 / dist) if dist > 0 else "—",
    }
    for col, label_, nd in cols:
        v = _wmean(sub, col)
        row[label_] = (round(v, nd) if nd else int(round(v))) if np.isfinite(v) else None
    return row


def lap_role_summary(classified: pd.DataFrame) -> pd.DataFrame:
    """역할별 평균 — 본 구간만의 페이스·심박이 실제로 의미 있는 수치입니다.
    맨 아래 '전체' 줄은 이 훈련 전체의 평균입니다(역할이 둘 이상일 때만)."""
    if classified is None or classified.empty or "역할" not in classified.columns:
        return pd.DataFrame()
    cols = [(c, lab, nd) for c, lab, nd in _LAP_AVG_COLS
            if c in classified.columns
            and pd.to_numeric(classified[c], errors="coerce").fillna(0).abs().sum() > 0]
    present = [r for r in LAP_ROLES if (classified["역할"] == r).any()]
    rows = [_role_row(r, classified[classified["역할"] == r], cols) for r in present]
    if len(rows) > 1:
        rows.append(_role_row("전체", classified, cols))
    out = pd.DataFrame(rows)
    # 전부 빈 열은 표에서 빼 줍니다 (예: 파워 미측정)
    return out.dropna(axis=1, how="all")


def interval_shape(classified: pd.DataFrame) -> str:
    """'5 × 1.00km @ 4:12/km (회복 4랩)' 형태의 한 줄 요약."""
    if classified is None or classified.empty or "역할" not in classified.columns:
        return ""
    rep = classified[classified["역할"] == "반복"]
    if rep.empty:
        tot_d = float(classified["DistanceKm"].sum())
        tot_m = float(classified["DurationMinutes"].sum())
        return (f"지속주 {tot_d:.2f}km @ {pace_str(tot_m * 60 / tot_d)}"
                if tot_d > 0 else "")
    d_mean = float(rep["DistanceKm"].mean())
    mins = float(rep["DurationMinutes"].sum())
    dist = float(rep["DistanceKm"].sum())
    rec = int((classified["역할"] == "회복").sum())
    unit = f"{d_mean:.2f}km" if d_mean >= 0.2 else f"{d_mean*1000:.0f}m"
    tail = f" · 회복 {rec}랩" if rec else ""
    return f"{len(rep)} × {unit} @ {pace_str(mins * 60 / dist)}{tail}"


# ═══════════════════════════════════════════════════════════════════════════
# 가민 .fit 활동 파일 읽기
# ═══════════════════════════════════════════════════════════════════════════
# 시계가 직접 쓴 원본 파일입니다. Connect 화면에서 눈으로 옮겨 적던 값이
# 거의 전부 들어 있고, 1초 단위 기록까지 있어 디커플링처럼 '중간이 있어야
# 계산되는 값'을 제대로 낼 수 있습니다.
#   받는 곳: Garmin Connect 웹 → 활동 → 우상단 ⚙ → 원본 파일 내보내기
#
# 주의 — 트레드밀: Connect에서 거리를 보정해도 그 보정은 **원본 파일에 반영되지
# 않습니다**. 파일에는 시계가 잰 거리가 그대로 들어 있습니다. 그래서 가져올 때
# 총 거리를 고쳐 넣을 수 있게 하고, 고치면 랩·페이스도 같은 비율로 맞춥니다.

# 가민이 활동에 매기는 '주요 효과' — 공개 규격에 이름이 없는 번호 필드라
# 실제 파일 4개(베이스 2건 / VO2max / 회복)로 대조해 확인한 순서입니다.
FIT_BENEFIT_FIELD = 188
FIT_BENEFIT = {0: "", 1: "Recovery", 2: "Base", 3: "Tempo", 4: "Threshold",
               5: "VO2max", 6: "Anaerobic", 7: "Sprint"}

# 랩 강도 — 구조화 훈련에서는 시계가 직접 붙여 줍니다(추정할 필요가 없습니다)
FIT_LAP_ROLE = {"warmup": "워밍업", "interval": "반복", "active": "반복",
                "recovery": "회복", "rest": "회복", "cooldown": "쿨다운",
                "warm_up": "워밍업", "cool_down": "쿨다운"}

# 주요 효과 → 훈련 유형 추천 (확정이 아니라 첫 값입니다)
FIT_TYPE_HINT = {"Recovery": "Recovery", "Base": "Easy", "Tempo": "Tempo",
                 "Threshold": "Threshold", "VO2max": "Interval",
                 "Anaerobic": "Interval", "Sprint": "Sprint"}


def _fit_num(v, default=np.nan):
    try:
        f = float(v)
        return f if np.isfinite(f) else default
    except (TypeError, ValueError):
        return default


def _fit_spm(cad, frac):
    """FIT의 케이던스는 '한쪽 발 기준'입니다 — 두 배 해야 spm 이 됩니다."""
    c = _fit_num(cad)
    if not np.isfinite(c):
        return np.nan
    return round((c + _fit_num(frac, 0.0)) * 2)


def _fit_local_offset(msgs) -> pd.Timedelta:
    """파일의 시각은 UTC 입니다. activity 메시지의 local_timestamp 로 시차를 구합니다."""
    try:
        a = msgs["activity_mesgs"][0]
        loc = a.get("local_timestamp")
        utc = a.get("timestamp")
        if loc is None or utc is None:
            return pd.Timedelta(0)
        # local_timestamp 는 FIT 기준시(1989-12-31)부터의 초
        base = pd.Timestamp("1989-12-31", tz="UTC")
        loc_ts = base + pd.Timedelta(seconds=float(loc))
        off = loc_ts - pd.Timestamp(utc)
        # 15분 단위로 반올림 — 시차는 그 배수입니다
        return pd.Timedelta(minutes=round(off.total_seconds() / 900) * 15)
    except Exception:
        return pd.Timedelta(0)


def fit_decode(data):
    """.fit 바이트 또는 경로 → 메시지 묶음. 라이브러리가 없으면 안내를 냅니다."""
    try:
        from garmin_fit_sdk import Decoder, Stream
    except ImportError as e:                                # pragma: no cover
        raise RuntimeError(
            "가민 .fit 파일을 읽으려면 garmin-fit-sdk 가 필요합니다. "
            "requirements.txt 에 `garmin-fit-sdk` 를 넣고 다시 배포하세요.") from e
    if isinstance(data, (bytes, bytearray)):
        stream = Stream.from_byte_array(bytearray(data))
    else:
        stream = Stream.from_file(str(data))
    msgs, errors = Decoder(stream).read()
    return msgs, errors


def fit_series(msgs) -> pd.DataFrame:
    """1초 단위 기록 → 표. 없으면 빈 표."""
    rec = msgs.get("record_mesgs") or []
    if not rec:
        return pd.DataFrame()
    keep = ["timestamp", "distance", "enhanced_speed", "speed", "heart_rate",
            "cadence", "fractional_cadence", "stance_time", "vertical_oscillation",
            "vertical_ratio", "step_length", "enhanced_altitude", "altitude",
            "power", "temperature"]
    d = pd.DataFrame([{k: r.get(k) for k in keep if k in r} for r in rec])
    if d.empty or "timestamp" not in d.columns:
        return pd.DataFrame()
    d["timestamp"] = pd.to_datetime(d["timestamp"], errors="coerce", utc=True)
    d = d.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    if "enhanced_speed" in d.columns:
        d["speed"] = pd.to_numeric(d["enhanced_speed"], errors="coerce")
    elif "speed" in d.columns:
        d["speed"] = pd.to_numeric(d["speed"], errors="coerce")
    d["t"] = (d["timestamp"] - d["timestamp"].iloc[0]).dt.total_seconds()
    return d


def fit_decoupling(series: pd.DataFrame) -> float:
    """1초 기록으로 계산한 심박 디커플링(Pa:HR, %).

    전반/후반의 '속도 ÷ 심박'을 견줍니다. 양수가 크면 후반에 같은 페이스를 더
    높은 심박으로 버틴 것 — 유산소 지구력 쪽 신호입니다(보통 5% 미만이면 양호).
    랩 단위로 재던 것과 달리 멈춤·신호 대기까지 그대로 반영됩니다.
    """
    if series is None or series.empty or "speed" not in series.columns:
        return np.nan
    d = series[["t", "speed", "heart_rate"]].copy()
    d["speed"] = pd.to_numeric(d["speed"], errors="coerce")
    d["heart_rate"] = pd.to_numeric(d["heart_rate"], errors="coerce")
    # 서 있는 구간은 빼야 합니다 — 0으로 나눈 EF가 평균을 망칩니다
    d = d[(d["speed"] > 0.5) & (d["heart_rate"] > 50)].dropna()
    if len(d) < 300:                    # 5분치도 안 되면 뜻이 없습니다
        return np.nan
    half = d["t"].iloc[0] + (d["t"].iloc[-1] - d["t"].iloc[0]) / 2
    a, b = d[d.t <= half], d[d.t > half]
    if len(a) < 120 or len(b) < 120:
        return np.nan
    ef1 = a["speed"].mean() / a["heart_rate"].mean()
    ef2 = b["speed"].mean() / b["heart_rate"].mean()
    if not np.isfinite(ef1) or ef1 <= 0:
        return np.nan
    return float((ef1 - ef2) / ef1 * 100)


def fit_form_split(series: pd.DataFrame) -> dict:
    """전반/후반 폼 지표 — 후반에 무너지는지 봅니다."""
    out = {}
    if series is None or series.empty:
        return out
    d = series.copy()
    if "speed" in d.columns:
        d = d[pd.to_numeric(d["speed"], errors="coerce") > 0.5]
    if len(d) < 300:
        return out
    half = d["t"].iloc[0] + (d["t"].iloc[-1] - d["t"].iloc[0]) / 2
    a, b = d[d.t <= half], d[d.t > half]
    for col, name in (("stance_time", "접지 시간 (ms)"),
                      ("vertical_oscillation", "수직 진동 (mm)"),
                      ("vertical_ratio", "수직 비율 (%)"),
                      ("step_length", "보폭 (mm)"),
                      ("cadence", "케이던스 (한쪽)"),
                      ("heart_rate", "심박 (bpm)")):
        if col not in d.columns:
            continue
        va = pd.to_numeric(a[col], errors="coerce").mean()
        vb = pd.to_numeric(b[col], errors="coerce").mean()
        if np.isfinite(va) and np.isfinite(vb):
            out[name] = (float(va), float(vb))
    return out


def fit_laps(msgs, offset=None) -> pd.DataFrame:
    """랩 메시지 → 앱의 Laps 시트 모양. 랩 역할은 시계가 붙인 강도를 그대로 씁니다."""
    laps = msgs.get("lap_mesgs") or []
    if not laps:
        return pd.DataFrame()
    off = offset if offset is not None else pd.Timedelta(0)
    rows, cum = [], 0.0
    for i, L in enumerate(laps):
        dist_km = _fit_num(L.get("total_distance"), 0.0) / 1000.0
        mins = _fit_num(L.get("total_timer_time"), 0.0) / 60.0
        mv = _fit_num(L.get("total_timer_time"))
        el = _fit_num(L.get("total_elapsed_time"))
        rows.append({
            "LapNo": i + 1,
            "CumMinutes": round(cum, 2),
            "DistanceKm": round(dist_km, 3),
            "DurationMinutes": round(_fit_num(el, mins * 60) / 60.0, 3),
            "PaceSec": round(mins * 60 / dist_km, 1) if dist_km > 0 else "",
            "AvgHeartRate": _fit_num(L.get("avg_heart_rate"), ""),
            "MaxHeartRate": _fit_num(L.get("max_heart_rate"), ""),
            "AvgPower": _fit_num(L.get("avg_power"), ""),
            "AvgCadence": _fit_spm(L.get("avg_cadence"), L.get("avg_fractional_cadence")),
            "ElevGainM": _fit_num(L.get("total_ascent"), ""),
            "ElevLossM": _fit_num(L.get("total_descent"), ""),
            "AvgGCTms": _fit_num(L.get("avg_stance_time"), ""),
            "AvgStrideM": (round(_fit_num(L.get("avg_step_length")) / 1000.0, 3)
                           if np.isfinite(_fit_num(L.get("avg_step_length"))) else ""),
            "AvgVertOscCm": (round(_fit_num(L.get("avg_vertical_oscillation")) / 10.0, 2)
                             if np.isfinite(_fit_num(L.get("avg_vertical_oscillation")))
                             else ""),
            "AvgVertRatioPct": _fit_num(L.get("avg_vertical_ratio"), ""),
            "Calories": _fit_num(L.get("total_calories"), ""),
            "TempC": _fit_num(L.get("avg_temperature"), ""),
            "LapRole": FIT_LAP_ROLE.get(str(L.get("intensity") or "").lower(), ""),
            "NormPower": _fit_num(L.get("normalized_power"), ""),
            "MaxPower": _fit_num(L.get("max_power"), ""),
            "MaxPaceSec": (round(1000.0 / _fit_num(L.get("enhanced_max_speed")), 1)
                           if _fit_num(L.get("enhanced_max_speed"), 0) > 0 else ""),
            "MaxCadence": _fit_spm(L.get("max_cadence"), 0),
            "MovingMinutes": round(mv / 60.0, 3) if np.isfinite(mv) else "",
            "_trigger": str(L.get("lap_trigger") or ""),
        })
        cum += mins
    out = pd.DataFrame(rows)
    # 거리 오토랩만 있고 강도가 전부 같으면 '구조 없는 훈련'입니다 — 역할을 비웁니다
    roles = set(out["LapRole"]) - {""}
    if len(roles) <= 1:
        out["LapRole"] = ""
    return out


def fit_workout(msgs, offset=None) -> dict:
    """세션 메시지 → 앱의 Workouts 시트 한 줄(+ 판단에 쓰는 몇 가지)."""
    ses = (msgs.get("session_mesgs") or [{}])[0]
    off = offset if offset is not None else _fit_local_offset(msgs)
    start = pd.to_datetime(ses.get("start_time"), errors="coerce", utc=True)
    local = (start + off) if pd.notna(start) else pd.NaT

    dist_km = _fit_num(ses.get("total_distance"), 0.0) / 1000.0
    el_min = _fit_num(ses.get("total_elapsed_time"), 0.0) / 60.0
    mv_min = _fit_num(ses.get("total_timer_time"), 0.0) / 60.0
    ben = FIT_BENEFIT.get(int(_fit_num(ses.get(FIT_BENEFIT_FIELD), -1))
                          if np.isfinite(_fit_num(ses.get(FIT_BENEFIT_FIELD))) else -1, "")
    sub = str(ses.get("sub_sport") or "")
    rpe = _fit_num(ses.get("workout_rpe"))

    def g(key, scale=1.0, nd=None):
        v = _fit_num(ses.get(key))
        if not np.isfinite(v):
            return ""
        v = v * scale
        return round(v, nd) if nd is not None else v

    row = {
        "WorkoutDate": local.strftime("%Y-%m-%d") if pd.notna(local) else "",
        "DistanceKm": round(dist_km, 3),
        "DurationMinutes": round(el_min, 3),
        "PaceSec": round(mv_min * 60 / dist_km, 1) if dist_km > 0 else "",
        "AvgHeartRate": g("avg_heart_rate"),
        "MaxHeartRate": g("max_heart_rate"),
        "AvgPower": g("avg_power"),
        "AvgCadence": _fit_spm(ses.get("avg_cadence"), ses.get("avg_fractional_cadence")),
        "MaxCadence": _fit_spm(ses.get("max_cadence"), 0),
        "ElevationGainM": g("total_ascent"),
        "ElevLossM": g("total_descent"),
        "Temperature": g("avg_temperature"),
        "AerobicTE": g("total_training_effect"),
        "AnaerobicTE": g("total_anaerobic_training_effect"),
        "PrimaryBenefit": ben,
        "TrainingLoad": g("training_load_peak", nd=0),
        "Calories": g("total_calories"),
        "AvgGCTms": g("avg_stance_time", nd=1),
        "AvgStrideM": g("avg_step_length", 0.001, 3),
        "AvgVertOscCm": g("avg_vertical_oscillation", 0.1, 2),
        "AvgVertRatioPct": g("avg_vertical_ratio", nd=2),
        "NormPower": g("normalized_power"),
        "MaxPaceSec": (round(1000.0 / _fit_num(ses.get("enhanced_max_speed")), 1)
                       if _fit_num(ses.get("enhanced_max_speed"), 0) > 0 else ""),
        "MovingMinutes": round(mv_min, 3),
        "Surface": "트레드밀" if sub == "treadmill" else "로드",
        "RPE": int(min(10, max(1, round(rpe / 10)))) if np.isfinite(rpe) and rpe > 0 else "",
        "WorkoutType": FIT_TYPE_HINT.get(ben, "Easy"),
    }
    row["_start_local"] = local
    row["_sub_sport"] = sub
    row["_sport"] = str(ses.get("sport") or "")
    row["_profile"] = str(ses.get("sport_profile_name") or "")
    row["_feel"] = _fit_num(ses.get("workout_feel"))
    return row


def fit_type_hint(w: dict, laps: pd.DataFrame) -> str:
    """훈련 유형 첫 값 — 주요 효과만 보면 어긋납니다.

    시계는 15초 스프린트 8세트짜리 훈련도 '주요 효과: 베이스'로 적습니다
    (전체 시간의 대부분이 쉬운 러닝이라서). 그래서 **랩 구조를 먼저** 봅니다.
    """
    ben = str(w.get("PrimaryBenefit") or "")
    reps = pd.DataFrame()
    if laps is not None and not laps.empty and "LapRole" in laps.columns:
        reps = laps[laps["LapRole"] == "반복"]
    if len(reps) >= 2:                       # 구조화 훈련
        if ben in ("VO2max", "Anaerobic", "Sprint", "Threshold", "Tempo"):
            return FIT_TYPE_HINT.get(ben, "Interval")
        sec = pd.to_numeric(reps["DurationMinutes"], errors="coerce").median() * 60
        if np.isfinite(sec) and sec < 60:
            return "Sprint"
        if np.isfinite(sec) and sec < 360:
            return "Interval"
        return "Threshold"
    # 쭉 달린 훈련
    if ben in ("", "Base"):
        mins = _fit_num(w.get("DurationMinutes"), 0)
        km = _fit_num(w.get("DistanceKm"), 0)
        if mins >= 90 or km >= 21:
            return "LSD"
        return FIT_TYPE_HINT.get(ben, "Easy")
    return FIT_TYPE_HINT.get(ben, "Easy")


def fit_steady(laps: pd.DataFrame, series: pd.DataFrame) -> bool:
    """쭉 달린 훈련인가 — 디커플링은 이럴 때만 뜻이 있습니다.

    인터벌은 후반이 원래 더 힘들게 짜여 있어서, 디커플링을 재면 늘 큰 값이
    나옵니다(피로가 아니라 훈련 설계 때문). 그런 훈련에서는 내지 않습니다.
    """
    if laps is not None and not laps.empty and "LapRole" in laps.columns:
        if len(set(laps["LapRole"]) - {""}) > 1:
            return False
    if series is None or series.empty or "speed" not in series.columns:
        return True
    sp = pd.to_numeric(series["speed"], errors="coerce")
    sp = sp[sp > 0.5]
    if len(sp) < 300 or sp.mean() <= 0:
        return True
    return bool(sp.std() / sp.mean() < 0.18)


def fit_read(data, name: str = "") -> dict:
    """가민 .fit 활동 파일 한 개를 앱이 쓰는 모양으로 바꿉니다.

    반환: {"workout": dict, "laps": DataFrame, "series": DataFrame,
           "decoupling": float, "form": dict, "warnings": [str], "zones": dict}
    """
    msgs, errors = fit_decode(data)
    warn = [f"읽는 중 넘어간 부분이 {len(errors)}군데 있습니다."] if errors else []
    if not msgs.get("session_mesgs"):
        return {"workout": {}, "laps": pd.DataFrame(), "series": pd.DataFrame(),
                "decoupling": np.nan, "form": {}, "zones": {},
                "warnings": warn + ["활동 요약(session)이 없는 파일입니다 — "
                                    "활동 파일이 맞는지 확인해 주세요."]}
    off = _fit_local_offset(msgs)
    w = fit_workout(msgs, off)
    laps = fit_laps(msgs, off)
    ser = fit_series(msgs)

    if w.get("_sport") and w["_sport"] != "running":
        warn.append(f"달리기가 아닌 활동입니다 ({w['_profile'] or w['_sport']}) — "
                    "그대로 넣으면 통계가 섞입니다.")
    if w.get("_sub_sport") == "treadmill":
        warn.append(
            "트레드밀 활동입니다. **Connect에서 고친 거리는 이 파일에 반영되지 "
            "않습니다** — 파일에는 시계가 잰 거리가 그대로 들어 있습니다. "
            "아래에서 Connect에 뜨는 총 거리로 고쳐 넣으면 랩과 페이스도 "
            "같은 비율로 맞춰 넣습니다.")
    if w.get("ElevationGainM") == "":
        warn.append("상승고도가 없는 파일입니다 (트레드밀·실내) — 빈 칸으로 둡니다.")

    # 시계가 쓰던 심박존 — 추정 대신 그대로 쓸 수 있습니다
    zones = {}
    for z in (msgs.get("time_in_zone_mesgs") or []):
        if str(z.get("reference_mesg")) == "session":
            zones = {"bounds": list(z.get("hr_zone_high_boundary") or []),
                     "time": list(z.get("time_in_hr_zone") or []),
                     "lthr": _fit_num(z.get("threshold_heart_rate")),
                     "max": _fit_num(z.get("max_heart_rate")),
                     "rest": _fit_num(z.get("resting_heart_rate")),
                     "calc": str(z.get("hr_calc_type") or "")}
            break

    w["WorkoutType"] = fit_type_hint(w, laps)
    steady = fit_steady(laps, ser)
    # ── 1초 기록에서 뽑아 '저장할' 값 ──────────────────────────────────────
    # 원본 1초 기록은 남기지 않습니다(1년이면 시트 한 문서 한도를 넘습니다).
    # 대신 여러 훈련을 가로질러 비교되는 값만 훈련 줄에 같이 넣습니다.
    _form = fit_form_split(ser)
    _gct = _form.get("접지 시간 (ms)")
    w["GctDriftPct"] = (round((_gct[1] - _gct[0]) / _gct[0] * 100, 2)
                        if _gct and _gct[0] > 0 else "")
    if zones.get("time"):
        _t = [int(round(_fit_num(x, 0))) for x in zones["time"]]
        w["WatchZoneSec"] = "|".join(str(x) for x in _t)
        w["WatchZoneBounds"] = "|".join(
            str(int(round(_fit_num(b, 0)))) for b in (zones.get("bounds") or []))
    else:
        w["WatchZoneSec"] = ""
        w["WatchZoneBounds"] = ""
    dec = fit_decoupling(ser) if steady else np.nan
    if not steady:
        warn.append("구간이 나뉜 훈련이라 **심박 디커플링은 내지 않습니다** — "
                    "후반이 원래 더 힘들게 짜여 있어서, 재면 피로가 아니라 "
                    "훈련 설계가 찍힙니다.")
    w["DecouplingPct"] = round(float(dec), 2) if np.isfinite(dec) else ""
    return {"workout": w, "laps": laps, "series": ser,
            "decoupling": dec, "steady": steady, "form": _form,
            "zones": zones, "warnings": warn, "name": name}


def fit_rescale(res: dict, new_km: float) -> dict:
    """총 거리를 고쳐 넣으면 랩·페이스를 같은 비율로 맞춥니다 (트레드밀 보정)."""
    old = _fit_num(res.get("workout", {}).get("DistanceKm"), 0.0)
    new = _fit_num(new_km, 0.0)
    if old <= 0 or new <= 0 or abs(new - old) < 1e-6:
        return res
    k = new / old
    w = dict(res["workout"])
    w["DistanceKm"] = round(new, 3)
    mv = _fit_num(w.get("MovingMinutes"), 0.0)
    w["PaceSec"] = round(mv * 60 / new, 1) if new > 0 else ""
    for key in ("MaxPaceSec",):
        v = _fit_num(w.get(key))
        if np.isfinite(v) and v > 0:
            w[key] = round(v / k, 1)
    st = _fit_num(w.get("AvgStrideM"))
    if np.isfinite(st):
        w["AvgStrideM"] = round(st * k, 3)
    laps = res.get("laps")
    if laps is not None and not laps.empty:
        laps = laps.copy()
        d = pd.to_numeric(laps["DistanceKm"], errors="coerce") * k
        laps["DistanceKm"] = d.round(3)
        mvl = pd.to_numeric(laps["MovingMinutes"], errors="coerce")
        laps["PaceSec"] = (mvl * 60 / d).round(1).where(d > 0, "")
    out = dict(res)
    out["workout"] = w
    out["laps"] = laps if laps is not None else res.get("laps")
    out["rescaled"] = round(k, 4)
    return out


def parse_zone_sec(txt) -> list[float]:
    """'28|35|3478|778|0|0|0' → [28, 35, 3478, 778, 0, 0, 0]"""
    if txt is None or (isinstance(txt, float) and not np.isfinite(txt)):
        return []
    t = str(txt).strip()
    if not t or t.lower() in ("nan", "none", "<na>"):
        return []
    out = []
    for p in t.split("|"):
        try:
            v = float(p)
        except ValueError:
            v = 0.0
        out.append(v if np.isfinite(v) else 0.0)
    return out


def watch_intensity(df_work: pd.DataFrame, days: int = 90) -> dict:
    """시계가 **직접 잰** 존 체류 시간으로 낸 강도 분포.

    지금까지의 강도 분포는 훈련의 *평균* 심박으로 존을 하나 고르는 추정이라,
    강약이 섞인 인터벌이 통째로 중간 존에 들어가 버렸습니다. .fit 파일에는
    시계가 초보다 촘촘하게 재서 존별로 더해 둔 실제 시간이 들어 있습니다.

    FIT 규격상 time_in_hr_zone 은 0번이 'Z1 아래', 1~5번이 Z1~Z5 입니다.
    존 경계는 시기에 따라 달라질 수 있지만(프로필을 바꾸면), 존 번호의 뜻은
    그대로라 그대로 더해도 됩니다 — Connect 화면과 같은 방식입니다.

    반환: {"low","mid","high","minutes","n","n_total"} · 실측이 없으면 {}
    """
    if df_work is None or df_work.empty or "WatchZoneSec" not in df_work.columns:
        return {}
    d = df_work
    if days and "WorkoutDate" in d.columns:
        # 날짜가 문자로 들어올 수도 있어 여기서 직접 맞춥니다
        _dt = pd.to_datetime(d["WorkoutDate"], errors="coerce")
        _cut = _dt.max() - pd.Timedelta(days=int(days))
        d = d[_dt >= _cut]
    if d.empty:
        return {}
    tot = np.zeros(7)
    n = 0
    for v in d["WatchZoneSec"]:
        z = parse_zone_sec(v)
        if not z or sum(z) <= 0:
            continue
        z = (z + [0.0] * 7)[:7]
        tot += np.array(z, dtype=float)
        n += 1
    if n == 0 or tot.sum() <= 0:
        return {}
    low = tot[0] + tot[1] + tot[2]        # Z1 아래 + Z1 + Z2
    mid = tot[3] + tot[4]                 # Z3 + Z4
    high = tot[5] + tot[6]                # Z5 이상
    s = low + mid + high
    return {"low": round(float(low) / float(s) * 100, 1),
            "mid": round(float(mid) / float(s) * 100, 1),
            "high": round(float(high) / float(s) * 100, 1),
            "minutes": {f"Z{i}": round(float(tot[i]) / 60, 1) for i in range(1, 6)},
            "below": round(float(tot[0]) / 60, 1),
            "n": n, "n_total": int(len(d))}


# ── 이미 있는 훈련과 .fit 파일 맞추기 ─────────────────────────────────────
# 예전에 손으로 넣은 기록은 8.00km / 50분처럼 어림수인 경우가 많습니다.
# 날짜·거리·시간이 **정확히** 같아야만 같은 훈련으로 보면, 같은 러닝이
# 두 줄로 들어가 버립니다. 그래서 여기서는 느슨하게 맞추되, 애매하면
# 자동으로 처리하지 않고 사람에게 넘깁니다.
FIT_MATCH_DIST = 0.08      # 거리 8% 또는
FIT_MATCH_DIST_ABS = 0.5   # 0.5km 안쪽
FIT_MATCH_DUR = 0.08       # 시간 8% 또는
FIT_MATCH_DUR_ABS = 4.0    # 4분 안쪽

# 시계가 더 정확한 값 — '교체'에서 덮어씁니다
FIT_HARD_FIELDS = [
    "DistanceKm", "DurationMinutes", "MovingMinutes", "PaceSec", "MaxPaceSec",
    "AvgHeartRate", "MaxHeartRate", "AvgPower", "NormPower",
    "AvgCadence", "MaxCadence", "ElevationGainM", "ElevLossM", "Temperature",
    "AerobicTE", "AnaerobicTE", "PrimaryBenefit", "TrainingLoad", "Calories",
    "AvgGCTms", "AvgStrideM", "AvgVertOscCm", "AvgVertRatioPct",
    "DecouplingPct", "GctDriftPct", "WatchZoneSec", "WatchZoneBounds",
    "Surface", "RPE",
]
# 사람이 적은 것 — 어떤 모드에서도 건드리지 않습니다
FIT_KEEP_FIELDS = ["WorkoutID", "ProjectID", "ShoeID", "Notes",
                   "LegFatigue", "CardioFatigue", "SourceKey"]


def _fit_blank(v) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and not np.isfinite(v):
        return True
    return str(v).strip() in ("", "nan", "None", "<NA>", "0", "0.0", "-", "—")


def fit_match(w: dict, df_work: pd.DataFrame) -> dict:
    """이 .fit 이 기존 훈련 중 어느 것인지 찾습니다.

    반환: {"status": "new"|"one"|"many", "row": Series|None, "why": str,
           "n": 후보 수}
      · new  — 같은 날 비슷한 훈련이 없음 → 새로 추가
      · one  — 하나만 걸림 → 채우기/교체 가능
      · many — 여러 개가 걸림 → **자동 처리하지 않습니다** (사람이 고르도록)
    """
    if df_work is None or df_work.empty or not w.get("WorkoutDate"):
        return {"status": "new", "row": None, "why": "", "n": 0}
    d = df_work.copy()
    day = pd.to_datetime(d.get("WorkoutDate"), errors="coerce").dt.strftime("%Y-%m-%d")
    same = d[day == str(w["WorkoutDate"])[:10]]
    if same.empty:
        return {"status": "new", "row": None, "why": "같은 날 기록 없음", "n": 0}
    km = _num(w.get("DistanceKm"), np.nan)
    mn = _num(w.get("DurationMinutes"), np.nan)
    cand = []
    for _, r in same.iterrows():
        rk = _num(r.get("DistanceKm"), np.nan)
        rm = _num(r.get("DurationMinutes"), np.nan)
        if not np.isfinite(rk) or not np.isfinite(rm) or rk <= 0 or rm <= 0:
            continue
        dk, dm = abs(rk - km), abs(rm - mn)
        ok_k = dk <= FIT_MATCH_DIST_ABS or (km > 0 and dk / km <= FIT_MATCH_DIST)
        ok_m = dm <= FIT_MATCH_DUR_ABS or (mn > 0 and dm / mn <= FIT_MATCH_DUR)
        if ok_k and ok_m:
            cand.append(((dk / max(km, 0.1)) + (dm / max(mn, 0.1)), r, dk, dm))
    if not cand:
        return {"status": "new", "row": None,
                "why": f"같은 날 기록 {len(same)}건이 있지만 거리·시간이 많이 다름",
                "n": 0}
    cand.sort(key=lambda x: x[0])
    _, row, dk, dm = cand[0]
    why = (f"{str(row.get('WorkoutDate'))[:10]} 기록과 맞음 "
           f"(거리 {_num(row.get('DistanceKm'), 0):.2f}→{km:.2f}km, "
           f"시간 {_num(row.get('DurationMinutes'), 0):.1f}→{mn:.1f}분)")
    if len(cand) > 1:
        return {"status": "many", "row": row, "n": len(cand),
                "why": f"같은 날 비슷한 기록이 {len(cand)}건 — 직접 확인하세요"}
    return {"status": "one", "row": row, "why": why, "n": 1}


def _fit_same(a, b) -> bool:
    """같은 값인가 — 150 과 150.0 은 같습니다."""
    if str(a).strip() == str(b).strip():
        return True
    fa, fb = _num(a, np.nan), _num(b, np.nan)
    if np.isfinite(fa) and np.isfinite(fb):
        return abs(fa - fb) < 0.005
    return False


def fit_plan(w: dict, old: pd.Series, mode: str, wtype: str = "") -> dict:
    """무엇을 어떻게 바꿀지 미리 정리합니다 — 저장 전에 그대로 보여 줍니다.

    mode: "fill"(빈 칸만) | "replace"(시계 값으로 교체)
    반환: {"changes": DataFrame[항목, 지금, 파일, 결과], "values": dict}
    """
    rows, vals = [], {}
    fields = [c for c in w if not c.startswith("_") and c not in FIT_KEEP_FIELDS]
    for c in fields:
        new = w.get(c)
        if _fit_blank(new) and c not in ("DecouplingPct", "GctDriftPct"):
            continue
        cur = old.get(c, "") if old is not None else ""
        if c == "WorkoutType":
            new = wtype or new
        blank = _fit_blank(cur)
        if mode == "fill":
            if not blank:
                continue
            act = "채움"
        else:
            if c not in FIT_HARD_FIELDS and c != "WorkoutType":
                if not blank:
                    continue
                act = "채움"
            elif _fit_same(cur, new):
                continue
            else:
                act = "채움" if blank else "바꿈"
        vals[c] = new
        rows.append({"항목": c, "지금": ("(빈칸)" if blank else str(cur)[:24]),
                     "파일": str(new)[:24], "결과": act})
    return {"changes": pd.DataFrame(rows), "values": vals}
