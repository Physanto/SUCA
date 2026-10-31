/**
 * @file Versión elegida por el evaluador: se guarda en el almacenamiento del
 * navegador y se puede fijar desde la URL al abrir el sitio.
 *
 * - `?version=V1` elige una versión predefinida.
 * - `?problems=1,4` elige la versión personalizada con esos problemas.
 *
 * El parámetro se quita de la URL después de leerlo, para que las direcciones
 * que ve (y registra) cualquier herramienta sean idénticas en todas las
 * versiones.
 */

import { CUSTOM, DEFAULT_VERSION, isVersion, problemsFromNumbers } from './versions.js';

/** Clave de la configuración en el almacenamiento. */
export const SETTINGS_KEY = 'ceiba.settings';

/**
 * Lee la configuración guardada.
 *
 * @param {Storage} storage - Almacenamiento del navegador (o un sustituto).
 * @returns {import('./versions.js').Settings} La guardada, o V0 si no hay una
 *   válida.
 */
export function loadSettings(storage) {
  try {
    const saved = JSON.parse(storage.getItem(SETTINGS_KEY) ?? 'null');
    if (saved && isVersion(saved.version) && Array.isArray(saved.custom)) {
      return { version: saved.version, custom: saved.custom.filter((k) => typeof k === 'string') };
    }
  } catch {
    // Un valor corrupto se trata como si no hubiera configuración.
  }
  return { version: DEFAULT_VERSION, custom: [] };
}

/**
 * Guarda la configuración.
 *
 * @param {Storage} storage - Almacenamiento del navegador (o un sustituto).
 * @param {import('./versions.js').Settings} settings - Configuración a guardar.
 * @returns {void}
 */
export function saveSettings(storage, settings) {
  storage.setItem(
    SETTINGS_KEY,
    JSON.stringify({ version: settings.version, custom: [...settings.custom] }),
  );
}

/**
 * Lee la versión pedida en los parámetros de la URL.
 *
 * @param {URLSearchParams} params - Parámetros de la URL.
 * @returns {{ settings: import('./versions.js').Settings|null, error: string|null }}
 *   La configuración pedida (o `null` si la URL no pide ninguna) y un mensaje
 *   técnico si el parámetro no es válido.
 */
export function settingsFromParams(params) {
  if (params.has('problems')) {
    const custom = problemsFromNumbers(params.get('problems'));
    if (custom === null) return { settings: null, error: 'unknown problem number' };
    return { settings: { version: CUSTOM, custom }, error: null };
  }
  if (params.has('version')) {
    const version = params.get('version').toUpperCase();
    if (version === CUSTOM.toUpperCase() || !isVersion(version)) {
      return { settings: null, error: `unknown version ${params.get('version')}` };
    }
    return { settings: { version, custom: [] }, error: null };
  }
  return { settings: null, error: null };
}

/**
 * Quita de una URL los parámetros de versión.
 *
 * @param {URL} url - URL actual.
 * @returns {string} Ruta, consulta y fragmento sin `version` ni `problems`.
 */
export function withoutSettingsParams(url) {
  const clean = new URL(url);
  clean.searchParams.delete('version');
  clean.searchParams.delete('problems');
  return `${clean.pathname}${clean.search}${clean.hash}`;
}
