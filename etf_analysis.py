"""ETF 比較分析（主動型 vs 被動型）。只做「比較與描述」，不產生買賣時機訊號。

重點
  - 各 ETF 用「還原價」（含配息再投入）計算報酬、波動、最大回撤。
  - 歷史很短的 ETF（尤其是 2025 年後上市的主動型）只給「累積報酬」，不年化，並標示歷史長度。
  - 共同期間比較：所有在 ETF_COMMON_CUTOFF 之前上市的 ETF，從「最晚上市者」的第一天起一起比，才是公平比較。
  - 與 0050 同期間比較，避免用不同期間的數字互相比。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config as C
from etf_universe import ETFS

TD = C.TRADING_DAYS


def _grade(days: int) -> str:
    if days < 180:
        return "不足（未滿 6 個月）"
    if days < 365:
        return "偏短（未滿 1 年）"
    if days < 1095:
        return "尚短（未滿 3 年）"
    return "較完整（3 年以上）"


def _risk(adj: pd.Series) -> dict:
    r = adj.pct_change().dropna()
    vol = float(r.std() * np.sqrt(TD)) if len(r) >= 40 else None
    mdd = float((adj / adj.cummax() - 1).min()) if len(adj) >= 5 else None
    return {"vol": vol, "mdd": mdd, "ret": float(adj.iloc[-1] / adj.iloc[0] - 1) if len(adj) >= 2 else None}


def _cagr(adj: pd.Series):
    days = (adj.index[-1] - adj.index[0]).days
    if days < 365 or adj.iloc[0] <= 0:
        return None
    return float((adj.iloc[-1] / adj.iloc[0]) ** (365.25 / days) - 1)


def _gap_freq(d: pd.Series) -> str:
    gaps = np.diff(d.index.values[-7:]).astype("timedelta64[D]").astype(float)  # 最近最多 6 個間隔，反映「目前」的頻率
    g = float(np.median(gaps))
    if g < 45:
        return "月配"
    if g < 135:
        return "季配"
    if g < 270:
        return "半年配"
    return "年配"


def _freq(d: pd.Series, days: int, declared: str | None) -> tuple[str, str]:
    """配息頻率：有 3 次以上配息 → 用最近幾次的間隔（能反映頻率有沒有改過）；
    歷史滿 1 年但配息很少 → 用次數；歷史未滿 1 年且配息不足 → 用公告值。回傳 (頻率, 來源：實際／公告／不明)。"""
    d = d[d > 0].sort_index()
    if len(d) >= 3:
        return _gap_freq(d), "實際"
    if days >= 365:
        return {0: "不配息", 1: "年配", 2: "半年配"}[len(d)], "實際"
    if len(d) == 2:
        return _gap_freq(d), "實際"
    if declared:
        return declared, "公告"
    return "不明", "不明"


def analyze(adj: pd.DataFrame, raw: pd.DataFrame, div: pd.DataFrame, failed: list, fixes: list) -> dict:
    meta = {e["code"]: e for e in ETFS}
    ok_codes = [e["code"] for e in ETFS if e["code"] in adj.columns and adj[e["code"]].dropna().shape[0] >= C.ETF_MIN_DAYS]
    bench = adj["0050"].dropna() if "0050" in adj.columns else None
    end = adj.index.max()

    rows = []
    for code in ok_codes:
        m = meta[code]
        s = adj[code].dropna()
        first, last = s.index[0], s.index[-1]
        days = (last - first).days
        k = _risk(s)
        row = {
            "code": code, "name": m["name"], "kind": m["kind"], "style": m["style"],
            "first": first.strftime("%Y-%m-%d"), "last": last.strftime("%Y-%m-%d"),
            "months": round(days / 30.44, 1), "grade": _grade(days),
            "cum": k["ret"], "cagr": _cagr(s), "vol": k["vol"], "mdd": k["mdd"],
            "cur_dd": float(s.iloc[-1] / s.cummax().iloc[-1] - 1),
            "cagr5": None, "sharpe": None, "corr": None, "ex": None, "ex_cagr": None,
        }
        if days >= 5 * 365:
            row["cagr5"] = _cagr(s.loc[last - pd.Timedelta(days=int(5 * 365.25)):])
        if row["cagr"] is not None and k["vol"]:
            row["sharpe"] = float((row["cagr"] - C.RF) / k["vol"])
        # 殖利率（近 365 天配息 ÷ 最新價）；歷史不滿一年者只含已發生的配息，標示 partial
        d = div[code].dropna() if code in div.columns else pd.Series(dtype=float)
        d = d[d.index > last - pd.Timedelta(days=365)]
        d = d[d > 0]
        px = raw[code].dropna().iloc[-1] if code in raw.columns and raw[code].notna().any() else np.nan
        row["yld"] = float(d.sum() / px) if px == px and px > 0 else None
        row["ndiv"] = int(len(d))
        row["freq"], row["freq_src"] = _freq(d, days, m.get("freq"))
        row["yld_partial"] = days < 365
        # 與 0050 比較（同一期間）
        if bench is not None and code != "0050":
            b = bench.loc[first:last]
            if len(b) >= 20:
                row["ex"] = None if row["cum"] is None else float(row["cum"] - (b.iloc[-1] / b.iloc[0] - 1))
                bc = _cagr(b)
                if bc is not None and row["cagr"] is not None:
                    row["ex_cagr"] = float(row["cagr"] - bc)
            both = pd.concat([s.pct_change(), bench.pct_change()], axis=1, join="inner").dropna()
            if len(both) >= 60:
                row["corr"] = float(both.corr().iloc[0, 1])
        rows.append(row)

    # ---- 共同期間（公平比較）----
    cut = pd.Timestamp(C.ETF_COMMON_CUTOFF)
    elig = [r for r in rows if pd.Timestamp(r["first"]) <= cut]
    common = None
    if len(elig) >= 2:
        cstart = max(pd.Timestamp(r["first"]) for r in elig)
        crow = {}
        for r in elig:
            s = adj[r["code"]].dropna().loc[cstart:]
            if len(s) >= 20:
                k = _risk(s)
                crow[r["code"]] = {"ret": k["ret"], "vol": k["vol"], "mdd": k["mdd"]}
        for r in rows:
            r["common"] = crow.get(r["code"])
        b = crow.get("0050")
        act = [crow[r["code"]]["ret"] for r in elig if r["kind"] == "active" and r["code"] in crow]
        summary = {"start": cstart.strftime("%Y-%m-%d"), "end": end.strftime("%Y-%m-%d"),
                   "months": round((end - cstart).days / 30.44, 1), "n_active": len(act),
                   "n_passive": len([r for r in elig if r["kind"] == "passive" and r["code"] in crow])}
        if b is not None and act:
            summary["bench_ret"] = b["ret"]
            summary["n_beat"] = int(sum(1 for x in act if x > b["ret"]))
            summary["median_excess"] = float(np.median([x - b["ret"] for x in act]))
        common = summary
    else:
        for r in rows:
            r["common"] = None

    new_active = [r["code"] for r in rows if r["kind"] == "active" and pd.Timestamp(r["first"]) > cut]
    return {
        "as_of": end.strftime("%Y-%m-%d"),
        "rows": rows,
        "common": common,
        "failed": failed,
        "fixes": fixes,
        "new_active": new_active,
        "cutoff": C.ETF_COMMON_CUTOFF,
    }
