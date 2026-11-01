/**
 * @file Características de los ojos de un cuadro, para el modelo de mirada.
 *
 * Sigue el método de WebGazer: recorta cada ojo con los puntos del rostro, lo
 * pasa a gris, lo reduce a 10 × 6 y ecualiza su histograma, para que la
 * iluminación pese menos. A eso se suma la posición del iris dentro de cada
 * ojo y la orientación y posición de la cabeza, que ayudan cuando el
 * participante se mueve.
 *
 * Las funciones son puras (reciben números y píxeles): se prueban en Node.
 */

(function (root) {
  'use strict';

  const UX = (root.UX = root.UX || {});

  /**
   * Índices de los puntos del modelo de rostro de MediaPipe (478 puntos). "Izquierdo"
   * y "derecho" son desde el participante. Los arcos son los de WebGazer.
   */
  const EYES = Object.freeze({
    left: {
      upper: [466, 388, 387, 386, 385, 384, 398],
      lower: [263, 249, 390, 373, 374, 380, 381, 382, 362],
      outer: 263,
      inner: 362,
      top: 386,
      bottom: 374,
    },
    right: {
      upper: [246, 161, 160, 159, 158, 157, 173],
      lower: [33, 7, 163, 144, 145, 153, 154, 155, 133],
      outer: 33,
      inner: 133,
      top: 159,
      bottom: 145,
    },
  });
  /** Centros de los dos iris en el modelo de 478 puntos. */
  const IRIS_CENTERS = [468, 473];
  /** Tamaño al que se reduce cada ojo, como en WebGazer. */
  const PATCH_WIDTH = 10;
  const PATCH_HEIGHT = 6;
  /** Cantidad total de características: dos ojos, iris y cabeza. */
  const FEATURE_COUNT = 2 * PATCH_WIDTH * PATCH_HEIGHT + 4 + 6;

  /** Punto de un landmark normalizado, en píxeles del cuadro. */
  const toPixels = (landmark, width, height) => ({ x: landmark.x * width, y: landmark.y * height });

  /**
   * Caja de cada ojo en píxeles del cuadro, desde sus arcos superior e inferior.
   *
   * @param {{x: number, y: number}[]} landmarks - Puntos del rostro, normalizados entre 0 y 1.
   * @param {number} width - Ancho del cuadro en píxeles.
   * @param {number} height - Alto del cuadro en píxeles.
   * @returns {({left: object, right: object}|null)} Cajas `{x, y, width, height}`
   *   enteras, o `null` si algún ojo queda fuera del cuadro o sin tamaño.
   */
  function eyeBoxes(landmarks, width, height) {
    if (!landmarks || landmarks.length < 478) {
      return null;
    }
    const boxes = {};
    for (const [side, eye] of Object.entries(EYES)) {
      const points = [...eye.upper, ...eye.lower].map((i) => toPixels(landmarks[i], width, height));
      const x0 = Math.floor(Math.min(...points.map((p) => p.x)));
      const y0 = Math.floor(Math.min(...points.map((p) => p.y)));
      const x1 = Math.ceil(Math.max(...points.map((p) => p.x)));
      const y1 = Math.ceil(Math.max(...points.map((p) => p.y)));
      if (x0 < 0 || y0 < 0 || x1 > width || y1 > height || x1 - x0 < 2 || y1 - y0 < 2) {
        return null;
      }
      boxes[side] = { x: x0, y: y0, width: x1 - x0, height: y1 - y0 };
    }
    return boxes;
  }

  /**
   * Convierte un recorte RGBA en un parche gris de 10 × 6 con el histograma ecualizado.
   *
   * @param {Uint8ClampedArray|number[]} rgba - Píxeles del recorte, 4 valores por píxel.
   * @param {number} width - Ancho del recorte.
   * @param {number} height - Alto del recorte.
   * @returns {number[]} 60 valores entre 0 y 1, por filas.
   */
  function eyePatch(rgba, width, height) {
    const levels = [];
    for (let py = 0; py < PATCH_HEIGHT; py += 1) {
      // Cada celda promedia su parte del recorte; si el recorte es más chico que
      // el parche, la celda toma al menos un píxel.
      const y0 = Math.min(height - 1, Math.floor((py * height) / PATCH_HEIGHT));
      const y1 = Math.max(y0 + 1, Math.floor(((py + 1) * height) / PATCH_HEIGHT));
      for (let px = 0; px < PATCH_WIDTH; px += 1) {
        const x0 = Math.min(width - 1, Math.floor((px * width) / PATCH_WIDTH));
        const x1 = Math.max(x0 + 1, Math.floor(((px + 1) * width) / PATCH_WIDTH));
        let sum = 0;
        for (let y = y0; y < y1; y += 1) {
          for (let x = x0; x < x1; x += 1) {
            const i = (y * width + x) * 4;
            // Luminancia (Rec. 601), la misma que usa WebGazer.
            sum += 0.299 * rgba[i] + 0.587 * rgba[i + 1] + 0.114 * rgba[i + 2];
          }
        }
        levels.push(Math.round(sum / ((y1 - y0) * (x1 - x0))));
      }
    }
    return equalize(levels);
  }

  /** Ecualiza el histograma de valores entre 0 y 255 y los devuelve entre 0 y 1. */
  function equalize(levels) {
    const histogram = new Array(256).fill(0);
    levels.forEach((level) => (histogram[level] += 1));
    const cdf = new Array(256);
    let running = 0;
    for (let i = 0; i < 256; i += 1) {
      running += histogram[i];
      cdf[i] = running;
    }
    const min = cdf.find((value) => value > 0);
    const range = levels.length - min;
    // Un parche de un solo tono no tiene contraste que ecualizar.
    return levels.map((level) => (range === 0 ? 0.5 : (cdf[level] - min) / range));
  }

  /**
   * Posición del iris dentro de cada ojo: a lo largo de la línea entre sus
   * comisuras (0 = comisura externa, 1 = interna) y hacia arriba o abajo desde
   * el centro de los párpados, en anchos de ojo.
   *
   * @param {{x: number, y: number}[]} landmarks - Puntos del rostro, normalizados.
   * @param {number} width - Ancho del cuadro en píxeles.
   * @param {number} height - Alto del cuadro en píxeles.
   * @returns {number[]} `[izq. horizontal, izq. vertical, der. horizontal, der. vertical]`.
   */
  function irisOffsets(landmarks, width, height) {
    const irises = IRIS_CENTERS.map((i) => toPixels(landmarks[i], width, height));
    const result = [];
    for (const eye of [EYES.left, EYES.right]) {
      const outer = toPixels(landmarks[eye.outer], width, height);
      const inner = toPixels(landmarks[eye.inner], width, height);
      const center = { x: (outer.x + inner.x) / 2, y: (outer.y + inner.y) / 2 };
      // El orden de los iris en el modelo no está documentado: se toma el más cercano al ojo.
      const iris = irises.reduce((best, p) =>
        Math.hypot(p.x - center.x, p.y - center.y) < Math.hypot(best.x - center.x, best.y - center.y)
          ? p
          : best,
      );
      const axis = { x: inner.x - outer.x, y: inner.y - outer.y };
      const length = Math.hypot(axis.x, axis.y) || 1;
      const along = ((iris.x - outer.x) * axis.x + (iris.y - outer.y) * axis.y) / length ** 2;
      const top = toPixels(landmarks[eye.top], width, height);
      const bottom = toPixels(landmarks[eye.bottom], width, height);
      const lidsY = (top.y + bottom.y) / 2;
      result.push(along, (iris.y - lidsY) / length);
    }
    return result;
  }

  /**
   * Arma el vector de características de un cuadro.
   *
   * @param {object} parts - Partes ya calculadas.
   * @param {number[]} parts.left - Parche del ojo izquierdo (60 valores).
   * @param {number[]} parts.right - Parche del ojo derecho (60 valores).
   * @param {number[]} parts.iris - Resultado de `irisOffsets` (4 valores).
   * @param {{yaw: number, pitch: number, roll: number, tx: number, ty: number, tz: number}} parts.head -
   *   Orientación en grados y posición de la cabeza.
   * @returns {number[]} Vector de `FEATURE_COUNT` valores.
   */
  function featureVector({ left, right, iris, head }) {
    const vector = [...left, ...right, ...iris, head.yaw, head.pitch, head.roll, head.tx, head.ty, head.tz];
    if (vector.length !== FEATURE_COUNT) {
      throw new Error(`expected ${FEATURE_COUNT} features, got ${vector.length}`);
    }
    return vector;
  }

  UX.eyeFeatures = Object.freeze({
    EYES,
    FEATURE_COUNT,
    PATCH_WIDTH,
    PATCH_HEIGHT,
    eyeBoxes,
    eyePatch,
    irisOffsets,
    featureVector,
  });
})(globalThis);
