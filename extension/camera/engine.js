/**
 * @file Motor de la cámara: une los cuadros procesados con la pestaña evaluada.
 *
 * Corre en el documento *offscreen* de la extensión (`camera/engine.html`), que
 * no se recarga al navegar. Por eso aquí viven el estimador de mirada entrenado,
 * la corrección de deriva y el registro de los intervalos sin datos: sobreviven
 * a cada cambio de página.
 *
 * Responsabilidad:
 * - recibir cada cuadro ya analizado (valores faciales, pose de la cabeza y
 *   características de los ojos), estimar la mirada, pedirle al monitor su
 *   estado y confianza, y filtrarla (One Euro);
 * - entregarlo a la pestaña evaluada por su conexión (`camera.js`), con las
 *   características numéricas del cuadro para el lote `gaze_features`;
 * - atender la calibración (`calibration.js`): reiniciar, agregar los cuadros de
 *   cada punto fijo o en movimiento, entrenar (elige el estimador y mide el
 *   retraso de la cámara con el punto en movimiento) y las comprobaciones de
 *   deriva, que miden el error y pueden corregirlo;
 * - detectar los intervalos sin datos (navegación, permiso negado, fallo) y
 *   entregarlos cuando vuelven los datos, o al cerrar la sesión.
 *
 * No toca la cámara ni Chrome: `engine-main.mjs` le pasa los cuadros y las
 * conexiones. Así se prueba en Node.
 *
 * Mensajes por la conexión (forma en `camera/README.md`):
 * - Al conectar: `hello` con el estado, si hay calibración y el momento en que
 *   arrancó este motor (`started_at`).
 * - Del motor a la pestaña: `status`, `frame` (con el encuadre del rostro, la
 *   mirada, su estado y las características), `gap` y `reply`.
 * - De la pestaña al motor: `request` con `action` y un `id` que la respuesta repite.
 */

(function (root) {
  'use strict';

  const UX = (root.UX = root.UX || {});
  const { median, percentile } = UX.numeric;

  /**
   * Cuánto tiempo de cuadros se guarda para la calibración, en milisegundos.
   * Alcanza para el tramo más largo: el punto en movimiento.
   */
  const BUFFER_MS = 20000;
  /** Un hueco más corto que esto no se registra: es una demora normal del procesamiento. */
  const MIN_GAP_MS = 250;
  /** Cuadros que se usan para las estadísticas. */
  const STATS_WINDOW = 120;
  /** Estados que existen en el contrato (`camera_status`). */
  const PROBLEM_STATUSES = ['no_permission', 'error'];
  /** Estados de la mirada en que la persona mira la pantalla (`gaze_state`). */
  const LOOKING = ['on_screen', 'low_confidence'];
  /**
   * Del punto en movimiento se descarta el primer tramo: los ojos tardan en
   * engancharse a un objetivo que empieza a moverse.
   */
  const PURSUIT_SKIP_MS = 1000;
  /** Tramos en que se parte el recorrido del punto en movimiento para la validación cruzada. */
  const PURSUIT_GROUPS = 4;
  /** Retrasos de cámara que se prueban, en milisegundos. */
  const DELAYS_MS = Array.from({ length: 31 }, (_, i) => i * 10);
  /** En la calibración, un cuadro más lejos que esto de la mediana de su punto se descarta (en MAD). */
  const OUTLIER_MADS = 3.5;
  /** Piso de la MAD de la posición del iris, para no descartar todo cuando el punto es muy estable. */
  const MIN_MAD = 0.004;
  /** Percentiles del giro de la cabeza que forman el rango calibrado. */
  const POSE_RANGE = [0.05, 0.95];

  /** Posición de un recorrido en un momento, interpolando; fuera de él, el extremo. */
  function pathAt(path, t) {
    if (t <= path[0].t) {
      return path[0];
    }
    for (let i = 1; i < path.length; i += 1) {
      if (t <= path[i].t) {
        const a = path[i - 1];
        const b = path[i];
        const f = b.t === a.t ? 0 : (t - a.t) / (b.t - a.t);
        return { t, x: a.x + f * (b.x - a.x), y: a.y + f * (b.y - a.y) };
      }
    }
    return path[path.length - 1];
  }

  /**
   * Crea el motor.
   *
   * @param {object} deps - Dependencias.
   * @param {{now: function(): number}} deps.clock - Reloj común (`UX.clock`).
   * @param {object} deps.estimator - Estimador de mirada (`UX.createGazeEstimator`).
   * @param {object} deps.monitor - Monitor de la mirada (`UX.createGazeMonitor`).
   * @param {object} deps.filter - Filtro temporal (`UX.createOneEuroFilter`).
   * @param {number} deps.blinkThreshold - Parpadeo desde el que un cuadro no entrena.
   * @param {function(string): void} [deps.onStatus] - Avisa cada cambio a un estado
   *   del contrato (`active`, `no_permission`, `error`).
   * @param {function(): object} [deps.info] - Datos extra para las estadísticas
   *   (por ejemplo, si MediaPipe usa la GPU o la CPU).
   * @returns {object} Motor con `connect`, `setStatus`, `frame`, `status` y `stats`.
   */
  function createEngine({ clock, estimator, monitor, filter, blinkThreshold, onStatus = () => {}, info = () => ({}) }) {
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
    /** Calibración en curso o terminada: ventana, poses vistas y punto en movimiento. */
    let calibration = null;
    /** Corrección de deriva que se suma a la mirada, en píxeles. */
    let correction = { x: 0, y: 0 };
    let previousState = null;
    let lastFit = null;

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

    /** Estadísticas de los últimos cuadros y del estimador. */
    function stats() {
      const span = recent.length > 1 ? recent[recent.length - 1].t - recent[0].t : 0;
      return {
        ...info(),
        status,
        calibrated: estimator.isFitted(),
        estimator: estimator.chosen(),
        correction: { ...correction },
        last_fit: lastFit,
        frames: recent.length,
        hz: span > 0 ? ((recent.length - 1) * 1000) / span : null,
        delay_ms: median(recent.map((r) => r.delay)),
        face_ratio: recent.length ? recent.filter((r) => r.face).length / recent.length : null,
      };
    }

    /** Punto que da el estimador para unas características, con la corrección de deriva. */
    function estimate(features) {
      const point = features && estimator.isFitted() ? estimator.predict(features) : null;
      return point === null ? null : { x: point.x + correction.x, y: point.y + correction.y };
    }

    /** Cuadros del búfer con características y ojos abiertos, entre dos momentos. */
    function usableFrames(tStart, tEnd) {
      return buffer.filter(
        (f) =>
          f.t >= tStart &&
          f.t <= tEnd &&
          f.features &&
          !(f.features.signals.blink !== null && f.features.signals.blink >= blinkThreshold),
      );
    }

    /**
     * Descarta los cuadros de un punto fijo cuya posición del iris se aleja mucho de
     * la del resto (una mirada que todavía no llegaba, un reflejo): mediana ± MAD.
     */
    function withoutOutliers(frames) {
      const geometric = frames.filter((f) => f.features.geometric);
      if (geometric.length < 5) {
        return frames;
      }
      const spread = (key) => {
        const values = geometric.map((f) => f.features.geometric[key]);
        const center = median(values);
        const mad = Math.max(MIN_MAD, median(values.map((v) => Math.abs(v - center))));
        return { center, mad };
      };
      const h = spread('h');
      const v = spread('v');
      return frames.filter((f) => {
        const g = f.features.geometric;
        return !g || (Math.abs(g.h - h.center) <= OUTLIER_MADS * h.mad && Math.abs(g.v - v.center) <= OUTLIER_MADS * v.mad);
      });
    }

    /**
     * Retraso de la cámara: el que mejor alinea la mirada estimada con el punto en
     * movimiento. Un cuadro con marca `t` muestra el ojo de `t − retraso`, que en un
     * seguimiento suave miraba el punto donde estaba en ese momento.
     */
    function pursuitDelay(pursuit) {
      let best = { delay: null, error: Infinity };
      const predictions = pursuit.frames.map((f) => ({ t: f.t, point: estimator.predict(f.features) }));
      for (const delay of DELAYS_MS) {
        let total = 0;
        let count = 0;
        for (const { t, point } of predictions) {
          if (point !== null) {
            const target = pathAt(pursuit.path, t - delay);
            total += Math.hypot(point.x - target.x, point.y - target.y);
            count += 1;
          }
        }
        if (count > 0 && total / count < best.error) {
          best = { delay, error: total / count };
        }
      }
      return best.delay;
    }

    /** Entrena con lo reunido y, si hubo punto en movimiento, mide el retraso y lo suma. */
    function fit() {
      if (calibration === null) {
        return { ok: false, samples: 0, groups: 0, lambda: null, cv_error_px: null, estimator: null };
      }
      const context = { viewport: calibration.viewport };
      let result = estimator.fit(context);
      let delay = null;
      const { pursuit } = calibration;
      if (result.ok && pursuit && pursuit.frames.length > 0) {
        delay = pursuitDelay(pursuit);
        if (delay !== null) {
          const span = pursuit.frames[pursuit.frames.length - 1].t - pursuit.frames[0].t || 1;
          for (const f of pursuit.frames) {
            const target = pathAt(pursuit.path, f.t - delay);
            const chunk = Math.min(PURSUIT_GROUPS - 1, Math.floor(((f.t - pursuit.frames[0].t) / span) * PURSUIT_GROUPS));
            estimator.add(f.features, target.x, target.y, `pursuit:${chunk}`);
          }
          result = estimator.fit(context);
        }
      }
      filter.reset();
      previousState = null;
      correction = { x: 0, y: 0 };
      if (result.ok) {
        const poses = calibration.poses;
        monitor.calibrate({
          yaw: [percentile(poses.yaw, POSE_RANGE[0]), percentile(poses.yaw, POSE_RANGE[1])],
          pitch: [percentile(poses.pitch, POSE_RANGE[0]), percentile(poses.pitch, POSE_RANGE[1])],
          open: median(poses.open) ?? 0,
          viewport: calibration.viewport,
        });
      }
      lastFit = { ...result, camera_delay_ms: delay };
      return lastFit;
    }

    /**
     * Mide la deriva en unos puntos y, si se pide y el error lo justifica, la corrige
     * desplazando la mirada en el error medio.
     */
    function driftCheck({ points, correct, min_error_px: minErrorPx }) {
      const residuals = [];
      let total = 0;
      let count = 0;
      for (const point of points) {
        const frames = usableFrames(point.t_start, point.t_end);
        const errors = frames.map((f) => estimate(f.features)).filter((p) => p !== null);
        if (errors.length === 0) {
          continue;
        }
        const mean = {
          x: errors.reduce((sum, p) => sum + p.x - point.x, 0) / errors.length,
          y: errors.reduce((sum, p) => sum + p.y - point.y, 0) / errors.length,
        };
        residuals.push(mean);
        errors.forEach((p) => {
          total += Math.hypot(p.x - point.x, p.y - point.y);
          count += 1;
        });
      }
      if (count === 0) {
        return { ok: false, samples: 0, error_px: null, corrected: false, correction: { ...correction } };
      }
      const errorPx = total / count;
      const corrected = correct === true && errorPx >= minErrorPx;
      if (corrected) {
        correction = {
          x: correction.x - residuals.reduce((sum, r) => sum + r.x, 0) / residuals.length,
          y: correction.y - residuals.reduce((sum, r) => sum + r.y, 0) / residuals.length,
        };
        filter.reset();
      }
      return { ok: true, samples: count, error_px: errorPx, corrected, correction: { ...correction } };
    }

    /** Ejecuta un pedido de una pestaña y devuelve lo que se responde. */
    function handle(action, request) {
      switch (action) {
        case 'calibration.reset': {
          estimator.clear();
          monitor.reset();
          filter.reset();
          previousState = null;
          correction = { x: 0, y: 0 };
          lastFit = null;
          const viewport = request.viewport || null;
          calibration = { viewport, poses: { yaw: [], pitch: [], open: [] }, pursuit: null };
          return { ok: true };
        }
        case 'calibration.point': {
          if (calibration === null) {
            throw new Error('calibration.point before calibration.reset');
          }
          const { x, y, t_start: tStart, t_end: tEnd, group, phase = 'points' } = request;
          const frames = withoutOutliers(usableFrames(tStart, tEnd));
          frames.forEach((f) => {
            estimator.add(f.features, x, y, `${phase}:${group}`);
            const { yaw, pitch, open } = f.features.signals;
            if (yaw !== null) {
              calibration.poses.yaw.push(yaw);
              calibration.poses.pitch.push(pitch);
            }
            if (open !== null) {
              calibration.poses.open.push(open);
            }
          });
          return { ok: true, samples: frames.length };
        }
        case 'calibration.pursuit': {
          if (calibration === null) {
            throw new Error('calibration.pursuit before calibration.reset');
          }
          const { points, t_start: tStart, t_end: tEnd } = request;
          if (!Array.isArray(points) || points.length < 2) {
            throw new Error('calibration.pursuit needs a path of at least two points');
          }
          const frames = usableFrames(tStart + PURSUIT_SKIP_MS, tEnd);
          calibration.pursuit = { path: [...points].sort((a, b) => a.t - b.t), frames };
          return { ok: true, samples: frames.length };
        }
        case 'calibration.fit':
          return fit();
        case 'calibration.drift':
          return driftCheck(request);
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

    /** Estado, confianza y mirada filtrada de un cuadro. */
    function gazeOf(t, face, features) {
      const raw = estimate(features);
      const signals = features ? features.signals : { blink: null, open: null, yaw: null, pitch: null, refined: 0 };
      const { state, confidence } = monitor.assess({
        t,
        face: face !== null && features !== null,
        calibrated: estimator.isFitted(),
        ...signals,
        point: raw,
      });
      let gaze = null;
      if (LOOKING.includes(state)) {
        // Al volver de mirar fuera, el filtro empieza de nuevo: no mezcla el teclado con la página.
        if (!LOOKING.includes(previousState) && previousState !== 'blink') {
          filter.reset();
        }
        gaze = filter.next(t, raw);
      } else if (state !== 'blink') {
        // En un parpadeo el filtro conserva su estado; en los demás casos se reinicia.
        filter.reset();
      }
      previousState = state;
      return { raw, gaze, state, confidence };
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
        client.post({ kind: 'hello', status, calibrated: estimator.isFitted(), started_at: startedAt });
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
          filter.reset();
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
       * @param {(object|null)} frame.features - Características del cuadro, o `null`:
       *   `geometric` y `appearance` (una por estimador), `signals` (`blink`, `open`, `yaw`,
       *   `pitch`, `refined`) para el monitor y `record` (los números del lote `gaze_features`).
       * @returns {void}
       */
      frame({ t, processedAt, face, features }) {
        buffer.push({ t, features });
        buffer = buffer.filter((f) => f.t >= t - BUFFER_MS);
        recent.push({ t, delay: processedAt - t, face: face !== null });
        if (recent.length > STATS_WINDOW) {
          recent.shift();
        }
        const { raw, gaze, state, confidence } = gazeOf(t, face, features);
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
          gaze_state: state,
          gaze_confidence: confidence,
          features: features ? { ...features.record, raw_x: raw ? raw.x : null, raw_y: raw ? raw.y : null } : null,
        });
      },

      /** @returns {string} Estado actual (`starting` hasta que la cámara responde). */
      status: () => status,

      stats,
    });
  }

  UX.createCameraEngine = createEngine;
})(globalThis);
