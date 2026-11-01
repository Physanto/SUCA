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
      message.textContent = text(strings.notices[notice.code], notice.session_id);
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
    renderGuided(state);
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
  });

  fillStrings();
  controller.subscribe(render);
  render(controller.getState());

  byId('start-form').addEventListener('submit', (event) => {
    event.preventDefault();
    controller.startSession(readForm());
  });
  byId('close').addEventListener('click', () => controller.closeSession());
  byId('retry').addEventListener('click', () => controller.retry());
  byId('task-start').addEventListener('click', () => controller.startTask());
  byId('task-done').addEventListener('click', () => controller.endTask('done'));
  byId('task-gave-up').addEventListener('click', () => controller.endTask('gave_up'));

  controller.init();
})(globalThis);
