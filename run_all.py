"""一鍵執行。

  python run_all.py            # 抓真實資料 → 回測 → 產生 result.js
  python run_all.py --demo     # 用合成示範資料（不連網），僅供測試介面
  python run_all.py --skip-fetch   # 沿用 data/raw 已下載的資料，只重跑回測
"""
import argparse
import sys
from pathlib import Path

import demo_data, fetch_data, pipeline

ROOT = Path(__file__).resolve().parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="使用合成示範資料")
    ap.add_argument("--skip-fetch", action="store_true", help="不重新下載資料")
    a = ap.parse_args()

    if a.demo:
        raw_dir = demo_data.generate()
    else:
        raw_dir = ROOT / "data" / "raw"
        if not a.skip_fetch:
            fetch_data.main()
    pipeline.run(raw_dir)
    print("完成。請用瀏覽器開啟 index.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
