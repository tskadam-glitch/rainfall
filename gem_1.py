import streamlit as st
import pandas as pd
import numpy as np
import datetime
import time
from math import radians, cos, sin, asin, sqrt
import plotly.graph_objects as go
import plotly.express as px

# ==========================================
# PAGE CONFIGURATION & GLOBAL SETTINGS
# ==========================================
st.set_page_config(
    page_title="Mantra Weather Risk Ledger | Buy-Side Manager",
    page_icon="⛈️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Constants
MULTIPLIER = 50.0  # ₹50 per 1 mm tick
LPA_BASE = 2206.7  # Baseline Long Period Average (mm)
CR_TO_INR = 10000000.0

# ==========================================
# UTILITY FUNCTIONS
# ==========================================
def haversine(lon1, lat1, lon2, lat2):
    """Calculate the great circle distance between two points on the earth (specified in decimal degrees)"""
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    r = 6371 # Radius of earth in kilometers
    return c * r

# ==========================================
# SESSION STATE INITIALIZATION
# ==========================================
def init_session_state():
    if 'initialized' not in st.session_state:
        st.session_state.initialized = True
        
        # 1. Simulated Market Data
        st.session_state.market_data = {
            'spot_cdr': 185.5,
            'contracts': {
                'June': {'ltp': 210.0, 'oi': 4500},
                'July': {'ltp': 320.5, 'oi': 12050},
                'August': {'ltp': 280.0, 'oi': 8900},
                'September': {'ltp': 150.0, 'oi': 3400}
            }
        }
        
        # 2. Terminal Logs
        st.session_state.terminal_logs = [
            f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] SYSTEM INITIALIZED. NCDEX Data Engine Online."
        ]
        
        # 3. Portfolio Asset Master
        st.session_state.portfolio = [
            {
                'deal_id': 'PC-MUM-401',
                'name': 'Mumbai Commercial RE Development Note (Andheri Facility)',
                'capital_cr': 150.0,
                'coupon_pct': 14.5,
                'dsra_cr': 5.0,
                'contract_month': 'July',
                'position': 'Long',
                'lots': 200,
                'entry_price': 250.0,
                'target_cdr': 200.0,
                'lat': 19.1136,
                'lon': 72.8697
            },
            {
                'deal_id': 'PC-MUM-402',
                'name': 'Bhiwandi Port Logistics Infrastructure Note',
                'capital_cr': 250.0,
                'coupon_pct': 16.0,
                'dsra_cr': 8.5,
                'contract_month': 'August',
                'position': 'Long',
                'lots': 350,
                'entry_price': 200.0,
                'target_cdr': 300.0,
                'lat': 19.3000,
                'lon': 73.0667
            }
        ]

init_session_state()

# ==========================================
# MODULE 1: SIMULATED LIVE NCDEX INGESTION ENGINE
# ==========================================
def run_ai_scraper():
    now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    st.session_state.terminal_logs.insert(0, f"[{now_str}] Attributes Extracted Successfully.")
    st.session_state.terminal_logs.insert(0, f"[{now_str}] AI Scraper Parsing NCDEX Web Nodes...")
    
    # Introduce controlled randomness to simulate live price ticks
    drift = np.random.normal(5, 15)
    st.session_state.market_data['spot_cdr'] += drift
    
    for month, data in st.session_state.market_data['contracts'].items():
        data['ltp'] += np.random.normal(drift * 0.8, 10)
        data['oi'] += int(np.random.normal(50, 200))
        
    # Keep logs manageable
    st.session_state.terminal_logs = st.session_state.terminal_logs[:15]

with st.sidebar:
    st.header("📡 NCDEX Ingestion Engine")
    st.markdown("---")
    
    if st.button("Force 15-Min Scrape Refresh", use_container_width=True):
        with st.spinner("Executing Data Pipeline..."):
            time.sleep(0.5)
            run_ai_scraper()
            
    st.metric(label="Spot Underlying (CDR)", value=f"{st.session_state.market_data['spot_cdr']:.1f} mm", 
              delta=f"{st.session_state.market_data['spot_cdr'] - 185.5:.1f} mm from base")
    
    st.markdown("### Active Contract Months (LTP)")
    for month, data in st.session_state.market_data['contracts'].items():
        col1, col2 = st.columns(2)
        col1.markdown(f"**{month}**")
        col2.markdown(f"₹{data['ltp']:.2f} (OI: {data['oi']})")
        
    st.markdown("---")
    st.markdown("### Pipeline Execution Logs")
    log_text = "\n".join(st.session_state.terminal_logs)
    st.text_area("Terminal Output", value=log_text, height=250, disabled=True)

# ==========================================
# MAIN DASHBOARD LAYOUT
# ==========================================
st.title("Mantra Weather Risk Ledger")
st.subheader("Buy-Side Private Credit & Derivatives Portfolio Manager")
st.markdown("---")

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "Security Master", 
    "Quant Distribution & Margin", 
    "Extreme Loss Terminal", 
    "30-Year Climate Matrix", 
    "Spatial Basis Risk Map"
])

# ==========================================
# MODULE 2: MULTI-ASSET SECURITY MASTER
# ==========================================
with tab1:
    st.markdown("### Portfolio Asset Master (Structure 1: Monsoon-Toggle Debt)")
    
    df_portfolio = pd.DataFrame(st.session_state.portfolio)
    st.dataframe(df_portfolio[['deal_id', 'name', 'capital_cr', 'coupon_pct', 'contract_month', 'target_cdr']], use_container_width=True)
    
    st.markdown("---")
    st.markdown("### Provision & Link New Debt Asset")
    with st.form("new_asset_form"):
        col1, col2, col3 = st.columns(3)
        deal_id = col1.text_input("Deal ID", value="PC-MUM-403")
        deal_name = col2.text_input("Asset/Deal Name", value="Navi Mumbai Highway Extension Note")
        capital_cr = col3.number_input("Capital Deployed (Cr)", min_value=1.0, value=100.0)
        
        col4, col5, col6 = st.columns(3)
        coupon_pct = col4.number_input("Base Coupon Rate (%)", min_value=1.0, value=12.5)
        dsra_cr = col5.number_input("Mandatory DSRA (Cr)", min_value=0.1, value=4.0)
        contract_month = col6.selectbox("NCDEX Contract Tranche", ["June", "July", "August", "September"])
        
        col7, col8, col9 = st.columns(3)
        position = col7.selectbox("Derivative Position", ["Long", "Short"])
        lots = col8.number_input("Number of Lots", min_value=1, value=150)
        target_cdr = col9.number_input("Target CDR Threshold (Holiday Trigger)", value=350.0)
        
        col10, col11 = st.columns(2)
        lat = col10.number_input("Asset Latitude", value=19.0330)
        lon = col11.number_input("Asset Longitude", value=73.0297)
        
        submit_asset = st.form_submit_button("Link Asset & Provision Ledger")
        if submit_asset:
            new_asset = {
                'deal_id': deal_id, 'name': deal_name, 'capital_cr': capital_cr,
                'coupon_pct': coupon_pct, 'dsra_cr': dsra_cr, 'contract_month': contract_month,
                'position': position, 'lots': lots, 'entry_price': st.session_state.market_data['contracts'][contract_month]['ltp'],
                'target_cdr': target_cdr, 'lat': lat, 'lon': lon
            }
            st.session_state.portfolio.append(new_asset)
            st.success(f"Asset {deal_id} successfully provisioned and linked to the {contract_month} NCDEX order book.")
            st.rerun()

# ==========================================
# MODULE 3: QUANTITATIVE DISTRIBUTION ENGINE & MARGIN LEDGER
# ==========================================
with tab2:
    st.markdown("### Quantitative Distribution & Dynamic Ledger Computations")
    
    for asset in st.session_state.portfolio:
        st.markdown(f"#### {asset['deal_id']}: {asset['name']}")
        
        # Fetch current market state
        spot_cdr = st.session_state.market_data['spot_cdr']
        ltp = st.session_state.market_data['contracts'][asset['contract_month']]['ltp']
        
        # Financial Logic Calculations
        base_yield_inr = (asset['capital_cr'] * CR_TO_INR) * (asset['coupon_pct'] / 100.0) / 4.0 # Quarterly distribution
        holiday_triggered = spot_cdr > asset['target_cdr']
        
        if holiday_triggered:
            cash_dist = base_yield_inr * 0.25 # 75% deferred to PIK
            pik_dist = base_yield_inr * 0.75
            status_text = "🟢 COVENANT HOLIDAY ACTIVATED (Cash deferred to PIK)"
        else:
            cash_dist = base_yield_inr
            pik_dist = 0.0
            status_text = "⚪ STANDARD CASH DISTRIBUTION (No threshold breach)"
            
        # Hedge P&L
        price_diff = ltp - asset['entry_price']
        if asset['position'] == 'Short':
            price_diff = -price_diff
            
        hedge_pnl = price_diff * asset['lots'] * MULTIPLIER
        
        # Shadow NAV
        nav_base = asset['capital_cr'] * CR_TO_INR
        shadow_nav = nav_base + pik_dist + hedge_pnl
        
        # Margin Monitor (99% 3-Day VaR)
        position_value = ltp * asset['lots'] * MULTIPLIER
        volatility_mm = 15.0 # Estimated standard deviation in mm
        var_3d = position_value * 2.33 * (volatility_mm / ltp) * np.sqrt(3)
        init_margin = position_value * 0.10
        var_margin = max(0, -hedge_pnl) # Cash required to offset MTM losses
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Shadow NAV (INR)", f"₹{shadow_nav:,.2f}", f"Hedge P&L: ₹{hedge_pnl:,.2f}")
        col2.metric("Base Qtr Yield", f"₹{base_yield_inr:,.2f}")
        col3.metric("Required Cash Dist.", f"₹{cash_dist:,.2f}")
        col4.metric("PIK Capitalized", f"₹{pik_dist:,.2f}")
        
        st.caption(status_text)
        
        # Margin UI
        margin_df = pd.DataFrame([{
            'Metric': 'Value',
            'Gross Exposure': f"₹{position_value:,.2f}",
            'Initial Margin (10%)': f"₹{init_margin:,.2f}",
            'Variation Margin Required': f"₹{var_margin:,.2f}",
            '99% 3-Day VaR': f"₹{var_3d:,.2f}"
        }])
        st.table(margin_df.set_index('Metric'))
        st.markdown("---")

# ==========================================
# MODULE 4: HIGH-SEVERITY RISK & EXTREME LOSS ALERT TERMINAL
# ==========================================
with tab3:
    st.markdown("### Automated Boundary & Tail-Risk Monitor")
    
    # Check for systemic boundary breach
    spot_cdr = st.session_state.market_data['spot_cdr']
    CRITICAL_BOUNDARY = 400.0
    
    if spot_cdr > CRITICAL_BOUNDARY:
        st.markdown(
            """
            <style>
            .blink_me {
                animation: blinker 0.8s linear infinite;
                background-color: #8b0000;
                color: white;
                font-weight: bold;
                font-size: 24px;
                padding: 20px;
                text-align: center;
                border-radius: 5px;
                border: 2px solid red;
            }
            @keyframes blinker {
                50% { opacity: 0.3; }
            }
            </style>
            <div class="blink_me">⚠️ CRITICAL OUTFLOW ALERT: SYSTEMIC CLOUDBURST DETECTED (CDR > 400mm). IMMINENT VARIATION MARGIN EXHAUSTION ON SHORT-VOL PORTFOLIO. IMMEDIATE LIQUIDITY REPLENISHMENT REQUIRED.</div>
            <br>
            """, 
            unsafe_allow_html=True
        )
    else:
        st.success(f"System Operational. Current Spot CDR ({spot_cdr:.1f} mm) is within the safety boundary (< {CRITICAL_BOUNDARY} mm).")

    st.markdown("#### Real-Time Asset Stress Test")
    stress_data = []
    for asset in st.session_state.portfolio:
        ltp = st.session_state.market_data['contracts'][asset['contract_month']]['ltp']
        pnl = (ltp - asset['entry_price']) * asset['lots'] * MULTIPLIER
        if asset['position'] == 'Short': pnl = -pnl
        
        # Calculate DSRA Burn Rate if max loss occurs
        var_margin_call = max(0, -pnl)
        dsra_inr = asset['dsra_cr'] * CR_TO_INR
        dsra_depletion = (var_margin_call / dsra_inr) * 100 if dsra_inr > 0 else 100.0
        
        stress_data.append({
            'Deal ID': asset['deal_id'],
            'DSRA Reserve (INR)': f"₹{dsra_inr:,.2f}",
            'Current Margin Call': f"₹{var_margin_call:,.2f}",
            'DSRA Depletion %': min(dsra_depletion, 100.0),
            'Status': 'CRITICAL' if dsra_depletion > 80 else ('WARNING' if dsra_depletion > 50 else 'SAFE')
        })
    
    st.table(pd.DataFrame(stress_data))

# ==========================================
# MODULE 5: 30-YEAR TREND ANALYSIS & CLIMATE CONFIDENCE MATRIX
# ==========================================
with tab4:
    st.markdown("### Institutional Statistical Weather Modeling (IMD Baselines 1996-2025)")
    
    # Generate 30-year dummy cyclical trend data mathematically (122 days of monsoon)
    days = np.arange(1, 123)
    # Sigmoidal cumulative curve mimicking monsoon buildup
    base_curve = 2500 / (1 + np.exp(-0.06 * (days - 60))) 
    
    # Calculate statistical bands
    std_dev = base_curve * 0.12 # 12% standard deviation historically
    ci_68_upper = base_curve + std_dev
    ci_68_lower = base_curve - std_dev
    ci_95_upper = base_curve + (2 * std_dev)
    ci_95_lower = base_curve - (2 * std_dev)
    ci_99_upper = base_curve + (2.57 * std_dev)
    ci_99_lower = base_curve - (2.57 * std_dev)
    
    fig = go.Figure()
    
    # 99% CI Band
    fig.add_trace(go.Scatter(x=days, y=ci_99_upper, line=dict(width=0), showlegend=False, hoverinfo='skip'))
    fig.add_trace(go.Scatter(x=days, y=ci_99_lower, fill='tonexty', fillcolor='rgba(200, 200, 200, 0.2)', line=dict(width=0), name='99% CI'))
    
    # 95% CI Band
    fig.add_trace(go.Scatter(x=days, y=ci_95_upper, line=dict(width=0), showlegend=False, hoverinfo='skip'))
    fig.add_trace(go.Scatter(x=days, y=ci_95_lower, fill='tonexty', fillcolor='rgba(100, 150, 250, 0.2)', line=dict(width=0), name='95% CI'))
    
    # 68% CI Band
    fig.add_trace(go.Scatter(x=days, y=ci_68_upper, line=dict(width=0), showlegend=False, hoverinfo='skip'))
    fig.add_trace(go.Scatter(x=days, y=ci_68_lower, fill='tonexty', fillcolor='rgba(50, 100, 200, 0.4)', line=dict(width=0), name='68% CI'))

    # Historical Mean
    fig.add_trace(go.Scatter(x=days, y=base_curve, mode='lines', line=dict(color='black', width=3), name='30-Year Hist. Mean (LPA)'))
    
    # Current Year Simulated Trajectory (Up to day 45)
    current_day = 45
    current_traj = base_curve[:current_day] + (st.session_state.market_data['spot_cdr'] * np.linspace(0, 1, current_day))
    fig.add_trace(go.Scatter(x=np.arange(1, current_day+1), y=current_traj, mode='lines', line=dict(color='red', width=3, dash='dash'), name='Current Season Trajectory'))
    
    fig.update_layout(
        title="Predictive Cumulative Rainfall Matrix (Mumbai)",
        xaxis_title="Monsoon Day (Day 1 = June 1)",
        yaxis_title="Cumulative Rainfall (mm)",
        hovermode="x unified",
        template="plotly_white",
        height=500
    )
    st.plotly_chart(fig, use_container_width=True)

# ==========================================
# MODULE 6: SPATIAL BASIS RISK MAPPING (GIS SCOPE)
# ==========================================
with tab5:
    st.markdown("### Spatial Basis Risk & Infrastructure Geo-location")
    st.markdown("Evaluating locational mismatch between illiquid physical collateral and liquid benchmark indexes.")
    
    # Reference Weather Stations
    stations = [
        {'name': 'IMD Santacruz (Primary Index)', 'lat': 19.0856, 'lon': 72.8496, 'type': 'Station'},
        {'name': 'IMD Colaba (Secondary Index)', 'lat': 18.9067, 'lon': 72.8147, 'type': 'Station'}
    ]
    
    geo_data = stations.copy()
    for asset in st.session_state.portfolio:
        geo_data.append({
            'name': asset['deal_id'],
            'lat': asset['lat'],
            'lon': asset['lon'],
            'type': 'Asset Collateral'
        })
        
    df_geo = pd.DataFrame(geo_data)
    
    # Plotly Scatter Map (Using open-street-map, no token required)
    fig_map = px.scatter_mapbox(
        df_geo, lat="lat", lon="lon", hover_name="name", color="type",
        color_discrete_sequence=["red", "blue"], zoom=9, height=500
    )
    fig_map.update_layout(mapbox_style="open-street-map", margin={"r":0,"t":0,"l":0,"b":0})
    st.plotly_chart(fig_map, use_container_width=True)
    
    st.markdown("#### Geodesic Basis Risk Matrix")
    basis_risk_data = []
    santacruz = stations[0]
    colaba = stations[1]
    
    for asset in st.session_state.portfolio:
        dist_sc = haversine(asset['lon'], asset['lat'], santacruz['lon'], santacruz['lat'])
        dist_col = haversine(asset['lon'], asset['lat'], colaba['lon'], colaba['lat'])
        
        # Calculate a crude "basis risk score" based on distance (further = higher risk of local microclimate variations)
        risk_score = min(100.0, (min(dist_sc, dist_col) / 50.0) * 100) 
        
        basis_risk_data.append({
            'Asset Deal ID': asset['deal_id'],
            'Dist. to Santacruz (km)': f"{dist_sc:.2f}",
            'Dist. to Colaba (km)': f"{dist_col:.2f}",
            'Microclimate Basis Risk Score (0-100)': f"{risk_score:.1f}"
        })
        
    st.table(pd.DataFrame(basis_risk_data))