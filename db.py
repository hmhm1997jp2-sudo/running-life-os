"""
Running Life OS - 데이터 저장소 모듈 (db.py)
============================================
Google Sheets(기본) 와 로컬 엑셀(자동 대체)을 같은 함수로 다룹니다.

  - st.secrets 에 [gcp_service_account] 가 있으면  → Google Sheets 사용
  - 없으면                                          → 로컬 엑셀 파일 사용 (내 PC 테스트용)

app.py 에서는 저장 방식을 신경 쓸 필요 없이 아래 4개만 쓰면 됩니다.
    db.init_db()                  # 최초 1회 (시트 자동 생성)
    db.load_data("Workouts")      # 읽기  → DataFrame
    db.append_rows("Workouts", df)# 추가
    db.write_sheet("Workouts", df)# 통째로 덮어쓰기(수정/삭제)
"""

from __future__ import annotations

import os
import pandas as pd
import numpy as np
import streamlit as st

SPREADSHEET_NAME = "Running Life OS Database"
EXCEL_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "Running Life OS Database.xlsx")

# ---------------------------------------------------------------------------
# 스키마 정의 — 여기에 컬럼을 추가하면 자동으로 시트에도 반영됩니다.
# ---------------------------------------------------------------------------
SCHEMA: dict[str, list[str]] = {
    # ※ 새 컬럼은 반드시 맨 뒤에 추가할 것
    "Athlete": ["AthleteID", "Name", "BirthDate", "Sex", "HeightCm",
                "CurrentWeightKg", "StartWeightKg", "HRRest", "HRMax", "LTHR",
                "RunZonePct"],
    "Projects": ["ProjectID", "ProjectName", "Status", "GoalType", "GoalValue",
                 "StartDate", "TargetDate", "Description"],
    "Workouts": ["WorkoutID", "ProjectID", "WorkoutDate", "WorkoutType", "DistanceKm",
                 "DurationMinutes", "PaceSec", "AvgHeartRate", "MaxHeartRate", "AvgPower",
                 "AvgCadence", "ElevationGainM", "Temperature", "Surface", "ShoeID",
                 "AerobicTE", "AnaerobicTE", "PrimaryBenefit",
                 # 러닝 다이나믹스 (가민 활동 상세 CSV에서 자동 입력)
                 "Calories", "AvgGCTms", "AvgStrideM", "AvgVertOscCm", "AvgVertRatioPct",
                 "RPE", "LegFatigue", "CardioFatigue", "Notes", "SourceKey",
                 # 아래는 맨 뒤에 추가된 항목 — 순서를 바꾸지 말 것
                 "ElevLossM", "GapPaceSec", "NormPower", "MaxPaceSec", "MaxCadence",
                 "MovingMinutes"],
    # ── 가민 일일 지표 (Connect 홈에서 매일 보이는 값) ──────────────────────
    "DailyStatus": ["StatusID", "StatusDate", "TrainingStatus", "AcuteLoad", "LoadRatio",
                    "RecoveryTimeHr", "TrainingReadiness", "BodyBattery",
                    "HRVStatus", "HRVms", "SleepScore", "RestingHR",
                    "IntensityMinutes", "Notes",
                    # 맨 뒤에 추가 — 입력 시각과 회복 완료 예상 시각
                    "MeasuredAt", "RecoveryUntil",
                    # 맨 뒤에 추가 — 가민 '트레이닝 준비 상태'의 나머지 두 요인과
                    # 이 줄이 아침 체크인인지 훈련 후 체크인인지
                    "SleepHistory", "StressHistory", "EntryKind"],
    # ── 프로필·지표 변경 이력 (날짜별 스냅샷) ─────────────────────────────
    #    체중/심박/LTHR 이 바뀐 시점을 남기면 과거 훈련은 그 시점 값으로 계산됩니다.
    "Metrics": ["MetricID", "MetricDate", "HRRest", "HRMax", "VO2Max", "FitnessAge",
                "EnduranceScore", "HillScore",
                "FocusAnaerobic", "FocusHighAerobic", "FocusLowAerobic",
                "Pred5K", "Pred10K", "PredHalf", "PredFull",
                "LTPace", "LTHR", "LTPower",
                "WeightKg", "BodyFatPct", "Notes"],
    "Shoes": ["ShoeID", "ShoeName", "Brand", "PurchaseDate", "InitialDistanceKm",
              "TargetDistanceKm", "Status", "Category", "Notes"],
    "Races": ["RaceID", "ProjectID", "RaceDate", "RaceName", "Distance", "DistanceKm",
              "GoalTime", "ActualTime", "ShoeID", "ResultStatus", "Notes"],
    # ── 랩(구간) 기록 — 활동 상세 CSV를 올리면 함께 저장됩니다 ───────────
    # ※ 새 컬럼은 반드시 맨 뒤에 추가할 것 (중간 삽입 시 기존 데이터가 한 칸씩 밀림)
    "Laps": ["LapID", "WorkoutID", "WorkoutDate", "WorkoutType", "LapNo",
             "CumMinutes", "DistanceKm", "DurationMinutes",
             "PaceSec", "AvgHeartRate", "MaxHeartRate", "AvgPower", "AvgCadence",
             "ElevGainM", "ElevLossM", "AvgGCTms", "AvgStrideM",
             "AvgVertOscCm", "AvgVertRatioPct", "Calories", "TempC",
             "LapRole",
             # 가민 활동 상세 CSV의 나머지 랩 항목 (맨 뒤에 추가)
             "GapPaceSec", "NormPower", "AvgWkg", "MaxPower", "MaxWkg",
             "MaxPaceSec", "MaxCadence", "MovingMinutes", "MovingPaceSec"],
    "CoachNotes": ["NoteID", "ProjectID", "NoteDate", "Category", "NoteText"],
    "TrainingPlans": ["PlanID", "PlanDate", "GarminPlan", "CopilotPlan",
                      "SelectedPlan", "Status", "Notes"],
}

# 숫자로 변환할 컬럼
NUMERIC_COLS = {
    "HeightCm", "CurrentWeightKg", "StartWeightKg", "HRRest", "HRMax", "LTHR",
    "DistanceKm", "DurationMinutes", "PaceSec", "AvgHeartRate", "MaxHeartRate",
    "AvgPower", "AvgCadence", "ElevationGainM", "Temperature", "RPE", "LegFatigue",
    "CardioFatigue", "TrainingReadiness", "BodyBattery", "SleepScore", "RestingHR",
    "WeightKg", "BodyFatPct", "VO2Max", "LTPower", "InitialDistanceKm",
    "TargetDistanceKm",
    # 가민 지표
    "AcuteLoad", "LoadRatio", "RecoveryTimeHr", "HRVms", "IntensityMinutes",
    "HRRest", "HRMax",
    "FitnessAge", "EnduranceScore", "HillScore",
    "FocusAnaerobic", "FocusHighAerobic", "FocusLowAerobic",
    "AerobicTE", "AnaerobicTE",
    "LapNo", "ElevGainM", "ElevLossM",
    "Calories", "AvgGCTms", "AvgStrideM", "AvgVertOscCm", "AvgVertRatioPct", "TempC",
    "CumMinutes",
    # CSV 랩 상세에서 함께 들어오는 숫자 항목
    "GapPaceSec", "NormPower", "AvgWkg", "MaxPower", "MaxWkg",
    "MaxPaceSec", "MaxCadence", "MovingMinutes", "MovingPaceSec",
}

# ---------------------------------------------------------------------------
# 과거 스키마 (컬럼 순서 이력)
#   시트의 값은 '위치'로 저장되므로, 스키마 중간에 컬럼을 끼워 넣으면
#   그 전에 저장된 행이 밀립니다. 행의 칸 수로 어느 시절 행인지 판별해
#   이름 기준으로 다시 맞추기 위한 표입니다.
#   ※ 앞으로 새 컬럼은 반드시 스키마 '맨 뒤'에 추가할 것.
# ---------------------------------------------------------------------------
LEGACY_SCHEMAS: dict[str, dict[int, list[str]]] = {
    "Workouts": {
        20: ["WorkoutID", "ProjectID", "WorkoutDate", "WorkoutType", "DistanceKm",
             "DurationMinutes", "PaceSec", "AvgHeartRate", "MaxHeartRate", "AvgPower",
             "AvgCadence", "ElevationGainM", "Temperature", "Surface", "ShoeID",
             "RPE", "LegFatigue", "CardioFatigue", "Notes", "SourceKey"],
        23: ["WorkoutID", "ProjectID", "WorkoutDate", "WorkoutType", "DistanceKm",
             "DurationMinutes", "PaceSec", "AvgHeartRate", "MaxHeartRate", "AvgPower",
             "AvgCadence", "ElevationGainM", "Temperature", "Surface", "ShoeID",
             "AerobicTE", "AnaerobicTE", "PrimaryBenefit",
             "RPE", "LegFatigue", "CardioFatigue", "Notes", "SourceKey"],
    },
    "Metrics": {
        9:  ["MetricID", "MetricDate", "WeightKg", "BodyFatPct", "VO2Max",
             "LTPace", "LTHR", "LTPower", "Notes"],
        19: ["MetricID", "MetricDate", "VO2Max", "FitnessAge",
             "EnduranceScore", "HillScore",
             "FocusAnaerobic", "FocusHighAerobic", "FocusLowAerobic",
             "Pred5K", "Pred10K", "PredHalf", "PredFull",
             "LTPace", "LTHR", "LTPower", "WeightKg", "BodyFatPct", "Notes"],
    },
    "DailyStatus": {
        8:  ["StatusID", "StatusDate", "TrainingReadiness", "BodyBattery",
             "HRVStatus", "SleepScore", "RestingHR", "Notes"],
        14: ["StatusID", "StatusDate", "TrainingStatus", "AcuteLoad", "LoadRatio",
             "RecoveryTimeHr", "TrainingReadiness", "BodyBattery",
             "HRVStatus", "HRVms", "SleepScore", "RestingHR",
             "IntensityMinutes", "Notes"],
        16: ["StatusID", "StatusDate", "TrainingStatus", "AcuteLoad", "LoadRatio",
             "RecoveryTimeHr", "TrainingReadiness", "BodyBattery",
             "HRVStatus", "HRVms", "SleepScore", "RestingHR",
             "IntensityMinutes", "Notes", "MeasuredAt", "RecoveryUntil"],
    },
    "Laps": {
        11: ["LapID", "WorkoutID", "LapNo", "DistanceKm", "DurationMinutes",
             "PaceSec", "AvgHeartRate", "MaxHeartRate", "AvgPower",
             "ElevGainM", "ElevLossM"],
        18: ["LapID", "WorkoutID", "LapNo", "DistanceKm", "DurationMinutes",
             "PaceSec", "AvgHeartRate", "MaxHeartRate", "AvgPower", "AvgCadence",
             "ElevGainM", "ElevLossM", "AvgGCTms", "AvgStrideM",
             "AvgVertOscCm", "AvgVertRatioPct", "Calories", "TempC"],
    },
}


def _raw_values(sheet: str) -> list[list[str]]:
    """시트 원본 값(헤더 포함)을 그대로 읽는다 — 진단·복구용."""
    if use_gsheets():
        ws = _retry(_spreadsheet().worksheet, sheet)
        return _retry(ws.get_all_values) or []
    if not os.path.exists(EXCEL_FILE):
        return []
    df = pd.read_excel(EXCEL_FILE, sheet_name=sheet).fillna("")
    return [list(df.columns)] + df.astype(str).values.tolist()


def _suspect_shift(sheet: str, rows: list[list[str]]) -> dict[int, int]:
    """
    '값이 밀린 것으로 보이는' 행 수를 과거 스키마 길이별로 센다.
    폭이 이미 현재 스키마로 맞춰진 뒤에도 내용으로 판별할 수 있게 한다.
    """
    import re as _re
    _PACE = _re.compile("[0-9]{1,2}:[0-9]{2}$")      # 4:58 같은 페이스 (백슬래시 없이)
    cur = SCHEMA.get(sheet, [])
    out: dict[int, int] = {}

    def val(r, name, names):
        try:
            i = names.index(name)
        except ValueError:
            return ""
        return str(r[i]).strip() if i < len(r) else ""

    def looks_pace(t: str) -> bool:
        if not _PACE.match(t):
            return False
        try:
            return int(t.split(":")[0]) < 20      # 하프 예측이라면 1시간 이상이어야 함
        except ValueError:
            return False

    def looks_number(t: str) -> bool:
        try:
            return 0 < float(t) < 1000            # 풀 예측 자리에 숫자만 = LTHR
        except ValueError:
            return False

    for ln, old in LEGACY_SCHEMAS.get(sheet, {}).items():
        cnt = 0
        for r in rows:
            if len(r) == ln and ln != len(cur):
                cnt += 1
                continue
            if sheet == "Metrics" and ln == 19:
                ph, pf = val(r, "PredHalf", cur), val(r, "PredFull", cur)
                lp = val(r, "LTPace", cur)
                if (looks_pace(ph) or looks_number(pf)) and not lp:
                    cnt += 1
            elif sheet == "Workouts" and ln == 23:
                cal, rpe = val(r, "Calories", cur), val(r, "RPE", cur)
                if cal.isdigit() and 1 <= int(cal) <= 10 and not rpe:
                    cnt += 1
        if cnt:
            out[ln] = cnt
    return out


def diagnose(sheet: str) -> dict:
    """시트에 값이 밀린 행이 있는지 확인한다."""
    vals = _raw_values(sheet)
    cur = SCHEMA.get(sheet, [])
    if not vals:
        return {"sheet": sheet, "rows": 0, "suspects": {}, "ok": True, "header_ok": True}
    header = [str(h) for h in vals[0]]
    body = [r for r in vals[1:] if any(str(c).strip() for c in r)]
    susp = _suspect_shift(sheet, body)
    return {"sheet": sheet, "rows": len(body), "suspects": susp,
            "header_ok": header[:len(cur)] == cur,
            "misaligned": sum(susp.values()),
            "ok": not susp and header[:len(cur)] == cur}


def _remap_rows(sheet: str, legacy_len: int) -> pd.DataFrame:
    """과거 스키마(legacy_len 열) 기준으로 이름을 다시 붙여 현재 스키마로 정렬."""
    vals = _raw_values(sheet)
    cur = SCHEMA.get(sheet, [])
    old = LEGACY_SCHEMAS.get(sheet, {}).get(legacy_len, [])
    if not vals or not cur or not old:
        return pd.DataFrame(columns=cur)
    recs = []
    for r in vals[1:]:
        if not any(str(c).strip() for c in r):
            continue
        recs.append({n: (r[i] if i < len(r) else "") for i, n in enumerate(old)})
    df = pd.DataFrame(recs)
    for c in cur:
        if c not in df.columns:
            df[c] = ""
    return df[cur]


def repair_preview(sheet: str, legacy_len: int, n: int = 3) -> tuple:
    """교정 전/후 비교. 값이 실제로 바뀌는 컬럼만 골라 보여준다."""
    vals = _raw_values(sheet)
    cur = SCHEMA.get(sheet, [])
    if not vals:
        return pd.DataFrame(), pd.DataFrame()
    body = [r for r in vals[1:] if any(str(c).strip() for c in r)]
    before = pd.DataFrame(
        [{c: (r[i] if i < len(r) else "") for i, c in enumerate(cur)} for r in body])
    after = _remap_rows(sheet, legacy_len)
    n = min(n, len(before), len(after)) or 1
    b, a = before.head(n), after.head(n)
    diff = [c for c in cur
            if c in b.columns and c in a.columns
            and not b[c].astype(str).equals(a[c].astype(str))]
    key = [c for c in cur[:2]]
    keep = key + [c for c in diff if c not in key]
    keep = keep[:10] or cur[:8]
    return b[[c for c in keep if c in b.columns]], a[[c for c in keep if c in a.columns]]


def repair(sheet: str, legacy_len: int) -> dict:
    """값은 그대로 두고 '어느 컬럼인지'만 바로잡아 시트를 다시 씁니다."""
    df = _remap_rows(sheet, legacy_len)
    if df.empty:
        return {"rows": 0}
    write_sheet(sheet, df)
    return {"rows": len(df)}


DEFAULT_ATHLETE = {
    "AthleteID": "ATH-001", "Name": "Runner", "BirthDate": "", "Sex": "M",
    "HeightCm": 180, "CurrentWeightKg": 85.0, "StartWeightKg": 115.0,
    "HRRest": 55, "HRMax": 190, "LTHR": 170, "RunZonePct": "",
}


# ---------------------------------------------------------------------------
# 저장 방식 판별
# ---------------------------------------------------------------------------
def use_gsheets() -> bool:
    try:
        return "gcp_service_account" in st.secrets
    except Exception:
        return False


def backend_name() -> str:
    return "Google Sheets" if use_gsheets() else "로컬 엑셀 파일"


class QuotaError(RuntimeError):
    """Google Sheets 분당 호출 한도 초과."""


def _retry(fn, *args, tries: int = 4, **kwargs):
    """429(한도 초과) 시 잠깐 쉬었다 다시 시도."""
    import time
    last = None
    for i in range(tries):
        try:
            return fn(*args, **kwargs)
        except Exception as e:  # gspread.exceptions.APIError 포함
            last = e
            code = getattr(getattr(e, "response", None), "status_code", None)
            if code not in (429, 500, 503):
                raise
            time.sleep(1.5 * (i + 1))
    raise QuotaError(str(last))


@st.cache_resource(show_spinner=False)
def _spreadsheet():
    """gspread 스프레드시트 핸들 (세션당 1회 연결)."""
    import gspread
    from google.oauth2.service_account import Credentials

    scopes = ["https://www.googleapis.com/auth/spreadsheets",
              "https://www.googleapis.com/auth/drive"]
    info = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(info, scopes=scopes)
    client = gspread.authorize(creds)

    name = st.secrets.get("SPREADSHEET_NAME", SPREADSHEET_NAME)
    key = st.secrets.get("SPREADSHEET_KEY", None)
    return client.open_by_key(key) if key else client.open(name)


# ---------------------------------------------------------------------------
# 초기화
# ---------------------------------------------------------------------------
def init_db() -> None:
    """없는 시트를 만들고 헤더를 채웁니다. 기존 데이터는 건드리지 않습니다.
    Streamlit은 조작할 때마다 스크립트를 처음부터 다시 실행하므로,
    세션당 1회만 수행해 Sheets 호출 수를 줄입니다."""
    if st.session_state.get("_db_init_done"):
        return
    if use_gsheets():
        sh = _spreadsheet()
        ws_by_name = {ws.title: ws for ws in _retry(sh.worksheets)}
        existing = set(ws_by_name)

        # 없는 시트 생성
        created = []
        for name, cols in SCHEMA.items():
            if name not in existing:
                ws = _retry(sh.add_worksheet, title=name, rows=200,
                            cols=max(12, len(cols) + 4))
                _retry(ws.update, range_name="A1", values=[cols])
                if name == "Athlete":
                    _retry(ws.append_row,
                           [str(DEFAULT_ATHLETE.get(c, "")) for c in cols],
                           value_input_option="USER_ENTERED")
                created.append(name)

        # 기존 시트의 헤더가 스키마보다 좁으면 넓힌다
        # (컬럼을 추가한 뒤 새 행만 넓게 들어가면 읽을 때 폭이 어긋납니다)
        # 시트 열 수가 스키마보다 적으면 먼저 넓힌다 (헤더를 쓸 자리 확보)
        for name, cols in SCHEMA.items():
            ws = ws_by_name.get(name)
            if ws is None:
                continue
            try:
                if int(getattr(ws, "col_count", 0) or 0) < len(cols):
                    _retry(ws.resize, cols=len(cols) + 4)
            except Exception:
                pass

        old = [n for n in SCHEMA if n in existing and n not in created]
        if old:
            try:
                resp = _retry(sh.values_batch_get, [f"'{n}'!1:1" for n in old])
                fixes = []
                for name, vr in zip(old, resp.get("valueRanges", [])):
                    cur = [str(h) for h in (vr.get("values", [[]]) or [[]])[0]]
                    want = SCHEMA[name]
                    if cur[:len(want)] != want:
                        fixes.append({"range": f"'{name}'!A1", "values": [want]})
                if fixes:
                    _retry(sh.values_batch_update,
                           {"valueInputOption": "RAW", "data": fixes})
            except Exception:
                pass   # 헤더 보정 실패해도 읽기 쪽에서 폭을 맞춰 처리합니다
    else:
        if not os.path.exists(EXCEL_FILE):
            with pd.ExcelWriter(EXCEL_FILE, engine="openpyxl") as w:
                for name, cols in SCHEMA.items():
                    df = pd.DataFrame(columns=cols)
                    if name == "Athlete":
                        df = pd.DataFrame([DEFAULT_ATHLETE])[cols]
                    df.to_excel(w, sheet_name=name, index=False)
        else:
            xl = pd.ExcelFile(EXCEL_FILE)
            missing = [s for s in SCHEMA if s not in xl.sheet_names]
            if missing:
                data = {s: pd.read_excel(EXCEL_FILE, sheet_name=s) for s in xl.sheet_names}
                for s in missing:
                    data[s] = pd.DataFrame(columns=SCHEMA[s])
                _atomic_excel_write(data)
    st.session_state["_db_init_done"] = True


def _atomic_excel_write(sheets: dict[str, pd.DataFrame]) -> None:
    """임시파일에 쓰고 교체 — 중간에 실패해도 원본이 깨지지 않습니다."""
    tmp = EXCEL_FILE + ".tmp.xlsx"   # pandas가 확장자로 엔진을 검증하므로 .xlsx 유지
    with pd.ExcelWriter(tmp, engine="openpyxl") as w:
        for name, df in sheets.items():
            df.to_excel(w, sheet_name=name, index=False)
    os.replace(tmp, EXCEL_FILE)


# ---------------------------------------------------------------------------
# 읽기
# ---------------------------------------------------------------------------
def _normalize(df: pd.DataFrame, sheet: str) -> pd.DataFrame:
    cols = SCHEMA.get(sheet, list(df.columns))
    for c in cols:
        if c not in df.columns:
            df[c] = np.nan
    extra = [c for c in df.columns if c not in cols]
    df = df[cols + extra]
    for c in df.columns:
        if c in NUMERIC_COLS:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        else:
            df[c] = df[c].astype(object).where(df[c].notna(), "")
    return df.reset_index(drop=True)


@st.cache_data(ttl=300, show_spinner=False)
def _read_all(version: int = 0) -> dict[str, pd.DataFrame]:
    """
    모든 시트를 '한 번의 호출'로 읽습니다.
    시트마다 따로 읽으면 화면 한 번 그릴 때 10회 가까이 호출돼
    Google Sheets 분당 한도(사용자당 60회 읽기)에 금방 걸립니다.
    """
    out: dict[str, pd.DataFrame] = {}
    if use_gsheets():
        sh = _spreadsheet()
        names = list(SCHEMA)
        resp = _retry(sh.values_batch_get, names)
        ranges = resp.get("valueRanges", [])
        for name, vr in zip(names, ranges):
            values = vr.get("values", []) or []
            if not values:
                out[name] = pd.DataFrame(columns=SCHEMA[name])
                continue
            header = [str(h) for h in values[0]]
            body = values[1:]
            # 헤더보다 넓은 데이터 행이 있으면(스키마 확장 직후) 헤더를 늘려 맞춘다
            width = max([len(header)] + [len(r) for r in body]) if body else len(header)
            schema_cols = SCHEMA.get(name, [])
            while len(header) < width:
                i = len(header)
                header.append(schema_cols[i] if i < len(schema_cols) else f"_extra{i}")
            rows = [list(r) + [""] * (width - len(r)) for r in body]
            df = pd.DataFrame(rows, columns=header).replace("", np.nan)
            out[name] = df.dropna(how="all")
    else:
        xl = pd.ExcelFile(EXCEL_FILE)
        for name in SCHEMA:
            out[name] = (pd.read_excel(EXCEL_FILE, sheet_name=name)
                         if name in xl.sheet_names else pd.DataFrame(columns=SCHEMA[name]))
    return out


def load_data(sheet: str) -> pd.DataFrame:
    try:
        raw = _read_all(st.session_state.get("_db_version", 0)).get(
            sheet, pd.DataFrame(columns=SCHEMA.get(sheet, [])))
    except QuotaError:
        st.error("⏳ Google Sheets 호출 한도(분당)를 넘었습니다. "
                 "1분쯤 기다렸다가 새로고침해 주세요. 데이터는 안전합니다.")
        st.stop()
    except Exception as e:
        st.error(f"'{sheet}' 시트를 읽지 못했습니다: {e}")
        raw = pd.DataFrame(columns=SCHEMA.get(sheet, []))
    return _normalize(raw.copy(), sheet)


def _bump():
    """캐시 무효화 — 쓰기 직후 호출."""
    st.session_state["_db_version"] = st.session_state.get("_db_version", 0) + 1
    _read_all.clear()


# ---------------------------------------------------------------------------
# 쓰기
# ---------------------------------------------------------------------------
def _to_cells(df: pd.DataFrame, cols: list[str]) -> list[list[str]]:
    out = df.reindex(columns=cols).copy()
    out = out.replace([np.inf, -np.inf], np.nan)
    return [["" if (pd.isna(v)) else str(v) for v in row]
            for row in out.itertuples(index=False, name=None)]


def write_sheet(sheet: str, df: pd.DataFrame) -> None:
    """시트 전체 덮어쓰기 (수정/삭제용)."""
    cols = SCHEMA.get(sheet, list(df.columns))
    if use_gsheets():
        ws = _retry(_spreadsheet().worksheet, sheet)
        _retry(ws.clear)
        _retry(ws.update, range_name="A1", values=[cols] + _to_cells(df, cols),
               value_input_option="USER_ENTERED")
    else:
        xl = pd.ExcelFile(EXCEL_FILE)
        data = {s: (df.reindex(columns=cols) if s == sheet
                    else pd.read_excel(EXCEL_FILE, sheet_name=s))
                for s in xl.sheet_names}
        _atomic_excel_write(data)
    _bump()


def append_rows(sheet: str, new_df: pd.DataFrame) -> None:
    """행 추가 (신규 등록용) — Sheets에서는 전체 재작성 없이 append."""
    if new_df is None or new_df.empty:
        return
    cols = SCHEMA.get(sheet, list(new_df.columns))
    if use_gsheets():
        ws = _retry(_spreadsheet().worksheet, sheet)
        _retry(ws.append_rows, _to_cells(new_df, cols), value_input_option="USER_ENTERED")
        _bump()
    else:
        old = load_data(sheet)
        write_sheet(sheet, pd.concat([old, new_df.reindex(columns=cols)],
                                     ignore_index=True))


def reset_db() -> None:
    """모든 시트를 비웁니다 (헤더만 남김). Athlete는 기본값 1행 복원."""
    for sheet, cols in SCHEMA.items():
        df = pd.DataFrame([DEFAULT_ATHLETE])[cols] if sheet == "Athlete" \
            else pd.DataFrame(columns=cols)
        write_sheet(sheet, df)


def export_excel_bytes() -> bytes:
    """현재 데이터를 엑셀 한 파일로 묶어 백업 다운로드."""
    import io
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        for sheet in SCHEMA:
            load_data(sheet).to_excel(w, sheet_name=sheet, index=False)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# 선수 프로필 헬퍼
# ---------------------------------------------------------------------------
def upsert_row(sheet: str, match: dict, row: dict) -> str:
    """match 조건에 맞는 줄이 있으면 그 줄을 고치고, 없으면 새로 추가합니다.

    아침 체크인처럼 '하루에 한 번 확정되는' 값은 같은 날 다시 넣으면 줄이 쌓이지
    않고 갱신되어야 합니다. 빈 값('')은 덮어쓰지 않습니다 — 일부만 다시 넣어도
    앞서 넣은 값이 지워지지 않게 하기 위해서입니다.
    반환값: "updated" 또는 "added".
    """
    df = load_data(sheet)
    if not df.empty:
        hit = pd.Series(True, index=df.index)
        for k, v in match.items():
            if k not in df.columns:
                hit = pd.Series(False, index=df.index)
                break
            hit &= df[k].astype(str).str.strip() == str(v).strip()
        if bool(hit.any()):
            _id_col = (SCHEMA.get(sheet) or [None])[0]   # 갱신 시 ID는 유지
            for col, v in row.items():
                if col in match or col == _id_col or v in ("", None):
                    continue
                if col not in df.columns:
                    df[col] = ""
                try:
                    df.loc[hit, col] = v
                except (TypeError, ValueError):
                    df[col] = df[col].astype(object)
                    df.loc[hit, col] = v
            write_sheet(sheet, df)
            return "updated"
    append_rows(sheet, pd.DataFrame([{**match, **row}]))
    return "added"


def get_athlete() -> dict:
    df = load_data("Athlete")
    if df.empty:
        return dict(DEFAULT_ATHLETE)
    row = df.iloc[0].to_dict()
    for k, v in DEFAULT_ATHLETE.items():
        if row.get(k) in ("", None) or (isinstance(row.get(k), float) and np.isnan(row[k])):
            row[k] = v
    return row


def save_athlete(row: dict) -> None:
    df = load_data("Athlete")
    base = dict(DEFAULT_ATHLETE)
    if not df.empty:
        base.update({k: v for k, v in df.iloc[0].to_dict().items() if v not in ("", None)})
    base.update(row)
    write_sheet("Athlete", pd.DataFrame([base]))
