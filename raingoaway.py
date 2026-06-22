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

# =====================================================================================
# GLOBAL CONSTANTS & NCDEX SPECS
# =====================================================================================

LPA_BASELINE_MM = 2206.7          
TICK_VALUE_RS = 50                
CONTRACT_MONTHS = ["JUN", "JUL", "AUG", "SEP"]
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
    .hud-card { background-color: #f7f9fc; border: 1px solid #d3dce6; border-radius: 8px; padding: 15px; text-align: center; }
    .hud-title { font-size: 13px; color: #5c6ac4; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 5px; }
    .hud-val { font-size: 24px; color: #0b1f3a; font-family: 'IBM Plex Mono', monospace; font-weight: 700; }
    .section-title { font-size: 18px; font-weight: 700; color: #0b1f3a; border-left: 5px solid #0e3a5f; padding-left: 10px; margin: 18px 0 10px 0; }
    .pill { display: inline-block; background-color: #e6edf7; color: #0b1f3a; border-radius: 14px; padding: 3px 12px; font-size: 11.5px; font-weight: 600; margin-right: 6px; }
    .pill-pik { background-color: #fbe6d4; color: #7a3b00; }
    .pill-cash { background-color: #d7f0e1; color: #0a5c33; }
    </style>
    """, unsafe_allow_html=True
)

# =====================================================================================
# SESSION STATE INITIALIZATION & HISTORICAL PATH
# =====================================================================================

def init_state():
    if "initialized" in st.session_state: return
    st.session_state.initialized = True

    # September 1 Environment
    st.session_state.current_monsoon_day = 93
    st.session_state.cdr_spot = 2510.0
    st.session_state.prev_cdr_spot = 2495.5
    
    st.session_state.futures_ltp = {
        "JUN": 2130.5, "JUL": 2480.0, "AUG": 2495.5, "SEP": 2510.0
    }
    
    st.session_state.assets = [
        {
            "deal_id": "PC-MUM-401", "name": "Mumbai Commercial RE Development Note",
            "capital_cr": 185.0, "base_coupon_pct": 13.25,
            "hedge_target_offset_pct": 0.50, "hedge_shock_mm": 50.0,
            "ladder_months": ["JUN", "JUL", "AUG"], "entry_price": 2210.0, "threshold_mm": 2350.0,
        }
    ]

# =====================================================================================
# MONTE CARLO STOCHASTIC ENGINE
# =====================================================================================

def run_monte_carlo_sims(start_cdr, days_forward, num_sims=10000, inject_black_swan=False):
    """Generates thousands of random future paths based on historical volatility."""
    np.random.seed(42) # For reproducible UI rendering
    
    # Base daily parameters (mean drift and standard deviation in mm)
    drift = 1.5 
    volatility = 5.0 
    
    if inject_black_swan:
        volatility = 8.0 # Higher baseline variance
        
    # Generate daily shocks matrix: shape (days, sims)
    daily_shocks = np.random.normal(drift, volatility, (days_forward, num_sims))
    
    if inject_black_swan:
        # Introduce a 4% chance of a massive 40-70mm daily cloudburst per day
        cloudbursts = np.random.choice([0, 1], size=(days_forward, num_sims), p=[0.96, 0.04])
        cloudburst_magnitudes = np.random.uniform(40, 70, (days_forward, num_sims))
        daily_shocks += (cloudbursts * cloudburst_magnitudes)
        
    # Build cumulative paths
    paths = np.vstack([np.full(num_sims, start_cdr), start_cdr + np.cumsum(daily_shocks, axis=0)])
    return paths

# =====================================================================================
# UI LAYOUT
# =====================================================================================

init_state()

st.markdown(
    """
    <div class="mantra-header">
        <h1>🌧️ Mantra Weather Risk Ledger</h1>
        <p>Buy-Side Portfolio Manager &nbsp;|&nbsp; RAINMUMBAI Multi-Month Derivatives &nbsp;|&nbsp; 1mm = ₹50</p>
    </div>
    """, unsafe_allow_html=True
)

tab1, tab2 = st.tabs(["🏛️ Portfolio Master Ledger", "🎲 ML Trade Probability Sandbox"])

# -------------------------------------------------------------------------------------
# TAB 1: QUICK LEDGER (Abridged for focus)
# -------------------------------------------------------------------------------------
with tab1:
    st.markdown("<div class='section-title'>Active Private Credit Facilities</div>", unsafe_allow_html=True)
    asset = st.session_state.assets[0]
    with st.container(border=True):
        st.markdown(f"### {asset['name']} · `{asset['deal_id']}`")
        st.write(f"**Principal:** ₹{asset['capital_cr']} Cr | **Base Coupon:** {asset['base_coupon_pct']}% | **Hedge Strategy:** Q3 Ladder (JUN/JUL/AUG)")
        st.info("Months Jun, Jul, and Aug have settled. Realized P&L has been swept to the bank. Switch to the ML Sandbox to model active SEP hedging risk.")

# -------------------------------------------------------------------------------------
# TAB 2: ML TRADE PROBABILITY SANDBOX (MONTE CARLO)
# -------------------------------------------------------------------------------------
with tab2:
    st.markdown("<div class='section-title'>Monte Carlo Trade Probability Simulator</div>", unsafe_allow_html=True)
    st.write("Run 10,000 algorithmic future weather paths to determine the statistical probability of your trade generating targeted alpha versus triggering critical margin pain.")

    col_inputs, col_viz = st.columns([1, 3])

    # --- 1. THE COCKPIT (INPUTS) ---
    with col_inputs:
        st.markdown("#### Trade Parameters")
        
        position = st.selectbox("Directional Bias", ["Long (Buy)", "Short (Sell)"])
        is_long = position == "Long (Buy)"
        
        lots = st.slider("Position Size (Lots)", min_value=100, max_value=25000, value=5000, step=100)
        days_forward = st.slider("Days to Expiry / Holding Period", min_value=1, max_value=30, value=15)
        
        st.markdown("#### Financial Boundaries")
        target_profit_cr = st.number_input("Target Profit (₹ Crores)", min_value=0.1, max_value=20.0, value=2.0, step=0.1)
        max_loss_cr = st.number_input("Margin Pain Limit (Max Loss ₹ Cr)", min_value=0.1, max_value=20.0, value=1.0, step=0.1)
        
        st.markdown("#### Tail Risk")
        inject_swan = st.toggle("Inject Extreme Cloudburst Probability")
        
        if st.button("Run 10,000 Simulations", use_container_width=True, type="primary"):
            pass # Triggers a rerun automatically
            
    # --- CALCULATION ENGINE ---
    target_profit_rs = target_profit_cr * CR_TO_RS
    max_loss_rs = max_loss_cr * CR_TO_RS
    
    # Calculate equivalent CDR Index levels that represent these financial triggers
    mm_move_for_target = target_profit_rs / (lots * TICK_VALUE_RS)
    mm_move_for_loss = max_loss_rs / (lots * TICK_VALUE_RS)
    
    entry_price = st.session_state.cdr_spot
    
    if is_long:
        target_cdr_level = entry_price + mm_move_for_target
        loss_cdr_level = entry_price - mm_move_for_loss
    else:
        target_cdr_level = entry_price - mm_move_for_target
        loss_cdr_level = entry_price + mm_move_for_loss

    # Run Simulations
    paths = run_monte_carlo_sims(entry_price, days_forward, 10000, inject_swan)
    final_day_cdrs = paths[-1, :] # The CDR levels on the final day across all 10,000 sims
    
    # Calculate Probabilities based on Final Day Distribution
    if is_long:
        prob_profit = np.mean(final_day_cdrs > entry_price)
        prob_target = np.mean(final_day_cdrs >= target_cdr_level)
        prob_margin_survival = np.mean(final_day_cdrs > loss_cdr_level)
        avg_final_cdr = np.mean(final_day_cdrs)
        expected_value_rs = (avg_final_cdr - entry_price) * lots * TICK_VALUE_RS
    else:
        prob_profit = np.mean(final_day_cdrs < entry_price)
        prob_target = np.mean(final_day_cdrs <= target_cdr_level)
        prob_margin_survival = np.mean(final_day_cdrs < loss_cdr_level)
        avg_final_cdr = np.mean(final_day_cdrs)
        expected_value_rs = (entry_price - avg_final_cdr) * lots * TICK_VALUE_RS

    # --- 2. THE HUD / MATRIX ---
    with col_viz:
        c1, c2, c3, c4 = st.columns(4)
        c1.markdown(f"<div class='hud-card'><div class='hud-title'>Probability of Profit</div><div class='hud-val' style='color: {'#0a5c33' if prob_profit>0.5 else '#0b1f3a'};'>{prob_profit*100:.1f}%</div></div>", unsafe_allow_html=True)
        c2.markdown(f"<div class='hud-card'><div class='hud-title'>Hit Profit Target</div><div class='hud-val'>{prob_target*100:.1f}%</div></div>", unsafe_allow_html=True)
        c3.markdown(f"<div class='hud-card'><div class='hud-title'>Margin Survival (No Call)</div><div class='hud-val' style='color: {'#0a5c33' if prob_margin_survival>0.8 else '#b30000'};'>{prob_margin_survival*100:.1f}%</div></div>", unsafe_allow_html=True)
        
        ev_color = "#0a5c33" if expected_value_rs > 0 else "#b30000"
        ev_sign = "+" if expected_value_rs > 0 else ""
        c4.markdown(f"<div class='hud-card'><div class='hud-title'>Expected Value (EV)</div><div class='hud-val' style='color: {ev_color};'>{ev_sign}₹{abs(expected_value_rs)/CR_TO_RS:.2f} Cr</div></div>", unsafe_allow_html=True)
        
        st.write("")
        
        # --- 3. THE VISUAL SIMULATOR (Plotly) ---
        fig = go.Figure()

        days_axis = np.arange(0, days_forward + 1)
        mean_path = np.mean(paths, axis=1)
        pct_95 = np.percentile(paths, 97.5, axis=1)
        pct_05 = np.percentile(paths, 2.5, axis=1)

        # Plot 50 random ghost paths to show the "Monte Carlo spread"
        for i in range(50):
            fig.add_trace(go.Scatter(x=days_axis, y=paths[:, i], mode='lines', 
                                     line=dict(color='rgba(14, 58, 95, 0.03)', width=1), showlegend=False, hoverinfo='skip'))

        # Plot the 95% Confidence Band
        fig.add_trace(go.Scatter(x=np.concatenate([days_axis, days_axis[::-1]]), 
                                 y=np.concatenate([pct_95, pct_05[::-1]]),
                                 fill='toself', fillcolor='rgba(14,58,95,0.1)', line=dict(color='rgba(255,255,255,0)'),
                                 name='95% Probability Cone'))

        # Plot Mean Path
        fig.add_trace(go.Scatter(x=days_axis, y=mean_path, mode='lines', 
                                 line=dict(color='#0b1f3a', width=3), name='Mean Simulated Path'))

        # Entry Price Line
        fig.add_hline(y=entry_price, line_color="black", line_dash="solid", line_width=2, 
                      annotation_text=f"Entry: {entry_price:.1f} mm", annotation_position="top left")

        # Profit Target Line
        fig.add_hline(y=target_cdr_level, line_color="green", line_dash="dash", line_width=2, 
                      annotation_text=f"Target Profit (₹{target_profit_cr} Cr)", annotation_position="bottom right" if is_long else "top right")

        # Max Loss Line
        fig.add_hline(y=loss_cdr_level, line_color="red", line_dash="dash", line_width=2, 
                      annotation_text=f"Margin Call (Loss > ₹{max_loss_cr} Cr)", annotation_position="top right" if is_long else "bottom right")

        # Dynamic Colored Shading for Profit/Loss Zones on the background
        y_max = np.max(paths) + 50
        y_min = np.min(paths) - 50
        
        if is_long:
            fig.add_hrect(y0=entry_price, y1=y_max, fillcolor="green", opacity=0.05, line_width=0, layer="below")
            fig.add_hrect(y0=y_min, y1=entry_price, fillcolor="red", opacity=0.05, line_width=0, layer="below")
        else:
            fig.add_hrect(y0=y_min, y1=entry_price, fillcolor="green", opacity=0.05, line_width=0, layer="below")
            fig.add_hrect(y0=entry_price, y1=y_max, fillcolor="red", opacity=0.05, line_width=0, layer="below")

        fig.update_layout(
            xaxis_title="Days from Trade Entry",
            yaxis_title="CDR Index Level (mm)",
            hovermode="x unified",
            plot_bgcolor="white",
            height=500,
            margin=dict(l=0, r=0, t=30, b=0),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        st.plotly_chart(fig, use_container_width=True)
        
        st.caption(f"*Simulation Stats: 10,000 paths calculated based on a daily volatility of {8.0 if inject_swan else 5.0} mm. Position sized at {lots:,} lots.*")
