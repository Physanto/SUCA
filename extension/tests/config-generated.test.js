/**
 * @file Pruebas de config.generated.js: define UX.config y UX.contracts sobre
 * globalThis, congelados y sin pisar lo que ya exista en UX.
 */

const test = require('node:test');
const assert = require('node:assert/strict');

// El archivo generado se carga en un espacio UX que ya tiene contenido, como
// ocurre cuando otro script común se cargó antes.
globalThis.UX = { previous: true };
require('../config.generated.js');

const { UX } = globalThis;

/**
 * Indica si un objeto y todos los objetos que contiene están congelados.
 *
 * @param {object} value - Objeto a revisar.
 * @returns {boolean} Verdadero si todo está congelado.
 */
function isDeepFrozen(value) {
  return (
    Object.isFrozen(value) &&
    Object.values(value).every(
      (child) => child === null || typeof child !== 'object' || isDeepFrozen(child),
    )
  );
}

test('keeps existing members of the UX namespace', () => {
  assert.equal(UX.previous, true);
});

test('exposes only the configuration sections the extension needs', () => {
  assert.deepEqual(Object.keys(UX.config).sort(), ['camera', 'capture', 'sending', 'server']);
});

test('exposes contract version and enums', () => {
  assert.match(UX.contracts.version, /^\d+\.\d+\.\d+$/);
  assert.ok(UX.contracts.enums.batch_type.includes('events'));
  assert.ok(UX.contracts.enums.message_type.includes('session.started'));
});

test('configuration and contracts are deeply frozen', () => {
  assert.ok(isDeepFrozen(UX.config));
  assert.ok(isDeepFrozen(UX.contracts));
});
