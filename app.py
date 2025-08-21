import io
import time
import pandas as pd
import streamlit as st
import altair as alt
from datetime import datetime, date

# ---------------------- CONFIG ----------------------
st.set_page_config(page_title="Church Attendance", layout="wide")
ADMIN_PIN = st.secrets.get("ADMIN_PIN", "1234")  # override on Streamlit Cloud via Secrets
# ---------------------------------------------------

@st.cache_data
def load_blank_df():
    return pd.DataFrame(
        columns=["Timestamp","ServiceDate","ServiceName","Attendee","Household","Notes"]
    )

def as_int(x, default=1):
    try:
        v = int(x)
        return v if v > 0 else default
    except Exception:
        return default

# Session state store
if "df" not in st.session_state:
    st.session_state.df = load_blank_df().copy()
if "is_admin" not in st.session_state:
    st.session_state.is_admin = False

st.title("🙏 Church Attendance Register")

# ---------------- Sidebar: Service + Admin ---------------
with st.sidebar:
    st.header("Service")
    svc_date = st.date_input("Service date", value=date.today())
    svc_name = st.text_input("Service name", placeholder="e.g., Sunday 1st Service")

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

# ---------------- Add Attendance -------------------------
st.subheader("Add attendee")
col1, col2, col3 = st.columns([3,1,3])
with col1:
    attendee_first = st.text_input("First name", placeholder="First name").strip()
with col2:
    attendee_last = st.text_input("Last name", placeholder="Last name").strip()
with col3:
    notes = st.text_input("Notes (e.g., Title, comments)")

household_str = st.text_input("Household size", value="1")
btn_add = st.button("Add")
if btn_add:
    if not attendee_first or not attendee_last:
        st.warning("Please enter both first and last name.")
    elif not svc_date or not (svc_name or "").strip():
        st.warning("Please set **Service date** and **Service name** in the sidebar.")
    else:
        full_name = f"{attendee_first} {attendee_last}".strip()
        row = {
            "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "ServiceDate": svc_date.isoformat(),
            "ServiceName": svc_name,
            "Attendee": full_name,
            "Household": as_int(household_str, 1),
            "Notes": notes
        }
        st.session_state.df = pd.concat([st.session_state.df, pd.DataFrame([row])], ignore_index=True)
        st.success(f"Added: {full_name} (Household {row['Household']})")
        time.sleep(0.1)
        st.rerun()

# ---------------- Summary Cards --------------------------
st.markdown("### Summary")
df = st.session_state.df.copy()

# ---- Ensure correct types for filtering (fixes TypeError) ----
# Coerce ServiceDate to date ISO strings (yyyy-mm-dd)
if "ServiceDate" in df.columns:
    # Try to parse; if already strings, this is no-op
    try:
        parsed = pd.to_datetime(df["ServiceDate"], errors="coerce")
        df["ServiceDate"] = parsed.dt.date.astype(str)
    except Exception:
        df["ServiceDate"] = df["ServiceDate"].astype(str)

selected_date = svc_date.isoformat() if isinstance(svc_date, date) else str(svc_date)
name_pred = (df["ServiceName"] == svc_name) if (svc_name or "").strip() else True
date_pred = (df["ServiceDate"] == selected_date) if selected_date else True
svc_filter = date_pred & name_pred
df_today = df[svc_filter].copy()

if df.empty:
    st.info("No records yet. Add your first attendee above or import a CSV.")
else:
    total_entries = len(df_today)
    total_people = df_today["Household"].astype(int).sum() if not df_today.empty else 0

    c1, c2, c3 = st.columns(3)
    c1.metric("Entries (selected service)", f"{total_entries}")
    c2.metric("People (selected service)", f"{total_people}")
    c3.metric("All-time records", f"{len(df)}")

    st.markdown("#### Totals per Service")
    summary = (df.assign(Household=df["Household"].astype(int))
                 .groupby(["ServiceDate","ServiceName"], as_index=False)
                 .agg(entries=("Attendee","count"), people=("Household","sum"))
                 .sort_values(["ServiceDate","ServiceName"]))
    st.dataframe(summary, use_container_width=True)

# ---------------- Dashboard ------------------------------
st.markdown("## 📊 Dashboard")

if df.empty:
    st.info("No data to chart yet.")
else:
    # Clean types
    dfc = df.copy()
    dfc["ServiceDate"] = pd.to_datetime(dfc["ServiceDate"], errors="coerce")
    dfc = dfc.dropna(subset=["ServiceDate"])
    dfc["Household"] = pd.to_numeric(dfc["Household"], errors="coerce").fillna(1).astype(int)

    # Filters for dashboard
    fc1, fc2, fc3 = st.columns([2,2,2])
    with fc1:
        if not dfc.empty:
            min_d, max_d = dfc["ServiceDate"].min().date(), dfc["ServiceDate"].max().date()
        else:
            min_d, max_d = date.today(), date.today()
        dr = st.date_input("Date range", value=(min_d, max_d))
    with fc2:
        svc_opts = ["All"] + sorted(dfc["ServiceName"].dropna().unique().tolist())
        svc_pick = st.selectbox("Service", svc_opts, index=0)
    with fc3:
        roll = st.slider("Rolling mean (days)", 1, 8, 3)

    # Apply filters
    if isinstance(dr, tuple) and len(dr) == 2:
        dfc = dfc[(dfc["ServiceDate"].dt.date >= dr[0]) &
                  (dfc["ServiceDate"].dt.date <= dr[1])]
    if svc_pick != "All":
        dfc = dfc[dfc["ServiceName"] == svc_pick]

    # KPI row
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Unique attendees", dfc["Attendee"].nunique())
    k2.metric("Total entries", len(dfc))
    k3.metric("Total people", int(dfc["Household"].sum()))
    avg_house = (dfc["Household"].sum() / max(len(dfc),1))
    k4.metric("Avg household per entry", f"{avg_house:.2f}")

    # ---- Chart 1: People over time (line + rolling) ----
    daily = (dfc.groupby(dfc["ServiceDate"].dt.date, as_index=False)
                .agg(people=("Household","sum"), entries=("Attendee","count"))
                .rename(columns={"ServiceDate":"Date"}))
    if not daily.empty:
        daily["Date"] = pd.to_datetime(daily["Date"])
        daily["roll"] = daily["people"].rolling(roll).mean()
        line1 = alt.Chart(daily).mark_line().encode(
            x=alt.X("Date:T", title="Date"),
            y=alt.Y("people:Q", title="People")
        )
        line2 = alt.Chart(daily).mark_line(strokeDash=[6,3]).encode(
            x="Date:T",
            y="roll:Q",
            tooltip=["Date:T","people:Q","roll:Q"]
        )
        st.altair_chart((line1 + line2).properties(height=320).interactive(), use_container_width=True)
    else:
        st.info("No points in selected range.")

    # ---- Chart 2: Service mix (stacked area by service) ----
    svc_mix = (dfc.groupby([dfc["ServiceDate"].dt.date,"ServiceName"], as_index=False)
                  .agg(people=("Household","sum"))
                  .rename(columns={"ServiceDate":"Date"}))
    if not svc_mix.empty:
        svc_mix["Date"] = pd.to_datetime(svc_mix["Date"])
        area = alt.Chart(svc_mix).mark_area().encode(
            x="Date:T",
            y="people:Q",
            color=alt.Color("ServiceName:N", title="Service"),
            tooltip=["Date:T","ServiceName:N","people:Q"]
        )
        st.altair_chart(area.properties(height=260).interactive(), use_container_width=True)

    # ---- Chart 3: Top attendees (bar) ----
    topn = (dfc.groupby("Attendee", as_index=False)
               .agg(times=("Attendee","count"), people=("Household","sum"))
               .sort_values("people", ascending=False)
               .head(20))
    if not topn.empty:
        bars = alt.Chart(topn).mark_bar().encode(
            x=alt.X("people:Q", title="People (incl. household)"),
            y=alt.Y("Attendee:N", sort="-x", title=None),
            tooltip=["Attendee:N","times:Q","people:Q"]
        )
        st.altair_chart(bars.properties(height=28*len(topn) + 40), use_container_width=True)

# ---------------- Log / Edit -----------------------------
st.markdown("### Attendance Log")
if df.empty:
    st.write("—")
else:
    fcol1, fcol2, fcol3 = st.columns(3)
    with fcol1:
        f_date = st.date_input("Filter by date", value=None, key="log_date")
    with fcol2:
        f_svc = st.text_input("Filter service name contains", key="log_svc")
    with fcol3:
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
        idx = st.number_input("Row index to edit/delete", min_value=0, max_value=len(df)-1 if len(df)>0 else 0, step=1, value=0)
        colA, colB, colC, colD = st.columns(4)
        with colA:
            new_name = st.text_input("New name", value=df.loc[idx,"Attendee"])
        with colB:
            new_house = st.text_input("New household", value=str(df.loc[idx,"Household"]))
        with colC:
            new_notes = st.text_input("New notes", value=df.loc[idx,"Notes"])
        with colD:
            if st.button("Apply edit"):
                st.session_state.df.loc[idx, "Attendee"] = new_name.strip()
                st.session_state.df.loc[idx, "Household"] = as_int(new_house, 1)
                st.session_state.df.loc[idx, "Notes"] = new_notes
                st.success("Row updated.")
                time.sleep(0.1)
                st.rerun()

        if st.button("Delete row"):
            st.session_state.df = st.session_state.df.drop(index=idx).reset_index(drop=True)
            st.success("Row deleted.")
            time.sleep(0.1)
            st.rerun()

# ---------------- Export / Import ------------------------
st.markdown("### Data Export / Import")
colx, coly = st.columns([1,1])
with colx:
    csv = st.session_state.df.to_csv(index=False).encode("utf-8")
    st.download_button("Save attendance.csv", data=csv, file_name="attendance.csv", mime="text/csv", use_container_width=True)

with coly:
    if st.session_state.is_admin:
        up = st.file_uploader("Import CSV (same columns)", type=["csv"])
        if up is not None:
            try:
                newdf = pd.read_csv(up)
                required = ["Timestamp","ServiceDate","ServiceName","Attendee","Household","Notes"]
                missing = [c for c in required if c not in newdf.columns]
                if missing:
                    st.error(f"CSV must include columns: {', '.join(required)}. Missing: {', '.join(missing)}")
                else:
                    st.session_state.df = newdf[required].copy()
                    st.success("Imported CSV and replaced current data.")
                    time.sleep(0.1)
                    st.rerun()
            except Exception as e:
                st.error(f"Import failed: {e}")

st.caption("Tip: For durable storage (multi-device/multi-user), connect Google Sheets, Airtable, or a DB like Supabase. This demo uses in-memory + CSV.")
