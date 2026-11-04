/**
 * @file Tapa zonas de una captura de la sesión antes de enviarla al servidor.
 *
 * Lo usa el worker con las zonas que mide `content/frames.js`: los campos cuyo
 * texto el estudio no registra. Si algo falla, lanza el error y la captura no se
 * envía; nunca sale una imagen sin tapar.
 */

(function (root) {
  'use strict';

  const UX = (root.UX = root.UX || {});

  /** Color de las zonas tapadas: gris neutro, distinto del blanco de un campo vacío. */
  const MASK_COLOR = '#9ca3af';

  /**
   * Crea la función que tapa zonas, sobre las APIs de imagen del contexto.
   *
   * @param {object} deps - APIs de imagen (en el worker, las globales).
   * @param {function(Blob): Promise<ImageBitmap>} deps.createImageBitmap - Decodifica la imagen.
   * @param {Function} deps.OffscreenCanvas - Lienzo sin documento.
   * @param {Function} deps.Blob - Constructor de `Blob`.
   * @param {function(string): string} deps.atob - Base64 a binario.
   * @param {function(string): string} deps.btoa - Binario a base64.
   * @returns {function(string, Array<object>, number, number): Promise<string>} `maskFrame`.
   */
  function createFrameMasker({ createImageBitmap, OffscreenCanvas, Blob, atob, btoa }) {
    /** Data URL a `Blob`. */
    function toBlob(dataUrl) {
      const [header, encoded] = dataUrl.split(',', 2);
      const binary = atob(encoded);
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i += 1) {
        bytes[i] = binary.charCodeAt(i);
      }
      return new Blob([bytes], { type: header.slice('data:'.length, header.indexOf(';')) });
    }

    /** `Blob` a data URL, en partes para no pasar un argumento gigante a `fromCharCode`. */
    async function toDataUrl(blob) {
      const bytes = new Uint8Array(await blob.arrayBuffer());
      let binary = '';
      for (let i = 0; i < bytes.length; i += 0x8000) {
        binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
      }
      return `data:${blob.type};base64,${btoa(binary)}`;
    }

    /**
     * Tapa las zonas de una captura con rectángulos grises.
     *
     * @param {string} dataUrl - Captura JPEG como data URL.
     * @param {Array<{x: number, y: number, w: number, h: number}>} masks - Zonas en
     *   píxeles CSS de la ventana.
     * @param {number} viewportWidth - Ancho de la ventana en píxeles CSS.
     * @param {number} quality - Calidad JPEG de la imagen nueva, de 0 a 100.
     * @returns {Promise<string>} Captura tapada como data URL JPEG (la misma si no hay zonas).
     */
    return async function maskFrame(dataUrl, masks, viewportWidth, quality) {
      if (masks.length === 0) {
        return dataUrl;
      }
      const bitmap = await createImageBitmap(toBlob(dataUrl));
      // La captura está en píxeles del dispositivo; las zonas, en píxeles CSS.
      const scale = bitmap.width / viewportWidth;
      const canvas = new OffscreenCanvas(bitmap.width, bitmap.height);
      const context = canvas.getContext('2d');
      context.drawImage(bitmap, 0, 0);
      context.fillStyle = MASK_COLOR;
      for (const { x, y, w, h } of masks) {
        context.fillRect(x * scale, y * scale, w * scale, h * scale);
      }
      return toDataUrl(await canvas.convertToBlob({ type: 'image/jpeg', quality: quality / 100 }));
    };
  }

  UX.createFrameMasker = createFrameMasker;
  if (typeof root.OffscreenCanvas === 'function') {
    UX.maskFrame = createFrameMasker({
      createImageBitmap: root.createImageBitmap.bind(root),
      OffscreenCanvas: root.OffscreenCanvas,
      Blob: root.Blob,
      atob: root.atob.bind(root),
      btoa: root.btoa.bind(root),
    });
  }
})(globalThis);
