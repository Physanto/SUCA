/**
 * @file Rutas de la aplicación de una sola página con el historial del
 * navegador (`history.pushState` y `popstate`), como la mayoría de las SPA
 * actuales: cada pantalla tiene una URL real (`/product/101`) que se puede
 * recargar o abrir directamente.
 */

/**
 * @typedef {object} RouteMatch
 * @property {object} route - Definición de la ruta que coincidió.
 * @property {Object<string, string>} params - Parámetros de la ruta (`:id`).
 */

/**
 * Prepara las rutas: convierte cada patrón (`/product/:id`) en una expresión
 * regular.
 *
 * @param {ReadonlyArray<{ path: string }>} definitions - Rutas con su patrón.
 * @returns {Array<object>} Las mismas rutas con `regex` y `keys`.
 */
export function compileRoutes(definitions) {
  return definitions.map((definition) => {
    const keys = [];
    const source = definition.path
      .split('/')
      .map((segment) => {
        if (!segment.startsWith(':')) return segment.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        keys.push(segment.slice(1));
        return '([^/]+)';
      })
      .join('/');
    return { ...definition, keys, regex: new RegExp(`^${source}/?$`) };
  });
}

/**
 * Busca la primera ruta que coincide con una ruta de URL.
 *
 * @param {ReadonlyArray<object>} routes - Rutas preparadas con `compileRoutes`.
 * @param {string} pathname - Ruta de la URL, sin consulta ni fragmento.
 * @returns {RouteMatch|null} La ruta y sus parámetros, o `null`.
 */
export function matchRoute(routes, pathname) {
  for (const route of routes) {
    const found = route.regex.exec(pathname);
    if (found) {
      const params = {};
      route.keys.forEach((key, index) => {
        params[key] = decodeURIComponent(found[index + 1]);
      });
      return { route, params };
    }
  }
  return null;
}

/**
 * Indica si un clic en un enlace debe manejarlo la aplicación en lugar del
 * navegador.
 *
 * @param {MouseEvent} event - Clic.
 * @param {HTMLAnchorElement} link - Enlace pulsado.
 * @param {Location} location - Ubicación actual.
 * @returns {boolean} `true` para enlaces internos sin teclas modificadoras.
 */
export function isAppLink(event, link, location) {
  if (event.defaultPrevented || event.button !== 0) return false;
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return false;
  if (link.target && link.target !== '_self') return false;
  if (link.hasAttribute('download') || link.origin !== location.origin) return false;
  // Archivos con extensión (por ejemplo, /terms.html) se abren como página aparte.
  if (/\.[a-z0-9]+$/i.test(link.pathname)) return false;
  // Un ancla de la misma página la maneja el navegador (solo cambia el fragmento).
  return !(link.pathname === location.pathname && link.search === location.search && link.hash);
}

/**
 * Crea el router sobre una ventana del navegador.
 *
 * @param {object} options - Dependencias.
 * @param {Window} options.window - Ventana (historial, ubicación y documento).
 * @param {(location: Location, how: { initial: boolean, pop: boolean }) => void} options.onChange
 *   - Se llama al iniciar y en cada cambio de ruta.
 * @returns {{ start: () => void, navigate: (url: string, options?: { replace?: boolean }) => void }}
 *   Router.
 */
export function createRouter({ window, onChange }) {
  const { history, location, document } = window;

  /** Guarda el scroll de la entrada actual para restaurarlo al volver. */
  function rememberScroll() {
    history.replaceState({ ...(history.state ?? {}), scrollY: window.scrollY }, '');
  }

  /**
   * Va a otra ruta de la aplicación.
   *
   * @param {string} url - Ruta con consulta y fragmento opcionales.
   * @param {{ replace?: boolean }} [options] - `replace` no agrega una entrada al historial.
   */
  function navigate(url, { replace = false } = {}) {
    if (replace) {
      history.replaceState({ scrollY: 0 }, '', url);
    } else {
      rememberScroll();
      history.pushState({ scrollY: 0 }, '', url);
    }
    onChange(location, { initial: false, pop: false });
  }

  return {
    navigate,
    start() {
      // El scroll se restaura a mano porque el contenido se dibuja después de
      // cambiar la URL y el navegador lo restauraría antes de tiempo.
      history.scrollRestoration = 'manual';
      document.addEventListener('click', (event) => {
        const link = event.target instanceof Element ? event.target.closest('a[href]') : null;
        if (!link || !isAppLink(event, link, location)) return;
        event.preventDefault();
        const url = `${link.pathname}${link.search}${link.hash}`;
        if (url === `${location.pathname}${location.search}${location.hash}`) return;
        navigate(url);
      });
      window.addEventListener('popstate', () => onChange(location, { initial: false, pop: true }));
      onChange(location, { initial: true, pop: false });
    },
  };
}
