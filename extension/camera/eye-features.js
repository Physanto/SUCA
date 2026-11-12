/**
 * @file Características de los ojos de un cuadro, para el modelo de mirada.
 *
 * Dos juegos de características:
 * - **Apariencia** (estimador por apariencia, como WebGazer): cada ojo recortado,
 *   en gris, reducido a 10 × 6 y con el histograma ecualizado, más la posición
 *   del iris y la pose de la cabeza (`featureVector`).
 * - **Geometría** (estimador geométrico): el iris de MediaPipe como semilla
 *   (`irisSeeds`), el recorte y los párpados para refinarlo (`eyeCrop`,
 *   `eyeLids`) y la posición del iris refinado dentro del ojo (`eyeGeometry`).
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

  /** Centro y contorno de cada iris en el modelo de 478 puntos. */
  const IRISES = Object.freeze([
    { center: 468, contour: [469, 470, 471, 472] },
    { center: 473, contour: [474, 475, 476, 477] },
  ]);

  /** Centro de un ojo (punto medio entre sus comisuras), en píxeles. */
  function eyeCenter(landmarks, eye, width, height) {
    const outer = toPixels(landmarks[eye.outer], width, height);
    const inner = toPixels(landmarks[eye.inner], width, height);
    return { x: (outer.x + inner.x) / 2, y: (outer.y + inner.y) / 2 };
  }

  /**
   * Iris de MediaPipe de cada ojo, en píxeles: centro y radio (distancia media a
   * los cuatro puntos del contorno). Sirve de semilla para refinarlo.
   *
   * @param {{x: number, y: number}[]} landmarks - Puntos del rostro, normalizados.
   * @param {number} width - Ancho del cuadro.
   * @param {number} height - Alto del cuadro.
   * @returns {{left: {x: number, y: number, r: number}, right: {x: number, y: number, r: number}}} Iris.
   */
  function irisSeeds(landmarks, width, height) {
    const irises = IRISES.map(({ center, contour }) => {
      const c = toPixels(landmarks[center], width, height);
      const r =
        contour
          .map((i) => toPixels(landmarks[i], width, height))
          .reduce((sum, p) => sum + Math.hypot(p.x - c.x, p.y - c.y), 0) / contour.length;
      return { x: c.x, y: c.y, r };
    });
    const result = {};
    for (const [side, eye] of Object.entries(EYES)) {
      const center = eyeCenter(landmarks, eye, width, height);
      // El orden de los iris en el modelo no está documentado: se toma el más cercano al ojo.
      result[side] = irises.reduce((best, iris) =>
        Math.hypot(iris.x - center.x, iris.y - center.y) < Math.hypot(best.x - center.x, best.y - center.y)
          ? iris
          : best,
      );
    }
    return result;
  }

  /**
   * Contorno de los párpados de un ojo, en píxeles.
   *
   * @param {{x: number, y: number}[]} landmarks - Puntos del rostro, normalizados.
   * @param {string} side - `left` o `right` (de la persona).
   * @param {number} width - Ancho del cuadro.
   * @param {number} height - Alto del cuadro.
   * @returns {{upper: Array<{x: number, y: number}>, lower: Array<{x: number, y: number}>}} Párpados.
   *   El superior incluye las comisuras, para cubrir todo el ancho del ojo.
   */
  function eyeLids(landmarks, side, width, height) {
    const eye = EYES[side];
    const corners = [eye.outer, eye.inner].map((i) => toPixels(landmarks[i], width, height));
    return {
      upper: [...corners, ...eye.upper.map((i) => toPixels(landmarks[i], width, height))],
      lower: eye.lower.map((i) => toPixels(landmarks[i], width, height)),
    };
  }

  /**
   * Recorte de un ojo para refinar el iris: la caja del ojo con margen para que
   * entre el iris completo aunque el párpado lo tape.
   *
   * @param {{x: number, y: number}[]} landmarks - Puntos del rostro, normalizados.
   * @param {string} side - `left` o `right`.
   * @param {{r: number}} iris - Iris de MediaPipe del ojo, en píxeles.
   * @param {number} width - Ancho del cuadro.
   * @param {number} height - Alto del cuadro.
   * @returns {({x: number, y: number, width: number, height: number}|null)} Caja entera, o
   *   `null` si el ojo queda fuera del cuadro.
   */
  function eyeCrop(landmarks, side, iris, width, height) {
    const eye = EYES[side];
    const points = [...eye.upper, ...eye.lower].map((i) => toPixels(landmarks[i], width, height));
    const xs = points.map((p) => p.x);
    const ys = points.map((p) => p.y);
    const eyeWidth = Math.max(...xs) - Math.min(...xs);
    const margin = Math.max(0.25 * eyeWidth, 1.7 * iris.r);
    const x0 = Math.floor(Math.min(...xs) - 0.1 * eyeWidth);
    const x1 = Math.ceil(Math.max(...xs) + 0.1 * eyeWidth);
    const cy = (Math.min(...ys) + Math.max(...ys)) / 2;
    const y0 = Math.floor(Math.min(Math.min(...ys), cy - margin));
    const y1 = Math.ceil(Math.max(Math.max(...ys), cy + margin));
    if (x0 < 0 || y0 < 0 || x1 > width || y1 > height || x1 - x0 < 4 || y1 - y0 < 4) {
      return null;
    }
    return { x: x0, y: y0, width: x1 - x0, height: y1 - y0 };
  }

  /**
   * Posición de cada iris dentro de su ojo y apertura de los párpados, en anchos
   * de ojo, para el estimador geométrico.
   *
   * Los ejes son los de la imagen, corregidos por la inclinación de la cabeza: el
   * horizontal va de la comisura de la izquierda de la imagen a la de la derecha,
   * en los dos ojos, y el vertical es su perpendicular hacia abajo. Así `h` tiene
   * el mismo sentido en los dos ojos y se pueden promediar.
   *
   * @param {{x: number, y: number}[]} landmarks - Puntos del rostro, normalizados.
   * @param {{left: {x: number, y: number}, right: {x: number, y: number}}} irises - Centro de
   *   cada iris en píxeles (refinado o de MediaPipe).
   * @param {number} width - Ancho del cuadro.
   * @param {number} height - Alto del cuadro.
   * @returns {{left: {h: number, v: number, open: number}, right: {h: number, v: number,
   *   open: number}, u: number, v: number}} Cada ojo, y el punto medio entre los ojos en
   *   la imagen (`u`, `v`, entre 0 y 1).
   */
  function eyeGeometry(landmarks, irises, width, height) {
    const result = {};
    const centers = [];
    for (const [side, eye] of Object.entries(EYES)) {
      const a = toPixels(landmarks[eye.outer], width, height);
      const b = toPixels(landmarks[eye.inner], width, height);
      const [left, right] = a.x <= b.x ? [a, b] : [b, a];
      const length = Math.hypot(right.x - left.x, right.y - left.y) || 1;
      const axis = { x: (right.x - left.x) / length, y: (right.y - left.y) / length };
      const down = { x: -axis.y, y: axis.x };
      const center = { x: (left.x + right.x) / 2, y: (left.y + right.y) / 2 };
      const top = toPixels(landmarks[eye.top], width, height);
      const bottom = toPixels(landmarks[eye.bottom], width, height);
      const lids = { x: (top.x + bottom.x) / 2, y: (top.y + bottom.y) / 2 };
      const iris = irises[side];
      result[side] = {
        h: ((iris.x - center.x) * axis.x + (iris.y - center.y) * axis.y) / length,
        v: ((iris.x - lids.x) * down.x + (iris.y - lids.y) * down.y) / length,
        open: Math.max(0, ((bottom.x - top.x) * down.x + (bottom.y - top.y) * down.y) / length),
      };
      centers.push(center);
    }
    result.u = (centers[0].x + centers[1].x) / 2 / width;
    result.v = (centers[0].y + centers[1].y) / 2 / height;
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
    IRISES,
    irisSeeds,
    eyeLids,
    eyeCrop,
    eyeGeometry,
    FEATURE_COUNT,
    PATCH_WIDTH,
    PATCH_HEIGHT,
    eyeBoxes,
    eyePatch,
    irisOffsets,
    featureVector,
  });
})(globalThis);
