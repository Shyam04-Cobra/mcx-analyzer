import streamlit as st
import pandas as pd
import requests
import pyotp
from SmartApi import SmartConnect

st.set_page_config(page_title="MCX Live Analyzer", layout="centered")
st.title("MCX Analyzer")

API_KEY = st.secrets["API_KEY"]
CLIENT_ID = st.secrets["CLIENT_ID"]
MPIN = st.secrets["MPIN"]
TOTP_SECRET = st.secrets["TOTP_SECRET"]

commodity = st.radio("Select Commodity:", ["GOLDM", "SILVERM"], horizontal=True)

if st.button("Update Data"):
    try:
        obj = SmartConnect(api_key=API_KEY)
        totp = pyotp.TOTP(TOTP_SECRET).now()
        login = obj.generateSession(CLIENT_ID, MPIN, totp)
        
        if not login['status']:
            st.error("Login Failed!")
        else:
            url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
            data = requests.get(url).json()
            df = pd.DataFrame(data)
            inst_df = df[(df['exch_seg'] == 'MCX') & (df['instrumenttype'] == 'OPTFUT')]
            
            comm_df = inst_df[inst_df['name'] == commodity].copy()
            comm_df['expiry_dt'] = pd.to_datetime(comm_df['expiry'])
            nearest_expiry = comm_df['expiry_dt'].min()
            active_options = comm_df[comm_df['expiry_dt'] == nearest_expiry]
            
            st.write(f"Expiry: {nearest_expiry.strftime('%d %b %Y')}")
            tokens = active_options['token'].tolist()[:30]
            
            market_data = obj.getMarketData("FULL", {"MCX": tokens})
            if market_data['status']:
                fetched = market_data['data']['fetched']
                oi_list = []
                for item in fetched:
                    sym = item['tradingSymbol']
                    strike = float(active_options[active_options['token'] == item['symbolToken']]['strike'].values[0]) / 100
                    opt_type = "CE" if sym.endswith("CE") else "PE"
                    oi_list.append({
                        "Strike": int(strike),
                        "Type": opt_type,
                        "OI": item.get('opnInterest', 0),
                        "LTP": item.get('ltp', 0)
                    })
                
                res_df = pd.DataFrame(oi_list)
                st.dataframe(res_df, use_container_width=True)
    except Exception as e:
        st.error(f"Error: {e}")
