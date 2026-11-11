/**
 * @file Vista del panel lateral: muestra el estado del controlador en el HTML
 * y le pasa las acciones del evaluador. No tiene lógica de sesión.
 *
 * Es el punto de composición del panel: crea el controlador con las
 * utilidades comunes (`UX.api`, `UX.session`, `UX.messages`, `UX.batcher`,
 * `UX.platform`) y los datos de la pantalla. Los textos salen de `UX.strings`.
 */

(function (root) {
  'use strict';

  const { UX } = root;
  const { document } = root;
  const strings = UX.strings;
  /** Elemento del panel por su id. */
  const byId = (id) => document.getElementById(id);

  /** Busca un texto por su ruta, por ejemplo `modes.free`. */
  const lookup = (path) => path.split('.').reduce((node, key) => node && node[key], strings);

  /** Devuelve un texto que puede ser una función de sus datos. */
  const text = (value, ...args) => (typeof value === 'function' ? value(...args) : value);

  /**
   * Versión completa de Chrome. `userAgentData` da los cuatro números; el
   * `userAgent` reducido solo da la versión mayor, y se usa como respaldo.
   */
  async function chromeVersion() {
    const data = root.navigator.userAgentData;
    if (data && data.getHighEntropyValues) {
      const { fullVersionList = [] } = await data.getHighEntropyValues(['fullVersionList']);
      const brand = fullVersionList.find((item) => /Chrome|Chromium/.test(item.brand));
      if (brand) {
        return brand.version;
      }
    }
    const match = /Chrome\/([\d.]+)/.exec(root.navigator.userAgent);
    return match ? match[1] : 'unknown';
  }

  /** Pone los textos fijos de `strings.js` en el HTML. */
  function fillStrings() {
    for (const element of document.querySelectorAll('[data-string]')) {
      element.textContent = lookup(element.dataset.string);
    }
    for (const element of document.querySelectorAll('[data-placeholder]')) {
      element.placeholder = lookup(element.dataset.placeholder);
    }
    const modeSelect = byId('mode');
    for (const mode of UX.contracts.enums.session_mode) {
      modeSelect.append(new Option(strings.modes[mode], mode));
    }
  }

  /** Rehace la lista de estudios si cambió, conservando la selección. */
  function renderStudies(studies) {
    const select = byId('study');
    const ids = studies.map((study) => String(study.id));
    if ([...select.options].map((option) => option.value).join() === ids.join()) {
      return;
    }
    const selected = select.value;
    select.replaceChildren(...studies.map((study) => new Option(study.name, String(study.id))));
    if (ids.includes(selected)) {
      select.value = selected;
    }
  }

  /** Número de orden de una tarea del estudio, para nombrarla en los avisos. */
  function positionOf(state, taskId) {
    const task = ((state.reference || state.guided || {}).tasks || []).find((item) => item.id === taskId);
    return task ? task.position : taskId;
  }

  /** Muestra el error o el aviso general y marca los campos con problemas. */
  function renderMessage(state) {
    const message = byId('message');
    const { error, notice } = state;
    message.hidden = error === null && notice === null;
    message.className = error ? 'message error' : 'message notice';
    if (error) {
      const known = error.fields.filter((field) => field in strings.fieldErrors);
      message.textContent =
        error.code in strings.errors ? text(strings.errors[error.code], error.detail) : error.detail;
      if (error.code === 'invalid_request' && known.length < error.fields.length) {
        message.textContent += ` (${error.detail})`;
      }
    } else if (notice) {
      message.textContent = text(strings.notices[notice.code], notice.session_id, {
        ...notice,
        position: positionOf(state, notice.task_id),
      });
    }
    for (const fieldError of document.querySelectorAll('[data-field]')) {
      const field = fieldError.dataset.field;
      const invalid = Boolean(error && error.fields.includes(field));
      fieldError.hidden = !invalid;
      fieldError.textContent = invalid ? strings.fieldErrors[field] : '';
      const input = document.querySelector(`[name="${field}"]`);
      if (input) {
        input.setAttribute('aria-invalid', String(invalid));
      }
    }
    byId('retry').hidden = !(error && error.code === 'server_unreachable');
  }

  /** Muestra la sesión en curso. */
  function renderActive(state) {
    const current = state.session;
    if (current === null) {
      return;
    }
    const study = state.studies.find((item) => item.id === current.study_id);
    byId('active-session').textContent = String(current.session_id);
    byId('active-study').textContent = study ? study.name : String(current.study_id);
    byId('active-mode').textContent = strings.modes[current.mode];
    byId('active-tab').textContent = state.tab ? state.tab.title || state.tab.url : strings.tabUnknown;
    const capture = [strings.tabStatus[state.tabStatus] || ''];
    if (state.failedModules.length > 0) {
      capture.push(strings.failedModules(state.failedModules));
    }
    byId('active-capture').textContent = capture.join(' ');
  }

  /** Muestra la grabación de referencia: la tarea a elegir, la que se graba y las ya guardadas. */
  function renderReference(state) {
    const reference = state.reference;
    const visible = reference !== null && ['active', 'closing'].includes(state.phase);
    byId('reference-section').hidden = !visible;
    if (!visible) {
      return;
    }
    const positionOfTask = (taskId) => positionOf(state, taskId);
    const saved = new Set(reference.saved.map((item) => item.task_id));
    const available = reference.tasks.filter((task) => !saved.has(task.id));
    const busy = reference.recording !== null || reference.unsaved !== null;

    const status = byId('reference-status');
    if (!reference.loaded) {
      status.textContent = state.error ? '' : strings.referenceLoading;
    } else if (reference.tasks.length === 0) {
      status.textContent = strings.referenceNoTasks;
    } else if (available.length === 0 && !busy) {
      status.textContent = strings.referenceAllRecorded;
    } else {
      status.textContent = '';
    }
    status.hidden = status.textContent === '';

    // La lista se rehace solo si cambian las tareas disponibles, para conservar la elección.
    const select = byId('reference-task');
    const ids = available.map((task) => String(task.id));
    if ([...select.options].map((option) => option.value).join() !== ids.join()) {
      const chosen = select.value;
      select.replaceChildren(
        ...available.map(
          (task) => new Option(strings.referenceTaskOption(task.position, task.instruction), String(task.id)),
        ),
      );
      if (ids.includes(chosen)) {
        select.value = chosen;
      }
    }
    byId('reference-picker').hidden = busy || available.length === 0;
    byId('reference-start').disabled = state.phase === 'closing';

    const recording = byId('reference-recording');
    if (reference.recording !== null) {
      recording.textContent = strings.referenceRecording(positionOfTask(reference.recording.task_id));
    } else if (reference.unsaved !== null) {
      recording.textContent = strings.referenceUnsaved(positionOfTask(reference.unsaved));
    }
    recording.hidden = !busy;
    byId('reference-stop').hidden = reference.recording === null;
    byId('reference-stop').disabled = state.phase === 'closing';
    byId('reference-retry').hidden = reference.unsaved === null;
    byId('reference-retry').disabled = state.phase === 'closing';

    byId('capture-screen').disabled = reference.capturing || state.phase === 'closing';
    byId('capture-list').replaceChildren(
      ...reference.captures.map((item) => {
        const line = document.createElement('li');
        line.textContent = strings.captureItem(item.capture_id, item.url);
        return line;
      }),
    );

    byId('reference-saved').replaceChildren(
      ...reference.saved.map((item) => {
        const line = document.createElement('li');
        line.textContent = strings.referenceSavedItem(positionOfTask(item.task_id), item.reference_id);
        return line;
      }),
    );
  }

  /** Muestra el tiempo transcurrido de la sesión libre. */
  function renderElapsed(state) {
    const visible = state.session !== null && state.session.mode === 'free';
    byId('elapsed-label').hidden = !visible;
    byId('active-elapsed').hidden = !visible;
    if (visible) {
      byId('active-elapsed').textContent =
        state.startedAt === null
          ? strings.elapsedUnknown
          : strings.elapsedTime(UX.clock.now() - state.startedAt);
    }
  }

  /** Muestra el estado de la cámara y los botones y resultados de la calibración. */
  function renderCamera(state) {
    const status = state.camera === null ? 'unknown' : state.camera;
    byId('camera-status').textContent = strings.cameraStatus[status];
    // Solo se bloquea cuando se sabe que la cámara no sirve; la sesión sigue igual.
    const blocked = !['unknown', 'active'].includes(status) || state.phase === 'closing';
    for (const type of ['initial', 'drift_check', 'final']) {
      const button = byId(`calibrate-${type}`);
      button.textContent = strings.calibrationButtons[type];
      button.disabled = blocked;
      const result = state.calibration[type];
      byId(`calibration-${type}`).textContent = result
        ? strings.calibrationResult(result)
        : state.calibration.pending === type
          ? strings.calibrationWaiting
          : '';
    }
  }

  /** Muestra la tarea que toca en el modo guiado, con los botones que corresponden. */
  function renderGuided(state) {
    const guided = state.guided;
    const visible = guided !== null && ['active', 'closing'].includes(state.phase);
    byId('guided-section').hidden = !visible;
    if (!visible) {
      return;
    }
    const total = guided.tasks.length;
    const task = guided.tasks[guided.index];
    const status = byId('tasks-status');
    if (!guided.loaded) {
      // Si la carga falló, el mensaje de error ya lo explica.
      status.textContent = state.error ? '' : strings.tasksLoading;
    } else if (total === 0) {
      status.textContent = strings.noTasks;
    } else {
      status.textContent = task === undefined ? strings.tasksFinished : '';
    }
    status.hidden = status.textContent === '';
    byId('task-progress').hidden = task === undefined;
    byId('task-instruction').hidden = task === undefined;
    if (task !== undefined) {
      byId('task-progress').textContent = strings.taskProgress(guided.index + 1, total);
      byId('task-instruction').textContent = task.instruction;
    }
    const running = guided.current !== null;
    byId('task-actions').hidden = task === undefined;
    byId('task-start').hidden = running;
    byId('task-done').hidden = !running;
    byId('task-gave-up').hidden = !running;
    byId('task-start').disabled = state.phase === 'closing';
  }

  /** Arma las 10 preguntas del SUS, cada una con sus cinco opciones, una sola vez. */
  function buildSus() {
    byId('sus-scale').textContent = strings.susScale;
    byId('sus-questions').replaceChildren(
      ...strings.susQuestions.map((question, index) => {
        const item = index + 1;
        const group = document.createElement('fieldset');
        const legend = document.createElement('legend');
        legend.textContent = strings.susQuestionLabel(item, question);
        const options = document.createElement('div');
        options.className = 'sus-options';
        for (let value = 1; value <= 5; value += 1) {
          const label = document.createElement('label');
          const input = document.createElement('input');
          input.type = 'radio';
          input.name = `sus-${item}`;
          input.value = String(value);
          input.dataset.item = String(item);
          label.append(input, String(value));
          options.append(label);
        }
        group.append(legend, options);
        return group;
      }),
    );
  }

  /** Muestra el cuestionario SUS cuando terminaron las tareas del modo guiado. */
  function renderSus(state) {
    const { guided } = state;
    const finished =
      guided !== null &&
      guided.loaded &&
      guided.tasks.length > 0 &&
      guided.index >= guided.tasks.length;
    const visible = finished && ['active', 'closing'].includes(state.phase);
    byId('sus-section').hidden = !visible;
    if (!visible) {
      return;
    }
    const { answers, saving, saved } = guided.sus;
    byId('sus-form').hidden = saved;
    byId('sus-saved').hidden = !saved;
    const locked = saving || state.phase === 'closing';
    for (const input of byId('sus-questions').querySelectorAll('input')) {
      input.checked = answers[Number(input.dataset.item) - 1] === Number(input.value);
      input.disabled = locked;
    }
    const missing = answers.filter((answer) => answer === null).length;
    byId('sus-missing').textContent = missing > 0 ? strings.susMissing(missing) : '';
    byId('sus-missing').hidden = missing === 0;
    byId('sus-send').disabled = missing > 0 || locked;
  }

  /**
   * Dibuja el estado completo del panel.
   *
   * @param {object} state - Estado del controlador.
   * @returns {void}
   */
  function render(state) {
    const { phase } = state;
    const busy = { loading: strings.loading, starting: strings.starting, closing: strings.closing };
    byId('status').hidden = !(phase in busy);
    byId('status').textContent = busy[phase] || '';

    byId('start-section').hidden = !['idle', 'starting'].includes(phase);
    byId('active-section').hidden = !['active', 'closing'].includes(phase);
    renderStudies(state.studies);
    byId('no-studies').hidden = state.studies.length > 0 || phase === 'loading';
    byId('start-fields').disabled = phase === 'starting' || state.studies.length === 0;
    byId('close').disabled = phase === 'closing';
    renderActive(state);
    renderElapsed(state);
    renderCamera(state);
    renderReference(state);
    renderGuided(state);
    renderSus(state);
    renderMessage(state);
  }

  /** Lee el formulario de inicio con los tipos que espera el controlador. */
  function readForm() {
    return {
      study_id: Number(byId('study').value),
      participant_id: byId('participant').value.trim(),
      version: byId('version').value.trim(),
      mode: byId('mode').value,
    };
  }

  const controller = UX.createPanelController({
    api: UX.api,
    session: UX.session,
    messages: UX.messages,
    batcher: UX.batcher,
    clock: UX.clock,
    platform: UX.platform,
    environment: {
      screen: { width: root.screen.width, height: root.screen.height },
      devicePixelRatio: root.devicePixelRatio,
      chromeVersion,
    },
    camera: UX.config.camera,
  });

  fillStrings();
  buildSus();
  controller.subscribe(render);
  render(controller.getState());

  byId('start-form').addEventListener('submit', (event) => {
    event.preventDefault();
    controller.startSession(readForm());
  });
  byId('close').addEventListener('click', () => controller.closeSession());
  for (const button of document.querySelectorAll('[data-calibration]')) {
    button.addEventListener('click', () => controller.requestCalibration(button.dataset.calibration));
  }
  byId('retry').addEventListener('click', () => controller.retry());
  byId('reference-start').addEventListener('click', () =>
    controller.startRecording(Number(byId('reference-task').value)),
  );
  byId('reference-stop').addEventListener('click', () => controller.stopRecording());
  byId('capture-screen').addEventListener('click', () => controller.captureScreen());
  byId('sus-questions').addEventListener('change', (event) =>
    controller.answerSus(Number(event.target.dataset.item), Number(event.target.value)),
  );
  byId('sus-send').addEventListener('click', () => controller.submitSus());
  byId('reference-retry').addEventListener('click', () => controller.retrySave());
  byId('task-start').addEventListener('click', () => controller.startTask());
  byId('task-done').addEventListener('click', () => controller.endTask('done'));
  byId('task-gave-up').addEventListener('click', () => controller.endTask('gave_up'));

  // El tiempo transcurrido avanza solo, sin esperar a un cambio de estado.
  setInterval(() => renderElapsed(controller.getState()), 1000);

  controller.init();
})(globalThis);
