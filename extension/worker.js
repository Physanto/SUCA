/**
 * @file Service worker de la extensión: mediador entre el panel lateral y la
 * pestaña evaluada, y envío de los lotes al servidor.
 *
 * Es el punto de composición del worker: arma la cola de envío con el cliente
 * del servidor y `storage.local`, y registra los manejadores de mensajes. Chrome
 * puede terminarlo en cualquier momento; por eso la cola se guarda antes de
 * enviar y se recupera cada vez que el worker despierta.
 *
 * Mensajes que atiende (forma en `contracts/extension-messages.md`):
 * - `batch`: guarda el lote en la cola y responde cuando quedó guardado.
 * - `session.started`, `task.started`, `calibration.request`: los reenvía del
 *   panel a la pestaña evaluada.
 * - `session.closed`: lo reenvía a la pestaña, espera que vacíe su acumulador y
 *   pone el cierre de la sesión en la cola, detrás de sus lotes.
 * - `screen_capture.request`: captura la pestaña evaluada y la envía al servidor.
 * - `tab.identify`: responde a un content script el id de su pestaña.
 * - `camera.status`: si el motor de la cámara no tiene permiso, abre la página
 *   para darlo (una vez por sesión).
 *
 * Cámara: el motor (`camera/engine.html`) es un documento offscreen, que no se
 * recarga al navegar. El worker lo crea al empezar la sesión y cada vez que la
 * pestaña evaluada carga una página (por si Chrome lo cerró), y lo cierra al
 * terminar la sesión, lo que apaga la cámara.
 */

importScripts(
  'config.generated.js',
  'common/platform.js',
  'common/clock.js',
  'common/messages.js',
  'common/session.js',
  'common/send-queue.js',
  'common/api.js',
);

(function (UX) {
  'use strict';

  const { platform, messages, session, api, config, contracts } = UX;
  const { types } = messages;

  /** Clave de la cola de envío en `storage.local`. */
  const QUEUE_STORAGE_KEY = 'send_queue';
  /** Tipos de trabajo de la cola. */
  const BATCH_JOB = 'batch';
  const CLOSE_JOB = 'close';
  /** Mensajes que el panel envía a la pestaña evaluada a través del worker. */
  const FORWARDED_TO_TAB = [types.SESSION_STARTED, types.TASK_STARTED, types.CALIBRATION_REQUEST];
  /** Documento offscreen del motor de la cámara. */
  const CAMERA_ENGINE = {
    path: 'camera/engine.html',
    reasons: ['USER_MEDIA'],
    justification: 'Estimar la mirada y los movimientos faciales con la webcam durante la sesión.',
  };
  /** Página para dar el permiso de cámara. */
  const CAMERA_PERMISSION_PAGE = 'camera/permission.html';

  const queueStorage = platform.storage('local');
  const queue = UX.createSendQueue({
    send: (job) =>
      job.kind === CLOSE_JOB
        ? api.closeSession(job.session_id)
        : api.sendBatch(job.session_id, job.body),
    persist: (jobs) => queueStorage.set(QUEUE_STORAGE_KEY, jobs),
    retryInitialMs: config.sending.retry_initial_ms,
    retryMaxMs: config.sending.retry_max_ms,
  });
  // Al despertar se recupera lo que quedó pendiente y se reintenta.
  const queueReady = queueStorage.get(QUEUE_STORAGE_KEY).then((saved) => {
    queue.load(saved);
    queue.drain();
  });

  platform.allowSessionStorageInContentScripts();
  platform.openPanelOnActionClick();
  platform.onBrowserStartup(() => {
    queueReady.then(() => queue.drain());
  });
  // Al instalar se pide el permiso de cámara, para que la primera sesión no lo necesite.
  platform.onFirstInstall(() => platform.openExtensionTab(CAMERA_PERMISSION_PAGE));

  /** Sesión para la que ya se abrió la página del permiso de cámara. */
  let permissionAskedFor = null;
  /** Creación del motor en curso: Chrome no admite dos documentos offscreen. */
  let cameraStarting = null;

  /**
   * Crea el motor de la cámara si no existe. Un fallo se registra y no detiene
   * la sesión, que puede seguir sin cámara.
   *
   * @returns {Promise<void>}
   */
  function ensureCamera() {
    if (cameraStarting === null) {
      cameraStarting = platform
        .ensureOffscreen(CAMERA_ENGINE)
        .catch((error) => console.error('camera engine could not start:', error))
        .finally(() => {
          cameraStarting = null;
        });
    }
    return cameraStarting;
  }

  /**
   * Cierra el motor de la cámara, si existe; eso apaga la cámara.
   *
   * @returns {Promise<void>}
   */
  async function stopCamera() {
    await cameraStarting;
    try {
      await platform.closeOffscreen();
    } catch (error) {
      console.warn(`camera engine could not be closed: ${error.message}`);
    }
  }

  session.subscribe((state) => {
    if (state === null) {
      stopCamera();
    }
  });

  /** Indica si el mensaje viene de una página de la extensión (el panel) y no de una pestaña. */
  const fromPanel = (sender) => sender.tabId === null;

  /**
   * Devuelve la pestaña evaluada de la sesión activa. Se lee del almacenamiento
   * y no de la copia en memoria, porque el panel acaba de escribir el estado y
   * el aviso de cambio puede no haber llegado todavía.
   *
   * @returns {Promise<number>} Id de la pestaña evaluada.
   */
  async function evaluatedTab() {
    const current = await session.reload();
    if (current === null) {
      throw new Error('no active session');
    }
    return current.tab_id;
  }

  /**
   * Guarda un lote en la cola persistente.
   *
   * @param {{session_id: number, type: string, records: object[]}} payload - Lote del acumulador.
   * @returns {Promise<{queued: boolean}>} Se cumple cuando el lote quedó guardado.
   */
  async function enqueueBatch({ session_id, type, records }) {
    if (!Number.isInteger(session_id)) {
      throw new Error('batch without session_id');
    }
    await queueReady;
    await queue.enqueue({
      kind: BATCH_JOB,
      session_id,
      body: { contract_version: contracts.version, type, records },
    });
    return { queued: true };
  }

  /**
   * Cierra una sesión después de que la pestaña evaluada entregó sus últimos lotes.
   *
   * @param {{session_id: number}} payload - Sesión a cerrar.
   * @returns {Promise<{closing: boolean}>} Se cumple cuando el cierre quedó en la cola.
   */
  async function closeSession({ session_id }) {
    const current = await session.reload();
    if (current !== null && current.session_id === session_id) {
      try {
        await messages.sendToTab(current.tab_id, types.SESSION_CLOSED, { session_id });
      } catch (error) {
        // La pestaña se cerró o no tiene content scripts: no queda nada por entregar.
        console.warn(`evaluated tab did not confirm the close: ${error.message}`);
      }
    }
    await stopCamera();
    await queueReady;
    await queue.enqueue({ kind: CLOSE_JOB, session_id });
    return { closing: true };
  }

  /**
   * Captura la parte visible de la pestaña evaluada y la envía al servidor.
   *
   * @param {{study_id: number, screen: {url: string, title: string}}} payload - Datos de la captura.
   * @returns {Promise<{capture_id: number, file_path: string}>} Respuesta del servidor.
   */
  async function captureScreen({ study_id, screen }) {
    const image = await platform.captureTab(await evaluatedTab());
    return api.sendCapture({ study_id, screen, image });
  }

  // Los manejadores se registran al cargar, como exige Chrome para despertar al worker.
  messages.on(types.BATCH, (payload) => enqueueBatch(payload));

  for (const type of FORWARDED_TO_TAB) {
    messages.on(type, (payload, sender) => {
      if (!fromPanel(sender)) {
        return undefined;
      }
      // El motor se crea antes de iniciar los módulos, para que la cámara se conecte enseguida.
      const ready = type === types.SESSION_STARTED ? ensureCamera() : Promise.resolve();
      return ready
        .then(evaluatedTab)
        .then((tabId) => messages.sendToTab(tabId, type, payload));
    });
  }

  messages.on(types.SESSION_CLOSED, (payload, sender) =>
    fromPanel(sender) ? closeSession(payload) : undefined,
  );

  messages.on(types.SCREEN_CAPTURE_REQUEST, (payload, sender) =>
    fromPanel(sender) ? captureScreen(payload) : undefined,
  );

  messages.on(types.TAB_IDENTIFY, (payload, sender) => {
    // Cada página que carga la pestaña evaluada lo pregunta: es el momento de
    // revisar que el motor de la cámara siga abierto.
    session.reload().then((state) => {
      if (state !== null && state.tab_id === sender.tabId) {
        ensureCamera();
      }
    });
    return { tab_id: sender.tabId };
  });

  messages.on(types.CAMERA_STATUS, ({ status }, sender) => {
    if (fromPanel(sender) && status === 'no_permission') {
      session.reload().then((state) => {
        if (state !== null && permissionAskedFor !== state.session_id) {
          permissionAskedFor = state.session_id;
          platform.openExtensionTab(CAMERA_PERMISSION_PAGE);
        }
      });
    }
    // No responde: el mensaje es para el panel lateral.
    return undefined;
  });
})(globalThis.UX);
