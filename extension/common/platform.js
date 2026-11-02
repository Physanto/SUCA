/**
 * @file Adaptador sobre las APIs de Chrome. Es el único archivo de la extensión
 * que llama a `chrome.*`: el resto depende de `UX.platform`, así que en las
 * pruebas se reemplaza por un sustituto con las mismas funciones.
 *
 * Funciona en los tres contextos (content script, service worker y panel), pero
 * cada contexto solo usa lo que Chrome le permite: por ejemplo, `sendToTab` y
 * `captureTab` solo tienen sentido en el worker y en el panel.
 */

(function (root) {
  'use strict';

  const UX = (root.UX = root.UX || {});

  /**
   * Crea el adaptador sobre un objeto `chrome`.
   *
   * @param {object} chrome - API de Chrome de la extensión.
   * @returns {object} Adaptador con las operaciones que usa la extensión.
   */
  function createPlatform(chrome) {
    /**
     * Acceso a un área de `chrome.storage` con una clave a la vez.
     *
     * @param {string} area - `session` o `local`.
     * @returns {object} Funciones `get`, `set`, `remove` y `onChanged`.
     */
    function storage(area) {
      const store = chrome.storage[area];
      return Object.freeze({
        get: (key) => store.get(key).then((items) => items[key]),
        set: (key, value) => store.set({ [key]: value }),
        remove: (key) => store.remove(key),
        onChanged(key, listener) {
          /** Avisa solo los cambios de esta área y esta clave. */
          const wrapped = (changes, areaName) => {
            if (areaName === area && key in changes) {
              listener(changes[key].newValue);
            }
          };
          chrome.storage.onChanged.addListener(wrapped);
          return () => chrome.storage.onChanged.removeListener(wrapped);
        },
      });
    }

    return Object.freeze({
      storage,

      /**
       * Envía un mensaje a las páginas de la extensión (worker y panel).
       *
       * @param {object} message - Mensaje `{ type, payload }`.
       * @returns {Promise<*>} Respuesta del receptor, o `undefined` si nadie responde.
       */
      sendMessage: (message) => chrome.runtime.sendMessage(message),

      /**
       * Envía un mensaje a los content scripts de una pestaña.
       *
       * @param {number} tabId - Pestaña de destino.
       * @param {object} message - Mensaje `{ type, payload }`.
       * @returns {Promise<*>} Respuesta del receptor, o `undefined` si nadie responde.
       */
      sendToTab: (tabId, message) => chrome.tabs.sendMessage(tabId, message),

      /**
       * Escucha los mensajes que llegan a este contexto.
       *
       * Si `listener` devuelve una promesa, su resultado se envía como respuesta;
       * si devuelve `undefined`, este contexto no responde y puede hacerlo otro.
       *
       * @param {function(object, {tabId: (number|null)}): (Promise<*>|undefined)} listener -
       *   Recibe el mensaje y su remitente; `tabId` es `null` si lo envió una
       *   página de la extensión.
       * @returns {function(): void} Función que deja de escuchar.
       */
      onMessage(listener) {
        const extensionOrigin = chrome.runtime.getURL('');
        /** Traduce el remitente y la respuesta de Chrome a la forma del adaptador. */
        const wrapped = (message, sender, sendResponse) => {
          // Una página de la extensión abierta en una pestaña (por ejemplo, el panel
          // abierto como pestaña al depurarlo) también trae `sender.tab`.
          const fromExtensionPage = !sender.tab || (sender.url || '').startsWith(extensionOrigin);
          const answer = listener(message, { tabId: fromExtensionPage ? null : sender.tab.id });
          if (answer === undefined) {
            return false;
          }
          answer.then(sendResponse);
          // true mantiene abierto el canal hasta que la promesa responda.
          return true;
        };
        chrome.runtime.onMessage.addListener(wrapped);
        return () => chrome.runtime.onMessage.removeListener(wrapped);
      },

      /**
       * Permite que los content scripts lean y escuchen `storage.session`, que por
       * defecto solo ven las páginas de la extensión. Lo llama el worker.
       *
       * @returns {Promise<void>}
       */
      allowSessionStorageInContentScripts: () =>
        chrome.storage.session.setAccessLevel({ accessLevel: 'TRUSTED_AND_UNTRUSTED_CONTEXTS' }),

      /**
       * Hace que el ícono de la extensión abra el panel lateral.
       *
       * @returns {Promise<void>}
       */
      openPanelOnActionClick: () =>
        chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }),

      /**
       * Devuelve la pestaña activa de la ventana actual. Desde el panel lateral,
       * es la página que se ve junto al panel.
       *
       * @returns {Promise<({id: number, url: string, title: string, width: number,
       *   height: number}|null)>} La pestaña, con el tamaño de su contenido en
       *   píxeles CSS, o `null`.
       */
      async activeTab() {
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        return tab
          ? { id: tab.id, url: tab.url, title: tab.title, width: tab.width, height: tab.height }
          : null;
      },

      /**
       * Captura la parte visible de una pestaña, que debe ser la activa de su ventana.
       *
       * @param {number} tabId - Pestaña a capturar.
       * @returns {Promise<string>} Imagen PNG como data URL.
       */
      async captureTab(tabId) {
        const tab = await chrome.tabs.get(tabId);
        return chrome.tabs.captureVisibleTab(tab.windowId, { format: 'png' });
      },

      /**
       * Registra una función para cuando Chrome se abre. Registrarla hace que
       * Chrome despierte al worker al abrirse.
       *
       * @param {function(): void} listener - Función a llamar.
       * @returns {void}
       */
      onBrowserStartup: (listener) => chrome.runtime.onStartup.addListener(listener),

      /**
       * Registra una función para cuando la extensión se instala por primera vez.
       *
       * @param {function(): void} listener - Función a llamar.
       * @returns {void}
       */
      onFirstInstall(listener) {
        chrome.runtime.onInstalled.addListener(({ reason }) => {
          if (reason === 'install') {
            listener();
          }
        });
      },

      /**
       * Dirección completa de un archivo de la extensión.
       *
       * @param {string} path - Ruta dentro de `extension/`, por ejemplo `lib/x.wasm`.
       * @returns {string} URL `chrome-extension://…`.
       */
      extensionUrl: (path) => chrome.runtime.getURL(path),

      /**
       * Abre una página de la extensión en una pestaña nueva.
       *
       * @param {string} path - Ruta dentro de `extension/`.
       * @returns {Promise<void>}
       */
      async openExtensionTab(path) {
        await chrome.tabs.create({ url: chrome.runtime.getURL(path) });
      },

      /**
       * Crea el documento offscreen si no existe. Lo usa el worker.
       *
       * @param {{path: string, reasons: string[], justification: string}} options -
       *   Página, motivos de `chrome.offscreen.Reason` y explicación.
       * @returns {Promise<boolean>} `true` si lo creó, `false` si ya existía.
       */
      async ensureOffscreen({ path, reasons, justification }) {
        const url = chrome.runtime.getURL(path);
        const existing = await chrome.runtime.getContexts({
          contextTypes: ['OFFSCREEN_DOCUMENT'],
          documentUrls: [url],
        });
        if (existing.length > 0) {
          return false;
        }
        await chrome.offscreen.createDocument({ url, reasons, justification });
        return true;
      },

      /**
       * Cierra el documento offscreen si existe.
       *
       * @returns {Promise<boolean>} `true` si había uno y se cerró.
       */
      async closeOffscreen() {
        const existing = await chrome.runtime.getContexts({ contextTypes: ['OFFSCREEN_DOCUMENT'] });
        if (existing.length === 0) {
          return false;
        }
        await chrome.offscreen.closeDocument();
        return true;
      },

      /**
       * Abre una conexión con las páginas de la extensión. Desde un content
       * script, llega al documento offscreen que la escucha.
       *
       * @param {string} name - Nombre de la conexión.
       * @returns {{post: function(object): void, onMessage: function(function(object): void): void,
       *   onDisconnect: function(function(): void): void, disconnect: function(): void}} Conexión.
       */
      connect: (name) => wrapPort(chrome.runtime.connect({ name })),

      /**
       * Escucha las conexiones con un nombre.
       *
       * @param {string} name - Nombre de la conexión.
       * @param {function(object): void} listener - Recibe la conexión, con la misma forma que `connect`.
       * @returns {void}
       */
      onConnect(name, listener) {
        chrome.runtime.onConnect.addListener((port) => {
          if (port.name === name) {
            listener(wrapPort(port));
          }
        });
      },
    });
  }

  /**
   * Adapta un `chrome.runtime.Port`. Enviar por una conexión cerrada no falla:
   * se ignora, porque el otro lado ya no está.
   *
   * @param {object} port - Conexión de Chrome.
   * @returns {object} Conexión con `post`, `onMessage`, `onDisconnect` y `disconnect`.
   */
  function wrapPort(port) {
    let open = true;
    port.onDisconnect.addListener(() => {
      open = false;
      // Leer el error evita el aviso "Unchecked runtime.lastError" de Chrome.
      void (root.chrome && root.chrome.runtime && root.chrome.runtime.lastError);
    });
    return Object.freeze({
      post(message) {
        if (!open) {
          return;
        }
        try {
          port.postMessage(message);
        } catch {
          open = false;
        }
      },
      onMessage: (listener) => port.onMessage.addListener((message) => listener(message)),
      onDisconnect: (listener) => port.onDisconnect.addListener(() => listener()),
      disconnect() {
        open = false;
        port.disconnect();
      },
    });
  }

  UX.createPlatform = createPlatform;
  // Sin Chrome (pruebas en Node) no hay plataforma: las pruebas usan sustitutos.
  UX.platform = root.chrome && root.chrome.runtime ? createPlatform(root.chrome) : null;
})(globalThis);
