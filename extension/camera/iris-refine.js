/**
 * @file Refina el centro del iris con precisión sub-píxel en el recorte del ojo
 * a resolución completa.
 *
 * MediaPipe ubica el iris dentro de su propio recorte reducido del rostro, así
 * que su centro tiembla y puede estar corrido uno o dos píxeles de la cámara.
 * Mover la mirada un grado mueve el iris apenas medio píxel a 1080p: hace falta
 * algo más fino. Aquí, partiendo del iris de MediaPipe:
 *
 * 1. se lanzan rayos desde el centro y en cada uno se busca el borde del iris
 *    (el mayor salto de oscuro a claro: del iris a la esclera), con posición
 *    sub-píxel por interpolación parabólica;
 * 2. se descartan los bordes que caen sobre los párpados (MediaPipe da su contorno);
 * 3. se ajusta un círculo a los bordes con RANSAC (resiste reflejos y pestañas)
 *    y luego por mínimos cuadrados con los puntos que concuerdan.
 *
 * Con luz visible y ojos oscuros la pupila casi no se distingue del iris; el
 * borde que sí se ve bien es el del iris contra la esclera.
 *
 * Funciones puras sobre una imagen en gris: se prueban en Node.
 */

(function (root) {
  'use strict';

  const UX = (root.UX = root.UX || {});

  /** Rayos que se lanzan desde el centro. */
  const RAYS = 48;
  /** Tramo de cada rayo donde se busca el borde, en radios del iris de MediaPipe. */
  const RAY_FROM = 0.55;
  const RAY_TO = 1.6;
  /** Paso de muestreo a lo largo del rayo, en píxeles. */
  const RAY_STEP = 0.25;
  /** Salto mínimo de brillo por píxel para aceptar un borde (niveles de 0 a 255). */
  const MIN_CONTRAST = 3;
  /** Distancia mínima de un borde al contorno de un párpado, en píxeles. */
  const LID_MARGIN = 1;
  /** Bordes que hacen falta para confiar en el círculo. */
  const MIN_INLIERS = 8;
  /** Intentos de RANSAC. */
  const RANSAC_ITERATIONS = 60;
  /** El radio puede diferir del de MediaPipe hasta este factor, y el centro moverse hasta esta fracción del radio. */
  const RADIUS_RANGE = [0.6, 1.5];
  const MAX_SHIFT = 0.6;

  /**
   * Convierte píxeles RGBA en una imagen en gris (luminancia Rec. 601), suavizada
   * con un filtro de 3 × 3 para que el ruido del sensor no cree bordes falsos.
   *
   * @param {Uint8ClampedArray|number[]} rgba - Píxeles, 4 valores por píxel.
   * @param {number} width - Ancho.
   * @param {number} height - Alto.
   * @returns {Float32Array} Gris de 0 a 255, por filas.
   */
  function grayscale(rgba, width, height) {
    const gray = new Float32Array(width * height);
    for (let i = 0; i < width * height; i += 1) {
      gray[i] = 0.299 * rgba[4 * i] + 0.587 * rgba[4 * i + 1] + 0.114 * rgba[4 * i + 2];
    }
    // Núcleo binomial [1 2 1] en cada eje; los bordes de la imagen repiten su píxel.
    const pass = (source, dx, dy) => {
      const out = new Float32Array(width * height);
      for (let y = 0; y < height; y += 1) {
        for (let x = 0; x < width; x += 1) {
          const at = (xx, yy) =>
            source[Math.min(height - 1, Math.max(0, yy)) * width + Math.min(width - 1, Math.max(0, xx))];
          out[y * width + x] = (at(x - dx, y - dy) + 2 * at(x, y) + at(x + dx, y + dy)) / 4;
        }
      }
      return out;
    };
    return pass(pass(gray, 1, 0), 0, 1);
  }

  /** Brillo en un punto con interpolación bilineal; `null` fuera de la imagen. */
  function sample(gray, width, height, x, y) {
    if (x < 0 || y < 0 || x > width - 1 || y > height - 1) {
      return null;
    }
    const x0 = Math.floor(x);
    const y0 = Math.floor(y);
    const x1 = Math.min(width - 1, x0 + 1);
    const y1 = Math.min(height - 1, y0 + 1);
    const fx = x - x0;
    const fy = y - y0;
    const top = gray[y0 * width + x0] * (1 - fx) + gray[y0 * width + x1] * fx;
    const bottom = gray[y1 * width + x0] * (1 - fx) + gray[y1 * width + x1] * fx;
    return top * (1 - fy) + bottom * fy;
  }

  /** Altura de una polilínea (ordenada por x o no) en una abscisa, interpolando; `null` fuera de ella. */
  function heightAt(polyline, x) {
    const sorted = [...polyline].sort((a, b) => a.x - b.x);
    for (let i = 0; i < sorted.length - 1; i += 1) {
      const a = sorted[i];
      const b = sorted[i + 1];
      if (x >= a.x && x <= b.x) {
        const f = b.x === a.x ? 0 : (x - a.x) / (b.x - a.x);
        return a.y + f * (b.y - a.y);
      }
    }
    return null;
  }

  /** Si un punto queda entre los dos párpados, con margen. Sin párpados, siempre. */
  function insideLids(lids, point) {
    if (!lids) {
      return true;
    }
    const upper = heightAt(lids.upper, point.x);
    const lower = heightAt(lids.lower, point.x);
    if (upper === null || lower === null) {
      return false;
    }
    return point.y > upper + LID_MARGIN && point.y < lower - LID_MARGIN;
  }

  /**
   * Bordes del iris a lo largo de rayos desde un centro aproximado.
   *
   * @param {Float32Array} gray - Imagen en gris.
   * @param {number} width - Ancho.
   * @param {number} height - Alto.
   * @param {{x: number, y: number, r: number}} seed - Iris aproximado.
   * @param {?{upper: Array<{x: number, y: number}>, lower: Array<{x: number, y: number}>}} lids -
   *   Contornos de los párpados, en las mismas coordenadas.
   * @returns {Array<{x: number, y: number}>} Puntos de borde.
   */
  function edgePoints(gray, width, height, seed, lids) {
    const points = [];
    for (let ray = 0; ray < RAYS; ray += 1) {
      const angle = (2 * Math.PI * ray) / RAYS;
      const dx = Math.cos(angle);
      const dy = Math.sin(angle);
      const profile = [];
      for (let r = RAY_FROM * seed.r - RAY_STEP; r <= RAY_TO * seed.r + RAY_STEP; r += RAY_STEP) {
        profile.push({ r, value: sample(gray, width, height, seed.x + r * dx, seed.y + r * dy) });
      }
      let best = null;
      for (let i = 1; i < profile.length - 1; i += 1) {
        const before = profile[i - 1].value;
        const after = profile[i + 1].value;
        if (before === null || after === null) {
          continue;
        }
        const slope = (after - before) / (2 * RAY_STEP);
        if (slope >= MIN_CONTRAST && (best === null || slope > best.slope)) {
          best = { i, slope };
        }
      }
      if (best === null || best.i < 2 || best.i > profile.length - 3) {
        continue;
      }
      // Vértice de la parábola que pasa por las tres pendientes alrededor del máximo.
      const slopeAt = (i) => (profile[i + 1].value - profile[i - 1].value) / (2 * RAY_STEP);
      const s0 = slopeAt(best.i - 1);
      const s1 = best.slope;
      const s2 = slopeAt(best.i + 1);
      const curvature = s0 - 2 * s1 + s2;
      const offset = curvature < 0 ? Math.max(-0.5, Math.min(0.5, (s0 - s2) / (2 * curvature))) : 0;
      const r = profile[best.i].r + offset * RAY_STEP;
      const point = { x: seed.x + r * dx, y: seed.y + r * dy };
      if (insideLids(lids, point)) {
        points.push(point);
      }
    }
    return points;
  }

  /** Círculo que pasa por tres puntos, o `null` si están alineados. */
  function circleThrough(a, b, c) {
    const d = 2 * (a.x * (b.y - c.y) + b.x * (c.y - a.y) + c.x * (a.y - b.y));
    if (Math.abs(d) < 1e-9) {
      return null;
    }
    const a2 = a.x * a.x + a.y * a.y;
    const b2 = b.x * b.x + b.y * b.y;
    const c2 = c.x * c.x + c.y * c.y;
    const x = (a2 * (b.y - c.y) + b2 * (c.y - a.y) + c2 * (a.y - b.y)) / d;
    const y = (a2 * (c.x - b.x) + b2 * (a.x - c.x) + c2 * (b.x - a.x)) / d;
    return { x, y, r: Math.hypot(a.x - x, a.y - y) };
  }

  /**
   * Círculo de mínimos cuadrados algebraicos (método de Kåsa) por una lista de puntos.
   *
   * @param {Array<{x: number, y: number}>} points - Al menos tres puntos.
   * @returns {({x: number, y: number, r: number}|null)} Círculo, o `null` si no hay solución.
   */
  function fitCircle(points) {
    // x² + y² + D·x + E·y + F = 0, lineal en D, E y F.
    const ata = [
      [0, 0, 0],
      [0, 0, 0],
      [0, 0, 0],
    ];
    const atb = [[0], [0], [0]];
    for (const p of points) {
      const row = [p.x, p.y, 1];
      const rhs = -(p.x * p.x + p.y * p.y);
      for (let i = 0; i < 3; i += 1) {
        atb[i][0] += row[i] * rhs;
        for (let j = 0; j < 3; j += 1) {
          ata[i][j] += row[i] * row[j];
        }
      }
    }
    let solution;
    try {
      solution = UX.numeric.solveSymmetric(ata, atb).map((row) => row[0]);
    } catch (error) {
      return null;
    }
    const [d, e, f] = solution;
    const x = -d / 2;
    const y = -e / 2;
    const r2 = x * x + y * y - f;
    return r2 > 0 ? { x, y, r: Math.sqrt(r2) } : null;
  }

  /** Generador pseudoaleatorio fijo: el mismo cuadro da siempre el mismo resultado. */
  function seededRandom(seed) {
    let state = seed >>> 0 || 1;
    return () => {
      state = (1664525 * state + 1013904223) >>> 0;
      return state / 4294967296;
    };
  }

  /**
   * Refina el iris de un ojo.
   *
   * @param {Float32Array} gray - Recorte del ojo en gris (`grayscale`).
   * @param {number} width - Ancho del recorte.
   * @param {number} height - Alto del recorte.
   * @param {{x: number, y: number, r: number}} seed - Centro y radio del iris de MediaPipe,
   *   en píxeles del recorte.
   * @param {?{upper: Array<{x: number, y: number}>, lower: Array<{x: number, y: number}>}} [lids] -
   *   Contorno de los párpados en píxeles del recorte.
   * @returns {{x: number, y: number, r: number, inliers: number, ok: boolean}} Iris refinado.
   *   Si no se pudo (`ok` falso), devuelve el de MediaPipe.
   */
  function refineIris(gray, width, height, seed, lids = null) {
    const fallback = { x: seed.x, y: seed.y, r: seed.r, inliers: 0, ok: false };
    if (!(seed.r > 1)) {
      return fallback;
    }
    const points = edgePoints(gray, width, height, seed, lids);
    if (points.length < MIN_INLIERS) {
      return fallback;
    }
    const tolerance = Math.max(0.75, 0.08 * seed.r);
    const plausible = (circle) =>
      circle !== null &&
      circle.r >= RADIUS_RANGE[0] * seed.r &&
      circle.r <= RADIUS_RANGE[1] * seed.r &&
      Math.hypot(circle.x - seed.x, circle.y - seed.y) <= MAX_SHIFT * seed.r;
    const inliersOf = (circle) =>
      points.filter((p) => Math.abs(Math.hypot(p.x - circle.x, p.y - circle.y) - circle.r) <= tolerance);
    const random = seededRandom(Math.round(seed.x * 1000 + seed.y * 7919));
    let best = [];
    for (let i = 0; i < RANSAC_ITERATIONS; i += 1) {
      const pick = () => points[Math.floor(random() * points.length)];
      const circle = circleThrough(pick(), pick(), pick());
      if (!plausible(circle)) {
        continue;
      }
      const inliers = inliersOf(circle);
      if (inliers.length > best.length) {
        best = inliers;
      }
    }
    if (best.length < MIN_INLIERS) {
      return fallback;
    }
    // Dos pasadas: el círculo de todos los que concuerdan puede sumar algunos más.
    let circle = fitCircle(best);
    if (plausible(circle)) {
      const again = inliersOf(circle);
      if (again.length >= best.length) {
        circle = fitCircle(again) || circle;
        best = again;
      }
    }
    if (!plausible(circle)) {
      return fallback;
    }
    return { x: circle.x, y: circle.y, r: circle.r, inliers: best.length, ok: true };
  }

  UX.irisRefine = Object.freeze({ grayscale, refineIris, fitCircle });
})(globalThis);
