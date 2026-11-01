/**
 * @file Textos visibles del panel lateral, en español. Ningún otro archivo del
 * panel escribe textos para el evaluador o el participante: la vista los toma
 * de aquí (en el HTML, con el atributo `data-string`).
 *
 * Los textos con datos son funciones que reciben esos datos.
 */

(function (root) {
  'use strict';

  const UX = (root.UX = root.UX || {});

  /** Congela un objeto y todo lo que contiene. */
  function deepFreeze(value) {
    Object.values(value).forEach((child) => {
      if (child !== null && typeof child === 'object') {
        deepFreeze(child);
      }
    });
    return Object.freeze(value);
  }

  UX.strings = deepFreeze({
    title: 'SUCA',
    loading: 'Conectando con el servidor local…',
    starting: 'Iniciando la sesión…',
    closing: 'Cerrando la sesión…',
    retryButton: 'Reintentar',

    // Inicio de sesión.
    newSession: 'Nueva sesión',
    studyLabel: 'Estudio',
    noStudies: 'No hay estudios cargados. Carga uno con: python -m scripts.load_study <archivo>.yaml',
    participantLabel: 'Código del participante',
    participantHint: 'Un código anónimo, como P07. Nunca un nombre.',
    versionLabel: 'Versión del sistema',
    versionPlaceholder: 'V0',
    modeLabel: 'Modo',
    modes: { free: 'Libre', guided: 'Guiado', reference: 'Referencia' },
    startButton: 'Iniciar sesión',
    startHint: 'Antes de iniciar, abre en la pestaña activa la página que se va a evaluar.',

    // Sesión en curso.
    activeSession: 'Sesión en curso',
    sessionLabel: 'Sesión',
    tabLabel: 'Pestaña evaluada',
    tabUnknown: 'La pestaña en la que se inició la sesión',
    captureLabel: 'Captura',
    tabStatus: {
      capturing: 'Activa en la pestaña evaluada.',
      pending: 'La pestaña todavía no respondió. Si es una página web, recárgala.',
      unknown: 'Sin información desde que se abrió el panel.',
    },
    failedModules: (names) => `No arrancaron: ${names.join(', ')}. Revisa la consola de la pestaña.`,
    closeButton: 'Cerrar sesión',
    elapsedLabel: 'Tiempo',
    elapsedUnknown: '—',
    /** Tiempo transcurrido como `mm:ss`, o `h:mm:ss` desde la primera hora. */
    elapsedTime: (ms) => {
      const total = Math.max(Math.floor(ms / 1000), 0);
      const two = (value) => String(value).padStart(2, '0');
      const hours = Math.floor(total / 3600);
      const rest = `${two(Math.floor((total % 3600) / 60))}:${two(total % 60)}`;
      return hours > 0 ? `${hours}:${rest}` : rest;
    },

    // Cámara y calibración.
    cameraTitle: 'Cámara y calibración',
    cameraLabel: 'Cámara:',
    cameraStatus: {
      unknown: 'Sin información todavía.',
      active: 'Activa.',
      no_permission: 'Sin permiso de cámara. La sesión puede seguir sin ella.',
      error: 'Con error. La sesión puede seguir sin ella.',
    },
    calibrationButtons: { initial: 'Calibración inicial', final: 'Calibración final' },
    calibrationWaiting: 'Esperando el resultado en la pestaña…',
    calibrationResult: (result) => {
      const number = (value) => value.toFixed(1).replace('.', ',');
      const verdict = result.accepted ? 'Aceptada' : 'No aceptada';
      return `Error ${number(result.error_px)} px (${number(result.error_deg)}°) · ${verdict}`;
    },

    // Modo guiado.
    tasksTitle: 'Tareas',
    taskProgress: (number, total) => `Tarea ${number} de ${total}`,
    taskStartButton: 'Empezar',
    taskDoneButton: 'Terminé',
    taskGaveUpButton: 'No pude',
    tasksLoading: 'Cargando las tareas…',
    noTasks: 'Este estudio no tiene tareas.',
    tasksFinished: 'Completaste todas las tareas. Cierra la sesión para terminar.',

    // Avisos.
    notices: {
      session_closed: (sessionId) => `Sesión ${sessionId} cerrada.`,
    },

    // Errores. Las claves son los códigos que informa la lógica del panel.
    errors: {
      server_unreachable:
        'No se pudo conectar con el servidor local. Comprueba que esté en marcha (python -m server).',
      tab_not_evaluable:
        'La pestaña activa no se puede evaluar. Abre en ella la página del estudio (http o https) y vuelve a intentarlo.',
      calibration_unavailable:
        'La pestaña evaluada no respondió a la calibración. Si es una página web, recárgala e inténtalo de nuevo.',
      invalid_request: 'Revisa los datos marcados.',
      unexpected: (detail) => `Error inesperado: ${detail}`,
    },
    fieldErrors: {
      study_id: 'Elige un estudio.',
      participant_id: 'Usa solo letras, números, guion y guion bajo (hasta 32 caracteres).',
      version: 'Escribe la versión (hasta 32 caracteres).',
      mode: 'Elige un modo.',
    },
  });
})(globalThis);
