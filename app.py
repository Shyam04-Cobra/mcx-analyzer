import streamlit as st
import pandas as pd
import requests
import pyotp
from SmartApi import SmartConnect

st.set_page_config(page_title="MCX Live Analyzer", page_icon="🪙", layout="centered")
st.title("MCX Gold & Silver Mini Analyzer")

API_KEY = st.secrets["API_KEY"]
CLIENT_ID = st.secrets["CLIENT_ID"]
MPIN = st.secrets["MPIN"]
TOTP_SECRET = st.secrets["TOTP_SECRET"]

commodity = st.radio("कमोडिटी चुनें:", ["GOLDM", "SILVERM"], horizontal=True)

@st.cache_data(ttl=3600)
def get_mcx_instruments():
    url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
    data = requests.get(url).json()
    df = pd.DataFrame(data)
    return df[(df['exch_seg'] == 'MCX') & (df['instrumenttype'] == 'OPTFUT')]

if st.button("लाइव ऑप्शन डेटा अपडेट करें", use_container_width=True):
    with st.spinner("Angel One से डेटा आ रहा है..."):
        try:
            obj = SmartConnect(api_key=API_KEY)
            totp = pyotp.TOTP(TOTP_SECRET).now()
            login = obj.generateSession(CLIENT_ID, MPIN, totp)
            
            if not login['status']:
                st.error("लॉगिन विफल!")
            else:
                inst_df = get_mcx_instruments()
                comm_df = inst_df[inst_df['name'] == commodity].copy()
                comm_df['expiry_dt'] = pd.to_datetime(comm_df['expiry'])
                nearest_expiry = comm_df['expiry_dt'].min()
                active_options = comm_df[comm_df['expiry_dt'] == nearest_expiry]
                
                st.caption(f"Expiry: {nearest_expiry.strftime('%d %b %Y')}")
                
                tokens = active_options['token'].tolist()[:50]
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
                    ce_df = res_df[res_df['Type'] == 'CE'].set_index('Strike')
                    pe_df = res_df[res_df['Type'] == 'Ref'].set_index('Strike') if 'Ref' in res_df['Type'].values else res_df[res_df['Type'] == 'PE'].set_index('Strike')
                    
                    chain = pd.DataFrame({
                        "CE_OI": ce_df['OI'],
                        "CE_LTP": ce_df['LTP'],
                        "PE_LTP": pe_df['LTP'],
                        "PE_OI": pe_df['OI']
                    }).fillna(0).sort_index()
                    
                    max_ce_strike = chain['CE_OI'].idxmax()
                    max_pe_strike = chain['PE_OI'].idxmax()
                    total_ce = chain['CE_OI'].sum()
                    total_pe = chain['PE_OI'].sum()
                    pcr = round(total_pe / max(total_ce, 1), 2)
                    
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Support Level", f"₹ {max_pe_strike:,}")
                    c2.metric("Resistance Level", f"₹ {max_ce_strike:,}")
                    c3.metric("PCR Ratio", pcr)
                    
                    st.markdown("---")
                    if pcr > 1.2:
                        st.success("Strong Bullish (Put writing is high)")
                    elif pcr < 0.8:
                        st.error("Strong Bearish (Call writers dominating)")
                    else:
                        st.w
