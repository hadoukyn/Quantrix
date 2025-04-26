import pandas as pd
import numpy as np
import sys
from datetime import datetime
from pathlib import Path
import joblib
import winsound

if getattr(sys, 'frozen', False):
    base_path = Path(sys._MEIPASS)
else:
    base_path = Path(__file__).resolve().parent.parent
model_path = base_path / "models"
db_path = base_path / "database"
log_file = base_path / "logs" / "intraday_signals.xlsx"

# === CONFIG (Default values if not passed from dashboard) ===
def get_confidence_arg():
    try:
        return int(sys.argv[1])
    except:
        return 50

def calculate_position_size(account_size, risk_pct, leverage, entry_price, stop_loss):
    risk_amount = account_size * (risk_pct / 100)
    sl_pips = abs(entry_price - stop_loss) * 10000
    if sl_pips == 0:
        return 0.0
    pip_value = 10
    lots = (risk_amount / (sl_pips * pip_value))
    adjusted_lots = lots * (leverage / 30)
    return round(adjusted_lots, 2)

def play_signal_sound():
    sound_path = base_path / "assets" / "signal.wav"
    if sound_path.exists():
        winsound.PlaySound(str(sound_path), winsound.SND_FILENAME | winsound.SND_ASYNC)

# === LOAD MODEL ===
model = joblib.load(model_path / "calibrated_model.pkl")

# === LOAD DATABASE ===
ohlc_data = {}
fvg_data = {}
pairs = ["EURUSD", "GBPUSD", "USDCAD", "USDJPY", "AUDUSD", "NZDUSD", "XAUUSD", "XAGUSD", "DXY"]
for p in pairs:
    ohlc_data[p] = pd.read_pickle(db_path / f"{p}_ohlc.pkl")
    fvg_data[p] = pd.read_pickle(db_path / f"{p}_fvg.pkl")

# === COMPARED PAIRS ===
pair_sets = [
    ("EURUSD", "GBPUSD"),
    ("GBPUSD", "EURUSD"),
    ("DXY", "USDCAD"),
    ("USDCAD", "DXY"),
    ("DXY", "USDJPY"),
    ("USDJPY", "DXY"),
    ("AUDUSD", "NZDUSD"),
    ("NZDUSD", "AUDUSD"),
    ("XAGUSD", "XAUUSD"),
    ("XAUUSD", "XAGUSD")
]

# === SIGNAL SCANNING ===
signals_today = []
min_confidence = get_confidence_arg()

# === Load from args passed by dashboard ===
try:
    account_size = float(sys.argv[2])
    risk_pct = float(sys.argv[3])
    leverage = float(sys.argv[4])
except:
    account_size = 10000
    risk_pct = 1
    leverage = 30

now = datetime.now()
today = now.date()
current_weekday = today.weekday()  # 0=Monday, 1=Tuesday, etc.

# Find the most recent Tuesday and Wednesday in this week
days_to_check = []

# Get this week's Tuesday (weekday 1)
if current_weekday >= 1:  # If today is Tuesday or later
    tuesday_date = today - pd.Timedelta(days=(current_weekday - 1))  
    days_to_check.append((tuesday_date, "Tuesday"))

# Get this week's Wednesday (weekday 2)
if current_weekday >= 2:  # If today is Wednesday or later
    wednesday_date = today - pd.Timedelta(days=(current_weekday - 2))
    days_to_check.append((wednesday_date, "Wednesday"))

if not days_to_check:
    print("No Tuesday or Wednesday data available yet this week.")
    sys.exit()

for check_date, day_name in days_to_check:
    print(f"Checking for divergences on {day_name} ({check_date})")
    
    for pair1, pair2 in pair_sets:
        df1 = ohlc_data[pair1]
        df2 = ohlc_data[pair2]
        if check_date not in df1.index or check_date not in df2.index:
            continue

        prev_day = df1.index[df1.index.get_loc(check_date) - 1]
        p1_today = df1.loc[check_date]
        p2_today = df2.loc[check_date]
        p1_prev = df1.loc[prev_day]
        p2_prev = df2.loc[prev_day]

        # === Bullish Divergence ===
        if (p1_today["Low"] < p1_prev["Low"] and p2_today["Low"] >= p2_prev["Low"]) or \
           (p2_today["Low"] < p2_prev["Low"] and p1_today["Low"] >= p1_prev["Low"]):

            direction = "long"
            entry_price = p1_today["Open"]
            stop_loss = p1_today["Low"] - 0.0005

        # === Bearish Divergence ===
        elif (p1_today["High"] > p1_prev["High"] and p2_today["High"] <= p2_prev["High"]) or \
             (p2_today["High"] > p2_prev["High"] and p1_today["High"] <= p1_prev["High"]):

            direction = "short"
            entry_price = p1_today["Open"]
            stop_loss = p1_today["High"] + 0.0005

        else:
            continue

        # === Features ===
        week_start = check_date - pd.Timedelta(days=check_date.weekday())
        week_end = week_start + pd.Timedelta(days=4)
        week_fvg = fvg_data[pair1][(fvg_data[pair1].index >= week_start) & (fvg_data[pair1].index <= week_end)]
        bullish_count = len(week_fvg[week_fvg['Type'].str.lower() == 'bullish'])
        bearish_count = len(week_fvg[week_fvg['Type'].str.lower() == 'bearish'])
        high_low_range = p1_today["High"] - p1_today["Low"]

        features = pd.DataFrame.from_dict([{
            "DayOfWeek": day_name,
            "Direction": direction,
            "Bullish_FVG_Count": bullish_count,
            "Bearish_FVG_Count": bearish_count,
            "High_Low_Range": high_low_range
        }])

        prob = model.predict_proba(features)[0][1 if direction == "long" else 0]

        if prob >= min_confidence / 100:
            play_signal_sound()
            position_size = calculate_position_size(account_size, risk_pct, leverage, entry_price, stop_loss)

            signals_today.append({
                "Date": check_date,
                "Day": day_name,
                "Pair": pair1,
                "Direction": direction,
                "Confidence": round(prob * 100, 2),
                "Entry": entry_price,
                "Stop": stop_loss,
                "Position Size": f"{position_size} lots"
            })

# === SAVE TO EXCEL ===
if signals_today:
    df_signals = pd.DataFrame(signals_today)
    if log_file.exists():
        existing = pd.read_excel(log_file)
        df_signals = pd.concat([existing, df_signals], ignore_index=True)
    df_signals.to_excel(log_file, index=False)
    print("\nLIVE Divergence Signals:")
    for sig in signals_today:
        print(f"📈 {sig['Date']} | {sig['Pair']} | {sig['Direction'].upper()} | Confidence: {sig['Confidence']}%")
        print(f"   Entry: {sig['Entry']}, Stop: {sig['Stop']}, Size: {sig['Position Size']}")
        print("-" * 50)
else:
    print("\nNo valid divergences at this time.")