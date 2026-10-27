<div align="center">

<img src="assets/hero.jpg" alt="筆脈 BiMai — 草書與放大鏡" width="100%">

# 筆脈 BiMai · Chaosu OCR 工作台

**把古籍、尺牘、書法的直排草書書影，轉成可編輯的電子文字。**

<sub>瀏覽器工作台 ＋ 命令列，接上 llama.cpp 的視覺語言模型（Qwen3-VL-8B 草書微調版）</sub>

[![Model](https://img.shields.io/badge/model-HuggingFace%20BiMai--Chaoshu--OCR-ff9d00?logo=huggingface&logoColor=white)](https://huggingface.co/kinyeah/BiMai-Chaoshu-OCR)
[![Runtime](https://img.shields.io/badge/runtime-llama.cpp-2f6f4e)](https://github.com/ggml-org/llama.cpp)
[![Python](https://img.shields.io/badge/python-3.9%2B-3776ab?logo=python&logoColor=white)](https://www.python.org/)
[![Licence](https://img.shields.io/badge/licence-MIT-1f6feb)](LICENSE)

| 基準（40 欄、331 字、無污染） | 原版 Qwen3-VL-8B | **筆脈 v16** | 改善 |
|:--|:--:|:--:|:--:|
| 字準 Accuracy | 64.4% | **72.2%** | **+7.8 pt** |
| **錯字率 CER** | 35.6% | **27.8%** | **−21.9%（相對）** |

</div>

---

## ⚡ 30 秒上手 · Quick Start

```bash
# 1) 取得本專案
git clone <本 repo> && cd BiMai-Chaoshu-OCR
pip install -r requirements.txt          # 只需 Pillow

# 2) 到 HuggingFace 下載模型（兩個檔案）
#    https://huggingface.co/kinyeah/BiMai-Chaoshu-OCR
#    caoshu-v16-merged-Q4_K_M.gguf       4.7 GB
#    caoshu-v16-merged-mmproj-F16.gguf   1.1 GB

# 3) 啟動推論引擎（單檔，免 --lora）
llama-server -m models/caoshu-v16-merged-Q4_K_M.gguf \
  --mmproj models/caoshu-v16-merged-mmproj-F16.gguf \
  --host 127.0.0.1 --port 8800 --ctx-size 8192 --jinja

# 4) 開工作台
python3 -m mochiocr.gui --port 8810
#    瀏覽器打開 http://127.0.0.1:8810
```

> 需要 [llama.cpp](https://github.com/ggml-org/llama.cpp)（含多模態 mmproj 支援，自行編譯或用官方 release）。
> 書影放在別的位置時：`BIMAI_ROOT=/data/books python3 -m mochiocr.gui --port 8810`

---

## 🧭 工作台怎麼用

### ① 讀入書籍 —— 五種方式
| 方式 | 操作 | 說明 |
|:--|:--|:--|
| **PDF** | 路徑欄貼上 `.pdf` →〔載入〕 | 自動轉頁，每頁一張圖 |
| **圖片資料夾** | 貼資料夾路徑 →〔載入〕 | 資料夾內圖片依序成頁 |
| **單一圖片** | 貼 `.jpg/.png/.tif/.webp` →〔載入〕 | 一張圖一頁 |
| **網址圖片** | 貼 `https://…/x.jpg` →〔載入網址圖〕 | 加入成這本書的下一頁 |
| **本機檔案** |〔加入本機圖片檔案〕→ 選檔（可多選） | 手機拍照、別台電腦的圖都行 |

### ② 逐欄辨識
點縮圖選頁 →〔**辨識此頁**〕。進度條顯示 `辨識中 N/總欄數 · 平均秒數 · 目前第幾欄`。
GPU 上約 **1 秒／欄**，一頁 10 欄約 10–30 秒。

### ③ 逐欄校對（核心）

```
[ 原圖裁切 ]
欄 @x402  ⚠ 待校                    ← 候選不一致時標紅；一致時顯示「· 候選一致」
┌──────────────────┐
│ 春風吹白蘋醉上碧岩堯 │              ← 可直接編輯（直書輸入框）
└──────────────────┘
其他可能讀法（點選採用）：
  [ 春風吹白蘋醉上碧岩毫 ]            ← 一鍵替換
  [ 春風吹白鷴醉上碧岩毫 ]
        [ 標記已確認 ]
```

- 頁面上方統計：`本頁 12 欄 · ✓ 已確認 3 · ⚠ 待校 5`
- 勾選「**待校欄位排最前**」→ 只把可疑欄位排到最前面，快速掃過
- 全部確認後統計列變綠字「本頁已校完」

### ④ 匯出
-〔儲存校對〕：把目前這頁寫入結果檔
-〔匯出全書文字〕：下載整本書純文字（各頁自動串接）

---

## 📊 為什麼有效 · Benchmarks

基準 `gold_test40`：40 欄手工核對、331 字、**無污染**（訓練流程內建守門，洩漏必須為 0）。
量測：貪婪解碼（`temperature=0`）、同一提示詞、同一裁切圖、LCS 逐欄 CER。

| 模型 | 字準 | **CER** | 逐欄中位 | ≥80% 欄 | <50% 欄 |
|:--|--:|--:|--:|:--:|:--:|
| 原版 `Qwen3-VL-8B-Instruct`（無 LoRA） | 64.4% | 35.6% | 65.2 | 9 / 40 | 9 / 40 |
| 筆脈 v8（首次微調） | 65.3% | 34.7% | — | — | — |
| **筆脈 v16（本專案採用）** | **72.2%** | **27.8%** | **75.0** | **13 / 40** | **4 / 40** |

> 微調把**錯字率從 35.6% 壓到 27.8%**（相對 −21.9%）；讀得很差的欄位由 9 欄降到 4 欄。
> 改善集中在**生僻字與連筆字**，並抑制原版「默寫名帖／跳字成句」的傾向。

<details>
<summary><b>🔬 深入：候選集上界（oracle）與為什麼要人工挑選</b></summary>

每欄取 10 個樣本、**取其中最好的一條**可達 **CER 22.19%（字準 77.8%）**——
正確讀法多半已在模型分佈中，缺的是「挑出正確那條」的選擇器。

實測並排除四種自動選擇器：

| 選擇器 | 結果 |
|:--|:--|
| 置信度加權投票 | 27.5%（噪聲內，無顯著增益） |
| 取最高置信度樣本 | 受控實驗 −1.2 pt，正式管線無效 |
| 4-gram 語言模型重排 | **+1.8 pt（有害）** |
| 跨模型集成（v13/v14/v16） | **+2.8 pt（有害）** |
| LLM 當驗證器 | **+1.6 pt（有害）** |

**這就是工作台存在的理由**：不追求全自動，而是把「兩條替代讀法」攤在眼前，
讓人只花一秒做對選擇——把 oracle 的上界轉化成實際效率。

</details>

---

## 🔧 運作原理

```
書影／PDF
   │  pdftoppm（pdfrender.py）
   ▼
頁面圖 ── 直列偵測（segment.py：投影法 + 切分）──▶ 單欄長條
   │
   ▼
Qwen3-VL-8B + 草書 LoRA（llama.cpp，ocrclient.py）
   │
   ▼
逐欄文字 ── 組稿（assemble.py）──▶ 校對工作台 / TXT
```

**為什麼要切成單欄？** 整頁直接餵給模型，模型容易「默寫名帖全文」或跳行漏字；
一欄一條是最穩定的粒度，也讓錯誤可定位、可校對。

---

## 💻 命令列（批次）

```bash
# 整本 PDF → 文字（不開工作台）
python3 -m mochiocr pdf2text 某古籍.pdf -o 輸出目錄 --backend http://127.0.0.1:8800/v1

# 只跑前 3 頁、限制長邊 4200px
python3 -m mochiocr pdf2text 某古籍.pdf -o out --pages 1-3 --max-side 4200

# 檢查引擎是否就緒
python3 -m mochiocr serve --check
```

---

## 📁 目錄結構

```
mochiocr/
├─ gui.py          網頁工作台（:8810）— 逐欄校對、替代讀法、待校標記、匯出
├─ cli.py          命令列：pdf2text / serve
├─ segment.py      直列偵測（投影法、切分、跨欄處理）
├─ pdfrender.py    PDF → 頁面圖
├─ ocrclient.py    VLM 辨識客戶端（OpenAI 相容 /chat/completions）
├─ assemble.py     逐欄組稿
├─ cer.py          LCS 字準與 CER
└─ ensemble.py     多樣本置信度加權投票（實驗性質）
```

> 模型權重不隨本 repo 散佈，請由 [HuggingFace](https://huggingface.co/kinyeah/BiMai-Chaoshu-OCR) 下載。

---

## ❓ 常見問題

| 症狀 | 處理 |
|:--|:--|
| 工作台按鈕沒反應 | 強制重新整理（Ctrl+F5）；狀態列會顯示頁面錯誤訊息 |
| 顯示「引擎沒有回應」 | 先啟動 `llama-server`，確認 `http://127.0.0.1:8800/health` 回應 ok |
| 網址圖載入失敗 | 該站可能擋外連（403/404）或非圖片格式；改用本機檔案上傳 |
| 一頁只辨識出很少欄 | 書影解析度太低或非直排；提高 `--max-side` 或先裁切 |
| 某些欄整段亂碼 | 狂草／連筆嚴重或拓本；建議人工校對，或確認是否為雙行夾註版式 |

---

## ⚠️ 已知限制

| 情境 | 表現 |
|:--|:--|
| 工整行草、常用字 | 良好（76–100% 字準） |
| **狂草、連筆嚴重** | 錯誤率明顯上升，務必人工校對 |
| **拓本**（碑帖黑白拓片） | 未支援 |
| **雙行夾註**版式 | 未支援 |
| **印刷體**古籍 | 非訓練風域（可用但非特化） |

> 辨識結果僅供研究與輔助，**出版或學術引用前請務必人工校對**。

---

## 📄 授權 · Licence

- **程式碼**：MIT（見 [`LICENSE`](LICENSE)）
- **模型權重**：由 [HuggingFace 模型頁](https://huggingface.co/kinyeah/BiMai-Chaoshu-OCR) 提供，
  沿用基底 `Qwen/Qwen3-VL-8B-Instruct` 授權條款（Apache-2.0 兼容）

---

<details>
<summary><b>🇬🇧 English</b></summary>

**BiMai — Chaosu OCR Workbench**: turn vertical cursive (*caoshu*) pages of classical Chinese books
and calligraphy into editable text, using a QLoRA-finetuned **Qwen3-VL-8B** served by llama.cpp.

**Model weights → [kinyeah/BiMai-Chaoshu-OCR](https://huggingface.co/kinyeah/BiMai-Chaoshu-OCR)**
(recommended: `caoshu-v16-merged-Q4_K_M.gguf` + `caoshu-v16-merged-mmproj-F16.gguf`).

**Results** on a clean 40-column holdout: **72.2% character accuracy / 27.8% CER**
vs 64.4% / 35.6% for the un-finetuned base model — a **21.9% relative CER reduction**.

**Run**
```bash
llama-server -m models/caoshu-v16-merged-Q4_K_M.gguf \
  --mmproj models/caoshu-v16-merged-mmproj-F16.gguf \
  --host 127.0.0.1 --port 8800 --ctx-size 8192 --jinja
python3 -m mochiocr.gui --port 8810    # open http://127.0.0.1:8810
```

Load a PDF, an image folder, a single image path, an image URL, or local files; click
**辨識此頁 / Recognise this page**; then review column by column. Each column shows the crop,
the transcription, **two alternative readings (one-click swap)**, and a ⚠ flag when candidates
disagree — so a human reviewer only needs to look at the uncertain columns. Export the whole book as plain text.

Code MIT. Weights follow the base model licence. Always proofread before publication.

</details>
