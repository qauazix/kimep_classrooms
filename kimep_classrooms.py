import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px

# -------------------------------------------------------------
# ---------------- SMART TIME PARSER (AUTO FIX) ---------------
# -------------------------------------------------------------

def to_minutes(t):
    h, m = t.split(":")
    return int(h) * 60 + int(m)

def parse_interval_smart(interval: str):
    if not isinstance(interval, str):
        return None, None, False, "Non-string interval"

    interval = interval.replace(" ", "")
    if "-" not in interval:
        return None, None, False, "Missing dash"

    if any(x in interval.upper() for x in ["ONLINE", "TBA"]):
        return None, None, False, "Non-time entry"

    try:
        start_str, end_str = interval.split("-", 1)
        start = to_minutes(start_str)
        end = to_minutes(end_str)
    except:
        return None, None, False, "Bad time format"

    fixed = False
    if end <= start:
        end += 720
        fixed = True
    if end <= start:
        end += 1440
        fixed = True

    duration = end - start
    if duration > 300:
        return start, end, False, f"Duration too long ({duration} min)"

    return start, end, fixed, ""


# -------------------------------------------------------------
# ------------------- SMART DAY DECODER -----------------------
# -------------------------------------------------------------

DAY_TOKEN_MAP = {
    "M": "Mon",
    "T": "Tue",
    "W": "Wed",
    "Th": "Thu",
    "F": "Fri",
    "St": "Sat",
    "Sn": "Sun"
}

def decode_days(code: str):
    if not isinstance(code, str):
        return []
    code = code.strip()

    tokens = []
    i = 0
    while i < len(code):
        if i+2 <= len(code) and code[i:i+2] in ("Th", "St", "Sn"):
            tokens.append(code[i:i+2])
            i += 2
        else:
            tokens.append(code[i])
            i += 1

    days = [DAY_TOKEN_MAP[t] for t in tokens if t in DAY_TOKEN_MAP]
    return list(dict.fromkeys(days))  # remove duplicates keep order


# -------------------------------------------------------------
# ---------------------- PREPROCESS DATA -----------------------
# -------------------------------------------------------------

def preprocess_data(df):
    df = df.copy()

    if "Days" not in df.columns or "Class_Times" not in df.columns or "Hall" not in df.columns:
        st.error("Dataset must contain columns: Days, Class_Times, Hall")
        return pd.DataFrame(), pd.DataFrame()

    df["Days"] = df["Days"].astype(str).str.strip()
    df["Hall"] = df["Hall"].astype(str).fillna("UNKNOWN")

    df["Class_Times"] = (
        df["Class_Times"]
        .astype(str)
        .str.replace("–", "-", regex=False)
        .str.replace("—", "-", regex=False)
        .str.replace(".", ":", regex=False)
        .str.replace(" ", "")
    )

    parsed = df["Class_Times"].apply(lambda x: pd.Series(parse_interval_smart(x)))
    parsed.columns = ["Start_Min", "End_Min", "AutoFixed", "ErrorMessage"]
    df = pd.concat([df, parsed], axis=1)

    df["Duration"] = df["End_Min"] - df["Start_Min"]
    df["Start_Hour"] = (df["Start_Min"] // 60).astype("Int64")
    df["Day_List"] = df["Days"].apply(decode_days)

    df_valid = df[df["ErrorMessage"] == ""].copy()
    df_errors = df[df["ErrorMessage"] != ""].copy()

    return df_valid, df_errors


# -------------------------------------------------------------
# ------------------------ FILE UPLOAD -------------------------
# -------------------------------------------------------------

def smart_load():
    st.sidebar.header("📂 Upload Dataset")
    f = st.sidebar.file_uploader("Upload CSV or Excel", type=["csv", "xlsx"])
    if f is None:
        st.info("Upload a schedule file to continue.")
        return None

    if f.name.endswith(".csv"):
        return pd.read_csv(f)
    return pd.read_excel(f)


# -------------------------------------------------------------
# ------------------- AVAILABILITY CHECKER --------------------
# -------------------------------------------------------------

def get_availability(df_valid, weekday, hour):
    minute = hour * 60

    df_day = df_valid[df_valid["Day_List"].apply(lambda lst: weekday in lst)]

    occupied = df_day[
        (df_day["Start_Min"] <= minute) &
        (minute < df_day["End_Min"])
    ]

    all_halls = df_valid["Hall"].unique().tolist()
    occupied_halls = occupied["Hall"].unique().tolist()
    available = [h for h in all_halls if h not in occupied_halls]

    return available, occupied


# -------------------------------------------------------------
# --------------------------- APP ------------------------------
# -------------------------------------------------------------

def main():
    st.set_page_config(page_title="KIMEP Dashboard", layout="wide")

    st.markdown("<h1 style='color:#6A355D;'>KIMEP Classroom Occupancy Dashboard</h1>", unsafe_allow_html=True)

    raw_df = smart_load()
    if raw_df is None:
        st.stop()

    df_valid, df_errors = preprocess_data(raw_df)

    st.success("Dataset loaded successfully!")

    # KPIs
    st.subheader("📊 Key Metrics")
    c1, c2, c3 = st.columns(3)
    c1.metric("Total Classes", len(df_valid))
    c2.metric("Distinct Halls", df_valid["Hall"].nunique())
    c3.metric("Peak Start Hour", int(df_valid["Start_Hour"].mode()[0]))

    tab1, tab2, tabA, tab3, tab4 = st.tabs([
        "Overview", "Analytics", "Availability", "Data Explorer", "Errors"
    ])

    # ---------------- OVERVIEW ----------------
    with tab1:
        st.header("🕒 Start Time Distribution")

        hourly_counts = df_valid.groupby("Start_Hour").size().reset_index(name="Count")
        fig = px.bar(
            hourly_counts,
            x="Start_Hour",
            y="Count",
            color="Count",
            title="Class Start Times by Hour",
            text_auto=True,
            color_continuous_scale=["#CBAACB", "#6A355D"]
        )
        fig.update_layout(plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, use_container_width=True)

    # ---------------- ANALYTICS ----------------
    with tab2:
        st.header("🏫 Hall Usage Frequency")

        hall_counts = df_valid["Hall"].value_counts().reset_index()
        hall_counts.columns = ["Hall", "Count"]

        fig1 = px.bar(
            hall_counts,
            x="Hall",
            y="Count",
            text="Count",
            color="Count",
            color_continuous_scale=["#EBD4CB", "#6A355D"]
        )
        st.plotly_chart(fig1, use_container_width=True)

        st.header("🔥 Heatmap: Hall Usage by Hour")

        heat = df_valid.groupby(["Hall", "Start_Hour"]).size().reset_index(name="Count")
        pivot = heat.pivot(index="Hall", columns="Start_Hour", values="Count")

        fig_h = px.imshow(
            pivot,
            aspect="auto",
            labels=dict(color="Number of Classes"),
            color_continuous_scale="Viridis"
        )
        fig_h.update_layout(height=900, title="Heatmap of Hall Occupancy")
        st.plotly_chart(fig_h, use_container_width=True)

    # ---------------- AVAILABILITY ----------------
    with tabA:
        st.header("🟢 Classroom Availability Checker")

        weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        selected_wd = st.selectbox("Weekday:", weekdays)
        selected_hr = st.slider("Hour:", 7, 21, 9)

        available, occupied = get_availability(df_valid, selected_wd, selected_hr)

        st.subheader(f"Results for {selected_wd} at {selected_hr}:00")

        st.markdown("### 🟢 Available Halls")
        st.success(available if available else "No available halls.")

        st.markdown("### 🔴 Occupied Halls")
        st.dataframe(occupied[["Hall", "Class_Times", "Days", "Duration"]])

    # ---------------- DATA EXPLORER ----------------
    with tab3:
        st.header("🔍 Data Explorer")
        st.dataframe(df_valid)

    # ---------------- ERRORS ----------------
    with tab4:
        st.header("⚠ Invalid Time Entries")
        st.dataframe(df_errors)


if __name__ == "__main__":
    main()
