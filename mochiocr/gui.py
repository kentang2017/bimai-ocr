#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MochiOCR GUI v5 — 筆脈 BiMai · Chaoshu OCR 工作台（全新整併版：v2 主體 + 網址圖 + 進度視覺化）"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qsl, unquote

ROOT = Path(os.environ.get("BIMAI_ROOT") or Path(__file__).resolve().parent.parent)
WS = ROOT / "mochiocr" / "gui_workspace"
WS.mkdir(parents=True, exist_ok=True)

JOBS: dict[str, dict] = {}
DEF_BACKEND = "http://127.0.0.1:8800/v1"


def save_job(job_id):
    d = WS / job_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "book.json").write_text(json.dumps(JOBS[job_id], ensure_ascii=False, indent=1),
                                 encoding="utf-8")


def load_jobs():
    for f in WS.glob("*/book.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            JOBS[d["id"]] = d
        except Exception:
            pass


load_jobs()


def latest_job_id():
    files = sorted(WS.glob("*/book.json"), key=lambda x: x.stat().st_mtime, reverse=True)
    if not files:
        return None
    return json.loads(files[0].read_text(encoding="utf-8"))["id"]


def _edit(a, b):
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
        prev = cur
    return prev[-1]


def unc_of(text, alts):
    if not alts:
        return 0.0
    best = min(_edit(text or "", a or "") / max(len(text or ""), 1) for a in alts)
    return round(min(1.0, best), 3)


def ocr_page(job_id, page_index):
    try:
        from PIL import Image
        from mochiocr.segment import detect_columns, crop_strip
        from mochiocr import ocrclient
        from mochiocr.ocrclient import DEFAULT_PROMPT
        meta = JOBS[job_id]
        st = meta["status"]
        st.update(page=page_index, stage="segment", n_cols=None, cols_done=0, msg="分欄中…", error="")
        save_job(job_id)
        page = Image.open(meta["pages"][page_index]["path"]).convert("RGB")
        page.thumbnail((meta["max_side"], meta["max_side"]))
        segs = detect_columns(page, verbose=False).strips
        cols_map = {}
        for s_ in segs:
            cols_map.setdefault(s_.x0, []).append(s_)
        ordered = sorted(cols_map, key=lambda x: -x)
        cols = []
        for x0 in ordered:
            parts = sorted(cols_map[x0], key=lambda s_: s_.y0)
            cols.append({"x0": x0,
                         "tiles": [{"x0": s_.x0, "y0": s_.y0, "x1": s_.x1, "y1": s_.y1,
                                    "tile": s_.tile_i, "n": s_.parts} for s_ in parts],
                         "text": ""})
        if not cols:
            st.update(stage="done", msg="此頁未偵測到直列", n_cols=0)
            save_job(job_id); return
        st.update(stage="ocr", n_cols=len(cols), cols_done=0, cur_col=1, msg="辨識中…")
        save_job(job_id)
        crops = []
        for c in cols:
            t0 = c["tiles"][0]
            cr = type("S", (), t0)()
            crops.append(crop_strip(page, cr, side=3100))
        for ci, (c, crop) in enumerate(zip(cols, crops)):
            t0 = time.time()
            try:
                c["text"] = ocrclient.chat_ocr_robust(meta["backend"], meta["model"],
                                                      crop, prompt=DEFAULT_PROMPT, max_tokens=260)
                c["ok"] = 1
                # 另取兩條替代讀法（不同種子/溫度），供人工一鍵切換
                alts = []
                for k in range(2):
                    try:
                        t = ocrclient.clean_text(ocrclient.chat_ocr(
                            meta["backend"], meta["model"], crop,
                            prompt=DEFAULT_PROMPT, temperature=0.7,
                            max_tokens=260))
                    except Exception:
                        t = ""
                    if t and t != c["text"] and t not in alts and not ocrclient.degenerated(t):
                        alts.append(t)
                c["alts"] = alts[:2]
                c["unc"] = unc_of(c["text"], c["alts"])
                c["ck"] = False
            except Exception as e:
                c["text"] = ""
                st.update(error="引擎連線失敗：%s" % e)
            c["secs"] = round(time.time() - t0)
            secs_list = [xx.get("secs", 0) for xx in cols[:ci + 1] if xx.get("secs")]
            st.update(cols_done=ci + 1, cur_col=ci + 1,
                      avg_secs=(round(sum(secs_list) / len(secs_list)) if secs_list else None),
                      msg="第 %d/%d 欄 ok（%ss）" % (ci + 1, len(cols), c["secs"]))
            save_job(job_id)
        meta["pages"][page_index]["columns"] = cols
        st.update(stage="done", msg="完成；請校對後按「儲存校對」",
                  n_cols=len(cols), cols_done=len(cols), error=st.get("error", ""))
        save_job(job_id)
    except Exception as e:
        m = JOBS.get(job_id)
        if m:
            m["status"].update(stage="error", error="%s: %s" % (type(e).__name__, e))
            save_job(job_id)


def new_job(source):
    return {"id": str(uuid.uuid4())[:8], "source": source, "pages": [],
            "backend": DEF_BACKEND, "model": "default", "max_side": 3200,
            "status": {"stage": "boot", "msg": "", "error": ""}}


PAGE_TMPL = """<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<title>筆脈 BiMai — Chaoshu OCR 工作台 (v5)</title><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
 body{font-family:"Noto Serif TC","Microsoft JhengHei",serif;background:#efe9dc;margin:0;padding:16px;color:#2a2419}
 .card{background:#fffdf6;border:1px solid #d8cdb4;border-radius:10px;padding:12px 16px;margin-bottom:14px}
 h1{font-size:19px;margin:2px 0 10px} h2{font-size:14px;margin:0 0 8px;color:#5a4a2f}
 input,button,textarea{font-family:inherit}
 input,button{font-size:14px;padding:6px 10px;border:1px solid #b7a987;border-radius:6px;background:#fff}
 button{cursor:pointer;background:#7a6234;color:#fff;border:none}
 button:disabled{opacity:.35;cursor:default}
 textarea{font-size:15px;border:1px solid #b7a987;border-radius:6px;background:#fffdf6}
 .thumbs{display:flex;gap:8px;flex-wrap:wrap}
 .thumbs .w{cursor:pointer;text-align:center;font-size:11px;color:#8a7a5a}
 .thumbs img{height:120px;border:2px solid transparent;border-radius:4px;display:block}
 .thumbs .cur img{border-color:#a05a2c;background:#fff}
 .cols{display:flex;flex-direction:row-reverse;justify-content:flex-start;overflow-x:auto;gap:12px;padding-bottom:8px}
 .col{min-width:200px;background:#faf6ea;border:1px solid #c9bb9c;border-radius:8px;padding:8px}
 .col img.crop{height:430px;display:block;margin:0 auto 6px;background:#fff}
 .col textarea{width:100%;height:210px;box-sizing:border-box;
   writing-mode:vertical-rl;text-orientation:upright;line-height:1.7}
 .meta{font-size:11px;color:#8a7a5a;text-align:center}
 .bar{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
 #status{min-height:22px;font-size:14px;color:#4a442f}
 #full{white-space:pre-wrap;background:#f6f1e4;border:1px solid #d8cdb4;border-radius:6px;
   padding:10px;max-height:300px;overflow:auto;font-size:14px}
 .hint{font-size:12px;color:#8a7a5a;margin-top:6px}
 .prog{height:12px;background:#e6dcc6;border-radius:6px;overflow:hidden;margin:8px 0;position:relative;flex:1;min-width:200px}
 .prog-fill{height:100%;width:0%;background:linear-gradient(90deg,#a06a2c,#c99b53);transition:width .5s}
 .prog-fill.run::after{content:"";position:absolute;inset:0;
   background:linear-gradient(105deg,transparent 40%,rgba(255,255,255,.45) 50%,transparent 60%);
   animation:sweep 1.1s linear infinite}
 @keyframes sweep{from{transform:translateX(-100%)}to{transform:translateX(100%)}}
 .prog-text{font-size:12px;color:#6a5c40;min-width:190px}
 .col.running{animation:pulse 1.4s ease-in-out infinite;border-color:#c99b53}
 .col.queued{opacity:.45}
 @keyframes pulse{50%{background:#f5ecd7}}
 .spin{display:inline-block;width:12px;height:12px;border:2px solid #a06a2c;border-top-color:transparent;
   border-radius:50%;vertical-align:-2px;animation:rot 0.8s linear infinite;margin-right:5px}
 @keyframes rot{to{transform:rotate(360deg)}}
 .okmark{color:#3a7d2c;font-weight:bold}
 .alts{margin-top:6px;display:flex;flex-direction:column;gap:4px}
 .altlab{font-size:11px;color:#8a7a5a}
 .alt{font-size:12px;padding:3px 6px;background:#f2ead6;color:#5a4a2f;border:1px solid #cbbd9c;
      border-radius:5px;cursor:pointer;text-align:left;direction:rtl}
 .alt:hover{background:#e8dcc0}
 .alt.on{background:#a06a2c;color:#fff;border-color:#a06a2c}
 .warn{color:#b3541e;font-weight:bold}
 .soft{color:#a89a76}
 .ckbtn{margin-top:6px;font-size:11px;padding:3px 8px;background:#f2ead6;color:#5a4a2f;
        border:1px solid #cbbd9c;border-radius:5px;cursor:pointer}
 .ckbtn.on{background:#3a7d2c;color:#fff;border-color:#3a7d2c}
</style></head><body>
<h1>筆脈 BiMai · Chaoshu OCR 工作台 <span style="font-size:11px;color:#b06a9a">UI v5</span></h1>
<div class="card"><h2>① 讀入書籍</h2>
 <div class="bar">
   <input id="path" style="flex:1;min-width:280px"
          placeholder="PDF／單一圖片（jpg/png/tif）／圖片資料夾路徑，例：/media/kinyeah/本機磁碟/書/頁1.jpg"/>
   <button id="loadBtn" onclick="loadBook()">載入</button>
   <button id="lastBtn" onclick="loadLast()">載入上次</button>
   <span id="stat1"></span>
 </div>
 <div class="bar" style="margin-top:8px">
   <input id="url" style="flex:1;min-width:280px" placeholder="貼上圖片網址（jpg/png/tiff/webp）"/>
   <button id="urlBtn" onclick="loadUrl()">載入網址圖</button>
 </div>
 <div class="bar" style="margin-top:8px">
   <input type="file" id="fileInput" accept="image/*" multiple style="flex:1;min-width:240px"/>
   <button id="fileBtn" onclick="uploadFiles()">加入本機圖片檔案</button>
 </div><div class="hint">網址圖會加入成為此書的下一頁；「載入上次」回到上次整本書。</div></div>
<div class="card"><h2>② 頁面（點縮圖選頁）</h2>
 <div class="thumbs" id="thumbs"><i style="color:#8a7a5a;font-size:12px">尚未載入書籍。</i></div>
 <div class="bar" style="margin-top:10px">
   <button id="ocrBtn" onclick="runOcr()" disabled>辨識此頁</button>
   <button id="saveBtn" onclick="saveCols()" disabled>儲存校對</button>
   <button id="expBtn" onclick="exportTxt()" disabled>匯出全書文字</button>
   <div class="prog" id="prog" style="display:none"><div class="prog-fill" id="progFill"></div></div>
   <span class="prog-text" id="progText"></span>
 </div>
 <div id="status"></div>
 <div id="review" style="display:none;margin-top:8px;font-size:13px;color:#4a442f"></div>
 <label style="font-size:12px;color:#6a5c40;display:inline-block;margin-top:6px">
   <input type="checkbox" id="sortNeed" onchange="window.__sortNeed=this.checked;refreshJob()"/> 待校欄位排最前
 </label>
 </div>
<div class="card"><h2>③ 逐列校對（由右至左，右起第一欄＝一頁首行）</h2>
 <div class="cols" id="cols"></div>
 <div id="full" style="margin-top:10px"></div></div>
<script>
let job=null, cur=0, polling=false;
const $=x=>document.getElementById(x);
window.onerror=function(m,src,l){ const el=document.getElementById("status");
 if(el) el.textContent="⚠ 頁面錯誤 "+src+":"+l+" "+m; };
async function api(path, body){
  const opt = body?{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}:{};
  const r = await fetch(path, opt);
  const t = await r.text();
  try{ return JSON.parse(t); }catch(e){ $("status").textContent="⚠ 伺服器回應異常："+t.slice(0,120); return {}; }
}
async function loadBook(){
  const path=$("path").value.trim();
  if(!path){ $("stat1").textContent="請先輸入路徑"; return; }
  $("stat1").textContent="載入中…";
  const j = await api("/api/load",{path,dpi:200});
  if(j.error){ $("stat1").textContent="錯誤："+j.error; return; }
  setJob(j);
}
async function uploadFiles(){
  const inp=$("fileInput");
  if(!inp.files || !inp.files.length){ $("stat1").textContent="請先選擇圖片檔"; return; }
  const list=[].slice.call(inp.files);
  $("stat1").textContent="上傳中… 0/"+list.length;
  let last=null, okn=0;
  for(let i=0;i<list.length;i++){
    const f=list[i];
    const b64=await new Promise(function(res,rej){
      const fr=new FileReader();
      fr.onload=function(){ res(fr.result); };
      fr.onerror=rej; fr.readAsDataURL(f);
    });
    const j=await api("/api/upload_image",{job:job,name:f.name,data:b64});
    if(j && j.error){ $("stat1").textContent="錯誤："+j.error; continue; }
    last=j; okn++;
    $("stat1").textContent="上傳中… "+okn+"/"+list.length;
  }
  if(last){
    if(!job || last.id!==job){ job=last.id; }
    cur=last.pages.length;
    renderThumbs(last);
    renderThumbsState(cur);
    $("stat1").textContent="✓ 已加入 "+okn+" 張本機圖片（共 "+last.pages.length+" 頁）— 按「辨識此頁」";
    refreshButtons(last);
  }
  inp.value="";
}
async function loadLast(){
  const j = await api("/api/last");
  if(j && j.id){ setJob(j); $("stat1").textContent="已載入上次（"+j.pages.length+" 頁）"; }
  else $("stat1").textContent="沒有上次記錄";
}
async function loadUrl(){
  const u=$("url").value.trim();
  if(!u){ $("stat1").textContent="請先貼上圖片網址"; return; }
  $("stat1").textContent="下載網址圖中…";
  const j = await api("/api/load_url",{url:u, job:job});
  if(j.error){ $("stat1").textContent="錯誤："+j.error; return; }
  if(!job || j.id!==job){ job=j.id; }
  cur = j.pages.length;
  renderThumbs(j);
  $("url").value=""; $("stat1").textContent="✓ 網址圖已加入（第 "+cur+" 頁）— 按「辨識此頁」開始 OCR";
  refreshButtons(j);
}
function renderThumbs(j){
  const th=$("thumbs"); th.innerHTML="";
  j.pages.forEach(function(p,i){
    const w=document.createElement("div"); w.className="w";
    const img=document.createElement("img"); img.src="/thumb/"+encodeURIComponent(p.path);
    const cap=document.createElement("div"); cap.textContent="第"+(i+1)+"頁";
    w.appendChild(img); w.appendChild(cap);
    w.onclick=function(){ pick(i+1); };
    th.appendChild(w);
  });
}
function setJob(j, keepCur){
  job=j.id; cur=keepCur? Math.min(j.pages.length, Math.max(cur,1)) : Math.min(1, j.pages.length);
  renderThumbs(j);
  pick(cur); renderEngine();
}
async function renderEngine(){
  const e = await api("/api/backend");
  const el=$("status");
  el.textContent = e.ready ? "引擎就緒："+e.backend : "⚠ OCR 伺服器沒有回應：先跑 python3 -m mochiocr serve";
}
function pick(n){
  cur=n; renderThumbsState(n);
  $("ocrBtn").disabled=false; drawCols(null);
  refreshJob();
}
function renderThumbsState(n){
  [...$("thumbs").children].forEach(function(w,i){ w.className=(i===n-1)?"w cur":"w"; });
}
function refreshButtons(j){
  const pg=($("ocrBtn")); if(pg) pg.disabled=!(j && j.pages && j.pages.length);
  const p=j && j.pages && j.pages[cur-1];
  const sv=$("saveBtn"); if(sv) sv.disabled=!(p && p.columns);
  const ex=$("expBtn"); if(ex) ex.disabled=!(j && (j.pages||[]).some(function(x){ return x.columns; }));
}
async function refreshJob(){
  if(!job) return;
  const j = await api("/api/job/"+job);
  drawCols(j);
  $("saveBtn").disabled = !(j.pages[cur-1].columns);
  $("expBtn").disabled = !j.pages.some(function(p){ return p.columns; });
}
async function runOcr(){
  if(!job) return;
  $("status").textContent="啟動辨識…（每欄約 30–60 秒）";
  await api("/api/ocr",{job:job,page:cur});
  if(polling) return; polling=true;
  while(polling){
    const j=await api("/api/job/"+job);
    $("status").textContent=(j.status.msg||"")+(j.status.error?(" ⚠ "+j.status.error):"");
    drawCols(j);
    if(j.status.stage!=="ocr" && j.status.stage!=="segment") polling=false;
    await new Promise(function(r){ setTimeout(r,1500); });
  }
  refreshJob();
}
function updProg(j){
  const st=j.status;
  const pr=$("prog"), pf=$("progFill"), pt=$("progText");
  if(st.stage==="ocr" && st.n_cols){
    pr.style.display="block"; pf.classList.add("run");
    pf.style.width=Math.round(100*st.cols_done/st.n_cols)+"%";
    const avg=st.avg_secs? (st.avg_secs+"s/欄 · ") : "";
    pt.textContent="辨識中 "+st.cols_done+"/"+st.n_cols+" 欄 · "+avg+"進行中：第 "+(st.cur_col||"?")+" 欄";
  } else if(st.stage==="segment"){
    pr.style.display="block"; pf.style.width="6%"; pf.classList.add("run");
    pt.textContent="直列偵測中…";
  } else if(st.stage==="done" && st.n_cols){
    pr.style.display="block"; pf.classList.remove("run");
    pf.style.width="100%"; pt.textContent="完成 "+st.n_cols+" 欄";
  } else { pr.style.display="none"; }
}
function drawCols(j){
  if(!j) return;
  updProg(j);
  const p=j.pages[cur-1];
  const box=$("cols"); box.innerHTML="";
  const st=j.status;
  if(!p.columns || !p.columns.length){
    if(st.stage==="ocr" && st.n_cols){
      box.className="cols";
      for(let i=0;i<st.n_cols;i++){
        const w=document.createElement("div");
        w.className="col "+(i<st.cols_done?"ok":(i===st.cols_done?"running":"queued"));
        const meta=document.createElement("div"); meta.className="meta";
        meta.innerHTML = i<st.cols_done ? ("<span class=\\"okmark\\">✓</span> 第"+(i+1)+"欄")
          : (i===st.cols_done ? ("<span class=\\"spin\\"></span>辨識中 第"+(i+1)+"欄") : ("排隊中 第"+(i+1)+"欄"));
        w.appendChild(meta);
        const ta=document.createElement("textarea"); ta.dataset.x0="q"+i; ta.value=""; ta.disabled=true;
        ta.placeholder="辨識完成後填入…";
        w.appendChild(ta);
        box.appendChild(w);
      }
      return;
    }
    box.innerHTML="<i style=\\"color:#8a7a5a;font-size:12px\\">此頁尚未辨識（按「辨識此頁」）。</i>";
    return;
  }
  box.className="cols";
  [...p.columns].reverse().forEach(function(c){
    const w=document.createElement("div"); w.className="col";
    const im=document.createElement("img"); im.className="crop";
    im.src="/crop/"+encodeURIComponent(p.path)+"?x0="+c.tiles[0].x0+
           "&y0="+c.tiles[0].y0+"&x1="+c.tiles[0].x1+"&y1="+c.tiles[0].y1;
    const meta=document.createElement("div"); meta.className="meta";
    const uncN=(c.unc||0);

    const badge = c.ck ? "<span class='okmark'>✓ 已確認</span>" : (uncN>0.34 ? "<span class='warn'>⚠ 待校</span>" : "<span class='soft'>· 候選一致</span>");

    meta.innerHTML="欄 @x"+c.x0+" "+badge+(c.secs?(" <span style='color:#b0a080'>· "+c.secs+"s</span>"):"");
    const ta=document.createElement("textarea"); ta.dataset.x0=c.x0; ta.value=c.text||"";
    const alts=document.createElement("div"); alts.className="alts";
    (c.alts||[]).forEach(function(t){
      const b=document.createElement("button"); b.className="alt"; b.textContent=t;
      b.onclick=function(ev){ ev.preventDefault(); ta.value=t;
        alts.querySelectorAll(".alt").forEach(function(x){ x.classList.remove("on"); });
        b.classList.add("on"); };
      alts.appendChild(b);
    });
    if((c.alts||[]).length){
      const lab=document.createElement("div"); lab.className="altlab"; lab.textContent="其他可能讀法（點選採用）：";
      alts.insertBefore(lab, alts.firstChild);
    }
    const ckB=document.createElement("button"); ckB.className="ckbtn";
    ckB.textContent=(c.ck?"✓ 已確認":"標記已確認");
    if(c.ck) ckB.classList.add("on");
    ckB.onclick=function(ev){ ev.preventDefault(); c.ck=!c.ck;
      ckB.textContent=(c.ck?"✓ 已確認":"標記已確認");
      ckB.classList.toggle("on", !!c.ck); updReviewBar(j); };
    w.appendChild(im); w.appendChild(meta); w.appendChild(ta); w.appendChild(alts); w.appendChild(ckB);
    box.appendChild(w);
  });
  const full=j.pages.map(function(pp,i){ return pp.columns&&pp.columns.length?
     ("第 "+(i+1)+" 頁\\n"+[...pp.columns].reverse().map(function(c){ return c.text||""; }).join("\\n")):null; })
     .filter(Boolean).join("\\n\\n");
  $("full").textContent=full||"（尚無內容）";
  updReviewBar(j);
}
function updReviewBar(j){
  const p=j.pages[cur-1]; const cols=p.columns||[];
  const bar=$("review");
  if(!cols.length){ bar.style.display="none"; return; }
  const need=cols.filter(function(c){ return !c.ck && (c.unc||0)>0.34; });
  const done=cols.filter(function(c){ return c.ck; }).length;
  bar.style.display="block";
  bar.innerHTML="本頁 <b>"+cols.length+"</b> 欄 · ✓ 已確認 <b>"+done+"</b> · ⚠ 待校 <b>"+need.length+"</b>"
    +(need.length?"　<span style='font-size:12px;color:#8a7a5a'>（點替代讀法或直接改字，再按「標記已確認」）</span>":"　<span style='color:#3a7d2c'>本頁已校完</span>");
  if(window.__sortNeed){
    const box=$("cols");
    const items=[].slice.call(box.children);
    const isNeed=function(el){
      const t=el.querySelector("textarea"); if(!t) return false;
      const c=cols.filter(function(z){ return String(z.x0)===t.dataset.x0; })[0];
      return c && !c.ck && (c.unc||0)>0.34;
    };
    items.sort(function(a,b){ return (isNeed(b)?1:0)-(isNeed(a)?1:0); });
    items.forEach(function(el){ box.appendChild(el); });
  }
}
async function saveCols(){
  const j=await api("/api/job/"+job);
  const texts={};
  $("cols").querySelectorAll("textarea").forEach(function(t){ texts[t.dataset.x0]=t.value; });
  const ck={};
  (j.pages[cur-1].columns||[]).forEach(function(c){ if(c.ck) ck[String(c.x0)]=true; });
  const r=await api("/api/save",{job:job,page:cur,texts:texts,ck:ck});
  $("full").textContent = (r&&r.page_text)||$("full").textContent;
  $("status").textContent="已儲存並組稿（第 "+cur+" 頁）";
  refreshJob();
}
async function exportTxt(){
  const r=await api("/api/export",{job:job});
  const blob=new Blob(["\\ufeff"+(r.text||"")],{type:"text/plain;charset=utf-8"});
  const a=document.createElement("a"); a.href=URL.createObjectURL(blob);
  a.download="mochiocr_輸出.txt"; a.click();
}
window.addEventListener("DOMContentLoaded", function(){
  const bind=function(id,fn){ const b=$(String(id).replace(/^#/,"")); if(b) b.addEventListener("click",function(e){ e.preventDefault(); fn(); }); };
  bind("#loadBtn", loadBook); bind("#lastBtn", loadLast); bind("#urlBtn", loadUrl);
  bind("#fileBtn", uploadFiles);
  bind("#ocrBtn", runOcr); bind("#saveBtn", saveCols); bind("#expBtn", exportTxt);
  loadLast();
});
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u, q = urlparse(self.path).path, dict(parse_qsl(urlparse(self.path).query, keep_blank_values=True))
        if u in ("/", "/gui", "/index.html"):
            self._send(200, PAGE_TMPL.encode(), "text/html; charset=utf-8")
            return
        if u == "/api/backend":
            from mochiocr import ocrclient
            self._send(200, json.dumps({"ready": ocrclient.server_ready(DEF_BACKEND),
                                        "backend": DEF_BACKEND, "model": "default"}).encode())
            return
        if u == "/judge":
            src = (ROOT / "npmwork" / "judge_review.html").read_text(encoding="utf-8")
            inject = ("""<script>
(async function(){
  const bar=document.querySelector(".bar");
  if(!bar) return;
  const stat=document.createElement("span"); stat.className="prog-text";
  bar.appendChild(stat);
  const mk=function(txt,fn){ const b=document.createElement("button"); b.textContent=txt;
    b.addEventListener("click",function(e){ e.preventDefault(); fn(); }); bar.appendChild(b); };
  mk("✓ 同步答案到伺服器", async function(){
    const out={};
    document.querySelectorAll(".col").forEach(function(c){
      const row=JSON.parse(c.dataset.json);
      const v=c.querySelector(".ans").value.trim();
      if(v) out[row.image.split("/").pop()]=v;
    });
    const r=await fetch("/api/judge_save",{method:"POST",
      headers:{"Content-Type":"application/json"}, body:JSON.stringify({answers:out})});
    const d=await r.json();
    stat.textContent="已同步 "+d.updated+" 列 · 判讀進度 "+d.filled+"/"+d.total;
  });
  mk("▶ 啟動 v16 訓練", async function(){
    if(!confirm("併入判讀列並啟動 v16 訓練（約 70 分鐘）？")) return;
    const r=await fetch("/api/npm_v16",{method:"POST"});
    const d=await r.json();
    stat.textContent=d.started? "✓ v16 訓練已啟動（train_v16.log 可查）" : "啟動失敗";
  });
})();
</script>""")
            src = src.replace("</body>", inject + "\n</body>", 1)
            self._send(200, src.encode(), "text/html; charset=utf-8")
            return
        if u == "/api/last":
            jid = latest_job_id()
            if not jid:
                self._send(200, b"{}"); return
            self._send(200, json.dumps(JOBS[jid], ensure_ascii=False).encode())
            return
        if u.startswith("/api/job/"):
            jid = u.split("/")[3]
            meta = JOBS.get(jid)
            if not meta:
                self._send(404, b"{}"); return
            self._send(200, json.dumps(meta, ensure_ascii=False).encode())
            return
        if u.startswith("/thumb/"):
            fp = ROOT / Path(unquote(u[len("/thumb/"):]))
            try:
                from PIL import Image
                im = Image.open(fp).convert("RGB")
                im.thumbnail((420, 420))
                buf = io.BytesIO(); im.save(buf, format="JPEG", quality=80)
                self._send(200, buf.getvalue(), "image/jpeg")
            except Exception as e:
                self._send(404, str(e).encode())
            return
        if u.startswith("/crop/"):
            fp = ROOT / Path(unquote(u[len("/crop/"):]))
            try:
                from PIL import Image
                x0, y0, x1, y1 = int(q["x0"]), int(q["y0"]), int(q["x1"]), int(q["y1"])
                im = Image.open(fp).convert("RGB")
                pad = 6
                im = im.crop((max(0, x0-pad), max(0, y0-pad),
                              min(im.width, x1+pad), min(im.height, y1+pad)))
                if max(im.size) > 1200:
                    r = 1200 / max(im.size)
                    im = im.resize((int(im.width*r), int(im.height*r)))
                buf = io.BytesIO(); im.save(buf, format="PNG")
                self._send(200, buf.getvalue(), "image/png")
            except Exception as e:
                self._send(404, str(e).encode())
            return
        self._send(404, b"{}")

    def do_POST(self):
        u = urlparse(self.path).path
        ln = int(self.headers.get("Content-Length", 0))
        try:
            p = json.loads(self.rfile.read(ln).decode())
        except Exception:
            p = {}
        if u == "/api/load":
            src = Path(str(p.get("path", "")).strip())
            out = new_job(str(src))
            try:
                from mochiocr.pdfrender import image_dir_images, pdf_pages, resize_pages
                if not src.exists():
                    raise ValueError("路徑不存在：" + str(src))
                if src.is_dir():
                    paths = image_dir_images(src)
                    d0 = WS / out["id"] / "src"
                    d0.mkdir(parents=True, exist_ok=True)
                    copied = []
                    for x in paths:
                        dst = d0 / x.name
                        shutil.copyfile(x, dst)
                        copied.append(dst)
                    paths = resize_pages(copied, out["max_side"])
                elif src.suffix.lower() == ".pdf":
                    d = WS / out["id"] / "pages"
                    paths = pdf_pages(src, d, None, int(p.get("dpi", 200)))
                    paths = resize_pages(paths, out["max_side"])
                elif src.suffix.lower() in (".jpg", ".jpeg", ".png", ".tif", ".tiff",
                                            ".webp", ".bmp", ".gif"):
                    from PIL import Image as _PILImage
                    d = WS / out["id"] / "pages"
                    d.mkdir(parents=True, exist_ok=True)
                    im = _PILImage.open(src).convert("RGB")
                    if max(im.size) > out["max_side"]:
                        r = out["max_side"] / max(im.size)
                        im = im.resize((max(1, int(im.width * r)), max(1, int(im.height * r))))
                    dst = d / (src.stem[:40] + "_001.png")
                    im.save(dst)
                    paths = [dst]
                else:
                    raise ValueError("請給 PDF、單一圖片（jpg/png/tif/webp）或圖片資料夾")
                for i, x in enumerate(paths):
                    out["pages"].append({"page": i + 1,
                                         "path": str(Path(x).relative_to(ROOT)),
                                         "columns": None})
                out["status"].update(stage="ready", msg="%d 頁就緒" % len(paths))
                JOBS[out["id"]] = out
                save_job(out["id"])
                self._send(200, json.dumps(out, ensure_ascii=False).encode())
            except Exception as e:
                self._send(400, json.dumps({"error": "%s: %s" % (type(e).__name__, e)},
                                           ensure_ascii=False).encode())
            return
        if u == "/api/upload_image":
            import base64 as _b64
            from PIL import Image as _PILImage
            name = str(p.get("name") or "img.png")
            data = p.get("data") or ""
            if not data:
                self._send(400, b'{"error":"empty"}')
                return
            jid = p.get("job")
            if not (jid and jid in JOBS):
                out = new_job("本機上傳：" + name)
                jid = out["id"]
            else:
                out = JOBS[jid]
            try:
                raw = _b64.b64decode(data.split(",")[-1])
                im = _PILImage.open(io.BytesIO(raw)).convert("RGB")
                if max(im.size) > out.get("max_side", 3200):
                    r = out.get("max_side", 3200) / max(im.size)
                    im = im.resize((max(1, int(im.width * r)), max(1, int(im.height * r))))
                fpd = WS / jid / "pages"
                fpd.mkdir(parents=True, exist_ok=True)
                stem = Path(name).stem[:40] or "upload"
                fp = fpd / ("up_%03d_%s.png" % (len(out["pages"]) + 1, stem))
                im.save(fp)
                rel = str(fp.relative_to(ROOT))
                out["pages"].append({"page": len(out["pages"]) + 1, "path": rel,
                                     "columns": None, "src_name": name})
                out["status"].update(stage="ready",
                                     msg="本機圖片 %d 已加入（%dx%d）" % (len(out["pages"]), im.width, im.height))
                JOBS[jid] = out
                save_job(jid)
                self._send(200, json.dumps(out, ensure_ascii=False).encode())
            except Exception as e:
                self._send(400, json.dumps({"error": "圖片載入失敗：%s: %s" % (type(e).__name__, e)},
                                           ensure_ascii=False).encode())
            return
        if u == "/api/load_url":
            urlx = str(p.get("url", "")).strip()
            if not urlx.startswith("http"):
                self._send(400, json.dumps({"error": "請貼上 http(s) 圖片網址"}, ensure_ascii=False).encode())
                return
            jid = p.get("job")
            if not (jid and jid in JOBS):
                out = new_job(urlx[:120])
                jid = out["id"]
            else:
                out = JOBS[jid]
            try:
                import urllib.request
                from PIL import Image as PILImage
                data = urllib.request.urlopen(urllib.request.Request(
                    urlx, headers={"User-Agent": "Mozilla/5.0 Chrome/120", "Referer": urlx}),
                    timeout=90).read()
                im = PILImage.open(io.BytesIO(data)).convert("RGB")
                if max(im.size) > out.get("max_side", 3200):
                    r = out.get("max_side", 3200) / max(im.size)
                    im = im.resize((max(1, int(im.width * r)), max(1, int(im.height * r))))
                fpd = WS / jid / "pages"
                fpd.mkdir(parents=True, exist_ok=True)
                fp = fpd / ("url_%03d.png" % (len(out["pages"]) + 1))
                im.save(fp)
                rel = str(fp.relative_to(ROOT))
                out["pages"] = [pg for pg in out["pages"] if pg["path"] != rel]
                out["pages"].append({"page": len(out["pages"]) + 1, "path": rel,
                                     "columns": None, "url": urlx})
                for i, pg in enumerate(out["pages"]):
                    pg["page"] = i + 1
                out["status"].update(stage="ready",
                                     msg="網址圖 %d 已載入（%dx%d）" % (len(out["pages"]), im.width, im.height))
                JOBS[jid] = out
                save_job(jid)
                self._send(200, json.dumps(out, ensure_ascii=False).encode())
            except Exception as e:
                self._send(400, json.dumps({"error": "網址圖載入失敗：%s: %s" % (type(e).__name__, e)},
                                           ensure_ascii=False).encode())
            return
        if u == "/api/judge_save":
            answers = p.get("answers", {})
            updated = 0
            for pj in Path(ROOT / "cols").glob("strips/npm_judge_*.jsonl"):
                rows = [json.loads(l) for l in pj.read_text(encoding="utf-8").splitlines() if l.strip()]
                changed = 0
                for r in rows:
                    base = Path(r["image"]).name
                    if base in answers and answers[base].strip():
                        r["text"] = answers[base].strip()
                        changed += 1
                if changed:
                    pj.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                                  encoding="utf-8")
                    updated += changed
            filled = total = 0
            for pj in Path(ROOT / "cols").glob("strips/npm_judge_*.jsonl"):
                for l in pj.read_text(encoding="utf-8").splitlines():
                    if not l.strip():
                        continue
                    total += 1
                    rr = json.loads(l)
                    if rr.get("text", "").strip():
                        filled += 1
            self._send(200, json.dumps({"ok": True, "updated": updated,
                                        "filled": filled, "total": total}).encode())
            return
        if u == "/api/ocr":
            jid = p.get("job"); page_index = int(p.get("page", 1)) - 1
            meta = JOBS.get(jid)
            if not meta:
                self._send(404, b"{}"); return
            meta["pages"][page_index]["columns"] = None
            threading.Thread(target=ocr_page, args=(jid, page_index), daemon=True).start()
            self._send(200, b'{"started":true}')
            return
        if u == "/api/save":
            jid = p["job"]; page = JOBS[jid]["pages"][int(p["page"]) - 1]
            cols = page.get("columns") or []
            for c in cols:
                t = "".join(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]",
                                       p["texts"].get(str(c["x0"]), c.get("text") or "")))
                c["text"] = t
            ck = p.get("ck") or {}
            for c in cols:
                if str(c["x0"]) in ck:
                    c["ck"] = bool(ck[str(c["x0"])])
            page_text = "\n".join(c["text"] for c in cols)
            d = WS / jid / "out"
            d.mkdir(parents=True, exist_ok=True)
            (d / ("page_%04d.txt" % int(p["page"]))).write_text(page_text, encoding="utf-8")
            (d / ("page_%04d.json" % int(p["page"]))).write_text(
                json.dumps({"columns": cols}, ensure_ascii=False, indent=1), encoding="utf-8")
            save_job(jid)
            self._send(200, json.dumps({"ok": True, "page_text": page_text}).encode())
            return
        if u == "/api/export":
            meta = JOBS[p["job"]]
            parts = []
            for pg in meta["pages"]:
                if pg.get("columns"):
                    parts.append("第 %d 頁\n%s" % (pg["page"],
                                 "\n".join(c["text"] for c in pg["columns"])))
            self._send(200, json.dumps({"text": "\n\n".join(parts)},
                                       ensure_ascii=False).encode())
            return
        self._send(404, b"{}")


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8810)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()