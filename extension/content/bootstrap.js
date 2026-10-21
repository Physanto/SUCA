/**
 * @file Arranque de los content scripts: une los módulos registrados al ciclo
 * de la sesión, solo en la pestaña evaluada.
 *
 * Es el punto de composición de los content scripts: arma el contexto que
 * reciben los módulos y decide cuándo iniciarlos y detenerlos.
 * - **Al cargar la página:** si hay una sesión activa y esta pestaña es la
 *   evaluada (lo pregunta con `tab.identify`), inicia los módulos. Así vuelven
 *   a arrancar después de cada navegación.
 * - **`session.started`** (del panel, vía worker): inicia los módulos y
 *   responde `{ started, failed }`.
 * - **`session.closed`** (vía worker): detiene los módulos, vacía el acumulador
 *   y responde `{ flushed }`; recién entonces el worker cierra la sesión.
 * - **Estado borrado** sin `session.closed` (por ejemplo, el evaluador cerró el
 *   panel): detiene los módulos.
 *
 * Se carga último, después de las utilidades comunes y de los módulos.
 */

(function (root) {
  'use strict';

  const UX = (root.UX = root.UX || {});

  /**
   * Conecta los módulos con el ciclo de la sesión de esta pestaña.
   *
   * @param {object} deps - Dependencias.
   * @param {object} deps.modules - Registro de módulos (`UX.modules`).
   * @param {object} deps.messages - Canal de mensajes (`UX.messages`).
   * @param {object} deps.session - Estado de la sesión (`UX.session`).
   * @param {object} deps.batcher - Acumulador (`UX.batcher`).
   * @param {object} deps.clock - Reloj (`UX.clock`).
   * @param {object} deps.config - Configuración (`UX.config`).
   * @param {object} deps.contracts - Versión y enumeraciones (`UX.contracts`).
   * @returns {{ready: Promise<boolean>, context: object}} `ready` se cumple
   *   cuando terminó la revisión inicial (`true` si inició los módulos);
   *   `context` es lo que reciben los módulos.
   */
  function createBootstrap({ modules, messages, session, batcher, clock, config, contracts }) {
    const { types } = messages;

    // Los módulos leen la sesión pero no la escriben: solo el panel la escribe.
    const context = Object.freeze({
      clock,
      batcher,
      messages,
      config,
      contracts,
      session: Object.freeze({ get: session.get, subscribe: session.subscribe }),
    });

    /** Inicia los módulos con el estado de la sesión recién leído. */
    async function start() {
      // El panel acaba de escribir el estado y el aviso puede no haber llegado:
      // sin releerlo, el acumulador descartaría los primeros registros.
      await session.reload();
      return modules.startAll(context);
    }

    /** Detiene los módulos y entrega lo que quedaba en el acumulador. */
    async function stop() {
      await modules.stopAll();
      return { flushed: await batcher.flush() };
    }

    messages.on(types.SESSION_STARTED, () => start());
    messages.on(types.SESSION_CLOSED, () => stop());
    session.subscribe((state) => {
      if (state === null && modules.isRunning()) {
        stop();
      }
    });

    const ready = (async () => {
      await session.ready;
      const state = session.get();
      if (state === null) {
        return false;
      }
      const { tab_id: tabId } = await messages.send(types.TAB_IDENTIFY);
      if (tabId !== state.tab_id) {
        return false;
      }
      await start();
      return true;
    })().catch((error) => {
      console.error('bootstrap could not check the session', error);
      return false;
    });

    return Object.freeze({ ready, context });
  }

  UX.createBootstrap = createBootstrap;
  if (UX.platform) {
    UX.bootstrap = createBootstrap({
      modules: UX.modules,
      messages: UX.messages,
      session: UX.session,
      batcher: UX.batcher,
      clock: UX.clock,
      config: UX.config,
      contracts: UX.contracts,
    });
  }
})(globalThis);
