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
 * - `startedAt`: marca de tiempo del inicio de la sesión según el reloj común, o `null` si
 *   se desconoce (el panel se abrió con la sesión en curso: el estado de la sesión no la guarda);
 * - `guided`: solo en modo guiado, `null` en los demás. Tiene `loaded` (si ya
 *   llegaron las tareas), `tasks` (las del estudio, en orden), `index` (posición
 *   de la tarea que toca; igual a `tasks.length` cuando se terminaron todas) y
 *   `current` (`{ task_id, t_start }` de la tarea en curso, o `null`);
 * - `reference`: solo en modo referencia, `null` en los demás. Tiene `loaded`, `tasks` (las
 *   del estudio), `recording` (`{ task_id, t_start }` de la tarea que se graba, o `null`),
 *   `saved` (`{ task_id, reference_id }` de las que ya se guardaron en esta sesión) y
 *   `unsaved` (tarea grabada cuyo guardado falló y espera un reintento, o `null`);
 * - `camera`: estado que informa la cámara (`active`, `no_permission` o `error`), o
 *   `null` si no ha informado (el aviso llega al abrirla y al cambiar, no al abrir el panel);
 * - `calibration`: `pending` (tipo pedido, `initial` o `final`, o `null`) y el último
 *   resultado de cada tipo, `{ error_px, error_deg, accepted }` o `null`.
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

  /** Calibración sin pedir y sin resultados. */
  const NO_CALIBRATION = Object.freeze({ pending: null, initial: null, final: null });

  /** Tipos de calibración del contrato. */
  const CALIBRATION_TYPES = Object.freeze(['initial', 'final']);

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
   *   `startSession`, `startTask`, `endTask`, `startRecording`, `stopRecording`, `retrySave`,
   *   `requestCalibration`, `closeSession`, `getState` y `subscribe`.
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
      startedAt: null,
      guided: null,
      reference: null,
      camera: null,
      calibration: NO_CALIBRATION,
    });
    /** Hay un guardado de referencia en curso (evita repetirlo con un segundo clic). */
    let saving = false;

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
      startedAt: null,
      guided: null,
      reference: null,
      camera: null,
      calibration: NO_CALIBRATION,
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
     * Carga las tareas del estudio de una sesión guiada o de referencia. En el
     * modo libre no hace nada.
     *
     * Si el panel se abrió con una tarea en curso, la retoma: el estado de la
     * sesión guarda cuál es (`task_id`), pero no cuándo empezó, así que su
     * `t_start` pasa a ser el momento de reabrir el panel.
     *
     * @returns {Promise<void>}
     */
    async function loadTasks() {
      const current = session.get();
      if (current === null || !['guided', 'reference'].includes(current.mode)) {
        return;
      }
      const isGuided = current.mode === 'guided';
      try {
        const tasks = await api.listTasks(current.study_id);
        const running = tasks.findIndex((task) => task.id === current.task_id);
        const resumed = running >= 0 ? { task_id: current.task_id, t_start: clock.now() } : null;
        setState({
          ...(isGuided
            ? { guided: { loaded: true, tasks, index: Math.max(running, 0), current: resumed } }
            : { reference: { loaded: true, tasks, recording: resumed, saved: [], unsaved: null } }),
          error: null,
        });
      } catch (error) {
        setState({
          ...(isGuided
            ? { guided: { loaded: false, tasks: [], index: 0, current: null } }
            : {
                reference: { loaded: false, tasks: [], recording: null, saved: [], unsaved: null },
              }),
          error: describeError(error),
        });
      }
    }

    /**
     * Guarda en el servidor la referencia de una tarea ya grabada: primero vacía
     * el acumulador, para que el registro de la tarea y sus eventos salgan antes.
     * Si falla, la tarea queda en `unsaved` para reintentar.
     *
     * @param {number} taskId - Tarea grabada.
     * @returns {Promise<void>}
     */
    async function saveReference(taskId) {
      const current = session.get();
      if (saving || current === null) {
        return;
      }
      saving = true;
      try {
        await batcher.flush();
        const created = await api.createReference({
          task_id: taskId,
          source_session_id: current.session_id,
        });
        const { reference } = state;
        if (reference !== null) {
          setState({
            reference: {
              ...reference,
              unsaved: null,
              saved: [...reference.saved, { task_id: taskId, reference_id: created.reference_id }],
            },
            notice: { code: 'reference_saved', task_id: taskId, reference_id: created.reference_id },
            error: null,
          });
        }
      } catch (error) {
        setState({ error: describeError(error) });
      } finally {
        saving = false;
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
        // La cámara informa su estado y el resultado de cada calibración que se pidió.
        messages.on(types.CAMERA_STATUS, ({ status }) => {
          if (state.phase !== PHASES.IDLE) {
            setState({ camera: status });
          }
        });
        messages.on(types.CALIBRATION_RESULT, ({ error_px, error_deg, accepted }) => {
          // El resultado no dice de qué calibración es: es la que se pidió último.
          const { pending } = state.calibration;
          if (state.phase !== PHASES.IDLE && pending !== null) {
            setState({
              calibration: { ...state.calibration, [pending]: { error_px, error_deg, accepted } },
            });
          }
        });
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
        const tasks = state.guided || state.reference;
        if (tasks !== null && !tasks.loaded) {
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
            startedAt: clock.now(),
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
       * Empieza a grabar una tarea en modo referencia: la anota en el estado de la
       * sesión, para que la captura marque con ella sus registros, y avisa a la
       * pestaña sin condición final (la grabación la termina el evaluador).
       *
       * @param {number} taskId - Tarea que se graba; una vez por sesión.
       * @returns {Promise<void>}
       */
      async startRecording(taskId) {
        const { reference } = state;
        if (
          state.phase !== PHASES.ACTIVE ||
          reference === null ||
          reference.recording !== null ||
          reference.unsaved !== null ||
          !reference.tasks.some((task) => task.id === taskId) ||
          reference.saved.some((item) => item.task_id === taskId)
        ) {
          return;
        }
        // El estado cambia antes de esperar, para que un segundo clic no repita el inicio.
        setState({
          reference: { ...reference, recording: { task_id: taskId, t_start: clock.now() } },
          error: null,
          notice: null,
        });
        try {
          await session.update({ task_id: taskId });
        } catch (error) {
          setState({ reference, error: describeError(error) });
          return;
        }
        try {
          await messages.send(types.TASK_STARTED, { task_id: taskId, end_condition: null });
        } catch (error) {
          // Sin content scripts, la grabación sigue: la captura lee la tarea de la sesión.
          setState({ tabStatus: 'pending' });
        }
      },

      /**
       * Termina la grabación en curso y guarda su referencia en borrador. El
       * registro de la tarea sale con `ended_by: done`.
       *
       * @returns {Promise<void>}
       */
      async stopRecording() {
        const { reference } = state;
        if (state.phase !== PHASES.ACTIVE || reference === null || reference.recording === null) {
          return;
        }
        const { task_id, t_start } = reference.recording;
        // El estado cambia antes de esperar, para que un segundo clic no repita el registro.
        setState({
          reference: { ...reference, recording: null, unsaved: task_id },
          error: null,
          notice: null,
        });
        batcher.add('tasks', {
          task_id,
          t_start,
          t_end: Math.max(clock.now(), t_start),
          ended_by: 'done',
        });
        try {
          await session.update({ task_id: null });
        } catch (error) {
          setState({ error: describeError(error) });
        }
        await saveReference(task_id);
      },

      /**
       * Repite el guardado de la referencia de una tarea grabada que no se pudo guardar.
       *
       * @returns {Promise<void>}
       */
      async retrySave() {
        const { reference } = state;
        if (state.phase === PHASES.ACTIVE && reference !== null && reference.unsaved !== null) {
          await saveReference(reference.unsaved);
        }
      },

      /**
       * Pide una calibración de mirada a la cámara de la pestaña evaluada. Con la
       * cámara sin permiso o con error no se pide: la sesión sigue sin ella.
       *
       * @param {string} type - `initial` o `final`.
       * @returns {Promise<void>}
       */
      async requestCalibration(type) {
        if (!CALIBRATION_TYPES.includes(type)) {
          throw new Error(`unknown calibration type: ${type}`);
        }
        const { camera } = state;
        if (state.phase !== PHASES.ACTIVE || (camera !== null && camera !== 'active')) {
          return;
        }
        setState({ calibration: { ...state.calibration, pending: type, [type]: null }, error: null });
        try {
          await messages.send(types.CALIBRATION_REQUEST, { type });
        } catch (error) {
          setState({
            calibration: { ...state.calibration, pending: null },
            error: { code: 'calibration_unavailable', fields: [], detail: error.message },
          });
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
