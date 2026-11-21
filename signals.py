"""大盤高低點「計分制」反轉訊號 + 事後統計驗證。

設計原則
  * 單一指標不可靠，所以用多個獨立面向的指標「同時成立幾項」來計分。
  * 不宣稱「預測」，只回答：這種訊號出現後，未來 N 日的勝率與平均報酬，比隨便一天好多少？
  * 訊號在「收盤」判定，統計報酬從「下一個交易日收盤」起算（避免前視偏差）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config as C


# ------------------------- 指標 -------------------------

def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    au = up.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    ad = down.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = au / ad.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.where(ad != 0, 100.0).where(au.notna())


def build_indicators(idx: pd.DataFrame, margin: pd.Series | None) -> pd.DataFrame:
    c, h, l = idx["close"], idx["high"], idx["low"]
    o = pd.DataFrame(index=idx.index)
    o["close"] = c
    o["ma200"] = c.rolling(200, min_periods=200).mean()
    o["bias200"] = c / o["ma200"] - 1
    o["rsi14"] = rsi(c, 14)

    ll, hh = l.rolling(9, min_periods=9).min(), h.rolling(9, min_periods=9).max()
    rsv = (c - ll) / (hh - ll).replace(0, np.nan) * 100
    o["k"] = rsv.ewm(alpha=1 / 3, adjust=False).mean()
    o["d"] = o["k"].ewm(alpha=1 / 3, adjust=False).mean()

    ma20, sd20 = c.rolling(20, min_periods=20).mean(), c.rolling(20, min_periods=20).std()
    o["pctb"] = (c - (ma20 - 2 * sd20)) / (4 * sd20).replace(0, np.nan)

    o["dd252"] = c / c.rolling(252, min_periods=120).max() - 1

    hi60 = c.rolling(60, min_periods=60).max()
    rsi_hi60 = o["rsi14"].rolling(60, min_periods=60).max()
    o["divergence"] = ((c >= hi60 * 0.98) & (o["rsi14"] < rsi_hi60 - 8)).astype(float)
    o.loc[hi60.isna() | rsi_hi60.isna(), "divergence"] = np.nan

    if margin is not None and len(margin) > 0:
        m = margin.reindex(idx.index).ffill()
        o["margin"] = m
        o["margin_pct"] = m.rolling(C.MARGIN_PCT_WINDOW, min_periods=250).apply(
            lambda x: float((x[-1] >= x).mean()), raw=True
        )
    return o


# ------------------------- 計分規則 -------------------------

BOTTOM_RULES = [
    ("rsi", f"RSI(14) < {C.RSI_LOW}（超賣）", lambda d: d["rsi14"] < C.RSI_LOW),
    ("bias", f"收盤低於 200 日線 {abs(C.BIAS200_LOW):.0%} 以上", lambda d: d["bias200"] < C.BIAS200_LOW),
    ("dd", f"較一年高點回落超過 {abs(C.DD252_LOW):.0%}", lambda d: d["dd252"] < C.DD252_LOW),
    ("kd", f"KD 的 K 值 < {C.K_LOW}", lambda d: d["k"] < C.K_LOW),
    ("boll", "收盤跌破布林通道下軌", lambda d: d["pctb"] < 0),
    ("margin", "融資維持率處於近 3 年低檔（≤10 百分位）", lambda d: d["margin_pct"] <= C.MARGIN_PCT_LOW),
]
TOP_RULES = [
    ("rsi", f"RSI(14) > {C.RSI_HIGH}（超買）", lambda d: d["rsi14"] > C.RSI_HIGH),
    ("bias", f"收盤高於 200 日線 {C.BIAS200_HIGH:.0%} 以上", lambda d: d["bias200"] > C.BIAS200_HIGH),
    ("kd", f"KD 的 K 值 > {C.K_HIGH}", lambda d: d["k"] > C.K_HIGH),
    ("boll", "收盤突破布林通道上軌", lambda d: d["pctb"] > 1),
    ("div", "價格近 60 日高點但 RSI 背離（動能轉弱）", lambda d: d["divergence"] == 1),
    ("margin", "融資維持率處於近 3 年高檔（≥90 百分位）", lambda d: d["margin_pct"] >= C.MARGIN_PCT_HIGH),
]


def compute_scores(ind: pd.DataFrame) -> tuple[pd.DataFrame, list, list]:
    has_margin = "margin_pct" in ind.columns
    brules = [r for r in BOTTOM_RULES if has_margin or r[0] != "margin"]
    trules = [r for r in TOP_RULES if has_margin or r[0] != "margin"]
    flags = pd.DataFrame(index=ind.index)
    for key, _, fn in brules:
        flags[f"b_{key}"] = fn(ind).fillna(False).astype(int)
    for key, _, fn in trules:
        flags[f"t_{key}"] = fn(ind).fillna(False).astype(int)
    flags["bottom_score"] = flags[[c for c in flags.columns if c.startswith("b_")]].sum(axis=1)
    flags["top_score"] = flags[[c for c in flags.columns if c.startswith("t_")]].sum(axis=1)
    return flags, brules, trules


# ------------------------- 事件與驗證 -------------------------

def detect_events(score: pd.Series, thr: int, cooldown: int) -> list[int]:
    """分數由 <thr 升到 >=thr 的那一天算一次事件；兩次事件至少間隔 cooldown 個交易日。"""
    active = (score.values >= thr)
    events, last = [], -10**9
    for i in range(1, len(active)):
        if active[i] and not active[i - 1] and i - last >= cooldown:
            events.append(i)
            last = i
    return events


def forward_returns(close: np.ndarray, pos: int, horizons: list[int]) -> dict[int, float]:
    """訊號日收盤後，下一個交易日收盤進場，持有 h 個交易日。"""
    out = {}
    for h in horizons:
        e, x = pos + 1, pos + 1 + h
        out[h] = close[x] / close[e] - 1 if x < len(close) else np.nan
    return out


def _agg(vals: list[float], bearish: bool) -> dict:
    a = np.array([v for v in vals if v == v], dtype=float)
    if len(a) == 0:
        return {"n": 0, "win": None, "mean": None, "median": None}
    win = (a < 0).mean() if bearish else (a > 0).mean()
    return {"n": int(len(a)), "win": float(win), "mean": float(a.mean()), "median": float(np.median(a))}


def signal_statistics(ind: pd.DataFrame, flags: pd.DataFrame, bt_start: pd.Timestamp, split: pd.Timestamp) -> dict:
    close = ind["close"].values
    dates = ind.index
    valid = dates >= bt_start
    out: dict = {"baseline": {}, "bottom": {}, "top": {}, "events": []}

    # 基準：回測期間內「任一天」進場的未來報酬
    for seg, mask in [("all", valid), ("is", valid & (dates <= split)), ("oos", valid & (dates > split))]:
        out["baseline"][seg] = {}
        for h in C.HORIZONS:
            rets = [forward_returns(close, i, [h])[h] for i in np.where(mask)[0]]
            out["baseline"][seg][str(h)] = {
                "bottom": _agg(rets, bearish=False),
                "top": _agg(rets, bearish=True),
            }

    for kind, col, bearish in [("bottom", "bottom_score", False), ("top", "top_score", True)]:
        for thr in C.THRESHOLDS:
            ev = [i for i in detect_events(flags[col], thr, C.COOLDOWN) if valid[i]]
            seg_stats = {}
            for seg in ["all", "is", "oos"]:
                if seg == "all":
                    sel = ev
                elif seg == "is":
                    sel = [i for i in ev if dates[i] <= split]
                else:
                    sel = [i for i in ev if dates[i] > split]
                seg_stats[seg] = {
                    str(h): _agg([forward_returns(close, i, [h])[h] for i in sel], bearish) for h in C.HORIZONS
                }
                seg_stats[seg]["count"] = len(sel)
            out[kind][str(thr)] = seg_stats
            if thr == C.DEFAULT_THRESHOLD:
                for i in ev:
                    fr = forward_returns(close, i, C.HORIZONS)
                    out["events"].append(
                        {
                            "date": dates[i].strftime("%Y-%m-%d"),
                            "type": kind,
                            "score": int(flags[col].iloc[i]),
                            "close": float(close[i]),
                            **{f"fwd{h}": (None if fr[h] != fr[h] else float(fr[h])) for h in C.HORIZONS},
                        }
                    )
    out["events"].sort(key=lambda e: e["date"])
    return out


# ------------------------- 大盤擇時策略（用 0050 當交易標的） -------------------------

def timing_strategy(ind: pd.DataFrame, flags: pd.DataFrame, etf_close: pd.Series, bt_start: pd.Timestamp) -> dict:
    """起始持有；高點訊號出現→次日收盤賣出；底部訊號出現→次日收盤買回。"""
    thr = C.DEFAULT_THRESHOLD
    buy_ev = set(detect_events(flags["bottom_score"], thr, C.COOLDOWN))
    sell_ev = set(detect_events(flags["top_score"], thr, C.COOLDOWN))

    px = etf_close.reindex(ind.index).ffill()
    dates = ind.index
    start_i = int(np.searchsorted(dates, bt_start))
    buy_cost = (C.COMMISSION * C.FEE_DISCOUNT) + C.SLIPPAGE
    sell_cost = (C.COMMISSION * C.FEE_DISCOUNT) + C.TAX_ETF + C.SLIPPAGE

    holding, pending = True, None
    eq, bh, trades = [], [], []
    v, v_bh = 1.0, 1.0
    for i in range(start_i, len(dates)):
        if i > start_i:
            r = px.iloc[i] / px.iloc[i - 1] - 1
            if holding:
                v *= 1 + r
            v_bh *= 1 + r
        if pending == "sell" and holding:
            v *= 1 - sell_cost
            holding = False
            trades.append({"date": dates[i].strftime("%Y-%m-%d"), "action": "sell"})
        elif pending == "buy" and not holding:
            v *= 1 - buy_cost
            holding = True
            trades.append({"date": dates[i].strftime("%Y-%m-%d"), "action": "buy"})
        pending = None
        eq.append(v)
        bh.append(v_bh)
        if i in sell_ev and holding:
            pending = "sell"
        elif i in buy_ev and not holding:
            pending = "buy"
    d = dates[start_i:]
    return {
        "dates": [x.strftime("%Y-%m-%d") for x in d],
        "equity": np.round(eq, 5).tolist(),
        "buyhold": np.round(bh, 5).tolist(),
        "trades": trades,
        "series": pd.Series(eq, index=d),
        "bh_series": pd.Series(bh, index=d),
    }


# ------------------------- 目前狀態 -------------------------

def current_state(ind: pd.DataFrame, flags: pd.DataFrame, brules: list, trules: list) -> dict:
    last = ind.index[-1]
    row_i, row_f = ind.iloc[-1], flags.iloc[-1]
    bs, ts = int(row_f["bottom_score"]), int(row_f["top_score"])
    thr = C.DEFAULT_THRESHOLD
    if bs >= thr and bs > ts:
        status = "bottom"
    elif ts >= thr and ts > bs:
        status = "top"
    elif bs >= thr and ts >= thr:
        status = "mixed"
    else:
        status = "neutral"

    def last_event(col):
        evs = detect_events(flags[col], thr, C.COOLDOWN)
        if not evs:
            return None
        i = evs[-1]
        return {"date": ind.index[i].strftime("%Y-%m-%d"), "days_ago": int(len(ind) - 1 - i)}

    def num(x):
        return None if x != x else float(x)

    return {
        "date": last.strftime("%Y-%m-%d"),
        "close": float(row_i["close"]),
        "status": status,
        "threshold": thr,
        "bottom_score": bs,
        "top_score": ts,
        "bottom_max": len(brules),
        "top_max": len(trules),
        "bottom_flags": [{"key": k, "label": lab, "on": bool(row_f[f"b_{k}"])} for k, lab, _ in brules],
        "top_flags": [{"key": k, "label": lab, "on": bool(row_f[f"t_{k}"])} for k, lab, _ in trules],
        "last_bottom_event": last_event("bottom_score"),
        "last_top_event": last_event("top_score"),
        "indicators": {
            "rsi14": num(row_i["rsi14"]),
            "bias200": num(row_i["bias200"]),
            "dd252": num(row_i["dd252"]),
            "k": num(row_i["k"]),
            "d": num(row_i["d"]),
            "pctb": num(row_i["pctb"]),
            "margin": num(row_i["margin"]) if "margin" in ind.columns else None,
            "margin_pct": num(row_i["margin_pct"]) if "margin_pct" in ind.columns else None,
        },
    }
