import time
from datetime import datetime, date

import altair as alt
import pandas as pd
import streamlit as st

import gspread
from google.oauth2.service_account import Credentials
from gspread_dataframe import get_as_dataframe, set_with_dataframe
from gspread.exceptions import SpreadsheetNotFound, APIError

# ========================== APP CONFIG ==========================
st.set_page_config(page_title="Church Attendance", layout="wide")

ADMIN_PIN  = st.secrets.get("ADMIN_PIN", "1234")
SHEET_NAME = st.secrets.get("SHEET_NAME", "Church Attendance Tracker")

ATTENDANCE_WS = "attendance"
MEMBERS_WS    = "members"

ABSENCES_WS   = "absences"
ABSENCE_COLS  = ["Timestamp", "ServiceDate", "ServiceName", "Attendee", "Note"]

ATTENDANCE_COLS = ["Timestamp", "ServiceDate", "ServiceName", "Attendee", "Household", "Notes"]
MEMBER_COLS     = ["FirstName", "LastName", "Attendee", "Notes", "Active"]  # Active: 1/0

# ==================== GOOGLE SHEETS HELPERS =====================
@st.cache_resource(show_spinner=False)
def get_gspread_client() -> gspread.Client:
    # Make the private key robust to either real newlines or literal "\n"
    svc = dict(st.secrets["gcp_service_account"])
    pk = svc.get("private_key", "")
    if "\\n" in pk:
        svc["private_key"] = pk.replace("\\n", "\n")

    creds = Credentials.from_service_account_info(
        svc,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ],
    )
    return gspread.authorize(creds)

def open_or_create_spreadsheet(gc: gspread.Client):
    """Open the spreadsheet by title; create if missing (Drive API must be enabled)."""
    try:
        return gc.open(SHEET_NAME)
    except (SpreadsheetNotFound, APIError):
        return gc.create(SHEET_NAME)

def open_or_create_ws(sh, title: str, header: list[str]):
    """Open a worksheet or create it with headers."""
    try:
        ws = sh.worksheet(title)
    except Exception:
        ws = sh.add_worksheet(title=title, rows=3000, cols=max(8, len(header)))
        ws.update([header])
    return ws

def ensure_attendance_cols(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        df = pd.DataFrame(columns=ATTENDANCE_COLS)
    for c in ATTENDANCE_COLS:
        if c not in df.columns:
            df[c] = "" if c != "Household" else 1
    df = df[ATTENDANCE_COLS].copy()
    df["Household"] = pd.to_numeric(df["Household"], errors="coerce").fillna(1).astype(int)
    df["ServiceDate"] = df["ServiceDate"].astype(str)
    return df

def ensure_member_cols(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        df = pd.DataFrame(columns=MEMBER_COLS)
    for c in MEMBER_COLS:
        if c not in df.columns:
            df[c] = "" if c not in ("Active",) else 1
    # Compose Attendee consistently
    df["FirstName"] = df["FirstName"].fillna("").astype(str).str.strip()
    df["LastName"]  = df["LastName"].fillna("").astype(str).str.strip()
    df["Attendee"]  = (df["FirstName"] + " " + df["LastName"]).str.strip()
    df["Active"]    = pd.to_numeric(df["Active"], errors="coerce").fillna(1).astype(int)
    df = df[MEMBER_COLS].copy()
    return df

@st.cache_data(ttl=10, show_spinner=False)
def load_attendance() -> pd.DataFrame:
    gc = get_gspread_client()
    sh = open_or_create_spreadsheet(gc)
    ws = open_or_create_ws(sh, ATTENDANCE_WS, ATTENDANCE_COLS)
    df = get_as_dataframe(ws, evaluate_formulas=True, header=0, dtype=str)
    if df is None or df.empty or df.columns.tolist()[:1] != ["Timestamp"]:
        df = pd.DataFrame(columns=ATTENDANCE_COLS)
    df = df.dropna(how="all")
    return ensure_attendance_cols(df)

@st.cache_data(ttl=30, show_spinner=False)
def load_members() -> pd.DataFrame:
    gc = get_gspread_client()
    sh = open_or_create_spreadsheet(gc)
    ws = open_or_create_ws(sh, MEMBERS_WS, MEMBER_COLS)
    df = get_as_dataframe(ws, evaluate_formulas=True, header=0, dtype=str)
    if df is None or df.empty or ("FirstName" not in df.columns and "Attendee" not in df.columns):
        df = pd.DataFrame(columns=MEMBER_COLS)
    df = df.dropna(how="all")
    return ensure_member_cols(df)

def save_attendance(df: pd.DataFrame) -> None:
    gc = get_gspread_client()
    sh = open_or_create_spreadsheet(gc)
    ws = open_or_create_ws(sh, ATTENDANCE_WS, ATTENDANCE_COLS)
    clean = ensure_attendance_cols(df)
    ws.clear()
    set_with_dataframe(ws, clean, include_index=False, include_column_header=True)
    load_attendance.clear()

def save_members(df: pd.DataFrame) -> None:
    gc = get_gspread_client()
    sh = open_or_create_spreadsheet(gc)
    ws = open_or_create_ws(sh, MEMBERS_WS, MEMBER_COLS)
    clean = ensure_member_cols(df)
    ws.clear()
    set_with_dataframe(ws, clean, include_index=False, include_column_header=True)
    load_members.clear()

def ensure_absence_cols(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        df = pd.DataFrame(columns=ABSENCE_COLS)
    for c in ABSENCE_COLS:
        if c not in df.columns:
            df[c] = ""
    return df[ABSENCE_COLS].copy()

@st.cache_data(ttl=30, show_spinner=False)
def load_absences() -> pd.DataFrame:
    gc = get_gspread_client()
    sh = open_or_create_spreadsheet(gc)
    ws = open_or_create_ws(sh, ABSENCES_WS, ABSENCE_COLS)
    df = get_as_dataframe(ws, evaluate_formulas=True, header=0, dtype=str)
    if df is None or df.empty or ("Attendee" not in df.columns):
        df = pd.DataFrame(columns=ABSENCE_COLS)
    df = df.dropna(how="all")
    return ensure_absence_cols(df)

def save_absences(df: pd.DataFrame) -> None:
    gc = get_gspread_client()
    sh = open_or_create_spreadsheet(gc)
    ws = open_or_create_ws(sh, ABSENCES_WS, ABSENCE_COLS)
    clean = ensure_absence_cols(df)
    ws.clear()
    set_with_dataframe(ws, clean, include_index=False, include_column_header=True)
    load_absences.clear()
    
# ============================ UI STATE ==========================
if "is_admin" not in st.session_state:
    st.session_state.is_admin = False

st.title("Mansfield PIWC Attendance")

with st.sidebar:
    st.header("Service")
    svc_date = st.date_input("Service date", value=date.today())
    svc_name = st.text_input("Service name", value="Sunday 1st Service")

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

# Load persistent data
att = load_attendance()
mem = load_members()
abs_df = load_absences()

# ===================== ADD ATTENDEE (WITH ROSTER) =====================
st.subheader("Add attendee")

mode = st.radio(
    "Choose input mode",
    ["From roster", "Batch from roster", "Manual entry"],
    horizontal=True
)

col1, col2, col3 = st.columns([3, 3, 1])
notes_in = st.text_input("Notes (e.g., Title, visitor, etc.)", value="")

if mode == "From roster":
    # Use active members first; the selectbox is searchable when the list is long
    active_mem = mem[mem["Active"] == 1].copy()
    options = active_mem["Attendee"].dropna().sort_values().unique().tolist()
    selected = col1.selectbox("Search member (type to filter)", options, index=None, placeholder="Start typing a name…")
    col3_number = col3.number_input("Household size", min_value=1, value=1, step=1)

    # Quick view or add-if-missing
    with col2:
        st.write("")  # spacer
        if selected:
            mrow = active_mem[active_mem["Attendee"] == selected].iloc[0]
            st.success(f"Selected: {mrow['FirstName']} {mrow['LastName']}")
        else:
            st.info("Tip: If a person isn’t listed, switch to **Manual entry** and you can add them to the roster.")

    if st.button("Add attendee"):
        if not selected:
            st.warning("Pick a member from the roster first.")
        else:
            new = {
                "Timestamp":  datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "ServiceDate": svc_date.isoformat(),
                "ServiceName": svc_name.strip(),
                "Attendee":    selected,
                "Household":   int(col3_number),
                "Notes":       notes_in,
            }
            att = pd.concat([att, pd.DataFrame([new])], ignore_index=True)
            save_attendance(att)
            st.success(f"Checked in: {selected} (Household {int(col3_number)})")
            time.sleep(0.1)
            st.rerun()

elif mode == "Batch from roster":
    # Build roster of active members
    active_mem = mem[mem["Active"] == 1].copy()
    roster = (
        active_mem["Attendee"]
        .dropna().astype(str).str.strip()
        .sort_values().unique().tolist()
    )

    # Optional quick filter
    q = st.text_input("Filter roster (optional)", placeholder="Type to filter names…")
    if q:
        roster = [n for n in roster if q.lower() in n.lower()]

    if not roster:
        st.info("No matching names. Clear the filter or add members to the roster.")
    else:
        # Editable table: select multiple; set per-person household & notes
        base = pd.DataFrame({
            "Attendee": roster,
            "Household": 1,
            "Notes": "",
            "Select": False,
        })

        edited = st.data_editor(
            base,
            use_container_width=True,
            hide_index=True,
            num_rows="fixed",
            column_config={
                "Select": st.column_config.CheckboxColumn("Select"),
                "Attendee": st.column_config.TextColumn("Attendee", disabled=True),
                "Household": st.column_config.NumberColumn("Household", min_value=1, step=1),
                "Notes": st.column_config.TextColumn("Notes (optional)"),
            },
        )

        chosen = edited[edited["Select"]].copy()

        # Batch add button
        add_label = f"Add {len(chosen)} selected attendee(s)" if len(chosen) else "Add selected attendee(s)"
        if st.button(add_label, use_container_width=True):
            if chosen.empty:
                st.warning("Select at least one person in the list.")
            else:
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                def to_int(x):
                    try:
                        v = int(float(x));  return v if v > 0 else 1
                    except:
                        return 1
                new_rows = [{
                    "Timestamp":  ts,
                    "ServiceDate": svc_date.isoformat(),
                    "ServiceName": svc_name.strip(),
                    "Attendee":    r["Attendee"],
                    "Household":   to_int(r["Household"]),
                    "Notes":       str(r.get("Notes", "")).strip(),
                } for _, r in chosen.iterrows()]

                att = pd.concat([att, pd.DataFrame(new_rows)], ignore_index=True)
                save_attendance(att)
                st.success(f"Checked in {len(new_rows)} attendee(s).")
                time.sleep(0.1); st.rerun()

elif mode == "Manual entry":
    first = col1.text_input("First name").strip()
    last  = col2.text_input("Last name").strip()
    hh    = col3.number_input("Household size", min_value=1, value=1, step=1)

    add_to_roster = st.checkbox("Also add to roster", value=True,
                                help="If checked, this person is saved to the Members list for future autocomplete.")

    if st.button("Add attendee"):
        if not first or not last:
            st.warning("Please enter both first and last name.")
        elif not svc_name.strip():
            st.warning("Please enter a Service name.")
        else:
            full = f"{first} {last}".strip()
            new = {
                "Timestamp":  datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "ServiceDate": svc_date.isoformat(),
                "ServiceName": svc_name.strip(),
                "Attendee":    full,
                "Household":   int(hh),
                "Notes":       notes_in,
            }
            att = pd.concat([att, pd.DataFrame([new])], ignore_index=True)
            save_attendance(att)

            if add_to_roster:
                # Only add if not already present (case-insensitive)
                exists = (mem["Attendee"].str.lower() == full.lower()).any()
                if not exists:
                    mem = pd.concat(
                        [mem, pd.DataFrame([{
                            "FirstName": first, "LastName": last,
                            "Attendee": full, "Notes": "", "Active": 1
                        }])],
                        ignore_index=True
                    )
                    save_members(mem)

            st.success(f"Checked in: {full} (Household {int(hh)})")
            time.sleep(0.1)
            st.rerun()

# ============================ SUMMARY =============================
st.markdown("### Summary")
att = ensure_attendance_cols(att)
sel_date = svc_date.isoformat()
mask = (att["ServiceDate"] == sel_date) & ((att["ServiceName"] == svc_name.strip()) if svc_name.strip() else True)
att_today = att[mask].copy()

if att.empty:
    st.info("No records yet. Add an attendee or import a CSV.")
else:
    total_entries = len(att_today)
    total_people  = int(pd.to_numeric(att_today["Household"], errors="coerce").fillna(1).sum()) if not att_today.empty else 0
    c1, c2, c3 = st.columns(3)
    c1.metric("Entries (selected service)", total_entries)
    c2.metric("People (selected service)", total_people)
    c3.metric("All-time records", len(att))

    st.markdown("#### Totals per Service")
    summary = (
        att.assign(Household=pd.to_numeric(att["Household"], errors="coerce").fillna(1).astype(int))
           .groupby(["ServiceDate","ServiceName"], as_index=False)
           .agg(entries=("Attendee","count"), people=("Household","sum"))
           .sort_values(["ServiceDate","ServiceName"])
    )
    st.dataframe(summary, use_container_width=True)

# ====================== ABSENTEES & REASONS (ADMIN) ======================
st.markdown("### Absentees & Reasons (Admin)")

if not st.session_state.is_admin:
    st.info("Unlock Admin mode in the sidebar to manage absentees.")
else:
    # Active roster (Attendee names) vs attendees for the selected service/date
    active_attendees = (
        mem[mem["Active"] == 1]["Attendee"]
        .dropna().astype(str).str.strip().unique().tolist()
    )

    present_today = (
        att_today["Attendee"].dropna().astype(str).str.strip().unique().tolist()
        if not att_today.empty else []
    )

    missing = sorted(set(active_attendees) - set(present_today))

    cA, cB = st.columns([2, 1])
    with cA:
        st.write(
            f"**Service:** {svc_name.strip() or '(no name)'}  |  "
            f"**Date:** {svc_date.isoformat()}  |  "
            f"**Active roster:** {len(active_attendees)}  |  "
            f"**Present:** {len(present_today)}  |  "
            f"**Absent:** {len(missing)}"
        )

    if st.button("Find absentees for this service"):
        if not missing:
            st.success("No absentees — everyone on the active roster attended 🎉")
        else:
            st.info("Enter a note for any absent member (e.g., traveling, unwell, work). Leave blank to skip.")
            notes_inputs = {}
            for name in missing:
                key = f"abs_note__{svc_date.isoformat()}__{svc_name.strip()}__{name}"
                notes_inputs[name] = st.text_input(f"Reason / note — {name}", key=key)

            if st.button("Save absence notes"):
                current_abs = load_absences()
                new_rows = []
                ts_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                for name, note in notes_inputs.items():
                    note = (note or "").strip()
                    if note:
                        new_rows.append({
                            "Timestamp":  ts_now,
                            "ServiceDate": svc_date.isoformat(),
                            "ServiceName": svc_name.strip(),
                            "Attendee":    name,
                            "Note":        note,
                        })
                if new_rows:
                    updated = pd.concat([current_abs, pd.DataFrame(new_rows)], ignore_index=True)
                    save_absences(updated)
                    st.success(f"Saved {len(new_rows)} absence note(s).")
                    time.sleep(0.1); st.rerun()
                else:
                    st.warning("No notes entered — nothing to save.")

    # Show saved notes for this service/date
    svc_abs = abs_df[
        (abs_df["ServiceDate"] == svc_date.isoformat()) &
        ((abs_df["ServiceName"] == svc_name.strip()) if svc_name.strip() else True)
    ].copy()

    if not svc_abs.empty:
        st.markdown("#### Notes saved for this service")
        st.dataframe(svc_abs.sort_values("Attendee"), use_container_width=True)
    else:
        st.caption("No saved absence notes for the selected service yet.")
        
# =========================== DASHBOARD ===========================
st.markdown("## 📊 Dashboard")
if att.empty:
    st.info("No data to chart yet.")
else:
    dfc = att.copy()
    dfc["ServiceDate"] = pd.to_datetime(dfc["ServiceDate"], errors="coerce")
    dfc = dfc.dropna(subset=["ServiceDate"])
    dfc["Household"] = pd.to_numeric(dfc["Household"], errors="coerce").fillna(1).astype(int)

    fc1, fc2, fc3 = st.columns([2,2,2])
    with fc1:
        dmin, dmax = (dfc["ServiceDate"].min().date(), dfc["ServiceDate"].max().date()) if not dfc.empty else (date.today(), date.today())
        dr = st.date_input("Date range", value=(dmin, dmax))
    with fc2:
        svc_opts = ["All"] + sorted(dfc["ServiceName"].dropna().unique().tolist())
        svc_pick = st.selectbox("Service", svc_opts, index=0)
    with fc3:
        roll = st.slider("Rolling mean (days)", 1, 8, 3)

    if isinstance(dr, tuple) and len(dr) == 2:
        dfc = dfc[(dfc["ServiceDate"].dt.date >= dr[0]) & (dfc["ServiceDate"].dt.date <= dr[1])]
    if svc_pick != "All":
        dfc = dfc[dfc["ServiceName"] == svc_pick]

    dfc = dfc.copy()
    dfc["Date"] = dfc["ServiceDate"].dt.date
    daily = dfc.groupby("Date", as_index=False).agg(people=("Household","sum"), entries=("Attendee","count"))
    if not daily.empty:
        daily["Date"] = pd.to_datetime(daily["Date"])
        daily["roll"] = daily["people"].rolling(roll).mean()
        line1 = alt.Chart(daily).mark_line().encode(x="Date:T", y=alt.Y("people:Q", title="People"), tooltip=["Date:T","people"])
        line2 = alt.Chart(daily).mark_line(strokeDash=[6,3]).encode(x="Date:T", y="roll:Q", tooltip=["Date:T","roll"])
        st.altair_chart((line1+line2).properties(height=320).interactive(), use_container_width=True)

    svc_mix = dfc.groupby(["Date","ServiceName"], as_index=False).agg(people=("Household","sum"))
    if not svc_mix.empty:
        svc_mix["Date"] = pd.to_datetime(svc_mix["Date"])
        area = alt.Chart(svc_mix).mark_area().encode(x="Date:T", y="people:Q", color="ServiceName:N", tooltip=["Date:T","ServiceName","people"])
        st.altair_chart(area.properties(height=260).interactive(), use_container_width=True)

    topn = (dfc.groupby("Attendee", as_index=False)
              .agg(times=("Attendee","count"), people=("Household","sum"))
              .sort_values("people", ascending=False).head(20))
    if not topn.empty:
        bars = alt.Chart(topn).mark_bar().encode(
            x=alt.X("people:Q", title="People (incl. household)"),
            y=alt.Y("Attendee:N", sort="-x", title=None),
            tooltip=["Attendee","times","people"],
        )
        st.altair_chart(bars.properties(height=28*len(topn)+40), use_container_width=True)

# =========================== LOG / EDIT ==========================
st.markdown("### Attendance Log")
if att.empty:
    st.write("—")
else:
    f1, f2, f3 = st.columns(3)
    with f1:
        f_date = st.date_input("Filter by date", value=None, key="log_date")
    with f2:
        f_svc = st.text_input("Filter service name contains", key="log_svc")
    with f3:
        f_name = st.text_input("Filter attendee name contains", key="log_name")

    log = att.copy()
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
                              min_value=0, max_value=len(att) - 1, step=1, value=0)
        cA, cB, cC, cD = st.columns(4)
        with cA:
            new_name = st.text_input("New name", value=att.loc[idx, "Attendee"])
        with cB:
            new_house = st.text_input("New household", value=str(att.loc[idx, "Household"]))
        with cC:
            new_notes = st.text_input("New notes", value=att.loc[idx, "Notes"])
        with cD:
            if st.button("Apply edit"):
                def to_int(x):
                    try:
                        v = int(float(x));  return v if v > 0 else 1
                    except:
                        return 1
                att.loc[idx, "Attendee"]  = new_name.strip()
                att.loc[idx, "Household"] = to_int(new_house)
                att.loc[idx, "Notes"]     = new_notes
                save_attendance(att)
                st.success("Row updated.")
                time.sleep(0.1); st.rerun()

        if st.button("Delete row"):
            att = att.drop(index=idx).reset_index(drop=True)
            save_attendance(att)
            st.success("Row deleted.")
            time.sleep(0.1); st.rerun()

# ======================= IMPORT / EXPORT (SIDEBAR) =========================
with st.sidebar:
    if st.session_state.is_admin:
        st.markdown("### 📂 Data Export / Import")

        csv_att = ensure_attendance_cols(att).to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Download attendance CSV", data=csv_att,
                           file_name="attendance_export.csv", mime="text/csv")

        st.markdown("**Import attendance CSV**")
        up = st.file_uploader("Upload attendance CSV",
                              type=["csv"], key="up_att", label_visibility="collapsed")
        if up is not None:
            try:
                newdf = pd.read_csv(up)
                missing = [c for c in ATTENDANCE_COLS if c not in newdf.columns]
                if missing:
                    st.error(f"CSV must include: {', '.join(ATTENDANCE_COLS)}. Missing: {', '.join(missing)}")
                else:
                    save_attendance(newdf[ATTENDANCE_COLS].copy())
                    st.success("Imported attendance and saved to Google Sheets.")
                    time.sleep(0.1); st.rerun()
            except Exception as e:
                st.error(f"Import failed: {e}")

        st.markdown("---")
        st.markdown("**Members roster**")

        csv_mem = ensure_member_cols(mem).to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Download roster CSV", data=csv_mem,
                           file_name="members_export.csv", mime="text/csv")

        upm = st.file_uploader("Upload roster CSV",
                               type=["csv"], key="up_mem", label_visibility="collapsed")
        if upm is not None:
            try:
                mdf = pd.read_csv(upm, dtype=str)
                # Flexible: accept Attendee or First/Last; normalize
                if "Attendee" in mdf.columns and ("FirstName" not in mdf.columns or "LastName" not in mdf.columns):
                    split = mdf["Attendee"].fillna("").astype(str).str.strip().str.split(" ", n=1, expand=True)
                    mdf["FirstName"] = split[0].fillna("")
                    mdf["LastName"]  = split[1].fillna("")
                mdf["Active"] = pd.to_numeric(mdf.get("Active", 1), errors="coerce").fillna(1).astype(int)
                mdf["Notes"]  = mdf.get("Notes", "")
                mdf = ensure_member_cols(mdf)
                save_members(mdf)
                st.success("Roster imported.")
                time.sleep(0.1); st.rerun()
            except Exception as e:
                st.error(f"Roster import failed: {e}")

        st.markdown("---")
        with st.expander("Export absences (optional)"):
            abs_all = load_absences()
            if abs_all.empty:
                st.caption("No absences saved yet.")
            else:
                csv_abs = abs_all.to_csv(index=False).encode("utf-8")
                st.download_button(
                    "⬇️ Download absences CSV",
                    data=csv_abs,
                    file_name="absences_export.csv",
                    mime="text/csv",
                )
                
# ===================== ADMIN: DELETE SERVICE RECORDS (SIDEBAR) =====================
if st.session_state.is_admin and not att.empty:
    st.sidebar.markdown("---")
    st.sidebar.header("🗑️ Delete Service Records")

    # Build list of unique services (date + name)
    service_list = (
        att[["ServiceDate", "ServiceName"]]
        .drop_duplicates()
        .sort_values(["ServiceDate", "ServiceName"])
    )

    if not service_list.empty:
        options = [
            f"{r.ServiceDate} — {r.ServiceName}"
            for r in service_list.itertuples(index=False)
        ]

        sel_service = st.sidebar.selectbox(
            "Select service to delete",
            ["--"] + options,
            index=0,
            help="This will remove ALL rows that match the selected date + service.",
        )

        confirm = st.sidebar.checkbox(
            "⚠️ Confirm delete",
            value=False,
            key="confirm_del_service"
        )

        if sel_service != "--" and confirm and st.sidebar.button("Delete selected service"):
            sdate, sname = sel_service.split(" — ", 1)
            before = len(att)
            att = att[
                ~((att["ServiceDate"] == sdate) & (att["ServiceName"] == sname))
            ].reset_index(drop=True)
            save_attendance(att)
            st.sidebar.success(f"Deleted {before - len(att)} rows for {sdate} — {sname}")
            time.sleep(0.1)
            st.rerun()
    else:
        st.sidebar.info("No services found to delete.")

st.caption("Data is stored in Google Sheets. Tabs: 'attendance' and 'members'. Share the Sheet with your service account as Editor.")
