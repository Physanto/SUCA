/**
 * @file Control mínimo de Chrome con la extensión cargada, por el protocolo de
 * DevTools sobre una tubería, sin dependencias.
 *
 * Chrome con marca ya no acepta `--load-extension`: una extensión sin empaquetar
 * solo se carga por el protocolo (`Extensions.loadUnpacked`), y eso exige la
 * tubería (`--remote-debugging-pipe`) y `--enable-unsafe-extension-debugging`.
 * Por la tubería viajan mensajes JSON terminados en un byte nulo: Chrome lee
 * del descriptor 3 y escribe en el 4.
 *
 * Las acciones imitan a una persona: eventos reales del ratón y del teclado en
 * coordenadas de la pantalla, no llamadas a `click()` desde la página.
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
];

/** Tiempo máximo de un comando del protocolo, en ms. */
const COMMAND_TIMEOUT_MS = 30000;

/** Teclas especiales que usan las pruebas, con lo que Chrome necesita para cada una. */
const KEYS = {
  Tab: { code: 'Tab', windowsVirtualKeyCode: 9 },
  Enter: { code: 'Enter', windowsVirtualKeyCode: 13, text: '\r' },
  Escape: { code: 'Escape', windowsVirtualKeyCode: 27 },
};

/** Espera un tiempo dado. */
export const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Encuentra el ejecutable de Chrome.
 *
 * @returns {string} Ruta del ejecutable (variable `CHROME_PATH` o una ubicación habitual).
 * @throws {Error} Si no encuentra Chrome.
 */
export function findChrome() {
  const path = process.env.CHROME_PATH ?? CHROME_CANDIDATES.find((candidate) => existsSync(candidate));
  if (!path) {
    throw new Error('Chrome not found; set CHROME_PATH');
  }
  return path;
}

/**
 * Abre Chrome con un perfil nuevo y carga la extensión.
 *
 * @param {string} extensionDir - Carpeta de la extensión (la del manifiesto).
 * @param {{width?: number, height?: number, headless?: boolean}} [options] - Ventana.
 * @returns {Promise<Browser>} Navegador con `extensionId` ya definido.
 */
export async function launchWithExtension(extensionDir, { width = 1280, height = 900, headless = true } = {}) {
  const profile = mkdtempSync(join(tmpdir(), 'suca-chrome-'));
  const args = [
    headless ? '--headless=new' : null,
    '--remote-debugging-pipe',
    '--enable-unsafe-extension-debugging',
    `--user-data-dir=${profile}`,
    `--window-size=${width},${height}`,
    '--no-first-run',
    '--no-default-browser-check',
    'about:blank',
  ].filter(Boolean);
  const chrome = spawn(findChrome(), args, { stdio: ['ignore', 'ignore', 'ignore', 'pipe', 'pipe'] });
  const browser = new Browser(chrome, profile, { width, height });
  try {
    const { id } = await browser.send('Extensions.loadUnpacked', { path: extensionDir });
    browser.extensionId = id;
  } catch (error) {
    await browser.close();
    throw error;
  }
  return browser;
}

/** Navegador conectado por la tubería. */
export class Browser {
  /**
   * @param {import('node:child_process').ChildProcess} chrome - Proceso de Chrome.
   * @param {string} profile - Carpeta del perfil temporal.
   * @param {{width: number, height: number}} viewport - Tamaño de las páginas.
   */
  constructor(chrome, profile, viewport) {
    this.chrome = chrome;
    this.profile = profile;
    this.viewport = viewport;
    this.extensionId = null;
    this.nextId = 1;
    this.pending = new Map();
    /** Oyentes de eventos del protocolo, por sesión y método. */
    this.listeners = new Map();
    this.buffer = '';
    this.exited = new Promise((resolve) => chrome.once('exit', resolve));
    chrome.once('exit', (code) => {
      for (const { reject } of this.pending.values()) {
        reject(new Error(`Chrome exited with code ${code}`));
      }
      this.pending.clear();
    });
    chrome.stdio[4].setEncoding('utf8');
    chrome.stdio[4].on('data', (chunk) => this.read(chunk));
  }

  /** Separa los mensajes que llegan por la tubería y los atiende. */
  read(chunk) {
    this.buffer += chunk;
    let end;
    while ((end = this.buffer.indexOf('\0')) >= 0) {
      const message = JSON.parse(this.buffer.slice(0, end));
      this.buffer = this.buffer.slice(end + 1);
      if (message.id && this.pending.has(message.id)) {
        const { resolve, reject, timer } = this.pending.get(message.id);
        clearTimeout(timer);
        this.pending.delete(message.id);
        if (message.error) {
          reject(new Error(`${message.error.message} (${message.error.data ?? ''})`));
        } else {
          resolve(message.result);
        }
      } else if (message.method) {
        const key = `${message.sessionId ?? ''}|${message.method}`;
        for (const listener of this.listeners.get(key) ?? []) {
          listener(message.params);
        }
      }
    }
  }

  /**
   * Envía un comando del protocolo.
   *
   * @param {string} method - Comando, por ejemplo `Target.getTargets`.
   * @param {object} [params] - Parámetros.
   * @param {string} [sessionId] - Sesión de un destino (pestaña o worker), si aplica.
   * @returns {Promise<object>} Resultado del comando.
   */
  send(method, params = {}, sessionId = undefined) {
    const id = this.nextId;
    this.nextId += 1;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`${method} timed out`));
      }, COMMAND_TIMEOUT_MS);
      this.pending.set(id, { resolve, reject, timer });
      this.chrome.stdio[3].write(`${JSON.stringify({ id, method, params, sessionId })}\0`);
    });
  }

  /**
   * Escucha un evento del protocolo.
   *
   * @param {string|undefined} sessionId - Sesión del destino; `undefined` para el navegador.
   * @param {string} method - Evento, por ejemplo `Runtime.exceptionThrown`.
   * @param {function(object): void} listener - Recibe los parámetros del evento.
   * @returns {void}
   */
  on(sessionId, method, listener) {
    const key = `${sessionId ?? ''}|${method}`;
    this.listeners.set(key, [...(this.listeners.get(key) ?? []), listener]);
  }

  /**
   * Se conecta al service worker de la extensión. Espera a que Chrome lo arranque.
   *
   * @returns {Promise<Target>} Worker con la consola registrada en `messages`.
   */
  async worker() {
    const url = `chrome-extension://${this.extensionId}/worker.js`;
    for (let attempt = 0; attempt < 100; attempt += 1) {
      const { targetInfos } = await this.send('Target.getTargets');
      const found = targetInfos.find((info) => info.type === 'service_worker' && info.url === url);
      if (found) {
        const target = await this.attach(found.targetId);
        await target.send('Runtime.enable');
        return target;
      }
      await sleep(100);
    }
    throw new Error('the extension service worker did not start');
  }

  /**
   * Abre una pestaña nueva, vacía.
   *
   * @returns {Promise<Page>} Pestaña lista para navegar.
   */
  async newPage() {
    const { targetId } = await this.send('Target.createTarget', { url: 'about:blank' });
    const target = await this.attach(targetId);
    const page = new Page(target);
    await page.init(this.viewport);
    return page;
  }

  /** Cierra las pestañas que abrió la extensión (por ejemplo, la del permiso de cámara). */
  async closeExtensionTabs() {
    const { targetInfos } = await this.send('Target.getTargets');
    for (const info of targetInfos) {
      if (info.type === 'page' && info.url.startsWith(`chrome-extension://${this.extensionId}/`)) {
        await this.send('Target.closeTarget', { targetId: info.targetId });
      }
    }
  }

  /** Se conecta a un destino y devuelve su sesión. */
  async attach(targetId) {
    const { sessionId } = await this.send('Target.attachToTarget', { targetId, flatten: true });
    return new Target(this, sessionId, targetId);
  }

  /** Cierra Chrome y borra el perfil temporal. */
  async close() {
    this.chrome.kill();
    await this.exited;
    rmSync(this.profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
  }
}

/** Sesión del protocolo con un destino: una pestaña o el service worker. */
export class Target {
  /**
   * @param {Browser} browser - Navegador.
   * @param {string} sessionId - Sesión del protocolo.
   * @param {string} targetId - Destino.
   */
  constructor(browser, sessionId, targetId) {
    this.browser = browser;
    this.sessionId = sessionId;
    this.targetId = targetId;
    /** Mensajes de consola y excepciones: `{ level, text }`. */
    this.messages = [];
    browser.on(sessionId, 'Runtime.consoleAPICalled', ({ type, args }) => {
      this.messages.push({ level: type, text: args.map((arg) => arg.value ?? arg.description).join(' ') });
    });
    browser.on(sessionId, 'Runtime.exceptionThrown', ({ exceptionDetails }) => {
      this.messages.push({
        level: 'exception',
        text: exceptionDetails.exception?.description ?? exceptionDetails.text,
      });
    });
  }

  /** Envía un comando a este destino. */
  send(method, params = {}) {
    return this.browser.send(method, params, this.sessionId);
  }

  /**
   * Evalúa una expresión y devuelve su valor; espera las promesas.
   *
   * @param {string} expression - Código JavaScript.
   * @returns {Promise<any>} Valor serializado como JSON.
   * @throws {Error} Si la expresión lanza un error.
   */
  async evaluate(expression) {
    const { result, exceptionDetails } = await this.send('Runtime.evaluate', {
      expression,
      awaitPromise: true,
      returnByValue: true,
    });
    if (exceptionDetails) {
      throw new Error(exceptionDetails.exception?.description ?? exceptionDetails.text);
    }
    return result.value;
  }
}

/** Pestaña con acciones de alto nivel. */
export class Page {
  /** @param {Target} target - Sesión de la pestaña. */
  constructor(target) {
    this.target = target;
    this.mouse = { x: 10, y: 10 };
  }

  /** Mensajes de consola y excepciones de la página y de los content scripts. */
  get messages() {
    return this.target.messages;
  }

  /** Activa los dominios y fija el tamaño y el foco de la ventana. */
  async init({ width, height }) {
    await this.target.send('Page.enable');
    await this.target.send('Runtime.enable');
    await this.target.send('Emulation.setDeviceMetricsOverride', {
      width,
      height,
      deviceScaleFactor: 1,
      mobile: false,
    });
    // Sin interfaz la ventana no tiene foco y los campos no reciben `focus` ni `blur`.
    await this.target.send('Emulation.setFocusEmulationEnabled', { enabled: true });
  }

  /** Evalúa una expresión en la página (el mundo de la página, no el de la extensión). */
  evaluate(expression) {
    return this.target.evaluate(expression);
  }

  /**
   * Espera hasta que una expresión de la página sea verdadera.
   *
   * @param {string} expression - Condición en JavaScript.
   * @param {number} [timeoutMs] - Tiempo máximo.
   * @returns {Promise<void>}
   * @throws {Error} Si no se cumple a tiempo.
   */
  async waitFor(expression, timeoutMs = 15000) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      try {
        if (await this.evaluate(expression)) {
          return;
        }
      } catch {
        // La página puede estar cambiando: se vuelve a intentar.
      }
      await sleep(100);
    }
    throw new Error(`timed out waiting for: ${expression}`);
  }

  /**
   * Abre una dirección y espera a que la página termine de cargar.
   *
   * @param {string} url - Dirección.
   * @returns {Promise<void>}
   */
  async goto(url) {
    await this.target.send('Page.navigate', { url });
    await this.waitForLoad();
  }

  /** Espera a que la página termine de cargar y a que corran los content scripts. */
  async waitForLoad() {
    await sleep(300);
    await this.waitFor('document.readyState === "complete"', 30000);
    // Los content scripts corren con `document_idle` y la sesión arranca al preguntar la pestaña.
    await sleep(1000);
  }

  /**
   * Lleva un elemento a la vista y devuelve su centro.
   *
   * @param {string} selector - Selector CSS.
   * @param {string} [text] - Si se da, el elemento debe contener ese texto visible.
   * @returns {Promise<{x: number, y: number}>} Centro en coordenadas de la ventana.
   * @throws {Error} Si no hay un elemento visible con ese selector (y ese texto).
   */
  async center(selector, text = null) {
    const point = await this.evaluate(`(() => {
      const text = ${JSON.stringify(text)};
      const element = [...document.querySelectorAll(${JSON.stringify(selector)})].find(
        (node) => node.checkVisibility && node.checkVisibility() && (text === null || node.innerText.includes(text)),
      );
      if (!element) return null;
      element.scrollIntoView({ block: 'center', inline: 'center' });
      const box = element.getBoundingClientRect();
      return { x: box.x + box.width / 2, y: box.y + box.height / 2 };
    })()`);
    if (point === null) {
      throw new Error(`no visible element for ${selector}${text === null ? '' : ` with "${text}"`}`);
    }
    // El scroll de `scrollIntoView` también lo registra la captura; se le da tiempo.
    await sleep(150);
    return point;
  }

  /**
   * Mueve el ratón en línea recta, en varios pasos.
   *
   * @param {number} x - Destino horizontal.
   * @param {number} y - Destino vertical.
   * @param {number} [steps] - Pasos intermedios.
   * @returns {Promise<void>}
   */
  async moveTo(x, y, steps = 8) {
    const from = { ...this.mouse };
    for (let step = 1; step <= steps; step += 1) {
      const point = { x: from.x + ((x - from.x) * step) / steps, y: from.y + ((y - from.y) * step) / steps };
      await this.target.send('Input.dispatchMouseEvent', { type: 'mouseMoved', ...point });
      await sleep(16);
    }
    this.mouse = { x, y };
  }

  /**
   * Hace clic en el centro de un elemento.
   *
   * @param {string} selector - Selector CSS.
   * @param {{button?: string, count?: number, text?: string}} [options] - Botón, cantidad de
   *   clics y, si se da, el texto visible que debe tener el elemento.
   * @returns {Promise<void>}
   */
  async click(selector, { button = 'left', count = 1, text = null } = {}) {
    const { x, y } = await this.center(selector, text);
    await this.moveTo(x, y);
    for (let clickCount = 1; clickCount <= count; clickCount += 1) {
      await this.target.send('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button, clickCount });
      await this.target.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x, y, button, clickCount });
      await sleep(60);
    }
  }

  /**
   * Gira la rueda del ratón donde está el puntero.
   *
   * @param {number} deltaY - Desplazamiento vertical, en píxeles.
   * @returns {Promise<void>}
   */
  async wheel(deltaY) {
    await this.target.send('Input.dispatchMouseEvent', {
      type: 'mouseWheel',
      ...this.mouse,
      deltaX: 0,
      deltaY,
    });
    await sleep(200);
  }

  /**
   * Escribe un texto en el elemento con foco, carácter por carácter.
   *
   * @param {string} text - Texto.
   * @returns {Promise<void>}
   */
  async type(text) {
    for (const char of text) {
      await this.target.send('Input.dispatchKeyEvent', { type: 'keyDown', key: char, text: char });
      await this.target.send('Input.dispatchKeyEvent', { type: 'keyUp', key: char });
      await sleep(20);
    }
  }

  /**
   * Presiona una tecla especial.
   *
   * @param {'Tab'|'Enter'|'Escape'} key - Tecla.
   * @returns {Promise<void>}
   */
  async press(key) {
    const info = KEYS[key];
    await this.target.send('Input.dispatchKeyEvent', { type: 'keyDown', key, ...info });
    await this.target.send('Input.dispatchKeyEvent', { type: 'keyUp', key, ...info, text: undefined });
    await sleep(100);
  }

  /** Vuelve a la página anterior del historial y espera a que cargue. */
  async back() {
    await this.evaluate('history.back()');
    await this.waitForLoad();
  }
}
