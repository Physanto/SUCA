/**
 * @file Calibración de la mirada (M3): una capa sobre la página con puntos que el
 * participante mira, para entrenar el estimador de mirada del motor y medir su error.
 *
 * Procedimientos (`calibration_type`):
 * - **Inicial** (`initial`), poco más de un minuto, en tres partes:
 *   1. 13 puntos fijos (cuadrícula de 3 × 3 y cuatro intermedios): el participante
 *      mira cada uno y hace clic; los cuadros alrededor del clic entrenan el modelo.
 *   2. Un punto en movimiento que sigue con la vista (12 s): da muestras por toda
 *      la pantalla y, con el desfase que mejor alinea la mirada con el punto, el
 *      retraso de la cámara (`camera_delay_ms`).
 *   3. El punto central fijo mientras mueve la cabeza (8 s): separa el giro de la
 *      cabeza del giro del ojo, para que la mirada siga sirviendo cuando se mueve.
 *   Después, la validación.
 * - **Final** (`final`): solo la validación, con el modelo de la inicial, para
 *   estimar cuánto se degradó durante la sesión.
 * - **Comprobación de deriva** (`drift_check`): tres puntos con clic, unos
 *   segundos; el motor mide el error y, si `camera.drift_correction` lo pide y el
 *   error supera `camera.drift_correction_min_error_deg`, corrige la mirada. El
 *   panel la pide entre tareas.
 *
 * **Validación:** 8 puntos sin clic y un noveno al volver de mirar el teclado (la
 * capa espera a que el monitor note la salida y la vuelta). Da el error medio
 * (`error_px`, `error_deg`), la precisión (`precision_deg`: temblor entre muestras
 * consecutivas) y el error al volver (`return_error_deg`). El error en grados usa
 * la distancia medida durante la validación (o, si no se pudo medir, la de
 * `camera.viewing_distance_cm`). Se acepta si no supera `camera.calibration_max_error_deg`.
 *
 * **Encuadre.** Antes de la calibración inicial, la pantalla de instrucciones
 * muestra si la cara se ve, a qué distancia está, si está centrada y si mira de
 * frente, con una figura que se mueve con la persona (sin mostrar el video).
 * **Comenzar** se habilita cuando todo está bien; **Comenzar de todos modos**
 * deja seguir al evaluador si la estimación falla. La inclinación vertical de la
 * cabeza no se exige: en un portátil la persona mira un poco hacia abajo.
 *
 * Mensajes:
 * - Recibe: `calibration.request` (`type`: `initial`, `final` o `drift_check`) del
 *   panel lateral, vía worker.
 * - Envía: `calibration.result` (`error_px`, `error_deg`, `accepted`) al panel
 *   lateral; el registro completo en un lote `calibration` y cada punto mostrado en
 *   un lote `gaze_target`, con `ctx.batcher.add`. Si la cámara todavía arranca, se
 *   espera hasta 20 s. Si no está activa o no se detecta el rostro, no se envía
 *   resultado: la capa lo explica y el panel ve el estado de la cámara.
 *
 * Durante la calibración la mirada no se registra (las características sí, para
 * poder medir y reajustar después), y los clics, el cursor, la rueda y las teclas
 * de desplazamiento sobre la capa no llegan a la captura de eventos ni mueven la
 * página (no son interacción con la aplicación).
 */

(function (root) {
  'use strict';

  const UX = (root.UX = root.UX || {});

  /**
   * Puntos de calibración: la cuadrícula de 3 × 3 en el 10, 50 y 90 % de la ventana
   * y cuatro intermedios en el 30 y 70 %, para cubrir también el medio de cada cuadrante.
   */
  const CALIBRATION_POINTS = [
    ...[0.1, 0.5, 0.9].flatMap((y) => [0.1, 0.5, 0.9].map((x) => ({ x, y }))),
    ...[0.3, 0.7].flatMap((y) => [0.3, 0.7].map((x) => ({ x, y }))),
  ];
  /** Puntos de validación: distintos de los de calibración, repartidos por toda la ventana. */
  const VALIDATION_POINTS = [
    { x: 0.2, y: 0.2 },
    { x: 0.8, y: 0.2 },
    { x: 0.2, y: 0.8 },
    { x: 0.8, y: 0.8 },
    { x: 0.5, y: 0.3 },
    { x: 0.5, y: 0.7 },
    { x: 0.3, y: 0.5 },
    { x: 0.7, y: 0.5 },
  ];
  /** Punto que se mira al volver de mirar el teclado (el noveno de la validación). */
  const LOOK_AWAY_POINT = { x: 0.5, y: 0.45 };
  /** Puntos de la comprobación de deriva: el centro y dos esquinas al azar. */
  const DRIFT_CENTER = { x: 0.5, y: 0.5 };
  const DRIFT_CORNERS = [
    { x: 0.2, y: 0.2 },
    { x: 0.8, y: 0.2 },
    { x: 0.2, y: 0.8 },
    { x: 0.8, y: 0.8 },
  ];
  /**
   * Cuadros que entrenan cada punto: desde un poco antes del clic (la vista ya llegó)
   * hasta un poco después. El motor descarta además parpadeos y cuadros atípicos.
   */
  const BEFORE_CLICK_MS = 300;
  const AFTER_CLICK_MS = 800;
  /** Punto en movimiento: duración y frecuencias de su curva de Lissajous (en Hz). */
  const PURSUIT_MS = 12000;
  const PURSUIT_FREQUENCIES = { x: 0.15, y: 0.2 };
  /** Amplitud del recorrido, en fracción de la ventana a cada lado del centro. */
  const PURSUIT_AMPLITUDE = 0.4;
  /** Recorrido que se guarda como objetivo: un punto cada este tiempo. */
  const PURSUIT_RECORD_MS = 33;
  /** Tiempo mirando el punto central mientras se mueve la cabeza. */
  const HEAD_MS = 8000;
  /** En la validación: espera a que la vista llegue al punto, y tiempo que se mide. */
  const SETTLE_MS = 700;
  const MEASURE_MS = 1000;
  /**
   * Al volver de mirar el teclado: espera máxima a que el monitor note la salida y la
   * vuelta, y tiempo tras la vuelta antes de medir (la sacada de regreso).
   */
  const LOOK_AWAY_MAX_MS = 6000;
  const RETURN_SETTLE_MS = 300;
  /** Muestras de validación que hacen falta para dar un resultado. */
  const MIN_VALIDATION_SAMPLES = 10;
  /** Estados de la mirada en que la persona mira la pantalla (`gaze_state`). */
  const LOOKING = ['on_screen', 'low_confidence'];
  /**
   * Si la cámara todavía arranca (el motor carga MediaPipe y su modelo, unos segundos),
   * se espera hasta esto antes de darla por no disponible, mirando cada `STATUS_POLL_MS`.
   */
  const CAMERA_START_WAIT_MS = 20000;
  const STATUS_POLL_MS = 250;
  /** Estados de la conexión que significan "todavía no se sabe": la cámara puede llegar. */
  const PENDING_STATUSES = ['starting', 'unknown'];
  /** Grados por radián. */
  const DEG = 180 / Math.PI;
  /**
   * Límites del encuadre. El centro de la cara puede alejarse hasta estas
   * fracciones del centro de la imagen (más margen en vertical: la cámara de un
   * portátil mira la cara un poco desde abajo) y la cabeza puede girar hasta estos
   * grados. La distancia aceptable está en la configuración (`camera.min_distance_cm`
   * y `camera.max_distance_cm`): cada persona se sienta a la distancia que le es
   * cómoda dentro de ese rango, porque la calibración mide la suya.
   */
  const FRAMING_LIMITS = Object.freeze({ horizontal: 0.15, vertical: 0.2, yawDeg: 15 });
  /** El encuadre se juzga con los cuadros de este último tramo, para que no parpadee. */
  const FRAMING_WINDOW_MS = 1000;
  /** Fracción mínima de cuadros del tramo con rostro para decir que la cara se ve. */
  const FRAMING_MIN_FACE_RATIO = 0.8;
  /** Cada cuánto se redibuja el encuadre, en milisegundos. */
  const FRAMING_RENDER_MS = 150;

  /** Mediana de una lista de números, o `null` si está vacía. */
  function median(values) {
    if (values.length === 0) {
      return null;
    }
    const sorted = [...values].sort((a, b) => a - b);
    const middle = sorted.length >> 1;
    return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
  }

  /**
   * Juzga el encuadre de la persona con los cuadros recientes del motor.
   *
   * Las direcciones son las de la persona mirando la pantalla: la imagen de la
   * cámara no está espejada, así que una cara a la izquierda de la imagen está
   * corrida hacia la derecha de la persona.
   *
   * @param {Array<{face_detected: boolean, head_yaw: (number|null), framing: (object|null)}>} frames -
   *   Cuadros recientes (mensajes `frame` del motor).
   * @param {{min_distance_cm: number, max_distance_cm: number}} camera - Configuración de la cámara.
   * @returns {{ok: boolean, face: boolean, distance_cm: (number|null),
   *   distance: (string|null), horizontal: (string|null), vertical: (string|null),
   *   frontal: (boolean|null), x: (number|null), y: (number|null), width: (number|null)}}
   *   `distance`: `ok`, `near` o `far`; `horizontal`: `ok`, `left` o `right` (hacia
   *   dónde debe moverse la persona); `vertical`: `ok`, `up` o `down` (hacia dónde
   *   inclinar la cámara); `x` e `y`, el centro de la cara en la imagen espejada (como
   *   en un espejo), y `width`, su ancho, para dibujar la figura.
   */
  function assessFraming(frames, camera) {
    const seen = frames.filter((frame) => frame.face_detected && frame.framing);
    const face = frames.length > 0 && seen.length / frames.length >= FRAMING_MIN_FACE_RATIO;
    if (!face) {
      return {
        ok: false,
        face: false,
        distance_cm: null,
        distance: null,
        horizontal: null,
        vertical: null,
        frontal: null,
        x: null,
        y: null,
        width: null,
      };
    }
    const distanceCm = median(seen.map((frame) => frame.framing.distance_cm));
    const x = median(seen.map((frame) => frame.framing.x));
    const y = median(seen.map((frame) => frame.framing.y));
    const yaw = median(seen.map((frame) => frame.head_yaw).filter((value) => value !== null));
    const distance =
      distanceCm < camera.min_distance_cm ? 'near' : distanceCm > camera.max_distance_cm ? 'far' : 'ok';
    // Cara a la izquierda de la imagen = persona corrida a su derecha: debe ir a su izquierda.
    const dx = x - 0.5;
    const horizontal = Math.abs(dx) <= FRAMING_LIMITS.horizontal ? 'ok' : dx < 0 ? 'left' : 'right';
    // Cara arriba en la imagen: la cámara debe apuntar más arriba para centrarla.
    const dy = y - 0.5;
    const vertical = Math.abs(dy) <= FRAMING_LIMITS.vertical ? 'ok' : dy < 0 ? 'up' : 'down';
    const frontal = yaw === null || Math.abs(yaw) <= FRAMING_LIMITS.yawDeg;
    return {
      ok: distance === 'ok' && horizontal === 'ok' && vertical === 'ok' && frontal,
      face: true,
      distance_cm: Math.round(distanceCm),
      distance,
      horizontal,
      vertical,
      frontal,
      x: Math.round((1 - x) * 1000) / 1000,
      y,
      width: median(seen.map((frame) => frame.framing.width)),
    };
  }

  /**
   * Sigue el encuadre con los cuadros del motor y avisa cada cambio.
   *
   * @param {object} link - Conexión con el motor (`onFrame`).
   * @param {{min_distance_cm: number, max_distance_cm: number}} camera - Configuración de la cámara.
   * @param {function(object): void} listener - Recibe el resultado de `assessFraming`.
   * @returns {function(): void} Deja de seguirlo.
   */
  function watchFraming(link, camera, listener) {
    let recent = [];
    return link.onFrame((frame) => {
      recent.push(frame);
      recent = recent.filter((item) => item.t >= frame.t - FRAMING_WINDOW_MS);
      listener(assessFraming(recent, camera));
    });
  }

  /**
   * Convierte un error en píxeles CSS a grados de ángulo visual.
   *
   * @param {number} errorPx - Error en píxeles CSS.
   * @param {{viewing_distance_cm: number, css_px_per_cm: number}} camera - Configuración de la cámara.
   * @param {number} [distanceCm] - Distancia medida; por omisión, la de la configuración.
   * @returns {number} Grados.
   */
  function pxToDeg(errorPx, camera, distanceCm = camera.viewing_distance_cm) {
    return Math.atan(errorPx / camera.css_px_per_cm / distanceCm) * DEG;
  }

  /** Inversa de `pxToDeg`: píxeles CSS que corresponden a unos grados a una distancia. */
  function degToPx(deg, camera, distanceCm = camera.viewing_distance_cm) {
    return Math.tan(deg / DEG) * distanceCm * camera.css_px_per_cm;
  }

  /** Mezcla una lista (Fisher-Yates), para que el participante no adivine el siguiente punto. */
  function shuffle(list, random) {
    const copy = [...list];
    for (let i = copy.length - 1; i > 0; i -= 1) {
      const j = Math.floor(random() * (i + 1));
      [copy[i], copy[j]] = [copy[j], copy[i]];
    }
    return copy;
  }

  /**
   * Reduce un recorrido a un punto cada `minGapMs` como mínimo, para guardarlo
   * como objetivo sin repetir la frecuencia de la pantalla.
   *
   * @param {Array<{t: number, x: number, y: number}>} points - Recorrido en orden de tiempo.
   * @param {number} minGapMs - Separación mínima entre puntos guardados, en milisegundos.
   * @returns {Array<{t: number, x: number, y: number}>} El primer punto, los que
   *   quedan a `minGapMs` o más del último guardado y el último del recorrido.
   */
  function thinPath(points, minGapMs) {
    const kept = [];
    for (const point of points) {
      // Se compara con el último guardado, no con el anterior del recorrido: la
      // pantalla dibuja más rápido que `minGapMs` y ningún punto pasaría el filtro.
      // Se tolera 1 ms porque los cuadros de la pantalla no llegan exactos.
      if (kept.length === 0 || point.t - kept[kept.length - 1].t >= minGapMs - 1) {
        kept.push(point);
      }
    }
    const last = points[points.length - 1];
    // El final se conserva para que el objetivo cubra todo el recorrido mostrado.
    if (last !== undefined && kept[kept.length - 1] !== last) {
      kept.push(last);
    }
    return kept;
  }

  /**
   * Posición del punto en movimiento en una fracción del recorrido (curva de Lissajous
   * que empieza en el centro). Su velocidad máxima, ~0,4 anchos de ventana por segundo,
   * se sigue con la vista sin saltos.
   *
   * @param {number} elapsedMs - Tiempo desde el inicio del recorrido.
   * @param {{width: number, height: number}} viewport - Ventana.
   * @returns {{x: number, y: number}} Punto en píxeles CSS.
   */
  function pursuitAt(elapsedMs, viewport) {
    const s = elapsedMs / 1000;
    return {
      x: viewport.width * (0.5 + PURSUIT_AMPLITUDE * Math.sin(2 * Math.PI * PURSUIT_FREQUENCIES.x * s)),
      y: viewport.height * (0.5 + PURSUIT_AMPLITUDE * Math.sin(2 * Math.PI * PURSUIT_FREQUENCIES.y * s)),
    };
  }

  /**
   * Raíz cuadrática media de la distancia entre muestras consecutivas: el temblor
   * de la mirada mientras se mira un punto quieto.
   *
   * @param {Array<Array<{x: number, y: number}>>} series - Muestras de cada punto, en orden.
   * @returns {(number|null)} Precisión en píxeles, o `null` sin pares de muestras.
   */
  function precisionPx(series) {
    let total = 0;
    let count = 0;
    for (const samples of series) {
      for (let i = 1; i < samples.length; i += 1) {
        total += (samples[i].x - samples[i - 1].x) ** 2 + (samples[i].y - samples[i - 1].y) ** 2;
        count += 1;
      }
    }
    return count === 0 ? null : Math.sqrt(total / count);
  }

  /** Redondea a una cantidad de decimales. */
  const round = (value, digits) => (value === null ? null : Math.round(value * 10 ** digits) / 10 ** digits);

  /**
   * Crea el procedimiento de calibración, sin DOM: la capa visual se recibe.
   *
   * @param {object} deps - Dependencias.
   * @param {object} deps.link - Conexión con el motor (`UX.cameraLink`).
   * @param {object} deps.ui - Capa visual: `intro(type)`, `point(x, y, mode, hint)`,
   *   `pursuit(positionAt, durationMs)`, `hold(ms)`, `message(text, buttons)`, `viewport()` y `close()`.
   * @param {{now: function(): number}} deps.clock - Reloj común.
   * @param {function(number): Promise<void>} deps.wait - Espera unos milisegundos.
   *   También se usa para esperar a que la cámara termine de arrancar.
   * @param {object} deps.strings - Textos (`UX.cameraStrings.calibration`).
   * @param {function(object): void} [deps.onResult] - Recibe cada resultado en cuanto se mide.
   * @param {function(object): void} [deps.onTarget] - Recibe cada objetivo mostrado, con la
   *   forma de `gaze_target.schema.json`.
   * @param {function(): number} [deps.random] - Azar entre 0 y 1.
   * @returns {{run: function(string, object): Promise<(object|null)>}} Procedimiento.
   */
  function createCalibrationProcedure({
    link,
    ui,
    clock,
    wait,
    strings,
    onResult = () => {},
    onTarget = () => {},
    random = Math.random,
  }) {
    /** Avisa un objetivo mostrado. */
    function target(type, phase, group, tStart, tEnd, points) {
      const { width, height } = ui.viewport();
      onTarget({
        t_start: tStart,
        t_end: tEnd,
        calibration_type: type,
        phase,
        group,
        viewport_width: width,
        viewport_height: height,
        points: points.map((p) => ({ t: p.t, x: round(p.x, 1), y: round(p.y, 1) })),
      });
    }

    /**
     * Muestra puntos fijos con clic y avisa al motor el tramo de cada uno.
     *
     * @param {string} type - Tipo de calibración.
     * @param {string} phase - `points` o `drift_check`.
     * @param {Array<{x: number, y: number}>} fractions - Puntos en fracciones de la ventana.
     * @param {?string} action - Pedido al motor por cada punto (`calibration.point`), o `null`.
     * @returns {Promise<Array<{x: number, y: number, t_start: number, t_end: number}>>} Tramos.
     */
    async function clickPoints(type, phase, fractions, action) {
      const { width, height } = ui.viewport();
      const windows = [];
      for (let group = 0; group < fractions.length; group += 1) {
        const x = fractions[group].x * width;
        const y = fractions[group].y * height;
        const { clickedAt } = await ui.point(x, y, 'click');
        await ui.hold(AFTER_CLICK_MS);
        const window = { x, y, t_start: clickedAt - BEFORE_CLICK_MS, t_end: clickedAt + AFTER_CLICK_MS };
        windows.push(window);
        if (action) {
          await link.request(action, { ...window, group, phase });
        }
        target(type, phase, group, window.t_start, window.t_end, [{ t: window.t_start, x, y }]);
      }
      return windows;
    }

    /** Punto en movimiento: lo sigue la vista; el motor mide el retraso y lo usa para entrenar. */
    async function pursue(type) {
      if ((await ui.message(strings.pursuitIntro, ['ready'])) !== 'ready') {
        return false;
      }
      const viewport = ui.viewport();
      const { points, tStart, tEnd } = await ui.pursuit((elapsed) => pursuitAt(elapsed, viewport), PURSUIT_MS);
      if (points.length < 2) {
        return true;
      }
      await link.request('calibration.pursuit', { points, t_start: tStart, t_end: tEnd });
      // Como objetivo se guarda el recorrido a la frecuencia de la cámara: basta para interpolar.
      target(type, 'pursuit', 0, tStart, tEnd, thinPath(points, PURSUIT_RECORD_MS));
      return true;
    }

    /** Punto central fijo mientras la cabeza se mueve: separa la cabeza del ojo. */
    async function moveHead(type) {
      if ((await ui.message(strings.headIntro, ['ready'])) !== 'ready') {
        return false;
      }
      const { width, height } = ui.viewport();
      const x = width / 2;
      const y = height / 2;
      await ui.point(x, y, 'look', strings.headHint);
      await wait(SETTLE_MS);
      const tStart = clock.now();
      await wait(HEAD_MS);
      const tEnd = clock.now();
      await link.request('calibration.point', { x, y, t_start: tStart, t_end: tEnd, group: 0, phase: 'head' });
      target(type, 'head', 0, tStart, tEnd, [{ t: tStart, x, y }]);
      return true;
    }

    /**
     * Entrena el estimador: puntos fijos, punto en movimiento y movimiento de cabeza.
     *
     * @param {object} camera - Sección `camera` de la configuración, con la pantalla de este equipo.
     * @returns {Promise<(object|null)>} Resultado del ajuste del motor si pudo entrenar, si no `null`.
     */
    async function train(camera) {
      const viewport = ui.viewport();
      // El motor solo conoce la configuración compartida: se le pasa la pantalla de este equipo.
      await link.request('calibration.reset', { viewport, css_px_per_cm: camera.css_px_per_cm });
      await clickPoints('initial', 'points', shuffle(CALIBRATION_POINTS, random), 'calibration.point');
      if (!(await pursue('initial')) || !(await moveHead('initial'))) {
        return null;
      }
      await ui.message(strings.fitting, []);
      const fit = await link.request('calibration.fit');
      return fit.ok === true ? fit : null;
    }

    /**
     * Junta las muestras de mirada mientras se mira un punto.
     *
     * @returns {{start: function({x: number, y: number}): void, stop: function(): Array,
     *   close: function(): void, distances: number[]}} Colector.
     */
    function collector() {
      let current = null;
      let samples = [];
      const distances = [];
      const off = link.onFrame((frame) => {
        if (current !== null && frame.gaze) {
          samples.push({ x: frame.gaze.x, y: frame.gaze.y, error: Math.hypot(frame.gaze.x - current.x, frame.gaze.y - current.y) });
        }
        if (current !== null && frame.framing) {
          distances.push(frame.framing.distance_cm);
        }
      });
      return {
        distances,
        start(point) {
          current = point;
          samples = [];
        },
        stop() {
          current = null;
          return samples;
        },
        close: off,
      };
    }

    /**
     * Espera a que la persona mire fuera de la pantalla y vuelva, según el estado
     * que da el monitor del motor. Si el monitor no lo nota, se rinde a tiempo.
     */
    async function awayAndBack() {
      let away = false;
      let back = false;
      const off = link.onFrame((frame) => {
        if (!LOOKING.includes(frame.gaze_state) && frame.gaze_state !== 'blink') {
          away = true;
        } else if (away && LOOKING.includes(frame.gaze_state)) {
          back = true;
        }
      });
      try {
        let waited = 0;
        while (!back && waited < LOOK_AWAY_MAX_MS) {
          await wait(100);
          waited += 100;
        }
      } finally {
        off();
      }
    }

    /**
     * Mide el error de la mirada en los puntos de validación y, al final, al volver
     * de mirar el teclado; también la precisión y la distancia a la cámara.
     *
     * @param {string} type - Tipo de calibración.
     * @returns {Promise<(object|null)>} `errorPx`, `precisionPx`, `returnErrorPx` y
     *   `distanceCm`, o `null` si no hubo muestras suficientes.
     */
    async function validate(type) {
      const { width, height } = ui.viewport();
      const collect = collector();
      const errors = [];
      const series = [];
      let returnErrors = [];
      try {
        for (let group = 0; group < VALIDATION_POINTS.length; group += 1) {
          const x = VALIDATION_POINTS[group].x * width;
          const y = VALIDATION_POINTS[group].y * height;
          ui.point(x, y, 'look');
          await wait(SETTLE_MS);
          const tStart = clock.now();
          collect.start({ x, y });
          await wait(MEASURE_MS);
          const samples = collect.stop();
          series.push(samples);
          errors.push(...samples.map((sample) => sample.error));
          target(type, 'validation', group, tStart, clock.now(), [{ t: tStart, x, y }]);
        }
        if ((await ui.message(strings.lookAwayIntro, ['ready'])) === 'ready') {
          const x = LOOK_AWAY_POINT.x * width;
          const y = LOOK_AWAY_POINT.y * height;
          ui.point(x, y, 'look', strings.lookAwayHint);
          await awayAndBack();
          await wait(RETURN_SETTLE_MS);
          const tStart = clock.now();
          collect.start({ x, y });
          await wait(MEASURE_MS);
          const samples = collect.stop();
          returnErrors = samples.map((sample) => sample.error);
          errors.push(...returnErrors);
          target(type, 'look_away', 0, tStart, clock.now(), [{ t: tStart, x, y }]);
        }
      } finally {
        collect.close();
      }
      if (errors.length < MIN_VALIDATION_SAMPLES) {
        return null;
      }
      const distance = median(collect.distances);
      const average = (values) => values.reduce((sum, e) => sum + e, 0) / values.length;
      return {
        errorPx: average(errors),
        precisionPx: precisionPx(series),
        returnErrorPx: returnErrors.length > 0 ? average(returnErrors) : null,
        distanceCm: distance === null ? null : Math.round(distance * 10) / 10,
      };
    }

    /**
     * Comprobación de deriva: tres puntos con clic; el motor mide el error y, si la
     * configuración lo pide y el error lo justifica, corrige la mirada.
     */
    async function driftCheck(camera) {
      const distances = [];
      const off = link.onFrame((frame) => frame.framing && distances.push(frame.framing.distance_cm));
      let windows;
      try {
        const corners = shuffle(DRIFT_CORNERS, random).slice(0, 2);
        windows = await clickPoints('drift_check', 'drift_check', [DRIFT_CENTER, ...corners], null);
      } finally {
        off();
      }
      const distance = median(distances);
      const distanceCm = distance === null ? camera.viewing_distance_cm : distance;
      const reply = await link.request('calibration.drift', {
        points: windows,
        correct: camera.drift_correction,
        min_error_px: degToPx(camera.drift_correction_min_error_deg, camera, distanceCm),
      });
      if (!reply.ok || reply.error_px === null) {
        return null;
      }
      return {
        errorPx: reply.error_px,
        distanceCm: distance === null ? null : Math.round(distance * 10) / 10,
        corrected: reply.corrected,
        correction: reply.correction,
      };
    }

    /**
     * Espera a que la cámara esté activa si todavía está arrancando. Mientras, la capa
     * lo avisa. Devuelve si quedó activa.
     */
    async function cameraReady() {
      if (PENDING_STATUSES.includes(link.status())) {
        await ui.message(strings.cameraStarting, []);
        let waited = 0;
        while (waited < CAMERA_START_WAIT_MS && PENDING_STATUSES.includes(link.status())) {
          await wait(STATUS_POLL_MS);
          waited += STATUS_POLL_MS;
        }
      }
      return link.status() === 'active';
    }

    /** Estimador en uso según el motor, o `null` si no lo informa. */
    async function currentEstimator() {
      try {
        const stats = await link.request('stats');
        return stats.estimator || null;
      } catch (error) {
        return null;
      }
    }

    /** Registro del lote `calibration` de una medición. */
    function recordOf(type, measured, camera, extra) {
      const distanceCm = measured.distanceCm ?? camera.viewing_distance_cm;
      const toDeg = (px) => (px === null || px === undefined ? null : round(pxToDeg(px, camera, distanceCm), 2));
      const errorDeg = pxToDeg(measured.errorPx, camera, distanceCm);
      const record = {
        t: clock.now(),
        type,
        error_px: round(measured.errorPx, 1),
        error_deg: round(errorDeg, 2),
        accepted: errorDeg <= camera.calibration_max_error_deg,
        viewing_distance_cm: measured.distanceCm,
        // La pantalla con que se pasaron los píxeles a grados: el análisis usa la misma.
        css_px_per_cm: camera.css_px_per_cm,
        precision_deg: toDeg(measured.precisionPx),
        return_error_deg: toDeg(measured.returnErrorPx),
        ...extra,
      };
      return Object.fromEntries(Object.entries(record).filter(([, value]) => value !== undefined));
    }

    return Object.freeze({
      /**
       * Hace una calibración, una validación final o una comprobación de deriva con la capa.
       *
       * @param {string} type - `initial`, `final` o `drift_check`.
       * @param {object} camera - Sección `camera` de la configuración.
       * @returns {Promise<(object|null)>} Registro del lote `calibration` del último
       *   intento, o `null` si no hubo resultado (cámara inactiva, sin rostro o cancelada).
       */
      async run(type, camera) {
        if (!(await cameraReady())) {
          await ui.message(strings.cameraUnavailable, ['continue']);
          return null;
        }
        // El encuadre se comprueba antes de la calibración inicial. En las demás no: deben
        // medir la mirada con la postura que la persona tenga, sin corregirla.
        const framing = type === 'initial' ? (listener) => watchFraming(link, camera, listener) : null;
        if (!['start', 'startAnyway'].includes(await ui.intro(type, framing, camera))) {
          return null;
        }
        if (type === 'drift_check') {
          const measured = await driftCheck(camera);
          if (measured === null) {
            await ui.message(strings.notCalibrated, ['continue']);
            return null;
          }
          const record = recordOf(type, measured, camera, {
            estimator: (await currentEstimator()) ?? undefined,
            corrected: measured.corrected,
            correction_x_px: round(measured.correction.x, 1),
            correction_y_px: round(measured.correction.y, 1),
          });
          onResult(record);
          const verdict = !record.accepted ? strings.driftLarge : measured.corrected ? strings.driftCorrected : strings.driftOk;
          await ui.message(`${verdict} ${strings.result(record.error_deg)}`, ['continue']);
          return record;
        }
        let last = null;
        for (;;) {
          let fit = null;
          if (type === 'initial') {
            // La línea base facial se registra antes de entrenar la mirada; no aporta
            // muestras al modelo. El rostro sigue capturándose mientras la mirada está pausada.
            const { width, height } = ui.viewport();
            ui.point(width / 2, height / 2, 'look', strings.neutralBaselineHint);
            const baselineStart = clock.now();
            await wait(10000);
            target(type, 'neutral_baseline', 0, baselineStart, clock.now(), [
              { t: baselineStart, x: width / 2, y: height / 2 },
            ]);
            fit = await train(camera);
            if (fit === null) {
              if ((await ui.message(strings.noFace, ['repeat', 'cancel'])) === 'repeat') {
                continue;
              }
              return last;
            }
            await ui.message(strings.validating, []);
            await wait(SETTLE_MS);
          }
          const measured = await validate(type);
          if (measured === null) {
            const message = type === 'final' && last === null ? strings.notCalibrated : strings.noFace;
            if ((await ui.message(message, ['repeat', 'cancel'])) === 'repeat') {
              continue;
            }
            return last;
          }
          last = recordOf(type, measured, camera, {
            estimator: (fit ? fit.estimator : await currentEstimator()) ?? undefined,
            // Retraso del sensor hasta la marca de tiempo de cada muestra: lo mide el motor
            // con el punto en movimiento de la calibración inicial. No es el tiempo de análisis
            // (`stats.delay_ms`): la marca de tiempo se toma antes de analizar el cuadro.
            camera_delay_ms: fit && Number.isFinite(fit.camera_delay_ms) ? fit.camera_delay_ms : null,
          });
          onResult(last);
          const text = `${last.accepted ? strings.accepted : strings.rejected} ${strings.result(last.error_deg)}`;
          const buttons = last.accepted ? ['continue'] : ['repeat', 'continue'];
          if ((await ui.message(text, buttons)) !== 'repeat') {
            return last;
          }
        }
      },
    });
  }

  /**
   * Crea la capa visual de la calibración sobre la página, dentro de un shadow
   * DOM para que los estilos del sitio no la alteren.
   *
   * @param {object} deps - Dependencias.
   * @param {Window} deps.page - Ventana de la página.
   * @param {object} deps.strings - Textos (`UX.cameraStrings.calibration`).
   * @param {{now: function(): number}} deps.clock - Reloj común.
   * @returns {object} Capa con la interfaz que espera `createCalibrationProcedure`.
   */
  function createOverlay({ page, strings, clock }) {
    const { document } = page;
    const host = document.createElement('div');
    host.setAttribute('data-suca-calibration', '');
    const shadow = host.attachShadow({ mode: 'closed' });
    shadow.innerHTML = `
      <style>
        :host { all: initial; }
        .backdrop { position: fixed; inset: 0; z-index: 2147483647; background: #eceff3;
          font: 18px/1.5 system-ui, sans-serif; color: #1d1d1f; cursor: default; }
        .card { position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%);
          max-width: 32rem; background: #fff; border-radius: 12px; padding: 1.5rem 2rem;
          box-shadow: 0 4px 24px rgba(0, 0, 0, 0.12); text-align: center; }
        .card[hidden], .dot[hidden], .hint[hidden] { display: none; }
        h2 { font-size: 1.3rem; margin: 0 0 0.75rem; }
        button { font: inherit; margin: 1rem 0.4rem 0; padding: 0.5rem 1.2rem; border: 0;
          border-radius: 8px; background: #1a5fb4; color: #fff; cursor: pointer; }
        button.secondary { background: #6b7280; }
        .dot { position: fixed; width: 28px; height: 28px; margin: -14px 0 0 -14px;
          border-radius: 50%; background: #d7263d; box-shadow: 0 0 0 4px #fff;
          transition: transform 1s linear; cursor: pointer; }
        .dot::after { content: ''; position: absolute; inset: 11px; border-radius: 50%; background: #fff; }
        .dot.shrink { transform: scale(0.3); }
        .hint { position: fixed; bottom: 1.5rem; left: 0; right: 0; text-align: center; color: #4b5563;
          pointer-events: none; }
        button:disabled { background: #9ca3af; cursor: not-allowed; }
        button.link { display: block; margin: 0.75rem auto 0; padding: 0; background: none; color: #1a5fb4;
          text-decoration: underline; font-size: 0.9rem; }
        .framing { margin-top: 1rem; }
        .framing[hidden], button.link[hidden] { display: none; }
        /* Vista de la cámara sin video: un óvalo guía y una figura que se mueve con la persona. */
        .view { display: block; width: 240px; height: 180px; margin: 0 auto; border-radius: 8px;
          background: #f3f4f6; }
        .view .frame { fill: none; stroke: #9ca3af; }
        .view .target { fill: none; stroke: #4b5563; stroke-width: 1.5; stroke-dasharray: 5 4; }
        .view .figure { fill: #c2410c; opacity: 0.85; }
        .view.ok .figure { fill: #1f8a4c; }
        .checks { list-style: none; margin: 0.75rem 0 0; padding: 0; text-align: left; font-size: 0.95rem; }
        .checks li::before { display: inline-block; width: 1.4em; font-weight: bold; }
        .checks li.ok::before { content: '✓'; color: #1f8a4c; }
        .checks li.bad::before { content: '✗'; color: #c2410c; }
        .checks li.wait::before { content: '…'; color: #6b7280; }
        .framing-status { margin: 0.75rem 0 0; font-weight: 600; }
      </style>
      <div class="backdrop">
        <div class="card" hidden>
          <h2></h2><p></p>
          <div class="framing" hidden>
            <svg class="view" viewBox="0 0 160 120" aria-hidden="true">
              <rect class="frame" x="0.5" y="0.5" width="159" height="119" rx="8"></rect>
              <ellipse class="target" cx="80" cy="60" rx="22" ry="28"></ellipse>
              <g class="figure" visibility="hidden">
                <ellipse class="body" cx="80" cy="117" rx="40" ry="24"></ellipse>
                <ellipse class="head" cx="80" cy="60" rx="22" ry="28"></ellipse>
              </g>
            </svg>
            <ul class="checks"></ul>
            <p class="framing-status"></p>
          </div>
          <div class="buttons"></div>
          <button type="button" class="link" data-action="startAnyway" hidden></button>
        </div>
        <div class="dot" hidden data-action="dot"></div>
        <div class="hint" hidden></div>
      </div>`;
    const card = shadow.querySelector('.card');
    const framingBox = shadow.querySelector('.framing');
    const view = shadow.querySelector('.view');
    const anyway = shadow.querySelector('button.link');
    anyway.textContent = strings.startAnywayButton;
    const dot = shadow.querySelector('.dot');
    const hint = shadow.querySelector('.hint');
    let onAction = null;
    let onCancel = null;
    /** Si la capa ya se quitó: lo que se pida después termina enseguida, como cancelado. */
    let closed = false;

    /**
     * Eventos que no deben llegar a la página ni a la captura mientras la capa está
     * abierta. Incluye el movimiento del cursor y la rueda: mover el cursor hacia cada
     * punto no es interacción con la aplicación, y no debe contarse como tal.
     */
    const BLOCKED = [
      'click', 'dblclick', 'contextmenu', 'auxclick', 'mousedown', 'mouseup', 'pointerdown', 'pointerup',
      'mousemove', 'pointermove', 'mouseover', 'mouseout', 'wheel',
    ];
    /** `wheel` en `window` es pasivo por omisión; sin `passive: false` no se puede impedir el scroll. */
    const BLOCK_OPTIONS = { capture: true, passive: false };
    /** Teclas que desplazan la página: bajo la capa no deben moverla. */
    const SCROLL_KEYS = [' ', 'PageUp', 'PageDown', 'Home', 'End', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'];

    /**
     * Los oyentes de la captura están en `document` en fase de captura; este,
     * en `window`, corre antes y detiene el evento. Por eso la capa atiende sus
     * propios clics aquí.
     */
    function intercept(event) {
      const path = event.composedPath();
      if (!path.includes(host)) {
        return;
      }
      event.stopImmediatePropagation();
      if (event.type === 'wheel') {
        event.preventDefault();
      }
      if (event.type !== 'click') {
        return;
      }
      event.preventDefault();
      // Con el shadow DOM cerrado, `composedPath` no muestra sus nodos a un oyente
      // de `window`: el botón o el punto se buscan en la posición del clic.
      let node = shadow.elementFromPoint(event.clientX, event.clientY);
      while (node && !(node.dataset && node.dataset.action)) {
        node = node.parentElement;
      }
      if (node && node.disabled) {
        return;
      }
      if (node && onAction) {
        onAction(node.dataset.action, clock.now());
      }
    }

    /** Detiene el teclado mientras la capa está abierta; Escape cancela. */
    function onKey(event) {
      event.stopImmediatePropagation();
      if (SCROLL_KEYS.includes(event.key)) {
        // Solo las teclas de desplazamiento: los atajos del navegador siguen funcionando.
        event.preventDefault();
      }
      if (event.key === 'Escape') {
        if (onCancel) {
          onCancel();
        } else if (onAction) {
          onAction('cancel', clock.now());
        }
      }
    }

    /** Espera a que se elija una de las acciones dadas. */
    function waitFor(actions) {
      if (closed) {
        return Promise.resolve({ action: 'cancel', at: clock.now() });
      }
      return new Promise((resolve) => {
        onAction = (action, at) => {
          if (actions.includes(action)) {
            onAction = null;
            resolve({ action, at });
          }
        };
      });
    }

    /** Muestra la tarjeta con un título, un texto y botones. */
    function showCard(title, text, buttons) {
      dot.hidden = true;
      hint.hidden = true;
      framingBox.hidden = true;
      anyway.hidden = true;
      card.hidden = false;
      card.querySelector('h2').textContent = title;
      card.querySelector('p').textContent = text;
      const container = card.querySelector('.buttons');
      container.textContent = '';
      for (const action of buttons) {
        const button = document.createElement('button');
        button.type = 'button';
        button.dataset.action = action;
        button.textContent = strings[`${action}Button`];
        if (action === 'cancel' || (action === 'continue' && buttons.includes('repeat'))) {
          button.className = 'secondary';
        }
        container.append(button);
      }
    }

    /** Error con el que termina un punto de calibración cancelado. */
    function cancelledError() {
      const error = new Error('calibration cancelled');
      error.name = 'CalibrationCancelled';
      return error;
    }

    let title = '';

    /** Pone los atributos de un elemento del SVG. */
    function setShape(selector, attributes) {
      const shape = view.querySelector(selector);
      for (const [name, value] of Object.entries(attributes)) {
        shape.setAttribute(name, String(Math.round(value * 10) / 10));
      }
    }

    /**
     * Líneas de la lista de comprobaciones: `[estado, texto]`, con estado `ok`,
     * `bad` o `wait`.
     */
    function framingChecks(assessment) {
      const texts = strings.framing;
      if (assessment === null) {
        return [['wait', texts.searching]];
      }
      if (!assessment.face) {
        return [['bad', texts.noFace]];
      }
      const distance = {
        ok: ['ok', texts.distance(assessment.distance_cm)],
        near: ['bad', texts.near(assessment.distance_cm)],
        far: ['bad', texts.far(assessment.distance_cm)],
      }[assessment.distance];
      const horizontal = assessment.horizontal === 'ok' ? null : ['bad', texts[assessment.horizontal]];
      const vertical = assessment.vertical === 'ok' ? null : ['bad', texts[assessment.vertical]];
      const centered = horizontal || vertical ? null : ['ok', texts.centered];
      const frontal = assessment.frontal ? ['ok', texts.frontal] : ['bad', texts.turned];
      return [['ok', texts.face], distance, centered, horizontal, vertical, frontal].filter(Boolean);
    }

    /**
     * Dibuja el encuadre: la figura donde está la cara (como en un espejo y del
     * tamaño con que se ve), el óvalo del tamaño que tendría a la distancia
     * indicada, la lista de comprobaciones y los botones.
     */
    function renderFraming(assessment, camera) {
      const ok = assessment !== null && assessment.ok;
      view.classList.toggle('ok', ok);
      const figure = view.querySelector('.figure');
      if (assessment !== null && assessment.face) {
        // El ancho de la imagen son 160 unidades; la cabeza es un poco más alta que ancha.
        const rx = (assessment.width * 160) / 2;
        const cx = assessment.x * 160;
        const cy = assessment.y * 120;
        // Cabeza un poco más alta que ancha y, debajo, los hombros.
        setShape('.head', { cx, cy, rx, ry: rx * 1.25 });
        setShape('.body', { cx, cy: cy + rx * 2.6, rx: rx * 1.8, ry: rx * 1.1 });
        // El óvalo es el tamaño que tendría la cara en el borde más cercano del rango
        // aceptable; dentro del rango, el de la cara: basta con que quede centrada.
        const allowed = Math.min(Math.max(assessment.distance_cm, camera.min_distance_cm), camera.max_distance_cm);
        const targetRx = (rx * assessment.distance_cm) / allowed;
        setShape('.target', { rx: targetRx, ry: targetRx * 1.25 });
        figure.setAttribute('visibility', 'visible');
      } else {
        figure.setAttribute('visibility', 'hidden');
      }
      const list = view.parentNode.querySelector('.checks');
      list.textContent = '';
      for (const [state, text] of framingChecks(assessment)) {
        const item = document.createElement('li');
        item.className = state;
        item.textContent = text;
        list.append(item);
      }
      framingBox.querySelector('.framing-status').textContent = ok
        ? strings.framing.ready
        : strings.framing.adjust;
      card.querySelector('[data-action="start"]').disabled = !ok;
      anyway.hidden = ok;
    }

    return Object.freeze({
      /** Agrega la capa a la página. */
      open() {
        page.addEventListener('keydown', onKey, true);
        page.addEventListener('keyup', onKey, true);
        BLOCKED.forEach((type) => page.addEventListener(type, intercept, BLOCK_OPTIONS));
        document.documentElement.append(host);
      },

      /** Ancho y alto de la ventana en píxeles CSS. */
      viewport: () => ({ width: page.innerWidth, height: page.innerHeight }),

      /**
       * Pantalla de inicio; se cumple con `start`, `startAnyway` o `cancel`.
       *
       * Con `framing`, muestra el encuadre en vivo: **Comenzar** se habilita cuando
       * está bien, y **Comenzar de todos modos** permite seguir sin esperar.
       *
       * @param {string} type - `initial` o `final`.
       * @param {(function(function(object): void): function(): void)|null} [framing] -
       *   Se suscribe a los cambios del encuadre (`watchFraming`) y devuelve cómo dejar de oírlos.
       * @param {{min_distance_cm: number, max_distance_cm: number}} [camera] - Configuración de la cámara.
       * @returns {Promise<string>} Acción elegida.
       */
      async intro(type, framing = null, camera = null) {
        title = strings.title[type];
        // Antes de calibrar se muestra qué pantalla y distancias se suponen, para notar si no son las de este equipo.
        const screen = type === 'initial' && camera ? ` ${strings.screenSummary(camera)}` : '';
        showCard(title, `${strings.intro[type]}${screen}`, ['start', 'cancel']);
        if (framing === null) {
          return (await waitFor(['start', 'cancel'])).action;
        }
        framingBox.hidden = false;
        renderFraming(null, camera);
        // Unas 6 veces por segundo bastan para que la figura se vea fluida. Si llegan más
        // cuadros entre dos dibujos, se dibuja el último al cumplirse el intervalo.
        let renderedAt = -Infinity;
        let latest = null;
        let timer = null;
        const draw = () => {
          timer = null;
          renderedAt = clock.now();
          renderFraming(latest, camera);
        };
        const off = framing((assessment) => {
          latest = assessment;
          const wait = FRAMING_RENDER_MS - (clock.now() - renderedAt);
          if (wait <= 0) {
            draw();
          } else if (timer === null) {
            timer = page.setTimeout(draw, wait);
          }
        });
        try {
          return (await waitFor(['start', 'startAnyway', 'cancel'])).action;
        } finally {
          off();
          page.clearTimeout(timer);
        }
      },

      /**
       * Muestra un punto. En modo `click` se cumple cuando el participante hace
       * clic en él (y se rechaza con `CalibrationCancelled` si presiona Escape);
       * en modo `look` se cumple enseguida. `hintText` reemplaza la indicación de abajo.
       */
      async point(x, y, mode, hintText = null) {
        card.hidden = true;
        dot.classList.remove('shrink');
        dot.style.left = `${x}px`;
        dot.style.top = `${y}px`;
        dot.hidden = false;
        hint.hidden = false;
        hint.textContent = hintText || (mode === 'click' ? strings.clickHint : strings.lookHint);
        if (mode !== 'click') {
          return { clickedAt: clock.now() };
        }
        if (closed) {
          throw cancelledError();
        }
        const cancelled = new Promise((_, reject) => {
          onCancel = () => reject(cancelledError());
        });
        try {
          const { at } = await Promise.race([waitFor(['dot']), cancelled]);
          return { clickedAt: at };
        } finally {
          onCancel = null;
        }
      },

      /**
       * Mueve el punto por un recorrido, cuadro a cuadro de la pantalla, y anota dónde
       * estuvo en cada momento. Termina al cumplirse la duración o si se quita la capa.
       *
       * @param {function(number): {x: number, y: number}} positionAt - Posición según el
       *   tiempo transcurrido, en milisegundos.
       * @param {number} durationMs - Duración del recorrido.
       * @returns {Promise<{points: Array<{t: number, x: number, y: number}>, tStart: number,
       *   tEnd: number}>} Recorrido mostrado.
       */
      pursuit(positionAt, durationMs) {
        card.hidden = true;
        dot.classList.remove('shrink');
        dot.hidden = false;
        hint.hidden = false;
        hint.textContent = strings.pursuitHint;
        const points = [];
        const tStart = clock.now();
        return new Promise((resolve) => {
          const step = () => {
            const t = clock.now();
            if (closed || t - tStart >= durationMs) {
              resolve({ points, tStart, tEnd: t });
              return;
            }
            const position = positionAt(t - tStart);
            dot.style.left = `${position.x}px`;
            dot.style.top = `${position.y}px`;
            points.push({ t, x: position.x, y: position.y });
            page.requestAnimationFrame(step);
          };
          step();
        });
      },

      /** Achica el punto mientras se toman los cuadros. */
      hold(ms) {
        dot.classList.add('shrink');
        return new Promise((resolve) => page.setTimeout(resolve, ms));
      },

      /** Muestra un mensaje; con botones, se cumple con la acción elegida. */
      async message(text, buttons) {
        showCard(title, text, buttons);
        if (buttons.length === 0) {
          return null;
        }
        return (await waitFor([...buttons, 'cancel'])).action;
      },

      /**
       * Quita la capa y los oyentes. Lo que esperaba una acción del participante
       * termina como cancelado, para que el procedimiento no quede colgado.
       */
      close() {
        closed = true;
        const cancelPoint = onCancel;
        const pendingAction = onAction;
        onAction = null;
        onCancel = null;
        if (cancelPoint) {
          cancelPoint();
        } else if (pendingAction) {
          pendingAction('cancel', clock.now());
        }
        page.removeEventListener('keydown', onKey, true);
        page.removeEventListener('keyup', onKey, true);
        BLOCKED.forEach((type) => page.removeEventListener(type, intercept, BLOCK_OPTIONS));
        host.remove();
      },
    });
  }

  /**
   * Crea el módulo de calibración de la pestaña.
   *
   * @param {object} deps - Dependencias.
   * @param {object} deps.link - Conexión con el motor (`UX.cameraLink`).
   * @param {function(): object} deps.createUi - Crea la capa visual.
   * @param {object} deps.strings - Textos (`UX.cameraStrings.calibration`).
   * @param {function(number): Promise<void>} [deps.wait] - Espera.
   * @param {function(object): Promise<object>} [deps.screenCamera] - Sección `camera` con
   *   la pantalla y las distancias de este equipo (`UX.screenSetup`); por defecto, la
   *   configuración tal cual.
   * @returns {{name: string, start: function(object): void, stop: function(): void}} Módulo.
   */
  function createCalibrationModule({
    link,
    createUi,
    strings,
    wait = (ms) => new Promise((resolve) => root.setTimeout(resolve, ms)),
    screenCamera = async (camera) => camera,
  }) {
    let ctx = null;
    let off = null;
    let ui = null;

    /** Atiende un pedido de calibración; uno a la vez. */
    async function calibrate(type) {
      if (ui !== null || ctx === null) {
        return;
      }
      const context = ctx;
      const ownUi = createUi();
      ui = ownUi;
      // Si la sesión se cerró (`stop`) mientras se medía, el intento sigue un momento
      // hasta notarlo: lo que mida ya no se registra ni se informa.
      const stillRunning = () => ui === ownUi;
      const onResult = (record) => {
        if (!stillRunning()) {
          return;
        }
        context.batcher.add('calibration', record);
        const { error_px, error_deg, accepted } = record;
        context.messages
          .send(context.messages.types.CALIBRATION_RESULT, { error_px, error_deg, accepted })
          .catch(() => {});
      };
      const onTarget = (record) => {
        if (stillRunning()) {
          context.batcher.add('gaze_target', record);
        }
      };
      const procedure = createCalibrationProcedure({
        link,
        ui: ownUi,
        clock: context.clock,
        wait,
        strings,
        onResult,
        onTarget,
      });
      link.pauseGaze(true);
      ownUi.open();
      try {
        await procedure.run(type, await screenCamera(context.config.camera));
      } catch (error) {
        // Tras `stop`, los pedidos al motor fallan porque la conexión se cerró: no es un error.
        if (error.name !== 'CalibrationCancelled' && stillRunning()) {
          console.error('calibration failed:', error);
        }
      } finally {
        // `stop` ya cerró la capa y reanudó la mirada; quizás hay otro intento en curso.
        if (stillRunning()) {
          link.pauseGaze(false);
          ownUi.close();
          ui = null;
        }
      }
    }

    return Object.freeze({
      name: 'calibration',

      /**
       * Empieza a escuchar `calibration.request`.
       *
       * @param {object} context - Contexto del módulo.
       * @returns {void}
       */
      start(context) {
        ctx = context;
        const { types } = context.messages;
        off = context.messages.on(types.CALIBRATION_REQUEST, ({ type }) => {
          if (context.contracts.enums.calibration_type.includes(type)) {
            calibrate(type);
          } else {
            console.warn(`unknown calibration type: ${type}`);
          }
          // Sin respuesta: el resultado viaja como `calibration.result`.
          return undefined;
        });
      },

      /**
       * Quita la capa si está visible y deja de escuchar.
       *
       * @returns {void}
       */
      stop() {
        if (off) {
          off();
          off = null;
        }
        if (ui) {
          ui.close();
          ui = null;
          link.pauseGaze(false);
        }
        ctx = null;
      },
    });
  }

  UX.createCalibrationProcedure = createCalibrationProcedure;
  UX.createCalibrationModule = createCalibrationModule;
  UX.calibrationMath = Object.freeze({
    pxToDeg,
    degToPx,
    assessFraming,
    pursuitAt,
    thinPath,
    precisionPx,
    FRAMING_LIMITS,
    CALIBRATION_POINTS,
    VALIDATION_POINTS,
  });
  if (UX.platform && UX.modules && UX.cameraLink) {
    const strings = UX.cameraStrings.calibration;
    UX.modules.register(
      createCalibrationModule({
        link: UX.cameraLink,
        strings,
        createUi: () => createOverlay({ page: root, strings, clock: UX.clock }),
        screenCamera: async (camera) =>
          UX.screenSetup.apply(camera, await UX.screenSetup.load(UX.platform.storage('local'))),
      }),
    );
  }
})(globalThis);
