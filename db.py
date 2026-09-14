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
    "Athlete": ["AthleteID", "Name", "BirthDate", "Sex", "HeightCm",
                "CurrentWeightKg", "StartWeightKg", "HRRest", "HRMax", "LTHR"],
    "Projects": ["ProjectID", "ProjectName", "Status", "GoalType", "GoalValue",
                 "StartDate", "TargetDate", "Description"],
    "Workouts": ["WorkoutID", "ProjectID", "WorkoutDate", "WorkoutType", "DistanceKm",
                 "DurationMinutes", "PaceSec", "AvgHeartRate", "MaxHeartRate", "AvgPower",
                 "AvgCadence", "ElevationGainM", "Temperature", "Surface", "ShoeID",
                 "AerobicTE", "AnaerobicTE", "PrimaryBenefit",
                 # 러닝 다이나믹스 (가민 활동 상세 CSV에서 자동 입력)
                 "Calories", "AvgGCTms", "AvgStrideM", "AvgVertOscCm", "AvgVertRatioPct",
                 "RPE", "LegFatigue", "CardioFatigue", "Notes", "SourceKey"],
    # ── 가민 일일 지표 (Connect 홈에서 매일 보이는 값) ──────────────────────
    "DailyStatus": ["StatusID", "StatusDate", "TrainingStatus", "AcuteLoad", "LoadRatio",
                    "RecoveryTimeHr", "TrainingReadiness", "BodyBattery",
                    "HRVStatus", "HRVms", "SleepScore", "RestingHR",
                    "IntensityMinutes", "Notes"],
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
    "Laps": ["LapID", "WorkoutID", "WorkoutDate", "WorkoutType", "LapNo",
             "CumMinutes", "DistanceKm", "DurationMinutes",
             "PaceSec", "AvgHeartRate", "MaxHeartRate", "AvgPower", "AvgCadence",
             "ElevGainM", "ElevLossM", "AvgGCTms", "AvgStrideM",
             "AvgVertOscCm", "AvgVertRatioPct", "Calories", "TempC"],
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
}

DEFAULT_ATHLETE = {
    "AthleteID": "ATH-001", "Name": "Runner", "BirthDate": "", "Sex": "M",
    "HeightCm": 180, "CurrentWeightKg": 85.0, "StartWeightKg": 115.0,
    "HRRest": 55, "HRMax": 190, "LTHR": 170,
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
