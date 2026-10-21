/**
 * @file Captura de interacción (M1): registra lo que hace el participante en la
 * página evaluada (clics, cursor, scroll, selección, formularios y cambios de
 * pantalla), sin capturar nunca lo que escribe.
 *
 * PROVISIONAL: implementación mínima de demostración de la base. Solo registra
 * clics, con un descriptor básico del elemento, para comprobar que un clic
 * viaja de la página a la base de datos. M1 la reemplaza por la captura
 * completa (todos los tipos de evento, descriptor definitivo, filtros de
 * privacidad y respuesta tras el clic).
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
  /** Campos de formulario: su texto nunca se registra. */
  const FIELD_TAGS = ['input', 'textarea', 'select'];
  /** Etiquetas y roles que se consideran interactivos en esta versión básica. */
  const INTERACTIVE_TAGS = ['a', 'button', 'input', 'select', 'textarea', 'summary', 'option'];
  const INTERACTIVE_ROLES = [
    'button', 'link', 'checkbox', 'radio', 'menuitem', 'tab', 'switch', 'option',
    'textbox', 'searchbox', 'combobox',
  ];
  /** Roles implícitos de las etiquetas más comunes. */
  const IMPLICIT_ROLES = {
    a: 'link',
    button: 'button',
    select: 'combobox',
    textarea: 'textbox',
    nav: 'navigation',
    main: 'main',
    form: 'form',
  };
  const INPUT_ROLES = { checkbox: 'checkbox', radio: 'radio', search: 'searchbox', button: 'button', submit: 'button', reset: 'button' };

  let ctx = null;

  /** Rol ARIA explícito o, si no tiene, el implícito de su etiqueta. */
  function roleOf(element, tag) {
    const explicit = element.getAttribute('role');
    if (explicit) {
      return explicit;
    }
    if (tag === 'input') {
      return INPUT_ROLES[element.type] || 'textbox';
    }
    if (tag === 'a' && !element.hasAttribute('href')) {
      return null;
    }
    return IMPLICIT_ROLES[tag] || null;
  }

  /**
   * Texto visible recortado, o `null`. Nunca se toma de campos ni de zonas
   * editables, porque contendría lo que escribe el participante.
   */
  function textOf(element, tag) {
    const editable = '[contenteditable]:not([contenteditable="false"])';
    if (FIELD_TAGS.includes(tag) || element.closest(editable) || element.querySelector(editable)) {
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
      const sameTag = [...node.parentElement.children].filter((child) => child.tagName === node.tagName);
      parts.unshift(sameTag.length > 1 ? `${tag}:nth-of-type(${sameTag.indexOf(node) + 1})` : tag);
    }
    return parts.join(' > ');
  }

  /**
   * Describe un elemento con la forma de `contracts/element.schema.json`.
   *
   * @param {Element} element - Elemento sobre el que ocurrió el evento.
   * @returns {object} Descriptor del elemento.
   */
  function describe(element) {
    const tag = element.tagName.toLowerCase();
    const role = roleOf(element, tag);
    const box = element.getBoundingClientRect();
    return {
      tag,
      id: element.id || null,
      role,
      text: textOf(element, tag),
      selector: selectorOf(element),
      box: { x: box.x, y: box.y, w: box.width, h: box.height },
      interactive:
        INTERACTIVE_TAGS.includes(tag) || INTERACTIVE_ROLES.includes(role) || element.hasAttribute('onclick'),
    };
  }

  /** Registra un clic con sus coordenadas y el elemento. */
  function onClick(event) {
    const state = ctx.session.get();
    const target = event.target instanceof Element ? event.target : null;
    ctx.batcher.add('events', {
      t: ctx.clock.now(),
      type: 'click',
      x: event.clientX,
      y: event.clientY,
      screen: { url: root.location.href, title: root.document.title },
      task_id: state ? state.task_id : null,
      element: target ? describe(target) : null,
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
      root.document.addEventListener('click', onClick, true);
    },

    /**
     * Deja de escuchar los clics.
     *
     * @returns {void}
     */
    stop() {
      root.document.removeEventListener('click', onClick, true);
      ctx = null;
    },
  });
})(globalThis);
