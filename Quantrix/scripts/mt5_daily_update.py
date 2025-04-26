import MetaTrader5 as mt5
import pandas as pd
from pathlib import Path
import os
from datetime import datetime, timedelta
import sys

# === INIT ===
if getattr(sys, 'frozen', False):
    base_path = Path(sys._MEIPASS)  # When running from PyInstaller bundle
else:
    base_path = Path(__file__).resolve().parent.parent  # When running normally
db_path = base_path / "database"

# === Connect to MT5 ===
print("Connecting to MetaTrader 5...")
if not mt5.initialize():
    raise RuntimeError("Failed to initialize MetaTrader 5. Is it running?")
else:
    print("Connected to MetaTrader 5")

# Define pairs
pairs = ["EURUSD", "GBPUSD", "USDCAD", "USDJPY", "AUDUSD", "NZDUSD"]

# === Date Settings ===
today = datetime.now()
yesterday = today - timedelta(days=1)

# === Loop through all pairs and update ===
for pair in pairs:
    print(f"\nUpdating {pair}")

    # === Load existing OHLC from DB ===
    file_path = os.path.join(db_path, f"{pair}_ohlc.pkl")
    if not os.path.exists(file_path):
        print(f"No existing OHLC file found for {pair}, skipping.")
        continue

    df = pd.read_pickle(file_path)

    # === Find last date in database ===
    last_date = df.index.max()
    print(f"Last date in database: {last_date.date()}")
    
    # Ensure the last date is before today
    if last_date.date() >= yesterday.date():
        print(f"Database is already up to date for {pair}.")
        continue
        
    print(f"Fetching data from {(last_date + timedelta(days=1)).date()} to {yesterday.date()}")

    # === Pull recent candles from MT5 ===
    # Get more candles than we need to ensure we have enough
    days_to_fetch = (today - last_date).days + 5  # Add buffer of 5 days
    candles = mt5.copy_rates_from(pair, mt5.TIMEFRAME_D1, today, days_to_fetch)
    
    if candles is None or len(candles) == 0:
        print(f"No candle data returned from MT5 for {pair}.")
        continue

    # Convert to DataFrame
    live_df = pd.DataFrame(candles)
    live_df['time'] = pd.to_datetime(live_df['time'], unit='s')
    live_df.set_index('time', inplace=True)
    live_df.rename(columns={
        'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close',
        'tick_volume': 'Volume'
    }, inplace=True)
    
    # Add day of week
    live_df['Day'] = live_df.index.day_name()
    
    # Filter to only include dates after the last date and before today
    new_candles = live_df[(live_df.index.date > last_date.date()) & 
                         (live_df.index.date <= yesterday.date())]
    
    if new_candles.empty:
        print(f"No new complete candles to add for {pair}.")
        continue
    
    print(f"Found {len(new_candles)} new candles to add")
    
    # Count new entries
    new_entries = 0
    
    # Add each candle to the database
    for date, candle in new_candles.iterrows():
        if date in df.index:
            print(f"Candle for {date.date()} already exists in database.")
            continue
            
        df.loc[date] = {
            'Day': date.day_name(),
            'Open': candle['Open'],
            'High': candle['High'],
            'Low': candle['Low'],
            'Close': candle['Close'],
            'Volume': candle['Volume']
        }
        print(f"Added candle for {date.date()} ({date.day_name()})")
        new_entries += 1
    
    if new_entries > 0:
        # Sort by date
        df.sort_index(inplace=True)
        
        # Save updated OHLC
        df.to_pickle(file_path)
        print(f"Added {new_entries} new candles to {pair} database.")
    else:
        print(f"No new candles were added for {pair}.")

# === Disconnect from MT5 ===
mt5.shutdown()
print("\nAll pairs updated with missing candles.")