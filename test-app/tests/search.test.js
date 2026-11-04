import assert from 'node:assert/strict';
import test from 'node:test';

import { FEATURED_PRODUCTS, PRODUCTS } from '../public/js/data.js';
import { editDistance, searchProducts } from '../public/js/search.js';

const ids = (products) => products.map((product) => product.id);

test('finds the wireless headphones first, ignoring case and accents', () => {
  const found = searchProducts(PRODUCTS, 'AUDIFONOS inalambricos');

  assert.equal(found[0].id, 101);
  assert.deepEqual(ids(found).slice(0, 3), [101, 102, 103]);
});

test('the home page features none of the products task 1 searches for', () => {
  // Un destacado sería un atajo a la tarea 1 sin pasar por la búsqueda.
  const found = ids(searchProducts(PRODUCTS, 'audifonos inalambricos'));

  assert.deepEqual(FEATURED_PRODUCTS.filter((id) => found.includes(id)), []);
  assert.ok(FEATURED_PRODUCTS.every((id) => PRODUCTS.some((product) => product.id === id)));
});

test('tolerates small typos by default', () => {
  assert.equal(searchProducts(PRODUCTS, 'audfonos inalambricos')[0].id, 101);
  assert.equal(searchProducts(PRODUCTS, 'audifonos inlambricos')[0].id, 101);
  assert.equal(searchProducts(PRODUCTS, 'audiofnos')[0].category, 'audio');
});

test('matches word prefixes, categories and keywords', () => {
  assert.ok(ids(searchProducts(PRODUCTS, 'parla')).includes(104));
  assert.ok(ids(searchProducts(PRODUCTS, 'smartwatch')).includes(305));
  assert.deepEqual(
    ids(searchProducts(PRODUCTS, 'hogar')).sort(),
    [401, 402, 403, 404, 405, 406],
  );
});

test('requires every word of the query', () => {
  assert.deepEqual(ids(searchProducts(PRODUCTS, 'audifonos portatil')), []);
});

test('strict mode needs complete, correctly spelled words', () => {
  assert.deepEqual(ids(searchProducts(PRODUCTS, 'audfonos', { tolerant: false })), []);
  assert.deepEqual(ids(searchProducts(PRODUCTS, 'audi', { tolerant: false })), []);
  assert.equal(searchProducts(PRODUCTS, 'Audífonos inalámbricos', { tolerant: false })[0].id, 101);
});

test('an empty query finds nothing', () => {
  assert.deepEqual(searchProducts(PRODUCTS, '  '), []);
});

test('edit distance counts a transposition as one edit', () => {
  assert.equal(editDistance('audifonos', 'audifonos'), 0);
  assert.equal(editDistance('audfionos', 'audifonos'), 1);
  assert.equal(editDistance('audfonos', 'audifonos'), 1);
  assert.equal(editDistance('', 'abc'), 3);
});
