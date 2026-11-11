"""Download the UCI Individual Household Electric Power Consumption dataset (CC BY 4.0),
cut a 21-day window, clean it, add NASA POWER temperature, and make 2 graphs.

Run:  python get_public_dataset.py
Or:   python get_public_dataset.py 2008-01-01 2008-01-21

Needs: pip install pandas requests matplotlib
Citation: Hebrail, G. & Berard, A. (2006). Individual Household Electric Power
Consumption. UCI Machine Learning Repository. https://doi.org/10.24432/C58K54
"""
import io
import os
import sys
import zipfile

import matplotlib.pyplot as plt
import pandas as pd
import requests

START = sys.argv[1] if len(sys.argv) > 2 else "2008-01-01"
END = sys.argv[2] if len(sys.argv) > 2 else "2008-01-21"
URL = "https://archive.ics.uci.edu/static/public/235/individual+household+electric+power+consumption.zip"
TXT = "household_power_consumption.txt"

# 1) download (skipped if the file is already in this folder)
if not os.path.exists(TXT):
    print("Downloading UCI dataset (about 20 MB)...")
    try:
        r = requests.get(URL, timeout=120)
        r.raise_for_status()
        zipfile.ZipFile(io.BytesIO(r.content)).extract(TXT)
    except Exception as e:
        sys.exit(
            f"Download failed: {e}\n"
            "Manual fix: open https://archive.ics.uci.edu/dataset/235 , click Download, "
            f"unzip, and put {TXT} in this folder. Then run this script again."
        )

# 2) load + clean
df = pd.read_csv(TXT, sep=";", na_values="?", low_memory=False)
df["timestamp"] = pd.to_datetime(df["Date"] + " " + df["Time"], format="%d/%m/%Y %H:%M:%S")
df = df.set_index("timestamp").drop(columns=["Date", "Time"]).astype(float)
df = df.loc[START:END + " 23:59"]
raw = df.copy()
raw.to_csv("public_raw_21days.csv")

missing = int(df.isna().any(axis=1).sum())
df = df.interpolate(limit=30).dropna()  # fill gaps up to 30 min, drop the rest
print(f"Window {START} to {END}: {len(raw)} rows, {missing} with missing values, {len(df)} kept")

# 3) energy per minute in Wh, then hourly and daily kWh
df["total_wh"] = df["Global_active_power"] * 1000 / 60
df["other_wh"] = df["total_wh"] - df[["Sub_metering_1", "Sub_metering_2", "Sub_metering_3"]].sum(axis=1)
cols = {"total_wh": "total_kwh", "Sub_metering_1": "kitchen_kwh",
        "Sub_metering_2": "laundry_kwh", "Sub_metering_3": "water_heater_ac_kwh", "other_wh": "other_kwh"}
hourly = (df[list(cols)].resample("h").sum() / 1000).rename(columns=cols)
daily = hourly.resample("D").sum()
hourly.to_csv("public_cleaned_hourly.csv")

# 4) real temperature from NASA POWER (house is in Sceaux, near Paris)
try:
    t = requests.get("https://power.larc.nasa.gov/api/temporal/daily/point", params=dict(
        parameters="T2M", community="RE", latitude=48.78, longitude=2.30,
        start=START.replace("-", ""), end=END.replace("-", ""), format="JSON"), timeout=30)
    t = pd.Series(t.json()["properties"]["parameter"]["T2M"])
    daily["temp_c"] = [t.get(d.strftime("%Y%m%d")) for d in daily.index]
except Exception as e:
    print("Temperature download failed (continuing without it):", e)
daily.to_csv("public_cleaned_daily.csv")

# 5) two graphs
prof = hourly.groupby(hourly.index.hour).mean()
prof[["kitchen_kwh", "laundry_kwh", "water_heater_ac_kwh", "other_kwh"]].plot.bar(stacked=True, figsize=(9, 4))
plt.title("Average hourly load profile (kWh)"); plt.xlabel("Hour of day"); plt.tight_layout()
plt.savefig("graph1_hourly_profile.png", dpi=150); plt.close()

daily[["kitchen_kwh", "laundry_kwh", "water_heater_ac_kwh", "other_kwh"]].plot.bar(stacked=True, figsize=(9, 4))
plt.title("Daily energy by sub-meter (kWh)"); plt.xlabel("Day"); plt.tight_layout()
plt.savefig("graph2_daily_by_submeter.png", dpi=150); plt.close()

print("Done. Files: public_raw_21days.csv, public_cleaned_hourly.csv, public_cleaned_daily.csv, 2 PNG graphs")
