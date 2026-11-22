"""個股多因子選股 + 月度再平衡回測 + 目前建議清單。

流程
  月底收盤計算因子排名 → 下一個交易日收盤執行交易（避免前視偏差）
  買進：趨勢向上（還原價 > 200 日線）、流動性足夠、綜合分數最高的前 TOP_N 檔（等權重）
  賣出：已持有者若排名掉出前 KEEP_RANK 名，或跌破 200 日線，下個月底換股
  成本：手續費 + 證交稅 + 滑價（見 config.py）
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config as C
from universe import NAMES


# ------------------------- 績效指標 -------------------------

def metrics(eq: pd.Series) -> dict:
    eq = eq.dropna()
    if len(eq) < 30:
        return {}
    r = (eq / eq.shift(1) - 1).dropna()
    days = (eq.index[-1] - eq.index[0]).days
    total = float(eq.iloc[-1] / eq.iloc[0])
    cagr = total ** (365.25 / days) - 1 if days > 0 and total > 0 else float("nan")
    vol = float(r.std() * np.sqrt(C.TRADING_DAYS))
    sharpe = float((r.mean() * C.TRADING_DAYS - C.RF) / vol) if vol > 0 else float("nan")
    mdd = float((eq / eq.cummax() - 1).min())
    calmar = float(cagr / abs(mdd)) if mdd < 0 else float("nan")
    return {
        "start": eq.index[0].strftime("%Y-%m-%d"),
        "end": eq.index[-1].strftime("%Y-%m-%d"),
        "total": total - 1,
        "cagr": float(cagr),
        "vol": vol,
        "sharpe": sharpe,
        "mdd": mdd,
        "calmar": calmar,
    }


def drawdown(eq: pd.Series) -> pd.Series:
    return eq / eq.cummax() - 1


# ------------------------- 因子面板 -------------------------

def _build_rev_panel(rev: pd.DataFrame | None, index: pd.DatetimeIndex, cols) -> pd.DataFrame | None:
    """月營收年增率（近 3 個月均值）。公布時點保守取「次月 11 日」之後才可使用，避免前視偏差。"""
    if rev is None or len(rev) == 0:
        return None
    r = rev.copy()
    r["m"] = pd.to_datetime(
        {"year": r["revenue_year"].astype(int), "month": r["revenue_month"].astype(int), "day": 1}
    )
    piv = r.pivot_table(index="m", columns="stock_id", values="revenue", aggfunc="last").sort_index()
    piv = piv.reindex(pd.date_range(piv.index.min(), piv.index.max(), freq="MS"))
    yoy = (piv / piv.shift(12) - 1).clip(-1, 5)
    yoy3 = yoy.rolling(3, min_periods=2).mean()
    yoy3.index = yoy3.index + pd.DateOffset(months=1) + pd.Timedelta(days=10)
    full = yoy3.reindex(yoy3.index.union(index)).sort_index().ffill(limit=75).reindex(index)
    return full.reindex(columns=cols)


class Panels:
    def __init__(self, adj, raw, vol, div, rev):
        self.adj, self.raw = adj, raw
        self.ret = adj / adj.shift(1) - 1
        self.mom12 = adj.shift(21) / adj.shift(252) - 1
        self.mom6 = adj.shift(21) / adj.shift(126) - 1
        self.ma200 = adj.rolling(200, min_periods=200).mean()
        self.vol60 = self.ret.rolling(60, min_periods=40).std() * np.sqrt(C.TRADING_DAYS)
        self.tv60 = (raw * vol).rolling(60, min_periods=40).mean()
        self.dy = div.fillna(0).rolling("365D").sum() / raw
        self.rev = _build_rev_panel(rev, adj.index, adj.columns)
        self.has_rev = self.rev is not None
        self._cache: dict = {}


def snapshot(P: Panels, t: pd.Timestamp, pit_top="default") -> pd.DataFrame:
    """pit_top：只允許「當時」60 日成交值排名前 N 的股票入選（降低存活者偏差）。None＝不限制。"""
    if pit_top == "default":
        pit_top = C.PIT_TOP
    if t not in P._cache:
        P._cache[t] = _snapshot_base(P, t)
    df = P._cache[t].copy()
    if pit_top and len(df):
        rank = df["tv60"].rank(ascending=False, method="first")
        df["eligible"] = df["eligible"] & (rank <= pit_top)
    return df


def _snapshot_base(P: Panels, t: pd.Timestamp) -> pd.DataFrame:
    df = pd.DataFrame(
        {
            "close": P.raw.loc[t],
            "adj": P.adj.loc[t],
            "ma200": P.ma200.loc[t],
            "mom12": P.mom12.loc[t],
            "mom6": P.mom6.loc[t],
            "dy": P.dy.loc[t],
            "vol60": P.vol60.loc[t],
            "tv60": P.tv60.loc[t],
            "rev": P.rev.loc[t] if P.has_rev else np.nan,
        }
    )
    df = df[df["mom12"].notna() & df["mom6"].notna() & df["adj"].notna()].copy()
    if df.empty:
        df["score"] = []
        df["eligible"] = []
        return df

    pr = lambda s: s.rank(pct=True)  # noqa: E731
    F = pd.DataFrame(index=df.index)
    F["momentum"] = 0.5 * pr(df["mom12"]) + 0.5 * pr(df["mom6"])
    F["revenue"] = pr(df["rev"]) if P.has_rev else np.nan
    F["dividend"] = pr(df["dy"])
    F["lowvol"] = pr(-df["vol60"])
    w = pd.Series(C.FACTOR_WEIGHTS)[F.columns]
    mask = F.notna()
    df["score"] = 100 * (F.fillna(0) * w).sum(axis=1) / (mask * w).sum(axis=1)
    df["eligible"] = (df["adj"] > df["ma200"]) & (df["tv60"] >= C.MIN_AVG_TURNOVER)
    df["above_ma200"] = df["adj"] > df["ma200"]
    return df


# ------------------------- 回測 -------------------------

def month_end_dates(days: pd.DatetimeIndex) -> pd.DatetimeIndex:
    g = days.to_series().groupby([days.year, days.month]).max()
    out = pd.DatetimeIndex(g.values)
    if len(out) and (out[-1] + pd.offsets.BDay(1)).month == out[-1].month:
        out = out[:-1]  # 最後一個月尚未結束，不算月底
    return out


def run_backtest(P: Panels, bt_start: pd.Timestamp, top_n: int = C.TOP_N, keep_rank: int = C.KEEP_RANK, pit_top="default", score_fn=None) -> dict:
    days = P.adj.index
    start_i = int(np.searchsorted(days, bt_start))
    rebal = set(month_end_dates(days[start_i:]))
    buy_rate = C.COMMISSION * C.FEE_DISCOUNT + C.SLIPPAGE
    sell_rate = C.COMMISSION * C.FEE_DISCOUNT + C.TAX_STOCK + C.SLIPPAGE

    pos: dict[str, float] = {}
    cash = 1.0
    pending: list[str] | None = None
    holdings: list[str] = []
    started = False
    eq_d, eq_v, turnovers, history = [], [], [], []

    for i in range(start_i, len(days)):
        t = days[i]
        if pos:
            r = P.ret.iloc[i]
            for k in pos:
                v = r.get(k, np.nan)
                if v == v:
                    pos[k] *= 1 + v

        if pending is not None:
            total = cash + sum(pos.values())
            tgt = total / top_n
            buy = sell = 0.0
            for k in set(pos) | set(pending):
                cur, goal = pos.get(k, 0.0), (tgt if k in pending else 0.0)
                if goal > cur:
                    buy += goal - cur
                else:
                    sell += cur - goal
            total2 = total - (buy * buy_rate + sell * sell_rate)
            each = total2 / top_n
            pos = {k: each for k in pending}
            cash = total2 - each * len(pending)
            turnovers.append((buy + sell) / 2 / total)
            pending = None
            started = True

        if started:
            eq_d.append(t)
            eq_v.append(cash + sum(pos.values()))

        if t in rebal:
            snap = snapshot(P, t, pit_top)
            if score_fn is not None and len(snap):
                snap["score"] = score_fn(snap)
            ranked = snap[snap["eligible"]].sort_values("score", ascending=False)
            erank = ranked["score"].rank(ascending=False, method="first")
            keep = [h for h in holdings if h in ranked.index and erank[h] <= keep_rank]
            fill = [c for c in ranked.index if c not in keep][: max(top_n - len(keep), 0)]
            new = keep + fill
            history.append(
                {
                    "date": t.strftime("%Y-%m-%d"),
                    "holdings": new,
                    "bought": [c for c in new if c not in holdings],
                    "sold": [c for c in holdings if c not in new],
                }
            )
            holdings = new
            pending = list(new)

    eq = pd.Series(eq_v, index=pd.DatetimeIndex(eq_d))
    years = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-9) if len(eq) else 1
    return {
        "equity": eq,
        "history": history,
        "holdings": holdings,
        "turnover_annual": float(np.sum(turnovers) / years) if turnovers else 0.0,
    }


def equal_weight_benchmark(P: Panels, start: pd.Timestamp) -> pd.Series:
    r = P.ret.loc[start:].iloc[1:].mean(axis=1, skipna=True)
    return (1 + r.fillna(0)).cumprod()


def pit_equal_weight(P: Panels, start: pd.Timestamp, pit_top) -> pd.Series:
    """同條件等權重基準：每月底取「當時」60 日成交值前 N 名等權重持有。
    換股成本以「新進名單占比 × 買賣費率」估計（與策略同一套費率），讓它能和策略公平比較。"""
    days = P.adj.index
    si = int(np.searchsorted(days, start))
    rebal = list(month_end_dates(days[si:]))
    pos_of = {d: i for i, d in enumerate(days)}
    r_all = P.ret
    buy_rate = C.COMMISSION * C.FEE_DISCOUNT + C.SLIPPAGE
    sell_rate = C.COMMISSION * C.FEE_DISCOUNT + C.TAX_STOCK + C.SLIPPAGE
    vals, idx = [], []
    cur, prev = 1.0, set()
    for k, t in enumerate(rebal):
        i = pos_of[t]
        end_i = pos_of[rebal[k + 1]] + 1 if k + 1 < len(rebal) else len(days) - 1
        if i + 1 >= len(days):
            break
        tv = snapshot(P, t, None)["tv60"].dropna()
        if len(tv) == 0:
            continue
        names = list(tv.sort_values(ascending=False).index[: pit_top or len(tv)])
        frac_new = len(set(names) - prev) / max(len(names), 1)
        frac_out = len(prev - set(names)) / max(len(prev), 1) if prev else 0.0
        cost = frac_new * buy_rate + frac_out * sell_rate
        if not vals:
            cur *= 1 - cost
            vals.append(cur); idx.append(days[i + 1])
        else:
            cur *= 1 - cost
            vals[-1] = cur
        prev = set(names)
        for j in range(i + 2, min(end_i, len(days) - 1) + 1):
            rr = r_all.iloc[j][names].mean(skipna=True)
            cur *= 1 + (0.0 if rr != rr else rr)
            vals.append(cur); idx.append(days[j])
    return pd.Series(vals, index=pd.DatetimeIndex(idx))


def random_pick_test(P: Panels, main: dict, bt_start: pd.Timestamp, split: pd.Timestamp,
                     sims: int = C.RANDOM_SIMS, seed: int = C.RANDOM_SEED, pit_top="default",
                     top_n: int = C.TOP_N, keep_rank: int = C.KEEP_RANK) -> dict:
    """隨機選股對照：用「完全相同」的回測引擎（同合格名單、同續抱規則、同成本），
    只把因子分數換成隨機數，重複 sims 次，看策略的實際績效落在隨機分布的哪裡。"""
    def seg_cagr(eq):
        return {"full": M_cagr(eq), "is": M_cagr(eq.loc[:split]), "oos": M_cagr(eq.loc[split:])}

    def M_cagr(eq):
        return metrics(eq).get("cagr", float("nan"))

    strat = seg_cagr(main["equity"])
    rows = {"full": [], "is": [], "oos": []}
    for k in range(sims):
        rng = np.random.default_rng(seed + k)
        res = run_backtest(P, bt_start, top_n=top_n, keep_rank=keep_rank, pit_top=pit_top,
                           score_fn=lambda s, rng=rng: pd.Series(rng.random(len(s)) * 100, index=s.index))
        sc = seg_cagr(res["equity"])
        for key in rows:
            rows[key].append(sc[key])
    out = {"sims": sims}
    for key, vals in rows.items():
        v = np.array([x for x in vals if x == x])
        if len(v) < 10 or strat[key] != strat[key]:
            out[key] = None
            continue
        out[key] = {"strategy": float(strat[key]), "random_median": float(np.median(v)),
                    "random_p90": float(np.percentile(v, 90)), "percentile": float((v < strat[key]).mean())}
    return out


# ------------------------- 目前建議 -------------------------

def _row(code: str, r: pd.Series, rank: int | None, action: str, reason: str = "") -> dict:
    def f(x, nd=4):
        return None if x != x else round(float(x), nd)

    return {
        "code": code,
        "name": NAMES.get(code, code),
        "rank": rank,
        "action": action,
        "reason": reason,
        "close": f(r["close"], 2),
        "score": f(r["score"], 1),
        "mom12": f(r["mom12"]),
        "mom6": f(r["mom6"]),
        "rev": f(r["rev"]),
        "dy": f(r["dy"]),
        "vol": f(r["vol60"]),
        "bias200": f(r["adj"] / r["ma200"] - 1) if r["ma200"] == r["ma200"] else None,
    }


def current_picks(P: Panels, prev_holdings: list[str], top_n: int = C.TOP_N, keep_rank: int = C.KEEP_RANK) -> dict:
    t = P.adj.index[-1]
    snap = snapshot(P, t)
    ranked = snap[snap["eligible"]].sort_values("score", ascending=False)
    erank = ranked["score"].rank(ascending=False, method="first")

    buy = []
    for code in ranked.index[:top_n]:
        action = "續抱" if code in prev_holdings else "買進"
        buy.append(_row(code, snap.loc[code], int(erank[code]), action))

    sell = []
    for code in prev_holdings:
        if code not in snap.index:
            continue
        row = snap.loc[code]
        if code in ranked.index and erank[code] <= keep_rank:
            continue
        if not bool(row["above_ma200"]):
            why = "跌破 200 日線，趨勢轉弱"
        elif code in ranked.index:
            why = f"綜合排名掉到第 {int(erank[code])} 名（門檻 {keep_rank}）"
        else:
            why = "流動性或資料條件不符"
        sell.append(_row(code, row, int(erank[code]) if code in erank.index else None, "賣出", why))

    worst = snap.sort_values("score").head(10)
    avoid = [_row(code, worst.loc[code], None, "避開", "綜合分數墊底") for code in worst.index]

    return {
        "as_of": t.strftime("%Y-%m-%d"),
        "buy": buy,
        "sell": sell,
        "avoid": avoid,
        "universe_size": int(len(snap)),
        "eligible_size": int(len(ranked)),
    }
