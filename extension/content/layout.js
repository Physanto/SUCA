/**
 * @file Disposición de la pantalla: qué ocupa cada parte de la ventana.
 *
 * Mide las regiones semánticas (`header`, `nav`, `main`, `aside`, `footer`,
 * `search`) y los elementos visibles, con su rectángulo en la ventana y si
 * tienen posición fija. Los elementos son de dos clases:
 *
 * - **interactivos:** enlaces, botones, campos y elementos con rol interactivo;
 * - **de contenido:** lo que se mira sin interactuar (títulos, párrafos,
 *   imágenes, etiquetas, celdas, mensajes `role="alert"`, tarjetas, secciones)
 *   y los bloques genéricos con texto propio.
 *
 * Cada elemento lleva el índice de su ancestro registrado más cercano
 * (`parent`): juntos forman el árbol de la pantalla. El análisis lo usa para
 * subir de nivel cuando la mirada no alcanza a distinguir dos elementos
 * pequeños vecinos ("estaba en la tarjeta, no se sabe en cuál de sus enlaces").
 *
 * El registro (`contracts/batches/layout.schema.json`) se toma junto con cada
 * captura de la pestaña (`content/frames.js`) y permite, después de la sesión,
 * atribuir la mirada a los elementos cuando la página ya no existe.
 *
 * Usa los mismos criterios que el resto de la pestaña: la región de
 * `content/camera/zones.js` y los elementos interactivos, el selector y la
 * pantalla de la captura de eventos. **Nunca guarda texto de la página:** para
 * decidir si un bloque genérico tiene texto propio solo se comprueba que exista.
 */

(function (root) {
  'use strict';

  const UX = (root.UX = root.UX || {});

  /** Máximo de elementos interactivos por registro; los demás se omiten y el registro lo indica. */
  const MAX_ELEMENTS = 300;
  /** Máximo de elementos de contenido por registro, aparte de los interactivos. */
  const MAX_CONTENT = 300;
  /** Candidatos a región: etiquetas con región propia y cualquier elemento con rol. */
  const REGION_SELECTOR = 'header, footer, nav, main, aside, search, [role]';
  /** Candidatos a elemento interactivo; el filtro final es el de la captura. */
  const ELEMENT_SELECTOR = 'a, button, input, select, textarea, summary, option, [role], [onclick]';
  /** Posiciones que no se mueven con el scroll de la página. */
  const FIXED_POSITIONS = ['fixed', 'sticky'];
  /** Etiquetas de contenido: lo que se mira aunque no se interactúe con ello. */
  const CONTENT_TAGS = [
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'li', 'dt', 'dd', 'label', 'legend', 'caption', 'figcaption',
    'blockquote', 'pre', 'th', 'td', 'img', 'svg', 'picture', 'video', 'canvas', 'figure', 'table',
    'article', 'section', 'form', 'fieldset', 'dialog', 'details',
  ];
  /** Roles de contenido; `alert` y `status` cubren los mensajes de error y de estado. */
  const CONTENT_ROLES = [
    'alert', 'alertdialog', 'status', 'heading', 'img', 'figure', 'dialog', 'article', 'region', 'listitem',
    'cell', 'note', 'tooltip',
  ];
  /** Candidatos a elemento de contenido; el filtro final es `isContent`. */
  const CONTENT_SELECTOR = [...CONTENT_TAGS, '[role]', '[aria-live]', 'div', 'span'].join(', ');
  /**
   * Elementos que se miran como un todo: lo que hay dentro (el ícono de un botón,
   * el `path` de un `svg`) no se registra aparte.
   */
  const ATOMIC_TAGS = ['svg', 'picture', 'video', 'canvas', 'img'];
  /** Lado mínimo, en píxeles CSS, de un elemento de contenido: uno más chico no se puede mirar aparte. */
  const MIN_CONTENT_SIDE = 4;
  /** Tipo de nodo de texto del DOM. */
  const TEXT_NODE = 3;

  /** Redondea a un decimal: más precisión que un píxel no aporta. */
  const round = (value) => Math.round(value * 10) / 10;

  /**
   * Crea el medidor de la disposición.
   *
   * @param {object} deps - Criterios compartidos.
   * @param {function(Element): (string|null)} deps.regionOf - Región propia de un nodo
   *   (`UX.gazeZones.regionOf`).
   * @param {function(Element): string} deps.selectorOf - Selector de un elemento
   *   (`UX.gazeZones.selectorOf`).
   * @param {function(Element, string): (string|null)} deps.roleOf - Rol ARIA de un elemento
   *   (`UX.captureCriteria.roleOf`).
   * @param {function(Element): boolean} deps.isInteractive - Si un elemento es interactivo
   *   (`UX.captureCriteria.isInteractive`).
   * @param {function(): {url: string, title: string}} deps.screen - Pantalla actual, ya
   *   redactada (`UX.captureCriteria.currentScreen`).
   * @param {number} [deps.maxElements] - Máximo de elementos interactivos por registro.
   * @param {number} [deps.maxContent] - Máximo de elementos de contenido por registro.
   * @returns {{measure: function(object, number): object}} Medidor.
   */
  function createLayoutMeter({
    regionOf,
    selectorOf,
    roleOf,
    isInteractive,
    screen,
    maxElements = MAX_ELEMENTS,
    maxContent = MAX_CONTENT,
  }) {
    /** Si el nodo tiene un nodo de texto propio no vacío. Se comprueba, no se lee ni se guarda. */
    function hasOwnText(node) {
      for (const child of node.childNodes || []) {
        if (child.nodeType === TEXT_NODE && /\S/.test(child.nodeValue || '')) {
          return true;
        }
      }
      return false;
    }

    /** Si el nodo es de contenido: etiqueta o rol de contenido, región viva o bloque con texto. */
    function isContent(node, tag) {
      if (CONTENT_TAGS.includes(tag)) {
        return true;
      }
      const role = node.getAttribute('role');
      if (role && CONTENT_ROLES.includes(role)) {
        return true;
      }
      if (node.hasAttribute('aria-live')) {
        return true;
      }
      return (tag === 'div' || tag === 'span') && hasOwnText(node);
    }

    /**
     * Mide la disposición de la ventana.
     *
     * @param {object} page - Ventana de la página (`window`): documento, tamaño, scroll y
     *   `getComputedStyle`.
     * @param {number} t - Momento de la medición.
     * @returns {object} Registro con la forma de `layout.schema.json`.
     */
    function measure(page, t) {
      const width = page.innerWidth;
      const height = page.innerHeight;
      // Un mismo ancestro se consulta para muchos elementos: se calcula una vez por medición.
      const fixedCache = new Map();

      /** Si el nodo o un ancestro tiene posición fija o pegajosa. */
      function isFixed(node) {
        if (!node || node.nodeType !== 1) {
          return false;
        }
        if (fixedCache.has(node)) {
          return fixedCache.get(node);
        }
        const style = page.getComputedStyle(node);
        const fixed = FIXED_POSITIONS.includes(style && style.position) || isFixed(node.parentElement);
        fixedCache.set(node, fixed);
        return fixed;
      }

      /** Rectángulo del nodo si se ve en la ventana; si no, `null`. */
      function visibleBox(node) {
        const box = node.getBoundingClientRect();
        const inside =
          box.width > 0 && box.height > 0 && box.left < width && box.top < height && box.right > 0 && box.bottom > 0;
        if (!inside) {
          return null;
        }
        const style = page.getComputedStyle(node);
        if (style && style.visibility === 'hidden') {
          return null;
        }
        return { x: round(box.left), y: round(box.top), w: round(box.width), h: round(box.height) };
      }

      const regions = [];
      for (const node of page.document.querySelectorAll(REGION_SELECTOR)) {
        const zone = regionOf(node);
        const box = zone && visibleBox(node);
        if (box) {
          regions.push({ zone, box, fixed: isFixed(node) });
        }
      }

      // Un ancestro interactivo o atómico se consulta para muchos nodos: una vez por medición.
      const insideCache = new Map();

      /** Si algún ancestro es interactivo o atómico: el nodo es parte de él, no se registra aparte. */
      function insideWhole(node) {
        const parent = node.parentElement;
        if (!parent || parent.nodeType !== 1) {
          return false;
        }
        if (insideCache.has(parent)) {
          return insideCache.get(parent);
        }
        const inside =
          ATOMIC_TAGS.includes(parent.tagName.toLowerCase()) || isInteractive(parent) || insideWhole(parent);
        insideCache.set(parent, inside);
        return inside;
      }

      const elements = [];
      const nodes = [];
      let truncated = false;

      /** Agrega un elemento visible con su caja y su clase. */
      function add(node, tag, box, interactive) {
        elements.push({
          selector: selectorOf(node),
          tag,
          role: roleOf(node, tag),
          box,
          fixed: isFixed(node),
          interactive,
          parent: null,
        });
        nodes.push(node);
      }

      let interactiveCount = 0;
      for (const node of page.document.querySelectorAll(ELEMENT_SELECTOR)) {
        if (!isInteractive(node)) {
          continue;
        }
        const box = visibleBox(node);
        if (!box) {
          continue;
        }
        if (interactiveCount >= maxElements) {
          truncated = true;
          break;
        }
        add(node, node.tagName.toLowerCase(), box, true);
        interactiveCount += 1;
      }

      const seen = new Set(nodes);
      let contentCount = 0;
      for (const node of page.document.querySelectorAll(CONTENT_SELECTOR)) {
        const tag = node.tagName.toLowerCase();
        if (seen.has(node) || isInteractive(node) || !isContent(node, tag) || insideWhole(node)) {
          continue;
        }
        const box = visibleBox(node);
        if (!box || box.w < MIN_CONTENT_SIDE || box.h < MIN_CONTENT_SIDE) {
          continue;
        }
        if (contentCount >= maxContent) {
          truncated = true;
          break;
        }
        seen.add(node);
        add(node, tag, box, false);
        contentCount += 1;
      }

      // El árbol: cada elemento apunta a su ancestro registrado más cercano.
      const indexOf = new Map(nodes.map((node, index) => [node, index]));
      nodes.forEach((node, index) => {
        for (let ancestor = node.parentElement; ancestor; ancestor = ancestor.parentElement) {
          if (indexOf.has(ancestor)) {
            elements[index].parent = indexOf.get(ancestor);
            break;
          }
        }
      });

      return {
        t,
        screen: screen(),
        viewport_width: width,
        viewport_height: height,
        scroll_x: Math.max(0, round(page.scrollX || 0)),
        scroll_y: Math.max(0, round(page.scrollY || 0)),
        regions,
        elements,
        truncated,
      };
    }

    return Object.freeze({ measure });
  }

  UX.createLayoutMeter = createLayoutMeter;
})(globalThis);
