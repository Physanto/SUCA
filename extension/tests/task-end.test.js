/**
 * @file Pruebas de `content/task-end.js`: la revisión de la condición final
 * (`visible_text`, `url_pattern`, `element_present`), el límite de revisiones,
 * la condición guardada entre páginas y la limpieza de `stop()`. El DOM es un
 * sustituto mínimo en memoria.
 */

const test = require('node:test');
const assert = require('node:assert/strict');

const { createFakeTimers, createFakeWorld, settle } = require('./fakes.js');

const STORAGE_KEY = 'task_end';
const TYPES = { TASK_STARTED: 'task.started', TASK_COMPLETED: 'task.completed' };
const VISIBLE_TEXT = { type: 'visible_text', text: 'Pedido confirmado' };
const URL_PATTERN = { type: 'url_pattern', pattern: '/order/{id}/confirmation' };
const ELEMENT = { type: 'element_present', text: 'Seguir comprando', role: 'button' };

let registered = null;
globalThis.UX = { modules: { register: (module) => (registered = module) } };
require('../content/task-end.js');
const taskEnd = registered;

/** Elemento falso con lo que usa el módulo: etiqueta, atributos, texto y visibilidad. */
function el(tag, attributes = {}, text = '', { hidden = false, textContent = text } = {}) {
  return {
    tagName: tag.toUpperCase(),
    getAttribute: (name) => (name in attributes ? attributes[name] : null),
    hasAttribute: (name) => name in attributes,
    innerText: text,
    textContent,
    checkVisibility: () => !hidden,
  };
}

/** ¿El elemento cumple una parte simple del selector que arma el módulo? */
function matchesPart(element, part) {
  const role = /^\[role="(.+)"\]$/.exec(part);
  if (role) {
    return element.getAttribute('role') === role[1];
  }
  const input = /^input\[type="(.+)"\]$/.exec(part);
  if (input) {
    return element.tagName === 'INPUT' && element.getAttribute('type') === input[1];
  }
  if (part === 'a[href]') {
    return element.tagName === 'A' && element.hasAttribute('href');
  }
  return element.tagName === part.toUpperCase();
}

class FakeMutationObserver {
  constructor(callback) {
    this.callback = callback;
    this.observing = false;
    FakeMutationObserver.instances.push(this);
  }

  observe() {
    this.observing = true;
  }

  disconnect() {
    this.observing = false;
  }
}
FakeMutationObserver.instances = [];

/**
 * Prepara una página, un contexto y el módulo iniciado. `page` es el estado
 * que la prueba cambia: texto visible, ruta y elementos.
 */
async function setup({ session = { session_id: 5, task_id: null }, saved } = {}) {
  const real = { setTimeout: globalThis.setTimeout, clearTimeout: globalThis.clearTimeout };
  const timers = createFakeTimers();
  const world = createFakeWorld();
  const platform = world.platform();
  const page = { text: '', path: '/cart', elements: [], reads: 0 };
  const sent = [];
  const handlers = new Map();
  const sessionListeners = new Set();
  const pageListeners = new Map();
  let current = session;

  FakeMutationObserver.instances = [];
  globalThis.MutationObserver = FakeMutationObserver;
  globalThis.location = {
    get href() {
      return `https://shop.local${page.path}`;
    },
  };
  globalThis.addEventListener = (type, listener) => pageListeners.set(type, listener);
  globalThis.removeEventListener = (type, listener) => {
    if (pageListeners.get(type) === listener) {
      pageListeners.delete(type);
    }
  };
  globalThis.document = {
    body: {
      get innerText() {
        page.reads += 1;
        return page.text;
      },
    },
    querySelectorAll: (selector) =>
      page.elements.filter((element) => selector.split(',').some((part) => matchesPart(element, part))),
  };
  globalThis.UX.platform = platform;
  if (saved !== undefined) {
    world.areas.session.set(STORAGE_KEY, saved);
  }

  const ctx = {
    clock: { now: timers.now },
    messages: {
      types: TYPES,
      on(type, handler) {
        handlers.set(type, handler);
        return () => handlers.delete(type);
      },
      async send(type, payload) {
        sent.push({ type, payload });
      },
    },
    session: {
      get: () => current,
      subscribe(listener) {
        sessionListeners.add(listener);
        return () => sessionListeners.delete(listener);
      },
    },
  };

  // Los temporizadores falsos solo valen mientras el módulo los toma al iniciar.
  globalThis.setTimeout = timers.setTimeout;
  globalThis.clearTimeout = timers.clearTimeout;
  try {
    taskEnd.start(ctx);
  } finally {
    globalThis.setTimeout = real.setTimeout;
    globalThis.clearTimeout = real.clearTimeout;
  }
  await settle();

  return {
    page,
    sent,
    timers,
    world,
    ctx,
    handlers,
    pageListeners,
    sessionListeners,
    observer: () => FakeMutationObserver.instances[0],
    /** La sesión pasa a esta tarea (como lo hace el panel) y llega `task.started`. */
    async startTask(taskId, endCondition) {
      current = { ...current, task_id: taskId };
      sessionListeners.forEach((listener) => listener(current));
      handlers.get(TYPES.TASK_STARTED)({ task_id: taskId, end_condition: endCondition });
      await timers.advance(0);
    },
    /** La sesión cambia de tarea o termina. */
    async setSession(next) {
      current = next;
      sessionListeners.forEach((listener) => listener(current));
      await settle();
    },
    /** La página cambia: el observador avisa y pasa el tiempo. */
    async mutate(ms = 300) {
      FakeMutationObserver.instances.forEach((instance) => instance.observing && instance.callback([]));
      await timers.advance(ms);
    },
    async finish() {
      taskEnd.stop();
      await settle();
    },
  };
}

/** Ejecuta una prueba con la página lista y la limpia al terminar. */
function withPage(name, body, options) {
  test(name, async () => {
    const env = await setup(options);
    try {
      await body(env);
    } finally {
      await env.finish();
    }
  });
}

withPage('visible_text completes when the text appears, without caring for case or spacing', async (env) => {
  await env.startTask(3, VISIBLE_TEXT);
  assert.deepEqual(env.sent, []);

  env.page.text = 'Gracias.\n  PEDIDO   confirmado  ';
  await env.mutate();

  assert.deepEqual(env.sent, [
    { type: 'task.completed', payload: { task_id: 3, ended_by: 'reference' } },
  ]);
});

withPage('visible_text that is already on the page completes right away', async (env) => {
  env.page.text = 'Pedido confirmado';

  await env.startTask(3, VISIBLE_TEXT);

  assert.equal(env.sent.length, 1);
});

withPage('url_pattern matches the whole path, with {id} for any segment', async (env) => {
  await env.startTask(3, URL_PATTERN);

  for (const path of [
    '/order/confirmation',
    '/order/1/2/confirmation',
    '/x/order/9/confirmation',
    '/order/1/confirmation-old',
  ]) {
    env.page.path = path;
    await env.mutate();
  }
  assert.deepEqual(env.sent, []);

  env.page.path = '/order/8841/confirmation/?utm=1#top';
  await env.mutate();
  assert.equal(env.sent.length, 1);
});

withPage('url_pattern takes the symbols of the pattern literally', async (env) => {
  await env.startTask(3, { type: 'url_pattern', pattern: '/a.b' });

  env.page.path = '/axb';
  await env.mutate();
  assert.deepEqual(env.sent, []);

  env.page.path = '/a.b';
  await env.mutate();
  assert.equal(env.sent.length, 1);
});

withPage('element_present needs the role and the text of the element', async (env) => {
  await env.startTask(3, ELEMENT);

  env.page.elements = [
    el('button', {}, 'Pagar'),
    el('a', { href: '/shop' }, 'Seguir comprando'),
    el('button', { role: 'link' }, 'Seguir comprando'),
    el('button', {}, 'Seguir comprando', { hidden: true }),
    el('div', {}, 'Seguir comprando'),
  ];
  await env.mutate();
  assert.deepEqual(env.sent, []);

  env.page.elements.push(el('button', {}, '  seguir   COMPRANDO '));
  await env.mutate();
  assert.equal(env.sent.length, 1);
});

withPage('element_present reads the text as the capture does, with innerText', async (env) => {
  await env.startTask(3, { type: 'element_present', text: 'Pagar ahora', role: 'link' });

  // Dos bloques dentro del enlace y una etiqueta oculta: `textContent` daría otro texto.
  env.page.elements = [
    el('a', { href: '/pay' }, 'Pagar\nahora', { textContent: 'PagarahoraNuevo' }),
  ];
  await env.mutate();

  assert.equal(env.sent.length, 1);
});

withPage('element_present accepts an explicit role and a text cut to 50 characters', async (env) => {
  const long = 'Ver el detalle completo del pedido y de todos sus artículos incluidos';
  await env.startTask(3, { type: 'element_present', text: long.slice(0, 50), role: 'tab' });

  env.page.elements = [el('div', { role: 'tab' }, long)];
  await env.mutate();

  assert.equal(env.sent.length, 1);
});

withPage('a task without a final condition watches nothing', async (env) => {
  await env.startTask(3, null);

  assert.equal(env.observer(), undefined);
  assert.equal(env.pageListeners.size, 0);
  assert.equal(env.timers.pending(), 0);
  assert.deepEqual(env.sent, []);
});

withPage('checks at most 4 times per second and still sees the last change', async (env) => {
  await env.startTask(3, VISIBLE_TEXT);
  const readsAfterStart = env.page.reads;

  // 40 cambios en un segundo.
  for (let i = 0; i < 40; i += 1) {
    await env.mutate(25);
  }
  assert.ok(env.page.reads - readsAfterStart <= 4, `reads: ${env.page.reads - readsAfterStart}`);

  env.page.text = 'Pedido confirmado';
  await env.mutate(0);
  assert.equal(env.sent.length, 0);
  await env.timers.advance(250);
  assert.equal(env.sent.length, 1);
});

withPage('popstate and hashchange check the path without any change in the page', async (env) => {
  await env.startTask(3, URL_PATTERN);
  env.page.path = '/order/7/confirmation';

  env.pageListeners.get('popstate')();
  await env.timers.advance(300);

  assert.equal(env.sent.length, 1);
});

withPage('sends task.completed only once and then stops watching', async (env) => {
  env.page.text = 'Pedido confirmado';
  await env.startTask(3, VISIBLE_TEXT);

  await env.mutate();
  await env.mutate();

  assert.equal(env.sent.length, 1);
  assert.equal(env.observer().observing, false);
  assert.equal(env.pageListeners.size, 0);
  assert.equal(env.world.areas.session.get(STORAGE_KEY), undefined);
});

withPage('stops watching when the active task changes or the session ends', async (env) => {
  await env.startTask(3, VISIBLE_TEXT);
  await env.setSession({ session_id: 5, task_id: null });

  env.page.text = 'Pedido confirmado';
  await env.mutate();

  assert.deepEqual(env.sent, []);
  assert.equal(env.observer().observing, false);
  assert.equal(env.world.areas.session.get(STORAGE_KEY), undefined);
});

withPage('a new task replaces the condition of the previous one', async (env) => {
  await env.startTask(3, VISIBLE_TEXT);
  await env.startTask(4, URL_PATTERN);

  env.page.text = 'Pedido confirmado';
  await env.mutate();
  assert.deepEqual(env.sent, []);

  env.page.path = '/order/1/confirmation';
  await env.mutate();
  assert.deepEqual(env.sent, [{ type: 'task.completed', payload: { task_id: 4, ended_by: 'reference' } }]);
});

withPage('saves the condition while the task runs, for the pages that load later', async (env) => {
  await env.startTask(3, VISIBLE_TEXT);

  assert.deepEqual(env.world.areas.session.get(STORAGE_KEY), { task_id: 3, end_condition: VISIBLE_TEXT });
});

withPage(
  'a page that loads in the middle of the task resumes its saved condition',
  async (env) => {
    assert.notEqual(env.observer(), undefined);
    env.page.path = '/order/2/confirmation';

    await env.mutate();

    assert.deepEqual(env.sent, [{ type: 'task.completed', payload: { task_id: 3, ended_by: 'reference' } }]);
  },
  { session: { session_id: 5, task_id: 3 }, saved: { task_id: 3, end_condition: URL_PATTERN } },
);

withPage(
  'discards a saved condition that belongs to another task',
  async (env) => {
    assert.equal(env.observer(), undefined);
    assert.equal(env.world.areas.session.get(STORAGE_KEY), undefined);
  },
  { session: { session_id: 5, task_id: 4 }, saved: { task_id: 3, end_condition: URL_PATTERN } },
);

withPage('stop removes every listener, observer, timer and the saved condition', async (env) => {
  await env.startTask(3, VISIBLE_TEXT);
  assert.equal(env.observer().observing, true);
  assert.deepEqual([...env.pageListeners.keys()].sort(), ['hashchange', 'popstate']);
  await env.mutate(0);
  assert.equal(env.timers.pending(), 1);

  taskEnd.stop();
  await settle();

  assert.equal(env.observer().observing, false);
  assert.equal(env.pageListeners.size, 0);
  assert.equal(env.timers.pending(), 0);
  assert.equal(env.handlers.size, 0);
  assert.equal(env.sessionListeners.size, 0);
  assert.equal(env.world.areas.session.get(STORAGE_KEY), undefined);

  env.page.text = 'Pedido confirmado';
  await env.timers.advance(1000);
  assert.deepEqual(env.sent, []);
});

withPage('a failing task.completed does not break the page', async (env) => {
  const errors = [];
  const realError = console.error;
  console.error = (...args) => errors.push(args);
  env.ctx.messages.send = async () => {
    throw new Error('no receiver');
  };
  env.page.text = 'Pedido confirmado';
  try {
    await env.startTask(3, VISIBLE_TEXT);
    await settle();
  } finally {
    console.error = realError;
  }

  assert.equal(errors.length, 1);
});
