import streamlit as st
import pandas as pd
import requests
import pyotp
from SmartApi import SmartConnect
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="MCX Live Chart & OI Overlay", layout="wide")
st.title("📈 MCX Live Chart & Key Levels Overlay")

st_autorefresh(interval=1000, key="chart_refresh")

if "API_KEY" not in st.secrets:
    st.error("API_KEY missing")
    st.stop()

API_KEY = st.secrets["API_KEY"]
CLIENT_ID = st.secrets["CLIENT_ID"]
MPIN = st.secrets["MPIN"]
TOTP_SECRET = st.secrets["TOTP_SECRET"]

commodity = st.sidebar.radio("Select Commodity:", ["GOLDM", "SILVERM"], horizontal=True)

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

def fetch_levels():
    if not st.session_state.get('logged', False):
        return 0, 0, 0
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
                    oi = item.get('opnInterest', 0)
                    oi_list.append({"Strike": int(strike), "Type": opt_type, "OI": oi})
            if oi_list:
                rdf = pd.DataFrame(oi_list)
                ce = rdf[rdf['Type'] == 'CE'].groupby('Strike')['OI'].sum()
                pe = rdf[rdf['Type'] == 'PE'].groupby('Strike')['OI'].sum()
                
                m_ce = int(ce.idxmax()) if not ce.empty else 0
                m_pe = int(pe.idxmax()) if not pe.empty else 0
                pcr = round(pe.sum() / max(ce.sum(), 1), 2)
                return m_pe, m_ce, pcr
    except:
        pass
    return 0, 0, 0

support, resistance, pcr = fetch_levels()

st.markdown(f"### 📊 {commodity} ({nearest_expiry.strftime('%d %b %Y')}) Key Levels")
c1, c2, c3 = st.columns(3)
c1.metric("🛡️ Support (Max PE)", str(support))
c2.metric("🧱 Resistance (Max CE)", str(resistance))
c3.metric("📈 PCR Ratio", str(pcr))

st.markdown("---")

# यहाँ 100% काम करने वाले यूनिवर्सल स्पॉट सिंबल का उपयोग किया गया है
if commodity == "GOLDM":
    tv_url = "https://s.tradingview.com/widgetembed/?symbol=OANDA%3AXAUUSD&interval=D&hidesidetoolbar=0&symboledit=1&saveimage=1&toolbarbg=f1f3f6&studies=[]&theme=dark&style=1&timezone=Asia%2FKolkata&locale=in"
else:
    tv_url = "https://s.tradingview.com/widgetembed/?symbol=OANDA%3AXAGUSD&interval=D&hidesidetoolbar=0&symboledit=1&saveimage=1&toolbarbg=f1f3f6&studies=[]&theme=dark&style=1&timezone=Asia%2FKolkata&locale=in"

chart_html = f"""
<iframe src="{tv_url}" width="100%" height="550" frameborder="0" allowtransparency="true" scrolling="no"></iframe>
"""
st.components.v1.html(chart_html, height=570)
