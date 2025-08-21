import streamlit as st
import pandas as pd
import altair as alt
from datetime import datetime

st.set_page_config(page_title="Church Attendance", layout="wide")

# ---------- Functions ----------

@st.cache_data
def load_data():
    try:
        df = pd.read_csv("attendance.csv")
    except:
        df = pd.DataFrame(columns=[
            "Timestamp", "ServiceDate", "ServiceName", "Attendee", "Household", "Notes"
        ])
    return df

def save_data(df):
    df.to_csv("attendance.csv", index=False)

# ---------- Load data ----------
df = load_data()

# ---------- Sidebar Inputs ----------
st.sidebar.header("Service")
svc_date = st.sidebar.date_input("Service date", datetime.today())
svc_name = st.sidebar.text_input("Service name", "Sunday 1st Service")

st.sidebar.header("Admin")
admin_mode = st.sidebar.checkbox("Admin mode ON", value=True)

# ---------- Main Header ----------
st.title("⛪ Church Attendance Tracker")

# ---------- Attendance Entry ----------
st.subheader("Add Attendee")

with st.form("attendee_form"):
    first_name = st.text_input("First name")
    last_name = st.text_input("Last name")
    household = st.number_input("Household size", 1, 20, 1)
    notes = st.text_input("Notes (e.g. Title, visitor, etc.)")
    submit = st.form_submit_button("Add attendee")

if submit:
    attendee = f"{first_name.strip()} {last_name.strip()}"
    new_row = {
        "Timestamp": datetime.now().isoformat(),
        "ServiceDate": str(svc_date),
        "ServiceName": svc_name,
        "Attendee": attendee,
        "Household": household,
        "Notes": notes
    }
    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    save_data(df)
    st.success(f"Added {attendee}")

# ---------- Summary ----------
st.header("Summary")

svc_filter = (df["ServiceDate"] == str(svc_date)) & (df["ServiceName"] == svc_name)
today_df = df[svc_filter]

if not today_df.empty:
    st.metric("Unique attendees", today_df["Attendee"].nunique())
    st.metric("Total entries", len(today_df))
    st.metric("Total people", today_df["Household"].sum())
else:
    st.info("No records yet. Add your first attendee above.")

# ---------- Dashboard ----------
st.header("📊 Dashboard")

date_range = st.date_input("Date range", [df["ServiceDate"].min() if not df.empty else datetime.today(),
                                          df["ServiceDate"].max() if not df.empty else datetime.today()])
roll = st.slider("Rolling mean (days)", 1, 14, 3)

if not df.empty:
    dfc = df.copy()
    dfc["ServiceDate"] = pd.to_datetime(dfc["ServiceDate"], errors="coerce")
    dfc = dfc[(dfc["ServiceDate"] >= pd.to_datetime(date_range[0])) &
              (dfc["ServiceDate"] <= pd.to_datetime(date_range[1]))]

    # ---- Chart 1: People over time (line + rolling) ----
    dfc = dfc.copy()
    dfc["Date"] = dfc["ServiceDate"].dt.date

    daily = (dfc.groupby("Date", as_index=False)
               .agg(people=("Household", "sum"),
                    entries=("Attendee", "count")))

    if not daily.empty:
        daily["Date"] = pd.to_datetime(daily["Date"])
        daily["roll"] = daily["people"].rolling(roll).mean()

        line1 = alt.Chart(daily).mark_line().encode(
            x=alt.X("Date:T", title="Date"),
            y=alt.Y("people:Q", title="People"),
            tooltip=["Date:T", "people:Q"]
        )
        line2 = alt.Chart(daily).mark_line(strokeDash=[6, 3]).encode(
            x="Date:T",
            y="roll:Q",
            tooltip=["Date:T", "people:Q", "roll:Q"]
        )
        st.altair_chart((line1 + line2).properties(height=320).interactive(),
                        use_container_width=True)
    else:
        st.info("No points in selected range.")

    # ---- Chart 2: Service mix (stacked area by service) ----
    svc_mix = dfc.copy()
    svc_mix["Date"] = svc_mix["ServiceDate"].dt.date

    svc_mix = (svc_mix.groupby(["Date", "ServiceName"], as_index=False)
                     .agg(people=("Household", "sum")))

    if not svc_mix.empty:
        svc_mix["Date"] = pd.to_datetime(svc_mix["Date"])
        area = alt.Chart(svc_mix).mark_area().encode(
            x="Date:T",
            y="people:Q",
            color=alt.Color("ServiceName:N", title="Service"),
            tooltip=["Date:T", "ServiceName:N", "people:Q"]
        )
        st.altair_chart(area.properties(height=260).interactive(),
                        use_container_width=True)

# ---------- Attendance Log ----------
st.header("Attendance Log")

if admin_mode:
    st.dataframe(df.sort_values("Timestamp", ascending=False), use_container_width=True)

# ---------- Data Export / Import ----------
st.header("Data Export / Import")

c1, c2 = st.columns(2)
with c1:
    st.download_button("Download CSV", df.to_csv(index=False), "attendance_export.csv")

with c2:
    upload = st.file_uploader("Import CSV (same columns)", type="csv")
    if upload:
        new_df = pd.read_csv(upload)
        df = new_df
        save_data(df)
        st.success("Imported CSV and replaced current data.")
