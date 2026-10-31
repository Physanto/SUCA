import assert from 'node:assert/strict';
import test from 'node:test';

import { PRODUCTS } from '../public/js/data.js';
import { reviewsFor } from '../public/js/reviews.js';

test('each product always shows the same three different reviews', () => {
  for (const product of PRODUCTS) {
    const reviews = reviewsFor(product);
    assert.equal(reviews.length, 3);
    assert.equal(new Set(reviews.map((review) => review.author)).size, 3);
    assert.deepEqual(reviewsFor(product), reviews);
  }
});
