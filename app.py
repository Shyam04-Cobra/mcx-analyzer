import streamlit as st
import pandas as pd
import requests
import pyotp
from SmartApi import SmartConnect

st.set_page_config(page_title="MCX Live Analyzer", layout="wide")
st.title("🚀 MCX Advanced Option & Volatility Analyzer")

# सीक्रेट्स लोड करें
try:
    API_KEY = st.secrets["API_KEY"]
    CLIENT_ID = st.secrets["CLIENT_ID"]
    MPIN = st.secrets["MPIN"]
    TOTP_SECRET = st.secrets["TOTP_SECRET"]
except:
    st.error("कृपया Streamlit Secrets में API_KEY, CLIENT_ID, MPIN और TOTP_SECRET सेट करें।")
    st.stop()

commodity = st.radio("Select Commodity:", ["GOLDM", "SILVERM"], horizontal=True)

if st.button("Update Data & Analyze"):
    try:
        obj = SmartConnect(api_key=API_KEY)
        totp = pyotp.TOTP(TOTP_SECRET).now()
        login = obj.generateSession(CLIENT_ID, MPIN, totp)
        
        if not login['status']:
            st.error("Angel One Login Failed! कृपया क्रेडेंशियल्स चेक करें।")
        else:
            url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
            data = requests.get(url).json()
            df = pd.DataFrame(data)
            inst_df = df[(df['exch_seg'] == 'MCX') & (df['instrumenttype'] == 'OPTFUT')]
            
            comm_df = inst_df[inst_df['name'] == commodity].copy()
            comm_df['expiry_dt'] = pd.to_datetime(comm_df['expiry'])
            nearest_expiry = comm_df['expiry_dt'].min()
            active_options = comm_df[comm_df['expiry_dt'] == nearest_expiry]
            
            st.info(f"📅 Active Expiry: {nearest_expiry.strftime('%d %b %Y')}")
            tokens = active_options['token'].tolist()[:80]
            
            market_data = obj.getMarketData("FULL", {"MCX": tokens})
            if market_data['status']:
                fetched = market_data['data']['fetched']
                oi_list = []
                underlying_price = 0
                
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
                    ce_df = res_df[res_df['Type'] == 'CE'].groupby('Strike').agg({'OI': 'sum', 'LTP': 'mean'})
                    pe_df = res_df[res_df['Type'] == 'PE'].groupby('Strike').agg({'OI': 'sum', 'LTP': 'mean'})
                    
                    chain = pd.DataFrame({
                        "CE_OI": ce_df['OI'],
                        "CE_LTP": ce_df['LTP'],
                        "PE_LTP": pe_df['LTP'],
                        "PE_OI": pe_df['OI']
                    }).fillna(0).sort_index()
                    
                    # अंडरलाइंग या एटीएम स्ट्राइक का अनुमान (जहाँ कुल OI एक्टिविटी सबसे ज्यादा है या औसत स्ट्राइक)
                    total_ce = chain['CE_OI'].sum()
                    total_pe = chain['PE_OI'].sum()
                    pcr = round(total_pe / max(total_ce, 1), 2)
                    
                    max_ce_strike = chain['CE_OI'].idxmax() if not chain.empty else 0
                    max_pe_strike = chain['PE_OI'].idxmax() if not chain.empty else 0
