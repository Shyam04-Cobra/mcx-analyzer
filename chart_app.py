import streamlit as st
import pandas as pd
import requests
import pyotp
from datetime import datetime, timedelta
from SmartApi import SmartConnect
from streamlit_autorefresh import st_autorefresh
import plotly.graph_objects as go

st.set_page_config(page_title="MCX Ultra-Fast Live Candlestick Analyzer", layout="wide")
st.title("⚡ MCX 1-Sec Live Candlestick & Multi-Timeframe Analyzer")

# ऑटो-रिफ्रेश (अब यह हर 1 सेकंड में रिफ्रेश होगा)
st_autorefresh(interval=1000, key="ultra_fast_refresh")

if "API_KEY" not in st.secrets:
    st.error("API_KEY missing in Streamlit Secrets")
    st.stop()

API_KEY = st.secrets["API_KEY"]
CLIENT_ID = st.secrets["CLIENT_ID"]
MPIN = st.secrets["MPIN"]
TOTP_SECRET = st.secrets["TOTP_SECRET"]

# साइडबार कंट्रोल्स (1 मिनट से लेकर 1 दिन तक के सारे टाइमफ्रेम)
commodity = st.sidebar.selectbox("Select Commodity:", ["GOLDM", "SILVERM", "COPPER", "CRUDEOIL"])

timeframe_map = {
    "1 Second (Tick-based)": "ONE_MINUTE",  # एंजेल वन API न्यूनतम ONE_MINUTE सपोर्ट करता है
    "1 Minute": "ONE_MINUTE",
    "3 Minute": "THREE_MINUTE",
    "5 Minute": "FIVE_MINUTE",
    "15 Minute": "FIFTEEN_MINUTE",
    "30 Minute": "THIRTY_MINUTE",
    "1 Hour": "ONE_HOUR",
    "1 Day": "ONE_DAY"
}

selected_tf_label = st.sidebar.selectbox("Select Timeframe:", list(timeframe_map.keys()), index=1)
selected_tf = timeframe_map[selected_tf_label]

# मास्टर डेटा फेच करना
@st.cache_data(ttl=600)
def get_master(comm):
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
        
        return row_fut['token'], row_fut['symbol'], ne, opt_df
    except Exception as e:
        return None, None, None, pd.DataFrame()

fut_token, fut_symbol, nearest_expiry, active_options = get_master(commodity)

if not fut_token:
    st.warning("⚠️ मास्टर डेटा लोड हो रहा है...")
    st.stop()

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

def fetch_market_data():
    if not st.session_state.get('logged', False):
        return 0, pd.DataFrame(), pd.DataFrame(), 0, 0, 50
    
    obj = st.session_state['smart_obj']
    spot_price = 0
    df_chart = pd.DataFrame()
    oi_table = pd.DataFrame()
    support, resistance, pcr = 0, 0, 0

    try:
        to_date = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        # यदि 1 Day चुना है, तो पीछे का डेटा अधिक दिनों का होना चाहिए ताकि कैंडल सही दिखें
        days_back = 30 if selected_tf == "ONE_DAY" else 5
        from_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d %H:%M")
        
        hist_data = obj.getCandleData({
            "exchange": "MCX",
            "symboltoken": fut_token,
            "interval": selected_tf,
            "fromdate": from_date,
            "todate": to_date
        })
        
        if hist_data and hist_data.get('status') and hist_data.get('data'):
            raw = hist_data['data']
            df_chart = pd.DataFrame(raw, columns=['Datetime', 'Open', 'High', 'Low', 'Close', 'Volume'])
            df_chart['Datetime'] = pd.to_datetime(df_chart['Datetime'])
            spot_price = float(df_chart['Close'].iloc[-1])

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
                    
                    if spot_price > 0:
                        support = int(pe_df.idxmax()) if not pe_df.empty else 0
                        resistance = int(ce_df.idxmax()) if not ce_df.empty else 0
                        pcr = round(pe_df.sum() / max(ce_df.sum(), 1), 2)
                        oi_table = combined.sort_values(by='Strike')
    except Exception as e:
        pass

    return spot_price, df_chart, oi_table, support, resistance, pcr

spot_price, chart_df, oi_table, support, resistance, pcr = fetch_market_data()

# डैशबोर्ड लेवल्स
st.markdown(f"### 🎯 MCX {commodity} ({fut_symbol}) Live Dashboard")
col1, col2, col3, col4 = st.columns(4)
col1.metric("💰 Current Price", f"₹ {spot_price:,.2f}" if spot_price else "Loading...")
col2.metric("🛡️ Support (Max PE)", f"₹ {support}" if support else "Calculating...")
col3.metric("🧱 Resistance (Max CE)", f"₹ {resistance}" if resistance else "Calculating...")
col4.metric("📊 PCR Ratio", str(pcr))

st.markdown("---")

# प्लॉटली कैंडलस्टिक चार्ट (हर टाइमफ्रेम के लिए)
st.subheader(f"🕯️ Live Candlestick Chart ({selected_tf_label})")
if not chart_df.empty:
    fig = go.Figure(data=[go.Candlestick(
        x=chart_df['Datetime'],
        open=chart_df['Open'],
        high=chart_df['High'],
        low=chart_df['Low'],
        close=chart_df['Close'],
        increasing_line_color='#26a69a', 
        decreasing_line_color='#ef5350'
    )])
    
    fig.update_layout(
        xaxis_title='Time / Date',
        yaxis_title='Price (INR)',
        height=520,
        margin=dict(l=10, r=10, t=10, b=10),
        template='plotly_dark'
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("🔄 कैंडल डेटा लोड हो रहा है...")

st.markdown("---")

# ऑप्शन चेन और स्ट्राइक प्राइस टेबल
st.subheader("📊 Option Chain OI & Strike Analysis (ATM / ITM / OTM)")
if not oi_table.empty and spot_price > 0:
    display_df = oi_table.copy()
    display_df['Call Moneyness'] = display_df['Strike'].apply(lambda x: 'ITM' if x < spot_price else ('ATM' if abs(x - spot_price) < 100 else 'OTM'))
    display_df['Put Moneyness'] = display_df['Strike'].apply(lambda x: 'ITM' if x > spot_price else ('ATM' if abs(x - spot_price) < 100 else 'OTM'))
    
    st.dataframe(display_df[['Strike', 'Call OI', 'Call Moneyness', 'Put OI', 'Put Moneyness']], use_container_width=True)
else:
    st.info("🔄 ऑप्शन चेन डेटा लोड हो रहा है...")
