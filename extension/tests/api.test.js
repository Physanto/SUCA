/**
 * @file Pruebas del cliente del servidor: rutas, token y clasificación de errores.
 */

const test = require('node:test');
const assert = require('node:assert/strict');

require('../common/api.js');

const { UX } = globalThis;
const SERVER = { host: '127.0.0.1', port: 8765, token: 'secret' };

/** Crea un cliente cuyo `fetch` responde con `status` y `body`, y guarda las peticiones. */
function setup(status = 200, body = {}) {
  const requests = [];
  const api = UX.createApi({
    server: SERVER,
    fetch: async (url, init) => {
      requests.push({ url, ...init });
      return { ok: status < 400, status, statusText: 'status', json: async () => body };
    },
  });
  return { api, requests };
}

test('sends the token and a JSON body to the configured server', async () => {
  const { api, requests } = setup(200, { stored: 1 });

  const answer = await api.sendBatch(7, { type: 'events' });

  assert.deepEqual(answer, { stored: 1 });
  assert.equal(requests[0].url, 'http://127.0.0.1:8765/sessions/7/batches');
  assert.equal(requests[0].method, 'POST');
  assert.equal(requests[0].headers['X-Api-Token'], 'secret');
  assert.equal(requests[0].headers['Content-Type'], 'application/json');
  assert.equal(requests[0].body, '{"type":"events"}');
});

test('requests without a body send no content type', async () => {
  const { api, requests } = setup();

  await api.closeSession(7);

  assert.equal(requests[0].url, 'http://127.0.0.1:8765/sessions/7/close');
  assert.equal(requests[0].headers['Content-Type'], undefined);
  assert.equal(requests[0].body, undefined);
});

test('client errors are permanent and carry the server details', async () => {
  const errors = [{ record: 3, field: 'x', message: "'x' is a required property" }];
  const { api } = setup(422, { detail: 'batch does not match its contract', errors });

  await assert.rejects(api.sendBatch(7, {}), (error) => {
    assert.equal(error.name, 'ApiError');
    assert.equal(error.status, 422);
    assert.equal(error.permanent, true);
    assert.deepEqual(error.errors, errors);
    assert.match(error.message, /422: batch does not match its contract/);
    return true;
  });
});

test('server errors, timeouts and rate limits can be retried', async () => {
  for (const status of [500, 503, 408, 429]) {
    const { api } = setup(status, { detail: 'later' });

    await assert.rejects(api.health(), (error) => error.permanent === false);
  }
});

test('an unreachable server is a transient error with status 0', async () => {
  const api = UX.createApi({
    server: SERVER,
    fetch: async () => {
      throw new TypeError('Failed to fetch');
    },
  });

  await assert.rejects(api.health(), (error) => {
    assert.equal(error.status, 0);
    assert.equal(error.permanent, false);
    assert.match(error.message, /server unreachable: Failed to fetch/);
    return true;
  });
});
