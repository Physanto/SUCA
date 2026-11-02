/**
 * @file Fin de tarea (M2): en el modo guiado, revisa si la página llegó a la
 * condición final de la referencia de la tarea activa.
 *
 * La condición (`visible_text`, `url_pattern` o `element_present`) se revisa al
 * recibirla y después en cada cambio de la página o de la ruta, como máximo 4
 * veces por segundo (con una revisión final, para no perder el último cambio).
 * Solo revisa la condición final, no los pasos obligatorios: el éxito lo decide
 * el análisis.
 *
 * Cómo se compara:
 * - `visible_text`: el texto está en el texto visible de la página. No distingue
 *   mayúsculas y colapsa los espacios.
 * - `url_pattern`: coincide con la ruta completa de la URL, sin consulta. El
 *   fragmento solo cuenta si es una ruta (`#/carrito` o `#!/carrito`), como al
 *   agrupar pantallas en el análisis: con la ruta `/` queda solo la del fragmento
 *   y si no, `ruta#fragmento`. `{id}` vale por cualquier segmento; se ignora una
 *   barra final.
 * - `element_present`: hay un elemento visible con ese rol (explícito o el
 *   implícito de su etiqueta) y ese texto. El texto se lee con `innerText` y se
 *   compara recortado a 50 caracteres, como lo guarda la captura.
 *
 * Deja de revisar cuando la tarea activa de la sesión cambia (Terminé, No pude o
 * una tarea nueva) o la sesión se cierra. El aviso de `task.started` puede llegar
 * antes que el cambio de la sesión, por eso no se compara al revisar.
 *
 * La página se carga de nuevo en cada navegación y `task.started` llega una sola
 * vez, así que la condición se guarda en `storage.session` (clave propia de este
 * módulo, fuera del estado de la sesión) mientras la tarea siga activa.
 *
 * Mensajes:
 * - Recibe: `task.started` (`task_id`, `end_condition` o `null`) del panel
 *   lateral, vía worker. Con `null` no hay nada que revisar.
 * - Envía: `task.completed` (`task_id`, `ended_by: 'reference'`) al panel
 *   lateral cuando se cumple la condición.
 *
 * Nunca guarda el texto de la página: solo lo compara con la condición.
 */

(function (root) {
  'use strict';

  /** Clave de `storage.session` donde se guarda la condición de la tarea activa. */
  const STORAGE_KEY = 'task_end';
  /** Tiempo mínimo entre dos revisiones, en ms (4 por segundo). */
  const CHECK_INTERVAL_MS = 250;
  /** Largo máximo del texto de un elemento en la captura. */
  const TEXT_MAX_LENGTH = 50;
  const PAGE_EVENTS = ['popstate', 'hashchange'];

  /** Etiquetas que dan cada rol implícito, para no recorrer toda la página. */
  const ROLE_SELECTORS = {
    button: 'button,input[type="button"],input[type="submit"],input[type="reset"]',
    link: 'a[href]',
    heading: 'h1,h2,h3,h4,h5,h6',
    option: 'option',
    listitem: 'li',
  };
  const IMPLICIT_ROLES = { button: 'button', option: 'option', li: 'listitem' };
  const INPUT_BUTTON_TYPES = ['button', 'submit', 'reset'];

  /** Texto sin diferencias de espacios ni de mayúsculas. */
  const normalize = (text) => text.replace(/\s+/g, ' ').trim().toLowerCase();
  /** Texto de un elemento como lo guarda la captura: recortado a 50 caracteres, sin espacios sobrantes. */
  const cut = (text) => normalize(text).slice(0, TEXT_MAX_LENGTH).trim();

  /** Rol explícito del elemento o, si no tiene, el implícito de su etiqueta. */
  function roleOf(element) {
    const explicit = element.getAttribute('role');
    if (explicit) {
      return explicit;
    }
    const tag = element.tagName.toLowerCase();
    if (tag === 'input') {
      const type = (element.getAttribute('type') || 'text').toLowerCase();
      return INPUT_BUTTON_TYPES.includes(type) ? 'button' : null;
    }
    if (tag === 'a') {
      return element.hasAttribute('href') ? 'link' : null;
    }
    return /^h[1-6]$/.test(tag) ? 'heading' : IMPLICIT_ROLES[tag] || null;
  }

  /** Si el texto de la condición aparece en el texto visible de la página. */
  function hasVisibleText(condition) {
    const body = root.document.body;
    return body !== null && normalize(body.innerText || '').includes(normalize(condition.text));
  }

  /** Ruta sin barras finales; vacía queda como `/`. */
  const trimSlashes = (route) => route.replace(/\/+$/, '') || '/';
  /** Ruta y fragmento sin barras finales, cada uno por su lado. */
  const trimRoute = (route) => route.split('#').map(trimSlashes).join('#');

  /**
   * Ruta de la página como la agrupa el análisis en pantallas: la ruta de la URL y,
   * si el fragmento es una ruta de una SPA (`#/…` o `#!/…`), también esa ruta.
   */
  function currentRoute() {
    const url = new URL(root.location.href);
    const path = url.pathname || '/';
    const fragment = url.hash.slice(1).replace(/^!/, '');
    if (!fragment.startsWith('/')) {
      return path;
    }
    const route = fragment.split(/[?#]/)[0];
    return path === '/' ? route : `${path}#${route}`;
  }

  /** Si la ruta de la URL actual coincide con el patrón. */
  function matchesUrlPattern(condition) {
    const path = trimRoute(currentRoute());
    const pattern = trimRoute(condition.pattern);
    const source = pattern
      .split(/(\{id\})/)
      .map((part) => (part === '{id}' ? '[^/]+' : part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')))
      .join('');
    return new RegExp(`^${source}$`).test(path);
  }

  /** Si hay un elemento visible con el rol y el texto de la condición. */
  function hasElement(condition) {
    const escaped = condition.role.replace(/["\\]/g, '\\$&');
    const selector = [`[role="${escaped}"]`, ROLE_SELECTORS[condition.role]].filter(Boolean).join(',');
    const wanted = cut(condition.text);
    return [...root.document.querySelectorAll(selector)].some(
      (element) =>
        roleOf(element) === condition.role &&
        (!element.checkVisibility || element.checkVisibility()) &&
        // `innerText`, como la captura: separa los bloques internos y omite lo oculto.
        cut(element.innerText ?? element.textContent ?? '') === wanted,
    );
  }

  const CHECKS = { visible_text: hasVisibleText, url_pattern: matchesUrlPattern, element_present: hasElement };

  let ctx = null;
  let store = null;
  /** Tarea en revisión: `{ task_id, end_condition }`, o `null`. */
  let active = null;
  let observer = null;
  let timer = null;
  let timers = null;
  let lastCheck = -Infinity;
  let unsubscribe = [];
  /** Cambia en cada `start` y `stop`, para descartar lecturas que llegan tarde. */
  let generation = 0;

  /** Deja de revisar y suelta el observador, el temporizador y los oyentes de la página. */
  function deactivate() {
    active = null;
    if (observer !== null) {
      observer.disconnect();
      observer = null;
    }
    if (timer !== null) {
      timers.clearTimeout(timer);
      timer = null;
    }
    for (const type of PAGE_EVENTS) {
      root.removeEventListener(type, schedule);
    }
  }

  /** Borra la condición guardada; un fallo del almacenamiento no debe romper la página. */
  function forget() {
    return store ? store.remove(STORAGE_KEY).catch(() => {}) : Promise.resolve();
  }

  /** Revisa la condición y, si se cumple, avisa al panel una sola vez. */
  function check() {
    timer = null;
    if (active === null) {
      return;
    }
    lastCheck = ctx.clock.now();
    let met = false;
    try {
      met = CHECKS[active.end_condition.type](active.end_condition);
    } catch (error) {
      console.error('task_end could not check the end condition', error);
    }
    if (!met) {
      return;
    }
    const { task_id } = active;
    deactivate();
    forget();
    ctx.messages
      .send(ctx.messages.types.TASK_COMPLETED, { task_id, ended_by: 'reference' })
      .catch((error) => console.error('task_end could not send task.completed', error));
  }

  /** Pide una revisión: de inmediato si pasó el intervalo, o al cumplirse. */
  function schedule() {
    if (active === null || timer !== null) {
      return;
    }
    const wait = CHECK_INTERVAL_MS - (ctx.clock.now() - lastCheck);
    timer = timers.setTimeout(check, Math.max(wait, 0));
  }

  /**
   * Empieza a revisar la condición de una tarea. Con `null` no hay nada que revisar.
   *
   * @param {{task_id: number, end_condition: (object|null)}} task - Tarea y condición.
   * @returns {void}
   */
  function activate(task) {
    deactivate();
    if (task.end_condition === null) {
      forget();
      return;
    }
    active = { task_id: task.task_id, end_condition: task.end_condition };
    observer = new root.MutationObserver(schedule);
    observer.observe(root.document, {
      subtree: true,
      childList: true,
      characterData: true,
      attributes: true,
    });
    for (const type of PAGE_EVENTS) {
      root.addEventListener(type, schedule);
    }
    lastCheck = -Infinity;
    schedule();
  }

  /** Retoma la condición guardada si sigue siendo la de la tarea activa. */
  async function resume(token) {
    const saved = await store.get(STORAGE_KEY);
    if (token !== generation || !saved) {
      return;
    }
    const current = ctx.session.get();
    if (current !== null && current.task_id === saved.task_id) {
      activate(saved);
    } else {
      await forget();
    }
  }

  root.UX.modules.register({
    name: 'task_end',

    /**
     * Empieza a escuchar `task.started` y retoma la condición de la tarea activa.
     *
     * @param {object} context - Contexto del módulo.
     * @returns {void}
     */
    start(context) {
      ctx = context;
      // Se toman ahora y no al usarlos, para poder probarlos con temporizadores falsos.
      // `bind` es necesario: en el navegador, llamarlos desde otro objeto da "Illegal invocation".
      timers = {
        setTimeout: root.setTimeout.bind(root),
        clearTimeout: root.clearTimeout.bind(root),
      };
      generation += 1;
      const token = generation;
      store = root.UX.platform ? root.UX.platform.storage('session') : null;
      unsubscribe = [
        ctx.messages.on(ctx.messages.types.TASK_STARTED, ({ task_id, end_condition }) => {
          activate({ task_id, end_condition });
          if (store && end_condition !== null) {
            store.set(STORAGE_KEY, { task_id, end_condition }).catch(() => {});
          }
        }),
        ctx.session.subscribe((state) => {
          if (active !== null && (state === null || state.task_id !== active.task_id)) {
            deactivate();
            forget();
          }
        }),
      ];
      if (store) {
        resume(token).catch((error) => console.error('task_end could not resume', error));
      }
    },

    /**
     * Deja de revisar la condición, quita todos los oyentes y borra la condición guardada.
     *
     * @returns {void}
     */
    stop() {
      generation += 1;
      for (const remove of unsubscribe) {
        remove();
      }
      unsubscribe = [];
      deactivate();
      forget();
    },
  });
})(globalThis);
