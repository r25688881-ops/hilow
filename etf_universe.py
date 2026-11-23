"""ETF 清單（主動型 23 檔台股型 + 被動型 8 檔）。

主動型清單與上市日期來源：經理人「2026 主動式 ETF 一覽」（資料日 2026-10-27）。
被動型清單為常見的大型 ETF，是否仍在交易以 Yahoo 實際抓到的資料為準（抓不到會在網頁標示）。
「分類」是依名稱做的簡易歸類，不是官方分類。Yahoo 代碼：上市 .TW。
"""

ETFS = [
    # ---- 被動型 ----
    {"code": "0050", "name": "元大台灣50", "kind": "passive", "style": "市值型"},
    {"code": "006208", "name": "富邦台50", "kind": "passive", "style": "市值型"},
    {"code": "0056", "name": "元大高股息", "kind": "passive", "style": "高股息"},
    {"code": "00878", "name": "國泰永續高股息", "kind": "passive", "style": "高股息"},
    {"code": "00919", "name": "群益台灣精選高息", "kind": "passive", "style": "高股息"},
    {"code": "00929", "name": "復華台灣科技優息", "kind": "passive", "style": "高股息"},
    {"code": "00940", "name": "元大台灣價值高息", "kind": "passive", "style": "高股息"},
    {"code": "00713", "name": "元大台灣高息低波", "kind": "passive", "style": "高息低波"},
    # ---- 主動型（依上市日排序）----
    {"code": "00980A", "name": "主動野村臺灣優選", "kind": "active", "style": "成長", "listed": "2025-05-05"},
    {"code": "00982A", "name": "主動群益台灣強棒", "kind": "active", "style": "成長", "listed": "2025-05-22"},
    {"code": "00981A", "name": "主動統一台股增長", "kind": "active", "style": "成長", "listed": "2025-05-27"},
    {"code": "00984A", "name": "主動安聯台灣高息", "kind": "active", "style": "高息", "listed": "2025-07-14"},
    {"code": "00985A", "name": "主動野村台灣50", "kind": "active", "style": "核心50", "listed": "2025-07-21"},
    {"code": "00991A", "name": "主動復華未來50", "kind": "active", "style": "核心50", "listed": "2025-12-18"},
    {"code": "00987A", "name": "主動台新優勢成長", "kind": "active", "style": "成長", "listed": "2025-12-30"},
    {"code": "00992A", "name": "主動群益科技創新", "kind": "active", "style": "科技", "listed": "2025-12-30"},
    {"code": "00994A", "name": "主動第一金台股優", "kind": "active", "style": "成長", "listed": "2026-01-07"},
    {"code": "00995A", "name": "主動中信台灣卓越", "kind": "active", "style": "成長", "listed": "2026-01-22"},
    {"code": "00993A", "name": "主動安聯台灣", "kind": "active", "style": "成長", "listed": "2026-02-03"},
    {"code": "00996A", "name": "主動兆豐台灣豐收", "kind": "active", "style": "高息", "listed": "2026-03-25"},
    {"code": "00400A", "name": "主動國泰動能高息", "kind": "active", "style": "高息", "listed": "2026-04-09"},
    {"code": "00401A", "name": "主動摩根台灣鑫收", "kind": "active", "style": "高息", "listed": "2026-04-10"},
    {"code": "00999A", "name": "主動野村臺灣高息", "kind": "active", "style": "高息", "listed": "2026-05-05"},
    {"code": "00403A", "name": "主動統一升級50", "kind": "active", "style": "核心50", "listed": "2026-05-12"},
    {"code": "00404A", "name": "主動聯博動能50", "kind": "active", "style": "核心50", "listed": "2026-06-09"},
    {"code": "00405A", "name": "主動富邦台灣龍耀", "kind": "active", "style": "成長", "listed": "2026-06-09"},
    {"code": "00406A", "name": "主動中信台灣收益", "kind": "active", "style": "高息", "listed": "2026-06-11"},
    {"code": "00407A", "name": "主動凱基台灣", "kind": "active", "style": "成長", "listed": "2026-06-24"},
    {"code": "00410A", "name": "主動永豐科技趨勢", "kind": "active", "style": "科技", "listed": "2026-08-03"},
    {"code": "00408A", "name": "主動第一金優股息", "kind": "active", "style": "高息", "listed": "2026-07-15"},
    {"code": "00415A", "name": "主動群益核心50", "kind": "active", "style": "核心50", "listed": "2026-10-20"},
]

ETF_NAMES = {e["code"]: e["name"] for e in ETFS}


def etf_symbol(code: str) -> str:
    return f"{code}.TW"
