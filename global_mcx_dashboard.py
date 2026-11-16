import streamlit as st
import pandas as pd
import requests
import pyotp
import yfinance as yf
from datetime import datetime, timedelta
from SmartApi import SmartConnect
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="Global & MCX Dashboard", layout="wide")
st.title("🌐 Global (OANDA/US) & MCX Signal Dashboard")

# ऑटो-रिफ्रेश (हर 5 सेकंड में डेटा अपडेट होगा)
st_autorefresh(interval=5000, key="dashboard_refresh")

if "API_KEY" not in st.secrets:
    st.error("API_KEY missing in Streamlit Secrets")
    st.stop()

API_KEY = st.secrets["API_KEY"]
CLIENT_ID = st.secrets["CLIENT_ID"]
MPIN = st.secrets["MPIN"]
TOTP_SECRET = st.secrets["TOTP_SECRET"]

# साइडबार कंट्रोल्स
commodity = st.sidebar.selectbox("Select Commodity:", ["GOLDM", "SILVERM"])

# 1. फ्री ग्लोबल (US / OANDA) डेटा फेच करना (बिना किसी API Key के)
@st.cache_data(ttl=30)
def get_global_prices(comm):
    try:
        # Yahoo Finance symbols for Gold and Silver
        ticker_symbol = "GC=F" if comm == "GOLDM" else "SI=F"
        data = yf.Ticker(ticker_symbol)
        hist = data.history(period="1d", interval="1m")
        if not hist.empty:
            current_price = float(hist['Close'].iloc[-1])
            prev_close = float(data.info.get('previousClose', current_price))
            change = current_price - prev_close
            pct_change = (change / prev_close) * 100
            return current_price, change, pct_change
    except:
        pass
    return 0.0, 0.0, 0.0

global_price, g_change, g_pct = get_global_prices(commodity)

# 2. एंजेल वन मास्टर डेटा (MCX के लिए)
@st.cache_data(ttl=600)
def get_mcx_master(comm):
    try:
        url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
        res = requests.get(url, timeout=10)
        df = pd.DataFrame(res.json())
        
        inst_fut = df[(df['exch_seg'] == 'MCX') & (df['instrumenttype'] == 'FUTCOM')]
        cdf_fut = inst_fut[inst_fut['name'] == comm].copy()
        cdf_fut['expiry_dt'] = pd.to_datetime(cdf_fut['expiry'])
        ne = cdf_fut['expiry_dt'].min()
        row_fut = cdf_fut[cdf_fut['expiry_dt'] == ne].iloc[0]
        
        inst_opt = df[(df['exch_seg'] == 'MCX') & (df['instrumenttype'] == 'OPTFUT')]
        cdf_opt = inst_opt[inst_opt['name'] == comm].copy()
        cdf_opt['expiry_dt'] = pd.to_datetime(cdf_opt['expiry'])
        opt_df = cdf_opt[cdf_opt['expiry_dt'] == ne]
        
        return row_fut['token'], row_fut['symbol'], opt_df
    except:
        return None, None, pd.DataFrame()

fut_token, fut_symbol, active_options = get_mcx_master(commodity)

# सेशन लॉगिन
if 'smart_obj' not in st.session_state:
    try:
        obj = SmartConnect(api_key=API_KEY)
        totp = pyotp.TOTP(TOTP_SECRET).now()
        l = obj.generateSession(CLIENT_ID, MPIN, totp)
        if l and l.get('status'):
            st.session_state['smart_obj'] = obj
            st.session_state['logged'] = True
        else:
            st.session_state['logged'] = False
    except:
        st.session_state['logged'] = False

# MCX डेटा और ऑप्शन चेन फेच करना
def fetch_mcx_data():
    if not st.session_state.get('logged', False) or not fut_token:
        return 0, 0, 0, 0, pd.DataFrame()
    
    obj = st.session_state['smart_obj']
    spot_price = 0
    support, resistance, pcr = 0, 0, 0
    oi_table = pd.DataFrame()

    try:
        # फ्यूचर्स LTP के लिए
        ltp_data = obj.ltpData("MCX", fut_symbol, fut_token)
        if ltp_data and ltp_data.get('status'):
            spot_price = float(ltp_data['data']['ltp'])

        # ऑप्शन चेन डेटा
        if not active_options.empty:
            tokens = active_options['token'].tolist()[:100]
            md = obj.getMarketData("FULL", {"MCX": tokens})
            if md and md.get('status'):
                fetched = md['data']['fetched']
                records = []
                for item in fetched:
                    sym = item.get('tradingSymbol', '')
                    tval = item.get('symbolToken', '')
                    srow = active_options[active_options['token'] == tval]
                    if not srow.empty:
                        strike = float(srow['strike'].values[0]) / 100
                        opt_type = "CE" if sym.endswith("CE") else "PE"
                        oi = item.get('opnInterest', 0)
                        ltp = item.get('ltp', 0)
                        records.append({"Strike": strike, "Type": opt_type, "OI": oi, "LTP": ltp})
                
                if records:
                    rdf = pd.DataFrame(records)
                    ce_df = rdf[rdf['Type'] == 'CE'].set_index('Strike')['OI']
                    pe_df = rdf[rdf['Type'] == 'PE'].set_index('Strike')['OI']
                    combined = pd.DataFrame({'Call OI': ce_df, 'Put OI': pe_df}).fillna(0).reset_index()
                    
                    support = int(pe_df.idxmax()) if not pe_df.empty else 0
                    resistance = int(ce_df.idxmax()) if not ce_df.empty else 0
                    pcr = round(pe_df.sum() / max(ce_df.sum(), 1), 2)
                    oi_table = combined.sort_values(by='Strike')
    except:
        pass

    return spot_price, support, resistance, pcr, oi_table

mcx_price, support, resistance, pcr, oi_table = fetch_mcx_data()

# --- UI DISPLAY (App.py Style) ---

st.subheader(f"🌍 Global / US Market ({commodity})")
gc1, gc2 = st.columns(2)
gc1.metric("US Live Price (USD)", f"${global_price:,.2f}" if global_price else "Loading...", f"{g_change:+.2f} ({g_pct:+.2f}%)")

st.markdown("---")

st.subheader(f"🇮🇳 MCX Market Overview ({fut_symbol if fut_symbol else commodity})")
mc1, mc2, mc3, mc4 = st.columns(4)
mc1.metric("MCX Live Price", f"₹ {mcx_price:,.2f}" if mcx_price else "Loading...")
mc2.metric("🛡️ Support (Max PE OI)", f"₹ {support}" if support else "Calculating...")
mc3.metric("🧱 Resistance (Max CE OI)", f"₹ {resistance}" if resistance else "Calculating...")
mc4.metric("📊 PCR Ratio", str(pcr))

# सिग्नल इंडिकेटर
st.markdown("### 🚦 Market Signal Analysis")
if pcr > 1.2:
    st.success("🟢 **Bullish Signal:** PCR बहुत मजबूत है (Put OI अधिक है), मार्केट ऊपर की तरफ इशारा कर रहा है।")
elif pcr < 0.8 and pcr > 0:
    st.error("🔴 **Bearish Signal:** PCR कमजोर है (Call OI भारी है),ि दबाव देखने को मिल सकता है।")
else:
    st.info("⚪ **Neutral Signal:** बाजार अभी साइडवेज या स्थिर है।")

st.markdown("---")

st.subheader("📊 Strike Price & Open Interest Table")
if not oi_table.empty and mcx_price > 0:
    display_df = oi_table.copy()
    display_df['Call Moneyness'] = display_df['Strike'].apply(lambda x: 'ITM' if x < mcx_price else ('ATM' if abs(x - mcx_price) < 100 else 'OTM'))
    display_df['Put Moneyness'] = display_df['Strike'].apply(lambda x: 'ITM' if x > mcx_price else ('ATM' if abs(x - mcx_price) < 100 else 'OTM'))
    
    st.dataframe(display_df[['Strike', 'Call OI', 'Call Moneyness', 'Put OI', 'Put Moneyness']], use_container_width=True)
else:
    st.info("🔄 ऑप्शन चेन और स्ट्राइक डेटा लोड हो रहा है...")
