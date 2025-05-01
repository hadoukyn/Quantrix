import pandas as pd
import numpy as np
import sys
from datetime import datetime, timedelta
from pathlib import Path
import joblib
import winsound
import MetaTrader5 as mt5
import yfinance as yf

# === PATH SETUP ===
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

# === INITIALIZE MT5 CONNECTION ===
def connect_to_mt5():
    print("Connecting to MetaTrader 5...")
    if not mt5.initialize():
        print("Failed to initialize MetaTrader 5. Is it running?")
        return False
    print("Connected to MetaTrader 5")
    return True

# === GET LIVE DATA FOR FOREX PAIRS FROM MT5 ===
def get_mt5_live_data(pairs):
    live_data = {}
    
    for pair in pairs:
        # Get today's candle
        candle = mt5.copy_rates_from(pair, mt5.TIMEFRAME_D1, datetime.now(), 1)
        
        if candle is None or len(candle) == 0:
            print(f"Warning: No live data available for {pair}")
            continue
            
        # Convert to DataFrame with the same structure as in pickle files
        df = pd.DataFrame(candle)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        
        # Format data to match pickle structure
        # Use the day name mapping to match the expected format
        day_name = get_day_name(df['time'].iloc[0].weekday())
        
        today_data = {
            'Day': day_name,
            'Open': float(df['open'].iloc[0]),
            'High': float(df['high'].iloc[0]),
            'Low': float(df['low'].iloc[0]),
            'Close': float(df['close'].iloc[0]), # Current close (will update until day end)
            'Volume': float(df['tick_volume'].iloc[0])
        }
        
        live_data[pair] = today_data
        print(f"Got live data for {pair}: Open={today_data['Open']}, High={today_data['High']}, Low={today_data['Low']}")
    
    return live_data

# Helper function to get day name from weekday index
def get_day_name(weekday):
    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    return days[weekday]

# === GET LIVE DATA FOR DXY, GOLD, SILVER FROM YAHOO FINANCE ===
def get_yahoo_live_data(symbols):
    live_data = {}
    yahoo_symbols = {
        "DXY": "DX-Y.NYB",
        "XAUUSD": "GC=F",
        "XAGUSD": "SI=F"
    }
    
    for pair, yahoo_symbol in yahoo_symbols.items():
        if pair not in symbols:
            continue
            
        try:
            # Get today's data
            # Explicitly set auto_adjust=False to match previous behavior
            data = yf.download(yahoo_symbol, period="1d", interval="1d", auto_adjust=False, progress=False)
            
            if data.empty:
                print(f"Warning: No live data available for {pair}")
                continue
            
            # Get day name using our helper function
            day_name = get_day_name(datetime.now().weekday())
            
            # Fix: Extract values properly to avoid Series deprecation warnings
            today_data = {
                'Day': day_name,
                'Open': data['Open'].iloc[0],  # No float() wrapper needed
                'High': data['High'].iloc[0],
                'Low': data['Low'].iloc[0],
                'Close': data['Close'].iloc[0],
                'Volume': data['Volume'].iloc[0] if 'Volume' in data.columns else 0
            }
            
            live_data[pair] = today_data
            print(f"Got live data for {pair}: Open={today_data['Open']}, High={today_data['High']}, Low={today_data['Low']}")
                
        except Exception as e:
            print(f"Error getting Yahoo data for {pair}: {e}")
    
    return live_data

# === MERGE LIVE DATA WITH HISTORICAL DATA ===
def merge_live_with_historical(ohlc_data, live_data):
    merged_data = {}
    
    for pair, historical_df in ohlc_data.items():
        if pair not in live_data:
            print(f"Skipping {pair} - no live data available")
            merged_data[pair] = historical_df
            continue
            
        # Create a copy of historical data
        merged_df = historical_df.copy()
        
        # Add today's data
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        
        # If today already exists in the data, update it
        if today in merged_df.index:
            print(f"Updating existing today's data for {pair}")
            merged_df.loc[today] = live_data[pair]
        else:
            print(f"Adding today's data for {pair}")
            merged_df.loc[today] = live_data[pair]
            
        merged_data[pair] = merged_df
        
    return merged_data

# === DETECT DIVERGENCES ===
def detect_divergences(merged_data, days_to_check, pair_sets):
    signals = []
    now = datetime.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    
    for check_date, day_name in days_to_check:
        print(f"Checking for divergences on {day_name} ({check_date})")
        
        # Only check the current day against the previous day
        if check_date.date() != today.date():
            continue
            
        for pair1, pair2 in pair_sets:
            df1 = merged_data.get(pair1)
            df2 = merged_data.get(pair2)
            
            if df1 is None or df2 is None:
                print(f"Missing data for pair set {pair1} vs {pair2}")
                continue
                
            if check_date not in df1.index or check_date not in df2.index:
                print(f"Missing current day data for {pair1} or {pair2}")
                continue
                
            # Get previous trading day
            prev_dates = [d for d in df1.index if d < check_date]
            if not prev_dates:
                print(f"No previous data available for {pair1}")
                continue
                
            prev_day = max(prev_dates)
            
            # Ensure previous day exists in both dataframes
            if prev_day not in df2.index:
                print(f"Missing previous day data for {pair2}")
                continue
                
            print(f"Comparing {pair1} vs {pair2}: {check_date.date()} against {prev_day.date()}")
            
            p1_today = df1.loc[check_date]
            p2_today = df2.loc[check_date]
            p1_prev = df1.loc[prev_day]
            p2_prev = df2.loc[prev_day]

            # === DETAILED DIVERGENCE LOGGING ===
            print(f"\n=== DETAILED COMPARISON ===")
            print(f"{pair1} Previous: High={p1_prev['High']}, Low={p1_prev['Low']}")
            print(f"{pair1} Today:    High={p1_today['High']}, Low={p1_today['Low']}")
            print(f"{pair2} Previous: High={p2_prev['High']}, Low={p2_prev['Low']}")
            print(f"{pair2} Today:    High={p2_today['High']}, Low={p2_today['Low']}")
            
            # === Extract scalar values for comparison - fixed to avoid deprecation warnings ===
            # For p1_today
            p1_today_low = p1_today["Low"] if isinstance(p1_today["Low"], (int, float)) else p1_today["Low"].iloc[0]
            p1_today_high = p1_today["High"] if isinstance(p1_today["High"], (int, float)) else p1_today["High"].iloc[0]
            p1_today_open = p1_today["Open"] if isinstance(p1_today["Open"], (int, float)) else p1_today["Open"].iloc[0]
            
            # For p1_prev
            p1_prev_low = p1_prev["Low"] if isinstance(p1_prev["Low"], (int, float)) else p1_prev["Low"].iloc[0]
            p1_prev_high = p1_prev["High"] if isinstance(p1_prev["High"], (int, float)) else p1_prev["High"].iloc[0]
            
            # For p2_today
            p2_today_low = p2_today["Low"] if isinstance(p2_today["Low"], (int, float)) else p2_today["Low"].iloc[0]
            p2_today_high = p2_today["High"] if isinstance(p2_today["High"], (int, float)) else p2_today["High"].iloc[0]
            
            # For p2_prev
            p2_prev_low = p2_prev["Low"] if isinstance(p2_prev["Low"], (int, float)) else p2_prev["Low"].iloc[0]
            p2_prev_high = p2_prev["High"] if isinstance(p2_prev["High"], (int, float)) else p2_prev["High"].iloc[0]
            
            # === Bullish Divergence (using scalar values) ===
            bull_div_condition1 = p1_today_low < p1_prev_low and p2_today_low >= p2_prev_low
            bull_div_condition2 = p2_today_low < p2_prev_low and p1_today_low >= p1_prev_low
            
            # === Bearish Divergence (using scalar values) ===
            bear_div_condition1 = p1_today_high > p1_prev_high and p2_today_high <= p2_prev_high
            bear_div_condition2 = p2_today_high > p2_prev_high and p1_today_high <= p1_prev_high
            
            print(f"Bullish divergence condition 1: {bull_div_condition1}")
            print(f"Bullish divergence condition 2: {bull_div_condition2}")
            print(f"Bearish divergence condition 1: {bear_div_condition1}")
            print(f"Bearish divergence condition 2: {bear_div_condition2}")

            if bull_div_condition1 or bull_div_condition2:
                direction = "long"
                entry_price = p1_today_open
                stop_loss = p1_today_low - 0.0005
                divergence_type = "Bullish Divergence"
                print(f"Detected {divergence_type} between {pair1} and {pair2}")

            elif bear_div_condition1 or bear_div_condition2:
                direction = "short"
                entry_price = p1_today_open
                stop_loss = p1_today_high + 0.0005
                divergence_type = "Bearish Divergence"
                print(f"Detected {divergence_type} between {pair1} and {pair2}")

            else:
                print(f"No divergence detected between {pair1} and {pair2}")
                continue
            
            signals.append({
                "Date": check_date,
                "Day": day_name,
                "Pair": pair1,
                "Direction": direction,
                "Entry": entry_price,
                "Stop": stop_loss,
                "Type": divergence_type,
                "Compared_With": pair2
            })
            
    return signals

def main():
    # === LOAD MODEL ===
    try:
        model = joblib.load(model_path / "calibrated_model.pkl")
        model_loaded = True
    except Exception as e:
        print(f"Warning: Could not load model: {e}")
        model_loaded = False

    # === DEFINE PAIRS ===
    mt5_pairs = ["EURUSD", "GBPUSD", "USDCAD", "USDJPY", "AUDUSD", "NZDUSD"]
    yahoo_pairs = ["DXY", "XAUUSD", "XAGUSD"]
    all_pairs = mt5_pairs + yahoo_pairs

    # === LOAD HISTORICAL DATABASE ===
    ohlc_data = {}
    fvg_data = {}
    for p in all_pairs:
        try:
            ohlc_data[p] = pd.read_pickle(db_path / f"{p}_ohlc.pkl")
            try:
                fvg_data[p] = pd.read_pickle(db_path / f"{p}_fvg.pkl")
            except:
                print(f"Warning: FVG data not available for {p}")
        except Exception as e:
            print(f"Error loading data for {p}: {e}")

    # === GET LIVE DATA ===
    mt5_connected = connect_to_mt5()
    
    live_data = {}
    if mt5_connected:
        # Get live MT5 data
        mt5_live_data = get_mt5_live_data(mt5_pairs)
        live_data.update(mt5_live_data)
        
    # Get Yahoo data regardless of MT5 connection
    yahoo_live_data = get_yahoo_live_data(yahoo_pairs)
    live_data.update(yahoo_live_data)
    
    # Disconnect from MT5 after use
    if mt5_connected:
        mt5.shutdown()
        print("Disconnected from MetaTrader 5")

    # === MERGE LIVE DATA WITH HISTORICAL DATA ===
    merged_data = merge_live_with_historical(ohlc_data, live_data)

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

    # === GET DAYS TO CHECK ===
    today = datetime.now().date()
    current_weekday = today.weekday()  # 0=Monday, 1=Tuesday, etc.
    now = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    # For the current implementation, we're only checking today
    # Only check Tuesday or Wednesday
    days_to_check = []
    
    if current_weekday == 1:  # Tuesday
        # Check Tuesday (today) with Monday (previous day)
        days_to_check.append((now, "Tuesday"))
    elif current_weekday == 2:  # Wednesday
        # Check Wednesday (today) with Wednesday (previous day)
        days_to_check.append((now, "Wednesday"))
    
    if not days_to_check:
        print("Today is not Tuesday or Wednesday, no divergence checks needed.")
        return

    # === DETECT DIVERGENCES ===
    raw_signals = detect_divergences(merged_data, days_to_check, pair_sets)
    
    if not raw_signals:
        print("\nNo divergences detected today.")
        return
        
    # === EVALUATE SIGNALS WITH MODEL ===
    signals_today = []
    min_confidence = get_confidence_arg()
    
    # === Load config from args passed by dashboard ===
    try:
        account_size = float(sys.argv[2])
        risk_pct = float(sys.argv[3])
        leverage = float(sys.argv[4])
    except:
        account_size = 10000
        risk_pct = 1
        leverage = 30
        
    for signal in raw_signals:
        pair1 = signal["Pair"]
        check_date = signal["Date"]
        day_name = signal["Day"]
        direction = signal["Direction"]
        
        # Skip if we can't find FVG data
        if pair1 not in fvg_data:
            print(f"Skipping model evaluation for {pair1} - no FVG data")
            continue
            
        # === Features ===
        # Find the current week's start and end
        week_start = check_date - timedelta(days=check_date.weekday())
        week_end = week_start + timedelta(days=4)
        
        # Get FVG data for the current week
        week_fvg = fvg_data[pair1][(fvg_data[pair1].index >= week_start) & 
                                  (fvg_data[pair1].index <= week_end)]
        
        # Count bullish and bearish FVGs
        bullish_count = len(week_fvg[week_fvg['Type'].str.lower() == 'bullish'])
        bearish_count = len(week_fvg[week_fvg['Type'].str.lower() == 'bearish'])
        
        # Calculate high-low range
        p1_today = merged_data[pair1].loc[check_date]
        
        # Extract scalar values properly to avoid deprecation warnings
        p1_today_high = p1_today["High"] if isinstance(p1_today["High"], (int, float)) else p1_today["High"].iloc[0]
        p1_today_low = p1_today["Low"] if isinstance(p1_today["Low"], (int, float)) else p1_today["Low"].iloc[0]
        high_low_range = p1_today_high - p1_today_low

        # Create features for model
        features = pd.DataFrame.from_dict([{
            "DayOfWeek": day_name,
            "Direction": direction,
            "Bullish_FVG_Count": bullish_count,
            "Bearish_FVG_Count": bearish_count,
            "High_Low_Range": high_low_range
        }])
        
        # Convert categorical columns to proper type for model
        # This fixes the DataFrame.dtypes error by converting categorical variables
        if model_loaded:
            # Convert categorical columns to category type
            categorical_columns = ["DayOfWeek", "Direction"]
            for col in categorical_columns:
                features[col] = features[col].astype('category')
        
        # Skip model evaluation if model not loaded
        if not model_loaded:
            print(f"Skipping model evaluation - model not available")
            signal["Confidence"] = "N/A"
            position_size = calculate_position_size(
                account_size, risk_pct, leverage, signal["Entry"], signal["Stop"]
            )
            signal["Position Size"] = f"{position_size} lots"
            signals_today.append(signal)
            continue

        # Predict with model
        try:
            prob = model.predict_proba(features)[0][1 if direction == "long" else 0]
            confidence = round(prob * 100, 2)
            
            if confidence >= min_confidence:
                play_signal_sound()
                position_size = calculate_position_size(
                    account_size, risk_pct, leverage, signal["Entry"], signal["Stop"]
                )
                
                signal["Confidence"] = confidence
                signal["Position Size"] = f"{position_size} lots"
                signals_today.append(signal)
                
        except Exception as e:
            print(f"Error predicting with model: {e}")
            print("Consider retraining the model with the categorical features explicitly handled")
            
    # === SAVE TO EXCEL ===
    if signals_today:
        df_signals = pd.DataFrame(signals_today)
        if log_file.exists():
            try:
                existing = pd.read_excel(log_file)
                df_signals = pd.concat([existing, df_signals], ignore_index=True)
            except Exception as e:
                print(f"Error reading existing log: {e}")
        
        try:
            df_signals.to_excel(log_file, index=False)
        except Exception as e:
            print(f"Error saving signals to Excel: {e}")
            
        print("\nLIVE Divergence Signals:")
        for sig in signals_today:
            print(f"{sig['Date'].date()} | {sig['Pair']} | {sig['Direction'].upper()} | Type: {sig['Type']}")
            if 'Confidence' in sig:
                print(f"   Confidence: {sig['Confidence']}%")
            print(f"   Entry: {sig['Entry']}, Stop: {sig['Stop']}, Size: {sig['Position Size']}")
            print(f"   Compared with: {sig['Compared_With']}")
            print("-" * 50)
    else:
        print("\nNo valid divergences at this time.")

if __name__ == "__main__":
    main()