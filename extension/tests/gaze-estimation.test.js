/**
 * @file Pruebas de la estimación de mirada: álgebra (`numeric.js`), estimador
 * geométrico (`gaze-geometry.js`), estimador combinado (`gaze-estimator.js`),
 * filtro One Euro (`gaze-filter.js`) y monitor (`gaze-monitor.js`).
 *
 * El estimador geométrico se prueba con una persona simulada: un modelo con
 * parámetros conocidos genera, para cada punto de la pantalla y cada postura de
 * la cabeza, la posición del iris que tendría. El estimador debe recuperar la
 * mirada en posturas que no vio durante la calibración.
 */

const test = require('node:test');
const assert = require('node:assert/strict');

require('../camera/numeric.js');
require('../camera/gaze-model.js');
require('../camera/gaze-geometry.js');
require('../camera/gaze-estimator.js');
require('../camera/gaze-filter.js');
require('../camera/gaze-monitor.js');

const { UX } = globalThis;
const { project } = UX.gazeGeometry;

const VIEWPORT = { width: 1280, height: 720 };
const PX_PER_CM = 40;
const RAD = Math.PI / 180;

/** Generador pseudoaleatorio fijo, para que las pruebas den siempre lo mismo. */
function seeded(seed) {
  let state = seed;
  return () => {
    state = (1103515245 * state + 12345) % 2147483648;
    return state / 2147483648;
  };
}

/** Persona simulada: parámetros verdaderos del modelo y su apertura de ojos de referencia. */
const TRUTH = [-2.2, 0.04, -2.8, -0.05, 0.6, 1, 1, 650, -90, 1.05, 0.97];
const OPEN_REF = 0.3;

/**
 * Posición del iris (`h`, `v`) que hace mirar un punto con una postura dada,
 * invirtiendo el modelo verdadero.
 */
function irisFor(target, pose) {
  const [aH, bH, aV, bV, cOpen, gYaw, gPitch, cx, cy, kx, ky] = TRUTH;
  const tanV = Math.tan((63 * RAD) / 2);
  const tanH = tanV * pose.aspect;
  const oz = pose.distance;
  const ox = -(pose.eyeU - 0.5) * 2 * tanH * oz;
  const oy = (pose.eyeV - 0.5) * 2 * tanV * oz;
  const px = (target.x - cx) / (kx * PX_PER_CM);
  const py = (target.y - cy) / (ky * PX_PER_CM);
  const yaw = Math.atan((px - ox) / oz);
  const pitch = Math.atan(((oy - py) * Math.cos(yaw)) / oz);
  const theta = yaw - gYaw * pose.yaw * RAD;
  const phi = pitch - gPitch * pose.pitch * RAD;
  return { h: (theta - bH) / aH, v: (phi - bV - cOpen * (pose.open - OPEN_REF)) / aV };
}

/** Postura de la cabeza al azar alrededor de una postura central. */
function poseNear(random, center, spread) {
  const jitter = (range) => (random() - 0.5) * 2 * range;
  return {
    yaw: center.yaw + jitter(spread.yaw),
    pitch: center.pitch + jitter(spread.pitch),
    distance: center.distance + jitter(spread.distance),
    eyeU: 0.5 + jitter(0.08),
    eyeV: 0.45 + jitter(0.06),
    aspect: 16 / 9,
    open: OPEN_REF + jitter(0.02),
  };
}

/** Cuadro simulado: postura más el iris que corresponde, con ruido de medición. */
function frameFor(target, pose, random, noise = 0.002) {
  const iris = irisFor(target, pose);
  return { ...pose, h: iris.h + (random() - 0.5) * 2 * noise, v: iris.v + (random() - 0.5) * 2 * noise };
}

/** Puntos de una cuadrícula en fracciones de la ventana. */
const grid = (fractions) =>
  fractions.flatMap((fy) => fractions.map((fx) => ({ x: fx * VIEWPORT.width, y: fy * VIEWPORT.height })));

test('the simulated person looks where the true model says', () => {
  const random = seeded(3);
  const pose = poseNear(random, { yaw: 5, pitch: -10, distance: 60 }, { yaw: 0, pitch: 0, distance: 0 });
  const target = { x: 300, y: 200 };

  const point = project(TRUTH, frameFor(target, pose, random, 0), { cssPxPerCm: PX_PER_CM, openRef: OPEN_REF });

  assert.ok(Math.hypot(point.x - target.x, point.y - target.y) < 1e-6);
});

test('the geometric estimator learns a person and keeps working in head postures it never saw', () => {
  const random = seeded(11);
  const model = UX.createGeometricModel({ cssPxPerCm: PX_PER_CM });
  const calibrationPose = { yaw: 0, pitch: -8, distance: 58 };
  // Calibración: 13 puntos con la cabeza casi quieta, y un punto central con la cabeza moviéndose.
  const points = [...grid([0.1, 0.5, 0.9]), ...grid([0.3, 0.7])];
  points.forEach((target, group) => {
    for (let k = 0; k < 20; k += 1) {
      const frame = frameFor(target, poseNear(random, calibrationPose, { yaw: 2, pitch: 2, distance: 2 }), random);
      model.add(frame, target.x, target.y, group);
    }
  });
  const center = { x: VIEWPORT.width / 2, y: VIEWPORT.height / 2 };
  for (let k = 0; k < 80; k += 1) {
    const frame = frameFor(center, poseNear(random, calibrationPose, { yaw: 12, pitch: 10, distance: 8 }), random);
    model.add(frame, center.x, center.y, 'head');
  }

  const fit = model.fit({ viewport: VIEWPORT });

  assert.equal(fit.ok, true);
  assert.equal(fit.groups, 14);
  // Prueba: otra postura (girado, inclinado y más lejos) y puntos nuevos.
  const shiftedPose = { yaw: 9, pitch: -15, distance: 66 };
  const errors = grid([0.2, 0.4, 0.6, 0.8]).map((target) => {
    const frame = frameFor(target, poseNear(random, shiftedPose, { yaw: 1, pitch: 1, distance: 1 }), random);
    const point = model.predict(frame);
    return Math.hypot(point.x - target.x, point.y - target.y);
  });
  const mean = errors.reduce((sum, e) => sum + e, 0) / errors.length;
  // Ruido del iris de ±0,002 anchos de ojo equivale a unos 20 px; sin modelo de cabeza el error sería de cientos.
  assert.ok(mean < 45, `mean error ${mean.toFixed(1)} px`);
  assert.ok(Math.abs(model.params().g_yaw - 1) < 0.15);
});

test('the geometric estimator needs four calibration points and predicts nothing before', () => {
  const model = UX.createGeometricModel({ cssPxPerCm: PX_PER_CM });
  const random = seeded(5);
  grid([0.1, 0.9]).slice(0, 3).forEach((target, group) => {
    model.add(frameFor(target, poseNear(random, { yaw: 0, pitch: 0, distance: 60 }, { yaw: 1, pitch: 1, distance: 1 }), random), target.x, target.y, group);
  });

  assert.deepEqual(model.fit({ viewport: VIEWPORT }), { ok: false, samples: 3, groups: 3, lambda: null, cv_error_px: null });
  assert.equal(model.predict({ yaw: 0, pitch: 0, distance: 60, eyeU: 0.5, eyeV: 0.5, aspect: 1.7, h: 0, v: 0, open: 0.3 }), null);
  assert.throws(() => UX.createGeometricModel({ cssPxPerCm: 0 }), /must be positive/);
});

test('the combined estimator uses the candidate with the lower cross-validation error', () => {
  /** Candidato falso con un error de validación cruzada fijo. */
  const fake = (error, answer) => {
    const added = [];
    return {
      added,
      add: (features) => added.push(features),
      clear: () => added.splice(0),
      fit: () => ({ ok: error !== null, samples: added.length, groups: 4, lambda: 1, cv_error_px: error }),
      predict: () => answer,
      isFitted: () => true,
    };
  };
  const geometric = fake(80, { x: 1, y: 1 });
  const appearance = fake(120, { x: 2, y: 2 });
  const estimator = UX.createGazeEstimator({ geometric, appearance });
  estimator.add({ geometric: { h: 0 }, appearance: null }, 10, 10, 0);

  const fit = estimator.fit({ viewport: VIEWPORT });

  assert.equal(fit.estimator, 'geometric');
  assert.deepEqual(fit.candidates, { geometric: 80, appearance: 120 });
  assert.deepEqual([geometric.added.length, appearance.added.length], [1, 0]);
  assert.deepEqual(estimator.predict({ geometric: { h: 0 }, appearance: [1] }), { x: 1, y: 1 });
  assert.equal(estimator.predict({ geometric: null, appearance: [1] }), null);
});

test('the combined estimator reports no model when no candidate could train', () => {
  const failing = { add() {}, clear() {}, fit: () => ({ ok: false, samples: 0, groups: 0, lambda: null, cv_error_px: null }), predict: () => null, isFitted: () => false };
  const estimator = UX.createGazeEstimator({ geometric: failing });

  const fit = estimator.fit({});

  assert.equal(fit.ok, false);
  assert.equal(estimator.isFitted(), false);
  assert.equal(estimator.predict({ geometric: {} }), null);
});

test('Levenberg-Marquardt fits a nonlinear curve', () => {
  const xs = [0, 0.5, 1, 1.5, 2, 2.5, 3];
  const ys = xs.map((x) => 2.5 * Math.exp(-1.3 * x) + 0.4);
  const residuals = ([a, b, c]) => xs.map((x, i) => a * Math.exp(-b * x) + c - ys[i]);

  const { params, cost } = UX.numeric.levenbergMarquardt(residuals, [1, 1, 0]);

  assert.ok(cost < 1e-12);
  assert.ok(Math.abs(params[0] - 2.5) < 1e-5 && Math.abs(params[1] - 1.3) < 1e-5);
});

test('percentiles interpolate between neighbours', () => {
  assert.equal(UX.numeric.median([5, 1, 3]), 3);
  assert.equal(UX.numeric.median([4, 1, 3, 2]), 2.5);
  assert.equal(UX.numeric.percentile([0, 10], 0.9), 9);
  assert.equal(UX.numeric.median([]), null);
});

test('the One Euro filter steadies a fixation and follows a saccade quickly', () => {
  const filter = UX.createOneEuroFilter({ minCutoff: 0.5, beta: 0.003 });
  const random = seeded(9);
  let t = 0;
  let last = null;
  const raw = [];
  const steady = [];
  for (let k = 0; k < 90; k += 1) {
    t += 33;
    const point = { x: 400 + (random() - 0.5) * 60, y: 300 + (random() - 0.5) * 60 };
    last = filter.next(t, point);
    if (k >= 30) {
      raw.push(point);
      steady.push(last);
    }
  }
  const rms = (points) => Math.sqrt(points.reduce((sum, p) => sum + (p.x - 400) ** 2 + (p.y - 300) ** 2, 0) / points.length);
  assert.ok(rms(steady) < 0.45 * rms(raw), `fixation RMS ${rms(steady).toFixed(1)} px from ${rms(raw).toFixed(1)} px`);

  // Salto de 600 px: a los 100 ms ya debe haber recorrido la mayor parte.
  for (let k = 0; k < 3; k += 1) {
    t += 33;
    last = filter.next(t, { x: 1000, y: 300 });
  }
  assert.ok(last.x > 950, `after a saccade the filter is at x = ${last.x.toFixed(0)}`);

  filter.reset();
  assert.deepEqual(filter.next(t + 33, { x: 5, y: 6 }), { x: 5, y: 6 });
  assert.throws(() => UX.createOneEuroFilter({ minCutoff: 0, beta: 0 }), /invalid One Euro/);
});

/** Monitor calibrado con un rango de cabeza de ±10° y ojos de apertura 0,3. */
function calibratedMonitor() {
  const monitor = UX.createGazeMonitor({ blinkThreshold: 0.45, headMarginDeg: 12, offScreenMarginPx: 120 });
  monitor.calibrate({ yaw: [-10, 10], pitch: [-15, 5], open: 0.3, viewport: VIEWPORT });
  return monitor;
}

/** Cuadro normal mirando el centro de la pantalla. */
const looking = (t, changes = {}) => ({
  t,
  face: true,
  calibrated: true,
  blink: 0.05,
  open: 0.3,
  yaw: 0,
  pitch: -5,
  refined: 2,
  point: { x: 640, y: 360 },
  ...changes,
});

test('the monitor tells looking at the screen from blinking, looking away and losing the face', () => {
  const monitor = calibratedMonitor();

  assert.deepEqual(monitor.assess(looking(0)), { state: 'on_screen', confidence: 1 });
  assert.equal(monitor.assess(looking(33, { blink: 0.8 })).state, 'blink');
  assert.equal(monitor.assess(looking(66, { open: 0.1 })).state, 'blink');
  // Mirar el teclado: la cabeza baja más de 12° por debajo de lo calibrado, o el punto cae muy abajo.
  assert.equal(monitor.assess(looking(99, { pitch: -35 })).state, 'off_screen');
  assert.equal(monitor.assess(looking(132, { point: { x: 640, y: 1100 } })).state, 'off_screen');
  assert.equal(monitor.assess(looking(165, { face: false })).state, 'no_face');
  assert.equal(monitor.assess(looking(198, { calibrated: false })).state, 'uncalibrated');
});

test('the monitor lowers the confidence just after coming back, outside the calibrated pose and without refined irises', () => {
  const monitor = calibratedMonitor();
  monitor.assess(looking(0, { pitch: -40 }));

  const back = monitor.assess(looking(33));
  const settled = monitor.assess(looking(300));
  const tilted = monitor.assess(looking(333, { yaw: 18 }));
  const rough = monitor.assess(looking(366, { refined: 0 }));

  assert.deepEqual(back, { state: 'low_confidence', confidence: 0.5 });
  assert.equal(settled.state, 'on_screen');
  // 8° fuera del rango, con 12° de margen: 1 − 0,6 · 8 / 12 = 0,6.
  assert.deepEqual(tilted, { state: 'low_confidence', confidence: 0.6 });
  assert.deepEqual(rough, { state: 'low_confidence', confidence: 0.6 });
});

test('coming back from a blink does not count as coming back from looking away', () => {
  const monitor = calibratedMonitor();
  monitor.assess(looking(0));
  monitor.assess(looking(33, { blink: 0.9 }));

  assert.deepEqual(monitor.assess(looking(66)), { state: 'on_screen', confidence: 1 });
});

test('the combined estimator passes the screen only to the candidates that use it', () => {
  const screens = [];
  const geometric = { ...UX.createGazeModel(), configure: (screen) => screens.push(screen) };
  const estimator = UX.createGazeEstimator({ geometric, appearance: UX.createGazeModel() });

  estimator.configure({ cssPxPerCm: 40 });

  assert.deepEqual(screens, [{ cssPxPerCm: 40 }]);
});

test('the geometric model refuses a screen without a positive density', () => {
  const model = UX.createGeometricModel({ cssPxPerCm: 36 });

  assert.throws(() => model.configure({ cssPxPerCm: 0 }), /cssPxPerCm must be positive/);
  model.configure({ cssPxPerCm: 50 });
});
