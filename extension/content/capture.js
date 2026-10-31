/**
 * @file Captura de interacción (M1): registra lo que hace el participante en la
 * página evaluada (clics, cursor, scroll, selección, formularios y cambios de
 * pantalla), sin capturar nunca lo que escribe.
 *
 * Por ahora registra los clics (`click`, `dblclick` y `contextmenu`) con el
 * descriptor definitivo del elemento, y el movimiento del cursor y el scroll
 * con una frecuencia máxima configurable, y la longitud (nunca el contenido) del
 * texto seleccionado. Los demás tipos de evento se agregan
 * en las siguientes tareas de M1.
 *
 * Mensajes:
 * - Envía: lotes `events` con `ctx.batcher.add('events', registro)`; el
 *   acumulador los entrega al worker.
 * - Recibe: `task.started` llega a esta pestaña, pero la captura no necesita
 *   escucharlo: lee la tarea activa de `ctx.session.get().task_id`, que el panel
 *   actualiza al empezar y terminar cada tarea.
 *
 * Formato de los registros: `contracts/batches/events.schema.json` y
 * `contracts/element.schema.json`.
 */

(function (root) {
  'use strict';

  const { UX } = root;

  /** Largo máximo del texto del descriptor. */
  const TEXT_MAX_LENGTH = 50;
  /** Espera, en milisegundos, a que termine de seleccionar antes de registrar la selección. */
  const SELECTION_WAIT_MS = 300;
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
   * Texto visible recortado, o `null`. Nunca se toma de campos ni de zonas
   * editables, porque contendría lo que escribe el participante.
   */
  function textOf(element, tag) {
    if (FIELD_TAGS.includes(tag) || element.closest(EDITABLE_SELECTOR) || element.querySelector(EDITABLE_SELECTOR)) {
      return null;
    }
    const text = (element.innerText || element.textContent || '').replace(/\s+/g, ' ').trim();
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
   * de un botón), describe al interactivo más cercano.
   *
   * @param {Element} target - Elemento sobre el que ocurrió el evento.
   * @returns {object} Descriptor del elemento.
   */
  function describe(target) {
    const element = nearestInteractive(target);
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

  /** Entrega un registro de evento con los campos comunes (momento, pantalla y tarea activa). */
  function record(t, type, fields) {
    const state = ctx.session.get();
    ctx.batcher.add('events', {
      t,
      type,
      ...fields,
      screen: { url: root.location.href, title: root.document.title },
      task_id: state ? state.task_id : null,
    });
  }

  /** Registra un clic, doble clic o clic derecho con sus coordenadas y el elemento. */
  function onClick(event) {
    const target = event.target instanceof Element ? event.target : null;
    record(ctx.clock.now(), event.type, {
      x: event.clientX,
      y: event.clientY,
      element: target ? describe(target) : null,
      data: {},
    });
  }

  /** Intervalo mínimo, en milisegundos, de una frecuencia máxima en Hz. */
  function intervalOf(hz, key) {
    if (typeof hz !== 'number' || !Number.isFinite(hz) || hz <= 0) {
      throw new Error(`config capture.${key} must be a positive number`);
    }
    return 1000 / hz;
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
    lastMove = { x: event.clientX, y: event.clientY };
    mouseSampler.request();
  }

  /** Guarda la posición de scroll de la página; los desplazamientos de cajas internas se ignoran. */
  function onScroll(event) {
    if (event.target !== root.document) {
      return;
    }
    // Los navegadores con rebote pueden informar posiciones negativas; el contrato las excluye.
    lastScroll = {
      scroll_x: Math.max(0, root.scrollX),
      scroll_y: Math.max(0, root.scrollY),
    };
    scrollSampler.request();
  }

  /** Temporizadores de esta ejecución (se toman en `start`) y espera pendiente de la selección. */
  let timers = null;
  let selectionTimer = null;

  /** Si el elemento es un campo de formulario o está dentro de una zona editable. */
  function isFieldOrEditable(element) {
    return FIELD_TAGS.includes(element.tagName.toLowerCase()) || Boolean(element.closest(EDITABLE_SELECTOR));
  }

  /** Reinicia la espera: solo se registra cuando la selección lleva 300 ms sin cambiar. */
  function onSelectionChange() {
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
    const anchor = selection.anchorNode;
    const anchorElement = anchor && (anchor.nodeType === 1 ? anchor : anchor.parentElement);
    if (anchorElement && isFieldOrEditable(anchorElement)) {
      return;
    }
    // El texto solo se usa para contar: no se guarda ni se envía.
    const length = selection.toString().length;
    if (length > 0) {
      record(ctx.clock.now(), 'selection', { data: { length } });
    }
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
      ctx = context;
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
        emit: () => record(ctx.clock.now(), 'mousemove', { x: lastMove.x, y: lastMove.y, data: {} }),
      });
      scrollSampler = createSampler({
        intervalMs: scrollInterval,
        now,
        timers,
        emit: () =>
          record(ctx.clock.now(), 'scroll', {
            data: { scroll_x: lastScroll.scroll_x, scroll_y: lastScroll.scroll_y },
          }),
      });
      CLICK_TYPES.forEach((type) => root.document.addEventListener(type, onClick, true));
      root.document.addEventListener('mousemove', onMouseMove, PASSIVE);
      root.document.addEventListener('scroll', onScroll, PASSIVE);
      root.document.addEventListener('selectionchange', onSelectionChange, true);
    },

    /**
     * Deja de escuchar los eventos y descarta lo que esperaba su turno.
     *
     * @returns {void}
     */
    stop() {
      CLICK_TYPES.forEach((type) => root.document.removeEventListener(type, onClick, true));
      root.document.removeEventListener('mousemove', onMouseMove, PASSIVE);
      root.document.removeEventListener('scroll', onScroll, PASSIVE);
      root.document.removeEventListener('selectionchange', onSelectionChange, true);
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
