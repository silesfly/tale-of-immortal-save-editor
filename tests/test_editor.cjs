// FILE: tests/test_editor.cjs
'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');

const Catalog = require('../src/catalog-data.js');
const Codec = require('../src/cache-codec.js');
const Core = require('../src/editor-core.js');

let assertionCount = 0;
function ok(value, message) { assertionCount++; assert.ok(value, message); }
function equal(actual, expected, message) { assertionCount++; assert.strictEqual(actual, expected, message); }
function deepEqual(actual, expected, message) { assertionCount++; assert.deepStrictEqual(actual, expected, message); }

function toBuffer(bytes) {
  if (Buffer.isBuffer(bytes)) return bytes;
  if (bytes instanceof Uint8Array) return Buffer.from(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  return Buffer.from(bytes);
}

function testCatalog() {
  ok(Catalog && typeof Catalog === 'object', 'Catalog export');
  ok(Array.isArray(Catalog.items) && Catalog.items.length >= 3200, 'items >= 3200');
  ok(Array.isArray(Catalog.realms) && Catalog.realms.length === 44, 'realms === 44');
  ok(Array.isArray(Catalog.destinies) && Catalog.destinies.length >= 1100, 'destinies >= 1100');
  ok(Array.isArray(Catalog.sprites) && Catalog.sprites.length === 32, 'sprites === 32');
  ok(Array.isArray(Catalog.hearts) && Catalog.hearts.length === 21, 'hearts === 21');
  ok(Array.isArray(Catalog.wingmen) && Catalog.wingmen.length === 11, 'wingmen === 11');
  ok(Array.isArray(Catalog.domains) && Catalog.domains.length === 12, 'domains === 12');
  ok(Array.isArray(Catalog.endgameBuilds) && Catalog.endgameBuilds.length === 6, 'endgameBuilds === 6');
  ok(Array.isArray(Catalog.codexEntries) && Catalog.codexEntries.length >= 100, 'codexEntries >= 100');
  ok(Catalog.propertyFields && Catalog.propertyFields.all && Object.keys(Catalog.propertyFields.all).length >= 50, 'propertyFields.all');
  ok(Catalog.propertyFields.groups && typeof Catalog.propertyFields.groups === 'object', 'propertyFields.groups');
  ok(Array.isArray(Catalog.difficulties) && Catalog.difficulties.length >= 5, 'difficulties');
  ok(Catalog.schoolNames && typeof Catalog.schoolNames === 'object', 'schoolNames');
  ok(Catalog.martialNames && typeof Catalog.martialNames === 'object', 'martialNames');
}

async function testCodec() {
  equal(Codec.HEADER_ASCII, '1b8bg-/%ePe]P[-/921CG', 'HEADER_ASCII');
  equal(Codec.KEY_ASCII, '5:.A%KL;,.?<aH._=-/DF4s', 'KEY_ASCII');

  const plain = Buffer.from('Tale of Immortal codec roundtrip 한글 테스트 \x00\x01\xff', 'utf8');
  const gzPlain = Codec.gzipCompressSync(plain);
  const enc = Codec.encryptGzipToPayload(gzPlain);
  const dec = Codec.gzipDecompressSync(Codec.decryptPayloadToGzip(enc));
  ok(toBuffer(dec).equals(plain), 'cipher+gzip sync roundtrip');

  const payload = {
    name: '홍길동',
    createTicks: Codec.makeInt64('637860102819648961'),
    rows: [1, 2, 3]
  };
  const gz = Codec.encodeCacheDataSync(payload, { mode: 'cipher-gzip' });
  const round = Codec.decodeCacheBytesSync(gz);
  equal(round.mode, 'cipher-gzip', 'decode mode sync');
  equal(round.data.name, '홍길동', 'decode data.name sync');
  equal(Codec.int64ToString(round.data.createTicks), '637860102819648961', 'decode int64 sync');

  const gzAsync = await Codec.encodeCacheData(payload, { mode: 'cipher-gzip' });
  const roundAsync = await Codec.decodeCacheBytes(gzAsync);
  equal(roundAsync.mode, 'cipher-gzip', 'decode mode async');
  equal(roundAsync.data.name, '홍길동', 'decode data.name async');
  equal(Codec.int64ToString(roundAsync.data.createTicks), '637860102819648961', 'decode int64 async');

  for (const s of ['637860102819648961', '-9223372036854775808', '9223372036854775807']) {
    const v = Codec.makeInt64(s);
    ok(Codec.isInt64Token(v), `isInt64Token ${s}`);
    equal(Codec.int64ToString(v), s, `int64ToString ${s}`);
    const serialized = Codec.stringifyJson64({ big: v });
    ok(serialized.includes(`"big":${s}`), `raw JSON literal ${s}`);
    const parsed = Codec.parseJson64(serialized);
    equal(Codec.int64ToString(parsed.big), s, `json int64 ${s}`);
  }

  const rawCollisionJson = '{"intVal":637860102819648961,"a":"@@__TOI_I64__:637860102819648961","b":"@@__TOI_ESC__:nested__marker","@@__TOI_I64__:99":1}';
  const memCollision = Codec.parseJson64(rawCollisionJson);
  ok(Codec.isInt64Token(memCollision.intVal), 'raw int64 becomes int64 token');
  ok(!Codec.isInt64Token(memCollision.a), 'raw JSON string starting with I64_PREFIX is escaped, NOT an int64 token');
  const reserializedCollision = Codec.stringifyJson64(memCollision);
  equal(reserializedCollision, rawCollisionJson, 'raw JSON with marker-like strings roundtrips losslessly');
  const plainParsed = JSON.parse(reserializedCollision);
  equal(plainParsed.a, '@@__TOI_I64__:637860102819648961', 'literal I64 marker string preserved in output JSON');
  equal(plainParsed.b, '@@__TOI_ESC__:nested__marker', 'literal ESC marker string preserved in output JSON');

  const unicodeEscJson = '{"a":"\\u0040@__TOI_I64__:7","k":1,"\\u0040\\u0040__TOI_ESC__:k":"\\u0040\\u0040__TOI_I64__:99","q":"@@__\\u0054OI_I64__:123\\n\\"quote\\""}';
  const unicodeMem = Codec.parseJson64(unicodeEscJson);
  ok(!Codec.isInt64Token(unicodeMem.a), 'unicode-escaped I64 sentinel stays string, not int64');
  const unicodeOut = Codec.stringifyJson64(unicodeMem);
  const unicodePlain = JSON.parse(unicodeOut);
  equal(unicodePlain.a, '@@__TOI_I64__:7', 'unicode-escaped sentinel preserved as string');
  equal(unicodePlain.k, 1, 'plain key k preserved without collision');
  equal(unicodePlain['@@__TOI_ESC__:k'], '@@__TOI_I64__:99', 'escaped ESC key & value preserved without collision');
  equal(unicodePlain.q, '@@__TOI_I64__:123\n"quote"', 'escaped quotes/newlines inside sentinel string preserved');
  equal(memCollision.a, '@@__TOI_I64__:637860102819648961', 'in-memory string is unmangled');
  ok(!Codec.isInt64Token('@@__TOI_I64__:123'), 'user string with I64_PREFIX is not an int64 token');
  ok(!Codec.isInt64Token({ digits: '637860102819648961' }), 'plain object is not an int64 token');
  const directMixed = Codec.stringifyJson64({ tick: Codec.makeInt64('637860102819648961'), s1: '@@__TOI_I64__:123', s2: '@@__TOI_ESC__:abc', s3: '__TOI_I64_SLOT_0__:999', s4: '__TOI_I64_SLOT_9007199254740992__:123' });
  ok(directMixed.includes('"tick":637860102819648961'), 'direct mixed int64 is unquoted');
  const directPlain = JSON.parse(directMixed);
  equal(directPlain.s1, '@@__TOI_I64__:123', 'direct mixed s1 preserved');
  equal(directPlain.s2, '@@__TOI_ESC__:abc', 'direct mixed s2 preserved');
  equal(directPlain.s3, '__TOI_I64_SLOT_0__:999', 'direct mixed s3 preserved');
  equal(directPlain.s4, '__TOI_I64_SLOT_9007199254740992__:123', 'direct mixed s4 preserved');
  const directRevived = Codec.parseJson64(directMixed);
  ok(Codec.isInt64Token(directRevived.tick), 'direct mixed tick revived');
  equal(Codec.int64ToString(directRevived.tick), '637860102819648961', 'direct mixed tick digits preserved');
  ok(!Codec.isInt64Token(directRevived.s1), 'direct revived s1 is plain');
  ok(!Codec.isInt64Token(directRevived.s2), 'direct revived s2 is plain');
  ok(!Codec.isInt64Token(directRevived.s3), 'direct revived s3 is plain');
  ok(!Codec.isInt64Token(directRevived.s4), 'direct revived s4 is plain');
}

async function testSessions() {
  const demo = Core.createDemoSlotFilesSync();
  const demoAsync = await Core.createDemoSlotFiles();
  equal(toBuffer(demo.CacheFixVer).toString('utf8'), '85', 'CacheFixVer demo bytes');
  ok(demo['untouched_extra.cache'] instanceof Uint8Array, 'untouched_extra.cache present');

  const session = Core.openSessionSync(demo, { slotLabel: '테스트 슬롯' });
  const asyncSession = await Core.openSession(demoAsync, { slotLabel: '비동기 슬롯' });
  ok(session && session.byRole.header && session.byRole.unit, 'sync session roles');
  ok(asyncSession && asyncSession.byRole.header && asyncSession.byRole.unit, 'async session roles');

  const initSummary = Core.getSummary(session);
  equal(initSummary.dirtyFiles.length, 0, 'initially clean');
  equal(initSummary.createTicks, '637860102819648961', 'initial createTicks');

  Core.setPlayerIdentity(session, {
    surname: '홍',
    givenName: '길동',
    sex: 1,
    gradeID: 34,
    exp: 123456,
    ageMonths: 480,
    lifeMonths: 9600,
    worldDay: 2500,
    gameLevel: 4,
    resurgeCount: 5,
    animaWeapons: [1, 2, 3]
  });

  for (const presetId of [
    'rich-cultivator',
    'full-recovery',
    'omni-aptitude',
    'immortal-stat',
    'martial-perfection',
    'sect-prosperity'
  ]) {
    ok(Core.applyPreset(session, presetId), `applyPreset ${presetId}`);
  }
  Core.unlockAllAchievements(session);

  const summary = Core.getSummary(session);
  ok(!summary.dirtyFiles.includes('CacheFixVer'), 'CacheFixVer never dirty');
  ok(!summary.dirtyFiles.includes('untouched_extra.cache'), 'untouched_extra.cache never dirty');
  equal(summary.fullName, '홍길동', 'fullName without space');
  equal(summary.gradeID, 34, 'summary gradeID');
  equal(summary.worldDay, 2500, 'summary worldDay');
  equal(summary.gameLevel, 4, 'summary gameLevel');
  equal(summary.spiritStones, 9999999, 'rich-cultivator spiritStones');

  const hData = session.byRole.header.data;
  equal(hData.name, '홍길동', 'CacheData.name synced without space');
  equal(hData.gradeID, 34, 'CacheData.gradeID synced');
  equal(hData.worldDay, 2500, 'CacheData.worldDay synced');
  equal(hData.gameLevel, 4, 'CacheData.gameLevel synced');
  equal(Codec.int64ToString(hData.createTicks), '637860102819648961', 'CacheData.createTicks preserved');

  // Property & currency mutators
  Core.setPropertyValue(session, 'qt', 888);
  equal(Core.getPropertyValue(session, 'qt'), 888, 'property qt');
  Core.setCurrencyCount(session, 10011, 54321);
  equal(Core.getCurrencyCount(session, 10011), 54321, 'sectContrib currency');

  // Inventory add / set / remove
  const extraItemId = Catalog.items[Catalog.items.length - 1].id;
  Core.addOrUpdateItem(session, extraItemId, 7);
  let inv = Core.listInventory(session);
  let entry = inv.find(x => x.itemId === extraItemId);
  ok(entry && entry.count === 7, 'inventory added');
  Core.setInventoryCount(session, entry.index, 12);
  entry = Core.listInventory(session).find(x => x.itemId === extraItemId);
  equal(entry.count, 12, 'inventory updated');
  Core.removeInventoryIndex(session, entry.index);
  ok(!Core.listInventory(session).some(x => x.itemId === extraItemId), 'inventory removed');

  // Destinies: born max 9 cap + add/remove
  for (let i = 0; i < 12; i++) {
    Core.addDestiny(session, 'born', Catalog.destinies[i].id, -1);
  }
  equal(Core.listDestinies(session).born.length, 9, 'born destinies capped at 9');
  Core.removeDestiny(session, 'born', 0);
  equal(Core.listDestinies(session).born.length, 8, 'born destiny removed');
  Core.addDestiny(session, 'add', Catalog.destinies[20].id, 24);
  ok(Core.listDestinies(session).add.length >= 2, 'postnatal destiny added');

  // Martials
  const martials = Core.listMartials(session);
  ok(martials.length >= 2, 'martials present');
  Core.setMartialGradeQuality(session, martials[0].soleId, 8, 6, 888888);
  const m0 = Core.listMartials(session).find(m => m.soleId === martials[0].soleId);
  equal(m0.grade, 8, 'martial grade');
  equal(m0.quality, 6, 'martial quality');
  equal(m0.exp, 888888, 'martial exp');

  // Sect (loyal + Loyal dual update)
  Core.updateSect(session, { loyal: 950, money: 8765432 });
  const sc = session.byRole.school.data.allBuild.SCH001;
  equal(sc.propertyData.loyal, 950, 'sect propertyData.loyal');
  equal(sc.propertyData.Loyal, 950, 'sect propertyData.Loyal synced');
  equal(Core.getSectSummary(session).money, 8765432, 'sect money');

  // Sprites, Heart/Wingman, Relations, Achievements
  Core.updateSprite(session, 0, { intimacy: 250, exp: 5000, stamina: 100 });
  equal(Core.listSprites(session)[0].intimacy, 250, 'sprite intimacy');
  Core.updateHeartAndWingman(session, { confID: 1002, state: 4, onDemon: false, wingManID: 1003, isPassRebornBattle: true });
  const hw = Core.getHeartAndWingman(session);
  equal(hw.confID, 1002, 'confID');
  equal(hw.wingManID, 1003, 'wingManID');
  Core.setNpcIntimacy(session, 'NPC001', 300);
  equal(Core.listRelations(session)[0].toNpc, 300, 'NPC intimacy');
  const ach = Core.getAchievementStats(session);
  equal(ach.unlocked, ach.total, 'all achievements unlocked');

  // Export dirty files & reopen lossless check
  const dirtySync = Core.exportDirtyFilesSync(session);
  const dirtyAsync = await Core.exportDirtyFiles(session);
  ok(Array.isArray(dirtySync) && dirtySync.length === 5, '5 dirty files exported');
  equal(dirtyAsync.length, 5, 'async dirty files count');
  ok(!dirtySync.some(f => f.name === 'CacheFixVer'), 'CacheFixVer not exported');
  ok(!dirtySync.some(f => f.name === 'untouched_extra.cache'), 'untouched_extra.cache not exported');

  const merged = Object.assign({}, demo);
  for (const f of dirtySync) merged[f.name] = f.bytes;
  ok(toBuffer(merged.CacheFixVer).equals(toBuffer(demo.CacheFixVer)), 'CacheFixVer byte-identical');
  ok(toBuffer(merged['untouched_extra.cache']).equals(toBuffer(demo['untouched_extra.cache'])), 'untouched_extra byte-identical');

  const reopened = Core.openSessionSync(merged);
  const reSum = Core.getSummary(reopened);
  equal(reSum.fullName, '홍길동', 'reopened fullName');
  equal(reSum.gradeID, 34, 'reopened gradeID');
  equal(reSum.worldDay, 2500, 'reopened worldDay');
  equal(reSum.spiritStones, 9999999, 'reopened spiritStones');
  equal(reSum.createTicks, '637860102819648961', 'reopened createTicks exact');

  Core.markSessionClean(session, dirtySync);
  equal(Core.getSummary(session).dirtyFiles.length, 0, 'markSessionClean clears dirty');

  const hdrOnly = Core.openSessionSync({ CacheData: demo.CacheData });
  const hdrSum = Core.getSummary(hdrOnly);
  equal(hdrSum.hasUnit, false, 'header-only session has no unit');
  equal(hdrSum.hasWorld, false, 'header-only session has no world');
  equal(hdrSum.surname, '', 'header-only session has empty surname');
  equal(hdrSum.givenName, '청운', 'header-only session reads given name');
  equal(hdrSum.fullName, '청운', 'header-only session reads full name');

  Core.setPlayerIdentity(hdrOnly, {
    surname: '',
    givenName: '',
    gradeID: 22,
    worldDay: 2160,
    gameLevel: 5
  });
  equal(hdrOnly.byRole.header.data.name, '청운', 'header-only identity update does not blank name');
  equal(hdrOnly.byRole.header.data.gradeID, 22, 'header-only identity updates gradeID');
  equal(hdrOnly.byRole.header.data.worldDay, 2160, 'header-only identity updates worldDay');
  equal(hdrOnly.byRole.header.data.gameLevel, 5, 'header-only identity updates gameLevel');

  Core.setPlayerIdentity(hdrOnly, { surname: '묵', givenName: '연' });
  equal(hdrOnly.byRole.header.data.name, '묵연', 'header-only identity joins surname and given name');

  async function verifyExportedIdentity(dirtyList, baseMap, c, hasUnit, modeLabel) {
    const hdrSnap = dirtyList.find(f => f.role === 'header');
    ok(!!hdrSnap, modeLabel + ': header snapshot exists');
    const plainHdr = JSON.parse(Codec.decodeCacheBytesSync(hdrSnap.bytes).text);
    ok(typeof plainHdr.name === 'string', modeLabel + ': exported name is string');
    equal(plainHdr.name, c.expected, modeLabel + ': exported name preserved');
    ok(typeof plainHdr.createTicks === 'number', modeLabel + ': createTicks is number');
    equal(plainHdr.createTicks, 637860102819648961, modeLabel + ': createTicks exact');
    if (hasUnit) {
      const unitSnap = dirtyList.find(f => f.role === 'unit');
      ok(!!unitSnap, modeLabel + ': unit snapshot exists');
      const plainUnit = JSON.parse(Codec.decodeCacheBytesSync(unitSnap.bytes).text);
      const qArr = plainUnit.allUnit.DEMO01.q.q;
      ok(typeof qArr[0] === 'string', modeLabel + ': unit surname is string');
      ok(typeof qArr[1] === 'string', modeLabel + ': unit givenName is string');
      equal(qArr[0], c.surname, modeLabel + ': unit surname preserved');
      equal(qArr[1], c.givenName, modeLabel + ': unit givenName preserved');
    }
    const mergedMap = Object.assign({}, baseMap);
    for (const f of dirtyList) mergedMap[f.name] = f.bytes;
    const reopenedSync = Core.openSessionSync(mergedMap);
    equal(Core.getSummary(reopenedSync).fullName, c.expected, modeLabel + '/reopenSync: fullName preserved');
    ok(Codec.isInt64Token(reopenedSync.byRole.header.data.createTicks), modeLabel + '/reopenSync: createTicks token');
    equal(Core.getSummary(reopenedSync).createTicks, '637860102819648961', modeLabel + '/reopenSync: createTicks digits');
    const reopenedAsync = await Core.openSession(mergedMap);
    equal(Core.getSummary(reopenedAsync).fullName, c.expected, modeLabel + '/reopenAsync: fullName preserved');
    ok(Codec.isInt64Token(reopenedAsync.byRole.header.data.createTicks), modeLabel + '/reopenAsync: createTicks token');
    equal(Core.getSummary(reopenedAsync).createTicks, '637860102819648961', modeLabel + '/reopenAsync: createTicks digits');
  }

  const fullDemoForIdentity = Core.createDemoSlotFilesSync();
  const identityBaseMaps = [
    { label: 'fullDemo', map: fullDemoForIdentity, hasUnit: true },
    { label: 'headerOnly', map: { CacheData: fullDemoForIdentity.CacheData }, hasUnit: false }
  ];
  const identityCases = [
    { surname: '', givenName: '@@__TOI_I64__:123', expected: '@@__TOI_I64__:123' },
    { surname: '@@__TOI_', givenName: 'I64__:456', expected: '@@__TOI_I64__:456' },
    { surname: '__TOI_I64_SLOT_0__:', givenName: '789', expected: '__TOI_I64_SLOT_0__:789' },
    { surname: '__TOI_I64_SLOT_9007199254740992__:', givenName: '123', expected: '__TOI_I64_SLOT_9007199254740992__:123' },
    { surname: '@@__TOI_ESC__:', givenName: 'tail', expected: '@@__TOI_ESC__:tail' }
  ];
  for (const base of identityBaseMaps) {
    for (const c of identityCases) {
      const target = Core.openSessionSync(base.map);
      Core.setPlayerIdentity(target, { surname: c.surname, givenName: c.givenName });
      equal(target.byRole.header.data.name, c.expected, base.label + ': in-memory fullName preserved');
      await verifyExportedIdentity(Core.exportDirtyFilesSync(target), base.map, c, base.hasUnit, base.label + '/sync');
      await verifyExportedIdentity(await Core.exportDirtyFiles(target), base.map, c, base.hasUnit, base.label + '/async');
    }
  }

  Core.setCurrencyCount(session, 10001, 11111);
  const snap1 = Core.exportDirtyFilesSync(session);
  Core.setCurrencyCount(session, 10001, 22222);
  Core.markSessionClean(session, snap1);
  equal(session.byRole.unit.dirty, true, 'concurrent edit after snapshot remains dirty');
  equal(session.changelog.length, 1, 'concurrent changelog entry remains after revision-safe clean');

  const snap2 = Core.exportDirtyFilesSync(session);
  Core.markSessionClean(session, snap2);
  equal(Core.getSummary(session).dirtyFiles.length, 0, 'second markSessionClean clears concurrent edit');
  equal(session.changelog.length, 0, 'second markSessionClean clears remaining changelog');

  Core.setCurrencyCount(session, 10001, 33333);
  const origEncodeText = Codec.encodeCacheText;
  try {
    let firstEncode = true;
    Codec.encodeCacheText = async function (text, opts) {
      if (firstEncode) {
        firstEncode = false;
        await new Promise(r => setTimeout(r, 15));
        Core.setCurrencyCount(session, 10001, 44444);
      }
      return origEncodeText.call(Codec, text, opts);
    };
    const asyncSnap = await Core.exportDirtyFiles(session);
    const unitEntry = asyncSnap.find(entry => entry.role === 'unit');
    ok(Boolean(unitEntry), 'exported unit entry present');
    const snapSession = Core.openSessionSync({ [unitEntry.name]: unitEntry.bytes });
    equal(Core.getCurrencyCount(snapSession, 10001), 33333, 'exported unit snapshot is frozen during in-flight async encode');
    equal(Core.getCurrencyCount(session, 10001), 44444, 'live session retains in-flight currency edit');

    Core.markSessionClean(session, asyncSnap);
    equal(session.byRole.unit.dirty, true, 'in-flight edit during async encode remains dirty');
    equal(session.changelog.length, 1, 'in-flight changelog preserved');

    const snap3 = await Core.exportDirtyFiles(session);
    Core.markSessionClean(session, snap3);
    equal(Core.getSummary(session).dirtyFiles.length, 0, 'clean after saving in-flight edit');
  } finally {
    Codec.encodeCacheText = origEncodeText;
  }

  Core.unlockAllAchievements(session);
  Core.markSessionClean(session, Core.exportDirtyFilesSync(session));
  const achKeys = Object.keys(session.byRole.global.data.achievement.allAchievement);
  const k0 = achKeys[0];
  session.byRole.global.data.achievement.allAchievement[k0].achieved = true;
  session.byRole.global.data.achievement.allAchievement[k0].count = 0;
  session.byRole.global.dirty = false;
  const globalRev0 = session.byRole.global.rev || 0;
  const achFixed = Core.unlockAllAchievements(session);
  equal(achFixed, true, 'unlockAllAchievements detects secondary count=0');
  equal(session.byRole.global.dirty, true, 'global marked dirty when count=0 fixed');
  ok((session.byRole.global.rev || 0) > globalRev0, 'global rev incremented when count=0 fixed');
  const gDirty = Core.exportDirtyFilesSync(session);
  const gEntry = gDirty.find(e => e.role === 'global');
  const gReopen = Core.openSessionSync({ [gEntry.name]: gEntry.bytes });
  equal(gReopen.byRole.global.data.achievement.allAchievement[k0].count, 1, 'reopened global cache preserves fixed count=1');
  Core.markSessionClean(session, gDirty);
  const pu = session.byRole.unit.data.allUnit[Core.getSummary(session).playerUnitID];
  delete pu.qe;
  delete pu.qi;
  const hwBefore = Core.getHeartAndWingman(session);
  equal(hwBefore.hasHeart, false, 'missing pu.qe means no heart');
  equal(hwBefore.hasWingman, false, 'missing pu.qi means no wingman');
  session.byRole.unit.dirty = false;
  const unitRevBeforeHw = session.byRole.unit.rev || 0;
  const hwChanged = Core.updateHeartAndWingman(session, { confID: 1001, state: 2, onDemon: false, hp: 0, heartEffectLevel: 1, heartEffectHP: 100, isPassRebornBattle: false, wingManID: 0 });
  equal(hwChanged, true, 'creating missing pu.qe/pu.qi with default values marks changed');
  equal(session.byRole.unit.dirty, true, 'unit marked dirty on pu.qe/pu.qi creation');
  ok((session.byRole.unit.rev || 0) > unitRevBeforeHw, 'unit rev incremented on pu.qe/pu.qi creation');
  const hwDirty = Core.exportDirtyFilesSync(session);
  const hwUnitEntry = hwDirty.find(e => e.role === 'unit');
  ok(Boolean(hwUnitEntry), 'unit file exported for newly created pu.qe/pu.qi');
  const hwReopen = Core.openSessionSync(Object.assign({}, merged, { [hwUnitEntry.name]: hwUnitEntry.bytes }));
  const hwAfter = Core.getHeartAndWingman(hwReopen);
  equal(hwAfter.hasHeart, true, 'reopened hasHeart');
  equal(hwAfter.hasWingman, true, 'reopened hasWingman');
  equal(hwAfter.confID, 1001, 'reopened confID=1001');
  equal(hwAfter.state, 2, 'reopened state=2');
  equal(hwAfter.heartEffectHP, 100, 'reopened heartEffectHP=100');
  equal(hwAfter.wingManID, 0, 'reopened wingManID=0');
  Core.markSessionClean(session, hwDirty);
  equal(Core.updateHeartAndWingman(session, { confID: 1001, state: 2, onDemon: false, hp: 0, heartEffectLevel: 1, heartEffectHP: 100, isPassRebornBattle: false, wingManID: 0 }), false, 're-applying identical heart/wingman values is idempotent');
  equal(session.byRole.unit.dirty, false, 'unit stays clean on idempotent heart/wingman reapply');
}

function testBundledHtml() {
  const p = path.join(__dirname, '..', 'dist', 'TaleOfImmortalSaveEditor-v1.0.html');
  ok(fs.existsSync(p), 'bundled HTML exists');
  const stat = fs.statSync(p);
  ok(stat.size > 1000000, 'bundled HTML > 1MB');
  const html = fs.readFileSync(p, 'utf8');
  const externalUrl = /(?:https?|ftp|wss?):\/\/|(?:src|href|action|poster|data|cite)\s*=\s*["']?\s*\/\/|url\(\s*["']?\s*(?:https?|ftp|wss?)?\/\//i;
  ok(!externalUrl.test(html), 'zero external URL references');
  ok(html.includes('<meta name="color-scheme" content="light dark">'), 'color-scheme meta');
  ok(html.includes('<dialog'), 'dialog element');
  ok(html.includes('role="tablist"'), 'tablist role');
  ok(html.includes('hidden="until-found"'), 'hidden until-found');
  ok(html.includes('overscroll-behavior: contain'), 'overscroll-behavior: contain');
  ok(html.includes('id="btn-theme-toggle"'), 'theme toggle button present');
  ok(html.includes(':root:has(> head > meta[name="color-scheme"]'), 'color-scheme :has() CSS mapping');
  ok(html.includes('[role="tabpanel"][hidden] { pointer-events: none; }'), 'hidden tabpanel pointer-events guard');
  ok(!html.includes('grid-area: 1 / 1'), 'no overlapping grid-area stack on tabpanels');
  ok(!/\[role="tabpanel"\]\[hidden\][^}]*(?:display\s*:\s*none|visibility\s*:\s*hidden)/.test(html), 'until-found searchability preserved');
  ok(html.includes('data-sect="prosperousMax"') && html.includes('data-sect="largeArrayHPMax"'), 'sect max inputs present');

  for (const rel of ['editor-page.html', 'editor-ui.js']) {
    const srcPath = path.join(__dirname, '..', 'src', rel);
    const src = fs.readFileSync(srcPath, 'utf8');

    const labelRe = /<label\b[^>]*>[\s\S]*?<\/label>/g;
    let labelMatch;
    while ((labelMatch = labelRe.exec(src))) {
      const block = labelMatch[0];
      const openTag = block.match(/^<label\b[^>]*>/i)[0];
      const hasFor = /\bfor\s*=/i.test(openTag);
      const wrapsControl = /<(?:input|select)\b/i.test(block.slice(openTag.length));
      ok(hasFor || wrapsControl, `${rel}: label ${labelMatch.index} uses for= or wraps input/select`);
    }

    const forRe = /\bfor="([^"]+)"/g;
    let forMatch;
    while ((forMatch = forRe.exec(src))) {
      const forValue = forMatch[1];
      ok(src.includes(`id="${forValue}"`), `${rel}: for="${forValue}" has matching id`);
    }
  }
}

function testRealSaves() {
  const root = process.env.TOI_REAL_SAVES_DIR;
  if (!root || !fs.existsSync(root)) return;
  const entries = fs.readdirSync(root, { withFileTypes: true });
  let checkedSlots = 0;
  for (const ent of entries) {
    if (!ent.isDirectory() || !/^\d+_/.test(ent.name)) continue;
    const dir = path.join(root, ent.name);
    const map = {};
    for (const f of fs.readdirSync(dir)) {
      const fp = path.join(dir, f);
      if (fs.statSync(fp).isFile()) map[f] = new Uint8Array(fs.readFileSync(fp));
    }
    const parentGlobal = path.join(root, 'DataGloble.cache');
    if (fs.existsSync(parentGlobal)) {
      map['DataGloble.cache'] = new Uint8Array(fs.readFileSync(parentGlobal));
    }
    const session = Core.openSessionSync(map, { slotLabel: ent.name });
    const sum = Core.getSummary(session);
    ok(Boolean(sum.playerUnitID), `slot ${ent.name} playerUnitID`);
    ok(sum.gradeID >= 1 && sum.gradeID <= 44, `slot ${ent.name} gradeID`);
    ok(typeof sum.createTicks === 'string' && sum.createTicks.length >= 15, `slot ${ent.name} createTicks`);
    const reEncoded = Codec.encodeCacheDataSync(session.byRole.header.data, session.byRole.header.mode);
    const reDecoded = Codec.decodeCacheBytesSync(reEncoded);
    equal(Codec.int64ToString(reDecoded.data.createTicks), sum.createTicks, `slot ${ent.name} createTicks roundtrip`);
    checkedSlots++;
  }
  ok(checkedSlots >= 1, 'checked >= 1 real save slot');
}

(async () => {
  try {
    testCatalog();
    await testCodec();
    await testSessions();
    testBundledHtml();
    testRealSaves();
    console.log(`PASS test_editor.cjs (${assertionCount} assertions)`);
    process.exit(0);
  } catch (err) {
    console.error('FAIL test_editor.cjs');
    console.error((err && err.stack) || err);
    process.exit(1);
  }
})();
