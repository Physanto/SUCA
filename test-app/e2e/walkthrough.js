/**
 * @file Recorrido automático de la tienda en Chrome sin interfaz: inicio de
 * sesión y las 4 tareas del estudio de ejemplo, como las haría una persona, y
 * después las demás funciones del sitio (listados, diálogo, anclas, cuenta,
 * boletín y página aparte).
 *
 * Comprueba que cada tarea llega a su estado final, que recargar una ruta
 * funciona, que ordenar o saltar a un ancla no cambia de pantalla y que la
 * página no tiene errores de JavaScript. La ventana mide
 * 920 × 800, el espacio que queda con el panel lateral de Chrome abierto.
 *
 * Requiere la app servida (`python -m scripts.serve_test_app`) y Chrome
 * instalado (o la variable `CHROME_PATH`).
 *
 * Pasa en V0, V1 y V2: los problemas sembrados agregan fricción, pero no
 * cambian la ruta ideal de ninguna tarea.
 *
 * Uso:
 *   node test-app/e2e/walkthrough.js [--url http://127.0.0.1:8767] [--version V0]
 */

import assert from 'node:assert/strict';
import { parseArgs } from 'node:util';

import { DEMO_ACCOUNT, TEST_CARD } from '../public/js/data.js';
import { launch } from './browser.js';

const { values: options } = parseArgs({
  options: {
    url: { type: 'string', default: 'http://127.0.0.1:8767' },
    version: { type: 'string', default: 'V0' },
  },
});

/** Pasos del recorrido: nombre y acción. */
const STEPS = [
  [
    'opens the store with the requested version and a clean address',
    async (page) => {
      await page.goto(`${options.url}/login?version=${options.version}`);
      assert.equal(await page.evaluate('location.pathname + location.search'), '/login');
      assert.equal(await page.evaluate('document.title'), 'Iniciar sesión · Ceiba');
    },
  ],
  [
    'logs in with the demo account',
    async (page) => {
      await page.fill('Correo electrónico', DEMO_ACCOUNT.email);
      await page.fill('Contraseña', DEMO_ACCOUNT.password);
      await page.click('button', 'Ingresar');
      await page.waitForPath(/^\/$/);
    },
  ],
  [
    'task 1: searches the headphones and opens the first result',
    async (page) => {
      await page.fill('Buscar productos', 'audifonos inalambricos');
      await page.press('Enter');
      await page.waitForPath(/^\/search\?q=audifonos/);
      await page.click('main a', 'Audífonos inalámbricos SoundMax');
      await page.waitForPath(/^\/product\/101$/);
    },
  ],
  [
    'task 2: adds two units to the cart',
    async (page) => {
      await page.click('button', 'Aumentar cantidad');
      await page.click('button', 'Agregar al carrito');
      await page.waitForPath(/^\/cart$/);
      await page.waitForText('Audífonos inalámbricos SoundMax × 2');
    },
  ],
  [
    'task 3: completes the purchase paying by card',
    async (page) => {
      await page.click('a', 'Ir a pagar');
      await page.waitForPath(/^\/checkout\/shipping$/);
      await page.click('button', 'Continuar al pago');
      await page.waitForPath(/^\/checkout\/payment$/);
      await page.click('input', 'Tarjeta de crédito o débito');
      // Sin espacios y con el año completo: el formato que aceptan las tres
      // versiones. Así el mismo recorrido comprueba que la ruta ideal no cambia.
      await page.fill('Número de la tarjeta', TEST_CARD.number.replace(/\s/g, ''));
      await page.fill('Nombre como aparece en la tarjeta', TEST_CARD.name);
      await page.fill('Vencimiento', TEST_CARD.expiry.replace('/', '/20'));
      await page.fill('Código de seguridad', TEST_CARD.cvc);
      await page.click('button', await page.evaluate("document.querySelector('main button[type=submit]').innerText.trim()"));
      await page.waitForPath(/^\/order\/\d+\/confirmation$/);
      await page.waitForText('Pedido confirmado');
    },
  ],
  [
    'task 4: changes the shipping address from the account menu',
    async (page) => {
      await page.click('button', 'Mi cuenta');
      await page.click('a', 'Ver mi cuenta');
      await page.waitForPath(/^\/account$/);
      await page.click('a', 'Cambiar dirección de envío');
      await page.waitForPath(/^\/account\/address$/);
      await page.fill('Dirección', 'Calle 10 # 20-30');
      await page.select('Ciudad', 'Bogotá');
      await page.click('button', 'Guardar');
      await page.waitForText('Dirección actualizada');
    },
  ],
  [
    'reloads a deep route and keeps the saved state',
    async (page) => {
      await page.reload();
      assert.equal(await page.evaluate('location.pathname'), '/account/address');
      assert.equal(await page.evaluate("document.querySelector('#street').value"), 'Calle 10 # 20-30');
    },
  ],
  [
    'goes back through the history',
    async (page) => {
      await page.back();
      await page.waitForPath(/^\/account$/);
      await page.waitForText('Calle 10 # 20-30');
    },
  ],
  [
    'listing: sorts and filters in place and loads more products',
    async (page) => {
      await page.click('a', 'Inicio');
      await page.waitForPath(/^\/$/);
      await page.click('a', 'Ver todos los productos');
      await page.waitForPath(/^\/products$/);
      const entries = await page.evaluate('history.length');
      await page.evaluate("window.listingMarker = document.querySelector('main h1')");
      await page.select('Ordenar por', 'Menor precio');
      await page.waitFor("location.search === '?sort=price_asc'", 'sort in the URL');
      const prices = await page.evaluate(
        "[...document.querySelectorAll('.product-grid .price-current')].map((e) => Number(e.textContent.replace(/\\D/g, '')))",
      );
      assert.deepEqual(prices, [...prices].sort((a, b) => a - b));
      await page.click('button', 'Cargar más productos');
      await page.waitFor("document.querySelectorAll('.product-grid li').length === 16", '16 products');
      await page.click('input', 'Solo con descuento');
      await page.waitFor("location.search === '?sort=price_asc&discount=1'", 'filter in the URL');
      assert.equal(await page.evaluate('history.length'), entries);
      assert.equal(await page.evaluate("window.listingMarker === document.querySelector('main h1')"), true);
    },
  ],
  [
    'listing: a click on a product image opens its detail through the name link',
    async (page) => {
      // Lo que queda bajo el centro de la imagen es el enlace del nombre: el clic
      // se registra igual que un clic en el nombre (mismo texto y mismo rol).
      const target = await page.evaluate(`(() => {
        const image = document.querySelector('.product-grid .product-image');
        image.scrollIntoView({ block: 'center' });
        const box = image.getBoundingClientRect();
        const hit = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
        const card = image.closest('.product-card');
        return { tag: hit.tagName, same: hit === card.querySelector('.product-card-title a') };
      })()`);
      assert.deepEqual(target, { tag: 'A', same: true });
      await page.clickSelector('.product-grid .product-image');
      await page.waitForPath(/^\/product\/\d+$/);
      await page.back();
      await page.waitForPath(/^\/products\?sort=price_asc&discount=1$/);
    },
  ],
  [
    'product: opens and closes the image dialog and jumps to the reviews in place',
    async (page) => {
      await page.fill('Buscar productos', 'parlante');
      await page.press('Enter');
      await page.waitForPath(/^\/search\?q=parlante$/);
      await page.click('main a', 'Parlante portátil Ritmo Mini');
      await page.waitForPath(/^\/product\/104$/);
      // Con el problema 1 activo el botón es una imagen sin diálogo (lo comprueba problems.js).
      if (!(await page.evaluate("!!document.querySelector('img.zoom-badge')"))) {
        await page.click('button', 'Ampliar imagen');
        await page.waitFor("document.querySelector('dialog').open", 'open dialog');
        await page.press('Escape');
        await page.waitFor("!document.querySelector('dialog').open", 'closed dialog');
      }
      await page.evaluate("window.productMarker = document.querySelector('main h1')");
      await page.click('a', 'Ver opiniones');
      await page.waitFor("location.hash === '#resenas'", 'reviews anchor');
      await new Promise((resolve) => setTimeout(resolve, 400));
      assert.equal(await page.evaluate("window.productMarker === document.querySelector('main h1')"), true);
    },
  ],
  [
    'account: edits the personal data and opens an order',
    async (page) => {
      await page.click('button', 'Mi cuenta');
      await page.click('a', 'Ver mi cuenta');
      await page.waitForPath(/^\/account$/);
      await page.click('a', 'Editar datos personales');
      await page.waitForPath(/^\/account\/profile$/);
      await page.fill('Nombre completo', 'Ana María Gómez');
      await page.click('button', 'Guardar');
      await page.waitForText('Datos actualizados');
      await page.click('a', 'Volver a mi cuenta');
      await page.waitForText('Ana María Gómez');
      const order = await page.evaluate("document.querySelector('.orders-table a').innerText");
      await page.click('a', order);
      await page.waitForPath(/^\/account\/orders\/\d+$/);
      await page.waitForText(`Pedido ${order}`);
    },
  ],
  [
    'footer: subscribes to the newsletter and opens the terms as a separate page',
    async (page) => {
      await page.fill('Correo electrónico', 'nombre@ejemplo.com');
      await page.click('button', 'Suscribirme');
      await page.waitForText('Te suscribiste al boletín');
      await page.click('a', 'Términos y condiciones');
      await page.waitFor("location.pathname === '/terms.html' && document.readyState === 'complete'", 'terms page');
      await page.click('main a', 'Volver a la tienda');
      await page.waitForPath(/^\/$/);
    },
  ],
  [
    'login: the forgotten password link opens its answer in the help',
    async (page) => {
      await page.click('button', 'Mi cuenta');
      await page.click('button', 'Cerrar sesión');
      await page.waitForPath(/^\/login$/);
      await page.click('a', '¿Olvidaste tu contraseña?');
      await page.waitForPath(/^\/help$/);
      await page.waitFor("document.getElementById('olvide-mi-contrasena').open", 'open answer');
    },
  ],
];

const page = await launch({ width: 920, height: 800 });
let failed = false;
try {
  for (const [name, step] of STEPS) {
    try {
      await step(page);
      // Un valor sin dibujar (null, undefined, NaN) delata un error de la vista.
      const leaked = await page.evaluate("document.body.innerText.match(/\\b(null|undefined|NaN)\\b/)?.[0] ?? ''");
      assert.equal(leaked, '', `the page shows "${leaked}"`);
      console.log(`ok - ${name}`);
    } catch (error) {
      failed = true;
      const screen = await page.evaluate("document.querySelector('main')?.innerText ?? ''").catch(() => '');
      const url = await page.evaluate('location.href').catch(() => '?');
      console.log(`not ok - ${name}\n  ${error.message}\n  at: ${url}\n  screen: ${screen.replace(/\s+/g, ' ').slice(0, 600)}`);
      break;
    }
  }
  if (page.errors.length > 0) {
    failed = true;
    console.log(`not ok - page errors:\n  ${page.errors.join('\n  ')}`);
  }
} finally {
  await page.close();
}
console.log(failed ? 'walkthrough failed' : `walkthrough passed (${options.version})`);
process.exitCode = failed ? 1 : 0;
