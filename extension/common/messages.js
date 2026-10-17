/**
 * @file Mensajes entre las partes de la extensión (publicación y suscripción).
 *
 * Los tipos de mensaje vienen del contrato (`UX.contracts.enums.message_type`) y
 * se exponen como constantes en `UX.messages.types`, por ejemplo
 * `types.SESSION_STARTED`. Un tipo que no está en el contrato es un error
 * inmediato. La forma de cada mensaje está en `contracts/extension-messages.md`.
 */

(function (root) {
  'use strict';

  const UX = (root.UX = root.UX || {});

  /**
   * Convierte un tipo de mensaje en el nombre de su constante:
   * `screen_capture.request` → `SCREEN_CAPTURE_REQUEST`.
   *
   * @param {string} type - Tipo de mensaje del contrato.
   * @returns {string} Nombre de la constante.
   */
  function constantName(type) {
    return type.replace(/\./g, '_').toUpperCase();
  }

  /**
   * Extrae el valor de una respuesta, o lanza el error que informó el receptor.
   *
   * @param {*} response - Respuesta recibida, o `undefined` si nadie respondió.
   * @returns {*} Valor de la respuesta.
   */
  function unwrap(response) {
    if (response === undefined || response === null) {
      return undefined;
    }
    if (response.ok === false) {
      throw new Error(response.error);
    }
    return response.value;
  }

  /**
   * Crea el canal de mensajes de un contexto.
   *
   * @param {object} deps - Dependencias.
   * @param {object} deps.platform - Adaptador de plataforma.
   * @param {string[]} deps.messageTypes - Tipos de mensaje del contrato.
   * @returns {object} Canal con `types`, `send`, `sendToTab` y `on`.
   */
  function createMessages({ platform, messageTypes }) {
    const known = new Set(messageTypes);
    const types = Object.freeze(
      Object.fromEntries(messageTypes.map((type) => [constantName(type), type])),
    );
    const handlers = new Map();
    let listening = false;

    function check(type) {
      if (!known.has(type)) {
        throw new Error(`unknown message type: ${type}`);
      }
    }

    /**
     * Entrega un mensaje recibido a sus suscriptores. Responde con el primer
     * valor que devuelva alguno; los errores viajan como `{ ok: false, error }`.
     */
    function dispatch(message, sender) {
      const subscribers = message && handlers.get(message.type);
      if (!subscribers) {
        return undefined;
      }
      let answer;
      for (const handler of [...subscribers]) {
        let result;
        try {
          result = handler(message.payload, sender);
        } catch (error) {
          result = Promise.reject(error);
        }
        if (answer === undefined && result !== undefined) {
          answer = result;
        }
      }
      if (answer === undefined) {
        return undefined;
      }
      return Promise.resolve(answer).then(
        (value) => ({ ok: true, value }),
        (error) => ({ ok: false, error: error instanceof Error ? error.message : String(error) }),
      );
    }

    return Object.freeze({
      types,

      /**
       * Envía un mensaje a las páginas de la extensión (worker y panel).
       *
       * @param {string} type - Tipo de mensaje, de `types`.
       * @param {object} [payload={}] - Datos del mensaje.
       * @returns {Promise<*>} Respuesta del receptor, o `undefined` si no responde.
       */
      async send(type, payload = {}) {
        check(type);
        return unwrap(await platform.sendMessage({ type, payload }));
      },

      /**
       * Envía un mensaje a los content scripts de una pestaña. Lo usa el worker.
       *
       * @param {number} tabId - Pestaña de destino.
       * @param {string} type - Tipo de mensaje, de `types`.
       * @param {object} [payload={}] - Datos del mensaje.
       * @returns {Promise<*>} Respuesta del receptor, o `undefined` si no responde.
       */
      async sendToTab(tabId, type, payload = {}) {
        check(type);
        return unwrap(await platform.sendToTab(tabId, { type, payload }));
      },

      /**
       * Se suscribe a un tipo de mensaje.
       *
       * @param {string} type - Tipo de mensaje, de `types`.
       * @param {function(object, {tabId: (number|null)}): *} handler - Recibe los
       *   datos y el remitente. Si devuelve algo distinto de `undefined` (un
       *   valor o una promesa), eso es la respuesta.
       * @returns {function(): void} Función que cancela la suscripción.
       */
      on(type, handler) {
        check(type);
        if (!listening) {
          listening = true;
          platform.onMessage(dispatch);
        }
        if (!handlers.has(type)) {
          handlers.set(type, new Set());
        }
        handlers.get(type).add(handler);
        return () => handlers.get(type).delete(handler);
      },
    });
  }

  UX.createMessages = createMessages;
  if (UX.platform) {
    UX.messages = createMessages({
      platform: UX.platform,
      messageTypes: UX.contracts.enums.message_type,
    });
  }
})(globalThis);
