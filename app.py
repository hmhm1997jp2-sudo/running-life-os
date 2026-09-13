import streamlit as st
import pandas as pd
from datetime import datetime
import os

st.set_page_config(page_title="Running Life OS", page_icon="🏃", layout="wide")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "Running Life OS Database.xlsx")

def init_db():
    if not os.path.exists(DB_FILE):
        with pd.ExcelWriter(DB_FILE, engine='openpyxl') as writer:
            pd.DataFrame(columns=["ProjectID", "ProjectName", "Status", "GoalValue"]).to_excel(writer, sheet_name="Projects", index=False)
            pd.DataFrame(columns=["WorkoutDate", "ProjectID", "WorkoutType", "DistanceKm", "DurationMinutes", "AvgPace", "AvgHeartRate", "Notes"]).to_excel(writer, sheet_name="Workouts", index=False)
            pd.DataFrame(columns=["StatusDate", "TrainingReadiness", "BodyBattery", "HRVStatus", "Notes"]).to_excel(writer, sheet_name="DailyStatus", index=False)

init_db()

def load_data(sheet):
    init_db()
    return pd.read_excel(DB_FILE, sheet_name=sheet)

def save_data(sheet, new_df):
    old_df = load_data(sheet)
    updated = pd.concat([old_df, new_df], ignore_index=True)
    with pd.ExcelWriter(DB_FILE, engine='openpyxl', mode='a', if_sheet_exists='replace') as writer:
        updated.to_excel(writer, sheet_name=sheet, index=False)

# 메뉴 구성
st.sidebar.title("🏃 Running Life OS")
menu = st.sidebar.radio("메뉴 선택", ["📱 메인 대시보드", "📝 오늘의 데이터 입력", "🎯 프로젝트 관리"])

# 1. 메인 대시보드
if menu == "📱 메인 대시보드":
    st.title("📊 Running Life OS")
    df_daily = load_data("DailyStatus")
    
    col1, col2, col3 = st.columns(3)
    latest = df_daily.iloc[-1] if not df_daily.empty else {}
    col1.metric("🔋 Body Battery", latest.get("BodyBattery", "-"))
    col2.metric("⚡ Training Readiness", latest.get("TrainingReadiness", "-"))
    col3.metric("💙 HRV Status", latest.get("HRVStatus", "-"))
    
    st.divider()
    st.subheader("🏃 최근 훈련 기록")
    st.dataframe(load_data("Workouts").tail(5), width="stretch")

# 2. 데이터 입력
elif menu == "📝 오늘의 데이터 입력":
    st.title("📝 데이터 입력")
    t1, t2 = st.tabs(["일일 상태 (3분 소요)", "운동 기록 (5분 소요)"])
    
    with t1:
        with st.form("daily_form"):
            d_date = st.date_input("날짜", datetime.now())
            tr = st.number_input("Training Readiness (0~100)", 0, 100, 80)
            bb = st.number_input("Body Battery (0~100)", 0, 100, 85)
            hrv = st.selectbox("HRV", ["Balanced", "Unbalanced", "Low"])
            note = st.text_input("메모")
            if st.form_submit_button("저장하기"):
                save_data("DailyStatus", pd.DataFrame([{"StatusDate": d_date, "TrainingReadiness": tr, "BodyBattery": bb, "HRVStatus": hrv, "Notes": note}]))
                st.success("일일 상태가 저장되었습니다!")

    with t2:
        df_p = load_data("Projects")
        p_list = df_p["ProjectName"].tolist() if not df_p.empty else ["기본 프로젝트"]
        with st.form("workout_form"):
            w_date = st.date_input("운동 날짜", datetime.now())
            w_proj = st.selectbox("관련 프로젝트", p_list)
            w_type = st.selectbox("운동 유형", ["Easy", "LSD", "Threshold", "Interval", "Race"])
            dist = st.number_input("거리 (km)", 0.0, step=0.1, value=5.0)
            dur = st.number_input("시간 (분)", 0.0, step=1.0, value=30.0)
            pace = st.text_input("평균 페이스 (예: 5:30)", "5:30")
            hr = st.number_input("평균 심박수", 0, value=145)
            w_note = st.text_area("Copilot / 코치 메모")
            if st.form_submit_button("훈련 저장하기"):
                save_data("Workouts", pd.DataFrame([{"WorkoutDate": w_date, "ProjectID": w_proj, "WorkoutType": w_type, "DistanceKm": dist, "DurationMinutes": dur, "AvgPace": pace, "AvgHeartRate": hr, "Notes": w_note}]))
                st.success("운동 기록이 저장되었습니다!")

# 3. 프로젝트 관리
elif menu == "🎯 프로젝트 관리":
    st.title("🎯 프로젝트 관리")
    st.dataframe(load_data("Projects"), width="stretch")
    with st.form("proj_form"):
        p_name = st.text_input("프로젝트 이름 (예: Road to 10K 50)")
        p_goal = st.text_input("목표 (예: 10km 49분 진입)")
        if st.form_submit_button("프로젝트 추가"):
            save_data("Projects", pd.DataFrame([{"ProjectID": f"PRJ-{datetime.now().strftime('%M%S')}", "ProjectName": p_name, "Status": "ACTIVE", "GoalValue": p_goal}]))
            st.success("프로젝트가 생성되었습니다!")