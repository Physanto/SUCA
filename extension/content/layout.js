/**
 * @file Disposición de la pantalla: qué ocupa cada parte de la ventana.
 *
 * Mide las regiones semánticas (`header`, `nav`, `main`, `aside`, `footer`,
 * `search`) y los elementos interactivos visibles, con su rectángulo en la
 * ventana y si tienen posición fija. El registro (`contracts/batches/layout.schema.json`)
 * se toma junto con cada captura de la pestaña (`content/frames.js`) y permite,
 * después de la sesión, asignar zona y elemento a un punto de mirada corregido,
 * cuando la página ya no existe.
 *
 * Usa los mismos criterios que el resto de la pestaña: la región de
 * `content/camera/zones.js` y los elementos interactivos, el selector y la
 * pantalla de la captura de eventos. Nunca lee texto de la página.
 */

(function (root) {
  'use strict';

  const UX = (root.UX = root.UX || {});

  /** Máximo de elementos por registro; los demás se omiten y el registro lo indica. */
  const MAX_ELEMENTS = 300;
  /** Candidatos a región: etiquetas con región propia y cualquier elemento con rol. */
  const REGION_SELECTOR = 'header, footer, nav, main, aside, search, [role]';
  /** Candidatos a elemento interactivo; el filtro final es el de la captura. */
  const ELEMENT_SELECTOR = 'a, button, input, select, textarea, summary, option, [role], [onclick]';
  /** Posiciones que no se mueven con el scroll de la página. */
  const FIXED_POSITIONS = ['fixed', 'sticky'];

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
   * @param {number} [deps.maxElements] - Máximo de elementos por registro.
   * @returns {{measure: function(object, number): object}} Medidor.
   */
  function createLayoutMeter({ regionOf, selectorOf, roleOf, isInteractive, screen, maxElements = MAX_ELEMENTS }) {
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

      const elements = [];
      let truncated = false;
      for (const node of page.document.querySelectorAll(ELEMENT_SELECTOR)) {
        if (!isInteractive(node)) {
          continue;
        }
        const box = visibleBox(node);
        if (!box) {
          continue;
        }
        if (elements.length >= maxElements) {
          truncated = true;
          break;
        }
        const tag = node.tagName.toLowerCase();
        elements.push({ selector: selectorOf(node), tag, role: roleOf(node, tag), box, fixed: isFixed(node) });
      }

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
