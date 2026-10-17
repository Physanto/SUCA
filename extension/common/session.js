/**
 * @file Estado de la sesión activa, compartido por el panel, el worker y los
 * content scripts a través de `chrome.storage.session`.
 *
 * Cada contexto guarda una copia en memoria, así `get()` es síncrono: la
 * captura necesita la tarea activa en cada evento y no puede esperar una
 * lectura. La copia se actualiza sola cuando otro contexto cambia el estado.
 * Solo el panel lateral lo escribe. La forma del estado está en
 * `contracts/extension-messages.md`.
 */

(function (root) {
  'use strict';

  const UX = (root.UX = root.UX || {});

  /** Clave del estado en `storage.session`. */
  const STORAGE_KEY = 'session';

  /** Campos del estado y si deben ser enteros. `task_id` también admite `null`. */
  const INTEGER_FIELDS = ['session_id', 'study_id', 'tab_id', 'task_id'];
  const FIELDS = ['session_id', 'mode', 'study_id', 'tab_id', 'task_id'];

  /**
   * Comprueba que un estado tenga la forma del contrato.
   *
   * @param {object} state - Estado a escribir.
   * @param {string[]} modes - Modos de sesión del contrato.
   * @returns {void}
   */
  function validate(state, modes) {
    for (const key of Object.keys(state)) {
      if (!FIELDS.includes(key)) {
        throw new Error(`unknown session field: ${key}`);
      }
    }
    for (const key of INTEGER_FIELDS) {
      const value = state[key];
      const allowsNull = key === 'task_id';
      if (!(Number.isInteger(value) || (allowsNull && value === null))) {
        throw new Error(`session field ${key} must be an integer, got ${JSON.stringify(value)}`);
      }
    }
    if (!modes.includes(state.mode)) {
      throw new Error(`unknown session mode: ${state.mode}`);
    }
  }

  /**
   * Crea el acceso al estado de la sesión de un contexto.
   *
   * @param {object} deps - Dependencias.
   * @param {object} deps.platform - Adaptador de plataforma.
   * @param {string[]} deps.modes - Modos de sesión del contrato (`session_mode`).
   * @returns {object} Estado con `ready`, `get`, `reload`, `start`, `update`,
   *   `clear` y `subscribe`.
   */
  function createSession({ platform, modes }) {
    const store = platform.storage('session');
    const listeners = new Set();
    let state = null;
    let changedBeforeReady = false;

    /** Actualiza la copia en memoria y avisa a los suscriptores si cambió. */
    function apply(next) {
      const value = next === undefined || next === null ? null : Object.freeze({ ...next });
      if (JSON.stringify(value) === JSON.stringify(state)) {
        return;
      }
      state = value;
      for (const listener of [...listeners]) {
        try {
          listener(state);
        } catch (error) {
          console.error('session listener failed', error);
        }
      }
    }

    store.onChanged(STORAGE_KEY, (value) => {
      changedBeforeReady = true;
      apply(value);
    });
    // Si el estado cambió mientras se leía, la lectura ya es vieja y se descarta.
    const ready = store.get(STORAGE_KEY).then((value) => {
      if (!changedBeforeReady) {
        apply(value);
      }
    });

    async function write(next) {
      validate(next, modes);
      await store.set(STORAGE_KEY, next);
      apply(next);
    }

    return Object.freeze({
      /** Promesa que se cumple cuando la copia en memoria tiene el estado guardado. */
      ready,

      /**
       * Devuelve el estado de la sesión activa.
       *
       * @returns {(object|null)} Estado congelado, o `null` si no hay sesión
       *   (o todavía no se cumplió `ready`).
       */
      get: () => state,

      /**
       * Vuelve a leer el estado guardado. Sirve cuando otro contexto acaba de
       * escribirlo y el aviso de cambio todavía no llegó.
       *
       * @returns {Promise<(object|null)>} Estado actual.
       */
      async reload() {
        apply(await store.get(STORAGE_KEY));
        return state;
      },

      /**
       * Inicia una sesión. Lo llama el panel después de crearla en el servidor.
       *
       * @param {{session_id: number, mode: string, study_id: number, tab_id: number}} info -
       *   Datos de la sesión y pestaña evaluada.
       * @returns {Promise<void>}
       */
      start: (info) => write({ ...info, task_id: null }),

      /**
       * Cambia campos del estado, por ejemplo `{ task_id: 3 }`.
       *
       * @param {object} changes - Campos a cambiar.
       * @returns {Promise<void>}
       */
      async update(changes) {
        await ready;
        if (state === null) {
          throw new Error('no active session to update');
        }
        await write({ ...state, ...changes });
      },

      /**
       * Borra el estado: ya no hay sesión activa.
       *
       * @returns {Promise<void>}
       */
      async clear() {
        await store.remove(STORAGE_KEY);
        apply(null);
      },

      /**
       * Se suscribe a los cambios del estado, de este contexto o de otro.
       *
       * @param {function((object|null)): void} listener - Recibe el estado nuevo.
       * @returns {function(): void} Función que cancela la suscripción.
       */
      subscribe(listener) {
        listeners.add(listener);
        return () => listeners.delete(listener);
      },
    });
  }

  UX.createSession = createSession;
  if (UX.platform) {
    UX.session = createSession({
      platform: UX.platform,
      modes: UX.contracts.enums.session_mode,
    });
  }
})(globalThis);
