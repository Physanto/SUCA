/**
 * @file Sesiones reales de captura (integración I1): abre Chrome con la
 * extensión, inicia una sesión en modo libre por sitio, interactúa como una
 * persona y cierra la sesión. Escribe en la salida estándar un JSON con lo que
 * hizo, para que `tests/integration/test_i1_real_capture.py` revise la base.
 *
 * La sesión se inicia y se cierra desde el service worker real, con los mismos
 * pasos que el panel lateral (que no se puede abrir sin interfaz): crear la
 * sesión en el servidor, guardar el estado, avisar a la pestaña y, al final,
 * pedirle que entregue sus lotes, esperar a que la cola se vacíe y cerrar.
 *
 * Todo lo que se escribe en los campos lleva el prefijo `qzx`, que no aparece en
 * ningún sitio: si llega a la base, la captura guardó algo escrito.
 *
 * Requiere el servidor local escuchando en la dirección de la configuración.
 *
 * Uso:
 *   node tests/integration/browser/real-capture.mjs --site test_page --test-page-url http://127.0.0.1:8766/
 *   node tests/integration/browser/real-capture.mjs --site python_docs --site react
 */

import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';

import { launchWithExtension, sleep } from './chrome.mjs';

const EXTENSION_DIR = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..', 'extension');

/** Prefijo de todo lo que se escribe. */
export const SENTINEL = 'qzx';

/** Lo que se escribe en cada campo. */
const TYPED = {
  name: 'Qzxname',
  email: 'qzxmail@example.com',
  password: 'Qzxpass8841!',
  otherPassword: 'Qzxother8841',
  comment: 'Qzxcomment',
  search: 'qzxsearch',
};

/** Espera de la respuesta tras un clic (`capture.click_response_wait_ms`) más un margen. */
const CLICK_RESPONSE_MS = 1800;

/** Pasea el ratón por la ventana. */
async function wander(page) {
  await page.moveTo(640, 300);
  await page.moveTo(300, 600);
  await page.moveTo(900, 450);
}

/** Escribe una traza en la salida de errores, para saber dónde se detuvo una corrida. */
const log = (text) => process.stderr.write(`[real-capture] ${text}\n`);

/**
 * Selecciona el texto del primer elemento visible con texto, como lo haría el ratón,
 * y espera a que se registre.
 */
async function selectText(page, selector) {
  await page.evaluate(`(() => {
    const element = [...document.querySelectorAll(${JSON.stringify(selector)})].find(
      (node) => node.checkVisibility() && node.textContent.trim().length > 40,
    );
    if (!element) throw new Error('nothing to select');
    const range = document.createRange();
    range.selectNodeContents(element);
    getSelection().removeAllRanges();
    getSelection().addRange(range);
  })()`);
  // La captura registra la selección cuando lleva 300 ms sin cambiar.
  await sleep(600);
  await page.evaluate('getSelection().removeAllRanges()');
}

/**
 * Sitios y lo que se hace en cada uno. `url` es la página donde empieza la
 * sesión; `run` hace las interacciones.
 */
const SITES = {
  test_page: {
    url: (options) => options['test-page-url'],
    async run(page) {
      await wander(page);
      await page.click('#counter-button');
      await sleep(CLICK_RESPONSE_MS);
      await page.click('#counter-button', { count: 2 });
      await page.click('#fake-button', { button: 'right' });
      await page.click('#dead-button');
      await sleep(CLICK_RESPONSE_MS);
      await page.moveTo(640, 450);
      await page.wheel(500);
      await page.wheel(400);
      await selectText(page, 'aside p');

      // Formulario: primero un intento con errores, después uno válido.
      await page.click('#name');
      await page.type(TYPED.name);
      await page.press('Tab');
      await page.type(TYPED.email);
      await page.press('Tab');
      await page.type(TYPED.password);
      await page.press('Tab');
      await page.type(TYPED.otherPassword);
      await page.click('#comments');
      await page.type(TYPED.comment);
      await page.click('#signup-form button[type="submit"]');
      await sleep(500);
      await page.click('#password-confirm');
      await page.evaluate('document.getElementById("password-confirm").select()');
      await page.type(TYPED.password);
      await page.evaluate('document.getElementById("country").focus()');
      await page.type('C');
      await page.click('input[name="plan"][value="basic"]');
      await page.click('#terms');
      await page.click('#signup-form button[type="submit"]');
      await sleep(CLICK_RESPONSE_MS);

      // Búsqueda: la página filtra una lista, sin cambiar la dirección.
      await page.click('#search-input');
      await page.type(TYPED.search);
      await page.press('Enter');
      await sleep(500);

      // Aplicación de una sola página y navegación completa de ida y vuelta.
      await page.click('.app-nav a[data-view="products"]');
      await sleep(1000);
      await page.click('.app-nav a[data-view="cart"]');
      await sleep(1000);
      await page.click('#enlaces a[href="second-page.html"]');
      await page.waitForLoad();
      await wander(page);
      await page.back();
      await wander(page);
    },
  },

  python_docs: {
    url: () => 'https://docs.python.org/es/3/tutorial/index.html',
    async run(page) {
      await wander(page);
      await page.wheel(500);
      await selectText(page, 'section p');
      // Un enlace del índice: navegación completa.
      await page.click('section li a.reference.internal[href$=".html"]');
      await page.waitForLoad();
      await wander(page);
      await page.wheel(600);
      // Búsqueda: lo escrito viaja en `?q=`, que la captura debe redactar.
      await page.click('input[name="q"]');
      await page.type(`${TYPED.search}docs`);
      await page.press('Enter');
      await page.waitForLoad();
      await sleep(1500);
      await wander(page);
      await page.back();
      await wander(page);
    },
  },

  react: {
    url: () => 'https://react.dev/learn',
    async run(page) {
      await wander(page);
      await page.wheel(700);
      await selectText(page, 'article p');
      // Enlace del artículo: la página cambia sin recargar (aplicación de una sola página).
      await page.click('article a[href^="/learn/"]');
      await sleep(2000);
      await wander(page);
      await page.wheel(600);
      // Búsqueda en un diálogo, con sugerencias mientras se escribe.
      await page.click('button', { text: 'Search' });
      await sleep(800);
      await page.type(`${TYPED.search}react`);
      await sleep(1500);
      await page.press('Escape');
      await sleep(500);
      await page.back();
      await sleep(1500);
      await wander(page);
    },
  },
};

/**
 * Inicia una sesión en la pestaña con los mismos pasos que el panel lateral.
 *
 * @returns {Promise<{session_id: number, reply: object}>} Sesión creada y la respuesta de la pestaña.
 */
async function startSession(worker, page, { site, studyId }) {
  const url = await page.evaluate('location.href');
  return worker.evaluate(`(async () => {
    const { api, session, messages } = globalThis.UX;
    const tab = (await chrome.tabs.query({})).find((item) => item.url === ${JSON.stringify(url)});
    const studies = await api.listStudies();
    const studyId = ${JSON.stringify(studyId)} ?? studies[0].id;
    const created = await api.createSession({
      study_id: studyId,
      participant_id: ${JSON.stringify(`I1-${site}`.slice(0, 32))},
      version: 'V0',
      mode: 'free',
      screen_info: {
        window_width: tab.width,
        window_height: tab.height,
        screen_width: tab.width,
        screen_height: tab.height,
        device_pixel_ratio: 1,
        chrome_version: navigator.userAgent.match(/Chrome\\/([\\d.]+)/)[1],
      },
    });
    const state = { session_id: created.session_id, mode: 'free', study_id: studyId, tab_id: tab.id };
    await session.start(state);
    const reply = await messages.sendToTab(tab.id, messages.types.SESSION_STARTED, {
      session_id: state.session_id,
      mode: state.mode,
      study_id: state.study_id,
    });
    return { session_id: created.session_id, reply };
  })()`);
}

/**
 * Cierra la sesión como el worker al recibir `session.closed` del panel: la
 * pestaña entrega sus lotes, la cola se vacía y se cierra en el servidor.
 */
async function closeSession(worker, sessionId) {
  return worker.evaluate(`(async () => {
    const { api, session, messages } = globalThis.UX;
    const state = await session.reload();
    try {
      await messages.sendToTab(state.tab_id, messages.types.SESSION_CLOSED, { session_id: ${sessionId} });
    } catch (error) {
      console.warn('tab did not confirm the close: ' + error.message);
    }
    for (let waited = 0; ; waited += 200) {
      const { send_queue: queue } = await chrome.storage.local.get('send_queue');
      if (!queue || queue.length === 0) break;
      if (waited > 30000) throw new Error('send queue did not drain: ' + queue.length + ' jobs left');
      await new Promise((resolve) => setTimeout(resolve, 200));
    }
    await api.closeSession(${sessionId});
    await session.clear();
  })()`);
}

/** Mensajes de error o aviso, sin repetir. */
const problems = (messages) => [
  ...new Set(
    messages
      .filter((message) => ['error', 'warning', 'exception', 'assert'].includes(message.level))
      .map((message) => `${message.level}: ${message.text}`),
  ),
];

/** Corre un sitio y devuelve su resumen. */
async function runSite(browser, worker, name, options) {
  const site = SITES[name];
  const page = await browser.newPage();
  log(`${name}: opening ${site.url(options)}`);
  await page.goto(site.url(options));
  log(`${name}: starting the session`);
  const { session_id: sessionId, reply } = await startSession(worker, page, {
    site: name,
    studyId: options['study-id'] ? Number(options['study-id']) : null,
  });
  await sleep(500);
  let error = null;
  try {
    log(`${name}: interacting`);
    await site.run(page);
    // Una vuelta más del acumulador antes de cerrar.
    await sleep(2500);
  } catch (failure) {
    error = failure.stack;
  }
  log(`${name}: closing the session`);
  await closeSession(worker, sessionId);
  await page.target.send('Page.close').catch(() => {});
  return {
    site: name,
    session_id: sessionId,
    started: reply.started,
    failed: reply.failed,
    error,
    page_problems: problems(page.messages),
  };
}

/** Punto de entrada. */
async function main() {
  const { values: options } = parseArgs({
    options: {
      site: { type: 'string', multiple: true, default: ['test_page'] },
      'test-page-url': { type: 'string' },
      'study-id': { type: 'string' },
      headed: { type: 'boolean', default: false },
    },
  });
  const browser = await launchWithExtension(EXTENSION_DIR, { headless: !options.headed });
  const sessions = [];
  let worker = null;
  try {
    worker = await browser.worker();
    await sleep(500);
    await browser.closeExtensionTabs();
    for (const name of options.site) {
      if (!(name in SITES)) {
        throw new Error(`unknown site: ${name}`);
      }
      sessions.push(await runSite(browser, worker, name, options));
    }
  } finally {
    const workerProblems = worker === null ? [] : problems(worker.messages);
    process.stdout.write(`${JSON.stringify({ sentinel: SENTINEL, sessions, worker_problems: workerProblems })}\n`);
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error.stack);
  process.exit(1);
});
