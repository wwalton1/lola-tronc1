
import io
import calendar
from pathlib import Path
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Lola & Co Tronc App", layout="wide")

EXCLUDE_FIRST_NAMES = {"quim", "marc", "josep", "pep"}
WINDOW_START_HOUR = 12
WINDOW_END_HOUR = 23
APP_DIR = Path(__file__).parent
DATA_DIR = APP_DIR / "data"
TIPS_FILE = DATA_DIR / "daily_tips.csv"

st.title("Lola & Co Tronc Calculator")
st.caption("12:00–23:00 only • Breaks deducted • TOTAL row tips only • Daily rate calculation")

st.markdown(
    """
    <style>
    @media (max-width: 700px) {
        .stButton > button, .stDownloadButton > button {
            width: 100%;
            min-height: 3rem;
        }
        [data-testid="stMetricValue"] {
            font-size: 1.6rem;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

def month_dates(month_start):
    start = pd.Timestamp(month_start).normalize()
    days_in_month = calendar.monthrange(start.year, start.month)[1]
    return pd.date_range(start, periods=days_in_month)

def load_saved_tips():
    if not TIPS_FILE.exists():
        return pd.DataFrame(columns=["date", "tips"])

    saved = pd.read_csv(TIPS_FILE)
    if saved.empty:
        return pd.DataFrame(columns=["date", "tips"])

    saved["date"] = pd.to_datetime(saved["date"], errors="coerce")
    saved["tips"] = pd.to_numeric(saved["tips"], errors="coerce").fillna(0)
    saved = saved.dropna(subset=["date"])
    saved["date"] = saved["date"].dt.normalize()
    saved = saved.groupby("date", as_index=False)["tips"].last()
    return saved.sort_values("date")

def save_tips(tips):
    DATA_DIR.mkdir(exist_ok=True)
    tips = tips.copy()
    tips["date"] = pd.to_datetime(tips["date"], errors="coerce")
    tips["tips"] = pd.to_numeric(tips["tips"], errors="coerce").fillna(0)
    tips = tips.dropna(subset=["date"])
    tips["date"] = tips["date"].dt.normalize()
    tips = tips.groupby("date", as_index=False)["tips"].last().sort_values("date")
    tips.to_csv(TIPS_FILE, index=False, date_format="%Y-%m-%d")

def save_daily_tip(entry_date, amount):
    saved = load_saved_tips()
    entry = pd.DataFrame({"date": [pd.Timestamp(entry_date).normalize()], "tips": [float(amount or 0)]})
    save_tips(pd.concat([saved, entry], ignore_index=True))

def tips_for_month(month_start):
    days = month_dates(month_start)
    default_tips = pd.DataFrame({"date": days, "tips": [0.0] * len(days)})
    saved = load_saved_tips()

    if saved.empty:
        return default_tips

    return default_tips.drop(columns=["tips"]).merge(saved, on="date", how="left").fillna({"tips": 0.0})

def monthly_tip_summary(selected_month):
    selected_month = pd.Timestamp(selected_month)
    month_tips = tips_for_month(selected_month)
    today = pd.Timestamp.today().normalize()
    days_with_tips = month_tips[month_tips["tips"] > 0]
    today_match = month_tips[month_tips["date"].eq(today)]
    today_tips = float(today_match["tips"].iloc[0]) if not today_match.empty else 0.0
    best_day = days_with_tips.sort_values("tips", ascending=False).head(1)
    best_day_text = "No entries yet"

    if not best_day.empty:
        best_day_text = f"{best_day['date'].iloc[0]:%d %b} (£{best_day['tips'].iloc[0]:,.2f})"

    return {
        "month_tips": month_tips,
        "total": month_tips["tips"].sum(),
        "days_recorded": len(days_with_tips),
        "today_tips": today_tips,
        "average": days_with_tips["tips"].mean() if not days_with_tips.empty else 0.0,
        "best_day": best_day_text,
    }

def overlap_hours(a_start, a_end, b_start, b_end):
    return max(0, (min(a_end, b_end) - max(a_start, b_start)).total_seconds() / 3600)

def load_blip(file):
    ts = pd.read_excel(file, header=1)
    ts = ts.iloc[:, :14]
    ts.columns = [
        "First Name","Last Name","Job Title","Team","Blip Type",
        "Clock In Date","Clock In Time","Clock In Location",
        "Clock Out Date","Clock Out Time","Clock Out Location",
        "Total Duration","Total Excl Breaks","Notes"
    ]
    return ts

def calculate(ts, tips, manual):
    shifts = ts[(ts["Blip Type"] == "Shift") & (~ts["First Name"].astype(str).str.lower().isin(EXCLUDE_FIRST_NAMES))].copy()
    breaks = ts[(ts["Blip Type"] == "Break") & (~ts["First Name"].astype(str).str.lower().isin(EXCLUDE_FIRST_NAMES))].copy()

    for df in (shifts, breaks):
        df["start"] = pd.to_datetime(df["Clock In Date"].astype(str) + " " + df["Clock In Time"].astype(str), errors="coerce")
        df["end"] = pd.to_datetime(df["Clock Out Date"].astype(str) + " " + df["Clock Out Time"].astype(str), errors="coerce")

    shifts = shifts.dropna(subset=["start", "end"])
    breaks = breaks.dropna(subset=["start", "end"])

    records = []
    for (date, first, last), grp in shifts.groupby([shifts["start"].dt.date, "First Name", "Last Name"]):
        eligible = 0.0
        person_breaks = breaks[(breaks["First Name"] == first) & (breaks["Last Name"] == last)]

        for _, r in grp.iterrows():
            day = pd.Timestamp(date)
            ws = day + pd.Timedelta(hours=WINDOW_START_HOUR)
            we = day + pd.Timedelta(hours=WINDOW_END_HOUR)

            s = max(r["start"], ws)
            e = min(r["end"], we)
            if e <= s:
                continue

            duration = (e - s).total_seconds() / 3600

            for _, b in person_breaks.iterrows():
                duration -= overlap_hours(s, e, b["start"], b["end"])

            eligible += max(0, duration)

        full_hours = pd.to_timedelta(grp["Total Excl Breaks"], errors="coerce").dt.total_seconds().fillna(0).sum() / 3600
        records.append([pd.Timestamp(date), first, last, eligible, full_hours])

    hours = pd.DataFrame(records, columns=["date", "First Name", "Last Name", "eligible_hours", "full_hours"])

    manual_records = []
    if manual is not None and not manual.empty:
        manual = manual[manual["Include?"].astype(str).str.upper().eq("YES")].copy()
        for _, row in manual.iterrows():
            if pd.isna(row["Date"]) or not row["First Name"]:
                continue
            date = pd.to_datetime(row["Date"])
            start = pd.to_datetime(str(date.date()) + " " + str(row["Start Time"]))
            end = pd.to_datetime(str(date.date()) + " " + str(row["End Time"]))
            ws = date.normalize() + pd.Timedelta(hours=WINDOW_START_HOUR)
            we = date.normalize() + pd.Timedelta(hours=WINDOW_END_HOUR)
            eligible = max(0, (min(end, we) - max(start, ws)).total_seconds() / 3600)
            eligible -= float(row.get("Break Minutes", 0) or 0) / 60
            eligible = max(0, eligible)
            manual_records.append([date.normalize(), row["First Name"], row["Last Name"], eligible, eligible])

    if manual_records:
        hours = pd.concat([hours, pd.DataFrame(manual_records, columns=hours.columns)], ignore_index=True)

    tips = tips.copy()
    tips["date"] = pd.to_datetime(tips["date"])
    tips["tips"] = pd.to_numeric(tips["tips"], errors="coerce").fillna(0)

    report = hours.merge(tips, on="date", how="left")
    report["tips"] = report["tips"].fillna(0)
    report["total_hours_day"] = report.groupby("date")["eligible_hours"].transform("sum")
    report["rate_per_hour"] = 0.0
    has_hours = report["total_hours_day"] > 0
    report.loc[has_hours, "rate_per_hour"] = report.loc[has_hours, "tips"] / report.loc[has_hours, "total_hours_day"]
    report["tronc_pay"] = report["eligible_hours"] * report["rate_per_hour"]

    monthly = report.groupby(["First Name", "Last Name"], as_index=False).agg(
        full_hours=("full_hours", "sum"),
        eligible_hours=("eligible_hours", "sum"),
        tronc_pay=("tronc_pay", "sum")
    )
    monthly["full_hours"] = monthly["full_hours"].round(2)
    monthly["eligible_hours"] = monthly["eligible_hours"].round(2)
    monthly["tronc_pay"] = monthly["tronc_pay"].round(2)
    monthly = monthly.sort_values("tronc_pay", ascending=False)

    return report, monthly, hours, tips

def to_excel(monthly, report, hours, tips, manual):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        monthly.to_excel(writer, index=False, sheet_name="Monthly Payroll")
        report.to_excel(writer, index=False, sheet_name="Daily Audit")
        hours.to_excel(writer, index=False, sheet_name="Hours Used")
        tips.to_excel(writer, index=False, sheet_name="Tip Totals")
        manual.to_excel(writer, index=False, sheet_name="Manual Shifts")
    return output.getvalue()

with st.sidebar:
    st.header("Rules")
    st.write("Excluded: Quim, Marc, Josep, Pep")
    st.write("Included: everyone else")
    st.write("Eligible window: 12:00–23:00")
    st.write("Breaks: deducted")
    st.write("Tips: TOTAL rows only")

dashboard_tab, daily_tab, monthly_tab = st.tabs(["Dashboard", "Daily tips", "Monthly payroll"])

with dashboard_tab:
    st.subheader("Dashboard")

    dashboard_month = st.date_input(
        "Dashboard month",
        value=pd.Timestamp.today().date(),
        key="dashboard_month",
    )
    summary = monthly_tip_summary(dashboard_month)
    month_tips = summary["month_tips"]

    c1, c2 = st.columns(2)
    c1.metric("This Month", f"£{summary['total']:,.2f}")
    c2.metric("Today", f"£{summary['today_tips']:,.2f}")

    c3, c4 = st.columns(2)
    c3.metric("Days Recorded", f"{summary['days_recorded']}/{len(month_tips)}")
    c4.metric("Average Day", f"£{summary['average']:,.2f}")

    st.caption(f"Best day: {summary['best_day']}")

    chart_data = month_tips.set_index("date")["tips"]
    st.bar_chart(chart_data)

    recent_tips = load_saved_tips().sort_values("date", ascending=False).head(7)
    st.subheader("Recent Entries")
    if recent_tips.empty:
        st.info("No saved daily tips yet.")
    else:
        st.dataframe(recent_tips, width="stretch", hide_index=True)

with daily_tab:
    st.subheader("Daily TOTAL tips")

    entry_date = st.date_input("Date", value=pd.Timestamp.today().date(), key="daily_tip_date")
    existing_tips = load_saved_tips()
    existing_match = existing_tips[existing_tips["date"].eq(pd.Timestamp(entry_date).normalize())]
    existing_amount = float(existing_match["tips"].iloc[0]) if not existing_match.empty else 0.0

    tip_amount = st.number_input(
        "TOTAL tips for this date",
        min_value=0.0,
        value=existing_amount,
        step=1.0,
        format="%.2f",
        key=f"daily_tip_amount_{pd.Timestamp(entry_date):%Y_%m_%d}",
    )

    if st.button("Save Daily Tips", type="primary"):
        save_daily_tip(entry_date, tip_amount)
        st.success(f"Saved £{tip_amount:,.2f} for {pd.Timestamp(entry_date):%d %b %Y}.")

    saved_tips = load_saved_tips()
    if not saved_tips.empty:
        this_month = saved_tips[saved_tips["date"].dt.to_period("M").eq(pd.Timestamp(entry_date).to_period("M"))]
        month_total = this_month["tips"].sum()
        st.metric("Saved This Month", f"£{month_total:,.2f}")
        st.dataframe(this_month.sort_values("date", ascending=False), width="stretch", hide_index=True)
    else:
        st.info("No saved daily tips yet.")

with monthly_tab:
    hours_file = st.file_uploader("Upload Blip hours .xlsx", type=["xlsx"])

    st.subheader("Daily TOTAL tips")
    st.write("Saved daily tips are filled in automatically. You can still edit them before calculating.")
    month_start = st.date_input("Month start date", key="month_start_date")
    default_tips = tips_for_month(month_start)
    tips_df = st.data_editor(default_tips, num_rows="dynamic", width="stretch")

    if st.button("Save Edited Monthly Tips"):
        saved_tips = load_saved_tips()
        month_period = pd.Timestamp(month_start).to_period("M")
        outside_month = saved_tips[~saved_tips["date"].dt.to_period("M").eq(month_period)] if not saved_tips.empty else saved_tips
        save_tips(pd.concat([outside_month, tips_df], ignore_index=True))
        st.success("Saved monthly tip changes.")

    st.subheader("Manual shifts")
    st.write("Use this for staff not on the Blip sheet, e.g. Harry Wright.")
    manual_default = pd.DataFrame({
        "First Name": ["Harry"],
        "Last Name": ["Wright"],
        "Date": [pd.to_datetime(month_start)],
        "Start Time": ["16:00"],
        "End Time": ["22:00"],
        "Break Minutes": [0],
        "Include?": ["NO"]
    })
    manual_df = st.data_editor(manual_default, num_rows="dynamic", width="stretch")

    if st.button("Calculate Tronc", type="primary"):
        if hours_file is None:
            st.error("Please upload the Blip hours file first.")
        else:
            ts = load_blip(hours_file)
            report, monthly, hours, tips_clean = calculate(ts, tips_df, manual_df)

            total_tips = tips_clean["tips"].sum()
            total_eligible = report["eligible_hours"].sum()
            avg_rate = total_tips / total_eligible if total_eligible else 0

            c1, c2, c3 = st.columns(3)
            c1.metric("Total Tips", f"£{total_tips:,.2f}")
            c2.metric("Total Eligible Hours", f"{total_eligible:,.2f}")
            c3.metric("Average £/Hour", f"£{avg_rate:,.2f}")

            st.subheader("Monthly Payroll")
            st.dataframe(monthly, width="stretch")

            st.subheader("Daily Audit")
            st.dataframe(report, width="stretch")

            xlsx = to_excel(monthly, report, hours, tips_clean, manual_df)
            st.download_button(
                "Download Excel Report",
                data=xlsx,
                file_name="tronc_report.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
