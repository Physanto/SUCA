/** @file Comprueba el guion y sus ventanas de verdad sin reloj ni navegador. */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { stepAt, truthWindow } = require('../test-page/attention.js');
const script = require('../test-page/attention-script.json');

test('the script covers content, small links, empty space and the keyboard', () => {
  assert.equal(script.targets.length, 20);
  assert.equal(script.step_ms, 3000);
  assert.equal(script.settle_ms, 500);
  const html = readFileSync(`${__dirname}/../test-page/attention.html`, 'utf8');
  for (const target of script.targets) {
    if (target.kind === 'element') assert.ok(html.includes(`id="${target.selector.slice(1)}"`));
    else assert.equal(target.selector, null);
  }
  for (const kind of ['element', 'empty', 'keyboard']) {
    assert.ok(script.targets.some(target => target.kind === kind));
  }
});

test('the clock uses absolute steps and discards the first 500 milliseconds', () => {
  assert.equal(stepAt(script, -1), -1);
  for (let k = 0; k < script.targets.length; k += 1) {
    assert.equal(stepAt(script, k * 3000), k);
    assert.equal(stepAt(script, (k + 1) * 3000 - 1), k);
    assert.deepEqual(truthWindow(script, k), [k * 3000 + 500, (k + 1) * 3000]);
  }
  assert.equal(stepAt(script, 60000), -1);
  assert.equal(stepAt(script, 60001), -1);
});
