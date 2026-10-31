import assert from 'node:assert/strict';
import test from 'node:test';

import { DEMO_ACCOUNT, FIRST_ORDER_ID, TEST_CARD } from '../public/js/data.js';
import { checkCredentials, createShop, STORE_KEY } from '../public/js/shop.js';
import { memoryStorage } from './fakes.js';

test('only the demo account can log in; the email ignores case and spaces', () => {
  assert.equal(checkCredentials(` ${DEMO_ACCOUNT.email.toUpperCase()} `, DEMO_ACCOUNT.password), true);
  assert.equal(checkCredentials(DEMO_ACCOUNT.email, DEMO_ACCOUNT.password.toLowerCase()), false);
  assert.equal(checkCredentials('otra@correo.test', DEMO_ACCOUNT.password), false);
});

test('the state survives a reload through the storage', () => {
  const storage = memoryStorage();
  const shop = createShop(storage);
  shop.login(DEMO_ACCOUNT.email, DEMO_ACCOUNT.password);
  shop.addToCart(101, 2);

  const reloaded = createShop(storage);

  assert.equal(reloaded.get().user.email, DEMO_ACCOUNT.email);
  assert.deepEqual(reloaded.get().cart, [{ productId: 101, quantity: 2 }]);
});

test('a corrupt saved state is discarded', () => {
  const storage = memoryStorage();
  storage.setItem(STORE_KEY, 'not json');

  assert.equal(createShop(storage).get().user, null);
});

test('placing an order empties the cart and numbers the orders', () => {
  const shop = createShop(memoryStorage(), { now: () => 1000 });
  shop.login(DEMO_ACCOUNT.email, DEMO_ACCOUNT.password);
  shop.addToCart(101, 2);
  shop.saveShipping({ name: 'Ana Gómez', street: 'Carrera 7 # 45-12', city: 'Medellín', phone: '3001234567', notes: '' });

  const first = shop.placeOrder({ method: 'card', label: `Tarjeta terminada en ${TEST_CARD.number.slice(-4)}` }, 359800);
  shop.addToCart(204, 1);
  shop.saveShipping({ ...first.shipping });
  const second = shop.placeOrder({ method: 'pse', label: 'PSE · Banco Andino' }, 289900);

  assert.equal(first.id, FIRST_ORDER_ID);
  assert.equal(second.id, FIRST_ORDER_ID + 1);
  assert.deepEqual(first.items, [{ productId: 101, quantity: 2 }]);
  assert.equal(first.placedAt, 1000);
  assert.deepEqual(shop.get().cart, []);
  assert.equal(shop.get().shipping, null);
  assert.deepEqual(shop.get().orders.map((order) => order.id), [second.id, first.id]);
});

test('subscribers hear every change until they unsubscribe', () => {
  const shop = createShop(memoryStorage());
  const seen = [];
  const unsubscribe = shop.subscribe((state) => seen.push(state.cart.length));

  shop.addToCart(101, 1);
  unsubscribe();
  shop.addToCart(102, 1);

  assert.deepEqual(seen, [1]);
});

test('reset returns to a fresh store for the next participant', () => {
  const shop = createShop(memoryStorage());
  shop.login(DEMO_ACCOUNT.email, DEMO_ACCOUNT.password);
  shop.addToCart(101, 1);
  shop.updateAddress({ street: 'Calle 10 # 20-30', city: 'Bogotá', details: '' });

  shop.reset();

  assert.equal(shop.get().user, null);
  assert.deepEqual(shop.get().cart, []);
  assert.deepEqual(shop.get().address, DEMO_ACCOUNT.address);
});

test('the edited name is kept after logging out and in again', () => {
  const shop = createShop(memoryStorage());
  shop.login(DEMO_ACCOUNT.email, DEMO_ACCOUNT.password);
  shop.updateProfile({ name: 'Ana María Gómez', phone: '310 000 0000' });

  shop.logout();
  shop.login(DEMO_ACCOUNT.email, DEMO_ACCOUNT.password);

  assert.equal(shop.get().user.name, 'Ana María Gómez');
  assert.equal(shop.get().phone, '310 000 0000');
});
