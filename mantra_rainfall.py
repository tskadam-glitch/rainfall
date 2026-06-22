"""
Mantra Weather Risk Ledger: Buy-Side Private Credit & Derivatives Portfolio Manager
=====================================================================================
Institutional-grade buy-side prototype tracking Private Credit debt facilities 
hedged with the NCDEX RAINMUMBAI weather futures contract.
"""

import math
import random
from datetime import datetime, timedelta, date

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import scipy.stats as stats
from sklearn.linear_model import Ridge
from sklearn.preprocessing import PolynomialFeatures
from sklearn.pipeline import make_pipeline

# =====================================================================================
# GLOBAL CONSTANTS & NCDEX SPECS
# =====================================================================================

LPA_BASELINE_MM = 2206.7          # Starting Anchor for Mumbai monsoon CDR
TICK_VALUE_RS = 50                # ₹ per mm move (NCDEX RAINMUMBAI multiplier)
CONTRACT_MONTHS = ["JUN", "JUL", "AUG", "SEP"]
SEVERE_MARGIN_DRAWDOWN_PCT = 0.75 # Alert if variation margin eats 75% of initial margin
MARGIN_INITIAL_PCT = 0.12         # 12% initial margin on notional
CR_TO_RS = 1e7                    # 1 Crore = 1,00,00,000 INR

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

    html, body, [class*="css"]  { font-family: 'IBM Plex Sans', sans-serif; }

    .mantra-header {
        background: linear-gradient(135deg, #0b1f3a 0%, #102a52 45%, #0e3a5f 100%);
        padding: 22px 30px;
        border-radius: 10px;
        border: 1px solid #1d4a78;
        margin-bottom: 18px;
    }
    .mantra-header h1 { color: #eaf2ff; font-size: 26px; font-weight: 700; margin: 0; }
    .mantra-header p { color: #9fc1e8; font-size: 13.5px; margin: 6px 0 0 0; font-family: 'IBM Plex Mono', monospace; }

    .term-box {
        background-color: #050b14; color: #5ef58a; font-family: 'IBM Plex Mono', monospace;
        font-size: 12.3px; padding: 14px 16px; border-radius: 8px; border: 1px solid #163a2c;
        height: 250px; overflow-y: auto; line-height: 1.55;
    }
    .metric-card { background-color: #0f1b2d; border: 1px solid #1f3553; border-radius: 10px; padding: 14px 16px; }

    .alert-flash {
        animation: flashred 1s infinite; background-color: #7a0000; border: 2px solid #ff2b2b;
        color: #ffe9e9; font-family: 'IBM Plex Mono', monospace; font-weight: 700; font-size: 14.5px;
        padding: 16px 20px; border-radius: 8px; margin-bottom: 14px;
    }
    @keyframes flashred {
        0%   { background-color: #7a0000; box-shadow: 0 0 6px #ff0000; }
        50%  { background-color: #b30000; box-shadow: 0 0 22px #ff2b2b; }
        100% { background-color: #7a0000; box-shadow: 0 0 6px #ff0000; }
    }
    .safe-banner {
        background-color: #0d2417; border: 1px solid #1f6b3f; color: #9fe8bb;
        font-family: 'IBM Plex Mono', monospace; font-size: 13.5px; padding: 12px 18px;
        border-radius: 8px; margin-bottom: 14px;
    }
    .section-title { font-size: 18px; font-weight: 700; color: #0b1f3a; border-left: 5px solid #0e3a5f; padding-left: 10px; margin: 18px 0 10px 0; }
    .pill { display: inline-block; background-color: #e6edf7; color: #0b1f3a; border-radius: 14px; padding: 3px 12px; font-size: 11.5px; font-weight: 600; margin-right: 6px; }
    .pill-pik { background-color: #fbe6d4; color: #7a3b00; }
    .pill-cash { background-color: #d7f0e1; color: #0a5c33; }
    div[data-testid="stMetricValue"] { font-family: 'IBM Plex Mono', monospace; }
    </style>
    """,
    unsafe_allow_html=True,
)

# =====================================================================================
# SESSION STATE INITIALIZATION
# =====================================================================================

def init_state():
    if "initialized" in st.session_state: return
    st.session_state.initialized = True

    # Current Day: June 22 (Monsoon Day 22)
    st.session_state.current_monsoon_day = 22
    
    # NCDEX CDR Spot Tracking (Realistic anchored to 2206.7)
    # Assume a slight rainfall deficit so far, index dropped to 2185.4
    st.session_state.prev_cdr_spot = 2190.2
    st.session_state.cdr_spot = 2185.4 
    
    st.session_state.futures_ltp = {
        "JUN": 2180.0,
        "JUL": 2240.0,
        "AUG": 2265.0,
        "SEP": 2280.0,
    }
    st.session_state.oi_by_month = {m: random.randint(2500, 15000) for m in CONTRACT_MONTHS}
    st.session_state.last_scrape_time = datetime.now()
    st.session_state.terminal_log = []
    
    log_line(f"AI Scraper Bootstrapped. NCDEX RAINMUMBAI API connected.")
    log_line(f"Baseline LPA anchor confirmed at {LPA_BASELINE_MM} mm.")

    # Base Portfolio Master
    st.session_state.assets = [
        {
            "deal_id": "PC-MUM-401",
            "name": "Mumbai Commercial RE Development Note",
            "capital_cr": 185.0,
            "base_coupon_pct": 13.25,
            "structure": "Structure 1 — Monsoon-Toggle Debt",
            "pik_capitalized_cr": 0.0,
            "hedge_target_offset_pct": 0.50, # Hedging 50% of the cash interest
            "hedge_shock_mm": 50.0,          # Payout triggers on a 50mm adverse move
            "hedges": [
                {"month": "JUL", "position": "Long", "entry_price": 2210.0, "threshold_mm": 2260.0, "holiday_active": False},
            ],
        },
        {
            "deal_id": "PC-MUM-402",
            "name": "Bhiwandi Port Logistics Note",
            "capital_cr": 240.0,
            "base_coupon_pct": 12.60,
            "structure": "Structure 1 — Monsoon-Toggle Debt",
            "pik_capitalized_cr": 0.0,
            "hedge_target_offset_pct": 1.00, # Hedging 100% of the cash interest
            "hedge_shock_mm": 80.0,          # Payout triggers on an 80mm adverse move
            "hedges": [
                {"month": "SEP", "position": "Long", "entry_price": 2230.0, "threshold_mm": 2310.0, "holiday_active": False},
            ],
        },
    ]

def log_line(message: str):
    ts = datetime.now().strftime("%H:%M:%S")
    st.session_state.terminal_log.insert(0, f"[{ts}] {message}")
    st.session_state.terminal_log = st.session_state.terminal_log[:60]

# =====================================================================================
# FINANCIAL QUANT ENGINE
# =====================================================================================

def calculate_institutional_lots(asset: dict) -> int:
    """Calculates required lot size to offset target interest cash flow based on an extreme weather shock."""
    principal_rs = (asset["capital_cr"] + asset["pik_capitalized_cr"]) * CR_TO_RS
    qtr_coupon_rs = principal_rs * (asset["base_coupon_pct"] / 100.0) / 4.0
    target_payout_rs = qtr_coupon_rs * asset["hedge_target_offset_pct"]
    payout_per_lot = asset["hedge_shock_mm"] * TICK_VALUE_RS
    return int(target_payout_rs / payout_per_lot)

def hedge_mtm(hedge: dict, lots: int, current_price: float) -> float:
    direction = 1 if hedge["position"] == "Long" else -1
    return direction * (current_price - hedge["entry_price"]) * lots * TICK_VALUE_RS

def initial_margin(current_price: float, lots: int) -> float:
    return current_price * lots * TICK_VALUE_RS * MARGIN_INITIAL_PCT

def process_ledger(asset: dict, current_cdr: float, futures_ltp: dict):
    lots = calculate_institutional_lots(asset)
    
    principal_rs = (asset["capital_cr"] + asset["pik_capitalized_cr"]) * CR_TO_RS
    qtr_coupon_rs = principal_rs * (asset["base_coupon_pct"] / 100.0) / 4.0

    # Evaluate Holiday Breaches
    holiday_active = any(current_cdr >= h["threshold_mm"] for h in asset["hedges"])
    pik_portion_rs = qtr_coupon_rs * 0.55 if holiday_active else 0.0
    cash_portion_rs = qtr_coupon_rs - pik_portion_rs

    # Evaluate Hedges
    total_mtm_rs = 0.0
    total_im_rs = 0.0
    margin_book = []
    
    for h in asset["hedges"]:
        h["holiday_active"] = current_cdr >= h["threshold_mm"]
        px = futures_ltp.get(h["month"], h["entry_price"])
        mtm = hedge_mtm(h, lots, px)
        im = initial_margin(px, lots)
        vm = min(mtm, 0.0) * -1
        
        total_mtm_rs += mtm
        total_im_rs += im
        
        margin_book.append({
            "Tranche": h["month"],
            "Lots": lots,
            "Entry Px (mm)": h["entry_price"],
            "Live Px (mm)": round(px, 1),
            "Init Margin (₹)": round(im, 0),
            "Var Margin Call (₹)": round(vm, 0),
            "MTM P&L (₹)": round(mtm, 0)
        })

    realizable_offset = max(0, min(cash_portion_rs, total_mtm_rs))
    unrealised_nav = total_im_rs + total_mtm_rs
    shadow_nav = principal_rs + unrealised_nav

    return {
        "holiday_active": holiday_active,
        "qtr_coupon_rs": qtr_coupon_rs,
        "cash_portion_rs": cash_portion_rs,
        "pik_portion_rs": pik_portion_rs,
        "realizable_offset": realizable_offset,
        "shadow_nav": shadow_nav,
        "margin_book": margin_book
    }

def fmt_cr(val: float) -> str: return f"₹{val / CR_TO_RS:,.2f} Cr"
def fmt_rs(val: float) -> str: return f"₹{val:,.0f}"

# =====================================================================================
# MACHINE LEARNING ENGINE (SIMULATED FOR PROTOTYPE)
# =====================================================================================

def generate_ml_forecast(current_day: int, current_spot: float, days_to_predict: int = 100):
    """
    Simulates a Machine Learning prediction pipeline (e.g. Ridge Regression on polynomial features
    mixed with Monte Carlo paths) to forecast the CDR Index for the rest of the monsoon.
    """
    days = np.arange(current_day, current_day + days_to_predict).reshape(-1, 1)
    
    # Train a dummy ML pipeline to create a smooth, curved trajectory
    model = make_pipeline(PolynomialFeatures(degree=3), Ridge(alpha=1.0))
    X_train = np.array([1, 40, 80, 122]).reshape(-1, 1)
    y_train = np.array([2206.7, 2350, 2600, 2800]) # Example typical seasonal curve values
    model.fit(X_train, y_train)
    
    base_pred = model.predict(days)
    
    # Adjust prediction to anchor smoothly from today's spot price
    offset = current_spot - base_pred[0]
    mean_forecast = base_pred + offset
    
    # Generate Monte Carlo bounds (Confidence Intervals) via expanding variance
    volatility = 4.5 # mm per day
    std_devs = np.sqrt(np.arange(1, days_to_predict + 1)) * volatility
    
    ci_95_upper = mean_forecast + (1.96 * std_devs)
    ci_95_lower = mean_forecast - (1.96 * std_devs)
    
    return days.flatten(), mean_forecast, ci_95_upper, ci_95_lower

# =====================================================================================
# UI LAYOUT
# =====================================================================================

init_state()

st.markdown(
    """
    <div class="mantra-header">
        <h1>🌧️ Mantra Weather Risk Ledger</h1>
        <p>Buy-Side Portfolio Manager &nbsp;|&nbsp; RAINMUMBAI Futures &nbsp;|&nbsp; Tick: 1mm = ₹50 &nbsp;|&nbsp; Index: Cumulative Deviation Rainfall (CDR)</p>
    </div>
    """, unsafe_allow_html=True
)

# -------------------------------------------------------------------------------------
# SIDEBAR: NCDEX INGESTION
# -------------------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### 🛰️ NCDEX Data Engine")
    st.caption("AI DOM Scraper · Cadence: 15 min")

    st.markdown(
        f"<div class='metric-card'><b>Last Scrape:</b> {st.session_state.last_scrape_time.strftime('%H:%M:%S')}<br>"
        f"<b>Day of Monsoon:</b> {st.session_state.current_monsoon_day}<br>"
        f"<b>Prev Day Spot:</b> {st.session_state.prev_cdr_spot:.1f} mm<br>"
        f"<b>Live CDR Spot:</b> {st.session_state.cdr_spot:.1f} mm</div>",
        unsafe_allow_html=True,
    )

    st.write("")
    if st.button("🔄 Force Data Refresh", use_container_width=True):
        log_line("Polling NCDEX API for RAINMUMBAI order book updates...")
        st.session_state.cdr_spot += random.gauss(0, 10)
        for m in CONTRACT_MONTHS:
            st.session_state.futures_ltp[m] += random.gauss(0, 8)
        log_line(f"CDR Spot updated: {st.session_state.cdr_spot:.1f} mm")
        st.session_state.last_scrape_time = datetime.now()
        st.rerun()

    board_df = pd.DataFrame({
        "Contract": CONTRACT_MONTHS,
        "LTP (mm)": [round(st.session_state.futures_ltp[m], 1) for m in CONTRACT_MONTHS],
        "OI": [st.session_state.oi_by_month[m] for m in CONTRACT_MONTHS],
    })
    st.dataframe(board_df, hide_index=True, use_container_width=True)
    
    st.markdown("#### Terminal Log")
    log_html = "<br>".join(st.session_state.terminal_log)
    st.markdown(f"<div class='term-box'>{log_html}</div>", unsafe_allow_html=True)

# -------------------------------------------------------------------------------------
# MAIN TABS
# -------------------------------------------------------------------------------------
tab1, tab2 = st.tabs(["🏛️ Portfolio Master & Margin Ledger", "🧠 ML Predictive Forecasting"])

# --- TAB 1: COMBINED LEDGER ---
with tab1:
    st.markdown("<div class='section-title'>Unified Portfolio Master & Derivative Ledger</div>", unsafe_allow_html=True)
    st.write("Aggregated view of debt facility distribution rules, dynamic institutional lot sizing, live NCDEX margin monitors, and automated severe risk alerts.")

    for asset in st.session_state.assets:
        ledger = process_ledger(asset, st.session_state.cdr_spot, st.session_state.futures_ltp)
        
        with st.container(border=True):
            st.markdown(f"### {asset['name']} · `{asset['deal_id']}`")
            
            # --- Status & Severe Risk Alerts ---
            breach_found = False
            for mb in ledger["margin_book"]:
                if mb["Var Margin Call (₹)"] > (mb["Init Margin (₹)"] * SEVERE_MARGIN_DRAWDOWN_PCT):
                    breach_found = True
                    st.markdown(
                        f"<div class='alert-flash'>⚠️ CRITICAL RISK ALERT: {mb['Tranche']} Tranche.<br>"
                        f"Variation margin call (₹{mb['Var Margin Call (₹)']:,.0f}) exceeds {SEVERE_MARGIN_DRAWDOWN_PCT*100}% of Initial Margin. "
                        f"Unrealised NAV is severely impaired.</div>", unsafe_allow_html=True
                    )
            
            status_pill = "<span class='pill pill-pik'>🟠 COVENANT HOLIDAY ACTIVE</span>" if ledger["holiday_active"] else "<span class='pill pill-cash'>🟢 NORMAL DISTRIBUTIONS</span>"
            if not breach_found:
                st.markdown(f"{status_pill} <span style='margin-left: 10px; color: #1f6b3f; font-size: 13px; font-weight: bold;'>✓ Margin Capitalization Healthy</span>", unsafe_allow_html=True)
            else:
                st.markdown(status_pill, unsafe_allow_html=True)

            # --- Financial Metrics ---
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Principal Outstanding", fmt_cr(asset["capital_cr"] * CR_TO_RS))
            c2.metric("Quarterly Interest Due", fmt_cr(ledger["qtr_coupon_rs"]))
            c3.metric("Cash Int. at Risk (Post-PIK)", fmt_cr(ledger["cash_portion_rs"]))
            c4.metric("Shadow NAV (Inc. Futures)", fmt_cr(ledger["shadow_nav"]))

            # --- Hedge & Margin Book ---
            st.markdown(f"**Institutional Hedge Sizing:** System calculated **{ledger['margin_book'][0]['Lots']:,} lots** required to offset {asset['hedge_target_offset_pct']*100}% of interest upon a {asset['hedge_shock_mm']} mm adverse monsoon shock.")
            
            m_df = pd.DataFrame(ledger["margin_book"])
            st.dataframe(m_df, hide_index=True, use_container_width=True)

            # Highlight if the hedge is actively paying out
            if ledger["realizable_offset"] > 0:
                st.success(f"☔ Weather Hedge Actively Offsetting Cash Interest Risk: {fmt_cr(ledger['realizable_offset'])} in deployable exchange liquidity.")

# --- TAB 2: ML FORECASTING ---
with tab2:
    st.markdown("<div class='section-title'>Ensemble Machine Learning Forecast (CDR Index)</div>", unsafe_allow_html=True)
    st.write("Leveraging an algorithmic regression model trained on IMD historical distributions to project the RAINMUMBAI forward curve and estimate target breach probabilities.")

    days_left = 122 - st.session_state.current_monsoon_day
    days_arr, mean_f, upper_f, lower_f = generate_ml_forecast(st.session_state.current_monsoon_day, st.session_state.cdr_spot, days_left)

    colA, colB = st.columns([1, 3])
    
    with colA:
        st.markdown("#### Scenario Parameters")
        target_cdr = st.number_input("Test CDR Target (mm)", value=2310.0, step=10.0)
        
        # Calculate ML Probabilities
        final_mean = mean_f[-1]
        final_std = (upper_f[-1] - mean_f[-1]) / 1.96
        z_score = (target_cdr - final_mean) / final_std
        prob_breach = 1 - stats.norm.cdf(z_score)
        
        st.write("---")
        st.metric("ML Projected Final CDR", f"{final_mean:.1f} mm")
        st.metric(f"Probability to Breach {target_cdr}mm", f"{prob_breach*100:.1f}%")
        st.metric(f"Probability to Fall Short", f"{(1-prob_breach)*100:.1f}%")

    with colB:
        fig = go.Figure()
        
        # Confidence Band
        fig.add_trace(go.Scatter(x=np.concatenate([days_arr, days_arr[::-1]]), 
                                 y=np.concatenate([upper_f, lower_f[::-1]]),
                                 fill='toself', fillcolor='rgba(14,58,95,0.15)', line=dict(color='rgba(255,255,255,0)'),
                                 name='95% ML Confidence Interval'))
        
        # Mean Forecast Line
        fig.add_trace(go.Scatter(x=days_arr, y=mean_f, mode='lines', line=dict(color='#0e3a5f', width=3), name='ML Mean Trajectory'))
        
        # Current Spot Marker
        fig.add_trace(go.Scatter(x=[st.session_state.current_monsoon_day], y=[st.session_state.cdr_spot], mode='markers', 
                                 marker=dict(color='red', size=10), name='Live Spot (Today)'))
        
        # Target Threshold Line
        fig.add_hline(y=target_cdr, line_dash="dash", line_color="#c0392b", annotation_text=f"Breach Target: {target_cdr} mm")
        
        fig.update_layout(
            title="Algorithm Projected CDR Evolution (Remainder of Monsoon)",
            xaxis_title="Day of Monsoon Season (1-122)",
            yaxis_title="CDR Index Level (mm)",
            hovermode="x unified",
            plot_bgcolor="white",
            height=500
        )
        st.plotly_chart(fig, use_container_width=True)
