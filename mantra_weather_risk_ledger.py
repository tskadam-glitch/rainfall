"""
Mantra Weather Risk Ledger: Buy-Side Private Credit & Derivatives Portfolio Manager
=====================================================================================
Institutional-grade buy-side prototype for alternative asset managers tracking
Private Credit debt facilities and structural notes hedged with the NCDEX
RAINMUMBAI weather futures contract.
"""

import math
import random
from datetime import datetime, timedelta, date

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import scipy.stats as stats

# =====================================================================================
# GLOBAL CONSTANTS
# =====================================================================================

LPA_BASELINE_MM = 2206.7          # Long Period Average baseline (mm) for Mumbai monsoon CDR
TICK_VALUE_RS = 50                # ₹ per mm move (NCDEX RAINMUMBAI multiplier)
CONTRACT_MONTHS = ["JUN", "JUL", "AUG", "SEP"]
SEVERE_MARGIN_DRAWDOWN_PCT = 0.75 # Alert if variation margin eats 75% of initial margin
VAR_CONFIDENCE_Z = 2.33           # 99% one-tailed Z score for 3-day VaR
MARGIN_INITIAL_PCT = 0.12         # 12% initial margin on notional
CR_TO_RS = 1e7                    # 1 Crore = 1,00,00,000 INR

IMD_STATIONS = {
    "IMD Santacruz Observatory": {"lat": 19.0896, "lon": 72.8656},
    "IMD Colaba Observatory":    {"lat": 18.9070, "lon": 72.8147},
}

st.set_page_config(
    page_title="Mantra Weather Risk Ledger",
    page_icon="🌧️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# =====================================================================================
# CORPORATE STYLING
# =====================================================================================

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap');

    html, body, [class*="css"]  {
        font-family: 'IBM Plex Sans', sans-serif;
    }

    .mantra-header {
        background: linear-gradient(135deg, #0b1f3a 0%, #102a52 45%, #0e3a5f 100%);
        padding: 22px 30px;
        border-radius: 10px;
        border: 1px solid #1d4a78;
        margin-bottom: 18px;
    }
    .mantra-header h1 {
        color: #eaf2ff;
        font-size: 26px;
        font-weight: 700;
        margin: 0;
        letter-spacing: 0.3px;
    }
    .mantra-header p {
        color: #9fc1e8;
        font-size: 13.5px;
        margin: 6px 0 0 0;
        font-family: 'IBM Plex Mono', monospace;
    }

    .term-box {
        background-color: #050b14;
        color: #5ef58a;
        font-family: 'IBM Plex Mono', monospace;
        font-size: 12.3px;
        padding: 14px 16px;
        border-radius: 8px;
        border: 1px solid #163a2c;
        height: 250px;
        overflow-y: auto;
        line-height: 1.55;
    }

    .metric-card {
        background-color: #0f1b2d;
        border: 1px solid #1f3553;
        border-radius: 10px;
        padding: 14px 16px;
    }

    .alert-flash {
        animation: flashred 1s infinite;
        background-color: #7a0000;
        border: 2px solid #ff2b2b;
        color: #ffe9e9;
        font-family: 'IBM Plex Mono', monospace;
        font-weight: 700;
        font-size: 14.5px;
        padding: 16px 20px;
        border-radius: 8px;
        margin-bottom: 14px;
        letter-spacing: 0.4px;
    }
    @keyframes flashred {
        0%   { background-color: #7a0000; box-shadow: 0 0 6px #ff0000; }
        50%  { background-color: #b30000; box-shadow: 0 0 22px #ff2b2b; }
        100% { background-color: #7a0000; box-shadow: 0 0 6px #ff0000; }
    }

    .safe-banner {
        background-color: #0d2417;
        border: 1px solid #1f6b3f;
        color: #9fe8bb;
        font-family: 'IBM Plex Mono', monospace;
        font-size: 13.5px;
        padding: 12px 18px;
        border-radius: 8px;
        margin-bottom: 14px;
    }

    .section-title {
        font-size: 18px;
        font-weight: 700;
        color: #0b1f3a;
        border-left: 5px solid #0e3a5f;
        padding-left: 10px;
        margin: 18px 0 10px 0;
    }

    .pill {
        display: inline-block;
        background-color: #e6edf7;
        color: #0b1f3a;
        border-radius: 14px;
        padding: 3px 12px;
        font-size: 11.5px;
        font-weight: 600;
        margin-right: 6px;
    }

    .pill-pik { background-color: #fbe6d4; color: #7a3b00; }
    .pill-cash { background-color: #d7f0e1; color: #0a5c33; }

    div[data-testid="stMetricValue"] {
        font-family: 'IBM Plex Mono', monospace;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# =====================================================================================
# SESSION STATE INITIALIZATION
# =====================================================================================

def init_state():
    if "initialized" in st.session_state:
        return

    st.session_state.initialized = True

    # ---- Live market state for RAINMUMBAI contracts ----
    st.session_state.cdr_spot = 412.4
    st.session_state.prev_cdr_spot = 390.5 # Track previous day's spot
    st.session_state.oi_by_month = {m: random.randint(800, 3200) for m in CONTRACT_MONTHS}
    st.session_state.futures_ltp = {
        "JUN": 440.0,
        "JUL": 690.0,
        "AUG": 905.0,
        "SEP": 1040.0,
    }
    st.session_state.last_scrape_time = datetime.now()
    st.session_state.current_monsoon_day = 23 # E.g., June 23rd
    st.session_state.terminal_log = []
    log_line(f"AI Scraper Bootstrapped. NCDEX RAINMUMBAI feed handler online.")
    log_line(f"Baseline LPA anchor set to {LPA_BASELINE_MM} mm (IMD Santacruz / Colaba composite).")

    # ---- Security Master: Two pre-populated Structure 1 debt assets ----
    st.session_state.assets = [
        {
            "deal_id": "PC-MUM-401",
            "name": "Mumbai Commercial RE Development Note (Andheri Facility)",
            "start_date": date(2025, 4, 1),
            "maturity_date": date(2028, 3, 31),
            "capital_cr": 185.0,
            "base_coupon_pct": 13.25,
            "dsra_months": 3,
            "lat": 19.1197,
            "lon": 72.8468,
            "structure": "Structure 1 — Monsoon-Toggle Debt (Cash/PIK Coupon, DSRA Holiday)",
            "pik_capitalized_cr": 0.0,
            "hedges": [
                {"month": "JUL", "position": "Long", "lots": 40, "entry_price": 660.0,
                 "threshold_mm": 850.0, "holiday_active": False},
            ],
        },
        {
            "deal_id": "PC-MUM-402",
            "name": "Bhiwandi Port Logistics Infrastructure Note",
            "start_date": date(2026, 1, 15),
            "maturity_date": date(2029, 1, 14),
            "capital_cr": 240.0,
            "base_coupon_pct": 12.60,
            "dsra_months": 4,
            "lat": 19.2813,
            "lon": 73.0483,
            "structure": "Structure 1 — Monsoon-Toggle Debt (Cash/PIK Coupon, DSRA Holiday)",
            "pik_capitalized_cr": 0.0,
            "hedges": [
                {"month": "SEP", "position": "Long", "lots": 35, "entry_price": 1000.0,
                 "threshold_mm": 1180.0, "holiday_active": False},
            ],
        },
    ]

    # ---- 30-year synthetic historical IMD daily rainfall dataset ----
    st.session_state.history_df = generate_30yr_history()

def log_line(message: str):
    ts = datetime.now().strftime("%H:%M:%S")
    st.session_state.terminal_log.insert(0, f"[{ts}] {message}")
    st.session_state.terminal_log = st.session_state.terminal_log[:60]

# =====================================================================================
# SIMULATED 30-YEAR HISTORICAL DATASET GENERATION
# =====================================================================================

def generate_30yr_history(seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    years = range(1996, 2026)
    records = []
    monsoon_start_doy = 152   # ~June 1
    monsoon_end_doy = 273     # ~Sep 30

    for yr in years:
        year_total_target = rng.normal(LPA_BASELINE_MM, LPA_BASELINE_MM * 0.16)
        year_total_target = max(year_total_target, LPA_BASELINE_MM * 0.55)
        n_days = monsoon_end_doy - monsoon_start_doy + 1
        weights = rng.gamma(shape=1.6, scale=1.0, size=n_days)
        weights = weights / weights.sum()
        daily_rain = weights * year_total_target
        # add bursty cloudburst noise
        burst_mask = rng.random(n_days) < 0.05
        daily_rain[burst_mask] *= rng.uniform(2.0, 4.5, size=burst_mask.sum())

        start_date = date(yr, 1, 1) + timedelta(days=monsoon_start_doy - 1)
        for i in range(n_days):
            records.append({
                "date": start_date + timedelta(days=i),
                "year": yr,
                "day_of_monsoon": i + 1,
                "rainfall_mm": round(float(daily_rain[i]), 2),
            })

    df = pd.DataFrame(records)
    df["cumulative_cdr_mm"] = df.groupby("year")["rainfall_mm"].cumsum()
    return df

# =====================================================================================
# QUANTITATIVE ENGINE FUNCTIONS
# =====================================================================================

def hedge_mtm(hedge: dict, current_price: float) -> float:
    """MTM P&L in Rs for a single futures hedge leg."""
    direction = 1 if hedge["position"] == "Long" else -1
    return direction * (current_price - hedge["entry_price"]) * hedge["lots"] * TICK_VALUE_RS

def hedge_notional(hedge: dict, current_price: float) -> float:
    return current_price * hedge["lots"] * TICK_VALUE_RS

def var_3day_99_clean(hedge: dict, current_price: float, daily_vol_pct: float = 0.045) -> float:
    """Cleaner 99% 3-day VaR: Notional * Z * vol * sqrt(3)."""
    notional = hedge_notional(hedge, current_price)
    return notional * VAR_CONFIDENCE_Z * daily_vol_pct * math.sqrt(3)

def initial_margin(hedge: dict, current_price: float) -> float:
    return hedge_notional(hedge, current_price) * MARGIN_INITIAL_PCT

def variation_margin(hedge: dict, current_price: float) -> float:
    """Variation margin = today's MTM loss settled in cash (only loss side draws cash)."""
    mtm = hedge_mtm(hedge, current_price)
    return min(mtm, 0.0) * -1  # cash required to cover a loss; 0 if in profit

def evaluate_covenant_holiday(asset: dict, current_cdr: float):
    """
    If ANY linked hedge threshold is breached, the DSRA Covenant Holiday activates.
    """
    holiday_triggered = False
    for hedge in asset["hedges"]:
        hedge["holiday_active"] = current_cdr >= hedge["threshold_mm"]
        if hedge["holiday_active"]:
            holiday_triggered = True
    return holiday_triggered

def quarterly_distribution(asset: dict, current_cdr: float, total_mtm_rs: float):
    """
    Calculates the interest due, the portion deferred to PIK (if holiday active),
    and how much of the cash interest risk is offset by selling the hedge.
    """
    principal_rs = (asset["capital_cr"] + asset["pik_capitalized_cr"]) * CR_TO_RS
    quarterly_coupon_rs = principal_rs * (asset["base_coupon_pct"] / 100.0) / 4.0

    holiday_active = evaluate_covenant_holiday(asset, current_cdr)
    pik_pct_of_coupon = 0.55 if holiday_active else 0.0

    pik_portion_rs = quarterly_coupon_rs * pik_pct_of_coupon
    cash_portion_rs = quarterly_coupon_rs - pik_portion_rs
    
    # If the borrower defaults on the cash portion due to weather, the hedge profit offsets it.
    realizable_offset = max(0, min(cash_portion_rs, total_mtm_rs))

    return {
        "holiday_active": holiday_active,
        "principal_rs": principal_rs,
        "quarterly_coupon_rs": quarterly_coupon_rs,
        "cash_portion_rs": cash_portion_rs,
        "pik_portion_rs": pik_portion_rs,
        "realizable_offset_rs": realizable_offset
    }

def shadow_nav(asset: dict, current_cdr: float, futures_ltp: dict):
    """
    Shadow NAV = illiquid note principal + Unrealized NAV of Futures
    Unrealized NAV of Futures = Initial Margin Posted + MTM
    """
    total_hedge_mtm_rs = 0.0
    total_initial_margin_rs = 0.0
    
    for hedge in asset["hedges"]:
        px = futures_ltp.get(hedge["month"], hedge["entry_price"])
        total_hedge_mtm_rs += hedge_mtm(hedge, px)
        total_initial_margin_rs += initial_margin(hedge, px)

    dist = quarterly_distribution(asset, current_cdr, total_hedge_mtm_rs)
    note_value_rs = dist["principal_rs"]

    # Unrealised NAV of Futures tracks total cash value tied up in the exchange
    unrealised_futures_nav = total_initial_margin_rs + total_hedge_mtm_rs
    shadow_nav_rs = note_value_rs + unrealised_futures_nav
    
    return {
        "note_value_rs": note_value_rs,
        "hedge_mtm_rs": total_hedge_mtm_rs,
        "unrealised_futures_nav": unrealised_futures_nav,
        "shadow_nav_rs": shadow_nav_rs,
        "distribution": dist,
    }

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))

def fmt_rs_cr(value_rs: float) -> str:
    return f"₹{value_rs / CR_TO_RS:,.2f} Cr"

def fmt_rs(value_rs: float) -> str:
    return f"₹{value_rs:,.0f}"

# =====================================================================================
# RUN INITIALIZATION
# =====================================================================================

init_state()

# =====================================================================================
# HEADER
# =====================================================================================

st.markdown(
    """
    <div class="mantra-header">
        <h1>🌧️ Mantra Weather Risk Ledger</h1>
        <p>Buy-Side Private Credit &amp; Derivatives Portfolio Manager &nbsp;|&nbsp;
        NCDEX RAINMUMBAI Weather Futures &nbsp;|&nbsp;
        Tick Size: 1mm = ₹50 &nbsp;|&nbsp;
        Index: Cumulative Deviation Rainfall (CDR) &nbsp;|&nbsp;
        Stations: IMD Santacruz / Colaba</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# =====================================================================================
# SIDEBAR — MODULE 1: SIMULATED LIVE NCDEX INGESTION ENGINE
# =====================================================================================

with st.sidebar:
    st.markdown("### 🛰️ NCDEX Ingestion Engine")
    st.caption("Automated AI scraper · polling cadence: 15 min (simulated)")

    elapsed = (datetime.now() - st.session_state.last_scrape_time).total_seconds()
    st.markdown(
        f"<div class='metric-card'><b>Last Scrape:</b> "
        f"{st.session_state.last_scrape_time.strftime('%H:%M:%S')}<br>"
        f"<b>Elapsed:</b> {int(elapsed)}s ago<br>"
        f"<b>Prev Day Spot:</b> {st.session_state.prev_cdr_spot:.1f} mm<br>"
        f"<b>Live CDR Spot:</b> {st.session_state.cdr_spot:.1f} mm</div>",
        unsafe_allow_html=True,
    )

    st.write("")
    if st.button("🔄 Force 15-Min Scrape Refresh", use_container_width=True):
        log_line("AI Scraper Parsing NCDEX Web Nodes...")
        
        # simulate spot tick
        spot_shift = random.gauss(0, 15)
        st.session_state.cdr_spot = max(0.0, st.session_state.cdr_spot + spot_shift)

        for m in CONTRACT_MONTHS:
            tick = random.gauss(0, 12)
            st.session_state.futures_ltp[m] = max(0.0, st.session_state.futures_ltp[m] + tick)
            oi_tick = random.randint(-50, 120)
            st.session_state.oi_by_month[m] = max(50, st.session_state.oi_by_month[m] + oi_tick)

        log_line("Attributes Extracted Successfully.")
        log_line(
            f"CDR Spot updated -> {st.session_state.cdr_spot:.1f} mm | "
            + " ".join([f"{m}:{st.session_state.futures_ltp[m]:.0f}" for m in CONTRACT_MONTHS])
        )
        st.session_state.last_scrape_time = datetime.now()
        st.rerun()

    st.markdown("#### Live Contract Board")
    board_df = pd.DataFrame({
        "Month": CONTRACT_MONTHS,
        "LTP (mm)": [round(st.session_state.futures_ltp[m], 1) for m in CONTRACT_MONTHS],
        "OI (lots)": [st.session_state.oi_by_month[m] for m in CONTRACT_MONTHS],
    })
    st.dataframe(board_df, hide_index=True, use_container_width=True)

# =====================================================================================
# TABS
# =====================================================================================

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "🏗️ Security Master",
    "📊 Distribution & Margin Ledger",
    "🚨 Risk & Loss Alert Terminal",
    "📈 Forward Confidence Matrix",
    "🗺️ Spatial Basis Risk Map",
])

# -------------------------------------------------------------------------------------
# TAB 1 — MULTI-ASSET SECURITY MASTER
# -------------------------------------------------------------------------------------
with tab1:
    st.markdown("<div class='section-title'>Multi-Asset Security Master — Structure 1 Console</div>", unsafe_allow_html=True)
    st.write(
        "Structure 1 assets are **Monsoon-Toggle Debt** facilities carrying dynamic Cash/PIK "
        "coupon mechanics with a DSRA Covenant Reserve Holiday triggered by NCDEX RAINMUMBAI "
        "CDR thresholds linked to each note. The borrower holds the futures contract to hedge interest payment defaults."
    )

    for asset in st.session_state.assets:
        with st.container(border=True):
            colA, colB = st.columns([3, 1])
            with colA:
                st.markdown(f"**{asset['name']}** ·  `{asset['deal_id']}`")
                st.caption(f"Term: {asset['start_date'].strftime('%b %Y')} to {asset['maturity_date'].strftime('%b %Y')} | {asset['structure']}")
            with colB:
                st.markdown(f"<span class='pill'>Capital: ₹{asset['capital_cr']:.1f} Cr</span>", unsafe_allow_html=True)

            m1, m2, m3 = st.columns(3)
            m1.metric("Base Coupon Rate", f"{asset['base_coupon_pct']:.2f}%")
            m2.metric("DSRA Monthly Coverage", f"{asset['dsra_months']} months")
            m3.metric("PIK Capitalized to Date", f"₹{asset['pik_capitalized_cr']:.3f} Cr")

            hedge_rows = []
            for h in asset["hedges"]:
                hedge_rows.append({
                    "Contract Month": h["month"],
                    "Position": h["position"],
                    "Lots": h["lots"],
                    "Entry Price (mm)": h["entry_price"],
                    "CDR Holiday Threshold (mm)": h["threshold_mm"],
                    "Holiday Status": "🟠 ACTIVE" if h["holiday_active"] else "🟢 Standard",
                })
            st.dataframe(pd.DataFrame(hedge_rows), hide_index=True, use_container_width=True)

# -------------------------------------------------------------------------------------
# TAB 2 — QUANTITATIVE DISTRIBUTION ENGINE & MARGIN LEDGER
# -------------------------------------------------------------------------------------
with tab2:
    st.markdown("<div class='section-title'>Quantitative Distribution Engine & Derivative Margin Ledger</div>", unsafe_allow_html=True)

    total_shadow_nav_rs = 0.0

    for asset in st.session_state.assets:
        nav = shadow_nav(asset, st.session_state.cdr_spot, st.session_state.futures_ltp)
        dist = nav["distribution"]
        total_shadow_nav_rs += nav["shadow_nav_rs"]

        with st.container(border=True):
            st.markdown(f"### {asset['name']}  ·  `{asset['deal_id']}`")

            status_pill = "<span class='pill pill-pik'>COVENANT HOLIDAY ACTIVE — PIK TOGGLE ON</span>" if dist["holiday_active"] \
                else "<span class='pill pill-cash'>STANDARD CASH COUPON</span>"
            st.markdown(status_pill, unsafe_allow_html=True)

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Quarterly Interest Due", fmt_rs_cr(dist["quarterly_coupon_rs"]))
            c2.metric("Cash Interest at Risk", fmt_rs_cr(dist["cash_portion_rs"]))
            
            # The core mechanism: Selling futures to offset interest payment loss
            offset_color = "normal" if dist["realizable_offset_rs"] == 0 else "off"
            c3.metric("Hedge Offset Realized", fmt_rs_cr(dist["realizable_offset_rs"]), 
                      delta=f"From ₹{nav['hedge_mtm_rs']/CR_TO_RS:,.2f}Cr total MTM" if nav['hedge_mtm_rs']>0 else None, delta_color=offset_color)
            
            c4.metric("Shadow NAV (Incl. Futures)", fmt_rs_cr(nav["shadow_nav_rs"]))

            st.markdown("#### Hedge Book — Margin & Unrealised NAV Tracker")
            margin_rows = []
            for h in asset["hedges"]:
                px = st.session_state.futures_ltp.get(h["month"], h["entry_price"])
                mtm = hedge_mtm(h, px)
                im = initial_margin(h, px)
                vm = variation_margin(h, px)
                
                margin_rows.append({
                    "Month": h["month"],
                    "Position": h["position"],
                    "Lots": h["lots"],
                    "Current Px (mm)": round(px, 1),
                    "Initial Margin Req (₹)": round(im, 0),
                    "Variation Margin Due (₹)": round(vm, 0),
                    "MTM P&L (₹)": round(mtm, 0),
                    "Unrealised NAV of Futures (₹)": round(im + mtm, 0) # Margin posted + Profits/Losses
                })
            margin_df = pd.DataFrame(margin_rows)
            st.dataframe(margin_df, hide_index=True, use_container_width=True)

# -------------------------------------------------------------------------------------
# TAB 3 — HIGH-SEVERITY RISK & EXTREME LOSS ALERT TERMINAL
# -------------------------------------------------------------------------------------
with tab3:
    st.markdown("<div class='section-title'>High-Severity Risk & Extreme Loss Alert Terminal</div>", unsafe_allow_html=True)
    st.write(
        "This monitor evaluates if the daily CDR shifts are causing variation margin calls "
        "that deplete operational liquidity to unreasonable levels, drawing critical capital losses."
    )

    breach_found = False
    for asset in st.session_state.assets:
        for h in asset["hedges"]:
            px = st.session_state.futures_ltp.get(h["month"], h["entry_price"])
            im = initial_margin(h, px)
            vm = variation_margin(h, px)
            
            if vm > (im * SEVERE_MARGIN_DRAWDOWN_PCT):
                breach_found = True
                st.markdown(
                    f"<div class='alert-flash'>⚠️ CRITICAL MARGIN CALL: {asset['deal_id']} — {h['month']} Tranche.<br>"
                    f"Variation margin (₹{vm:,.0f}) exceeds {SEVERE_MARGIN_DRAWDOWN_PCT*100}% of Initial Margin (₹{im:,.0f}).<br>"
                    f"Unrealised NAV is structurally compromised. Immediate liquidity required or position unwind imminent.</div>",
                    unsafe_allow_html=True,
                )

    if not breach_found:
        st.markdown(
            "<div class='safe-banner'>✅ No margin exhaustion detected. Unrealised NAVs are adequately collateralized.</div>",
            unsafe_allow_html=True,
        )

# -------------------------------------------------------------------------------------
# TAB 4 — FORWARD CONFIDENCE MATRIX
# -------------------------------------------------------------------------------------
with tab4:
    st.markdown("<div class='section-title'>Forward Climate Confidence Matrix (Trade Entry Modeling)</div>", unsafe_allow_html=True)
    st.write(
        "Using 30-year historical daily LPA calculations to determine the statistical confidence "
        "of the remaining monsoon season delivering enough rainfall to breach structural thresholds."
    )

    hist_df = st.session_state.history_df
    
    colA, colB, colC = st.columns(3)
    with colA:
        entry_day = st.number_input("Entry Date (Day of Monsoon, 1=Jun 1)", min_value=1, max_value=122, value=st.session_state.current_monsoon_day)
    with colB:
        current_spot = st.number_input("Spot CDR on Entry Date (mm)", value=float(st.session_state.prev_cdr_spot))
    with colC:
        target_cdr = st.number_input("Target CDR Threshold (mm)", value=850.0, step=10.0)

    # Calculate remaining required rainfall
    remaining_required = target_cdr - current_spot
    
    # Isolate historical data for the remaining days of the season
    remaining_days_df = hist_df[hist_df["day_of_monsoon"] > entry_day]
    
    # Sum rainfall from entry_day to end of season for each historical year
    yearly_remaining = remaining_days_df.groupby("year")["rainfall_mm"].sum()
    
    mu_rem = yearly_remaining.mean()
    std_rem = yearly_remaining.std()
    
    st.markdown(f"**To hit the target of {target_cdr} mm, the remaining monsoon must deliver {remaining_required:.1f} mm.**")
    st.caption(f"Historical stats from Day {entry_day} to Day 122 -> Mean: {mu_rem:.1f} mm | Std Dev: {std_rem:.1f} mm")

    if remaining_required <= 0:
        prob_breach = 1.0
    else:
        # Z-score for remaining required vs historical remaining distribution
        z = (remaining_required - mu_rem) / std_rem if std_rem > 0 else 0.0
        prob_breach = 1 - stats.norm.cdf(z)
        
    prob_shortfall = 1 - prob_breach

    pcol1, pcol2 = st.columns(2)
    pcol1.metric("Confidence of Surpassing Target (Breach)", f"{prob_breach*100:.2f}%")
    pcol2.metric("Confidence of Falling Short", f"{prob_shortfall*100:.2f}%")
    
    # Plotting the historical distribution of the remaining rainfall
    fig = go.Figure()
    fig.add_trace(go.Histogram(
        x=yearly_remaining,
        nbinsx=15,
        name="Historical Remaining Rainfall",
        marker_color="#0e3a5f"
    ))
    fig.add_vline(x=remaining_required, line_dash="dash", line_color="#c0392b", annotation_text=f"Required: {remaining_required:.1f} mm")
    fig.update_layout(
        title=f"Distribution of Rainfall Delivered After Day {entry_day} (1996-2025)",
        xaxis_title="Rainfall (mm)",
        yaxis_title="Frequency (Years)",
        height=400,
        plot_bgcolor="white"
    )
    st.plotly_chart(fig, use_container_width=True)

# -------------------------------------------------------------------------------------
# TAB 5 — SPATIAL BASIS RISK MAPPING (GIS SCOPE)
# -------------------------------------------------------------------------------------
with tab5:
    st.markdown("<div class='section-title'>Spatial Basis Risk Mapping — GIS Scope</div>", unsafe_allow_html=True)
    st.write(
        "Flags structural basis risk where illiquid physical collateral may suffer localized "
        "weather damage that the liquid benchmark indices (Santacruz/Colaba) fail to capture."
    )

    map_fig = go.Figure()
    map_fig.add_trace(go.Scattermap(
        lat=[v["lat"] for v in IMD_STATIONS.values()],
        lon=[v["lon"] for v in IMD_STATIONS.values()],
        mode="markers+text",
        marker=dict(size=16, color="#c0392b", symbol="circle"),
        text=list(IMD_STATIONS.keys()),
        textposition="top right",
        name="IMD Reference Stations",
    ))

    map_fig.add_trace(go.Scattermap(
        lat=[a["lat"] for a in st.session_state.assets],
        lon=[a["lon"] for a in st.session_state.assets],
        mode="markers+text",
        marker=dict(size=14, color="#0e3a5f", symbol="circle"),
        text=[a["deal_id"] for a in st.session_state.assets],
        textposition="bottom right",
        name="Private Credit Assets",
    ))

    map_fig.update_layout(
        height=520,
        map=dict(style="open-street-map", zoom=9.4, center=dict(lat=19.05, lon=72.93)),
        margin=dict(l=0, r=0, t=10, b=0),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0),
    )
    st.plotly_chart(map_fig, use_container_width=True)

    st.markdown("#### Geodesic Distance & Basis Risk Flag Matrix")
    BASIS_RISK_KM_THRESHOLD = 12.0
    risk_rows = []
    for asset in st.session_state.assets:
        for station_name, coords in IMD_STATIONS.items():
            dist_km = haversine_km(asset["lat"], asset["lon"], coords["lat"], coords["lon"])
            flag = "🔴 HIGH BASIS RISK" if dist_km > BASIS_RISK_KM_THRESHOLD else "🟢 Low Basis Risk"
            risk_rows.append({
                "Deal ID": asset["deal_id"],
                "Asset Name": asset["name"],
                "Reference Station": station_name,
                "Geodesic Distance (km)": round(dist_km, 2),
                "Basis Risk Flag": flag,
            })

    st.dataframe(pd.DataFrame(risk_rows), hide_index=True, use_container_width=True)