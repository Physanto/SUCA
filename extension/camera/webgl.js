/**
 * @file Comprueba que el navegador puede crear un contexto WebGL.
 *
 * MediaPipe Face Landmarker recibe cada cuadro como una textura WebGL, también
 * cuando analiza con la CPU. Sin WebGL (por ejemplo, con la aceleración
 * gráfica de Chrome desactivada) el modelo carga, pero falla en el primer
 * cuadro. Por eso el motor lo comprueba antes de abrir la webcam.
 *
 * La función es pura respecto al navegador: recibe cómo crear el lienzo, así
 * que se prueba en Node.
 */

(function (root) {
  'use strict';

  const UX = (root.UX = root.UX || {});

  /** Tipos de contexto que acepta MediaPipe, del preferido al de respaldo. */
  const CONTEXT_TYPES = ['webgl2', 'webgl'];

  /**
   * Indica si se puede crear un contexto WebGL. El contexto de la prueba se
   * libera enseguida para no ocupar uno de los pocos que Chrome permite.
   *
   * @param {function(): {getContext: function(string): ?object}} createCanvas -
   *   Crea un lienzo (`OffscreenCanvas` o `<canvas>`).
   * @returns {boolean} `true` si algún tipo de contexto WebGL está disponible.
   */
  function webglAvailable(createCanvas) {
    for (const type of CONTEXT_TYPES) {
      let context = null;
      try {
        context = createCanvas().getContext(type);
      } catch {
        // Algunos navegadores lanzan en vez de devolver null: cuenta como no disponible.
      }
      if (context) {
        const lose = context.getExtension && context.getExtension('WEBGL_lose_context');
        if (lose) {
          lose.loseContext();
        }
        return true;
      }
    }
    return false;
  }

  UX.webglAvailable = webglAvailable;
})(globalThis);
