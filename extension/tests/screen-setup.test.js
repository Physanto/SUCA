/**
 * @file Pruebas de `common/screen-setup.js`: densidad de la pantalla a partir de su
 * tamaño, revisión de los ajustes y combinación con la configuración.
 */

const test = require('node:test');
const assert = require('node:assert/strict');

require('../common/screen-setup.js');

const { screenSetup } = globalThis.UX;

const CAMERA = Object.freeze({
  css_px_per_cm: 55.7,
  viewing_distance_cm: 60,
  min_distance_cm: 35,
  max_distance_cm: 75,
  blink_threshold: 0.45,
});

const SETUP = Object.freeze({
  css_px_per_cm: 36.22,
  viewing_distance_cm: 50,
  min_distance_cm: 35,
  max_distance_cm: 65,
});

test('the density comes from the visible width, the most exact measure', () => {
  assert.equal(screenSetup.cssPxPerCm({ width_cm: 53 }, { width: 1920, height: 1080 }), 36.23);
});

test('the density comes from the diagonal in inches when there is no width', () => {
  // 15,6″ a 1920 × 1080: 2203 px de diagonal en 39,6 cm.
  assert.equal(screenSetup.cssPxPerCm({ diagonal_in: 15.6 }, { width: 1920, height: 1080 }), 55.6);
  assert.equal(
    screenSetup.cssPxPerCm({ diagonal_in: 15.6, width_cm: 53 }, { width: 1920, height: 1080 }),
    36.23,
    'the width wins over the diagonal',
  );
});

test('the density needs a size and a screen', () => {
  assert.throws(() => screenSetup.cssPxPerCm({}, { width: 1920, height: 1080 }), /diagonal in inches or its width/);
  assert.throws(() => screenSetup.cssPxPerCm({ width_cm: 50 }, { width: 0, height: 0 }), /must be positive/);
});

test('settings out of range or with the distances out of order are refused', () => {
  assert.deepEqual(screenSetup.problems(SETUP), []);
  assert.equal(screenSetup.problems({ ...SETUP, css_px_per_cm: 5 }).length, 1);
  assert.equal(screenSetup.problems({ ...SETUP, viewing_distance_cm: '50' }).length, 1);
  assert.deepEqual(screenSetup.problems({ ...SETUP, viewing_distance_cm: 70 }), [
    'the distances must keep min <= usual <= max',
  ]);
});

test('the settings of this computer replace the screen and distances of the configuration', () => {
  const camera = screenSetup.apply(CAMERA, SETUP);

  assert.equal(camera.css_px_per_cm, 36.22);
  assert.equal(camera.viewing_distance_cm, 50);
  assert.equal(camera.max_distance_cm, 65);
  assert.equal(camera.blink_threshold, 0.45, 'the rest of the configuration stays');
  assert.equal(camera.screen_setup, 'local');
  assert.ok(Object.isFrozen(camera));
});

test('without valid settings the configuration is used as it is', () => {
  for (const setup of [null, undefined, { ...SETUP, min_distance_cm: 80 }]) {
    const camera = screenSetup.apply(CAMERA, setup);
    assert.equal(camera.css_px_per_cm, 55.7);
    assert.equal(camera.screen_setup, 'config');
  }
});

test('loading returns the stored settings, or null when there are none or storage fails', async () => {
  const stored = { get: async (key) => (key === screenSetup.STORAGE_KEY ? SETUP : undefined) };
  const empty = { get: async () => undefined };
  const broken = {
    get: async () => {
      throw new Error('no storage');
    },
  };

  assert.deepEqual(await screenSetup.load(stored), SETUP);
  assert.equal(await screenSetup.load(empty), null);
  assert.equal(await screenSetup.load(broken), null);
});
