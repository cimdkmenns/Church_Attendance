import time
from datetime import datetime, date

import altair as alt
import pandas as pd
import streamlit as st

import gspread
from google.oauth2.service_account import Credentials
from gspread_dataframe import get_as_dataframe, set_with_dataframe

# ---------------------- APP CONFIG ----------------------
st.set_page_config(page_title="Church Attendance", layout="wide")

# Read settings from Streamlit secrets
ADMIN_PIN  = st.secrets.get("ADMIN_PIN", "1234")
SHEET_NAME = st.secrets.get("SHEET_NAME", "Church Attendance Tracker")  # <-- your sheet name
WORKSHEET  = "attendance"                                              # tab name inside the sheet

REQUIRED_COLS = ["Timestamp", "ServiceDate", "ServiceName", "Attendee", "Household", "Notes"]


# ---------------------- GOOGLE SHEETS HELPERS ----------------------
@st.cache_resource(show_spinner=True)
def get_gspread_client() -> gspread.Client:
    """Authorize a Google API client from the service-account JSON in secrets."""
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ],
    )
    return gspread.authorize(creds)

def open_or_create_ws(gc: gspread.Client):
    """Open the sheet & worksheet; create them (with headers) if missing."""
    try:
        sh = gc.open(SHEET_NAME)
    except gspread.SpreadsheetNotFound:
        sh = gc.create(SHEET_NAME)

    try:
        ws = sh.worksheet(WORKSHEET)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=WORKSHEET, rows=2000, cols=len(REQUIRED_COLS))
        ws.update([REQUIRED_COLS])  # header row
    return ws

def ensure_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Guarantee required columns in correct order and sensible types."""
    if df is None or df.empty:
        df = pd.DataFrame(columns=REQUIRED_COLS)
    for c in REQUIRED_COLS:
        if c not in df.columns:
            df[c] = "" if c != "Household" else 1
    df = df[REQUIRED_COLS].copy()
    df["Household"]  = pd.to_numeric(df["Household"], errors="coerce").fillna(1).astype(int)
    df["ServiceDate"] = df["ServiceDate"].astype(str)
    return df

@st.cache_data(ttl=10, show_spinner=False)
def load_df_from_sheet() -> pd.DataFrame:
    """Read entire worksheet into a DataFrame (cached briefly)."""
    gc = get_gspread_client()
    ws = open_or_create_ws(gc)
    df = get_as_dataframe(ws, evaluate_formulas=True, header=0, dtype=str)
    if df is None or df.empty or df.columns.tolist()[:1] != ["Timestamp"]:
        df = pd.DataFrame(columns=REQUIRED_COLS)
    df = df.dropna(how="all")  # drop fully blank rows
    return ensure_columns(df)

def save_df_to_sheet(df: pd.DataFrame) -> None:
    """Write the full DataFrame back to the worksheet and clear cache."""
    gc = get_gspread_client()
    ws = open_or_create_ws(gc)
    clean = ensure_columns(df)
    ws.clear()
    set_with_dataframe(ws, clean, include_index=False, include_column_header=True)
    load_df_from_sheet.clear()   # bust cache so subsequent reads refresh


# ---------------------- APP STATE ----------------------
if "is_admin" not in st.session_state:
    st.session_state.is_admin = False

st.title("🙏 Church Attendance Tracker")

# Sidebar — service controls + admin unlock
with st.sidebar:
    st.header("Service")
    svc_date = st.date_input("Service date", value=date.today())
    svc_name = st.text_input("Service name", value="Membership Import")

    st.markdown("---")
    st.header("Admin")
    if not st.session_state.is_admin:
        pin = st.text_input("Enter Admin PIN", type="password")
        if st.button("Unlock"):
            if pin == ADMIN_PIN:
                st.session_state.is_admin = True
                st.success("Admin unlocked.")
            else:
                st.error("Incorrect PIN.")
    else:
        st.success("Admin mode ON")
        if st.button("Lock admin"):
            st.session_state.is_admin = False

# Load current dataset (persistent from Google Sheets)
df = load_df_from_sheet()


# ---------------------- ADD ATTENDEE ----------------------
st.subheader("Add attendee")

c1, c2, c3 = st.columns([3, 3, 1])
with c1:
    first = st.text_input("First name").strip()
with c2:
    last  = st.text_input("Last name").strip()
with c3:
    household_str = st.text_input("Household size", value="1")

notes = st.text_input("Notes (e.g., Title, visitor, etc.)")

def to_int_safe(x, default=1):
    try:
        v = int(float(x))
        return v if v > 0 else default
    except Exception:
        return default

if st.button("Add attendee"):
    if not first or not last:
        st.warning("Please enter both first and last name.")
    elif not svc_name.strip():
        st.warning("Please enter a Service name.")
    else:
        new = {
            "Timestamp":  datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "ServiceDate": svc_date.isoformat(),
            "ServiceName":  svc_name,
            "Attendee":     f"{first} {last}".strip(),
            "Household":    to_int_safe(household_str, 1),
            "Notes":        notes,
        }
        df = pd.concat([df, pd.DataFrame([new])], ignore_index=True)
        save_df_to_sheet(df)
        st.success(f"Added: {new['Attendee']} (Household {new['Household']})")
        time.sleep(0.1)
        st.rerun()


# ---------------------- SUMMARY ----------------------
st.markdown("### Summary")

df = ensure_columns(df)
sel_date = svc_date.isoformat()
mask = (df["ServiceDate"] == sel_date) & ((df["ServiceName"] == svc_name) if svc_name.strip() else True)
df_today = df[mask].copy()

if df.empty:
    st.info("No records yet. Add an attendee or import a CSV.")
else:
    total_entries = len(df_today)
    total_people  = int(pd.to_numeric(df_today["Household"], errors="coerce").fillna(1).sum()) if not df_today.empty else 0

    m1, m2, m3 = st.columns(3)
    m1.metric("Entries (selected service)", total_entries)
    m2.metric("People (selected service)", total_people)
    m3.metric("All-time records", len(df))

    st.markdown("#### Totals per Service")
    summary = (
        df.assign(Household=pd.to_numeric(df["Household"], errors="coerce").fillna(1).astype(int))
          .groupby(["ServiceDate", "ServiceName"], as_index=False)
          .agg(entries=("Attendee","count"), people=("Household","sum"))
          .sort_values(["ServiceDate", "ServiceName"])
    )
    st.dataframe(summary, use_container_width=True)


# ---------------------- DASHBOARD ----------------------
st.markdown("## 📊 Dashboard")

if df.empty:
    st.info("No data to chart yet.")
else:
    dfc = df.copy()
    dfc["ServiceDate"] = pd.to_datetime(dfc["ServiceDate"], errors="coerce")
    dfc = dfc.dropna(subset=["ServiceDate"])
    dfc["Household"] = pd.to_numeric(dfc["Household"], errors="coerce").fillna(1).astype(int)

    fc1, fc2, fc3 = st.columns([2, 2, 2])
    with fc1:
        if not dfc.empty:
            dmin, dmax = dfc["ServiceDate"].min().date(), dfc["ServiceDate"].max().date()
        else:
            dmin = dmax = date.today()
        dr = st.date_input("Date range", value=(dmin, dmax))
    with fc2:
        svc_opts = ["All"] + sorted(dfc["ServiceName"].dropna().unique().tolist())
        svc_pick = st.selectbox("Service", svc_opts, index=0)
    with fc3:
        roll = st.slider("Rolling mean (days)", 1, 8, 3)

    # Apply filters
    if isinstance(dr, tuple) and len(dr) == 2:
        dfc = dfc[(dfc["ServiceDate"].dt.date >= dr[0]) & (dfc["ServiceDate"].dt.date <= dr[1])]
    if svc_pick != "All":
        dfc = dfc[dfc["ServiceName"] == svc_pick]

    # Chart 1: People over time (line + rolling)
    dfc = dfc.copy()
    dfc["Date"] = dfc["ServiceDate"].dt.date
    daily = (
        dfc.groupby("Date", as_index=False)
           .agg(people=("Household", "sum"),
                entries=("Attendee",  "count"))
    )

    if not daily.empty:
        daily["Date"] = pd.to_datetime(daily["Date"])
        daily["roll"] = daily["people"].rolling(roll).mean()

        line1 = alt.Chart(daily).mark_line().encode(
            x=alt.X("Date:T", title="Date"),
            y=alt.Y("people:Q", title="People"),
            tooltip=["Date:T", "people:Q"],
        )
        line2 = alt.Chart(daily).mark_line(strokeDash=[6, 3]).encode(
            x="Date:T", y="roll:Q",
            tooltip=["Date:T", "people:Q", "roll:Q"],
        )
        st.altair_chart((line1 + line2).properties(height=320).interactive(),
                        use_container_width=True)
    else:
        st.info("No points in selected range.")

    # Chart 2: Service mix (stacked area)
    svc_mix = dfc.copy()
    svc_mix["Date"] = svc_mix["ServiceDate"].dt.date
    svc_mix = (
        svc_mix.groupby(["Date", "ServiceName"], as_index=False)
               .agg(people=("Household", "sum"))
    )
    if not svc_mix.empty:
        svc_mix["Date"] = pd.to_datetime(svc_mix["Date"])
        area = alt.Chart(svc_mix).mark_area().encode(
            x="Date:T", y="people:Q",
            color=alt.Color("ServiceName:N", title="Service"),
            tooltip=["Date:T", "ServiceName:N", "people:Q"],
        )
        st.altair_chart(area.properties(height=260).interactive(),
                        use_container_width=True)

    # Chart 3: Top attendees (bar)
    topn = (
        dfc.groupby("Attendee", as_index=False)
           .agg(times=("Attendee", "count"), people=("Household", "sum"))
           .sort_values("people", ascending=False)
           .head(20)
    )
    if not topn.empty:
        bars = alt.Chart(topn).mark_bar().encode(
            x=alt.X("people:Q", title="People (incl. household)"),
            y=alt.Y("Attendee:N", sort="-x", title=None),
            tooltip=["Attendee:N", "times:Q", "people:Q"],
        )
        st.altair_chart(bars.properties(height=28 * len(topn) + 40),
                        use_container_width=True)


# ---------------------- LOG / EDIT ----------------------
st.markdown("### Attendance Log")

if df.empty:
    st.write("—")
else:
    f1, f2, f3 = st.columns(3)
    with f1:
        f_date = st.date_input("Filter by date", value=None, key="log_date")
    with f2:
        f_svc = st.text_input("Filter service name contains", key="log_svc")
    with f3:
        f_name = st.text_input("Filter attendee name contains", key="log_name")

    log = df.copy()
    if f_date:
        log = log[log["ServiceDate"] == f_date.isoformat()]
    if f_svc:
        log = log[log["ServiceName"].str.contains(f_svc, case=False, na=False)]
    if f_name:
        log = log[log["Attendee"].str.contains(f_name, case=False, na=False)]

    st.dataframe(log, use_container_width=True)

    if st.session_state.is_admin and not log.empty:
        st.markdown("#### Edit / Delete (Admin)")
        idx = st.number_input("Row index to edit/delete",
                              min_value=0, max_value=len(df) - 1, step=1, value=0)
        cA, cB, cC, cD = st.columns(4)
        with cA:
            new_name = st.text_input("New name", value=df.loc[idx, "Attendee"])
        with cB:
            new_house = st.text_input("New household", value=str(df.loc[idx, "Household"]))
        with cC:
            new_notes = st.text_input("New notes", value=df.loc[idx, "Notes"])
        with cD:
            if st.button("Apply edit"):
                df.loc[idx, "Attendee"]  = new_name.strip()
                df.loc[idx, "Household"] = to_int_safe(new_house, 1)
                df.loc[idx, "Notes"]     = new_notes
                save_df_to_sheet(df)
                st.success("Row updated.")
                time.sleep(0.1)
                st.rerun()

        if st.button("Delete row"):
            df = df.drop(index=idx).reset_index(drop=True)
            save_df_to_sheet(df)
            st.success("Row deleted.")
            time.sleep(0.1)
            st.rerun()


# ---------------------- IMPORT / EXPORT ----------------------
st.markdown("### Data Export / Import")

cX, cY = st.columns([1, 1])
with cX:
    csv_bytes = ensure_columns(df).to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download CSV",
        data=csv_bytes,
        file_name="attendance_export.csv",
        mime="text/csv",
        use_container_width=True,
    )

with cY:
    if st.session_state.is_admin:
        up = st.file_uploader("Import CSV (same columns)", type=["csv"])
        if up is not None:
            try:
                newdf = pd.read_csv(up)
                missing = [c for c in REQUIRED_COLS if c not in newdf.columns]
                if missing:
                    st.error(f"CSV must include: {', '.join(REQUIRED_COLS)}. Missing: {', '.join(missing)}")
                else:
                    save_df_to_sheet(newdf[REQUIRED_COLS].copy())
                    st.success("Imported CSV and saved to Google Sheets.")
                    time.sleep(0.1)
                    st.rerun()
            except Exception as e:
                st.error(f"Import failed: {e}")

st.caption("Data is stored in Google Sheets (worksheet: 'attendance'). Share this app URL with ushers; all updates persist.")
