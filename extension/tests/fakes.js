/**
 * @file Sustitutos para las pruebas de la extensión: una plataforma en memoria
 * con varios contextos (panel, worker, pestañas), temporizadores manuales y un
 * objeto `chrome` falso para cargar el worker completo.
 *
 * No es un archivo de pruebas (no termina en `.test.js`): lo usan las pruebas.
 */

'use strict';

const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const EXTENSION_DIR = path.join(__dirname, '..');

/** Copia un valor como lo haría la mensajería de Chrome (sin referencias compartidas). */
const clone = (value) => (value === undefined ? undefined : structuredClone(value));

/**
 * Espera a que se ejecute lo pendiente: promesas y avisos de almacenamiento.
 *
 * Usa `setTimeout` y no `setImmediate`: los avisos del almacenamiento falso
 * también usan `setTimeout`, y así se ejecutan antes, en el orden en que se
 * programaron.
 *
 * @param {number} [rounds=3] - Vueltas del ciclo de eventos.
 * @returns {Promise<void>}
 */
async function settle(rounds = 3) {
  for (let i = 0; i < rounds; i += 1) {
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
}

/**
 * Entrega un mensaje a los suscriptores de unos contextos y devuelve la primera
 * respuesta, como `chrome.runtime.sendMessage`.
 */
async function deliver(targets, message, sender) {
  if (targets.length === 0) {
    throw new Error('Could not establish connection. Receiving end does not exist.');
  }
  for (const target of targets) {
    for (const listener of [...target.listeners]) {
      const answer = listener(clone(message), sender);
      if (answer !== undefined) {
        return clone(await answer);
      }
    }
  }
  return undefined;
}

/**
 * Crea un "navegador" en memoria. Cada llamada a `platform()` es un contexto
 * con el mismo almacenamiento, como el panel, el worker y las pestañas.
 *
 * @returns {{platform: function({tabId: (number|null)}=): object, areas: object}} Mundo falso.
 */
function createFakeWorld() {
  const areas = { session: new Map(), local: new Map() };
  const storageListeners = new Set();
  const contexts = [];

  function notify(area, key, value) {
    // Chrome avisa los cambios de forma asíncrona, a veces después de que la
    // escritura ya terminó.
    setTimeout(() => {
      for (const entry of [...storageListeners]) {
        if (entry.area === area && entry.key === key) {
          entry.listener(clone(value));
        }
      }
    }, 0);
  }

  function platform({ tabId = null } = {}) {
    const context = { tabId, listeners: new Set() };
    contexts.push(context);
    return {
      storage(area) {
        return {
          get: async (key) => clone(areas[area].get(key)),
          set: async (key, value) => {
            areas[area].set(key, clone(value));
            notify(area, key, value);
          },
          remove: async (key) => {
            areas[area].delete(key);
            notify(area, key, undefined);
          },
          onChanged(key, listener) {
            const entry = { area, key, listener };
            storageListeners.add(entry);
            return () => storageListeners.delete(entry);
          },
        };
      },
      sendMessage: (message) =>
        deliver(
          contexts.filter((other) => other !== context && other.tabId === null),
          message,
          { tabId },
        ),
      sendToTab: (targetTab, message) =>
        deliver(
          contexts.filter((other) => other.tabId === targetTab),
          message,
          { tabId: null },
        ),
      onMessage(listener) {
        context.listeners.add(listener);
        return () => context.listeners.delete(listener);
      },
    };
  }

  return { platform, areas };
}

/**
 * Temporizadores que solo avanzan cuando la prueba lo pide.
 *
 * @returns {object} `setTimeout`, `clearTimeout`, `now`, `advance` y `pending`.
 */
function createFakeTimers() {
  let now = 0;
  let nextId = 1;
  const timers = new Map();

  return {
    setTimeout(callback, delay) {
      const id = nextId;
      nextId += 1;
      timers.set(id, { at: now + delay, callback });
      return id;
    },
    clearTimeout(id) {
      timers.delete(id);
    },
    now: () => now,
    pending: () => timers.size,
    /** Avanza el reloj y ejecuta, en orden, los temporizadores que vencen. */
    async advance(ms) {
      const target = now + ms;
      for (;;) {
        const due = [...timers.entries()]
          .filter(([, timer]) => timer.at <= target)
          .sort((a, b) => a[1].at - b[1].at)[0];
        if (!due) {
          break;
        }
        const [id, timer] = due;
        timers.delete(id);
        now = timer.at;
        timer.callback();
        await settle();
      }
      now = target;
      await settle();
    },
  };
}

/**
 * Crea un objeto `chrome` falso suficiente para el worker, con una pestaña
 * evaluada simulada y un servidor simulado.
 *
 * @param {object} [options] - Opciones.
 * @param {function(string, object): {status: number, body: object}} [options.server] -
 *   Responde cada petición; por defecto, 200 con `{}`.
 * @returns {object} `chrome`, `fetch`, registros de llamadas y funciones para
 *   simular al panel y a las pestañas.
 */
function createFakeChrome({ server = () => ({ status: 200, body: {} }) } = {}) {
  const areas = { session: new Map(), local: new Map() };
  const storageListeners = [];
  const runtimeListeners = [];
  const tabs = new Map();
  const requests = [];
  const calls = { accessLevel: null, panelBehavior: null, captured: [] };

  const area = (name) => ({
    get: async (key) => ({ [key]: clone(areas[name].get(key)) }),
    set: async (items) => {
      for (const [key, value] of Object.entries(items)) {
        areas[name].set(key, clone(value));
        storageListeners.forEach((listener) => listener({ [key]: { newValue: clone(value) } }, name));
      }
    },
    remove: async (key) => {
      areas[name].delete(key);
      storageListeners.forEach((listener) => listener({ [key]: { newValue: undefined } }, name));
    },
    setAccessLevel: async (options) => {
      calls.accessLevel = options;
    },
  });

  const chrome = {
    runtime: {
      id: 'fake-extension',
      getURL: (resource = '') => `chrome-extension://fake-extension/${resource}`,
      onMessage: {
        addListener: (listener) => runtimeListeners.push(listener),
        removeListener() {},
      },
      sendMessage: async () => undefined,
      onStartup: { addListener() {} },
    },
    storage: {
      session: area('session'),
      local: area('local'),
      onChanged: { addListener: (listener) => storageListeners.push(listener), removeListener() {} },
    },
    sidePanel: {
      setPanelBehavior: async (options) => {
        calls.panelBehavior = options;
      },
    },
    tabs: {
      async sendMessage(tabId, message) {
        const handler = tabs.get(tabId);
        if (!handler) {
          throw new Error('Could not establish connection. Receiving end does not exist.');
        }
        return clone(await handler(clone(message)));
      },
      get: async (id) => ({ id, windowId: 100 + id }),
      captureVisibleTab: async (windowId, options) => {
        calls.captured.push({ windowId, options });
        return 'data:image/png;base64,iVBORw0KGgo=';
      },
    },
  };

  async function fetch(url, init) {
    const request = {
      method: init.method,
      path: new URL(url).pathname,
      headers: init.headers,
      body: init.body === undefined ? undefined : JSON.parse(init.body),
    };
    requests.push(request);
    const { status, body } = server(request.path, request);
    return { ok: status < 400, status, statusText: String(status), json: async () => body };
  }

  /**
   * Entrega un mensaje al worker como lo haría Chrome y devuelve su respuesta ya
   * desempaquetada (`{ ok, value }` → `value`).
   */
  function sendToWorker(message, sender) {
    return new Promise((resolve, reject) => {
      for (const listener of runtimeListeners) {
        const keepOpen = listener(clone(message), sender, (response) => {
          if (response && response.ok === false) {
            reject(new Error(response.error));
          } else {
            resolve(response && clone(response.value));
          }
        });
        if (keepOpen === true) {
          return;
        }
      }
      resolve(undefined);
    });
  }

  return {
    chrome,
    fetch,
    areas,
    requests,
    calls,
    /** Simula al panel lateral: sin pestaña de origen. */
    fromPanel: (type, payload = {}) => sendToWorker({ type, payload }, {}),
    /** Simula a un content script de la pestaña `tabId`. */
    fromTab: (tabId, type, payload = {}) => sendToWorker({ type, payload }, { tab: { id: tabId } }),
    /** Define cómo responde a los mensajes el content script de una pestaña. */
    onTabMessage: (tabId, handler) => tabs.set(tabId, handler),
    sendToWorker,
  };
}

/**
 * Carga `worker.js` en un contexto aislado con un `chrome` y un `fetch` falsos,
 * como si Chrome lo despertara.
 *
 * @param {object} fake - Resultado de `createFakeChrome`.
 * @returns {object} Contexto global del worker (con `UX`).
 */
function loadWorker(fake) {
  const context = vm.createContext({
    chrome: fake.chrome,
    fetch: fake.fetch,
    console,
    // unref: un reintento pendiente de la cola no debe impedir que Node termine.
    setTimeout: (callback, delay) => setTimeout(callback, delay).unref(),
    clearTimeout,
    structuredClone,
    performance,
    URL,
  });
  const run = (file) =>
    vm.runInContext(fs.readFileSync(path.join(EXTENSION_DIR, file), 'utf8'), context, {
      filename: file,
    });
  context.importScripts = (...files) => files.forEach(run);
  run('worker.js');
  return context;
}

module.exports = { createFakeWorld, createFakeTimers, createFakeChrome, loadWorker, settle };
