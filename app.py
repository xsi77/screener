"""
放量二次上攻 A股選股器 — Streamlit Web App
============================================
啟動: streamlit run app.py
瀏覽器會自動開啟 http://localhost:8501
"""
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st


# ============ 模式偵測邏輯 (與 CLI 版相同) ============
@dataclass
class Config:
    LOOKBACK_DAYS: int = 120
    FIRST_WAVE_MIN_VOL_RATIO: float = 1.5
    FIRST_WAVE_MIN_GAIN: float = 0.03
    FIRST_WAVE_WINDOW_MIN: int = 5
    FIRST_WAVE_WINDOW_MAX: int = 40
    PULLBACK_MIN_DAYS: int = 3
    PULLBACK_MAX_DAYS: int = 20
    PULLBACK_MIN_PCT: float = 0.03
    PULLBACK_MAX_PCT: float = 0.15
    HOLD_BREAKOUT_LOW: bool = True
    SECOND_WAVE_MIN_VOL_RATIO: float = 1.5
    SECOND_WAVE_VS_FIRST_RATIO: float = 0.8
    REQUIRE_RED_CANDLE: bool = True
    REQUIRE_BREAK_HIGH: bool = True
    MIN_AVG_VOLUME_LOTS: int = 10_000
    MIN_PRICE: float = 5.0
    MAX_PRICE: float = 500.0
    EXCLUDE_ST: bool = True
    MAX_WORKERS: int = 10
    USE_PRE_FILTER: bool = True


def detect_pattern(df: pd.DataFrame, cfg: Config, intraday_data: dict = None):
    """
    intraday_data (可選): 盤中模式,覆寫今日的關鍵欄位
        - 'vol_ratio': 用交易所「量比」取代計算值 (時間加權,盤中準確)
        - 'volume': 用「全日預估量」取代當前累積量 (= vol_ma5 × 量比)
    """
    if len(df) < max(40, cfg.FIRST_WAVE_WINDOW_MAX + 5):
        return None
    df = df.copy().reset_index(drop=True)
    df['pct_chg'] = df['close'].pct_change() * 100
    df['vol_ma20'] = df['volume'].rolling(20).mean()
    df['vol_ratio'] = df['volume'] / df['vol_ma20']
    n = len(df)

    # 盤中覆寫
    if intraday_data:
        if 'vol_ratio' in intraday_data and not pd.isna(intraday_data['vol_ratio']):
            df.at[n - 1, 'vol_ratio'] = intraday_data['vol_ratio']
        if 'volume' in intraday_data and not pd.isna(intraday_data['volume']):
            df.at[n - 1, 'volume'] = intraday_data['volume']

    today = df.iloc[-1]

    if pd.isna(today['vol_ma20']) or today['vol_ma20'] < cfg.MIN_AVG_VOLUME_LOTS:
        return None
    if cfg.REQUIRE_RED_CANDLE and today['close'] <= today['open']:
        return None
    if today['vol_ratio'] < cfg.SECOND_WAVE_MIN_VOL_RATIO:
        return None

    window_end = n - 1 - cfg.FIRST_WAVE_WINDOW_MIN
    window_start = max(20, n - 1 - cfg.FIRST_WAVE_WINDOW_MAX)
    if window_end <= window_start:
        return None

    best = None
    for i in range(window_start, window_end + 1):
        r = df.iloc[i]
        if pd.isna(r['vol_ratio']):
            continue
        if (r['pct_chg'] >= cfg.FIRST_WAVE_MIN_GAIN * 100
                and r['vol_ratio'] >= cfg.FIRST_WAVE_MIN_VOL_RATIO):
            seg_end = min(i + 10, n - 2)
            seg = df.iloc[i:seg_end + 1]
            local_high = seg['high'].max()
            local_high_idx = seg['high'].idxmax()
            if best is None or local_high > best[0]:
                best = (local_high, i, local_high_idx)

    if best is None:
        return None
    first_wave_high, fw_idx, fw_high_idx = best

    if fw_high_idx >= n - 1 - cfg.PULLBACK_MIN_DAYS:
        return None
    pullback_seg = df.iloc[fw_high_idx + 1:n - 1]
    if not (cfg.PULLBACK_MIN_DAYS <= len(pullback_seg) <= cfg.PULLBACK_MAX_DAYS):
        return None
    pullback_low = pullback_seg['low'].min()
    pullback_pct = 1 - pullback_low / first_wave_high
    if not (cfg.PULLBACK_MIN_PCT <= pullback_pct <= cfg.PULLBACK_MAX_PCT):
        return None
    if cfg.HOLD_BREAKOUT_LOW:
        if pullback_low < df.iloc[fw_idx]['low']:
            return None
    if cfg.REQUIRE_BREAK_HIGH and today['close'] <= first_wave_high:
        return None
    fw_volume = df.iloc[fw_idx]['volume']
    if today['volume'] < fw_volume * cfg.SECOND_WAVE_VS_FIRST_RATIO:
        return None

    return {
        'today_close': round(today['close'], 2),
        'today_pct': round(today['pct_chg'], 2),
        'today_vol_ratio': round(today['vol_ratio'], 2),
        'first_wave_date': str(df.iloc[fw_idx]['date'])[:10],
        'first_wave_high': round(first_wave_high, 2),
        'first_wave_vol_ratio': round(df.iloc[fw_idx]['vol_ratio'], 2),
        'fw_idx': fw_idx,
        'fw_high_idx': fw_high_idx,
        'pullback_days': len(pullback_seg),
        'pullback_pct': round(pullback_pct * 100, 2),
        'breakout_pct': round((today['close'] / first_wave_high - 1) * 100, 2),
        'today_vs_fw_vol': round(today['volume'] / fw_volume, 2),
        '_df': df,
    }


# ============ 盤中判斷 ============
def trading_minutes_elapsed(now=None):
    """A股交易已過分鐘數 / 全日 240 分鐘"""
    from datetime import time as dtime
    if now is None:
        now = datetime.now()
    if now.weekday() >= 5:
        return 0, 240
    t = now.time()
    if t < dtime(9, 30): return 0, 240
    if t < dtime(11, 30):
        return (now.hour - 9) * 60 + (now.minute - 30), 240
    if t < dtime(13, 0): return 120, 240
    if t < dtime(15, 0):
        return 120 + (now.hour - 13) * 60 + now.minute, 240
    return 240, 240


def market_status(now=None):
    """回傳 (狀態, 已過分鐘, 全日分鐘)"""
    if now is None:
        now = datetime.now()
    elapsed, total = trading_minutes_elapsed(now)
    if now.weekday() >= 5:
        return 'closed_weekend', elapsed, total
    if elapsed == 0:
        return 'pre_open', elapsed, total
    if elapsed >= total:
        return 'closed_today', elapsed, total
    if 120 <= elapsed < 121 and now.time().hour == 12:
        return 'lunch', elapsed, total
    return 'open', elapsed, total


# ============ 資料取得 (akshare) ============
@st.cache_data(ttl=60, show_spinner=False)
def get_pool(use_prefilter: bool, min_price: float, max_price: float, exclude_st: bool):
    """主板個股池 (排除 ST / 創業板 / 科創板 / 北交所)"""
    import akshare as ak
    df = ak.stock_zh_a_spot_em()
    df = df.rename(columns={'代码': 'code', '名称': 'name', '最新价': 'price',
                            '涨跌幅': 'pct', '换手率': 'turnover', '量比': 'vol_ratio',
                            '今开': 'today_open', '最高': 'today_high',
                            '最低': 'today_low', '成交量': 'today_vol'})
    # 只留主板: 沪 600/601/603/605, 深 000/001/002/003
    df = df[df['code'].str.match(r'^(600|601|603|605|000|001|002|003)')]
    if exclude_st:
        df = df[~df['name'].str.contains('ST|退|N ', na=False)]
    df = df[(df['price'] >= min_price) & (df['price'] <= max_price)]
    if use_prefilter:
        df = df[df['pct'] > 1.0]
        df = df[df['vol_ratio'] > 1.3]
    cols = ['code', 'name', 'price', 'pct', 'vol_ratio',
            'today_open', 'today_high', 'today_low', 'today_vol']
    return df[cols].reset_index(drop=True)


@st.cache_data(ttl=600, show_spinner=False)
def get_hist(code: str, days: int):
    import akshare as ak
    end = datetime.now().strftime('%Y%m%d')
    start = (datetime.now() - timedelta(days=days)).strftime('%Y%m%d')
    try:
        df = ak.stock_zh_a_hist(symbol=code, period='daily',
                                start_date=start, end_date=end, adjust='qfq')
        if df is None or len(df) == 0:
            return None
        df = df.rename(columns={'日期': 'date', '开盘': 'open', '收盘': 'close',
                                '最高': 'high', '最低': 'low', '成交量': 'volume'})
        return df[['date', 'open', 'high', 'low', 'close', 'volume']].sort_values('date').reset_index(drop=True)
    except Exception:
        return None


def check_one(code, name, cfg, snapshot=None):
    """
    snapshot: 若提供 (盤中模式),用 snapshot 補今日 K bar:
        keys: today_open, today_high, today_low, price, today_vol, vol_ratio
    """
    df = get_hist(code, cfg.LOOKBACK_DAYS)
    if df is None or len(df) < 40:
        return None

    intraday_data = None
    today_str = datetime.now().strftime('%Y-%m-%d')

    if snapshot is not None:
        last_date = str(df.iloc[-1]['date'])[:10]
        if last_date != today_str:
            # 歷史資料無今日 → 從 snapshot 補上
            vol_ma5 = df['volume'].iloc[-5:].mean()
            liang_bi = snapshot.get('vol_ratio', 1.0)
            if pd.isna(liang_bi) or liang_bi <= 0:
                liang_bi = 1.0
            # 全日量預估 = 5日均量 × 量比 (時間加權)
            proj_vol = vol_ma5 * liang_bi

            today_row = pd.DataFrame([{
                'date': pd.Timestamp(today_str),
                'open': snapshot['today_open'],
                'high': snapshot['today_high'],
                'low': snapshot['today_low'],
                'close': snapshot['price'],
                'volume': proj_vol,
            }])
            df = pd.concat([df, today_row], ignore_index=True)
            intraday_data = {'vol_ratio': liang_bi, 'volume': proj_vol}

    r = detect_pattern(df, cfg, intraday_data=intraday_data)
    if r is None:
        return None
    r['code'] = code
    r['name'] = name
    r['intraday'] = intraday_data is not None
    return r


# ============ K 線圖 ============
def plot_candlestick(result):
    df = result['_df'].copy()
    df['date'] = pd.to_datetime(df['date'])
    fw_idx = result['fw_idx']
    fw_high_idx = result['fw_high_idx']

    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=df['date'], open=df['open'], high=df['high'],
        low=df['low'], close=df['close'],
        increasing_line_color='#d63031', decreasing_line_color='#00b894',
        name='K線'))

    # 標記第一波突破日
    fig.add_annotation(x=df.iloc[fw_idx]['date'], y=df.iloc[fw_idx]['high'],
                       text="第一波<br>突破", showarrow=True, arrowhead=2,
                       ax=0, ay=-40, font=dict(color='orange', size=11),
                       bordercolor='orange', borderwidth=1)
    # 第一波高點水平線
    fig.add_hline(y=result['first_wave_high'], line_dash='dash',
                  line_color='orange', annotation_text=f"第一波高 {result['first_wave_high']}")
    # 標記今日
    fig.add_annotation(x=df.iloc[-1]['date'], y=df.iloc[-1]['high'],
                       text="二次<br>上攻", showarrow=True, arrowhead=2,
                       ax=0, ay=-40, font=dict(color='red', size=11),
                       bordercolor='red', borderwidth=1)

    fig.update_layout(
        height=400, xaxis_rangeslider_visible=False,
        margin=dict(l=10, r=10, t=30, b=10),
        showlegend=False,
        xaxis=dict(showgrid=False),
        yaxis=dict(showgrid=True, gridcolor='rgba(128,128,128,0.2)'),
    )
    return fig


# ============ Streamlit UI ============
st.set_page_config(
    page_title="放量二次上攻選股器",
    layout="wide",
    page_icon="📈",
    initial_sidebar_state="collapsed",  # 手機友善:預設收起 sidebar
    menu_items={'About': '放量二次上攻 A股選股器 · 主板專用'}
)

st.title("📈 放量二次上攻 A股選股器")
st.caption("僅主板 · 排除 ST / 創業板 / 科創板 · 盤中即時偵測")

# 市場狀態
_status, _elapsed, _total = market_status()
_status_map = {
    'pre_open': ('⏸️ 未開盤', '使用昨日資料偵測'),
    'open': (f'🟢 盤中 · {_elapsed}/{_total} 分鐘', '自動補今日 K bar (5日均量 × 量比)'),
    'lunch': ('⏸️ 午休', '使用上午資料偵測'),
    'closed_today': ('🔴 已收盤', '使用今日完整資料'),
    'closed_weekend': ('⏸️ 週末休市', '使用最新交易日資料'),
}
_label, _hint = _status_map.get(_status, ('狀態未知', ''))
st.info(f"**{_label}** · {_hint}")

# ----- Sidebar 參數 -----
st.sidebar.header("⚙️ 參數")

with st.sidebar.expander("🚀 第一波 (發動)", expanded=True):
    fw_vol = st.slider("量比 ≥", 1.0, 3.0, 1.5, 0.1, key='fw_vol')
    fw_gain = st.slider("漲幅 % ≥", 1.0, 8.0, 3.0, 0.5, key='fw_gain')
    fw_win_max = st.slider("回溯交易日上限", 15, 60, 40, 5, key='fw_win')

with st.sidebar.expander("📉 回檔 (整理)", expanded=True):
    pb_days = st.slider("回檔天數", 2, 30, (3, 20), key='pb_days')
    pb_pct = st.slider("回檔幅度 %", 1.0, 25.0, (3.0, 15.0), 0.5, key='pb_pct')
    hold_low = st.checkbox("不破第一波突破日低點", True, key='hold')

with st.sidebar.expander("🎯 二次上攻 (今日)", expanded=True):
    sw_vol = st.slider("今日量比 ≥", 1.0, 3.0, 1.5, 0.1, key='sw_vol')
    sw_vs_fw = st.slider("今日量 / 第一波量 ≥", 0.3, 1.5, 0.8, 0.1, key='sw_vs')
    req_red = st.checkbox("須收紅 K", True, key='red')
    req_break = st.checkbox("須突破第一波高點", True, key='brk')

with st.sidebar.expander("💰 過濾"):
    min_avg_vol = st.number_input("20日均量下限 (手)", 1000, 100000, 10000, 1000)
    price_range = st.slider("價格區間 (元)", 1.0, 800.0, (5.0, 500.0))
    excl_st = st.checkbox("排除 ST", True)
    prefilter = st.checkbox("今日漲幅 >1% 粗篩 (加速)", True,
                            help="關閉後掃全市場,慢約 5-10x")
    workers = st.slider("並行數", 4, 20, 10)

# ----- 主區 -----
col1, col2 = st.columns([3, 1])
with col1:
    if st.button("🚀 開始掃描", type="primary", use_container_width=True):
        cfg = Config(
            FIRST_WAVE_MIN_VOL_RATIO=fw_vol,
            FIRST_WAVE_MIN_GAIN=fw_gain / 100,
            FIRST_WAVE_WINDOW_MAX=fw_win_max,
            PULLBACK_MIN_DAYS=pb_days[0],
            PULLBACK_MAX_DAYS=pb_days[1],
            PULLBACK_MIN_PCT=pb_pct[0] / 100,
            PULLBACK_MAX_PCT=pb_pct[1] / 100,
            HOLD_BREAKOUT_LOW=hold_low,
            SECOND_WAVE_MIN_VOL_RATIO=sw_vol,
            SECOND_WAVE_VS_FIRST_RATIO=sw_vs_fw,
            REQUIRE_RED_CANDLE=req_red,
            REQUIRE_BREAK_HIGH=req_break,
            MIN_AVG_VOLUME_LOTS=int(min_avg_vol),
            MIN_PRICE=price_range[0],
            MAX_PRICE=price_range[1],
            EXCLUDE_ST=excl_st,
            USE_PRE_FILTER=prefilter,
            MAX_WORKERS=workers,
        )

        t0 = time.time()
        with st.spinner("取得標的池..."):
            pool = get_pool(cfg.USE_PRE_FILTER, cfg.MIN_PRICE, cfg.MAX_PRICE, cfg.EXCLUDE_ST)

        # 盤中模式: 把 snapshot 傳入 check_one
        is_intraday = _status == 'open'
        mode_msg = "🟢 盤中模式 (snapshot 補今日)" if is_intraday else "📊 收盤資料模式"
        st.info(f"{mode_msg} · 初篩標的: **{len(pool)}** 檔 · 開始掃描...")

        progress = st.progress(0)
        status = st.empty()
        results = []
        total = len(pool)

        with ThreadPoolExecutor(max_workers=cfg.MAX_WORKERS) as ex:
            futures = {}
            for _, r in pool.iterrows():
                snap = r.to_dict() if is_intraday else None
                futures[ex.submit(check_one, r['code'], r['name'], cfg, snap)] = r['code']
            done = 0
            for fut in as_completed(futures):
                done += 1
                progress.progress(done / total)
                if done % 10 == 0:
                    status.text(f"進度 {done}/{total} · 命中 {len(results)}")
                r = fut.result()
                if r:
                    results.append(r)

        progress.empty()
        status.empty()
        elapsed = time.time() - t0
        st.session_state['results'] = results
        st.session_state['elapsed'] = elapsed

with col2:
    if 'results' in st.session_state:
        st.metric("命中數", len(st.session_state['results']),
                  delta=f"{st.session_state.get('elapsed', 0):.0f}s")

# ----- 顯示結果 -----
if 'results' in st.session_state and st.session_state['results']:
    results = st.session_state['results']
    cols = ['code', 'name', 'today_close', 'today_pct', 'today_vol_ratio',
            'first_wave_date', 'first_wave_high', 'pullback_days', 'pullback_pct',
            'breakout_pct', 'today_vs_fw_vol', 'intraday']
    df_out = pd.DataFrame([{k: r.get(k) for k in cols} for r in results])
    df_out = df_out.sort_values(['today_vol_ratio', 'breakout_pct'], ascending=[False, False])

    st.subheader(f"✅ 命中清單 ({len(df_out)} 檔)")

    # 下載按鈕
    csv = df_out.to_csv(index=False).encode('utf-8-sig')
    st.download_button("📥 下載 CSV", csv,
                       f"second_wave_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                       "text/csv")

    # 結果表
    st.dataframe(df_out, use_container_width=True, hide_index=True,
                 column_config={
                     'today_pct': st.column_config.NumberColumn('漲幅%', format="%.2f"),
                     'today_vol_ratio': st.column_config.NumberColumn('量比', format="%.2f"),
                     'breakout_pct': st.column_config.NumberColumn('突破%', format="%.2f"),
                     'pullback_pct': st.column_config.NumberColumn('回檔%', format="%.2f"),
                 })

    # K 線圖檢視
    st.subheader("📊 K 線檢視")
    pick = st.selectbox("選擇個股",
                        [f"{r['code']} {r['name']}" for r in results])
    if pick:
        code = pick.split()[0]
        target = next(r for r in results if r['code'] == code)
        st.plotly_chart(plot_candlestick(target), use_container_width=True)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("今日量比", f"{target['today_vol_ratio']}x")
        c2.metric("回檔幅度", f"{target['pullback_pct']}%")
        c3.metric("突破幅度", f"{target['breakout_pct']}%")
        c4.metric("二次/一次量", f"{target['today_vs_fw_vol']}x")

elif 'results' in st.session_state:
    st.warning("無標的命中,試試放寬參數")

else:
    st.info("👈 左側調整參數後按「開始掃描」")
    with st.expander("📖 模式說明"):
        st.markdown("""
        **放量二次上攻** 三段式形態:
        1. **第一波**:近期帶量突破日 (量比放大 + 漲幅突出)
        2. **回檔**:高點後縮量整理,不破第一波突破日低點
        3. **二次上攻**:今日收盤突破第一波高點,量再放大

        **進場思路**:命中後隔日量縮高開介入,跌破第一波高點停損,風報比明確。
        """)
