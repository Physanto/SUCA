/**
 * @file Zona y elemento de un punto de mirada.
 *
 * La zona se resuelve con una lista ordenada de estrategias:
 * 1. **Regiones semánticas:** la región HTML o ARIA más cercana que contiene al
 *    elemento mirado (`search`, `header`, `nav`, `main`, `aside`, `footer`).
 * 2. **Cuadrícula de 3 × 3** de la ventana, si el elemento no está en ninguna.
 *
 * Los nombres salen de `gaze_zone` en `contracts/enums.json`.
 */

(function (root) {
  'use strict';

  const UX = (root.UX = root.UX || {});

  /** Región de cada rol ARIA. */
  const ROLE_ZONES = {
    search: 'search',
    banner: 'header',
    navigation: 'nav',
    main: 'main',
    complementary: 'aside',
    contentinfo: 'footer',
  };
  /** Región de cada etiqueta. `header` y `footer` solo cuentan si no están dentro de una sección. */
  const TAG_ZONES = { search: 'search', header: 'header', nav: 'nav', main: 'main', aside: 'aside', footer: 'footer' };
  /** Etiquetas que vuelven local a un `header` o `footer`: dejan de ser el de la página. */
  const SECTIONING = ['article', 'aside', 'main', 'nav', 'section'];
  const ROWS = ['top', 'middle', 'bottom'];
  const COLUMNS = ['left', 'center', 'right'];

  /** Etiqueta en minúsculas. */
  const tagOf = (node) => (node.tagName || '').toLowerCase();

  /** Si un `header` o `footer` está dentro de una sección y por eso no es de la página. */
  function isScoped(node) {
    for (let parent = node.parentElement; parent; parent = parent.parentElement) {
      if (SECTIONING.includes(tagOf(parent))) {
        return true;
      }
    }
    return false;
  }

  /** Región semántica propia de un nodo, o `null`. */
  function regionOf(node) {
    const role = node.getAttribute && node.getAttribute('role');
    if (role && ROLE_ZONES[role]) {
      return ROLE_ZONES[role];
    }
    const tag = tagOf(node);
    if (!TAG_ZONES[tag]) {
      return null;
    }
    if ((tag === 'header' || tag === 'footer') && isScoped(node)) {
      return null;
    }
    return TAG_ZONES[tag];
  }

  /**
   * Zona de un punto de la ventana.
   *
   * @param {(Element|null)} element - Elemento bajo el punto, o `null`.
   * @param {number} x - Coordenada horizontal en la ventana.
   * @param {number} y - Coordenada vertical en la ventana.
   * @param {number} width - Ancho de la ventana.
   * @param {number} height - Alto de la ventana.
   * @returns {string} Valor de `gaze_zone`.
   */
  function zoneOf(element, x, y, width, height) {
    for (let node = element; node && node.nodeType === 1; node = node.parentElement) {
      const region = regionOf(node);
      if (region) {
        return region;
      }
    }
    const column = Math.min(2, Math.max(0, Math.floor((3 * x) / width)));
    const row = Math.min(2, Math.max(0, Math.floor((3 * y) / height)));
    return `grid_${ROWS[row]}_${COLUMNS[column]}`;
  }

  /**
   * Selector CSS que ubica al elemento: su `id` si tiene, o la ruta desde `body`.
   * Es el mismo formato que usa la captura de eventos, para poder cruzar la
   * mirada con los clics.
   *
   * @param {Element} element - Elemento.
   * @param {function(string): string} [escape] - Escape de identificadores (`CSS.escape`).
   * @returns {string} Selector.
   */
  function selectorOf(element, escape = (value) => root.CSS.escape(value)) {
    const parts = [];
    for (let node = element; node && node.nodeType === 1; node = node.parentElement) {
      const tag = tagOf(node);
      if (node.id) {
        parts.unshift(`#${escape(node.id)}`);
        break;
      }
      if (tag === 'body' || tag === 'html') {
        parts.unshift(tag);
        break;
      }
      const siblings = node.parentElement ? [...node.parentElement.children] : [node];
      const sameTag = siblings.filter((child) => child.tagName === node.tagName);
      parts.unshift(sameTag.length > 1 ? `${tag}:nth-of-type(${sameTag.indexOf(node) + 1})` : tag);
    }
    return parts.join(' > ');
  }

  UX.gazeZones = Object.freeze({ zoneOf, regionOf, selectorOf });
})(globalThis);
