# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""花蓮高中 NPDL 工作坊．現場分享牆 本機伺服器。

用法：
    uv run workshop_server.py [port]

啟動後，讓所有裝置連到同一個 Wi-Fi，並在瀏覽器輸入伺服器印出的網址：
    - 老師手機／平板：提交分享
    - 投影布幕：即時分享牆（/wall）
"""

import json
import os
import socket
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "workshop_submissions.json")
WORKSHOP_PAGE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "school-status-workshop.html")
LOCK = threading.Lock()


def load_workshop_page():
    try:
        with open(WORKSHOP_PAGE_FILE, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None

DIMENSIONS = [
    {"id": "vision", "name": "願景與目標", "color": "#1E3A8A"},
    {"id": "leadership", "name": "領導力", "color": "#15803d"},
    {"id": "culture", "name": "協作文化", "color": "#f97316"},
    {"id": "deepening", "name": "深化學習", "color": "#1E3A8A"},
    {"id": "assessment", "name": "新的評估與檢核", "color": "#15803d"},
]
USAGE_DIM = {"id": "usage", "name": "討論：在學校使用該評量規準的方式", "color": "#7c3aed"}
ALL_DIMS = DIMENSIONS + [USAGE_DIM]
DIM_BY_ID = {d["id"]: d for d in ALL_DIMS}


def load_submissions():
    if not os.path.exists(DATA_FILE):
        return []
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def save_submissions(items):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def get_local_ips():
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                ips.add(ip)
    except OSError:
        pass
    return sorted(ips) or ["127.0.0.1"]


DIMENSION_OPTIONS_HTML = "\n".join(
    '<option value="%s">%s</option>' % (d["id"], d["name"]) for d in DIMENSIONS
) + '\n<option value="usage">💬 %s</option>' % USAGE_DIM["name"]

SUBMIT_HTML = """<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>現場分享．花蓮高中 NPDL 工作坊</title>
<style>
  :root {
    --navy: #1E3A8A; --navy-dark: #152a63; --navy-soft: #eef2fb;
    --leaf: #16a34a; --amber: #f97316; --slate: #64748b; --bg: #f8fafc;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: #1e293b;
    font-family: "Segoe UI", "Microsoft JhengHei", "PingFang TC", sans-serif;
    padding-bottom: 40px;
  }
  header {
    background: linear-gradient(135deg, var(--navy-dark), var(--navy));
    color: #fff; padding: 28px 20px 24px; text-align: center;
  }
  header h1 { margin: 0 0 6px; font-size: 1.35rem; }
  header p { margin: 0; font-size: 0.85rem; color: #cbd5e1; }
  main { max-width: 480px; margin: -16px auto 0; padding: 0 16px; }
  .card {
    background: #fff; border-radius: 18px; padding: 22px 20px;
    box-shadow: 0 10px 30px -12px rgba(30,58,138,0.25); margin-bottom: 18px;
  }
  label { display: block; font-weight: 700; font-size: 0.85rem; color: var(--navy); margin-bottom: 8px; }
  select, input[type=text], textarea {
    width: 100%; border: 1.5px solid #e2e8f0; border-radius: 12px;
    padding: 12px 14px; font-size: 1rem; margin-bottom: 18px;
    font-family: inherit; color: #1e293b; background: #fff;
  }
  select:focus, input:focus, textarea:focus { outline: none; border-color: var(--navy); }
  textarea { resize: vertical; min-height: 100px; }
  button {
    width: 100%; padding: 15px; border: none; border-radius: 999px;
    background: var(--amber); color: #fff; font-size: 1.05rem; font-weight: 700;
    cursor: pointer; transition: transform .15s ease, opacity .15s ease;
  }
  button:active { transform: scale(0.98); }
  button:disabled { opacity: 0.6; cursor: not-allowed; }
  #status { text-align: center; font-size: 0.85rem; margin-top: 10px; min-height: 20px; }
  #status.ok { color: var(--leaf); font-weight: 700; }
  #status.err { color: #dc2626; font-weight: 700; }
  .mine { margin-top: 6px; }
  .mine h2 { font-size: 0.8rem; color: var(--slate); text-transform: uppercase; letter-spacing: .05em; margin: 0 0 10px; }
  .mine-item {
    background: #fff; border-left: 4px solid var(--navy); border-radius: 8px;
    padding: 10px 12px; margin-bottom: 8px; font-size: 0.85rem; box-shadow: 0 2px 6px rgba(0,0,0,0.05);
  }
  .mine-item .dim { font-weight: 700; color: var(--navy); }
  a.walllink {
    display: block; text-align: center; margin-top: 8px; font-size: 0.8rem;
    color: var(--slate); text-decoration: none;
  }
</style>
</head>
<body>
  <header>
    <h1>學校現況規準工作坊</h1>
    <p>現場分享．送出後即時顯示在投影牆上</p>
  </header>
  <main>
    <form class="card" id="submitForm">
      <label for="dim">向度</label>
      <select id="dim" required>
        __DIMENSION_OPTIONS__
      </select>

      <label for="group">組別／夥伴姓名（選填）</label>
      <input type="text" id="group" placeholder="例如：3 樓 A 組、王老師 ＆ 李老師">

      <label for="text">關鍵想法</label>
      <textarea id="text" placeholder="寫下你們兩人討論後的關鍵想法……" required></textarea>

      <button type="submit" id="submitBtn">送出到分享牆</button>
      <div id="status"></div>
    </form>

    <div class="mine" id="mineWrap" style="display:none;">
      <h2>本裝置已送出</h2>
      <div id="mineList"></div>
    </div>

    <a class="walllink" href="/wall" target="_blank">查看即時分享牆 →</a>
  </main>

<script>
  const form = document.getElementById('submitForm');
  const statusEl = document.getElementById('status');
  const submitBtn = document.getElementById('submitBtn');
  const mineWrap = document.getElementById('mineWrap');
  const mineList = document.getElementById('mineList');

  function loadMine() {
    try { return JSON.parse(localStorage.getItem('workshop-mine') || '[]'); }
    catch (e) { return []; }
  }
  function saveMine(list) {
    try { localStorage.setItem('workshop-mine', JSON.stringify(list)); } catch (e) {}
  }
  function renderMine() {
    const list = loadMine();
    if (!list.length) { mineWrap.style.display = 'none'; return; }
    mineWrap.style.display = 'block';
    mineList.innerHTML = list.slice().reverse().map(item =>
      `<div class="mine-item"><span class="dim">${item.dimName}</span>：${item.text}</div>`
    ).join('');
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const dimSelect = document.getElementById('dim');
    const dimId = dimSelect.value;
    const dimName = dimSelect.options[dimSelect.selectedIndex].text;
    const group = document.getElementById('group').value.trim();
    const text = document.getElementById('text').value.trim();
    if (!text) return;

    submitBtn.disabled = true;
    statusEl.textContent = '送出中…';
    statusEl.className = '';

    try {
      const res = await fetch('/api/submit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ dimensionId: dimId, groupName: group, text: text })
      });
      if (!res.ok) throw new Error('failed');
      statusEl.textContent = '已送出！謝謝分享 🎉';
      statusEl.className = 'ok';
      const mine = loadMine();
      mine.push({ dimName, text, ts: Date.now() });
      saveMine(mine);
      renderMine();
      document.getElementById('text').value = '';
    } catch (err) {
      statusEl.textContent = '送出失敗，請確認已連上同一個 Wi-Fi 後再試一次。';
      statusEl.className = 'err';
    } finally {
      submitBtn.disabled = false;
    }
  });

  renderMine();
</script>
</body>
</html>
"""

WALL_HTML = """<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>現場分享牆．花蓮高中 NPDL 工作坊</title>
<style>
  :root { --navy: #1E3A8A; --navy-dark: #152a63; --leaf: #16a34a; --amber: #f97316; --slate: #64748b; --bg: #f8fafc; }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: #1e293b;
    font-family: "Segoe UI", "Microsoft JhengHei", "PingFang TC", sans-serif;
  }
  header {
    background: linear-gradient(135deg, var(--navy-dark), var(--navy));
    color: #fff; padding: 22px 32px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px;
  }
  header h1 { margin: 0; font-size: 1.5rem; }
  header .meta { font-size: 0.9rem; color: #cbd5e1; text-align: right; }
  header .meta #ghSyncStatus { font-size: 0.78rem; color: #a5b4fc; margin-top: 2px; }
  #urlBanner {
    background: #fffbeb; color: #92400e; text-align: center; padding: 10px 16px;
    font-size: 0.95rem; font-weight: 700; border-bottom: 1px solid #fde68a;
  }
  #urlBanner span { font-family: Consolas, monospace; background: #fff; padding: 2px 10px; border-radius: 6px; margin-left: 6px; }
  #adminBar { text-align: center; padding-bottom: 18px; display: flex; justify-content: center; gap: 10px; }
  #adminBar button {
    background: none; border: 1px solid #cbd5e1; color: #94a3b8; font-size: 0.75rem;
    padding: 6px 14px; border-radius: 999px; cursor: pointer;
  }
  #adminBar button:hover { color: #dc2626; border-color: #fca5a5; }
  #ghDownloadBtn:hover { color: var(--navy); border-color: var(--navy); }
  #board {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    gap: 18px; padding: 24px 32px 48px;
  }
  .col { background: #fff; border-radius: 16px; box-shadow: 0 8px 24px -12px rgba(30,58,138,0.2); overflow: hidden; display: flex; flex-direction: column; max-height: 78vh; }
  .col-head { padding: 14px 18px; color: #fff; font-weight: 700; font-size: 1.05rem; display: flex; justify-content: space-between; align-items: center; }
  .col-body { padding: 14px; overflow-y: auto; flex: 1; }
  .note {
    background: #f8fafc; border-radius: 12px; padding: 12px 14px; margin-bottom: 10px;
    border-left: 4px solid #cbd5e1; animation: pop .3s ease both;
  }
  .note .grp { font-size: 0.75rem; font-weight: 700; color: var(--slate); margin-bottom: 4px; }
  .note .txt { font-size: 0.95rem; line-height: 1.5; white-space: pre-wrap; }
  .note .time { font-size: 0.7rem; color: #94a3b8; margin-top: 6px; }
  .empty { text-align: center; color: #94a3b8; font-size: 0.85rem; padding: 20px 0; }
  @keyframes pop { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
  #footerBar { text-align: center; padding: 14px; font-size: 0.8rem; color: #94a3b8; }
  #usageSection { margin: 0 32px 40px; background: #fff; border-radius: 16px; box-shadow: 0 8px 24px -12px rgba(30,58,138,0.2); overflow: hidden; }
  .usage-head { padding: 16px 20px; color: #fff; font-weight: 700; font-size: 1.1rem; display: flex; justify-content: space-between; align-items: center; background: __USAGE_COLOR__; }
  .usage-body { padding: 18px 20px; display: flex; flex-wrap: wrap; gap: 14px; }
  .usage-body .note { flex: 1 1 280px; max-width: 380px; margin-bottom: 0; }
  .usage-body .empty { width: 100%; }
  #githubPanel {
    max-width: 420px; margin: 0 auto 28px; padding: 18px 20px; background: #fff;
    border-radius: 14px; box-shadow: 0 4px 14px -6px rgba(0,0,0,0.12); text-align: center;
  }
  #githubPanel .gh-label { font-size: 0.8rem; color: var(--slate); font-weight: 700; margin: 0 0 12px; }
  #ghUploadBtn {
    width: 100%; padding: 11px; border: none; border-radius: 999px; background: var(--navy);
    color: #fff; font-weight: 700; font-size: 0.85rem; cursor: pointer; margin-bottom: 10px;
  }
  #ghUploadBtn:hover { background: var(--navy-dark); }
  #ghUploadBtn:disabled { opacity: 0.6; cursor: not-allowed; }
  #ghToken {
    width: 100%; padding: 9px 12px; border: 1px solid #e2e8f0; border-radius: 10px;
    font-size: 0.85rem; margin-bottom: 8px; font-family: inherit; box-sizing: border-box;
  }
  .gh-remember { display: flex; align-items: center; gap: 6px; font-size: 0.72rem; color: #94a3b8; justify-content: center; margin-bottom: 4px; }
  #ghStatus { font-size: 0.75rem; min-height: 16px; margin-top: 6px; }
</style>
</head>
<body>
  <header>
    <h1>🗂 現場分享牆</h1>
    <div class="meta">
      <div id="count">共 0 則分享</div>
      <div id="updated">尚未更新</div>
      <div id="ghSyncStatus">GitHub：尚未同步</div>
    </div>
  </header>
  <div id="urlBanner">老師請用手機連到：<span id="submitUrl"></span></div>
  <div id="board"></div>
  <div id="usageSection">
    <div class="usage-head">
      <span>__USAGE_NAME__</span>
      <span id="n-usage">0</span>
    </div>
    <div class="usage-body" id="body-usage"><div class="empty">尚無分享</div></div>
  </div>
  <div id="adminBar">
    <button id="clearBtn">清除所有紀錄</button>
    <button id="ghDownloadBtn">下載 GitHub 內容</button>
  </div>

  <div id="githubPanel">
    <p class="gh-label">☁️ 上傳到 GitHub 分享牆（給主持人使用）</p>
    <button id="ghUploadBtn" type="button">上傳 GitHub</button>
    <input id="ghToken" type="password" placeholder="貼上 GitHub Personal Access Token" autocomplete="off">
    <label class="gh-remember"><input type="checkbox" id="ghRemember"> 記住這個 Token（借用電腦請勿勾選）</label>
    <p id="ghStatus"></p>
  </div>

  <div id="footerBar">每 4 秒自動更新（本機）．每 10 秒自動合併 GitHub 上的資料．學校現況評量規準工作坊</div>

<script>
  const DIMENSIONS = __DIMENSIONS_JSON__;
  const board = document.getElementById('board');
  const countEl = document.getElementById('count');
  const updatedEl = document.getElementById('updated');

  board.innerHTML = DIMENSIONS.map(d => `
    <div class="col" data-dim="${d.id}">
      <div class="col-head" style="background:${d.color}">
        <span>${d.name}</span>
        <span id="n-${d.id}">0</span>
      </div>
      <div class="col-body" id="body-${d.id}"><div class="empty">尚無分享</div></div>
    </div>
  `).join('');

  function fmtTime(ts) {
    const d = new Date(ts);
    return d.getHours().toString().padStart(2,'0') + ':' + d.getMinutes().toString().padStart(2,'0');
  }

  function escapeHtml(s) {
    return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  // ---------- Merge local (LAN) submissions with GitHub (teacher direct-upload) submissions ----------
  const GITHUB_CONFIG = { owner: 'dfleoyang-HLHS', repo: 'npdl', path: 'workshop_submissions.json', branch: 'main' };
  let localItems = [];
  let githubItems = [];
  const ghSyncStatusEl = document.getElementById('ghSyncStatus');

  function mergeItems(a, b) {
    const map = new Map();
    a.forEach(it => map.set(it.id, it));
    b.forEach(it => map.set(it.id, it));
    return Array.from(map.values());
  }

  function renderBoard(items) {
    countEl.textContent = `共 ${items.length} 則分享`;
    updatedEl.textContent = '最後更新：' + new Date().toLocaleTimeString('zh-TW');

    DIMENSIONS.forEach(d => {
      const list = items.filter(it => it.dimensionId === d.id).sort((a,b) => b.ts - a.ts);
      document.getElementById('n-' + d.id).textContent = list.length;
      const body = document.getElementById('body-' + d.id);
      if (!list.length) { body.innerHTML = '<div class="empty">尚無分享</div>'; return; }
      body.innerHTML = list.map(it => `
        <div class="note" style="border-left-color:${d.color}">
          ${it.groupName ? `<div class="grp">${escapeHtml(it.groupName)}</div>` : ''}
          <div class="txt">${escapeHtml(it.text)}</div>
          <div class="time">${fmtTime(it.ts)}</div>
        </div>
      `).join('');
    });

    const usageList = items.filter(it => it.dimensionId === 'usage').sort((a,b) => b.ts - a.ts);
    document.getElementById('n-usage').textContent = usageList.length;
    const usageBody = document.getElementById('body-usage');
    if (!usageList.length) {
      usageBody.innerHTML = '<div class="empty">尚無分享</div>';
    } else {
      usageBody.innerHTML = usageList.map(it => `
        <div class="note" style="border-left-color:__USAGE_COLOR__">
          ${it.groupName ? `<div class="grp">${escapeHtml(it.groupName)}</div>` : ''}
          <div class="txt">${escapeHtml(it.text)}</div>
          <div class="time">${fmtTime(it.ts)}</div>
        </div>
      `).join('');
    }
  }

  async function refresh() {
    try {
      const res = await fetch('/api/submissions', { cache: 'no-store' });
      localItems = await res.json();
      renderBoard(mergeItems(localItems, githubItems));
    } catch (e) {
      updatedEl.textContent = '連線中斷，重試中…';
    }
  }

  async function fetchGithubItems() {
    ghSyncStatusEl.textContent = 'GitHub：同步中…';
    try {
      const url = `https://raw.githubusercontent.com/${GITHUB_CONFIG.owner}/${GITHUB_CONFIG.repo}/${GITHUB_CONFIG.branch}/${GITHUB_CONFIG.path}?t=${Date.now()}`;
      const res = await fetch(url, { cache: 'no-store' });
      if (!res.ok) throw new Error('http ' + res.status);
      githubItems = await res.json();
      ghSyncStatusEl.textContent = `GitHub：已同步 ${githubItems.length} 則（${new Date().toLocaleTimeString('zh-TW')}）`;
      renderBoard(mergeItems(localItems, githubItems));
    } catch (e) {
      ghSyncStatusEl.textContent = 'GitHub：同步失敗，稍後自動重試';
    }
  }

  document.getElementById('submitUrl').textContent = location.origin + '/';
  document.getElementById('ghDownloadBtn').addEventListener('click', fetchGithubItems);

  document.getElementById('clearBtn').addEventListener('click', async () => {
    if (!confirm('確定要清除所有分享紀錄嗎？此動作無法復原。')) return;
    await fetch('/api/clear', { method: 'POST' });
    refresh();
  });

  // ---------- Upload to GitHub (merges local-only items into whatever is already there) ----------
  const ghToken = document.getElementById('ghToken');
  const ghRemember = document.getElementById('ghRemember');
  const ghUploadBtn = document.getElementById('ghUploadBtn');
  const ghStatus = document.getElementById('ghStatus');

  try {
    const saved = localStorage.getItem('gh-token');
    if (saved) { ghToken.value = saved; ghRemember.checked = true; }
  } catch (e) {}

  function syncGhTokenStorage() {
    try {
      if (ghRemember.checked) localStorage.setItem('gh-token', ghToken.value);
      else localStorage.removeItem('gh-token');
    } catch (e) {}
  }
  ghRemember.addEventListener('change', syncGhTokenStorage);
  ghToken.addEventListener('input', syncGhTokenStorage);

  function setGhStatus(text, tone) {
    const colors = { neutral: '#94a3b8', warn: '#d97706', ok: '#16a34a', err: '#dc2626' };
    ghStatus.textContent = text;
    ghStatus.style.color = colors[tone] || colors.neutral;
    ghStatus.style.fontWeight = tone === 'neutral' ? 'normal' : '700';
  }

  function utf8ToBase64(str) {
    return btoa(unescape(encodeURIComponent(str)));
  }
  function base64ToUtf8(b64) {
    return decodeURIComponent(escape(atob(b64.replace(/\\n/g, ''))));
  }

  ghUploadBtn.addEventListener('click', async () => {
    const token = ghToken.value.trim();
    if (!token) {
      setGhStatus('請先在下方輸入 GitHub Token。', 'warn');
      return;
    }

    ghUploadBtn.disabled = true;
    setGhStatus('上傳中…', 'neutral');

    const apiUrl = `https://api.github.com/repos/${GITHUB_CONFIG.owner}/${GITHUB_CONFIG.repo}/contents/${GITHUB_CONFIG.path}`;
    const authHeaders = { Authorization: 'Bearer ' + token, Accept: 'application/vnd.github+json' };
    const maxAttempts = 4;

    try {
      const localRes = await fetch('/api/submissions', { cache: 'no-store' });
      const localData = await localRes.json();

      for (let attempt = 1; attempt <= maxAttempts; attempt++) {
        let remoteItems = [];
        let sha;
        const getRes = await fetch(apiUrl + '?ref=' + GITHUB_CONFIG.branch, { headers: authHeaders, cache: 'no-store' });
        if (getRes.status === 200) {
          const info = await getRes.json();
          sha = info.sha;
          try { remoteItems = JSON.parse(base64ToUtf8(info.content)); } catch (e) { remoteItems = []; }
        } else if (getRes.status !== 404) {
          const err = await getRes.json().catch(() => ({}));
          throw new Error('讀取現有資料失敗（' + getRes.status + '）' + (err.message ? '：' + err.message : ''));
        }

        const remoteIds = new Set(remoteItems.map(it => it.id));
        const toAdd = localData.filter(it => !remoteIds.has(it.id));
        const merged = remoteItems.concat(toAdd);
        const content = utf8ToBase64(JSON.stringify(merged, null, 2));

        const putRes = await fetch(apiUrl, {
          method: 'PUT',
          headers: Object.assign({ 'Content-Type': 'application/json' }, authHeaders),
          body: JSON.stringify(Object.assign(
            { message: '同步本機分享牆資料 ' + new Date().toLocaleString('zh-TW'), content: content, branch: GITHUB_CONFIG.branch },
            sha ? { sha } : {}
          ))
        });

        if (putRes.ok) {
          setGhStatus(`已同步！新增了 ${toAdd.length} 則本機資料到 GitHub（合計 ${merged.length} 則）🎉`, 'ok');
          githubItems = merged;
          renderBoard(mergeItems(localItems, githubItems));
          return;
        }
        if (putRes.status === 409 && attempt < maxAttempts) continue;
        const err = await putRes.json().catch(() => ({}));
        throw new Error('上傳失敗（' + putRes.status + '）' + (err.message ? '：' + err.message : '，請確認 Token 是否正確且有寫入權限。'));
      }
      setGhStatus('上傳失敗：太多人同時上傳，請稍後再試一次。', 'err');
    } catch (e) {
      setGhStatus('上傳失敗：' + e.message, 'err');
    } finally {
      ghUploadBtn.disabled = false;
    }
  });

  refresh();
  fetchGithubItems();
  setInterval(refresh, 4000);
  setInterval(fetchGithubItems, 10000);
</script>
</body>
</html>
"""

DIMENSIONS_JSON = json.dumps(DIMENSIONS, ensure_ascii=False)
SUBMIT_HTML = SUBMIT_HTML.replace("__DIMENSION_OPTIONS__", DIMENSION_OPTIONS_HTML)
WALL_HTML = (
    WALL_HTML.replace("__DIMENSIONS_JSON__", DIMENSIONS_JSON)
    .replace("__USAGE_COLOR__", USAGE_DIM["color"])
    .replace("__USAGE_NAME__", USAGE_DIM["name"])
)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print("  [%s] %s" % (time.strftime("%H:%M:%S"), fmt % args))

    def _send(self, code, body, content_type="text/html; charset=utf-8"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/submit", "/index.html"):
            self._send(200, SUBMIT_HTML)
        elif path == "/wall":
            self._send(200, WALL_HTML)
        elif path == "/workshop":
            html = load_workshop_page()
            if html is None:
                self._send(
                    404,
                    "<h1>找不到 school-status-workshop.html</h1>"
                    "<p>請確認它與 workshop_server.py 放在同一個資料夾。</p>",
                )
            else:
                self._send(200, html)
        elif path == "/api/submissions":
            with LOCK:
                items = load_submissions()
            self._send(200, json.dumps(items, ensure_ascii=False), "application/json; charset=utf-8")
        else:
            self._send(404, "<h1>404 Not Found</h1>")

    def do_POST(self):
        path = self.path.split("?")[0]
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""

        if path == "/api/submit":
            try:
                payload = json.loads(raw.decode("utf-8"))
                dim_id = payload.get("dimensionId", "")
                text = (payload.get("text") or "").strip()
                group = (payload.get("groupName") or "").strip()
                if dim_id not in DIM_BY_ID or not text:
                    self._send(400, json.dumps({"ok": False, "error": "invalid"}), "application/json")
                    return
                item = {
                    "id": uuid.uuid4().hex[:10],
                    "dimensionId": dim_id,
                    "groupName": group[:100],
                    "text": text[:1000],
                    "ts": int(time.time() * 1000),
                }
                with LOCK:
                    items = load_submissions()
                    items.append(item)
                    save_submissions(items)
                self._send(200, json.dumps({"ok": True}), "application/json; charset=utf-8")
            except (json.JSONDecodeError, UnicodeDecodeError):
                self._send(400, json.dumps({"ok": False, "error": "bad_json"}), "application/json")
        elif path == "/api/clear":
            with LOCK:
                save_submissions([])
            self._send(200, json.dumps({"ok": True}), "application/json; charset=utf-8")
        else:
            self._send(404, "Not Found")


DEFAULT_PORT = 80
FALLBACK_PORT = 8080


def url(ip, port):
    return "http://%s/" % ip if port == 80 else "http://%s:%d/" % (ip, port)


def start_server(port):
    return ThreadingHTTPServer(("0.0.0.0", port), Handler)


def main():
    port = DEFAULT_PORT
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass

    try:
        server = start_server(port)
    except OSError as e:
        print("=" * 56)
        print(" 無法啟動伺服器在連接埠 %d：%s" % (port, e))
        print("=" * 56)
        if port == DEFAULT_PORT:
            print(" 可能原因：連接埠 80 已被其他程式占用（例如 Skype、IIS），")
            print(" 或需要系統管理員權限。")
            print()
            print(" 請改用其他連接埠再試一次，例如：")
            print("   python workshop_server.py %d" % FALLBACK_PORT)
            print(" 注意：改用非 80 的連接埠後，老師端網址就需要加上 :%d，" % FALLBACK_PORT)
            print(" 無法再只打 IP 位置。")
        else:
            print(" 請確認連接埠 %d 沒有被其他程式占用，或改用其他數字再試一次。" % port)
        print("=" * 56)
        sys.exit(1)

    ips = get_local_ips()

    print("=" * 56)
    print(" 花蓮高中 NPDL 工作坊．現場分享牆伺服器已啟動")
    print("=" * 56)
    print()
    if port == DEFAULT_PORT:
        print(" 老師端只要在瀏覽器網址列輸入下面的 IP 位置即可，")
        print(" 不需要輸入 http:// 或連接埠：")
    else:
        print(" 請確認所有裝置都連到「同一個 Wi-Fi」，再開啟下列網址：")
    print()
    for ip in ips:
        print("   老師規準卡片＋送出： %sworkshop" % url(ip, port))
    print()
    print(" ⚠ 請務必請老師連到上面這個網址（不是 GitHub Pages 那個 https 連結！），")
    print("   否則瀏覽器會因為「安全網頁無法呼叫非安全網址」而擋下送出動作。")
    print()
    for ip in ips:
        print("   簡易快速提交（不含規準卡片）： %s" % url(ip, port))
    print()
    for ip in ips:
        print("   投影分享牆　： %swall" % url(ip, port))
    print()
    print(" ⚠ 第一次啟動時，Windows 可能會跳出「Windows 防火牆已封鎖部分")
    print("   功能」的視窗，請務必勾選「私人網路」與「公用網路」兩個選項")
    print("   後按「允許存取」，否則其他裝置將無法連線送出分享。")
    print("   若已經跳過這個視窗，可到「Windows 安全性 → 防火牆與網路保護")
    print("   → 允許應用程式通過防火牆」，找到 Python 並勾選兩個網路類型。")
    print()
    print(" 按 Ctrl+C 可停止伺服器。資料會儲存在：")
    print("   %s" % DATA_FILE)
    print("=" * 56)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n伺服器已停止。")


if __name__ == "__main__":
    main()
