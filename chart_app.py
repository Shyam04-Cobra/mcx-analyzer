import streamlit as st
import pandas as pd
import requests
import pyotp
from datetime import datetime, timedelta
from SmartApi import SmartConnect
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="MCX Live Chart & OI Overlay", layout="wide")
st.title("📈 MCX Live Price & OI Analyzer")

st_autorefresh(interval=5000, key="chart_refresh")

if "API_KEY" not in st.secrets:
    st.error("API_KEY missing in Streamlit Secrets")
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
        inst = df[(df['exch_seg'] == 'MCX') & (df['instrumenttype'] == 'FUTCOM')]
        cdf = inst[inst['name'] == comm].copy()
        cdf['expiry_dt'] = pd.to_datetime(cdf['expiry'])
        ne = cdf['expiry_dt'].min()
        row = cdf[cdf['expiry_dt'] == ne].iloc[0]
        return row['token'], row['symbol'], ne
    except:
        return None, None, None

fut_token, fut_symbol, nearest_expiry = get_master(commodity)

@st.cache_data(ttl=600)
def get_opt_master(comm):
    try:
        url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
        res = requests.get(url, timeout=10)
        df = pd.DataFrame(res.json())
        inst = df[(df['exch_seg'] == 'MCX') & (df['instrumenttype'] == 'OPTFUT')]
        cdf = inst[inst['name'] == comm].copy()
        cdf['expiry_dt'] = pd.to_datetime(cdf['expiry'])
        ne = cdf['expiry_dt'].min()
        return cdf[cdf['expiry_dt'] == ne]
    except:
        return None

active_options = get_opt_master(commodity)

if not fut_token:
    st.warning("⚠️ कमोडिटी मास्टर डेटा लोड हो रहा है...")
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

def fetch_levels_and_chart():
    if not st.session_state.get('logged', False):
        return 0, 0, 0, pd.DataFrame()
    
    obj = st.session_state['smart_obj']
    support, resistance, pcr = 0, 0, 0
    df_chart = pd.DataFrame()

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
                support = int(pe.idxmax()) if not pe.empty else 0
                resistance = int(ce.idxmax()) if not ce.empty else 0
                pcr = round(pe.sum() / max(ce.sum(), 1), 2)

        to_date = datetime.now().strftime("%Y-%m-%d %H:%M")
        from_date = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d %H:%M")
        
        hist_params = {
            "exchange": "MCX",
            "symboltoken": fut_token,
            "interval": "FIVE_MINUTE",
            "fromdate": from_date,
            "todate": to_date
        }
        hist_data = obj.getCandleData(hist_params)
        if hist_data and hist_data.get('status') and hist_data.get('data'):
            raw_candles = hist_data['data']
            df_chart = pd.DataFrame(raw_candles, columns=['Datetime', 'Open', 'High', 'Low', 'Close', 'Volume'])
            df_chart['Datetime'] = pd.to_datetime(df_chart['Datetime'])
            df_chart.set_index('Datetime', inplace=True)
            df_chart = df_chart[['Close']]
    except Exception as e:
        pass

    return support, resistance, pcr, df_chart

support, resistance, pcr, chart_df = fetch_levels_and_chart()

st.markdown(f"### 📊 MCX {commodity} ({fut_symbol}) Key Levels")
c1, c2, c3 = st.columns(3)
c1.metric("🛡️ Support (Max PE)", str(support))
c2.metric("🧱 Resistance (Max CE)", str(resistance))
c3.metric("📈 PCR Ratio", str(pcr))

st.markdown("---")
st.subheader(f"📉 MCX {commodity} Live Price Trend (INR)")

if not chart_df.empty:
    st.line_chart(chart_df, height=450)
else:
    st.info("🔄 Angel One से MCX लाइव चार्ट डेटा लोड हो रहा है...")
