/**
 * @file Valores faciales y orientación de la cabeza a partir del resultado de
 * MediaPipe Face Landmarker.
 *
 * Los nombres de los valores salen del contrato (`face_value`, en snake_case) y
 * se traducen a los de MediaPipe (camelCase) solo aquí: `brow_down_left` →
 * `browDownLeft`. Así, agregar un valor al contrato basta para registrarlo.
 *
 * Las funciones son puras: se prueban en Node.
 */

(function (root) {
  'use strict';

  const UX = (root.UX = root.UX || {});

  /** Radianes a grados. */
  const DEG = 180 / Math.PI;

  /**
   * Nombre de MediaPipe de un valor del contrato: `brow_down_left` → `browDownLeft`.
   *
   * @param {string} name - Valor de `face_value`.
   * @returns {string} Nombre de la categoría en MediaPipe.
   */
  function mediapipeName(name) {
    return name.replace(/_([a-z])/g, (_, letter) => letter.toUpperCase());
  }

  /**
   * Extrae los valores faciales del contrato de las categorías de MediaPipe.
   *
   * @param {{categoryName: string, score: number}[]} categories - Blendshapes de un rostro.
   * @param {string[]} names - Valores de `face_value` que se registran.
   * @returns {Object<string, number>} Valor de cada nombre, entre 0 y 1. Los que
   *   MediaPipe no entregó no aparecen.
   */
  function faceValues(categories, names) {
    const scores = new Map(categories.map((c) => [c.categoryName, c.score]));
    const values = {};
    for (const name of names) {
      const score = scores.get(mediapipeName(name));
      if (typeof score === 'number' && Number.isFinite(score)) {
        values[name] = Math.min(1, Math.max(0, score));
      }
    }
    return values;
  }

  /**
   * Lee una matriz 4 × 4 de transformación sin importar si viene por columnas o
   * por filas: en una matriz afín la última fila es `0 0 0 1`, y eso delata el orden.
   *
   * @param {number[]} data - Los 16 valores de la matriz.
   * @returns {function(number, number): number} Acceso `(fila, columna)`.
   */
  function matrixReader(data) {
    if (!data || data.length !== 16) {
      throw new Error('expected a 4x4 matrix');
    }
    const columnMajor = Math.abs(data[3]) + Math.abs(data[7]) + Math.abs(data[11]) < 1e-6;
    return columnMajor ? (r, c) => data[c * 4 + r] : (r, c) => data[r * 4 + c];
  }

  /**
   * Orientación y posición de la cabeza desde la matriz de transformación facial.
   *
   * La matriz lleva el rostro canónico al espacio de la cámara (x hacia la
   * derecha de la imagen, y hacia arriba, z hacia la cámara). La tercera columna
   * es hacia dónde apunta la nariz. Como la imagen no está espejada, la derecha
   * del participante queda a la izquierda de la imagen.
   *
   * @param {number[]} data - Los 16 valores de `facialTransformationMatrixes[0].data`.
   * @returns {{yaw: number, pitch: number, roll: number, tx: number, ty: number, tz: number}}
   *   `yaw` en grados, positivo hacia la derecha del participante; `pitch`, positivo
   *   hacia arriba; `roll`, inclinación lateral; `tx`, `ty`, `tz`, posición en centímetros.
   */
  function headPose(data) {
    const m = matrixReader(data);
    const forward = { x: m(0, 2), y: m(1, 2), z: m(2, 2) };
    const up = { x: m(0, 1), y: m(1, 1) };
    return {
      yaw: Math.atan2(-forward.x, forward.z) * DEG,
      pitch: Math.atan2(forward.y, Math.hypot(forward.x, forward.z)) * DEG,
      roll: Math.atan2(up.x, up.y) * DEG,
      tx: m(0, 3),
      ty: m(1, 3),
      tz: m(2, 3),
    };
  }

  /**
   * Encuadre del rostro en la imagen de la cámara: dónde está la cara, qué tan
   * grande se ve y a qué distancia está. Sirve para comprobar, antes de calibrar,
   * que la persona está a buena distancia y centrada, sin mostrar el video.
   *
   * La distancia es la posición `tz` de la cabeza que calcula MediaPipe. Como
   * MediaPipe supone un ángulo de visión típico de webcam, se corrige con la
   * escala propia de cada cámara (`camera.distance_scale`).
   *
   * @param {Array<{x: number, y: number}>} landmarks - Puntos del rostro, normalizados
   *   entre 0 y 1 respecto de la imagen.
   * @param {{tz: number}} pose - Posición de la cabeza (`headPose`).
   * @param {number} [distanceScale] - Corrección de la distancia de esta webcam.
   * @returns {{x: number, y: number, width: number, distance_cm: number}} Centro de la
   *   cara (fracciones de la imagen, sin espejar), ancho de la cara (fracción del ancho
   *   de la imagen) y distancia a la cámara en centímetros.
   */
  function faceFraming(landmarks, pose, distanceScale = 1) {
    let minX = Infinity;
    let maxX = -Infinity;
    let minY = Infinity;
    let maxY = -Infinity;
    for (const point of landmarks) {
      minX = Math.min(minX, point.x);
      maxX = Math.max(maxX, point.x);
      minY = Math.min(minY, point.y);
      maxY = Math.max(maxY, point.y);
    }
    const round = (value, places) => Math.round(value * 10 ** places) / 10 ** places;
    return {
      x: round((minX + maxX) / 2, 3),
      y: round((minY + maxY) / 2, 3),
      width: round(maxX - minX, 3),
      // El rostro está delante de la cámara, en z negativa.
      distance_cm: round(Math.abs(pose.tz) * distanceScale, 1),
    };
  }

  UX.faceFeatures = Object.freeze({ mediapipeName, faceValues, headPose, faceFraming });
})(globalThis);
