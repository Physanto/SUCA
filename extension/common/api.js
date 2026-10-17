/**
 * @file Cliente del servidor local. Lo usan el worker (lotes y cierre de
 * sesión) y el panel lateral (estudios, sesiones, SUS y referencias).
 *
 * Cada función corresponde a un endpoint del servidor y envía el token en
 * `X-Api-Token`. Los errores son `ApiError`, con `permanent` para distinguir
 * los que no se arreglan reintentando (4xx) de los que sí (red caída, 5xx).
 */

(function (root) {
  'use strict';

  const UX = (root.UX = root.UX || {});

  /** Encabezado del token que exige el servidor. */
  const TOKEN_HEADER = 'X-Api-Token';

  /**
   * Error de una petición al servidor.
   *
   * @property {number} status - Código HTTP, o 0 si el servidor no respondió.
   * @property {string} detail - Resumen del error.
   * @property {object[]} errors - Problemas por campo (`record`, `field`, `message`) en los 422.
   * @property {boolean} permanent - `true` si reintentar la misma petición no sirve.
   */
  class ApiError extends Error {
    /**
     * @param {{status: number, detail: string, errors: object[]}} info - Datos del error.
     */
    constructor({ status, detail, errors }) {
      super(status === 0 ? detail : `${status}: ${detail}`);
      this.name = 'ApiError';
      this.status = status;
      this.detail = detail;
      this.errors = errors;
      // 408 y 429 son 4xx, pero indican "más tarde", no "nunca".
      this.permanent = status >= 400 && status < 500 && status !== 408 && status !== 429;
    }
  }

  /**
   * Crea el cliente del servidor.
   *
   * @param {object} deps - Dependencias.
   * @param {Function} deps.fetch - Función `fetch`.
   * @param {{host: string, port: number, token: string}} deps.server - Sección
   *   `server` de la configuración.
   * @returns {object} Una función por endpoint.
   */
  function createApi({ fetch, server }) {
    const baseUrl = `http://${server.host}:${server.port}`;

    async function request(method, path, body) {
      const headers = { [TOKEN_HEADER]: server.token };
      if (body !== undefined) {
        headers['Content-Type'] = 'application/json';
      }
      let response;
      try {
        response = await fetch(baseUrl + path, {
          method,
          headers,
          body: body === undefined ? undefined : JSON.stringify(body),
        });
      } catch (error) {
        throw new ApiError({ status: 0, detail: `server unreachable: ${error.message}`, errors: [] });
      }
      const data = await response.json().catch(() => null);
      if (!response.ok) {
        throw new ApiError({
          status: response.status,
          detail: (data && data.detail) || response.statusText,
          errors: (data && data.errors) || [],
        });
      }
      return data;
    }

    return Object.freeze({
      /** `GET /health`. */
      health: () => request('GET', '/health'),
      /** `GET /studies`. */
      listStudies: () => request('GET', '/studies'),
      /** `GET /studies/{id}/tasks`: tareas con sus referencias confirmadas. */
      listTasks: (studyId) => request('GET', `/studies/${studyId}/tasks`),
      /** `POST /sessions`, con un cuerpo `new-session`. */
      createSession: (body) => request('POST', '/sessions', body),
      /** `POST /sessions/{id}/batches`, con un lote completo. */
      sendBatch: (sessionId, batch) => request('POST', `/sessions/${sessionId}/batches`, batch),
      /** `POST /sessions/{id}/sus`, con un cuerpo `sus-answers`. */
      saveSus: (sessionId, body) => request('POST', `/sessions/${sessionId}/sus`, body),
      /** `POST /sessions/{id}/close`. Lo usa el worker, nunca el panel. */
      closeSession: (sessionId) => request('POST', `/sessions/${sessionId}/close`),
      /** `POST /references`, con un cuerpo `new-reference`. */
      createReference: (body) => request('POST', '/references', body),
      /** `POST /captures`, con un cuerpo `new-capture`. */
      sendCapture: (body) => request('POST', '/captures', body),
    });
  }

  UX.ApiError = ApiError;
  UX.createApi = createApi;
  if (UX.platform) {
    UX.api = createApi({ fetch: (...args) => root.fetch(...args), server: UX.config.server });
  }
})(globalThis);
