/**
 * @file Pruebas de la comprobación de WebGL del motor de la cámara.
 */

const test = require('node:test');
const assert = require('node:assert/strict');

require('../camera/webgl.js');

const { UX } = globalThis;

/**
 * Lienzo falso que solo crea los contextos indicados.
 *
 * @param {string[]} available - Tipos de contexto que se pueden crear.
 * @returns {{createCanvas: function(): object, asked: string[], lost: string[]}}
 */
function fakeCanvases(available) {
  const asked = [];
  const lost = [];
  const createCanvas = () => ({
    getContext(type) {
      asked.push(type);
      if (!available.includes(type)) {
        return null;
      }
      return {
        getExtension: (name) => (name === 'WEBGL_lose_context' ? { loseContext: () => lost.push(type) } : null),
      };
    },
  });
  return { createCanvas, asked, lost };
}

test('reports WebGL as available with a WebGL 2 context and releases it', () => {
  const { createCanvas, asked, lost } = fakeCanvases(['webgl2', 'webgl']);

  assert.equal(UX.webglAvailable(createCanvas), true);
  assert.deepEqual(asked, ['webgl2']);
  assert.deepEqual(lost, ['webgl2']);
});

test('falls back to WebGL 1 when WebGL 2 is missing', () => {
  const { createCanvas, asked, lost } = fakeCanvases(['webgl']);

  assert.equal(UX.webglAvailable(createCanvas), true);
  assert.deepEqual(asked, ['webgl2', 'webgl']);
  assert.deepEqual(lost, ['webgl']);
});

test('reports WebGL as unavailable when no context can be created', () => {
  const { createCanvas, asked } = fakeCanvases([]);

  assert.equal(UX.webglAvailable(createCanvas), false);
  assert.deepEqual(asked, ['webgl2', 'webgl']);
});

test('treats a canvas that throws as unavailable', () => {
  const createCanvas = () => ({
    getContext() {
      throw new Error('GPU process unavailable');
    },
  });

  assert.equal(UX.webglAvailable(createCanvas), false);
});

test('accepts a context without the lose context extension', () => {
  const createCanvas = () => ({ getContext: () => ({ getExtension: () => null }) });

  assert.equal(UX.webglAvailable(createCanvas), true);
});
