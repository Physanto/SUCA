/**
 * @file Estimador de mirada combinado: entrena varios estimadores con las mismas
 * muestras de calibración y usa el que menos se equivoca en la validación
 * cruzada (Strategy + Registry).
 *
 * Los candidatos son el geométrico (`gaze-geometry.js`) y el de apariencia
 * (`gaze-model.js`). El geométrico suele ganar cuando la persona se mueve; el de
 * apariencia puede ganar si la estimación de la pose falla (por ejemplo, con
 * una webcam muy distinta a la que supone MediaPipe). Elegirlo con datos de la
 * propia sesión evita depender de una sola suposición.
 *
 * Cada cuadro trae un objeto de características con una entrada por candidato
 * (`{ geometric: {...}, appearance: [...] }`); cada candidato usa la suya.
 *
 * Se prueba en Node.
 */

(function (root) {
  'use strict';

  const UX = (root.UX = root.UX || {});

  /**
   * Crea el estimador combinado.
   *
   * @param {Object<string, object>} candidates - Estimadores por nombre (`gaze_estimator` del
   *   contrato). Cada uno tiene `add`, `clear`, `fit`, `predict` e `isFitted`.
   * @returns {object} Estimador con `add`, `clear`, `fit`, `predict`, `isFitted` y `chosen`.
   */
  function createGazeEstimator(candidates) {
    const names = Object.keys(candidates);
    if (names.length === 0) {
      throw new Error('the gaze estimator needs at least one candidate');
    }
    let chosen = null;

    return Object.freeze({
      /**
       * Agrega una muestra a cada candidato que tenga sus características en el cuadro.
       *
       * @param {Object<string, *>} features - Características por candidato.
       * @param {number} x - Punto mirado.
       * @param {number} y - Punto mirado.
       * @param {*} group - Objetivo de calibración.
       * @returns {void}
       */
      add(features, x, y, group) {
        for (const name of names) {
          if (features[name] !== null && features[name] !== undefined) {
            candidates[name].add(features[name], x, y, group);
          }
        }
      },

      /** Borra las muestras y los modelos de todos los candidatos. */
      clear() {
        names.forEach((name) => candidates[name].clear());
        chosen = null;
      },

      /**
       * Entrena todos los candidatos y elige el de menor error en validación cruzada.
       *
       * @param {object} context - Datos de la calibración que algunos candidatos usan (`viewport`).
       * @returns {object} Resultado del elegido (`ok`, `samples`, `groups`, `lambda`,
       *   `cv_error_px`), con `estimator` y el error de cada candidato (`candidates`).
       */
      fit(context) {
        const results = Object.fromEntries(names.map((name) => [name, candidates[name].fit(context)]));
        const usable = names.filter((name) => results[name].ok && Number.isFinite(results[name].cv_error_px));
        if (usable.length === 0) {
          chosen = null;
          const first = results[names[0]];
          return { ...first, ok: false, estimator: null, candidates: errorsOf(results) };
        }
        chosen = usable.reduce((best, name) => (results[name].cv_error_px < results[best].cv_error_px ? name : best));
        return { ...results[chosen], estimator: chosen, candidates: errorsOf(results) };
      },

      /**
       * Estima el punto mirado con el candidato elegido.
       *
       * @param {Object<string, *>} features - Características por candidato.
       * @returns {({x: number, y: number}|null)} Punto, o `null` sin modelo o sin sus características.
       */
      predict(features) {
        if (chosen === null || features[chosen] === null || features[chosen] === undefined) {
          return null;
        }
        return candidates[chosen].predict(features[chosen]);
      },

      /** @returns {boolean} Si hay un candidato elegido. */
      isFitted: () => chosen !== null,

      /** @returns {(string|null)} Nombre del candidato elegido. */
      chosen: () => chosen,
    });
  }

  /** Error de validación cruzada de cada candidato, o `null` si no entrenó. */
  function errorsOf(results) {
    return Object.fromEntries(
      Object.entries(results).map(([name, result]) => [name, result.ok ? result.cv_error_px : null]),
    );
  }

  UX.createGazeEstimator = createGazeEstimator;
})(globalThis);
