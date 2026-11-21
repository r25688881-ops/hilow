"""抓取免費資料並存成 CSV（data/raw/）。

資料來源
  1) Yahoo Finance（yfinance）：加權指數 ^TWII、0050、股票池的價量與股利  【必要】
  2) FinMind 免費 API：整體市場融資維持率、個股月營收                  【選用，失敗會自動略過】
     - 申請免費 token 可提高額度：環境變數 FINMIND_TOKEN（GitHub 請放在 Secrets）

用法：python fetch_data.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

import config as C
from universe import UNIVERSE, yahoo_symbol

RAW_DIR = Path(__file__).resolve().parent / "data" / "raw"


def log(msg: str) -> None:
    print(f"[fetch] {msg}", flush=True)


def _history(symbol: str, start: str, retries: int = 3) -> pd.DataFrame | None:
    import yfinance as yf

    for attempt in range(retries):
        try:
            h = yf.Ticker(symbol).history(start=start, auto_adjust=False, actions=True)
            if h is not None and len(h) > 0:
                h = h.copy()
                idx = pd.DatetimeIndex(h.index)
                if idx.tz is not None:
                    idx = idx.tz_localize(None)
                h.index = idx.normalize()
                h = h[~h.index.duplicated(keep="last")]
                return h
        except Exception as e:  # noqa: BLE001
            log(f"  {symbol} 第 {attempt + 1} 次失敗：{e}")
        time.sleep(2 * (attempt + 1))
    return None


def fetch_yahoo(start: str) -> dict:
    status = {"index": False, "etf": False, "stocks_ok": 0, "stocks_failed": []}

    idx = _history(C.INDEX_TICKER, start)
    if idx is None:
        raise RuntimeError("抓不到加權指數 ^TWII，無法繼續")
    idx[["Open", "High", "Low", "Close", "Volume"]].rename(columns=str.lower).to_csv(
        RAW_DIR / "index.csv", index_label="date"
    )
    status["index"] = True
    log(f"加權指數：{len(idx)} 筆，{idx.index[0].date()} ~ {idx.index[-1].date()}")

    etf = _history(C.ETF_TICKER, start)
    if etf is not None:
        etf[["Adj Close"]].rename(columns={"Adj Close": "close"}).to_csv(
            RAW_DIR / "etf0050.csv", index_label="date"
        )
        status["etf"] = True
        log(f"0050：{len(etf)} 筆")
    else:
        log("0050 抓取失敗，大盤擇時策略改用指數價格代替")

    adj, raw, vol, div = {}, {}, {}, {}
    for code, name in UNIVERSE:
        h = _history(yahoo_symbol(code), start)
        if h is None or len(h) < 300:
            status["stocks_failed"].append(code)
            log(f"  {code} {name}：資料不足，略過")
        else:
            adj[code] = h["Adj Close"]
            raw[code] = h["Close"]
            vol[code] = h["Volume"]
            div[code] = h["Dividends"] if "Dividends" in h.columns else pd.Series(0.0, index=h.index)
            status["stocks_ok"] += 1
        time.sleep(0.4)  # 避免被 Yahoo 限流

    if status["stocks_ok"] < 0.7 * len(UNIVERSE):
        raise RuntimeError(f"成功抓到的個股過少（{status['stocks_ok']}/{len(UNIVERSE)}），請稍後重試")

    for fname, d in [("prices_adj", adj), ("prices_raw", raw), ("volume", vol), ("dividends", div)]:
        pd.DataFrame(d).sort_index().to_csv(RAW_DIR / f"{fname}.csv", index_label="date")
    log(f"個股：成功 {status['stocks_ok']} 檔，失敗 {len(status['stocks_failed'])} 檔")
    return status


# ---------------- FinMind（選用） ----------------

def _finmind(dataset: str, start: str, data_id: str | None = None) -> pd.DataFrame | None:
    import requests

    params = {"dataset": dataset, "start_date": start}
    if data_id:
        params["data_id"] = data_id
    token = os.environ.get("FINMIND_TOKEN", "").strip()
    if token:
        params["token"] = token
    try:
        r = requests.get(C.FINMIND_URL, params=params, timeout=60)
        j = r.json()
        if j.get("status") != 200:
            log(f"  FinMind {dataset} {data_id or ''} 回傳：{j.get('msg')}")
            return None
        df = pd.DataFrame(j.get("data", []))
        return df if len(df) else None
    except Exception as e:  # noqa: BLE001
        log(f"  FinMind {dataset} 失敗：{e}")
        return None


def fetch_margin(start: str) -> bool:
    """整體市場融資維持率。欄位名稱不同版本可能不一，這裡自動尋找數值欄。"""
    df = _finmind("TaiwanTotalExchangeMarginMaintenance", start)
    if df is None or "date" not in df.columns:
        log("融資維持率：未取得（將改用純價量訊號，不影響其他功能）")
        return False
    value_cols = [c for c in df.columns if c != "date" and pd.api.types.is_numeric_dtype(df[c])]
    pref = [c for c in value_cols if "aintenance" in c]
    col = (pref or value_cols or [None])[0]
    if col is None:
        log("融資維持率：找不到數值欄位")
        return False
    out = pd.DataFrame({"date": pd.to_datetime(df["date"]), "maintenance": df[col].astype(float)})
    out = out.dropna().drop_duplicates("date").sort_values("date")
    out.to_csv(RAW_DIR / "margin.csv", index=False)
    log(f"融資維持率：{len(out)} 筆")
    return True


def fetch_revenue(start: str, codes: list[str]) -> bool:
    frames = []
    for i, code in enumerate(codes, 1):
        df = _finmind("TaiwanStockMonthRevenue", start, data_id=code)
        if df is not None and {"revenue", "revenue_year", "revenue_month"} <= set(df.columns):
            frames.append(
                df[["revenue_year", "revenue_month", "revenue"]].assign(stock_id=code)
            )
        if i % 20 == 0:
            log(f"  月營收進度 {i}/{len(codes)}")
        time.sleep(0.3)
    if len(frames) < 0.5 * len(codes):
        log(f"月營收：僅取得 {len(frames)}/{len(codes)} 檔，視為不可用（將略過營收因子）")
        return False
    out = pd.concat(frames, ignore_index=True)
    out.to_csv(RAW_DIR / "revenue.csv", index=False)
    log(f"月營收：{len(frames)} 檔，{len(out)} 筆")
    return True


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for f in RAW_DIR.glob("*.csv"):
        f.unlink()  # 清掉舊資料，避免混到舊版
    start_dt = date.today() - timedelta(days=int(C.BACKTEST_YEARS * 365.25) + C.FETCH_EXTRA_DAYS)
    start = start_dt.isoformat()
    log(f"抓取起日：{start}")

    ystatus = fetch_yahoo(start)
    # FinMind 營收需要多一點暖機（算年增率要前一年資料）
    fm_start = (start_dt - timedelta(days=400)).isoformat()
    margin_ok = fetch_margin(fm_start)
    codes = [c for c, _ in UNIVERSE if c not in ystatus["stocks_failed"]]
    rev_ok = fetch_revenue(fm_start, codes)

    meta = {
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "yahoo": ystatus,
        "finmind_margin": margin_ok,
        "finmind_revenue": rev_ok,
        "demo": False,
    }
    (RAW_DIR / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    log("完成")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        print(f"[fetch] 失敗：{e}", file=sys.stderr)
        sys.exit(1)
