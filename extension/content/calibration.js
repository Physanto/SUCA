/**
 * @file Calibración de la mirada (M3): muestra una capa sobre la página con 9
 * puntos de calibración y 5 de validación, y mide el error resultante.
 *
 * Procedimiento:
 * - **Inicial** (`initial`): el participante mira cada uno de los 9 puntos y
 *   hace clic en él; los cuadros de alrededor del clic entrenan el modelo de
 *   mirada del motor. Después mira 5 puntos de validación, distintos de los
 *   anteriores, sin hacer clic, y se mide la distancia entre la mirada
 *   estimada y cada punto.
 * - **Final** (`final`): solo la validación, con el modelo de la calibración
 *   inicial, para estimar cuánto se degradó durante la sesión.
 *
 * El error medio se informa en píxeles CSS y en grados de ángulo visual, a la
 * distancia medida durante la validación (o, si no se pudo medir, a la de
 * `camera.viewing_distance_cm`). La calibración se acepta si el error en grados
 * no supera `camera.calibration_max_error_deg`. Si no se acepta, el
 * participante puede repetirla.
 *
 * **Encuadre.** Antes de la calibración inicial, la pantalla de instrucciones
 * muestra si la cara se ve, a qué distancia está, si está centrada y si mira de
 * frente, con una figura que se mueve con la persona (sin mostrar el video).
 * **Comenzar** se habilita cuando todo está bien; **Comenzar de todos modos**
 * deja seguir al evaluador si la estimación falla. La inclinación vertical de la
 * cabeza no se exige: en un portátil la persona mira un poco hacia abajo.
 *
 * Mensajes:
 * - Recibe: `calibration.request` (`type`: `initial` o `final`) del panel
 *   lateral, vía worker.
 * - Envía: `calibration.result` (`error_px`, `error_deg`, `accepted`) al panel
 *   lateral, y el mismo resultado al servidor en un lote `calibration` con
 *   `ctx.batcher.add`. Si la cámara todavía arranca, se espera hasta 20 s. Si no
 *   está activa o no se detecta el rostro, no se envía resultado: la capa lo
 *   explica y el panel ve el estado de la cámara.
 *
 * Durante la calibración la mirada no se registra, y los clics, el cursor, la
 * rueda y las teclas de desplazamiento sobre la capa no llegan a la captura de
 * eventos ni mueven la página (no son interacción con la aplicación).
 */

(function (root) {
  'use strict';

  const UX = (root.UX = root.UX || {});

  /** Puntos de calibración y de validación, en fracciones de la ventana. */
  const CALIBRATION_POINTS = [0.1, 0.5, 0.9].flatMap((y) => [0.1, 0.5, 0.9].map((x) => ({ x, y })));
  const VALIDATION_POINTS = [
    { x: 0.5, y: 0.5 },
    { x: 0.3, y: 0.3 },
    { x: 0.7, y: 0.3 },
    { x: 0.3, y: 0.7 },
    { x: 0.7, y: 0.7 },
  ];
  /** Cuadros que entrenan cada punto: desde un poco antes del clic hasta un poco después. */
  const BEFORE_CLICK_MS = 400;
  const AFTER_CLICK_MS = 1000;
  /** En la validación: espera a que la vista llegue al punto, y tiempo que se mide. */
  const SETTLE_MS = 700;
  const MEASURE_MS = 1000;
  /** Muestras de validación que hacen falta para dar un resultado. */
  const MIN_VALIDATION_SAMPLES = 10;
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
   * Límites del encuadre. La distancia puede alejarse hasta esto de
   * `camera.viewing_distance_cm`; el centro de la cara, hasta estas fracciones
   * del centro de la imagen (más margen en vertical: la cámara de un portátil
   * mira la cara un poco desde abajo); y la cabeza puede girar hasta estos grados.
   */
  const FRAMING_LIMITS = Object.freeze({ distanceCm: 10, horizontal: 0.15, vertical: 0.2, yawDeg: 15 });
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
   * @param {{viewing_distance_cm: number}} camera - Configuración de la cámara.
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
    const offset = distanceCm - camera.viewing_distance_cm;
    const distance = Math.abs(offset) <= FRAMING_LIMITS.distanceCm ? 'ok' : offset < 0 ? 'near' : 'far';
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
   * @param {{viewing_distance_cm: number}} camera - Configuración de la cámara.
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
   * Crea el procedimiento de calibración, sin DOM: la capa visual se recibe.
   *
   * @param {object} deps - Dependencias.
   * @param {object} deps.link - Conexión con el motor (`UX.cameraLink`).
   * @param {object} deps.ui - Capa visual: `intro(type)`, `point(x, y, mode)`,
   *   `hold(ms)`, `message(text, buttons)`, `viewport()` y `close()`.
   * @param {{now: function(): number}} deps.clock - Reloj común.
   * @param {function(number): Promise<void>} deps.wait - Espera unos milisegundos.
   * @param {object} deps.strings - Textos (`UX.cameraStrings.calibration`).
   * @param {function(object): void} [deps.onResult] - Recibe cada resultado en cuanto se mide.
   * @param {function(): number} [deps.random] - Azar entre 0 y 1.
   * @returns {{run: function(string, object): Promise<(object|null)>}} Procedimiento.
   *   `wait` también se usa para esperar a que la cámara termine de arrancar.
   */
  function createCalibrationProcedure({
    link,
    ui,
    clock,
    wait,
    strings,
    onResult = () => {},
    random = Math.random,
  }) {
    /** Entrena el modelo con los 9 puntos. Devuelve si el motor pudo entrenar. */
    async function train() {
      const { width, height } = ui.viewport();
      await link.request('calibration.reset');
      const points = shuffle(CALIBRATION_POINTS, random);
      for (let group = 0; group < points.length; group += 1) {
        const x = points[group].x * width;
        const y = points[group].y * height;
        const { clickedAt } = await ui.point(x, y, 'click');
        await ui.hold(AFTER_CLICK_MS);
        await link.request('calibration.point', {
          x,
          y,
          t_start: clickedAt - BEFORE_CLICK_MS,
          t_end: clickedAt + AFTER_CLICK_MS,
          group,
        });
      }
      await ui.message(strings.fitting, []);
      const fit = await link.request('calibration.fit');
      return fit.ok === true;
    }

    /**
     * Mide el error de la mirada en los 5 puntos de validación, y la distancia de la
     * persona a la cámara mientras tanto.
     *
     * @returns {Promise<({errorPx: number, distanceCm: (number|null)}|null)>} Error medio
     *   y mediana de la distancia, o `null` si no hubo muestras suficientes.
     */
    async function validate() {
      const { width, height } = ui.viewport();
      const errors = [];
      const distances = [];
      let target = null;
      const off = link.onFrame((frame) => {
        if (target !== null && frame.gaze) {
          errors.push(Math.hypot(frame.gaze.x - target.x, frame.gaze.y - target.y));
        }
        if (target !== null && frame.framing) {
          distances.push(frame.framing.distance_cm);
        }
      });
      try {
        for (const point of VALIDATION_POINTS) {
          const x = point.x * width;
          const y = point.y * height;
          ui.point(x, y, 'look');
          await wait(SETTLE_MS);
          target = { x, y };
          await wait(MEASURE_MS);
          target = null;
        }
      } finally {
        off();
      }
      if (errors.length < MIN_VALIDATION_SAMPLES) {
        return null;
      }
      const distance = median(distances);
      return {
        errorPx: errors.reduce((sum, e) => sum + e, 0) / errors.length,
        distanceCm: distance === null ? null : Math.round(distance * 10) / 10,
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

    return Object.freeze({
      /**
       * Hace una calibración completa con la capa.
       *
       * @param {string} type - `initial` o `final`.
       * @param {{viewing_distance_cm: number, css_px_per_cm: number,
       *   calibration_max_error_deg: number}} camera - Configuración de la cámara.
       * @returns {Promise<(object|null)>} Registro del lote `calibration` del último
       *   intento, o `null` si no hubo resultado (cámara inactiva, sin rostro o cancelada).
       */
      async run(type, camera) {
        if (!(await cameraReady())) {
          await ui.message(strings.cameraUnavailable, ['continue']);
          return null;
        }
        // El encuadre se comprueba antes de la calibración inicial. En la final no: debe
        // medir cuánto se degradó la mirada con la postura que la persona tenga, sin corregirla.
        const framing = type === 'initial' ? (listener) => watchFraming(link, camera, listener) : null;
        if (!['start', 'startAnyway'].includes(await ui.intro(type, framing, camera))) {
          return null;
        }
        let last = null;
        for (;;) {
          if (type === 'initial') {
            if (!(await train())) {
              if ((await ui.message(strings.noFace, ['repeat', 'cancel'])) === 'repeat') {
                continue;
              }
              return last;
            }
            await ui.message(strings.validating, []);
            await wait(SETTLE_MS);
          }
          const measured = await validate();
          if (measured === null) {
            const message = type === 'final' && last === null ? strings.notCalibrated : strings.noFace;
            if ((await ui.message(message, ['repeat', 'cancel'])) === 'repeat') {
              continue;
            }
            return last;
          }
          const { errorPx, distanceCm } = measured;
          const errorDeg = pxToDeg(errorPx, camera, distanceCm ?? camera.viewing_distance_cm);
          last = {
            t: clock.now(),
            type,
            error_px: Math.round(errorPx * 10) / 10,
            error_deg: Math.round(errorDeg * 100) / 100,
            accepted: errorDeg <= camera.calibration_max_error_deg,
            viewing_distance_cm: distanceCm,
            // Retraso del sensor hasta la marca de tiempo de cada muestra: todavía no se
            // mide. No es el tiempo de análisis (`stats.delay_ms`), porque la marca de
            // tiempo se toma antes de analizar el cuadro y ya no lo incluye.
            camera_delay_ms: null,
          };
          onResult(last);
          const text = `${last.accepted ? strings.accepted : strings.rejected} ${strings.result(errorDeg)}`;
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
        const targetRx = (rx * assessment.distance_cm) / camera.viewing_distance_cm;
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
       * @param {{viewing_distance_cm: number}} [camera] - Configuración de la cámara.
       * @returns {Promise<string>} Acción elegida.
       */
      async intro(type, framing = null, camera = null) {
        title = strings.title[type];
        showCard(title, strings.intro[type], ['start', 'cancel']);
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
       * en modo `look` se cumple enseguida.
       */
      async point(x, y, mode) {
        card.hidden = true;
        dot.classList.remove('shrink');
        dot.style.left = `${x}px`;
        dot.style.top = `${y}px`;
        dot.hidden = false;
        hint.hidden = false;
        hint.textContent = mode === 'click' ? strings.clickHint : strings.lookHint;
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
   * @returns {{name: string, start: function(object): void, stop: function(): void}} Módulo.
   */
  function createCalibrationModule({
    link,
    createUi,
    strings,
    wait = (ms) => new Promise((resolve) => root.setTimeout(resolve, ms)),
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
      const procedure = createCalibrationProcedure({
        link,
        ui: ownUi,
        clock: context.clock,
        wait,
        strings,
        onResult,
      });
      link.pauseGaze(true);
      ownUi.open();
      try {
        await procedure.run(type, context.config.camera);
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
    assessFraming,
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
      }),
    );
  }
})(globalThis);
