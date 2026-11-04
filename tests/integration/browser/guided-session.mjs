/**
 * @file Sesión guiada real en la app de prueba (integración I2): abre Chrome con
 * la extensión, maneja el panel del evaluador y hace las tareas del estudio de
 * ejemplo en la tienda como una persona. Escribe en la salida estándar un JSON
 * con lo que hizo, para que `tests/integration/test_i2_guided_session.py`
 * revise la base.
 *
 * A diferencia de I1, la sesión se maneja con el **panel real**: `panel.html`,
 * con su vista y su controlador. Sin interfaz no se puede abrir el panel
 * lateral, así que el panel se abre como una pestaña más de la ventana y la
 * tienda se abre desde él, activa y en la misma ventana: el panel toma como
 * pestaña evaluada la activa de su ventana, igual que en el panel lateral. Los
 * botones del panel se pulsan desde su documento (el panel no se captura); en
 * la tienda, en cambio, todo es ratón y teclado reales.
 *
 * Recorrido (versión elegida, V1 por omisión):
 * - antes de la primera tarea, inicia sesión en la tienda (fuera de toda tarea);
 * - tareas 1 a 3 completas, cada una terminada con **Terminé**;
 * - entre la tarea 3 y la 4, fuera de toda tarea: listado ordenado y filtrado
 *   (`replaceState`), opiniones de un producto (`#resenas`), boletín y la página
 *   de términos (navegación completa) con regreso a la tienda;
 * - tarea 4: abre su cuenta y se rinde con **No pude**;
 * - contesta el SUS y cierra la sesión desde el panel.
 *
 * Lo que se escribe en el boletín lleva el prefijo `qzx`, que no aparece en la
 * tienda: si llega a la base, la captura guardó algo escrito.
 *
 * Requiere el servidor local escuchando en la dirección de la configuración y
 * la app de prueba servida en `--app-url`.
 *
 * Uso:
 *   node tests/integration/browser/guided-session.mjs --app-url http://127.0.0.1:8767 [--version V1] [--headed]
 */

import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';

import { DEMO_ACCOUNT, TEST_CARD } from '../../../test-app/public/js/data.js';
import { launchWithExtension, Page, sleep } from './chrome.mjs';

const EXTENSION_DIR = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..', 'extension');

/** Prefijo de todo lo que se escribe que la tienda no muestra. */
export const SENTINEL = 'qzx';

/** Participante de la sesión: un código, no un nombre. */
const PARTICIPANT = 'I2-auto';

/** Respuestas del SUS, de la pregunta 1 a la 10. */
const SUS_ANSWERS = [4, 2, 4, 1, 5, 2, 4, 2, 4, 3];

/** Espera de la respuesta tras un clic (`capture.click_response_wait_ms`) más un margen. */
const CLICK_RESPONSE_MS = 1800;

/** Pausa tras pulsar un botón del panel, para que la pestaña reciba el cambio de tarea. */
const TASK_SWITCH_MS = 700;

/** Escribe una traza en la salida de errores, para saber dónde se detuvo una corrida. */
const log = (text) => process.stderr.write(`[guided-session] ${text}\n`);

// ---------------------------------------------------------------------------
// Tienda: acciones de una persona, buscando los elementos por su texto visible
// o su etiqueta (la tienda no tiene nada especial para la herramienta).
// ---------------------------------------------------------------------------

/**
 * Centro del elemento visible de un selector cuyo texto, `aria-label` o
 * etiqueta coincide exactamente. Lo lleva a la vista.
 */
async function pointOf(page, selector, text) {
  const expression = `(() => {
    const wanted = ${JSON.stringify(text)};
    const clean = (value) => (value ?? '').replace(/\\s+/g, ' ').trim();
    const element = [...document.querySelectorAll(${JSON.stringify(selector)})].find((candidate) => {
      const box = candidate.getBoundingClientRect();
      const label = candidate.labels?.[0]?.innerText;
      return box.width > 0 && box.height > 0 &&
        [candidate.innerText, candidate.getAttribute('aria-label'), label].some((value) => clean(value) === wanted);
    });
    if (!element) return null;
    element.scrollIntoView({ block: 'center' });
    const box = element.getBoundingClientRect();
    return { x: box.left + box.width / 2, y: box.top + box.height / 2 };
  })()`;
  await page.waitFor(`${expression} !== null`);
  // El scroll de `scrollIntoView` también lo registra la captura; se le da tiempo.
  await sleep(150);
  return page.evaluate(expression);
}

/** Hace clic con el ratón en el elemento de un selector con ese texto exacto. */
async function clickText(page, selector, text) {
  const { x, y } = await pointOf(page, selector, text);
  await page.moveTo(x, y);
  await page.target.send('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button: 'left', clickCount: 1 });
  await page.target.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x, y, button: 'left', clickCount: 1 });
  await sleep(60);
}

/** Escribe en el campo de una etiqueta: clic, selecciona lo que tiene y lo reemplaza. */
async function fill(page, label, text) {
  await clickText(page, 'input, textarea', label);
  await page.evaluate('document.activeElement.select?.()');
  await page.type(text);
}

/** Elige una opción de una lista desplegable por su etiqueta (la lista nativa no se abre sin interfaz). */
async function choose(page, label, option) {
  await clickText(page, 'select', label);
  const done = await page.evaluate(`(() => {
    const select = document.activeElement;
    const found = [...select.options].find((item) => item.text === ${JSON.stringify(option)});
    if (!found) return false;
    select.value = found.value;
    select.dispatchEvent(new Event('input', { bubbles: true }));
    select.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  })()`);
  if (!done) throw new Error(`option "${option}" not found in "${label}"`);
}

/** Espera a que la ruta (con la consulta) cumpla una expresión regular. */
const waitForPath = (page, pattern) =>
  page.waitFor(`${pattern}.test(location.pathname + location.search)`, 15000);

/** Espera a que la página muestre un texto. */
const waitForText = (page, text) => page.waitFor(`document.body.innerText.includes(${JSON.stringify(text)})`, 15000);

/** Inicia sesión en la tienda con la cuenta de demostración. */
async function logIn(page) {
  await fill(page, 'Correo electrónico', DEMO_ACCOUNT.email);
  await fill(page, 'Contraseña', DEMO_ACCOUNT.password);
  await clickText(page, 'button', 'Ingresar');
  await waitForPath(page, /^\/$/);
}

/** Tareas del estudio de ejemplo, en orden. */
const TASKS = [
  {
    name: 'task 1: search the headphones and open the first result',
    async run(page) {
      await fill(page, 'Buscar productos', 'audifonos inalambricos');
      await page.press('Enter');
      await waitForPath(page, /^\/search\?q=audifonos/);
      await clickText(page, 'main a', 'Audífonos inalámbricos SoundMax');
      await waitForPath(page, /^\/product\/101$/);
    },
    end: 'done',
  },
  {
    name: 'task 2: add two units to the cart',
    async run(page) {
      await clickText(page, 'button', 'Aumentar cantidad');
      await clickText(page, 'button', 'Agregar al carrito');
      await waitForPath(page, /^\/cart$/);
      await waitForText(page, 'Audífonos inalámbricos SoundMax × 2');
    },
    end: 'done',
  },
  {
    name: 'task 3: buy paying by card',
    async run(page) {
      await clickText(page, 'a', 'Ir a pagar');
      await waitForPath(page, /^\/checkout\/shipping$/);
      await clickText(page, 'button', 'Continuar al pago');
      await waitForPath(page, /^\/checkout\/payment$/);
      await clickText(page, 'input', 'Tarjeta de crédito o débito');
      // El formato que aceptan las tres versiones (ver test-app/e2e/walkthrough.js).
      await fill(page, 'Número de la tarjeta', TEST_CARD.number.replace(/\s/g, ''));
      await fill(page, 'Nombre como aparece en la tarjeta', TEST_CARD.name);
      await fill(page, 'Vencimiento', TEST_CARD.expiry.replace('/', '/20'));
      await fill(page, 'Código de seguridad', TEST_CARD.cvc);
      const submit = await page.evaluate("document.querySelector('main button[type=submit]').innerText.trim()");
      await clickText(page, 'button', submit);
      await waitForPath(page, /^\/order\/\d+\/confirmation$/);
      await waitForText(page, 'Pedido confirmado');
    },
    end: 'done',
  },
  {
    name: 'task 4: open the account and give up',
    async run(page) {
      await clickText(page, 'button', 'Mi cuenta');
      await clickText(page, 'a', 'Ver mi cuenta');
      await waitForPath(page, /^\/account$/);
    },
    end: 'gave_up',
  },
];

/**
 * Lo que se hace entre la tarea 3 y la 4, sin tarea activa: lo que no debe
 * crear pantallas nuevas en el análisis (ordenar, filtrar, ancla) y lo que sí
 * (la página de términos, que es otra página, y el regreso a la tienda).
 */
async function browseBetweenTasks(page) {
  await clickText(page, 'a', 'Inicio');
  await waitForPath(page, /^\/$/);
  await clickText(page, 'a', 'Ver todos los productos');
  await waitForPath(page, /^\/products$/);
  await choose(page, 'Ordenar por', 'Menor precio');
  await waitForPath(page, /^\/products\?sort=price_asc$/);
  await clickText(page, 'input', 'Solo con descuento');
  await waitForPath(page, /^\/products\?sort=price_asc&discount=1$/);
  await sleep(CLICK_RESPONSE_MS);

  await fill(page, 'Buscar productos', 'parlante');
  await page.press('Enter');
  await waitForPath(page, /^\/search\?q=parlante$/);
  await clickText(page, 'main a', 'Parlante portátil Ritmo Mini');
  await waitForPath(page, /^\/product\/104$/);
  await clickText(page, 'a', 'Ver opiniones');
  await page.waitFor("location.hash === '#resenas'");
  await sleep(CLICK_RESPONSE_MS);

  await fill(page, 'Correo electrónico', `${SENTINEL}news@example.com`);
  await clickText(page, 'button', 'Suscribirme');
  await waitForText(page, 'Te suscribiste al boletín');
  await clickText(page, 'a', 'Términos y condiciones');
  await page.waitForLoad();
  await page.waitFor("location.pathname === '/terms.html'");
  await page.wheel(400);
  await clickText(page, 'main a', 'Volver a la tienda');
  await page.waitForLoad();
  await waitForPath(page, /^\/$/);
}

// ---------------------------------------------------------------------------
// Panel del evaluador: se maneja desde su propio documento.
// ---------------------------------------------------------------------------

/** Pulsa un botón del panel por su id. */
async function press(panel, id) {
  await panel.waitFor(`(() => {
    const button = document.getElementById(${JSON.stringify(id)});
    return button.checkVisibility() && !button.disabled;
  })()`);
  await panel.evaluate(`document.getElementById(${JSON.stringify(id)}).click()`);
}

/** Texto visible de un elemento del panel. */
const panelText = (panel, id) => panel.evaluate(`document.getElementById(${JSON.stringify(id)}).innerText`);

/** Llena el formulario de inicio y empieza una sesión guiada con el primer estudio. */
async function startGuidedSession(panel, version) {
  await panel.waitFor("document.getElementById('study').options.length > 0");
  await panel.evaluate(`(() => {
    const set = (id, value) => {
      const field = document.getElementById(id);
      field.value = value;
      field.dispatchEvent(new Event('input', { bubbles: true }));
      field.dispatchEvent(new Event('change', { bubbles: true }));
    };
    set('participant', ${JSON.stringify(PARTICIPANT)});
    set('version', ${JSON.stringify(version)});
    set('mode', 'guided');
    document.getElementById('start-form').requestSubmit();
  })()`);
  await panel.waitFor("!document.getElementById('active-section').hidden", 20000);
  await panel.waitFor("document.getElementById('task-start').checkVisibility()", 20000);
}

/** Hace una tarea: **Empezar**, la tarea en la tienda y **Terminé** o **No pude**. */
async function doTask(panel, page, task) {
  await press(panel, 'task-start');
  await panel.waitFor("document.getElementById('task-done').checkVisibility()");
  await sleep(TASK_SWITCH_MS);
  await task.run(page);
  await sleep(CLICK_RESPONSE_MS);
  await press(panel, task.end === 'done' ? 'task-done' : 'task-gave-up');
  // Pasa a la siguiente tarea, o a "todas terminadas".
  await panel.waitFor(
    "document.getElementById('task-start').checkVisibility() || !document.getElementById('sus-section').hidden",
  );
  await sleep(TASK_SWITCH_MS);
}

/** Contesta el SUS y espera a que el servidor lo guarde. */
async function answerSus(panel) {
  await panel.waitFor("!document.getElementById('sus-section').hidden");
  await panel.evaluate(`(() => {
    const answers = ${JSON.stringify(SUS_ANSWERS)};
    answers.forEach((value, index) => {
      document.querySelector('input[name="sus-' + (index + 1) + '"][value="' + value + '"]').click();
    });
  })()`);
  await press(panel, 'sus-send');
  await panel.waitFor("!document.getElementById('sus-saved').hidden");
}

/** Cierra la sesión desde el panel y espera a que el worker entregue todo al servidor. */
async function closeSession(panel, worker) {
  await press(panel, 'close');
  await panel.waitFor("!document.getElementById('start-section').hidden", 30000);
  await worker.evaluate(`(async () => {
    for (let waited = 0; ; waited += 200) {
      const { send_queue: queue } = await chrome.storage.local.get('send_queue');
      if (!queue || queue.length === 0) return;
      if (waited > 30000) throw new Error('send queue did not drain: ' + queue.length + ' jobs left');
      await new Promise((resolve) => setTimeout(resolve, 200));
    }
  })()`);
}

// ---------------------------------------------------------------------------
// Pestañas: el panel y la tienda en la misma ventana.
// ---------------------------------------------------------------------------

/**
 * Abre la tienda desde el panel, activa y en su misma ventana, y se conecta a ella.
 *
 * @param {string} appUrl - Dirección de la tienda, sin barra final.
 * @param {string} path - Ruta con la que se abre.
 * @returns {Promise<{page: Page, tabId: number}>} Pestaña de la tienda.
 */
async function openStore(browser, panel, appUrl, path) {
  const tabId = await panel.evaluate(
    `chrome.tabs.create({ url: ${JSON.stringify(appUrl + path)}, active: true }).then((tab) => tab.id)`,
  );
  let found = null;
  for (let attempt = 0; attempt < 100 && found === null; attempt += 1) {
    const { targetInfos } = await browser.send('Target.getTargets');
    found = targetInfos.find((info) => info.type === 'page' && info.url.startsWith(`${appUrl}/`)) ?? null;
    if (found === null) await sleep(100);
  }
  if (found === null) throw new Error('the store tab did not open');
  const page = new Page(await browser.attach(found.targetId));
  await page.init(browser.viewport);
  await page.waitForLoad();
  return { page, tabId };
}

/**
 * Cierra las pestañas de la extensión que no son el panel (la del permiso de
 * cámara, que el worker abre si la cámara no tiene permiso) y vuelve a activar
 * la tienda.
 */
async function keepStoreActive(browser, panel, tabId) {
  const { targetInfos } = await browser.send('Target.getTargets');
  for (const info of targetInfos) {
    if (
      info.type === 'page' &&
      info.url.startsWith(`chrome-extension://${browser.extensionId}/`) &&
      !info.url.includes('/panel/panel.html')
    ) {
      await browser.send('Target.closeTarget', { targetId: info.targetId });
    }
  }
  await panel.evaluate(`chrome.tabs.update(${tabId}, { active: true }).then(() => true)`);
}

/** Mensajes de error o aviso, sin repetir. */
const problems = (messages) => [
  ...new Set(
    messages
      .filter((message) => ['error', 'warning', 'exception', 'assert'].includes(message.level))
      .map((message) => `${message.level}: ${message.text}`),
  ),
];

/** Punto de entrada. */
async function main() {
  const { values: options } = parseArgs({
    options: {
      'app-url': { type: 'string' },
      version: { type: 'string', default: 'V1' },
      headed: { type: 'boolean', default: false },
    },
  });
  if (!options['app-url']) {
    throw new Error('--app-url is required');
  }
  const appUrl = options['app-url'].replace(/\/$/, '');
  const browser = await launchWithExtension(EXTENSION_DIR, { headless: !options.headed });
  const summary = {
    sentinel: SENTINEL,
    participant_id: PARTICIPANT,
    version: options.version,
    sus_answers: SUS_ANSWERS,
    tasks: TASKS.map((task) => task.end),
    session_label: null,
    capture_status: null,
    error: null,
    page_problems: [],
    panel_problems: [],
    worker_problems: [],
  };
  let worker = null;
  let panel = null;
  let page = null;
  try {
    worker = await browser.worker();
    await sleep(500);
    await browser.closeExtensionTabs();

    log('opening the panel');
    panel = await browser.newPage();
    await panel.goto(`chrome-extension://${browser.extensionId}/panel/panel.html`);

    log(`opening the store (${options.version})`);
    const store = await openStore(browser, panel, appUrl, `/login?version=${options.version}`);
    page = store.page;
    await page.waitFor("location.pathname === '/login'");

    log('starting the guided session');
    await startGuidedSession(panel, options.version);
    await sleep(1500);
    await keepStoreActive(browser, panel, store.tabId);
    summary.session_label = await panelText(panel, 'active-session');
    summary.capture_status = await panelText(panel, 'active-capture');

    log('logging in, before the first task');
    await logIn(page);
    await sleep(CLICK_RESPONSE_MS);

    for (const [index, task] of TASKS.entries()) {
      if (index === 3) {
        log('browsing between tasks 3 and 4');
        await browseBetweenTasks(page);
        await sleep(CLICK_RESPONSE_MS);
      }
      log(task.name);
      await doTask(panel, page, task);
    }

    log('answering the SUS');
    await answerSus(panel);
    log('closing the session');
    await closeSession(panel, worker);
  } catch (failure) {
    summary.error = failure.stack;
  } finally {
    summary.page_problems = page === null ? [] : problems(page.messages);
    summary.panel_problems = panel === null ? [] : problems(panel.messages);
    summary.worker_problems = worker === null ? [] : problems(worker.messages);
    process.stdout.write(`${JSON.stringify(summary)}\n`);
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error.stack);
  process.exit(1);
});
