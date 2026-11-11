import datetime as dt
import os

import numpy as np
import pandas as pd
import plotly.express as px
import requests
import streamlit as st

st.set_page_config(page_title="Hostel Room Energy Audit", layout="wide")

LOG, CTX, DEV = "usage_log.csv", "daily_context.csv", "devices.csv"
LOG_COLS = ["date", "device", "start", "end"]
CTX_COLS = ["date", "occupancy_hours", "exam_week", "note"]

# EDIT these to YOUR appliances (read watts from the label / spec sheet)
DEFAULT_DEVICES = pd.DataFrame(
    [
        ["Ceiling fan", 60, 0.0, False, True],
        ["Light", 18, 0.0, False, True],
        ["Laptop", 45, 1.0, False, False],
        ["Phone charger", 5, 0.3, True, False],
        ["Kettle", 1500, 0.0, False, False],
    ],
    columns=["device", "active_w", "standby_w", "always_plugged", "occupancy_linked"],
)


# ---------- storage ----------
def load(path, cols):
    return pd.read_csv(path) if os.path.exists(path) else pd.DataFrame(columns=cols)


def append(path, row, cols):
    df = load(path, cols)
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    df.to_csv(path, index=False)


def load_devices():
    if os.path.exists(DEV):
        return pd.read_csv(DEV)
    DEFAULT_DEVICES.to_csv(DEV, index=False)
    return DEFAULT_DEVICES.copy()


# ---------- demo data (for testing only, NOT for submission) ----------
def make_demo():
    rng = np.random.default_rng(1)
    rows, ctx = [], []
    for i in range(21):
        d = dt.date.today() - dt.timedelta(days=21 - i)
        occ = float(rng.integers(8, 20))
        ctx.append([d, occ, i in (14, 15, 16), ""])
        fan = occ + rng.integers(-2, 6)
        rows.append([d, "Ceiling fan", "18:00", f"{int((18 + fan) % 24):02d}:00"])
        rows.append([d, "Light", "18:00", f"{int((18 + occ / 2) % 24):02d}:00"])
        rows.append([d, "Laptop", "09:00", f"{int(9 + rng.integers(3, 9)):02d}:00"])
        if rng.random() < 0.4:
            rows.append([d, "Kettle", "07:00", "07:10"])
    return pd.DataFrame(rows, columns=LOG_COLS), pd.DataFrame(ctx, columns=CTX_COLS)


# ---------- calculations ----------
def sessions(log, dev):
    d = log.copy()
    d["start_dt"] = pd.to_datetime(d["date"].astype(str) + " " + d["start"].astype(str))
    d["end_dt"] = pd.to_datetime(d["date"].astype(str) + " " + d["end"].astype(str))
    d.loc[d.end_dt <= d.start_dt, "end_dt"] += pd.Timedelta(days=1)  # past midnight
    d["hours"] = (d.end_dt - d.start_dt).dt.total_seconds() / 3600
    d = d.merge(dev[["device", "active_w"]], on="device", how="left")
    d["kwh"] = d.hours * d.active_w / 1000
    return d


def daily_table(s, dev):
    s = s.assign(day=s.start_dt.dt.normalize())
    days = pd.date_range(s.day.min(), s.day.max())
    act = s.groupby(["day", "device"]).agg(hours=("hours", "sum"), kwh=("kwh", "sum"))
    rows = []
    for day in days:
        for _, r in dev.iterrows():
            h, k = act.hours.get((day, r.device), 0.0), act.kwh.get((day, r.device), 0.0)
            sb = r.standby_w * max(24 - h, 0) / 1000 if r.always_plugged else 0.0
            rows.append(dict(day=day, device=r.device, hours=h, active_kwh=k, standby_kwh=sb))
    t = pd.DataFrame(rows)
    t["total_kwh"] = t.active_kwh + t.standby_kwh
    return t


def hourly_profile(s, n_days):
    acc = np.zeros(24)
    for _, r in s.iterrows():
        t = r.start_dt
        while t < r.end_dt:
            nxt = min(t.floor("h") + pd.Timedelta(hours=1), r.end_dt)
            acc[t.hour] += (nxt - t).total_seconds() / 3600 * r.active_w / 1000
            t = nxt
    return pd.DataFrame({"hour": range(24), "avg_kwh": acc / max(n_days, 1)})


@st.cache_data(show_spinner=False)
def nasa_temp(lat, lon, start, end):
    r = requests.get(
        "https://power.larc.nasa.gov/api/temporal/daily/point",
        params=dict(parameters="T2M", community="RE", longitude=lon, latitude=lat,
                    start=start, end=end, format="JSON"),
        timeout=30,
    )
    t = pd.Series(r.json()["properties"]["parameter"]["T2M"])
    t = t[t > -900]
    return pd.DataFrame({"day": pd.to_datetime(t.index, format="%Y%m%d"), "temp_c": t.values})


# ---------- sidebar ----------
st.title("Hostel Room Energy Audit")
with st.sidebar:
    demo = st.toggle("Use DEMO data (testing only)", value=False)
    tariff = st.number_input("Tariff (Rs/kWh)", 0.0, 30.0, 6.0, 0.5)
    ef = st.number_input("Grid emission factor (kg CO2/kWh)", 0.0, 2.0, 0.71, 0.01,
                         help="Use the latest CEA figure")
    rooms = st.number_input("Rooms in hostel (for scale-up)", 1, 5000, 300)
    lat = st.number_input("Latitude", value=13.08)
    lon = st.number_input("Longitude", value=80.27)

dev = load_devices()
if demo:
    log, ctx = make_demo()
    st.warning("DEMO DATA: synthetic. Do not submit it as your dataset.")
else:
    log, ctx = load(LOG, LOG_COLS), load(CTX, CTX_COLS)

tab_log, tab_dash, tab_model, tab_save = st.tabs(
    ["1. Daily log", "2. Dashboard", "3. Regression & alerts", "4. Savings simulator"]
)

# ---------- tab 1: logging ----------
with tab_log:
    st.subheader("Appliances (edit watts from labels / spec sheets)")
    dev = st.data_editor(dev, num_rows="dynamic", use_container_width=True)
    if st.button("Save appliance table"):
        dev.to_csv(DEV, index=False)
        st.success("Saved")

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Log a usage session")
        with st.form("session", clear_on_submit=True):
            d = st.date_input("Date", dt.date.today())
            name = st.selectbox("Device", dev.device.tolist())
            s_t = st.time_input("Switched ON", dt.time(18, 0))
            e_t = st.time_input("Switched OFF", dt.time(23, 0))
            if st.form_submit_button("Add session") and not demo:
                append(LOG, dict(date=d, device=name, start=s_t.strftime("%H:%M"),
                                 end=e_t.strftime("%H:%M")), LOG_COLS)
                st.success("Logged (end time earlier than start = past midnight)")
    with c2:
        st.subheader("Daily context (once a day)")
        with st.form("context", clear_on_submit=True):
            d2 = st.date_input("Date ", dt.date.today())
            occ = st.number_input("Hours you were in the room", 0.0, 24.0, 12.0, 0.5)
            exam = st.checkbox("Exam week / holiday / unusual day")
            note = st.text_input("Note")
            if st.form_submit_button("Save day") and not demo:
                append(CTX, dict(date=d2, occupancy_hours=occ, exam_week=exam, note=note), CTX_COLS)
                st.success("Saved")
    st.caption(f"Days with logged sessions: {log['date'].nunique() if len(log) else 0} / 21 minimum")

if log.empty:
    for t in (tab_dash, tab_model, tab_save):
        with t:
            st.info("Log some sessions first.")
    st.stop()

S = sessions(log, dev)
D = daily_table(S, dev)
n_days = D.day.nunique()
per_day = D.groupby("day").total_kwh.sum()

# ---------- tab 2: dashboard ----------
with tab_dash:
    m = st.columns(4)
    m[0].metric("Avg daily kWh", f"{per_day.mean():.2f}")
    m[1].metric("Est. monthly kWh", f"{per_day.mean() * 30:.1f}")
    m[2].metric("Est. monthly bill (Rs)", f"{per_day.mean() * 30 * tariff:.0f}")
    m[3].metric("CO2 per year (kg)", f"{per_day.mean() * 365 * ef:.0f}")

    share = D.groupby("device")[["active_kwh", "standby_kwh"]].sum().reset_index()
    share["total"] = share.active_kwh + share.standby_kwh
    c1, c2 = st.columns(2)
    c1.plotly_chart(px.pie(share, names="device", values="total", title="Appliance-wise share of kWh"),
                    use_container_width=True)
    c2.plotly_chart(px.bar(D, x="day", y="total_kwh", color="device", title="Daily kWh by appliance"),
                    use_container_width=True)
    c3, c4 = st.columns(2)
    c3.plotly_chart(px.bar(hourly_profile(S, n_days), x="hour", y="avg_kwh",
                           title="Average hourly load profile (kWh)"), use_container_width=True)
    sb = pd.DataFrame({"type": ["Active", "Standby"],
                       "kWh": [D.active_kwh.sum(), D.standby_kwh.sum()]})
    c4.plotly_chart(px.bar(sb, x="type", y="kWh", title="Active vs standby energy"),
                    use_container_width=True)

# ---------- tab 3: regression + alerts ----------
with tab_model:
    st.subheader("Daily kWh vs temperature and occupancy")
    X = per_day.reset_index().rename(columns={"total_kwh": "kwh"})
    ctx2 = ctx.copy()
    ctx2["day"] = pd.to_datetime(ctx2["date"])
    X = X.merge(ctx2[["day", "occupancy_hours"]], on="day", how="left")
    try:
        temp = nasa_temp(lat, lon, X.day.min().strftime("%Y%m%d"), X.day.max().strftime("%Y%m%d"))
        X = X.merge(temp, on="day", how="left")
    except Exception as e:
        st.info(f"NASA POWER unavailable ({e}). Add temperature manually if needed.")
        X["temp_c"] = np.nan
    Xm = X.dropna(subset=["kwh", "temp_c", "occupancy_hours"])
    if len(Xm) >= 7:
        A = np.column_stack([np.ones(len(Xm)), Xm.temp_c, Xm.occupancy_hours])
        coef, *_ = np.linalg.lstsq(A, Xm.kwh, rcond=None)
        pred = A @ coef
        r2 = 1 - ((Xm.kwh - pred) ** 2).sum() / ((Xm.kwh - Xm.kwh.mean()) ** 2).sum()
        st.write(f"kWh = {coef[0]:.3f} + {coef[1]:.3f} x temp(C) + {coef[2]:.3f} x occupancy(h)   |   R2 = {r2:.2f}")
        fig = px.scatter(Xm, x="temp_c", y="kwh", color="occupancy_hours", title="Daily kWh vs temperature")
        k = np.polyfit(Xm.temp_c, Xm.kwh, 1)
        xs = np.linspace(Xm.temp_c.min(), Xm.temp_c.max(), 20)
        fig.add_scatter(x=xs, y=np.polyval(k, xs), mode="lines", name="trend")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Need at least 7 days with temperature and occupancy to fit the model.")

    st.subheader("Waste alerts: appliance ON longer than you were in the room")
    linked = dev[dev.occupancy_linked.astype(bool)].device.tolist()
    W = D[D.device.isin(linked)].merge(ctx2[["day", "occupancy_hours"]], on="day", how="inner")
    W = W.merge(dev[["device", "active_w"]], on="device")
    W["excess_h"] = (W.hours - W.occupancy_hours).clip(lower=0)
    W["wasted_kwh"] = W.excess_h * W.active_w / 1000
    bad = W[W.excess_h > 0.5].sort_values("wasted_kwh", ascending=False)
    if bad.empty:
        st.success("No wasteful days found (or no context logged yet).")
    else:
        st.warning(f"{len(bad)} wasteful device-days. Total wasted: {bad.wasted_kwh.sum():.2f} kWh")
        st.dataframe(bad[["day", "device", "hours", "occupancy_hours", "wasted_kwh"]], use_container_width=True)

# ---------- tab 4: simulator ----------
with tab_save:
    st.subheader("What if I changed my habits?")
    cut = st.slider("Cut occupancy-linked appliance hours by (%)", 0, 100, 25)
    kill_sb = st.checkbox("Eliminate standby loads (unplug / switch off)", True)
    T = D.groupby("device")[["active_kwh", "standby_kwh"]].sum() / n_days * 30
    lk = T.index.isin(linked)
    saved_room = T.active_kwh[lk].sum() * cut / 100 + (T.standby_kwh.sum() if kill_sb else 0)
    c = st.columns(4)
    c[0].metric("Saved / room / month (kWh)", f"{saved_room:.1f}")
    c[1].metric("Money saved / month (Rs)", f"{saved_room * tariff:.0f}")
    c[2].metric("CO2 saved / room / year (kg)", f"{saved_room * 12 * ef:.0f}")
    c[3].metric(f"CO2 saved, {rooms} rooms / year (kg)", f"{saved_room * 12 * ef * rooms:.0f}")

    st.subheader("Export datasets")
    st.download_button("Raw log CSV", log.to_csv(index=False), "raw_usage_log.csv")
    st.download_button("Cleaned daily dataset CSV", D.to_csv(index=False), "cleaned_daily_energy.csv")
