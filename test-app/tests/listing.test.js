import assert from 'node:assert/strict';
import test from 'node:test';

import { PRODUCTS } from '../public/js/data.js';
import { arrange, listingOptions, PAGE_SIZE, withListingOptions } from '../public/js/listing.js';

const ids = (products) => products.map((product) => product.id);

test('relevance keeps the arrival order without touching the input', () => {
  const input = PRODUCTS.slice(0, 5);
  const copy = [...input];

  assert.deepEqual(ids(arrange(input, { sort: 'relevance', discountOnly: false })), ids(copy));
  assert.deepEqual(input, copy);
});

test('sorts by price and rating, keeping ties in arrival order', () => {
  const byPrice = arrange(PRODUCTS, { sort: 'price_asc', discountOnly: false });
  const byPriceDesc = arrange(PRODUCTS, { sort: 'price_desc', discountOnly: false });
  const byRating = arrange(PRODUCTS, { sort: 'rating', discountOnly: false });

  for (let i = 1; i < byPrice.length; i += 1) assert.ok(byPrice[i - 1].price <= byPrice[i].price);
  for (let i = 1; i < byPriceDesc.length; i += 1) {
    assert.ok(byPriceDesc[i - 1].price >= byPriceDesc[i].price);
  }

  const tied = byRating.filter((product) => product.rating === 4.5).map((product) => product.id);
  assert.deepEqual(tied, ids(PRODUCTS.filter((product) => product.rating === 4.5)));
});

test('the discount filter keeps only products with a list price', () => {
  const found = arrange(PRODUCTS, { sort: 'relevance', discountOnly: true });

  assert.ok(found.length > 0);
  assert.ok(found.every((product) => product.listPrice));
});

test('options come from the query and unknown values fall back to the defaults', () => {
  assert.deepEqual(listingOptions(new URLSearchParams('sort=price_asc&discount=1')), {
    sort: 'price_asc',
    discountOnly: true,
  });
  assert.deepEqual(listingOptions(new URLSearchParams('sort=cheapest&discount=yes')), {
    sort: 'relevance',
    discountOnly: false,
  });
});

test('options are written to the query keeping the search text, and defaults are omitted', () => {
  const query = new URLSearchParams('q=audifonos&sort=rating&discount=1');

  assert.equal(withListingOptions(query, { sort: 'price_desc', discountOnly: true }).toString(), 'q=audifonos&sort=price_desc&discount=1');
  assert.equal(withListingOptions(query, { sort: 'relevance', discountOnly: false }).toString(), 'q=audifonos');
  assert.equal(query.toString(), 'q=audifonos&sort=rating&discount=1');
});

test('the full catalog needs more than one page', () => {
  assert.ok(PRODUCTS.length > PAGE_SIZE);
});
