# 台股高低點訊號 × 個股選股回測 App

純靜態網頁（`index.html`）+ Python 回測。資料來源皆為免費：Yahoo Finance（價量、股利）、FinMind（融資維持率、月營收，選用）。

> ⚠ 目前 `result.js` 是**合成示範資料**（頁面頂端有黃色 DEMO 橫幅）。照下面步驟執行一次，就會換成真實資料。

## 部署到 GitHub（不需要上傳資料夾）

所有檔案都在最外層，只有一個檔案需要「建立在資料夾裡」。

1. 建立新的 GitHub repository。
2. **Add file → Upload files**，把解壓後的檔案全部選起來一次上傳（`.py`、`index.html`、`result.js`、圖示、`README.md` 等，共約 17 個，**不含資料夾**），按 Commit。
3. **建立工作流程檔**（GitHub 不能上傳隱藏資料夾，所以用手動建立）：
   Add file → **Create new file**，檔名欄輸入 `.github/workflows/update.yml`（輸入 `/` 會自動建立資料夾），貼上附檔 `update.yml` 的內容，Commit。
4. **Settings → Pages**：Source 選 *Deploy from a branch*，Branch 選 `main`、資料夾 **`/ (root)`**。
5. **Settings → Actions → General → Workflow permissions**：選 **Read and write permissions**，Save。
6. **Actions → update-backtest → Run workflow**，手動跑第一次（約 3~10 分鐘）。跑完會自動更新 `result.js`，網頁即換成真實資料；之後每個交易日台灣 15:30 自動更新。
7. （建議）到 [FinMind](https://finmindtrade.com/) 免費註冊取得 token，放進 Settings → Secrets and variables → Actions → New repository secret，名稱 `FINMIND_TOKEN`。

網址：`https://<你的帳號>.github.io/<repo 名稱>/`

## 手機安裝成 App

用手機瀏覽器開啟 Pages 網址 → 分享／選單 → **加入主畫面**，就會以專屬圖示全螢幕開啟。

## 本機執行

```bash
pip install -r requirements.txt
python run_all.py            # 抓真實資料 + 回測 → result.js
python run_all.py --demo     # 不連網，用合成資料測試
python run_all.py --skip-fetch   # 沿用已下載資料，只重跑回測（改參數時很快）
```
然後直接雙擊開啟 `index.html`（資料以 `<script>` 載入，file:// 也能用）。

## 專案結構（全部在最外層）

```
run_all.py            一鍵入口
config.py             所有參數（門檻、權重、成本、持股檔數）
universe.py           股票池（可自行增減）
fetch_data.py         抓 Yahoo / FinMind 資料
signals.py            大盤計分制訊號 + 事後統計 + 擇時策略
stock_model.py        多因子選股 + 月度再平衡回測 + 目前建議
pipeline.py           串接並輸出 result.js / result.json
demo_data.py          合成示範資料（只供測試）
index.html            前端（無外部套件）
result.js             回測結果（目前是示範資料，Actions 會覆蓋）
icon.svg / icon-*.png / manifest.webmanifest   App 圖示
PROMPT.md             提示詞集
.github/workflows/update.yml   每日自動更新（需手動建立，見上）
```

## 方法重點

- **大盤訊號**：底部 / 高點各 6 項指標（RSI、200 日乖離、距高點回落、KD、布林、融資維持率；高點另有 RSI 背離）。同時成立 ≥3 項才算警示。
- **驗證**：訊號收盤判定、隔日收盤進場，統計 20/60/120 日報酬，對照「任一天進場」基準，並拆樣本內（前 10 年）／樣本外（最近 5 年）。
- **選股**：動能 45% + 月營收年增 25% + 殖利率 15% + 低波動 15%，趨勢（還原價 > 200 日線）與流動性過濾，前 10 名等權重，月底決策、隔日成交，排名前 20 內續抱。
- **成本**：手續費 0.1425% 雙邊、證交稅 0.3%（ETF 0.1%）、滑價 0.1%。想用券商折扣請改 `config.py` 的 `FEE_DISCOUNT`。
- **不調參**：參數都是通用慣例值；網頁提供持股檔數敏感度表，檢查結果是否穩健。

## 重要限制

- **存活者偏差**：股票池是現在的大型股，回測績效偏樂觀。想降低偏差，請改成各年度歷史成分股。
- **訊號事件少**（15 年僅數十次且群聚），看「樣本外」與「基準對照」，不要只看勝率。
- 免費資料可能缺漏；FinMind 抓不到時程式會自動略過並在頁首標示。
- 本專案的抓資料程式（Yahoo / FinMind）在開發環境無法連網，**只用合成資料測試過完整流程**；首次在 GitHub 執行時請看 Actions 日誌是否有 `[fetch]` 警告。
- 僅供研究與教學，**不是投資建議**。
