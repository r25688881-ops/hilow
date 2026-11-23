"""集中管理所有參數。

重要：這些參數都是「事先依通用慣例設定」，沒有針對回測績效做最佳化。
刻意不調參，是為了降低過度擬合（overfitting）的風險。
"""

# ---------- 回測區間 ----------
BACKTEST_YEARS = 15          # 回測年數
OOS_YEARS = 5                # 最後 N 年視為「樣本外」，其餘為「樣本內」
FETCH_EXTRA_DAYS = 480       # 抓資料時多抓的暖機天數（算 200 日線、12 個月動能用）

# ---------- 個股模型 ----------
TOP_N = 10                   # 持股檔數
KEEP_RANK = 20               # 已持有者，排名在前 KEEP_RANK 名內就續抱（降低換手）
SENS_TOP_N = [5, 10, 15, 20] # 敏感度分析：不同持股檔數
PIT_TOP = 50                 # 降低存活者偏差：每月只從「當時」60日成交值前 N 名中選股（None＝不限制）
PIT_SENS = [None, 60, 50, 40, 30]  # 敏感度：不同 N
RANDOM_SIMS = 200            # 隨機選股對照次數
RANDOM_SEED = 42
MIN_AVG_TURNOVER = 5e7       # 60 日平均成交值下限（新台幣），過濾流動性不足
FACTOR_WEIGHTS = {           # 多因子權重（缺資料的因子會自動重新分配權重）
    "momentum": 0.45,        # 動能：12-1 月 與 6-1 月 報酬
    "revenue": 0.25,         # 營收：近 3 個月營收年增率均值（FinMind，缺資料則略過）
    "dividend": 0.15,        # 殖利率：近 12 個月現金股利 / 股價
    "lowvol": 0.15,          # 低波動：60 日波動率越低越好
}

# ---------- 交易成本（台股） ----------
COMMISSION = 0.001425        # 手續費（單邊）
TAX_STOCK = 0.003            # 證交稅（賣出，股票）
TAX_ETF = 0.001              # 證交稅（賣出，ETF）
SLIPPAGE = 0.001             # 滑價（單邊）
FEE_DISCOUNT = 1.0           # 手續費折扣；1.0 = 不打折（保守）。券商常見 0.28~0.6

# ---------- 大盤訊號 ----------
HORIZONS = [20, 60, 120]     # 訊號出現後，觀察未來 N 個交易日報酬
THRESHOLDS = [2, 3, 4]       # 計分門檻敏感度
DEFAULT_THRESHOLD = 3        # 預設：同時 >=3 項才算警示
CONFIRM_LOOKBACK = 20      # 確認型訊號：過熱/超賣出現後，N 個交易日內等待價格確認
COOLDOWN = 20                # 同類訊號至少間隔 N 個交易日才算新事件（去除連續重複）

# 指標門檻（通用慣例值）
RSI_LOW, RSI_HIGH = 30, 70
BIAS200_LOW, BIAS200_HIGH = -0.08, 0.15
DD252_LOW = -0.15
K_LOW, K_HIGH = 20, 80
MARGIN_PCT_LOW, MARGIN_PCT_HIGH = 0.10, 0.90
MARGIN_PCT_WINDOW = 750      # 融資維持率百分位的滾動視窗（約 3 年）

# ---------- 績效統計 ----------
RF = 0.01                    # 無風險利率（年）
TRADING_DAYS = 245           # 台股一年約 245 個交易日

# ---------- 資料來源 ----------
INDEX_TICKER = "^TWII"
ETF_TICKER = "0050.TW"
FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"

# 資料格式版本：改了輸出欄位就加 1。網頁會比對，不一致時提醒「請重新執行 Actions」
SCHEMA_VERSION = 4
LADDER_LEVELS = [0.10, 0.15, 0.20, 0.25, 0.30]   # 分批進場參考：較一年高點回落幅度
LADDER_HORIZONS = [60, 120, 250]
LADDER_RESET = 0.05                                 # 回落收斂到 5% 內才算下一輪
