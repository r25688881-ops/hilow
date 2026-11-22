"""讀取 data/raw（或 data/demo）→ 計算訊號與回測 → 輸出 result.json 與 result.js。"""
from __future__ import annotations

import json
import math
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

import numpy as np
import pandas as pd

import config as C
import signals as S
import stock_model as M
from universe import NAMES

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT


def log(msg: str) -> None:
    print(f"[backtest] {msg}", flush=True)


def _read_wide(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df.columns = df.columns.astype(str)
    return df.sort_index()


def load_raw(raw_dir: Path) -> dict:
    idx = pd.read_csv(raw_dir / "index.csv", index_col=0, parse_dates=True).sort_index()
    idx = idx[~idx.index.duplicated(keep="last")].dropna(subset=["close"])
    etf = None
    if (raw_dir / "etf0050.csv").exists():
        etf = pd.read_csv(raw_dir / "etf0050.csv", index_col=0, parse_dates=True)["close"].sort_index()
    margin = None
    if (raw_dir / "margin.csv").exists():
        m = pd.read_csv(raw_dir / "margin.csv", parse_dates=["date"]).set_index("date")["maintenance"]
        margin = m[~m.index.duplicated(keep="last")].sort_index()
    rev = None
    if (raw_dir / "revenue.csv").exists():
        rev = pd.read_csv(raw_dir / "revenue.csv", dtype={"stock_id": str})
    meta = json.loads((raw_dir / "meta.json").read_text(encoding="utf-8")) if (raw_dir / "meta.json").exists() else {}
    return {
        "index": idx,
        "etf": etf,
        "margin": margin,
        "rev": rev,
        "adj": _read_wide(raw_dir / "prices_adj.csv"),
        "raw": _read_wide(raw_dir / "prices_raw.csv"),
        "vol": _read_wide(raw_dir / "volume.csv"),
        "div": _read_wide(raw_dir / "dividends.csv"),
        "meta": meta,
    }


def clean(o):
    """轉成可 JSON 序列化的物件；NaN/inf → None。"""
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        v = float(o)
        return None if (math.isnan(v) or math.isinf(v)) else v
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (pd.Timestamp, datetime)):
        return o.strftime("%Y-%m-%d")
    return o


def _series_pack(s: pd.Series, nd: int = 4) -> list:
    return [None if v != v else round(float(v), nd) for v in s.values]


SPLIT_RATIOS = [1 / 10, 1 / 8, 1 / 6, 1 / 5, 1 / 4, 1 / 3, 1 / 2, 2, 3, 4, 5, 10]


def repair_splits(s: pd.Series, name: str, fixes: list) -> pd.Series:
    """修復「分割／減資未還原」造成的價格斷層。

    台股單日漲跌幅限制 10%，所以單日變動超過 25% 不可能是真實報酬。
    若變動倍數接近常見的分割比例（1/4、1/2、2 倍…，誤差 20% 內），就把斷層之前的價格乘上該比例接起來，
    斷層日剩下的小幅差異視為真實報酬。每一筆修正都會記錄並顯示在網頁上。
    """
    x = s.dropna()
    if len(x) < 3:
        return s
    r = x.pct_change()
    out = s.astype(float).copy()
    for d, v in r[r.abs() > 0.25].items():
        q = 1 + v
        if q <= 0:
            continue
        sr = min(SPLIT_RATIOS, key=lambda c: abs(math.log(q / c)))
        if abs(math.log(q / sr)) < math.log(1.2):
            out.loc[out.index < d] *= sr
            fixes.append({"name": name, "date": d.strftime("%Y-%m-%d"), "ratio": float(sr), "jump": float(v)})
    return out


def data_quality(D: dict, adj: pd.DataFrame, bench_raw: pd.Series, bench: pd.Series, fixes: list) -> dict:
    """掃描單日漲跌幅 > 15% 的資料點（台股漲跌幅限制 10%，超過多半是分割、減資或資料錯誤），並記錄基準最大回撤的位置。"""
    items = []

    def scan(name: str, s: pd.Series, skip: int = 0) -> None:
        # skip：個股前約一年的資料不檢查（可能是興櫃階段，沒有 10% 漲跌幅限制；選股也要滿 12 個月歷史才會用到）
        r = s.dropna().pct_change().dropna().iloc[skip:]
        for d, v in r[r.abs() > 0.15].items():
            items.append({"name": name, "date": d.strftime("%Y-%m-%d"), "ret": float(v)})

    scan("加權指數", D["index"]["close"])
    if D["etf"] is not None:
        scan("0050", D["etf"])
    for c in adj.columns:
        scan(f"{NAMES.get(c, c)}({c})", adj[c], skip=250)
    items.sort(key=lambda x: -abs(x["ret"]))

    dd = bench / bench.cummax() - 1
    t = dd.idxmin()
    pk = bench.loc[:t].idxmax()
    etf_mdd = {
        "peak": pk.strftime("%Y-%m-%d"), "trough": t.strftime("%Y-%m-%d"), "mdd": float(dd.min()),
        "peak_price": float(bench_raw.loc[pk]), "trough_price": float(bench_raw.loc[t]),
    }
    log(f"資料品質：單日變動 >15% 的資料點 {len(items)} 筆")
    for it in items[:15]:
        log(f"  {it['name']} {it['date']} {it['ret']:+.1%}")
    log(f"基準最大回撤 {etf_mdd['mdd']:.1%}：{etf_mdd['peak']}（{etf_mdd['peak_price']:.2f}）→ {etf_mdd['trough']}（{etf_mdd['trough_price']:.2f}）")
    log(f"自動修正價格斷層 {len(fixes)} 筆")
    for f in fixes[:15]:
        log(f"  {f['name']} {f['date']} 單日 {f['jump']:+.1%} → 以比例 {f['ratio']:.4g} 接合")
    return {"count": len(items), "top": items[:25], "etf_mdd": etf_mdd,
            "fix_count": len(fixes), "fixes": sorted(fixes, key=lambda f: -abs(f["jump"]))[:30]}


def run(raw_dir: Path, out_dir: Path = OUT_DIR) -> Path:
    D = load_raw(raw_dir)
    meta = D["meta"]
    fixes: list = []
    if D["etf"] is not None:
        D["etf"] = repair_splits(D["etf"], "0050", fixes)
    D["adj"] = D["adj"].apply(lambda col: repair_splits(col, f"{NAMES.get(col.name, col.name)}({col.name})", fixes))
    idx = D["index"]
    end = idx.index[-1]
    bt_start = end - pd.DateOffset(years=C.BACKTEST_YEARS)
    split = end - pd.DateOffset(years=C.OOS_YEARS)
    if idx.index[0] > bt_start - pd.Timedelta(days=300):
        log(f"警告：指數資料起點 {idx.index[0].date()} 不足 15 年 + 暖機，回測區間將縮短")
        bt_start = idx.index[0] + pd.Timedelta(days=300)
    log(f"資料截止 {end.date()}，回測起點 {bt_start.date()}，樣本內/外分界 {split.date()}")

    # ---------- 大盤訊號 ----------
    ind = S.build_indicators(idx, D["margin"])
    flags, brules, trules = S.compute_scores(ind)
    stats = S.signal_statistics(ind, flags, bt_start, split)
    stats["confirm"] = S.confirm_statistics(ind, flags, bt_start, split)
    etf = D["etf"] if D["etf"] is not None else idx["close"]
    timing = S.timing_strategy(ind, flags, etf, bt_start)
    state = S.current_state(ind, flags, brules, trules)
    log(f"目前大盤：底部分數 {state['bottom_score']}/{state['bottom_max']}，高點分數 {state['top_score']}/{state['top_max']}")

    win = ind.index >= bt_start
    index_chart = {
        "dates": [d.strftime("%Y-%m-%d") for d in ind.index[win]],
        "close": _series_pack(ind["close"][win], 2),
        "ma200": _series_pack(ind["ma200"][win], 2),
        "bottom_score": flags["bottom_score"][win].astype(int).tolist(),
        "top_score": flags["top_score"][win].astype(int).tolist(),
    }
    timing_metrics = {
        "strategy": M.metrics(timing["series"]),
        "buyhold": M.metrics(timing["bh_series"]),
        "strategy_oos": M.metrics(timing["series"].loc[split:]),
        "buyhold_oos": M.metrics(timing["bh_series"].loc[split:]),
        "trades": len(timing["trades"]),
    }
    timing_out = {k: timing[k] for k in ["dates", "equity", "buyhold", "trades"]}
    timing_out["metrics"] = timing_metrics

    # ---------- 個股 ----------
    adj, raw, vol, div = D["adj"], D["raw"], D["vol"], D["div"]
    common = adj.index.intersection(idx.index)
    adj, raw, vol, div = [x.reindex(common) for x in (adj, raw, vol, div)]
    P = M.Panels(adj, raw, vol, div, D["rev"])
    log(f"個股池 {adj.shape[1]} 檔；營收因子：{'啟用' if P.has_rev else '未啟用（無 FinMind 營收資料）'}")

    main = M.run_backtest(P, bt_start)
    eq = main["equity"]
    start_d = eq.index[0]
    bench_src = D["etf"] if D["etf"] is not None else idx["close"]
    bench = bench_src.reindex(common).ffill().loc[start_d:]
    bench = bench / bench.iloc[0]
    ew = M.equal_weight_benchmark(P, start_d)
    ew = ew / ew.iloc[0]
    ewp = M.pit_equal_weight(P, start_d, C.PIT_TOP)
    dates_common = eq.index.intersection(bench.index).intersection(ew.index).intersection(ewp.index)
    eq, bench, ew, ewp = eq.loc[dates_common], bench.loc[dates_common], ew.loc[dates_common], ewp.loc[dates_common]
    eq, bench, ew, ewp = eq / eq.iloc[0], bench / bench.iloc[0], ew / ew.iloc[0], ewp / ewp.iloc[0]
    dq = data_quality(D, adj, bench_src.reindex(common).ffill(), bench, fixes)

    def seg_metrics(s):
        return {"full": M.metrics(s), "is": M.metrics(s.loc[:split]), "oos": M.metrics(s.loc[split:])}

    stock_metrics = {
        "strategy": seg_metrics(eq),
        "benchmark": seg_metrics(bench),
        "equal_weight": seg_metrics(ew),
        "equal_weight_pit": seg_metrics(ewp),
        "turnover_annual": main["turnover_annual"],
    }

    sens = []
    for n in C.SENS_TOP_N:
        res = main if n == C.TOP_N else M.run_backtest(P, bt_start, top_n=n, keep_rank=max(2 * n, C.KEEP_RANK))
        e = res["equity"]
        m = M.metrics(e)
        sens.append({"top_n": n, "cagr": m.get("cagr"), "mdd": m.get("mdd"), "sharpe": m.get("sharpe"),
                     "oos_cagr": M.metrics(e.loc[split:]).get("cagr"), "turnover": res["turnover_annual"]})

    # ---- 降低存活者偏差：PIT 流動性過濾敏感度 + 隨機選股對照 ----
    pit_rows = []
    for n in C.PIT_SENS:
        res = main if n == C.PIT_TOP else M.run_backtest(P, bt_start, pit_top=n)
        e = res["equity"]
        pit_rows.append({"pit_top": n, "cagr": M.metrics(e).get("cagr"), "is_cagr": M.metrics(e.loc[:split]).get("cagr"),
                         "oos_cagr": M.metrics(e.loc[split:]).get("cagr"), "mdd": M.metrics(e).get("mdd")})
    log("隨機選股對照中…")
    rnd = M.random_pick_test(P, main, bt_start, split, pit_top=C.PIT_TOP)
    log(f"隨機選股對照完成（{C.RANDOM_SIMS} 次）")
    bias = {"pit_top": C.PIT_TOP, "sens": pit_rows, "random": rnd}

    picks = M.current_picks(P, main["holdings"])
    hist = []
    for h in main["history"][-12:][::-1]:
        hist.append({
            "date": h["date"],
            "holdings": [{"code": c, "name": NAMES.get(c, c)} for c in h["holdings"]],
            "bought": [NAMES.get(c, c) for c in h["bought"]],
            "sold": [NAMES.get(c, c) for c in h["sold"]],
        })

    stock_out = {
        "dates": [d.strftime("%Y-%m-%d") for d in eq.index],
        "equity": _series_pack(eq, 4),
        "benchmark": _series_pack(bench, 4),
        "equal_weight": _series_pack(ew, 4),
        "equal_weight_pit": _series_pack(ewp, 4),
        "bias": bias,
        "dd_strategy": _series_pack(M.drawdown(eq), 4),
        "dd_benchmark": _series_pack(M.drawdown(bench), 4),
        "metrics": stock_metrics,
        "sensitivity": sens,
        "picks": picks,
        "history": hist,
        "revenue_factor": P.has_rev,
    }

    result = {
        "meta": {
            "generated_at": datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y-%m-%d %H:%M"),
            "data_through": end.strftime("%Y-%m-%d"),
            "backtest_start": bt_start.strftime("%Y-%m-%d"),
            "oos_start": split.strftime("%Y-%m-%d"),
            "demo": bool(meta.get("demo", False)),
            "finmind_margin": bool(D["margin"] is not None),
            "finmind_revenue": bool(P.has_rev),
            "universe_size": int(adj.shape[1]),
            "data_quality": dq,
            "params": {
                "top_n": C.TOP_N, "keep_rank": C.KEEP_RANK, "factor_weights": C.FACTOR_WEIGHTS,
                "commission": C.COMMISSION * C.FEE_DISCOUNT, "tax_stock": C.TAX_STOCK, "tax_etf": C.TAX_ETF,
                "slippage": C.SLIPPAGE, "threshold": C.DEFAULT_THRESHOLD, "cooldown": C.COOLDOWN,
                "horizons": C.HORIZONS, "thresholds": C.THRESHOLDS, "oos_years": C.OOS_YEARS,
                "backtest_years": C.BACKTEST_YEARS, "pit_top": C.PIT_TOP, "random_sims": C.RANDOM_SIMS, "confirm_lookback": C.CONFIRM_LOOKBACK,
            },
        },
        "market": {"state": state, "chart": index_chart, "stats": stats, "timing": timing_out},
        "stocks": stock_out,
    }
    result = clean(result)

    out_dir.mkdir(parents=True, exist_ok=True)
    txt = json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    (out_dir / "result.json").write_text(txt, encoding="utf-8")
    # result.js 讓網頁可直接雙擊開啟（file:// 下 fetch 會被瀏覽器擋，<script> 不會）
    (out_dir / "result.js").write_text("window.RESULT = " + txt + ";\n", encoding="utf-8")
    log(f"已輸出 {out_dir / 'result.js'}（{len(txt) / 1024:.0f} KB）")
    return out_dir / "result.js"
