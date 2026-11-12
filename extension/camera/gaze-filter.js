/**
 * @file Filtro temporal de la mirada: filtro One Euro (Casiez, Roussel y Vogel, 2012).
 *
 * Suaviza mucho cuando el punto está quieto (una fijación, donde el temblor es
 * ruido) y casi nada cuando se mueve rápido (un salto de la mirada, que debe
 * seguirse enseguida). Reemplaza a una media exponencial de peso fijo, que
 * retrasaba los saltos y arrastraba el punto entre zonas.
 *
 * Funciones puras: se prueban en Node.
 */

(function (root) {
  'use strict';

  const UX = (root.UX = root.UX || {});

  /** Peso del valor nuevo en un pasa bajos de primer orden con una frecuencia de corte. */
  const alpha = (cutoffHz, dtSeconds) => {
    const tau = 1 / (2 * Math.PI * cutoffHz);
    return 1 / (1 + tau / dtSeconds);
  };

  /**
   * Crea un filtro One Euro para puntos 2D. La velocidad se mide en el plano, así
   * los dos ejes se suavizan igual.
   *
   * @param {object} options - Parámetros.
   * @param {number} options.minCutoff - Corte mínimo, en Hz: más bajo suaviza más las fijaciones.
   * @param {number} options.beta - Cuánto sube el corte por cada píxel por segundo de velocidad.
   * @param {number} [options.derivativeCutoff=1] - Corte del pasa bajos de la velocidad, en Hz.
   * @returns {{next: function(number, {x: number, y: number}): {x: number, y: number}, reset: function(): void}}
   *   Filtro: `next(t, punto)` con `t` en milisegundos.
   */
  function createOneEuroFilter({ minCutoff, beta, derivativeCutoff = 1 }) {
    if (!(minCutoff > 0) || !(beta >= 0)) {
      throw new Error(`invalid One Euro parameters: minCutoff ${minCutoff}, beta ${beta}`);
    }
    let last = null;

    return Object.freeze({
      next(t, point) {
        if (last === null || !(t > last.t)) {
          last = { t, x: point.x, y: point.y, vx: 0, vy: 0 };
          return { x: point.x, y: point.y };
        }
        const dt = (t - last.t) / 1000;
        // La velocidad se filtra con signo, por eje: el temblor de una fijación va y
        // vuelve y se cancela; un salto de la mirada no.
        const ad = alpha(derivativeCutoff, dt);
        const vx = last.vx + ad * ((point.x - last.x) / dt - last.vx);
        const vy = last.vy + ad * ((point.y - last.y) / dt - last.vy);
        const a = alpha(minCutoff + beta * Math.hypot(vx, vy), dt);
        last = { t, x: last.x + a * (point.x - last.x), y: last.y + a * (point.y - last.y), vx, vy };
        return { x: last.x, y: last.y };
      },

      reset() {
        last = null;
      },
    });
  }

  UX.createOneEuroFilter = createOneEuroFilter;
})(globalThis);
