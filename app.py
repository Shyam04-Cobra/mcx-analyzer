import streamlit as st
import pandas as pd
import requests
import pyotp
from SmartApi import SmartConnect
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="MCX 1-Sec Live Analyzer", layout="wide")
st.title("⚡ MCX Real-Time 1-Second Option Analyzer")

st_autorefresh(interval=1000, key="mcx_1sec_refresh")

if "API_KEY" not in st.secrets:
    st.error("कृपया Streamlit Secrets में API_KEY सेट करें।")
    st.stop()

API_KEY = st.secrets["API_KEY"]
CLIENT_ID = st.secrets["CLIENT_ID"]
MPIN = st.secrets["MPIN"]
TOTP_SECRET = st.secrets["TOTP_SECRET"]

commodity = st.radio("Select Commodity:", ["GOLDM", "SILVERM"], horizontal=True)

@st.cache_data(ttl=600)
def get_scrip_master(comm):
    try:
        url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
        response = requests.get(url, timeout=10)
        data = response.json()
        df = pd.DataFrame(data)
        inst_df = df[(df['exch_seg'] == 'MCX') & (df['instrumenttype'] == 'OPTFUT')]
        comm_df = inst_df[inst_df['name'] == comm].copy()
        comm_df['expiry_dt'] = pd.to_datetime(comm_df['expiry'])
        nearest_expiry = comm_df['expiry_dt'].min()
        active_options = comm_df[comm_df['expiry_dt'] == nearest_expiry]
        return active_options, nearest_expiry
    except Exception as e:
        return None, None

active_options, nearest_expiry = get_scrip_master(commodity)

if active_options is None or active_options.empty:
    st.warning("⚠️ स्क्रिप्ट मास्टर डेटा लोड करने में समस्या।")
    st.stop()

st.caption(f"📅 Active Expiry: {nearest_expiry.strftime('%d %b %Y')} | ⚡ Live Refresh: Every 1 Second")

if 'smart_obj' not in st.session_state or 'logged_in' not in st.session_state:
    try:
        obj = SmartConnect(api_key=API_KEY)
        totp = pyotp.TOTP(TOTP_SECRET).now()
        login = obj.generateSession(CLIENT_ID, MPIN, totp)
        if login and login.get('status'):
            st.session_state['smart_obj'] = obj
            st.session_state['logged_in'] = True
        else:
            st.session_state['logged_in'] = False
    except Exception as e:
        st.session_state['logged_in'] = False

if not st.session_state.get('logged_in', False):
    st.info("ℹ️ आज वीकेंड (रविवार) है या मार्केट बंद है, इसलिए लॉगिन सेशन स्थापित नहीं हो पा रहा है। सोमवार को मार्केट खुलते ही यह स्वतः काम करने लगेगा।")
else:
    obj = st.session_state['smart_obj']
    try:
        tokens = active_options['token'].tolist()[:80]
        market_data = obj.getMarketData("FULL", {"MCX": tokens})
        
        if market_data and market_data.get('status'):
            fetched = market_data['data']['fetched']
            oi_list = []
            
            for item in fetched:
                sym = item.get('tradingSymbol', '')
                token_val = item.get('symbolToken', '')
                strike_row = active_options[active_options['token'] == token_val]
                if not strike_row.empty:
                    strike = float(strike_row['strike'].values[0]) / 100
                    
                    if sym.endswith("CE"):
                        opt_type = "CE"
                    else:
                        opt_type = "PE"
                        
                    ltp = item.get('ltp', 0)
                    oi = item.get('opnInterest', 0)
                    oi_list.append({"Strike": int(strike), "Type": opt_type, "OI": oi, "LTP": ltp})
            
            if oi_list:
                res_df = pd.DataFrame(oi_list)
                
                ce_sub = res_df[res_df['Type'] == 'CE'].groupby('Strike')[['OI', 'LTP']].sum()
                ce_df = ce_sub.rename(columns={'OI': 'CE_OI', 'LTP': 'CE_LTP'})
                
                pe_sub = res_
