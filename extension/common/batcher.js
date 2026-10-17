/**
 * @file Acumula registros y los entrega al service worker por lotes.
 *
 * Los módulos solo llaman a `UX.batcher.add(type, record)`. El acumulador
 * agrupa por sesión y tipo de lote, entrega cada `sending.interval_ms` o en
 * cuanto un grupo llega a `sending.max_batch_records`, y vacía todo cuando la
 * página se oculta o se descarga. Si una entrega falla, los registros vuelven
 * al acumulador y se reintentan en la siguiente vuelta: no se pierden.
 */

(function (root) {
  'use strict';

  const UX = (root.UX = root.UX || {});

  /**
   * Devuelve una función que avisa cuando la página se oculta o se descarga.
   *
   * @param {object} globalScope - Objeto global de la página.
   * @returns {function(function(): void): void} Registra la función a llamar.
   */
  function pageHideListener(globalScope) {
    return (callback) => {
      if (!globalScope.document) {
        return;
      }
      globalScope.addEventListener('pagehide', callback);
      globalScope.document.addEventListener('visibilitychange', () => {
        if (globalScope.document.visibilityState === 'hidden') {
          callback();
        }
      });
    };
  }

  /**
   * Crea un acumulador de registros.
   *
   * @param {object} deps - Dependencias.
   * @param {object} deps.messages - Canal de mensajes (`UX.messages`).
   * @param {object} deps.session - Estado de la sesión (`UX.session`).
   * @param {{interval_ms: number, max_batch_records: number}} deps.sending -
   *   Sección `sending` de la configuración.
   * @param {string[]} deps.batchTypes - Tipos de lote del contrato (`batch_type`).
   * @param {{setTimeout: Function, clearTimeout: Function}} [deps.timers] -
   *   Temporizadores; por defecto, los globales.
   * @param {function(function(): void): void} [deps.onPageHide] - Registra la
   *   función a llamar cuando la página se oculta.
   * @returns {object} Acumulador con `add`, `flush` y `size`.
   */
  function createBatcher({ messages, session, sending, batchTypes, timers = root, onPageHide }) {
    const buffers = new Map();
    let timer = null;
    let warnedWithoutSession = false;

    const keyOf = (sessionId, type) => `${sessionId}:${type}`;

    function schedule() {
      if (timer === null) {
        timer = timers.setTimeout(() => {
          timer = null;
          flush();
        }, sending.interval_ms);
      }
    }

    /** Entrega un grupo; si falla, lo devuelve al acumulador antes que los más nuevos. */
    async function deliver(buffer) {
      try {
        await messages.send(messages.types.BATCH, {
          session_id: buffer.session_id,
          type: buffer.type,
          records: buffer.records,
        });
        return true;
      } catch (error) {
        console.warn(`batch not delivered, will retry: ${error.message}`);
        const key = keyOf(buffer.session_id, buffer.type);
        const newer = buffers.get(key);
        buffers.set(key, {
          ...buffer,
          records: newer ? buffer.records.concat(newer.records) : buffer.records,
        });
        schedule();
        return false;
      }
    }

    /**
     * Entrega ya todo lo acumulado.
     *
     * @returns {Promise<boolean>} `true` si se entregó todo; `false` si algo
     *   quedó para reintentar.
     */
    async function flush() {
      if (timer !== null) {
        timers.clearTimeout(timer);
        timer = null;
      }
      const pending = [...buffers.values()];
      buffers.clear();
      const results = await Promise.all(pending.map(deliver));
      return results.every(Boolean);
    }

    /**
     * Agrega un registro al lote de su tipo.
     *
     * @param {string} type - Tipo de lote según `contracts/enums.json`.
     * @param {object} record - Registro que cumple el esquema de su tipo.
     * @returns {boolean} `false` si no hay sesión activa y el registro se descartó.
     */
    function add(type, record) {
      if (!batchTypes.includes(type)) {
        throw new Error(`unknown batch type: ${type}`);
      }
      const current = session.get();
      if (current === null) {
        if (!warnedWithoutSession) {
          warnedWithoutSession = true;
          console.warn('records are discarded while there is no active session');
        }
        return false;
      }
      const key = keyOf(current.session_id, type);
      if (!buffers.has(key)) {
        buffers.set(key, { session_id: current.session_id, type, records: [] });
      }
      const buffer = buffers.get(key);
      // Se copia el registro para que cambios posteriores no alteren el lote.
      buffer.records.push(structuredClone(record));
      if (buffer.records.length >= sending.max_batch_records) {
        buffers.delete(key);
        deliver(buffer);
      } else {
        schedule();
      }
      return true;
    }

    if (onPageHide) {
      onPageHide(() => {
        flush();
      });
    }

    return Object.freeze({
      add,
      flush,

      /**
       * Cuenta los registros que esperan entrega.
       *
       * @returns {number} Registros acumulados.
       */
      size: () => [...buffers.values()].reduce((total, buffer) => total + buffer.records.length, 0),
    });
  }

  UX.createBatcher = createBatcher;
  if (UX.platform) {
    UX.batcher = createBatcher({
      messages: UX.messages,
      session: UX.session,
      sending: UX.config.sending,
      batchTypes: UX.contracts.enums.batch_type,
      onPageHide: pageHideListener(root),
    });
  }
})(globalThis);
