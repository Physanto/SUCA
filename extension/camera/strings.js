/**
 * @file Textos de la cámara que ven el participante y el evaluador, en español:
 * la capa de calibración (en la pestaña evaluada) y la página del permiso de
 * cámara. Ningún otro archivo de la cámara escribe textos visibles.
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
      title: { initial: 'Calibración de la mirada', final: 'Comprobación final de la mirada' },
      intro: {
        initial:
          'Van a aparecer puntos en la pantalla, uno a la vez. Mira cada punto y haz clic sobre él. Después sigue mirándolo hasta que desaparezca. Mantén la cabeza quieta durante toda la prueba.',
        final:
          'Van a aparecer algunos puntos, uno a la vez. Solo míralos hasta que desaparezcan; no hace falta hacer clic. Mantén la cabeza quieta.',
      },
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
      clickHint: 'Mira el punto y haz clic sobre él',
      lookHint: 'Mira el punto',
      validating: 'Ahora solo mira cada punto, sin hacer clic.',
      fitting: 'Calculando…',
      accepted: 'Listo. La calibración quedó bien.',
      rejected: 'La calibración no quedó suficientemente precisa. Puedes repetirla.',
      result: (errorDeg) => `Error medio: ${errorDeg.toFixed(1)}°`,
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
  });
})(globalThis);
