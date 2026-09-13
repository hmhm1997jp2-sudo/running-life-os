import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import os

st.set_page_config(page_title="Running Life OS", page_icon="🏃", layout="wide", initial_sidebar_state="collapsed")

# 🎨 Custom CSS
st.markdown("""
    <style>
    .css-card {
        background-color: #f8fafc;
        border-radius: 12px;
        padding: 18px;
        margin-bottom: 16px;
        border: 1px solid #e2e8f0;
        box-shadow: 0 2px 8px rgba(0,0,0,0.05);
    }
    .card-title {
        font-size: 1.1rem;
        font-weight: 700;
        color: #0f172a;
        margin-bottom: 12px;
    }
    div[data-testid="stMetricValue"] {
        font-size: 1.8rem !important;
        font-weight: 700 !important;
        color: #0284c7 !important;
    }
    div[data-testid="stMetricLabel"] {
        font-size: 0.9rem !important;
        color: #475569 !important;
        font-weight: 600 !important;
    }
    .stButton>button {
        border-radius: 8px !important;
        background-color: #0284c7 !important;
        color: white !important;
        font-weight: 600 !important;
        border: none !important;
    }
    </style>
""", unsafe_allow_html=True)

# 🔒 보안 처리
def check_password():
    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False
    if st.session_state["authenticated"]:
        return True

    st.markdown("<h2 style='text-align: center;'>🔒 Running Life OS</h2>", unsafe_allow_html=True)
    st.caption("<p style='text-align: center;'>개인 보호용 Running Life OS 시스템입니다. 비밀번호를 입력하세요.</p>", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        user_password = st.text_input("🔑 Password", type="password")
        if st.button("Access OS", use_container_width=True):
            if "PASSWORD" in st.secrets and user_password == st.secrets["PASSWORD"]:
                st.session_state["authenticated"] = True
                st.rerun()
            elif "PASSWORD" not in st.secrets and user_password == "1234":
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("❌ 비밀번호가 올바르지 않습니다.")
    return False

if not check_password():
    st.stop()

# 🏃 메인 시스템 DB 파일 핸들링
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "Running Life OS Database.xlsx")

def get_clean_default_sheets():
    return {
        "Athlete": pd.DataFrame([{"AthleteID": "ATH-001", "BirthDate": "1997-10-28", "HeightCm": 180, "CurrentWeightKg": 85.0, "StartWeightKg": 115.0, "HRRest": 55, "HRMax": 190}]),
        "Projects": pd.DataFrame(columns=["ProjectID", "ProjectName", "Status", "GoalType", "GoalValue", "StartDate", "TargetDate", "Description"]),
        "Workouts": pd.DataFrame(columns=["WorkoutID", "ProjectID", "WorkoutDate", "WorkoutType", "DistanceKm", "DurationMinutes", "AvgPace", "AvgHeartRate", "AvgPower", "Temperature", "ShoeID", "RPE", "LegFatigue", "CardioFatigue", "Notes"]),
        "DailyStatus": pd.DataFrame(columns=["StatusID", "StatusDate", "TrainingReadiness", "BodyBattery", "HRVStatus", "Notes"]),
        "Metrics": pd.DataFrame(columns=["MetricID", "MetricDate", "WeightKg", "VO2Max", "LTPace", "LTHR", "LTPower"]),
        "Shoes": pd.DataFrame(columns=["ShoeID", "ShoeName", "Brand", "PurchaseDate", "InitialDistanceKm", "TargetDistanceKm", "Status", "Category"]),
        "Races": pd.DataFrame(columns=["RaceID", "ProjectID", "RaceDate", "RaceName", "Distance", "GoalTime", "ActualTime", "ShoeID", "ResultStatus"]),
        "CoachNotes": pd.DataFrame(columns=["NoteID", "ProjectID", "NoteDate", "Category", "NoteText"]),
        "PersonalRecords": pd.DataFrame([
            {"Category": "1km", "TimeOrDist": "-", "AchievedDate": "-", "Notes": "-"},
            {"Category": "5km", "TimeOrDist": "-", "AchievedDate": "-", "Notes": "-"},
            {"Category": "10km", "TimeOrDist": "-", "AchievedDate": "-", "Notes": "-"},
            {"Category": "Half Marathon", "TimeOrDist": "-", "AchievedDate": "-", "Notes": "-"},
            {"Category": "Full Marathon", "TimeOrDist": "-", "AchievedDate": "-", "Notes": "-"},
            {"Category": "Longest Run", "TimeOrDist": "-", "AchievedDate": "-", "Notes": "-"}
        ]),
        "TrainingPlans": pd.DataFrame(columns=["PlanID", "PlanDate", "GarminPlan", "CopilotPlan", "SelectedPlan", "Status"])
    }

def init_db(reset=False):
    default_sheets = get_clean_default_sheets()
    if reset or not os.path.exists(DB_FILE):
        with pd.ExcelWriter(DB_FILE, engine='openpyxl') as writer:
            for s_name, s_df in default_sheets.items():
                s_df.to_excel(writer, sheet_name=s_name, index=False)
    else:
        excel_obj = pd.ExcelFile(DB_FILE)
        existing_sheets = excel_obj.sheet_names
        missing_sheets = [s for s in default_sheets.keys() if s not in existing_sheets]
        
        if missing_sheets:
            all_data = {s: pd.read_excel(DB_FILE, sheet_name=s) for s in existing_sheets}
            for ms in missing_sheets:
                all_data[ms] = default_sheets[ms]
            with pd.ExcelWriter(DB_FILE, engine='openpyxl') as writer:
                for s_name, s_df in all_data.items():
                    s_df.to_excel(writer, sheet_name=s_name, index=False)

init_db()

def load_data(sheet):
    init_db()
    return pd.read_excel(DB_FILE, sheet_name=sheet)

def write_sheet(sheet, df):
    excel_obj = pd.ExcelFile(DB_FILE)
    all_sheets = {s_name: (df if s_name == sheet else pd.read_excel(DB_FILE, sheet_name=s_name)) for s_name in excel_obj.sheet_names}
    with pd.ExcelWriter(DB_FILE, engine='openpyxl') as writer:
        for s_name, s_df in all_sheets.items():
            s_df.to_excel(writer, sheet_name=s_name, index=False)

def save_data(sheet, new_df):
    old_df = load_data(sheet)
    updated = pd.concat([old_df, new_df], ignore_index=True)
    write_sheet(sheet, updated)

# -----------------------------------------------------------------------------
# 🧮 런얼라이즈 전용 알고리즘 엔진 (Effective VO2max & Marathon Shape & TRIMP)
# -----------------------------------------------------------------------------
def calculate_runalyze_metrics():
    df_work = load_data("Workouts")
    df_ath = load_data("Athlete")
    
    hr_rest = float(df_ath.iloc[0].get("HRRest", 55)) if not df_ath.empty else 55.0
    hr_max = float(df_ath.iloc[0].get("HRMax", 190)) if not df_ath.empty else 190.0
    
    if df_work.empty:
        return {"effective_vo2max": "-", "marathon_shape": 0, "ctl": 0, "atl": 0, "tsb": 0}
    
    df_work['WorkoutDate'] = pd.to_datetime(df_work['WorkoutDate'])
    df_work = df_work.sort_values('WorkoutDate')
    
    # 1. Effective VO2max (런얼라이즈 방식: 심박 대비 속도 비율)
    eff_vo2max_list = []
    trimp_list = []
    
    for idx, row in df_work.iterrows():
        dist = float(row.get("DistanceKm", 0.0))
        dur = float(row.get("DurationMinutes", 0.0))
        hr = float(row.get("AvgHeartRate", 0.0))
        
        if dur > 0 and dist > 0 and hr > hr_rest:
            speed_mmin = (dist * 1000.0) / dur
            hr_reserve_pct = (hr - hr_rest) / (hr_max - hr_rest)
            
            # 런얼라이즈 Daniels Daniels & Gilbert VO2max 계산 근사식
            vo2 = (-4.60 + 0.182258 * speed_mmin + 0.000104 * (speed_mmin ** 2)) / (0.8 + 0.189439 * np.exp(-0.012778 * dur) + 0.298955 * np.exp(-0.193260 * dur))
            eff_vo2 = vo2 / max(0.5, hr_reserve_pct)
            eff_vo2max_list.append(eff_vo2)
            
            # TRIMP (Training Impulse) 계산
            trimp = dur * hr_reserve_pct * 0.64 * np.exp(1.92 * hr_reserve_pct)
            trimp_list.append(trimp)
        else:
            trimp_list.append(0.0)
            
    df_work['TRIMP'] = trimp_list
    latest_eff_vo2max = np.mean(eff_vo2max_list[-5:]) if eff_vo2max_list else 45.0
    
    # 2. Marathon Shape (%) (런얼라이즈 방식)
    today = datetime.now()
    six_months_ago = today - timedelta(days=180)
    recent_work = df_work[df_work['WorkoutDate'] >= six_months_ago]
    
    weekly_avg_km = recent_work['DistanceKm'].sum() / 26.0 if not recent_work.empty else 0.0
    target_weekly_km = 65.0 # 10K/하프 목표 기본 수치
    marathon_shape = min(100.0, (weekly_avg_km / target_weekly_km) * 100.0)
    
    # 3. TRIMP 피로도 모델 (CTL/ATL/TSB)
    ctl = df_work['TRIMP'].tail(28).mean() if len(df_work) >= 28 else df_work['TRIMP'].mean()
    atl = df_work['TRIMP'].tail(7).mean() if len(df_work) >= 7 else df_work['TRIMP'].mean()
    tsb = ctl - atl
    
    return {
        "effective_vo2max": round(latest_eff_vo2max, 1),
        "marathon_shape": round(marathon_shape, 1),
        "ctl": round(ctl, 1),
        "atl": round(atl, 1),
        "tsb": round(tsb, 1)
    }

# Header UI
col_title, col_view, col_logout = st.columns([3, 2, 1])
with col_title:
    st.markdown("<h1 style='color: #0284c7; margin:0;'>🏃 Running Life OS</h1>", unsafe_allow_html=True)
with col_view:
    view_mode = st.radio("📱💻 View Mode", ["📱 Mobile View", "💻 PC Desktop View"], horizontal=True)
with col_logout:
    if st.button("🔒 Lock"):
        st.session_state["authenticated"] = False
        st.rerun()

menu = st.selectbox(
    "📌 메뉴 이동", 
    [
        "🏠 Dashboard (홈)", 
        "📊 러닝 분석 (Runalyze Engine)", 
        "📅 Dual-Plan 훈련 계획", 
        "🏃 훈련 이력 조회 & 수정", 
        "📝 데이터 상세 입력", 
        "🏁 대회 (Race) 일정 & 기록", 
        "🏆 주요 기록 (PR) & 지표", 
        "📥 Garmin CSV/엑셀 가져오기", 
        "🎯 프로젝트 관리", 
        "👟 신발 자산 & 수명 관리", 
        "🤖 코치 노트",
        "⚙️ DB 백업 및 관리"
    ],
    index=0
)

st.divider()

# -----------------------------------------------------------------------------
# 1. 🏠 Dashboard (홈)
# -----------------------------------------------------------------------------
if menu == "🏠 Dashboard (홈)":
    df_daily = load_data("DailyStatus")
    df_met = load_data("Metrics")
    df_proj = load_data("Projects")
    df_work = load_data("Workouts")
    ra_metrics = calculate_runalyze_metrics()
    
    latest_daily = df_daily.iloc[-1] if not df_daily.empty else {}
    m_latest = df_met.iloc[-1] if not df_met.empty else {}
    active_proj = df_proj[df_proj["Status"] == "ACTIVE"] if not df_proj.empty else pd.DataFrame()

    if view_mode == "📱 Mobile View":
        st.subheader("📱 Today's Mobile Snapshot")
        m1, m2 = st.columns(2)
        m1.metric("Body Battery", latest_daily.get("BodyBattery", "-"))
        m2.metric("Readiness", latest_daily.get("TrainingReadiness", "-"))
        st.caption(f"💙 HRV Status: **{latest_daily.get('HRVStatus', '-')}**")
        st.divider()

        st.subheader("📊 Runalyze Analytics Engine")
        r1, r2 = st.columns(2)
        r1.metric("Effective VO₂max", ra_metrics["effective_vo2max"])
        r2.metric("Marathon Shape", f"{ra_metrics['marathon_shape']}%")
        st.caption(f"📈 Form (TSB): **{ra_metrics['tsb']}** (Fitness: {ra_metrics['ctl']} / Fatigue: {ra_metrics['atl']})")
        st.divider()

        st.subheader("🎯 Active Project")
        if not active_proj.empty:
            p = active_proj.iloc[0]
            st.success(f"**{p['ProjectName']}**\n\n🎯 목표: {p['GoalValue']}\n🗓️ 기한: ~{p.get('TargetDate', '-')}")
        else:
            st.info("등록된 활성 프로젝트가 없습니다.")
        st.divider()

        st.subheader("🏃 Recent Workouts")
        if not df_work.empty:
            for idx, row in df_work.tail(3).iloc[::-1].iterrows():
                st.info(f"**{row['WorkoutDate']} | {row['WorkoutType']}** ({row['DistanceKm']}km / {row['AvgPace']})\n\n💬 {row.get('Notes', '')}")
        else:
            st.caption("기록된 훈련이 없습니다.")

    else:
        st.subheader("💻 PC Master Operations Dashboard")
        pc_col1, pc_col2, pc_col3 = st.columns(3)
        
        with pc_col1:
            st.markdown("<div class='card-title'>🔋 Daily Condition</div>", unsafe_allow_html=True)
            st.metric("Body Battery", latest_daily.get("BodyBattery", "-"))
            st.metric("Training Readiness", latest_daily.get("TrainingReadiness", "-"))
            st.caption(f"HRV: {latest_daily.get('HRVStatus', '-')}")
            
        with pc_col2:
            st.markdown("<div class='card-title'>📊 Runalyze Metrics</div>", unsafe_allow_html=True)
            st.metric("Effective VO₂max", ra_metrics["effective_vo2max"])
            st.metric("Marathon Shape", f"{ra_metrics['marathon_shape']}%")
            st.caption(f"TSB (Form): {ra_metrics['tsb']} | CTL: {ra_metrics['ctl']} | ATL: {ra_metrics['atl']}")
            
        with pc_col3:
            st.markdown("<div class='card-title'>🎯 Active Project</div>", unsafe_allow_html=True)
            if not active_proj.empty:
                p = active_proj.iloc[0]
                st.success(f"**{p['ProjectName']}**\n\n- Goal: {p['GoalValue']}\n- Target Date: {p.get('TargetDate', '-')}")
            else:
                st.info("등록된 활성 프로젝트가 없습니다.")
                
        st.divider()
        st.markdown("<div class='card-title'>📋 Recent Workouts & Analysis Table</div>", unsafe_allow_html=True)
        if not df_work.empty:
            st.dataframe(df_work.tail(10).iloc[::-1], use_container_width=True)
        else:
            st.caption("기록된 운동이 없습니다.")

# -----------------------------------------------------------------------------
# 2. 📊 러닝 분석 (Runalyze Engine)
# -----------------------------------------------------------------------------
elif menu == "📊 러닝 분석 (Runalyze Engine)":
    st.subheader("📊 런얼라이즈(Runalyze) 정밀 분석 대시보드")
    df_work = load_data("Workouts")
    ra_metrics = calculate_runalyze_metrics()
    
    st.markdown("<div class='css-card'>", unsafe_allow_html=True)
    st.markdown("### 🏃 런얼라이즈 독자 유산소 지표")
    rc1, rc2, rc3 = st.columns(3)
    rc1.metric("Effective VO₂max", ra_metrics["effective_vo2max"])
    rc2.metric("Marathon Shape (%)", f"{ra_metrics['marathon_shape']}%")
    rc3.metric("TSB (컨디션 폼)", ra_metrics["tsb"])
    st.markdown("</div>", unsafe_allow_html=True)

    if not df_work.empty:
        df_work['WorkoutDate'] = pd.to_datetime(df_work['WorkoutDate'])
        
        c_chart1, c_chart2 = st.columns(2)
        with c_chart1:
            st.markdown("### 📅 월별 누적 거리 (km)")
            df_work['YearMonth'] = df_work['WorkoutDate'].dt.to_period('M').astype(str)
            st.bar_chart(df_work.groupby('YearMonth')['DistanceKm'].sum())
        with c_chart2:
            st.markdown("### 🏃 훈련 유형별 비중")
            st.bar_chart(df_work.groupby('WorkoutType')['DistanceKm'].sum())
            
        st.divider()
        st.markdown("### 👟 신발 자산별 누적 거리")
        st.bar_chart(df_work.groupby('ShoeID')['DistanceKm'].sum())
    else:
        st.info("통계를 산출할 데이터가 없습니다.")

# -----------------------------------------------------------------------------
# 3~12 메뉴 유지
# -----------------------------------------------------------------------------
elif menu == "📅 Dual-Plan 훈련 계획":
    st.subheader("📅 Garmin vs Copilot AI Dual-Plan 제안")
    df_plans = load_data("TrainingPlans")
    st.dataframe(df_plans, use_container_width=True)
    
    st.divider()
    with st.expander("+ 오늘의 훈련 계획 등록 & 제안 선택"):
        with st.form("dual_plan_form"):
            plan_date = st.date_input("계획 날짜", datetime.now())
            garmin_plan = st.text_input("⌚ Garmin 제안 훈련", "Threshold Run (30분 @ 4:55/km)")
            copilot_plan = st.text_input("🤖 Copilot AI 추천 훈련", "Easy Zone 2 Run (45분 @ 5:50/km) + 스트레칭")
            selected_choice = st.radio("오늘 최종 채택할 훈련 계획 (Choice)", ["GarminPlan (가민 제안)", "CopilotPlan (AI 추천)"])
            
            if st.form_submit_button("오늘의 훈련 계획 결정 저장", use_container_width=True):
                choice_code = "GarminPlan" if "Garmin" in selected_choice else "CopilotPlan"
                save_data("TrainingPlans", pd.DataFrame([{
                    "PlanID": f"PLAN-{datetime.now().strftime('%Y%m%d%H%M')}",
                    "PlanDate": plan_date.strftime("%Y-%m-%d"),
                    "GarminPlan": garmin_plan,
                    "CopilotPlan": copilot_plan,
                    "SelectedPlan": choice_code,
                    "Status": "ADOPTED"
                }]))
                st.success("저장 완료!")
                st.rerun()

elif menu == "🏃 훈련 이력 조회 & 수정":
    st.subheader("🏃 훈련 이력 조회 및 관리")
    df_work = load_data("Workouts")
    df_proj = load_data("Projects")
    df_shoes = load_data("Shoes")
    
    p_list = ["전체 프로젝트 보기"] + (df_proj["ProjectName"].tolist() if not df_proj.empty else [])
    selected_p = st.selectbox("🎯 프로젝트 필터 선택", p_list)
    
    filtered_w = df_work[df_work["ProjectID"] == selected_p] if (selected_p != "전체 프로젝트 보기" and not df_work.empty) else df_work

    if not filtered_w.empty:
        tot_dist = filtered_w["DistanceKm"].sum()
        st.info(f"📊 **{selected_p}** 요약: 총 **{tot_dist:.1f} km** (총 {len(filtered_w)}회 수행)")
        
        with st.expander("✏️ 훈련 기록 수정 / 삭제하기"):
            w_options = [f"{r['WorkoutID']} | {r['WorkoutDate']} | {r['WorkoutType']} ({r['DistanceKm']}km)" for idx, r in filtered_w.iloc[::-1].iterrows()]
            target_w_str = st.selectbox("수정/삭제할 훈련 선택", w_options)
            target_id = target_w_str.split(" | ")[0]
            w_row = df_work[df_work["WorkoutID"] == target_id].iloc[0]
            
            def parse_date(d_val):
                try: return datetime.strptime(str(d_val)[:10], "%Y-%m-%d")
                except: return datetime.now()

            with st.form("edit_workout_form"):
                edit_w_date = st.date_input("운동 날짜", parse_date(w_row["WorkoutDate"]))
                edit_w_proj = st.selectbox("관련 프로젝트", df_proj["ProjectName"].tolist() if not df_proj.empty else ["기본"], index=df_proj["ProjectName"].tolist().index(w_row["ProjectID"]) if w_row["ProjectID"] in df_proj["ProjectName"].tolist() else 0)
                edit_w_type = st.selectbox("운동 유형", ["Easy", "Recovery", "LSD", "Threshold", "Interval", "Sprint", "Race"], index=["Easy", "Recovery", "LSD", "Threshold", "Interval", "Sprint", "Race"].index(w_row["WorkoutType"]) if w_row["WorkoutType"] in ["Easy", "Recovery", "LSD", "Threshold", "Interval", "Sprint", "Race"] else 0)
                
                c1, c2 = st.columns(2)
                edit_dist = c1.number_input("거리 (km)", 0.0, step=0.1, value=float(w_row["DistanceKm"]))
                edit_dur = c1.number_input("시간 (분)", 0.0, step=1.0, value=float(w_row["DurationMinutes"]))
                edit_pace = c2.text_input("평균 페이스", str(w_row["AvgPace"]))
                edit_hr = c2.number_input("평균 심박수", 0, value=int(w_row.get("AvgHeartRate", 145)))
                
                edit_shoe = st.selectbox("착용 신발", df_shoes["ShoeName"].tolist() if not df_shoes.empty else ["기본"], index=df_shoes["ShoeName"].tolist().index(w_row["ShoeID"]) if w_row["ShoeID"] in df_shoes["ShoeName"].tolist() else 0)
                edit_rpe = st.slider("강도 (RPE 1~10)", 1, 10, int(w_row.get("RPE", 5)))
                edit_notes = st.text_area("메모/노트", str(w_row.get("Notes", "")))
                
                col_btn1, col_btn2 = st.columns(2)
                btn_save = col_btn1.form_submit_button("💾 수정사항 저장", use_container_width=True)
                btn_del = col_btn2.form_submit_button("🗑️ 이 훈련 삭제", use_container_width=True)
                
                if btn_save:
                    df_work.loc[df_work["WorkoutID"] == target_id, "WorkoutDate"] = edit_w_date.strftime("%Y-%m-%d")
                    df_work.loc[df_work["WorkoutID"] == target_id, "ProjectID"] = edit_w_proj
                    df_work.loc[df_work["WorkoutID"] == target_id, "WorkoutType"] = edit_w_type
                    df_work.loc[df_work["WorkoutID"] == target_id, "DistanceKm"] = edit_dist
                    df_work.loc[df_work["WorkoutID"] == target_id, "DurationMinutes"] = edit_dur
                    df_work.loc[df_work["WorkoutID"] == target_id, "AvgPace"] = edit_pace
                    df_work.loc[df_work["WorkoutID"] == target_id, "AvgHeartRate"] = edit_hr
                    df_work.loc[df_work["WorkoutID"] == target_id, "ShoeID"] = edit_shoe
                    df_work.loc[df_work["WorkoutID"] == target_id, "RPE"] = edit_rpe
                    df_work.loc[df_work["WorkoutID"] == target_id, "Notes"] = edit_notes
                    write_sheet("Workouts", df_work)
                    st.success("수정 완료!")
                    st.rerun()
                    
                if btn_del:
                    df_work = df_work[df_work["WorkoutID"] != target_id]
                    write_sheet("Workouts", df_work)
                    st.warning("삭제 완료!")
                    st.rerun()

        st.divider()
        st.subheader("📋 훈련 목록")
        if view_mode == "💻 PC Desktop View":
            st.dataframe(filtered_w.iloc[::-1], use_container_width=True)
        else:
            for idx, row in filtered_w.iloc[::-1].iterrows():
                st.markdown(f"**📅 {str(row['WorkoutDate'])[:10]} | {row['WorkoutType']} ({row['ProjectID']})**")
                st.markdown(f"📏 **{row['DistanceKm']}km** ({row['DurationMinutes']}분) | ⏱️ **{row['AvgPace']}** | 👟 {row['ShoeID']}")
                if pd.notnull(row.get('Notes')) and row.get('Notes') != "":
                    st.caption(f"💬 {row['Notes']}")
                st.divider()
    else:
        st.caption("조건에 맞는 훈련 기록이 없습니다.")

elif menu == "📝 데이터 상세 입력":
    tab1, tab2, tab3 = st.tabs(["일일 상태", "운동 기록 (수동)", "Garmin 지표"])
    
    with tab1:
        st.caption("Garmin 아침 컨디션 입력 (3분 소요)")
        with st.form("daily_form"):
            d_date = st.date_input("날짜", datetime.now())
            tr = st.number_input("Readiness (0~100)", 0, 100, 80)
            bb = st.number_input("Body Battery (0~100)", 0, 100, 85)
            hrv = st.selectbox("HRV Status", ["Balanced", "Unbalanced", "Low", "Poor"])
            note = st.text_input("메모")
            if st.form_submit_button("일일 상태 저장", use_container_width=True):
                save_data("DailyStatus", pd.DataFrame([{
                    "StatusID": f"DS-{datetime.now().strftime('%Y%m%d%H%M')}",
                    "StatusDate": d_date, "TrainingReadiness": tr, "BodyBattery": bb, "HRVStatus": hrv, "Notes": note
                }]))
                st.success("저장 완료!")
                st.rerun()

    with tab2:
        df_p = load_data("Projects")
        df_s = load_data("Shoes")
        p_list = df_p["ProjectName"].tolist() if not df_p.empty else ["기본 프로젝트"]
        s_list = df_s["ShoeName"].tolist() if not df_s.empty else ["기본 러닝화"]
        
        with st.form("workout_form"):
            w_date = st.date_input("운동 날짜", datetime.now())
            w_proj = st.selectbox("관련 프로젝트", p_list)
            w_type = st.selectbox("운동 유형", ["Easy", "Recovery", "LSD", "Threshold", "Interval", "Sprint", "Race"])
            
            c1, c2 = st.columns(2)
            dist = c1.number_input("거리 (km)", 0.0, step=0.1, value=5.0)
            dur = c1.number_input("시간 (분)", 0.0, step=1.0, value=30.0)
            pace = c2.text_input("평균 페이스 (예: 5:30)", "5:30")
            hr = c2.number_input("평균 심박수", 0, value=145)
            power = c2.number_input("평균 파워 (W)", 0, value=250)
            temp = c1.number_input("기온 (°C)", -20.0, 50.0, value=20.0)
            
            shoe = st.selectbox("착용 신발 자산", s_list)
            rpe = st.slider("주관적 운동 강도 (RPE 1~10)", 1, 10, 5)
            
            c3, c4 = st.columns(2)
            leg_fatigue = c3.slider("다리 피로도 (1~10)", 1, 10, 3)
            cardio_fatigue = c4.slider("심폐 피로도 (1~10)", 1, 10, 3)
            w_note = st.text_area("Copilot 분석 노트 & 메모")
            
            if st.form_submit_button("상세 운동 기록 저장", use_container_width=True):
                save_data("Workouts", pd.DataFrame([{
                    "WorkoutID": f"WO-{datetime.now().strftime('%Y%m%d%H%M')}",
                    "ProjectID": w_proj, "WorkoutDate": w_date, "WorkoutType": w_type,
                    "DistanceKm": dist, "DurationMinutes": dur, "AvgPace": pace, "AvgHeartRate": hr,
                    "AvgPower": power, "Temperature": temp, "ShoeID": shoe, "RPE": rpe,
                    "LegFatigue": leg_fatigue, "CardioFatigue": cardio_fatigue, "Notes": w_note
                }]))
                st.success("저장 완료!")
                st.rerun()
                
    with tab3:
        with st.form("metric_form"):
            m_date = st.date_input("측정 날짜", datetime.now())
            wt = st.number_input("현재 체중 (kg)", 0.0, step=0.1, value=85.0)
            vo2 = st.number_input("VO₂max", 0.0, step=0.1, value=48.4)
            lt_p = st.text_input("LT Pace (역치 페이스)", "4:58")
            lt_h = st.number_input("LT HR (역치 심박)", 0, value=161)
            lt_pow = st.number_input("LT Power (W)", 0, value=404)
            
            if st.form_submit_button("성능 지표 저장", use_container_width=True):
                save_data("Metrics", pd.DataFrame([{
                    "MetricID": f"MET-{datetime.now().strftime('%Y%m%d%H%M')}",
                    "MetricDate": m_date, "WeightKg": wt, "VO2Max": vo2, "LTPace": lt_p, "LTHR": lt_h, "LTPower": lt_pow
                }]))
                st.success("저장 완료!")
                st.rerun()

elif menu == "🏁 대회 (Race) 일정 & 기록":
    st.subheader("🏁 대회 일정 및 완주 기록 관리")
    df_races = load_data("Races")
    df_shoes = load_data("Shoes")
    df_proj = load_data("Projects")
    
    with st.expander("➕ 새 대회 등록하기"):
        with st.form("add_race_form"):
            rc1, rc2 = st.columns(2)
            r_name = rc1.text_input("대회 이름", "JTBC 서울 마라톤")
            r_dist = rc2.selectbox("대회 종목", ["10km", "Half Marathon", "Full Marathon", "Ultra"])
            
            rc3, rc4 = st.columns(2)
            r_date = rc3.date_input("대회 일자", datetime.now())
            r_status = rc4.selectbox("진행 상태", ["PLANNED (목표 대회)", "COMPLETED (완주)", "DNS/DNF"])
            
            rc5, rc6 = st.columns(2)
            g_time = rc5.text_input("목표 기록 (Goal Time)", "1:50:00")
            a_time = rc6.text_input("실제 달성 기록 (Actual Time)", "-")
            
            r_shoe = st.selectbox("착용 예정/착용 신발", df_shoes["ShoeName"].tolist() if not df_shoes.empty else ["기본 러닝화"])
            r_proj = st.selectbox("관련 프로젝트", df_proj["ProjectName"].tolist() if not df_proj.empty else ["기본 프로젝트"])
            
            if st.form_submit_button("대회 등록 완료", use_container_width=True):
                save_data("Races", pd.DataFrame([{
                    "RaceID": f"RACE-{datetime.now().strftime('%M%S')}",
                    "ProjectID": r_proj, "RaceDate": r_date.strftime("%Y-%m-%d"),
                    "RaceName": r_name, "Distance": r_dist, "GoalTime": g_time,
                    "ActualTime": a_time, "ShoeID": r_shoe, "ResultStatus": r_status.split(" ")[0]
                }]))
                st.success("대회 일정이 등록되었습니다!")
                st.rerun()
                
    st.divider()
    st.dataframe(df_races, use_container_width=True)

elif menu == "🏆 주요 기록 (PR) & 지표":
    st.subheader("🏆 Personal Records (주요 최고 기록)")
    df_pr = load_data("PersonalRecords")
    
    if view_mode == "💻 PC Desktop View":
        cols = st.columns(len(df_pr)) if not df_pr.empty else []
        for idx, row in df_pr.iterrows():
            cols[idx % len(cols)].metric(f"🥇 {row['Category']}", row['TimeOrDist'], f"달성: {row['AchievedDate']}")
    else:
        for idx in range(0, len(df_pr), 2):
            col_a, col_b = st.columns(2)
            row1 = df_pr.iloc[idx]
            col_a.metric(f"🥇 {row1['Category']}", row1['TimeOrDist'], f"달성: {row1['AchievedDate']}")
            if idx + 1 < len(df_pr):
                row2 = df_pr.iloc[idx + 1]
                col_b.metric(f"🥇 {row2['Category']}", row2['TimeOrDist'], f"달성: {row2['AchievedDate']}")
            
    st.divider()
    st.dataframe(df_pr, use_container_width=True)
    
    with st.expander("✏️ 주요 기록 (PR) 업데이트"):
        with st.form("pr_update_form"):
            cat_select = st.selectbox("기록 항목 선택", df_pr["Category"].tolist() if not df_pr.empty else ["1km", "5km", "10km", "Half Marathon", "Full Marathon", "Longest Run"])
            new_val = st.text_input("새 기록 (예: 49:30 또는 30 km)", "")
            new_date = st.date_input("달성 일자", datetime.now())
            new_notes = st.text_input("비고/대회명", "")
            
            if st.form_submit_button("주요 기록 저장", use_container_width=True):
                df_pr.loc[df_pr["Category"] == cat_select, "TimeOrDist"] = new_val
                df_pr.loc[df_pr["Category"] == cat_select, "AchievedDate"] = new_date.strftime("%Y-%m-%d")
                df_pr.loc[df_pr["Category"] == cat_select, "Notes"] = new_notes
                write_sheet("PersonalRecords", df_pr)
                st.success("저장 완료!")
                st.rerun()

elif menu == "📥 Garmin CSV/엑셀 가져오기":
    st.subheader("📥 Garmin 내보내기 파일 자동 등록")
    df_p = load_data("Projects")
    df_s = load_data("Shoes")
    p_list = df_p["ProjectName"].tolist() if not df_p.empty else ["기본 프로젝트"]
    s_list = df_s["ShoeName"].tolist() if not df_s.empty else ["기본 러닝화"]
    
    uploaded_file = st.file_uploader("Garmin 파일 업로드", type=["csv", "xlsx"])
    
    if uploaded_file is not None:
        try:
            df_uploaded = pd.read_csv(uploaded_file) if uploaded_file.name.endswith('.csv') else pd.read_excel(uploaded_file)
            st.success("파일 읽기 성공!")
            st.dataframe(df_uploaded.head(), use_container_width=True)
            
            with st.form("import_confirm_form"):
                def_proj = st.selectbox("관련 프로젝트", p_list)
                def_shoe = st.selectbox("기본 신발", s_list)
                
                if st.form_submit_button("데이터베이스에 자동 등록하기", use_container_width=True):
                    new_rows = []
                    for idx, r in df_uploaded.iterrows():
                        w_date = str(r.get("Date", r.get("날짜", datetime.now().strftime("%Y-%m-%d"))))[:10]
                        dist = float(r.get("Distance", r.get("거리", 0.0)))
                        dur = float(r.get("Time", r.get("시간", 0.0)))
                        pace = str(r.get("Avg Pace", r.get("평균 페이스", "-")))
                        hr = int(r.get("Avg HR", r.get("평균 심박수", 0))) if pd.notnull(r.get("Avg HR", r.get("평균 심박수", 0))) else 0
                        
                        new_rows.append({
                            "WorkoutID": f"WO-IMP-{datetime.now().strftime('%M%S')}-{idx}",
                            "ProjectID": def_proj, "WorkoutDate": w_date, "WorkoutType": "Garmin Import",
                            "DistanceKm": dist, "DurationMinutes": dur, "AvgPace": pace, "AvgHeartRate": hr,
                            "AvgPower": 0, "Temperature": 20, "ShoeID": def_shoe, "RPE": 5,
                            "LegFatigue": 3, "CardioFatigue": 3, "Notes": f"Garmin 파일({uploaded_file.name})에서 가져옴"
                        })
                    
                    save_data("Workouts", pd.DataFrame(new_rows))
                    st.success(f"🎉 총 {len(new_rows)}건 추가 완료!")
                    st.rerun()
        except Exception as e:
            st.error(f"오류 발생: {e}")

elif menu == "🎯 프로젝트 관리":
    st.subheader("🎯 프로젝트 목록 & 수정")
    df_proj = load_data("Projects")
    st.dataframe(df_proj, use_container_width=True)
    
    if not df_proj.empty:
        with st.expander("✏️ 기존 프로젝트 일정 / 정보 수정"):
            selected_proj_id = st.selectbox("수정할 프로젝트 선택", df_proj["ProjectID"].tolist())
            proj_row = df_proj[df_proj["ProjectID"] == selected_proj_id].iloc[0]
            
            def parse_date(d_val):
                try: return datetime.strptime(str(d_val)[:10], "%Y-%m-%d")
                except: return datetime.now()

            start_d_default = parse_date(proj_row.get("StartDate", datetime.now().strftime("%Y-%m-%d")))
            target_d_default = parse_date(proj_row.get("TargetDate", datetime.now().strftime("%Y-%m-%d")))

            with st.form("edit_proj_form"):
                edit_name = st.text_input("프로젝트 이름", proj_row["ProjectName"])
                edit_status = st.selectbox("상태", ["ACTIVE", "PLANNED", "COMPLETED", "CANCELLED"], 
                                           index=["ACTIVE", "PLANNED", "COMPLETED", "CANCELLED"].index(proj_row["Status"]) if proj_row["Status"] in ["ACTIVE", "PLANNED", "COMPLETED", "CANCELLED"] else 0)
                edit_goal = st.text_input("목표 값", proj_row["GoalValue"])
                
                c_s, c_t = st.columns(2)
                edit_start_date = c_s.date_input("시작일 수정", start_d_default)
                edit_target_date = c_t.date_input("목표 완료일 수정", target_d_default)
                edit_desc = st.text_area("설명", proj_row.get("Description", ""))
                
                if st.form_submit_button("프로젝트 수정 내용 저장", use_container_width=True):
                    df_proj.loc[df_proj["ProjectID"] == selected_proj_id, "ProjectName"] = edit_name
                    df_proj.loc[df_proj["ProjectID"] == selected_proj_id, "Status"] = edit_status
                    df_proj.loc[df_proj["ProjectID"] == selected_proj_id, "GoalValue"] = edit_goal
                    df_proj.loc[df_proj["ProjectID"] == selected_proj_id, "StartDate"] = edit_start_date.strftime("%Y-%m-%d")
                    df_proj.loc[df_proj["ProjectID"] == selected_proj_id, "TargetDate"] = edit_target_date.strftime("%Y-%m-%d")
                    df_proj.loc[df_proj["ProjectID"] == selected_proj_id, "Description"] = edit_desc
                    
                    write_sheet("Projects", df_proj)
                    st.success("수정 완료!")
                    st.rerun()

    with st.expander("+ 새 프로젝트 등록"):
        with st.form("proj_add"):
            pn = st.text_input("프로젝트 명")
            stt = st.selectbox("상태", ["PLANNED", "ACTIVE", "COMPLETED"])
            gt = st.selectbox("목표 유형", ["Time Trial", "Distance", "Habit"])
            gv = st.text_input("목표 값", "Half Marathon Sub-1:50")
            s_d = st.date_input("시작일", datetime.now())
            t_d = st.date_input("목표일", datetime.now())
            if st.form_submit_button("프로젝트 생성", use_container_width=True):
                save_data("Projects", pd.DataFrame([{
                    "ProjectID": f"PRJ-{datetime.now().strftime('%M%S')}", "ProjectName": pn,
                    "Status": stt, "GoalType": gt, "GoalValue": gv, 
                    "StartDate": s_d.strftime("%Y-%m-%d"), "TargetDate": t_d.strftime("%Y-%m-%d")
                }]))
                st.success("생성 완료!")
                st.rerun()

elif menu == "👟 신발 자산 & 수명 관리":
    st.subheader("👟 러닝화 자산 및 수명 관리")
    df_shoes = load_data("Shoes")
    df_work = load_data("Workouts")
    
    with st.expander("➕ 새 러닝화 등록하기"):
        with st.form("add_shoe_form"):
            c_s1, c_s2 = st.columns(2)
            s_name = c_s1.text_input("신발 이름", "Nike Zoom Fly 6")
            s_brand = c_s2.text_input("브랜드", "Nike")
            
            c_s3, c_s4 = st.columns(2)
            s_cat = c_s3.selectbox("카테고리", ["Daily Trainer", "Tempo/Speed", "Race/Carbon", "Recovery/Long"])
            s_status = c_s4.selectbox("상태", ["NEW (신규)", "ACTIVE (사용 중)", "RETIRED (은퇴/완료)"])
            
            c_s5, c_s6 = st.columns(2)
            init_dist = c_s5.number_input("기존 달린 거리 (초기 거리 km)", 0.0, step=1.0, value=0.0)
            target_dist = c_s6.number_input("목표 수명 거리 (총 달릴 거리 km)", 100.0, 1500.0, step=50.0, value=600.0)
            
            p_date = st.date_input("구매일", datetime.now())
            
            if st.form_submit_button("신발 등록 완료", use_container_width=True):
                status_code = s_status.split(" ")[0]
                save_data("Shoes", pd.DataFrame([{
                    "ShoeID": f"SHOE-{datetime.now().strftime('%M%S')}",
                    "ShoeName": s_name, "Brand": s_brand, "PurchaseDate": p_date.strftime("%Y-%m-%d"),
                    "InitialDistanceKm": init_dist, "TargetDistanceKm": target_dist,
                    "Status": status_code, "Category": s_cat
                }]))
                st.success("새 러닝화가 등록되었습니다!")
                st.rerun()

    st.divider()

    if not df_shoes.empty:
        st.markdown("### 📊 러닝화 수명 및 상태 현황")
        for idx, shoe in df_shoes.iterrows():
            shoe_id = shoe.get("ShoeName", shoe.get("ShoeID"))
            init_d = float(shoe.get("InitialDistanceKm", 0.0))
            target_d = float(shoe.get("TargetDistanceKm", 600.0))
            status = shoe.get("Status", "ACTIVE")
            
            workout_dist = df_work[df_work["ShoeID"] == shoe_id]["DistanceKm"].sum() if not df_work.empty else 0.0
            total_used_dist = init_d + workout_dist
            usage_pct = min(100.0, (total_used_dist / target_d) * 100.0) if target_d > 0 else 0.0

            with st.container():
                st.markdown("<div class='css-card'>", unsafe_allow_html=True)
                sc1, sc2, sc3 = st.columns([3, 2, 2])
                with sc1:
                    st.markdown(f"#### 👟 **{shoe_id}** ({shoe.get('Brand', '-')})")
                    st.caption(f"카테고리: **{shoe.get('Category', '-')}** | 상태: **{status}**")
                with sc2:
                    st.metric("총 누적 거리", f"{total_used_dist:.1f} km", f"목표: {target_d:.0f} km")
                with sc3:
                    st.metric("수명 사용률", f"{usage_pct:.1f} %")
                
                st.progress(int(usage_pct))
                
                if usage_pct >= 90.0 and status != "RETIRED":
                    st.error("⚠️ 수명이 90% 이상 소진되었습니다. 교체를 검토해 주세요!")
                elif status == "RETIRED":
                    st.info("🏁 사용이 완료되어 은퇴 처리된 신발입니다.")
                st.markdown("</div>", unsafe_allow_html=True)

        st.divider()
        with st.expander("신발 정보 수정하기"):
            selected_shoe_name = st.selectbox("수정할 신발 선택", df_shoes["ShoeName"].tolist())
            shoe_row = df_shoes[df_shoes["ShoeName"] == selected_shoe_name].iloc[0]
            
            with st.form("edit_shoe_form"):
                es_status = st.selectbox("상태 변경", ["NEW", "ACTIVE", "RETIRED"], index=["NEW", "ACTIVE", "RETIRED"].index(shoe_row["Status"]) if shoe_row["Status"] in ["NEW", "ACTIVE", "RETIRED"] else 1)
                es_init = st.number_input("기존 초기 거리 (km)", value=float(shoe_row.get("InitialDistanceKm", 0.0)))
                es_target = st.number_input("목표 수명 거리 (km)", value=float(shoe_row.get("TargetDistanceKm", 600.0)))
                
                if st.form_submit_button("신발 상태 / 목표 수정 저장", use_container_width=True):
                    df_shoes.loc[df_shoes["ShoeName"] == selected_shoe_name, "Status"] = es_status
                    df_shoes.loc[df_shoes["ShoeName"] == selected_shoe_name, "InitialDistanceKm"] = es_init
                    df_shoes.loc[df_shoes["ShoeName"] == selected_shoe_name, "TargetDistanceKm"] = es_target
                    write_sheet("Shoes", df_shoes)
                    st.success("수정 사항이 저장되었습니다!")
                    st.rerun()

elif menu == "🤖 코치 노트":
    st.subheader("🤖 Copilot 코치 노트")
    df_notes = load_data("CoachNotes")
    if not df_notes.empty:
        for idx, row in df_notes.iloc[::-1].iterrows():
            st.info(f"**[{row['NoteDate']}] {row['ProjectID']} ({row['Category']})**\n\n{row['NoteText']}")
    
    with st.expander("+ 코치 노트 추가"):
        df_p = load_data("Projects")
        p_list = df_p["ProjectName"].tolist() if not df_p.empty else ["General"]
        with st.form("note_add"):
            n_proj = st.selectbox("관련 프로젝트", p_list)
            n_cat = st.selectbox("카테고리", ["Weekly", "Monthly", "Review"])
            n_text = st.text_area("Garmin 데이터 해석 및 코치 지침")
            if st.form_submit_button("코치 노트 저장", use_container_width=True):
                save_data("CoachNotes", pd.DataFrame([{
                    "NoteID": f"NOTE-{datetime.now().strftime('%Y%m%d%H%M')}", "ProjectID": n_proj,
                    "NoteDate": datetime.now().strftime('%Y-%m-%d'), "Category": n_cat, "NoteText": n_text
                }]))
                st.success("저장 완료!")
                st.rerun()

elif menu == "⚙️ DB 백업 및 관리":
    st.subheader("⚙️ 시스템 데이터베이스 백업 및 리셋")
    st.markdown("### 📥 DB 백업 다운로드")
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "rb") as f:
            st.download_button(
                label="💾 전체 데이터베이스 (.xlsx) 다운로드",
                data=f,
                file_name=f"Running_Life_OS_Backup_{datetime.now().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
            
    st.divider()
    st.markdown("### 🚨 데이터베이스 초기화")
    if st.button("🚨 데이터베이스 깨끗하게 초기화하기", use_container_width=True):
        init_db(reset=True)
        st.success("데이터베이스가 리셋되었습니다!")
        st.rerun()
