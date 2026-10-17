/**
 * @file Lógica del panel lateral, sin DOM: estudios, inicio y cierre de la
 * sesión. La vista (`panel.js`) solo muestra el estado que publica este
 * controlador y le pasa lo que hace el evaluador.
 *
 * El estado es un objeto inmutable con:
 * - `phase`: `loading`, `idle` (sin sesión), `starting`, `active` o `closing`;
 * - `studies`: estudios del servidor (`id`, `name`, …);
 * - `session`: estado de la sesión activa (`UX.session.get()`), o `null`;
 * - `tab`: título y URL de la pestaña evaluada, si se conocen;
 * - `tabStatus`: `capturing` (la pestaña inició sus módulos), `pending` (la
 *   pestaña no respondió) o `unknown` (el panel se abrió con la sesión en curso);
 * - `failedModules`: módulos que no arrancaron en la pestaña;
 * - `error`: `{ code, fields, detail }` o `null`; `notice`: `{ code, session_id }` o `null`.
 *
 * Los códigos de error y de aviso son claves de `strings.js`.
 */

(function (root) {
  'use strict';

  const UX = (root.UX = root.UX || {});

  /** Fases del panel. */
  const PHASES = Object.freeze({
    LOADING: 'loading',
    IDLE: 'idle',
    STARTING: 'starting',
    ACTIVE: 'active',
    CLOSING: 'closing',
  });

  /** Chrome no inyecta content scripts en sus propias páginas: solo se evalúan páginas web. */
  const EVALUABLE_URL = /^https?:\/\//;

  /**
   * Traduce un error del servidor o de los mensajes a un código para la vista.
   *
   * @param {Error} error - Error recibido; los del servidor traen `status` y `errors`.
   * @returns {{code: string, fields: string[], detail: string}} Error para la vista.
   */
  function describeError(error) {
    if (error.status === 0) {
      return { code: 'server_unreachable', fields: [], detail: error.message };
    }
    if (error.status === 422) {
      const fields = (error.errors || []).map((item) => item.field).filter(Boolean);
      return { code: 'invalid_request', fields, detail: error.message };
    }
    return { code: 'unexpected', fields: [], detail: error.message };
  }

  /**
   * Crea la lógica del panel lateral.
   *
   * @param {object} deps - Dependencias.
   * @param {object} deps.api - Cliente del servidor (`UX.api`).
   * @param {object} deps.session - Estado de la sesión (`UX.session`).
   * @param {object} deps.messages - Canal de mensajes (`UX.messages`).
   * @param {object} deps.batcher - Acumulador del panel (`UX.batcher`).
   * @param {{activeTab: Function}} deps.platform - Adaptador de plataforma.
   * @param {{screen: {width: number, height: number}, devicePixelRatio: number,
   *   chromeVersion: function(): Promise<string>}} deps.environment - Datos de
   *   la pantalla y del navegador para `screen_info`.
   * @returns {object} Controlador con `init`, `loadStudies`, `startSession`,
   *   `closeSession`, `getState` y `subscribe`.
   */
  function createPanelController({ api, session, messages, batcher, platform, environment }) {
    const { types } = messages;
    const listeners = new Set();
    let state = Object.freeze({
      phase: PHASES.LOADING,
      studies: [],
      session: null,
      tab: null,
      tabStatus: null,
      failedModules: [],
      error: null,
      notice: null,
    });

    function setState(changes) {
      state = Object.freeze({ ...state, ...changes });
      for (const listener of [...listeners]) {
        listener(state);
      }
    }

    /** Estado de "sin sesión", conservando los estudios. */
    const idle = (changes = {}) => ({
      phase: PHASES.IDLE,
      session: null,
      tab: null,
      tabStatus: null,
      failedModules: [],
      ...changes,
    });

    /** Avisa a la pestaña evaluada que empezó la sesión y anota si respondió. */
    async function announce(current) {
      try {
        const reply = await messages.send(types.SESSION_STARTED, {
          session_id: current.session_id,
          mode: current.mode,
          study_id: current.study_id,
        });
        // Solo la pestaña evaluada responde con la lista de módulos; otra respuesta no confirma nada.
        if (reply && Array.isArray(reply.started)) {
          setState({ tabStatus: 'capturing', failedModules: reply.failed || [] });
        } else {
          setState({ tabStatus: 'pending' });
        }
      } catch (error) {
        // Sin content scripts todavía: la pestaña inicia sus módulos al cargar una página.
        setState({ tabStatus: 'pending' });
      }
    }

    /** Lleva el panel al estado de la sesión cuando otro panel la cambia. */
    function follow(current) {
      if (current === null && state.phase === PHASES.ACTIVE) {
        setState(idle());
      } else if (current !== null && state.phase === PHASES.IDLE) {
        setState({ phase: PHASES.ACTIVE, session: current, tabStatus: 'unknown' });
      } else if (current !== null) {
        setState({ session: current });
      }
    }

    /**
     * Carga los estudios del servidor.
     *
     * @returns {Promise<void>}
     */
    async function loadStudies() {
      try {
        setState({ studies: await api.listStudies(), error: null });
      } catch (error) {
        setState({ error: describeError(error) });
      }
    }

    return Object.freeze({
      /**
       * Prepara el panel: estudios y, si la hay, la sesión en curso.
       *
       * @returns {Promise<void>}
       */
      async init() {
        session.subscribe(follow);
        await loadStudies();
        // Se relee lo guardado: otro contexto pudo escribirlo y su aviso no haber llegado.
        const current = await session.reload();
        setState(
          current === null
            ? idle()
            : { phase: PHASES.ACTIVE, session: current, tabStatus: 'unknown' },
        );
      },

      loadStudies,

      /**
       * Crea una sesión en el servidor para la pestaña activa y la inicia.
       *
       * @param {{study_id: number, participant_id: string, version: string,
       *   mode: string}} form - Datos que eligió el evaluador.
       * @returns {Promise<void>}
       */
      async startSession(form) {
        if (state.phase !== PHASES.IDLE) {
          return;
        }
        setState({ phase: PHASES.STARTING, error: null, notice: null });
        try {
          const tab = await platform.activeTab();
          if (tab === null || !EVALUABLE_URL.test(tab.url || '')) {
            setState(idle({ error: { code: 'tab_not_evaluable', fields: [], detail: '' } }));
            return;
          }
          const created = await api.createSession({
            study_id: form.study_id,
            participant_id: form.participant_id,
            version: form.version,
            mode: form.mode,
            screen_info: {
              window_width: tab.width,
              window_height: tab.height,
              screen_width: environment.screen.width,
              screen_height: environment.screen.height,
              device_pixel_ratio: environment.devicePixelRatio,
              chrome_version: await environment.chromeVersion(),
            },
          });
          await session.start({
            session_id: created.session_id,
            mode: form.mode,
            study_id: form.study_id,
            tab_id: tab.id,
          });
          setState({
            phase: PHASES.ACTIVE,
            session: session.get(),
            tab: { title: tab.title, url: tab.url },
          });
          await announce(session.get());
        } catch (error) {
          setState(idle({ error: describeError(error) }));
        }
      },

      /**
       * Cierra la sesión activa. El cierre en el servidor lo hace el worker,
       * después de los últimos lotes de la pestaña.
       *
       * @returns {Promise<void>}
       */
      async closeSession() {
        const current = session.get();
        if (state.phase !== PHASES.ACTIVE || current === null) {
          return;
        }
        setState({ phase: PHASES.CLOSING, error: null });
        try {
          await batcher.flush();
          await messages.send(types.SESSION_CLOSED, { session_id: current.session_id });
          await session.clear();
          setState(idle({ notice: { code: 'session_closed', session_id: current.session_id } }));
        } catch (error) {
          setState({ phase: PHASES.ACTIVE, error: describeError(error) });
        }
      },

      /**
       * Devuelve el estado actual del panel.
       *
       * @returns {object} Estado inmutable.
       */
      getState: () => state,

      /**
       * Se suscribe a los cambios de estado.
       *
       * @param {function(object): void} listener - Recibe el estado nuevo.
       * @returns {function(): void} Función que cancela la suscripción.
       */
      subscribe(listener) {
        listeners.add(listener);
        return () => listeners.delete(listener);
      },
    });
  }

  UX.PANEL_PHASES = PHASES;
  UX.createPanelController = createPanelController;
})(globalThis);
