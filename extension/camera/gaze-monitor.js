/**
 * @file Monitor de la mirada: decide en cada cuadro si la estimación es
 * utilizable y con qué confianza.
 *
 * Estados (`gaze_state` en `contracts/enums.json`):
 * - `no_face`: no se ve el rostro; `uncalibrated`: todavía no hay modelo;
 * - `blink`: ojos cerrados (valor de parpadeo alto o párpados mucho más cerrados
 *   que en la calibración);
 * - `off_screen`: mira fuera de la pantalla (el teclado, el mouse, la habitación):
 *   la cabeza giró bastante más allá de lo visto en la calibración, o el punto
 *   estimado cae lejos de la ventana;
 * - `low_confidence` / `on_screen`: mira la pantalla, con confianza baja o alta.
 *   Baja con el iris sin refinar, con la cabeza fuera del rango calibrado
 *   (dentro del margen) y en los primeros instantes al volver de mirar fuera
 *   (de `off_screen` o `no_face`, aunque en el medio haya un parpadeo).
 *
 * Distinguir "mira el teclado" de "falló la estimación" importa para el
 * análisis, y permite reiniciar el filtro al volver, sin mezclar el teclado con
 * la página.
 *
 * Funciones puras: se prueban en Node.
 */

(function (root) {
  'use strict';

  const UX = (root.UX = root.UX || {});

  /** Tras volver de mirar fuera, la confianza queda baja este tiempo (la sacada de regreso). */
  const RETURN_MS = 150;
  /** Debajo de esta confianza el estado es `low_confidence`. */
  const LOW_CONFIDENCE = 0.7;
  /** Fracción de la apertura de la calibración por debajo de la cual el ojo se considera cerrado. */
  const CLOSED_FRACTION = 0.45;
  /** Factor de confianza según cuántos iris se refinaron (0, 1 o 2). */
  const REFINED_FACTOR = [0.6, 0.85, 1];
  /** Estados en que la persona mira la pantalla. */
  const LOOKING = ['on_screen', 'low_confidence'];
  /** Estados en que la persona dejó de mirar la pantalla. */
  const AWAY = ['off_screen', 'no_face'];

  /**
   * Crea el monitor.
   *
   * @param {object} options - Umbrales de `camera` en la configuración.
   * @param {number} options.blinkThreshold - Parpadeo de MediaPipe desde el que se cuenta.
   * @param {number} options.headMarginDeg - Grados fuera del rango calibrado antes de `off_screen`.
   * @param {number} options.offScreenMarginPx - Píxeles fuera de la ventana antes de `off_screen`.
   * @returns {object} Monitor con `calibrate`, `reset` y `assess`.
   */
  function createGazeMonitor({ blinkThreshold, headMarginDeg, offScreenMarginPx }) {
    let calibration = null;
    /** Si la persona dejó de mirar la pantalla (fuera o sin rostro) y todavía no volvió. */
    let away = false;
    let returnedAt = -Infinity;

    /** Grados que la cabeza está fuera del rango calibrado (0 si está dentro). */
    function headOutside(yaw, pitch) {
      const { yaw: yawRange, pitch: pitchRange } = calibration;
      return Math.max(0, yaw - yawRange[1], yawRange[0] - yaw, pitch - pitchRange[1], pitchRange[0] - pitch);
    }

    /** Si el punto cae lejos de la ventana de la calibración. */
    function farFromViewport(point) {
      const { width, height } = calibration.viewport;
      const m = offScreenMarginPx;
      return point.x < -m || point.y < -m || point.x > width + m || point.y > height + m;
    }

    /**
     * Recuerda si la persona dejó de mirar la pantalla. Un parpadeo no cambia nada:
     * mirar el teclado, parpadear y volver sigue siendo volver.
     */
    function settle(state, confidence) {
      if (AWAY.includes(state)) {
        away = true;
      } else if (LOOKING.includes(state)) {
        away = false;
      }
      return { state, confidence };
    }

    return Object.freeze({
      /**
       * Fija lo que se vio en la calibración.
       *
       * @param {object} range - Rango de giro de la cabeza (`yaw`, `pitch`: `[mín, máx]` en
       *   grados), apertura típica de los ojos (`open`) y ventana (`viewport`).
       * @returns {void}
       */
      calibrate(range) {
        calibration = { ...range };
        away = false;
        returnedAt = -Infinity;
      },

      /** Olvida la calibración y el estado anterior. */
      reset() {
        calibration = null;
        away = false;
        returnedAt = -Infinity;
      },

      /**
       * Evalúa un cuadro.
       *
       * @param {object} frame - Datos del cuadro.
       * @param {number} frame.t - Momento.
       * @param {boolean} frame.face - Si se detectó el rostro.
       * @param {boolean} frame.calibrated - Si hay modelo de mirada.
       * @param {?number} frame.blink - Mayor parpadeo de los dos ojos (0 a 1).
       * @param {?number} frame.open - Apertura media de los ojos.
       * @param {?number} frame.yaw - Giro de la cabeza, en grados.
       * @param {?number} frame.pitch - Inclinación de la cabeza, en grados.
       * @param {number} frame.refined - Iris refinados en el cuadro (0, 1 o 2).
       * @param {?{x: number, y: number}} frame.point - Punto estimado, sin filtrar.
       * @returns {{state: string, confidence: number}} Estado y confianza.
       */
      assess({ t, face, calibrated, blink, open, yaw, pitch, refined, point }) {
        if (!face) {
          return settle('no_face', 0);
        }
        if (!calibrated || calibration === null || point === null) {
          return settle('uncalibrated', 0);
        }
        const closed = calibration.open > 0 && open !== null && open < CLOSED_FRACTION * calibration.open;
        if ((blink !== null && blink >= blinkThreshold) || closed) {
          return settle('blink', 0);
        }
        const outside = headOutside(yaw, pitch);
        if (outside > headMarginDeg || farFromViewport(point)) {
          return settle('off_screen', 0);
        }
        let confidence = REFINED_FACTOR[Math.max(0, Math.min(2, refined))];
        confidence *= 1 - (0.6 * outside) / headMarginDeg;
        if (away) {
          returnedAt = t;
        }
        if (t - returnedAt < RETURN_MS) {
          confidence *= 0.5;
        }
        confidence = Math.round(confidence * 1000) / 1000;
        return settle(confidence < LOW_CONFIDENCE ? 'low_confidence' : 'on_screen', confidence);
      },
    });
  }

  UX.createGazeMonitor = createGazeMonitor;
  UX.gazeMonitorStates = Object.freeze({ LOOKING });
})(globalThis);
