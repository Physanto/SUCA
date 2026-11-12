/**
 * @file Estimador geométrico de mirada: separa lo que hace la cabeza de lo que
 * hace el ojo, para que la mirada siga sirviendo cuando la persona se mueve.
 *
 * Por cada cuadro:
 * 1. El ojo gira dentro de la cabeza en proporción al desplazamiento del iris
 *    (`h`, `v`, en anchos de ojo): `θ = a_h·h + b_h`, `φ = a_v·v + b_v + c·(apertura − referencia)`.
 *    La apertura de los párpados ayuda en vertical, porque al mirar abajo el
 *    párpado tapa parte del iris.
 * 2. La dirección de la mirada suma el giro de la cabeza (de la matriz de
 *    MediaPipe) y el del ojo: `yaw = g_y·yaw_cabeza + θ`, `pitch = g_p·pitch_cabeza + φ`.
 * 3. El rayo sale del punto medio entre los ojos, ubicado en 3D con su posición
 *    en la imagen y la distancia a la cámara, y se corta con el plano de la
 *    pantalla (la cámara está en el borde de la pantalla y mira perpendicular a
 *    ella).
 * 4. El punto de corte, en centímetros desde la cámara, se pasa a píxeles de la
 *    ventana: `x = c_x + k_x·px_por_cm·P_x`, `y = c_y + k_y·px_por_cm·P_y`.
 *
 * Son 11 parámetros por persona con significado físico; se ajustan en la
 * calibración con Levenberg-Marquardt, con valores previos razonables. Encima,
 * una ridge pequeña corrige lo que la geometría no explica, si la validación
 * cruzada dice que ayuda.
 *
 * Como el modelo sabe dónde está la cabeza, inclinarse, acercarse o girar no
 * exige haber calibrado en esa postura. Las mismas cuentas se repiten en
 * Python (`analysis/gaze/model.py`) para reprocesar la sesión.
 *
 * Requiere `numeric.js` y `gaze-model.js` (`UX.ridge`). Se prueba en Node.
 */

(function (root) {
  'use strict';

  const UX = (root.UX = root.UX || {});
  const { levenbergMarquardt, median } = UX.numeric;
  const { trainRidge, applyRidge, columnStats, standardize } = UX.ridge;

  /**
   * Campo de visión vertical que supone MediaPipe para su matriz de pose. La
   * posición de los ojos en 3D se calcula con la misma cámara, para que sea
   * coherente con la distancia que da la matriz.
   */
  const VERTICAL_FOV_DEG = 63;
  const RAD = Math.PI / 180;
  /** Puntos de calibración distintos que hacen falta para entrenar. */
  const MIN_GROUPS = 4;
  /** Escala de los residuos en píxeles: solo pondera los datos frente a los valores previos. */
  const SIGMA_PX = 50;
  /** Distancia típica de la cámara al borde superior de la ventana, en centímetros. */
  const CAMERA_TO_VIEWPORT_CM = 2.5;
  /** Penalizaciones de la ridge del residuo; `null` es "sin residuo". */
  const RESIDUAL_LAMBDAS = [null, 10, 100, 1000];
  /** Nombres de los parámetros, en orden. */
  const PARAMS = ['a_h', 'b_h', 'a_v', 'b_v', 'c_open', 'g_yaw', 'g_pitch', 'c_x', 'c_y', 'k_x', 'k_y'];

  /**
   * Valores previos de los parámetros y cuánto pueden alejarse de ellos.
   *
   * El iris se mueve ~0,4 anchos de ojo por radián de giro del ojo (globo de ~1,2 cm
   * de radio, ojo de ~3 cm de ancho): `a ≈ −2,5`, negativo porque la imagen no está
   * espejada (mirar a la derecha de la persona mueve el iris a la izquierda de la
   * imagen) y porque en la imagen "abajo" es positivo.
   */
  function priors(viewport, cssPxPerCm) {
    return {
      mean: [-2.5, 0, -2.5, 0, 0, 1, 1, viewport.width / 2, -CAMERA_TO_VIEWPORT_CM * cssPxPerCm, 1, 1],
      sigma: [3, 1, 3, 1, 5, 0.5, 0.5, viewport.width, 20 * cssPxPerCm, 0.3, 0.3],
    };
  }

  /**
   * Punto de la ventana que mira un cuadro con unos parámetros.
   *
   * @param {number[]} p - Parámetros, en el orden de `PARAMS`.
   * @param {object} f - Características geométricas del cuadro (`yaw`, `pitch` en grados,
   *   `distance` en cm, `eyeU`, `eyeV`, `aspect`, `h`, `v`, `open`).
   * @param {{cssPxPerCm: number, openRef: number}} context - Píxeles por cm y apertura de referencia.
   * @returns {{x: number, y: number}} Punto en píxeles CSS de la ventana.
   */
  function project(p, f, { cssPxPerCm, openRef }) {
    const theta = p[0] * f.h + p[1];
    const phi = p[2] * f.v + p[3] + p[4] * (f.open - openRef);
    const yaw = p[5] * f.yaw * RAD + theta;
    const pitch = p[6] * f.pitch * RAD + phi;
    const tanV = Math.tan((VERTICAL_FOV_DEG * RAD) / 2);
    const tanH = tanV * f.aspect;
    // Ejes de la pantalla vistos por la persona: x a su derecha (−x de la cámara) e y hacia abajo.
    const oz = f.distance;
    const ox = -(f.eyeU - 0.5) * 2 * tanH * oz;
    const oy = (f.eyeV - 0.5) * 2 * tanV * oz;
    const px = ox + oz * Math.tan(yaw);
    const py = oy - (oz * Math.tan(pitch)) / Math.cos(yaw);
    return { x: p[7] + p[9] * cssPxPerCm * px, y: p[8] + p[10] * cssPxPerCm * py };
  }

  /** Características del residuo: términos de segundo orden del iris, apertura y pose. */
  const residualFeatures = (f, openRef) => [
    f.h,
    f.v,
    f.h * f.h,
    f.v * f.v,
    f.h * f.v,
    f.open - openRef,
    f.yaw,
    f.pitch,
    f.distance,
  ];

  /**
   * Ajusta los parámetros geométricos a unas muestras. Cada punto de calibración
   * pesa lo mismo, tenga los cuadros que tenga.
   *
   * @param {Array<{f: object, x: number, y: number, group: *}>} samples - Muestras.
   * @param {object} context - `cssPxPerCm`, `openRef` y valores previos (`prior`).
   * @param {number[]} initial - Parámetros iniciales.
   * @returns {number[]} Parámetros ajustados.
   */
  function fitParams(samples, context, initial) {
    const counts = new Map();
    samples.forEach((s) => counts.set(s.group, (counts.get(s.group) || 0) + 1));
    const weights = samples.map((s) => Math.sqrt(1 / (counts.get(s.group) * counts.size)) / SIGMA_PX);
    const { mean, sigma } = context.prior;
    const residuals = (p) => {
      const out = [];
      samples.forEach((s, i) => {
        const q = project(p, s.f, context);
        out.push(weights[i] * (q.x - s.x), weights[i] * (q.y - s.y));
      });
      p.forEach((value, j) => out.push((value - mean[j]) / sigma[j]));
      return out;
    };
    return levenbergMarquardt(residuals, initial).params;
  }

  /** Entrena la ridge del residuo; `null` si `lambda` es `null`. */
  function fitResidual(samples, params, context, lambda) {
    if (lambda === null) {
      return null;
    }
    const rows = samples.map((s) => residualFeatures(s.f, context.openRef));
    const stats = columnStats(rows);
    const targets = samples.map((s) => {
      const q = project(params, s.f, context);
      return [s.x - q.x, s.y - q.y];
    });
    return { stats, model: trainRidge(rows.map((row) => standardize(row, stats)), targets, lambda) };
  }

  /** Predicción completa: geometría más residuo. */
  function predictWith(fitted, f) {
    const q = project(fitted.params, f, fitted.context);
    if (fitted.residual === null) {
      return q;
    }
    const r = applyRidge(fitted.residual.model, standardize(residualFeatures(f, fitted.context.openRef), fitted.residual.stats));
    return { x: q.x + r.x, y: q.y + r.y };
  }

  /**
   * Crea un estimador geométrico vacío. Tiene la misma forma que el de apariencia
   * (`createGazeModel`), así el estimador combinado los trata igual.
   *
   * @param {object} options - Opciones.
   * @param {number} options.cssPxPerCm - Píxeles CSS por centímetro de la pantalla.
   * @returns {object} Estimador con `configure`, `add`, `clear`, `fit`, `predict`, `count`,
   *   `isFitted` y `params`.
   */
  function createGeometricModel({ cssPxPerCm }) {
    /** Falla si los píxeles por centímetro no son un número positivo. */
    function checked(value) {
      if (!(value > 0)) {
        throw new Error(`cssPxPerCm must be positive, got ${value}`);
      }
      return value;
    }
    // Puede cambiar entre calibraciones: cada equipo tiene su pantalla (`common/screen-setup.js`).
    let pxPerCm = checked(cssPxPerCm);
    let samples = [];
    let fitted = null;

    return Object.freeze({
      /**
       * Cambia la pantalla para el próximo ajuste. El modelo ya ajustado conserva
       * la suya hasta que se ajuste de nuevo.
       *
       * @param {{cssPxPerCm: number}} screen - Píxeles CSS por centímetro de la pantalla.
       * @returns {void}
       */
      configure({ cssPxPerCm: value }) {
        pxPerCm = checked(value);
      },

      /**
       * Agrega una muestra de entrenamiento.
       *
       * @param {object} f - Características geométricas del cuadro.
       * @param {number} x - Punto mirado, en la ventana.
       * @param {number} y - Punto mirado, en la ventana.
       * @param {*} group - Objetivo al que pertenece (para la validación cruzada).
       * @returns {void}
       */
      add(f, x, y, group) {
        samples.push({ f: { ...f }, x, y, group });
      },

      /** Borra las muestras y el modelo. */
      clear() {
        samples = [];
        fitted = null;
      },

      /**
       * Ajusta el modelo y elige, por validación cruzada dejando fuera un
       * objetivo a la vez, si suma la corrección del residuo y con qué penalización.
       *
       * @param {{viewport: {width: number, height: number}}} options - Ventana de la calibración.
       * @returns {{ok: boolean, samples: number, groups: number, lambda: (number|null),
       *   cv_error_px: (number|null)}} Resultado.
       */
      fit({ viewport }) {
        const groups = [...new Set(samples.map((s) => s.group))];
        const summary = { samples: samples.length, groups: groups.length };
        if (groups.length < MIN_GROUPS) {
          fitted = null;
          return { ok: false, ...summary, lambda: null, cv_error_px: null };
        }
        const prior = priors(viewport, pxPerCm);
        const context = { cssPxPerCm: pxPerCm, openRef: median(samples.map((s) => s.f.open)), prior };
        const params = fitParams(samples, context, prior.mean);
        // Error de cada opción de residuo, promediando cada objetivo dejado fuera por igual.
        const errors = RESIDUAL_LAMBDAS.map(() => 0);
        for (const left of groups) {
          const train = samples.filter((s) => s.group !== left);
          const test = samples.filter((s) => s.group === left);
          const foldParams = fitParams(train, context, params);
          RESIDUAL_LAMBDAS.forEach((lambda, k) => {
            const fold = { params: foldParams, context, residual: fitResidual(train, foldParams, context, lambda) };
            const error = test.reduce((sum, s) => {
              const q = predictWith(fold, s.f);
              return sum + Math.hypot(q.x - s.x, q.y - s.y);
            }, 0);
            errors[k] += error / test.length / groups.length;
          });
        }
        const best = errors.indexOf(Math.min(...errors));
        const lambda = RESIDUAL_LAMBDAS[best];
        fitted = { params, context, residual: fitResidual(samples, params, context, lambda) };
        return { ok: true, ...summary, lambda, cv_error_px: errors[best] };
      },

      /**
       * Estima el punto mirado.
       *
       * @param {object} f - Características geométricas del cuadro.
       * @returns {({x: number, y: number}|null)} Punto en la ventana, o `null` sin modelo.
       */
      predict(f) {
        if (fitted === null) {
          return null;
        }
        const q = predictWith(fitted, f);
        return Number.isFinite(q.x) && Number.isFinite(q.y) ? q : null;
      },

      /** @returns {number} Muestras acumuladas. */
      count: () => samples.length,

      /** @returns {boolean} Si hay un modelo entrenado. */
      isFitted: () => fitted !== null,

      /** @returns {(object|null)} Parámetros ajustados por nombre, para las estadísticas. */
      params: () =>
        fitted === null ? null : Object.fromEntries(PARAMS.map((name, i) => [name, fitted.params[i]])),
    });
  }

  UX.createGeometricModel = createGeometricModel;
  UX.gazeGeometry = Object.freeze({ project, VERTICAL_FOV_DEG, PARAMS });
})(globalThis);
