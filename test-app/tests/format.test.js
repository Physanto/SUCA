import assert from 'node:assert/strict';
import test from 'node:test';

import { money, normalizeText, productCount } from '../public/js/format.js';

test('prices are written as Colombian pesos with a plain space', () => {
  assert.equal(money(179900), '$ 179.900');
  assert.equal(money(2899000), '$ 2.899.000');
});

test('product counts agree in number', () => {
  assert.equal(productCount(1), '1 producto');
  assert.equal(productCount(2), '2 productos');
});

test('text is normalized without accents, case or punctuation', () => {
  assert.equal(normalizeText('  Audífonos, ¡INALÁMBRICOS!  '), 'audifonos inalambricos');
});
