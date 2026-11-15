// FILE: src/cache-codec.js
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    var api = factory();
    root.TaleOfImmortalCodec = api;
    root.TOICodec = api;
  }
})(typeof globalThis !== 'undefined' ? globalThis : (typeof self !== 'undefined' ? self : this), function () {
  'use strict';

  var HEADER_ASCII = '1b8bg-/%ePe]P[-/921CG';
  var KEY_ASCII = '5:.A%KL;,.?<aH._=-/DF4s';
  var I64_PREFIX = '@@__TOI_I64__:';
  var ESC_PREFIX = '@@__TOI_ESC__:';
  var isNode = typeof process === 'object' && process !== null && !!process.versions && !!process.versions.node;
  var zlibMod = null;

  function getZlib() {
    if (!zlibMod) zlibMod = require('zlib');
    return zlibMod;
  }

  function toU8(input) {
    if (input instanceof Uint8Array) return input;
    if (input instanceof ArrayBuffer) return new Uint8Array(input);
    if (ArrayBuffer.isView(input)) return new Uint8Array(input.buffer, input.byteOffset, input.byteLength);
    if (Array.isArray(input)) return Uint8Array.from(input);
    throw new TypeError('Expected Uint8Array, ArrayBuffer, ArrayBufferView, or number array');
  }

  function utf8Encode(str) {
    str = String(str);
    if (typeof TextEncoder !== 'undefined') return new TextEncoder().encode(str);
    var a = [], i, c, d, cp;
    for (i = 0; i < str.length; i++) {
      c = str.charCodeAt(i);
      if (c < 0x80) a.push(c);
      else if (c < 0x800) a.push(0xc0 | (c >> 6), 0x80 | (c & 63));
      else if (c >= 0xd800 && c <= 0xdbff && i + 1 < str.length) {
        d = str.charCodeAt(i + 1);
        if (d >= 0xdc00 && d <= 0xdfff) {
          cp = 0x10000 + ((c - 0xd800) << 10) + (d - 0xdc00);
          a.push(0xf0 | (cp >> 18), 0x80 | ((cp >> 12) & 63), 0x80 | ((cp >> 6) & 63), 0x80 | (cp & 63));
          i++;
        } else a.push(0xef, 0xbf, 0xbd);
      } else if (c >= 0xd800 && c <= 0xdfff) a.push(0xef, 0xbf, 0xbd);
      else a.push(0xe0 | (c >> 12), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63));
    }
    return Uint8Array.from(a);
  }

  function utf8Decode(u8) {
    u8 = toU8(u8);
    if (typeof TextDecoder !== 'undefined') {
      return new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(u8);
    }
    throw new Error('TextDecoder is required for UTF-8 decoding');
  }

  function bytesToBase64(u8) {
    u8 = toU8(u8);
    if (isNode) return Buffer.from(u8.buffer, u8.byteOffset, u8.byteLength).toString('base64');
    var parts = [], i, end, sub, s, j;
    for (i = 0; i < u8.length; i += 0x8000) {
      end = Math.min(i + 0x8000, u8.length);
      sub = u8.subarray(i, end);
      s = '';
      for (j = 0; j < sub.length; j++) s += String.fromCharCode(sub[j]);
      parts.push(s);
    }
    return btoa(parts.join(''));
  }

  function base64ToBytes(b64) {
    b64 = String(b64).replace(/\s+/g, '');
    if (isNode) return new Uint8Array(Buffer.from(b64, 'base64'));
    var bin = atob(b64), out = new Uint8Array(bin.length), i;
    for (i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }

  var HEADER_BYTES = utf8Encode(HEADER_ASCII);
  var KEY_BYTES = utf8Encode(KEY_ASCII);

  function hasCacheHeader(bytes) {
    var u8 = toU8(bytes);
    if (u8.length < 21) return false;
    for (var i = 0; i < 21; i++) {
      if (u8[i] !== HEADER_BYTES[i]) return false;
    }
    return true;
  }

  function decryptPayloadToGzip(bytes) {
    var u8 = toU8(bytes);
    if (!hasCacheHeader(u8)) {
      throw new Error('유효한 귀곡팔황 암호화 세이브 헤더가 아닙니다.');
    }
    var gz = new Uint8Array(u8.length - 21);
    for (var i = 0; i < gz.length; i++) {
      gz[i] = (u8[21 + i] - KEY_BYTES[i % 23]) & 0xFF;
    }
    if (!(gz.length >= 2 && gz[0] === 0x1F && gz[1] === 0x8B)) {
      throw new Error('복호화된 데이터가 GZip 형식이 아닙니다.');
    }
    return gz;
  }

  function encryptGzipToPayload(gzBytes) {
    var gz = toU8(gzBytes);
    var out = new Uint8Array(21 + gz.length);
    out.set(HEADER_BYTES, 0);
    for (var i = 0; i < gz.length; i++) {
      out[21 + i] = (gz[i] + KEY_BYTES[i % 23]) & 0xFF;
    }
    return out;
  }

  function gzipDecompressSync(u8) {
    if (!isNode) throw new Error('gzipDecompressSync requires Node.js');
    var b = toU8(u8);
    return new Uint8Array(getZlib().gunzipSync(Buffer.from(b.buffer, b.byteOffset, b.byteLength)));
  }

  function gzipCompressSync(u8) {
    if (!isNode) throw new Error('gzipCompressSync requires Node.js');
    var b = toU8(u8);
    return new Uint8Array(getZlib().gzipSync(Buffer.from(b.buffer, b.byteOffset, b.byteLength)));
  }

  async function readStreamToU8(stream) {
    var reader = stream.getReader(), chunks = [], total = 0, r, i;
    while (!(r = await reader.read()).done) {
      chunks.push(r.value);
      total += r.value.length;
    }
    var out = new Uint8Array(total), offset = 0;
    for (i = 0; i < chunks.length; i++) {
      out.set(chunks[i], offset);
      offset += chunks[i].length;
    }
    return out;
  }

  async function gzipDecompress(u8) {
    if (isNode) return gzipDecompressSync(u8);
    if (typeof DecompressionStream === 'undefined') throw new Error('DecompressionStream을 지원하지 않는 브라우저입니다.');
    return readStreamToU8(new Blob([toU8(u8)]).stream().pipeThrough(new DecompressionStream('gzip')));
  }

  async function gzipCompress(u8) {
    if (isNode) return gzipCompressSync(u8);
    if (typeof CompressionStream === 'undefined') throw new Error('CompressionStream을 지원하지 않는 브라우저입니다.');
    return readStreamToU8(new Blob([toU8(u8)]).stream().pipeThrough(new CompressionStream('gzip')));
  }

  var INT64_TOKENS = new WeakSet();
  var TAG_BASE = '__TOI_I64_SLOT_';
  var INT64_PROTO = Object.freeze({
    toString: function () { return this.digits; },
    valueOf: function () { return Number(this.digits); }
  });
  function makeInt64(rawDigits) {
    var s = String(rawDigits).trim();
    if (!/^-?(?:0|[1-9]\d*)$/.test(s)) throw new TypeError('Invalid int64 string: ' + rawDigits);
    var tokObj = Object.create(INT64_PROTO);
    tokObj.digits = s;
    Object.freeze(tokObj);
    INT64_TOKENS.add(tokObj);
    return tokObj;
  }
  function isInt64Token(v) {
    return typeof v === 'object' && v !== null && INT64_TOKENS.has(v);
  }
  function int64ToString(v) {
    return isInt64Token(v) ? v.digits : String(v);
  }
  function makeSlotPrefix(zeroCount) {
    return TAG_BASE + '0'.repeat(zeroCount) + '__:';
  }
  function parseJson64(text) {
    text = String(text);
    if (text.length > 0 && text.charCodeAt(0) === 0xFEFF) text = text.slice(1);
    if (!/\d{16}/.test(text)) return JSON.parse(text);
    var spans = [];
    var n = text.length;
    var maxTagLen = 0;
    var i = 0;
    var reTag = /__TOI_I64_SLOT_(\d+)__:/g;
    var reNum = /-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/y;
    while (i < n) {
      var ch = text.charCodeAt(i);
      if (ch === 34) {
        var strStart = i;
        i++;
        while (i < n) {
          var c = text.charCodeAt(i);
          if (c === 92) { i += 2; continue; }
          if (c === 34) { i++; break; }
          i++;
        }
        if (i > n || text.charCodeAt(i - 1) !== 34) return JSON.parse(text);
        var rawStr = text.slice(strStart, i);
        if (rawStr.indexOf(TAG_BASE) >= 0 || rawStr.indexOf('\\u') >= 0) {
          var decStr;
          try { decStr = JSON.parse(rawStr); } catch (e) { return JSON.parse(text); }
          reTag.lastIndex = 0;
          var tagMatch;
          while ((tagMatch = reTag.exec(decStr))) {
            if (tagMatch[1].length > maxTagLen) maxTagLen = tagMatch[1].length;
          }
        }
        continue;
      }
      if (ch === 45 || (ch >= 48 && ch <= 57)) {
        reNum.lastIndex = i;
        var m = reNum.exec(text);
        if (m) {
          var tok = m[0];
          if (tok.indexOf('.') < 0 && tok.indexOf('e') < 0 && tok.indexOf('E') < 0) {
            var j = i + tok.length;
            while (j < n) {
              var wc = text.charCodeAt(j);
              if (wc === 32 || wc === 9 || wc === 10 || wc === 13) j++; else break;
            }
            var digits = tok.charAt(0) === '-' ? tok.slice(1) : tok;
            if ((j >= n || text.charCodeAt(j) !== 58) &&
                (digits.length >= 16 || Math.abs(Number(tok)) > 9007199254740991)) {
              spans.push([i, i + tok.length, tok]);
            }
          }
          i += tok.length;
          continue;
        }
      }
      i++;
    }
    if (spans.length === 0) return JSON.parse(text);
    var markerPrefix = makeSlotPrefix(maxTagLen + 1);
    var chunks = [];
    var last = 0;
    for (var si = 0; si < spans.length; si++) {
      var sp = spans[si];
      chunks.push(text.slice(last, sp[0]));
      chunks.push('"' + markerPrefix + sp[2] + '"');
      last = sp[1];
    }
    chunks.push(text.slice(last));
    return JSON.parse(chunks.join(''), function (_k, val) {
      return typeof val === 'string' && val.indexOf(markerPrefix) === 0
        ? makeInt64(val.slice(markerPrefix.length)) : val;
    });
  }
  function stringifyJson64(value, space) {
    var reTag = /__TOI_I64_SLOT_(\d+)__:/g;
    var maxTagLen = 0;
    var hasInt64 = false;
    var markerPrefix = makeSlotPrefix(1);
    function scanStr(s) {
      if (s.indexOf(TAG_BASE) >= 0) {
        reTag.lastIndex = 0;
        var m;
        while ((m = reTag.exec(s))) {
          if (m[1].length > maxTagLen) maxTagLen = m[1].length;
        }
      }
    }
    var text = JSON.stringify(value, function (k, v) {
      if (typeof k === 'string') scanStr(k);
      if (isInt64Token(v)) { hasInt64 = true; return markerPrefix + v.digits; }
      if (typeof v === 'string') scanStr(v);
      return v;
    }, space);
    if (text == null || !hasInt64) return text;
    if (maxTagLen >= 1) {
      markerPrefix = makeSlotPrefix(maxTagLen + 1);
      text = JSON.stringify(value, function (_k, v) {
        return isInt64Token(v) ? markerPrefix + v.digits : v;
      }, space);
    }
    var out = [];
    var last = 0;
    var n = text.length;
    var i = 0;
    while (i < n) {
      if (text.charCodeAt(i) !== 34) { i++; continue; }
      var strStart = i;
      i++;
      while (i < n) {
        var c = text.charCodeAt(i);
        if (c === 92) { i += 2; continue; }
        if (c === 34) break;
        i++;
      }
      if (i >= n) break;
      var inner = text.slice(strStart + 1, i);
      var j = i + 1;
      while (j < n) {
        var wc = text.charCodeAt(j);
        if (wc === 32 || wc === 9 || wc === 10 || wc === 13) j++; else break;
      }
      var isKey = j < n && text.charCodeAt(j) === 58;
      if (!isKey && inner.indexOf(markerPrefix) === 0) {
        var tok = inner.slice(markerPrefix.length);
        if (/^-?(?:0|[1-9]\d*)$/.test(tok)) {
          out.push(text.slice(last, strStart));
          out.push(tok);
          last = i + 1;
        }
      }
      i++;
    }
    out.push(text.slice(last));
    return out.join('');
  }

  function decodePlainJsonFallback(u8, opts) {
    var text = utf8Decode(u8);
    var trimmed = text.replace(/^\uFEFF/, '').trim();
    if (!(opts && opts.allowPlainJson) || (trimmed.charAt(0) !== '{' && trimmed.charAt(0) !== '[')) {
      throw new Error('유효한 귀곡팔황 암호화 세이브 파일이 아닙니다.');
    }
    return { mode: 'plain-json', text: text, data: parseJson64(text) };
  }

  function decodeCacheBytesSync(bytes, opts) {
    var u8 = toU8(bytes);
    if (hasCacheHeader(u8)) {
      var text = utf8Decode(gzipDecompressSync(decryptPayloadToGzip(u8)));
      return { mode: 'cipher-gzip', text: text, data: parseJson64(text) };
    }
    return decodePlainJsonFallback(u8, opts);
  }

  async function decodeCacheBytes(bytes, opts) {
    var u8 = toU8(bytes);
    if (hasCacheHeader(u8)) {
      var text = utf8Decode(await gzipDecompress(decryptPayloadToGzip(u8)));
      return { mode: 'cipher-gzip', text: text, data: parseJson64(text) };
    }
    return decodePlainJsonFallback(u8, opts);
  }

  function encodeCacheTextSync(text, opts) {
    var raw = utf8Encode(String(text));
    if (opts && opts.mode === 'plain-json') return raw;
    return encryptGzipToPayload(gzipCompressSync(raw));
  }

  function encodeCacheDataSync(data, opts) {
    return encodeCacheTextSync(stringifyJson64(data, opts && opts.space), opts);
  }

  async function encodeCacheText(text, opts) {
    var raw = utf8Encode(String(text));
    if (opts && opts.mode === 'plain-json') return raw;
    return encryptGzipToPayload(await gzipCompress(raw));
  }

  async function encodeCacheData(data, opts) {
    return encodeCacheText(stringifyJson64(data, opts && opts.space), opts);
  }

  return {
    HEADER_ASCII: HEADER_ASCII,
    KEY_ASCII: KEY_ASCII,
    I64_PREFIX: I64_PREFIX,
    ESC_PREFIX: ESC_PREFIX,
    toU8: toU8,
    utf8Encode: utf8Encode,
    utf8Decode: utf8Decode,
    bytesToBase64: bytesToBase64,
    base64ToBytes: base64ToBytes,
    hasCacheHeader: hasCacheHeader,
    decryptPayloadToGzip: decryptPayloadToGzip,
    encryptGzipToPayload: encryptGzipToPayload,
    gzipDecompressSync: gzipDecompressSync,
    gzipCompressSync: gzipCompressSync,
    gzipDecompress: gzipDecompress,
    gzipCompress: gzipCompress,
    decodeCacheBytesSync: decodeCacheBytesSync,
    decodeCacheBytes: decodeCacheBytes,
    encodeCacheTextSync: encodeCacheTextSync,
    encodeCacheDataSync: encodeCacheDataSync,
    encodeCacheText: encodeCacheText,
    encodeCacheData: encodeCacheData,
    parseJson64: parseJson64,
    stringifyJson64: stringifyJson64,
    makeInt64: makeInt64,
    isInt64Token: isInt64Token,
    int64ToString: int64ToString
  };
});
