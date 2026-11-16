import streamlit as st
import pandas as pd
import yfinance as yf
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="Live Gold/Silver Analyzer", layout="wide")
st.title("⚡ Live Global Gold & Silver Price Tracker")

# ऑटो-रिफ्रेश (हर 2 सेकंड में)
st_autorefresh(interval=2000, key="live_price_refresh")

# कमोडिटी सेलेक्टर
commodity_choice = st.sidebar.selectbox("Select Commodity:", ["Gold (GC=F)", "Silver (SI=F)"])
ticker_symbol = "GC=F" if "Gold" in commodity_choice else "SI=F"

# सटीक लाइव डेटा फेच करने का फंक्शन
@st.cache_data(ttl=5)
def get_live_prices(ticker):
    try:
        t = yf.Ticker(ticker)
        # फास्ट फेच के लिए 1 दिन का डेटा और info
        todays_data = t.history(period="2d", interval="1m")
        
        if not todays_data.empty:
            current_price = float(todays_data['Close'].iloc[-1])
            # पिछले दिन का क्लोज या आज का ओपन सही बेस के लिए
            if len(todays_data) > 1:
                # पिछले सेशन का आखिरी क्लोज
                prev_close = float(todays_data['Close'].iloc[-2])
            else:
                prev_close = float(t.info.get('previousClose', current_price))
                
            change = current_price - prev_close
            pct_change = (change / prev_close) * 100
            
            high_p = float(todays_data['High'].max())
            low_p = float(todays_data['Low'].min())
            
            return current_price, prev_close, high_p, low_p, change, pct_change, todays_data
    except Exception as e:
        pass
    return 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, pd.DataFrame()

cur_price, p_close, h_price, l_price, chg, pct_chg, hist_df = get_live_prices(ticker_symbol)

# --- UI DISPLAY ---
st.markdown(f"### 🌍 Live Market: {commodity_choice}")

col1, col2, col3, col4 = st.columns(4)

# सही ग्रीन/रेड कलर के साथ मेट्रिक दिखाना
col1.metric(
    "🔴 Live Price (USD)", 
    f"${cur_price:,.2f}" if cur_price else "Loading...", 
    f"{chg:+.2f} ({pct_chg:+.2f}%)",
    delta_color="normal"
)
col2.metric("📈 Day High", f"${h_price:,.2f}" if h_price else "-")
col3.metric("📉 Day Low", f"${l_price:,.2f}" if l_price else "-")
col4.metric("📊 Prev Close", f"${p_close:,.2f}" if p_close else "-")

st.markdown("---")

# सटीक सिग्नल
st.markdown("### 🚦 Market Trend Direction")
if chg > 0:
    st.success(f"🟢 **Bullish (तेजी):** बाजार हरे निशान में है, कीमत ${cur_price:,.2f} पर है।")
elif chg < 0:
    st.error(f"🔴 **Bearish (मंदी):** बाजार लाल निशान (गिरावट) में है, कीमत ${cur_price:,.2f} पर है।")
else:
    st.info("⚪ **Neutral:** बाजार स्थिर है।")

st.markdown("---")

st.subheader("📋 Recent Ticks Data")
if not hist_df.empty:
    st.dataframe(hist_df[['Open', 'High', 'Low', 'Close', 'Volume']].tail(10).sort_index(ascending=False), use_container_width=True)
else:
    st.info("🔄 डेटा लोड हो रहा है...")
