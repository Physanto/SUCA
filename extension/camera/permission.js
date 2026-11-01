/**
 * @file Página del permiso de cámara: pide la cámara con el aviso de Chrome y
 * la cierra enseguida. Solo sirve para que Chrome recuerde el permiso de la
 * extensión; no muestra ni guarda la imagen.
 */

(function (root) {
  'use strict';

  const texts = root.UX.cameraStrings.permission;
  const { document } = root;
  const status = document.getElementById('status');

  document.querySelectorAll('[data-string]').forEach((node) => {
    node.textContent = texts[node.dataset.string];
  });

  /** Muestra el resultado del permiso. */
  function show(state) {
    status.textContent = texts[state];
  }

  /**
   * Pide la cámara y la libera de inmediato.
   *
   * @returns {Promise<void>}
   */
  async function ask() {
    show('asking');
    try {
      const stream = await root.navigator.mediaDevices.getUserMedia({ video: true, audio: false });
      stream.getTracks().forEach((track) => track.stop());
      show('granted');
    } catch (error) {
      show(error && error.name === 'NotFoundError' ? 'noCamera' : 'denied');
    }
  }

  document.getElementById('allow').addEventListener('click', ask);

  // Si ya estaba permitida, se dice de entrada.
  root.navigator.permissions
    .query({ name: 'camera' })
    .then((permission) => {
      if (permission.state === 'granted') {
        show('granted');
      }
    })
    .catch(() => {});
})(globalThis);
