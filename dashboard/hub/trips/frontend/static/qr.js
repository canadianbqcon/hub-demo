/* QR encoder — byte mode, error correction level M, versions 1 through 10.

   Vendored rather than pulled from a CDN, and written rather than pip-installed,
   for one reason each. The Hub is a Flask app on the house machine that a phone
   reads over the tailnet and, with the service worker, off a saved copy in a
   basement with no signal — a CDN script is exactly the dependency that is not
   there when the QR is needed. And vault-code has no requirements.txt, so a pip
   dependency has no manifest to carry it to the PC; the second machine would
   serve a 500 where this machine serves a code.

   Scope is deliberately narrow. The only thing this encodes is a wifi join
   payload, `WIFI:T:WPA;S:<ssid>;P:<pass>;;`, which is short ASCII — so byte mode
   alone, one error-correction level, and ten versions cover it with room to
   spare (213 bytes at version 10, against a realistic payload under 80). Level M
   is what the wifi-QR convention uses: 15% recovery, enough for a screen held at
   arm's length, without the size jump H would cost on a phone.

   Correctness is not eyeballed. tests/qr.selftest.js compares every matrix this
   file produces against segno, an independent implementation, across payload
   lengths that straddle each version boundary — see that file for the method.

   ponytail: no dependencies, no DOM, no globals but QR.
*/
window.QR = (() => {
  

  // ── GF(256) ─────────────────────────────────────────────────────────────────
  // Reed-Solomon runs in the field the QR spec fixes: x^8 + x^4 + x^3 + x^2 + 1.
  // Log/antilog tables turn multiplication into an addition of exponents, which
  // is the whole reason the generator polynomials below are cheap to build.
  const EXP = new Uint8Array(512), LOG = new Uint8Array(256);
  for (let i = 0, x = 1; i < 255; i++) {
    EXP[i] = x; LOG[x] = i;
    x <<= 1;
    if (x & 0x100) x ^= 0x11d;
  }
  for (let i = 255; i < 512; i++) EXP[i] = EXP[i - 255];
  const mul = (a, b) => (a === 0 || b === 0) ? 0 : EXP[LOG[a] + LOG[b]];

  // The generator polynomial for n EC codewords is (x-a^0)(x-a^1)...(x-a^(n-1)),
  // built up one root at a time.
  function generator(n) {
    let g = [1];
    for (let i = 0; i < n; i++) {
      const next = new Array(g.length + 1).fill(0);
      for (let j = 0; j < g.length; j++) {
        next[j] ^= mul(g[j], 1);
        next[j + 1] ^= mul(g[j], EXP[i]);
      }
      g = next;
    }
    return g;
  }

  // Polynomial long division; the remainder IS the error-correction block.
  function ecBytes(data, n) {
    const g = generator(n);
    const rem = new Array(data.length + n).fill(0);
    for (let i = 0; i < data.length; i++) rem[i] = data[i];
    for (let i = 0; i < data.length; i++) {
      const factor = rem[i];
      if (!factor) continue;
      for (let j = 0; j < g.length; j++) rem[i + j] ^= mul(g[j], factor);
    }
    return rem.slice(data.length);
  }

  // ── The version tables ──────────────────────────────────────────────────────
  // Per version at level M: [EC codewords per block, [blocks, data codewords]…].
  // A version with two groups has blocks of two different data lengths, which is
  // what the interleave below has to cope with.
  const EC_M = {
    1:  [10, [[1, 16]]],
    2:  [16, [[1, 28]]],
    3:  [26, [[1, 44]]],
    4:  [18, [[2, 32]]],
    5:  [24, [[2, 43]]],
    6:  [16, [[4, 27]]],
    7:  [18, [[4, 31]]],
    8:  [22, [[2, 38], [2, 39]]],
    9:  [22, [[3, 36], [2, 37]]],
    10: [26, [[4, 43], [1, 44]]],
  };
  // Byte-mode payload capacity at level M, in bytes. Derived from the table above
  // (total data bits, less the 4-bit mode indicator and the character count),
  // and asserted against it by the self-test rather than trusted as typed.
  const CAP_M = { 1: 14, 2: 26, 3: 42, 4: 62, 5: 84, 6: 106, 7: 122, 8: 152, 9: 180, 10: 213 };
  // Row/column centres of the alignment patterns. Version 1 has none.
  const ALIGN = {
    1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30],
    6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50],
  };

  // ── BCH check bits ──────────────────────────────────────────────────────────
  // Format and version information carry their own error correction, computed the
  // same way: shift the payload up, divide by the fixed generator, keep the
  // remainder. Written out rather than tabled so the constants stay checkable.
  function bch(value, poly, bits) {
    let v = value << bits;
    const deg = poly.toString(2).length - 1;
    for (let i = (v.toString(2).length - 1); i >= deg; i--) {
      if (v & (1 << i)) v ^= poly << (i - deg);
    }
    return (value << bits) | v;
  }
  // Level M is 0b00; the five payload bits are level then mask, and the finished
  // 15 bits are XORed with a fixed pattern so an all-white code is never valid.
  const formatBits = (mask) => bch((0b00 << 3) | mask, 0b10100110111, 10) ^ 0b101010000010010;
  const versionBits = (v) => bch(v, 0b1111100100101, 12);

  // ── The bit stream ──────────────────────────────────────────────────────────
  function encodeData(bytes, version) {
    const [ecPer, groups] = EC_M[version];
    const dataCw = groups.reduce((n, [blocks, len]) => n + blocks * len, 0);
    const bits = [];
    const push = (val, n) => { for (let i = n - 1; i >= 0; i--) bits.push((val >> i) & 1); };
    push(0b0100, 4);                          // byte mode
    push(bytes.length, version < 10 ? 8 : 16); // character count, wider from v10
    bytes.forEach((b) => { push(b, 8); });
    // Terminator, then pad to a byte boundary, then the two alternating pad
    // codewords the spec fixes. Every one of these steps is "fill the rest",
    // which is why a capacity check has to happen before we get here.
    for (let i = 0; i < 4 && bits.length < dataCw * 8; i++) bits.push(0);
    while (bits.length % 8) bits.push(0);
    const cw = [];
    for (let i = 0; i < bits.length; i += 8) {
      let b = 0;
      for (let j = 0; j < 8; j++) b = (b << 1) | bits[i + j];
      cw.push(b);
    }
    for (let i = 0; cw.length < dataCw; i++) cw.push(i % 2 ? 0x11 : 0xec);

    // Split into blocks, error-correct each, then INTERLEAVE — codeword 0 of
    // every block, then codeword 1 of every block, and so on. A burst of damage
    // on the printed code then lands one codeword deep in many blocks instead of
    // wiping one block out, which is the whole point of the arrangement.
    const blocks = [];
    let at = 0;
    groups.forEach(([count, len]) => {
      for (let i = 0; i < count; i++) { blocks.push(cw.slice(at, at + len)); at += len; }
    });
    const ecs = blocks.map((b) => ecBytes(b, ecPer));
    const out = [];
    const maxData = Math.max(...blocks.map((b) => b.length));
    for (let i = 0; i < maxData; i++) blocks.forEach((b) => { if (i < b.length) out.push(b[i]); });
    for (let i = 0; i < ecPer; i++) ecs.forEach((e) => { out.push(e[i]); });
    return out;
  }

  // ── The matrix ──────────────────────────────────────────────────────────────
  // `res` marks every module reserved by function patterns, so the zigzag below
  // can walk the whole grid and simply skip what is already spoken for.
  function skeleton(version) {
    const n = version * 4 + 17;
    const m = [], res = [];
    for (let i = 0; i < n; i++) { m.push(new Array(n).fill(0)); res.push(new Array(n).fill(0)); }
    const set = (r, c, v) => { m[r][c] = v; res[r][c] = 1; };

    const finder = (r0, c0) => {
      for (let r = -1; r <= 7; r++) for (let c = -1; c <= 7; c++) {
        const r1 = r0 + r, c1 = c0 + c;
        if (r1 < 0 || c1 < 0 || r1 >= n || c1 >= n) continue;
        const on = (r >= 0 && r <= 6 && (c === 0 || c === 6))
          || (c >= 0 && c <= 6 && (r === 0 || r === 6))
          || (r >= 2 && r <= 4 && c >= 2 && c <= 4);
        set(r1, c1, on ? 1 : 0);   // the separator is the -1/7 ring, written as 0
      }
    };
    finder(0, 0); finder(0, n - 7); finder(n - 7, 0);

    for (let i = 8; i < n - 8; i++) { set(6, i, i % 2 === 0 ? 1 : 0); set(i, 6, i % 2 === 0 ? 1 : 0); }

    const centres = ALIGN[version];
    centres.forEach((r0) => { centres.forEach((c0) => {
      // The three corners already hold finders; an alignment pattern never
      // overlaps one, so those combinations are simply skipped.
      if ((r0 === 6 && c0 === 6) || (r0 === 6 && c0 === n - 7) || (r0 === n - 7 && c0 === 6)) return;
      for (let r = -2; r <= 2; r++) for (let c = -2; c <= 2; c++) {
        set(r0 + r, c0 + c, (Math.abs(r) === 2 || Math.abs(c) === 2 || (r === 0 && c === 0)) ? 1 : 0);
      }
    }); });

    set(n - 8, 8, 1);   // the dark module, always on, always here

    // Reserve the format strips now and fill them after masking, since the format
    // value depends on which mask wins.
    for (let i = 0; i < 9; i++) { if (!res[8][i] || i === 8) res[8][i] = 1; if (!res[i][8]) res[i][8] = 1; }
    for (let i = 0; i < 8; i++) { res[8][n - 1 - i] = 1; res[n - 1 - i][8] = 1; }
    if (version >= 7) {
      for (let i = 0; i < 6; i++) for (let j = 0; j < 3; j++) { res[i][n - 11 + j] = 1; res[n - 11 + j][i] = 1; }
    }
    return { m, res, n };
  }

  // Bottom-right to top-left, two columns at a time, alternating up and down —
  // and column 6 is skipped entirely because the vertical timing pattern owns it.
  function place(m, res, n, codewords) {
    let bit = 0;
    const total = codewords.length * 8;
    for (let right = n - 1; right > 0; right -= 2) {
      if (right === 6) right = 5;
      for (let vert = 0; vert < n; vert++) {
        for (let k = 0; k < 2; k++) {
          const c = right - k;
          const upward = ((right + 1) & 2) === 0;
          const r = upward ? n - 1 - vert : vert;
          if (res[r][c]) continue;
          let v = 0;
          if (bit < total) v = (codewords[bit >> 3] >> (7 - (bit & 7))) & 1;
          m[r][c] = v;
          bit++;
        }
      }
    }
  }

  const MASKS = [
    (i, j) => (i + j) % 2 === 0,
    (i, _j) => i % 2 === 0,
    (_i, j) => j % 3 === 0,
    (i, j) => (i + j) % 3 === 0,
    (i, j) => (Math.floor(i / 2) + Math.floor(j / 3)) % 2 === 0,
    (i, j) => ((i * j) % 2) + ((i * j) % 3) === 0,
    (i, j) => (((i * j) % 2) + ((i * j) % 3)) % 2 === 0,
    (i, j) => (((i + j) % 2) + ((i * j) % 3)) % 2 === 0,
  ];

  // The four penalty rules. They exist to stop a mask from producing something a
  // scanner mistakes for a function pattern, or a field so flat it cannot lock on.
  function penalty(m, n) {
    let p = 0;
    const runs = (get) => {
      for (let a = 0; a < n; a++) {
        let run = 1;
        for (let b = 1; b < n; b++) {
          if (get(a, b) === get(a, b - 1)) { run++; } else { if (run >= 5) p += run - 2; run = 1; }
        }
        if (run >= 5) p += run - 2;
      }
    };
    runs((a, b) => m[a][b]);          // rule 1, horizontal
    runs((a, b) => m[b][a]);          // rule 1, vertical
    for (let r = 0; r < n - 1; r++) for (let c = 0; c < n - 1; c++) {
      const v = m[r][c];
      if (v === m[r][c + 1] && v === m[r + 1][c] && v === m[r + 1][c + 1]) p += 3;  // rule 2
    }
    // Rule 3: the finder-lookalike 1011101 with four light modules on either side.
    const pat = [1, 0, 1, 1, 1, 0, 1];
    const hit = (get, a, b) => {
      for (let k = 0; k < 7; k++) if (get(a, b + k) !== pat[k]) return false;
      const before = [b - 4, b - 3, b - 2, b - 1].every((x) => x < 0 || get(a, x) === 0);
      const after = [b + 7, b + 8, b + 9, b + 10].every((x) => x >= n || get(a, x) === 0);
      return before || after;
    };
    for (let a = 0; a < n; a++) for (let b = 0; b <= n - 7; b++) {
      if (hit((x, y) => m[x][y], a, b)) p += 40;
      if (hit((x, y) => m[y][x], a, b)) p += 40;
    }
    let dark = 0;
    for (let r = 0; r < n; r++) for (let c = 0; c < n; c++) dark += m[r][c];
    p += Math.floor(Math.abs(dark * 100 / (n * n) - 50) / 5) * 10;   // rule 4
    return p;
  }

  // The 15 format bits are written TWICE, and the two copies do not run in the
  // same direction — which is the whole trap. One copy walks DOWN column 8 (bits
  // 0-5 in rows 0-5, bit 6 skipping the timing row into row 7, bit 7 at the
  // corner, bits 8-14 up the bottom-left finder). The other walks IN along row 8
  // from the right edge (bits 0-7), then jumps the timing column at col 7 and
  // continues left (bits 9-14). Getting those two halves the wrong way round
  // produces a code whose function patterns are perfect and which no scanner can
  // read at all, because the format is what tells it the mask and the EC level.
  function writeFormat(m, res, n, mask) {
    const f = formatBits(mask);
    for (let i = 0; i < 15; i++) {
      const bit = (f >> i) & 1;
      if (i < 6) m[i][8] = bit;
      else if (i < 8) m[i + 1][8] = bit;
      else m[n - 15 + i][8] = bit;

      if (i < 8) m[8][n - 1 - i] = bit;
      else if (i === 8) m[8][7] = bit;
      else m[8][14 - i] = bit;
    }
    m[n - 8][8] = 1;   // the dark module, which the second copy runs straight past
    res[n - 8][8] = 1;
  }


  function writeVersion(m, n, version) {
    if (version < 7) return;
    const v = versionBits(version);
    for (let i = 0; i < 18; i++) {
      const bit = (v >> i) & 1;
      m[Math.floor(i / 3)][n - 11 + (i % 3)] = bit;
      m[n - 11 + (i % 3)][Math.floor(i / 3)] = bit;
    }
  }

  // ── Public ──────────────────────────────────────────────────────────────────
  function bytesOf(text) {
    const out = [];
    // TextEncoder is everywhere this app runs; the fallback keeps the self-test
    // runnable under a bare node without a DOM shim.
    const enc = typeof TextEncoder !== "undefined" ? new TextEncoder().encode(text) : null;
    if (enc) return Array.from(enc);
    for (let i = 0; i < text.length; i++) out.push(text.charCodeAt(i) & 0xff);
    return out;
  }

  function matrix(text) {
    const bytes = bytesOf(text);
    let version = 0;
    for (let v = 1; v <= 10; v++) if (bytes.length <= CAP_M[v]) { version = v; break; }
    if (!version) throw new Error(`qr: payload is ${bytes.length} bytes, over the 213-byte ceiling`);
    const cw = encodeData(bytes, version);
    const { m, res, n } = skeleton(version);
    place(m, res, n, cw);
    writeVersion(m, n, version);

    // Try all eight, keep the least penalised. Cloning per attempt rather than
    // masking in place, because a mask applied twice is a mask undone.
    let best = null, bestScore = Infinity;
    for (let mask = 0; mask < 8; mask++) {
      const t = m.map((row) => row.slice());
      for (let r = 0; r < n; r++) for (let c = 0; c < n; c++) {
        if (!res[r][c] && MASKS[mask](r, c)) t[r][c] ^= 1;
      }
      writeFormat(t, res.map((row) => row.slice()), n, mask);
      const score = penalty(t, n);
      if (score < bestScore) { bestScore = score; best = t; }
    }
    return best;
  }

  // A path of black squares in one <path>, so the whole code is one DOM node and
  // scales to whatever box it is dropped in. The quiet zone is 4 modules, which
  // is the spec minimum and the thing most hand-rolled QRs get wrong — without it
  // a phone will not lock on at all.
  function svg(text, opts) {
    const o = opts || {};
    const m = matrix(text);
    const n = m.length, q = o.quiet == null ? 4 : o.quiet, size = n + q * 2;
    let d = "";
    for (let r = 0; r < n; r++) for (let c = 0; c < n; c++) {
      if (m[r][c]) d += `M${c + q} ${r + q}h1v1h-1z`;
    }
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${size} ${size}" `
      + `shape-rendering="crispEdges" role="img" aria-label="${o.label || "QR code"}">`
      + `<rect width="${size}" height="${size}" fill="${o.bg || "#fff"}"/>`
      + `<path d="${d}" fill="${o.fg || "#000"}"/></svg>`;
  }

  // The join payload. Backslash, semicolon, comma and colon are the four
  // characters that mean something inside it, so they are escaped rather than
  // left to truncate a password at the phone.
  const esc = (s) => String(s == null ? "" : s).replace(/([\\;,:"])/g, "\\$1");
  const wifiPayload = (ssid, pass) => pass
    ? `WIFI:T:WPA;S:${esc(ssid)};P:${esc(pass)};;`
    : `WIFI:T:nopass;S:${esc(ssid)};;`;

  // Forcing a mask is only ever a test affordance: the self-test compares against
  // an independent encoder, and a disagreement has to be diagnosable as "wrong
  // mask chosen" versus "wrong bits placed" without editing this file.
  function matrixWithMask(text, mask) {
    const bytes = bytesOf(text);
    let version = 0;
    for (let v = 1; v <= 10; v++) if (bytes.length <= CAP_M[v]) { version = v; break; }
    const cw = encodeData(bytes, version);
    const { m, res, n } = skeleton(version);
    place(m, res, n, cw);
    writeVersion(m, n, version);
    for (let r = 0; r < n; r++) for (let c = 0; c < n; c++) {
      if (!res[r][c] && MASKS[mask](r, c)) m[r][c] ^= 1;
    }
    writeFormat(m, res, n, mask);
    return m;
  }

  // The self-test needs to say WHERE a disagreement lives — wrong codewords, or
  // right codewords in the wrong cells — so it gets the intermediate state.
  function internals(text) {
    const bytes = bytesOf(text);
    let version = 0;
    for (let v = 1; v <= 10; v++) if (bytes.length <= CAP_M[v]) { version = v; break; }
    const sk = skeleton(version);
    return { version, n: sk.n, res: sk.res, codewords: encodeData(bytes, version) };
  }

  return { matrix, matrixWithMask, internals, penalty, svg, wifiPayload, CAP_M, EC_M };
})();

if (typeof module !== "undefined" && module.exports) module.exports = window.QR;
