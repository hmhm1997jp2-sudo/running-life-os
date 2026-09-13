import streamlit as st
import pandas as pd
from datetime import datetime
import os

st.set_page_config(page_title="Running Life OS", page_icon="🏃", layout="centered", initial_sidebar_state="collapsed")

# 🔒 보안 처리
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

# 🏃 메인 시스템 구동
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "Running Life OS Database.xlsx")

def init_db():
    required_sheets = ["Athlete", "Projects", "Workouts", "DailyStatus", "Metrics", "Shoes", "Races", "CoachNotes"]
    need_init = False
    if not os.path.exists(DB_FILE):
        need_init = True
    else:
        try:
            excel_obj = pd.ExcelFile(DB_FILE)
            if not all(sheet in excel_obj.sheet_names for sheet in required_sheets):
                need_init = True
        except Exception:
            need_init = True

    if need_init:
        with pd.ExcelWriter(DB_FILE, engine='openpyxl') as writer:
            pd.DataFrame([{"AthleteID": "ATH-001", "BirthDate": "1997-10-28", "HeightCm": 180, "CurrentWeightKg": 85.0, "StartWeightKg": 115.0}]).to_excel(writer, sheet_name="Athlete", index=False)
            pd.DataFrame([{"ProjectID": "PRJ-001", "ProjectName": "Road to 10K 50", "Status": "ACTIVE", "GoalType": "Time Trial", "GoalValue": "10km Sub-50", "StartDate": "2026-09-01", "TargetDate": "2026-11-30", "Description": "10k 50분 진입 프로젝트"}]).to_excel(writer, sheet_name="Projects", index=False)
            pd.DataFrame(columns=["WorkoutID", "ProjectID", "WorkoutDate", "WorkoutType", "DistanceKm", "DurationMinutes", "AvgPace", "AvgHeartRate", "AvgPower", "Temperature", "ShoeID", "RPE", "LegFatigue", "CardioFatigue", "Notes"]).to_excel(writer, sheet_name="Workouts", index=False)
            pd.DataFrame(columns=["StatusID", "StatusDate", "TrainingReadiness", "BodyBattery", "HRVStatus", "Notes"]).to_excel(writer, sheet_name="DailyStatus", index=False)
            pd.DataFrame([{"MetricID": "MET-001", "MetricDate": "2026-09-13", "WeightKg": 85.0, "VO2Max": 48.4, "LTPace": "4:58", "LTHR": 161, "LTPower": 404}]).to_excel(writer, sheet_name="Metrics", index=False)
            pd.DataFrame([
                {"ShoeID": "SHOE-001", "ShoeName": "Nike Zoom Fly 6", "Brand": "Nike", "PurchaseDate": "2026-01-10", "DistanceKm": 120.5, "Status": "ACTIVE", "Category": "Tempo"},
                {"ShoeID": "SHOE-002", "ShoeName": "Saucony Ride 19", "Brand": "Saucony", "PurchaseDate": "2026-03-15", "DistanceKm": 210.0, "Status": "ACTIVE", "Category": "Daily"},
                {"ShoeID": "SHOE-003", "ShoeName": "Saucony Triumph 23", "Brand": "Saucony", "PurchaseDate": "2026-05-20", "DistanceKm": 85.0, "Status": "ACTIVE", "Category": "Long Run"}
            ]).to_excel(writer, sheet_name="Shoes", index=False)
            pd.DataFrame(columns=["RaceID", "ProjectID", "RaceDate", "RaceName", "Distance", "GoalTime", "ActualTime", "ShoeID", "ResultStatus"]).to_excel(writer, sheet_name="Races", index=False)
            pd.DataFrame([{"NoteID": "NOTE-001", "ProjectID": "Road to 10K 50", "NoteDate": "2026-09-13", "Category": "Weekly", "NoteText": "Garmin VO2max 48.4 유지 중. 유산소 기반 양호."}]).to_excel(writer, sheet_name="CoachNotes", index=False)

init_db()

def load_data(sheet):
    init_db()
    return pd.read_excel(DB_FILE, sheet_name=sheet)

def write_sheet(sheet, df):
    # 특정 시트 전체 덮어쓰기 (수정/삭제용)
    excel_obj = pd.ExcelFile(DB_FILE)
    all_sheets = {}
    for s_name in excel_obj.sheet_names:
        if s_name == sheet:
            all_sheets[s_name] = df
        else:
            all_sheets[s_name] = pd.read_excel(DB_FILE, sheet_name=s_name)
            
    with pd.ExcelWriter(DB_FILE, engine='openpyxl') as writer:
        for s_name, s_df in all_sheets.items():
            s_df.to_excel(writer, sheet_name=s_name, index=False)

def save_data(sheet, new_df):
    old_df = load_data(sheet)
    updated = pd.concat([old_df, new_df], ignore_index=True)
    write_sheet(sheet, updated)

# 상단 헤더
col_title, col_logout = st.columns([3, 1])
with col_title:
    st.title("🏃 Running Life OS")
with col_logout:
    if st.button("🔒 Lock"):
        st.session_state["authenticated"] = False
        st.rerun()

menu = st.selectbox(
    "📌 메뉴 이동", 
    ["📱 홈 (대시보드)", "📝 데이터 입력 (상세)", "🎯 프로젝트 관리 및 수정", "👟 신발 관리 & 훈련 이력", "📊 주요 성능 지표 (Garmin)", "🤖 코치 노트"],
    index=0
)

st.divider()

# -----------------------------------------------------------------------------
# 1. 📱 홈 대시보드
# -----------------------------------------------------------------------------
if menu == "📱 홈 (대시보드)":
    st.subheader("🔋 오늘의 컨디션 지표")
    df_daily = load_data("DailyStatus")
    latest_daily = df_daily.iloc[-1] if not df_daily.empty else {}
    
    c1, c2 = st.columns(2)
    c1.metric("Body Battery", latest_daily.get("BodyBattery", "-"))
    c2.metric("Readiness", latest_daily.get("TrainingReadiness", "-"))
    st.caption(f"💙 HRV Status: **{latest_daily.get('HRVStatus', '-')}**")
    
    st.divider()
    
    # Garmin 주요 픽 지표 하이라이트 (R-005)
    st.subheader("⚡ 최신 역치 & 퍼포먼스 지표")
    df_met = load_data("Metrics")
    if not df_met.empty:
        m_latest = df_met.iloc[-1]
        m1, m2, m3 = st.columns(3)
        m1.metric("VO₂max", f"{m_latest.get('VO2Max', '-')}")
        m2.metric("LT Pace", f"{m_latest.get('LTPace', '-')}")
        m3.metric("LT HR", f"{m_latest.get('LTHR', '-')} bpm")
        st.caption(f"⚡ LT Power: **{m_latest.get('LTPower', '-')}W** | ⚖️ 체중: **{m_latest.get('WeightKg', '-')}kg**")
        
    st.divider()
    
    st.subheader("🎯 Active Project")
    df_proj = load_data("Projects")
    active_proj = df_proj[df_proj["Status"] == "ACTIVE"] if not df_proj.empty else pd.DataFrame()
    if not active_proj.empty:
        p = active_proj.iloc[0]
        st.success(f"**{p['ProjectName']}**\n\n🎯 목표: {p['GoalValue']} | Target: {p['TargetDate']}")
    else:
        st.info("등록된 활성 프로젝트가 없습니다.")
        
    st.divider()
    
    st.subheader("🏃 최근 훈련 (Top 3)")
    df_work = load_data("Workouts")
    if not df_work.empty:
        for idx, row in df_work.tail(3).iloc[::-1].iterrows():
            with st.container():
                st.markdown(f"**📅 {row['WorkoutDate']} | {row['WorkoutType']} ({row['ProjectID']})**")
                st.markdown(f"📏 **{row['DistanceKm']}km** ({row['DurationMinutes']}분) | ⏱️ **{row['AvgPace']}** | 👟 {row['ShoeID']}")
                if pd.notnull(row['Notes']) and row['Notes'] != "":
                    st.caption(f"💬 코치/기록 메모: {row['Notes']}")
                st.divider()
    else:
        st.caption("기록된 운동이 없습니다. '데이터 입력' 메뉴에서 작성하세요.")

# -----------------------------------------------------------------------------
# 2. 📝 데이터 입력 (상세 풀 스펙)
# -----------------------------------------------------------------------------
elif menu == "📝 데이터 입력 (상세)":
    tab1, tab2, tab3 = st.tabs(["일일 상태", "운동 기록 (상세)", "Garmin 지표"])
    
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
        st.caption("상세 훈련 기록 입력 (R-005, R-006 스펙 반영)")
        df_p = load_data("Projects")
        df_s = load_data("Shoes")
        p_list = df_p["ProjectName"].tolist() if not df_p.empty else ["기본 프로젝트"]
        s_list = df_s["ShoeName"].tolist() if not df_s.empty else ["기본 러닝화"]
        
        with st.form("workout_form"):
            w_date = st.date_input("운동 날짜", datetime.now())
            w_proj = st.selectbox("관련 프로젝트 (R-004)", p_list)
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
            
            w_note = st.text_area("Copilot 분석 노트 & 사용자 메모 (R-006)")
            
            if st.form_submit_button("상세 운동 기록 저장", use_container_width=True):
                save_data("Workouts", pd.DataFrame([{
                    "WorkoutID": f"WO-{datetime.now().strftime('%Y%m%d%H%M')}",
                    "ProjectID": w_proj, "WorkoutDate": w_date, "WorkoutType": w_type,
                    "DistanceKm": dist, "DurationMinutes": dur, "AvgPace": pace, "AvgHeartRate": hr,
                    "AvgPower": power, "Temperature": temp, "ShoeID": shoe, "RPE": rpe,
                    "LegFatigue": leg_fatigue, "CardioFatigue": cardio_fatigue, "Notes": w_note
                }]))
                st.success("훈련 데이터 저장 및 신발 누적 연동 완료!")
                
    with tab3:
        st.caption("Garmin 지표 업데이트 (R-005)")
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
                st.success("지표 업데이트 완료!")

# -----------------------------------------------------------------------------
# 3. 🎯 프로젝트 관리 및 수정 (요구사항 반영)
# -----------------------------------------------------------------------------
elif menu == "🎯 프로젝트 관리 및 수정":
    st.subheader("🎯 프로젝트 관리 & 편집")
    df_proj = load_data("Projects")
    
    st.dataframe(df_proj, use_container_width=True)
    
    # 프로젝트 수정/삭제 폼
    if not df_proj.empty:
        with st.expander("✏️ 기존 프로젝트 수정 / 삭제"):
            selected_proj_id = st.selectbox("수정할 프로젝트 ID 선택", df_proj["ProjectID"].tolist())
            proj_row = df_proj[df_proj["ProjectID"] == selected_proj_id].iloc[0]
            
            with st.form("edit_proj_form"):
                edit_name = st.text_input("프로젝트 이름", proj_row["ProjectName"])
                edit_status = st.selectbox("상태", ["ACTIVE", "PLANNED", "COMPLETED", "CANCELLED"], index=["ACTIVE", "PLANNED", "COMPLETED", "CANCELLED"].index(proj_row["Status"]) if proj_row["Status"] in ["ACTIVE", "PLANNED", "COMPLETED", "CANCELLED"] else 0)
                edit_goal = st.text_input("목표 값", proj_row["GoalValue"])
                edit_desc = st.text_area("설명", proj_row.get("Description", ""))
                
                col_u, col_d = st.columns(2)
                btn_update = col_u.form_submit_button("수정 내용 저장", use_container_width=True)
                
                if btn_update:
                    df_proj.loc[df_proj["ProjectID"] == selected_proj_id, "ProjectName"] = edit_name
                    df_proj.loc[df_proj["ProjectID"] == selected_proj_id, "Status"] = edit_status
                    df_proj.loc[df_proj["ProjectID"] == selected_proj_id, "GoalValue"] = edit_goal
                    df_proj.loc[df_proj["ProjectID"] == selected_proj_id, "Description"] = edit_desc
                    write_sheet("Projects", df_proj)
                    st.success("프로젝트가 성공적으로 수정되었습니다!")
                    st.rerun()

    with st.expander("+ 새 프로젝트 등록"):
        with st.form("proj_add"):
            pn = st.text_input("프로젝트 명 (예: Road to Half 1:50)")
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
                st.rerun()

# -----------------------------------------------------------------------------
# 4. 👟 신발 관리 & 훈련 이력 연동 (요구사항 반영)
# -----------------------------------------------------------------------------
elif menu == "👟 신발 관리 & 훈련 이력":
    st.subheader("👟 신발 자산 & 훈련 이력 조회")
    df_shoes = load_data("Shoes")
    df_work = load_data("Workouts")
    
    st.dataframe(df_shoes, use_container_width=True)
    
    st.divider()
    st.subheader("🔍 신발별 수행 훈련 보기")
    if not df_shoes.empty:
        selected_shoe = st.selectbox("조회할 신발을 선택하세요", df_shoes["ShoeName"].tolist())
        
        # 선택한 신발로 뛴 훈련들 자동 필터링
        filtered_workouts = df_work[df_work["ShoeID"] == selected_shoe] if not df_work.empty else pd.DataFrame()
        
        # 실시간 누적 거리 계산
        calc_dist = filtered_workouts["DistanceKm"].sum() if not filtered_workouts.empty else 0.0
        st.info(f"👟 **{selected_shoe}**로 기록된 총 훈련 거리: **{calc_dist:.1f} km** (총 {len(filtered_workouts)}회 수행)")
        
        if not filtered_workouts.empty:
            for idx, r in filtered_workouts.iloc[::-1].iterrows():
                st.write(f"🏃 **{r['WorkoutDate']}** | {r['WorkoutType']} | **{r['DistanceKm']}km** (페이스: {r['AvgPace']}, 심박: {r['AvgHeartRate']}bpm)")
                if pd.notnull(r['Notes']) and r['Notes'] != "":
                    st.caption(f"💬 {r['Notes']}")
                st.divider()
        else:
            st.caption("해당 신발로 기록된 훈련이 아직 없습니다.")
            
    with st.expander("+ 새 러닝화 자산 등록"):
        with st.form("shoe_add"):
            sn = st.text_input("신발 이름 (예: Nike Vaporfly 3)")
            sb = st.text_input("브랜드", "Nike")
            sc = st.selectbox("카테고리", ["Daily", "Long Run", "Tempo", "Race"])
            if st.form_submit_button("신발 추가", use_container_width=True):
                save_data("Shoes", pd.DataFrame([{
                    "ShoeID": f"SHOE-{datetime.now().strftime('%M%S')}", "ShoeName": sn,
                    "Brand": sb, "DistanceKm": 0.0, "Status": "ACTIVE", "Category": sc
                }]))
                st.success("신발이 자산으로 등록되었습니다!")
                st.rerun()

# -----------------------------------------------------------------------------
# 5. 📊 주요 성능 지표 (Garmin 트래킹)
# -----------------------------------------------------------------------------
elif menu == "📊 주요 성능 지표 (Garmin)":
    st.subheader("👤 러너 기본 정보")
    df_ath = load_data("Athlete")
    if not df_ath.empty:
        ath = df_ath.iloc[0]
        st.write(f"🎂 생년월일: **{ath.get('BirthDate', '-')}** (1997년생) | 📏 키: **{ath.get('HeightCm', '-')}cm**")
        st.write(f"⚖️ 시작 체중: **{ath.get('StartWeightKg', '-')}kg** $\rightarrow$ 현재 체중: **{ath.get('CurrentWeightKg', '-')}kg**")
        
    st.divider()
    st.subheader("📈 Garmin 주요 지표 트래킹 (VO₂max & 역치)")
    df_met = load_data("Metrics")
    st.dataframe(df_met, use_container_width=True)

# -----------------------------------------------------------------------------
# 6. 🤖 코치 노트 (R-006)
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
