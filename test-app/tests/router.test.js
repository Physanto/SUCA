import assert from 'node:assert/strict';
import test from 'node:test';

import { compileRoutes, isAppLink, matchRoute } from '../public/js/router.js';

const routes = compileRoutes([
  { path: '/', name: 'home' },
  { path: '/product/:id', name: 'product' },
  { path: '/order/:id/confirmation', name: 'confirmation' },
  { path: '/account', name: 'account' },
]);

test('routes match with their parameters, with or without a final slash', () => {
  assert.equal(matchRoute(routes, '/').route.name, 'home');
  assert.deepEqual(matchRoute(routes, '/product/101').params, { id: '101' });
  assert.deepEqual(matchRoute(routes, '/order/5012/confirmation/').params, { id: '5012' });
  assert.equal(matchRoute(routes, '/account/').route.name, 'account');
});

test('unknown routes do not match', () => {
  assert.equal(matchRoute(routes, '/product'), null);
  assert.equal(matchRoute(routes, '/product/101/extra'), null);
  assert.equal(matchRoute(routes, '/nothing'), null);
});

const location = { origin: 'http://127.0.0.1:8767', pathname: '/product/101', search: '' };
const click = (changes = {}) => ({ defaultPrevented: false, button: 0, ...changes });
const link = (href, attrs = {}) => {
  const url = new URL(href, location.origin);
  return {
    origin: url.origin,
    pathname: url.pathname,
    search: url.search,
    hash: url.hash,
    target: attrs.target ?? '',
    hasAttribute: (name) => name in attrs,
  };
};

test('internal links are handled by the app', () => {
  assert.equal(isAppLink(click(), link('/cart'), location), true);
  assert.equal(isAppLink(click(), link('/account#pedidos'), location), true);
});

test('the browser keeps links it should handle itself', () => {
  assert.equal(isAppLink(click({ ctrlKey: true }), link('/cart'), location), false);
  assert.equal(isAppLink(click({ button: 1 }), link('/cart'), location), false);
  assert.equal(isAppLink(click({ defaultPrevented: true }), link('/cart'), location), false);
  assert.equal(isAppLink(click(), link('/cart', { target: '_blank' }), location), false);
  assert.equal(isAppLink(click(), link('/terms.html'), location), false);
  assert.equal(isAppLink(click(), link('https://example.com/'), location), false);
  assert.equal(isAppLink(click(), link('/product/101#resenas'), location), false);
});
