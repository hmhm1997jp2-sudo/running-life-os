import streamlit as st
import pandas as pd
from datetime import datetime
from streamlit_gsheets import GSheetsConnection

st.set_page_config(page_title="Running Life OS", page_icon="🏃", layout="wide", initial_sidebar_state="collapsed")

# 🔒 보안 처리
def check_password():
    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False
    if st.session_state["authenticated"]:
        return True

    st.title("🔒 Running Life OS Access Control")
    st.caption("개인 보호용 Running Life OS 시스템입니다. 비밀번호를 입력하세요.")
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

# -----------------------------------------------------------------------------
# 📊 Google Sheets 실시간 연동 파이프라인 (데이터 영구 보전)
# -----------------------------------------------------------------------------
def get_connection():
    # Secrets에 등록된 GSHEETS_URL 연결
    return st.connection("gsheets", type=GSheetsConnection)

def load_data(sheet_name):
    conn = get_connection()
    try:
        url = st.secrets.get("GSHEETS_URL", "")
        df = conn.read(spreadsheet=url, worksheet=sheet_name, ttl="0s")
        return df.dropna(how="all") if df is not None else pd.DataFrame()
    except Exception:
        return pd.DataFrame()

def save_data(sheet_name, new_df):
    conn = get_connection()
    url = st.secrets.get("GSHEETS_URL", "")
    old_df = load_data(sheet_name)
    updated = pd.concat([old_df, new_df], ignore_index=True)
    conn.update(spreadsheet=url, worksheet=sheet_name, data=updated)
    st.cache_data.clear()

def write_sheet(sheet_name, full_df):
    conn = get_connection()
    url = st.secrets.get("GSHEETS_URL", "")
    conn.update(spreadsheet=url, worksheet=sheet_name, data=full_df)
    st.cache_data.clear()

# 상단 헤더 & 접속 모드 제어
col_title, col_view, col_logout = st.columns([3, 2, 1])
with col_title:
    st.title("🏃 Running Life OS")
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
        "📊 러닝 통계 분석", 
        "📅 Dual-Plan 훈련 계획", 
        "🏃 훈련 이력 조회 & 수정", 
        "📝 데이터 상세 입력", 
        "🏆 주요 기록 (PR) & 지표", 
        "📥 Garmin CSV/엑셀 가져오기", 
        "🎯 프로젝트 관리", 
        "👟 신발 관리 & 이력", 
        "🤖 코치 노트"
    ],
    index=0
)

st.divider()

# -----------------------------------------------------------------------------
# 1. 🏠 Dashboard (모바일 뷰 vs PC 뷰 분리 레이아웃)
# -----------------------------------------------------------------------------
if menu == "🏠 Dashboard (홈)":
    df_daily = load_data("DailyStatus")
    df_met = load_data("Metrics")
    df_proj = load_data("Projects")
    df_work = load_data("Workouts")
    
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

        st.subheader("⚡ Performance Metrics")
        st.markdown(f"🏃 **VO₂max**: `{m_latest.get('VO2Max', '-')}` | **LT Pace**: `{m_latest.get('LTPace', '-')}`")
        st.markdown(f"💙 **LT HR**: `{m_latest.get('LTHR', '-')} bpm` | ⚡ **LT Power**: `{m_latest.get('LTPower', '-')}W`")
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
            st.markdown("#### 🔋 Daily Condition")
            st.metric("Body Battery", latest_daily.get("BodyBattery", "-"))
            st.metric("Training Readiness", latest_daily.get("TrainingReadiness", "-"))
            st.caption(f"HRV: {latest_daily.get('HRVStatus', '-')}")
            
        with pc_col2:
            st.markdown("#### ⚡ Performance Thresholds")
            st.metric("VO₂max", f"{m_latest.get('VO2Max', '-')}")
            st.metric("LT Pace / HR", f"{m_latest.get('LTPace', '-')} / {m_latest.get('LTHR', '-')}bpm")
            st.caption(f"Power: {m_latest.get('LTPower', '-')}W | Weight: {m_latest.get('WeightKg', '-')}kg")
            
        with pc_col3:
            st.markdown("#### 🎯 Active Project")
            if not active_proj.empty:
                p = active_proj.iloc[0]
                st.success(f"**{p['ProjectName']}**\n\n- Goal: {p['GoalValue']}\n- Target Date: {p.get('TargetDate', '-')}")
            else:
                st.info("No active project.")
                
        st.divider()
        st.markdown("#### 📋 Recent Workouts & Analysis Table")
        if not df_work.empty:
            st.dataframe(df_work.tail(10).iloc[::-1], use_container_width=True)
        else:
            st.caption("기록된 운동이 없습니다.")

# -----------------------------------------------------------------------------
# 2. 📊 러닝 통계 분석
# -----------------------------------------------------------------------------
elif menu == "📊 러닝 통계 분석":
    st.subheader("📊 러닝 통계 및 시각화 리포트")
    df_work = load_data("Workouts")
    
    if not df_work.empty:
        df_work['WorkoutDate'] = pd.to_datetime(df_work['WorkoutDate'])
        
        if view_mode == "💻 PC Desktop View":
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
            st.markdown("### 📅 월별 누적 거리 (km)")
            df_work['YearMonth'] = df_work['WorkoutDate'].dt.to_period('M').astype(str)
            st.bar_chart(df_work.groupby('YearMonth')['DistanceKm'].sum())
            st.divider()
            st.markdown("### 🏃 훈련 유형별 비중")
            st.bar_chart(df_work.groupby('WorkoutType')['DistanceKm'].sum())
            st.divider()
            st.markdown("### 👟 신발 자산별 누적 거리")
            st.bar_chart(df_work.groupby('ShoeID')['DistanceKm'].sum())
    else:
        st.info("통계를 산출할 데이터가 없습니다.")

# -----------------------------------------------------------------------------
# 3. 📅 Dual-Plan 훈련 계획
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
                st.success("구글 시트에 성공적으로 동기화되었습니다!")
                st.rerun()

# -----------------------------------------------------------------------------
# 4. 🏃 훈련 이력 조회 & 수정
# -----------------------------------------------------------------------------
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
                    st.success("구글 시트에 수정사항이 반영되었습니다!")
                    st.rerun()
                    
                if btn_del:
                    df_work = df_work[df_work["WorkoutID"] != target_id]
                    write_sheet("Workouts", df_work)
                    st.warning("훈련 삭제 완료!")
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

# -----------------------------------------------------------------------------
# 5. 📝 데이터 상세 입력
# -----------------------------------------------------------------------------
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
                st.success("구글 시트에 영구 저장 완료!")
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
                st.success("구글 시트에 저장 완료!")
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

# -----------------------------------------------------------------------------
# 6. 🏆 주요 기록 (PR) & 지표
# -----------------------------------------------------------------------------
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

# -----------------------------------------------------------------------------
# 7. 📥 Garmin CSV/엑셀 가져오기
# -----------------------------------------------------------------------------
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
                    st.success(f"🎉 총 {len(new_rows)}건 구글 시트에 자동 추가 완료!")
                    st.rerun()
        except Exception as e:
            st.error(f"오류 발생: {e}")

# -----------------------------------------------------------------------------
# 8. 🎯 프로젝트 관리
# -----------------------------------------------------------------------------
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

# -----------------------------------------------------------------------------
# 9. 👟 신발 관리 & 이력
# -----------------------------------------------------------------------------
elif menu == "👟 신발 관리 & 이력":
    st.subheader("👟 신발 자산 & 훈련 이력")
    df_shoes = load_data("Shoes")
    df_work = load_data("Workouts")
    st.dataframe(df_shoes, use_container_width=True)
    
    st.divider()
    st.subheader("🔍 신발별 수행 훈련 보기")
    if not df_shoes.empty:
        selected_shoe = st.selectbox("조회할 신발 선택", df_shoes["ShoeName"].tolist())
        filtered_workouts = df_work[df_work["ShoeID"] == selected_shoe] if not df_work.empty else pd.DataFrame()
        calc_dist = filtered_workouts["DistanceKm"].sum() if not filtered_workouts.empty else 0.0
        st.info(f"👟 **{selected_shoe}** 총 훈련 거리: **{calc_dist:.1f} km** ({len(filtered_workouts)}회 수행)")
        
        if not filtered_workouts.empty:
            if view_mode == "💻 PC Desktop View":
                st.dataframe(filtered_workouts, use_container_width=True)
            else:
                for idx, r in filtered_workouts.iloc[::-1].iterrows():
                    st.write(f"🏃 **{str(r['WorkoutDate'])[:10]}** | {r['WorkoutType']} | **{r['DistanceKm']}km** (페이스: {r['AvgPace']})")
                    if pd.notnull(r.get('Notes')) and r.get('Notes') != "":
                        st.caption(f"💬 {r['Notes']}")
                    st.divider()
        else:
            st.caption("해당 신발로 기록된 훈련이 없습니다.")

# -----------------------------------------------------------------------------
# 10. 🤖 코치 노트
# -----------------------------------------------------------------------------
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
