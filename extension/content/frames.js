/**
 * @file Capturas de la sesión: pide al worker una captura de lo que se ve en la
 * pestaña evaluada cuando algo cambia, para que la reproducción del panel muestre
 * la página real de ese momento, con lo escrito en los campos declarados.
 *
 * Pide una captura (`frame.request`) después de:
 * - cargar la página o cambiar de dirección (aplicaciones de una sola página);
 * - un clic, cuando la página ya respondió;
 * - un scroll o una escritura, cuando se detienen (o cada 1,5 s si siguen);
 * - salir de un campo;
 * - cambios en la página sin interacción (una carga lenta), como máximo cada 3 s.
 *
 * Nunca más de una por segundo. Con cada pedido envía las zonas que el worker
 * tapa antes de guardar la imagen: los campos donde se escribe que el estudio no
 * declaró en `recorded_fields`, y siempre las contraseñas, los códigos y los datos
 * de tarjeta. El worker las vuelve a pedir (`frame.masks`) justo después de
 * capturar y tapa las de las dos mediciones: si la página cambió entre el pedido
 * y la captura, alguna de las dos coincide con la imagen.
 *
 * Limitaciones: no ve campos dentro de iframes ni de shadow DOM, que quedan sin tapar.
 */

(function (root) {
  'use strict';

  const { UX } = root;

  /** Tiempo mínimo entre dos pedidos: el worker no puede capturar más de dos por segundo. */
  const MIN_INTERVAL_MS = 1000;
  /** Si los cambios siguen (scroll largo, escritura continua), se captura igual tras este tiempo. */
  const MAX_WAIT_MS = 1500;
  /** Esperas antes de capturar, para que la página muestre el resultado de lo que pasó. */
  const AFTER_SCREEN_MS = 600;
  const AFTER_CLICK_MS = 350;
  const AFTER_SCROLL_MS = 300;
  const AFTER_TYPING_MS = 700;
  const AFTER_FOCUS_OUT_MS = 100;
  /** Cada cuánto se revisa si la dirección cambió y si la página cambió sola. */
  const SCREEN_POLL_MS = 250;
  const MUTATION_CHECK_MS = 3000;
  /** Margen alrededor de cada zona tapada, en píxeles CSS (bordes y sombras del campo). */
  const MASK_MARGIN_PX = 2;
  /** Campos donde se escribe: los candidatos a taparse. */
  const TYPING_SELECTOR = [
    'input',
    'textarea',
    '[contenteditable]:not([contenteditable="false"])',
    '[role="textbox"]',
    '[role="searchbox"]',
  ].join(',');
  /** Tipos de `input` que no muestran texto escrito: nunca se tapan. */
  const NOT_TYPED_INPUT_TYPES = ['checkbox', 'radio', 'button', 'submit', 'reset', 'image', 'range', 'color', 'file', 'hidden'];
  /** Campos que siempre se tapan, aunque se declaren (mismo criterio que la captura de eventos). */
  const SECRET_AUTOCOMPLETE = /^(current-password|new-password|one-time-code|cc-.*)$/;

  /**
   * Crea el módulo de capturas.
   *
   * @param {object} deps - Dependencias.
   * @param {object} deps.page - Ventana de la página (`window`): documento, tamaño,
   *   dirección, temporizadores y `MutationObserver`.
   * @returns {{name: string, start: function(object): void, stop: function(): void}} Módulo.
   */
  function createFramesModule({ page }) {
    let ctx = null;
    let timer = null;
    let pending = null;
    let lastSent = -Infinity;
    let lastHref = null;
    let screenTimer = null;
    let mutationTimer = null;
    let observer = null;
    let changed = false;
    let stopAnswering = null;

    /** Si el campo siempre se tapa: contraseñas, códigos y datos de tarjeta. */
    function isSecret(element) {
      if ((element.getAttribute('type') || '').toLowerCase() === 'password') {
        return true;
      }
      const tokens = (element.getAttribute('autocomplete') || '').toLowerCase().split(/\s+/);
      return tokens.some((token) => SECRET_AUTOCOMPLETE.test(token));
    }

    /** Si el elemento coincide con un selector; un selector inválido no coincide. */
    function matches(element, selector) {
      try {
        return element.matches(selector);
      } catch (error) {
        return false;
      }
    }

    /** Si el campo se tapa en la captura. */
    function needsMask(element, declared) {
      if (element.tagName.toLowerCase() === 'input') {
        const type = (element.getAttribute('type') || 'text').toLowerCase();
        if (NOT_TYPED_INPUT_TYPES.includes(type)) {
          return false;
        }
      }
      if (isSecret(element)) {
        return true;
      }
      return !declared.some((field) => matches(element, field.selector));
    }

    /**
     * Zonas que se tapan, en píxeles CSS de la ventana. Solo las visibles.
     *
     * @returns {Array<{x: number, y: number, w: number, h: number}>} Zonas.
     */
    function masks() {
      const state = ctx.session.get();
      const declared = (state && state.recorded_fields) || [];
      const width = page.innerWidth;
      const height = page.innerHeight;
      const zones = [];
      for (const element of page.document.querySelectorAll(TYPING_SELECTOR)) {
        if (!needsMask(element, declared)) {
          continue;
        }
        const box = element.getBoundingClientRect();
        const visible =
          box.width > 0 && box.height > 0 && box.right > 0 && box.bottom > 0 && box.left < width && box.top < height;
        if (visible) {
          zones.push({
            x: Math.floor(box.left) - MASK_MARGIN_PX,
            y: Math.floor(box.top) - MASK_MARGIN_PX,
            w: Math.ceil(box.width) + 2 * MASK_MARGIN_PX,
            h: Math.ceil(box.height) + 2 * MASK_MARGIN_PX,
          });
        }
      }
      return zones;
    }

    /** Zonas medidas ahora, con el ancho de la ventana para escalarlas. */
    function measure() {
      return { viewport_width: page.innerWidth, masks: masks() };
    }

    /** Envía el pedido con las zonas medidas ahora. Un fallo no detiene nada. */
    function send() {
      timer = null;
      pending = null;
      lastSent = ctx.clock.now();
      changed = false;
      Promise.resolve(ctx.messages.send(ctx.messages.types.FRAME_REQUEST, measure())).catch(() => {});
    }

    /**
     * Pide una captura dentro de `delay` ms. Si ya había una pedida, se corre hasta
     * el nuevo momento (así se captura cuando el scroll o la escritura se detienen),
     * pero no más de `MAX_WAIT_MS` desde el primer pedido. Nunca antes de un segundo
     * desde la anterior.
     *
     * @param {number} delay - Espera deseada, en milisegundos.
     * @returns {void}
     */
    function want(delay) {
      const now = ctx.clock.now();
      if (pending === null) {
        pending = { first: now, due: now };
      }
      const earliest = lastSent + MIN_INTERVAL_MS;
      const latest = Math.max(pending.first + MAX_WAIT_MS, earliest);
      pending.due = Math.min(Math.max(pending.due, now + delay, earliest), latest);
      page.clearTimeout(timer);
      timer = page.setTimeout(send, pending.due - now);
    }

    const onClick = () => want(AFTER_CLICK_MS);
    const onScroll = () => want(AFTER_SCROLL_MS);
    const onInput = () => want(AFTER_TYPING_MS);
    const onFocusOut = () => want(AFTER_FOCUS_OUT_MS);

    /** Revisa si la dirección cambió (las aplicaciones de una sola página no recargan). */
    function pollScreen() {
      if (page.location.href !== lastHref) {
        lastHref = page.location.href;
        want(AFTER_SCREEN_MS);
      }
      screenTimer = page.setTimeout(pollScreen, SCREEN_POLL_MS);
    }

    /** Si la página cambió sola desde la última captura, pide otra. */
    function checkMutations() {
      if (changed) {
        want(0);
      }
      mutationTimer = page.setTimeout(checkMutations, MUTATION_CHECK_MS);
    }

    return Object.freeze({
      name: 'frames',

      /**
       * Empieza a pedir capturas. La primera, de la página recién cargada.
       *
       * @param {object} context - Contexto de los módulos (reloj, mensajes, sesión).
       * @returns {void}
       */
      start(context) {
        ctx = context;
        stopAnswering = ctx.messages.on(ctx.messages.types.FRAME_MASKS, () => measure());
        const doc = page.document;
        doc.addEventListener('click', onClick, true);
        doc.addEventListener('scroll', onScroll, { capture: true, passive: true });
        doc.addEventListener('input', onInput, true);
        doc.addEventListener('focusout', onFocusOut, true);
        lastHref = page.location.href;
        want(AFTER_SCREEN_MS);
        screenTimer = page.setTimeout(pollScreen, SCREEN_POLL_MS);
        observer = new page.MutationObserver(() => {
          changed = true;
        });
        observer.observe(doc.documentElement, { childList: true, subtree: true, characterData: true });
        mutationTimer = page.setTimeout(checkMutations, MUTATION_CHECK_MS);
      },

      /**
       * Deja de pedir capturas; la que esperaba su turno se descarta.
       *
       * @returns {void}
       */
      stop() {
        const doc = page.document;
        doc.removeEventListener('click', onClick, true);
        doc.removeEventListener('scroll', onScroll, { capture: true, passive: true });
        doc.removeEventListener('input', onInput, true);
        doc.removeEventListener('focusout', onFocusOut, true);
        [timer, screenTimer, mutationTimer].forEach((id) => page.clearTimeout(id));
        if (observer) {
          observer.disconnect();
        }
        if (stopAnswering) {
          stopAnswering();
        }
        stopAnswering = null;
        timer = null;
        screenTimer = null;
        mutationTimer = null;
        observer = null;
        pending = null;
        lastSent = -Infinity;
        changed = false;
        ctx = null;
      },
    });
  }

  UX.createFramesModule = createFramesModule;
  if (UX.platform && UX.modules) {
    UX.modules.register(createFramesModule({ page: root }));
  }
})(globalThis);
