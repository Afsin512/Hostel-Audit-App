# Hostel Room Energy Audit App

Software-only energy audit for a hostel room. You log appliance ON/OFF sessions and daily occupancy; the app estimates energy, finds waste, fits a regression against NASA POWER temperature, and simulates savings.

## Run
```
pip install -r requirements.txt
streamlit run app.py
```
Data is saved next to `app.py` in `usage_log.csv`, `daily_context.csv`, `devices.csv`.

## Daily routine (21+ days, never batch at the end)
1. Edit the appliance table once (watts from labels/spec sheets).
2. Each evening, log every session (ON time, OFF time) and the day's context.
3. Do not use "DEMO data" for your submission; it is synthetic for testing only.

## Method
- Energy (kWh) = rated watts x hours ON / 1000
- Standby (kWh) = standby watts x hours not in use, for always-plugged devices
- CO2 = kWh x grid emission factor (set the latest CEA value in the sidebar)
- Regression: daily kWh ~ temperature (NASA POWER T2M) + occupancy hours
- Waste alert: occupancy-linked device ON for >0.5 h longer than you were in the room

## Limitations (state these in your report)
Rated watts are estimates (fan speed, laptop load vary). If possible, borrow a plug-in energy meter for 1-2 days and correct the watts in the appliance table.

## Deliverables mapping
Raw + cleaned CSV: Export tab | Graphs: Dashboard + Regression tabs | Recommendation numbers: Savings simulator
