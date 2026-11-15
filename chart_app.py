import streamlit as st
import pandas as pd
import requests
import pyotp
from datetime import datetime, timedelta
from SmartApi import SmartConnect
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="MCX Pro Option & Chart Analyzer", layout="wide")
st.title("⚡ MCX Pro Option Chain & Live Chart Analyzer")

# ऑटो-रिफ्रेश (हर 10 सेकंड में डेटा अपडेट होगा)
st_autorefresh(interval=10000, key="pro_refresh")

if "API_KEY" not in st.secrets:
    st.error("API_KEY missing in Streamlit Secrets")
    st.stop()

API_KEY = st.secrets["API_KEY"]
CLIENT_ID = st.secrets["CLIENT_ID"]
MPIN = st.secrets["MPIN"]
TOTP_SECRET = st.secrets["TOTP_SECRET"]

# साइडबार कंट्रोल्स
commodity = st.sidebar.selectbox("Select Commodity:", ["GOLDM", "SILVERM", "COPPER", "CRUDEOIL"])
timeframe_map = {
    "1 Minute": "ONE_MINUTE",
    "3 Minute": "THREE_MINUTE",
    "5 Minute": "FIVE_MINUTE",
    "15 Minute": "FIFTEEN_MINUTE",
    "30 Minute": "THIRTY_MINUTE"
}
selected_tf_label = st.sidebar.selectbox("Select Timeframe:", list(timeframe_map.keys()), index=3)
selected_tf = timeframe_map[selected_tf_label]

# एंजेल वन मास्टर डेटा से टोकन और एक्सपायरी निकालना
@st.cache_data(ttl=600)
def get_master(comm):
    try:
        url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
        res = requests.get(url, timeout=10)
        df = pd.DataFrame(res.json())
        
        # फ्यूचर्स टोकन
        inst_fut = df[(df['exch_seg'] == 'MCX') & (df['instrumenttype'] == 'FUTCOM')]
        cdf_fut = inst_fut[inst_fut['name'] == comm].copy()
        cdf_fut['expiry_dt'] = pd.to_datetime(cdf_fut['expiry'])
        ne = cdf_fut['expiry_dt'].min()
        row_fut = cdf_fut[cdf_fut['expiry_dt'] == ne].iloc[0]
        
        # ऑप्शंस डेटा
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

# डेटा फेच फंक्शन
def fetch_market_data():
    if not st.session_state.get('logged', False):
        return 0, pd.DataFrame(), pd.DataFrame(), 0, 0, 50
    
    obj = st.session_state['smart_obj']
    spot_price = 0
    df_chart = pd.DataFrame()
    oi_table = pd.DataFrame()
    support, resistance, pcr = 0, 0, 0

    try:
        # 1. फ्यूचर्स का करंट प्राइस और कैंडल डेटा
        to_date = datetime.now().strftime("%Y-%m-%d %H:%M")
        from_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d %H:%M")
        
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
            df_chart.set_index('Datetime', inplace=True)
            spot_price = float(df_chart['Close'].iloc[-1])

        # 2. ऑप्शन चेन और OI डेटा
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
                        # ATM खोजना
                        combined['Diff'] = abs(combined['Strike'] - spot_price)
                        atm_strike = combined.loc[combined['Diff'].idxmin()]['Strike']
                        
                        # ITM / OTM तय करना
                        def get_moneyness(row, opt_type):
                            strike = row['Strike']
                            if opt_type == 'CE':
                                return 'ITM' if strike < spot_price else ('ATM' if strike == atm_strike else 'OTM')
                            else:
                                return 'ITM' if strike > spot_price else ('ATM' if strike == atm_strike else 'OTM')
                        
                        # सपोर्ट और रेजिस्टेंस निकालना
                        support = int(pe_df.idxmax()) if not pe_df.empty else 0
                        resistance = int(ce_df.idxmax()) if not ce_df.empty else 0
                        pcr = round(pe_df.sum() / max(ce_df.sum(), 1), 2)
                        
                        oi_table = combined.sort_values(by='Strike')
    except Exception as e:
        pass

    return spot_price, df_chart, oi_table, support, resistance, pcr

spot_price, chart_df, oi_table, support, resistance, pcr = fetch_market_data()

# डैशबोर्ड लेवल्स मेट्रिक्स
st.markdown(f"### 🎯 MCX {commodity} ({fut_symbol}) Market Overview")
col1, col2, col3, col4 = st.columns(4)
col1.metric("💰 Current Spot/Fut Price", f"₹ {spot_price:,.2f}" if spot_price else "Loading...")
col2.metric("🛡️ Support (Max PE OI)", f"₹ {support}" if support else "Calculating...")
col3.metric("🧱 Resistance (Max CE OI)", f"₹ {resistance}" if resistance else "Calculating...")
col4.metric("📊 PCR Ratio", str(pcr))

st.markdown("---")

# चार्ट सेक्शन
st.subheader(f"📉 Price Chart ({selected_tf_label} Timeframe)")
if not chart_df.empty:
    st.line_chart(chart_df[['Open', 'High', 'Low', 'Close']], height=400)
else:
    st.info("🔄 चार्ट डेटा लोड हो रहा है...")

st.markdown("---")

# ऑप्शन चेन और स्ट्राइक प्राइस (ATM/ITM/OTM) सेक्शन
st.subheader("📊 Option Chain OI & Strike Analysis (ATM / ITM / OTM)")
if not oi_table.empty and spot_price > 0:
    # टेबल फॉर्मेटिंग
    display_df = oi_table.copy()
    display_df['Call Moneyness'] = display_df['Strike'].apply(lambda x: 'ITM' if x < spot_price else ('ATM' if abs(x - spot_price) < 100 else 'OTM'))
    display_df['Put Moneyness'] = display_df['Strike'].apply(lambda x: 'ITM' if x > spot_price else ('ATM' if abs(x - spot_price) < 100 else 'OTM'))
    
    st.dataframe(display_df[['Strike', 'Call OI', 'Call Moneyness', 'Put OI', 'Put Moneyness']], use_container_width=True)
else:
    st.info("🔄 ऑप्शन चेन और स्ट्राइक डेटा लोड हो रहा है...")
