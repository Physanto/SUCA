/**
 * @file Estimador de mirada por apariencia: convierte la imagen reducida de los
 * ojos, la posición de los iris y la pose de la cabeza de un cuadro en un punto
 * de la ventana, en píxeles CSS.
 *
 * Es una regresión ridge, como la de WebGazer: se entrena con los cuadros
 * tomados mientras el participante mira los puntos de la calibración. Las
 * características se estandarizan (media 0, desviación 1) para que una sola
 * penalización sirva para todas, y la penalización se elige por validación
 * cruzada dejando fuera un punto de calibración a la vez.
 *
 * Es uno de los dos candidatos del estimador de mirada (`gaze-estimator.js`);
 * el otro es el geométrico (`gaze-geometry.js`). La ridge también corrige el
 * residuo del geométrico (`UX.ridge`).
 *
 * Requiere `numeric.js`. No depende del navegador: se prueba en Node.
 */

(function (root) {
  'use strict';

  const UX = (root.UX = root.UX || {});
  const { solveSymmetric } = UX.numeric;

  /** Penalizaciones que se prueban al entrenar, de menor a mayor. */
  const DEFAULT_LAMBDAS = [0.1, 1, 10, 100, 1000];
  /** Puntos de calibración distintos que hacen falta para entrenar. */
  const MIN_GROUPS = 4;

  /**
   * Entrena una regresión ridge sobre muestras ya estandarizadas.
   *
   * @param {number[][]} rows - Características de cada muestra.
   * @param {number[][]} targets - Punto `[x, y]` de cada muestra.
   * @param {number} lambda - Penalización.
   * @returns {{weights: number[][], bias: number[]}} Pesos (n × 2) y término independiente.
   */
  function trainRidge(rows, targets, lambda) {
    const n = rows[0].length;
    const bias = [0, 1].map((axis) => targets.reduce((sum, t) => sum + t[axis], 0) / targets.length);
    const xtx = Array.from({ length: n }, () => new Float64Array(n));
    const xty = Array.from({ length: n }, () => [0, 0]);
    rows.forEach((row, index) => {
      const ty = [targets[index][0] - bias[0], targets[index][1] - bias[1]];
      for (let i = 0; i < n; i += 1) {
        const ri = row[i];
        if (ri === 0) {
          continue;
        }
        xty[i][0] += ri * ty[0];
        xty[i][1] += ri * ty[1];
        for (let j = 0; j <= i; j += 1) {
          xtx[i][j] += ri * row[j];
        }
      }
    });
    const a = xtx.map((row, i) => {
      const full = new Array(n);
      for (let j = 0; j < n; j += 1) {
        full[j] = j <= i ? row[j] : xtx[j][i];
      }
      full[i] += lambda;
      return full;
    });
    return { weights: solveSymmetric(a, xty), bias };
  }

  /** Aplica pesos entrenados a una fila estandarizada. */
  function applyRidge({ weights, bias }, row) {
    let x = bias[0];
    let y = bias[1];
    for (let i = 0; i < row.length; i += 1) {
      x += row[i] * weights[i][0];
      y += row[i] * weights[i][1];
    }
    return { x, y };
  }

  /** Media y desviación de cada columna; una columna constante queda con desviación 1. */
  function columnStats(rows) {
    const n = rows[0].length;
    const mean = new Array(n).fill(0);
    const std = new Array(n).fill(0);
    rows.forEach((row) => row.forEach((value, i) => (mean[i] += value)));
    mean.forEach((_, i) => (mean[i] /= rows.length));
    rows.forEach((row) => row.forEach((value, i) => (std[i] += (value - mean[i]) ** 2)));
    std.forEach((value, i) => {
      const s = Math.sqrt(value / rows.length);
      std[i] = s > 1e-9 ? s : 1;
    });
    return { mean, std };
  }

  /** Estandariza una fila con la media y la desviación del entrenamiento. */
  const standardize = (row, { mean, std }) => row.map((value, i) => (value - mean[i]) / std[i]);

  /**
   * Crea un modelo de mirada vacío.
   *
   * @param {object} [options] - Opciones.
   * @param {number[]} [options.lambdas] - Penalizaciones candidatas.
   * @returns {object} Modelo con `add`, `clear`, `fit`, `predict`, `count` e `isFitted`.
   */
  function createGazeModel({ lambdas = DEFAULT_LAMBDAS } = {}) {
    let samples = [];
    let fitted = null;

    /** Error medio, en píxeles, de entrenar sin cada grupo y predecirlo. */
    function crossValidate(groups, lambda) {
      let total = 0;
      let count = 0;
      for (const left of groups) {
        const train = samples.filter((s) => s.group !== left);
        const test = samples.filter((s) => s.group === left);
        const stats = columnStats(train.map((s) => s.features));
        const model = trainRidge(
          train.map((s) => standardize(s.features, stats)),
          train.map((s) => [s.x, s.y]),
          lambda,
        );
        for (const s of test) {
          const p = applyRidge(model, standardize(s.features, stats));
          total += Math.hypot(p.x - s.x, p.y - s.y);
          count += 1;
        }
      }
      return total / count;
    }

    return Object.freeze({
      /**
       * Agrega una muestra de entrenamiento.
       *
       * @param {number[]} features - Características del cuadro.
       * @param {number} x - Punto mirado, en la ventana.
       * @param {number} y - Punto mirado, en la ventana.
       * @param {number} group - Punto de calibración al que pertenece (para la validación cruzada).
       * @returns {void}
       */
      add(features, x, y, group) {
        if (samples.length > 0 && features.length !== samples[0].features.length) {
          throw new Error('all samples must have the same number of features');
        }
        samples.push({ features: Array.from(features), x, y, group });
      },

      /**
       * Borra las muestras y el modelo entrenado.
       *
       * @returns {void}
       */
      clear() {
        samples = [];
        fitted = null;
      },

      /**
       * Entrena con las muestras acumuladas.
       *
       * @returns {{ok: boolean, samples: number, groups: number, lambda: (number|null),
       *   cv_error_px: (number|null)}} Resultado; `ok` es falso si faltan puntos.
       */
      fit() {
        const groups = [...new Set(samples.map((s) => s.group))];
        const summary = { samples: samples.length, groups: groups.length };
        if (groups.length < MIN_GROUPS) {
          fitted = null;
          return { ok: false, ...summary, lambda: null, cv_error_px: null };
        }
        let best = { lambda: lambdas[0], error: Infinity };
        for (const lambda of lambdas) {
          const error = crossValidate(groups, lambda);
          if (error < best.error) {
            best = { lambda, error };
          }
        }
        const stats = columnStats(samples.map((s) => s.features));
        const model = trainRidge(
          samples.map((s) => standardize(s.features, stats)),
          samples.map((s) => [s.x, s.y]),
          best.lambda,
        );
        fitted = { stats, model };
        return { ok: true, ...summary, lambda: best.lambda, cv_error_px: best.error };
      },

      /**
       * Estima el punto mirado.
       *
       * @param {number[]} features - Características del cuadro.
       * @returns {({x: number, y: number}|null)} Punto en la ventana, o `null` si no hay modelo.
       */
      predict(features) {
        if (fitted === null) {
          return null;
        }
        return applyRidge(fitted.model, standardize(Array.from(features), fitted.stats));
      },

      /** @returns {number} Muestras acumuladas. */
      count: () => samples.length,

      /** @returns {boolean} Si hay un modelo entrenado. */
      isFitted: () => fitted !== null,
    });
  }

  UX.createGazeModel = createGazeModel;
  UX.ridge = Object.freeze({ trainRidge, applyRidge, columnStats, standardize, DEFAULT_LAMBDAS });
})(globalThis);
