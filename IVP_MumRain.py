"""
IVP Rainfall Module
=====================================================================================
Institutional-grade data management and trade modeling application for 
NCDEX RAINMUMBAI weather futures. 
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

LPA_BASELINE_MM = 2206.7          # Starting Anchor for Mumbai monsoon CDR
TICK_VALUE_RS = 50                # ₹ per mm move (NCDEX RAINMUMBAI multiplier)
CONTRACT_MONTHS = ["JUN", "JUL", "AUG", "SEP"]
MARGIN_INITIAL_PCT = 0.12         # 12% initial margin on notional
CR_TO_RS = 1e7                    

st.set_page_config(
    page_title="IVP Rainfall Module",
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
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
    
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
    
    .ivp-header {
        background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
        padding: 24px 32px; border-radius: 8px; border-left: 6px solid #3b82f6; margin-bottom: 20px;
    }
    .ivp-header h1 { color: #f8fafc; font-size: 28px; font-weight: 700; margin: 0; letter-spacing: -0.5px; }
    .ivp-header p { color: #94a3b8; font-size: 14px; margin: 8px 0 0 0; font-family: 'JetBrains Mono', monospace; }
    
    .term-box {
        background-color: #020617; color: #10b981; font-family: 'JetBrains Mono', monospace;
        font-size: 12px; padding: 16px; border-radius: 6px; border: 1px solid #1e293b;
        height: 200px; overflow-y: auto; line-height: 1.6;
    }
    .section-title { font-size: 18px; font-weight: 600; color: #0f172a; border-bottom: 2px solid #e2e8f0; padding-bottom: 8px; margin: 24px 0 16px 0; }
    .hud-card { background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 6px; padding: 16px; text-align: center; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
    .hud-title { font-size: 12px; color: #64748b; font-weight: 600; text-transform: uppercase; margin-bottom: 8px; }
    .hud-val { font-size: 24px; color: #0f172a; font-family: 'JetBrains Mono', monospace; font-weight: 700; }
    .pill { display: inline-block; border-radius: 4px; padding: 4px 10px; font-size: 11px; font-weight: 600; }
    .pill-long { background-color: #dcfce7; color: #166534; }
    .pill-short { background-color: #fee2e2; color: #991b1b; }
    </style>
    """, unsafe_allow_html=True
)

# =====================================================================================
# REALISTIC DATA GENERATION ENGINE
# =====================================================================================

def generate_daily_cdr(start_date: date, end_date: date):
    """Generates realistic daily Cumulative Deviation Rainfall (CDR) from June 1."""
    days = (end_date - start_date).days + 1
    dates = [start_date + timedelta(days=i) for i in range(days)]
    
    # LPA is roughly 2206.7 over 122 days -> ~18.08 mm/day normal
    normal_daily = 18.08
    
    np.random.seed(42) # For consistent rendering across re-runs
    actual_daily = np.random.normal(loc=17.5, scale=8.0, size=days) 
    actual_daily = np.maximum(actual_daily, 0) # No negative rainfall
    
    # Introduce a few heavy monsoon days
    cloudbursts = np.random.choice([0, 1], size=days, p=[0.92, 0.08])
    actual_daily += cloudbursts * np.random.uniform(40, 90, size=days)
    
    # CDR Calculation: Base + Cumulative(Actual - Normal)
    daily_deviations = actual_daily - normal_daily
    cdr_path = LPA_BASELINE_MM + np.cumsum(daily_deviations)
    
    df = pd.DataFrame({'Date': dates, 'Actual_Rain_mm': actual_daily, 'CDR_Index': cdr_path})
    return df

# =====================================================================================
# SESSION STATE INITIALIZATION
# =====================================================================================

def init_state():
    if "initialized" in st.session_state: return
    st.session_state.initialized = True

    # System defaults to June 23, 2026
    st.session_state.start_date = date(2026, 6, 1)
    st.session_state.current_date = date(2026, 6, 23)
    
    # Generate Data
    st.session_state.history_df = generate_daily_cdr(st.session_state.start_date, st.session_state.current_date)
    st.session_state.cdr_spot = st.session_state.history_df['CDR_Index'].iloc[-1]
    
    # Simulated Active Contract LTPs
    st.session_state.futures_ltp = {
        "JUN": st.session_state.cdr_spot + 15.0,
        "JUL": st.session_state.cdr_spot + 120.0,
        "AUG": st.session_state.cdr_spot + 145.0,
        "SEP": st.session_state.cdr_spot + 155.0,
    }
    
    st.session_state.last_scrape = datetime.now()
    st.session_state.log = ["[IVP AI] System Initialized. NCDEX Web nodes connected."]
    
    # Corporate Deal Ledger
    st.session_state.deals = [
        {
            "id": "LOG-001", "entity": "Western Express Logistics Corp", "industry": "Logistics",
            "contract": "JUL", "position": "Long", "lots": 2500, "entry_px": 2190.5,
            "rationale": "Hedging against severe flooding causing fleet grounding and port delays."
        },
        {
            "id": "AGR-002", "entity": "Maharashtra Fertilizer Dynamics", "industry": "Agriculture",
            "contract": "JUL", "position": "Short", "lots": 1800, "entry_px": 2240.0,
            "rationale": "Hedging against dry spells. If no rain, fertilizer sales plummet; short position yields payout."
        },
        {
            "id": "CON-003", "entity": "Navi Mumbai Infra Builders", "industry": "Construction",
            "contract": "AUG", "position": "Long", "lots": 4000, "entry_px": 2215.0,
            "rationale": "Protecting against monsoon site washouts and labor halting."
        },
        {
            "id": "FMC-004", "entity": "Bharat Consumer Goods", "industry": "FMCG",
            "contract": "SEP", "position": "Short", "lots": 3000, "entry_px": 2260.0,
            "rationale": "Hedging rural demand drop due to poor late-season monsoons."
        },
        {
            "id": "EVT-005", "entity": "Apex Event Management", "industry": "Events & Hospitality",
            "contract": "JUN", "position": "Long", "lots": 500, "entry_px": 2185.0,
            "rationale": "Insuring major outdoor corporate events scheduled for late June against washout."
        },
        {
            "id": "PC-006", "entity": "Mantra Private Credit - Real Estate Note", "industry": "Private Credit",
            "contract": "JUL", "position": "Long", "lots": 6500, "entry_px": 2200.0,
            "rationale": "Covenant Holiday backstop. Derivative MTM offsets at-risk cash interest during flood events."
        },
        {
            "id": "PC-007", "entity": "Mantra Private Credit - Port Debt Facility", "industry": "Private Credit",
            "contract": "AUG", "position": "Long", "lots": 8200, "entry_px": 2210.0,
            "rationale": "Debt interest hedge securing logistics borrower against operational revenue loss."
        }
    ]

def log_msg(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    st.session_state.log.insert(0, f"[{ts}] {msg}")
    st.session_state.log = st.session_state.log[:50]

# =====================================================================================
# UI LAYOUT
# =====================================================================================

init_state()

st.markdown(
    """
    <div class="ivp-header">
        <h1>IVP Rainfall Module</h1>
        <p>Institutional Data Management & AI Modeling | NCDEX RAINMUMBAI Futures | Base: 2206.7 mm</p>
    </div>
    """, unsafe_allow_html=True
)

tab1, tab2, tab3 = st.tabs(["📡 IVP AI Data Engine", "🏢 Corporate Deal Ledger", "🧠 IVP AI Intelligence & Modeler"])

# -------------------------------------------------------------------------------------
# TAB 1: IVP AI DATA ENGINE (Scraper & Daily Trends)
# -------------------------------------------------------------------------------------
with tab1:
    st.markdown("<div class='section-title'>IVP AI Scraper & Live Market Feed</div>", unsafe_allow_html=True)
    st.write("Simulated AI engine scraping NCDEX Level 2 order books and CDR spot indexes every 15 minutes. Data is reconciled against IMD daily LPA metrics.")
    
    col1, col2 = st.columns([1, 3])
    
    with col1:
        selected_date = st.date_input("Operating Date", value=st.session_state.current_date, min_value=date(2026, 6, 1), max_value=date(2026, 9, 30))
        if selected_date != st.session_state.current_date:
            st.session_state.current_date = selected_date
            st.session_state.history_df = generate_daily_cdr(st.session_state.start_date, selected_date)
            st.session_state.cdr_spot = st.session_state.history_df['CDR_Index'].iloc[-1]
            st.rerun()

        st.metric("Live CDR Spot (mm)", f"{st.session_state.cdr_spot:.2f}")
        
        if st.button("🔄 Force 15-Min Scrape Refresh", use_container_width=True):
            tick = random.uniform(-2.5, 3.5)
            st.session_state.cdr_spot += tick
            for m in CONTRACT_MONTHS: st.session_state.futures_ltp[m] += tick * random.uniform(0.8, 1.2)
            st.session_state.last_scrape = datetime.now()
            log_msg(f"NCDEX Feed Scraped. CDR Spot updated to {st.session_state.cdr_spot:.2f} mm.")
            st.rerun()
            
        st.markdown("<div class='term-box'>" + "<br>".join(st.session_state.log) + "</div>", unsafe_allow_html=True)
        
    with col2:
        df_hist = st.session_state.history_df
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df_hist['Date'], y=df_hist['CDR_Index'], mode='lines+markers', 
                                 line=dict(color='#3b82f6', width=2), marker=dict(size=4), name='CDR Index'))
        fig.add_hline(y=LPA_BASELINE_MM, line_color="#94a3b8", line_dash="dash", annotation_text="LPA Base (2206.7)")
        
        fig.update_layout(
            title=f"Mumbai CDR Index Trend (June 1 to {selected_date.strftime('%B %d')})",
            xaxis_title="Date", yaxis_title="Cumulative Deviation Rainfall (mm)",
            hovermode="x unified", plot_bgcolor="#f8fafc", height=400, margin=dict(l=0, r=0, t=40, b=0)
        )
        st.plotly_chart(fig, use_container_width=True)
        
        st.markdown("#### Active Exchange Tranches (LTP)")
        df_futs = pd.DataFrame({"Contract": CONTRACT_MONTHS, "Live Price (mm)": [round(st.session_state.futures_ltp[m], 2) for m in CONTRACT_MONTHS]})
        st.dataframe(df_futs.T, use_container_width=True)

# -------------------------------------------------------------------------------------
# TAB 2: CORPORATE DEAL LEDGER
# -------------------------------------------------------------------------------------
with tab2:
    st.markdown("<div class='section-title'>Institutional Deal Master & Hedging Ledger</div>", unsafe_allow_html=True)
    st.write("Aggregated view of how entities across Logistics, Agriculture, FMCG, and Private Credit utilize IVP data to structure margin-efficient climate hedges.")
    
    deal_data = []
    for d in st.session_state.deals:
        live_px = st.session_state.futures_ltp[d["contract"]]
        
        # Financial Math via standard definitions
        direction = 1 if d["position"] == "Long" else -1
        mtm_rs = direction * (live_px - d["entry_px"]) * d["lots"] * TICK_VALUE_RS
        margin_req_rs = live_px * d["lots"] * TICK_VALUE_RS * MARGIN_INITIAL_PCT
        
        deal_data.append({
            "Deal ID": d["id"],
            "Entity": d["entity"],
            "Industry": d["industry"],
            "Contract": d["contract"],
            "Pos": d["position"],
            "Lots": f"{d['lots']:,}",
            "Entry Px": f"{d['entry_px']:.1f}",
            "Live Px": f"{live_px:.1f}",
            "Initial Margin Req": f"₹{margin_req_rs/CR_TO_RS:.2f} Cr",
            "Unrealized P&L": f"₹{mtm_rs/CR_TO_RS:.2f} Cr",
            "Rationale": d["rationale"]
        })
        
    st.dataframe(pd.DataFrame(deal_data).style.applymap(
        lambda x: 'color: #166534; font-weight: bold;' if isinstance(x, str) and x.startswith('₹') and '-' not in x 
        else ('color: #991b1b; font-weight: bold;' if isinstance(x, str) and x.startswith('₹-') else ''),
        subset=['Unrealized P&L']
    ), hide_index=True, use_container_width=True)
    
    with st.expander("➕ Append New Deal to Ledger"):
        with st.form("new_deal_form", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            new_entity = c1.text_input("Entity Name")
            new_ind = c2.selectbox("Industry", ["Logistics", "Agriculture", "FMCG", "Construction", "Private Credit", "Other"])
            new_month = c3.selectbox("Contract Month", CONTRACT_MONTHS)
            
            c4, c5, c6 = st.columns(3)
            new_pos = c4.selectbox("Position", ["Long", "Short"])
            new_lots = c5.number_input("Lots", min_value=1, value=1000, step=100)
            new_entry = c6.number_input("Entry Price (mm)", value=float(st.session_state.cdr_spot))
            
            new_rationale = st.text_input("Hedging Rationale")
            
            if st.form_submit_button("Provision Deal"):
                st.session_state.deals.append({
                    "id": f"IVP-{(len(st.session_state.deals)+1):03d}",
                    "entity": new_entity, "industry": new_ind, "contract": new_month,
                    "position": new_pos, "lots": new_lots, "entry_px": new_entry, "rationale": new_rationale
                })
                st.success("Deal successfully provisioned into ledger.")
                st.rerun()

# -------------------------------------------------------------------------------------
# TAB 3: IVP AI INTELLIGENCE & MODELER
# -------------------------------------------------------------------------------------
with tab3:
    st.markdown("<div class='section-title'>IVP AI Trade Modeler & Cloud Tracking</div>", unsafe_allow_html=True)
    st.write("Utilize IVP Machine Learning and simulated geospatial cloud-tracking algorithms to forecast CDR probabilities and model trade outcomes.")
    
    mc1, mc2 = st.columns([1, 2])
    
    with mc1:
        st.markdown("#### Trade Sandbox Parameters")
        s_date = st.date_input("Target Trade Date", value=st.session_state.current_date)
        s_dir = st.selectbox("Market Bias", ["Long (Buy)", "Short (Sell)"])
        s_lots = st.number_input("Target Lot Size", min_value=100, value=5000, step=500)
        s_days = st.slider("Hold Duration (Days)", 1, 45, 15)
        
        st.markdown("#### IVP AI Geospatial Override")
        cloud_factor = st.selectbox("Simulated Satellite Forecast", ["Normal Monsoon Development", "Severe Depression (Heavy Rain Bias)", "El Niño Dominance (Dry Bias)"])
        
        if st.button("Run IVP AI Simulation", type="primary", use_container_width=True):
            pass # Triggers UI rerun
            
    with mc2:
        # IVP AI Math Generation
        np.random.seed(42) # Anchor
        entry_val = st.session_state.cdr_spot
        
        drift = 17.5 - 18.08 # normal drift
        if "Heavy" in cloud_factor: drift += 8.0
        if "Dry" in cloud_factor: drift -= 5.0
        
        # Monte carlo paths
        paths = np.vstack([np.full(1000, entry_val), entry_val + np.cumsum(np.random.normal(drift, 6.0, (s_days, 1000)), axis=0)])
        final_cdrs = paths[-1, :]
        mean_final = np.mean(final_cdrs)
        
        is_long = s_dir == "Long (Buy)"
        win_rate = np.mean(final_cdrs > entry_val) if is_long else np.mean(final_cdrs < entry_val)
        
        # EV Formula formatting via LaTeX explicitly for complex formulas per instructions
        st.markdown("IVP Engine evaluates Expected Value via: $$\\text{EV} = \\frac{1}{N} \\sum_{i=1}^{N} (\\text{Final CDR}_i - \\text{Entry}) \\times \\text{Lots} \\times 50$$")
        
        expected_pnl = (mean_final - entry_val) * s_lots * TICK_VALUE_RS if is_long else (entry_val - mean_final) * s_lots * TICK_VALUE_RS
        req_margin = entry_val * s_lots * TICK_VALUE_RS * MARGIN_INITIAL_PCT
        
        h1, h2, h3 = st.columns(3)
        h1.markdown(f"<div class='hud-card'><div class='hud-title'>Trade Win Probability</div><div class='hud-val' style='color: {'#166534' if win_rate>0.5 else '#0f172a'};'>{win_rate*100:.1f}%</div></div>", unsafe_allow_html=True)
        h2.markdown(f"<div class='hud-card'><div class='hud-title'>Expected P&L (EV)</div><div class='hud-val' style='color: {'#166534' if expected_pnl>0 else '#991b1b'};'>₹{expected_pnl/CR_TO_RS:.2f} Cr</div></div>", unsafe_allow_html=True)
        h3.markdown(f"<div class='hud-card'><div class='hud-title'>Required Margin</div><div class='hud-val'>₹{req_margin/CR_TO_RS:.2f} Cr</div></div>", unsafe_allow_html=True)
        
        st.write("")
        
        # Fan Chart
        days_ax = np.arange(0, s_days + 1)
        mean_path = np.mean(paths, axis=1)
        upper_90 = np.percentile(paths, 95, axis=1)
        lower_90 = np.percentile(paths, 5, axis=1)
        
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(x=np.concatenate([days_ax, days_ax[::-1]]), y=np.concatenate([upper_90, lower_90[::-1]]),
                                  fill='toself', fillcolor='rgba(59,130,246,0.15)', line=dict(color='rgba(255,255,255,0)'), name='90% IVP AI Confidence Interval'))
        fig2.add_trace(go.Scatter(x=days_ax, y=mean_path, mode='lines', line=dict(color='#1e293b', width=3), name='Mean AI Forecast'))
        fig2.add_hline(y=entry_val, line_color="#ef4444", line_dash="dash", annotation_text=f"Entry Level: {entry_val:.2f}")
        
        fig2.update_layout(title="IVP AI Dynamic Trade Trajectory Map", xaxis_title="Holding Days", yaxis_title="Forecasted CDR (mm)", 
                           height=350, margin=dict(l=0, r=0, t=35, b=0), plot_bgcolor="#f8fafc")
        st.plotly_chart(fig2, use_container_width=True)