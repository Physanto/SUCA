/**
 * @file Pruebas de `camera/iris-refine.js` con ojos sintéticos: un iris oscuro
 * sobre una esclera clara, con centro sub-píxel conocido.
 */

const test = require('node:test');
const assert = require('node:assert/strict');

require('../camera/numeric.js');
require('../camera/iris-refine.js');

const { UX } = globalThis;
const { grayscale, refineIris, fitCircle } = UX.irisRefine;

/**
 * Dibuja un ojo sintético en RGBA: esclera clara, iris oscuro (con borde suavizado
 * por supermuestreo) y, si se pide, un párpado que tapa la parte de arriba.
 *
 * @param {object} options - Ancho, alto, centro y radio del iris, altura del párpado,
 *   amplitud del ruido y semilla.
 * @returns {Uint8ClampedArray} Píxeles.
 */
function syntheticEye({ width = 80, height = 48, cx, cy, r, lidY = -Infinity, noise = 0, seed = 7 }) {
  const rgba = new Uint8ClampedArray(width * height * 4);
  let state = seed;
  const random = () => {
    state = (1103515245 * state + 12345) % 2147483648;
    return state / 2147483648;
  };
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      let inside = 0;
      for (let sy = 0; sy < 4; sy += 1) {
        for (let sx = 0; sx < 4; sx += 1) {
          const px = x + (sx + 0.5) / 4;
          const py = y + (sy + 0.5) / 4;
          inside += Math.hypot(px - cx - 0.5, py - cy - 0.5) <= r ? 1 : 0;
        }
      }
      let value = 210 - (inside / 16) * 150;
      if (y < lidY) {
        value = 150;
      }
      value += (random() - 0.5) * 2 * noise;
      const i = 4 * (y * width + x);
      rgba[i] = value;
      rgba[i + 1] = value;
      rgba[i + 2] = value;
      rgba[i + 3] = 255;
    }
  }
  return rgba;
}

test('finds the center of the iris to a fraction of a pixel from a rough seed', () => {
  const cx = 37.35;
  const cy = 22.8;
  const gray = grayscale(syntheticEye({ cx, cy, r: 11 }), 80, 48);

  const iris = refineIris(gray, 80, 48, { x: cx + 1.6, y: cy - 1.2, r: 9.5 });

  assert.equal(iris.ok, true);
  assert.ok(Math.hypot(iris.x - cx, iris.y - cy) < 0.15, `center off by ${Math.hypot(iris.x - cx, iris.y - cy)}`);
  assert.ok(Math.abs(iris.r - 11) < 0.6);
});

test('stays accurate with sensor noise', () => {
  const cx = 40.6;
  const cy = 24.1;
  const gray = grayscale(syntheticEye({ cx, cy, r: 12, noise: 12 }), 80, 48);

  const iris = refineIris(gray, 80, 48, { x: cx - 1, y: cy + 1, r: 12 });

  assert.equal(iris.ok, true);
  assert.ok(Math.hypot(iris.x - cx, iris.y - cy) < 0.3);
});

test('ignores the edge of the upper lid when its contour is given', () => {
  const cx = 38.2;
  const cy = 26.4;
  const lidY = 19;
  const gray = grayscale(syntheticEye({ cx, cy, r: 11, lidY }), 80, 48);
  const lids = {
    upper: [{ x: 0, y: lidY }, { x: 79, y: lidY }],
    lower: [{ x: 0, y: 47 }, { x: 79, y: 47 }],
  };

  const iris = refineIris(gray, 80, 48, { x: cx, y: cy - 1, r: 11 }, lids);

  assert.equal(iris.ok, true);
  assert.ok(Math.hypot(iris.x - cx, iris.y - cy) < 0.3);
});

test('falls back to the seed when there is no iris to see', () => {
  const flat = grayscale(new Uint8ClampedArray(80 * 48 * 4).fill(180), 80, 48);

  const iris = refineIris(flat, 80, 48, { x: 40, y: 24, r: 10 });

  assert.deepEqual(iris, { x: 40, y: 24, r: 10, inliers: 0, ok: false });
});

test('fits a circle through points on it', () => {
  const points = [0, 1, 2, 3, 4, 5].map((k) => ({
    x: 5 + 3 * Math.cos(k),
    y: -2 + 3 * Math.sin(k),
  }));

  const circle = fitCircle(points);

  assert.ok(Math.abs(circle.x - 5) < 1e-9 && Math.abs(circle.y + 2) < 1e-9 && Math.abs(circle.r - 3) < 1e-9);
});
