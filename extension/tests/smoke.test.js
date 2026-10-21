/**
 * @file Prueba de humo: confirma que el ejecutor de pruebas de Node funciona.
 */

const test = require('node:test');
const assert = require('node:assert/strict');

test('node test runner executes tests', () => {
  assert.equal(1 + 1, 2);
});
