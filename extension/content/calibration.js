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
 * distancia de `camera.viewing_distance_cm`. La calibración se acepta si el
 * error en grados no supera `camera.calibration_max_error_deg`. Si no se
 * acepta, el participante puede repetirla.
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
   * Convierte un error en píxeles CSS a grados de ángulo visual.
   *
   * @param {number} errorPx - Error en píxeles CSS.
   * @param {{viewing_distance_cm: number, css_px_per_cm: number}} camera - Configuración de la cámara.
   * @returns {number} Grados.
   */
  function pxToDeg(errorPx, camera) {
    return Math.atan(errorPx / camera.css_px_per_cm / camera.viewing_distance_cm) * DEG;
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

    /** Mide el error de la mirada en los 5 puntos de validación. */
    async function validate() {
      const { width, height } = ui.viewport();
      const errors = [];
      let target = null;
      const off = link.onFrame((frame) => {
        if (target !== null && frame.gaze) {
          errors.push(Math.hypot(frame.gaze.x - target.x, frame.gaze.y - target.y));
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
      return errors.reduce((sum, e) => sum + e, 0) / errors.length;
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
        if ((await ui.intro(type)) !== 'start') {
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
          const errorPx = await validate();
          if (errorPx === null) {
            const message = type === 'final' && last === null ? strings.notCalibrated : strings.noFace;
            if ((await ui.message(message, ['repeat', 'cancel'])) === 'repeat') {
              continue;
            }
            return last;
          }
          const errorDeg = pxToDeg(errorPx, camera);
          last = {
            t: clock.now(),
            type,
            error_px: Math.round(errorPx * 10) / 10,
            error_deg: Math.round(errorDeg * 100) / 100,
            accepted: errorDeg <= camera.calibration_max_error_deg,
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
      </style>
      <div class="backdrop">
        <div class="card" hidden><h2></h2><p></p><div class="buttons"></div></div>
        <div class="dot" hidden data-action="dot"></div>
        <div class="hint" hidden></div>
      </div>`;
    const card = shadow.querySelector('.card');
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

      /** Pantalla de inicio; se cumple con `start` o `cancel`. */
      async intro(type) {
        title = strings.title[type];
        showCard(title, strings.intro[type], ['start', 'cancel']);
        return (await waitFor(['start', 'cancel'])).action;
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
  UX.calibrationMath = Object.freeze({ pxToDeg, CALIBRATION_POINTS, VALIDATION_POINTS });
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
