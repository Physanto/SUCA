import assert from 'node:assert/strict';
import test from 'node:test';

import {
  loadSettings,
  saveSettings,
  settingsFromParams,
  SETTINGS_KEY,
  withoutSettingsParams,
} from '../public/js/settings.js';
import { activeProblems, PROBLEMS, problemsFromNumbers, VERSIONS } from '../public/js/versions.js';
import { memoryStorage } from './fakes.js';

const numbers = (keys) =>
  PROBLEMS.filter((problem) => keys.has(problem.key)).map((problem) => problem.number);

test('the catalog has the eight problems in order', () => {
  assert.deepEqual(
    PROBLEMS.map((problem) => problem.number),
    [1, 2, 3, 4, 5, 6, 7, 8],
  );
  assert.equal(new Set(PROBLEMS.map((problem) => problem.key)).size, 8);
});

test('V0 has no problems, V1 the first four and V2 all eight', () => {
  assert.deepEqual(numbers(activeProblems({ version: 'V0', custom: [] })), []);
  assert.deepEqual(numbers(activeProblems({ version: 'V1', custom: [] })), [1, 2, 3, 4]);
  assert.deepEqual(numbers(activeProblems({ version: 'V2', custom: [] })), [1, 2, 3, 4, 5, 6, 7, 8]);
  for (const key of VERSIONS.V1) assert.ok(VERSIONS.V2.includes(key));
});

test('the custom version turns on each problem separately', () => {
  for (const problem of PROBLEMS) {
    const active = activeProblems({ version: 'custom', custom: [problem.key] });
    assert.deepEqual([...active], [problem.key]);
  }
  assert.deepEqual([...activeProblems({ version: 'custom', custom: ['unknown'] })], []);
});

test('catalog numbers become problem keys in catalog order', () => {
  assert.deepEqual(problemsFromNumbers('4, 1'), ['button_like_image', 'form_clears_on_error']);
  assert.equal(problemsFromNumbers('1,9'), null);
});

test('settings are saved and loaded, and invalid ones fall back to V0', () => {
  const storage = memoryStorage();
  assert.deepEqual(loadSettings(storage), { version: 'V0', custom: [] });

  saveSettings(storage, { version: 'custom', custom: ['slow_login'] });
  assert.deepEqual(loadSettings(storage), { version: 'custom', custom: ['slow_login'] });

  storage.setItem(SETTINGS_KEY, '{ broken');
  assert.deepEqual(loadSettings(storage), { version: 'V0', custom: [] });
  storage.setItem(SETTINGS_KEY, JSON.stringify({ version: 'V9', custom: [] }));
  assert.deepEqual(loadSettings(storage), { version: 'V0', custom: [] });
});

test('the URL can choose a version or a list of problems', () => {
  const read = (query) => settingsFromParams(new URLSearchParams(query));

  assert.deepEqual(read(''), { settings: null, error: null });
  assert.deepEqual(read('version=v1'), { settings: { version: 'V1', custom: [] }, error: null });
  assert.deepEqual(read('problems=8'), {
    settings: { version: 'custom', custom: ['strict_search'] },
    error: null,
  });
  assert.equal(read('version=V7').settings, null);
  assert.match(read('version=V7').error, /unknown version/);
  assert.equal(read('version=custom').settings, null);
  assert.match(read('problems=0').error, /unknown problem/);
});

test('version parameters are removed from the address, keeping the rest', () => {
  const url = new URL('http://127.0.0.1:8767/search?q=audifonos&version=V2&problems=1#top');

  assert.equal(withoutSettingsParams(url), '/search?q=audifonos#top');
});
