import streamlit as st
import pandas as pd
from datetime import datetime
import os

# 모바일 기본 레이아웃 설정
st.set_page_config(page_title="Running Life OS", page_icon="🏃", layout="centered", initial_sidebar_state="collapsed")

# -----------------------------------------------------------------------------
# 🔒 보안 처리: Streamlit Cloud Secrets 기반 비밀번호 인증
# -----------------------------------------------------------------------------
def check_password():
    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False

    if st.session_state["authenticated"]:
        return True

    st.title("🔒 Running Life OS Access Control")
    st.caption("본 시스템은 개인 보호용 시스템입니다. 비밀번호를 입력하세요.")
    
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
# 🏃 메인 시스템 구동
# -----------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "Running Life OS Database.xlsx")

# 필수 시트가 누락되어 있을 경우 기존 DB를 완전한 릴리즈 스펙으로 초기화하는 함수
def init_db(force_reset=False):
    required_sheets = ["Athlete", "Projects", "Workouts", "DailyStatus", "Metrics", "Shoes", "Races", "CoachNotes"]
    
    need_init = False
    if not os.path.exists(DB_FILE) or force_reset:
        need_init = True
    else:
        # 기존 파일이 있더라도 필수 시트가 빠져있으면 재정의
        try:
            excel_obj = pd.ExcelFile(DB_FILE)
            if not all(sheet in excel_obj.sheet_names for sheet in required_sheets):
                need_init = True
        except Exception:
            need_init = True

    if need_init:
        with pd.ExcelWriter(DB_FILE, engine='openpyxl') as writer:
            pd.DataFrame([{"AthleteID": "ATH-001", "BirthDate": "1997-10-28", "HeightCm": 180, "CurrentWeightKg": 85.0, "StartWeightKg": 115.0}]).to_excel(writer, sheet_name="Athlete", index=False)
            pd.DataFrame([{"ProjectID": "PRJ-001", "ProjectName": "Road to 10K 50", "Status": "ACTIVE", "GoalType": "Time Trial", "GoalValue": "10km Sub-50", "StartDate": "2026-09-01", "TargetDate": "2026-11-30"}]).to_excel(writer, sheet_name="Projects", index=False)
            pd.DataFrame(columns=["WorkoutID", "ProjectID", "WorkoutDate", "WorkoutType", "DistanceKm", "DurationMinutes", "AvgPace", "AvgHeartRate", "ShoeID", "RPE", "Notes"]).to_excel(writer, sheet_name="Workouts", index=False)
            pd.DataFrame(columns=["StatusID", "StatusDate", "TrainingReadiness", "BodyBattery", "HRVStatus", "Notes"]).to_excel(writer, sheet_name="DailyStatus", index=False)
            pd.DataFrame([{"MetricID": "MET-001", "MetricDate": "2026-09-13", "WeightKg": 85.0, "VO2Max": 48.4, "LTPace": "4:58", "LTHR": 161, "LTPower": 404}]).to_excel(writer, sheet_name="Metrics", index=False)
            pd.DataFrame([
                {"ShoeID": "SHOE-001", "ShoeName": "Nike Zoom Fly 6", "Brand": "Nike", "DistanceKm": 120.5, "Status": "ACTIVE"},
                {"ShoeID": "SHOE-002", "ShoeName": "Saucony Ride 19", "Brand": "Saucony", "DistanceKm": 210.0, "Status": "ACTIVE"},
                {"ShoeID": "SHOE-003", "ShoeName": "Saucony Triumph 23", "Brand": "Saucony", "DistanceKm": 85.0, "Status": "ACTIVE"}
            ]).to_excel(writer, sheet_name="Shoes", index=False)
            pd.DataFrame(columns=["RaceID", "ProjectID", "RaceDate", "RaceName", "Distance", "GoalTime", "ActualTime", "ResultStatus"]).to_excel(writer, sheet_name="Races", index=False)
            pd.DataFrame([{"NoteID": "NOTE-001", "ProjectID": "Road to 10K 50", "NoteDate": "2026-09-13", "Category": "Weekly", "NoteText": "Garmin VO2max 48.4 유지 중. 유산소 기반 양호."}]).to_excel(writer, sheet_name="CoachNotes", index=False)

init_db()

def load_data(sheet):
    init_db()
    return pd.read_excel(DB_FILE, sheet_name=sheet)

def save_data(sheet, new_df):
    old_df = load_data(sheet)
    updated = pd.concat([old_df, new_df], ignore_index=True)
    with pd.ExcelWriter(DB_FILE, engine='openpyxl', mode='a', if_sheet_exists='replace') as writer:
        updated.to_excel(writer, sheet_name=sheet, index=False)

# 상단 헤더 및 잠금 버튼
col_title, col_logout = st.columns([3, 1])
with col_title:
    st.title("🏃 Running Life OS")
with col_logout:
    if st.button("🔒 Lock"):
        st.session_state["authenticated"] = False
        st.rerun()

menu = st.selectbox(
    "📌 메뉴 이동", 
    ["📱 홈 (대시보드)", "📝 빠른 데이터 입력", "🎯 프로젝트 & 대회", "📊 성능 지표 (Garmin)", "👟 신발 관리", "🤖 코치 노트"],
    index=0
)

st.divider()

# 1. 📱 홈 대시보드
if menu == "📱 홈 (대시보드)":
    st.subheader("🔋 Garmin 상태 (오늘)")
    df_daily = load_data("DailyStatus")
    latest_daily = df_daily.iloc[-1] if not df_daily.empty else {}
    
    c1, c2 = st.columns(2)
    c1.metric("Body Battery", latest_daily.get("BodyBattery", "-"))
    c2.metric("Readiness", latest_daily.get("TrainingReadiness", "-"))
    st.caption(f"💙 HRV Status: **{latest_daily.get('HRVStatus', '-')}**")
    
    st.divider()
    
    st.subheader("🎯 진행 중 프로젝트")
    df_proj = load_data("Projects")
    active_proj = df_proj[df_proj["Status"] == "ACTIVE"] if not df_proj.empty else pd.DataFrame()
    if not active_proj.empty:
        p = active_proj.iloc[0]
        st.success(f"**{p['ProjectName']}**\n\n🎯 목표: {p['GoalValue']} (목표일: {p['TargetDate']})")
    else:
        st.info("등록된 활성 프로젝트가 없습니다.")
        
    st.divider()
    
    st.subheader("🏃 최근 훈련 (Top 3)")
    df_work = load_data("Workouts")
    if not df_work.empty:
        for idx, row in df_work.tail(3).iloc[::-1].iterrows():
            with st.container():
                st.markdown(f"**📅 {row['WorkoutDate']} | {row['WorkoutType']}**")
                st.markdown(f"📏 **{row['DistanceKm']}km** ({row['DurationMinutes']}분) | ⏱️ 페이스: **{row['AvgPace']}**")
                if pd.notnull(row['Notes']) and row['Notes'] != "":
                    st.caption(f"💬 {row['Notes']}")
                st.divider()
    else:
        st.caption("아직 기록된 운동이 없습니다. '빠른 데이터 입력'에서 작성하세요.")

# 2. 📝 빠른 데이터 입력
elif menu == "📝 빠른 데이터 입력":
    tab1, tab2, tab3 = st.tabs(["일일 상태", "운동 기록", "Garmin 지표"])
    
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

    with tab2:
        st.caption("수행 훈련 입력 (5분 소요)")
        df_p = load_data("Projects")
        df_s = load_data("Shoes")
        p_list = df_p["ProjectName"].tolist() if not df_p.empty else ["기본 프로젝트"]
        s_list = df_s["ShoeName"].tolist() if not df_s.empty else ["기본 러닝화"]
        
        with st.form("workout_form"):
            w_date = st.date_input("운동 날짜", datetime.now())
            w_proj = st.selectbox("관련 프로젝트", p_list)
            w_type = st.selectbox("운동 유형", ["Easy", "Recovery", "LSD", "Threshold", "Interval", "Race"])
            dist = st.number_input("거리 (km)", 0.0, step=0.1, value=5.0)
            dur = st.number_input("시간 (분)", 0.0, step=1.0, value=30.0)
            pace = st.text_input("평균 페이스 (예: 5:30)", "5:30")
            hr = st.number_input("평균 심박수", 0, value=145)
            shoe = st.selectbox("착용 신발", s_list)
            rpe = st.slider("운동 강도 (RPE 1~10)", 1, 10, 5)
            w_note = st.text_area("코치 메모 / 훈련 느낌")
            
            if st.form_submit_button("운동 기록 저장", use_container_width=True):
                save_data("Workouts", pd.DataFrame([{
                    "WorkoutID": f"WO-{datetime.now().strftime('%Y%m%d%H%M')}",
                    "ProjectID": w_proj, "WorkoutDate": w_date, "WorkoutType": w_type,
                    "DistanceKm": dist, "DurationMinutes": dur, "AvgPace": pace, "AvgHeartRate": hr,
                    "ShoeID": shoe, "RPE": rpe, "Notes": w_note
                }]))
                st.success("저장 완료!")
                
    with tab3:
        st.caption("Garmin 지표 업데이트")
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
                st.success("업데이트 완료!")

# 3. 🎯 프로젝트 & 대회
elif menu == "🎯 프로젝트 & 대회":
    st.subheader("🎯 프로젝트 목록")
    st.dataframe(load_data("Projects"), use_container_width=True)
    
    with st.expander("+ 새 프로젝트 추가"):
        with st.form("proj_add"):
            pn = st.text_input("프로젝트 명", "Road to Half 1:50")
            stt = st.selectbox("상태", ["PLANNED", "ACTIVE", "COMPLETED"])
            gt = st.selectbox("목표 유형", ["Time Trial", "Distance", "Habit"])
            gv = st.text_input("목표 값", "Half Marathon Sub-1:50")
            s_d = st.date_input("시작일", datetime.now())
            t_d = st.date_input("목표일", datetime.now())
            if st.form_submit_button("프로젝트 생성", use_container_width=True):
                save_data("Projects", pd.DataFrame([{
                    "ProjectID": f"PRJ-{datetime.now().strftime('%M%S')}", "ProjectName": pn,
                    "Status": stt, "GoalType": gt, "GoalValue": gv, "StartDate": s_d, "TargetDate": t_d
                }]))
                st.success("생성 완료!")

# 4. 📊 성능 지표 (Garmin)
elif menu == "📊 성능 지표 (Garmin)":
    st.subheader("👤 러너 프로필 (1997년생)")
    df_ath = load_data("Athlete")
    if not df_ath.empty:
        ath = df_ath.iloc[0]
        st.write(f"🎂 생년월일: **{ath.get('BirthDate', '-')}** | 📏 키: **{ath.get('HeightCm', '-')}cm**")
        st.write(f"⚖️ 시작 체중: **{ath.get('StartWeightKg', '-')}kg** $\rightarrow$ 현재 체중: **{ath.get('CurrentWeightKg', '-')}kg**")
        
    st.divider()
    st.subheader("📈 Garmin 지표 히스토리")
    st.dataframe(load_data("Metrics"), use_container_width=True)

# 5. 👟 신발 관리
elif menu == "👟 신발 관리":
    st.subheader("👟 러닝화 자산 목록")
    st.dataframe(load_data("Shoes"), use_container_width=True)
    
    with st.expander("+ 새 러닝화 추가"):
        with st.form("shoe_add"):
            sn = st.text_input("신발 이름", "Nike Vaporfly 3")
            sb = st.text_input("브랜드", "Nike")
            if st.form_submit_button("신발 추가", use_container_width=True):
                save_data("Shoes", pd.DataFrame([{
                    "ShoeID": f"SHOE-{datetime.now().strftime('%M%S')}", "ShoeName": sn,
                    "Brand": sb, "DistanceKm": 0.0, "Status": "ACTIVE"
                }]))
                st.success("추가 완료!")

# 6. 🤖 코치 노트
elif menu == "🤖 코치 노트":
    st.subheader("🤖 Copilot 코치 노트")
    df_notes = load_data("CoachNotes")
    if not df_notes.empty:
        for idx, row in df_notes.iloc[::-1].iterrows():
            st.info(f"**[{row['NoteDate']}] {row['ProjectID']} ({row['Category']})**\n\n{row['NoteText']}")
    
    with st.expander("+ 코치 노트 작성"):
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
