/**
 * @file Ajustes de la pantalla y la distancia de este equipo.
 *
 * Las pantallas no son iguales: los grados de error de la mirada y el modelo
 * geométrico dependen de cuántos píxeles CSS tiene un centímetro de pantalla
 * (`css_px_per_cm`) y de a qué distancia se sienta la persona. La configuración
 * compartida (`config/shared.json` → `camera`) trae los valores del laboratorio;
 * la página de opciones de la extensión permite cambiarlos en cada equipo y los
 * guarda en `chrome.storage.local` con la clave `screen_setup`.
 *
 * La calibración los combina con la configuración (`apply`) y los registra en
 * cada calibración, así el análisis usa la pantalla real de cada sesión.
 */

(function (root) {
  'use strict';

  const UX = (root.UX = root.UX || {});

  /** Clave en `chrome.storage.local`. */
  const STORAGE_KEY = 'screen_setup';
  /** Centímetros por pulgada. */
  const CM_PER_INCH = 2.54;
  /** Rangos aceptados: fuera de ellos el valor es casi seguro un error de tipeo. */
  const LIMITS = Object.freeze({
    css_px_per_cm: [10, 150],
    viewing_distance_cm: [25, 120],
    min_distance_cm: [20, 120],
    max_distance_cm: [25, 150],
  });

  /** Redondea a dos decimales. */
  const round2 = (value) => Math.round(value * 100) / 100;

  /**
   * Píxeles CSS por centímetro a partir del tamaño físico de la pantalla.
   *
   * Con la diagonal se supone que la imagen ocupa toda la pantalla con su
   * proporción en píxeles (sin bordes negros), lo habitual en portátiles y monitores.
   *
   * @param {{diagonal_in?: number, width_cm?: number}} size - Diagonal en pulgadas o
   *   ancho visible en centímetros (si vienen los dos, manda el ancho, que es más exacto).
   * @param {{width: number, height: number}} screen - Tamaño de la pantalla en píxeles CSS
   *   (`window.screen`).
   * @returns {number} Píxeles CSS por centímetro.
   */
  function cssPxPerCm(size, screen) {
    if (!(screen.width > 0) || !(screen.height > 0)) {
      throw new Error('the screen size in pixels must be positive');
    }
    if (size.width_cm > 0) {
      return round2(screen.width / size.width_cm);
    }
    if (size.diagonal_in > 0) {
      const diagonalPx = Math.hypot(screen.width, screen.height);
      return round2(diagonalPx / (size.diagonal_in * CM_PER_INCH));
    }
    throw new Error('the screen needs its diagonal in inches or its width in cm');
  }

  /**
   * Revisa unos ajustes guardados.
   *
   * @param {object} setup - Ajustes (`css_px_per_cm`, `viewing_distance_cm`,
   *   `min_distance_cm`, `max_distance_cm`).
   * @returns {string[]} Problemas encontrados, en inglés (mensajes técnicos); vacío si
   *   son válidos.
   */
  function problems(setup) {
    const found = [];
    for (const [key, [low, high]] of Object.entries(LIMITS)) {
      const value = setup[key];
      if (typeof value !== 'number' || !Number.isFinite(value) || value < low || value > high) {
        found.push(`${key} must be a number between ${low} and ${high}`);
      }
    }
    if (found.length === 0) {
      const { min_distance_cm: min, viewing_distance_cm: usual, max_distance_cm: max } = setup;
      if (!(min <= usual && usual <= max && min < max)) {
        found.push('the distances must keep min <= usual <= max');
      }
    }
    return found;
  }

  /**
   * Sección `camera` de la configuración con los ajustes de este equipo encima.
   *
   * @param {object} camera - Sección `camera` de la configuración compartida.
   * @param {(object|null|undefined)} setup - Ajustes guardados; si faltan o no son
   *   válidos, se usa la configuración tal cual.
   * @returns {object} Sección `camera` congelada, con `screen_setup` en `local` o `config`
   *   según de dónde salieron los valores.
   */
  function apply(camera, setup) {
    if (!setup || problems(setup).length > 0) {
      return Object.freeze({ ...camera, screen_setup: 'config' });
    }
    return Object.freeze({
      ...camera,
      css_px_per_cm: setup.css_px_per_cm,
      viewing_distance_cm: setup.viewing_distance_cm,
      min_distance_cm: setup.min_distance_cm,
      max_distance_cm: setup.max_distance_cm,
      screen_setup: 'local',
    });
  }

  /**
   * Lee los ajustes guardados.
   *
   * @param {{get: function(string): Promise<*>}} storage - Área `local` de `UX.platform.storage`.
   * @returns {Promise<(object|null)>} Ajustes, o `null` si no hay o no se pueden leer.
   */
  async function load(storage) {
    try {
      const setup = await storage.get(STORAGE_KEY);
      return setup && typeof setup === 'object' ? setup : null;
    } catch (error) {
      // Sin acceso al almacenamiento se sigue con la configuración compartida.
      return null;
    }
  }

  UX.screenSetup = Object.freeze({ STORAGE_KEY, LIMITS, cssPxPerCm, problems, apply, load });
})(globalThis);
