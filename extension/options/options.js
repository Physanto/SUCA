/**
 * @file Página de opciones: pantalla y distancias de este equipo.
 *
 * Calcula los píxeles CSS por centímetro con la diagonal o el ancho de la
 * pantalla (`UX.screenSetup.cssPxPerCm`), dibuja una barra de 10 cm para
 * comprobarlo con una regla y guarda los ajustes en `chrome.storage.local`
 * (clave `UX.screenSetup.STORAGE_KEY`). La calibración los toma desde la
 * próxima vez. Los textos están en `camera/strings.js`.
 */

(function (root) {
  'use strict';

  const { UX } = root;
  const { screenSetup, cameraStrings, config, platform } = UX;
  const texts = cameraStrings.screenSetup;
  const storage = platform.storage('local');
  const doc = root.document;
  const byId = (id) => doc.getElementById(id);

  /** Pantalla donde está abierta la página: es la que se mide. */
  const screen = { width: root.screen.width, height: root.screen.height };

  /** Número escrito en un campo, o `null` si está vacío o no es un número. */
  function numberIn(id) {
    const value = Number.parseFloat(byId(id).value);
    return Number.isFinite(value) ? value : null;
  }

  /** Modo elegido para el tamaño: `diagonal` o `width`. */
  function mode() {
    return doc.querySelector('input[name="mode"]:checked').value;
  }

  /** Píxeles por centímetro con lo escrito, o `null` si falta el tamaño. */
  function density() {
    const size = mode() === 'width' ? { width_cm: numberIn('width') } : { diagonal_in: numberIn('diagonal') };
    try {
      return screenSetup.cssPxPerCm(size, screen);
    } catch (error) {
      return null;
    }
  }

  /** Muestra la densidad calculada y la barra de 10 cm. */
  function refresh() {
    byId('diagonal-row').hidden = mode() !== 'diagonal';
    byId('diagonal-presets').hidden = mode() !== 'diagonal';
    byId('width-row').hidden = mode() !== 'width';
    const pxPerCm = density();
    byId('density').textContent = pxPerCm === null ? texts.needSize : texts.density(pxPerCm);
    byId('ruler').style.width = pxPerCm === null ? '0' : `${pxPerCm * 10}px`;
  }

  /** Escribe un estado debajo de los botones. */
  function status(text, isError = false) {
    const node = byId('status');
    node.textContent = text;
    node.classList.toggle('error', isError);
  }

  /** Dice de dónde salen los valores que usa hoy la calibración. */
  function showSource(setup) {
    const usable = setup && screenSetup.problems(setup).length === 0;
    let text = usable ? texts.fromLocal(new Date(setup.saved_at).toLocaleString('es-CO')) : texts.fromConfig;
    if (usable && (setup.screen_width_px !== screen.width || setup.screen_height_px !== screen.height)) {
      text += ` ${texts.otherScreen(setup.screen_width_px, setup.screen_height_px)}`;
    }
    byId('source').textContent = text;
  }

  /** Llena el formulario con los ajustes guardados o, si no hay, con la configuración. */
  function fill(setup) {
    const camera = screenSetup.apply(config.camera, setup);
    const usable = setup && screenSetup.problems(setup).length === 0;
    if (usable && setup.width_cm > 0) {
      doc.querySelector('input[value="width"]').checked = true;
      byId('width').value = setup.width_cm;
    } else if (usable && setup.diagonal_in > 0) {
      byId('diagonal').value = setup.diagonal_in;
    } else {
      // Sin ajustes, se muestra el ancho que corresponde a la densidad configurada.
      doc.querySelector('input[value="width"]').checked = true;
      byId('width').value = Math.round((screen.width / camera.css_px_per_cm) * 10) / 10;
    }
    byId('usual').value = camera.viewing_distance_cm;
    byId('min').value = camera.min_distance_cm;
    byId('max').value = camera.max_distance_cm;
    showSource(setup);
    refresh();
  }

  /** Guarda lo escrito si es válido. */
  async function save(event) {
    event.preventDefault();
    const pxPerCm = density();
    if (pxPerCm === null) {
      status(texts.needSize, true);
      return;
    }
    const setup = {
      css_px_per_cm: pxPerCm,
      viewing_distance_cm: numberIn('usual'),
      min_distance_cm: numberIn('min'),
      max_distance_cm: numberIn('max'),
      diagonal_in: mode() === 'diagonal' ? numberIn('diagonal') : null,
      width_cm: mode() === 'width' ? numberIn('width') : null,
      screen_width_px: screen.width,
      screen_height_px: screen.height,
      saved_at: Date.now(),
    };
    if (screenSetup.problems(setup).length > 0) {
      status(texts.invalid, true);
      return;
    }
    await storage.set(screenSetup.STORAGE_KEY, setup);
    showSource(setup);
    status(texts.saved);
  }

  /** Borra los ajustes de este equipo. */
  async function reset() {
    await storage.remove(screenSetup.STORAGE_KEY);
    fill(null);
    status(texts.reset);
  }

  byId('detected').textContent = texts.detected(screen.width, screen.height, root.devicePixelRatio || 1);
  for (const radio of doc.querySelectorAll('input[name="mode"]')) {
    radio.addEventListener('change', refresh);
  }
  byId('diagonal').addEventListener('input', refresh);
  byId('width').addEventListener('input', refresh);
  for (const button of doc.querySelectorAll('[data-diagonal]')) {
    button.addEventListener('click', () => {
      byId('diagonal').value = button.dataset.diagonal;
      refresh();
    });
  }
  for (const button of doc.querySelectorAll('[data-distances]')) {
    button.addEventListener('click', () => {
      const [usual, min, max] = button.dataset.distances.split(',');
      byId('usual').value = usual;
      byId('min').value = min;
      byId('max').value = max;
    });
  }
  byId('form').addEventListener('submit', save);
  byId('reset').addEventListener('click', reset);
  screenSetup.load(storage).then(fill);
})(globalThis);
