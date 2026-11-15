import streamlit as st
import pandas as pd
import requests
import pyotp
from SmartApi import SmartConnect
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="MCX Analyzer", layout="wide")
st.title("⚡ MCX Real-Time Analyzer")

st_autorefresh(interval=1000, key="refresh")

if "API_KEY" not in st.secrets:
    st.error("API_KEY missing")
    st.stop()

API_KEY = st.secrets["API_KEY"]
CLIENT_ID = st.secrets["CLIENT_ID"]
MPIN = st.secrets["MPIN"]
TOTP_SECRET = st.secrets["TOTP_SECRET"]

commodity = st.radio("Commodity:", ["GOLDM", "SILVERM"], horizontal=True)

@st.cache_data(ttl=600)
def get_master(comm):
    try:
        url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
        res = requests.get(url, timeout=10)
        df = pd.DataFrame(res.json())
        inst = df[(df['exch_seg'] == 'MCX') & (df['instrumenttype'] == 'OPTFUT')]
        cdf = inst[inst['name'] == comm].copy()
        cdf['expiry_dt'] = pd.to_datetime(cdf['expiry'])
        ne = cdf['expiry_dt'].min()
        return cdf[cdf['expiry_dt'] == ne], ne
    except:
        return None, None

active_options, nearest_expiry = get_master(commodity)

if active_options is None or active_options.empty:
    st.warning("⚠️ डेटा लोड हो रहा है...")
    st.stop()

st.caption(f"Expiry: {nearest_expiry.strftime('%d %b %Y')} | Live")

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

if not st.session_state.get('logged', False):
    st.info("ℹ️ मार्केट बंद है या लॉगिन प्रतीक्षारत है।")
else:
    obj = st.session_state['smart_obj']
    try:
        tokens = active_options['token'].tolist()[:80]
        md = obj.getMarketData("FULL", {"MCX": tokens})
        
        if md and md.get('status'):
            fetched = md['data']['fetched']
            oi_list = []
            for item in fetched:
                sym = item.get('tradingSymbol', '')
                tval = item.get('symbolToken', '')
                srow = active_options[active_options['token'] == tval]
                if not srow.empty:
                    strike = float(srow['strike'].values[0]) / 100
                    opt_type = "CE" if sym.endswith("CE") else "PE"
                    ltp = item.get('ltp', 0)
                    oi = item.get('opnInterest', 0)
                    oi_list.append({"Strike": int(strike), "Type": opt_type, "OI": oi, "LTP": ltp})
            
            if oi_list:
                rdf = pd.DataFrame(oi_list)
                ce = rdf[rdf['Type'] == 'CE'].groupby('Strike')[['OI', 'LTP']].sum()
                ce = ce.rename(columns={'OI': 'CE_OI', 'LTP': 'CE_LTP'})
                pe = rdf[rdf['Type'] == 'PE'].groupby('Strike')[['OI', 'LTP']].sum()
                pe = pe.rename(columns={'OI': 'PE_OI', 'LTP': 'PE_LTP'})
                chain = pd.concat([ce, pe], axis=1).fillna(0).sort_index()
                
                t_ce = chain['CE_OI'].sum() if 'CE_OI' in chain.columns else 1
                t_pe = chain['PE_OI'].sum() if 'PE_OI' in chain.columns else 0
                pcr = round(t_pe / max(t_ce, 1), 2)
                
                m_ce = int(chain['CE_OI'].idxmax()) if 'CE_OI' in chain.columns and not chain.empty else 0
                m_pe = int(chain['PE_OI'].idxmax()) if 'PE_OI' in chain.columns and not chain.empty else 0
                
                bias = "BULLISH" if pcr > 1.15 else ("BEARISH" if pcr < 0.85 else "SIDEWAYS")
                
                st.markdown("### 📊 Dashboard")
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Support", str(m_pe))
                c2.met
