
import io
import time
import pandas as pd
import streamlit as st
import altair as alt

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
    svc_date = st.date_input("Service date")
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
    attendee = st.text_input("Attendee name*", placeholder="Full name").strip()
with col2:
    household = st.text_input("Household size", value="1")
with col3:
    notes = st.text_input("Notes (optional)")

btn_add = st.button("Add")
if btn_add:
    if not attendee:
        st.warning("Please enter attendee name.")
    elif not svc_name or not svc_date:
        st.warning("Please set **Service date** and **Service name** in the sidebar.")
    else:
        row = {
            "Timestamp": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
            "ServiceDate": pd.to_datetime(svc_date).date().isoformat(),
            "ServiceName": svc_name,
            "Attendee": attendee,
            "Household": as_int(household, 1),
            "Notes": notes
        }
        st.session_state.df = pd.concat([st.session_state.df, pd.DataFrame([row])], ignore_index=True)
        st.success(f"Added: {attendee} ({row['Household']})")
        time.sleep(0.2)
        st.experimental_rerun()

# ---------------- Summary Cards --------------------------
st.markdown("### Summary")
df = st.session_state.df.copy()

if df.empty:
    st.info("No records yet. Add your first attendee above.")
else:
    svc_filter = (df["ServiceDate"] == (pd.to_datetime(svc_date).date().isoformat() if svc_date else "")) & \
                 (df["ServiceName"] == svc_name if svc_name else "")
    df_today = df[svc_filter]

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
    dfc["ServiceDate"] = pd.to_datetime(dfc["ServiceDate"])
    dfc["Household"] = dfc["Household"].astype(int)

    # Filters for dashboard
    fc1, fc2, fc3 = st.columns([2,2,2])
    with fc1:
        min_d, max_d = dfc["ServiceDate"].min(), dfc["ServiceDate"].max()
        dr = st.date_input("Date range", value=(min_d, max_d))
    with fc2:
        svc_opts = ["All"] + sorted(dfc["ServiceName"].dropna().unique().tolist())
        svc_pick = st.selectbox("Service", svc_opts, index=0)
    with fc3:
        roll = st.slider("Rolling mean (days)", 1, 8, 3)

    # Apply filters
    if isinstance(dr, tuple) and len(dr) == 2:
        dfc = dfc[(dfc["ServiceDate"] >= pd.to_datetime(dr[0])) &
                  (dfc["ServiceDate"] <= pd.to_datetime(dr[1]))]
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
    daily = (dfc.groupby("ServiceDate", as_index=False)
                .agg(people=("Household","sum"), entries=("Attendee","count")))
    if not daily.empty:
        daily["roll"] = daily["people"].rolling(roll).mean()
        line1 = alt.Chart(daily).mark_line().encode(
            x=alt.X("ServiceDate:T", title="Date"),
            y=alt.Y("people:Q", title="People")
        )
        line2 = alt.Chart(daily).mark_line(strokeDash=[6,3]).encode(
            x="ServiceDate:T",
            y="roll:Q",
            tooltip=["ServiceDate:T","people:Q","roll:Q"]
        )
        st.altair_chart((line1 + line2).properties(height=320).interactive(), use_container_width=True)
    else:
        st.info("No points in selected range.")

    # ---- Chart 2: Service mix (stacked area by service) ----
    svc_mix = (dfc.groupby(["ServiceDate","ServiceName"], as_index=False)
                  .agg(people=("Household","sum")))
    if not svc_mix.empty:
        area = alt.Chart(svc_mix).mark_area().encode(
            x="ServiceDate:T",
            y="people:Q",
            color=alt.Color("ServiceName:N", title="Service"),
            tooltip=["ServiceDate:T","ServiceName:N","people:Q"]
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
        log = log[log["ServiceDate"] == pd.to_datetime(f_date).date().isoformat()]
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
                time.sleep(0.2)
                st.experimental_rerun()

        if st.button("Delete row"):
            st.session_state.df = st.session_state.df.drop(index=idx).reset_index(drop=True)
            st.success("Row deleted.")
            time.sleep(0.2)
            st.experimental_rerun()

# ---------------- Export / Import ------------------------
st.markdown("### Data Export / Import")
colx, coly = st.columns([1,1])
with colx:
    if st.button("Download CSV"):
        csv = st.session_state.df.to_csv(index=False).encode("utf-8")
        st.download_button("Save attendance.csv", data=csv, file_name="attendance.csv", mime="text/csv", use_container_width=True)

with coly:
    if st.session_state.is_admin:
        up = st.file_uploader("Import CSV (same columns)", type=["csv"])
        if up is not None:
            try:
                newdf = pd.read_csv(up)
                required = ["Timestamp","ServiceDate","ServiceName","Attendee","Household","Notes"]
                if not all(c in newdf.columns for c in required):
                    st.error(f"CSV must include columns: {', '.join(required)}")
                else:
                    st.session_state.df = newdf[required].copy()
                    st.success("Imported CSV and replaced current data.")
                    time.sleep(0.2)
                    st.experimental_rerun()
            except Exception as e:
                st.error(f"Import failed: {e}")

st.caption("Tip: For durable storage (multi-device/multi-user), connect Google Sheets, Airtable, or a DB like Supabase. This demo uses in-memory + CSV.")
