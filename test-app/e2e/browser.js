/**
 * @file Control mínimo de Chrome sin interfaz por el protocolo de DevTools,
 * sin dependencias: usa el `WebSocket` y el `fetch` nativos de Node 22.
 *
 * Las acciones imitan a una persona: los clics son eventos reales del ratón
 * en el centro del elemento (si algo lo tapa, el clic cae en lo que lo tapa) y
 * el texto se escribe con el teclado. Los elementos se buscan por su texto
 * visible o su etiqueta, nunca por atributos especiales.
 */

import { spawn } from 'node:child_process';
import { existsSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

/** Ubicaciones habituales de Chrome en Linux, macOS y Windows. */
const CHROME_CANDIDATES = [
  '/usr/bin/google-chrome-stable',
  '/usr/bin/google-chrome',
  '/usr/bin/chromium',
  '/usr/bin/chromium-browser',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
];

/**
 * Encuentra el ejecutable de Chrome.
 *
 * @returns {string} Ruta del ejecutable (variable `CHROME_PATH` o una ubicación habitual).
 * @throws {Error} Si no encuentra Chrome.
 */
function findChrome() {
  const path = process.env.CHROME_PATH ?? CHROME_CANDIDATES.find((candidate) => existsSync(candidate));
  if (!path) throw new Error('Chrome not found; set CHROME_PATH');
  return path;
}

/**
 * Abre Chrome sin interfaz con una pestaña y devuelve una página controlable.
 *
 * @param {{ width: number, height: number }} viewport - Tamaño de la ventana.
 * @returns {Promise<Page>} Página lista.
 */
export async function launch(viewport) {
  const profile = mkdtempSync(join(tmpdir(), 'test-app-chrome-'));
  const chrome = spawn(
    findChrome(),
    [
      '--headless=new',
      '--remote-debugging-port=0',
      `--user-data-dir=${profile}`,
      `--window-size=${viewport.width},${viewport.height}`,
      '--no-first-run',
      '--no-default-browser-check',
      'about:blank',
    ],
    { stdio: ['ignore', 'ignore', 'pipe'] },
  );
  const browserUrl = await new Promise((resolve, reject) => {
    let output = '';
    chrome.stderr.on('data', (chunk) => {
      output += chunk;
      const found = /DevTools listening on (ws:\/\/\S+)/.exec(output);
      if (found) resolve(found[1]);
    });
    chrome.on('exit', (code) => reject(new Error(`Chrome exited with code ${code}: ${output}`)));
  });
  const { port } = new URL(browserUrl);
  const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  const target = targets.find((item) => item.type === 'page');
  const exited = new Promise((resolve) => chrome.once('exit', resolve));
  const page = new Page(await connect(target.webSocketDebuggerUrl), async () => {
    chrome.kill();
    await exited;
    rmSync(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
  });
  await page.init(viewport);
  return page;
}

/**
 * Abre la conexión con una pestaña.
 *
 * @param {string} url - Dirección `ws://` de la pestaña.
 * @returns {Promise<WebSocket>} Conexión abierta.
 */
function connect(url) {
  return new Promise((resolve, reject) => {
    const socket = new WebSocket(url);
    socket.addEventListener('open', () => resolve(socket));
    socket.addEventListener('error', () => reject(new Error(`cannot connect to ${url}`)));
  });
}

/** Pestaña de Chrome con acciones de alto nivel. */
export class Page {
  /**
   * @param {WebSocket} socket - Conexión con la pestaña.
   * @param {() => Promise<void>} onClose - Cierra Chrome y borra su perfil.
   */
  constructor(socket, onClose) {
    this.socket = socket;
    this.onClose = onClose;
    this.nextId = 1;
    this.pending = new Map();
    /** Errores de JavaScript y mensajes `console.error` de la página. */
    this.errors = [];
    socket.addEventListener('message', (event) => this.receive(JSON.parse(event.data)));
  }

  /** Atiende respuestas y eventos del protocolo. */
  receive(message) {
    if (message.id && this.pending.has(message.id)) {
      const { resolve, reject } = this.pending.get(message.id);
      this.pending.delete(message.id);
      if (message.error) reject(new Error(message.error.message));
      else resolve(message.result);
    } else if (message.method === 'Runtime.exceptionThrown') {
      this.errors.push(message.params.exceptionDetails.exception?.description ?? 'exception');
    } else if (message.method === 'Runtime.consoleAPICalled' && message.params.type === 'error') {
      this.errors.push(message.params.args.map((arg) => arg.value ?? arg.description).join(' '));
    }
  }

  /**
   * Envía un comando del protocolo.
   *
   * @param {string} method - Comando, por ejemplo `Page.navigate`.
   * @param {object} [params] - Parámetros.
   * @returns {Promise<object>} Resultado.
   */
  send(method, params = {}) {
    const id = this.nextId;
    this.nextId += 1;
    this.socket.send(JSON.stringify({ id, method, params }));
    return new Promise((resolve, reject) => this.pending.set(id, { resolve, reject }));
  }

  /** Activa los dominios necesarios y fija el tamaño de la ventana. */
  async init({ width, height }) {
    await this.send('Runtime.enable');
    await this.send('Page.enable');
    await this.send('Emulation.setDeviceMetricsOverride', {
      width,
      height,
      deviceScaleFactor: 1,
      mobile: false,
    });
  }

  /**
   * Evalúa una expresión en la página y devuelve su valor.
   *
   * @param {string} expression - JavaScript; puede devolver una promesa.
   * @returns {Promise<unknown>} Valor de la expresión.
   */
  async evaluate(expression) {
    const { result, exceptionDetails } = await this.send('Runtime.evaluate', {
      expression,
      awaitPromise: true,
      returnByValue: true,
    });
    if (exceptionDetails) throw new Error(exceptionDetails.exception?.description ?? expression);
    return result.value;
  }

  /**
   * Espera a que una expresión sea verdadera.
   *
   * @param {string} expression - JavaScript que devuelve un valor verdadero al cumplirse.
   * @param {string} what - Descripción, para el error.
   * @param {number} [timeout] - Espera máxima en milisegundos.
   * @returns {Promise<unknown>} Valor de la expresión.
   */
  async waitFor(expression, what, timeout = 8000) {
    const end = Date.now() + timeout;
    while (Date.now() < end) {
      const value = await this.evaluate(expression).catch(() => null);
      if (value) return value;
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
    throw new Error(`timed out waiting for ${what}`);
  }

  /**
   * Abre una dirección y espera a que la página cargue.
   *
   * @param {string} url - Dirección.
   */
  async goto(url) {
    await this.send('Page.navigate', { url });
    // Se espera la página nueva: la anterior también cumple la condición mientras no se reemplace.
    const path = new URL(url).pathname;
    await this.waitFor(
      `location.pathname === ${JSON.stringify(path)} && document.readyState !== 'loading' && !!document.querySelector('main h1') && !document.querySelector('main[aria-busy]')`,
      `page ${url}`,
    );
  }

  /** Recarga la página y espera a que cargue. */
  async reload() {
    await this.send('Page.reload');
    await new Promise((resolve) => setTimeout(resolve, 200));
    await this.waitFor("document.readyState === 'complete' && !!document.querySelector('main h1')", 'reload');
  }

  /**
   * Espera a que la ruta de la URL coincida con una expresión regular.
   *
   * @param {RegExp} pattern - Patrón de `location.pathname + location.search`.
   * @returns {Promise<string>} La ruta.
   */
  waitForPath(pattern) {
    return this.waitFor(
      `(() => { const p = location.pathname + location.search; return ${pattern}.test(p) && !document.querySelector('main[aria-busy]') ? p : null; })()`,
      `path ${pattern}`,
    );
  }

  /**
   * Espera a que un texto aparezca en la página.
   *
   * @param {string} text - Texto visible.
   */
  waitForText(text) {
    return this.waitFor(`document.body.innerText.includes(${JSON.stringify(text)})`, `text "${text}"`);
  }

  /**
   * Hace clic con el ratón en el elemento visible cuyo texto (o etiqueta
   * accesible) coincide, dentro de un selector CSS.
   *
   * @param {string} selector - Selector CSS de los candidatos (`button`, `a`…).
   * @param {string} text - Texto visible o `aria-label` exacto.
   */
  async click(selector, text) {
    const point = await this.waitFor(
      `(() => {
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
      })()`,
      `${selector} "${text}"`,
    );
    for (const type of ['mouseMoved', 'mousePressed', 'mouseReleased']) {
      await this.send('Input.dispatchMouseEvent', { type, x: point.x, y: point.y, button: 'left', clickCount: 1 });
    }
  }

  /**
   * Escribe en el campo de una etiqueta: hace clic en él, borra lo que tiene
   * y escribe el texto.
   *
   * @param {string} label - Texto de la etiqueta del campo.
   * @param {string} text - Texto a escribir.
   */
  async fill(label, text) {
    await this.click('input, textarea', label);
    await this.evaluate('document.activeElement.select?.()');
    await this.send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Backspace', code: 'Backspace', windowsVirtualKeyCode: 8 });
    await this.send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Backspace', code: 'Backspace', windowsVirtualKeyCode: 8 });
    await this.send('Input.insertText', { text });
  }

  /**
   * Elige una opción de una lista desplegable por su etiqueta.
   *
   * @param {string} label - Texto de la etiqueta de la lista.
   * @param {string} option - Texto de la opción.
   */
  async select(label, option) {
    await this.click('select', label);
    const done = await this.evaluate(`(() => {
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

  /**
   * Pulsa una tecla.
   *
   * @param {'Enter'|'Escape'} key - Tecla.
   */
  async press(key) {
    const codes = { Enter: 13, Escape: 27 };
    const extra = key === 'Enter' ? { text: '\r' } : {};
    await this.send('Input.dispatchKeyEvent', { type: 'keyDown', key, code: key, windowsVirtualKeyCode: codes[key], ...extra });
    await this.send('Input.dispatchKeyEvent', { type: 'keyUp', key, code: key, windowsVirtualKeyCode: codes[key] });
  }

  /** Vuelve a la página anterior del historial. */
  async back() {
    await this.evaluate('history.back()');
  }

  /**
   * Cierra Chrome y espera a que termine.
   *
   * @returns {Promise<void>} Se resuelve con Chrome cerrado y su perfil borrado.
   */
  close() {
    this.socket.close();
    return this.onClose();
  }
}
