import streamlit as st
import pandas as pd
import requests
import pyotp
from SmartApi import SmartConnect

st.set_page_config(page_title="MCX Live Analyzer", layout="wide")
st.title("MCX Advanced Option Analyzer")

try:
    API_KEY = st.secrets["API_KEY"]
    CLIENT_ID = st.secrets["CLIENT_ID"]
    MPIN = st.secrets["MPIN"]
    TOTP_SECRET = st.secrets["TOTP_SECRET"]
except:
    st.error("कृपया Streamlit Secrets में सही क्रेडेंशियल्स सेट करें।")
    st.stop()

commodity = st.radio("Select Commodity:", ["GOLDM", "SILVERM"], horizontal=True)

if st.button("Update Data & Analyze"):
    try:
        obj = SmartConnect(api_key=API_KEY)
        totp = pyotp.TOTP(TOTP_SECRET).now()
        login = obj.generateSession(CLIENT_ID, MPIN, totp)
        
        if not login['status']:
            st.error("Angel One Login Failed!")
        else:
            url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
            data = requests.get(url).json()
            df = pd.DataFrame(data)
            inst_df = df[(df['exch_seg'] == 'MCX') & (df['instrumenttype'] == 'OPTFUT')]
            
            comm_df = inst_df[inst_df['name'] == commodity].copy()
            comm_df['expiry_dt'] = pd.to_datetime(comm_df['expiry'])
            nearest_expiry = comm_df['expiry_dt'].min()
            active_options = comm_df[comm_df['expiry_dt'] == nearest_expiry]
            
            st.info(f"Active Expiry: {nearest_expiry.strftime('%d %b %Y')}")
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
                    
                    chain = pd.concat([ce_df, pe_
