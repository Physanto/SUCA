/**
 * @file Captura de interacción (M1): registra lo que hace el participante en la
 * página evaluada (clics, cursor, scroll, selección, formularios y cambios de
 * pantalla), sin capturar nunca lo que escribe.
 *
 * Por ahora registra los clics (`click`, `dblclick` y `contextmenu`) con el
 * descriptor definitivo del elemento, y el movimiento del cursor y el scroll
 * con una frecuencia máxima configurable, la longitud (nunca el contenido) del
 * texto seleccionado y los eventos de formulario (foco, cambio de campo y
 * envío, sin valores), los errores de validación, la respuesta de la página tras un
 * clic y los cambios de pantalla.
 *
 * Mensajes:
 * - Envía: lotes `events` con `ctx.batcher.add('events', registro)`; el
 *   acumulador los entrega al worker.
 * - Recibe: `task.started` llega a esta pestaña, pero la captura no necesita
 *   escucharlo: lee la tarea activa de `ctx.session.get().task_id`, que el panel
 *   actualiza al empezar y terminar cada tarea. Cada registro lleva la tarea
 *   activa en el momento del hecho, también los que se entregan después.
 *
 * Formato de los registros: `contracts/batches/events.schema.json` y
 * `contracts/element.schema.json`.
 */

(function (root) {
  'use strict';

  const { UX } = root;

  /** Largo máximo del texto del descriptor. */
  const TEXT_MAX_LENGTH = 50;
  /**
   * Si el elemento tiene más texto que esto no se lee: no sirve como etiqueta, y leer
   * `innerText` de un enlace que envuelve una página entera tardó más de 100 ms.
   */
  const TEXT_SCAN_MAX_LENGTH = 1000;
  /** Espera, en milisegundos, a que termine de seleccionar antes de registrar la selección. */
  const SELECTION_WAIT_MS = 300;
  /** Tiempo mínimo, en milisegundos, entre dos `field_change` del mismo campo. */
  const FIELD_CHANGE_INTERVAL_MS = 1000;
  /** Eventos de foco del navegador y el tipo de evento que se registra por cada uno. */
  const FOCUS_TYPES = { focusin: 'focus_in', focusout: 'focus_out' };
  /** Espera, en milisegundos, tras salir de un campo para ver si el sitio le mostró un error. */
  const ERROR_CHECK_DELAY_MS = 200;
  /** Tipos de error que no vienen de la validación nativa (los demás salen de `validity`). */
  const ARIA_INVALID = 'aria_invalid';
  const VISIBLE_MESSAGE = 'visible_message';
  /** Roles de elementos donde se escribe texto: su texto visible nunca se registra. */
  const TEXT_INPUT_ROLES = ['textbox', 'searchbox', 'combobox', 'spinbutton'];
  /** Elemento con uno de esos roles; con `closest` alcanza también a quienes están dentro de él. */
  const TEXT_INPUT_SELECTOR = TEXT_INPUT_ROLES.map((role) => `[role="${role}"]`).join(',');
  /** Lista de opciones: las sugerencias de un buscador suelen ir en una. */
  const LISTBOX_SELECTOR = '[role="listbox"]';
  /** Tipos de `input` donde se escribe texto (los demás son casillas, botones, fechas…). */
  const TEXT_ENTRY_INPUT_TYPES = ['text', 'search', 'email', 'url', 'tel', 'number', 'password'];
  /** Campo donde se escribe texto, para buscarlo dentro de un `combobox` contenedor (ARIA 1.1). */
  const TYPING_INPUT_SELECTOR = [
    'input:not([type])',
    ...TEXT_ENTRY_INPUT_TYPES.map((type) => `input[type="${type}"]`),
    'textarea',
  ].join(',');
  /** Valor que reemplaza a los parámetros sensibles de una URL. */
  const REDACTED = 'redacted';
  /**
   * Parámetros de URL cuyo valor suele ser lo que el participante escribió en un
   * buscador o un secreto (credenciales, tokens, códigos). Se comparan en minúsculas.
   */
  const SENSITIVE_PARAMS = [
    'q', 'query', 'search', 's', 'keyword', 'keywords', 'term', 'email', 'user', 'username',
    'token', 'access_token', 'id_token', 'refresh_token', 'key', 'api_key', 'apikey',
    'password', 'pass', 'pwd', 'auth', 'session', 'sid', 'code', 'otp',
  ];
  /** Cada cuántos milisegundos se revisa si la dirección de la página cambió (aplicaciones de una sola página). */
  const SCREEN_POLL_MS = 250;
  /** Espera tras `popstate` o `hashchange`, para que la página actualice su título antes de registrar. */
  const SCREEN_SETTLE_MS = 50;
  /** Tras un cambio de dirección, cuánto se espera como máximo a que cambie el título y cada cuánto se mira. */
  const SCREEN_TITLE_WAIT_MS = 500;
  const SCREEN_TITLE_STEP_MS = 50;
  /** Eventos de clic que se registran, todos con el mismo formato. */
  const CLICK_TYPES = ['click', 'dblclick', 'contextmenu'];
  /** Campos de formulario: su texto nunca se registra. */
  const FIELD_TAGS = ['input', 'textarea', 'select'];
  /** Zonas editables: contienen lo que escribe el participante. */
  const EDITABLE_SELECTOR = '[contenteditable]:not([contenteditable="false"])';
  /** Etiquetas interactivas por sí mismas (`a` solo si tiene `href`, ver `isInteractive`). */
  const INTERACTIVE_TAGS = ['a', 'button', 'input', 'select', 'textarea', 'summary', 'option'];
  /** Roles ARIA que hacen interactivo a un elemento. */
  const INTERACTIVE_ROLES = [
    'button', 'link', 'checkbox', 'radio', 'menuitem', 'menuitemcheckbox', 'menuitemradio', 'tab',
    'switch', 'option', 'textbox', 'searchbox', 'combobox', 'slider', 'spinbutton',
  ];
  /** Roles implícitos de las etiquetas más comunes (`a` e `input` se resuelven aparte). */
  const IMPLICIT_ROLES = {
    button: 'button',
    select: 'combobox',
    textarea: 'textbox',
    option: 'option',
    img: 'img',
    h1: 'heading',
    h2: 'heading',
    h3: 'heading',
    h4: 'heading',
    h5: 'heading',
    h6: 'heading',
    ul: 'list',
    ol: 'list',
    li: 'listitem',
    table: 'table',
    dialog: 'dialog',
    nav: 'navigation',
    main: 'main',
    header: 'banner',
    footer: 'contentinfo',
    aside: 'complementary',
    form: 'form',
    search: 'search',
  };
  /** Rol implícito de cada tipo de `input` (los demás tipos son cuadros de texto). */
  const INPUT_ROLES = {
    checkbox: 'checkbox',
    radio: 'radio',
    range: 'slider',
    number: 'spinbutton',
    search: 'searchbox',
    button: 'button',
    submit: 'button',
    reset: 'button',
    image: 'button',
    hidden: null,
  };

  let ctx = null;

  /** Rol ARIA explícito o, si no tiene, el implícito de su etiqueta. */
  function roleOf(element, tag) {
    const explicit = element.getAttribute('role');
    if (explicit) {
      return explicit;
    }
    if (tag === 'input') {
      const type = (element.getAttribute('type') || 'text').toLowerCase();
      return type in INPUT_ROLES ? INPUT_ROLES[type] : 'textbox';
    }
    if (tag === 'a') {
      return element.hasAttribute('href') ? 'link' : null;
    }
    return IMPLICIT_ROLES[tag] || null;
  }

  /** Si el elemento, por sí mismo, es un enlace, botón, campo o tiene rol o manejador interactivo. */
  function isInteractive(element) {
    const tag = element.tagName.toLowerCase();
    const role = roleOf(element, tag);
    if (tag === 'input' && role === null) {
      return false;
    }
    if (tag === 'a') {
      return role === 'link';
    }
    return (
      INTERACTIVE_TAGS.includes(tag) || INTERACTIVE_ROLES.includes(role) || element.hasAttribute('onclick')
    );
  }

  /**
   * El elemento interactivo más cercano al destino del clic (él mismo o un
   * ancestro), para que un clic en el `span` de un botón se describa como el
   * botón. Si no hay ninguno, el propio destino.
   */
  function nearestInteractive(element) {
    for (let node = element; node && node.nodeType === 1; node = node.parentElement) {
      if (isInteractive(node)) {
        return node;
      }
      if (node.tagName.toLowerCase() === 'body') {
        break;
      }
    }
    return element;
  }

  /**
   * Si en el elemento se escribe texto libre: `input` de texto, `textarea`, zona
   * editable, rol `textbox` o `searchbox`, o un `combobox` que contiene uno de esos
   * campos (patrón de ARIA 1.1). Un `combobox` sin campo adentro (por ejemplo, un
   * `div` que abre una lista para elegir país) y los botones no cuentan: en ellos
   * no se escribe, se elige.
   */
  function isTypingField(element) {
    const tag = element.tagName.toLowerCase();
    if (tag === 'input') {
      return TEXT_ENTRY_INPUT_TYPES.includes((element.getAttribute('type') || 'text').toLowerCase());
    }
    if (tag === 'textarea' || element.closest(EDITABLE_SELECTOR)) {
      return true;
    }
    const role = element.getAttribute('role');
    if (role === 'textbox' || role === 'searchbox') {
      return true;
    }
    return role === 'combobox' && Boolean(element.querySelector(TYPING_INPUT_SELECTOR));
  }

  /**
   * Si el elemento es una opción de una lista de sugerencias de un campo de texto
   * (autocompletado). Su texto suele repetir lo que el participante escribió
   * ("zapat" → "zapatos deportivos"), y las sugerencias no están dentro del campo.
   * La lista se reconoce por tres enlaces con un campo donde se escribe
   * (`isTypingField`), porque los sitios no usan el mismo:
   *
   * 1. `aria-controls` o `aria-owns` del campo nombran el `id` de la lista (ARIA 1.2).
   * 2. `aria-activedescendant` del campo apunta a algo dentro de la lista.
   * 3. El campo comparte con la lista su `aria-labelledby` (react.dev enlaza así
   *    sus listas, que además repiten el mismo `id`).
   *
   * Solo cuentan los enlaces desde un campo donde se escribe, fuera de la lista: una
   * lista de selección normal (elegir país) también se enlaza así, pero desde un botón,
   * un `combobox` sin campo de texto o desde la propia lista (`aria-activedescendant`
   * de la lista), y conserva el texto de sus opciones, que sirve para comparar los
   * pasos con la ruta de referencia.
   *
   * @param {Element} element - Elemento sobre el que se hizo clic.
   * @returns {boolean} `true` si está dentro de una lista de sugerencias.
   */
  function isAutocompleteOption(element) {
    const list = element.closest(LISTBOX_SELECTOR);
    if (!list) {
      return false;
    }
    const doc = root.document;
    /** Si el elemento es un campo donde se escribe, fuera de la lista. */
    const typingOutside = (owner) => owner !== list && !list.contains(owner) && isTypingField(owner);
    if (list.id) {
      const id = CSS.escape(list.id);
      if ([...doc.querySelectorAll(`[aria-controls~="${id}"], [aria-owns~="${id}"]`)].some(typingOutside)) {
        return true;
      }
    }
    const activeOwner = [...doc.querySelectorAll('[aria-activedescendant]')].some((owner) => {
      const target = doc.getElementById(owner.getAttribute('aria-activedescendant'));
      return Boolean(target) && list.contains(target) && typingOutside(owner);
    });
    if (activeOwner) {
      return true;
    }
    return (list.getAttribute('aria-labelledby') || '')
      .split(/\s+/)
      .filter(Boolean)
      .some((label) => [...doc.querySelectorAll(`[aria-labelledby~="${CSS.escape(label)}"]`)].some(typingOutside));
  }

  /**
   * Texto visible recortado, o `null`. Solo se toma de elementos interactivos
   * (botones, enlaces, pestañas…): el de contenedores, párrafos o títulos puede ser
   * un eco de lo que el participante escribió (un mensaje enviado, una vista previa)
   * o datos personales visibles, y los pasos de una tarea son solo clics en
   * interactivos. Tampoco se toma de campos, de zonas editables ni de cuadros de
   * texto personalizados (rol `textbox`, `searchbox`, `combobox` o `spinbutton`), ni
   * de elementos que los contienen, ni de los que contienen un `textarea` (su contenido
   * inicial puede ser texto que el participante ya había escrito). Tampoco de las
   * sugerencias de autocompletado de un campo (`isAutocompleteOption`).
   */
  function textOf(element, tag) {
    if (
      !isInteractive(element) ||
      FIELD_TAGS.includes(tag) ||
      element.closest(EDITABLE_SELECTOR) ||
      element.closest(TEXT_INPUT_SELECTOR) ||
      isAutocompleteOption(element)
    ) {
      return null;
    }
    // Antes de recorrer lo que contiene (cada `querySelector` recorre todo el subárbol), se
    // descartan los elementos con demasiado texto. `textContent` no fuerza el cálculo de la
    // página; `innerText` sí, y solo se lee si el texto es corto.
    const raw = element.textContent || '';
    if (raw.length > TEXT_SCAN_MAX_LENGTH) {
      return null;
    }
    if (
      element.querySelector(EDITABLE_SELECTOR) ||
      element.querySelector(TEXT_INPUT_SELECTOR) ||
      element.querySelector('textarea')
    ) {
      return null;
    }
    const text = (element.innerText || raw).replace(/\s+/g, ' ').trim();
    return text === '' ? null : text.slice(0, TEXT_MAX_LENGTH);
  }

  /** Selector CSS que ubica al elemento: su `id` si tiene, o la ruta desde `body`. */
  function selectorOf(element) {
    const parts = [];
    for (let node = element; node && node.nodeType === 1; node = node.parentElement) {
      const tag = node.tagName.toLowerCase();
      if (node.id) {
        parts.unshift(`#${CSS.escape(node.id)}`);
        break;
      }
      if (tag === 'body' || tag === 'html') {
        parts.unshift(tag);
        break;
      }
      // Un elemento que el sitio ya desconectó del documento no tiene padre.
      const siblings = node.parentElement ? [...node.parentElement.children] : [node];
      const sameTag = siblings.filter((child) => child.tagName === node.tagName);
      parts.unshift(sameTag.length > 1 ? `${tag}:nth-of-type(${sameTag.indexOf(node) + 1})` : tag);
    }
    return parts.join(' > ');
  }

  /**
   * Describe un elemento con la forma de `contracts/element.schema.json`.
   *
   * Si el elemento está dentro de uno interactivo (por ejemplo, un `span` dentro
   * de un botón), describe al interactivo más cercano, salvo que `exact` sea
   * verdadero: los eventos de formulario describen el campo o formulario mismo.
   *
   * @param {Element} target - Elemento sobre el que ocurrió el evento.
   * @param {boolean} [exact=false] - Describir `target` y no el interactivo más cercano.
   * @returns {object} Descriptor del elemento.
   */
  function describe(target, exact = false) {
    const element = exact ? target : nearestInteractive(target);
    const tag = element.tagName.toLowerCase();
    const box = element.getBoundingClientRect();
    return {
      tag,
      id: element.id || null,
      role: roleOf(element, tag),
      text: textOf(element, tag),
      selector: selectorOf(element),
      box: { x: box.x, y: box.y, w: box.width, h: box.height },
      interactive: isInteractive(element),
    };
  }

  /** Tarea activa ahora, de la sesión que el panel mantiene al día; `null` si no hay ninguna. */
  function activeTask() {
    const state = ctx.session.get();
    return state ? state.task_id : null;
  }

  /**
   * Entrega un registro de evento con los campos comunes (momento, pantalla y tarea activa).
   *
   * Los registros que se entregan más tarde que el hecho que los causó (la respuesta
   * a un clic, una selección, un error que el sitio muestra después) reciben la
   * tarea del momento del hecho: si el clic termina la tarea, su respuesta sigue
   * perteneciendo a ella aunque la tarea ya se haya cerrado cuando se entrega.
   *
   * @param {number} t - Momento del registro.
   * @param {string} type - Tipo de evento.
   * @param {object} fields - Campos propios del tipo.
   * @param {number|null} [taskId] - Tarea del momento del hecho; por omisión, la activa ahora.
   * @param {{url: string, title: string}} [screen] - Pantalla del registro; por omisión, la actual.
   * @returns {void}
   */
  function record(t, type, fields, taskId = activeTask(), screen = currentScreen()) {
    ctx.batcher.add('events', { t, type, ...fields, screen, task_id: taskId });
  }

  /**
   * Pantalla de un registro: la URL ya redactada y el título.
   *
   * Si hubo que tachar la dirección, el título suele repetir lo mismo ("Resultados de …"):
   * se deja vacío, que el contrato admite, para no guardar lo que el participante buscó.
   *
   * @param {string} href - Dirección de la página.
   * @param {string} title - Título del documento.
   * @returns {{url: string, title: string}} Pantalla para el registro.
   */
  function screenOf(href, title) {
    const url = redactUrl(href);
    return { url, title: url === href ? title : '' };
  }

  /** Pantalla en la que está la página ahora. */
  function currentScreen() {
    return screenOf(root.location.href, root.document.title);
  }

  /** Decodifica el nombre de un parámetro; si está mal codificado, lo deja como está. */
  function decodeName(name) {
    try {
      return decodeURIComponent(name);
    } catch {
      return name;
    }
  }

  /** Reemplaza el valor de los parámetros sensibles de una lista `a=1&b=2`; el resto queda igual. */
  function redactParams(list) {
    return list
      .split('&')
      .map((part) => {
        const equals = part.indexOf('=');
        if (equals < 0 || !SENSITIVE_PARAMS.includes(decodeName(part.slice(0, equals)).toLowerCase())) {
          return part;
        }
        return `${part.slice(0, equals)}=${REDACTED}`;
      })
      .join('&');
  }

  /**
   * URL sin lo que el participante pudo escribir ni secretos: quita usuario y clave de
   * la dirección (`https://usuario:clave@sitio`) y reemplaza por `redacted` el valor de
   * los parámetros sensibles (`SENSITIVE_PARAMS`) de la parte de búsqueda y del
   * fragmento (`#access_token=…`, `#/buscar?q=…`). El resto se conserva, porque muchas
   * aplicaciones identifican la pantalla con la ruta, `?view=…` o `#/ruta`.
   *
   * @param {string} href - Dirección de la página.
   * @returns {string} Dirección sin valores sensibles.
   */
  function redactUrl(href) {
    const hashAt = href.indexOf('#');
    const fragment = hashAt < 0 ? '' : href.slice(hashAt + 1);
    const base = (hashAt < 0 ? href : href.slice(0, hashAt)).replace(/^([a-z][a-z0-9+.-]*:\/\/)[^/?#@]*@/i, '$1');
    const queryAt = base.indexOf('?');
    const path = queryAt < 0 ? base : base.slice(0, queryAt);
    const query = queryAt < 0 ? '' : `?${redactParams(base.slice(queryAt + 1))}`;
    if (hashAt < 0) {
      return path + query;
    }
    // Un fragmento puede ser una lista de parámetros o una ruta con su propia búsqueda.
    const routeQueryAt = fragment.indexOf('?');
    const redactedFragment =
      routeQueryAt < 0
        ? redactParams(fragment)
        : `${fragment.slice(0, routeQueryAt)}?${redactParams(fragment.slice(routeQueryAt + 1))}`;
    return `${path}${query}#${redactedFragment}`;
  }

  /**
   * Registra un clic, doble clic o clic derecho con sus coordenadas y el elemento.
   * Después de un clic simple se vigila si la página responde.
   */
  function onClick(event) {
    const target = event.target instanceof Element ? event.target : null;
    const t = ctx.clock.now();
    const taskId = activeTask();
    record(
      t,
      event.type,
      { x: event.clientX, y: event.clientY, element: target ? describe(target) : null, data: {} },
      taskId,
    );
    if (event.type === 'click') {
      watchResponse(t, taskId);
    }
  }

  /** Valida que un valor de configuración de la captura sea un número positivo. */
  function requirePositive(value, key) {
    if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) {
      throw new Error(`config capture.${key} must be a positive number`);
    }
    return value;
  }

  /** Intervalo mínimo, en milisegundos, de una frecuencia máxima en Hz. */
  function intervalOf(hz, key) {
    return 1000 / requirePositive(hz, key);
  }

  /** Espera, en milisegundos, para ver si la página responde a un clic (de la configuración). */
  let responseWaitMs = 0;
  /** Vigilancias de respuesta en curso, una por clic. */
  let pendingResponses = new Set();

  /**
   * Vigila si la página responde a un clic. Un `MutationObserver` propio del clic
   * cuenta los cambios del documento durante `responseWaitMs`. Si hubo cambios o
   * navegación se registra un `click_response` unido al clic por `click_t`; si no
   * hubo nada no se registra nada, y el análisis toma ese clic como un clic muerto.
   * El observador se crea antes de que el código del sitio atienda el clic, porque
   * este oyente corre primero (fase de captura).
   *
   * @param {number} clickT - Momento del clic, tal como quedó en su registro.
   * @param {number|null} taskId - Tarea del clic; la respuesta se registra con ella.
   * @returns {void}
   */
  function watchResponse(clickT, taskId) {
    const urlAtClick = root.location.href;
    let mutationCount = 0;
    const observer = new root.MutationObserver((records) => {
      mutationCount += records.length;
    });
    observer.observe(root.document.documentElement, {
      childList: true,
      attributes: true,
      characterData: true,
      subtree: true,
    });
    const watch = {
      timer: null,
      /** Termina la espera y registra la respuesta si la hubo; `unloading` si la página se descarga. */
      finish(unloading) {
        timers.clearTimeout(watch.timer);
        pendingResponses.delete(watch);
        // Cambios detectados pero que el observador aún no había entregado.
        mutationCount += observer.takeRecords().length;
        observer.disconnect();
        // Una aplicación de una sola página navega sin descargar la página: cambia la URL.
        const navigated = unloading || root.location.href !== urlAtClick;
        if (mutationCount > 0 || navigated) {
          record(
            ctx.clock.now(),
            'click_response',
            { data: { click_t: clickT, mutation_count: mutationCount, navigated } },
            taskId,
          );
        }
      },
      /** Abandona la vigilancia sin registrar nada. */
      cancel() {
        timers.clearTimeout(watch.timer);
        observer.disconnect();
      },
    };
    watch.timer = timers.setTimeout(() => watch.finish(false), responseWaitMs);
    pendingResponses.add(watch);
  }

  /**
   * Si la página se descarga durante una espera, la respuesta es una navegación:
   * se registra ya y se pide vaciar el acumulador, porque el acumulador ya vació
   * lo suyo al recibir este mismo aviso, antes que nosotros.
   */
  function onPageHide() {
    const waiting = [...pendingResponses];
    waiting.forEach((watch) => watch.finish(true));
    const hadScreen = pendingScreen !== null;
    flushPendingScreen();
    if (waiting.length > 0 || hadScreen) {
      Promise.resolve(ctx.batcher.flush()).catch(() => {});
    }
  }

  /**
   * Limita la frecuencia de un tipo de evento: entrega el primero de inmediato y,
   * si llegan más antes de que pase el intervalo, solo el último, cuando se cumple.
   * Así no se pierde la posición donde termina un movimiento o un desplazamiento.
   *
   * @param {object} options - Opciones.
   * @param {number} options.intervalMs - Tiempo mínimo entre dos entregas.
   * @param {function(): number} options.now - Reloj en milisegundos.
   * @param {{setTimeout: Function, clearTimeout: Function}} options.timers - Temporizadores.
   * @param {function(): void} options.emit - Entrega el último valor recibido.
   * @returns {{request: function(): void, cancel: function(): void}} `request` se llama en
   *   cada evento; `cancel` descarta lo pendiente.
   */
  function createSampler({ intervalMs, now, timers, emit }) {
    let lastEmit = -Infinity;
    let timer = null;

    /** Entrega el último valor y anota cuándo. */
    function fire() {
      timer = null;
      // Un temporizador puede dispararse una fracción de milisegundo antes: se reprograma.
      const wait = lastEmit + intervalMs - now();
      if (wait > 0) {
        timer = timers.setTimeout(fire, wait);
        return;
      }
      lastEmit = now();
      emit();
    }

    return {
      request() {
        const wait = lastEmit + intervalMs - now();
        if (wait <= 0) {
          timers.clearTimeout(timer);
          fire();
        } else if (timer === null) {
          timer = timers.setTimeout(fire, wait);
        }
      },
      cancel() {
        timers.clearTimeout(timer);
        timer = null;
        lastEmit = -Infinity;
      },
    };
  }

  /** Muestreadores de cursor y scroll; se crean en `start` con las frecuencias configuradas. */
  let mouseSampler = null;
  let scrollSampler = null;
  /**
   * Último movimiento del cursor y última posición de scroll, pendientes de entregar.
   * El registro lleva la hora en que se entrega y no la del evento, para que dos
   * registros nunca queden más cerca que el intervalo mínimo.
   */
  let lastMove = null;
  let lastScroll = null;

  /** Guarda el movimiento del cursor; el muestreador decide cuándo registrarlo. */
  function onMouseMove(event) {
    lastMove = { x: event.clientX, y: event.clientY, taskId: activeTask() };
    mouseSampler.request();
  }

  /** Guarda la posición de scroll de la página; los desplazamientos de cajas internas se ignoran. */
  function onScroll(event) {
    if (event.target !== root.document) {
      return;
    }
    // Los navegadores con rebote pueden informar posiciones negativas; el contrato las excluye.
    lastScroll = {
      taskId: activeTask(),
      scroll_x: Math.max(0, root.scrollX),
      scroll_y: Math.max(0, root.scrollY),
    };
    scrollSampler.request();
  }

  /** Temporizadores de esta ejecución (se toman en `start`) y espera pendiente de la selección. */
  let timers = null;
  let selectionTimer = null;
  /** Tarea activa en el último cambio de la selección. */
  let selectionTask = null;

  /** Si el elemento es un campo, o está dentro de una zona editable o de un cuadro de texto personalizado. */
  function isFieldOrEditable(element) {
    return (
      FIELD_TAGS.includes(element.tagName.toLowerCase()) ||
      Boolean(element.closest(EDITABLE_SELECTOR)) ||
      Boolean(element.closest(TEXT_INPUT_SELECTOR))
    );
  }

  /** Reinicia la espera: solo se registra cuando la selección lleva 300 ms sin cambiar. */
  function onSelectionChange() {
    selectionTask = activeTask();
    timers.clearTimeout(selectionTimer);
    selectionTimer = timers.setTimeout(recordSelection, SELECTION_WAIT_MS);
  }

  /**
   * Registra la longitud de la selección actual, nunca su contenido. No registra
   * selecciones vacías ni las hechas dentro de campos o zonas editables, porque
   * su longitud revelaría cuánto escribió el participante.
   */
  function recordSelection() {
    selectionTimer = null;
    const active = root.document.activeElement;
    if (active && isFieldOrEditable(active)) {
      return;
    }
    const selection = root.getSelection();
    if (!selection || selection.rangeCount === 0) {
      return;
    }
    // Se miran los dos extremos: una selección que empieza fuera de un campo y termina
    // dentro (o al revés) también incluye lo escrito, y su longitud lo revelaría.
    const endsInField = [selection.anchorNode, selection.focusNode].some((node) => {
      const element = node && (node.nodeType === 1 ? node : node.parentElement);
      return Boolean(element) && isFieldOrEditable(element);
    });
    if (endsInField) {
      return;
    }
    // El texto solo se usa para contar: no se guarda ni se envía.
    const length = selection.toString().length;
    if (length > 0) {
      record(ctx.clock.now(), 'selection', { data: { length } }, selectionTask);
    }
  }

  /** Si el elemento es un campo donde el participante escribe o elige (no un campo oculto). */
  function isFormField(element) {
    const tag = element.tagName.toLowerCase();
    if (tag === 'input') {
      return (element.getAttribute('type') || 'text').toLowerCase() !== 'hidden';
    }
    const editable = element.hasAttribute('contenteditable') && element.getAttribute('contenteditable') !== 'false';
    return tag === 'textarea' || tag === 'select' || editable;
  }

  /** Último `field_change` registrado de cada campo, para limitarlos a uno por segundo. */
  let lastChanges = new WeakMap();

  /** Registra que un campo ganó o perdió el foco. Solo el campo, nunca su valor. */
  function onFocus(event) {
    const target = event.target;
    if (target instanceof Element && isFormField(target)) {
      record(ctx.clock.now(), FOCUS_TYPES[event.type], { element: describe(target, true), data: {} });
      if (event.type === 'focusout') {
        scheduleFieldCheck(target);
      }
    }
  }

  /**
   * Registra que un campo cambió: solo que hubo un cambio y en qué campo. No se lee
   * `value` ni nada del evento (`data`, `inputType`), porque contendría lo escrito.
   */
  function onInput(event) {
    const target = event.target;
    if (!(target instanceof Element) || !isFormField(target)) {
      return;
    }
    const now = ctx.clock.now();
    const last = lastChanges.get(target);
    if (last !== undefined && now - last < FIELD_CHANGE_INTERVAL_MS) {
      return;
    }
    lastChanges.set(target, now);
    record(now, 'field_change', { element: describe(target, true), data: {} });
  }

  /** Registra el envío de un formulario. El navegador solo lo avisa si pasó la validación. */
  function onSubmit(event) {
    if (event.target instanceof Element) {
      record(ctx.clock.now(), 'form_submit', { element: describe(event.target, true), data: {} });
    }
  }

  /** Pares `[propiedad de validity, tipo de error]`, tomados de la enumeración del contrato en `start`. */
  let nativeFlags = [];
  /** Último error de cada campo ya registrado (aria o mensaje visible), para no repetirlo. */
  let reportedErrors = new WeakMap();
  /** Comprobaciones de error pendientes tras salir de un campo, y observador de `aria-invalid`. */
  let pendingChecks = new Set();
  let ariaObserver = null;

  /** `value_missing` → `valueMissing`: nombre de la propiedad de `ValidityState`. */
  function flagOf(errorType) {
    return errorType.replace(/_([a-z])/g, (_, letter) => letter.toUpperCase());
  }

  /** Entrega un `validation_error` del campo con su tipo y la tarea en que ocurrió. */
  function recordError(element, errorType, taskId = activeTask()) {
    record(
      ctx.clock.now(),
      'validation_error',
      { element: describe(element, true), data: { error_type: errorType } },
      taskId,
    );
  }

  /** Validación nativa: el navegador avisa con `invalid` de cada campo inválido al intentar enviar. */
  function onInvalid(event) {
    const target = event.target;
    if (!(target instanceof Element) || !target.validity) {
      return;
    }
    // Si hay varios problemas se registra el primero de la enumeración del contrato.
    const found = nativeFlags.find(([flag]) => target.validity[flag]);
    if (found) {
      recordError(target, found[1]);
    }
  }

  /** Registra el error de un campo salvo que ya se hubiera registrado y siga presente. */
  function reportError(element, errorType, taskId = activeTask()) {
    if (reportedErrors.get(element) !== errorType) {
      reportedErrors.set(element, errorType);
      recordError(element, errorType, taskId);
    }
  }

  /** Cambios del atributo `aria-invalid`: un campo que pasa a "true" tiene un error. */
  function onAriaMutations(mutations) {
    for (const { target } of mutations) {
      if (target.getAttribute('aria-invalid') === 'true') {
        reportError(target, ARIA_INVALID);
      } else {
        reportedErrors.delete(target);
      }
    }
  }

  /** Si el elemento es visible y tiene texto. Solo se mira si hay texto, no cuál es. */
  function hasVisibleText(node) {
    return node.checkVisibility({ visibilityProperty: true }) && (node.textContent || '').trim() !== '';
  }

  /** Si el elemento parece un mensaje de error (rol `alert` o un nombre que lo indica). */
  function looksLikeError(node) {
    const names = `${node.id} ${node.getAttribute('class') || ''}`;
    return node.getAttribute('role') === 'alert' || /err|invalid|danger/i.test(names);
  }

  /**
   * Si el campo tiene un mensaje de error visible: el que declara con
   * `aria-errormessage` o, entre los que lo describen con `aria-describedby`, uno
   * que parezca de error (para no tomar el texto de ayuda como error).
   */
  function hasVisibleErrorMessage(field) {
    const sources = [['aria-errormessage', false], ['aria-describedby', true]];
    return sources.some(([attribute, mustLookLikeError]) =>
      (field.getAttribute(attribute) || '')
        .split(/\s+/)
        .map((id) => (id ? root.document.getElementById(id) : null))
        .some((node) => node && (!mustLookLikeError || looksLikeError(node)) && hasVisibleText(node)),
    );
  }

  /** Revisa, algo después de salir de un campo, si el sitio le mostró un error. */
  function checkFieldError(field, taskId) {
    let errorType = null;
    if (field.getAttribute('aria-invalid') === 'true') {
      errorType = ARIA_INVALID;
    } else if (hasVisibleErrorMessage(field)) {
      errorType = VISIBLE_MESSAGE;
    }
    if (errorType) {
      reportError(field, errorType, taskId);
    } else {
      reportedErrors.delete(field);
    }
  }

  /** Programa la revisión; la espera da tiempo al sitio de mostrar su mensaje tras salir del campo. */
  function scheduleFieldCheck(field) {
    // La tarea es la del momento de salir del campo, no la de cuando se haga la revisión.
    const taskId = activeTask();
    const timer = timers.setTimeout(() => {
      pendingChecks.delete(timer);
      checkFieldError(field, taskId);
    }, ERROR_CHECK_DELAY_MS);
    pendingChecks.add(timer);
  }

  /** Última dirección registrada y temporizadores de la revisión periódica y de la espera tras `popstate`. */
  let lastHref = null;
  let screenTimer = null;
  let settleTimer = null;
  /** Título del documento en la última pantalla registrada, para saber si la página ya lo actualizó. */
  let lastTitle = null;
  /** Cambio de pantalla detectado cuyo título todavía se espera, y su temporizador. */
  let pendingScreen = null;
  let titleTimer = null;

  /**
   * Registra un cambio de pantalla.
   *
   * @param {number} t - Momento en que se detectó el cambio.
   * @param {number|null} taskId - Tarea activa en ese momento.
   * @param {{url: string, title: string}} [screen] - Pantalla; por omisión, la actual.
   * @returns {void}
   */
  function recordScreen(t = ctx.clock.now(), taskId = activeTask(), screen = currentScreen()) {
    record(t, 'screen_change', { data: {} }, taskId, screen);
  }

  /** Registra ya el cambio pendiente, con el título que se alcanzó a ver, y con la hora en que se detectó. */
  function flushPendingScreen() {
    timers.clearTimeout(titleTimer);
    titleTimer = null;
    const pending = pendingScreen;
    pendingScreen = null;
    if (pending) {
      lastTitle = pending.title;
      recordScreen(pending.t, pending.taskId, screenOf(pending.href, pending.title));
    }
  }

  /**
   * Espera a que la página actualice el título tras cambiar la dirección (muchas lo
   * hacen un instante después) y entonces registra el cambio, con la hora de la
   * detección. Si el título ya cambió, o pasa `SCREEN_TITLE_WAIT_MS`, registra sin más espera.
   */
  function settleTitle() {
    pendingScreen.title = root.document.title;
    if (pendingScreen.title !== lastTitle || pendingScreen.waited >= SCREEN_TITLE_WAIT_MS) {
      flushPendingScreen();
      return;
    }
    pendingScreen.waited += SCREEN_TITLE_STEP_MS;
    titleTimer = timers.setTimeout(settleTitle, SCREEN_TITLE_STEP_MS);
  }

  /** Detecta un cambio de dirección y lo registra, esperando antes el título de la pantalla nueva. */
  function checkScreen() {
    const href = root.location.href;
    if (href === lastHref) {
      return;
    }
    // Si llega otro cambio mientras se esperaba el título del anterior, el anterior se registra ya.
    flushPendingScreen();
    lastHref = href;
    pendingScreen = { t: ctx.clock.now(), taskId: activeTask(), href, title: root.document.title, waited: 0 };
    settleTitle();
  }

  /**
   * Revisa la dirección cada `SCREEN_POLL_MS`. El módulo corre en un contexto
   * aislado y no puede interceptar el `pushState` de la página, así que las
   * aplicaciones de una sola página solo se notan comparando la dirección.
   */
  function pollScreen() {
    checkScreen();
    screenTimer = timers.setTimeout(pollScreen, SCREEN_POLL_MS);
  }

  /** `popstate` y `hashchange`: se revisa sin esperar a la próxima vuelta, tras una pausa corta. */
  function onHistoryChange() {
    timers.clearTimeout(settleTimer);
    settleTimer = timers.setTimeout(() => {
      settleTimer = null;
      checkScreen();
    }, SCREEN_SETTLE_MS);
  }

  /** Oyentes que no bloquean el desplazamiento ni el cursor de la página. */
  const PASSIVE = { capture: true, passive: true };

  UX.modules.register({
    name: 'capture',

    /**
     * Empieza a escuchar los eventos, en fase de captura para no depender del
     * sitio. El cursor y el scroll se muestrean a las frecuencias máximas de
     * `context.config.capture`.
     *
     * @param {object} context - Contexto del módulo.
     * @returns {void}
     * @throws {Error} Si una frecuencia configurada no es un número positivo.
     */
    start(context) {
      const { mousemove_hz: mouseHz, scroll_hz: scrollHz } = context.config.capture;
      // Se valida antes de escuchar nada: si falla, no queda nada a medias.
      const mouseInterval = intervalOf(mouseHz, 'mousemove_hz');
      const scrollInterval = intervalOf(scrollHz, 'scroll_hz');
      const responseWait = requirePositive(context.config.capture.click_response_wait_ms, 'click_response_wait_ms');
      const errorTypes = context.contracts.enums.validation_error_type;
      for (const needed of [ARIA_INVALID, VISIBLE_MESSAGE]) {
        if (!errorTypes.includes(needed)) {
          throw new Error(`contract validation_error_type lacks ${needed}`);
        }
      }
      nativeFlags = errorTypes
        .filter((type) => type !== ARIA_INVALID && type !== VISIBLE_MESSAGE)
        .map((type) => [flagOf(type), type]);
      ctx = context;
      responseWaitMs = responseWait;
      // Se toman ahora y no al usarlos, para poder probarlos con temporizadores falsos.
      // `bind` es necesario: en el navegador, llamarlos desde otro objeto da "Illegal invocation".
      timers = {
        setTimeout: root.setTimeout.bind(root),
        clearTimeout: root.clearTimeout.bind(root),
      };
      const now = () => ctx.clock.now();
      mouseSampler = createSampler({
        intervalMs: mouseInterval,
        now,
        timers,
        emit: () =>
          record(ctx.clock.now(), 'mousemove', { x: lastMove.x, y: lastMove.y, data: {} }, lastMove.taskId),
      });
      scrollSampler = createSampler({
        intervalMs: scrollInterval,
        now,
        timers,
        emit: () =>
          record(
            ctx.clock.now(),
            'scroll',
            { data: { scroll_x: lastScroll.scroll_x, scroll_y: lastScroll.scroll_y } },
            lastScroll.taskId,
          ),
      });
      CLICK_TYPES.forEach((type) => root.document.addEventListener(type, onClick, true));
      root.document.addEventListener('mousemove', onMouseMove, PASSIVE);
      root.document.addEventListener('scroll', onScroll, PASSIVE);
      root.document.addEventListener('selectionchange', onSelectionChange, true);
      Object.keys(FOCUS_TYPES).forEach((type) => root.document.addEventListener(type, onFocus, true));
      root.document.addEventListener('input', onInput, true);
      root.document.addEventListener('submit', onSubmit, true);
      root.document.addEventListener('invalid', onInvalid, true);
      root.addEventListener('pagehide', onPageHide);
      root.addEventListener('popstate', onHistoryChange);
      root.addEventListener('hashchange', onHistoryChange);
      // Cada carga de página inicia la captura de nuevo, así que esta es la pantalla de la carga
      // (o la primera de la sesión, si se inició sobre una página ya cargada).
      lastHref = root.location.href;
      lastTitle = root.document.title;
      recordScreen();
      screenTimer = timers.setTimeout(pollScreen, SCREEN_POLL_MS);
      // Solo se observa un atributo, para que el costo en páginas con muchos cambios sea mínimo.
      ariaObserver = new root.MutationObserver(onAriaMutations);
      ariaObserver.observe(root.document.documentElement, {
        attributes: true,
        attributeFilter: ['aria-invalid'],
        subtree: true,
      });
    },

    /**
     * Deja de escuchar los eventos y descarta lo que esperaba su turno.
     *
     * @returns {void}
     */
    stop() {
      // Un cambio de pantalla que aún esperaba su título se registra antes de cerrar.
      if (ctx && timers) {
        flushPendingScreen();
      }
      CLICK_TYPES.forEach((type) => root.document.removeEventListener(type, onClick, true));
      root.document.removeEventListener('mousemove', onMouseMove, PASSIVE);
      root.document.removeEventListener('scroll', onScroll, PASSIVE);
      root.document.removeEventListener('selectionchange', onSelectionChange, true);
      Object.keys(FOCUS_TYPES).forEach((type) => root.document.removeEventListener(type, onFocus, true));
      root.document.removeEventListener('input', onInput, true);
      root.document.removeEventListener('submit', onSubmit, true);
      root.document.removeEventListener('invalid', onInvalid, true);
      root.removeEventListener('pagehide', onPageHide);
      root.removeEventListener('popstate', onHistoryChange);
      root.removeEventListener('hashchange', onHistoryChange);
      if (timers) {
        timers.clearTimeout(screenTimer);
        timers.clearTimeout(settleTimer);
      }
      screenTimer = null;
      settleTimer = null;
      titleTimer = null;
      pendingScreen = null;
      lastHref = null;
      lastTitle = null;
      pendingResponses.forEach((watch) => watch.cancel());
      pendingResponses = new Set();
      if (ariaObserver) {
        ariaObserver.disconnect();
      }
      ariaObserver = null;
      if (timers) {
        pendingChecks.forEach((timer) => timers.clearTimeout(timer));
      }
      pendingChecks = new Set();
      reportedErrors = new WeakMap();
      nativeFlags = [];
      lastChanges = new WeakMap();
      if (timers) {
        timers.clearTimeout(selectionTimer);
      }
      selectionTimer = null;
      [mouseSampler, scrollSampler].forEach((sampler) => sampler && sampler.cancel());
      mouseSampler = null;
      scrollSampler = null;
      lastMove = null;
      lastScroll = null;
      timers = null;
      ctx = null;
    },
  });
})(globalThis);
