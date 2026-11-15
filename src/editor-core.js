// FILE: src/editor-core.js
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory(require('./catalog-data.js'), require('./cache-codec.js'));
  } else {
    var api = factory(root.TaleOfImmortalCatalog || root.TOICatalog, root.TaleOfImmortalCodec || root.TOICodec);
    root.TaleOfImmortalCore = api;
    root.TOICore = api;
  }
})(typeof globalThis !== 'undefined' ? globalThis : (typeof self !== 'undefined' ? self : this), function (Catalog, Codec) {
  'use strict';

  const FILE_NAMES = {
    header: 'CacheData',
    fixVer: 'CacheFixVer',
    world: 'eMZk7avfjaaSiFBwLwtZHg==.cache',
    unit: 'O33a@9fkh++YwffVNeV1RA==.cache',
    school: 'soegnXJ65qU3ZS4O9xLDgg==.cache',
    global: 'DataGloble.cache'
  };

  const ROLE_BY_NAME = Object.keys(FILE_NAMES).reduce((out, role) => {
    out[FILE_NAMES[role]] = role;
    return out;
  }, Object.create(null));

  const EDITABLE_ROLES = {
    header: true,
    world: true,
    unit: true,
    school: true,
    global: true
  };

  const PRESETS = [
    { id: 'rich-cultivator', kr: '만능 재화 충만', desc: '영석 9,999,999 · 종문 공헌 999,999 · 성주령 9,999' },
    { id: 'full-recovery', kr: '상태 완전 회복', desc: '체력·영력·염력·건강·정력·기분 최대치 회복 및 도심 안정화' },
    { id: 'omni-aptitude', kr: '12대 자질 극대화', desc: '6대 영근·6대 무기·6대 기예 자질 999 달성' },
    { id: 'immortal-stat', kr: '불사 전투원', desc: '수명 9,999년 · 오성/매력 999 · 공격/방어 대폭 강화' },
    { id: 'martial-perfection', kr: '습득 비급 만렙', desc: '보유 무예·절기·신법·신통·심법 숙련도·품질 최대치' },
    { id: 'sect-prosperity', kr: '소속 종문 번영', desc: '종문 영석·명성·번영도·충성도·약재·광재·호산대진 강화' }
  ];

  function classifyFileRole(fileName) {
    const base = String(fileName == null ? '' : fileName).split(/[\\/]/).pop();
    const role = ROLE_BY_NAME[base];
    if (role) return role;
    return /\.cache$/i.test(base) ? 'other' : 'ignore';
  }

  function byId(list) {
    const out = Object.create(null);
    if (Array.isArray(list)) {
      for (const item of list) {
        if (item && item.id != null) out[String(item.id)] = item;
      }
    }
    return out;
  }

  const itemById = byId(Catalog && Catalog.items);
  const realmById = byId(Catalog && Catalog.realms);
  const destinyById = byId(Catalog && Catalog.destinies);
  const spriteById = byId(Catalog && Catalog.sprites);
  const heartById = byId(Catalog && Catalog.hearts);
  const wingmanById = byId(Catalog && Catalog.wingmen);
  const diffById = byId(Catalog && Catalog.difficulties);

  const propByKey = Object.create(null);
  const propByName = Object.create(null);
  const allPropsSpec = Catalog && Catalog.propertyFields && Catalog.propertyFields.all;
  if (allPropsSpec && typeof allPropsSpec === 'object') {
    for (const key of Object.keys(allPropsSpec)) {
      const prop = allPropsSpec[key];
      if (!prop) continue;
      propByKey[String(prop.key != null ? prop.key : key)] = prop;
      if (prop.name != null) propByName[String(prop.name)] = prop;
    }
  }

  function clampInt(v, min, max) {
    const n = Math.floor(Number(v));
    if (!Number.isFinite(n)) return min;
    return Math.max(min, Math.min(max, n));
  }

  function calendarFromWorldDay(worldDay) {
    const d = Math.max(0, Math.floor(Number(worldDay) || 0));
    return {
      year: Math.floor(d / 360) + 1,
      month: Math.floor((d % 360) / 30) + 1,
      day: (d % 30) + 1
    };
  }

  function worldDayFromCalendar(y, m, d) {
    return (Math.max(1, Math.floor(Number(y) || 1)) - 1) * 360 +
      (Math.max(1, Math.min(12, Math.floor(Number(m) || 1))) - 1) * 30 +
      (Math.max(1, Math.min(30, Math.floor(Number(d) || 1))) - 1);
  }

  function genSoleId(usedMap) {
    const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
    const used = usedMap || Object.create(null);
    for (let tries = 0; tries < 10000; tries++) {
      let id = '';
      for (let i = 0; i < 6; i++) id += chars[Math.floor(Math.random() * chars.length)];
      if (!used[id]) {
        used[id] = true;
        return id;
      }
    }
    let n = 0;
    while (used['ID' + n]) n++;
    const fallback = ('000000' + n).slice(-6);
    used[fallback] = true;
    return fallback;
  }

  function normalizeFileEntries(fileInput) {
    const entries = [];
    if (Array.isArray(fileInput)) {
      for (const item of fileInput) {
        if (!item || item.name == null) continue;
        const name = String(item.name).split(/[\\/]/).pop();
        entries.push({
          name,
          role: classifyFileRole(name),
          rawBytes: Codec.toU8(item.bytes),
          path: item.path == null ? null : String(item.path)
        });
      }
    } else if (fileInput && typeof fileInput === 'object') {
      for (const rawName of Object.keys(fileInput)) {
        const value = fileInput[rawName];
        if (value == null) continue;
        const bytes = value && value.bytes !== undefined ? value.bytes : value;
        const name = String(rawName).split(/[\\/]/).pop();
        entries.push({
          name,
          role: classifyFileRole(name),
          rawBytes: Codec.toU8(bytes),
          path: value && value.path != null ? String(value.path) : null
        });
      }
    }
    return entries;
  }

  function resolvePlayer(session) {
    const headerEntry = session && session.byRole ? session.byRole.header : null;
    const worldEntry = session && session.byRole ? session.byRole.world : null;
    const unitEntry = session && session.byRole ? session.byRole.unit : null;
    const allUnit = unitEntry && unitEntry.data && unitEntry.data.allUnit ? unitEntry.data.allUnit : {};
    let pid = worldEntry && worldEntry.data && worldEntry.data.playerUnitID;

    if (pid == null || !allUnit[pid]) {
      pid = null;
      for (const key of Object.keys(allUnit)) {
        const u = allUnit[key];
        if (u && u.q && Array.isArray(u.q.qb)) {
          pid = key;
          break;
        }
      }
      if (pid == null) pid = Object.keys(allUnit)[0] || null;
    }

    const pu = pid != null ? allUnit[pid] : null;
    const pq = pu && pu.q ? pu.q : null;
    return {
      playerUnitID: pid,
      pu,
      pq,
      headerEntry,
      worldEntry,
      unitEntry,
      header: headerEntry && headerEntry.data ? headerEntry.data : null,
      world: worldEntry && worldEntry.data ? worldEntry.data : null
    };
  }

  function recordChange(session, role, label, beforeVal, afterVal) {
    if (beforeVal === afterVal) return false;
    const entry = session.byRole[role];
    if (entry) {
      entry.dirty = true;
      entry.rev = (entry.rev || 0) + 1;
    }
    session.changelog.push({
      ts: Date.now(),
      role,
      label,
      before: beforeVal,
      after: afterVal
    });
    return true;
  }

  function syncHeaderInvariants(session) {
    const { pq, headerEntry, header, world } = resolvePlayer(session);
    if (!headerEntry || !header) return false;
    let changed = false;

    if (pq && Array.isArray(pq.q)) {
      const fullName = pq.q.join('');
      if (header.name !== fullName) {
        header.name = fullName;
        changed = true;
      }
    }
    if (pq && pq.d !== undefined && header.gradeID !== pq.d) {
      header.gradeID = pq.d;
      changed = true;
    }
    if (world && world.worldDay !== undefined && header.worldDay !== world.worldDay) {
      header.worldDay = world.worldDay;
      changed = true;
    }
    if (world && world.gameLevel !== undefined && header.gameLevel !== world.gameLevel) {
      header.gameLevel = world.gameLevel;
      changed = true;
    }

    if (changed) {
      headerEntry.dirty = true;
      headerEntry.rev = (headerEntry.rev || 0) + 1;
    }
    return changed;
  }

  function finalizeSession(entries, meta) {
    const session = {
      meta: meta || {},
      files: entries,
      byRole: Object.create(null),
      byName: Object.create(null),
      changelog: []
    };
    let editableCount = 0;
    for (const entry of entries) {
      session.byName[entry.name] = entry;
      if (!session.byRole[entry.role]) session.byRole[entry.role] = entry;
      if (EDITABLE_ROLES[entry.role]) editableCount++;
    }
    if (!editableCount) {
      throw new Error('편집 가능한 귀곡팔황 세이브 파일(CacheData 또는 주요 .cache)을 찾지 못했습니다.');
    }
    return session;
  }

  function applyDecodedEntry(entry, dec) {
    entry.data = dec ? dec.data : null;
    entry.mode = dec ? dec.mode : 'raw';
    entry.dirty = false;
    entry.rev = 0;
  }

  function prepareDirtyEntries(session) {
    if (
      (session.byRole.header && session.byRole.header.dirty) ||
      (session.byRole.world && session.byRole.world.dirty) ||
      (session.byRole.unit && session.byRole.unit.dirty)
    ) {
      syncHeaderInvariants(session);
    }
    return session.files.filter(entry => entry.dirty === true && EDITABLE_ROLES[entry.role]);
  }

  function openSessionSync(fileInput, meta) {
    const entries = normalizeFileEntries(fileInput);
    for (const entry of entries) {
      const dec = EDITABLE_ROLES[entry.role]
        ? Codec.decodeCacheBytesSync(entry.rawBytes, { allowPlainJson: true })
        : null;
      applyDecodedEntry(entry, dec);
    }
    return finalizeSession(entries, meta);
  }

  async function openSession(fileInput, meta) {
    const entries = normalizeFileEntries(fileInput);
    for (const entry of entries) {
      const dec = EDITABLE_ROLES[entry.role]
        ? await Codec.decodeCacheBytes(entry.rawBytes, { allowPlainJson: true })
        : null;
      applyDecodedEntry(entry, dec);
    }
    return finalizeSession(entries, meta);
  }

  function snapshotDirtyEntries(session) {
    const entries = prepareDirtyEntries(session);
    const changelogLen = session.changelog.length;
    return entries.map(entry => ({
      name: entry.name,
      role: entry.role,
      path: entry.path || null,
      mode: entry.mode,
      text: Codec.stringifyJson64(entry.data),
      rev: entry.rev || 0,
      changelogLen
    }));
  }

  function exportDirtyFilesSync(session) {
    return snapshotDirtyEntries(session).map(snap => {
      const bytes = Codec.encodeCacheTextSync(snap.text, { mode: snap.mode });
      return {
        name: snap.name,
        role: snap.role,
        path: snap.path,
        bytes,
        rev: snap.rev,
        changelogLen: snap.changelogLen
      };
    });
  }

  async function exportDirtyFiles(session) {
    const snapshots = snapshotDirtyEntries(session);
    const out = [];
    for (const snap of snapshots) {
      const bytes = await Codec.encodeCacheText(snap.text, { mode: snap.mode });
      out.push({
        name: snap.name,
        role: snap.role,
        path: snap.path,
        bytes,
        rev: snap.rev,
        changelogLen: snap.changelogLen
      });
    }
    return out;
  }

  function markSessionClean(session, writtenFiles) {
    if (!writtenFiles) {
      for (const entry of session.files) entry.dirty = false;
      session.changelog.length = 0;
      return;
    }

    const expectedRevs = new Map();
    let maxChangelogLen = null;
    for (const f of writtenFiles) {
      if (typeof f === 'string') {
        expectedRevs.set(f, null);
        continue;
      }
      if (!f) continue;
      expectedRevs.set(f.name, typeof f.rev === 'number' ? f.rev : null);
      if (typeof f.changelogLen === 'number') {
        maxChangelogLen = maxChangelogLen === null
          ? f.changelogLen
          : Math.max(maxChangelogLen, f.changelogLen);
      }
    }

    for (const entry of session.files) {
      if (!expectedRevs.has(entry.name)) continue;
      const expectedRev = expectedRevs.get(entry.name);
      if (expectedRev === null || (entry.rev || 0) === expectedRev) {
        entry.dirty = false;
      }
    }

    if (!session.files.some(e => e.dirty)) {
      session.changelog.length = 0;
    } else if (maxChangelogLen !== null) {
      session.changelog.splice(0, Math.min(maxChangelogLen, session.changelog.length));
    }
  }

  function ensurePropsArray(pu) {
    const used = Object.create(null);
    if (!pu.z) pu.z = {};
    if (!Array.isArray(pu.z.allProps)) pu.z.allProps = [];
    for (const p of pu.z.allProps) {
      if (p && p.q != null) used[String(p.q)] = true;
    }
    if (pu.k && typeof pu.k === 'object') {
      for (const id of Object.keys(pu.k)) used[String(id)] = true;
    }
    if (pu.m && Array.isArray(pu.m.q)) {
      for (const sp of pu.m.q) {
        if (sp && sp.q != null) used[String(sp.q)] = true;
      }
    }
    return used;
  }

  function getCurrencyCount(session, itemId) {
    const { pu } = resolvePlayer(session);
    if (!pu) return 0;
    ensurePropsArray(pu);
    const id = Number(itemId);
    return pu.z.allProps.reduce((sum, p) => {
      if (p && Array.isArray(p.w) && Number(p.w[1]) === id) sum += Number(p.w[2] || 0);
      return sum;
    }, 0);
  }

  function setCurrencyCount(session, itemId, count) {
    const { pu } = resolvePlayer(session);
    if (!pu) return false;
    const used = ensurePropsArray(pu);
    const id = Number(itemId);
    const c = clampInt(count, 0, 999999999);
    const before = getCurrencyCount(session, id);
    const matches = [];
    pu.z.allProps.forEach((p, i) => {
      if (p && Array.isArray(p.w) && Number(p.w[1]) === id) matches.push(i);
    });
    if (c === 0) {
      for (let i = matches.length - 1; i >= 0; i--) pu.z.allProps.splice(matches[i], 1);
    } else if (matches.length) {
      const first = pu.z.allProps[matches[0]];
      first.w[0] = first.w[0] != null ? first.w[0] : 1;
      first.w[1] = id;
      first.w[2] = c;
      for (let i = matches.length - 1; i >= 1; i--) pu.z.allProps.splice(matches[i], 1);
    } else {
      pu.z.allProps.push({ q: genSoleId(used), w: [1, id, c], e: '' });
    }
    const itemDef = itemById[String(id)];
    return recordChange(session, 'unit', (itemDef ? itemDef.kr : '재화 #' + id), before, c);
  }

  function getSummary(session) {
    const { playerUnitID, pu, pq, header, world } = resolvePlayer(session);
    const q = pq || {};
    const w = world || {};
    const h = header || {};
    const nameArr = pq && Array.isArray(pq.q) ? pq.q : ['', ''];
    let surname = '';
    let givenName = '';
    let fullName = '';
    if (pq) {
      surname = String(nameArr[0] || '');
      givenName = String(nameArr[1] || '');
      fullName = (surname + givenName) || String(h.name || '');
    } else {
      surname = '';
      givenName = String(h.name || '');
      fullName = givenName;
    }
    const gradeID = Number(q.d != null ? q.d : h.gradeID || 1) || 1;
    const realm = realmById[String(gradeID)] || {};
    const gameLevel = Number(w.gameLevel != null ? w.gameLevel : h.gameLevel || 1) || 1;
    const diff = diffById[String(gameLevel)] || {};
    const worldDay = Number(w.worldDay != null ? w.worldDay : h.worldDay || 0) || 0;
    return {
      slotLabel: (session.meta && session.meta.slotLabel) || '',
      hasUnit: !!pq,
      hasWorld: !!world,
      fullName,
      surname,
      givenName,
      sex: Number(q.r || 1) || 1,
      gradeID,
      realmKr: realm.kr || '',
      exp: Number(q.s || 0) || 0,
      ageMonths: Number(q.y || 0) || 0,
      lifeMonths: Number(q.u || 0) || 0,
      worldDay,
      calendar: calendarFromWorldDay(worldDay),
      gameLevel,
      difficultyKr: diff.kr || '',
      resurgeCount: Number(w.resurgeCount || 0) || 0,
      animaWeapons: Array.isArray(w.animaWeapons) ? w.animaWeapons.slice() : [],
      playerUnitID: playerUnitID || '',
      schoolID: pu && pu.u ? String(pu.u) : '',
      spiritStones: getCurrencyCount(session, 10001),
      sectContrib: getCurrencyCount(session, 10011),
      cityTokens: getCurrencyCount(session, 10041),
      createTicks: h && h.createTicks != null ? Codec.int64ToString(h.createTicks) : null,
      dirtyFiles: session.files.filter(f => f.dirty).map(f => f.name),
      changeCount: session.changelog.length
    };
  }

  function setPlayerIdentity(session, patch) {
    patch = patch || {};
    const { pq, world, header } = resolvePlayer(session);
    if (pq) {
      if (!Array.isArray(pq.q)) pq.q = ['', ''];
      if (patch.surname != null) {
        const before = String(pq.q[0] || '');
        pq.q[0] = String(patch.surname);
        recordChange(session, 'unit', '성(姓)', before, pq.q[0]);
      }
      if (patch.givenName != null) {
        const before = String(pq.q[1] || '');
        pq.q[1] = String(patch.givenName);
        recordChange(session, 'unit', '이름(名)', before, pq.q[1]);
      }
      if (patch.sex != null) {
        const before = pq.r;
        pq.r = clampInt(patch.sex, 1, 2);
        recordChange(session, 'unit', '성별', before, pq.r);
      }
      if (patch.gradeID != null) {
        const before = pq.d;
        pq.d = clampInt(patch.gradeID, 1, 44);
        recordChange(session, 'unit', '경지', before, pq.d);
      }
      if (patch.exp != null) {
        const before = pq.s;
        pq.s = clampInt(patch.exp, 0, 999999999);
        recordChange(session, 'unit', '수양(경험치)', before, pq.s);
      }
      const ageVal = patch.age != null ? patch.age : patch.ageMonths;
      if (ageVal != null) {
        const before = pq.y;
        pq.y = clampInt(ageVal, 12, 120000);
        recordChange(session, 'unit', '나이(개월)', before, pq.y);
      }
      const lifeVal = patch.life != null ? patch.life : patch.lifeMonths;
      if (lifeVal != null) {
        const before = pq.u;
        pq.u = clampInt(lifeVal, 12, 1200000);
        recordChange(session, 'unit', '수명 상한(개월)', before, pq.u);
      }
    }

    if (!pq && header) {
      if (patch.surname != null || patch.givenName != null) {
        const nextName = String(patch.surname || '') + String(patch.givenName || '');
        if (nextName.length > 0 || patch.allowEmptyName === true) {
          const before = header.name;
          header.name = nextName;
          recordChange(session, 'header', '캐릭터 이름', before, header.name);
        }
      }
      if (patch.gradeID != null) {
        const before = header.gradeID;
        header.gradeID = clampInt(patch.gradeID, 1, 44);
        recordChange(session, 'header', '경지', before, header.gradeID);
      }
    }

    if (world) {
      if (patch.worldDay != null) {
        const before = world.worldDay;
        world.worldDay = clampInt(patch.worldDay, 0, 3600000);
        recordChange(session, 'world', '진행 일수', before, world.worldDay);
      }
      if (patch.gameLevel != null) {
        const before = world.gameLevel;
        world.gameLevel = clampInt(patch.gameLevel, 1, 5);
        recordChange(session, 'world', '난이도', before, world.gameLevel);
      }
      if (patch.resurgeCount != null) {
        const before = world.resurgeCount;
        world.resurgeCount = clampInt(patch.resurgeCount, 0, 9999);
        recordChange(session, 'world', '부활 가능 횟수', before, world.resurgeCount);
      }
      if (patch.animaWeapons != null) {
        const before = JSON.stringify(world.animaWeapons || []);
        const next = Array.from(new Set(
          (Array.isArray(patch.animaWeapons) ? patch.animaWeapons : [])
            .map(v => clampInt(v, 1, 3))
            .filter(v => v >= 1 && v <= 3)
        )).sort((a, b) => a - b);
        world.animaWeapons = next;
        recordChange(session, 'world', '보유 신기', before, JSON.stringify(next));
      }
    }

    if (!world && header) {
      if (patch.worldDay != null) {
        const before = header.worldDay;
        header.worldDay = clampInt(patch.worldDay, 0, 3600000);
        recordChange(session, 'header', '진행 일수', before, header.worldDay);
      }
      if (patch.gameLevel != null) {
        const before = header.gameLevel;
        header.gameLevel = clampInt(patch.gameLevel, 1, 5);
        recordChange(session, 'header', '난이도', before, header.gameLevel);
      }
    }

    syncHeaderInvariants(session);
  }

  function getPropertyValue(session, keyOrName) {
    const spec = propByKey[keyOrName] || propByName[keyOrName];
    const { pq } = resolvePlayer(session);
    if (!spec || !pq) return null;
    return pq[spec.key];
  }

  function setPropertyValue(session, keyOrName, val) {
    const spec = propByKey[keyOrName] || propByName[keyOrName];
    const { pq } = resolvePlayer(session);
    if (!spec || !pq) return false;
    const before = pq[spec.key];
    const after = clampInt(val, spec.min, spec.max);
    pq[spec.key] = after;
    const changed = recordChange(session, 'unit', spec.kr, before, after);
    if (spec.key === 'd') syncHeaderInvariants(session);
    return changed;
  }

  function listInventory(session) {
    const { pu } = resolvePlayer(session);
    if (!pu) return [];
    ensurePropsArray(pu);
    return pu.z.allProps.map((p, index) => {
      if (!p || !Array.isArray(p.w) || p.w.length < 3) return null;
      const itemId = Number(p.w[1]) || 0;
      const item = itemById[String(itemId)] || {};
      return {
        index,
        soleId: p.q,
        itemId,
        count: Number(p.w[2] || 0) || 0,
        kr: item.kr || ('아이템 #' + itemId),
        ch: item.ch || '',
        cat: item.cat || '',
        lv: item.lv || 0,
        worth: item.worth || 0
      };
    }).filter(Boolean);
  }

  function addOrUpdateItem(session, itemId, count, asNewStack) {
    const { pu } = resolvePlayer(session);
    const id = Number(itemId);
    if (!pu || !(id > 0)) return false;
    const used = ensurePropsArray(pu);
    const c = clampInt(count, 1, 999999999);
    const def = itemById[String(id)];
    const label = def ? def.kr : ('아이템 #' + id);
    if (!asNewStack) {
      const hit = pu.z.allProps.find(p => p && Array.isArray(p.w) && Number(p.w[1]) === id && p.w.length === 3);
      if (hit) {
        const before = Number(hit.w[2] || 0);
        hit.w[2] = clampInt(before + c, 1, 999999999);
        return recordChange(session, 'unit', '소지품 수량 추가: ' + label, before, hit.w[2]);
      }
    }
    pu.z.allProps.push({ q: genSoleId(used), w: [1, id, c], e: '' });
    return recordChange(session, 'unit', '소지품 지급: ' + label, 0, c);
  }

  function setInventoryCount(session, index, count) {
    const { pu } = resolvePlayer(session);
    if (!pu) return false;
    ensurePropsArray(pu);
    const entry = pu.z.allProps[Number(index)];
    if (!entry || !Array.isArray(entry.w) || entry.w.length < 3) return false;
    const before = Number(entry.w[2] || 0);
    const next = clampInt(count, 1, 999999999);
    entry.w[2] = next;
    const def = itemById[String(entry.w[1])];
    return recordChange(session, 'unit', '소지품 수량 변경: ' + (def ? def.kr : '#' + entry.w[1]), before, next);
  }

  function removeInventoryIndex(session, index) {
    const { pu } = resolvePlayer(session);
    if (!pu) return false;
    ensurePropsArray(pu);
    const i = Number(index);
    if (i >= 0 && i < pu.z.allProps.length) {
      const removed = pu.z.allProps.splice(i, 1)[0];
      const id = removed && Array.isArray(removed.w) ? removed.w[1] : '';
      const def = itemById[String(id)];
      return recordChange(session, 'unit', '소지품 삭제: ' + (def ? def.kr : '#' + id), removed ? removed.q : i, null);
    }
    return false;
  }

  function listDestinies(session) {
    const { pq } = resolvePlayer(session);
    if (!pq) return { born: [], add: [] };
    const mapArr = arr => (Array.isArray(arr) ? arr : []).map((d, index) => {
      const def = destinyById[String(d && d.q)] || {};
      return {
        index,
        id: Number(d && d.q) || 0,
        dur: d && d.w != null ? Number(d.w) : -1,
        kr: def.kr || ('운명 #' + (d && d.q)),
        lv: def.lv || 0,
        tips: def.tips || ''
      };
    });
    return { born: mapArr(pq.qb), add: mapArr(pq.qn) };
  }

  function addDestiny(session, slotKind, destinyId, dur) {
    const { pq } = resolvePlayer(session);
    const id = Number(destinyId);
    if (!pq || !(id > 0)) return false;
    const isBorn = slotKind === 'born';
    const arr = isBorn
      ? (pq.qb = Array.isArray(pq.qb) ? pq.qb : [])
      : (pq.qn = Array.isArray(pq.qn) ? pq.qn : []);
    if (isBorn && arr.length >= 9) return false;
    const def = destinyById[String(id)];
    const wVal = dur == null ? (def && def.dur != null ? Number(def.dur) : -1) : Number(dur);
    arr.push({ q: id, w: wVal, e: 0, t: null });
    return recordChange(session, 'unit', (isBorn ? '선천기운 추가: ' : '후천운명 추가: ') + (def ? def.kr : '#' + id), null, id);
  }

  function removeDestiny(session, slotKind, index) {
    const { pq } = resolvePlayer(session);
    if (!pq) return false;
    const isBorn = slotKind === 'born';
    const arr = isBorn ? pq.qb : pq.qn;
    if (!Array.isArray(arr)) return false;
    const i = Number(index);
    if (i >= 0 && i < arr.length) {
      const removed = arr.splice(i, 1)[0];
      const def = destinyById[String(removed && removed.q)];
      return recordChange(session, 'unit', (isBorn ? '선천기운 제거: ' : '후천운명 제거: ') + (def ? def.kr : '#' + (removed && removed.q)), removed && removed.q, null);
    }
    return false;
  }

  function listMartials(session) {
    const { pu } = resolvePlayer(session);
    if (!pu || !pu.k || typeof pu.k !== 'object') return [];
    return Object.keys(pu.k).map(soleId => {
      const entry = pu.k[soleId] || {};
      const w = entry.q && Array.isArray(entry.q.w) ? entry.q.w : [];
      const mType = Number(w[3]) || 0;
      const baseId = Number(w[4]) || 0;
      const bucket = mType === 3 ? 'step' : (mType === 4 ? 'ability' : 'attack');
      const names = (Catalog && Catalog.martialNames && Catalog.martialNames[bucket]) || {};
      const typeLabel = mType === 1 ? '무예/영술' : mType === 2 ? '절기' : mType === 3 ? '신법' : mType === 4 ? '심법' : mType === 5 ? '신통' : ('분류 ' + mType);
      return {
        soleId,
        mType,
        typeLabel,
        baseId,
        grade: Number(w[5]) || 1,
        quality: Number(w[6]) || 1,
        exp: Number(entry.w || 0) || 0,
        kr: names[String(baseId)] || ('비급 #' + baseId)
      };
    });
  }

  function setMartialGradeQuality(session, soleId, grade, quality, exp) {
    const { pu } = resolvePlayer(session);
    const entry = pu && pu.k && pu.k[soleId];
    if (!entry || !entry.q || !Array.isArray(entry.q.w)) return false;
    const before = [entry.q.w[5], entry.q.w[6], entry.w].join('/');
    if (grade != null) entry.q.w[5] = clampInt(grade, 1, 10);
    if (quality != null) entry.q.w[6] = clampInt(quality, 1, 6);
    if (exp != null) entry.w = clampInt(exp, 0, 9999999);
    const after = [entry.q.w[5], entry.q.w[6], entry.w].join('/');
    return recordChange(session, 'unit', '습득 비급 조정 (' + soleId + ')', before, after);
  }

  function maxAllMartials(session) {
    const { pu } = resolvePlayer(session);
    if (!pu || !pu.k || typeof pu.k !== 'object') return 0;
    let count = 0;
    for (const soleId of Object.keys(pu.k)) {
      const entry = pu.k[soleId];
      if (!entry || !entry.q || !Array.isArray(entry.q.w)) continue;
      if (!(Number(entry.q.w[5]) >= 1)) entry.q.w[5] = 1;
      entry.q.w[6] = 6;
      entry.w = Math.max(Number(entry.w || 0) || 0, 999999);
      count++;
    }
    if (count > 0) recordChange(session, 'unit', '습득 비급 일괄 만렙', 0, count);
    return count;
  }

  function getSectSummary(session) {
    const { pu } = resolvePlayer(session);
    const se = session.byRole.school;
    const sm = se && se.data && se.data.allBuild;
    const sc = sm && pu && pu.u ? sm[pu.u] : null;
    if (!sc) {
      return {
        present: false,
        schoolID: pu && pu.u ? String(pu.u) : '',
        name: '',
        money: 0,
        reputation: 0,
        totalMember: 0,
        prosperous: 0,
        prosperousMax: 0,
        loyal: 0,
        medicina: 0,
        mine: 0,
        largeArrayHP: 0,
        largeArrayHPMax: 0
      };
    }
    const pd = sc.propertyData || {};
    let name = pd.fixName ? String(pd.fixName) : '';
    if (!name && Array.isArray(sc.values) && sc.values[0]) {
      try {
        const v = JSON.parse(sc.values[0]);
        const sn = (Catalog && Catalog.schoolNames) || {};
        const a = sn[String(v.name1ID)] || {};
        const b = sn[String(v.name2ID)] || {};
        name = (a.n1 || '') + (b.n2 || '');
      } catch (_) {}
    }
    return {
      present: true,
      schoolID: String(pu.u || sc.id || ''),
      name: name ? (name + '종') : String(pu.u || ''),
      money: Number(sc.money || 0),
      reputation: Number(sc.reputation || 0),
      totalMember: Number(sc.totalMember || 0),
      prosperous: Number(pd.prosperous || 0),
      prosperousMax: Number(pd.prosperousMax || 0),
      loyal: Number(pd.loyal != null ? pd.loyal : (pd.Loyal || 0)),
      medicina: Number(pd.medicina || 0),
      mine: Number(pd.mine || 0),
      largeArrayHP: Number(pd.largeArrayHP || 0),
      largeArrayHPMax: Number(pd.largeArrayHPMax || 0)
    };
  }

  function updateSect(session, patch) {
    const { pu } = resolvePlayer(session);
    const se = session.byRole.school;
    const sm = se && se.data && se.data.allBuild;
    const sc = sm && pu && pu.u ? sm[pu.u] : null;
    if (!sc) return false;
    const p = patch || {};
    let changed = false;
    const pdKeys = ['prosperous', 'prosperousMax', 'loyal', 'medicina', 'mine', 'largeArrayHP', 'largeArrayHPMax'];
    const hasPdPatch = pdKeys.some((key) => p[key] != null);
    let pd;
    if (hasPdPatch) {
      if (!sc.propertyData) {
        sc.propertyData = {};
        if (recordChange(session, 'school', '종문 속성 구조 생성', '미설정', '생성')) changed = true;
      }
      pd = sc.propertyData;
    }

    const setSc = (key, label) => {
      if (p[key] == null) return;
      const next = clampInt(p[key], 0, 999999999);
      const hadKey = Object.prototype.hasOwnProperty.call(sc, key);
      const before = hadKey ? Number(sc[key] || 0) : '미설정';
      if (hadKey && sc[key] === next) return;
      sc[key] = next;
      if (recordChange(session, 'school', label, before, next)) changed = true;
    };

    const setPd = (key, label) => {
      if (!pd || p[key] == null) return;
      const next = clampInt(p[key], 0, 999999999);

      if (key === 'loyal') {
        const effLower = Number(pd.loyal != null ? pd.loyal : (pd.Loyal || 0));
        const rawMismatch =
          (pd.loyal != null && Number(pd.loyal) !== next) ||
          (pd.Loyal != null && Number(pd.Loyal) !== next) ||
          (pd.loyal == null && pd.Loyal == null) ||
          (pd.loyal != null && pd.Loyal == null) ||
          (pd.loyal == null && pd.Loyal != null);

        let beforeDesc;
        if (rawMismatch) {
          beforeDesc = (pd.loyal == null && pd.Loyal == null)
            ? '미설정'
            : (effLower === next ? (String(pd.loyal) + '/' + String(pd.Loyal)) : effLower);
        }

        pd.loyal = next;
        pd.Loyal = next;

        if (rawMismatch) {
          recordChange(session, 'school', label, beforeDesc, next);
          changed = true;
        }
      } else {
        const hadKey = Object.prototype.hasOwnProperty.call(pd, key);
        const before = hadKey ? Number(pd[key] || 0) : '미설정';
        pd[key] = next;
        if (recordChange(session, 'school', label, before, next)) changed = true;
      }
    };
    setSc('money', '종문 영석');
    setSc('reputation', '종문 명성');
    setSc('totalMember', '종문 인원');
    setPd('prosperous', '종문 번영도');
    setPd('prosperousMax', '종문 번영도 상한');
    setPd('loyal', '종문 충성도');
    setPd('medicina', '종문 약재');
    setPd('mine', '종문 광재');
    setPd('largeArrayHP', '호산대진 내구도');
    setPd('largeArrayHPMax', '호산대진 최대 내구도');
    return changed;
  }

  function listSprites(session) {
    const { pu } = resolvePlayer(session);
    const list = pu && pu.m && Array.isArray(pu.m.q) ? pu.m.q : [];
    return list.map((sp, index) => {
      const def = spriteById[String(sp.w)] || {};
      return {
        index,
        soleId: sp.q,
        spriteId: Number(sp.w) || 0,
        kr: def.kr || ('기령 #' + sp.w),
        area: def.area || '',
        skill: def.skill || '',
        likes: def.likes || '',
        intimacy: Number(sp.r || 0),
        exp: Number(sp.u || 0),
        stamina: Number(sp.i || 0)
      };
    });
  }

  function updateSprite(session, index, patch) {
    const { pu } = resolvePlayer(session);
    const list = pu && pu.m && Array.isArray(pu.m.q) ? pu.m.q : [];
    const sp = list[Number(index)];
    if (!sp) return false;
    const p = patch || {};
    const before = [sp.r, sp.u, sp.i].join('/');
    if (p.intimacy != null) sp.r = clampInt(p.intimacy, 0, 9999);
    if (p.exp != null) sp.u = clampInt(p.exp, 0, 9999999);
    if (p.stamina != null) sp.i = clampInt(p.stamina, 0, 9999);
    const after = [sp.r, sp.u, sp.i].join('/');
    const def = spriteById[String(sp.w)];
    return recordChange(session, 'unit', '기령 성장 조정: ' + (def ? def.kr : '#' + sp.w), before, after);
  }

  function getHeartAndWingman(session) {
    const { pu } = resolvePlayer(session);
    const qe = pu && pu.qe ? pu.qe : null;
    const qi = pu && pu.qi ? pu.qi : null;
    const confID = qe ? Number(qe.y || 0) : 0;
    const wingManID = qi ? Number(qi.w || 0) : 0;
    const h = heartById[String(confID)] || {};
    const w = wingmanById[String(wingManID)] || {};
    return {
      hasHeart: !!qe,
      confID,
      heartKr: h.kr || '',
      heartDesc: h.desc || '',
      state: qe ? Number(qe.u || 0) : 0,
      onDemon: qe ? !!qe.o : false,
      hp: qe ? Number(qe.e || 0) : 0,
      heartEffectLevel: qe ? Number(qe.h || 0) : 0,
      heartEffectHP: qe ? Number(qe.j || 0) : 0,
      hasWingman: !!qi,
      isPassRebornBattle: qi ? !!qi.q : false,
      wingManID,
      wingmanKr: w.kr || '',
      wingmanDesc: w.desc || ''
    };
  }

  function updateHeartAndWingman(session, patch) {
    const { pu } = resolvePlayer(session);
    if (!pu) return false;
    const p = patch || {};
    const hasHeartPatch = (p.confID != null || p.state != null || p.onDemon != null || p.hp != null || p.heartEffectLevel != null || p.heartEffectHP != null);
    const hasWingmanPatch = (p.isPassRebornBattle != null || p.wingManID != null);
    let changed = false;

    if (!pu.qe && hasHeartPatch) {
      pu.qe = { y: 1001, u: 2, o: false, e: 0, h: 1, j: 100 };
      if (recordChange(session, 'unit', '도심 구조 생성', '미설정', '생성')) changed = true;
    }
    if (!pu.qi && hasWingmanPatch) {
      pu.qi = { q: false, w: 0, e: null, r: null };
      if (recordChange(session, 'unit', '명우 구조 생성', '미설정', '생성')) changed = true;
    }

    const qe = pu.qe;
    const qi = pu.qi;
    const set = (obj, key, val, label) => {
      if (!obj) return;
      const hadKey = Object.prototype.hasOwnProperty.call(obj, key);
      const before = hadKey ? obj[key] : '미설정';
      obj[key] = val;
      if (recordChange(session, 'unit', label, before, val)) changed = true;
    };

    if (p.confID != null) set(qe, 'y', clampInt(p.confID, 0, 999999), '도심 종류');
    if (p.state != null) set(qe, 'u', clampInt(p.state, 0, 10), '도심 단계');
    if (p.onDemon != null) set(qe, 'o', !!p.onDemon, '심마 잠식 해제/설정');
    if (p.hp != null) set(qe, 'e', clampInt(p.hp, 0, 999999), '도심 견고도');
    if (p.heartEffectLevel != null) set(qe, 'h', clampInt(p.heartEffectLevel, 0, 99), '도심 효과 등급');
    if (p.heartEffectHP != null) set(qe, 'j', clampInt(p.heartEffectHP, 0, 999999), '도심 보호 수치');
    if (p.isPassRebornBattle != null) set(qi, 'q', !!p.isPassRebornBattle, '명우 해금 돌파');
    if (p.wingManID != null) set(qi, 'w', clampInt(p.wingManID, 0, 999999), '선택 명우');
    return changed;
  }

  function relationIds(pu, key) {
    const v = pu && pu.x && pu.x[key];
    if (v == null || v === '') return [];
    return Array.isArray(v) ? v.map(String).filter(Boolean) : String(v).split(/[,;]/).map(s => s.trim()).filter(Boolean);
  }

  function listRelations(session) {
    const { playerUnitID, pu } = resolvePlayer(session);
    const all = (session.byRole.unit && session.byRole.unit.data && session.byRole.unit.data.allUnit) || {};
    const tagMap = { i: '부부/도려', o: '연인', p: '사부', a: '제자', r: '의형제', q: '부모', w: '자녀' };
    const tagLookup = Object.create(null);
    const ids = new Set();

    if (pu && pu.x && pu.x.d) {
      for (const id of Object.keys(pu.x.d)) ids.add(String(id));
    }
    for (const k of Object.keys(tagMap)) {
      for (const id of relationIds(pu, k)) {
        ids.add(id);
        if (!tagLookup[id]) tagLookup[id] = [];
        tagLookup[id].push(tagMap[k]);
      }
    }

    const out = [];
    for (const id of ids) {
      if (!id || id === playerUnitID) continue;
      const npc = all[id];
      const nq = npc && npc.q ? npc.q : null;
      const realm = nq ? (realmById[String(nq.d)] || {}) : {};
      out.push({
        npcId: id,
        name: nq && Array.isArray(nq.q) ? nq.q.join('') : id,
        gradeID: nq ? (Number(nq.d) || 0) : 0,
        realmKr: realm.kr || '',
        tags: tagLookup[id] || [],
        toNpc: pu && pu.x && pu.x.d && pu.x.d[id] != null ? Number(pu.x.d[id]) : 0,
        fromNpc: npc && npc.x && npc.x.d && npc.x.d[playerUnitID] != null ? Number(npc.x.d[playerUnitID]) : null
      });
    }
    out.sort((a, b) => (b.tags.length - a.tags.length) || (Math.abs(b.toNpc) - Math.abs(a.toNpc)));
    return out.slice(0, 200);
  }

  function setNpcIntimacy(session, npcId, val) {
    const { playerUnitID, pu } = resolvePlayer(session);
    if (!pu) return false;
    const all = (session.byRole.unit && session.byRole.unit.data && session.byRole.unit.data.allUnit) || {};
    pu.x = pu.x || {};
    pu.x.d = pu.x.d || {};

    const v = clampInt(val, -1000, 1000);

    const hasTo = Object.prototype.hasOwnProperty.call(pu.x.d, npcId);
    const prevTo = hasTo ? Number(pu.x.d[npcId] || 0) : 0;
    const changedTo = !hasTo || pu.x.d[npcId] !== v;

    const npc = all[npcId];
    const hasNpcMap = !!(npc && npc.x && npc.x.d && playerUnitID);
    const prevFrom = hasNpcMap && Object.prototype.hasOwnProperty.call(npc.x.d, playerUnitID)
      ? npc.x.d[playerUnitID]
      : undefined;
    const changedFrom = hasNpcMap && prevFrom !== v;

    pu.x.d[npcId] = v;
    if (hasNpcMap) npc.x.d[playerUnitID] = v;

    if (!changedTo && !changedFrom) return false;

    const beforeDesc = prevTo !== v
      ? prevTo
      : (changedFrom
          ? (v + ' (역방향:' + (prevFrom === undefined ? '미설정' : prevFrom) + ')')
          : '미설정');

    return recordChange(session, 'unit', '인물 호감도 조정 (' + npcId + ')', beforeDesc, v);
  }

  function getAchievementStats(session) {
    const ge = session.byRole.global;
    const achMap = ge && ge.data && ge.data.achievement && ge.data.achievement.allAchievement;
    if (!achMap || typeof achMap !== 'object') return { present: false, total: 0, unlocked: 0 };
    const keys = Object.keys(achMap);
    const unlocked = keys.filter(k => achMap[k] && achMap[k].achieved === true).length;
    return { present: true, total: keys.length, unlocked };
  }

  function unlockAllAchievements(session) {
    const ge = session.byRole.global;
    const achMap = ge && ge.data && ge.data.achievement && ge.data.achievement.allAchievement;
    if (!achMap || typeof achMap !== 'object') return false;
    const before = getAchievementStats(session).unlocked;
    const keys = Object.keys(achMap);
    let achievedFixed = 0;
    let countFixed = 0;
    for (const k of keys) {
      const existed = !!achMap[k];
      const a = achMap[k] || (achMap[k] = {});
      if (!existed || a.achieved !== true) achievedFixed++;
      const prevNum = Number(a.count);
      const nextCount = Number.isFinite(prevNum) && prevNum >= 1 ? Math.max(1, Math.trunc(prevNum)) : 1;
      if (a.count !== nextCount) countFixed++;
      a.achieved = true;
      a.count = nextCount;
    }
    if (achievedFixed === 0 && countFixed === 0) return false;
    const beforeDesc = achievedFixed > 0 ? before : (keys.length + ' (횟수보정 ' + countFixed + '건)');
    return recordChange(session, 'global', '전역 업적 일괄 해금', beforeDesc, keys.length);
  }

  function applyPreset(session, presetId) {
    const { pu, pq } = resolvePlayer(session);
    if (!pu || !pq) return false;
    if (presetId === 'rich-cultivator') {
      setCurrencyCount(session, 10001, 9999999);
      setCurrencyCount(session, 10011, 999999);
      setCurrencyCount(session, 10041, 9999);
      return true;
    }
    if (presetId === 'full-recovery') {
      for (const [curKey, maxKey, minMax] of [
        ['x', 'c', 1000],
        ['v', 'b', 1000],
        ['n', 'm', 1000],
        ['l', 'z', 500],
        ['5', '6', 500],
        ['qx', 'qc', 500]
      ]) {
        setPropertyValue(session, maxKey, Math.max(Number(pq[maxKey] || 0), minMax));
        setPropertyValue(session, curKey, getPropertyValue(session, maxKey));
      }
      if (pu.qe) updateHeartAndWingman(session, { onDemon: false });
      return true;
    }
    if (presetId === 'omni-aptitude') {
      const groups = (Catalog && Catalog.propertyFields && Catalog.propertyFields.groups) || {};
      for (const g of ['roots', 'weapons', 'artisans']) {
        for (const f of (groups[g] || [])) setPropertyValue(session, f.key, 999);
      }
      return true;
    }
    if (presetId === 'immortal-stat') {
      setPropertyValue(session, 'u', 119988);
      setPropertyValue(session, 'k', 999);
      setPropertyValue(session, 'i', 999);
      setPropertyValue(session, 'j', 99999);
      setPropertyValue(session, 'c', Math.max(Number(pq.c || 0), 9999999));
      setPropertyValue(session, 'x', Math.max(Number(pq.x || 0), 9999999));
      setPropertyValue(session, '1', Math.max(Number(pq['1'] || 0), 999999));
      setPropertyValue(session, '2', Math.max(Number(pq['2'] || 0), 999999));
      return true;
    }
    if (presetId === 'martial-perfection') {
      maxAllMartials(session);
      return true;
    }
    if (presetId === 'sect-prosperity') {
      return updateSect(session, {
        money: 9999999,
        reputation: 999999,
        prosperous: 99999,
        prosperousMax: 99999,
        loyal: 1000,
        medicina: 999999,
        mine: 999999,
        largeArrayHP: 999999,
        largeArrayHPMax: 999999
      });
    }
    return false;
  }

  function buildDemoRawData() {
    const pq = {
      q: ['청', '운'],
      r: 1,
      d: 16,
      s: 45000,
      y: 360,
      u: 3600,
      x: 5000,
      c: 8000,
      v: 3000,
      b: 4000,
      n: 1200,
      m: 1500,
      l: 200,
      z: 300,
      '5': 150,
      '6': 200,
      qx: 160,
      qc: 200,
      '1': 1800,
      '2': 950,
      '3': 600,
      '4': 90,
      '7': 400,
      '8': 200,
      '9': 300,
      qq: 150,
      qw: 420,
      qe: 0,
      qr: 0,
      i: 680,
      k: 720,
      a: 1500,
      j: 450,
      o: 300,
      p: 50,
      qt: 80,
      qy: 120,
      qu: 60,
      qi: 110,
      qo: 50,
      qp: 70,
      qa: 180,
      qs: 60,
      qd: 50,
      qf: 40,
      qg: 40,
      qh: 40,
      qj: 90,
      qk: 85,
      ql: 100,
      qz: 70,
      wq: 75,
      ww: 80,
      qb: [{ q: 102, w: -1, e: 0, t: null }],
      qn: [{ q: 201, w: 12, e: 0, t: null }]
    };
    return {
      header: {
        name: '청운',
        gradeID: 16,
        worldDay: 1835,
        gameLevel: 3,
        createTicks: Codec.makeInt64('637860102819648961')
      },
      world: {
        playerUnitID: 'DEMO01',
        worldDay: 1835,
        gameLevel: 3,
        resurgeCount: 3,
        animaWeapons: [1]
      },
      unit: {
        allUnit: {
          DEMO01: {
            u: 'SCH001',
            q: pq,
            z: {
              allProps: [
                { q: 'CUR001', w: [1, 10001, 25000], e: '' },
                { q: 'CUR002', w: [1, 10011, 1200], e: '' },
                { q: 'CUR003', w: [1, 10041, 15], e: '' }
              ]
            },
            k: {
              MRT001: { q: { q: 'MRT001', w: [2, 0, 0, 1, 10111, 4, 3], e: '' }, w: 120, e: 0, r: { allObject: {} } },
              MRT002: { q: { q: 'MRT002', w: [2, 0, 0, 3, 51011, 4, 4], e: '' }, w: 300, e: 0, r: { allObject: {} } }
            },
            m: { q: [{ q: 10001, w: 2001, r: 40, u: 100, i: 80, y: -1, o: {}, e: [] }], e: { q: 0, r: [] } },
            qe: { y: 1001, u: 2, o: false, e: 100, h: 2, j: 200 },
            qi: { q: true, w: 1001, e: null, r: null },
            x: { d: { NPC001: 120 }, i: [], o: ['NPC001'], p: [], a: [], r: [], q: [], w: [] }
          },
          NPC001: {
            q: { q: ['소', '월'], r: 2, d: 18 },
            x: { d: { DEMO01: 120 } }
          }
        },
        curUnitIndexNum: 2
      },
      school: {
        allBuild: {
          SCH001: {
            id: 'SCH001',
            money: 25000,
            reputation: 1200,
            totalMember: 84,
            values: ['{"name1ID":59,"name2ID":59}'],
            propertyData: {
              fixName: null,
              prosperous: 1200,
              prosperousMax: 5000,
              loyal: 650,
              Loyal: 650,
              medicina: 2500,
              mine: 2400,
              largeArrayHP: 12000,
              largeArrayHPMax: 50000
            }
          }
        }
      },
      global: {
        achievement: {
          allAchievement: {
            '110001': { count: 1, achieved: true },
            '110002': { count: 0, achieved: false },
            '110003': { count: 0, achieved: false }
          }
        }
      }
    };
  }

  function createDemoSlotFilesSync() {
    const raw = buildDemoRawData();
    const enc = v => Codec.encodeCacheDataSync(v);
    return {
      [FILE_NAMES.header]: enc(raw.header),
      [FILE_NAMES.fixVer]: Codec.utf8Encode('85'),
      [FILE_NAMES.world]: enc(raw.world),
      [FILE_NAMES.unit]: enc(raw.unit),
      [FILE_NAMES.school]: enc(raw.school),
      [FILE_NAMES.global]: enc(raw.global),
      'untouched_extra.cache': enc({ marker: 'untouched' })
    };
  }

  async function createDemoSlotFiles() {
    const raw = buildDemoRawData();
    const enc = v => Codec.encodeCacheData(v);
    return {
      [FILE_NAMES.header]: await enc(raw.header),
      [FILE_NAMES.fixVer]: Codec.utf8Encode('85'),
      [FILE_NAMES.world]: await enc(raw.world),
      [FILE_NAMES.unit]: await enc(raw.unit),
      [FILE_NAMES.school]: await enc(raw.school),
      [FILE_NAMES.global]: await enc(raw.global),
      'untouched_extra.cache': await enc({ marker: 'untouched' })
    };
  }

  return {
    FILE_NAMES,
    ROLE_BY_NAME,
    EDITABLE_ROLES,
    PRESETS,
    Catalog,
    Codec,
    itemById,
    realmById,
    destinyById,
    spriteById,
    heartById,
    wingmanById,
    diffById,
    propByKey,
    propByName,
    clampInt,
    calendarFromWorldDay,
    worldDayFromCalendar,
    genSoleId,
    classifyFileRole,
    normalizeFileEntries,
    resolvePlayer,
    recordChange,
    syncHeaderInvariants,
    openSessionSync,
    openSession,
    exportDirtyFilesSync,
    exportDirtyFiles,
    markSessionClean,
    getSummary,
    setPlayerIdentity,
    getPropertyValue,
    setPropertyValue,
    getCurrencyCount,
    setCurrencyCount,
    listInventory,
    addOrUpdateItem,
    setInventoryCount,
    removeInventoryIndex,
    listDestinies,
    addDestiny,
    removeDestiny,
    listMartials,
    setMartialGradeQuality,
    maxAllMartials,
    getSectSummary,
    updateSect,
    listSprites,
    updateSprite,
    getHeartAndWingman,
    updateHeartAndWingman,
    listRelations,
    setNpcIntimacy,
    getAchievementStats,
    unlockAllAchievements,
    applyPreset,
    buildDemoRawData,
    createDemoSlotFilesSync,
    createDemoSlotFiles
  };
});
