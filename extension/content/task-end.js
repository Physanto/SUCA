/**
 * @file Fin de tarea (M2): en el modo guiado, revisa si la página llegó a la
 * condición final de la referencia de la tarea activa.
 *
 * La condición (`visible_text`, `url_pattern` o `element_present`) se revisa en
 * cada cambio de la página o de pantalla, como máximo 4 veces por segundo. Solo
 * revisa la condición final, no los pasos obligatorios: el éxito lo decide el
 * análisis.
 *
 * Mensajes:
 * - Recibe: `task.started` (`task_id`, `end_condition` o `null`) del panel
 *   lateral, vía worker. Con `null` no hay nada que revisar.
 * - Envía: `task.completed` (`task_id`, `ended_by: 'reference'`) al panel
 *   lateral cuando se cumple la condición.
 *
 * Esqueleto: todavía no tiene lógica.
 */

(function (root) {
  'use strict';

  root.UX.modules.register({
    name: 'task_end',

    /**
     * Empezará a escuchar `task.started`.
     *
     * @param {object} ctx - Contexto del módulo.
     * @returns {void}
     */
    start(ctx) {},

    /**
     * Dejará de revisar la condición y de escuchar.
     *
     * @returns {void}
     */
    stop() {},
  });
})(globalThis);
