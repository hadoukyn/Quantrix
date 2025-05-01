import pandas as pd
from pathlib import Path

base_path = Path(__file__).resolve().parent.parent
db_path = base_path / "database"
log_file = base_path / "logs" / "intraday_signals.xlsx"

if not log_file.exists():
    print("No signal log file found.")
    exit()

# Load signal log
df = pd.read_excel(log_file)
if "Win" not in df.columns:
    df["Win"] = None

# Filter signals from this week missing Win
df["Date"] = pd.to_datetime(df["Date"])
latest_friday = df["Date"].max().normalize()
latest_friday += pd.Timedelta(days=(4 - latest_friday.weekday()))

pending = df[(df["Win"].isna()) & (df["Date"] <= latest_friday)]
if pending.empty:
    print("✅ All signals already evaluated.")
    exit()

print("🔍 Checking outcomes for", len(pending), "trades...")

# Load OHLC databases
ohlc_data = {}
for pair in pending["Pair"].unique():
    try:
        ohlc_data[pair] = pd.read_pickle(db_path / f"{pair}_ohlc.pkl")
    except:
        print(f"❌ Missing OHLC file for {pair}")

# Evaluate outcomes
for i, row in pending.iterrows():
    pair = row["Pair"]
    date = row["Date"]
    direction = row["Direction"].lower()
    entry = row["Entry"]
    stop = row["Stop"]

    friday = date + pd.Timedelta(days=(4 - date.weekday()))
    try:
        close = ohlc_data[pair].loc[friday]["Close"]
    except:
        print(f"❌ No Friday close for {pair} on {friday.date()}")
        continue

    if direction == "long":
        win = int(close > entry)
    else:
        win = int(close < entry)

    df.at[i, "Win"] = win
    print(f"✅ {pair} {direction.upper()} on {date.date()} → {'WIN' if win else 'LOSS'}")

# Save updated file
df.to_excel(log_file, index=False)
print("\n📁 intraday_signals.xlsx updated with new results.")
