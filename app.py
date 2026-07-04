
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
