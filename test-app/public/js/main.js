/**
 * @file Punto de composición de la tienda: lee la versión elegida, crea el
 * estado, conecta el encabezado y dibuja la pantalla de cada ruta.
 *
 * Es el único archivo que toca `window`, `localStorage` y el contenido
 * principal; las pantallas reciben lo que necesitan en el contexto `ctx`.
 */

import { createToaster, mountLayout } from './layout.js';
import { compileRoutes, createRouter, matchRoute } from './router.js';
import { loadSettings, saveSettings, settingsFromParams, withoutSettingsParams } from './settings.js';
import { createShop } from './shop.js';
import { loadingBlock } from './ui.js';
import { activeProblems } from './versions.js';
import * as account from './views/account.js';
import * as cart from './views/cart.js';
import * as category from './views/category.js';
import * as checkout from './views/checkout.js';
import * as help from './views/help.js';
import * as home from './views/home.js';
import * as login from './views/login.js';
import * as notFound from './views/not-found.js';
import * as product from './views/product.js';
import * as search from './views/search.js';
import * as setup from './views/setup.js';

/** Nombre de la tienda, al final del título de cada pantalla. */
const STORE_NAME = 'Ceiba';

/** Tiempo antes de mostrar "Cargando…", para no parpadear en pantallas rápidas. */
const LOADING_DELAY_MS = 100;

/**
 * Rutas de la tienda. `auth` exige sesión iniciada; sin ella se pasa por
 * `/login` y se vuelve a la ruta pedida.
 */
const ROUTES = compileRoutes([
  { path: '/', render: home.render },
  { path: '/login', render: login.render },
  { path: '/search', render: search.render },
  { path: '/products', render: category.renderAll },
  { path: '/category/:slug', render: category.render },
  { path: '/offers', render: category.renderOffers },
  { path: '/product/:id', render: product.render },
  { path: '/cart', render: cart.render },
  { path: '/checkout/shipping', auth: true, render: checkout.renderShipping },
  { path: '/checkout/payment', auth: true, render: checkout.renderPayment },
  { path: '/order/:id/confirmation', auth: true, render: checkout.renderConfirmation },
  { path: '/account', auth: true, render: account.renderAccount },
  { path: '/account/address', auth: true, render: account.renderAddress },
  { path: '/account/profile', auth: true, render: account.renderProfile },
  { path: '/account/orders/:id', auth: true, render: account.renderOrder },
  { path: '/help', render: help.render },
  { path: '/setup', render: setup.render },
]);

/**
 * Aplica la versión pedida en la URL, si la hay, y la quita de la dirección.
 * Pedir una versión desde la URL deja la tienda lista para un participante
 * nuevo (sin sesión, carrito ni pedidos).
 *
 * @param {Storage} storage - Almacenamiento del navegador.
 * @param {ReturnType<typeof createShop>} shop - Tienda.
 * @returns {import('./versions.js').Settings} Configuración vigente.
 */
function applySettingsFromUrl(storage, shop) {
  const url = new URL(window.location.href);
  const requested = settingsFromParams(url.searchParams);
  if (requested.error) console.warn(`test app: ignored settings in URL: ${requested.error}`);
  if (requested.settings) {
    saveSettings(storage, requested.settings);
    shop.reset();
  }
  if (requested.settings || requested.error) {
    window.history.replaceState(null, '', withoutSettingsParams(url));
  }
  return loadSettings(storage);
}

/** Arranca la tienda. */
function start() {
  const storage = window.localStorage;
  const shop = createShop(storage);
  const settings = applySettingsFromUrl(storage, shop);
  const main = document.querySelector('main');
  const toast = createToaster(document.querySelector('.toast-region'));
  let cleanup = null;
  let current = 0;

  const router = createRouter({ window, onChange: show });
  const ctx = Object.freeze({
    shop,
    settings,
    storage,
    problems: activeProblems(settings),
    navigate: router.navigate,
    replaceQuery: router.replaceQuery,
    toast,
    now: () => new Date(),
  });
  const layout = mountLayout({ shop, navigate: router.navigate, toast });

  /**
   * Dibuja la pantalla de la ruta actual.
   *
   * @param {Location} location - Ubicación actual.
   * @param {{ initial: boolean, pop: boolean }} how - Cómo se llegó a la ruta.
   */
  async function show(location, how) {
    const id = (current += 1);
    const match = matchRoute(ROUTES, location.pathname);
    if (match?.route.auth && !shop.get().user) {
      const next = `${location.pathname}${location.search}${location.hash}`;
      toast('Inicia sesión para continuar.');
      router.navigate(`/login?next=${encodeURIComponent(next)}`, { replace: true });
      return;
    }
    cleanup?.();
    cleanup = null;
    layout.update(location);
    main.setAttribute('aria-busy', 'true');
    // Solo si esta navegación sigue siendo la actual: si la persona ya fue a
    // otra pantalla, el aviso taparía la pantalla nueva.
    const timer = setTimeout(() => {
      if (id === current) main.replaceChildren(loadingBlock());
    }, LOADING_DELAY_MS);
    let result;
    try {
      const route = {
        params: match?.params ?? {},
        query: new URLSearchParams(location.search),
        hash: decodeURIComponent(location.hash.slice(1)),
      };
      result = match ? await match.route.render(ctx, route) : { notFound: true };
      if (result.notFound) result = notFound.render();
    } catch (error) {
      console.error('test app: screen failed to render', error);
      result = notFound.render();
    } finally {
      clearTimeout(timer);
    }
    // Si la persona ya fue a otra ruta mientras esta cargaba, se descarta.
    if (id !== current) {
      result.cleanup?.();
      return;
    }
    if (result.redirect) {
      router.navigate(result.redirect, { replace: true });
      return;
    }
    main.replaceChildren(result.node);
    main.removeAttribute('aria-busy');
    cleanup = result.cleanup ?? null;
    document.title = `${result.title} · ${STORE_NAME}`;
    placeView(location, how);
  }

  /**
   * Ubica la vista recién dibujada: restaura el scroll al volver, baja a un
   * ancla si la URL la tiene y lleva el foco al título para los lectores de pantalla.
   *
   * @param {Location} location - Ubicación actual.
   * @param {{ initial: boolean, pop: boolean }} how - Cómo se llegó a la ruta.
   */
  function placeView(location, how) {
    const anchor = location.hash ? document.getElementById(decodeURIComponent(location.hash.slice(1))) : null;
    if (how.pop) window.scrollTo(0, window.history.state?.scrollY ?? 0);
    else if (anchor) anchor.scrollIntoView();
    else window.scrollTo(0, 0);
    if (!how.initial) main.querySelector('h1')?.focus({ preventScroll: true });
  }

  router.start();
}

start();
