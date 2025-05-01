import sys
import os
import pandas as pd
import joblib
from datetime import timedelta
from collections import defaultdict
from pathlib import Path

# === CONFIG ===
base_path = Path(__file__).resolve().parent.parent
DB_PATH = base_path / "database"
MODEL_PATH = base_path / "models" / "calibrated_model.pkl"

PAIR_COMBOS = [
    ("EURUSD", "GBPUSD"),
    ("GBPUSD", "EURUSD"),
    ("USDCAD", "DXY"),
    ("USDJPY", "DXY"),
    ("AUDUSD", "NZDUSD"),
    ("NZDUSD", "AUDUSD"),
    ("XAGUSD", "XAUUSD"),
    ("XAUUSD", "XAGUSD")
]

# === Optional CLI Parameters ===
try:
    CONFIDENCE_THRESHOLD = float(sys.argv[1])
    START_BALANCE = float(sys.argv[2])
    RISK_PERCENT = float(sys.argv[3])
    # No longer using LEVERAGE from parameters
    LEVERAGE = 1  # Set to 1 to effectively ignore leverage
except IndexError:
    CONFIDENCE_THRESHOLD = 0.50
    START_BALANCE = 10000
    RISK_PERCENT = 0.01
    LEVERAGE = 1

# === Load Model ===
model = joblib.load(MODEL_PATH)

# === Load Data ===
def load_data(pair):
    ohlc_path = os.path.join(DB_PATH, f"{pair}_ohlc.pkl")
    fvg_path = os.path.join(DB_PATH, f"{pair}_fvg.pkl")
    ohlc = pd.read_pickle(ohlc_path)
    fvg = pd.read_pickle(fvg_path) if os.path.exists(fvg_path) else pd.DataFrame(columns=["Type", "FVG Low", "FVG High"])
    return ohlc.sort_index(), fvg.sort_index()

# === Check for divergence ===
def check_divergence(date, df1, df2):
    try:
        prev = date - timedelta(days=1)
        if date not in df1.index or prev not in df1.index or date not in df2.index or prev not in df2.index:
            return None, None

        p1_low_today, p1_low_prev = df1.loc[date]['Low'], df1.loc[prev]['Low']
        p2_low_today, p2_low_prev = df2.loc[date]['Low'], df2.loc[prev]['Low']
        p1_high_today, p1_high_prev = df1.loc[date]['High'], df1.loc[prev]['High']
        p2_high_today, p2_high_prev = df2.loc[date]['High'], df2.loc[prev]['High']

        if p1_low_today < p1_low_prev and p2_low_today >= p2_low_prev:
            return "long", 1
        if p2_low_today < p2_low_prev and p1_low_today >= p1_low_prev:
            return "long", 2
        if p1_high_today > p1_high_prev and p2_high_today <= p2_high_prev:
            return "short", 1
        if p2_high_today > p2_high_prev and p1_high_today <= p1_high_prev:
            return "short", 2
        return None, None
    except:
        return None, None

# === Extract features ===
def extract_features(date, pair, direction, ohlc, fvg):
    try:
        row = ohlc.loc[date]
        range_size = row['High'] - row['Low']
        week_start = date - timedelta(days=date.weekday())
        week_end = week_start + timedelta(days=6)

        fvg_window = fvg[(fvg.index >= week_start) & (fvg.index <= week_end)]
        bullish_count = len(fvg_window[fvg_window['Type'].str.lower() == 'bullish'])
        bearish_count = len(fvg_window[fvg_window['Type'].str.lower() == 'bearish'])

        day_val = 0 if date.weekday() == 1 else 1  # Tuesday = 1, Wednesday = 2
        dir_val = 1 if direction == "long" else 0

        return pd.DataFrame([{
            "DayOfWeek": day_val,
            "Direction": dir_val,
            "Bullish_FVG_Count": bullish_count,
            "Bearish_FVG_Count": bearish_count,
            "High_Low_Range": range_size
        }])
    except:
        return None

# === Main Backtest ===
trades = []
balance = START_BALANCE

# Build a global date index (Tuesday/Wednesday only)
dates = None
for pair1, pair2 in PAIR_COMBOS:
    df1, _ = load_data(pair1)
    df2, _ = load_data(pair2)
    if dates is None:
        dates = df1.index.intersection(df2.index)
    else:
        dates = dates.intersection(df1.index.intersection(df2.index))

dates = [d for d in dates if d.weekday() in [1, 2]]  # Tuesday or Wednesday

for date in dates:
    for pair1, pair2 in PAIR_COMBOS:
        df1, fvg1 = load_data(pair1)
        df2, fvg2 = load_data(pair2)

        direction, primary = check_divergence(date, df1, df2)
        if direction is None:
            continue

        ohlc = df1 if primary == 1 else df2
        fvg = fvg1 if primary == 1 else fvg2
        pair = pair1 if primary == 1 else pair2

        features = extract_features(date, pair, direction, ohlc, fvg)
        if features is None:
            continue

        confidence = model.predict_proba(features)[0][1]
        if confidence < CONFIDENCE_THRESHOLD:
            continue

        entry = ohlc.loc[date]['Open']
        stop = ohlc.loc[date]['Low'] - 0.0005 if direction == "long" else ohlc.loc[date]['High'] + 0.0005
        friday = date + timedelta(days=(4 - date.weekday()))
        if friday not in ohlc.index:
            continue

        exit_price = ohlc.loc[friday]['Close']
        profit = (exit_price - entry) if direction == "long" else (entry - exit_price)
        risk = START_BALANCE * RISK_PERCENT
        position_size = round((risk / abs(entry - stop)) * LEVERAGE, 2)
        pnl = round(profit * position_size, 2)
        balance += pnl
        win = 1 if pnl > 0 else 0

        trades.append({
            "Date": date.date(),
            "Day": date.strftime('%A'),
            "Pair": pair,
            "Direction": direction,
            "Confidence": round(confidence * 100, 2),
            "Entry": round(entry, 5),
            "Exit": round(exit_price, 5),
            "P/L ($)": pnl,
            "Win": win,
            "Balance": round(balance, 2),
            "Result": "Win" if win else "Loss"
        })

df_trades = pd.DataFrame(trades)

# Print Summary
print(f"\n=== Backtest Complete ===")
print(f"Confidence Threshold: {CONFIDENCE_THRESHOLD:.2f} ({CONFIDENCE_THRESHOLD*100:.0f}%)")

total = len(df_trades)
if total > 0:
    wins = df_trades["Win"].sum()
    win_rate = (wins / total) * 100
    print(f"Total Trades: {total}")
    print(f"Win Rate: {win_rate:.2f}%")
    print(f"Final Balance: ${balance:.2f}")
else:
    print("No trades found that met the criteria.")
    print(f"Final Balance: ${START_BALANCE:.2f}")