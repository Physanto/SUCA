/**
 * @file Cola de envío al servidor, con reintentos y espera creciente.
 *
 * Es lógica pura, sin APIs de Chrome: el envío, el guardado y los temporizadores
 * entran como dependencias, así que se prueba completa en Node. El worker la
 * usa con el cliente del servidor y `storage.local`.
 *
 * Reglas:
 * - Orden estricto: un trabajo no sale hasta que salió el anterior. Así el cierre
 *   de una sesión nunca llega antes que sus últimos lotes.
 * - Cada cambio se guarda antes de seguir: si Chrome termina el worker, la cola
 *   se recupera al despertar con `load`.
 * - Un error permanente (4xx) descarta el trabajo y sigue con el próximo; uno
 *   transitorio (red caída, 5xx) espera `retry_initial_ms`, luego el doble,
 *   hasta `retry_max_ms`, y vuelve a intentar.
 */

(function (root) {
  'use strict';

  const UX = (root.UX = root.UX || {});

  /**
   * Crea una cola de envío.
   *
   * @param {object} deps - Dependencias.
   * @param {function(object): Promise<*>} deps.send - Envía un trabajo. Si falla,
   *   el error puede tener `permanent: true`.
   * @param {function(object[]): Promise<void>} deps.persist - Guarda la cola completa.
   * @param {number} deps.retryInitialMs - Espera antes del primer reintento.
   * @param {number} deps.retryMaxMs - Espera máxima entre reintentos.
   * @param {function(): number} [deps.now] - Reloj en milisegundos.
   * @param {{setTimeout: Function, clearTimeout: Function}} [deps.timers] - Temporizadores.
   * @param {function(object, Error): void} [deps.onDrop] - Se llama con cada trabajo descartado.
   * @returns {object} Cola con `load`, `enqueue`, `drain`, `size` y `jobs`.
   */
  function createSendQueue({
    send,
    persist,
    retryInitialMs,
    retryMaxMs,
    now = Date.now,
    timers = root,
    onDrop = (job, error) => console.warn(`dropped ${job.kind} job: ${error.message}`),
  }) {
    let jobs = [];
    let nextId = 1;
    let draining = false;
    let timer = null;

    /** Copia de los trabajos, para guardarlos o entregarlos sin compartir referencias. */
    const snapshot = () => jobs.map((job) => ({ ...job }));
    /** Espera antes del reintento número `attempts`: se duplica hasta el máximo. */
    const delayFor = (attempts) => Math.min(retryInitialMs * 2 ** (attempts - 1), retryMaxMs);

    /** Vuelve a intentar el envío dentro de `ms`; reemplaza un intento ya programado. */
    function wakeAfter(ms) {
      if (timer !== null) {
        timers.clearTimeout(timer);
      }
      timer = timers.setTimeout(() => {
        timer = null;
        drain();
      }, ms);
    }

    /**
     * Envía los trabajos en orden hasta vaciar la cola o encontrar uno que
     * todavía deba esperar.
     *
     * @returns {Promise<void>}
     */
    async function drain() {
      if (draining) {
        return;
      }
      draining = true;
      try {
        while (jobs.length > 0) {
          const job = jobs[0];
          const wait = job.not_before - now();
          if (wait > 0) {
            wakeAfter(wait);
            return;
          }
          try {
            await send(job);
            jobs.shift();
          } catch (error) {
            if (!(error && error.permanent)) {
              job.attempts += 1;
              job.not_before = now() + delayFor(job.attempts);
              await persist(snapshot());
              wakeAfter(delayFor(job.attempts));
              return;
            }
            jobs.shift();
            onDrop(job, error);
          }
          await persist(snapshot());
        }
      } catch (error) {
        // Solo llega aquí si falla el guardado; se intenta de nuevo más tarde.
        console.error('send queue could not be saved', error);
        wakeAfter(retryMaxMs);
      } finally {
        draining = false;
      }
    }

    return Object.freeze({
      /**
       * Recupera la cola guardada, por ejemplo al despertar el worker.
       *
       * @param {(object[]|undefined)} saved - Trabajos guardados con `persist`.
       * @returns {void}
       */
      load(saved) {
        jobs = (saved || []).map((job) => ({ ...job }));
        nextId = jobs.reduce((max, job) => Math.max(max, job.id), 0) + 1;
      },

      /**
       * Agrega un trabajo al final, lo guarda y empieza a enviar.
       *
       * @param {object} job - Trabajo, por ejemplo `{ kind: 'batch', session_id, body }`.
       * @returns {Promise<void>} Se cumple cuando el trabajo quedó guardado.
       */
      async enqueue(job) {
        jobs.push({ ...job, id: nextId++, attempts: 0, not_before: 0 });
        await persist(snapshot());
        drain();
      },

      drain,

      /**
       * Cuenta los trabajos pendientes.
       *
       * @returns {number} Trabajos en la cola.
       */
      size: () => jobs.length,

      /**
       * Devuelve una copia de los trabajos pendientes, en orden.
       *
       * @returns {object[]} Trabajos.
       */
      jobs: snapshot,
    });
  }

  UX.createSendQueue = createSendQueue;
})(globalThis);
