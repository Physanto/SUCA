/**
 * @file Búsqueda de productos por nombre, categoría y palabras clave.
 *
 * Por defecto tolera mayúsculas, tildes, prefijos y errores de escritura
 * pequeños, como un buscador bien hecho. El modo estricto exige las palabras
 * completas y bien escritas (lo usa un problema sembrado).
 */

import { CATEGORIES } from './data.js';
import { normalizeText } from './format.js';

/** Puntos de cada tipo de coincidencia, de mejor a peor. */
const SCORE = Object.freeze({ exact: 3, prefix: 2, typo: 1 });

/** Letras mínimas de una palabra para aceptarla como prefijo. */
const MIN_PREFIX = 3;

/**
 * Distancia de edición entre dos palabras, contando una transposición de dos
 * letras vecinas como un solo error (distancia de Damerau-Levenshtein
 * restringida).
 *
 * @param {string} a - Primera palabra.
 * @param {string} b - Segunda palabra.
 * @returns {number} Número mínimo de ediciones.
 */
export function editDistance(a, b) {
  const rows = a.length + 1;
  const cols = b.length + 1;
  const d = Array.from({ length: rows }, (_, i) => [i, ...Array(cols - 1).fill(0)]);
  for (let j = 0; j < cols; j += 1) d[0][j] = j;
  for (let i = 1; i < rows; i += 1) {
    for (let j = 1; j < cols; j += 1) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost);
      if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) {
        d[i][j] = Math.min(d[i][j], d[i - 2][j - 2] + 1);
      }
    }
  }
  return d[rows - 1][cols - 1];
}

/**
 * Errores de escritura que se toleran según el largo de la palabra buscada.
 *
 * @param {string} word - Palabra buscada.
 * @returns {number} 0 hasta 3 letras, 1 hasta 6 y 2 desde 7.
 */
function allowedTypos(word) {
  if (word.length <= 3) return 0;
  return word.length <= 6 ? 1 : 2;
}

/**
 * Puntos de la mejor coincidencia de una palabra buscada con las de un producto.
 *
 * @param {string} word - Palabra buscada, normalizada.
 * @param {string[]} words - Palabras del producto, normalizadas.
 * @param {boolean} tolerant - Si se aceptan prefijos y errores de escritura.
 * @returns {number} Puntos (0 si no coincide).
 */
function wordScore(word, words, tolerant) {
  let best = 0;
  for (const candidate of words) {
    if (candidate === word) return SCORE.exact;
    if (!tolerant) continue;
    if (word.length >= MIN_PREFIX && candidate.startsWith(word)) {
      best = Math.max(best, SCORE.prefix);
    } else if (editDistance(word, candidate) <= allowedTypos(word)) {
      best = Math.max(best, SCORE.typo);
    }
  }
  return best;
}

/**
 * Palabras con las que se puede encontrar un producto.
 *
 * @param {import('./data.js').Product} product - Producto.
 * @returns {string[]} Palabras normalizadas de su nombre, categoría y claves.
 */
function productWords(product) {
  const category = CATEGORIES.find((item) => item.slug === product.category);
  const text = [product.name, category ? category.name : '', ...product.keywords].join(' ');
  return normalizeText(text).split(' ').filter(Boolean);
}

/**
 * Busca productos que contengan todas las palabras de la consulta.
 *
 * @param {ReadonlyArray<import('./data.js').Product>} products - Catálogo.
 * @param {string} query - Texto que escribió la persona.
 * @param {{ tolerant?: boolean }} [options] - `tolerant: false` exige palabras
 *   completas y bien escritas (sí ignora mayúsculas y tildes).
 * @returns {import('./data.js').Product[]} Productos encontrados, del más al
 *   menos parecido; a igual parecido, en el orden del catálogo.
 */
export function searchProducts(products, query, { tolerant = true } = {}) {
  const words = normalizeText(query).split(' ').filter(Boolean);
  if (words.length === 0) return [];
  const found = [];
  products.forEach((product, position) => {
    const candidates = productWords(product);
    let score = 0;
    for (const word of words) {
      const points = wordScore(word, candidates, tolerant);
      if (points === 0) return;
      score += points;
    }
    found.push({ product, score, position });
  });
  found.sort((a, b) => b.score - a.score || a.position - b.position);
  return found.map((item) => item.product);
}
