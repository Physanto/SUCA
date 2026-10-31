/**
 * @file Comprobación de cada problema sembrado en Chrome sin interfaz.
 *
 * Para cada problema abre la tienda dos veces: con solo ese problema activo
 * (`?problems=N`), donde debe verse el problema, y en V0, donde debe verse el
 * comportamiento correcto. Así se comprueba que cada problema se activa por
 * separado y que V0 no tiene ninguno.
 *
 * Los clics esperan lo mismo que la captura: un clic "sin respuesta" es uno
 * tras el cual el DOM no cambia en 1,5 s.
 *
 * Requiere la app servida (`python -m scripts.serve_test_app`) y Chrome.
 *
 * Uso:
 *   node test-app/e2e/problems.js [--url http://127.0.0.1:8767] [--only 4]
 */

import assert from 'node:assert/strict';
import { parseArgs } from 'node:util';

import { DEMO_ACCOUNT, TEST_CARD } from '../public/js/data.js';
import { launch } from './browser.js';

const { values: options } = parseArgs({
  options: {
    url: { type: 'string', default: 'http://127.0.0.1:8767' },
    only: { type: 'string' },
  },
});

/** Tiempo que la captura observa la página tras un clic. */
const CLICK_RESPONSE_MS = 1500;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Abre la tienda limpia con una configuración y en una ruta.
 *
 * @param {import('./browser.js').Page} page - Pestaña.
 * @param {string} setting - `version=V0` o `problems=N`.
 * @param {string} path - Ruta inicial.
 */
async function open(page, setting, path) {
  await page.goto(`${options.url}${path}?${setting}`);
}

/** Inicia sesión desde `/login` con la cuenta de demostración. */
async function login(page) {
  await page.fill('Correo electrónico', DEMO_ACCOUNT.email);
  await page.fill('Contraseña', DEMO_ACCOUNT.password);
  await page.click('button', 'Ingresar');
  await page.waitForPath(/^\/$/);
}

/** Con sesión iniciada, agrega el producto 101 y llega al pago con tarjeta. */
async function reachCardPayment(page) {
  await page.goto(`${options.url}/product/101`);
  await page.click('button', 'Agregar al carrito');
  await page.waitForPath(/^\/cart$/);
  await page.click('a', 'Ir a pagar');
  await page.waitForPath(/^\/checkout\/shipping$/);
  await page.click('button', 'Continuar al pago');
  await page.waitForPath(/^\/checkout\/payment$/);
  await page.click('input', 'Tarjeta de crédito o débito');
}

/** Llena la tarjeta tal como se muestra en pantalla y pulsa "Pagar". */
async function payAsShown(page) {
  await page.fill('Número de la tarjeta', TEST_CARD.number);
  await page.fill('Nombre como aparece en la tarjeta', TEST_CARD.name);
  await page.fill('Vencimiento', TEST_CARD.expiry);
  await page.fill('Código de seguridad', TEST_CARD.cvc);
  await page.click('button', await page.evaluate("document.querySelector('main button[type=submit]').innerText.trim()"));
}

/** Relación de contraste WCAG entre el color de un elemento y el fondo de su tarjeta. */
const CONTRAST = `(selectorText) => {
  const link = [...document.querySelectorAll('a')].find((a) => a.innerText.trim() === selectorText);
  const rgb = (color) => color.match(/\\d+(\\.\\d+)?/g).slice(0, 3).map(Number);
  const lum = ([r, g, b]) => {
    const c = [r, g, b].map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; });
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
  };
  let node = link;
  let bg = 'rgba(0, 0, 0, 0)';
  while (node && (bg === 'rgba(0, 0, 0, 0)' || bg === 'transparent')) { bg = getComputedStyle(node).backgroundColor; node = node.parentElement; }
  const [a, b] = [lum(rgb(getComputedStyle(link).color)), lum(rgb(bg))].sort((x, y) => y - x);
  return (a + 0.05) / (b + 0.05);
}`;

/**
 * Comprobaciones por número de problema: qué debe pasar con el problema
 * activo (`active = true`) y en V0 (`active = false`).
 */
const CHECKS = {
  1: async (page, active) => {
    await page.goto(`${options.url}/product/101`);
    if (active) {
      assert.equal(await page.evaluate("[...document.querySelectorAll('main button')].some((b) => b.innerText.includes('Ampliar'))"), false);
      await page.watchMutations();
      await page.clickSelector('img.zoom-badge');
      await sleep(CLICK_RESPONSE_MS);
      assert.equal(await page.mutations(), 0, 'the image must not respond');
    } else {
      await page.click('button', 'Ampliar imagen');
      await page.waitFor("document.querySelector('dialog').open", 'open dialog');
    }
  },
  2: async (page, active) => {
    await page.goto(`${options.url}/product/101`);
    await page.watchMutations();
    await page.click('button', 'Agregar al carrito', { times: 3 });
    await sleep(CLICK_RESPONSE_MS);
    const changes = await page.mutations();
    if (active) assert.equal(changes, 0, 'no visible response in the first 1.5 s');
    else assert.ok(changes > 0, 'immediate feedback');
    await page.waitForPath(/^\/cart$/);
    await page.waitForText('Tienes 1 producto en tu carrito.');
  },
  3: async (page, active) => {
    await login(page);
    await page.click('button', 'Mi cuenta');
    const items = await page.evaluate("[...document.querySelectorAll('.account-menu a')].map((a) => a.innerText.trim())");
    if (active) {
      assert.equal(items[0], 'Mi perfil');
      assert.ok(items.includes('Datos de envío'));
      assert.equal(items.at(-1), 'Ver mi cuenta');
    } else {
      assert.equal(items[0], 'Ver mi cuenta');
      assert.ok(!items.includes('Mi perfil'));
    }
    await page.click('a', 'Ver mi cuenta');
    await page.waitForPath(/^\/account$/);
  },
  4: async (page, active) => {
    await login(page);
    await reachCardPayment(page);
    await payAsShown(page);
    if (active) {
      await page.waitForText('Revisa los datos de pago marcados.');
      assert.equal(await page.evaluate("document.querySelector('#card-number').value + document.querySelector('#card-name').value"), '');
      assert.equal(await page.evaluate("document.querySelector('#card-number').getAttribute('aria-invalid')"), 'true');
      assert.equal(await page.evaluate("document.querySelector('#card-number').placeholder"), 'Solo números, sin espacios');
    } else {
      await page.waitForPath(/^\/order\/\d+\/confirmation$/);
    }
  },
  5: async (page, active) => {
    await login(page);
    await page.goto(`${options.url}/account`);
    const ratio = await page.evaluate(`(${CONTRAST})('Cambiar dirección de envío')`);
    if (active) assert.ok(ratio < 2, `contrast ${ratio.toFixed(2)} must be very low`);
    else assert.ok(ratio >= 4.5, `contrast ${ratio.toFixed(2)} must pass AA`);
    await page.click('a', 'Cambiar dirección de envío');
    await page.waitForPath(/^\/account\/address$/);
  },
  6: async (page, active) => {
    await login(page);
    await reachCardPayment(page);
    await payAsShown(page);
    if (active) {
      await page.waitForText('(Código E-102)');
      assert.equal(await page.evaluate("document.querySelectorAll('main [aria-invalid=true]').length"), 0);
      assert.equal(await page.evaluate("document.querySelector('#card-number').value"), TEST_CARD.number);
      assert.equal(await page.evaluate("document.querySelector('#card-expiry').placeholder"), 'MM/AAAA');
    } else {
      await page.waitForPath(/^\/order\/\d+\/confirmation$/);
    }
  },
  7: async (page, active) => {
    await page.fill('Correo electrónico', DEMO_ACCOUNT.email);
    await page.fill('Contraseña', DEMO_ACCOUNT.password);
    await page.watchMutations();
    await page.click('button', 'Ingresar', { times: 3 });
    await sleep(CLICK_RESPONSE_MS);
    const changes = await page.mutations();
    if (active) assert.equal(changes, 0, 'no visible response in the first 1.5 s');
    else assert.ok(changes > 0, 'immediate feedback');
    await page.waitForPath(/^\/$/);
  },
  8: async (page, active) => {
    await page.fill('Buscar productos', 'audfonos inalambricos');
    await page.press('Enter');
    await page.waitForPath(/^\/search/);
    if (active) await page.waitForText('No encontramos productos');
    else await page.waitForText('Audífonos inalámbricos SoundMax');
  },
};

/** Ruta en la que empieza cada comprobación. */
const START = { 7: '/login', 8: '/' };

const page = await launch({ width: 920, height: 800 });
let failed = false;
try {
  for (const [number, check] of Object.entries(CHECKS)) {
    if (options.only && options.only !== number) continue;
    for (const [setting, active] of [[`problems=${number}`, true], ['version=V0', false]]) {
      const name = `problem ${number} ${active ? 'active' : 'in V0'}`;
      try {
        await open(page, setting, START[number] ?? '/login');
        await check(page, active);
        console.log(`ok - ${name}`);
      } catch (error) {
        failed = true;
        const url = await page.evaluate('location.href').catch(() => '?');
        console.log(`not ok - ${name}\n  ${error.message}\n  at: ${url}`);
      }
    }
  }
  if (page.errors.length > 0) {
    failed = true;
    console.log(`not ok - page errors:\n  ${page.errors.join('\n  ')}`);
  }
} finally {
  await page.close();
}
console.log(failed ? 'problems check failed' : 'problems check passed');
process.exitCode = failed ? 1 : 0;
