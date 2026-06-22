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