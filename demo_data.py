"""產生「合成示範資料」，格式與 fetch_data 完全相同，只用來測試程式與網頁介面。

⚠ 這不是真實行情，績效數字沒有任何意義。網頁會顯示 DEMO 警告橫幅。
用法：python -m src.demo_data  （輸出到 data/demo/）
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

import config as C
from universe import UNIVERSE

DEMO_DIR = Path(__file__).resolve().parent / "data" / "demo"


def generate(out_dir: Path = DEMO_DIR, seed: int = 7) -> Path:
    rng = np.random.default_rng(seed)
    out_dir.mkdir(parents=True, exist_ok=True)

    end = pd.Timestamp.today().normalize()
    start = end - pd.Timedelta(days=int(C.BACKTEST_YEARS * 365.25) + C.FETCH_EXTRA_DAYS)
    days = pd.bdate_range(start, end)
    n = len(days)

    # ---- 大盤：牛熊狀態轉換 ----
    bull = True
    rets = np.empty(n)
    for i in range(n):
        if bull:
            rets[i] = rng.normal(0.00065, 0.0085)
            if rng.random() < 0.005:
                bull = False
        else:
            rets[i] = rng.normal(-0.0009, 0.019)
            if rng.random() < 0.03:
                bull = True
    close = 8000 * np.exp(np.cumsum(rets))
    rng_hl = np.abs(rng.normal(0.006, 0.003, n))
    idx = pd.DataFrame(
        {
            "open": close * (1 + rng.normal(0, 0.002, n)),
            "high": close * (1 + rng_hl),
            "low": close * (1 - rng_hl),
            "close": close,
            "volume": rng.integers(2e9, 6e9, n),
        },
        index=days,
    )
    idx["high"] = idx[["open", "high", "close"]].max(axis=1)
    idx["low"] = idx[["open", "low", "close"]].min(axis=1)
    idx.to_csv(out_dir / "index.csv", index_label="date")

    etf = pd.Series(close * np.exp(np.arange(n) * 0.00012) / 8000 * 40, index=days, name="close")
    etf.to_frame().to_csv(out_dir / "etf0050.csv", index_label="date")

    # ---- 融資維持率（示範用：隨大盤回檔而下降） ----
    roll_max = pd.Series(close, index=days).rolling(250, min_periods=1).max()
    dd = pd.Series(close, index=days) / roll_max - 1
    margin = (168 + dd * 120 + rng.normal(0, 2.5, n)).clip(118, 178)
    pd.DataFrame({"date": days, "maintenance": margin.values}).to_csv(out_dir / "margin.csv", index=False)

    # ---- 個股：市場 beta + 個別因子 + 緩慢變動的個別漂移（讓動能略有延續性） ----
    adj, raw, vol, div, rev_rows = {}, {}, {}, {}, []
    month_idx = pd.period_range(start - pd.DateOffset(months=14), end, freq="M")
    for code, _ in UNIVERSE:
        beta = rng.uniform(0.6, 1.4)
        idio = rng.uniform(0.011, 0.024)
        drift = np.zeros(n)
        d = rng.normal(0, 0.0002)
        for i in range(n):
            d = 0.995 * d + rng.normal(0, 0.00008)
            drift[i] = d
        r = beta * rets + drift + rng.normal(0, idio, n)
        listed_from = 0 if rng.random() > 0.08 else int(n * rng.uniform(0.2, 0.5))
        p = rng.uniform(30, 300) * np.exp(np.cumsum(r))
        s = pd.Series(p, index=days)
        s.iloc[:listed_from] = np.nan

        yld = rng.uniform(0.01, 0.055)
        ev = days[(days.month == 7) & (days.day <= 7)]
        ev = ev.to_series().groupby(ev.year).min().values  # 每年七月第一個交易日除息
        f = pd.Series(1.0, index=days)
        dvs = pd.Series(0.0, index=days)
        y_ev = yld * rng.uniform(0.7, 1.2)
        for e in ev:
            f.loc[:e - pd.Timedelta(days=1)] *= (1 - y_ev)
        adj_s = s.copy()
        raw_s = adj_s / f  # 還原價 = 原始價 × ∏(1-y)  →  原始價 = 還原價 / ∏(1-y)
        for e in ev:
            if e in raw_s.index and not np.isnan(raw_s.loc[e]):
                dvs.loc[e] = y_ev * raw_s.loc[e]
        adj[code], raw[code], div[code] = adj_s, raw_s, dvs
        vol[code] = pd.Series(rng.integers(5e6, 4e7, n).astype(float), index=days).where(adj_s.notna())

        g = rng.normal(0.06, 0.05)
        base = rng.uniform(2e9, 5e10)
        gs = []
        for _ in month_idx:
            g = 0.9 * g + 0.1 * 0.06 + rng.normal(0, 0.02)
            gs.append(g)
        level = base * np.exp(np.cumsum(gs)) * (1 + rng.normal(0, 0.05, len(month_idx)))
        for per, v in zip(month_idx, level):
            rev_rows.append((code, per.year, per.month, float(v)))

    for name, dct in [("prices_adj", adj), ("prices_raw", raw), ("volume", vol), ("dividends", div)]:
        pd.DataFrame(dct).to_csv(out_dir / f"{name}.csv", index_label="date")
    pd.DataFrame(rev_rows, columns=["stock_id", "revenue_year", "revenue_month", "revenue"]).to_csv(
        out_dir / "revenue.csv", index=False
    )
    (out_dir / "meta.json").write_text(
        json.dumps(
            {
                "fetched_at": pd.Timestamp.now().isoformat(timespec="seconds"),
                "demo": True,
                "finmind_margin": True,
                "finmind_revenue": True,
                "yahoo": {"stocks_ok": len(UNIVERSE), "stocks_failed": []},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return out_dir


if __name__ == "__main__":
    p = generate()
    print(f"示範資料已輸出到 {p}")
