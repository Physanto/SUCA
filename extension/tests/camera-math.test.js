/**
 * @file Pruebas de las piezas de cálculo de la cámara, que no dependen del
 * navegador: modelo de mirada, características de los ojos y valores faciales.
 */

const test = require('node:test');
const assert = require('node:assert/strict');

require('../config.generated.js');
require('../camera/gaze-model.js');
require('../camera/eye-features.js');
require('../camera/face-features.js');

const { UX } = globalThis;

/** Generador pseudoaleatorio con semilla, para que las pruebas sean repetibles. */
function seeded(seed) {
  let state = seed;
  return () => {
    state = (state * 1664525 + 1013904223) % 4294967296;
    return state / 4294967296;
  };
}

test('solves a symmetric positive definite system', () => {
  const x = UX.solveSymmetric(
    [
      [4, 1],
      [1, 3],
    ],
    [[1], [2]],
  );
  assert.ok(Math.abs(x[0][0] - 1 / 11) < 1e-9);
  assert.ok(Math.abs(x[1][0] - 7 / 11) < 1e-9);
});

test('learns a linear mapping from features to the viewport and predicts unseen points', () => {
  const random = seeded(1);
  const model = UX.createGazeModel();
  // Dos características dependen del punto mirado; el resto es ruido.
  const featuresOf = (x, y) => [x / 100 + random() * 0.01, y / 100 + random() * 0.01, random(), random()];
  const points = [0.1, 0.5, 0.9].flatMap((fy) => [0.1, 0.5, 0.9].map((fx) => [fx * 1200, fy * 800]));
  points.forEach(([x, y], group) => {
    for (let i = 0; i < 20; i += 1) {
      model.add(featuresOf(x, y), x, y, group);
    }
  });

  const fit = model.fit();
  const p = model.predict(featuresOf(300, 600));

  assert.equal(fit.ok, true);
  assert.equal(fit.samples, 180);
  assert.equal(fit.groups, 9);
  assert.ok(fit.cv_error_px < 30, `cross-validated error ${fit.cv_error_px}`);
  assert.ok(Math.hypot(p.x - 300, p.y - 600) < 30, `predicted ${p.x}, ${p.y}`);
});

test('refuses to fit with too few calibration points and predicts nothing until fitted', () => {
  const model = UX.createGazeModel();
  [0, 1, 2].forEach((group) => model.add([group, 1], group * 10, 0, group));

  assert.equal(model.predict([1, 1]), null);
  assert.equal(model.fit().ok, false);
  assert.equal(model.isFitted(), false);
});

test('clears samples and the fitted model', () => {
  const model = UX.createGazeModel();
  [0, 1, 2, 3].forEach((group) => {
    model.add([group, 0], group * 100, 0, group);
    model.add([group, 1], group * 100, 0, group);
  });
  assert.equal(model.fit().ok, true);

  model.clear();

  assert.equal(model.count(), 0);
  assert.equal(model.isFitted(), false);
});

test('rejects samples with a different number of features', () => {
  const model = UX.createGazeModel();
  model.add([1, 2], 0, 0, 0);
  assert.throws(() => model.add([1], 0, 0, 0), /same number of features/);
});

test('smooths points and starts over after a reset', () => {
  const smoother = UX.createSmoother(0.5);
  assert.deepEqual(smoother.next({ x: 0, y: 0 }), { x: 0, y: 0 });
  assert.deepEqual(smoother.next({ x: 100, y: 50 }), { x: 50, y: 25 });
  smoother.reset();
  assert.deepEqual(smoother.next({ x: 100, y: 50 }), { x: 100, y: 50 });
  assert.throws(() => UX.createSmoother(0), /alpha/);
});

/** Puntos de un rostro falso: todos en el centro salvo los que la prueba ubica. */
function fakeLandmarks(overrides = {}) {
  const landmarks = Array.from({ length: 478 }, () => ({ x: 0.5, y: 0.5, z: 0 }));
  for (const [index, point] of Object.entries(overrides)) {
    landmarks[index] = { z: 0, ...point };
  }
  return landmarks;
}

/** Ubica los arcos de un ojo dentro de una caja normalizada. */
function eyeAt(eye, x0, y0, x1, y1) {
  const points = {};
  eye.upper.forEach((i, k) => (points[i] = { x: x0 + ((x1 - x0) * k) / (eye.upper.length - 1), y: y0 }));
  eye.lower.forEach((i, k) => (points[i] = { x: x0 + ((x1 - x0) * k) / (eye.lower.length - 1), y: y1 }));
  return points;
}

test('finds the box of each eye in frame pixels', () => {
  const { EYES, eyeBoxes } = UX.eyeFeatures;
  const landmarks = fakeLandmarks({
    ...eyeAt(EYES.left, 0.55, 0.4, 0.65, 0.45),
    ...eyeAt(EYES.right, 0.35, 0.4, 0.45, 0.45),
  });

  const boxes = eyeBoxes(landmarks, 640, 480);

  assert.deepEqual(boxes.left, { x: 352, y: 192, width: 64, height: 24 });
  assert.deepEqual(boxes.right, { x: 224, y: 192, width: 64, height: 24 });
});

test('gives no eye boxes when the face is cut by the frame or incomplete', () => {
  const { EYES, eyeBoxes } = UX.eyeFeatures;
  const outside = fakeLandmarks({
    ...eyeAt(EYES.left, 0.95, 0.4, 1.05, 0.45),
    ...eyeAt(EYES.right, 0.35, 0.4, 0.45, 0.45),
  });
  assert.equal(eyeBoxes(outside, 640, 480), null);
  assert.equal(eyeBoxes([], 640, 480), null);
});

test('turns an eye crop into a 10 x 6 equalized patch', () => {
  const { eyePatch } = UX.eyeFeatures;
  // Mitad izquierda oscura, mitad derecha clara.
  const width = 20;
  const height = 12;
  const rgba = new Uint8ClampedArray(width * height * 4);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const value = x < width / 2 ? 40 : 200;
      rgba.set([value, value, value, 255], (y * width + x) * 4);
    }
  }

  const patch = eyePatch(rgba, width, height);

  assert.equal(patch.length, 60);
  assert.equal(patch[0], 0);
  assert.equal(patch[9], 1);
  assert.ok(patch.every((value) => value >= 0 && value <= 1));
  assert.ok(eyePatch(new Uint8ClampedArray(4 * 4 * 4).fill(90), 4, 4).every((v) => v === 0.5));
});

test('places the iris along each eye, from the outer to the inner corner', () => {
  const { EYES, irisOffsets } = UX.eyeFeatures;
  const landmarks = fakeLandmarks({
    [EYES.left.outer]: { x: 0.65, y: 0.42 },
    [EYES.left.inner]: { x: 0.55, y: 0.42 },
    [EYES.left.top]: { x: 0.6, y: 0.4 },
    [EYES.left.bottom]: { x: 0.6, y: 0.44 },
    [EYES.right.outer]: { x: 0.35, y: 0.42 },
    [EYES.right.inner]: { x: 0.45, y: 0.42 },
    [EYES.right.top]: { x: 0.4, y: 0.4 },
    [EYES.right.bottom]: { x: 0.4, y: 0.44 },
    468: { x: 0.375, y: 0.42 },
    473: { x: 0.6, y: 0.42 },
  });

  const [leftAlong, leftUp, rightAlong, rightUp] = irisOffsets(landmarks, 640, 480);

  assert.ok(Math.abs(leftAlong - 0.5) < 1e-9);
  assert.ok(Math.abs(rightAlong - 0.25) < 1e-9);
  assert.ok(Math.abs(leftUp) < 1e-9 && Math.abs(rightUp) < 1e-9);
});

test('builds a feature vector of fixed length', () => {
  const { featureVector, FEATURE_COUNT } = UX.eyeFeatures;
  const head = { yaw: 1, pitch: 2, roll: 3, tx: 4, ty: 5, tz: -50 };
  const vector = featureVector({ left: new Array(60).fill(0), right: new Array(60).fill(1), iris: [0, 0, 0, 0], head });

  assert.equal(vector.length, FEATURE_COUNT);
  assert.equal(vector[FEATURE_COUNT - 1], -50);
  assert.throws(() => featureVector({ left: [], right: [], iris: [], head }), /expected 130 features/);
});

test('maps contract face values to MediaPipe blendshapes and clamps them', () => {
  const { faceValues, mediapipeName } = UX.faceFeatures;
  const names = UX.contracts.enums.face_value;

  const values = faceValues(
    [
      { categoryName: 'browDownLeft', score: 0.3 },
      { categoryName: 'mouthSmileRight', score: 1.0000002 },
      { categoryName: 'jawOpen', score: 0.9 },
    ],
    names,
  );

  assert.equal(mediapipeName('brow_down_left'), 'browDownLeft');
  assert.deepEqual(values, { brow_down_left: 0.3, mouth_smile_right: 1 });
});

/** Matriz 4 × 4 por columnas de una rotación de `yaw` grados (alrededor de y) con traslación. */
function yawMatrix(degrees, translation = [0, 0, -50]) {
  const a = (degrees * Math.PI) / 180;
  // Columnas: eje x, eje y, eje z (nariz) del rostro, y traslación.
  return [Math.cos(a), 0, Math.sin(a), 0, 0, 1, 0, 0, -Math.sin(a), 0, Math.cos(a), 0, ...translation, 1];
}

test('reads head yaw with positive values toward the participant right', () => {
  const { headPose } = UX.faceFeatures;
  // Girar hacia su derecha lleva la nariz hacia la izquierda de la imagen (x negativo).
  const turned = headPose(yawMatrix(20));

  assert.ok(Math.abs(turned.yaw - 20) < 1e-9, `yaw ${turned.yaw}`);
  assert.ok(Math.abs(turned.pitch) < 1e-9);
  assert.equal(turned.tz, -50);
});

test('reads head pitch with positive values upward, in either matrix layout', () => {
  const { headPose } = UX.faceFeatures;
  const a = (15 * Math.PI) / 180;
  // Rotación alrededor de x: la nariz sube (y positivo).
  const columns = [1, 0, 0, 0, 0, Math.cos(a), -Math.sin(a), 0, 0, Math.sin(a), Math.cos(a), 0, 1, 2, -45, 1];
  const rows = [0, 1, 2, 3].flatMap((r) => [0, 1, 2, 3].map((c) => columns[c * 4 + r]));

  for (const data of [columns, rows]) {
    const pose = headPose(data);
    assert.ok(Math.abs(pose.pitch - 15) < 1e-9, `pitch ${pose.pitch}`);
    assert.ok(Math.abs(pose.yaw) < 1e-9);
    assert.deepEqual([pose.tx, pose.ty, pose.tz], [1, 2, -45]);
  }
  assert.throws(() => headPose([1, 2, 3]), /4x4/);
});
