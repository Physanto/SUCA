/**
 * @file Estimador de mirada combinado: entrena varios estimadores con las mismas
 * muestras de calibración. Con pose y ambos modelos entrenados combina sus
 * puntos: la apariencia pesa cerca de la postura calibrada y pierde peso al
 * alejarse. Sin pose conserva la selección por validación cruzada.
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
   * @param {object} [options] - Modo de combinación y límites de extrapolación de la pose.
   * @param {number} [options.headMarginDeg=12] - Margen fuera de los ángulos calibrados.
   * @param {boolean} [options.hybrid=true] - Si combina geométrico y apariencia según la
   *   postura. En `false` usa siempre el candidato de menor error de validación cruzada.
   * @returns {object} Estimador con `add`, `clear`, `fit`, `predict`, `isFitted` y `chosen`.
   */
  function createGazeEstimator(candidates, { headMarginDeg = 12, hybrid: allowHybrid = true } = {}) {
    const names = Object.keys(candidates);
    if (names.length === 0) {
      throw new Error('the gaze estimator needs at least one candidate');
    }
    let chosen = null;
    let usable = [];
    let poses = [];
    let poseRange = null;
    let hybrid = false;
    let appearanceWeight = 0;

    /** Pose válida; la ausencia de pose conserva la selección convencional por error. */
    function poseOf(features) {
      const pose = features.geometric;
      return pose && ['yaw', 'pitch', 'distance'].every(key => Number.isFinite(pose[key])) ? pose : null;
    }

    /** Limita la extrapolación angular; el monitor sigue evaluando la pose original. */
    function geometricPoint(features) {
      if (!poseRange || !features.geometric) return candidates.geometric.predict(features.geometric);
      const bounded = { ...features.geometric };
      for (const key of ['yaw', 'pitch']) {
        bounded[key] = Math.max(poseRange[key].low - headMarginDeg,
          Math.min(poseRange[key].high + headMarginDeg, bounded[key]));
      }
      return candidates.geometric.predict(bounded);
    }

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
        const pose = poseOf(features);
        if (pose) poses.push({ yaw: pose.yaw, pitch: pose.pitch, distance: pose.distance });
        for (const name of names) {
          if (features[name] !== null && features[name] !== undefined) {
            candidates[name].add(features[name], x, y, group);
          }
        }
      },

      /**
       * Pasa los datos de la pantalla a los candidatos que los usan (el geométrico).
       *
       * @param {{cssPxPerCm: number}} screen - Píxeles CSS por centímetro de la pantalla.
       * @returns {void}
       */
      configure(screen) {
        for (const name of names) {
          if (typeof candidates[name].configure === 'function') {
            candidates[name].configure(screen);
          }
        }
      },

      /** Borra las muestras y los modelos de todos los candidatos. */
      clear() {
        names.forEach((name) => candidates[name].clear());
        chosen = null;
        usable = [];
        poses = [];
        poseRange = null;
        hybrid = false;
      },

      /**
       * Entrena candidatos y prepara la combinación si hay pose de calibración.
       *
       * @param {object} context - Datos de la calibración que algunos candidatos usan (`viewport`).
       * @returns {object} Resultado del elegido (`ok`, `samples`, `groups`, `lambda`,
       *   `cv_error_px`), con `estimator` y errores de cada candidato (`candidates`).
       *   En modo híbrido `cv_error_px` es nulo: aún no se midió la combinación fuera de muestra.
       */
      fit(context) {
        const results = Object.fromEntries(names.map((name) => [name, candidates[name].fit(context)]));
        usable = names.filter((name) => results[name].ok && Number.isFinite(results[name].cv_error_px));
        hybrid = false;
        poseRange = null;
        if (usable.length === 0) {
          chosen = null;
          const first = results[names[0]];
          return { ...first, ok: false, estimator: null, candidates: errorsOf(results) };
        }
        chosen = usable.reduce((best, name) => (results[name].cv_error_px < results[best].cv_error_px ? name : best));
        if (poses.length) {
          poseRange = Object.fromEntries(['yaw', 'pitch', 'distance'].map(key => {
            const values = poses.map(pose => pose[key]).sort((a, b) => a - b);
            const quantile = p => values[Math.round((values.length - 1) * p)];
            return [key, { center: quantile(.5), low: values[0], high: values.at(-1),
              scale: Math.max(1, (quantile(.9) - quantile(.1)) / 2) }];
          }));
          hybrid = allowHybrid && usable.includes('geometric') && usable.includes('appearance');
          if (hybrid) {
            const geoError = Math.max(1, results.geometric.cv_error_px);
            const appError = Math.max(1, results.appearance.cv_error_px);
            appearanceWeight = geoError ** 2 / (geoError ** 2 + appError ** 2);
          }
        }
        // La validación cruzada de los candidatos no mide el error de su combinación.
        return { ...results[chosen], estimator: hybrid ? 'hybrid' : chosen,
          cv_error_px: hybrid ? null : results[chosen].cv_error_px, candidates: errorsOf(results) };
      },

      /**
       * Estima el punto combinando según postura, o con el candidato elegido.
       *
       * @param {Object<string, *>} features - Características por candidato.
       * @returns {({x: number, y: number}|null)} Punto, o `null` sin modelo o sin sus características.
       */
      predict(features) {
        if (hybrid) {
          const pose = poseOf(features);
          if (!pose) return null;
          const geometric = geometricPoint(features);
          const appearance = features.appearance == null ? null : candidates.appearance.predict(features.appearance);
          if (!geometric) return null;
          if (!appearance) return geometric;
          const change = ['yaw', 'pitch', 'distance'].reduce((sum, key) =>
            sum + ((pose[key] - poseRange[key].center) / poseRange[key].scale) ** 2, 0);
          const weight = appearanceWeight * Math.exp(-change / 2);
          return { x: weight * appearance.x + (1 - weight) * geometric.x,
            y: weight * appearance.y + (1 - weight) * geometric.y };
        }
        if (chosen === null || features[chosen] === null || features[chosen] === undefined) {
          return null;
        }
        return chosen === 'geometric' && poseRange ? geometricPoint(features)
          : candidates[chosen].predict(features[chosen]);
      },

      /** @returns {boolean} Si hay un candidato elegido. */
      isFitted: () => chosen !== null,

      /** @returns {(string|null)} Nombre del candidato elegido. */
      chosen: () => hybrid ? 'hybrid' : chosen,
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
