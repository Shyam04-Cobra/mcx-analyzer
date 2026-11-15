import streamlit as st
import pandas as pd
import requests
import pyotp
from SmartApi import SmartConnect
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="MCX 1-Sec Live Analyzer", layout="wide")
st.title("⚡ MCX Real-Time 1-Second Option Analyzer")

# हर 1 सेकंड (1000 मिलीसेकंड) में ऑटो-रिफ्रेश
st_autorefresh(interval=1000, key="mcx_1sec_refresh")

# क्रेडेंशियल्स की जांच
try:
    API_KEY = st.secrets["API_KEY"]
    CLIENT_ID = st.secrets["CLIENT_ID"]
    MPIN = st.secrets["MPIN"]
    TOTP_SECRET = st.secrets["TOTP_SECRET"]
except:
    st.error("कृपया Streamlit Secrets में API_KEY, CLIENT_ID, MPIN और TOTP_SECRET सेट करें।")
    st.stop()

commodity = st.radio("Select Commodity:", ["GOLDM", "SILVERM"], horizontal=True)

# स्क्रिप्ट मास्टर फेच करने का कैश्ड फंक्शन (ताकि बार-बार लोड न हो)
@st.cache_data(ttl=600)
def get_scrip_master(comm):
    url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
    data = requests.get(url).json()
    df = pd.DataFrame(data)
    inst_df = df[(df['exch_seg'] == 'MCX') & (df['instrumenttype'] == 'OPTFUT')]
    comm_df = inst_df[inst_df['name'] == comm].copy()
    comm_df['expiry_dt'] = pd.to_datetime(comm_df['expiry'])
    nearest_expiry = comm_df['expiry_dt'].min()
    active_options = comm_df[comm_df['expiry_dt'] == nearest_expiry]
    return active_options, nearest_expiry

active_options, nearest_expiry = get_scrip_master(commodity)
st.caption(f"📅 Active Expiry: {nearest_expiry.strftime('%d %b %Y')} | ⚡ Live Refresh: Every 1 Second")

# बिना किसी बटन के हर सेकंड लाइव डेटा फेच और अपडेट होगा
try:
    obj = SmartConnect(api_key=API_KEY)
    totp = pyotp.TOTP(TOTP_SECRET).now()
    login = obj.generateSession(CLIENT_ID, MPIN, totp)
    
    if not login['status']:
        st.error("Angel One Login Failed! कृपया क्रेडेंशियल्स चेक करें।")
    else:
        tokens = active_options['token'].tolist()[:80]
        market_data = obj.getMarketData("FULL", {"MCX": tokens})
        
        if market_data['status']:
            fetched = market_data['data']['fetched']
            oi_list = []
            
            for item in fetched:
                sym = item['tradingSymbol']
                token_val = item['symbolToken']
                strike_row = active_options[active_options['token'] == token_val]
                if not strike_row.empty:
                    strike = float(strike_row['strike'].values[0]) / 100
                    opt_type = "CE" if sym.endswith("CE") else "PE"
                    ltp = item.get('ltp', 0)
                    oi = item.get('opnInterest', 0)
                    
                    oi_list.append({
                        "Strike": int(strike),
                        "Type": opt_type,
                        "OI": oi,
                        "LTP": ltp
                    })
            
            if oi_list:
                res_df = pd.DataFrame(oi_list)
                ce_df = res_df[res_df['Type'] == 'CE'].groupby('Strike').agg({'OI': 'CE_OI', 'LTP': 'CE_LTP'})
                pe_df = res_df[res_df['Type'] == 'PE'].groupby('Strike').agg({'OI': 'PE_OI', 'LTP': 'PE_LTP'})
                
                chain = pd.concat([ce_df, pe_df], axis=1).fillna(0).sort_index()
                
                total_ce = chain['CE_OI'].sum() if 'CE_OI' in chain.columns else 1
                total_pe = chain['PE_OI'].sum() if 'PE_OI' in chain.columns else 0
                pcr = round(total_pe / max(total_ce, 1), 2)
                
                if not chain.empty and 'CE_OI' in chain.columns and 'PE_OI' in chain.columns:
                    max_ce_strike = int(chain['CE_OI'].idxmax())
                    max_pe_strike = int(
