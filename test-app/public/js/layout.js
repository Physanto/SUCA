/**
 * @file Partes fijas de la página: el contador del carrito, el área de la
 * cuenta con su menú, la búsqueda del encabezado, el menú de categorías
 * activo y los avisos emergentes.
 *
 * El esqueleto está en `index.html`; aquí solo se conecta y se actualiza con
 * el estado de la tienda.
 */

import { countUnits } from './cart.js';
import { h } from './dom.js';
import { productCount } from './format.js';
import { TOAST_MS } from './timing.js';

/** Opciones del menú de la cuenta: texto y destino. */
const MENU_ITEMS = [
  ['Ver mi cuenta', '/account'],
  ['Mis pedidos', '/account#pedidos'],
  ['Ayuda', '/help'],
];

/**
 * Opciones del menú con el problema 3 (`illogical_account_menu`): más opciones,
 * sin orden lógico y con señuelos ("Mi perfil" no tiene la dirección; "Datos
 * de envío" lleva a la ayuda sobre tiempos de entrega). "Ver mi cuenta" conserva
 * su texto y su destino, pero queda al final.
 */
const ILLOGICAL_MENU_ITEMS = [
  ['Mi perfil', '/account/profile'],
  ['Datos de envío', '/help#tiempo-de-entrega'],
  ['Mis cupones', '/offers'],
  ['Novedades', '/products'],
  ['Ayuda', '/help'],
  ['Mis pedidos', '/account#pedidos'],
  ['Ver mi cuenta', '/account'],
];

/**
 * Menú de la cuenta (patrón de divulgación: un botón que muestra y oculta una
 * lista de enlaces). Se cierra con Escape, con un clic fuera o al elegir una opción.
 *
 * @param {object} options - Datos y acciones.
 * @param {string} options.firstName - Nombre de la persona, para el saludo.
 * @param {() => void} options.onLogout - Cierra la sesión.
 * @param {boolean} options.illogical - Si el problema 3 está activo.
 * @returns {HTMLElement} Contenedor del botón y el menú.
 */
function accountMenu({ firstName, onLogout, illogical }) {
  const items = illogical ? ILLOGICAL_MENU_ITEMS : MENU_ITEMS;
  const list = h(
    'ul',
    { class: 'account-menu', id: 'account-menu', hidden: true },
    h('li', { class: 'account-menu-greeting' }, `Hola, ${firstName}`),
    items.map(([label, href]) => h('li', null, h('a', { href }, label))),
    h(
      'li',
      null,
      h('button', { type: 'button', class: 'link-button', on: { click: onLogout } }, 'Cerrar sesión'),
    ),
  );
  const button = h(
    'button',
    {
      type: 'button',
      class: 'account-button',
      'aria-expanded': 'false',
      'aria-controls': 'account-menu',
    },
    'Mi cuenta',
  );
  const wrapper = h('div', { class: 'account-wrapper' }, button, list);

  /** Abre o cierra el menú. */
  const setOpen = (open) => {
    button.setAttribute('aria-expanded', String(open));
    list.hidden = !open;
  };
  button.addEventListener('click', () => setOpen(list.hidden));
  list.addEventListener('click', (event) => {
    if (event.target instanceof Element && event.target.closest('a, button')) setOpen(false);
  });
  wrapper.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !list.hidden) {
      setOpen(false);
      button.focus();
    }
  });
  /** Cierra el menú con un clic fuera; deja de escuchar cuando el menú ya no está. */
  const closeOutside = (event) => {
    if (!wrapper.isConnected) document.removeEventListener('click', closeOutside);
    else if (!wrapper.contains(/** @type {Node} */ (event.target))) setOpen(false);
  };
  document.addEventListener('click', closeOutside);
  return wrapper;
}

/**
 * Conecta el encabezado con la tienda y el router.
 *
 * @param {object} options - Dependencias.
 * @param {object} options.shop - Tienda (`createShop`).
 * @param {(url: string, options?: object) => void} options.navigate - Navegación.
 * @param {(text: string) => void} options.toast - Aviso emergente.
 * @param {ReadonlySet<string>} options.problems - Problemas activos.
 * @returns {{ update: (location: Location) => void }} Actualiza lo que depende
 *   de la ruta (enlace activo, texto de la búsqueda).
 */
export function mountLayout({ shop, navigate, toast, problems }) {
  const cartCount = document.querySelector('.cart-count');
  const accountArea = document.querySelector('.account-area');
  const searchForm = document.querySelector('form[role="search"]');
  const searchInput = searchForm.querySelector('input[name="q"]');

  /** Nombre mostrado en el menú de la cuenta, o `null` sin sesión. */
  let shownName;

  /** Dibuja el contador y el área de la cuenta con el estado actual. */
  const render = (state) => {
    const units = countUnits(state.cart);
    cartCount.textContent = String(units);
    cartCount.hidden = units === 0;
    const link = cartCount.closest('a');
    link.setAttribute('aria-label', units === 0 ? 'Carrito vacío' : `Carrito, ${productCount(units)}`);
    const name = state.user ? state.user.name : null;
    if (shownName === name) return;
    shownName = name;
    accountArea.replaceChildren(
      name
        ? accountMenu({
            firstName: name.split(' ')[0],
            illogical: problems.has('illogical_account_menu'),
            onLogout: () => {
              shop.logout();
              toast('Cerraste sesión.');
              navigate('/login');
            },
          })
        : h('a', { href: '/login', class: 'login-link' }, 'Iniciar sesión'),
    );
  };
  render(shop.get());
  shop.subscribe(render);

  // Boletín: la validación del correo es la nativa; el correo no se guarda.
  const newsletter = document.querySelector('.newsletter-form');
  newsletter.addEventListener('submit', (event) => {
    event.preventDefault();
    newsletter.replaceWith(
      h('p', { class: 'newsletter-done', role: 'status' }, '¡Listo! Te suscribiste al boletín de ofertas.'),
    );
  });

  searchForm.addEventListener('submit', (event) => {
    event.preventDefault();
    const query = searchInput.value.trim();
    if (!query) {
      searchInput.focus();
      return;
    }
    navigate(`/search?q=${encodeURIComponent(query)}`);
  });

  return {
    update(location) {
      for (const link of document.querySelectorAll('.main-nav a')) {
        const active = link.pathname === location.pathname;
        if (active) link.setAttribute('aria-current', 'page');
        else link.removeAttribute('aria-current');
      }
      const params = new URLSearchParams(location.search);
      searchInput.value = location.pathname === '/search' ? (params.get('q') ?? '') : '';
    },
  };
}

/**
 * Crea la función que muestra avisos emergentes en la región `role="status"`.
 *
 * @param {Element} region - Región de avisos de `index.html`.
 * @returns {(text: string) => void} Muestra un aviso durante unos segundos.
 */
export function createToaster(region) {
  return (text) => {
    const toast = h('p', { class: 'toast' }, text);
    region.append(toast);
    setTimeout(() => toast.remove(), TOAST_MS);
  };
}
