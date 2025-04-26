import pandas as pd
from datetime import timedelta
from pathlib import Path
import sys


if getattr(sys, 'frozen', False):
    base_path = Path(sys._MEIPASS)  # When running from PyInstaller bundle
else:
    base_path = Path(__file__).resolve().parent.parent  # When running normally
db_path = base_path / "database"
pairs = ["EURUSD", "GBPUSD", "USDCAD", "USDJPY", "AUDUSD", "NZDUSD", "XAUUSD", "XAGUSD", "DXY"]

def detect_fvgs(df):
    fvgs = []
    for i in range(2, len(df)):
        c1 = df.iloc[i - 2]
        c2 = df.iloc[i - 1]
        c3 = df.iloc[i]

        c1_high = float(c1['High'])
        c2_high = float(c2['High'])
        c3_high = float(c3['High'])
        c1_low = float(c1['Low'])
        c2_low = float(c2['Low'])
        c3_low = float(c3['Low'])

        # Bullish FVG
        if c2_high > c1_high and c3_high > c2_high:
            if c1_high < c3_low:

                fvgs.append({
                    'Date': df.index[i],
                    'Day': df.index[i].day_name(),
                    'FVG High': c1['High'],
                    'FVG Low': c3['Low'],
                    'Type': 'Bullish'
                })

        # Bearish FVG
        if c2_low < c1_low and c3_low < c2_low:
            if c1_low > c3_high:

                fvgs.append({
                    'Date': df.index[i],
                    'Day': df.index[i].day_name(),
                    'FVG High': c3['High'],
                    'FVG Low': c1['Low'],
                    'Type': 'Bearish'
                })

    if not fvgs:
        return pd.DataFrame(columns=["Day", "FVG High", "FVG Low", "Type"])
    else:
        return pd.DataFrame(fvgs).set_index("Date")


for pair in pairs:
    ohlc_path = db_path / f"{pair}_ohlc.pkl"
    fvg_path = db_path / f"{pair}_fvg.pkl"

    if not ohlc_path.exists():
        print(f"OHLC missing for {pair}, skipping.")
        continue

    ohlc = pd.read_pickle(ohlc_path).sort_index()
    recent_ohlc = ohlc.loc[ohlc.index >= ohlc.index.max() - pd.Timedelta(days=14)]
  # last ~2-3 weeks

    new_fvgs = detect_fvgs(recent_ohlc)
    new_fvgs = new_fvgs.apply(lambda col: col.map(lambda x: x.iloc[0] if isinstance(x, pd.Series) else x))


    if fvg_path.exists():
        fvg = pd.read_pickle(fvg_path)
        frames = [fvg]
        if not new_fvgs.empty:
            frames.append(new_fvgs)
        combined = pd.concat(frames)
        combined = combined[~combined.index.duplicated(keep='first')].sort_index()
    else:
        combined = new_fvgs
    if new_fvgs.empty:
        print(f"[DEBUG] No new FVGs found for {pair}.")

    combined.to_pickle(fvg_path)
    print(f"{pair} FVGs updated.")
