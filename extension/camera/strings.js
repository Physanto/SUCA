/**
 * @file Textos de la cámara que ven el participante y el evaluador, en español:
 * la capa de calibración (en la pestaña evaluada), la página del permiso de
 * cámara y la página de opciones con la pantalla y las distancias. Ningún otro
 * archivo de la cámara escribe textos visibles.
 *
 * Están aparte de `panel/strings.js` porque se cargan en la pestaña evaluada y
 * en páginas de la extensión que no son el panel.
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

  UX.cameraStrings = deepFreeze({
    calibration: {
      title: {
        initial: 'Calibración de la mirada',
        final: 'Comprobación final de la mirada',
        drift_check: 'Comprobación rápida de la mirada',
      },
      intro: {
        initial:
          'Son tres partes cortas, de poco más de un minuto en total. Primero van a aparecer puntos, uno a la vez: mira cada punto, haz clic sobre él y sigue mirándolo hasta que desaparezca. Durante la calibración mantén la cabeza quieta salvo cuando se te pida moverla. Después podrás moverte con naturalidad.',
        final:
          'Van a aparecer algunos puntos, uno a la vez. Solo míralos hasta que desaparezcan; no hace falta hacer clic.',
        drift_check: 'Mira cada punto y haz clic sobre él. Son tres puntos y toma unos segundos.',
      },
      pursuitIntro:
        'Ahora un punto se va a mover por la pantalla. Síguelo con la vista, sin mover la cabeza, hasta que se detenga.',
      pursuitHint: 'Sigue el punto con la vista',
      neutralBaselineHint: 'Mira el centro durante 10 segundos con el rostro relajado y sin hablar.',
      headIntro:
        'Ahora mira el punto del centro sin dejar de mirarlo, y mueve la cabeza despacio: un poco a la izquierda, a la derecha, arriba, abajo, y acércate y aléjate de la pantalla.',
      headHint: 'Sin dejar de mirar el punto, mueve la cabeza despacio en todas direcciones',
      lookAwayIntro:
        'Último punto: al hacer clic en Listo, mira tu teclado, cuenta hasta tres y vuelve a mirar el punto rojo.',
      lookAwayHint: 'Mira tu teclado, cuenta hasta tres y vuelve a mirar este punto',
      readyButton: 'Listo',
      startButton: 'Comenzar',
      startAnywayButton: 'Comenzar de todos modos',
      framing: {
        searching: 'Buscando tu cara…',
        noFace: 'No se ve tu cara: siéntate frente a la cámara, con luz de frente.',
        face: 'Se ve tu cara',
        distance: (cm) => `Distancia: unos ${cm} cm`,
        near: (cm) => `Estás muy cerca (unos ${cm} cm): aléjate un poco`,
        far: (cm) => `Estás muy lejos (unos ${cm} cm): acércate un poco`,
        centered: 'Tu cara está centrada',
        left: 'Muévete un poco hacia tu izquierda',
        right: 'Muévete un poco hacia tu derecha',
        up: 'Tu cara queda muy arriba: inclina la cámara un poco hacia arriba (en un portátil, la pantalla hacia atrás)',
        down: 'Tu cara queda muy abajo: inclina la cámara un poco hacia abajo (en un portátil, la pantalla hacia adelante)',
        frontal: 'Miras de frente a la pantalla',
        turned: 'Gira la cabeza hacia la pantalla',
        ready: 'Todo bien: puedes comenzar.',
        adjust: 'Acomódate hasta que la figura quede verde, dentro del óvalo.',
      },
      screenSummary: (camera) =>
        `Pantalla: ${camera.css_px_per_cm} píxeles por centímetro; distancia habitual ${camera.viewing_distance_cm} cm ` +
        `(de ${camera.min_distance_cm} a ${camera.max_distance_cm} cm). ` +
        (camera.screen_setup === 'local'
          ? 'Ajustada en este equipo.'
          : 'Son los valores por defecto: si esta pantalla es otra, el evaluador los cambia en las opciones de la extensión (clic derecho en el ícono de SUCA → Opciones).'),
      clickHint: 'Mira el punto y haz clic sobre él',
      lookHint: 'Mira el punto',
      validating: 'Ahora solo mira cada punto, sin hacer clic.',
      fitting: 'Calculando…',
      accepted: 'Listo. La calibración quedó bien.',
      rejected: 'La calibración no quedó suficientemente precisa. Puedes repetirla.',
      result: (errorDeg) => `Error medio: ${errorDeg.toFixed(1)}°`,
      driftOk: 'La mirada sigue bien.',
      driftCorrected: 'La mirada se había corrido un poco y quedó corregida.',
      driftLarge: 'La mirada se desvió bastante. Conviene repetir la calibración inicial desde el panel.',
      continueButton: 'Continuar',
      repeatButton: 'Repetir',
      cancelButton: 'Cancelar',
      cameraStarting: 'Preparando la cámara…',
      cameraUnavailable:
        'La cámara no está disponible. Revisa el estado de la cámara en el panel lateral.',
      noFace:
        'No se detectó bien el rostro. Acomódate frente a la cámara, con buena luz de frente, y repite.',
      notCalibrated: 'Primero hace falta la calibración inicial.',
    },
    permission: {
      title: 'Permiso de cámara para SUCA',
      body: 'SUCA usa la cámara para estimar la mirada y los movimientos faciales. Solo guarda números: nunca guarda ni envía video ni imágenes. El permiso se da una sola vez en esta computadora.',
      button: 'Permitir la cámara',
      asking: 'Elige "Permitir" en el aviso de Chrome…',
      granted: 'Listo: la cámara quedó permitida. Puedes cerrar esta pestaña y volver a la sesión.',
      denied:
        'Chrome no dio el permiso. Para cambiarlo, haz clic en el ícono de la cámara de la barra de direcciones (o en Configuración del sitio) y elige "Permitir"; luego vuelve a presionar el botón.',
      noCamera: 'No se encontró una cámara conectada.',
    },
    screenSetup: {
      detected: (width, height, ratio) =>
        `Esta pantalla mide ${width} × ${height} píxeles CSS (escala del sistema ${ratio}).`,
      density: (pxPerCm) => `${pxPerCm} píxeles por centímetro`,
      needSize: 'Escribe la diagonal en pulgadas o el ancho visible en centímetros.',
      saved: 'Guardado. Se usa desde la próxima calibración.',
      reset: 'Se volvió a los valores por defecto del laboratorio.',
      fromConfig: 'Ahora se usan los valores por defecto del laboratorio.',
      fromLocal: (date) => `Ahora se usan los ajustes de este equipo (guardados el ${date}).`,
      otherScreen: (width, height) =>
        `Los ajustes guardados son de una pantalla de ${width} × ${height} píxeles: si cambiaste de monitor, revísalos.`,
      invalid: 'Revisa los valores: la distancia habitual debe quedar entre la mínima y la máxima, y todos deben ser razonables (pantalla de 10 a 150 píxeles por cm; distancias de 20 a 150 cm).',
    },
  });
})(globalThis);
