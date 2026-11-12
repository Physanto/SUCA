/**
 * @file Punto de composición del motor de la cámara, en el documento offscreen.
 *
 * Abre la webcam una sola vez, analiza cada cuadro con MediaPipe Face
 * Landmarker (rostro y puntos de los ojos) y le pasa el resultado al motor
 * (`engine.js`), que lo entrega a la pestaña evaluada. Los cuadros se leen con
 * `MediaStreamTrackProcessor` porque un documento offscreen no se dibuja y no
 * recibe `requestVideoFrameCallback`.
 *
 * Por cada cuadro: MediaPipe da los puntos del rostro, la pose y los valores
 * faciales; de cada ojo se recorta solo su rectángulo, a la resolución de la
 * cámara, para refinar el iris (`iris-refine.js`) y calcular su parche de
 * apariencia. Con eso se arman las características de los dos estimadores de
 * mirada, las señales del monitor (parpadeo, apertura, pose, iris refinados) y
 * los números del lote `gaze_features`.
 *
 * La webcam se pide a `camera.video_width` × `camera.video_height` (1080p): a
 * 640 × 480, un grado de mirada mueve el iris menos de un quinto de píxel. Unos
 * segundos después de abrirla se fijan su exposición, foco y balance de blancos
 * (`camera.lock_exposure`), si la webcam lo permite.
 *
 * Privacidad: cada cuadro se analiza aquí y se cierra enseguida. Solo salen
 * números (valores faciales, pose de la cabeza, posición de los iris y el
 * punto estimado de la mirada); ningún píxel sale de este documento.
 *
 * Estados (`camera.status`, al panel lateral): `active` cuando llegan cuadros,
 * `no_permission` si Chrome niega la cámara, `error` ante cualquier otro fallo.
 * Sin permiso o con error, se reintenta solo. Sin WebGL queda en `error` sin
 * abrir la webcam ni reintentar (ver `webgl.js`).
 */

import { FaceLandmarker } from '../lib/vision_bundle.mjs';

const { UX } = globalThis;

/** Espera entre reintentos de abrir la cámara, en milisegundos. */
const RETRY_MS = 5000;
/** Ancho máximo del recorte de cada ojo: más no mejora el borde del iris y cuesta más. */
const MAX_EYE_CROP_WIDTH = 200;
/** Espera tras abrir la cámara antes de fijar su exposición: deja que el ajuste automático se asiente. */
const LOCK_EXPOSURE_AFTER_MS = 3000;
/** Nombre de la conexión de las pestañas con el motor. */
const PORT_NAME = 'camera';
/** Errores de `getUserMedia` que significan "sin permiso". */
const PERMISSION_ERRORS = ['NotAllowedError', 'SecurityError'];

const { config, contracts, clock, platform, messages } = UX;
const camera = config.camera;
const faceValueNames = contracts.enums.face_value;
const { eyeBoxes, eyePatch, irisOffsets, featureVector, irisSeeds, eyeLids, eyeCrop, eyeGeometry } = UX.eyeFeatures;
const { faceValues, headPose, faceFraming } = UX.faceFeatures;
const { grayscale, refineIris } = UX.irisRefine;

let delegate = null;
/** Resolución y cuadros por segundo que la webcam entrega de verdad, y si se fijó su exposición. */
let video = null;
let exposureLocked = null;
const engine = UX.createCameraEngine({
  clock,
  estimator: UX.createGazeEstimator({
    geometric: UX.createGeometricModel({ cssPxPerCm: camera.css_px_per_cm }),
    appearance: UX.createGazeModel(),
  }, { headMarginDeg: camera.head_range_margin_deg, hybrid: camera.gaze_hybrid }),
  monitor: UX.createGazeMonitor({
    blinkThreshold: camera.blink_threshold,
    headMarginDeg: camera.head_range_margin_deg,
    offScreenMarginPx: camera.off_screen_margin_px,
  }),
  filter: UX.createOneEuroFilter({ minCutoff: camera.filter_min_cutoff_hz, beta: camera.filter_beta }),
  blinkThreshold: camera.blink_threshold,
  onStatus: (status) => {
    messages.send(messages.types.CAMERA_STATUS, { status }).catch(() => {
      // Nadie escucha (el panel está cerrado): el estado se vuelve a enviar al cambiar.
    });
  },
  info: () => ({ delegate, benchmark_ms: { ...benchmark }, video, exposure_locked: exposureLocked }),
});

platform.onConnect(PORT_NAME, (port) => {
  const link = engine.connect({ post: (message) => port.post(message) });
  port.onMessage((message) => link.receive(message));
  port.onDisconnect(() => link.disconnect());
});

/** Cuadros que se miden con cada procesador antes de elegir entre GPU y CPU. */
const BENCHMARK_FRAMES = 20;
/** Si la GPU analiza un cuadro en menos que esto, no se prueba la CPU. */
const FAST_ENOUGH_MS = 25;

/** Archivos de WebAssembly de MediaPipe, servidos por la extensión. */
const FILESET = {
  wasmLoaderPath: platform.extensionUrl('lib/vision_wasm_internal.js'),
  wasmBinaryPath: platform.extensionUrl('lib/vision_wasm_internal.wasm'),
};

/** Mediana de una lista de números. */
function median(values) {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[sorted.length >> 1];
}

/** Carga Face Landmarker con un procesador (`GPU` o `CPU`). */
function createLandmarker(processor) {
  return FaceLandmarker.createFromOptions(FILESET, {
    baseOptions: {
      modelAssetPath: platform.extensionUrl('lib/face_landmarker.task'),
      delegate: processor,
    },
    runningMode: 'VIDEO',
    numFaces: 1,
    outputFaceBlendshapes: true,
    outputFacialTransformationMatrixes: true,
  });
}

/** Tiempo medio por cuadro de cada procesador probado, para las estadísticas. */
const benchmark = {};

/**
 * Adaptador de MediaPipe Face Landmarker (`FaceProvider`): carga el modelo
 * desde `lib/` y analiza un cuadro.
 *
 * Empieza con la GPU. Según la computadora, la GPU puede ser más lenta que la
 * CPU (por ejemplo, sin aceleración gráfica): si sus primeros cuadros tardan
 * más de `FAST_ENOUGH_MS`, carga también la CPU, la mide con los cuadros
 * siguientes y se queda con la más rápida. Si la GPU no carga, usa la CPU.
 *
 * Las dos opciones necesitan WebGL: MediaPipe recibe cada cuadro como una
 * textura WebGL aunque analice con la CPU. Por eso `main` comprueba WebGL antes
 * de llegar aquí; la CPU no es una alternativa a la falta de WebGL.
 *
 * @returns {Promise<{detect: function(VideoFrame, number): object}>} Analizador.
 */
async function createFaceProvider() {
  const landmarkers = {};
  let current = null;
  let lastError = null;
  for (const processor of ['GPU', 'CPU']) {
    try {
      landmarkers[processor] = await createLandmarker(processor);
      current = processor;
      break;
    } catch (error) {
      lastError = error;
      console.warn(`face landmarker could not start with ${processor}:`, error);
    }
  }
  if (current === null) {
    throw lastError;
  }
  delegate = current;
  const timings = { GPU: [], CPU: [] };
  let decided = current === 'CPU';
  let loadingCpu = false;

  /** Usa un procesador y libera el otro. */
  function settle(chosen) {
    const other = chosen === 'GPU' ? 'CPU' : 'GPU';
    if (landmarkers[other]) {
      landmarkers[other].close();
      delete landmarkers[other];
    }
    current = chosen;
    delegate = chosen;
    decided = true;
    console.info(`face landmarker uses ${chosen}`, benchmark);
  }

  /** Decide con lo medido hasta ahora; puede pedir que se pruebe la CPU. */
  function decide() {
    benchmark[current] = median(timings[current]);
    if (current === 'GPU') {
      if (benchmark.GPU <= FAST_ENOUGH_MS) {
        settle('GPU');
      } else if (!loadingCpu) {
        loadingCpu = true;
        createLandmarker('CPU').then(
          (landmarker) => {
            landmarkers.CPU = landmarker;
            current = 'CPU';
            delegate = 'CPU';
          },
          () => settle('GPU'),
        );
      }
      return;
    }
    settle(benchmark.CPU < benchmark.GPU ? 'CPU' : 'GPU');
  }

  return {
    /** Analiza un cuadro; `timestampMs` debe crecer en cada llamada. */
    detect(frame, timestampMs) {
      const processor = current;
      const start = performance.now();
      const result = landmarkers[processor].detectForVideo(frame, timestampMs);
      if (!decided && !(processor === 'GPU' && loadingCpu)) {
        timings[processor].push(performance.now() - start);
        if (timings[processor].length >= BENCHMARK_FRAMES) {
          decide();
        }
      }
      return result;
    },
  };
}

/** Redondea para no enviar ruido numérico. */
const round = (value, digits) => (value === null || value === undefined ? null : Number(value.toFixed(digits)));

/** Promedio de los valores que existen, o `null`. */
function mean(values) {
  const present = values.filter((value) => Number.isFinite(value));
  return present.length ? present.reduce((sum, value) => sum + value, 0) / present.length : null;
}

/** Píxeles RGBA de un rectángulo de una imagen RGBA. */
function subImage(rgba, width, box) {
  const out = new Uint8ClampedArray(box.width * box.height * 4);
  for (let y = 0; y < box.height; y += 1) {
    const from = ((box.y + y) * width + box.x) * 4;
    out.set(rgba.subarray(from, from + box.width * 4), y * box.width * 4);
  }
  return out;
}

/**
 * Recorta un ojo del cuadro (solo ese rectángulo, nunca el cuadro completo), refina
 * su iris y calcula su parche de apariencia.
 *
 * @param {VideoFrame} frame - Cuadro.
 * @param {OffscreenCanvasRenderingContext2D} canvas - Lienzo pequeño para el recorte.
 * @param {object} eye - `crop` (caja en el cuadro), `seed` (iris de MediaPipe), `lids` y
 *   `box` (caja del parche de apariencia, o `null`), en píxeles del cuadro.
 * @returns {{iris: {x: number, y: number}, refined: boolean, patch: (number[]|null)}} Iris en
 *   píxeles del cuadro, si se refinó, y parche.
 */
function readEye(frame, canvas, { crop, seed, lids, box }) {
  const scale = Math.min(1, MAX_EYE_CROP_WIDTH / crop.width);
  const width = Math.max(1, Math.round(crop.width * scale));
  const height = Math.max(1, Math.round(crop.height * scale));
  // El lienzo solo crece: los dos ojos lo comparten sin reservar memoria en cada cuadro.
  if (canvas.canvas.width < width || canvas.canvas.height < height) {
    canvas.canvas.width = Math.max(canvas.canvas.width, width);
    canvas.canvas.height = Math.max(canvas.canvas.height, height);
  }
  canvas.drawImage(frame, crop.x, crop.y, crop.width, crop.height, 0, 0, width, height);
  const { data } = canvas.getImageData(0, 0, width, height);
  // El lienzo se borra para que la imagen no quede en memoria más de lo necesario.
  canvas.clearRect(0, 0, width, height);
  const toCrop = (p) => ({ x: (p.x - crop.x) * scale, y: (p.y - crop.y) * scale });
  const refined = refineIris(
    grayscale(data, width, height),
    width,
    height,
    { ...toCrop(seed), r: seed.r * scale },
    { upper: lids.upper.map(toCrop), lower: lids.lower.map(toCrop) },
  );
  let patch = null;
  if (box) {
    const inner = {
      x: Math.max(0, Math.floor((box.x - crop.x) * scale)),
      y: Math.max(0, Math.floor((box.y - crop.y) * scale)),
    };
    inner.width = Math.max(1, Math.min(width - inner.x, Math.round(box.width * scale)));
    inner.height = Math.max(1, Math.min(height - inner.y, Math.round(box.height * scale)));
    patch = eyePatch(subImage(data, width, inner), inner.width, inner.height);
  }
  return {
    iris: { x: crop.x + refined.x / scale, y: crop.y + refined.y / scale },
    refined: refined.ok,
    patch,
  };
}

/**
 * Analiza un cuadro: valores faciales, pose de la cabeza, encuadre del rostro y
 * características de los ojos para los dos estimadores de mirada y el monitor.
 *
 * @param {object} result - Resultado de Face Landmarker.
 * @param {VideoFrame} frame - Cuadro analizado.
 * @param {OffscreenCanvasRenderingContext2D} canvas - Lienzo para recortar los ojos.
 * @returns {{face: (object|null), features: (object|null)}} Datos del cuadro.
 */
function readFrame(result, frame, canvas) {
  if (!result.faceLandmarks || result.faceLandmarks.length === 0) {
    return { face: null, features: null };
  }
  const landmarks = result.faceLandmarks[0];
  const pose = headPose(result.facialTransformationMatrixes[0].data);
  const values = faceValues(result.faceBlendshapes[0].categories, faceValueNames);
  if (Object.keys(values).length === 0) {
    return { face: null, features: null };
  }
  const face = {
    values,
    head_yaw: pose.yaw,
    head_pitch: pose.pitch,
    framing: faceFraming(landmarks, pose, camera.distance_scale),
  };
  const width = frame.displayWidth;
  const height = frame.displayHeight;
  const seeds = irisSeeds(landmarks, width, height);
  const boxes = eyeBoxes(landmarks, width, height);
  const eyes = {};
  for (const side of ['left', 'right']) {
    const crop = eyeCrop(landmarks, side, seeds[side], width, height);
    eyes[side] = crop
      ? readEye(frame, canvas, { crop, seed: seeds[side], lids: eyeLids(landmarks, side, width, height), box: boxes && boxes[side] })
      : { iris: seeds[side], refined: false, patch: null };
  }
  const geometry = eyeGeometry(landmarks, { left: eyes.left.iris, right: eyes.right.iris }, width, height);
  const distance = Math.abs(pose.tz) * camera.distance_scale;
  // Basta con un ojo cerrado: un guiño o un párpado caído también tapan el iris.
  const blinks = [values.eye_blink_left, values.eye_blink_right].filter(Number.isFinite);
  const blink = blinks.length ? Math.min(1, Math.max(0, ...blinks)) : null;
  const open = mean([geometry.left.open, geometry.right.open]);
  const geometric = {
    yaw: pose.yaw,
    pitch: pose.pitch,
    distance,
    eyeU: geometry.u,
    eyeV: geometry.v,
    aspect: width / height,
    h: mean([geometry.left.h, geometry.right.h]),
    v: mean([geometry.left.v, geometry.right.v]),
    open,
  };
  const appearance =
    eyes.left.patch && eyes.right.patch
      ? featureVector({ left: eyes.left.patch, right: eyes.right.patch, iris: irisOffsets(landmarks, width, height), head: pose })
      : null;
  const refined = Number(eyes.left.refined) + Number(eyes.right.refined);
  return {
    face,
    features: {
      geometric,
      appearance,
      signals: { blink, open, yaw: pose.yaw, pitch: pose.pitch, refined },
      // Números del lote gaze_features: solo la zona de los ojos y la pose, nunca imágenes.
      record: {
        face_detected: true,
        head_yaw: round(pose.yaw, 2),
        head_pitch: round(pose.pitch, 2),
        head_roll: round(pose.roll, 2),
        head_tx: round(pose.tx, 2),
        head_ty: round(pose.ty, 2),
        head_tz: round(pose.tz, 2),
        distance_cm: round(distance, 2),
        eye_u: round(geometry.u, 5),
        eye_v: round(geometry.v, 5),
        aspect: round(width / height, 5),
        left_h: round(geometry.left.h, 5),
        left_v: round(geometry.left.v, 5),
        left_open: round(geometry.left.open, 5),
        left_refined: eyes.left.refined,
        right_h: round(geometry.right.h, 5),
        right_v: round(geometry.right.v, 5),
        right_open: round(geometry.right.open, 5),
        right_refined: eyes.right.refined,
        blink: round(blink, 4),
      },
    },
  };
}

/**
 * Fija la exposición, el foco y el balance de blancos de la webcam en los valores a
 * los que llegó su ajuste automático, para que la imagen de los ojos no cambie con
 * la luz de la pantalla. Solo lo que la webcam permite; si no permite nada, sigue
 * en automático.
 *
 * @param {MediaStreamTrack} track - Pista de video.
 * @returns {Promise<boolean>} Si se fijó algo.
 */
async function lockExposure(track) {
  const capabilities = typeof track.getCapabilities === 'function' ? track.getCapabilities() : {};
  const settings = track.getSettings();
  const constraints = {};
  const lock = (mode, value) => {
    if ((capabilities[mode] || []).includes('manual')) {
      constraints[mode] = 'manual';
      if (value in capabilities && settings[value] !== undefined) {
        constraints[value] = settings[value];
      }
    }
  };
  lock('exposureMode', 'exposureTime');
  lock('focusMode', 'focusDistance');
  lock('whiteBalanceMode', 'colorTemperature');
  if (Object.keys(constraints).length === 0) {
    return false;
  }
  try {
    await track.applyConstraints({ advanced: [constraints] });
    return true;
  } catch (error) {
    console.warn('camera exposure could not be locked:', error);
    return false;
  }
}

/**
 * Abre la cámara y analiza cuadros hasta que la pista termine.
 *
 * @param {object} provider - Analizador de `createFaceProvider`.
 * @returns {Promise<void>} Se cumple cuando la cámara deja de entregar cuadros.
 */
async function runCamera(provider) {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: false,
    video: {
      width: { ideal: camera.video_width },
      height: { ideal: camera.video_height },
      frameRate: { ideal: camera.gaze_hz },
    },
  });
  const [track] = stream.getVideoTracks();
  const { width, height, frameRate } = track.getSettings();
  video = { width, height, frame_rate: frameRate };
  console.info('camera delivers', video);
  exposureLocked = null;
  if (camera.lock_exposure) {
    setTimeout(() => {
      if (track.readyState === 'live') {
        lockExposure(track).then((locked) => {
          exposureLocked = locked;
        });
      }
    }, LOCK_EXPOSURE_AFTER_MS);
  }
  const reader = new MediaStreamTrackProcessor({ track, maxBufferSize: 1 }).readable.getReader();
  // Lienzo pequeño: solo recibe el recorte de un ojo a la vez, nunca el cuadro completo.
  const canvas = new OffscreenCanvas(1, 1).getContext('2d', { willReadFrequently: true });
  const minIntervalMs = 1000 / camera.gaze_hz;
  let lastT = -Infinity;
  engine.setStatus('active');
  try {
    for (;;) {
      const { value: frame, done } = await reader.read();
      if (done) {
        return;
      }
      const t = clock.now();
      // Una cámara más rápida que la frecuencia configurada no se analiza de más.
      if (t - lastT < minIntervalMs * 0.8) {
        frame.close();
        continue;
      }
      lastT = t;
      try {
        const result = provider.detect(frame, performance.now());
        const { face, features } = readFrame(result, frame, canvas);
        engine.frame({ t, processedAt: clock.now(), face, features });
      } finally {
        frame.close();
      }
    }
  } finally {
    track.stop();
  }
}

/** Estado que corresponde a un error al abrir la cámara. */
const statusOf = (error) => (PERMISSION_ERRORS.includes(error && error.name) ? 'no_permission' : 'error');

/** Espera unos milisegundos, o hasta que Chrome avise que cambió el permiso. */
function waitForRetry(permission) {
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, RETRY_MS);
    if (permission) {
      permission.onchange = () => {
        clearTimeout(timer);
        resolve();
      };
    }
  });
}

/** Crea un lienzo para la comprobación de WebGL. */
const createCanvas = () =>
  typeof OffscreenCanvas === 'function' ? new OffscreenCanvas(1, 1) : document.createElement('canvas');

/** Mantiene la cámara funcionando mientras exista este documento. */
async function main() {
  // Sin WebGL, MediaPipe falla en cada cuadro y la cámara se encendería y apagaría en
  // cada reintento. Activar la aceleración exige reiniciar Chrome, así que no se reintenta:
  // la cámara no se abre y la próxima sesión vuelve a comprobarlo.
  if (!UX.webglAvailable(createCanvas)) {
    console.error(
      'camera disabled: WebGL is not available; enable hardware acceleration in chrome://settings/system, ' +
        'relaunch Chrome and check chrome://gpu',
    );
    engine.setStatus('error');
    return;
  }
  let permission = null;
  try {
    permission = await navigator.permissions.query({ name: 'camera' });
  } catch {
    // Sin la API de permisos solo se reintenta por tiempo.
  }
  let provider;
  try {
    provider = await createFaceProvider();
  } catch (error) {
    console.error('face landmarker failed to load:', error);
    engine.setStatus('error');
    return;
  }
  for (;;) {
    try {
      await runCamera(provider);
      console.warn('camera track ended; reopening');
      engine.setStatus('error');
    } catch (error) {
      console.warn('camera could not start:', error);
      engine.setStatus(statusOf(error));
    }
    await waitForRetry(permission);
  }
}

main();
