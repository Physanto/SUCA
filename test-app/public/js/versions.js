/**
 * @file Configuración de versiones: qué problemas sembrados tiene activos cada
 * versión de la tienda.
 *
 * Es el único lugar donde se decide. El código de cada pantalla solo pregunta
 * si un problema está activo (`problems.has('slow_add_to_cart')`); así V0, V1
 * y V2 comparten un solo código, y cada problema se puede activar por separado
 * con la versión personalizada.
 *
 * Regla de diseño: ningún problema cambia la ruta ideal de una tarea (las
 * mismas pantallas, textos y roles en las tres versiones), para que una sola
 * referencia grabada sirva para todas. El catálogo detallado está en
 * `test-app/PROBLEMS.md`.
 */

/**
 * @typedef {object} Problem
 * @property {string} key - Identificador en el código.
 * @property {number} number - Número en el catálogo de problemas.
 * @property {string} title - Nombre corto, para la página del evaluador.
 * @property {string} where - Pantalla donde aparece.
 */

/** @type {ReadonlyArray<Readonly<Problem>>} */
export const PROBLEMS = Object.freeze(
  [
    {
      key: 'button_like_image',
      number: 1,
      title: 'Imagen que parece botón',
      where: 'Detalle de producto',
    },
    {
      key: 'slow_add_to_cart',
      number: 2,
      title: 'Botón lento sin indicador de carga',
      where: 'Detalle de producto',
    },
    {
      key: 'illogical_account_menu',
      number: 3,
      title: 'Opción importante en un menú poco lógico',
      where: 'Menú de la cuenta',
    },
    {
      key: 'form_clears_on_error',
      number: 4,
      title: 'Formulario que borra los datos al mostrar un error',
      where: 'Pago',
    },
    {
      key: 'low_contrast_link',
      number: 5,
      title: 'Enlace con bajo contraste',
      where: 'Mi cuenta',
    },
    {
      key: 'ambiguous_error',
      number: 6,
      title: 'Mensaje de error ambiguo',
      where: 'Pago',
    },
    {
      key: 'slow_login',
      number: 7,
      title: 'Inicio de sesión lento y sin retroalimentación',
      where: 'Iniciar sesión',
    },
    {
      key: 'strict_search',
      number: 8,
      title: 'Buscador que no tolera errores de escritura',
      where: 'Búsqueda',
    },
  ].map((problem) => Object.freeze(problem)),
);

/** Identificadores de todos los problemas, en orden de catálogo. */
const ALL = PROBLEMS.map((problem) => problem.key);

/**
 * Problemas activos de cada versión predefinida. V1 tiene ~4 problemas y V2
 * ~8, que incluyen los de V1.
 *
 * @type {Readonly<Object<string, ReadonlyArray<string>>>}
 */
export const VERSIONS = Object.freeze({
  V0: Object.freeze([]),
  V1: Object.freeze(ALL.slice(0, 4)),
  V2: Object.freeze(ALL.slice(0, 8)),
});

/** Versión personalizada: los problemas se eligen uno por uno. */
export const CUSTOM = 'custom';

/** Versión por defecto: sin problemas. */
export const DEFAULT_VERSION = 'V0';

/**
 * @typedef {object} Settings
 * @property {string} version - `V0`, `V1`, `V2` o `custom`.
 * @property {string[]} custom - Problemas elegidos para la versión personalizada.
 */

/**
 * Indica si un valor es una versión conocida.
 *
 * @param {unknown} version - Valor a revisar.
 * @returns {boolean} Si es `V0`, `V1`, `V2` o `custom`.
 */
export function isVersion(version) {
  return version === CUSTOM || Object.hasOwn(VERSIONS, version);
}

/**
 * Calcula los problemas activos de una configuración.
 *
 * @param {Settings} settings - Versión elegida y problemas personalizados.
 * @returns {ReadonlySet<string>} Identificadores de los problemas activos.
 */
export function activeProblems(settings) {
  if (settings.version === CUSTOM) {
    return new Set(settings.custom.filter((key) => ALL.includes(key)));
  }
  return new Set(VERSIONS[settings.version] ?? []);
}

/**
 * Convierte números de catálogo (`"1,4"`) en identificadores de problemas.
 *
 * @param {string} text - Números separados por comas.
 * @returns {string[]|null} Identificadores en orden de catálogo, o `null` si
 *   algún número no existe.
 */
export function problemsFromNumbers(text) {
  const numbers = String(text)
    .split(',')
    .map((part) => part.trim())
    .filter(Boolean)
    .map(Number);
  const keys = [];
  for (const number of numbers) {
    const problem = PROBLEMS.find((item) => item.number === number);
    if (!problem) return null;
    keys.push(problem.key);
  }
  return ALL.filter((key) => keys.includes(key));
}
