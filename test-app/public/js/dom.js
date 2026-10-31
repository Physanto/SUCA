/**
 * @file Ayudas pequeñas para construir el DOM sin librerías.
 */

/**
 * Crea un elemento con sus propiedades y sus hijos.
 *
 * - `class`: clases separadas por espacios.
 * - `on`: oyentes de eventos, por nombre (`{ click: fn }`).
 * - Claves con guion o `aria-*`/`role`: se ponen como atributos.
 * - `true` pone el atributo sin valor; `false`, `null` o `undefined` lo omiten.
 * - El resto se asigna como propiedad (`value`, `checked`, `hidden`…).
 *
 * @param {string} tag - Etiqueta HTML.
 * @param {object|null} [props] - Propiedades y atributos.
 * @param {...(Node|string|number|null|false|Array)} children - Hijos; los
 *   textos se convierten en nodos de texto y los vacíos se ignoran.
 * @returns {HTMLElement} Elemento creado.
 */
export function h(tag, props, ...children) {
  const element = document.createElement(tag);
  // Los hijos van primero: así `value` de un <select> encuentra sus opciones.
  append(element, children);
  for (const [key, value] of Object.entries(props ?? {})) {
    if (value === false || value === null || value === undefined) continue;
    if (key === 'class') element.className = value;
    else if (key === 'on') {
      for (const [type, handler] of Object.entries(value)) element.addEventListener(type, handler);
    } else if (key.includes('-') || key === 'role' || key === 'for' || !(key in element)) {
      element.setAttribute(key, value === true ? '' : String(value));
    } else {
      element[key] = value;
    }
  }
  return element;
}

/**
 * Agrega hijos a un elemento, aplanando listas e ignorando los vacíos.
 *
 * @param {Element} parent - Elemento padre.
 * @param {Array} children - Hijos.
 * @returns {void}
 */
function append(parent, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    parent.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}

/**
 * Lee los valores de un formulario como un objeto.
 *
 * @param {HTMLFormElement} form - Formulario.
 * @returns {Object<string, string>} Valor de cada campo, por su `name`.
 */
export function formValues(form) {
  return Object.fromEntries(new FormData(form).entries());
}

/**
 * Marca los campos inválidos de un formulario y escribe su mensaje.
 *
 * Cada campo con error recibe `aria-invalid="true"` y un mensaje enlazado con
 * `aria-describedby`; los demás se limpian. El foco va al primer campo con
 * error, para que la persona sepa por dónde empezar.
 *
 * @param {HTMLFormElement} form - Formulario.
 * @param {Object<string, string>} errors - Mensaje por nombre de campo.
 * @returns {void}
 */
export function showFieldErrors(form, errors) {
  let first = null;
  for (const field of form.querySelectorAll('[name]')) {
    const message = errors[field.name];
    const errorId = `${field.id}-error`;
    form.querySelector(`#${CSS.escape(errorId)}`)?.remove();
    const described = (field.getAttribute('aria-describedby') ?? '')
      .split(' ')
      .filter((id) => id && id !== errorId);
    if (!message) {
      field.removeAttribute('aria-invalid');
      setDescribedBy(field, described);
      continue;
    }
    field.setAttribute('aria-invalid', 'true');
    setDescribedBy(field, [...described, errorId]);
    const anchor = field.closest('.field') ?? field.parentElement;
    anchor.append(h('p', { class: 'field-error', id: errorId }, message));
    first ??= field;
  }
  first?.focus();
}

/**
 * Escribe la lista de ids de `aria-describedby`, o quita el atributo si está vacía.
 *
 * @param {Element} field - Campo.
 * @param {string[]} ids - Ids de los textos que lo describen.
 * @returns {void}
 */
function setDescribedBy(field, ids) {
  if (ids.length > 0) field.setAttribute('aria-describedby', ids.join(' '));
  else field.removeAttribute('aria-describedby');
}

/**
 * Espera un tiempo; simula la latencia de un servidor.
 *
 * @param {number} ms - Milisegundos.
 * @returns {Promise<void>} Se resuelve al cumplirse el tiempo.
 */
export function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
