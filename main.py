import os, time, yfinance as yf
from finnhub import Client as Finnhub
from sharia_filter import is_sharia_compliant

FINNHUB_KEY = os.getenv('FINNHUB_KEY')
finnhub_client = Finnhub(FINNHUB_KEY) if FINNHUB_KEY else None

MIN_PCT_CHANGE = float(os.getenv('MIN_PCT_CHANGE','5.0'))
VOLUME_MULTIPLIER = float(os.getenv('VOLUME_MULTIPLIER','2.0'))
VALUE_MIN_USD = float(os.getenv('VALUE_MIN_USD','200000'))

class Engine:
    def __init__(self, notifier):
        self.notifier = notifier

    def _get_minute_data(self,ticker):
        try:
            tk=yf.Ticker(ticker)
            df=tk.history(period='2d',interval='1m')
            return df if df is not None and not df.empty else None
        except: return None

    def _get_daily_stats(self,ticker):
        try:
            tk=yf.Ticker(ticker)
            hist=tk.history(period='30d',interval='1d')
            if hist.empty: return None
            avg_vol=hist['Volume'].tail(20).mean()
            last_close=hist['Close'].iloc[-1]
            info=tk.info if isinstance(tk.info,dict) else {}
            float_shares=info.get('floatShares') or info.get('sharesOutstanding')
            return {'avg_vol':avg_vol,'last_close':last_close,'float':float_shares}
        except: return None

    def _check_news(self,ticker):
        if not finnhub_client: return []
        try:
            now=int(time.time()); frm=now-(24*60*60)
            frm_s=time.strftime('%Y-%m-%d',time.gmtime(frm))
            to_s=time.strftime('%Y-%m-%d',time.gmtime(now))
            return finnhub_client.company_news(ticker,_from=frm_s,to=to_s) or []
        except: return []

    def analyze(self,ticker):
        if not is_sharia_compliant(ticker):
            return {'ticker':ticker,'sharia':False}
        df=self._get_minute_data(ticker)
        if df is None: return None
        try:
            last=float(df['Close'].iloc[-1])
            lookback=-30 if len(df)>=30 else 0
            prev=float(df['Close'].iloc[lookback])
            pct=(last-prev)/prev*100 if prev!=0 else 0.0
        except: return None
        stats=self._get_daily_stats(ticker)
        if not stats: return None
        recent_vol=int(df['Volume'].tail(30).sum())
        approx_value=int(recent_vol*last)
        cond_pct=pct>=MIN_PCT_CHANGE
        cond_vol=recent_vol>=stats['avg_vol']*VOLUME_MULTIPLIER/(390/30)
        cond_value=approx_value>=VALUE_MIN_USD
        news=self._check_news(ticker)
        support=float(df['Low'].tail(30).min())
        resistance=float(df['High'].tail(30).max())
        return {
            'ticker':ticker,'price':round(last,4),'pct_change':round(pct,2),
            'recent_vol':recent_vol,'avg_vol':int(stats['avg_vol']),
            'value':approx_value,'cond_pct':cond_pct,'cond_vol':cond_vol,
            'cond_value':cond_value,'news_count':len(news),
            'support':round(support,4),'resistance':round(resistance,4),
            'news':news[:2] if news else []
        }

    def scan_watchlist(self,path='watchlist.txt'):
        if not os.path.exists(path): return
        with open(path,'r') as f:
            tickers=[t.strip().upper() for t in f if t.strip()]
        for t in tickers:
            info=self.analyze(t)
            if not info or info.get('sharia') is False: continue
            if info['cond_pct'] and (info['cond_vol'] or info['news_count']>0) and info['cond_value']:
                msg=self.format_message(info)
                self.notifier.send(msg)

    def format_message(self,info):
        risk='🟩 آمن' if info['price']>=1 else ('🟨 متوسط' if info['price']>=0.5 else '🟥 مغامر')
        news_part=''
        if info.get('news'):
            head=info['news'][0].get('headline') or info['news'][0].get('summary','')
            news_part=f"\nالخبر: {head[:200]}"
        return (
            f"🚨 سهم قوي – Live PRO\n\n"
            f"الرمز: {info['ticker']}\n"
            f"السعر الآن: {info['price']}\n"
            f"الارتفاع: +{info['pct_change']}%\n"
            f"الفوليوم (آخر ~30m): {info['recent_vol']}\n"
            f"المتوسط اليومي: {info['avg_vol']}\n"
            f"القيمة التقريبية: ${info['value']}\n\n"
            f"مستوى المخاطر: {risk}\n"
            f"الشرعية: ✔ قيد الفحص\n\n"
            f"الدعم: {info['support']}\n"
            f"المقاومة: {info['resistance']}\n"
            f"{news_part}\n\n"
            "تنويه: هذه نسخة PRO — تحقق يدويًا قبل الدخول."
        )
