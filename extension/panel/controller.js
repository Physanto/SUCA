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
 * - `error`: `{ code, fields, detail }` o `null`; `notice`: `{ code, session_id }` o `null`;
 * - `guided`: solo en modo guiado, `null` en los demás. Tiene `loaded` (si ya
 *   llegaron las tareas), `tasks` (las del estudio, en orden), `index` (posición
 *   de la tarea que toca; igual a `tasks.length` cuando se terminaron todas) y
 *   `current` (`{ task_id, t_start }` de la tarea en curso, o `null`).
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

  /** Formas de terminar una tarea con un botón del panel (`ended_by` del contrato). */
  const BUTTON_ENDS = Object.freeze(['done', 'gave_up']);

  /**
   * Condición final de una tarea: la de su primera referencia confirmada (la de
   * menor `id`), o `null` si no tiene.
   *
   * @param {{references: Array<{id: number, end_condition: object}>}} task - Tarea del servidor.
   * @returns {(object|null)} Condición final para `task.started`.
   */
  function endConditionOf(task) {
    const [first] = [...(task.references || [])].sort((a, b) => a.id - b.id);
    return first ? first.end_condition : null;
  }

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
   * @param {{now: function(): number}} deps.clock - Reloj común (`UX.clock`), el de
   *   las marcas de tiempo de todos los registros.
   * @param {{activeTab: Function}} deps.platform - Adaptador de plataforma.
   * @param {{screen: {width: number, height: number}, devicePixelRatio: number,
   *   chromeVersion: function(): Promise<string>}} deps.environment - Datos de
   *   la pantalla y del navegador para `screen_info`.
   * @returns {object} Controlador con `init`, `loadStudies`, `loadTasks`, `retry`,
   *   `startSession`, `startTask`, `endTask`, `closeSession`, `getState` y `subscribe`.
   */
  function createPanelController({
    api,
    session,
    messages,
    batcher,
    clock,
    platform,
    environment,
  }) {
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
      guided: null,
    });

    /** Publica un estado nuevo, con los cambios dados, a la vista. */
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
      guided: null,
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
        loadTasks();
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

    /**
     * Carga las tareas del estudio de una sesión guiada. En otros modos no hace nada.
     *
     * Si el panel se abrió con una tarea en curso, la retoma: el estado de la
     * sesión guarda cuál es (`task_id`), pero no cuándo empezó, así que su
     * `t_start` pasa a ser el momento de reabrir el panel.
     *
     * @returns {Promise<void>}
     */
    async function loadTasks() {
      const current = session.get();
      if (current === null || current.mode !== 'guided') {
        return;
      }
      try {
        const tasks = await api.listTasks(current.study_id);
        const running = tasks.findIndex((task) => task.id === current.task_id);
        setState({
          guided: {
            loaded: true,
            tasks,
            index: Math.max(running, 0),
            current: running >= 0 ? { task_id: current.task_id, t_start: clock.now() } : null,
          },
          error: null,
        });
      } catch (error) {
        setState({
          guided: { loaded: false, tasks: [], index: 0, current: null },
          error: describeError(error),
        });
      }
    }

    /**
     * Cierra la tarea en curso: guarda su registro en el lote `tasks`, deja la
     * sesión sin tarea activa y pasa a la siguiente.
     *
     * @param {string} endedBy - Forma en que terminó (`ended_by` del contrato).
     * @param {number} [onlyTask] - Si se da, solo cierra la tarea en curso con ese id.
     * @returns {Promise<void>}
     */
    async function finishTask(endedBy, onlyTask) {
      const { guided } = state;
      if (state.phase !== PHASES.ACTIVE || guided === null || guided.current === null) {
        return;
      }
      if (onlyTask !== undefined && guided.current.task_id !== onlyTask) {
        return;
      }
      const { task_id, t_start } = guided.current;
      // El estado cambia antes de esperar, para que un segundo clic no repita el registro.
      setState({ guided: { ...guided, index: guided.index + 1, current: null }, error: null });
      batcher.add('tasks', {
        task_id,
        t_start,
        t_end: Math.max(clock.now(), t_start),
        ended_by: endedBy,
      });
      try {
        await session.update({ task_id: null });
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
        // La pestaña avisa cuando la página llegó a la condición final de la tarea.
        messages.on(types.TASK_COMPLETED, ({ task_id, ended_by }) =>
          ended_by === 'reference' ? finishTask('reference', task_id) : undefined,
        );
        await loadStudies();
        // Se relee lo guardado: otro contexto pudo escribirlo y su aviso no haber llegado.
        const current = await session.reload();
        setState(
          current === null
            ? idle()
            : { phase: PHASES.ACTIVE, session: current, tabStatus: 'unknown' },
        );
        await loadTasks();
      },

      loadStudies,

      loadTasks,

      /**
       * Repite lo que falló al cargar: los estudios y, en una sesión guiada, las tareas.
       *
       * @returns {Promise<void>}
       */
      async retry() {
        await loadStudies();
        if (state.guided !== null && !state.guided.loaded) {
          await loadTasks();
        }
      },

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
          await loadTasks();
        } catch (error) {
          setState(idle({ error: describeError(error) }));
        }
      },

      /**
       * Empieza la tarea que toca: la anota en el estado de la sesión, para que
       * la captura marque con ella sus registros, y avisa a la pestaña con su
       * condición final (o `null` si la tarea no tiene referencia confirmada).
       *
       * @returns {Promise<void>}
       */
      async startTask() {
        const { guided } = state;
        if (state.phase !== PHASES.ACTIVE || guided === null || guided.current !== null) {
          return;
        }
        const task = guided.tasks[guided.index];
        if (task === undefined) {
          return;
        }
        const t_start = clock.now();
        // El estado cambia antes de esperar, para que un segundo clic no repita el inicio.
        setState({ guided: { ...guided, current: { task_id: task.id, t_start } }, error: null });
        try {
          await session.update({ task_id: task.id });
        } catch (error) {
          setState({ guided, error: describeError(error) });
          return;
        }
        try {
          await messages.send(types.TASK_STARTED, {
            task_id: task.id,
            end_condition: endConditionOf(task),
          });
        } catch (error) {
          // Sin content scripts, la tarea sigue y termina con los botones.
          setState({ tabStatus: 'pending' });
        }
      },

      /**
       * Termina la tarea en curso con un botón y pasa a la siguiente. Guarda su
       * registro en el lote `tasks`.
       *
       * @param {string} endedBy - `done` (Terminé) o `gave_up` (No pude).
       * @returns {Promise<void>}
       */
      async endTask(endedBy) {
        if (!BUTTON_ENDS.includes(endedBy)) {
          throw new Error(`a button cannot end a task with ${endedBy}`);
        }
        await finishTask(endedBy);
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
