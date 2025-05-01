from pathlib import Path
from datetime import datetime, timedelta
import yfinance as yf
import pandas as pd
import os

# === INIT ===
base_path = Path(__file__).resolve().parent.parent
db_path = base_path / "database"

symbols = {
    "DXY": "DX-Y.NYB",
    "XAUUSD": "GC=F",
    "XAGUSD": "SI=F"
}

today = datetime.now().date()
yesterday = today - timedelta(days=1)

for pair, yahoo_symbol in symbols.items():
    file_path = db_path / f"{pair}_ohlc.pkl"

    if file_path.exists():
        df = pd.read_pickle(file_path)
        df.index = pd.to_datetime(df.index)
        existing_dates = set(df.index.date)
        last_date = max(existing_dates)
    else:
        df = pd.DataFrame()
        existing_dates = set()
        last_date = today - timedelta(days=365 * 10)

    start_date = last_date + timedelta(days=1)

    if start_date > yesterday:
        print(f"{pair} is already up-to-date.")
        continue

    print(f"Updating {pair} from {start_date} to {yesterday}")

    # Download missing data
    try:
        # Try with explicit auto_adjust=False
        data = yf.download(yahoo_symbol, start=start_date, end=today, interval="1d", progress=False, auto_adjust=False)
        
        # Print column information for debugging
        print(f"Data columns: {data.columns}")
        
        if data.empty:
            print(f"No data returned for {pair}")
            continue

        # Ensure we have the correct column structure
        required_cols = ["Open", "High", "Low", "Close"]
        
        # Handle if data comes back with multi-level columns
        if isinstance(data.columns, pd.MultiIndex):
            print(f"Multi-index columns detected: {data.columns}")
            # Try to find the correct column level with our required columns
            for level in range(data.columns.nlevels):
                level_values = [col[level] if isinstance(col, tuple) else col for col in data.columns]
                if all(col in level_values for col in required_cols):
                    data.columns = level_values
                    print(f"Using column level {level}: {data.columns}")
                    break
            else:
                # If we get here, we didn't find our required columns at any level
                raise ValueError(f"Could not find required columns in data: {data.columns}")
        
        # Verify we have the columns we need
        missing_cols = [col for col in required_cols if col not in data.columns]
        if missing_cols:
            print(f"Warning: Missing columns: {missing_cols}")
            # If we're missing required columns, try to map from what's available
            col_mapping = {}
            possible_variants = {
                "Open": ["open", "OPEN", "Open Price", "open_price"],
                "High": ["high", "HIGH", "High Price", "high_price"],
                "Low": ["low", "LOW", "Low Price", "low_price"],
                "Close": ["close", "CLOSE", "Close Price", "close_price", "Adj Close", "Adj. Close"]
            }
            
            for req_col, variants in possible_variants.items():
                for variant in variants:
                    if variant in data.columns:
                        col_mapping[req_col] = variant
                        break
            
            if col_mapping:
                print(f"Using column mapping: {col_mapping}")
                data = data.rename(columns=col_mapping)
        
        # Process new data
        for date, row in data.iterrows():
            # Skip if we already have this date
            if date.date() in existing_dates:
                continue

            try:
                # Create a clean row with safe access to columns
                clean_row = {"Day": date.day_name()}
                
                for col in required_cols:
                    if col in row.index:
                        clean_row[col] = float(row[col])
                    else:
                        # If we can't find the column, print debug info and use None
                        print(f"Column {col} not found in row with index {row.index}")
                        clean_row[col] = None
                
                # Only add the row if we have at least some valid data
                if any(v is not None for v in clean_row.values()):
                    df.loc[date] = clean_row
                    existing_dates.add(date.date())
                    print(f"Added data for {pair} on {date.date()}")
                else:
                    print(f"No valid data found for {pair} on {date.date()}")
                    
            except Exception as e:
                print(f"Error adding row for {pair} on {date}: {e}")
                print(f"Row data available: {row.index.tolist()}")
                
    except Exception as e:
        print(f"Download error for {pair}: {e}")

    # Ensure no duplicates and properly sorted
    df = df[~df.index.duplicated(keep='last')].sort_index()
    df.to_pickle(file_path)
    print(f"{pair} updated. Total rows: {len(df)}")

print("Yahoo-based updates complete.")