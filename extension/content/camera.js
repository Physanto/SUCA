/**
 * @file Cámara (M3): estima la mirada y registra los movimientos faciales con
 * una sola fuente de video, sin guardar ni enviar nunca imágenes.
 *
 * Responsabilidad:
 * - abrir la webcam una sola vez y alimentar con el mismo video a la mirada
 *   (`GazeProvider`, ~`camera.gaze_hz`) y al rostro (`FaceProvider`, ~`camera.face_hz`);
 * - asociar cada punto de mirada al elemento y a la zona de la página;
 * - registrar los intervalos sin datos de cámara.
 *
 * Mensajes:
 * - Envía: `camera.status` al panel lateral (`active`, `no_permission` o
 *   `error`), al iniciar y cada vez que cambia; lotes `gaze`, `face` y eventos
 *   `camera_gap` (lote `events`) con `ctx.batcher.add`.
 * - Recibe: ninguno propio. Arranca y se detiene con la sesión, a través del
 *   ciclo de vida de los módulos.
 *
 * Esqueleto: todavía no tiene lógica.
 */

(function (root) {
  'use strict';

  root.UX.modules.register({
    name: 'camera',

    /**
     * Abrirá la cámara y empezará el muestreo. Lo que tarda (pedir permiso) debe
     * seguir en segundo plano e informarse con `camera.status`.
     *
     * @param {object} ctx - Contexto del módulo.
     * @returns {void}
     */
    start(ctx) {},

    /**
     * Cerrará la cámara y entregará lo pendiente.
     *
     * @returns {void}
     */
    stop() {},
  });
})(globalThis);
