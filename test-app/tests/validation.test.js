import assert from 'node:assert/strict';
import test from 'node:test';

import { TEST_CARD } from '../public/js/data.js';
import {
  parseExpiry,
  passesLuhn,
  validateAddress,
  validatePayment,
  validateShipping,
} from '../public/js/validation.js';

const NOW = new Date(2026, 9, 31);

const card = (changes = {}) => ({
  method: 'card',
  number: TEST_CARD.number,
  name: TEST_CARD.name,
  expiry: TEST_CARD.expiry,
  cvc: TEST_CARD.cvc,
  ...changes,
});

test('the test card shown on screen is valid', () => {
  assert.deepEqual(validatePayment(card(), NOW), {});
});

test('card numbers accept spaces and dashes and must pass the Luhn check', () => {
  assert.deepEqual(validatePayment(card({ number: '4111-1111-1111-1111' }), NOW), {});
  assert.ok(validatePayment(card({ number: '4111 1111 1111 1112' }), NOW).number);
  assert.ok(validatePayment(card({ number: '4111' }), NOW).number);
  assert.equal(passesLuhn(''), false);
});

test('expiry dates accept common formats and reject expired cards', () => {
  assert.deepEqual(parseExpiry('12/29'), { month: 12, year: 2029 });
  assert.deepEqual(parseExpiry('1229'), { month: 12, year: 2029 });
  assert.deepEqual(parseExpiry('12/2029'), { month: 12, year: 2029 });
  assert.equal(parseExpiry('13/29'), null);
  assert.match(validatePayment(card({ expiry: '09/26' }), NOW).expiry, /vencida/);
  assert.deepEqual(validatePayment(card({ expiry: '10/26' }), NOW), {});
  assert.match(validatePayment(card({ expiry: 'diciembre' }), NOW).expiry, /MM\/AA/);
});

test('every invalid card field gets its own message', () => {
  const errors = validatePayment(card({ number: '', name: ' ', expiry: '', cvc: '12' }), NOW);

  assert.deepEqual(Object.keys(errors).sort(), ['cvc', 'expiry', 'name', 'number']);
});

test('bank transfer only needs a bank, and a method is required', () => {
  assert.deepEqual(validatePayment({ method: 'pse', bank: 'Banco Andino' }, NOW), {});
  assert.ok(validatePayment({ method: 'pse', bank: '' }, NOW).bank);
  assert.ok(validatePayment({ method: '' }, NOW).method);
});

test('shipping requires name, address, a known city and a 10 digit phone', () => {
  const valid = { name: 'Ana', street: 'Calle 10 # 20-30', city: 'Bogotá', phone: '300 123 4567' };

  assert.deepEqual(validateShipping(valid), {});
  const errors = validateShipping({ name: '', street: 'Cl', city: 'Lima', phone: '123' });
  assert.deepEqual(Object.keys(errors).sort(), ['city', 'name', 'phone', 'street']);
});

test('the account address requires a street and a known city', () => {
  assert.deepEqual(validateAddress({ street: 'Calle 10 # 20-30', city: 'Bogotá' }), {});
  assert.deepEqual(Object.keys(validateAddress({ street: '', city: '' })).sort(), ['city', 'street']);
});
