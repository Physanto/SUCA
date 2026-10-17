/**
 * @file Registro de los módulos de los content scripts y su ciclo de vida.
 *
 * Cada módulo (captura, cámara, calibración, fin de tarea) se registra al
 * cargarse con `UX.modules.register({ name, start(ctx), stop() })`, pero no
 * arranca solo: `content/bootstrap.js` llama a `startAll(ctx)` cuando la
 * pestaña evaluada tiene una sesión activa y a `stopAll()` cuando se cierra.
 *
 * Los módulos son independientes: un error al iniciar o detener uno se registra
 * en la consola y no impide que los demás sigan. Un `stop()` que no termina a
 * tiempo se abandona, para que el cierre de la sesión nunca quede esperando.
 */

(function (root) {
  'use strict';

  const UX = (root.UX = root.UX || {});

  /** Tiempo máximo que se espera a que un módulo termine su `stop()`. */
  const STOP_TIMEOUT_MS = 2000;

  /**
   * Crea un registro de módulos.
   *
   * @param {object} [deps] - Dependencias.
   * @param {{error: Function}} [deps.logger] - Dónde se registran los errores; por defecto, la consola.
   * @param {{setTimeout: Function, clearTimeout: Function}} [deps.timers] -
   *   Temporizadores; por defecto, los globales.
   * @param {number} [deps.stopTimeoutMs] - Espera máxima de cada `stop()`.
   * @returns {object} Registro con `register`, `startAll`, `stopAll`, `names` e `isRunning`.
   */
  function createModules({
    logger = root.console,
    timers = root,
    stopTimeoutMs = STOP_TIMEOUT_MS,
  } = {}) {
    const registered = [];
    let running = false;
    let startResult = null;

    /** Ejecuta un paso de un módulo; informa si terminó bien sin dejar escapar el error. */
    async function run(module, step, ctx) {
      try {
        await module[step](ctx);
        return true;
      } catch (error) {
        logger.error(`module ${module.name} failed to ${step}:`, error);
        return false;
      }
    }

    /** Detiene un módulo sin esperar más de `stopTimeoutMs`. */
    function stopWithin(module) {
      let timer;
      const timeout = new Promise((resolve) => {
        timer = timers.setTimeout(() => {
          logger.error(`module ${module.name} did not stop within ${stopTimeoutMs} ms`);
          resolve(false);
        }, stopTimeoutMs);
      });
      return Promise.race([run(module, 'stop'), timeout]).finally(() => timers.clearTimeout(timer));
    }

    /** Separa los nombres de los módulos según el resultado de cada uno. */
    function split(modules, results, okKey) {
      return {
        [okKey]: modules.filter((_, i) => results[i]).map((module) => module.name),
        failed: modules.filter((_, i) => !results[i]).map((module) => module.name),
      };
    }

    return Object.freeze({
      /**
       * Registra un módulo. Se llama al cargar el archivo del módulo, antes de
       * `bootstrap.js`.
       *
       * @param {{name: string, start: function(object): (void|Promise<void>),
       *   stop: function(): (void|Promise<void>)}} module - Módulo con nombre único.
       *   `start` recibe el contexto; `stop` debe poder llamarse aunque `start`
       *   haya fallado o no haya terminado.
       * @returns {void}
       */
      register(module) {
        const { name, start, stop } = module || {};
        if (typeof name !== 'string' || name === '') {
          throw new Error('module name must be a non-empty string');
        }
        if (typeof start !== 'function' || typeof stop !== 'function') {
          throw new Error(`module ${name} must define start(ctx) and stop()`);
        }
        if (registered.some((other) => other.name === name)) {
          throw new Error(`module already registered: ${name}`);
        }
        registered.push(module);
      },

      /**
       * Inicia todos los módulos a la vez. Si ya están iniciados, no hace nada
       * y devuelve el resultado del inicio anterior.
       *
       * @param {object} ctx - Contexto que recibe cada módulo.
       * @returns {Promise<{started: string[], failed: string[]}>} Módulos que
       *   arrancaron y módulos que fallaron.
       */
      startAll(ctx) {
        if (!running) {
          running = true;
          const modules = [...registered];
          // A la vez y no en orden: un módulo lento (la cámara esperando permiso)
          // no debe retrasar a los demás.
          startResult = Promise.all(modules.map((module) => run(module, 'start', ctx))).then(
            (results) => split(modules, results, 'started'),
          );
        }
        return startResult;
      },

      /**
       * Detiene todos los módulos. Si no están iniciados, no hace nada.
       *
       * @returns {Promise<{stopped: string[], failed: string[]}>} Módulos que se
       *   detuvieron y módulos que fallaron o no terminaron a tiempo.
       */
      async stopAll() {
        if (!running) {
          return { stopped: [], failed: [] };
        }
        running = false;
        startResult = null;
        const modules = [...registered];
        const results = await Promise.all(modules.map(stopWithin));
        return split(modules, results, 'stopped');
      },

      /**
       * Devuelve los nombres de los módulos registrados, en orden de registro.
       *
       * @returns {string[]} Nombres.
       */
      names: () => registered.map((module) => module.name),

      /**
       * Indica si los módulos están iniciados.
       *
       * @returns {boolean} `true` entre `startAll` y `stopAll`.
       */
      isRunning: () => running,
    });
  }

  UX.createModules = createModules;
  // No depende de Chrome: existe también en las pruebas, donde los módulos se registran al cargarse.
  UX.modules = createModules();
})(globalThis);
