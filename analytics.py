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
    return rows.reset_index(drop=True)


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
        })
    if not d.empty:
        lr = d.loc[d["DistanceKm"].idxmax()]
        rows.append({"Category": "Longest Run", "TimeOrDist": f"{lr['DistanceKm']:.2f} km",
                     "AchievedDate": lr["WorkoutDate"].strftime("%Y-%m-%d"),
                     "PaceStr": pace_str(_num(lr["PaceSec"], np.nan)),
                     "Source": "훈련 전체", "Workout": _wlabel(row=lr), "Note": ""})
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
    MeasuredAt('2026-09-20 07:51 (기상 직후)')이 있으면 그 시각을, 없으면 그 날 00:00을
    씁니다. 같은 날 아침/훈련 후 두 줄이 있을 때 어느 쪽이 더 나중인지 가리는 데 씁니다."""
    base = pd.to_datetime(df[date_col], errors="coerce")
    if "MeasuredAt" not in df.columns:
        return base
    txt = df["MeasuredAt"].astype(str).str.extract(
        r"(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2})", expand=False)
    exact = pd.to_datetime(txt, errors="coerce")
    return exact.fillna(base)


def _latest(df: pd.DataFrame, date_col: str, field: str):
    """해당 컬럼에서 값이 있는 가장 최근 행의 (값, 날짜)."""
    if df is None or df.empty or field not in df.columns:
        return None, None, None
    d = df.copy()
    d["_ts"] = _measured_ts(d, date_col)
    d[date_col] = pd.to_datetime(d[date_col], errors="coerce")
    d = d.dropna(subset=[date_col]).sort_values(["_ts", date_col], kind="stable")
    vals = d[field]
    mask = vals.notna() & (vals.astype(str).str.strip() != "")
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
    if not t or t == "—":
        return "—"
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


def lap_role_summary(classified: pd.DataFrame) -> pd.DataFrame:
    """역할별 합계 — 본 구간만의 페이스·심박이 실제로 의미 있는 수치입니다."""
    if classified is None or classified.empty or "역할" not in classified.columns:
        return pd.DataFrame()
    rows = []
    for role in LAP_ROLES:
        sub = classified[classified["역할"] == role]
        if sub.empty:
            continue
        dist = float(sub["DistanceKm"].sum())
        mins = float(sub["DurationMinutes"].sum())
        hr = sub[sub["AvgHeartRate"] > 0]
        hr_w = (float((hr["AvgHeartRate"] * hr["DurationMinutes"]).sum()
                      / hr["DurationMinutes"].sum()) if not hr.empty else np.nan)
        rows.append({
            "역할": role, "랩": int(len(sub)),
            "거리(km)": round(dist, 2),
            "시간": time_str(mins * 60),
            "평균 페이스": pace_str(mins * 60 / dist) if dist > 0 else "-",
            "평균 심박": int(round(hr_w)) if np.isfinite(hr_w) else "-",
        })
    return pd.DataFrame(rows)


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
