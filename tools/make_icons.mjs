#!/usr/bin/env node
/*
 * make_icons.mjs -- Generador de los iconos de la aplicacion
 * "Generador de clave de TikTok Live (via Streamlabs)".
 *
 * Dibuja el icono de forma programatica (arte original), lo muestrea con
 * supersampling 4x4 y escribe:
 *
 *   assets/icon.png      512 x 512   RGBA
 *   assets/icon@2x.png  1024 x 1024  RGBA
 *   assets/icon.ico     16, 24, 32, 48, 64, 128 y 256 px (payload PNG)
 *   assets/icon.icns    ic07..ic14 (payload PNG)
 *
 * Sin dependencias externas: solo modulos internos de Node
 * (node:zlib, node:fs, node:buffer, node:path, node:url). El PNG
 * (IHDR/IDAT/IEND con CRC32), el ICO y el ICNS se codifican aqui a mano.
 *
 * Uso:  node tools/make_icons.mjs
 *
 * Licencia: GPL-3.0, la misma del proyecto.
 */

import { deflateSync } from "node:zlib";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { Buffer } from "node:buffer";

/* ------------------------------------------------------------------ */
/* 1. Paleta y geometria (fracciones del lado de la tesela)           */
/* ------------------------------------------------------------------ */

const COLORS = {
  gradientTop: [0x1b, 0x24, 0x30], // #1B2430 azul pizarra profundo
  gradientBottom: [0x0e, 0x14, 0x1b], // #0E141B mas oscuro
  key: [0xf2, 0xf6, 0xfa], // #F2F6FA casi blanco
  cyan: [0x25, 0xf4, 0xee], // #25F4EE acento
  magenta: [0xfe, 0x2c, 0x55], // #FE2C55 acento
};

const DESIGN = {
  padRatio: 0.06, // margen transparente alrededor de la tesela (~6 %)
  cornerRatio: 0.11, // radio de esquina, relativo al lado de la tesela

  // Llavero: anillo con agujero real. El trazo es mas fino que el agujero para
  // que lea como el ojo de una llave y no como un circulo concentrico tipo OBS.
  // El motivo completo deja >= 3.4 % de margen dentro de la tesela.
  ringCx: 0.292,
  ringCy: 0.5,
  ringOuterR: 0.25,
  ringHoleR: 0.175,
  ringStrokeBoostBelow: 32, // a <= 32 px el trazo se engorda 1/4 px
  ringStrokeBoost: 0.25,

  // Pestillo: arranca en la mitad del trazo del anillo (nunca dentro del
  // agujero) y sale hacia la derecha.
  shaftFromX: 0.44,
  shaftToX: 0.752,
  shaftCy: 0.5,
  shaftHalfH: 0.036,

  // Dientes cuadrados hacia abajo: nacen en el borde inferior del pestillo y
  // sobresalen de el, para que se lean como dientes y no como un bloque.
  toothHalf: 0.045,
  toothTopY: 0.536,
  toothBottomY: 0.702,
  tooth1Cx: 0.598,
  tooth2Cx: 0.716,

  // Acento: triangulo "play" + punto de emision en el cuadrante inferior
  // derecho. Igual que el llavero, en fracciones del lado de la TESELA (U),
  // para que el pico del triangulo no lo recorte el borde de la tesela.
  play: { x0: 0.772, y0: 0.552, x1: 0.958, y1: 0.725, x2: 0.772, y2: 0.895, corner: 0.014 },
  dot: { cx: 0.908, cy: 0.725, r: 0.045 },

  // El motivo se baja un poco para quedar opticamente centrado en la tesela.
  motifY: 0.04,
};

/* ------------------------------------------------------------------ */
/* 2. Comprobacion de la paleta                                       */
/* ------------------------------------------------------------------ */

const hex = (c) => "#" + c.map((v) => v.toString(16).padStart(2, "0")).join("").toUpperCase();
const expected = {
  gradientTop: "#1B2430",
  gradientBottom: "#0E141B",
  key: "#F2F6FA",
  cyan: "#25F4EE",
  magenta: "#FE2C55",
};
for (const [k, v] of Object.entries(expected)) {
  if (hex(COLORS[k]) !== v) throw new Error(`paleta: ${k} = ${hex(COLORS[k])}, se esperaba ${v}`);
}

/* ------------------------------------------------------------------ */
/* 3. Mascaras geometricas (test explicito dentro/fuera + suavizado)   */
/* ------------------------------------------------------------------ */

/** Cobertura de un rectangulo redondeado mediante distancia con signo. */
function coverageRoundedRect(px, py, rect) {
  const x0 = rect.x - rect.r;
  const y0 = rect.y - rect.r;
  const x1 = rect.x + rect.w + rect.r;
  const y1 = rect.y + rect.h + rect.r;
  let dx = Math.max(x0 - px, px - x1); // <0 dentro, >0 fuera
  let dy = Math.max(y0 - py, py - y1);
  if (rect.r > 0) {
    // El redondeo se mide desde el tramo recto de la caja.
    const cx = Math.max(Math.min(px, rect.x + rect.w), rect.x) - px;
    const cy = Math.max(Math.min(py, rect.y + rect.h), rect.y) - py;
    const ex = Math.max(Math.abs(cx) - rect.r, 0);
    const ey = Math.max(Math.abs(cy) - rect.r, 0);
    const d = Math.hypot(ex, ey) - rect.r;
    dx = Math.max(dx, d);
    dy = Math.max(dy, d);
  }
  const d = Math.hypot(Math.max(dx, 0), Math.max(dy, 0)) + Math.min(Math.max(dx, dy), 0);
  return d <= 0 ? 1 : d >= 1 ? 0 : 1 - d;
}

/** Cobertura de un triangulo (aristas suavizadas en 1 px). */
function coverageTriangle(px, py, t) {
  const e0 = (t.x1 - t.x0) * (py - t.y0) - (t.y1 - t.y0) * (px - t.x0);
  const e1 = (t.x2 - t.x1) * (py - t.y1) - (t.y2 - t.y1) * (px - t.x1);
  const e2 = (t.x0 - t.x2) * (py - t.y2) - (t.y0 - t.y2) * (px - t.x2);
  const d = Math.min(e0, e1, e2);
  return d >= 1 ? 1 : d <= 0 ? 0 : d;
}

/** Cobertura de un anillo (toro): dentro del radio exterior y fuera del agujero. */
function coverageAnnulus(px, py, cx, cy, outerR, holeR) {
  const d = Math.hypot(px - cx, py - cy);
  const a = d <= outerR ? 1 : d >= outerR + 1 ? 0 : 1 - (d - outerR);
  const b = d <= holeR ? 1 : d >= holeR + 1 ? 0 : 1 - (d - holeR);
  return Math.max(0, a - b);
}

/** Cobertura de un circulo relleno. */
function coverageDisc(px, py, cx, cy, r) {
  const d = Math.hypot(px - cx, py - cy);
  return d <= r ? 1 : d >= r + 1 ? 0 : 1 - (d - r);
}

/* ------------------------------------------------------------------ */
/* 4. Composicion                                                     */
/* ------------------------------------------------------------------ */

/** Mezcla src (no premultiplicado) sobre dst premultiplicado. */
function over(dst, sr, sg, sb, w) {
  const iw = 1 - w;
  dst[0] = dst[0] * iw + sr * w;
  dst[1] = dst[1] * iw + sg * w;
  dst[2] = dst[2] * iw + sb * w;
  dst[3] = dst[3] * iw + w;
}

const overSolid = (dst, rgb, w) => over(dst, rgb[0], rgb[1], rgb[2], w);

/**
 * Rasteriza la imagen a `size` px con supersampling SS x SS: cada pixel es la
 * media de SS*SS muestras, de ahi el suavizado de bordes.
 */
function renderIcon(size, SS = 4) {
  const W = size;
  const D = DESIGN;
  const P = D.padRatio * W; // margen transparente
  const T = W - 2 * P; // lado de la tesela
  const U = (v) => P + v * T; // fraccion de la tesela -> px
  const UY = (v) => P + (v + D.motifY) * T; // igual, con el motivo centrado en vertical

  const boost = size <= D.ringStrokeBoostBelow ? D.ringStrokeBoost : 0;

  // Tesela y motivo resueltos una sola vez. Sin bisel: la tesela se apoya solo
  // en el degradado (un filete suelto se leia como una barra flotante).
  const tile = { x: P, y: P, w: T, h: T, r: D.cornerRatio * T };
  const ring = { cx: U(D.ringCx), cy: UY(D.ringCy), outerR: D.ringOuterR * T + boost, holeR: D.ringHoleR * T };
  const shaft = {
    x: U(D.shaftFromX),
    y: UY(D.shaftCy) - D.shaftHalfH * T,
    w: (D.shaftToX - D.shaftFromX) * T,
    h: D.shaftHalfH * 2 * T,
    r: Math.min(D.shaftHalfH * T, T * 0.02),
  };
  const toothW = D.toothHalf * 2 * T;
  const tooth = (cx) => ({
    x: U(cx) - toothW / 2,
    y: UY(D.toothTopY),
    w: toothW,
    h: (D.toothBottomY - D.toothTopY) * T,
    r: T * 0.012,
  });
  const toothA = tooth(D.tooth1Cx);
  const toothB = tooth(D.tooth2Cx);
  const dot = { cx: U(D.dot.cx), cy: U(D.dot.cy), r: D.dot.r * T };

  // Triangulo encogido hacia su centro para usarlo como mascara suavizada.
  const play = { x0: U(D.play.x0), y0: U(D.play.y0), x1: U(D.play.x1), y1: U(D.play.y1), x2: U(D.play.x2), y2: U(D.play.y2) };
  const gx = (play.x0 + play.x1 + play.x2) / 3;
  const gy = (play.y0 + play.y1 + play.y2) / 3;
  const k = D.play.corner;
  const tri = {
    x0: play.x0 + (gx - play.x0) * k,
    y0: play.y0 + (gy - play.y0) * k,
    x1: play.x1 + (gx - play.x1) * k,
    y1: play.y1 + (gy - play.y1) * k,
    x2: play.x2 + (gx - play.x2) * k,
    y2: play.y2 + (gy - play.y2) * k,
  };

  const top = COLORS.gradientTop;
  const bot = COLORS.gradientBottom;
  // Matriz de Bayer 4x4: un desplazamiento sub-LSB (±0.35/255) rompe el
  // bandeado del degradado oscuro sin alterar el color percibido.
  const BAYER = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5];
  const DITHER = 0.7 / 255;
  const out = new Uint8ClampedArray(W * W * 4);
  const acc = new Float64Array(4);
  const col = [0, 0, 0, 0];
  const inv = 1 / (SS * SS);

  for (let y = 0; y < W; y++) {
    for (let x = 0; x < W; x++) {
      acc[0] = acc[1] = acc[2] = acc[3] = 0;

      for (let sy = 0; sy < SS; sy++) {
        for (let sx = 0; sx < SS; sx++) {
          const fx = x + (sx + 0.5) / SS;
          const fy = y + (sy + 0.5) / SS;

          col[0] = col[1] = col[2] = col[3] = 0;

          // --- tesela: degradado vertical + esquinas redondeadas ------
          const aTile = coverageRoundedRect(fx, fy, tile);
          if (aTile > 0) {
            const t = Math.max(0, Math.min(1, (fy - P) / T));
            const dth = (BAYER[(y % 4) * 4 + (x % 4)] / 15 - 0.5) * DITHER;
            overSolid(
              col,
              [
                top[0] + (bot[0] - top[0]) * t + dth,
                top[1] + (bot[1] - top[1]) * t + dth,
                top[2] + (bot[2] - top[2]) * t + dth,
              ],
              aTile,
            );

            // --- motivo: llavero ---------------------------------------
            // 1) pestillo y dientes
            const aShaft = coverageRoundedRect(fx, fy, shaft);
            if (aShaft > 0) overSolid(col, COLORS.key, aShaft);
            const aTa = coverageRoundedRect(fx, fy, toothA);
            if (aTa > 0) overSolid(col, COLORS.key, aTa);
            const aTb = coverageRoundedRect(fx, fy, toothB);
            if (aTb > 0) overSolid(col, COLORS.key, aTb);

            // 2) anillo con agujero real
            const aRing = coverageAnnulus(fx, fy, ring.cx, ring.cy, ring.outerR, ring.holeR);
            if (aRing > 0) overSolid(col, COLORS.key, aRing);

            // 3) triangulo "play" y punto de emision
            const aPlay = coverageTriangle(fx, fy, tri);
            if (aPlay > 0) overSolid(col, COLORS.cyan, aPlay);
            const aDot = coverageDisc(fx, fy, dot.cx, dot.cy, dot.r);
            if (aDot > 0) overSolid(col, COLORS.magenta, aDot);
          }

          acc[0] += col[0] * col[3];
          acc[1] += col[1] * col[3];
          acc[2] += col[2] * col[3];
          acc[3] += col[3];
        }
      }

      const a = acc[3] * inv;
      const o = (y * W + x) * 4;
      if (a > 1e-6) {
        const invA = 1 / acc[3];
        out[o] = Math.round(acc[0] * invA);
        out[o + 1] = Math.round(acc[1] * invA);
        out[o + 2] = Math.round(acc[2] * invA);
      }
      out[o + 3] = Math.round(Math.min(1, a) * 255);
    }
  }
  return out;
}

/* ------------------------------------------------------------------ */
/* 5. Codificador PNG (8 bits, RGBA)                                  */
/* ------------------------------------------------------------------ */

const CRC_TABLE = (() => {
  const t = new Int32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c;
  }
  return t;
})();

function crc32(buf) {
  let c = 0xffffffff;
  for (let i = 0; i < buf.length; i++) c = CRC_TABLE[(c ^ buf[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function chunk(type, data) {
  const out = Buffer.alloc(12 + data.length);
  out.writeUInt32BE(data.length, 0);
  out.write(type, 4, "latin1");
  data.copy(out, 8);
  out.writeUInt32BE(crc32(out.subarray(4, 8 + data.length)), 8 + data.length);
  return out;
}

/**
 * Codifica un PNG RGBA de 8 bits.
 *
 * Se usa SIEMPRE el filtro 0 (None) en cada scanline: el flujo inflado es
 * exactamente (1 + width*4) bytes por fila (el byte 0 y despues los RGBA de la
 * fila), sin predictor, de modo que no puede desincronizarse con los datos.
 * Cuesta un archivo algo mayor, irrelevante para un icono.
 */
function encodePNG(w, h, rgba) {
  const stride = w * 4 + 1;
  const raw = Buffer.alloc(stride * h);
  for (let y = 0; y < h; y++) {
    const row = y * stride;
    raw[row] = 0; // filtro None
    let o = row + 1;
    for (let x = 0; x < w; x++) {
      const s = (y * w + x) * 4;
      raw[o++] = rgba[s];
      raw[o++] = rgba[s + 1];
      raw[o++] = rgba[s + 2];
      raw[o++] = rgba[s + 3];
    }
  }

  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(w, 0);
  ihdr.writeUInt32BE(h, 4);
  ihdr[8] = 8; // 8 bits por canal
  ihdr[9] = 6; // colour type 6: RGBA
  ihdr[10] = 0; // compresion deflate
  ihdr[11] = 0; // metodo de filtro 0
  ihdr[12] = 0; // sin entrelazado

  const idat = deflateSync(raw, { level: 9 });

  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", ihdr),
    chunk("IDAT", idat),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

/* ------------------------------------------------------------------ */
/* 6. Contenedores ICO e ICNS                                        */
/* ------------------------------------------------------------------ */

const ICO_SIZES = [16, 24, 32, 48, 64, 128, 256];

/** ICO multi-tamano; todas las entradas llevan payload PNG. */
function encodeICO(pngBySize) {
  const count = ICO_SIZES.length;
  const header = Buffer.alloc(6);
  header.writeUInt16LE(0, 0); // reservado
  header.writeUInt16LE(1, 2); // tipo: icono
  header.writeUInt16LE(count, 4);

  const dir = Buffer.alloc(16 * count);
  let offset = 6 + 16 * count;
  const payloads = [];

  ICO_SIZES.forEach((size, i) => {
    const png = pngBySize.get(size);
    if (!png) throw new Error("ICO: falta el PNG de " + size + " px");
    const o = i * 16;
    dir[o] = size >= 256 ? 0 : size; // 0 significa 256
    dir[o + 1] = size >= 256 ? 0 : size;
    dir[o + 2] = 0; // numero de colores de paleta
    dir[o + 3] = 0; // reservado
    dir.writeUInt16LE(1, o + 4); // planos
    dir.writeUInt16LE(32, o + 6); // bits por pixel
    dir.writeUInt32LE(png.length, o + 8); // bytesInRes
    dir.writeUInt32LE(offset, o + 12); // offset de la imagen
    offset += png.length;
    payloads.push(png);
  });

  return Buffer.concat([header, dir, ...payloads]);
}

/** Tipo ICNS -> lado en px. */
const ICNS_TYPES = [
  ["ic11", 32], // 16@2x
  ["ic12", 64], // 32@2x
  ["ic07", 128], // 128
  ["ic13", 256], // 128@2x
  ["ic08", 256], // 256
  ["ic14", 512], // 256@2x
  ["ic09", 512], // 512
  ["ic10", 1024], // 512@2x
];

/** ICNS con payload PNG por elemento (longitudes big-endian). */
function encodeICNS(pngBySize) {
  const elements = ICNS_TYPES.map(([type, size]) => {
    const png = pngBySize.get(size);
    if (!png) throw new Error("ICNS: falta el PNG de " + size + " px");
    const head = Buffer.alloc(8);
    head.write(type, 0, "latin1");
    head.writeUInt32BE(8 + png.length, 4);
    return Buffer.concat([head, png]);
  });

  const body = Buffer.concat(elements);
  const head = Buffer.alloc(8);
  head.write("icns", 0, "latin1");
  head.writeUInt32BE(8 + body.length, 4);
  return Buffer.concat([head, body]);
}

/* ------------------------------------------------------------------ */
/* 7. Programa principal                                              */
/* ------------------------------------------------------------------ */

const TARGET_SIZES = [16, 24, 32, 48, 64, 128, 256, 512, 1024];

function main() {
  const here = dirname(fileURLToPath(import.meta.url));
  const assets = join(here, "..", "assets");
  mkdirSync(assets, { recursive: true });

  const pngBySize = new Map();
  for (const size of TARGET_SIZES) {
    pngBySize.set(size, encodePNG(size, size, renderIcon(size, 4)));
  }

  const outputs = [
    ["icon.png", pngBySize.get(512)],
    ["icon@2x.png", pngBySize.get(1024)],
    ["icon.ico", encodeICO(pngBySize)],
    ["icon.icns", encodeICNS(pngBySize)],
  ];

  for (const [name, buf] of outputs) {
    writeFileSync(join(assets, name), buf);
    process.stdout.write(`${name}\t${buf.length} bytes\n`);
  }
}

main();
