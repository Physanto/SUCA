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
        const wrapped = (message, sender, sendResponse) => {
          const answer = listener(message, { tabId: sender.tab ? sender.tab.id : null });
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
    });
  }

  UX.createPlatform = createPlatform;
  // Sin Chrome (pruebas en Node) no hay plataforma: las pruebas usan sustitutos.
  UX.platform = root.chrome && root.chrome.runtime ? createPlatform(root.chrome) : null;
})(globalThis);
