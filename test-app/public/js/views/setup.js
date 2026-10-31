/**
 * @file Página del evaluador (`/setup`): elegir la versión de la tienda, o
 * los problemas uno por uno, y dejar la tienda lista para un participante.
 *
 * No tiene enlaces desde la tienda. Se abre antes de iniciar la sesión en la
 * extensión, para que no quede registrada.
 */

import { h } from '../dom.js';
import { saveSettings } from '../settings.js';
import { activeProblems, CUSTOM, PROBLEMS, VERSIONS } from '../versions.js';

/** Texto de cada opción de versión. */
const VERSION_LABELS = {
  V0: 'V0 · sin problemas',
  V1: 'V1 · problemas 1 a 4',
  V2: 'V2 · problemas 1 a 8',
  [CUSTOM]: 'Personalizada · elegir problemas',
};

/**
 * Describe una configuración en una línea.
 *
 * @param {import('../versions.js').Settings} settings - Configuración.
 * @returns {string} Por ejemplo, `V1 (problemas 1, 2, 3, 4)`.
 */
export function describeSettings(settings) {
  const active = activeProblems(settings);
  const numbers = PROBLEMS.filter((problem) => active.has(problem.key)).map((p) => p.number);
  const name = settings.version === CUSTOM ? 'Personalizada' : settings.version;
  return numbers.length === 0 ? `${name} (sin problemas)` : `${name} (problemas ${numbers.join(', ')})`;
}

/**
 * Dibuja la pantalla.
 *
 * @param {object} ctx - Contexto de la aplicación (usa `settings` y `storage`).
 * @returns {object} Título y contenido.
 */
export function render(ctx) {
  const current = ctx.settings;
  const versionInputs = Object.keys(VERSION_LABELS).map((version) =>
    h('input', {
      id: `version-${version}`,
      type: 'radio',
      name: 'version',
      value: version,
      checked: version === current.version,
    }),
  );
  const problemInputs = PROBLEMS.map((problem) =>
    h('input', { id: `problem-${problem.number}`, type: 'checkbox', name: 'problem', value: problem.key }),
  );

  /** Marca los problemas de la versión elegida; solo se editan en la personalizada. */
  const sync = () => {
    const version = versionInputs.find((input) => input.checked).value;
    const custom = version === CUSTOM;
    const active = custom ? null : new Set(VERSIONS[version]);
    for (const input of problemInputs) {
      input.disabled = !custom;
      if (!custom) input.checked = active.has(input.value);
    }
  };
  for (const input of problemInputs) {
    input.checked = activeProblems(current).has(input.value);
  }

  const form = h(
    'form',
    { class: 'form setup-form' },
    h(
      'fieldset',
      { class: 'fieldset' },
      h('legend', null, 'Versión'),
      versionInputs.map((input) =>
        h('div', { class: 'choice' }, input, h('label', { for: input.id }, VERSION_LABELS[input.value])),
      ),
    ),
    h(
      'fieldset',
      { class: 'fieldset' },
      h('legend', null, 'Problemas sembrados'),
      problemInputs.map((input, index) => {
        const problem = PROBLEMS[index];
        return h(
          'div',
          { class: 'choice' },
          input,
          h('label', { for: input.id }, `${problem.number}. ${problem.title} — ${problem.where}`),
        );
      }),
    ),
    h(
      'div',
      { class: 'form-actions' },
      h('button', { type: 'submit', class: 'button button-primary' }, 'Guardar y preparar para un participante'),
    ),
  );
  form.addEventListener('change', sync);
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    const version = versionInputs.find((input) => input.checked).value;
    const custom = problemInputs.filter((input) => input.checked).map((input) => input.value);
    saveSettings(ctx.storage, { version, custom: version === CUSTOM ? custom : [] });
    ctx.shop.reset();
    // Carga la página completa para que toda la tienda lea la versión nueva.
    window.location.assign('/login');
  });
  sync();

  return {
    title: 'Preparar la prueba',
    node: h(
      'section',
      { class: 'setup narrow', 'aria-labelledby': 'setup-title' },
      h('h1', { id: 'setup-title', tabindex: -1 }, 'Preparar la prueba'),
      h(
        'p',
        null,
        'Página del evaluador. Elige la versión antes de iniciar la sesión en la extensión, y elige la misma versión en el panel lateral.',
      ),
      h('p', { class: 'notice notice-info' }, `Versión activa: ${describeSettings(current)}.`),
      form,
      h(
        'p',
        { class: 'muted' },
        'Al guardar se cierra la sesión de la tienda y se vacían el carrito, los pedidos y la dirección. También puedes abrir la tienda con ?version=V1 o ?problems=1,4 en la dirección, con el mismo efecto.',
      ),
    ),
  };
}
