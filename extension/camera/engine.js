/**
 * @file Motor de la cámara: une los cuadros procesados con la pestaña evaluada.
 *
 * Corre en el documento *offscreen* de la extensión (`camera/engine.html`), que
 * no se recarga al navegar. Por eso aquí viven el modelo de mirada entrenado y
 * el registro de los intervalos sin datos: sobreviven a cada cambio de página.
 *
 * Responsabilidad:
 * - recibir cada cuadro ya analizado (valores faciales, orientación de la cabeza
 *   y características de los ojos) y estimar la mirada con el modelo;
 * - entregarlo a la pestaña evaluada por su conexión (`camera.js`);
 * - atender lo que pide la calibración (`calibration.js`): reiniciar el modelo,
 *   agregar los cuadros de un punto, entrenar;
 * - detectar los intervalos sin datos (navegación, permiso negado, fallo) y
 *   entregarlos cuando vuelven los datos, o al cerrar la sesión.
 *
 * No toca la cámara ni Chrome: `engine-main.mjs` le pasa los cuadros y las
 * conexiones. Así se prueba en Node.
 *
 * Mensajes por la conexión (forma en `camera/README.md`):
 * - Al conectar: `hello` con el estado, si hay calibración y el momento en que
 *   arrancó este motor (`started_at`).
 * - Del motor a la pestaña: `status`, `frame` (con el encuadre del rostro), `gap` y `reply`.
 * - De la pestaña al motor: `request` con `action` y un `id` que la respuesta repite.
 */

(function (root) {
  'use strict';

  const UX = (root.UX = root.UX || {});

  /** Cuánto tiempo de cuadros se guarda para la calibración, en milisegundos. */
  const BUFFER_MS = 5000;
  /** Un hueco más corto que esto no se registra: es una demora normal del procesamiento. */
  const MIN_GAP_MS = 250;
  /** Cuadros que se usan para las estadísticas. */
  const STATS_WINDOW = 120;
  /** Estados que existen en el contrato (`camera_status`). */
  const PROBLEM_STATUSES = ['no_permission', 'error'];

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
   * Crea el motor.
   *
   * @param {object} deps - Dependencias.
   * @param {{now: function(): number}} deps.clock - Reloj común (`UX.clock`).
   * @param {object} deps.gazeModel - Modelo de mirada (`UX.createGazeModel()`).
   * @param {object} deps.smoother - Suavizado de la mirada (`UX.createSmoother()`).
   * @param {function(string): void} [deps.onStatus] - Avisa cada cambio a un estado
   *   del contrato (`active`, `no_permission`, `error`).
   * @param {function(): object} [deps.info] - Datos extra para las estadísticas
   *   (por ejemplo, si MediaPipe usa la GPU o la CPU).
   * @returns {object} Motor con `connect`, `setStatus`, `frame`, `status` y `stats`.
   */
  function createEngine({ clock, gazeModel, smoother, onStatus = () => {}, info = () => ({}) }) {
    const clients = new Set();
    // Identifica a este motor: si Chrome cierra el documento y el worker crea otro, la
    // pestaña ve un valor distinto y sabe que se perdieron la calibración y los huecos.
    const startedAt = clock.now();
    let status = 'starting';
    let buffer = [];
    let lastDataT = null;
    let firstConnectT = null;
    let openGap = null;
    const recent = [];

    /** Envía un mensaje a todas las pestañas conectadas. */
    function broadcast(message) {
      for (const client of clients) {
        client.post(message);
      }
    }

    /** Abre un hueco si no hay uno abierto. */
    function openGapAt(t, reason) {
      if (openGap === null) {
        openGap = { t, reason };
      }
    }

    /** Cierra el hueco abierto con los primeros datos que llegan a una pestaña. */
    function closeGapAt(tEnd) {
      if (openGap === null) {
        return;
      }
      const gap = openGap;
      openGap = null;
      if (tEnd - gap.t >= MIN_GAP_MS) {
        broadcast({ kind: 'gap', t: gap.t, t_end: tEnd, reason: gap.reason });
      }
    }

    /** Estadísticas de los últimos cuadros. */
    function stats() {
      const span = recent.length > 1 ? recent[recent.length - 1].t - recent[0].t : 0;
      return {
        ...info(),
        status,
        calibrated: gazeModel.isFitted(),
        frames: recent.length,
        hz: span > 0 ? ((recent.length - 1) * 1000) / span : null,
        delay_ms: median(recent.map((r) => r.delay)),
        face_ratio: recent.length ? recent.filter((r) => r.face).length / recent.length : null,
      };
    }

    /** Ejecuta un pedido de una pestaña y devuelve lo que se responde. */
    function handle(action, request) {
      switch (action) {
        case 'calibration.reset':
          gazeModel.clear();
          smoother.reset();
          return { ok: true };
        case 'calibration.point': {
          const { x, y, t_start: tStart, t_end: tEnd, group } = request;
          const frames = buffer.filter((f) => f.t >= tStart && f.t <= tEnd && f.features);
          frames.forEach((f) => gazeModel.add(f.features, x, y, group));
          return { ok: true, samples: frames.length };
        }
        case 'calibration.fit': {
          smoother.reset();
          return gazeModel.fit();
        }
        case 'stats':
          return stats();
        case 'flush': {
          // La sesión se cierra: un hueco abierto termina sin datos.
          const gap = openGap === null ? null : { t: openGap.t, t_end: null, reason: openGap.reason };
          openGap = null;
          return { gap };
        }
        default:
          throw new Error(`unknown camera request: ${action}`);
      }
    }

    return Object.freeze({
      /**
       * Conecta una pestaña.
       *
       * @param {{post: function(object): void}} client - Cómo enviarle mensajes.
       * @returns {{receive: function(object): void, disconnect: function(): void}}
       *   Lo que la conexión llama al recibir un mensaje y al cerrarse.
       */
      connect(client) {
        clients.add(client);
        if (firstConnectT === null) {
          firstConnectT = clock.now();
        }
        client.post({ kind: 'hello', status, calibrated: gazeModel.isFitted(), started_at: startedAt });
        return {
          receive(message) {
            if (!message || message.kind !== 'request') {
              return;
            }
            let reply;
            try {
              reply = { ok: true, ...handle(message.action, message) };
            } catch (error) {
              reply = { ok: false, error: error.message };
            }
            client.post({ kind: 'reply', id: message.id, ...reply });
          },
          disconnect() {
            clients.delete(client);
            // Sin pestaña conectada no se registra nada: la página está navegando.
            if (clients.size === 0 && status === 'active' && lastDataT !== null) {
              openGapAt(lastDataT, 'navigation');
            }
          },
        };
      },

      /**
       * Cambia el estado de la cámara.
       *
       * @param {string} next - `active`, `no_permission` o `error`.
       * @returns {void}
       */
      setStatus(next) {
        if (next === status) {
          return;
        }
        status = next;
        if (PROBLEM_STATUSES.includes(next)) {
          smoother.reset();
          openGapAt(lastDataT ?? firstConnectT ?? clock.now(), next);
        }
        broadcast({ kind: 'status', status });
        onStatus(status);
      },

      /**
       * Recibe un cuadro analizado.
       *
       * @param {object} frame - Cuadro.
       * @param {number} frame.t - Momento en que llegó el cuadro (reloj común).
       * @param {number} frame.processedAt - Momento en que terminó su análisis.
       * @param {({values: object, head_yaw: number, head_pitch: number, framing: object}|null)} frame.face -
       *   Valores del rostro y su encuadre (`faceFraming`), o `null` si no se detectó.
       * @param {(number[]|null)} frame.features - Características de los ojos, o `null`.
       * @returns {void}
       */
      frame({ t, processedAt, face, features }) {
        buffer.push({ t, features });
        buffer = buffer.filter((f) => f.t >= t - BUFFER_MS);
        recent.push({ t, delay: processedAt - t, face: face !== null });
        if (recent.length > STATS_WINDOW) {
          recent.shift();
        }
        let gaze = null;
        if (features && gazeModel.isFitted()) {
          gaze = smoother.next(gazeModel.predict(features));
        } else {
          smoother.reset();
        }
        if (clients.size === 0) {
          return;
        }
        closeGapAt(t);
        lastDataT = t;
        broadcast({
          kind: 'frame',
          t,
          face_detected: face !== null,
          values: face ? face.values : null,
          head_yaw: face ? face.head_yaw : null,
          head_pitch: face ? face.head_pitch : null,
          framing: face && face.framing ? face.framing : null,
          gaze,
        });
      },

      /** @returns {string} Estado actual (`starting` hasta que la cámara responde). */
      status: () => status,

      stats,
    });
  }

  UX.createCameraEngine = createEngine;
})(globalThis);
