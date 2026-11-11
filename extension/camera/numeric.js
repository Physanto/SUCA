/**
 * @file Álgebra numérica que comparten los estimadores de mirada: sistemas
 * simétricos, mínimos cuadrados no lineales (Levenberg-Marquardt), mediana y
 * percentiles.
 *
 * Funciones puras, sin dependencias del navegador: se prueban en Node.
 */

(function (root) {
  'use strict';

  const UX = (root.UX = root.UX || {});

  /**
   * Resuelve `A · X = B` para una matriz simétrica definida positiva, con la
   * descomposición de Cholesky. `A` es n × n y `B` es n × k.
   *
   * @param {number[][]} a - Matriz del sistema; no se modifica.
   * @param {number[][]} b - Lados derechos, una columna por salida.
   * @returns {number[][]} Solución, n × k.
   * @throws {Error} Si la matriz no es definida positiva.
   */
  function solveSymmetric(a, b) {
    const n = a.length;
    const l = Array.from({ length: n }, () => new Float64Array(n));
    for (let i = 0; i < n; i += 1) {
      for (let j = 0; j <= i; j += 1) {
        let sum = a[i][j];
        for (let k = 0; k < j; k += 1) {
          sum -= l[i][k] * l[j][k];
        }
        if (i === j) {
          if (sum <= 0) {
            throw new Error('matrix is not positive definite');
          }
          l[i][i] = Math.sqrt(sum);
        } else {
          l[i][j] = sum / l[j][j];
        }
      }
    }
    const k = b[0].length;
    const x = Array.from({ length: n }, () => new Float64Array(k));
    for (let col = 0; col < k; col += 1) {
      // Sustitución hacia adelante (L · y = b) y hacia atrás (Lᵀ · x = y).
      const y = new Float64Array(n);
      for (let i = 0; i < n; i += 1) {
        let sum = b[i][col];
        for (let j = 0; j < i; j += 1) {
          sum -= l[i][j] * y[j];
        }
        y[i] = sum / l[i][i];
      }
      for (let i = n - 1; i >= 0; i -= 1) {
        let sum = y[i];
        for (let j = i + 1; j < n; j += 1) {
          sum -= l[j][i] * x[j][col];
        }
        x[i][col] = sum / l[i][i];
      }
    }
    return x.map((row) => Array.from(row));
  }

  /** Suma de cuadrados de un vector. */
  const sumOfSquares = (values) => values.reduce((sum, value) => sum + value * value, 0);

  /**
   * Minimiza la suma de cuadrados de un vector de residuos con el método de
   * Levenberg-Marquardt, con el jacobiano por diferencias finitas.
   *
   * @param {function(number[]): number[]} residuals - Residuos para unos parámetros;
   *   siempre del mismo largo.
   * @param {number[]} initial - Parámetros iniciales.
   * @param {object} [options] - Opciones.
   * @param {number} [options.iterations=60] - Máximo de iteraciones.
   * @param {number} [options.tolerance=1e-9] - Mejora relativa mínima para seguir.
   * @returns {{params: number[], cost: number, iterations: number}} Parámetros
   *   ajustados y suma de cuadrados final.
   */
  function levenbergMarquardt(residuals, initial, { iterations = 60, tolerance = 1e-9 } = {}) {
    let params = [...initial];
    let current = residuals(params);
    let cost = sumOfSquares(current);
    let damping = 1e-3;
    const n = params.length;
    let done = 0;
    for (; done < iterations; done += 1) {
      // Jacobiano por diferencias hacia adelante, columna por parámetro.
      const columns = params.map((value, j) => {
        const step = 1e-6 * Math.max(1, Math.abs(value));
        const shifted = [...params];
        shifted[j] = value + step;
        const moved = residuals(shifted);
        return moved.map((r, i) => (r - current[i]) / step);
      });
      const jtj = Array.from({ length: n }, (_, i) =>
        Array.from({ length: n }, (__, j) => columns[i].reduce((sum, v, row) => sum + v * columns[j][row], 0)),
      );
      const jtr = columns.map((column) => [column.reduce((sum, v, row) => sum + v * current[row], 0)]);
      let improved = false;
      // Si el paso empeora, se amortigua más y se prueba de nuevo.
      for (let attempt = 0; attempt < 10; attempt += 1) {
        const damped = jtj.map((row, i) => row.map((v, j) => (i === j ? v + damping * (v || 1) : v)));
        let delta;
        try {
          delta = solveSymmetric(damped, jtr).map((row) => -row[0]);
        } catch (error) {
          damping *= 10;
          continue;
        }
        const candidate = params.map((value, i) => value + delta[i]);
        const next = residuals(candidate);
        const nextCost = sumOfSquares(next);
        if (Number.isFinite(nextCost) && nextCost < cost) {
          const gain = (cost - nextCost) / Math.max(cost, 1e-300);
          params = candidate;
          current = next;
          cost = nextCost;
          damping = Math.max(damping / 10, 1e-12);
          improved = true;
          if (gain < tolerance) {
            return { params, cost, iterations: done + 1 };
          }
          break;
        }
        damping *= 10;
      }
      if (!improved) {
        break;
      }
    }
    return { params, cost, iterations: done };
  }

  /** Mediana de una lista de números, o `null` si está vacía. */
  function median(values) {
    return percentile(values, 0.5);
  }

  /**
   * Percentil de una lista de números, interpolando entre los dos más cercanos.
   *
   * @param {number[]} values - Valores.
   * @param {number} fraction - Entre 0 y 1 (0,5 es la mediana).
   * @returns {(number|null)} Percentil, o `null` si la lista está vacía.
   */
  function percentile(values, fraction) {
    if (values.length === 0) {
      return null;
    }
    const sorted = [...values].sort((a, b) => a - b);
    const position = (sorted.length - 1) * fraction;
    const low = Math.floor(position);
    const high = Math.ceil(position);
    return sorted[low] + (sorted[high] - sorted[low]) * (position - low);
  }

  UX.numeric = Object.freeze({ solveSymmetric, levenbergMarquardt, median, percentile });
})(globalThis);
