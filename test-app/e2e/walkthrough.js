/**
 * @file Recorrido automático de la tienda en Chrome sin interfaz: inicio de
 * sesión y las 4 tareas del estudio de ejemplo, como las haría una persona.
 *
 * Comprueba que cada tarea llega a su estado final, que recargar una ruta
 * funciona y que la página no tiene errores de JavaScript. La ventana mide
 * 920 × 800, el espacio que queda con el panel lateral de Chrome abierto.
 *
 * Requiere la app servida (`python -m scripts.serve_test_app`) y Chrome
 * instalado (o la variable `CHROME_PATH`).
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
      await page.fill('Número de la tarjeta', TEST_CARD.number);
      await page.fill('Nombre como aparece en la tarjeta', TEST_CARD.name);
      await page.fill('Vencimiento', TEST_CARD.expiry);
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
];

const page = await launch({ width: 920, height: 800 });
let failed = false;
try {
  for (const [name, step] of STEPS) {
    try {
      await step(page);
      console.log(`ok - ${name}`);
    } catch (error) {
      failed = true;
      const screen = await page.evaluate("document.querySelector('main')?.innerText ?? ''").catch(() => '');
      console.log(`not ok - ${name}\n  ${error.message}\n  screen: ${screen.replace(/\s+/g, ' ').slice(0, 600)}`);
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
