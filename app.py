import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import os

st.set_page_config(page_title="Running Life OS", page_icon="🏃", layout="wide", initial_sidebar_state="collapsed")

# 🎨 Custom CSS (토스/애플 라이크 모던 카드 UI)
st.markdown("""
    <style>
    /* 전체 메인 배경 및 가독성 최적화 */
    .main {
        background-color: #f8fafc;
    }
    /* 카드 디자인 */
    .css-card {
        background-color: #ffffff;
        border-radius: 16px;
        padding: 22px;
        margin-bottom: 20px;
        border: 1px solid #e2e8f0;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.03);
    }
    /* 탭 스타일링 */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background-color: #e2e8f0;
        padding: 6px;
        border-radius: 12px;
    }
    .stTabs [data-baseweb="tab"] {
        height: 44px;
        border-radius: 8px;
        font-weight: 600;
        color: #475569;
    }
    .stTabs [aria-selected="true"] {
        background-color: #ffffff !important;
        color: #0284c7 !important;
        box-shadow: 0 2px 6px rgba(0,0,0,0.05);
    }
    /* 메트릭 폰트 커스텀 */
    div[data-testid="stMetricValue"] {
        font-size: 1.8rem !important;
        font-weight: 700 !important;
        color: #0284c7 !important;
    }
    div[data-testid="stMetricLabel"] {
        font-size: 0.88rem !important;
        color: #64748b !important;
        font-weight: 600 !important;
    }
    /* 버튼 커스텀 */
    .stButton>button {
        border-radius: 10px !important;
        background-color: #0284c7 !important;
        color: white !important;
        font-weight: 600 !important;
        border: none !important;
        padding: 0.5rem 1rem !important;
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
# 🧮 런얼라이즈 계산 엔진
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
    
    eff_vo2max_list, trimp_list = [], []
    for idx, row in df_work.iterrows():
        dist = float(row.get("DistanceKm", 0.0))
        dur = float(row.get("DurationMinutes", 0.0))
        hr = float(row.get("AvgHeartRate", 0.0))
        
        if dur > 0 and dist > 0 and hr > hr_rest:
            speed_mmin = (dist * 1000.0) / dur
            hr_reserve_pct = (hr - hr_rest) / (hr_max - hr_rest)
            vo2 = (-4.60 + 0.182258 * speed_mmin + 0.000104 * (speed_mmin ** 2)) / (0.8 + 0.189439 * np.exp(-0.012778 * dur) + 0.298955 * np.exp(-0.193260 * dur))
            eff_vo2 = vo2 / max(0.5, hr_reserve_pct)
            eff_vo2max_list.append(eff_vo2)
            trimp_list.append(dur * hr_reserve_pct * 0.64 * np.exp(1.92 * hr_reserve_pct))
        else:
            trimp_list.append(0.0)
            
    df_work['TRIMP'] = trimp_list
    latest_eff_vo2max = np.mean(eff_vo2max_list[-5:]) if eff_vo2max_list else 45.0
    
    today = datetime.now()
    recent_work = df_work[df_work['WorkoutDate'] >= (today - timedelta(days=180))]
    weekly_avg_km = recent_work['DistanceKm'].sum() / 26.0 if not recent_work.empty else 0.0
    marathon_shape = min(100.0, (weekly_avg_km / 65.0) * 100.0)
    
    ctl = df_work['TRIMP'].tail(28).mean() if len(df_work) >= 28 else df_work['TRIMP'].mean()
    atl = df_work['TRIMP'].tail(7).mean() if len(df_work) >= 7 else df_work['TRIMP'].mean()
    
    return {
        "effective_vo2max": round(latest_eff_vo2max, 1),
        "marathon_shape": round(marathon_shape, 1),
        "ctl": round(ctl, 1), "atl": round(atl, 1), "tsb": round(ctl - atl, 1)
    }

# 헤더 UI
col_title, col_logout = st.columns([4, 1])
with col_title:
    st.markdown("<h2 style='color: #0284c7; margin:0;'>🏃 Running Life OS</h2>", unsafe_allow_html=True)
with col_logout:
    if st.button("🔒 Lock", use_container_width=True):
        st.session_state["authenticated"] = False
        st.rerun()

st.caption("개인 맞춤형 모던 러닝 분석 & 자산 관리 시스템")

# 📌 핵심 4대 메인 탭 구조
tab_dash, tab_work, tab_goals, tab_admin = st.tabs([
    "🏠 대시보드", 
    "🏃 훈련 & 리포트", 
    "🎯 목표 & 자산", 
    "⚙️ 관리 & 코치"
])

# -----------------------------------------------------------------------------
# TAB 1: 🏠 대시보드 (Dashboard)
# -----------------------------------------------------------------------------
with tab_dash:
    df_daily = load_data("DailyStatus")
    df_proj = load_data("Projects")
    df_work = load_data("Workouts")
    ra_metrics = calculate_runalyze_metrics()
    
    latest_daily = df_daily.iloc[-1] if not df_daily.empty else {}
    active_proj = df_proj[df_proj["Status"] == "ACTIVE"] if not df_proj.empty else pd.DataFrame()

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("<div class='css-card'>", unsafe_allow_html=True)
        st.markdown("#### 🔋 Today's Condition")
        st.metric("Body Battery", latest_daily.get("BodyBattery", "-"))
        st.metric("Training Readiness", latest_daily.get("TrainingReadiness", "-"))
        st.caption(f"HRV Status: **{latest_daily.get('HRVStatus', '-')}**")
        st.markdown("</div>", unsafe_allow_html=True)

    with c2:
        st.markdown("<div class='css-card'>", unsafe_allow_html=True)
        st.markdown("#### 📊 Runalyze Analytics")
        st.metric("Effective VO₂max", ra_metrics["effective_vo2max"])
        st.metric("Marathon Shape", f"{ra_metrics['marathon_shape']}%")
        st.caption(f"TSB (Form): **{ra_metrics['tsb']}** (Fitness: {ra_metrics['ctl']} / Fatigue: {ra_metrics['atl']})")
        st.markdown("</div>", unsafe_allow_html=True)

    with c3:
        st.markdown("<div class='css-card'>", unsafe_allow_html=True)
        st.markdown("#### 🎯 Active Project")
        if not active_proj.empty:
            p = active_proj.iloc[0]
            st.success(f"**{p['ProjectName']}**\n\n🎯 목표: {p['GoalValue']}\n🗓️ 기한: ~{p.get('TargetDate', '-')}")
        else:
            st.info("등록된 활성 프로젝트가 없습니다.")
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div class='css-card'>", unsafe_allow_html=True)
    st.markdown("#### 📋 최근 훈련 목록 (Recent Workouts)")
    if not df_work.empty:
        st.dataframe(df_work.tail(5).iloc[::-1], use_container_width=True)
    else:
        st.caption("기록된 운동이 없습니다.")
    st.markdown("</div>", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# TAB 2: 🏃 훈련 & 리포트 (Workouts & Analytics)
# -----------------------------------------------------------------------------
with tab_work:
    sub_w1, sub_w2, sub_w3 = st.tabs(["📋 훈련 이력 & 수정", "📊 통계 차트", "📥 Garmin CSV 연동"])
    
    with sub_w1:
        df_work = load_data("Workouts")
        df_proj = load_data("Projects")
        df_shoes = load_data("Shoes")
        
        p_list = ["전체 프로젝트 보기"] + (df_proj["ProjectName"].tolist() if not df_proj.empty else [])
        selected_p = st.selectbox("🎯 프로젝트 필터", p_list)
        filtered_w = df_work[df_work["ProjectID"] == selected_p] if (selected_p != "전체 프로젝트 보기" and not df_work.empty) else df_work

        if not filtered_w.empty:
            st.info(f"📊 총 **{filtered_w['DistanceKm'].sum():.1f} km** 달림 (총 {len(filtered_w)}회)")
            with st.expander("✏️ 훈련 기록 수정 / 삭제"):
                w_options = [f"{r['WorkoutID']} | {r['WorkoutDate']} | {r['WorkoutType']} ({r['DistanceKm']}km)" for idx, r in filtered_w.iloc[::-1].iterrows()]
                target_w_str = st.selectbox("수정 대상 선택", w_options)
                target_id = target_w_str.split(" | ")[0]
                w_row = df_work[df_work["WorkoutID"] == target_id].iloc[0]
                
                with st.form("edit_w_form"):
                    e_date = st.date_input("날짜", datetime.strptime(str(w_row["WorkoutDate"])[:10], "%Y-%m-%d"))
                    e_type = st.selectbox("유형", ["Easy", "Recovery", "LSD", "Threshold", "Interval", "Sprint", "Race"])
                    e_dist = st.number_input("거리(km)", value=float(w_row["DistanceKm"]))
                    e_dur = st.number_input("시간(분)", value=float(w_row["DurationMinutes"]))
                    e_pace = st.text_input("페이스", str(w_row["AvgPace"]))
                    e_notes = st.text_area("메모", str(w_row.get("Notes", "")))
                    
                    b_save, b_del = st.columns(2)
                    if b_save.form_submit_button("💾 저장", use_container_width=True):
                        df_work.loc[df_work["WorkoutID"] == target_id, ["WorkoutDate", "WorkoutType", "DistanceKm", "DurationMinutes", "AvgPace", "Notes"]] = [e_date.strftime("%Y-%m-%d"), e_type, e_dist, e_dur, e_pace, e_notes]
                        write_sheet("Workouts", df_work)
                        st.success("수정 완료!")
                        st.rerun()
                    if b_del.form_submit_button("🗑️ 삭제", use_container_width=True):
                        df_work = df_work[df_work["WorkoutID"] != target_id]
                        write_sheet("Workouts", df_work)
                        st.warning("삭제 완료!")
                        st.rerun()

            st.dataframe(filtered_w.iloc[::-1], use_container_width=True)
        else:
            st.caption("기록된 훈련이 없습니다.")

    with sub_w2:
        df_work = load_data("Workouts")
        if not df_work.empty:
            df_work['WorkoutDate'] = pd.to_datetime(df_work['WorkoutDate'])
            ch1, ch2 = st.columns(2)
            with ch1:
                st.markdown("### 📅 월별 누적 거리 (km)")
                df_work['YearMonth'] = df_work['WorkoutDate'].dt.to_period('M').astype(str)
                st.bar_chart(df_work.groupby('YearMonth')['DistanceKm'].sum())
            with ch2:
                st.markdown("### 🏃 훈련 유형별 비중")
                st.bar_chart(df_work.groupby('WorkoutType')['DistanceKm'].sum())
        else:
            st.info("분석할 데이터가 없습니다.")

    with sub_w3:
        st.subheader("📥 Garmin 파일 자동 가져오기")
        uploaded_file = st.file_uploader("Garmin CSV/XLSX 업로드", type=["csv", "xlsx"])
        if uploaded_file is not None:
            df_up = pd.read_csv(uploaded_file) if uploaded_file.name.endswith('.csv') else pd.read_excel(uploaded_file)
            st.dataframe(df_up.head(), use_container_width=True)
            if st.button("데이터베이스에 자동 연동 저장", use_container_width=True):
                new_rows = []
                for idx, r in df_up.iterrows():
                    new_rows.append({
                        "WorkoutID": f"WO-IMP-{datetime.now().strftime('%M%S')}-{idx}",
                        "ProjectID": "Default", "WorkoutDate": str(r.get("Date", r.get("날짜", datetime.now().strftime("%Y-%m-%d"))))[:10],
                        "WorkoutType": "Garmin Import", "DistanceKm": float(r.get("Distance", r.get("거리", 0.0))),
                        "DurationMinutes": float(r.get("Time", r.get("시간", 0.0))), "AvgPace": str(r.get("Avg Pace", "-")),
                        "AvgHeartRate": int(r.get("Avg HR", 0)) if pd.notnull(r.get("Avg HR")) else 0, "Notes": "Garmin 가져옴"
                    })
                save_data("Workouts", pd.DataFrame(new_rows))
                st.success("🎉 가져오기 완료!")
                st.rerun()

# -----------------------------------------------------------------------------
# TAB 3: 🎯 목표 & 자산 (Goals & Shoes)
# -----------------------------------------------------------------------------
with tab_goals:
    sub_g1, sub_g2, sub_g3, sub_g4 = st.tabs(["🎯 프로젝트", "👟 러닝화 수명", "🏁 대회 일정", "🏆 PR 기록"])
    
    with sub_g1:
        df_proj = load_data("Projects")
        st.dataframe(df_proj, use_container_width=True)
        with st.expander("+ 새 프로젝트 등록"):
            with st.form("add_p_form"):
                pn = st.text_input("프로젝트 명", "Road to 10K Sub-50")
                gv = st.text_input("목표 값", "10km 49:59")
                sd = st.date_input("시작일", datetime.now())
                td = st.date_input("목표일", datetime.now() + timedelta(days=90))
                if st.form_submit_button("프로젝트 생성", use_container_width=True):
                    save_data("Projects", pd.DataFrame([{"ProjectID": f"PRJ-{datetime.now().strftime('%M%S')}", "ProjectName": pn, "Status": "ACTIVE", "GoalType": "Time Trial", "GoalValue": gv, "StartDate": sd, "TargetDate": td}]))
                    st.success("생성 완료!")
                    st.rerun()

    with sub_g2:
        df_shoes = load_data("Shoes")
        df_work = load_data("Workouts")
        with st.expander("➕ 새 러닝화 등록"):
            with st.form("add_s_form"):
                sn = st.text_input("신발 이름", "Nike Zoom Fly 6")
                sb = st.text_input("브랜드", "Nike")
                init_d = st.number_input("기존 초기 거리 (km)", value=0.0)
                target_d = st.number_input("목표 수명 거리 (km)", value=600.0)
                if st.form_submit_button("러닝화 등록", use_container_width=True):
                    save_data("Shoes", pd.DataFrame([{"ShoeID": f"SHOE-{datetime.now().strftime('%M%S')}", "ShoeName": sn, "Brand": sb, "PurchaseDate": datetime.now().strftime("%Y-%m-%d"), "InitialDistanceKm": init_d, "TargetDistanceKm": target_d, "Status": "ACTIVE", "Category": "Daily"}]))
                    st.success("등록 완료!")
                    st.rerun()
        
        st.divider()
        if not df_shoes.empty:
            for idx, shoe in df_shoes.iterrows():
                s_name = shoe.get("ShoeName", shoe.get("ShoeID"))
                i_dist = float(shoe.get("InitialDistanceKm", 0.0))
                t_dist = float(shoe.get("TargetDistanceKm", 600.0))
                w_dist = df_work[df_work["ShoeID"] == s_name]["DistanceKm"].sum() if not df_work.empty else 0.0
                tot_d = i_dist + w_dist
                pct = min(100.0, (tot_d / t_dist) * 100.0) if t_dist > 0 else 0.0
                
                st.markdown("<div class='css-card'>", unsafe_allow_html=True)
                sc1, sc2 = st.columns([3, 1])
                sc1.markdown(f"#### 👟 **{s_name}** ({shoe.get('Brand', '-')})")
                sc2.metric("수명 진도율", f"{pct:.1f}%", f"{tot_d:.1f}/{t_dist:.0f} km")
                st.progress(int(pct))
                st.markdown("</div>", unsafe_allow_html=True)

    with sub_g3:
        df_races = load_data("Races")
        st.dataframe(df_races, use_container_width=True)
        with st.expander("➕ 대회 등록"):
            with st.form("add_r_form"):
                rn = st.text_input("대회명")
                rd = st.selectbox("종목", ["10km", "Half Marathon", "Full Marathon"])
                rdate = st.date_input("대회 날짜", datetime.now())
                if st.form_submit_button("대회 저장", use_container_width=True):
                    save_data("Races", pd.DataFrame([{"RaceID": f"RACE-{datetime.now().strftime('%M%S')}", "ProjectID": "Default", "RaceDate": rdate, "RaceName": rn, "Distance": rd, "GoalTime": "-", "ActualTime": "-", "ShoeID": "-", "ResultStatus": "PLANNED"}]))
                    st.success("대회 등록 완료!")
                    st.rerun()

    with sub_g4:
        df_pr = load_data("PersonalRecords")
        st.dataframe(df_pr, use_container_width=True)

# -----------------------------------------------------------------------------
# TAB 4: ⚙️ 관리 & 코치 (Admin & Notes)
# -----------------------------------------------------------------------------
with tab_admin:
    sub_a1, sub_a2, sub_a3 = st.tabs(["📝 수동 데이터 입력", "🤖 코치 노트", "💾 DB 백업 및 초기화"])
    
    with sub_a1:
        st.markdown("### 📝 데일리 컨디션 & 훈련 입력")
        with st.form("daily_input_form"):
            d_d = st.date_input("날짜", datetime.now())
            tr = st.number_input("Readiness (0~100)", 0, 100, 80)
            bb = st.number_input("Body Battery (0~100)", 0, 100, 85)
            hrv = st.selectbox("HRV Status", ["Balanced", "Unbalanced", "Low", "Poor"])
            if st.form_submit_button("컨디션 기록 저장", use_container_width=True):
                save_data("DailyStatus", pd.DataFrame([{"StatusID": f"DS-{datetime.now().strftime('%M%S')}", "StatusDate": d_d, "TrainingReadiness": tr, "BodyBattery": bb, "HRVStatus": hrv, "Notes": ""}]))
                st.success("저장 완료!")
                st.rerun()

    with sub_a2:
        df_notes = load_data("CoachNotes")
        if not df_notes.empty:
            for idx, row in df_notes.iloc[::-1].iterrows():
                st.info(f"**[{row['NoteDate']}] ({row['Category']})**\n\n{row['NoteText']}")
        with st.expander("+ 코치 노트 작성"):
            with st.form("note_form"):
                nt = st.text_area("Garmin/Runalyze 데이터 분석 지침 및 총평")
                if st.form_submit_button("노트 저장", use_container_width=True):
                    save_data("CoachNotes", pd.DataFrame([{"NoteID": f"NOTE-{datetime.now().strftime('%M%S')}", "ProjectID": "General", "NoteDate": datetime.now().strftime("%Y-%m-%d"), "Category": "Weekly", "NoteText": nt}]))
                    st.success("저장 완료!")
                    st.rerun()

    with sub_a3:
        st.markdown("### 📥 DB 백업")
        if os.path.exists(DB_FILE):
            with open(DB_FILE, "rb") as f:
                st.download_button("💾 전체 데이터 (.xlsx) 백업 다운로드", f, file_name=f"Running_Life_OS_Backup_{datetime.now().strftime('%Y%m%d')}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
        st.divider()
        st.markdown("### 🚨 DB 리셋")
        if st.button("🚨 데이터베이스 초기화", use_container_width=True):
            init_db(reset=True)
            st.success("리셋 완료!")
            st.rerun()
