/** @file Ejecuta el guion de mirada con tiempos absolutos desde el clic inicial. */
(function (root) {
  'use strict';

  /**
   * Índice del objetivo vigente; -1 cuando terminó. No acumula retrasos de temporizadores.
   * @param {object} script - Guion leído de attention-script.json.
   * @param {number} elapsedMs - Milisegundos desde el clic inicial.
   * @returns {number} Índice del objetivo, empezando en cero.
   */
  function stepAt(script, elapsedMs) {
    if (elapsedMs < 0 || elapsedMs >= script.targets.length * script.step_ms) return -1;
    return Math.floor(elapsedMs / script.step_ms);
  }

  /**
   * Tramo evaluable de un objetivo, descartando la sacada inicial.
   * @param {object} script - Guion.
   * @param {number} index - Índice del objetivo.
   * @returns {number[]} Inicio incluido y fin excluido, relativos al clic.
   */
  function truthWindow(script, index) {
    return [index * script.step_ms + script.settle_ms, (index + 1) * script.step_ms];
  }

  if (typeof module !== 'undefined') module.exports = { stepAt, truthWindow };
  if (!root.document) return;

  /** Inicializa la página; los fallos de montaje se muestran antes de empezar. */
  async function boot() {
    const button = document.getElementById('attention-start');
    const status = document.getElementById('attention-status');
    const marker = document.getElementById('attention-marker');
    try {
      const response = await fetch('attention-script.json');
      if (!response.ok) throw new Error('script unavailable');
      const script = await response.json();
      const selectors = new Set(script.targets.filter(t => t.selector).map(t => t.selector));
      selectors.add('#attention-empty');
      let running = false;
      let started = false;
      let origin = 0;
      let previous = -2;

      /** Comprueba que todos los objetivos caben sin desplazar la página. */
      function fits() {
        return [...selectors].every(selector => {
          const box = document.querySelector(selector)?.getBoundingClientRect();
          return box && box.left >= 0 && box.top >= 0 && box.right <= innerWidth && box.bottom <= innerHeight;
        });
      }

      /** Cancela un montaje inválido sin crear otro clic de inicio en la sesión. */
      function cancel() {
        if (!running) return;
        running = false;
        marker.hidden = true;
        document.body.classList.remove('running');
        status.textContent = 'Prueba interrumpida. Descarta esta ejecución y abre una sesión nueva.';
      }
      root.addEventListener('resize', cancel);
      root.addEventListener('scroll', cancel);
      document.addEventListener('visibilitychange', () => { if (document.hidden) cancel(); });

      /** Dibuja el objetivo según el tiempo real, incluso si un cuadro llegó tarde. */
      function tick() {
        if (!running) return;
        const index = stepAt(script, performance.now() - origin);
        if (index === -1) {
          running = false;
          marker.hidden = true;
          document.body.classList.remove('running');
          status.textContent = 'Listo. Cierra la sesión y analiza los datos.';
          return;
        }
        if (index !== previous) {
          previous = index;
          const target = script.targets[index];
          status.textContent = `${index + 1}/${script.targets.length}: ${target.label}`;
          marker.hidden = target.kind === 'keyboard';
          if (!marker.hidden) {
            const selector = target.selector || '#attention-empty';
            const box = document.querySelector(selector).getBoundingClientRect();
            Object.assign(marker.style, {
              left: `${box.left - 4}px`, top: `${box.top - 4}px`,
              width: `${box.width + 8}px`, height: `${box.height + 8}px`,
            });
          }
        }
        root.requestAnimationFrame(tick);
      }

      /** Habilita el inicio solo cuando todo el montaje cabe antes de registrar el clic. */
      function ready() {
        if (started) return;
        button.disabled = !fits();
        status.textContent = button.disabled
          ? 'Amplía la ventana hasta que todos los objetivos quepan sin desplazamiento.'
          : `${script.targets.length} objetivos, ${script.targets.length * script.step_ms / 1000} s. Mantén esta pestaña visible.`;
      }
      root.addEventListener('resize', ready);
      ready();
      button.addEventListener('click', () => {
        started = true;
        button.disabled = true;
        if (!fits()) {
          status.textContent = 'La página no cabe. Amplía la ventana antes de crear una sesión nueva.';
          return;
        }
        origin = performance.now();
        running = true;
        document.body.classList.add('running');
        tick();
      });
    } catch {
      status.textContent = 'No se pudo cargar el guion. Sirve la página con scripts.serve_test_page.';
    }
  }
  boot();
})(globalThis);
