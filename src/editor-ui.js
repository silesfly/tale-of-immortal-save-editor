// FILE: src/editor-ui.js
(function () {
  'use strict';

  const Catalog = window.TaleOfImmortalCatalog || window.TOICatalog;
  const Codec = window.TaleOfImmortalCodec || window.TOICodec;
  const Core = window.TaleOfImmortalCore || window.TOICore;

  const $ = id => document.getElementById(id);
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  }[c]));
  const val = v => (v === undefined || v === null ? '' : String(v));
  const num = v => (Number.isFinite(+v) ? +v : 0);

  function setStatus(msg, tone) {
    const el = $('status-banner');
    if (!el) return;
    el.textContent = msg;
    el.dataset.tone = tone || '';
  }

  let currentSession = null;
  let busyCount = 0;
  let nativeSession = null;
  let pendingNativeSave = null;
  let backgroundSaveReconciling = false;
  let timedOutSaveCount = 0;
  function isSaveOrOpenLocked() {
    return busyCount > 0 || pendingNativeSave !== null;
  }
  let serverSession = null;
  let serverSlot = '';
  let relativePathByName = Object.create(null);
  const uiFilter = { itemQ: '', destinyQ: '', codexQ: '' };
  const dirtyForms = new Set();
  const dirtyControls = new Set();
  let pointerDownButton = null;
  let keyDownButton = null;
  let deferredItemsDomSync = false;
  let deferredFullRender = false;
  let deferredFocusSnapshot = null;

  function hasActiveButtonActivation() {
    return !!((pointerDownButton && pointerDownButton.isConnected) || (keyDownButton && keyDownButton.isConnected));
  }
  function resetDirtyDrafts() {
    dirtyForms.clear();
    dirtyControls.clear();
  }

  const isWebView2 = !!(window.chrome && window.chrome.webview && typeof window.chrome.webview.postMessage === 'function');
  const serverConfig = window.__TOI_SERVER_CONFIG__ || null;
  const mode = isWebView2 ? 'webview2' : (serverConfig ? 'server' : 'browser');

  function syncToolbarButtons() {
    const locked = isSaveOrOpenLocked();
    const disableOnBusy = [
      'btn-load-demo',
      'btn-native-open-slot',
      'btn-native-open-files',
      'btn-server-load',
      'btn-browser-dir',
      'btn-browser-files',
      'server-slot-select'
    ];
    for (const id of disableOnBusy) {
      const el = $(id);
      if (el) el.disabled = locked;
    }
    const nativeSaveBtn = $('btn-native-save');
    if (nativeSaveBtn) nativeSaveBtn.disabled = locked || !currentSession || !nativeSession;
    const serverSaveBtn = $('btn-server-save');
    if (serverSaveBtn) serverSaveBtn.disabled = locked || !currentSession || !serverSlot || !serverSession;
    const browserExportBtn = $('btn-browser-export');
    if (browserExportBtn) browserExportBtn.disabled = locked || !currentSession;
  }

  function setBusy(delta) {
    busyCount = Math.max(0, busyCount + delta);
    syncToolbarButtons();
  }

  function confirmDiscardIfDirty() {
    if (typeof window.hasUnsavedChanges === 'function' && window.hasUnsavedChanges()) {
      return typeof window.confirm === 'function'
        ? window.confirm('저장하지 않은 변경 사항이 있습니다. 새 슬롯을 열면 현재 수정 내용이 사라집니다. 계속할까요?')
        : true;
    }
    return true;
  }

  document.querySelectorAll('.toolbar-group[data-mode]').forEach(g => {
    g.hidden = g.dataset.mode !== mode;
  });
  const badge = $('transport-badge');
  if (badge) {
    badge.textContent = mode === 'webview2'
      ? 'WebView2 데스크톱'
      : (mode === 'server' ? '로컬 보안 서버' : '오프라인 브라우저');
  }
  syncToolbarButtons();

  let rpcSeq = 0;
  const pendingRpc = new Map();

  function getRpcTimeoutMs() {
    return window.__TOI_RPC_TIMEOUT_MS__ > 0 ? window.__TOI_RPC_TIMEOUT_MS__ : 30000;
  }

  function getRpcPollMs() {
    return window.__TOI_RPC_POLL_MS__ > 0 ? window.__TOI_RPC_POLL_MS__ : 250;
  }

  function sleepMs(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  if (isWebView2) {
    window.chrome.webview.addEventListener('message', ev => {
      const msg = typeof ev.data === 'string' ? JSON.parse(ev.data) : ev.data;
      const p = msg && pendingRpc.get(msg.id);
      if (!p) {
        if (pendingNativeSave && msg && msg.id === pendingNativeSave.rpcId) {
          pendingNativeSave.lateResult = msg;
        }
        return;
      }
      clearTimeout(p.timer);
      pendingRpc.delete(msg.id);
      if (msg.ok === false || msg.error) p.reject(new Error(msg.error || 'WebView2 작업 실패'));
      else p.resolve(msg);
    });
  }

  function rpcCall(kind, payload, opts) {
    if (!isWebView2) return Promise.reject(new Error('WebView2 브리지를 사용할 수 없습니다.'));
    return new Promise((resolve, reject) => {
      opts = opts || {};
      const seq = ++rpcSeq;
      const id = opts.id || ('rpc-' + seq);
      const timeoutMs = opts.timeoutMs > 0 ? opts.timeoutMs : getRpcTimeoutMs();
      const timer = setTimeout(() => {
        pendingRpc.delete(id);
        const err = new Error('WebView2 응답 시간 초과: ' + kind);
        err.timedOut = true;
        err.rpcId = id;
        reject(err);
      }, timeoutMs);
      pendingRpc.set(id, { resolve, reject, timer });
      try {
        window.chrome.webview.postMessage(Object.assign({ id, seq }, payload || {}, { kind }));
      } catch (err) {
        clearTimeout(timer);
        pendingRpc.delete(id);
        reject(err);
      }
    });
  }

  async function nativeOpen(kind) {
    if (isSaveOrOpenLocked()) return;
    if (!confirmDiscardIfDirty()) return;
    setBusy(1);
    try {
      const res = await rpcCall(kind, {});
      if (!res || res.cancelled) return;
      const entries = (res.files || []).map(f => ({
        name: f.name,
        path: f.relativePath || f.name,
        bytes: Codec.base64ToBytes(f.base64)
      }));
      let sess;
      try {
        sess = await Core.openSession(entries, { slotLabel: res.folder || 'WebView2 슬롯' });
      } catch (err) {
        await rpcCall('discard-pending-session', { session: res.session }).catch(() => {});
        throw err;
      }
      await rpcCall('confirm-session', { session: res.session });
      currentSession = sess;
      resetDirtyDrafts();
      nativeSession = res.session;
      serverSession = null;
      relativePathByName = Object.create(null);
      for (const f of res.files || []) relativePathByName[f.name] = f.relativePath || f.name;
      renderAll();
      setStatus('세이브 슬롯을 불러왔습니다: ' + (res.folder || ''), 'ok');
    } finally {
      setBusy(-1);
    }
  }

  async function collectDirtyForSave(emptyMsg) {
    flushPendingForms();
    const dirty = await Core.exportDirtyFiles(currentSession);
    if (!dirty.length) {
      setStatus(emptyMsg, 'ok');
      return null;
    }
    return dirty;
  }

  function captureFocusSnapshot() {
    const activeEl = document.activeElement;
    const activeId = activeEl && activeEl.id ? activeEl.id : '';
    let activeSel = '';
    if (!activeId && activeEl && activeEl.dataset) {
      if (activeEl.dataset.invIndex !== undefined) {
        activeSel = activeEl.dataset.soleId
          ? '[data-inv-index][data-sole-id="' + activeEl.dataset.soleId + '"]'
          : '[data-inv-index="' + activeEl.dataset.invIndex + '"]';
      } else if (activeEl.dataset.martialSole !== undefined) {
        activeSel = '[data-martial-sole="' + activeEl.dataset.martialSole + '"][data-field="' + (activeEl.dataset.field || '') + '"]';
      } else if (activeEl.dataset.spriteIndex !== undefined) {
        activeSel = '[data-sprite-index="' + activeEl.dataset.spriteIndex + '"][data-field="' + (activeEl.dataset.field || '') + '"]';
      } else if (activeEl.dataset.npcId !== undefined) {
        activeSel = '[data-npc-id="' + activeEl.dataset.npcId + '"]';
      } else if (activeEl.dataset.currency !== undefined) {
        activeSel = '[data-currency="' + activeEl.dataset.currency + '"]';
      } else if (activeEl.dataset.action === 'remove-inventory' && activeEl.dataset.soleId) {
        activeSel = 'button[data-action="remove-inventory"][data-sole-id="' + activeEl.dataset.soleId + '"]';
      } else if (activeEl.dataset.action === 'remove-destiny' && activeEl.dataset.kind !== undefined && activeEl.dataset.index !== undefined) {
        activeSel = 'button[data-action="remove-destiny"][data-kind="' + activeEl.dataset.kind + '"][data-index="' + activeEl.dataset.index + '"]';
      } else if (activeEl.dataset.action) {
        activeSel = 'button[data-action="' + activeEl.dataset.action + '"]' + (activeEl.dataset.kind ? '[data-kind="' + activeEl.dataset.kind + '"]' : '');
      } else if (activeEl.dataset.preset) {
        activeSel = 'button[data-preset="' + activeEl.dataset.preset + '"]';
      } else if (activeEl.dataset.filter) {
        activeSel = '[data-filter="' + activeEl.dataset.filter + '"]';
      } else if (activeEl.dataset.sect) {
        activeSel = '[data-sect="' + activeEl.dataset.sect + '"]';
      } else if (typeof activeEl.hasAttribute === 'function' && activeEl.hasAttribute('data-item-select')) {
        activeSel = '[data-item-select]';
      } else if (typeof activeEl.hasAttribute === 'function' && activeEl.hasAttribute('data-item-count')) {
        activeSel = '[data-item-count]';
      } else if (typeof activeEl.hasAttribute === 'function' && activeEl.hasAttribute('data-destiny-select')) {
        activeSel = '[data-destiny-select]';
      } else if (typeof activeEl.hasAttribute === 'function' && activeEl.hasAttribute('data-destiny-dur')) {
        activeSel = '[data-destiny-dur]';
      }
    }
    const selStart = activeEl && typeof activeEl.selectionStart === 'number' ? activeEl.selectionStart : null;
    const selEnd = activeEl && typeof activeEl.selectionEnd === 'number' ? activeEl.selectionEnd : null;
    return { activeId, activeSel, selStart, selEnd };
  }

  function restoreFocusSnapshot(snap) {
    if (!snap) return;
    const nextEl = snap.activeId ? $(snap.activeId) : (snap.activeSel ? document.querySelector(snap.activeSel) : null);
    if (nextEl) {
      nextEl.focus({ preventScroll: true });
      if (snap.selStart !== null && typeof nextEl.setSelectionRange === 'function') {
        try { nextEl.setSelectionRange(snap.selStart, snap.selEnd); } catch (_) {}
      }
    }
  }

  function renderWithFocusRestore(snap) {
    const focusSnap = snap !== undefined ? snap : (deferredFocusSnapshot || captureFocusSnapshot());
    renderAll();
    restoreFocusSnapshot(focusSnap);
  }

  function finalizeSavedBatch(dirty) {
    const snap = captureFocusSnapshot();
    flushPendingForms(false);
    Core.markSessionClean(currentSession, dirty);
    if (hasActiveButtonActivation()) {
      deferredFullRender = true;
      deferredFocusSnapshot = snap;
      syncToolbarButtons();
    } else {
      renderWithFocusRestore(snap);
    }
  }

  async function reconcilePendingNativeSaveStep() {
    const pending = pendingNativeSave;
    if (!pending) return { done: true };
    const statusTimeout = window.__TOI_STATUS_TIMEOUT_MS__ > 0
      ? window.__TOI_STATUS_TIMEOUT_MS__
      : Math.max(getRpcTimeoutMs(), 5000);
    let st;
    try {
      st = await rpcCall('session-status', {}, { timeoutMs: statusTimeout });
    } catch (err) {
      if (err && err.timedOut) return { done: false };
      pendingNativeSave = null;
      nativeSession = null;
      syncToolbarButtons();
      throw err;
    }
    if (st && st.working) return { done: false };
    if (st && st.lastCompletedSaveId === pending.rpcId && st.lastCompletedSaveSession) {
      pendingNativeSave = null;
      nativeSession = st.lastCompletedSaveSession;
      if (currentSession === pending.sessionObj) {
        finalizeSavedBatch(pending.dirty);
      } else {
        syncToolbarButtons();
      }
      setStatus('원본 .backup-*.bak 백업 생성 및 원자적 저장 완료 (' + pending.dirty.length + '개 파일)', 'ok');
      return { done: true };
    }
    if (st && st.activeSession === pending.prevSession) {
      pendingNativeSave = null;
      syncToolbarButtons();
      throw new Error((pending.lateResult && pending.lateResult.error)
        ? pending.lateResult.error
        : '저장이 완료되지 않았습니다. 상태를 확인한 뒤 다시 시도해 주세요.');
    }
    pendingNativeSave = null;
    nativeSession = null;
    syncToolbarButtons();
    throw new Error('열었던 세이브 세션 상태가 변경되었습니다. 슬롯을 다시 열어 주세요.');
  }

  async function ensureBackgroundSaveReconciler() {
    if (backgroundSaveReconciling) return;
    backgroundSaveReconciling = true;
    try {
      while (pendingNativeSave) {
        await sleepMs(getRpcPollMs());
        const result = await reconcilePendingNativeSaveStep();
        if (result && result.done) break;
      }
    } catch (err) {
      setStatus(err && err.message ? err.message : '저장 상태 확인 중 오류가 발생했습니다.', 'error');
    } finally {
      backgroundSaveReconciling = false;
    }
  }

  async function nativeSave() {
    if (isSaveOrOpenLocked()) return;
    setBusy(1);
    try {
      if (!currentSession || !nativeSession) {
        setStatus('먼저 슬롯 폴더를 열어 주세요.', 'error');
        return;
      }
      const dirty = await collectDirtyForSave('저장할 변경 사항이 없습니다.');
      if (!dirty) return;
      const saveRpcId = 'rpc-save-' + (++rpcSeq);
      const prevSession = nativeSession;
      try {
        const res = await rpcCall('save-files', {
          session: nativeSession,
          files: dirty.map(f => ({
            name: f.name,
            relativePath: relativePathByName[f.name] || f.name,
            base64: Codec.bytesToBase64(f.bytes)
          }))
        }, { id: saveRpcId });
        nativeSession = res.session;
        finalizeSavedBatch(dirty);
        setStatus('원본 .backup-*.bak 백업 생성 및 원자적 저장 완료 (' + dirty.length + '개 파일)', 'ok');
      } catch (err) {
        if (!(err && err.timedOut)) throw err;
        timedOutSaveCount++;
        pendingNativeSave = {
          rpcId: saveRpcId,
          prevSession,
          dirty,
          sessionObj: currentSession,
          lateResult: null
        };
        syncToolbarButtons();
        setStatus('저장 응답이 지연되어 호스트 완료 상태를 확인하고 있습니다...', 'info');
        const maxPolls = window.__TOI_RPC_MAX_POLLS__ > 0 ? window.__TOI_RPC_MAX_POLLS__ : 20;
        let reconciled = false;
        try {
          for (let i = 0; i < maxPolls; i++) {
            await sleepMs(getRpcPollMs());
            const result = await reconcilePendingNativeSaveStep();
            if (result && result.done) {
              reconciled = true;
              break;
            }
          }
        } catch (pollErr) {
          setStatus(pollErr && pollErr.message ? pollErr.message : '저장 상태 확인 중 오류가 발생했습니다.', 'error');
          return;
        }
        if (!reconciled && pendingNativeSave) {
          ensureBackgroundSaveReconciler();
          setStatus('저장 작업이 계속 진행 중입니다. 완료가 확인될 때까지 재저장이 잠깁니다.', 'error');
        }
      }
    } finally {
      setBusy(-1);
    }
  }

  async function apiFetch(path, body) {
    const res = await fetch(path, {
      method: body ? 'POST' : 'GET',
      headers: Object.assign(
        { 'X-Toi-Token': serverConfig.token },
        body ? { 'Content-Type': 'application/json' } : {}
      ),
      body: body ? JSON.stringify(body) : undefined
    });
    let json;
    try {
      json = await res.json();
    } catch (_) {
      throw new Error('서버 JSON 응답을 해석할 수 없습니다.');
    }
    if (!res.ok || json.ok === false) {
      throw new Error(json.error || ('HTTP ' + res.status));
    }
    return json;
  }

  async function refreshServerSlots() {
    if (!serverConfig) return;
    const json = await apiFetch('/api/slots');
    const sel = $('server-slot-select');
    if (!sel) return;
    sel.innerHTML = '';
    for (const s of json.slots || []) {
      const opt = document.createElement('option');
      opt.value = s.slot || s.id || s.name;
      opt.textContent = s.label || s.name || opt.value;
      sel.appendChild(opt);
    }
    if (sel.options.length) {
      serverSlot = sel.options[0].value;
      sel.value = serverSlot;
    }
    syncToolbarButtons();
  }

  async function serverLoadSlot() {
    if (isSaveOrOpenLocked()) return;
    const sel = $('server-slot-select');
    const slot = (sel && sel.value) || serverSlot;
    if (!slot) {
      setStatus('불러올 슬롯을 선택하세요.', 'error');
      return;
    }
    if (!confirmDiscardIfDirty()) return;
    setBusy(1);
    try {
      const res = await apiFetch('/api/load-slot', { slot });
      const entries = (res.files || []).map(f => ({
        name: f.name,
        path: f.relativePath || f.name,
        bytes: Codec.base64ToBytes(f.base64)
      }));
      currentSession = await Core.openSession(entries, { slotLabel: res.label || slot });
      resetDirtyDrafts();
      serverSession = res.session || slot;
      serverSlot = slot;
      nativeSession = null;
      relativePathByName = Object.create(null);
      for (const f of res.files || []) relativePathByName[f.name] = f.relativePath || f.name;
      renderAll();
      setStatus('서버에서 슬롯을 불러왔습니다: ' + slot, 'ok');
    } finally {
      setBusy(-1);
    }
  }

  async function serverSaveSlot() {
    if (isSaveOrOpenLocked()) return;
    setBusy(1);
    try {
      if (!currentSession || !serverSlot || !serverSession) {
        setStatus('먼저 서버 슬롯을 불러오세요.', 'error');
        return;
      }
      const dirty = await collectDirtyForSave('저장할 변경 사항이 없습니다.');
      if (!dirty) return;
      const res = await apiFetch('/api/save-slot', {
        slot: serverSlot,
        session: serverSession,
        files: dirty.map(f => ({
          name: f.name,
          relativePath: relativePathByName[f.name] || f.name,
          base64: Codec.bytesToBase64(f.bytes)
        }))
      });
      serverSession = res.session || serverSession;
      finalizeSavedBatch(dirty);
      setStatus('서버 원본 백업(.bak) 생성 및 저장 완료 (' + dirty.length + '개 파일)', 'ok');
    } finally {
      setBusy(-1);
    }
  }

  async function browserPickDir() {
    if (isSaveOrOpenLocked()) return;
    if (typeof window.showDirectoryPicker !== 'function') {
      const fi = $('file-input');
      if (fi) fi.click();
      return;
    }
    if (!confirmDiscardIfDirty()) return;
    let dir;
    try {
      dir = await window.showDirectoryPicker();
    } catch (err) {
      if (err && err.name === 'AbortError') return;
      throw err;
    }
    if (!dir) return;
    setBusy(1);
    try {
      const files = [];
      for await (const ent of dir.values()) {
        if (ent.kind === 'file') {
          const file = await ent.getFile();
          files.push({ name: ent.name, path: ent.name, bytes: new Uint8Array(await file.arrayBuffer()) });
        }
      }
      currentSession = await Core.openSession(files, { slotLabel: dir.name });
      resetDirtyDrafts();
      nativeSession = null;
      serverSession = null;
      relativePathByName = Object.create(null);
      renderAll();
      setStatus('폴더를 불러왔습니다: ' + dir.name, 'ok');
    } finally {
      setBusy(-1);
    }
  }

  async function browserPickFiles(fileList) {
    if (isSaveOrOpenLocked()) return;
    if (!fileList || !fileList.length) return;
    if (!confirmDiscardIfDirty()) return;
    setBusy(1);
    try {
      const files = [];
      for (const file of Array.from(fileList)) {
        files.push({
          name: file.name,
          path: file.webkitRelativePath || file.name,
          bytes: new Uint8Array(await file.arrayBuffer())
        });
      }
      currentSession = await Core.openSession(files, { slotLabel: '선택한 파일 (' + files.length + '개)' });
      resetDirtyDrafts();
      nativeSession = null;
      serverSession = null;
      relativePathByName = Object.create(null);
      renderAll();
      setStatus('파일 ' + files.length + '개를 복호화해 불러왔습니다.', 'ok');
    } finally {
      setBusy(-1);
    }
  }

  async function browserExportDirty() {
    if (isSaveOrOpenLocked()) return;
    if (!currentSession) {
      setStatus('먼저 세이브 파일을 불러오세요.', 'error');
      return;
    }
    setBusy(1);
    try {
      const dirty = await collectDirtyForSave('내보낼 변경 사항이 없습니다.');
      if (!dirty) return;
      for (const f of dirty) {
        const url = URL.createObjectURL(new Blob([f.bytes]));
        const a = document.createElement('a');
        a.href = url;
        a.download = f.name;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1500);
      }
      finalizeSavedBatch(dirty);
      setStatus('수정된 파일 ' + dirty.length + '개를 암호화해 다운로드했습니다.', 'ok');
    } finally {
      setBusy(-1);
    }
  }

  async function loadDemo() {
    if (isSaveOrOpenLocked()) return;
    if (!confirmDiscardIfDirty()) return;
    setBusy(1);
    try {
      const files = await Core.createDemoSlotFiles();
      currentSession = await Core.openSession(files, { slotLabel: '체험용 슬롯 (청운)' });
      resetDirtyDrafts();
      nativeSession = null;
      serverSession = null;
      relativePathByName = Object.create(null);
      renderAll();
      setStatus('체험용 슬롯(청운 · 금단 초기)을 불러왔습니다.', 'ok');
    } finally {
      setBusy(-1);
    }
  }

  function applyStoredColorScheme(val) {
    const meta = document.querySelector('meta[name="color-scheme"]');
    if (meta) meta.content = (val === 'light' || val === 'dark') ? val : 'light dark';
  }

  const themeToggleBtn = $('btn-theme-toggle');
  if (themeToggleBtn) {
    themeToggleBtn.addEventListener('click', () => {
      let stored = null;
      try {
        stored = localStorage.getItem('color-scheme');
      } catch (err) {
        stored = null;
      }
      const current = (stored === 'light' || stored === 'dark')
        ? stored
        : (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
      const target = current === 'dark' ? 'light' : 'dark';
      const systemIsDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
      const systemMatches = (target === 'dark') === systemIsDark;
      try {
        if (systemMatches) localStorage.removeItem('color-scheme');
        else localStorage.setItem('color-scheme', target);
      } catch (err) {}
      applyStoredColorScheme(systemMatches ? null : target);
    });
  }

  window.addEventListener('storage', e => {
    if (!e.key || e.key === 'color-scheme') applyStoredColorScheme(e.newValue);
  });

  const hasNativeFocusGroup = typeof HTMLElement !== 'undefined' && Object.hasOwn(HTMLElement.prototype, 'focusGroup');

  function selectTab(tabBtn, moveFocus) {
    const list = $('editor-tablist');
    if (!list || !tabBtn) return;
    flushPendingForms();
    const tabs = Array.from(list.querySelectorAll('[role="tab"]'));
    for (const t of tabs) {
      const isSel = t === tabBtn;
      t.setAttribute('aria-selected', String(isSel));
      t.toggleAttribute('focusgroupstart', isSel);
      if (!hasNativeFocusGroup) t.tabIndex = isSel ? 0 : -1;
      const panel = $(t.dataset.panel);
      if (panel) {
        if (isSel) panel.removeAttribute('hidden');
        else panel.setAttribute('hidden', 'until-found');
      }
    }
    tabBtn.scrollIntoView({ block: 'nearest', inline: 'nearest', container: 'nearest' });
    if (moveFocus) tabBtn.focus();
  }

  const tablist = $('editor-tablist');
  if (tablist) {
    if (!hasNativeFocusGroup) {
      const tabs = Array.from(tablist.querySelectorAll('[role="tab"]'));
      const selected = tabs.find(t => t.getAttribute('aria-selected') === 'true') || tabs[0];
      for (const t of tabs) t.tabIndex = t === selected ? 0 : -1;
      tablist.addEventListener('focusin', e => {
        const t = e.target.closest('[role="tab"]');
        if (t && t.getAttribute('aria-selected') !== 'true') selectTab(t, false);
      });
    }
    tablist.addEventListener('click', e => {
      const t = e.target.closest('[role="tab"]');
      if (t) selectTab(t, false);
    });
    tablist.addEventListener('keydown', e => {
      if (!['ArrowRight', 'ArrowLeft', 'Home', 'End'].includes(e.key)) return;
      const tabs = Array.from(tablist.querySelectorAll('[role="tab"]'));
      const cur = document.activeElement && document.activeElement.closest('[role="tab"]');
      let idx = Math.max(0, tabs.indexOf(cur));
      if (e.key === 'ArrowRight') idx = (idx + 1) % tabs.length;
      else if (e.key === 'ArrowLeft') idx = (idx - 1 + tabs.length) % tabs.length;
      else if (e.key === 'Home') idx = 0;
      else if (e.key === 'End') idx = tabs.length - 1;
      e.preventDefault();
      selectTab(tabs[idx], true);
    });
  }

  document.querySelectorAll('[role="tabpanel"]').forEach(panel => {
    panel.addEventListener('beforematch', () => {
      const t = $(panel.getAttribute('aria-labelledby'));
      if (t) selectTab(t, false);
    });
  });

  const changelogDialog = $('changelog-dialog');
  const openChangelogBtn = $('btn-open-changelog');
  if (openChangelogBtn) {
    openChangelogBtn.addEventListener('click', () => {
      flushPendingForms();
      renderChangelogDialog();
      if (changelogDialog && typeof changelogDialog.showModal === 'function') {
        changelogDialog.showModal();
      }
    });
  }
  if (changelogDialog) {
    changelogDialog.addEventListener('close', () => {
      changelogDialog.returnValue = '';
    });
  }

  window.addEventListener('beforeunload', e => {
    if (window.hasUnsavedChanges()) {
      e.preventDefault();
      e.returnValue = '';
    }
  });

  function optionList(list, selected, labelFn) {
    return (list || []).map(o => {
      const id = val(o.id);
      const sel = id === val(selected) ? ' selected' : '';
      const text = labelFn ? labelFn(o) : (o.kr || o.name || id);
      return `<option value="${esc(id)}"${sel}>${esc(text)}</option>`;
    }).join('');
  }

  function wrapTable(captionId, captionText, labelsCss, headHtml, bodyHtml) {
    return `<div tabindex="0" role="region" aria-labelledby="${esc(captionId)}" class="table-wrapper">` +
      `<table style="${esc(labelsCss)}"><caption id="${esc(captionId)}">${esc(captionText)}</caption>` +
      `<thead><tr>${headHtml}</tr></thead><tbody>${bodyHtml}</tbody></table></div>`;
  }

  function renderHeaderAndFiles() {
    const strip = $('summary-strip');
    const pbar = $('preset-bar');
    const clBtn = $('btn-open-changelog');
    const tbody = $('loaded-files-tbody');

    if (!currentSession) {
      if (strip) strip.innerHTML = '';
      if (pbar) pbar.innerHTML = '';
      if (clBtn) clBtn.textContent = '변경 내역 (0)';
      if (tbody) tbody.innerHTML = '<tr><th scope="row" colspan="5">불러온 세이브 파일이 없습니다.</th></tr>';
      return;
    }

    const s = Core.getSummary(currentSession);
    if (strip) {
      strip.innerHTML =
        `<span class="kpi">슬롯<strong>${esc(s.slotLabel || '-')}</strong></span>` +
        `<span class="kpi">성명<strong>${esc(s.fullName || '-')}</strong></span>` +
        `<span class="kpi">경지<strong>${esc(s.realmKr || ('#' + s.gradeID))}</strong></span>` +
        `<span class="kpi">일정<strong>${s.calendar.year}년 ${s.calendar.month}월 ${s.calendar.day}일</strong></span>` +
        `<span class="kpi">난이도<strong>${esc(s.difficultyKr || ('#' + s.gameLevel))}</strong></span>` +
        `<span class="kpi">영석<strong>${s.spiritStones.toLocaleString()}</strong></span>` +
        `<span class="kpi">변경 파일<strong>${s.dirtyFiles.length} / ${currentSession.files.length}</strong></span>`;
    }
    if (pbar && !pbar.querySelector('[data-preset]')) {
      pbar.innerHTML = '<span class="muted">원클릭 프리셋:</span>' + (Core.PRESETS || []).map(p =>
        `<button type="button" class="btn sm" data-preset="${esc(p.id)}" title="${esc(p.desc)}">${esc(p.kr)}</button>`
      ).join('');
    }
    if (clBtn) clBtn.textContent = `변경 내역 (${currentSession.changelog.length})`;
    if (tbody) {
      tbody.innerHTML = currentSession.files.map(f =>
        `<tr><th scope="row">${esc(f.name)}</th><td>${esc(f.role)}</td>` +
        `<td>${f.rawBytes.length.toLocaleString()} B</td><td>${esc(f.mode)}</td>` +
        `<td>${f.dirty ? '<span class="badge dirty">수정됨</span>' : '원본 유지'}</td></tr>`
      ).join('');
    }
  }

  function renderOverview() {
    const el = $('mount-overview');
    if (!el) return;
    dirtyForms.delete('overview');
    if (!currentSession) {
      el.innerHTML =
        `<div class="subcard" style="margin-block-end:14px;">` +
        `<h2>귀곡팔황 세이브 슬롯을 불러오세요</h2>` +
        `<p class="muted">상단 도구 모음에서 슬롯 폴더를 열거나, 체험용 슬롯으로 모든 편집 기능을 바로 시험해 볼 수 있습니다.</p>` +
        `<button type="button" class="btn primary" data-action="load-demo">체험용 슬롯 불러오기</button></div>`;
      return;
    }
    const s = Core.getSummary(currentSession);
    const cal = s.calendar || { year: 1, month: 1, day: 1 };
    const animas = new Set((s.animaWeapons || []).map(String));
    const disUnit = s.hasUnit === false ? ' disabled' : '';
    const disWorld = s.hasWorld === false ? ' disabled' : '';
    el.innerHTML =
      `<h2>인물 · 세계 진행 정보</h2>` +
      `<div class="section-grid">` +
      `<div class="field"><label for="ov-surname">성(姓)</label><input id="ov-surname" data-id="surname" value="${esc(s.surname)}"></div>` +
      `<div class="field"><label for="ov-given">이름(名)</label><input id="ov-given" data-id="givenName" value="${esc(s.givenName)}"></div>` +
      `<div class="field"><label for="ov-sex">성별</label><select id="ov-sex" data-id="sex"${disUnit}><option value="1"${s.sex === 1 ? ' selected' : ''}>남성</option><option value="2"${s.sex === 2 ? ' selected' : ''}>여성</option></select></div>` +
      `<div class="field"><label for="ov-grade">경지 (1~44)</label><select id="ov-grade" data-id="gradeID">${optionList(Catalog.realms, s.gradeID, r => r.id + '. ' + r.kr)}</select></div>` +
      `<div class="field"><label for="ov-exp">수양 (경험치)</label><input id="ov-exp" type="number" data-id="exp" value="${num(s.exp)}"${disUnit}></div>` +
      `<div class="field"><label for="ov-age">나이 (개월)</label><input id="ov-age" type="number" data-id="age" value="${num(s.ageMonths)}"${disUnit}></div>` +
      `<div class="field"><label for="ov-life">수명 상한 (개월)</label><input id="ov-life" type="number" data-id="life" value="${num(s.lifeMonths)}"${disUnit}></div>` +
      `<div class="field"><label for="ov-year">진행 연(年)</label><input id="ov-year" type="number" data-id="year" min="1" value="${num(cal.year)}"></div>` +
      `<div class="field"><label for="ov-month">진행 월(1~12)</label><input id="ov-month" type="number" data-id="month" min="1" max="12" value="${num(cal.month)}"></div>` +
      `<div class="field"><label for="ov-day">진행 일(1~30)</label><input id="ov-day" type="number" data-id="day" min="1" max="30" value="${num(cal.day)}"></div>` +
      `<div class="field"><label for="ov-diff">난이도</label><select id="ov-diff" data-id="gameLevel">${optionList(Catalog.difficulties, s.gameLevel, d => d.id + '. ' + d.kr)}</select></div>` +
      `<div class="field"><label for="ov-resurge">부활 가능 횟수</label><input id="ov-resurge" type="number" data-id="resurgeCount" min="0" value="${num(s.resurgeCount)}"${disWorld}></div>` +
      `</div>` +
      `<div class="row-actions"><span class="muted">태고 신기:</span>` +
      (Catalog.animaWeapons || []).map(w =>
        `<label for="ov-anima-${esc(w.id)}"><input id="ov-anima-${esc(w.id)}" type="checkbox" data-id="animaWeapons" value="${esc(w.id)}"${animas.has(String(w.id)) ? ' checked' : ''}${disWorld}> ${esc(w.kr)}</label>`
      ).join(' ') +
      `<button type="button" class="btn primary" data-action="apply-identity">인물·세계 정보 적용</button>` +
      (s.createTicks ? `<span class="muted">createTicks(int64): ${esc(s.createTicks)}</span>` : '') +
      `</div>`;
  }

  function renderStats() {
    const el = $('mount-stats');
    if (!el) return;
    if (!currentSession) {
      el.innerHTML = '<p class="muted">세이브를 불러오면 생명·전투·영근·무기·기예 능력치를 편집할 수 있습니다.</p>';
      return;
    }
    const groups = (Catalog.propertyFields && Catalog.propertyFields.groups) || {};
    const labels = {
      vital: '생명 · 영력 · 염력 · 기력',
      combat: '전투 능력치',
      core: '핵심 수양 · 도력 · 성향',
      roots: '6대 영근 자질',
      weapons: '6대 무기 자질',
      artisans: '6대 기예 자질'
    };
    el.innerHTML = Object.keys(labels).map(g => {
      const fields = groups[g] || [];
      return `<h3>${esc(labels[g])}</h3><div class="section-grid">` + fields.map(f =>
        `<div class="field"><label for="prop-${esc(f.key)}">${esc(f.kr)} <span class="muted">(${esc(f.key)})</span></label>` +
        `<input id="prop-${esc(f.key)}" type="number" data-prop-key="${esc(f.key)}" min="${num(f.min)}" max="${num(f.max)}" value="${num(Core.getPropertyValue(currentSession, f.key))}"></div>`
      ).join('') + `</div>`;
    }).join('');
  }

  function buildItemSelectOptions() {
    const q = (uiFilter.itemQ || '').trim().toLowerCase();
    const matches = (Catalog.items || []).filter(i =>
      !q || `${i.id} ${i.kr || ''} ${i.ch || ''} ${i.cat || ''}`.toLowerCase().includes(q)
    ).slice(0, 50);
    return matches.map(i =>
      `<option value="${esc(i.id)}">[#${i.id}] ${esc(i.kr)} (${esc(i.cat || '-')})</option>`
    ).join('');
  }

  function renderInventoryRowHtml(r) {
    const soleAttr = (r.soleId != null && String(r.soleId) !== '') ? ' data-sole-id="' + esc(r.soleId) + '"' : '';
    return '<tr' + soleAttr + '><th scope="row">' + esc(r.kr) + '</th><td>#' + r.itemId + '</td><td>' + esc(r.cat || '-') + '</td>' +
      '<td><input type="number" data-inv-index="' + r.index + '"' + soleAttr + ' min="1" value="' + num(r.count) + '" aria-label="' + esc(r.kr) + ' 수량"></td>' +
      '<td>' + num(r.worth).toLocaleString() + '</td>' +
      '<td><button type="button" class="btn sm danger" data-action="remove-inventory" data-index="' + r.index + '"' + soleAttr + '>삭제</button></td></tr>';
  }

  function renderItems() {
    const el = $('mount-items');
    if (!el) return;
    if (!currentSession) {
      el.innerHTML = '<p class="muted">세이브를 불러오면 재화 및 3,222종 아이템을 지급·편집할 수 있습니다.</p>';
      return;
    }
    const inv = Core.listInventory(currentSession);
    const rows = inv.map(renderInventoryRowHtml).join('') || '<tr><th scope="row" colspan="6">보유 소지품이 없습니다.</th></tr>';

    el.innerHTML =
      `<h2>핵심 재화</h2><div class="section-grid">` +
      `<div class="field"><label for="cur-10001">영석 (#10001)</label><input id="cur-10001" type="number" data-currency="10001" min="0" value="${Core.getCurrencyCount(currentSession, 10001)}"></div>` +
      `<div class="field"><label for="cur-10011">종문 공헌 (#10011)</label><input id="cur-10011" type="number" data-currency="10011" min="0" value="${Core.getCurrencyCount(currentSession, 10011)}"></div>` +
      `<div class="field"><label for="cur-10041">성주령 (#10041)</label><input id="cur-10041" type="number" data-currency="10041" min="0" value="${Core.getCurrencyCount(currentSession, 10041)}"></div>` +
      `</div>` +
      `<h3>카탈로그 아이템 검색 및 지급 (총 ${(Catalog.items || []).length.toLocaleString()}종)</h3>` +
      `<div class="row-actions">` +
      `<input placeholder="한글명·한자·ID·분류 검색" data-filter="itemQ" value="${esc(uiFilter.itemQ)}" aria-label="아이템 검색">` +
      `<select data-item-select aria-label="지급할 아이템 선택">${buildItemSelectOptions()}</select>` +
      `<input type="number" data-item-count min="1" value="10" style="width:96px;" aria-label="지급 수량">` +
      `<button type="button" class="btn primary" data-action="grant-item">소지품 지급</button></div>` +
      wrapTable(
        'inv-caption',
        `보유 소지품 목록 (${inv.length}칸)`,
        "--label-2:'아이템ID';--label-3:'분류';--label-4:'수량';--label-5:'가치';--label-6:'작업';",
        '<th scope="col">아이템명</th><th scope="col">ID</th><th scope="col">분류</th><th scope="col">수량</th><th scope="col">가치</th><th scope="col">작업</th>',
        rows
      );
  }

  function buildDestinySelectOptions() {
    const q = (uiFilter.destinyQ || '').trim().toLowerCase();
    const matches = (Catalog.destinies || []).filter(x =>
      !q || `${x.id} ${x.kr || ''} ${x.ch || ''} ${x.tips || ''}`.toLowerCase().includes(q)
    ).slice(0, 50);
    return matches.map(x =>
      `<option value="${esc(x.id)}">[#${x.id} · 등급 ${x.lv}] ${esc(x.kr)}</option>`
    ).join('');
  }

  function renderDestinies() {
    const el = $('mount-destiny');
    if (!el) return;
    if (!currentSession) {
      el.innerHTML = '<p class="muted">세이브를 불러오면 1,129종 선천기운 및 후천운명을 편집할 수 있습니다.</p>';
      return;
    }
    const d = Core.listDestinies(currentSession);

    const makeRows = (arr, kind) => arr.map(x =>
      `<tr><th scope="row">${esc(x.kr)}</th><td>#${x.id}</td><td>${x.lv}</td><td>${x.dur}</td><td>${esc(x.tips)}</td>` +
      `<td><button type="button" class="btn sm danger" data-action="remove-destiny" data-kind="${kind}" data-index="${x.index}">제거</button></td></tr>`
    ).join('') || '<tr><th scope="row" colspan="6">보유 항목이 없습니다.</th></tr>';

    el.innerHTML =
      `<h2>운명 카탈로그 검색 및 추가 (총 ${(Catalog.destinies || []).length.toLocaleString()}종)</h2>` +
      `<div class="row-actions">` +
      `<input placeholder="기운명·효과·ID 검색" data-filter="destinyQ" value="${esc(uiFilter.destinyQ)}" aria-label="운명 검색">` +
      `<select data-destiny-select aria-label="운명 선택">${buildDestinySelectOptions()}</select>` +
      `<input type="number" data-destiny-dur value="-1" style="width:96px;" title="-1은 영구 지속" aria-label="지속 개월">` +
      `<button type="button" class="btn primary" data-action="add-destiny" data-kind="born">선천기운 추가</button>` +
      `<button type="button" class="btn" data-action="add-destiny" data-kind="add">후천운명 추가</button></div>` +
      wrapTable(
        'born-destiny-caption',
        `선천기운 (${d.born.length}개)`,
        "--label-2:'ID';--label-3:'등급';--label-4:'지속';--label-5:'효과';--label-6:'작업';",
        '<th scope="col">기운명</th><th scope="col">ID</th><th scope="col">등급</th><th scope="col">지속</th><th scope="col">효과</th><th scope="col">작업</th>',
        makeRows(d.born, 'born')
      ) +
      wrapTable(
        'add-destiny-caption',
        `후천운명 (${d.add.length}개)`,
        "--label-2:'ID';--label-3:'등급';--label-4:'지속';--label-5:'효과';--label-6:'작업';",
        '<th scope="col">운명명</th><th scope="col">ID</th><th scope="col">등급</th><th scope="col">지속</th><th scope="col">효과</th><th scope="col">작업</th>',
        makeRows(d.add, 'add')
      );
  }

  function renderMartials() {
    const el = $('mount-martials');
    if (!el) return;
    dirtyForms.delete('heart');
    if (!currentSession) {
      el.innerHTML = '<p class="muted">세이브를 불러오면 습득 비급·기령·도심·명우를 편집할 수 있습니다.</p>';
      return;
    }
    const ms = Core.listMartials(currentSession);
    const sp = Core.listSprites(currentSession);
    const hw = Core.getHeartAndWingman(currentSession);

    const mRows = ms.map(m =>
      `<tr><th scope="row">${esc(m.kr)}</th><td>${esc(m.typeLabel)}</td>` +
      `<td><input type="number" data-martial-sole="${esc(m.soleId)}" data-field="grade" min="1" max="10" value="${num(m.grade)}" style="width:76px;" aria-label="${esc(m.kr)} 경지 등급"></td>` +
      `<td><input type="number" data-martial-sole="${esc(m.soleId)}" data-field="quality" min="1" max="6" value="${num(m.quality)}" style="width:76px;" aria-label="${esc(m.kr)} 품질"></td>` +
      `<td><input type="number" data-martial-sole="${esc(m.soleId)}" data-field="exp" min="0" value="${num(m.exp)}" style="width:110px;" aria-label="${esc(m.kr)} 숙련도"></td></tr>`
    ).join('') || '<tr><th scope="row" colspan="5">습득한 비급이 없습니다.</th></tr>';

    const spRows = sp.map(x =>
      `<tr><th scope="row">${esc(x.kr)}</th><td>${esc(x.skill || '-')}</td>` +
      `<td><input type="number" data-sprite-index="${x.index}" data-field="intimacy" min="0" max="9999" value="${num(x.intimacy)}" style="width:90px;" aria-label="${esc(x.kr)} 친밀도"></td>` +
      `<td><input type="number" data-sprite-index="${x.index}" data-field="exp" min="0" value="${num(x.exp)}" style="width:110px;" aria-label="${esc(x.kr)} 경험치"></td>` +
      `<td><input type="number" data-sprite-index="${x.index}" data-field="stamina" min="0" value="${num(x.stamina)}" style="width:90px;" aria-label="${esc(x.kr)} 기력"></td></tr>`
    ).join('') || '<tr><th scope="row" colspan="5">보유 기령이 없습니다.</th></tr>';

    el.innerHTML =
      `<div class="row-actions"><h2 style="margin:0;margin-inline-end:auto;">습득 비급 (${ms.length}개)</h2>` +
      `<button type="button" class="btn primary" data-action="max-martials">전체 비급 홍색 품질 · 숙련 만렙</button></div>` +
      wrapTable(
        'martials-caption',
        '습득 무예 · 절기 · 신법 · 심법 · 신통',
        "--label-2:'분류';--label-3:'경지(1~10)';--label-4:'품질(1~6)';--label-5:'숙련도';",
        '<th scope="col">비급명</th><th scope="col">분류</th><th scope="col">경지(1~10)</th><th scope="col">품질(1~6)</th><th scope="col">숙련도</th>',
        mRows
      ) +
      `<h3 style="margin-block-start:18px;">동행 기령 (${sp.length}기)</h3>` +
      wrapTable(
        'sprites-caption',
        '보유 기령 성장 정보',
        "--label-2:'특기';--label-3:'친밀도';--label-4:'경험치';--label-5:'기력';",
        '<th scope="col">기령명</th><th scope="col">특기</th><th scope="col">친밀도</th><th scope="col">경험치</th><th scope="col">기력</th>',
        spRows
      ) +
      `<h3 style="margin-block-start:18px;">도심(道心) · 우화 명우(冥羽)</h3>` +
      `<div class="section-grid">` +
      `<div class="field"><label for="hw-confID">도심 종류</label><select id="hw-confID" data-id="confID"><option value="0">없음</option>${optionList(Catalog.hearts, hw.confID, h => h.id + '. ' + h.kr)}</select></div>` +
      `<div class="field"><label for="hw-heartState">도심 단계</label><input id="hw-heartState" type="number" data-id="heartState" min="0" max="10" value="${num(hw.state)}"></div>` +
      `<div class="field"><label for="hw-hp">도심 견고도</label><input id="hw-hp" type="number" data-id="hp" min="0" value="${num(hw.hp)}"></div>` +
      `<div class="field"><label for="hw-heartEffectLevel">도심 효과 등급</label><input id="hw-heartEffectLevel" type="number" data-id="heartEffectLevel" min="0" value="${num(hw.heartEffectLevel)}"></div>` +
      `<div class="field"><label for="hw-heartEffectHP">도심 보호 수치</label><input id="hw-heartEffectHP" type="number" data-id="heartEffectHP" min="0" value="${num(hw.heartEffectHP)}"></div>` +
      `<div class="field"><label for="hw-wingManID">우화 명우</label><select id="hw-wingManID" data-id="wingManID"><option value="0">미선택</option>${optionList(Catalog.wingmen, hw.wingManID, w => w.id + '. ' + w.kr)}</select></div>` +
      `</div>` +
      `<div class="row-actions">` +
      `<label><input type="checkbox" data-id="onDemon"${hw.onDemon ? ' checked' : ''}> 심마 잠식 상태</label>` +
      `<label><input type="checkbox" data-id="isPassRebornBattle"${hw.isPassRebornBattle ? ' checked' : ''}> 명우 돌파 완료</label>` +
      `<button type="button" class="btn primary" data-action="apply-heart">도심·명우 적용</button></div>`;
  }

  function renderSect() {
    const el = $('mount-sect');
    if (!el) return;
    dirtyForms.delete('sect');
    if (!currentSession) {
      el.innerHTML = '<p class="muted">세이브를 불러오면 소속 종문·인연 호감도·전역 업적을 편집할 수 있습니다.</p>';
      return;
    }
    const s = Core.getSectSummary(currentSession);
    const a = Core.getAchievementStats(currentSession);
    const rel = Core.listRelations(currentSession);

    const sectHtml = s.present
      ? `<h2>소속 종문: ${esc(s.name)} (${esc(s.schoolID)})</h2>` +
        `<div class="section-grid">` +
        `<div class="field"><label for="sect-money">종문 영석</label><input id="sect-money" type="number" data-sect="money" min="0" value="${num(s.money)}"></div>` +
        `<div class="field"><label for="sect-reputation">종문 명성</label><input id="sect-reputation" type="number" data-sect="reputation" min="0" value="${num(s.reputation)}"></div>` +
        `<div class="field"><label for="sect-totalMember">종문 인원</label><input id="sect-totalMember" type="number" data-sect="totalMember" min="0" value="${num(s.totalMember)}"></div>` +
        `<div class="field"><label for="sect-prosperous">번영도</label><input id="sect-prosperous" type="number" data-sect="prosperous" min="0" value="${num(s.prosperous)}"></div>` +
        `<div class="field"><label for="sect-prosperousMax">번영도 상한</label><input id="sect-prosperousMax" type="number" data-sect="prosperousMax" min="0" value="${num(s.prosperousMax)}"></div>` +
        `<div class="field"><label for="sect-loyal">충성도</label><input id="sect-loyal" type="number" data-sect="loyal" min="0" value="${num(s.loyal)}"></div>` +
        `<div class="field"><label for="sect-medicina">약재 비축</label><input id="sect-medicina" type="number" data-sect="medicina" min="0" value="${num(s.medicina)}"></div>` +
        `<div class="field"><label for="sect-mine">광재 비축</label><input id="sect-mine" type="number" data-sect="mine" min="0" value="${num(s.mine)}"></div>` +
        `<div class="field"><label for="sect-largeArrayHP">호산대진 내구도</label><input id="sect-largeArrayHP" type="number" data-sect="largeArrayHP" min="0" value="${num(s.largeArrayHP)}"></div>` +
        `<div class="field"><label for="sect-largeArrayHPMax">호산대진 최대 내구도</label><input id="sect-largeArrayHPMax" type="number" data-sect="largeArrayHPMax" min="0" value="${num(s.largeArrayHPMax)}"></div>` +
        `</div><div class="row-actions"><button type="button" class="btn primary" data-action="apply-sect">종문 자원 적용</button></div>`
      : `<div class="subcard" style="margin-block-end:14px;"><h4>소속 종문 없음</h4><p class="muted">현재 캐릭터가 가입한 종문이 없거나 종문 캐시 파일이 로드되지 않았습니다.</p></div>`;

    const achHtml = a.present
      ? `<div class="subcard" style="margin-block-end:14px;"><h4>전역 업적 (DataGloble.cache): ${a.unlocked} / ${a.total} 해금</h4>` +
        `<button type="button" class="btn primary" data-action="unlock-achievements">전역 업적 일괄 해금</button></div>`
      : `<div class="subcard" style="margin-block-end:14px;"><h4>전역 업적 파일 미포함</h4><p class="muted">상위 폴더의 DataGloble.cache를 함께 열면 업적 일괄 해금이 활성화됩니다.</p></div>`;

    const relRows = rel.map(r =>
      `<tr><th scope="row">${esc(r.name)}</th><td>${esc(r.realmKr || '-')}</td><td>${esc((r.tags || []).join(', ') || '일반')}</td>` +
      `<td><input type="number" data-npc-id="${esc(r.npcId)}" min="-1000" max="1000" value="${num(r.toNpc)}" style="width:100px;" aria-label="${esc(r.name)} 호감도"></td></tr>`
    ).join('') || '<tr><th scope="row" colspan="4">기록된 인연 관계가 없습니다.</th></tr>';

    el.innerHTML = sectHtml + achHtml + wrapTable(
      'relations-caption',
      `인물 인연 및 호감도 (${rel.length}명)`,
      "--label-2:'경지';--label-3:'관계';--label-4:'호감도(-1000~1000)';",
      '<th scope="col">이름</th><th scope="col">경지</th><th scope="col">관계</th><th scope="col">호감도 (-1000~1000)</th>',
      relRows
    );
  }

  function buildCodexResultsHtml() {
    const q = (uiFilter.codexQ || '').trim().toLowerCase();
    const hit = obj => !q || JSON.stringify(obj).toLowerCase().includes(q);
    const builds = (Catalog.endgameBuilds || []).filter(hit);
    const domains = (Catalog.domains || []).filter(hit);
    const codex = (Catalog.codexEntries || []).filter(hit);

    const codexRows = codex.map(c =>
      `<tr><th scope="row">${esc(c.name_ko)}</th><td>${esc(c.tier)}</td><td>${esc(c.effects)}</td><td>${esc(c.source)}</td></tr>`
    ).join('') || '<tr><th scope="row" colspan="4">검색 결과가 없습니다.</th></tr>';

    return `<h3>6대 혼돈 난이도 대표 엔드빌드</h3><div class="cards-grid" style="margin-block-end:16px;">` +
      builds.map((b, idx) => `<div class="subcard"><h4>엔드빌드 #${idx + 1} ${esc(b.name || '')}</h4><p class="muted">${esc(b.summary)}</p></div>`).join('') +
      `</div><h3>12대 도흔 영역 규칙</h3><div class="cards-grid" style="margin-block-end:16px;">` +
      domains.map(d => `<div class="subcard"><h4>${esc(d.root)} · ${esc(d.stone)}</h4><p>${esc(d.main_rule)}</p><p class="muted">부규칙: ${esc(d.sub_rule)}</p></div>`).join('') +
      `</div>` +
      wrapTable(
        'codex-caption',
        `12대 계통 핵심 비급 도감 (${codex.length}항목)`,
        "--label-2:'계통·단계';--label-3:'핵심 효과';--label-4:'입수처';",
        '<th scope="col">비급명</th><th scope="col">계통·단계</th><th scope="col">핵심 효과</th><th scope="col">입수처</th>',
        codexRows
      );
  }

  function renderCodex() {
    const el = $('mount-codex');
    if (!el) return;
    el.innerHTML =
      `<div class="row-actions"><h2 style="margin:0;margin-inline-end:auto;">귀곡팔황 전서 · 혼돈 엔드빌드 · 영역 규칙</h2>` +
      `<input placeholder="기술명·영역·빌드 검색" data-filter="codexQ" value="${esc(uiFilter.codexQ)}" aria-label="전서 검색"></div>` +
      `<div id="codex-results">${buildCodexResultsHtml()}</div>`;
  }

  function renderChangelogDialog() {
    const body = $('changelog-body');
    if (!body) return;
    if (!currentSession || !currentSession.changelog.length) {
      body.innerHTML = '<p class="muted">아직 기록된 변경 사항이 없습니다.</p>';
      return;
    }
    const rows = currentSession.changelog.map((c, idx) =>
      `<tr><th scope="row">#${idx + 1}</th><td>${esc(c.role)}</td><td>${esc(c.label)}</td>` +
      `<td>${esc(JSON.stringify(c.before))}</td><td>${esc(JSON.stringify(c.after))}</td></tr>`
    ).join('');
    body.innerHTML = wrapTable(
      'changelog-table-caption',
      `세션 변경 기록 (${currentSession.changelog.length}건)`,
      "--label-2:'파일역할';--label-3:'항목';--label-4:'이전';--label-5:'이후';",
      '<th scope="col">순번</th><th scope="col">역할</th><th scope="col">항목</th><th scope="col">이전</th><th scope="col">이후</th>',
      rows
    );
  }

  function renderAll() {
    deferredItemsDomSync = false;
    deferredFullRender = false;
    deferredFocusSnapshot = null;
    renderHeaderAndFiles();
    renderOverview();
    renderStats();
    renderItems();
    renderDestinies();
    renderMartials();
    renderSect();
    renderCodex();
    syncToolbarButtons();
  }

  function applyIdentityForm() {
    if (!currentSession) return;
    const root = $('mount-overview');
    const g = id => root && root.querySelector(`[data-id="${id}"]`);
    const s = Core.getSummary(currentSession);
    const patch = {
      surname: g('surname') ? g('surname').value : '',
      givenName: g('givenName') ? g('givenName').value : '',
      gradeID: num(g('gradeID') && g('gradeID').value),
      worldDay: Core.worldDayFromCalendar(
        num(g('year') && g('year').value),
        num(g('month') && g('month').value),
        num(g('day') && g('day').value)
      ),
      gameLevel: num(g('gameLevel') && g('gameLevel').value)
    };
    if (s.hasUnit !== false) {
      patch.sex = num(g('sex') && g('sex').value);
      patch.exp = num(g('exp') && g('exp').value);
      patch.age = num(g('age') && g('age').value);
      patch.life = num(g('life') && g('life').value);
    }
    if (s.hasWorld !== false) {
      patch.resurgeCount = num(g('resurgeCount') && g('resurgeCount').value);
      patch.animaWeapons = root
        ? Array.from(root.querySelectorAll('[data-id="animaWeapons"]:checked')).map(x => num(x.value))
        : [];
    }
    Core.setPlayerIdentity(currentSession, patch);
    dirtyForms.delete('overview');
  }

  function applyHeartForm() {
    if (!currentSession) return;
    const root = $('mount-martials');
    const g = id => root && root.querySelector(`[data-id="${id}"]`);
    Core.updateHeartAndWingman(currentSession, {
      confID: num(g('confID') && g('confID').value),
      state: num(g('heartState') && g('heartState').value),
      onDemon: !!(g('onDemon') && g('onDemon').checked),
      hp: num(g('hp') && g('hp').value),
      heartEffectLevel: num(g('heartEffectLevel') && g('heartEffectLevel').value),
      heartEffectHP: num(g('heartEffectHP') && g('heartEffectHP').value),
      isPassRebornBattle: !!(g('isPassRebornBattle') && g('isPassRebornBattle').checked),
      wingManID: num(g('wingManID') && g('wingManID').value)
    });
    dirtyForms.delete('heart');
  }

  function applySectForm() {
    if (!currentSession) return;
    const root = $('mount-sect');
    const g = k => root && root.querySelector(`[data-sect="${k}"]`);
    if (!root || !root.querySelector('[data-sect="money"]')) {
      dirtyForms.delete('sect');
      return;
    }
    Core.updateSect(currentSession, {
      money: num(g('money') && g('money').value),
      reputation: num(g('reputation') && g('reputation').value),
      totalMember: num(g('totalMember') && g('totalMember').value),
      prosperous: num(g('prosperous') && g('prosperous').value),
      prosperousMax: num(g('prosperousMax') && g('prosperousMax').value),
      loyal: num(g('loyal') && g('loyal').value),
      medicina: num(g('medicina') && g('medicina').value),
      mine: num(g('mine') && g('mine').value),
      largeArrayHP: num(g('largeArrayHP') && g('largeArrayHP').value),
      largeArrayHPMax: num(g('largeArrayHPMax') && g('largeArrayHPMax').value)
    });
    dirtyForms.delete('sect');
  }

  const INLINE_CONTROL_SEL = '[data-currency],[data-inv-index],[data-prop-key],[data-martial-sole],[data-sprite-index],[data-npc-id]';

  function commitInlineControl(t, syncDomValue) {
    if (!currentSession || !t || typeof t.matches !== 'function') return false;
    dirtyControls.delete(t);
    if (t.matches('[data-currency]')) {
      Core.setCurrencyCount(currentSession, num(t.dataset.currency), num(t.value));
      if (syncDomValue) t.value = val(Core.getCurrencyCount(currentSession, num(t.dataset.currency)));
    } else if (t.matches('[data-inv-index]')) {
      const soleId = t.dataset.soleId || '';
      const curInv = Core.listInventory(currentSession);
      const live = soleId ? curInv.find(x => String(x.soleId) === soleId) : curInv.find(x => x.index === num(t.dataset.invIndex));
      if (live) {
        Core.setInventoryCount(currentSession, live.index, num(t.value));
        if (syncDomValue) {
          const after = soleId
            ? Core.listInventory(currentSession).find(x => String(x.soleId) === soleId)
            : Core.listInventory(currentSession).find(x => x.index === live.index);
          if (after) t.value = val(num(after.count));
        }
      }
    } else if (t.matches('[data-prop-key]')) {
      Core.setPropertyValue(currentSession, t.dataset.propKey, num(t.value));
      if (syncDomValue) t.value = val(num(Core.getPropertyValue(currentSession, t.dataset.propKey)));
    } else if (t.matches('[data-martial-sole]')) {
      const tr = t.closest('tr');
      if (tr) tr.querySelectorAll('[data-martial-sole]').forEach(el => dirtyControls.delete(el));
      Core.setMartialGradeQuality(
        currentSession,
        t.dataset.martialSole,
        num(tr && tr.querySelector('[data-field="grade"]') ? tr.querySelector('[data-field="grade"]').value : 0),
        num(tr && tr.querySelector('[data-field="quality"]') ? tr.querySelector('[data-field="quality"]').value : 0),
        num(tr && tr.querySelector('[data-field="exp"]') ? tr.querySelector('[data-field="exp"]').value : 0)
      );
      if (syncDomValue && tr) {
        const m = Core.listMartials(currentSession).find(x => x.soleId === t.dataset.martialSole);
        if (m) {
          const grade = tr.querySelector('[data-field="grade"]');
          const quality = tr.querySelector('[data-field="quality"]');
          const exp = tr.querySelector('[data-field="exp"]');
          if (grade) grade.value = val(m.grade);
          if (quality) quality.value = val(m.quality);
          if (exp) exp.value = val(m.exp);
        }
      }
    } else if (t.matches('[data-sprite-index]')) {
      const tr = t.closest('tr');
      if (tr) tr.querySelectorAll('[data-sprite-index]').forEach(el => dirtyControls.delete(el));
      Core.updateSprite(currentSession, num(t.dataset.spriteIndex), {
        intimacy: num(tr && tr.querySelector('[data-field="intimacy"]') ? tr.querySelector('[data-field="intimacy"]').value : 0),
        exp: num(tr && tr.querySelector('[data-field="exp"]') ? tr.querySelector('[data-field="exp"]').value : 0),
        stamina: num(tr && tr.querySelector('[data-field="stamina"]') ? tr.querySelector('[data-field="stamina"]').value : 0)
      });
      if (syncDomValue && tr) {
        const sp = Core.listSprites(currentSession)[num(t.dataset.spriteIndex)];
        if (sp) {
          const intimacy = tr.querySelector('[data-field="intimacy"]');
          const exp = tr.querySelector('[data-field="exp"]');
          const stamina = tr.querySelector('[data-field="stamina"]');
          if (intimacy) intimacy.value = val(sp.intimacy);
          if (exp) exp.value = val(sp.exp);
          if (stamina) stamina.value = val(sp.stamina);
        }
      }
    } else if (t.matches('[data-npc-id]')) {
      Core.setNpcIntimacy(currentSession, t.dataset.npcId, num(t.value));
      if (syncDomValue) {
        const rel = Core.listRelations(currentSession).find(x => x.npcId === t.dataset.npcId);
        if (rel) t.value = val(rel.toNpc);
      }
    } else {
      return false;
    }
    return true;
  }

  function flushPendingForms(renderAfter) {
    if (!currentSession) return false;
    const hasDirty = dirtyForms.size > 0 || dirtyControls.size > 0;
    if (!hasDirty) {
      if (renderAfter !== false && (deferredFullRender || deferredItemsDomSync)) {
        if (hasActiveButtonActivation()) {
          syncToolbarButtons();
        } else if (deferredFullRender) {
          renderWithFocusRestore(deferredFocusSnapshot);
        } else {
          flushDeferredItemsDomSync();
        }
        return true;
      }
      return false;
    }
    for (const ctrl of Array.from(dirtyControls)) {
      if (ctrl && ctrl.isConnected) commitInlineControl(ctrl, false);
    }
    dirtyControls.clear();
    if (dirtyForms.has('overview')) applyIdentityForm();
    if (dirtyForms.has('heart')) applyHeartForm();
    if (dirtyForms.has('sect')) applySectForm();
    resetDirtyDrafts();
    if (renderAfter !== false) {
      if (hasActiveButtonActivation()) {
        deferredFullRender = true;
        syncToolbarButtons();
      } else if (deferredFocusSnapshot) {
        renderWithFocusRestore(deferredFocusSnapshot);
      } else {
        renderAll();
      }
    }
    return true;
  }

  document.addEventListener('click', e => {
    const t = e.target.closest('[data-action],[data-preset]');
    if (!t) return;
    try {
      if (t.dataset.preset) {
        if (!currentSession) return;
        flushPendingForms();
        const applied = Core.applyPreset(currentSession, t.dataset.preset);
        renderAll();
        if (!applied) {
          setStatus(
            t.dataset.preset === 'sect-prosperity'
              ? '가입한 소속 종문이 없어 종문 번영 프리셋을 적용할 수 없습니다.'
              : '현재 슬롯에는 해당 프리셋을 적용할 수 없습니다.',
            'error'
          );
        } else {
          setStatus('프리셋 적용 완료: ' + t.textContent, 'ok');
        }
        return;
      }
      const a = t.dataset.action;
      if (a === 'load-demo') {
        loadDemo().catch(err => setStatus(err.message || String(err), 'error'));
        return;
      }
      if (!currentSession) return;
      if (a === 'apply-identity') {
        flushPendingForms();
        applyIdentityForm();
        renderAll();
        setStatus('인물 및 세계 진행 정보를 반영했습니다.', 'ok');
      } else if (a === 'grant-item') {
        const root = $('mount-items');
        const selVal = root && root.querySelector('[data-item-select]') ? root.querySelector('[data-item-select]').value : '';
        const cntVal = root && root.querySelector('[data-item-count]') ? num(root.querySelector('[data-item-count]').value) : 1;
        if (selVal) {
          flushPendingForms();
          Core.addOrUpdateItem(currentSession, num(selVal), cntVal, false);
          renderAll();
        }
      } else if (a === 'remove-inventory') {
        const soleId = t.dataset.soleId || '';
        const idx = num(t.dataset.index);
        flushPendingForms();
        if (soleId) {
          const live = Core.listInventory(currentSession).find(x => String(x.soleId) === soleId);
          if (live) Core.removeInventoryIndex(currentSession, live.index);
        } else {
          Core.removeInventoryIndex(currentSession, idx);
        }
        renderAll();
      } else if (a === 'add-destiny') {
        const root = $('mount-destiny');
        const selVal = root && root.querySelector('[data-destiny-select]') ? root.querySelector('[data-destiny-select]').value : '';
        const durVal = root && root.querySelector('[data-destiny-dur]') ? num(root.querySelector('[data-destiny-dur]').value) : -1;
        const kind = t.dataset.kind;
        if (selVal) {
          flushPendingForms();
          const added = Core.addDestiny(currentSession, kind, num(selVal), durVal);
          renderAll();
          if (!added) {
            setStatus(
              kind === 'born'
                ? '선천기운은 최대 9개까지만 보유할 수 있습니다.'
                : '운명을 추가할 수 없습니다.',
              'error'
            );
          } else {
            setStatus('운명을 추가했습니다.', 'ok');
          }
        }
      } else if (a === 'remove-destiny') {
        const kind = t.dataset.kind;
        const idx = num(t.dataset.index);
        flushPendingForms();
        Core.removeDestiny(currentSession, kind, idx);
        renderAll();
      } else if (a === 'max-martials') {
        flushPendingForms();
        Core.maxAllMartials(currentSession);
        renderAll();
      } else if (a === 'apply-heart') {
        flushPendingForms();
        applyHeartForm();
        renderAll();
        setStatus('도심 및 우화 명우 정보를 반영했습니다.', 'ok');
      } else if (a === 'apply-sect') {
        flushPendingForms();
        applySectForm();
        renderAll();
        setStatus('종문 자원 정보를 반영했습니다.', 'ok');
      } else if (a === 'unlock-achievements') {
        flushPendingForms();
        Core.unlockAllAchievements(currentSession);
        renderAll();
      }
    } catch (err) {
      setStatus(err.message || String(err), 'error');
    }
  });

  document.addEventListener('input', e => {
    const t = e.target;
    if (!t || typeof t.matches !== 'function') return;
    if (t.matches('[data-filter]')) {
      uiFilter[t.dataset.filter] = t.value;
      if (t.dataset.filter === 'itemQ') {
        const sel = document.querySelector('#mount-items [data-item-select]');
        if (sel) sel.innerHTML = buildItemSelectOptions();
      } else if (t.dataset.filter === 'destinyQ') {
        const sel = document.querySelector('#mount-destiny [data-destiny-select]');
        if (sel) sel.innerHTML = buildDestinySelectOptions();
      } else if (t.dataset.filter === 'codexQ') {
        const res = $('codex-results');
        if (res) res.innerHTML = buildCodexResultsHtml();
      }
      return;
    }
    if (!currentSession) return;
    if (t.closest('#mount-overview') && t.matches('[data-id]')) {
      dirtyForms.add('overview');
      syncToolbarButtons();
    } else if (t.closest('#mount-martials') && t.matches('[data-id]')) {
      dirtyForms.add('heart');
      syncToolbarButtons();
    } else if (t.closest('#mount-sect') && t.matches('[data-sect]')) {
      dirtyForms.add('sect');
      syncToolbarButtons();
    } else if (t.matches(INLINE_CONTROL_SEL)) {
      dirtyControls.add(t);
      syncToolbarButtons();
    }
  });

  function reconcileItemsDom(changedInput) {
    if (!currentSession) return;

    [10001, 10011, 10041].forEach(cid => {
      const cEl = $('cur-' + cid);
      if (cEl && (cEl !== document.activeElement || cEl === changedInput)) {
        cEl.value = val(Core.getCurrencyCount(currentSession, cid));
      }
    });

    const itemsRoot = $('mount-items');
    const cap = $('inv-caption');
    const inv = Core.listInventory(currentSession);
    if (cap) cap.textContent = '보유 소지품 목록 (' + inv.length + '칸)';

    const tbody = itemsRoot && itemsRoot.querySelector('.table-wrapper tbody');
    if (!tbody) return;

    if (!inv.length) {
      tbody.innerHTML = '<tr><th scope="row" colspan="6">보유 소지품이 없습니다.</th></tr>';
      return;
    }

    const keys = inv.map(r => r.soleId != null ? String(r.soleId) : '');
    const uniqueKeyed = keys.every(Boolean) && new Set(keys).size === keys.length;

    if (!uniqueKeyed) {
      tbody.innerHTML = inv.map(renderInventoryRowHtml).join('');
      return;
    }

    const keySet = new Set(keys);
    tbody.querySelectorAll('tr:not([data-sole-id])').forEach(tr => tr.remove());
    tbody.querySelectorAll('tr[data-sole-id]').forEach(tr => {
      if (!keySet.has(String(tr.dataset.soleId))) tr.remove();
    });

    const rowsById = new Map();
    tbody.querySelectorAll('tr[data-sole-id]').forEach(tr => {
      rowsById.set(String(tr.dataset.soleId), tr);
    });

    for (let i = 0; i < inv.length; i++) {
      const soleId = keys[i];
      let tr = rowsById.get(soleId);

      if (!tr) {
        const template = document.createElement('template');
        template.innerHTML = renderInventoryRowHtml(inv[i]);
        tr = template.content.firstElementChild;
        tbody.insertBefore(tr, tbody.children[i] || null);
      } else if (tbody.children[i] !== tr) {
        tbody.insertBefore(tr, tbody.children[i] || null);
      }

      if (!tr) continue;

      const rowIdx = inv[i].index != null ? inv[i].index : i;
      const inp = tr.querySelector('input[data-inv-index]');
      if (inp) {
        inp.dataset.invIndex = String(rowIdx);
        inp.dataset.soleId = soleId;
        if (inp !== document.activeElement || inp === changedInput) {
          inp.value = val(inv[i].count);
        }
      }

      const rm = tr.querySelector('button[data-action="remove-inventory"]');
      if (rm) {
        rm.dataset.index = String(rowIdx);
        rm.dataset.soleId = soleId;
      }
    }
  }

  function flushDeferredItemsDomSync() {
    if (!deferredItemsDomSync) return;
    deferredItemsDomSync = false;
    if (!currentSession) return;

    renderHeaderAndFiles();
    if (!dirtyForms.has('overview')) renderOverview();
    reconcileItemsDom(null);
    syncToolbarButtons();
  }

  function flushDeferredUiSync() {
    if (hasActiveButtonActivation()) return;
    if (deferredFullRender) {
      const snap = deferredFocusSnapshot;
      flushPendingForms(false);
      renderWithFocusRestore(snap);
      return;
    }
    if (deferredItemsDomSync) {
      flushDeferredItemsDomSync();
    }
  }

  const onPointerPressStart = e => {
    if (e && typeof e.button === 'number' && e.button !== 0) return;
    const btn = (e.target && typeof e.target.closest === 'function')
      ? e.target.closest('button')
      : null;
    pointerDownButton = (btn && !btn.disabled) ? btn : null;
  };

  const onPointerPressEnd = () => {
    pointerDownButton = null;
    if (!hasActiveButtonActivation() && (deferredFullRender || deferredItemsDomSync)) setTimeout(flushDeferredUiSync, 0);
  };

  const onKeyPressStart = e => {
    if (!e || e.ctrlKey || e.altKey || e.metaKey) return;
    if (e.key === 'Escape' && keyDownButton) {
      onKeyPressEnd();
      return;
    }
    if (e.key === ' ' || e.code === 'Space') {
      const btn = (e.target && typeof e.target.closest === 'function')
        ? e.target.closest('button')
        : null;
      if (btn && !btn.disabled) keyDownButton = btn;
    }
  };

  const onKeyPressEnd = () => {
    keyDownButton = null;
    if (!hasActiveButtonActivation() && (deferredFullRender || deferredItemsDomSync)) setTimeout(flushDeferredUiSync, 0);
  };

  document.addEventListener('pointerdown', onPointerPressStart, true);
  document.addEventListener('mousedown', onPointerPressStart, true);
  window.addEventListener('pointerup', onPointerPressEnd, true);
  window.addEventListener('mouseup', onPointerPressEnd, true);
  window.addEventListener('pointercancel', onPointerPressEnd, true);
  document.addEventListener('keydown', onKeyPressStart, true);
  window.addEventListener('keyup', e => { if (!e || e.key === ' ' || e.code === 'Space') onKeyPressEnd(); }, true);
  document.addEventListener('focusout', e => { if (keyDownButton && (!e || e.target === keyDownButton)) onKeyPressEnd(); }, true);
  window.addEventListener('blur', e => {
    if (!e || e.target === window) {
      pointerDownButton = null;
      keyDownButton = null;
      if (deferredFullRender || deferredItemsDomSync) setTimeout(flushDeferredUiSync, 0);
    }
  });

  document.addEventListener('change', e => {
    const t = e.target;
    if (!t || typeof t.matches !== 'function') return;
    try {
      if (t.matches('[data-filter]')) return;
      if (!currentSession) return;
      if (t.closest('#mount-overview') && t.matches('[data-id]')) {
        dirtyForms.add('overview');
        syncToolbarButtons();
        return;
      }
      if (t.closest('#mount-martials') && t.matches('[data-id]')) {
        dirtyForms.add('heart');
        syncToolbarButtons();
        return;
      }
      if (t.closest('#mount-sect') && t.matches('[data-sect]')) {
        dirtyForms.add('sect');
        syncToolbarButtons();
        return;
      }

      if (t.matches(INLINE_CONTROL_SEL)) {
        if (t.matches('[data-currency],[data-inv-index]')) {
          const itemsRoot = $('mount-items');
          if (itemsRoot) {
            Array.from(dirtyControls).forEach(ctrl => {
              if (ctrl !== t && ctrl.isConnected && itemsRoot.contains(ctrl)) {
                commitInlineControl(ctrl, false);
              }
            });
          }
        }

        commitInlineControl(t, true);

        if (hasActiveButtonActivation()) {
          deferredItemsDomSync = true;

          if (t.matches('[data-currency],[data-inv-index]')) {
            [10001, 10011, 10041].forEach(cid => {
              const cEl = $('cur-' + cid);
              if (cEl && (cEl !== document.activeElement || cEl === t)) {
                cEl.value = val(Core.getCurrencyCount(currentSession, cid));
              }
            });
          }

          syncToolbarButtons();
        } else if (deferredFullRender) {
          renderWithFocusRestore(deferredFocusSnapshot);
        } else {
          deferredItemsDomSync = false;
          renderHeaderAndFiles();
          if (!dirtyForms.has('overview')) renderOverview();
          if (t.matches('[data-currency],[data-inv-index]')) reconcileItemsDom(t);
          syncToolbarButtons();
        }
      }
    } catch (err) {
      setStatus(err.message || String(err), 'error');
    }
  });

  function wire(id, fn) {
    const el = $(id);
    if (!el) return;
    el.addEventListener('click', e => {
      e.preventDefault();
      Promise.resolve().then(fn).catch(err => setStatus(err.message || String(err), 'error'));
    });
  }

  wire('btn-load-demo', loadDemo);
  wire('btn-native-open-slot', () => nativeOpen('open-slot'));
  wire('btn-native-open-files', () => nativeOpen('open-files'));
  wire('btn-native-save', nativeSave);
  wire('btn-server-load', serverLoadSlot);
  wire('btn-server-save', serverSaveSlot);
  wire('btn-browser-dir', browserPickDir);
  wire('btn-browser-files', () => {
    const fi = $('file-input');
    if (fi) fi.click();
  });
  wire('btn-browser-export', browserExportDirty);

  const fi = $('file-input');
  if (fi) {
    fi.addEventListener('change', () => {
      const selected = fi.files ? Array.from(fi.files) : [];
      fi.value = '';
      Promise.resolve(browserPickFiles(selected)).catch(err => setStatus(err.message || String(err), 'error'));
    });
  }

  window.hasUnsavedChanges = function () {
    return !!(pendingNativeSave !== null || (currentSession && (currentSession.files.some(f => f.dirty) || dirtyForms.size > 0 || dirtyControls.size > 0)));
  };

  window.TaleOfImmortalUI = {
    isBusy: () => busyCount > 0,
    getNativeSession: () => nativeSession,
    getServerSession: () => serverSession,
    getSession: () => currentSession,
    hasPendingSaveRecovery: () => pendingNativeSave !== null,
    getTimedOutSaveCount: () => timedOutSaveCount,
    refresh: renderAll,
    loadDemo
  };

  renderAll();
  if (mode === 'server') {
    refreshServerSlots().then(() => syncToolbarButtons()).catch(err => setStatus(err.message || String(err), 'error'));
  }
})();
