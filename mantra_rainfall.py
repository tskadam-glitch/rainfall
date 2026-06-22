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
SEVERE_MARGIN_DRAWDOWN_PCT = 0.75 
MARGIN_INITIAL_PCT = 0.12         
CR_TO_RS = 1e7                    

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
        padding: 22px 30px; border-radius: 10px; border: 1px solid #1d4a78; margin-bottom: 18px;
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
    @keyframes flashred { 0% { background-color: #7a0000; box-shadow: 0 0 6px #ff0000; } 50% { background-color: #b30000; box-shadow: 0 0 22px #ff2b2b; } 100% { background-color: #7a0000; box-shadow: 0 0 6px #ff0000; } }
    .section-title { font-size: 18px; font-weight: 700; color: #0b1f3a; border-left: 5px solid #0e3a5f; padding-left: 10px; margin: 18px 0 10px 0; }
    .pill { display: inline-block; background-color: #e6edf7; color: #0b1f3a; border-radius: 14px; padding: 3px 12px; font-size: 11.5px; font-weight: 600; margin-right: 6px; }
    .pill-pik { background-color: #fbe6d4; color: #7a3b00; }
    .pill-cash { background-color: #d7f0e1; color: #0a5c33; }
    div[data-testid="stMetricValue"] { font-family: 'IBM Plex Mono', monospace; }
    </style>
    """, unsafe_allow_html=True
)

# =====================================================================================
# SIMULATE REALISTIC HISTORICAL PATH (Jun 1 to Sept 1)
# =====================================================================================

def generate_realistic_season_path(current_day: int):
    # Base LPA daily average is approx 2206.7 / 122 = 18.08 mm/day
    path = [LPA_BASELINE_MM]
    
    for day in range(1, current_day + 1):
        if day <= 30:
            # June: Dry spell, actual rain < normal (negative deviation)
            dev = random.uniform(-10, 2)
        elif day <= 61:
            # July: Severe floods, actual rain >> normal (positive deviation)
            dev = random.uniform(5, 25)
            # Occasional extreme cloudburst
            if random.random() < 0.1: dev += 40
        else:
            # August: Normal/Sideways
            dev = random.uniform(-5, 6)
            
        path.append(path[-1] + dev)
    return np.array(path)

# =====================================================================================
# SESSION STATE INITIALIZATION
# =====================================================================================

def init_state():
    if "initialized" in st.session_state: return
    st.session_state.initialized = True

    # Current Day: September 1 (Monsoon Day 93)
    st.session_state.current_monsoon_day = 93
    
    # Generate past path up to today
    st.session_state.cdr_path = generate_realistic_season_path(st.session_state.current_monsoon_day)
    st.session_state.cdr_spot = st.session_state.cdr_path[-1]
    st.session_state.prev_cdr_spot = st.session_state.cdr_path[-2]
    
    # Futures Prices: Jun, Jul, Aug are Settled Prices. Sep is Live LTP.
    st.session_state.futures_ltp = {
        "JUN": 2130.5, # Expired (Dry month, settled low)
        "JUL": 2480.0, # Expired (Flooded month, settled high)
        "AUG": 2495.5, # Expired (Normal, settled sideways to July)
        "SEP": 2510.0, # Active Live Contract
    }
    
    st.session_state.oi_by_month = {"JUN": 0, "JUL": 0, "AUG": 0, "SEP": 14500}
    st.session_state.last_scrape_time = datetime.now()
    st.session_state.terminal_log = []
    
    log_line(f"System Time: September 1, 2026. Jun, Jul, Aug tranches settled.")
    log_line(f"Live Spot anchored at {LPA_BASELINE_MM} mm.")

    # Base Portfolio Master with MULTI-MONTH LADDERS
    st.session_state.assets = [
        {
            "deal_id": "PC-MUM-401",
            "name": "Mumbai Commercial RE Development Note",
            "capital_cr": 185.0,
            "base_coupon_pct": 13.25,
            "hedge_target_offset_pct": 0.50, # Hedging 50% of the Q3 cash interest
            "hedge_shock_mm": 50.0,          # Modeled payout on 50mm shock
            "ladder_months": ["JUN", "JUL", "AUG"], # Q3 Hedge Ladder
            "entry_price": 2210.0,           # Average entry index for the quarter
            "threshold_mm": 2350.0,          # Covenant Holiday Trigger
        },
        {
            "deal_id": "PC-MUM-402",
            "name": "Bhiwandi Port Logistics Note",
            "capital_cr": 240.0,
            "base_coupon_pct": 12.60,
            "hedge_target_offset_pct": 1.00, # Hedging 100% of the cash interest
            "hedge_shock_mm": 80.0,          
            "ladder_months": ["JUL", "AUG", "SEP"], # Late Season Logistics Exposure
            "entry_price": 2240.0,           
            "threshold_mm": 2400.0,          
        },
    ]

def log_line(message: str):
    ts = datetime.now().strftime("%H:%M:%S")
    st.session_state.terminal_log.insert(0, f"[{ts}] {message}")
    st.session_state.terminal_log = st.session_state.terminal_log[:60]

# =====================================================================================
# FINANCIAL QUANT ENGINE
# =====================================================================================

def process_ledger(asset: dict, current_cdr: float, futures_ltp: dict, current_day: int):
    # 1. Base Debt Math
    principal_rs = asset["capital_cr"] * CR_TO_RS
    qtr_coupon_rs = principal_rs * (asset["base_coupon_pct"] / 100.0) / 4.0
    
    # 2. Institutional Hedge Ladder Sizing
    # Target payout is divided evenly across the number of months in the ladder
    target_payout_rs = qtr_coupon_rs * asset["hedge_target_offset_pct"]
    payout_per_lot = asset["hedge_shock_mm"] * TICK_VALUE_RS
    total_lots_needed = target_payout_rs / payout_per_lot
    lots_per_month = int(total_lots_needed / len(asset["ladder_months"]))
    
    # 3. Covenant Holidays
    holiday_active = current_cdr >= asset["threshold_mm"]
    pik_portion_rs = qtr_coupon_rs * 0.55 if holiday_active else 0.0
    cash_portion_rs = qtr_coupon_rs - pik_portion_rs

    # 4. Hedge Book Tracking (Realized vs Unrealized)
    realized_mtm_rs = 0.0
    unrealized_mtm_rs = 0.0
    total_active_im_rs = 0.0
    margin_book = []
    
    # Define Expiry Matrix based on current_day = 93 (Sept 1)
    status_map = {"JUN": "Settled", "JUL": "Settled", "AUG": "Settled", "SEP": "Active"}
    
    for month in asset["ladder_months"]:
        status = status_map[month]
        px = futures_ltp[month]
        mtm = (px - asset["entry_price"]) * lots_per_month * TICK_VALUE_RS
        
        if status == "Settled":
            realized_mtm_rs += mtm
            im = 0.0  # Margin released back to bank
            vm = 0.0
        else:
            unrealized_mtm_rs += mtm
            im = px * lots_per_month * TICK_VALUE_RS * MARGIN_INITIAL_PCT
            total_active_im_rs += im
            vm = min(mtm, 0.0) * -1
            
        margin_book.append({
            "Tranche": month,
            "Status": status,
            "Lots": lots_per_month,
            "Entry Px (mm)": asset["entry_price"],
            "Px (mm)": round(px, 1),
            "Active IM (₹)": round(im, 0),
            "Var Margin Call (₹)": round(vm, 0) if status == "Active" else 0,
            "Realized P&L (₹)": round(mtm, 0) if status == "Settled" else 0,
            "Unrealized P&L (₹)": round(mtm, 0) if status == "Active" else 0,
        })

    total_pnl = realized_mtm_rs + unrealized_mtm_rs
    realizable_offset = max(0, min(cash_portion_rs, total_pnl))
    shadow_nav = principal_rs + total_active_im_rs + unrealized_mtm_rs + realized_mtm_rs

    return {
        "holiday_active": holiday_active,
        "qtr_coupon_rs": qtr_coupon_rs,
        "cash_portion_rs": cash_portion_rs,
        "pik_portion_rs": pik_portion_rs,
        "realizable_offset": realizable_offset,
        "realized_mtm_rs": realized_mtm_rs,
        "unrealized_mtm_rs": unrealized_mtm_rs,
        "active_im": total_active_im_rs,
        "shadow_nav": shadow_nav,
        "margin_book": margin_book
    }

def fmt_cr(val: float) -> str: return f"₹{val / CR_TO_RS:,.2f} Cr"

# =====================================================================================
# MACHINE LEARNING ENGINE
# =====================================================================================

def generate_ml_forecast(past_path: np.ndarray, days_to_predict: int = 30):
    current_day = len(past_path) - 1
    future_days = np.arange(current_day, current_day + days_to_predict).reshape(-1, 1)
    
    # Simple polynomial fit on recent trend to project forward
    model = make_pipeline(PolynomialFeatures(degree=2), Ridge(alpha=1.0))
    X_train = np.arange(len(past_path)).reshape(-1, 1)
    model.fit(X_train, past_path)
    
    base_pred = model.predict(future_days)
    offset = past_path[-1] - base_pred[0]
    mean_forecast = base_pred + offset
    
    # Confidence Intervals expanding over time
    volatility = 5.0 # mm per day
    std_devs = np.sqrt(np.arange(1, days_to_predict + 1)) * volatility
    
    ci_95_upper = mean_forecast + (1.96 * std_devs)
    ci_95_lower = mean_forecast - (1.96 * std_devs)
    
    return future_days.flatten(), mean_forecast, ci_95_upper, ci_95_lower

# =====================================================================================
# UI LAYOUT
# =====================================================================================

init_state()

st.markdown(
    """
    <div class="mantra-header">
        <h1>🌧️ Mantra Weather Risk Ledger</h1>
        <p>Buy-Side Portfolio Manager &nbsp;|&nbsp; Multi-Month Hedge Ladder Structuring &nbsp;|&nbsp; 1mm = ₹50</p>
    </div>
    """, unsafe_allow_html=True
)

# -------------------------------------------------------------------------------------
# SIDEBAR
# -------------------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### 🛰️ NCDEX Data Engine")
    st.caption("Environment: September 1, 2026")

    st.markdown(
        f"<div class='metric-card'><b>Day of Monsoon:</b> {st.session_state.current_monsoon_day}<br>"
        f"<b>Prev Day Spot:</b> {st.session_state.prev_cdr_spot:.1f} mm<br>"
        f"<b>Live CDR Spot:</b> {st.session_state.cdr_spot:.1f} mm</div>",
        unsafe_allow_html=True,
    )

    st.markdown("#### Contract Status")
    board_df = pd.DataFrame({
        "Contract": CONTRACT_MONTHS,
        "Status": ["Settled", "Settled", "Settled", "Active (LTP)"],
        "Price (mm)": [round(st.session_state.futures_ltp[m], 1) for m in CONTRACT_MONTHS],
    })
    st.dataframe(board_df, hide_index=True, use_container_width=True)
    
    st.markdown("#### Terminal Log")
    log_html = "<br>".join(st.session_state.terminal_log)
    st.markdown(f"<div class='term-box'>{log_html}</div>", unsafe_allow_html=True)

# -------------------------------------------------------------------------------------
# MAIN TABS
# -------------------------------------------------------------------------------------
tab1, tab2 = st.tabs(["🏛️ Portfolio Master & Ladder Ledger", "🧠 ML Predictive Forecasting"])

# --- TAB 1: COMBINED LEDGER ---
with tab1:
    st.markdown("<div class='section-title'>Unified Portfolio Master & Derivative Ledger</div>", unsafe_allow_html=True)
    st.write("Displaying institutional cross-month hedge ladders. Notice how Initial Margin drops to zero for settled months, converting Unrealized P&L into Realized Cash, drastically improving capital efficiency.")

    for asset in st.session_state.assets:
        ledger = process_ledger(asset, st.session_state.cdr_spot, st.session_state.futures_ltp, st.session_state.current_monsoon_day)
        
        with st.container(border=True):
            st.markdown(f"### {asset['name']} · `{asset['deal_id']}`")
            
            status_pill = "<span class='pill pill-pik'>🟠 EXTREME WEATHER HOLIDAY ACTIVE</span>" if ledger["holiday_active"] else "<span class='pill pill-cash'>🟢 NORMAL DISTRIBUTIONS</span>"
            st.markdown(status_pill, unsafe_allow_html=True)

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Quarterly Interest Due", fmt_cr(ledger["qtr_coupon_rs"]))
            c2.metric("Cash Int. at Risk", fmt_cr(ledger["cash_portion_rs"]))
            c3.metric("Total Hedge P&L (All Months)", fmt_cr(ledger["realized_mtm_rs"] + ledger["unrealized_mtm_rs"]))
            c4.metric("Shadow NAV", fmt_cr(ledger["shadow_nav"]))

            st.markdown(f"**Multi-Month Hedge Ladder:** Distributed evenly across **{asset['ladder_months']}**. Notice that IM capital is freed up as months settle.")
            
            m_df = pd.DataFrame(ledger["margin_book"])
            st.dataframe(m_df, hide_index=True, use_container_width=True)

            if ledger["realizable_offset"] > 0:
                st.success(f"☔ Weather Hedge Successfully Offsetting Cash Interest Risk: {fmt_cr(ledger['realizable_offset'])} in deployable exchange liquidity.")

# --- TAB 2: ML FORECASTING & REALISTIC PATH ---
with tab2:
    st.markdown("<div class='section-title'>Historical Trajectory & ML Forward Forecast</div>", unsafe_allow_html=True)
    st.write("The historical path (Days 1-93) shows a realistic CDR index dropping during a dry June, violently spiking during July floods, and leveling out in August. The ML engine forecasts the remaining September days.")

    past_path = st.session_state.cdr_path
    days_left = 122 - st.session_state.current_monsoon_day
    future_days, mean_f, upper_f, lower_f = generate_ml_forecast(past_path, days_left)

    fig = go.Figure()
    
    # 1. Plot Historical Realized Path
    fig.add_trace(go.Scatter(x=np.arange(1, len(past_path)+1), y=past_path, mode='lines', 
                             line=dict(color='black', width=2), name='Realized CDR Path (Jun-Aug)'))
    
    # 2. Plot ML Confidence Band
    fig.add_trace(go.Scatter(x=np.concatenate([future_days, future_days[::-1]]), 
                             y=np.concatenate([upper_f, lower_f[::-1]]),
                             fill='toself', fillcolor='rgba(14,58,95,0.15)', line=dict(color='rgba(255,255,255,0)'),
                             name='95% ML Confidence Interval (Sep)'))
    
    # 3. Plot ML Mean Forecast
    fig.add_trace(go.Scatter(x=future_days, y=mean_f, mode='lines', 
                             line=dict(color='#0e3a5f', width=3, dash='dash'), name='ML Mean Trajectory'))
    
    # 4. Reference Baseline
    fig.add_hline(y=LPA_BASELINE_MM, line_color="green", line_width=1, annotation_text="LPA Zero-Deviation Baseline (2206.7 mm)")
    
    # 5. Current Spot Marker
    fig.add_trace(go.Scatter(x=[st.session_state.current_monsoon_day], y=[st.session_state.cdr_spot], mode='markers', 
                             marker=dict(color='red', size=10), name='Today (Sep 1)'))
    
    fig.update_layout(
        title="Monsoon 2026 CDR Evolution: Realized Volatility vs ML Forward Curve",
        xaxis_title="Day of Monsoon Season (1-122)",
        yaxis_title="CDR Index Level (mm)",
        hovermode="x unified",
        plot_bgcolor="white",
        height=500
    )
    st.plotly_chart(fig, use_container_width=True)
