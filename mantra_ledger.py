"""
Mantra Weather Risk Ledger: Buy-Side Private Credit & Derivatives Portfolio Manager
=====================================================================================
Institutional-grade buy-side prototype for alternative asset managers tracking
Private Credit debt facilities and structural notes hedged with the NCDEX
RAINMUMBAI weather futures contract.

Run with:  streamlit run mantra_weather_risk_ledger.py
"""

import math
import random
from datetime import datetime, timedelta, date

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# =====================================================================================
# GLOBAL CONSTANTS
# =====================================================================================

LPA_BASELINE_MM = 2206.7          # Long Period Average baseline (mm) for Mumbai monsoon CDR
TICK_VALUE_RS = 50                # ₹ per mm move (NCDEX RAINMUMBAI multiplier)
CONTRACT_MONTHS = ["JUN", "JUL", "AUG", "SEP"]
SEVERE_BOUNDARY_MM = 400.0        # CDR deviation past which a severe alert triggers
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
    st.session_state.cdr_spot = 612.4
    st.session_state.oi_by_month = {m: random.randint(800, 3200) for m in CONTRACT_MONTHS}
    st.session_state.futures_ltp = {
        "JUN": 540.0,
        "JUL": 690.0,
        "AUG": 905.0,
        "SEP": 1040.0,
    }
    st.session_state.last_scrape_time = datetime.now()
    st.session_state.terminal_log = []
    log_line(f"AI Scraper Bootstrapped. NCDEX RAINMUMBAI feed handler online.")
    log_line(f"Baseline LPA anchor set to {LPA_BASELINE_MM} mm (IMD Santacruz / Colaba composite).")

    # ---- Security Master: Two pre-populated Structure 1 debt assets ----
    st.session_state.assets = [
        {
            "deal_id": "PC-MUM-401",
            "name": "Mumbai Commercial RE Development Note (Andheri Facility)",
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
                {"month": "AUG", "position": "Long", "lots": 25, "entry_price": 880.0,
                 "threshold_mm": 1050.0, "holiday_active": False},
            ],
        },
        {
            "deal_id": "PC-MUM-402",
            "name": "Bhiwandi Port Logistics Infrastructure Note",
            "capital_cr": 240.0,
            "base_coupon_pct": 12.60,
            "dsra_months": 4,
            "lat": 19.2813,
            "lon": 73.0483,
            "structure": "Structure 1 — Monsoon-Toggle Debt (Cash/PIK Coupon, DSRA Holiday)",
            "pik_capitalized_cr": 0.0,
            "hedges": [
                {"month": "JUN", "position": "Long", "lots": 30, "entry_price": 510.0,
                 "threshold_mm": 700.0, "holiday_active": False},
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


def var_3day_99(hedge: dict, current_price: float, daily_vol_pct: float = 0.045) -> float:
    """99% 3-day Value at Risk for a futures position."""
    notional = hedge_notional(hedge, current_price)
    three_day_vol = daily_vol_pct * math.sqrt(3)
    return notional * three_day_vol * VAR_CONFIDENCE_Z / 2.33 * VAR_CONFIDENCE_Z  # scaled VaR estimate


def var_3day_99_clean(hedge: dict, current_price: float, daily_vol_pct: float = 0.045) -> float:
    """Cleaner 99% 3-day VaR: Notional * Z * vol * sqrt(3)."""
    notional = hedge_notional(hedge, current_price)
    return notional * VAR_CONFIDENCE_Z * daily_vol_pct * math.sqrt(3)


def initial_margin(hedge: dict, current_price: float) -> float:
    return hedge_notional(hedge, current_price) * MARGIN_INITIAL_PCT


def variation_margin(hedge: dict, current_price: float) -> float:
    """Variation margin = today's MTM loss/gain settled in cash (only loss side draws cash)."""
    mtm = hedge_mtm(hedge, current_price)
    return min(mtm, 0.0) * -1  # cash required to cover a loss; 0 if in profit


def evaluate_covenant_holiday(asset: dict, current_cdr: float):
    """
    For each hedge leg, evaluate whether the CDR threshold has been breached.
    If ANY linked hedge threshold is breached, the DSRA Covenant Holiday activates:
    cash coupon requirement is reduced and the deferred portion is capitalized as PIK.
    """
    holiday_triggered = False
    for hedge in asset["hedges"]:
        hedge["holiday_active"] = current_cdr >= hedge["threshold_mm"]
        if hedge["holiday_active"]:
            holiday_triggered = True
    return holiday_triggered


def quarterly_distribution(asset: dict, current_cdr: float):
    """
    Returns dict with base coupon, cash portion, PIK portion, and updates
    the asset's capitalized PIK ledger in-place if a holiday is active.
    """
    principal_rs = (asset["capital_cr"] + asset["pik_capitalized_cr"]) * CR_TO_RS
    quarterly_coupon_rs = principal_rs * (asset["base_coupon_pct"] / 100.0) / 4.0

    holiday_active = evaluate_covenant_holiday(asset, current_cdr)

    if holiday_active:
        pik_pct_of_coupon = 0.55   # 55% of coupon deferred to PIK during a Covenant Holiday
    else:
        pik_pct_of_coupon = 0.0

    pik_portion_rs = quarterly_coupon_rs * pik_pct_of_coupon
    cash_portion_rs = quarterly_coupon_rs - pik_portion_rs

    return {
        "holiday_active": holiday_active,
        "principal_rs": principal_rs,
        "quarterly_coupon_rs": quarterly_coupon_rs,
        "cash_portion_rs": cash_portion_rs,
        "pik_portion_rs": pik_portion_rs,
    }


def shadow_nav(asset: dict, current_cdr: float, futures_ltp: dict):
    """
    Shadow NAV = illiquid note principal (incl. capitalized PIK) + liquid hedge MTM book.
    """
    dist = quarterly_distribution(asset, current_cdr)
    note_value_rs = dist["principal_rs"]

    total_hedge_mtm_rs = 0.0
    for hedge in asset["hedges"]:
        px = futures_ltp.get(hedge["month"], hedge["entry_price"])
        total_hedge_mtm_rs += hedge_mtm(hedge, px)

    shadow_nav_rs = note_value_rs + total_hedge_mtm_rs
    return {
        "note_value_rs": note_value_rs,
        "hedge_mtm_rs": total_hedge_mtm_rs,
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
    return f"₹{value_rs / CR_TO_RS:,.3f} Cr"


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
        Stations: IMD Santacruz / Colaba &nbsp;|&nbsp;
        LPA Baseline: 2,206.7 mm</p>
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
        f"<b>CDR Spot:</b> {st.session_state.cdr_spot:.1f} mm</div>",
        unsafe_allow_html=True,
    )

    st.write("")
    if st.button("🔄 Force 15-Min Scrape Refresh", use_container_width=True):
        log_line("AI Scraper Parsing NCDEX Web Nodes...")
        log_line("Crawling Market Watch DOM tree — RAINMUMBAI segment...")

        # simulate spot tick
        spot_shift = random.gauss(0, 35)
        st.session_state.cdr_spot = max(0.0, st.session_state.cdr_spot + spot_shift)

        for m in CONTRACT_MONTHS:
            tick = random.gauss(0, 28)
            st.session_state.futures_ltp[m] = max(0.0, st.session_state.futures_ltp[m] + tick)
            oi_tick = random.randint(-150, 220)
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
        "LTP (mm-pts)": [round(st.session_state.futures_ltp[m], 1) for m in CONTRACT_MONTHS],
        "OI (lots)": [st.session_state.oi_by_month[m] for m in CONTRACT_MONTHS],
    })
    st.dataframe(board_df, hide_index=True, use_container_width=True)

    st.markdown("#### Pseudo-Terminal Log")
    log_html = "<br>".join(st.session_state.terminal_log) if st.session_state.terminal_log else "Awaiting first scrape..."
    st.markdown(f"<div class='term-box'>{log_html}</div>", unsafe_allow_html=True)

# =====================================================================================
# TABS
# =====================================================================================

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "🛰️ NCDEX Ingestion",
    "🏗️ Security Master",
    "📊 Distribution & Margin Ledger",
    "🚨 Risk & Loss Alert Terminal",
    "📈 30-Yr Trend & Confidence Matrix",
    "🗺️ Spatial Basis Risk Map",
])

# -------------------------------------------------------------------------------------
# TAB 1 — NCDEX INGESTION (Main Panel Mirror)
# -------------------------------------------------------------------------------------
with tab1:
    st.markdown("<div class='section-title'>Simulated Live NCDEX RAINMUMBAI Ingestion Engine</div>", unsafe_allow_html=True)
    st.write(
        "An automated AI data pipeline simulates scraping of the NCDEX market watch feed "
        "every 15 minutes, extracting CDR spot levels, futures LTPs across active contract "
        "months, and live Open Interest. Use the sidebar control to force a manual refresh tick."
    )

    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("CDR Spot (Cumulative Deviation Rainfall)", f"{st.session_state.cdr_spot:.1f} mm",
                   f"{st.session_state.cdr_spot - LPA_BASELINE_MM:+.1f} mm vs LPA")
    with c2:
        st.metric("LPA Baseline Anchor", f"{LPA_BASELINE_MM:.1f} mm")
    with c3:
        deviation_pct = (st.session_state.cdr_spot / LPA_BASELINE_MM - 1) * 100
        st.metric("Deviation vs LPA", f"{deviation_pct:+.1f}%")

    st.markdown("#### Active Contract Months — Futures LTP & Open Interest")
    fig_board = go.Figure()
    fig_board.add_trace(go.Bar(
        x=CONTRACT_MONTHS,
        y=[st.session_state.futures_ltp[m] for m in CONTRACT_MONTHS],
        name="LTP (mm-pts)",
        marker_color="#0e3a5f",
    ))
    fig_board.update_layout(
        height=320,
        margin=dict(l=10, r=10, t=30, b=10),
        yaxis_title="LTP (mm index points)",
        showlegend=False,
        plot_bgcolor="white",
    )
    st.plotly_chart(fig_board, use_container_width=True)

    st.markdown("#### Full Terminal Log")
    full_log_html = "<br>".join(st.session_state.terminal_log) if st.session_state.terminal_log else "No log entries yet."
    st.markdown(f"<div class='term-box' style='height:200px;'>{full_log_html}</div>", unsafe_allow_html=True)

# -------------------------------------------------------------------------------------
# TAB 2 — MULTI-ASSET SECURITY MASTER
# -------------------------------------------------------------------------------------
with tab2:
    st.markdown("<div class='section-title'>Multi-Asset Security Master — Structure 1 Console</div>", unsafe_allow_html=True)
    st.write(
        "Structure 1 assets are **Monsoon-Toggle Debt** facilities carrying dynamic Cash/PIK "
        "coupon mechanics with a DSRA Covenant Reserve Holiday triggered by NCDEX RAINMUMBAI "
        "CDR thresholds linked to each note."
    )

    for asset in st.session_state.assets:
        with st.container(border=True):
            colA, colB = st.columns([3, 1])
            with colA:
                st.markdown(f"**{asset['name']}**  ·  `{asset['deal_id']}`")
                st.caption(asset["structure"])
            with colB:
                st.markdown(f"<span class='pill'>Capital: ₹{asset['capital_cr']:.1f} Cr</span>", unsafe_allow_html=True)

            m1, m2, m3 = st.columns(3)
            m1.metric("Base Coupon Rate", f"{asset['base_coupon_pct']:.2f}%")
            m2.metric("DSRA Monthly Coverage", f"{asset['dsra_months']} months")
            m3.metric("PIK Capitalized to Date", f"₹{asset['pik_capitalized_cr']:.3f} Cr")

            st.markdown("**Linked NCDEX RAINMUMBAI Hedge Tranches**")
            hedge_rows = []
            for h in asset["hedges"]:
                hedge_rows.append({
                    "Contract Month": h["month"],
                    "Position": h["position"],
                    "Lots": h["lots"],
                    "Entry Price (mm-pts)": h["entry_price"],
                    "CDR Holiday Threshold (mm)": h["threshold_mm"],
                    "Holiday Status": "🟠 ACTIVE" if h["holiday_active"] else "🟢 Standard",
                })
            st.dataframe(pd.DataFrame(hedge_rows), hide_index=True, use_container_width=True)

    st.markdown("---")
    st.markdown("#### ➕ Provision & Link New Debt Asset")

    with st.form("new_asset_form", clear_on_submit=True):
        fc1, fc2 = st.columns(2)
        with fc1:
            new_name = st.text_input("Asset / Deal Name")
            new_capital = st.number_input("Facility Capital Deployed (Crores)", min_value=0.0, value=100.0, step=5.0)
            new_coupon = st.number_input("Base Coupon Rate (%)", min_value=0.0, value=12.5, step=0.05)
        with fc2:
            new_dsra = st.number_input("Mandatory DSRA Monthly Coverage Reserve (months)", min_value=0, value=3, step=1)
            new_lat = st.number_input("Asset Latitude", value=19.10, format="%.4f")
            new_lon = st.number_input("Asset Longitude", value=72.88, format="%.4f")

        st.markdown("**Linked NCDEX RAINMUMBAI Futures Tranches**")
        h1, h2, h3, h4 = st.columns(4)
        with h1:
            hedge_month = st.selectbox("Contract Month", CONTRACT_MONTHS)
        with h2:
            hedge_position = st.selectbox("Position", ["Long", "Short"])
        with h3:
            hedge_lots = st.number_input("Number of Lots", min_value=1, value=20, step=1)
        with h4:
            hedge_threshold = st.number_input("Target CDR Threshold for Holiday (mm)", min_value=0.0, value=850.0, step=10.0)

        submitted = st.form_submit_button("Provision & Link Asset", use_container_width=True)

        if submitted:
            if not new_name.strip():
                st.error("Asset / Deal Name is required.")
            else:
                new_deal_id = f"PC-MUM-{400 + len(st.session_state.assets) + 1}"
                entry_px = st.session_state.futures_ltp.get(hedge_month, 600.0)
                new_asset = {
                    "deal_id": new_deal_id,
                    "name": new_name.strip(),
                    "capital_cr": float(new_capital),
                    "base_coupon_pct": float(new_coupon),
                    "dsra_months": int(new_dsra),
                    "lat": float(new_lat),
                    "lon": float(new_lon),
                    "structure": "Structure 1 — Monsoon-Toggle Debt (Cash/PIK Coupon, DSRA Holiday)",
                    "pik_capitalized_cr": 0.0,
                    "hedges": [{
                        "month": hedge_month,
                        "position": hedge_position,
                        "lots": int(hedge_lots),
                        "entry_price": entry_px,
                        "threshold_mm": float(hedge_threshold),
                        "holiday_active": False,
                    }],
                }
                st.session_state.assets.append(new_asset)
                log_line(f"New Structure 1 asset provisioned: {new_deal_id} — {new_name.strip()}")
                st.success(f"Asset {new_deal_id} provisioned and linked to {hedge_month} RAINMUMBAI futures.")
                st.rerun()

# -------------------------------------------------------------------------------------
# TAB 3 — QUANTITATIVE DISTRIBUTION ENGINE & MARGIN LEDGER
# -------------------------------------------------------------------------------------
with tab3:
    st.markdown("<div class='section-title'>Quantitative Distribution Engine &amp; Derivative Margin Ledger</div>", unsafe_allow_html=True)

    total_shadow_nav_rs = 0.0

    for asset in st.session_state.assets:
        nav = shadow_nav(asset, st.session_state.cdr_spot, st.session_state.futures_ltp)
        dist = nav["distribution"]
        total_shadow_nav_rs += nav["shadow_nav_rs"]

        # Apply PIK capitalization to ledger if holiday active (persist into principal)
        if dist["holiday_active"]:
            asset["pik_capitalized_cr"] += dist["pik_portion_rs"] / CR_TO_RS / 4.0  # incremental quarter accrual

        with st.container(border=True):
            st.markdown(f"### {asset['name']}  ·  `{asset['deal_id']}`")

            status_pill = "<span class='pill pill-pik'>COVENANT HOLIDAY ACTIVE — PIK TOGGLE ON</span>" if dist["holiday_active"] \
                else "<span class='pill pill-cash'>STANDARD CASH COUPON</span>"
            st.markdown(status_pill, unsafe_allow_html=True)

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Quarterly Coupon (Total)", fmt_rs_cr(dist["quarterly_coupon_rs"]))
            c2.metric("Cash Distribution", fmt_rs_cr(dist["cash_portion_rs"]))
            c3.metric("PIK Capitalized (this qtr)", fmt_rs_cr(dist["pik_portion_rs"]))
            c4.metric("Shadow NAV", fmt_rs_cr(nav["shadow_nav_rs"]))

            st.markdown("#### Hedge Book — Realized/Unrealized MTM & Margin")
            margin_rows = []
            for h in asset["hedges"]:
                px = st.session_state.futures_ltp.get(h["month"], h["entry_price"])
                mtm = hedge_mtm(h, px)
                im = initial_margin(h, px)
                vm = variation_margin(h, px)
                var99 = var_3day_99_clean(h, px)
                margin_rows.append({
                    "Month": h["month"],
                    "Position": h["position"],
                    "Lots": h["lots"],
                    "Entry": h["entry_price"],
                    "Current": round(px, 1),
                    "MTM P&L (₹)": round(mtm, 0),
                    "Initial Margin (₹)": round(im, 0),
                    "Variation Margin Due (₹)": round(vm, 0),
                    "99% 3-Day VaR (₹)": round(var99, 0),
                })
            margin_df = pd.DataFrame(margin_rows)
            st.dataframe(margin_df, hide_index=True, use_container_width=True)

            total_im = margin_df["Initial Margin (₹)"].sum()
            total_vm = margin_df["Variation Margin Due (₹)"].sum()
            total_var = margin_df["99% 3-Day VaR (₹)"].sum()
            mcol1, mcol2, mcol3 = st.columns(3)
            mcol1.metric("Total Initial Margin Required", fmt_rs(total_im))
            mcol2.metric("Total Variation Margin Due", fmt_rs(total_vm))
            mcol3.metric("Total 99% 3-Day VaR Exposure", fmt_rs(total_var))

    st.markdown("---")
    st.metric("📐 Portfolio-Wide Shadow NAV (Illiquid Note + Liquid Hedge MTM)", fmt_rs_cr(total_shadow_nav_rs))

# -------------------------------------------------------------------------------------
# TAB 4 — HIGH-SEVERITY RISK & EXTREME LOSS ALERT TERMINAL
# -------------------------------------------------------------------------------------
with tab4:
    st.markdown("<div class='section-title'>High-Severity Risk &amp; Extreme Loss Alert Terminal</div>", unsafe_allow_html=True)
    st.write(
        f"This monitor continuously evaluates whether the live CDR deviation from LPA baseline "
        f"has breached the severe safety boundary of **+{SEVERE_BOUNDARY_MM:.0f} mm**. A breach "
        f"signals an extreme cloudburst scenario capable of triggering cascading margin calls "
        f"and/or operational asset impairment."
    )

    current_deviation = st.session_state.cdr_spot - LPA_BASELINE_MM
    breach = current_deviation > SEVERE_BOUNDARY_MM

    gcol1, gcol2 = st.columns(2)
    gcol1.metric("Current CDR Deviation vs LPA", f"{current_deviation:+.1f} mm")
    gcol2.metric("Severe Safety Boundary", f"+{SEVERE_BOUNDARY_MM:.0f} mm")

    if breach:
        for asset in st.session_state.assets:
            st.markdown(
                f"<div class='alert-flash'>⚠️ CRITICAL OUTFLOW ALERT: VARIATION MARGIN EXHAUSTION ON "
                f"NOTE {asset['deal_id']} — {asset['name'].upper()}. "
                f"IMMEDIATE LIQUIDITY REPLENISHMENT REQUIRED.</div>",
                unsafe_allow_html=True,
            )
        log_line(f"SEVERE BOUNDARY BREACH DETECTED — CDR deviation {current_deviation:+.1f} mm exceeds +{SEVERE_BOUNDARY_MM:.0f} mm threshold.")
    else:
        st.markdown(
            "<div class='safe-banner'>✅ No severe boundary breach detected. CDR deviation is within "
            "tolerable risk parameters relative to the safety threshold.</div>",
            unsafe_allow_html=True,
        )

    st.markdown("#### Boundary Stress Simulator")
    sim_shift = st.slider(
        "Manually stress-test an additional CDR deviation shock (mm)",
        min_value=-200, max_value=600, value=0, step=10,
    )
    stressed_deviation = current_deviation + sim_shift
    stressed_cdr = LPA_BASELINE_MM + stressed_deviation
    stressed_breach = stressed_deviation > SEVERE_BOUNDARY_MM

    st.metric("Stressed CDR Deviation", f"{stressed_deviation:+.1f} mm",
               delta=f"{sim_shift:+d} mm shock applied")

    if stressed_breach:
        st.markdown(
            f"<div class='alert-flash'>🚨 STRESS SCENARIO BREACH: Under a {sim_shift:+d} mm shock, "
            f"deviation would reach {stressed_deviation:+.1f} mm — EXCEEDS the +{SEVERE_BOUNDARY_MM:.0f} mm "
            f"safety boundary. Cascading margin calls projected across all linked hedge books.</div>",
            unsafe_allow_html=True,
        )

        impact_rows = []
        for asset in st.session_state.assets:
            for h in asset["hedges"]:
                stressed_mtm = hedge_mtm(h, stressed_cdr)
                impact_rows.append({
                    "Deal ID": asset["deal_id"],
                    "Contract Month": h["month"],
                    "Stressed MTM (₹)": round(stressed_mtm, 0),
                    "Stressed Variation Margin Call (₹)": round(max(-stressed_mtm, 0), 0),
                })
        st.dataframe(pd.DataFrame(impact_rows), hide_index=True, use_container_width=True)
    else:
        st.info("Stress scenario remains within the severe safety boundary.")

# -------------------------------------------------------------------------------------
# TAB 5 — 30-YEAR TREND ANALYSIS & CLIMATE CONFIDENCE MATRIX
# -------------------------------------------------------------------------------------
with tab5:
    st.markdown("<div class='section-title'>30-Year Trend Analysis &amp; Climate Confidence Matrix</div>", unsafe_allow_html=True)
    st.write(
        "A programmatically generated 30-year daily historical monsoon rainfall dataset for "
        "Mumbai (representing official IMD baseline behavior) underpins this statistical trend "
        "panel. Select an operational day-of-monsoon range to assess the probability of breaching "
        "or falling short of a target CDR level."
    )

    hist_df = st.session_state.history_df

    day_range = st.slider(
        "Operational Day-of-Monsoon Range (Day 1 = ~June 1st)",
        min_value=1, max_value=int(hist_df["day_of_monsoon"].max()),
        value=(1, 90),
    )
    target_cdr = st.number_input("Target CDR Threshold (mm) to evaluate breach probability", min_value=0.0, value=850.0, step=10.0)

    window_df = hist_df[(hist_df["day_of_monsoon"] >= day_range[0]) & (hist_df["day_of_monsoon"] <= day_range[1])]

    stats = (
        window_df.groupby("day_of_monsoon")["cumulative_cdr_mm"]
        .agg(["mean", "std"])
        .reset_index()
        .sort_values("day_of_monsoon")
    )
    stats["std"] = stats["std"].fillna(stats["std"].mean())

    days = stats["day_of_monsoon"]
    mean = stats["mean"]
    std = stats["std"]

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=pd.concat([days, days[::-1]]),
        y=pd.concat([mean + 3 * std, (mean - 3 * std)[::-1]]),
        fill="toself", fillcolor="rgba(14,58,95,0.08)", line=dict(width=0),
        name="99% Confidence Band", showlegend=True,
    ))
    fig.add_trace(go.Scatter(
        x=pd.concat([days, days[::-1]]),
        y=pd.concat([mean + 2 * std, (mean - 2 * std)[::-1]]),
        fill="toself", fillcolor="rgba(14,58,95,0.16)", line=dict(width=0),
        name="95% Confidence Band", showlegend=True,
    ))
    fig.add_trace(go.Scatter(
        x=pd.concat([days, days[::-1]]),
        y=pd.concat([mean + std, (mean - std)[::-1]]),
        fill="toself", fillcolor="rgba(14,58,95,0.28)", line=dict(width=0),
        name="68% Confidence Band", showlegend=True,
    ))
    fig.add_trace(go.Scatter(
        x=days, y=mean, mode="lines",
        line=dict(color="#0b1f3a", width=2.5),
        name="30-Yr Mean Cumulative CDR",
    ))
    fig.add_hline(y=target_cdr, line_dash="dash", line_color="#c0392b",
                   annotation_text=f"Target CDR: {target_cdr:.0f} mm")

    fig.update_layout(
        height=460,
        xaxis_title="Day of Monsoon Season",
        yaxis_title="Cumulative CDR (mm)",
        plot_bgcolor="white",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(t=60, l=10, r=10, b=10),
    )
    st.plotly_chart(fig, use_container_width=True)

    last_day = day_range[1]
    row_at_day = stats[stats["day_of_monsoon"] == last_day]
    if not row_at_day.empty:
        mu = row_at_day["mean"].values[0]
        sigma = row_at_day["std"].values[0]
        z = (target_cdr - mu) / sigma if sigma > 0 else 0.0
        prob_breach = 1 - 0.5 * (1 + math.erf(z / math.sqrt(2)))
        prob_shortfall = 1 - prob_breach

        st.markdown("#### Probability Read-Out at End of Selected Window")
        pcol1, pcol2, pcol3 = st.columns(3)
        pcol1.metric(f"30-Yr Mean Cumulative CDR (Day {last_day})", f"{mu:.1f} mm")
        pcol2.metric("Probability of Breaching Target", f"{prob_breach*100:.1f}%")
        pcol3.metric("Probability of Falling Short", f"{prob_shortfall*100:.1f}%")

    with st.expander("View Underlying 30-Year Historical Dataset (sample)"):
        st.dataframe(hist_df.head(500), use_container_width=True, hide_index=True)

# -------------------------------------------------------------------------------------
# TAB 6 — SPATIAL BASIS RISK MAPPING (GIS SCOPE)
# -------------------------------------------------------------------------------------
with tab6:
    st.markdown("<div class='section-title'>Spatial Basis Risk Mapping — GIS Scope</div>", unsafe_allow_html=True)
    st.write(
        "This panel plots the precise geographical locations of the physical private credit "
        "real estate / infrastructure assets against the official IMD Santacruz and Colaba "
        "weather stations, computing geodesic distances to flag potential **Basis Risk** — "
        "hyperlocal rainfall discrepancies that may affect asset performance without moving "
        "the official exchange index."
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
        map=dict(
            style="open-street-map",
            zoom=9.4,
            center=dict(lat=19.05, lon=72.93),
        ),
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

    risk_df = pd.DataFrame(risk_rows)
    st.dataframe(risk_df, hide_index=True, use_container_width=True)

    st.caption(
        f"Basis Risk flag threshold set at {BASIS_RISK_KM_THRESHOLD:.0f} km. Assets beyond this "
        "distance from both reference stations face elevated structural exposure to hyperlocal "
        "rainfall variance that the official exchange index will not capture."
    )

# =====================================================================================
# FOOTER
# =====================================================================================

st.markdown("---")
st.caption(
    "Mantra Weather Risk Ledger — institutional prototype. All market data, pricing, "
    "and historical climate series are simulated for demonstration purposes and do not "
    "reflect live NCDEX or IMD feeds."
)
