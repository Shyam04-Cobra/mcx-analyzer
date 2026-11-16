import streamlit as st
import pandas as pd
import yfinance as yf
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="OANDA Live Gold/Silver Analyzer", layout="wide")
st.title("⚡ OANDA / Global Live Gold & Silver Ultra-Fast Dashboard")

# ऑटो-रिफ्रेश (हर 1 सेकंड में सबसे तेज अपडेट के लिए)
st_autorefresh(interval=1000, key="oanda_fast_refresh")

# साइडबार कमोडिटी सेलेक्टर (OANDA के लिए)
commodity_choice = st.sidebar.selectbox("Select Global Commodity:", ["Gold (GC=F)", "Silver (SI=F)"])

ticker_symbol = "GC=F" if "Gold" in commodity_choice else "SI=F"

# OANDA / Global लाइव डेटा फेच करने का सुपर-फास्ट फंक्शन
@st.cache_data(ttl=5)
def get_oanda_live_data(ticker):
    try:
        data = yf.Ticker(ticker)
        # आज का लाइव इंट्राडे डेटा (1 मिनट अंतराल पर)
        hist = data.history(period="1d", interval="1m")
        if not hist.empty:
            current_price = float(hist['Close'].iloc[-1])
            open_price = float(hist['Open'].iloc[0])
            high_price = float(hist['High'].max())
            low_price = float(hist['Low'].min())
            prev_close = float(data.info.get('previousClose', current_price))
            
            change = current_price - prev_close
            pct_change = (change / prev_close) * 100
            
            return current_price, open_price, high_price, low_price, change, pct_change, hist
    except Exception as e:
        pass
    return 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, pd.DataFrame()

cur_price, o_price, h_price, l_price, chg, pct_chg, hist_df = get_oanda_live_data(ticker_symbol)

# --- UI DISPLAY ---
st.markdown(f"### 🌍 Live Global Market: {commodity_choice}")

col1, col2, col3, col4 = st.columns(4)
col1.metric("🔴 Live Price (USD)", f"${cur_price:,.2f}" if cur_price else "Loading...", f"{chg:+.2f} ({pct_chg:+.2f}%)")
col2.metric("📈 Day High", f"${h_price:,.2f}" if h_price else "-")
col3.metric("📉 Day Low", f"${l_price:,.2f}" if l_price else "-")
col4.metric("📊 Open Price", f"${o_price:,.2f}" if o_price else "-")

st.markdown("---")

# ट्रेंड / सिग्नल इंडिकेटर
st.markdown("### 🚦 Live Price Action Signal")
if chg > 0:
    st.success(f"🟢 **Bullish Momentum:** ग्लोबल मार्केट में तेजी है, कीमत ${cur_price:,.2f} पर ट्रेड कर रही है।")
elif chg < 0:
    st.error(f"🔴 **Bearish Momentum:** ग्लोबल मार्केट में दबाव/मंदी है, कीमत ${cur_price:,.2f} पर है।")
else:
    st.info("⚪ **Neutral:** बाजार स्थिर है।")

st.markdown("---")

# हालिया टिक/प्राइस टेबल
st.subheader("📋 Recent Price Ticks (1-Min Interval)")
if not hist_df.empty:
    display_table = hist_df[['Open', 'High', 'Low', 'Close', 'Volume']].tail(10).sort_index(ascending=False)
    st.dataframe(display_table, use_container_width=True)
else:
    st.info("🔄 लाइव टिक्स लोड हो रहे हैं...")
