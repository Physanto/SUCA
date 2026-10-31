/**
 * @file Sustitutos para las pruebas de la app de prueba.
 */

/**
 * Almacenamiento en memoria con la interfaz de `localStorage`.
 *
 * @returns {Storage} Sustituto con `getItem`, `setItem`, `removeItem` y `clear`.
 */
export function memoryStorage() {
  const values = new Map();
  return {
    getItem: (key) => (values.has(key) ? values.get(key) : null),
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: (key) => values.delete(key),
    clear: () => values.clear(),
    get length() {
      return values.size;
    },
    key: (index) => [...values.keys()][index] ?? null,
  };
}
