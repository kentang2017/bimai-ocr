# 筆脈 BiMai — Chaosu OCR 工作台

**把古籍、尺牘、書法的直排草書書影，轉成可編輯的電子文字。**
瀏覽器工作台 + 命令列，接上 llama.cpp 的視覺語言模型（Qwen3-VL-8B 草書微調版）。

> **模型權重請到 HuggingFace 下載：**
> **[kinyeah/BiMai-Chaoshu-OCR](https://huggingface.co/kinyeah/BiMai-Chaoshu-OCR)**
> 建議使用 `caoshu-v16-merged-Q4_K_M.gguf` + `caoshu-v16-merged-mmproj-F16.gguf`（單檔合併版，免 `--lora`）。
> 實測：40 欄無污染金樣 **字準 72.2%、CER 27.8%**；工整行草與常用字可達 76–100%。

---

## 一、安裝

```bash
# 1) 取得本專案
git clone <本 repo> && cd BiMai-Chaoshu-OCR

# 2) 安裝 Python 依賴（只需 Pillow）
pip install -r requirements.txt

# 3) 取得模型（見上方 HuggingFace 連結），放到任意目錄，例如 ./models/
#    caoshu-v16-merged-Q4_K_M.gguf
#    caoshu-v16-merged-mmproj-F16.gguf
```

並準備 **llama.cpp**（需含多模態 mmproj 支援）：
<https://github.com/ggml-org/llama.cpp>（自行編譯或使用官方 release）

---

## 二、啟動

### 1. 啟動推論引擎
```bash
llama-server \
  -m models/caoshu-v16-merged-Q4_K_M.gguf \
  --mmproj models/caoshu-v16-merged-mmproj-F16.gguf \
  --host 127.0.0.1 --port 8800 --ctx-size 8192 --jinja
```

### 2. 開工作台
```bash
python3 -m mochiocr.gui --port 8810
```
瀏覽器打開 **<http://127.0.0.1:8810>**

> 若你的書影放在別的位置，可用 `BIMAI_ROOT` 指定工作根目錄（預設為本專案資料夾）：
> `BIMAI_ROOT=/data/books python3 -m mochiocr.gui --port 8810`

---

## 三、工作台怎麼用

### ① 讀入書籍 —— 五種方式都支援
| 方式 | 操作 | 說明 |
|---|---|---|
| **PDF** | 路徑欄貼上 `.pdf` → 按〔載入〕 | 自動轉頁（每頁一張圖） |
| **圖片資料夾** | 路徑欄貼上資料夾 → 〔載入〕 | 資料夾內所有圖片依序成頁 |
| **單一圖片** | 路徑欄貼上 `.jpg/.png/.tif/.webp` → 〔載入〕 | 一張圖一頁 |
| **網址圖片** | 貼 `https://…/xxx.jpg` → 〔載入網址圖〕 | 會加入成目前這本書的下一頁 |
| **本機檔案** | 〔加入本機圖片檔案〕→ 選檔（可多選） | 手機拍照、別台電腦的圖都行 |

### ② 頁面與辨識
- 點縮圖選頁 → 按〔**辨識此頁**〕
- 進度條顯示「辨識中 N/總欄數 · 平均秒數 · 目前第幾欄」
- GPU 上約 **1 秒／欄**；一頁 10 欄約 10–30 秒

### ③ 逐欄校對（核心）
每一欄顯示：
```
[原圖裁切]
欄 @x402 ⚠ 待校        ← 候選讀法不一致時標紅；一致時顯示「· 候選一致」
┌──────────────┐
│春風吹白蘋醉上碧岩堯│  ← 可直接編輯（直書輸入框）
└──────────────┘
其他可能讀法（點選採用）：
 [春風吹白蘋醉上碧岩毫]   ← 一鍵替換
 [春風吹白鷴醉上碧岩毫]
      [標記已確認]
```
- 頁面上方統計：`本頁 12 欄 · ✓ 已確認 3 · ⚠ 待校 5`
- 勾選「**待校欄位排最前**」→ 只把可疑欄位排到最前面，快速掃過
- 全部確認後統計列變綠字「本頁已校完」

### ④ 匯出
- 〔儲存校對〕：把目前這頁的文字寫入結果檔
- 〔匯出全書文字〕：下載整本書的純文字（各頁自動串接）

---

## 四、命令列（批次）

```bash
# 整本 PDF → 文字（不需開工作台）
python3 -m mochiocr pdf2text 某古籍.pdf -o 輸出目錄 --backend http://127.0.0.1:8800/v1

# 只跑前 3 頁、限制長邊 4200px
python3 -m mochiocr pdf2text 某古籍.pdf -o out --pages 1-3 --max-side 4200

# 檢查引擎是否就緒
python3 -m mochiocr serve --check
```

---

## 五、運作原理

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

## 六、提示詞

與模型訓練時一致（`ocrclient.py` 內建）：
```
只根據圖中可見筆畫逐字釋讀。禁止默寫唐詩或名帖全文。只輸出你確實看見的繁體字，看不清就停。
```
輸入建議：單一縱向裁切圖，短邊 ≥ 300px、長邊 ≤ 3200px。

---

## 七、目錄結構

```
mochiocr/
├─ gui.py          網頁工作台（:8810）— 逐欄校對、替代讀法、待校標記、匯出
├─ cli.py          命令列：pdf2text / serve
├─ segment.py      直列偵測（投影法、切分、跨欄處理）
├─ pdfrender.py    PDF → 頁面圖
├─ ocrclient.py    VLM 辨識客戶端（OpenAI 相容 /chat/completions）
├─ assemble.py     逐欄組稿
├─ cer.py          LCS 字準與 CER
└─ ensemble.py     多樣本置信度加權投票（實驗性質，可用於交叉檢查）
```

---

## 八、常見問題

| 症狀 | 處理 |
|---|---|
| 工作台按鈕沒反應 | 強制重新整理（Ctrl+F5）；狀態列會顯示頁面錯誤訊息 |
| 顯示「引擎沒有回應」 | 先啟動 `llama-server`（見二、1），確認 `http://127.0.0.1:8800/health` 回應 ok |
| 網址圖載入失敗 | 該站可能擋外連（403/404），或不是圖片格式；改用本機檔案上傳 |
| 一頁只辨識出很少欄 | 書影解析度太低、或該頁非直排；可提高 `--max-side` 或先裁切 |
| 某些欄整段亂碼 | 狂草／連筆嚴重或拓本；建議人工校對或先確認是否為雙行夾註版式 |

---

## 九、授權

- **程式碼**：MIT（見 `LICENSE`）
- **模型權重**：取自 [HuggingFace](https://huggingface.co/kinyeah/BiMai-Chaoshu-OCR)，
  沿用基底 `Qwen/Qwen3-VL-8B-Instruct` 授權條款
- 辨識結果僅供研究與輔助，**出版或引用前請務必人工校對**

---

## English

**BiMai — Chaosu OCR Workbench**: turn vertical cursive (*caoshu*) pages of classical Chinese
books and calligraphy into editable text, using a QLoRA-finetuned **Qwen3-VL-8B** served by llama.cpp.

**Model weights → [kinyeah/BiMai-Chaoshu-OCR](https://huggingface.co/kinyeah/BiMai-Chaoshu-OCR)**
(recommended: `caoshu-v16-merged-Q4_K_M.gguf` + `caoshu-v16-merged-mmproj-F16.gguf`).
Clean-holdout results: **72.2% character accuracy / 27.8% CER**; neat semi-cursive reaches 76–100%.

**Run**
```bash
llama-server -m models/caoshu-v16-merged-Q4_K_M.gguf \
  --mmproj models/caoshu-v16-merged-mmproj-F16.gguf \
  --host 127.0.0.1 --port 8800 --ctx-size 8192 --jinja
python3 -m mochiocr.gui --port 8810   # open http://127.0.0.1:8810
```

Load a PDF, an image folder, a single image path, an image URL, or local files; click
**辨識此頁 / Recognise this page**; then review column by column. Each column shows the crop,
the transcription, **two alternative readings (one-click swap)**, and a ⚠ flag when candidates
disagree — so a human reviewer only has to look at the uncertain columns. Export the whole book as plain text.

Code MIT. Weights follow the base model licence. Always proofread before publication.