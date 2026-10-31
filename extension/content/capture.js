/**
 * @file Captura de interacción (M1): registra lo que hace el participante en la
 * página evaluada (clics, cursor, scroll, selección, formularios y cambios de
 * pantalla), sin capturar nunca lo que escribe.
 *
 * Por ahora registra los clics (`click`, `dblclick` y `contextmenu`) con el
 * descriptor definitivo del elemento. Los demás tipos de evento se agregan en
 * las siguientes tareas de M1.
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

  /** Registra un clic, doble clic o clic derecho con sus coordenadas y el elemento. */
  function onClick(event) {
    const state = ctx.session.get();
    const target = event.target instanceof Element ? event.target : null;
    ctx.batcher.add('events', {
      t: ctx.clock.now(),
      type: event.type,
      x: event.clientX,
      y: event.clientY,
      screen: { url: root.location.href, title: root.document.title },
      task_id: state ? state.task_id : null,
      element: target ? describe(target) : null,
      data: {},
    });
  }

  UX.modules.register({
    name: 'capture',

    /**
     * Empieza a escuchar los clics, en fase de captura para no depender del sitio.
     *
     * @param {object} context - Contexto del módulo.
     * @returns {void}
     */
    start(context) {
      ctx = context;
      CLICK_TYPES.forEach((type) => root.document.addEventListener(type, onClick, true));
    },

    /**
     * Deja de escuchar los clics.
     *
     * @returns {void}
     */
    stop() {
      CLICK_TYPES.forEach((type) => root.document.removeEventListener(type, onClick, true));
      ctx = null;
    },
  });
})(globalThis);
