/**
 * @file Cámara (M3), en la pestaña evaluada: recibe del motor de la cámara
 * (documento offscreen `camera/engine.html`) la mirada y el rostro de cada
 * cuadro y los registra.
 *
 * Responsabilidad:
 * - mantener la conexión con el motor y reconectarse si se corta (el motor
 *   puede estar arrancando);
 * - registrar muestras `gaze` a `camera.gaze_hz` y `face` a `camera.face_hz`,
 *   cada punto de mirada con su scroll, elemento y zona;
 * - registrar los intervalos sin datos (`camera_gap`) que informa el motor, y el
 *   que deja un motor que Chrome cerró y el worker reemplazó (`reason: error`).
 *
 * La cámara no se abre aquí: el motor la abre una sola vez y persiste entre
 * navegaciones. A esta página solo llegan números, nunca imágenes.
 *
 * Mensajes:
 * - Envía: lotes `gaze`, `face` y eventos `camera_gap` (lote `events`) con
 *   `ctx.batcher.add`. `camera.status` lo envía el motor directamente al panel.
 * - Recibe: ninguno propio. Arranca y se detiene con la sesión.
 *
 * Expone `UX.cameraLink` para `calibration.js`: estado de la cámara, pedidos al
 * motor, cuadros recibidos y pausa de la mirada durante la calibración.
 */

(function (root) {
  'use strict';

  const UX = (root.UX = root.UX || {});

  /** Nombre de la conexión con el motor. */
  const PORT_NAME = 'camera';
  /** Espera antes de reconectar, en milisegundos. */
  const RECONNECT_MS = 1000;
  /** Espera máxima de una respuesta del motor, en milisegundos. */
  const REQUEST_TIMEOUT_MS = 3000;
  /** Margen para no descartar una muestra que llega unos milisegundos antes. */
  const RATE_TOLERANCE = 0.8;
  /** Un hueco más corto que esto no se registra (el mismo umbral que usa el motor). */
  const MIN_GAP_MS = 250;

  /** Redondea a una cantidad de decimales, para no enviar ruido numérico. */
  const round = (value, digits) => {
    const factor = 10 ** digits;
    return Math.round(value * factor) / factor;
  };

  /**
   * Crea la conexión con el motor de la cámara.
   *
   * @param {object} deps - Dependencias.
   * @param {{connect: function(string): object}} deps.platform - Adaptador de plataforma.
   * @param {{setTimeout: Function, clearTimeout: Function}} [deps.timers] - Temporizadores.
   * @returns {object} Conexión con `open`, `close`, `status`, `request`, `onFrame`,
   *   `onGap`, `onRestart`, `onLost`, `pauseGaze` y `gazePaused`.
   */
  function createCameraLink({ platform, timers = root }) {
    let port = null;
    let wanted = false;
    let reconnectTimer = null;
    let status = 'unknown';
    let nextId = 1;
    let paused = false;
    /** Momento en que arrancó el motor conocido (de su `hello`), o `null` si todavía no hubo ninguno. */
    let engineStartedAt = null;
    const pending = new Map();
    const frameListeners = new Set();
    const gapListeners = new Set();
    const restartListeners = new Set();
    const lostListeners = new Set();

    /**
     * Anota el motor que saludó. Si es otro que el anterior, Chrome cerró el documento
     * de la cámara y el worker creó uno nuevo: se avisa, porque el motor nuevo no sabe
     * del hueco ni tiene la calibración.
     */
    function noteEngine(hello) {
      const startedAt = typeof hello.started_at === 'number' ? hello.started_at : null;
      const previous = engineStartedAt;
      engineStartedAt = startedAt;
      if (previous !== null && startedAt !== null && startedAt !== previous) {
        restartListeners.forEach((listener) => listener({ calibrated: hello.calibrated === true }));
      }
    }

    /** Rechaza los pedidos sin respuesta: la conexión se cortó. */
    function failPending(reason) {
      for (const { reject, timer } of pending.values()) {
        timers.clearTimeout(timer);
        reject(new Error(reason));
      }
      pending.clear();
    }

    /** Atiende un mensaje del motor. */
    function dispatch(message) {
      switch (message && message.kind) {
        case 'hello':
          status = message.status;
          noteEngine(message);
          break;
        case 'status':
          status = message.status;
          break;
        case 'frame':
          frameListeners.forEach((listener) => listener(message));
          break;
        case 'gap':
          gapListeners.forEach((listener) => listener(message));
          break;
        case 'reply': {
          const request = pending.get(message.id);
          if (request) {
            pending.delete(message.id);
            timers.clearTimeout(request.timer);
            if (message.ok) {
              request.resolve(message);
            } else {
              request.reject(new Error(message.error));
            }
          }
          break;
        }
        default:
          break;
      }
    }

    /** Abre la conexión; si se corta, la vuelve a abrir mientras se quiera. */
    function connect() {
      reconnectTimer = null;
      if (!wanted) {
        return;
      }
      const current = platform.connect(PORT_NAME);
      port = current;
      // Si saludó, el motor existía: que la conexión se corte significa que se perdió.
      let greeted = false;
      current.onMessage((message) => {
        if (message && message.kind === 'hello') {
          greeted = true;
        }
        dispatch(message);
      });
      current.onDisconnect(() => {
        if (port !== current) {
          return;
        }
        port = null;
        status = 'unknown';
        failPending('camera engine disconnected');
        if (wanted) {
          if (greeted) {
            lostListeners.forEach((listener) => listener());
          }
          reconnectTimer = timers.setTimeout(connect, RECONNECT_MS);
        }
      });
    }

    return Object.freeze({
      /** Empieza a conectarse con el motor. */
      open() {
        if (!wanted) {
          wanted = true;
          connect();
        }
      },

      /** Cierra la conexión y deja de reconectar. */
      close() {
        wanted = false;
        if (reconnectTimer !== null) {
          timers.clearTimeout(reconnectTimer);
          reconnectTimer = null;
        }
        const current = port;
        port = null;
        status = 'unknown';
        failPending('camera link closed');
        if (current) {
          current.disconnect();
        }
      },

      /**
       * Estado de la cámara según el motor.
       *
       * @returns {string} `active`, `no_permission`, `error`, `starting` o
       *   `unknown` (sin conexión).
       */
      status: () => status,

      /**
       * Pide algo al motor.
       *
       * @param {string} action - Pedido (`calibration.reset`, `calibration.point`,
       *   `calibration.fit`, `stats`, `flush`).
       * @param {object} [payload] - Datos del pedido.
       * @returns {Promise<object>} Respuesta del motor.
       */
      request(action, payload = {}) {
        if (port === null) {
          return Promise.reject(new Error('camera engine not connected'));
        }
        const id = nextId;
        nextId += 1;
        return new Promise((resolve, reject) => {
          const timer = timers.setTimeout(() => {
            pending.delete(id);
            reject(new Error(`camera request timed out: ${action}`));
          }, REQUEST_TIMEOUT_MS);
          pending.set(id, { resolve, reject, timer });
          port.post({ ...payload, kind: 'request', action, id });
        });
      },

      /**
       * Escucha los cuadros que llegan del motor.
       *
       * @param {function(object): void} listener - Recibe cada cuadro.
       * @returns {function(): void} Función que deja de escuchar.
       */
      onFrame(listener) {
        frameListeners.add(listener);
        return () => frameListeners.delete(listener);
      },

      /**
       * Escucha los intervalos sin datos que informa el motor.
       *
       * @param {function(object): void} listener - Recibe `{ t, t_end, reason }`.
       * @returns {function(): void} Función que deja de escuchar.
       */
      onGap(listener) {
        gapListeners.add(listener);
        return () => gapListeners.delete(listener);
      },

      /**
       * Escucha cuando el motor fue reemplazado por otro durante la vida de esta página.
       *
       * @param {function({calibrated: boolean}): void} listener - Recibe si el motor
       *   nuevo tiene calibración (normalmente no).
       * @returns {function(): void} Función que deja de escuchar.
       */
      onRestart(listener) {
        restartListeners.add(listener);
        return () => restartListeners.delete(listener);
      },

      /**
       * Escucha cuando se corta la conexión con un motor que existía (no cuando el
       * motor todavía no estaba, ni al cerrar la conexión con `close`).
       *
       * @param {function(): void} listener - Función a llamar.
       * @returns {function(): void} Función que deja de escuchar.
       */
      onLost(listener) {
        lostListeners.add(listener);
        return () => lostListeners.delete(listener);
      },

      /**
       * Pausa o reanuda el registro de la mirada (durante la calibración).
       *
       * @param {boolean} value - `true` para pausar.
       * @returns {void}
       */
      pauseGaze(value) {
        paused = Boolean(value);
      },

      /** @returns {boolean} Si la mirada está en pausa. */
      gazePaused: () => paused,
    });
  }

  /**
   * Crea el módulo de cámara de la pestaña.
   *
   * @param {object} deps - Dependencias.
   * @param {object} deps.link - Conexión con el motor (`createCameraLink`).
   * @param {object} deps.zones - Zonas y selectores (`UX.gazeZones`).
   * @param {object} deps.page - Página: `window` con `document`, `location`,
   *   `scrollX`, `scrollY`, `innerWidth` e `innerHeight`.
   * @returns {{name: string, start: function(object): void, stop: function(): Promise<void>}} Módulo.
   */
  function createCameraModule({ link, zones, page }) {
    let ctx = null;
    let unsubscribe = [];
    let lastGazeT = -Infinity;
    let lastFaceT = -Infinity;
    /** Momento del último cuadro recibido, o `null` si no llegó ninguno en esta página. */
    let lastFrameT = null;
    /** Hueco que empezó cuando se perdió el motor anterior: `{ t }`, o `null`. */
    let restartGap = null;

    /** Tarea activa del modo guiado, o `null`. */
    function activeTask() {
      const state = ctx.session.get();
      return state && Number.isInteger(state.task_id) ? state.task_id : null;
    }

    /**
     * Pantalla de un intervalo sin datos. Solo origen y ruta: sin búsqueda ni
     * fragmento, que pueden llevar lo que escribió el participante.
     */
    function currentScreen() {
      const { origin, pathname } = page.location;
      return { url: `${origin}${pathname}`, title: '' };
    }

    /** Muestra de mirada con la forma de `gaze.schema.json`. */
    function gazeRecord(t, gaze) {
      const scroll = {
        scroll_x: Math.max(0, round(page.scrollX || 0, 1)),
        scroll_y: Math.max(0, round(page.scrollY || 0, 1)),
      };
      if (gaze === null) {
        return { t, x: null, y: null, ...scroll, element_selector: null, zone: null, valid: false };
      }
      const x = round(gaze.x, 1);
      const y = round(gaze.y, 1);
      const width = page.innerWidth;
      const height = page.innerHeight;
      if (x < 0 || y < 0 || x >= width || y >= height) {
        // Mira fuera de la página (por ejemplo, al panel lateral): no hay elemento ni zona.
        return { t, x, y, ...scroll, element_selector: null, zone: null, valid: false };
      }
      const element = page.document.elementFromPoint(x, y);
      return {
        t,
        x,
        y,
        ...scroll,
        element_selector: element ? zones.selectorOf(element) : null,
        zone: zones.zoneOf(element, x, y, width, height),
        valid: true,
      };
    }

    /** Muestra facial con la forma de `face.schema.json`. */
    function faceRecord(frame) {
      if (!frame.face_detected) {
        return { t: frame.t, values: null, head_yaw: null, head_pitch: null, face_detected: false };
      }
      // Solo pasan los nombres del contrato con un número entre 0 y 1: lo que llegue
      // además desde el motor no se registra.
      const allowed = ctx.contracts.enums.face_value;
      const values = Object.fromEntries(
        Object.entries(frame.values || {})
          .filter(([name, value]) => allowed.includes(name) && Number.isFinite(value))
          .map(([name, value]) => [name, round(Math.min(1, Math.max(0, value)), 4)]),
      );
      if (Object.keys(values).length === 0) {
        return { t: frame.t, values: null, head_yaw: null, head_pitch: null, face_detected: false };
      }
      return {
        t: frame.t,
        values,
        head_yaw: round(frame.head_yaw, 2),
        head_pitch: round(frame.head_pitch, 2),
        face_detected: true,
      };
    }

    /** Registra un cuadro, respetando la frecuencia de cada tipo. */
    function onFrame(frame) {
      if (restartGap !== null) {
        // Primer cuadro del motor nuevo: termina el hueco que dejó el anterior.
        const { t } = restartGap;
        restartGap = null;
        if (frame.t - t >= MIN_GAP_MS) {
          recordGap({ t, t_end: frame.t, reason: 'error' });
        }
      }
      lastFrameT = frame.t;
      const { camera } = ctx.config;
      if (frame.t - lastFaceT >= (1000 / camera.face_hz) * RATE_TOLERANCE) {
        lastFaceT = frame.t;
        ctx.batcher.add('face', faceRecord(frame));
      }
      if (!link.gazePaused() && frame.t - lastGazeT >= (1000 / camera.gaze_hz) * RATE_TOLERANCE) {
        lastGazeT = frame.t;
        ctx.batcher.add('gaze', gazeRecord(frame.t, frame.gaze));
      }
    }

    /** Registra un intervalo sin datos como evento `camera_gap`. */
    function recordGap({ t, t_end: tEnd, reason }) {
      ctx.batcher.add('events', {
        t,
        type: 'camera_gap',
        screen: currentScreen(),
        task_id: activeTask(),
        data: { t_end: tEnd, reason },
      });
    }

    /**
     * Se perdió el motor con la página todavía abierta (por ejemplo, en una aplicación
     * de una sola página). El worker revisa que el motor exista cada vez que la pestaña
     * evaluada pregunta su id con `tab.identify`, así que se pregunta de nuevo: si el
     * motor ya no está, el worker lo crea y la conexión se rehace sola.
     */
    function askForEngine() {
      Promise.resolve(ctx.messages.send(ctx.messages.types.TAB_IDENTIFY)).catch(() => {
        // Sin worker no hay a quién pedirlo: se seguirá reintentando la conexión.
      });
    }

    /**
     * El motor fue reemplazado (Chrome cerró el documento de la cámara): el nuevo no
     * conoce el hueco, así que lo registra esta pestaña desde su último cuadro. La
     * mirada queda sin calibrar (`valid: false`) hasta una calibración nueva.
     */
    function onRestart({ calibrated }) {
      if (lastFrameT !== null && restartGap === null) {
        restartGap = { t: lastFrameT };
      }
      if (!calibrated) {
        console.warn('camera engine restarted: gaze needs a new calibration');
      }
    }

    return Object.freeze({
      name: 'camera',

      /**
       * Se conecta con el motor y empieza a registrar. No espera a la cámara:
       * si todavía no está lista, los datos empiezan a llegar cuando lo esté.
       *
       * @param {object} context - Contexto del módulo.
       * @returns {void}
       */
      start(context) {
        ctx = context;
        lastGazeT = -Infinity;
        lastFaceT = -Infinity;
        lastFrameT = null;
        restartGap = null;
        unsubscribe = [
          link.onFrame(onFrame),
          link.onGap(recordGap),
          link.onRestart(onRestart),
          link.onLost(askForEngine),
        ];
        link.open();
      },

      /**
       * Deja de registrar. Si la cámara estaba sin datos, ese intervalo queda
       * abierto (`t_end: null`), porque la sesión termina.
       *
       * @returns {Promise<void>}
       */
      async stop() {
        unsubscribe.forEach((off) => off());
        unsubscribe = [];
        if (ctx !== null) {
          if (restartGap !== null) {
            // El motor nuevo nunca entregó datos: el hueco termina con la sesión.
            recordGap({ t: restartGap.t, t_end: null, reason: 'error' });
            restartGap = null;
          }
          try {
            const { gap } = await link.request('flush');
            if (gap) {
              recordGap(gap);
            }
          } catch {
            // El motor no responde: no hay nada que entregar.
          }
        }
        link.close();
        ctx = null;
      },
    });
  }

  UX.createCameraLink = createCameraLink;
  UX.createCameraModule = createCameraModule;
  if (UX.platform && UX.modules) {
    UX.cameraLink = createCameraLink({ platform: UX.platform });
    UX.modules.register(createCameraModule({ link: UX.cameraLink, zones: UX.gazeZones, page: root }));
  }
})(globalThis);
