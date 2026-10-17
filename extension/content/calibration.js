/**
 * @file Calibración de la mirada (M3): muestra una capa sobre la página con 9
 * puntos de calibración y 5 de validación, y mide el error resultante.
 *
 * Mensajes:
 * - Recibe: `calibration.request` (`type`: `initial` o `final`) del panel
 *   lateral, vía worker.
 * - Envía: `calibration.result` (`error_px`, `error_deg`, `accepted`) al panel
 *   lateral, y el mismo resultado al servidor en un lote `calibration` con
 *   `ctx.batcher.add`.
 *
 * Esqueleto: todavía no tiene lógica.
 */

(function (root) {
  'use strict';

  root.UX.modules.register({
    name: 'calibration',

    /**
     * Empezará a escuchar `calibration.request`.
     *
     * @param {object} ctx - Contexto del módulo.
     * @returns {void}
     */
    start(ctx) {},

    /**
     * Quitará la capa si está visible y dejará de escuchar.
     *
     * @returns {void}
     */
    stop() {},
  });
})(globalThis);
