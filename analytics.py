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
from datetime import datetime, timedelta

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
                      sex: str = "M", end_date: datetime | None = None) -> pd.DataFrame:
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
    if model == "%LTHR":
        base = resolve_lthr(lthr, hr_max)
        return [(n, base * lo, base * hi) for n, lo, hi in spec] if base > 0 else []
    if model == "%HRmax":
        return [(n, hr_max * lo, hr_max * hi) for n, lo, hi in spec] if hr_max > 0 else []
    if hr_max <= 0 or hr_max <= hr_rest:
        return []
    rng = hr_max - hr_rest
    return [(n, hr_rest + rng * lo, hr_rest + rng * hi) for n, lo, hi in spec]


def lthr_history(df_metrics: pd.DataFrame, current_lthr=None,
                 hr_max=None) -> pd.DataFrame:
    """
    LTHR 변경 이력 → [Date, LTHR]. Metrics 시트에 기록된 값만 사용하고,
    하나도 없으면 프로필의 현재 LTHR(또는 최대심박의 90%)을 단일 값으로 씁니다.
    """
    rows = pd.DataFrame(columns=["Date", "LTHR"])
    if df_metrics is not None and not df_metrics.empty and "LTHR" in df_metrics.columns:
        m = df_metrics[["MetricDate", "LTHR"]].copy()
        m["Date"] = pd.to_datetime(m["MetricDate"], errors="coerce")
        m["LTHR"] = pd.to_numeric(m["LTHR"], errors="coerce")
        m = m.dropna(subset=["Date", "LTHR"])
        m = m[m["LTHR"] > 0].sort_values("Date")
        if not m.empty:
            # 같은 값이 반복되면 변경 시점만 남긴다
            m = m.loc[m["LTHR"].ne(m["LTHR"].shift())]
            rows = m[["Date", "LTHR"]].reset_index(drop=True)
    if rows.empty:
        base = resolve_lthr(current_lthr, hr_max)
        if base <= 0:
            return rows
        rows = pd.DataFrame([{"Date": pd.Timestamp("2000-01-01"), "LTHR": base}])
    return rows.sort_values("Date").reset_index(drop=True)


def assign_zones(df_work: pd.DataFrame, model: str = DEFAULT_ZONE_MODEL,
                 lthr_hist: pd.DataFrame | None = None,
                 hr_rest=None, hr_max=None) -> pd.DataFrame:
    """
    각 훈련에 '그 시점 기준'의 존을 붙입니다.
    반환 컬럼 추가: LTHRUsed(적용된 LTHR), 존
    %HRmax·%HRR은 프로필의 최대/안정 심박(고정값)을 사용합니다.
    """
    d = prepare_workouts(df_work)
    if d.empty:
        return d.assign(LTHRUsed=np.nan, 존=pd.Series(dtype=str))
    d = d.sort_values("WorkoutDate").copy()

    if model == "%LTHR":
        hist = lthr_hist if lthr_hist is not None else pd.DataFrame()
        if hist.empty:
            d["LTHRUsed"] = np.nan
        else:
            d = pd.merge_asof(d, hist.rename(columns={"Date": "_d"}).sort_values("_d"),
                              left_on="WorkoutDate", right_on="_d", direction="backward")
            d = d.rename(columns={"LTHR": "LTHRUsed"}).drop(columns=["_d"], errors="ignore")
            # 첫 기록 이전의 훈련은 가장 이른 LTHR로 보정
            d["LTHRUsed"] = d["LTHRUsed"].fillna(float(hist["LTHR"].iloc[0]))
        spec = ZONE_MODELS["%LTHR"]

        def _z(hr, base):
            if not (base and base > 0) or not np.isfinite(_num(hr, np.nan)) or hr <= 0:
                return BELOW_Z1
            p = hr / base
            for n, lo, hi in spec:
                if lo <= p < hi:
                    return n
            return spec[-1][0] if p >= spec[-1][2] else BELOW_Z1

        d["존"] = [_z(hr, b) for hr, b in zip(d["AvgHeartRate"], d["LTHRUsed"])]
    else:
        bounds = zone_bounds(model, None, hr_rest, hr_max)
        d["LTHRUsed"] = np.nan
        d["존"] = [zone_of(hr, bounds) for hr in d["AvgHeartRate"]]
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

    if tot == 0:
        verdict = "데이터 부족"
    elif pol["low"] >= 78 and pol["mid"] <= 12:
        verdict = "✅ 폴라라이즈드 (80/20 준수)"
    elif pol["low"] >= 78:
        verdict = "피라미드형 — 중강도 비중 다소 높음"
    elif pol["low"] >= 65:
        verdict = "⚠️ 임계형(Threshold) — 회색지대(Gray Zone) 과다"
    else:
        verdict = "🚨 고강도 편중 — 이지런 비중을 늘릴 것"

    return {
        "model": model,
        "zone_minutes": {k: round(v, 1) for k, v in dist.items()},
        "zone_pct": {k: (round(v / total * 100, 1) if total else 0.0)
                     for k, v in dist.items()},
        "polarized_pct": pol, "verdict": verdict,
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


def detect_prs(df_work: pd.DataFrame, tol: float = 0.03) -> pd.DataFrame:
    """훈련 이력에서 거리별 최고 기록 자동 추출 (거리 ±3% 허용)."""
    d = prepare_workouts(df_work)
    rows = []
    for name, dist in PR_CATEGORIES:
        if d.empty:
            rows.append({"Category": name, "TimeOrDist": "-", "AchievedDate": "-", "PaceStr": "-"})
            continue
        c = d[(d["DistanceKm"] >= dist * (1 - tol)) & (d["DistanceKm"] <= dist * (1 + tol))]
        if c.empty:
            rows.append({"Category": name, "TimeOrDist": "-", "AchievedDate": "-", "PaceStr": "-"})
            continue
        # 거리 정규화 후 최속
        c = c.assign(NormSec=c["DurationMinutes"] * 60.0 * (dist / c["DistanceKm"]))
        best = c.loc[c["NormSec"].idxmin()]
        rows.append({
            "Category": name,
            "TimeOrDist": time_str(best["NormSec"]),
            "AchievedDate": best["WorkoutDate"].strftime("%Y-%m-%d"),
            "PaceStr": pace_str(best["NormSec"] / dist),
        })
    if not d.empty:
        lr = d.loc[d["DistanceKm"].idxmax()]
        rows.append({"Category": "Longest Run", "TimeOrDist": f"{lr['DistanceKm']:.2f} km",
                     "AchievedDate": lr["WorkoutDate"].strftime("%Y-%m-%d"),
                     "PaceStr": pace_str(_num(lr["PaceSec"], np.nan))})
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
            used = _num(s.get("InitialDistanceKm")) + float(
                d.loc[d["ShoeID"].astype(str) == str(sid), "DistanceKm"].sum())
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

TRAINING_STATUS = {
    "Peaking":      ("ok",   "피킹 — 레이스 기량 최고조"),
    "Productive":   ("ok",   "생산적 — 부하와 기량이 함께 상승 중"),
    "Maintaining":  ("info", "유지 — 현재 수준을 지키는 중"),
    "Recovery":     ("info", "회복 — 의도적으로 부하를 낮춘 구간"),
    "Unproductive": ("warn", "비생산적 — 부하는 있으나 기량이 따라오지 않음"),
    "Detraining":   ("warn", "트레이닝 부족 — 부하가 모자람"),
    "Overreaching": ("bad",  "과훈련 — 부하가 회복 능력을 넘어섬"),
    "Strained":     ("bad",  "무리한 훈련 — 즉시 회복 필요"),
    "No Status":    ("info", "상태 없음 — 데이터가 더 필요함"),
}
TRAINING_STATUS_KR = {
    "Peaking": "피킹", "Productive": "생산적", "Maintaining": "유지",
    "Recovery": "회복", "Unproductive": "비생산적", "Detraining": "트레이닝 부족",
    "Overreaching": "과훈련", "Strained": "무리한 훈련", "No Status": "상태 없음",
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


def _latest(df: pd.DataFrame, date_col: str, field: str):
    """해당 컬럼에서 값이 있는 가장 최근 행의 (값, 날짜)."""
    if df is None or df.empty or field not in df.columns:
        return None, None
    d = df.copy()
    d[date_col] = pd.to_datetime(d[date_col], errors="coerce")
    d = d.dropna(subset=[date_col]).sort_values(date_col)
    vals = d[field]
    mask = vals.notna() & (vals.astype(str).str.strip() != "")
    if not mask.any():
        return None, None
    row = d[mask].iloc[-1]
    return row[field], row[date_col]


def latest_garmin(df_daily: pd.DataFrame, df_metrics: pd.DataFrame) -> dict:
    """가민 일일/주간 지표에서 '가장 최근에 입력된 값'을 필드별로 모읍니다.
    필드마다 입력 주기가 다르므로 행 단위가 아니라 컬럼 단위로 최신값을 찾습니다."""
    out = {}
    daily_fields = ["TrainingStatus", "AcuteLoad", "LoadRatio", "RecoveryTimeHr",
                    "TrainingReadiness", "BodyBattery", "HRVStatus", "HRVms",
                    "SleepScore", "RestingHR", "IntensityMinutes"]
    weekly_fields = ["VO2Max", "FitnessAge", "EnduranceScore", "HillScore",
                     "FocusAnaerobic", "FocusHighAerobic", "FocusLowAerobic",
                     "Pred5K", "Pred10K", "PredHalf", "PredFull",
                     "LTPace", "LTHR", "WeightKg", "BodyFatPct"]
    for f in daily_fields:
        v, dt = _latest(df_daily, "StatusDate", f)
        out[f], out[f + "_date"] = v, dt
    for f in weekly_fields:
        v, dt = _latest(df_metrics, "MetricDate", f)
        out[f], out[f + "_date"] = v, dt
    return out


def status_meta(status) -> tuple[str, str, str]:
    """Training Status → (톤, 한글명, 설명)"""
    s = str(status or "").strip()
    tone, desc = TRAINING_STATUS.get(s, ("info", "가민에서 확인한 값을 입력하세요"))
    return tone, TRAINING_STATUS_KR.get(s, s or "—"), desc


def load_ratio_meta(ratio) -> tuple[str, str]:
    """가민 Load Ratio(급성:만성) 해석. 가민 권장 구간은 대략 0.8~1.5."""
    r = _num(ratio, np.nan)
    if not np.isfinite(r):
        return "info", "미입력"
    if r < 0.8:
        return "warn", "부하 부족 — 기량 유지가 어려움"
    if r <= 1.5:
        return "ok", "최적 구간"
    return "bad", "부하 과다 — 회복 우선"


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


def endurance_tier(score) -> str:
    """가민 Endurance Score 등급 (대략적인 구간)."""
    s = _num(score, np.nan)
    if not np.isfinite(s):
        return "—"
    for lim, name in [(1400, "Novice"), (2800, "Intermediate"), (4200, "Trained"),
                      (5600, "Well Trained"), (7000, "Expert"), (8400, "Superior")]:
        if s < lim:
            return name
    return "Elite"


def garmin_race_predictions(g: dict) -> list[tuple[str, str]]:
    return [(n, str(g.get(k) or "—")) for n, k in
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
