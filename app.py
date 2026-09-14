"""
Running Life OS — 개인 러닝 관리·분석 시스템
============================================
필요 파일 : app.py / ui.py / db.py / analytics.py / requirements.txt
저장소    : Google Sheets (st.secrets 설정 시) 또는 로컬 엑셀 (자동 대체)
"""

import hashlib
import uuid
from datetime import datetime, timedelta, date

import numpy as np
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Running Life OS", page_icon="🏃",
                   layout="wide", initial_sidebar_state="collapsed")

import altair as alt
import ui
import db
import analytics as ana

ui.boot()

WORKOUT_TYPES = ["Easy", "Recovery", "LSD", "Tempo", "Threshold",
                 "Interval", "Sprint", "Race", "Cross Training"]
SURFACES = ["로드", "트랙", "트레드밀", "트레일", "기타"]


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


def parse_duration(v) -> float:
    """'00:45:32' / '45:32' / 45.5 → 분(float)"""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return 0.0
    s = str(v).strip()
    if ":" in s:
        try:
            p = [float(x) for x in s.split(":")]
            if len(p) == 3:
                return p[0] * 60 + p[1] + p[2] / 60
            if len(p) == 2:
                return p[0] + p[1] / 60
        except ValueError:
            return 0.0
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return 0.0


def alt_base(df: pd.DataFrame):
    return alt.Chart(df).properties(height=ui.chart_height()).configure_view(
        strokeWidth=0).configure_axis(grid=True, gridOpacity=.25, domain=False,
                                      labelColor="#64748b", titleColor="#64748b")


# ═══════════════════════════════════════════════════════════════════════════
# 로그인
# ═══════════════════════════════════════════════════════════════════════════
def secret(key: str, default=None):
    """secrets.toml 이 아예 없어도 예외 없이 동작."""
    try:
        return st.secrets[key]
    except Exception:
        return default


def check_password() -> bool:
    if st.session_state.get("auth"):
        return True

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


# ═══════════════════════════════════════════════════════════════════════════
# 헤더
# ═══════════════════════════════════════════════════════════════════════════
if ui.is_mobile():
    st.markdown("<p class='rl-title'>🏃 Running Life OS</p>"
                f"<p class='rl-sub'>{db.backend_name()} · HR {HR_REST:.0f}–{HR_MAX:.0f}</p>",
                unsafe_allow_html=True)
    with st.popover("⚙️ 설정", width="stretch"):
        ui.mode_switch()
        if st.button("🔒 잠금", width="stretch"):
            st.session_state["auth"] = False
            st.rerun()
else:
    h1, h2, h3 = st.columns([5, 2, 1])
    h1.markdown("<p class='rl-title'>🏃 Running Life OS</p>"
                f"<p class='rl-sub'>{db.backend_name()} 연결됨 · "
                f"HR {HR_REST:.0f}–{HR_MAX:.0f} bpm</p>", unsafe_allow_html=True)
    ui.mode_switch(h2)
    if h3.button("🔒 잠금", width="stretch"):
        st.session_state["auth"] = False
        st.rerun()

st.write("")

TAB_LABELS = (["🏠", "🏃", "🎯", "⚙️"] if ui.is_mobile()
              else ["🏠 대시보드", "🏃 훈련 & 리포트", "🎯 목표 & 자산", "⚙️ 관리 & 코치"])
tab_dash, tab_work, tab_goal, tab_admin = st.tabs(TAB_LABELS)


# ═══════════════════════════════════════════════════════════════════════════
# TAB 1 · 대시보드
# ═══════════════════════════════════════════════════════════════════════════
with tab_dash:
    df_w = db.load_data("Workouts")
    df_daily = db.load_data("DailyStatus")
    df_metrics = db.load_data("Metrics")
    df_proj = db.load_data("Projects")
    df_shoes = db.load_data("Shoes")

    # 가민이 1차 지표 — 사용자가 Connect에서 보고 입력한 값을 그대로 씁니다.
    G = ana.latest_garmin(df_daily, df_metrics)

    # 계산 지표는 보조 — 기록으로부터 직접 산출 (교차검증용)
    daily = ana.daily_load_series(df_w, HR_REST, HR_MAX, SEX)
    summary = ana.load_summary(daily)
    weekly = ana.weekly_summary(df_w)
    inten = ana.intensity_distribution(df_w, HR_REST, HR_MAX, LTHR)
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

    alerts = ana.garmin_alerts(G) + ana.build_alerts(df_w, df_shoes, daily, weekly, inten)
    if alerts:
        with ui.card("alerts"):
            ui.head("🔔 오늘의 체크포인트")
            for a in alerts[:6]:
                getattr(st, a["level"])(a["msg"])

    # ─────────────────────────────────────────────────────────────────
    # 가민 · 트레이닝 상태 (히어로)
    # ─────────────────────────────────────────────────────────────────
    with ui.card("gstatus"):
        tone, kr, desc = ana.status_meta(G.get("TrainingStatus"))
        ui.head("⌚ 가민 트레이닝 상태", gdate("TrainingStatus"))
        st.markdown(
            f"<div style='display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;margin-bottom:4px'>"
            f"<span style='font-size:1.9rem;font-weight:750;letter-spacing:-.02em'>{kr}</span>"
            f"{ui.pill(str(G.get('TrainingStatus') or 'No Status'), tone)}</div>"
            f"<p class='rl-sub' style='margin-bottom:14px'>{desc}</p>",
            unsafe_allow_html=True)

        lr_tone, lr_txt = ana.load_ratio_meta(G.get("LoadRatio"))
        rc_tone, rc_txt = ana.recovery_meta(G.get("RecoveryTimeHr"))
        ui.metrics([
            ("Acute Load", gv("AcuteLoad", "{:.0f}"), gdate("AcuteLoad")),
            ("Load Ratio", gv("LoadRatio", "{:.2f}"), lr_txt),
            ("회복 시간", gv("RecoveryTimeHr", "{:.0f}", "h"), rc_txt),
            ("주간 고강도 분", gv("IntensityMinutes", "{:.0f}", "분"), None),
        ], per_row_pc=4)

    # ─────────────────────────────────────────────────────────────────
    # 가민 · 컨디션 / 기량
    # ─────────────────────────────────────────────────────────────────
    c = ui.cols(2, 1)
    with c[0]:
        with ui.card("gcond"):
            ui.head("🔋 가민 컨디션", gdate("BodyBattery"))
            ui.metrics([
                ("Body Battery", gv("BodyBattery", "{:.0f}"), None),
                ("Readiness", gv("TrainingReadiness", "{:.0f}"), None),
                ("HRV", gv("HRVms", "{:.0f}", " ms"), str(G.get("HRVStatus") or "—")),
                ("수면 점수", gv("SleepScore", "{:.0f}"), None),
            ], per_row_pc=4)
            hrv = str(G.get("HRVStatus") or "")
            if hrv:
                t = {"Balanced": "ok", "Unbalanced": "warn", "Low": "bad", "Poor": "bad"}.get(hrv, "info")
                st.markdown(f"HRV 상태 {ui.pill(hrv, t)} · 안정시 심박 "
                            f"<b>{gv('RestingHR', '{:.0f}', ' bpm')}</b>", unsafe_allow_html=True)

    with c[1 % len(c)]:
        with ui.card("gfit"):
            ui.head("📈 가민 기량", gdate("VO2Max"))
            ui.metrics([
                ("VO₂max", gv("VO2Max", "{:.0f}"), None),
                ("피트니스 나이", gv("FitnessAge", "{:.0f}", "세"), None),
                ("Endurance", gv("EnduranceScore", "{:.0f}"), ana.endurance_tier(G.get("EnduranceScore"))),
                ("Hill Score", gv("HillScore", "{:.0f}"), None),
            ], per_row_pc=4)
            lt = str(G.get("LTPace") or "")
            if lt or G.get("LTHR"):
                st.markdown(f"<span class='rl-sub'>젖산역치 {lt or '—'} · "
                            f"{gv('LTHR', '{:.0f}', ' bpm')}</span>", unsafe_allow_html=True)

    # ─────────────────────────────────────────────────────────────────
    # 가민 · Load Focus / 레이스 예측
    # ─────────────────────────────────────────────────────────────────
    d2 = ui.cols(2, 1)
    with d2[0]:
        with ui.card("gfocus"):
            ui.head("🎚️ 가민 Load Focus", "최근 4주 부하의 성격 분포")
            fo = ana.load_focus(G)
            if fo:
                labels_fo = [("무산소", "anaerobic", "#ef4444"),
                             ("고강도 유산소", "high_aerobic", "#f59e0b"),
                             ("저강도 유산소", "low_aerobic", "#3b82f6")]
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
                st.caption("‘관리 & 코치 → 📈 주간 가민 지표’에서 Load Focus 3개 값을 입력하세요.")

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
            ui.metrics([
                ("CTL 체력", summary["ctl"],
                 f"{summary['ctl_ramp_7d']:+.1f} / 7일" if summary.get("ctl_ramp_7d") else None),
                ("ATL 피로", summary["atl"], None),
                ("TSB 폼", summary["tsb"], summary["form_text"]),
                ("ACWR", f"{acwr:.2f}" if acwr else "—", summary["risk_text"]),
            ], per_row_pc=4)
            with st.expander("🔍 가민 값과 비교해 보기"):
                prs = ana.detect_prs(df_w)
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
        show = daily.tail(120 if ui.is_mobile() else 180).reset_index(names="Date")
        if show["CTL"].sum() > 0:
            long = show.melt("Date", ["CTL", "ATL"], var_name="지표", value_name="값")
            area = alt.Chart(show).mark_area(opacity=.16, color="#2563eb").encode(
                x=alt.X("Date:T", title=None), y=alt.Y("TSB:Q", title="TSB"))
            line = alt.Chart(long).mark_line(strokeWidth=2).encode(
                x=alt.X("Date:T", title=None),
                y=alt.Y("값:Q", title="부하"),
                color=alt.Color("지표:N", scale=alt.Scale(
                    domain=["CTL", "ATL"], range=["#2563eb", "#f97316"]), title=None),
                tooltip=["Date:T", "지표:N", alt.Tooltip("값:Q", format=".1f")])
            st.altair_chart(alt.layer(line, area).resolve_scale(y="independent")
                            .properties(height=ui.chart_height(300, 220)), width="stretch")
        else:
            st.caption("훈련 기록을 입력하면 곡선이 그려집니다.")

    # ─────────────────────────────────────────────────────────────────
    b = ui.cols(2, 1)
    with b[0]:
        with ui.card("proj"):
            ui.head("🎯 진행 중 프로젝트")
            act = df_proj[df_proj["Status"] == "ACTIVE"] if not df_proj.empty else pd.DataFrame()
            if not act.empty:
                for _, p in act.iterrows():
                    dd, ddt = None, "—"
                    try:
                        dd = (pd.to_datetime(p["TargetDate"]).date() - date.today()).days
                        ddt = f"D{dd:+d}"
                    except Exception:
                        pass
                    st.markdown(f"<div class='rl-item'><div class='t'>{p['ProjectName']} "
                                f"{ui.pill(ddt, 'warn' if (dd is not None and dd < 30) else 'info')}</div>"
                                f"<div class='m'>목표 {p.get('GoalValue','—')} · 기한 {p.get('TargetDate','—')}</div></div>",
                                unsafe_allow_html=True)
            else:
                st.caption("활성 프로젝트가 없습니다. ‘목표 & 자산’ 탭에서 등록하세요.")

    with b[1 % len(b)]:
        with ui.card("recent"):
            ui.head("📋 최근 훈련")
            if not df_w.empty:
                d = ana.prepare_workouts(df_w).tail(6).iloc[::-1]
                ui.item_list([
                    (f"{r.WorkoutType} · {r.DistanceKm:.2f} km",
                     f"{r.WorkoutDate:%Y-%m-%d} · {ana.pace_str(r.PaceSec)} · "
                     f"{int(r.AvgHeartRate) if r.AvgHeartRate > 0 else '—'} bpm")
                    for r in d.itertuples()])
            else:
                st.caption("기록된 훈련이 없습니다.")


# ═══════════════════════════════════════════════════════════════════════════
# TAB 2 · 훈련 & 리포트
# ═══════════════════════════════════════════════════════════════════════════
with tab_work:
    labels = (["➕", "📋", "⌚", "📊", "🔮", "📥"] if ui.is_mobile()
              else ["➕ 기록 입력", "📋 훈련 이력", "⌚ 가민 추이", "📊 계산 통계",
                    "🔮 기량 예측", "📥 가져오기"])
    s_new, s_hist, s_garmin, s_stat, s_pred, s_imp = st.tabs(labels)

    df_proj = db.load_data("Projects")
    df_shoes = db.load_data("Shoes")
    proj_opts = {"(없음)": ""} | {r["ProjectName"]: r["ProjectID"] for _, r in df_proj.iterrows()}
    shoe_opts = {"(없음)": ""} | {
        f"{r['ShoeName']}": r["ShoeID"] for _, r in df_shoes.iterrows()
        if str(r.get("Status", "")).upper() != "RETIRED"}

    # ── 2-1 기록 입력 ──────────────────────────────────────────────────────
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

    # ── 2-2 훈련 이력 ──────────────────────────────────────────────────────
    with s_hist:
        df_w = db.load_data("Workouts")
        d = ana.prepare_workouts(df_w)

        with ui.card("filter"):
            f = ui.cols(3, 1, keep_row=True)
            sel_p = f[0].selectbox("프로젝트", ["전체"] + list(proj_opts)[1:], key="hist_p")
            sel_t = f[1 % len(f)].selectbox("유형", ["전체"] + WORKOUT_TYPES, key="hist_t")
            days = f[2 % len(f)].selectbox("기간", [30, 90, 180, 365, 9999],
                                           index=2, format_func=lambda x: "전체" if x > 1000 else f"최근 {x}일")

        if not d.empty:
            view = d[d["WorkoutDate"] >= pd.Timestamp.now().normalize() - timedelta(days=days)]
            if sel_p != "전체":
                view = view[view["ProjectID"].astype(str) == proj_opts[sel_p]]
            if sel_t != "전체":
                view = view[view["WorkoutType"] == sel_t]
        else:
            view = d

        with ui.card("histsum"):
            if not view.empty:
                ui.metrics([
                    ("총 거리", f"{view['DistanceKm'].sum():.1f} km", None),
                    ("횟수", f"{len(view)}회", None),
                    ("총 시간", ana.time_str(view["DurationMinutes"].sum() * 60), None),
                    ("평균 페이스", ana.pace_str(
                        view["DurationMinutes"].sum() * 60 / max(view["DistanceKm"].sum(), .001)), None)],
                    per_row_pc=4)
            else:
                st.caption("조건에 맞는 기록이 없습니다.")

        if not view.empty:
            with ui.card("histlist"):
                ui.head("기록")
                if ui.is_mobile():
                    ui.item_list([
                        (f"{r.WorkoutType} · {r.DistanceKm:.2f} km",
                         f"{r.WorkoutDate:%m/%d} · {ana.pace_str(r.PaceSec)} · "
                         f"{int(r.AvgHeartRate) if r.AvgHeartRate > 0 else '—'}bpm")
                        for r in view.iloc[::-1].head(40).itertuples()])
                else:
                    show = view.iloc[::-1][["WorkoutDate", "WorkoutType", "DistanceKm",
                                            "DurationMinutes", "AvgHeartRate", "Surface", "Notes"]].copy()
                    show["페이스"] = view.iloc[::-1]["PaceSec"].apply(ana.pace_str)
                    show.columns = ["날짜", "유형", "거리(km)", "시간(분)", "평균심박", "노면", "메모", "페이스"]
                    st.dataframe(show, width="stretch", hide_index=True,
                                 column_config={"날짜": st.column_config.DateColumn(format="YYYY-MM-DD")})

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
                        df_w.loc[idx, ["WorkoutDate", "WorkoutType", "DistanceKm", "DurationMinutes",
                                       "AvgHeartRate", "ShoeID", "Notes", "PaceSec"]] = [
                            e_date.strftime("%Y-%m-%d"), e_type, e_dist, e_min, e_hr,
                            shoe_opts[e_shoe], e_note,
                            round(e_min * 60 / e_dist, 1) if e_dist > 0 else ""]
                        db.write_sheet("Workouts", df_w)
                        st.success("수정 완료")
                        st.rerun()
                    if q[1].form_submit_button("🗑️ 삭제", width="stretch"):
                        db.write_sheet("Workouts", df_w[df_w["WorkoutID"] != wid])
                        st.warning("삭제 완료")
                        st.rerun()

    # ── 2-3 가민 추이 (가민이 준 값 그대로) ────────────────────────────────
    with s_garmin:
        gd = db.load_data("DailyStatus")
        gm = db.load_data("Metrics")
        gw = ana.prepare_workouts(db.load_data("Workouts"))

        if gd.empty and gm.empty:
            st.info("‘관리 & 코치 → ⌚ 가민 일일 / 📈 가민 주간’에서 값을 입력하면 여기에 추이가 그려집니다.")
        else:
            if not gd.empty:
                gdv = gd.copy()
                gdv["StatusDate"] = pd.to_datetime(gdv["StatusDate"], errors="coerce")
                gdv = gdv.dropna(subset=["StatusDate"]).sort_values("StatusDate")

                with ui.card("gts"):
                    ui.head("⌚ 트레이닝 상태 타임라인", "가민이 판정한 상태의 변화")
                    tl = gdv[gdv["TrainingStatus"].astype(str).str.strip() != ""].copy()
                    if not tl.empty:
                        tl["상태"] = tl["TrainingStatus"].map(
                            lambda x: ana.TRAINING_STATUS_KR.get(str(x), str(x)))
                        order = ["무리한 훈련", "과훈련", "비생산적", "트레이닝 부족",
                                 "회복", "유지", "생산적", "피킹"]
                        st.altair_chart(alt.Chart(tl).mark_circle(size=110, opacity=.85).encode(
                            x=alt.X("StatusDate:T", title=None, axis=alt.Axis(format="%m/%d")),
                            y=alt.Y("상태:N", sort=order, title=None),
                            color=alt.Color("상태:N", sort=order, legend=None,
                                            scale=alt.Scale(scheme="redyellowgreen")),
                            tooltip=["StatusDate:T", "상태:N"]
                        ).properties(height=ui.chart_height(220, 200)), width="stretch")
                    else:
                        st.caption("Training Status 입력 기록이 없습니다.")

                with ui.card("gload"):
                    ui.head("📊 가민 부하 추이", "막대=Acute Load, 선=Load Ratio (권장 0.8~1.5)")
                    ld = gdv[["StatusDate", "AcuteLoad", "LoadRatio"]].dropna(how="all",
                                                                             subset=["AcuteLoad", "LoadRatio"])
                    if not ld.empty:
                        bars = alt.Chart(ld).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3,
                                                      color="#2563eb", opacity=.75).encode(
                            x=alt.X("StatusDate:T", title=None),
                            y=alt.Y("AcuteLoad:Q", title="Acute Load"),
                            tooltip=["StatusDate:T", "AcuteLoad:Q", "LoadRatio:Q"])
                        ln = alt.Chart(ld).mark_line(color="#f97316", strokeWidth=2.5,
                                                     point=True).encode(
                            x=alt.X("StatusDate:T", title=None),
                            y=alt.Y("LoadRatio:Q", title="Load Ratio"))
                        band = alt.Chart(pd.DataFrame({"lo": [0.8], "hi": [1.5]})).mark_rect(
                            opacity=.08, color="#059669").encode(y="lo:Q", y2="hi:Q")
                        st.altair_chart(alt.layer(bars, (band + ln))
                                        .resolve_scale(y="independent")
                                        .properties(height=ui.chart_height(290, 230)), width="stretch")
                    else:
                        st.caption("Acute Load / Load Ratio 입력 기록이 없습니다.")

                gg = ui.cols(2, 1)
                with gg[0]:
                    with ui.card("ghrv"):
                        ui.head("💓 HRV · 안정시 심박")
                        hv = gdv.melt("StatusDate", ["HRVms", "RestingHR"],
                                      var_name="지표", value_name="값").dropna()
                        if not hv.empty:
                            st.altair_chart(alt.Chart(hv).mark_line(point=True, strokeWidth=2).encode(
                                x=alt.X("StatusDate:T", title=None),
                                y=alt.Y("값:Q", title=None, scale=alt.Scale(zero=False)),
                                color=alt.Color("지표:N", title=None)
                            ).properties(height=ui.chart_height(200, 180)), width="stretch")
                        else:
                            st.caption("데이터 없음")
                with gg[1 % len(gg)]:
                    with ui.card("grec"):
                        ui.head("😴 회복 시간 · 수면")
                        rv = gdv.melt("StatusDate", ["RecoveryTimeHr", "SleepScore"],
                                      var_name="지표", value_name="값").dropna()
                        if not rv.empty:
                            st.altair_chart(alt.Chart(rv).mark_line(point=True, strokeWidth=2).encode(
                                x=alt.X("StatusDate:T", title=None),
                                y=alt.Y("값:Q", title=None, scale=alt.Scale(zero=False)),
                                color=alt.Color("지표:N", title=None)
                            ).properties(height=ui.chart_height(200, 180)), width="stretch")
                        else:
                            st.caption("데이터 없음")

            if not gm.empty:
                gmv = gm.copy()
                gmv["MetricDate"] = pd.to_datetime(gmv["MetricDate"], errors="coerce")
                gmv = gmv.dropna(subset=["MetricDate"]).sort_values("MetricDate")

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
                        st.altair_chart(alt.Chart(fo).mark_bar(cornerRadius=3, size=34).encode(
                            x=alt.X("측정일:O", title=None,
                                    axis=alt.Axis(labelAngle=-45, labelLimit=80)),
                            y=alt.Y("부하:Q", stack="normalize", title="비중",
                                    axis=alt.Axis(format="%")),
                            color=alt.Color("구분:N", title=None, scale=alt.Scale(
                                domain=["무산소", "고강도 유산소", "저강도 유산소"],
                                range=["#ef4444", "#f59e0b", "#3b82f6"])),
                            tooltip=["측정일:O", "구분:N", "부하:Q"]
                        ).properties(height=ui.chart_height(260, 220)), width="stretch")
                    else:
                        st.caption("Load Focus 입력 기록이 없습니다.")

                with ui.card("gscore"):
                    ui.head("🏅 가민 기량 점수 추이", "각 지표는 단위가 달라 따로 그립니다")
                    score_cols = [("VO2Max", "VO₂max", "#2563eb"),
                                  ("EnduranceScore", "Endurance Score", "#0d9488"),
                                  ("HillScore", "Hill Score", "#f97316"),
                                  ("FitnessAge", "피트니스 나이", "#7c3aed")]
                    sc_cols = ui.cols(2, 1)
                    for i, (col, title, color) in enumerate(score_cols):
                        sub = gmv[["MetricDate", col]].dropna()
                        with sc_cols[i % len(sc_cols)]:
                            st.markdown(f"<p class='rl-sub' style='margin:8px 0 -6px'>{title}</p>",
                                        unsafe_allow_html=True)
                            if not sub.empty:
                                st.altair_chart(alt.Chart(sub).mark_line(
                                    point=True, strokeWidth=2.5, color=color).encode(
                                    x=alt.X("MetricDate:T", title=None,
                                            axis=alt.Axis(format="%m/%d")),
                                    y=alt.Y(f"{col}:Q", title=None, scale=alt.Scale(zero=False)),
                                    tooltip=["MetricDate:T", f"{col}:Q"]
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
                            tooltip=["WorkoutDate:T", "WorkoutType", "AerobicTE", "AnaerobicTE"]
                        ).properties(height=ui.chart_height(300, 260)), width="stretch")

    # ── 2-3 통계 ──────────────────────────────────────────────────────────
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
                bars = alt.Chart(wdf).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4,
                                               color="#2563eb", opacity=.85).encode(
                    x=alt.X("주:O", title=None, axis=alt.Axis(labelAngle=-45, labelLimit=70)),
                    y=alt.Y("Distance:Q", title="km"),
                    tooltip=["주", "Distance", "Runs", "LongRun", "AvgPaceStr", "WoW%"])
                ma = alt.Chart(wdf).mark_line(color="#f97316", strokeWidth=2.5, point=True).encode(
                    x=alt.X("주:O", title=None), y=alt.Y("MA4:Q", title=None))
                st.altair_chart((bars + ma).properties(height=ui.chart_height(300, 240)),
                                width="stretch")
                if not ui.is_mobile():
                    st.dataframe(wk[["Distance", "Runs", "LongRun", "AvgPaceStr", "WoW%", "Ramp_Flag"]]
                                 .rename(columns={"Distance": "거리(km)", "Runs": "횟수",
                                                  "LongRun": "롱런(km)", "AvgPaceStr": "평균페이스",
                                                  "WoW%": "전주대비(%)", "Ramp_Flag": "경고"}),
                                 width="stretch")

            g = ui.cols(2, 1)
            with g[0]:
                with ui.card("zone"):
                    ui.head("🎚️ 강도 분포 (최근 90일)")
                    if inten := ana.intensity_distribution(df_w, HR_REST, HR_MAX, LTHR):
                        zd = pd.DataFrame({"존": list(inten["zone_pct"]),
                                           "비율": list(inten["zone_pct"].values())})
                        st.altair_chart(alt.Chart(zd).mark_bar(cornerRadius=4).encode(
                            y=alt.Y("존:N", sort=None, title=None),
                            x=alt.X("비율:Q", title="%"),
                            color=alt.Color("존:N", legend=None, scale=alt.Scale(
                                range=["#93c5fd", "#60a5fa", "#fbbf24", "#fb923c", "#ef4444"])),
                            tooltip=["존", "비율"]).properties(height=ui.chart_height(200, 180)),
                            width="stretch")
                        p = inten["polarized_pct"]
                        ui.rows([("저강도 (LT1 미만)", f"{p['low']}%"),
                                 ("중강도 (회색지대)", f"{p['mid']}%"),
                                 ("고강도 (LT2 이상)", f"{p['high']}%")])
                        st.markdown(ui.pill(inten["verdict"],
                                            "ok" if p["low"] >= 78 else "warn"),
                                    unsafe_allow_html=True)
                    else:
                        st.caption("심박 데이터가 있는 기록이 필요합니다.")

            with g[1 % len(g)]:
                with ui.card("effi"):
                    ui.head("💓 러닝 이코노미 (EF)", "이지런 속도÷심박 — 우상향이면 개선")
                    ef = ana.efficiency_factor(df_w)
                    if not ef.empty:
                        st.altair_chart(alt.Chart(ef).mark_circle(size=45, opacity=.45,
                                                                  color="#2563eb").encode(
                            x=alt.X("WorkoutDate:T", title=None), y=alt.Y("EF:Q", title="EF",
                                                                          scale=alt.Scale(zero=False)),
                            tooltip=["WorkoutDate:T", alt.Tooltip("EF:Q", format=".3f")])
                            .properties(height=ui.chart_height(200, 180))
                            + alt.Chart(ef).mark_line(color="#f97316", strokeWidth=2.5).encode(
                                x="WorkoutDate:T", y="EF_MA4:Q"),
                            width="stretch")
                    else:
                        st.caption("이지런(Easy/Recovery/LSD) 기록이 필요합니다.")

            with ui.card("scatter"):
                ui.head("🫀 페이스 대비 심박", "왼쪽 아래로 이동할수록 기량 향상")
                sc = d[(d["AvgHeartRate"] > 0) & (d["PaceSec"].notna())].copy()
                if not sc.empty:
                    sc["월"] = sc["WorkoutDate"].dt.to_period("M").astype(str)
                    sc["페이스(분/km)"] = sc["PaceSec"] / 60
                    st.altair_chart(alt.Chart(sc).mark_circle(size=80, opacity=.6).encode(
                        x=alt.X("페이스(분/km):Q", scale=alt.Scale(zero=False, reverse=True)),
                        y=alt.Y("AvgHeartRate:Q", title="평균 심박", scale=alt.Scale(zero=False)),
                        color=alt.Color("월:N", scale=alt.Scale(scheme="viridis"), title=None),
                        size=alt.Size("DistanceKm:Q", legend=None),
                        tooltip=["WorkoutDate:T", "WorkoutType", "DistanceKm", "AvgHeartRate"])
                        .properties(height=ui.chart_height(320, 260)), width="stretch")

            with ui.card("cal"):
                ui.head("🗓️ 훈련 달력", "진할수록 긴 거리")
                dl = ana.daily_load_series(df_w, HR_REST, HR_MAX, SEX).tail(
                    119 if ui.is_mobile() else 245).reset_index(names="Date")
                dl["요일"] = dl["Date"].dt.dayofweek
                dl["주차"] = ((dl["Date"] - dl["Date"].min()).dt.days // 7)
                dl["요일명"] = dl["요일"].map({0: "월", 1: "화", 2: "수", 3: "목",
                                            4: "금", 5: "토", 6: "일"})
                st.altair_chart(alt.Chart(dl).mark_rect(cornerRadius=3, stroke="white",
                                                        strokeWidth=2).encode(
                    x=alt.X("주차:O", axis=None),
                    y=alt.Y("요일명:N", sort=["월", "화", "수", "목", "금", "토", "일"], title=None),
                    color=alt.Color("DistanceKm:Q", scale=alt.Scale(scheme="blues"), legend=None),
                    tooltip=["Date:T", alt.Tooltip("DistanceKm:Q", title="거리", format=".1f")])
                    .properties(height=ui.chart_height(170, 150)), width="stretch")

            k = ui.cols(2, 1)
            with k[0]:
                with ui.card("bytype"):
                    ui.head("🏃 유형별 거리")
                    t = d.groupby("WorkoutType", as_index=False)["DistanceKm"].sum()
                    st.altair_chart(alt.Chart(t).mark_bar(cornerRadius=4, color="#2563eb").encode(
                        y=alt.Y("WorkoutType:N", sort="-x", title=None),
                        x=alt.X("DistanceKm:Q", title="km"), tooltip=["WorkoutType", "DistanceKm"])
                        .properties(height=ui.chart_height(220, 200)), width="stretch")
            with k[1 % len(k)]:
                with ui.card("bymonth"):
                    ui.head("📆 월별 누적 거리")
                    mm = d.copy()
                    mm["월"] = mm["WorkoutDate"].dt.to_period("M").astype(str)
                    mv = mm.groupby("월", as_index=False)["DistanceKm"].sum()
                    st.altair_chart(alt.Chart(mv).mark_bar(cornerRadius=4, color="#0ea5e9").encode(
                        x=alt.X("월:O", title=None, axis=alt.Axis(labelAngle=-45)),
                        y=alt.Y("DistanceKm:Q", title="km"), tooltip=["월", "DistanceKm"])
                        .properties(height=ui.chart_height(220, 200)), width="stretch")

    # ── 2-4 기량 예측 ──────────────────────────────────────────────────────
    with s_pred:
        df_w = db.load_data("Workouts")
        with ui.card("vdot"):
            ui.head("🔮 VDOT 기반 기량 예측", "최근 최고 기록 또는 직접 입력한 기록으로 계산")
            src = st.radio("기준 기록", ["기록에서 자동 추출", "직접 입력"],
                           horizontal=True, label_visibility="collapsed")
            vdot = np.nan
            if src == "직접 입력":
                v = ui.cols(3, 1, keep_row=True)
                bd = v[0].number_input("거리 (km)", 0.4, 100.0, 10.0, 0.1)
                bm = v[1 % len(v)].number_input("기록 (분)", 1.0, 600.0, 50.0, 0.1)
                vdot = ana.vdot_from_performance(bd, bm)
                v[2 % len(v)].metric("VDOT", f"{vdot:.1f}" if np.isfinite(vdot) else "—")
            else:
                prs = ana.detect_prs(df_w)
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

    # ── 2-5 가져오기 ───────────────────────────────────────────────────────
    with s_imp:
        with ui.card("imp"):
            ui.head("📥 Garmin CSV / XLSX 가져오기",
                    "Garmin Connect → 활동 → 내보내기(CSV) 파일을 올리세요")
            up = st.file_uploader("파일", type=["csv", "xlsx"], label_visibility="collapsed")
            if up is not None:
                try:
                    raw = pd.read_csv(up) if up.name.endswith(".csv") else pd.read_excel(up)
                except Exception as e:
                    st.error(f"파일을 읽지 못했습니다: {e}")
                    raw = pd.DataFrame()

                if not raw.empty:
                    st.dataframe(raw.head(4), width="stretch")
                    cand = list(raw.columns)

                    def guess(keys):
                        for k in keys:
                            for c in cand:
                                if k.lower() in str(c).lower():
                                    return c
                        return cand[0]

                    st.markdown("**컬럼 연결** — 자동으로 잡힌 값을 확인하고 틀리면 바꾸세요.")
                    mc = ui.cols(3, 1, keep_row=True)
                    c_date = mc[0].selectbox("날짜", cand, index=cand.index(guess(["날짜", "date", "시작"])))
                    c_dist = mc[1 % len(mc)].selectbox("거리", cand, index=cand.index(guess(["거리", "distance"])))
                    c_dur = mc[2 % len(mc)].selectbox("시간", cand, index=cand.index(guess(["시간", "time"])))
                    mc2 = ui.cols(3, 1, keep_row=True)
                    c_hr = mc2[0].selectbox("평균 심박", ["(없음)"] + cand,
                                            index=(cand.index(guess(["평균 심박", "avg hr"])) + 1)
                                            if guess(["평균 심박", "avg hr"]) in cand else 0)
                    unit = mc2[1 % len(mc2)].selectbox("거리 단위", ["km", "m", "mile"])
                    dtype = mc2[2 % len(mc2)].selectbox("기본 훈련 유형", WORKOUT_TYPES)

                    if st.button("데이터베이스에 저장", width="stretch", type="primary"):
                        exist = set(db.load_data("Workouts")["SourceKey"].astype(str))
                        mult = {"km": 1.0, "m": 0.001, "mile": 1.609344}[unit]
                        rows, dup = [], 0
                        for _, r in raw.iterrows():
                            dist = fnum(str(r[c_dist]).replace(",", "")) * mult
                            dur = parse_duration(r[c_dur])
                            try:
                                dt = pd.to_datetime(r[c_date]).strftime("%Y-%m-%d")
                            except Exception:
                                continue
                            if dist <= 0 or dur <= 0:
                                continue
                            key = src_key(dt, dist, dur)
                            if key in exist:
                                dup += 1
                                continue
                            exist.add(key)
                            rows.append({
                                "WorkoutID": new_id("WO"), "ProjectID": "",
                                "WorkoutDate": dt, "WorkoutType": dtype,
                                "DistanceKm": round(dist, 2), "DurationMinutes": round(dur, 1),
                                "PaceSec": round(dur * 60 / dist, 1),
                                "AvgHeartRate": fnum(r[c_hr]) if c_hr != "(없음)" else "",
                                "Notes": "Garmin 가져오기", "SourceKey": key})
                        if rows:
                            db.append_rows("Workouts", pd.DataFrame(rows))
                        st.success(f"{len(rows)}건 추가 · 중복 {dup}건 건너뜀")
                        st.rerun()


# ═══════════════════════════════════════════════════════════════════════════
# TAB 3 · 목표 & 자산
# ═══════════════════════════════════════════════════════════════════════════
with tab_goal:
    labels = (["🎯", "👟", "🏁", "🏆"] if ui.is_mobile()
              else ["🎯 프로젝트", "👟 러닝화", "🏁 대회", "🏆 개인 기록"])
    g1, g2, g3, g4 = st.tabs(labels)

    # 프로젝트
    with g1:
        df_proj = db.load_data("Projects")
        with ui.card("plist"):
            ui.head("🎯 프로젝트")
            if not df_proj.empty:
                for _, p in df_proj.iterrows():
                    tone = {"ACTIVE": "ok", "PLANNED": "info", "COMPLETED": "warn"}.get(
                        str(p["Status"]).upper(), "info")
                    st.markdown(f"<div class='rl-item'><div class='t'>{p['ProjectName']} "
                                f"{ui.pill(p['Status'], tone)}</div>"
                                f"<div class='m'>목표 {p.get('GoalValue','—')} · "
                                f"{p.get('StartDate','—')} → {p.get('TargetDate','—')}</div></div>",
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

    # 러닝화
    with g2:
        df_shoes = db.load_data("Shoes")
        df_w = db.load_data("Workouts")
        d = ana.prepare_workouts(df_w)

        with ui.card("sadd"):
            with st.expander("➕ 러닝화 등록"):
                with st.form("f_shoe", clear_on_submit=True):
                    sn = st.text_input("이름", "Nike Zoom Fly 6")
                    sb_ = ui.cols(2, 2, keep_row=True)
                    sbrand = sb_[0].text_input("브랜드", "Nike")
                    scat = sb_[1].selectbox("용도", ["Daily", "Tempo", "Race", "Trail"])
                    sd_ = ui.cols(2, 2, keep_row=True)
                    sinit = sd_[0].number_input("기존 누적 (km)", 0.0, 2000.0, 0.0, 1.0)
                    starg = sd_[1].number_input("목표 수명 (km)", 100.0, 2000.0, 600.0, 50.0)
                    if st.form_submit_button("등록", width="stretch", type="primary"):
                        db.append_rows("Shoes", pd.DataFrame([{
                            "ShoeID": new_id("SHOE"), "ShoeName": sn, "Brand": sbrand,
                            "PurchaseDate": date.today().strftime("%Y-%m-%d"),
                            "InitialDistanceKm": sinit, "TargetDistanceKm": starg,
                            "Status": "ACTIVE", "Category": scat, "Notes": ""}]))
                        st.success("등록 완료")
                        st.rerun()

        if df_shoes.empty:
            st.caption("등록된 러닝화가 없습니다.")
        else:
            sc = ui.cols(2, 1)
            for i, (_, s) in enumerate(df_shoes.iterrows()):
                with sc[i % len(sc)]:
                    with ui.card(f"shoe{i}"):
                        used = fnum(s.get("InitialDistanceKm")) + (
                            float(d.loc[d["ShoeID"].astype(str) == str(s["ShoeID"]),
                                        "DistanceKm"].sum()) if "ShoeID" in d.columns else 0.0)
                        targ = fnum(s.get("TargetDistanceKm"), 600.0) or 600.0
                        pct = min(100.0, used / targ * 100)
                        tone = "bad" if pct >= 100 else ("warn" if pct >= 85 else "")
                        st.markdown(f"<div class='t' style='font-weight:700'>👟 {s['ShoeName']}</div>"
                                    f"<div class='m'>{s.get('Brand','')} · {s.get('Category','')} · "
                                    f"{s.get('Status','')}</div>", unsafe_allow_html=True)
                        ui.bar(pct, tone)
                        st.markdown(f"<div class='rl-row'><span class='k'>누적</span>"
                                    f"<span class='v'>{used:.0f} / {targ:.0f} km "
                                    f"({pct:.0f}%)</span></div>", unsafe_allow_html=True)
                        if pct >= 85:
                            st.markdown(ui.pill("교체 시점 도달" if pct >= 100 else "교체 준비",
                                                tone or "warn"), unsafe_allow_html=True)

    # 대회
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
            prs = ana.detect_prs(df_w)
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
                    dtag = f"D{dday:+d}" if dday is not None else "—"
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

    # 개인 기록
    with g4:
        df_w = db.load_data("Workouts")
        with ui.card("pr"):
            ui.head("🏆 개인 최고 기록", "훈련 이력에서 자동 추출 (거리 ±3% 허용)")
            prs = ana.detect_prs(df_w)
            if ui.is_mobile():
                ui.item_list([(f"{r.Category} — {r.TimeOrDist}",
                               f"{r.AchievedDate} · {r.PaceStr}") for r in prs.itertuples()])
            else:
                st.dataframe(prs.rename(columns={"Category": "종목", "TimeOrDist": "기록",
                                                 "AchievedDate": "달성일", "PaceStr": "페이스"}),
                             width="stretch", hide_index=True)
            st.caption("※ 최대노력이 아닌 훈련도 포함될 수 있습니다. 레이스 기록은 대회 탭에서 따로 관리하세요.")


# ═══════════════════════════════════════════════════════════════════════════
# TAB 4 · 관리 & 코치
# ═══════════════════════════════════════════════════════════════════════════
with tab_admin:
    labels = (["👤", "⌚", "📈", "🤖", "💾"] if ui.is_mobile()
              else ["👤 프로필", "⌚ 가민 일일", "📈 가민 주간", "🤖 코치 노트", "💾 백업"])
    a1, a2, a3, a4, a5 = st.tabs(labels)

    with a1:
        with ui.card("prof"):
            ui.head("👤 선수 프로필", "심박 설정이 모든 분석의 기준값입니다 — 꼭 실제 값으로 맞추세요")
            with st.form("f_ath"):
                p1 = ui.cols(3, 1, keep_row=True)
                a_name = p1[0].text_input("이름", str(ATH.get("Name", "")))
                a_sex = p1[1 % len(p1)].selectbox("성별", ["M", "F"],
                                                  index=0 if SEX.upper().startswith("M") else 1)
                a_h = p1[2 % len(p1)].number_input("키 (cm)", 100, 230, int(fnum(ATH.get("HeightCm"), 175)))
                p2 = ui.cols(3, 1, keep_row=True)
                a_rest = p2[0].number_input("안정시 심박", 30, 100, int(HR_REST))
                a_max = p2[1 % len(p2)].number_input("최대 심박", 120, 230, int(HR_MAX))
                a_lt = p2[2 % len(p2)].number_input("젖산역치 심박 (LTHR)", 0, 230,
                                                    int(LTHR or round(HR_REST + .85 * (HR_MAX - HR_REST))))
                p3 = ui.cols(2, 2, keep_row=True)
                a_w = p3[0].number_input("현재 체중 (kg)", 30.0, 200.0, fnum(ATH.get("CurrentWeightKg"), 70.0), 0.1)
                a_sw = p3[1].number_input("시작 체중 (kg)", 30.0, 250.0, fnum(ATH.get("StartWeightKg"), 70.0), 0.1)
                if st.form_submit_button("저장", width="stretch", type="primary"):
                    db.save_athlete({"Name": a_name, "Sex": a_sex, "HeightCm": a_h,
                                     "HRRest": a_rest, "HRMax": a_max, "LTHR": a_lt,
                                     "CurrentWeightKg": a_w, "StartWeightKg": a_sw})
                    st.success("저장 완료")
                    st.rerun()
            zs = ana.hr_zones(HR_REST, HR_MAX)
            ui.rows([(n, f"{lo:.0f} – {(hi if hi < 900 else HR_MAX):.0f} bpm") for n, lo, hi in zs])

    # ── 가민 일일 지표 입력 ────────────────────────────────────────────
    with a2:
        with ui.card("gdaily"):
            ui.head("⌚ 가민 일일 지표", "Garmin Connect 홈 화면에서 보고 그대로 옮겨 적으세요")
            with st.form("f_daily", clear_on_submit=True):
                q0 = ui.cols(2, 1, keep_row=True)
                dd_ = q0[0].date_input("날짜", date.today())
                ts = q0[1 % len(q0)].selectbox(
                    "Training Status", list(ana.TRAINING_STATUS.keys()),
                    index=list(ana.TRAINING_STATUS).index("Productive"),
                    format_func=lambda k: f"{ana.TRAINING_STATUS_KR[k]} ({k})")

                st.markdown("<p class='rl-sub' style='margin:10px 0 2px'>트레이닝 부하</p>",
                            unsafe_allow_html=True)
                q1 = ui.cols(3, 1, keep_row=True)
                acute = q1[0].number_input("Acute Load", 0, 2000, 0,
                                           help="Connect → 트레이닝 상태 → 부하")
                ratio = q1[1 % len(q1)].number_input("Load Ratio", 0.0, 5.0, 0.0, 0.01,
                                                     help="급성:만성 부하비. 가민 권장 0.8~1.5")
                rec = q1[2 % len(q1)].number_input("회복 시간 (h)", 0, 200, 0)

                st.markdown("<p class='rl-sub' style='margin:10px 0 2px'>컨디션</p>",
                            unsafe_allow_html=True)
                q2 = ui.cols(4, 1, keep_row=True)
                tr = q2[0].number_input("Readiness", 0, 100, 0)
                bb = q2[1 % len(q2)].number_input("Body Battery", 0, 100, 0)
                hrvms = q2[2 % len(q2)].number_input("HRV (ms)", 0, 250, 0)
                hrv = q2[3 % len(q2)].selectbox("HRV 상태",
                                                ["Balanced", "Unbalanced", "Low", "Poor", "No Status"])

                q3 = ui.cols(3, 1, keep_row=True)
                slp = q3[0].number_input("수면 점수", 0, 100, 0)
                rhr = q3[1 % len(q3)].number_input("안정시 심박", 0, 120, 0)
                im = q3[2 % len(q3)].number_input("고강도 분 (주간)", 0, 1000, 0)
                nt = st.text_input("메모", "")

                if st.form_submit_button("저장", width="stretch", type="primary"):
                    db.append_rows("DailyStatus", pd.DataFrame([{
                        "StatusID": new_id("DS"), "StatusDate": dd_.strftime("%Y-%m-%d"),
                        "TrainingStatus": ts, "AcuteLoad": acute or "",
                        "LoadRatio": ratio or "", "RecoveryTimeHr": rec or "",
                        "TrainingReadiness": tr or "", "BodyBattery": bb or "",
                        "HRVStatus": hrv, "HRVms": hrvms or "", "SleepScore": slp or "",
                        "RestingHR": rhr or "", "IntensityMinutes": im or "", "Notes": nt}]))
                    st.success("저장 완료")
                    st.rerun()
            st.caption("입력하지 않은 항목(0)은 저장되지 않습니다. 매일 전부 채울 필요 없습니다 — "
                       "대시보드는 항목별로 가장 최근에 입력된 값을 씁니다.")

        df_daily = db.load_data("DailyStatus")
        if not df_daily.empty:
            with ui.card("dtrend"):
                ui.head("최근 추이")
                dv = df_daily.tail(60).copy()
                dv["StatusDate"] = pd.to_datetime(dv["StatusDate"], errors="coerce")
                long = dv.melt("StatusDate", ["BodyBattery", "TrainingReadiness", "HRVms"],
                               var_name="지표", value_name="값").dropna()
                if not long.empty:
                    st.altair_chart(alt.Chart(long).mark_line(point=True, strokeWidth=2).encode(
                        x=alt.X("StatusDate:T", title=None), y=alt.Y("값:Q", title=None),
                        color=alt.Color("지표:N", title=None)).properties(
                        height=ui.chart_height()), width="stretch")

    # ── 가민 주간 지표 입력 ────────────────────────────────────────────
    with a3:
        with ui.card("gweekly"):
            ui.head("📈 주간 가민 지표", "Connect → 통계/성과 에서 주 1회만 확인하면 됩니다")
            with st.form("f_metric", clear_on_submit=True):
                md_ = st.date_input("측정일", date.today())

                st.markdown("<p class='rl-sub' style='margin:10px 0 2px'>기량</p>",
                            unsafe_allow_html=True)
                r1 = ui.cols(4, 1, keep_row=True)
                mv = r1[0].number_input("VO₂max", 0.0, 90.0, 0.0, 0.5)
                fa = r1[1 % len(r1)].number_input("피트니스 나이", 0, 100, 0)
                es = r1[2 % len(r1)].number_input("Endurance Score", 0, 12000, 0)
                hs = r1[3 % len(r1)].number_input("Hill Score", 0, 100, 0)

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

                st.markdown("<p class='rl-sub' style='margin:10px 0 2px'>젖산역치 · 체성분</p>",
                            unsafe_allow_html=True)
                r4 = ui.cols(4, 1, keep_row=True)
                mlp = r4[0].text_input("LT 페이스", "", placeholder="4:50")
                mlh = r4[1 % len(r4)].number_input("LTHR", 0, 230, 0)
                mw = r4[2 % len(r4)].number_input("체중 (kg)", 0.0, 200.0, 0.0, 0.1)
                mf = r4[3 % len(r4)].number_input("체지방률 (%)", 0.0, 60.0, 0.0, 0.1)

                if st.form_submit_button("저장", width="stretch", type="primary"):
                    db.append_rows("Metrics", pd.DataFrame([{
                        "MetricID": new_id("MET"), "MetricDate": md_.strftime("%Y-%m-%d"),
                        "VO2Max": mv or "", "FitnessAge": fa or "",
                        "EnduranceScore": es or "", "HillScore": hs or "",
                        "FocusAnaerobic": fan or "", "FocusHighAerobic": fhi or "",
                        "FocusLowAerobic": flo or "",
                        "Pred5K": p5, "Pred10K": p10, "PredHalf": ph, "PredFull": pf,
                        "LTPace": mlp, "LTHR": mlh or "", "LTPower": "",
                        "WeightKg": mw or "", "BodyFatPct": mf or "", "Notes": ""}]))
                    st.success("저장 완료")
                    st.rerun()

        dm = db.load_data("Metrics")
        if not dm.empty:
            dm["MetricDate"] = pd.to_datetime(dm["MetricDate"], errors="coerce")
            mc = ui.cols(2, 1)
            charts = [("VO2Max", "VO₂max"), ("EnduranceScore", "Endurance Score"),
                      ("HillScore", "Hill Score"), ("WeightKg", "체중 (kg)")]
            for i, (col, title) in enumerate(charts):
                sub = dm[["MetricDate", col]].dropna()
                with mc[i % len(mc)]:
                    with ui.card(f"mt{i}"):
                        ui.head(title)
                        if not sub.empty:
                            st.altair_chart(alt.Chart(sub).mark_line(
                                point=True, strokeWidth=2.5, color="#2563eb").encode(
                                x=alt.X("MetricDate:T", title=None),
                                y=alt.Y(f"{col}:Q", title=None, scale=alt.Scale(zero=False))
                            ).properties(height=ui.chart_height(190, 170)), width="stretch")
                        else:
                            st.caption("데이터 없음")

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

    with a5:
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
