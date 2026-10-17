/**
 * @file Reloj común de la extensión. Todas las partes marcan sus datos con el
 * mismo reloj, en milisegundos desde 1970, para que eventos, mirada y rostro
 * queden en una sola línea de tiempo.
 */

(function (root) {
  'use strict';

  const UX = (root.UX = root.UX || {});

  /**
   * Crea un reloj sobre la API `performance`.
   *
   * `performance.timeOrigin + performance.now()` tiene resolución de
   * submilisegundos y no salta si el usuario cambia la hora del sistema.
   *
   * @param {{timeOrigin: number, now: function(): number}} performanceApi - API `performance`.
   * @returns {{now: function(): number}} Reloj.
   */
  function createClock(performanceApi) {
    return Object.freeze({
      /**
       * Devuelve el momento actual.
       *
       * @returns {number} Milisegundos desde 1970.
       */
      now: () => performanceApi.timeOrigin + performanceApi.now(),
    });
  }

  UX.createClock = createClock;
  UX.clock = createClock(root.performance);
})(globalThis);
