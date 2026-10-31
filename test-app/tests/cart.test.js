import assert from 'node:assert/strict';
import test from 'node:test';

import { addItem, cartLines, countUnits, removeItem, setQuantity, totals } from '../public/js/cart.js';
import { findProduct, FREE_SHIPPING_FROM, MAX_QUANTITY, SHIPPING_COST } from '../public/js/data.js';

test('adding a product twice adds up its units without changing the original cart', () => {
  const empty = [];
  const once = addItem(empty, 101, 1);
  const twice = addItem(once, 101, 1);

  assert.deepEqual(empty, []);
  assert.deepEqual(twice, [{ productId: 101, quantity: 2 }]);
  assert.equal(countUnits(twice), 2);
});

test('quantities stay between 1 and the maximum', () => {
  const cart = addItem([], 101, 50);

  assert.equal(cart[0].quantity, MAX_QUANTITY);
  assert.equal(setQuantity(cart, 101, 0)[0].quantity, 1);
  assert.equal(setQuantity(cart, 101, Number.NaN)[0].quantity, 1);
});

test('removing a product leaves the others', () => {
  const cart = addItem(addItem([], 101, 1), 204, 1);

  assert.deepEqual(removeItem(cart, 101), [{ productId: 204, quantity: 1 }]);
});

test('lines skip products that no longer exist', () => {
  const lines = cartLines([{ productId: 101, quantity: 2 }, { productId: 999, quantity: 1 }], findProduct);

  assert.equal(lines.length, 1);
  assert.equal(lines[0].subtotal, findProduct(101).price * 2);
});

test('shipping is charged below the free shipping amount and free from it', () => {
  assert.deepEqual(totals([]), { subtotal: 0, shipping: 0, total: 0 });
  assert.deepEqual(totals([{ subtotal: 50000 }]), {
    subtotal: 50000,
    shipping: SHIPPING_COST,
    total: 50000 + SHIPPING_COST,
  });
  assert.equal(totals([{ subtotal: FREE_SHIPPING_FROM }]).shipping, 0);
});
