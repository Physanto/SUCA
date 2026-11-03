/**
 * @file Punto de composición del motor de la cámara, en el documento offscreen.
 *
 * Abre la webcam una sola vez, analiza cada cuadro con MediaPipe Face
 * Landmarker (rostro y puntos de los ojos) y le pasa el resultado al motor
 * (`engine.js`), que lo entrega a la pestaña evaluada. Los cuadros se leen con
 * `MediaStreamTrackProcessor` porque un documento offscreen no se dibuja y no
 * recibe `requestVideoFrameCallback`.
 *
 * Privacidad: cada cuadro se analiza aquí y se cierra enseguida. Solo salen
 * números (valores faciales, orientación de la cabeza y el punto estimado de
 * la mirada); ningún píxel sale de este documento.
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
/** Suavizado de la mirada: peso del punto nuevo. */
const GAZE_SMOOTHING = 0.35;
/** Nombre de la conexión de las pestañas con el motor. */
const PORT_NAME = 'camera';
/** Errores de `getUserMedia` que significan "sin permiso". */
const PERMISSION_ERRORS = ['NotAllowedError', 'SecurityError'];

const { config, contracts, clock, platform, messages } = UX;
const faceValueNames = contracts.enums.face_value;
const { eyeBoxes, eyePatch, irisOffsets, featureVector } = UX.eyeFeatures;
const { faceValues, headPose } = UX.faceFeatures;

let delegate = null;
const engine = UX.createCameraEngine({
  clock,
  gazeModel: UX.createGazeModel(),
  smoother: UX.createSmoother(GAZE_SMOOTHING),
  onStatus: (status) => {
    messages.send(messages.types.CAMERA_STATUS, { status }).catch(() => {
      // Nadie escucha (el panel está cerrado): el estado se vuelve a enviar al cambiar.
    });
  },
  info: () => ({ delegate, benchmark_ms: { ...benchmark } }),
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

/**
 * Analiza un cuadro: valores faciales, orientación de la cabeza y
 * características de los ojos para la mirada.
 *
 * @param {object} result - Resultado de Face Landmarker.
 * @param {VideoFrame} frame - Cuadro analizado.
 * @param {OffscreenCanvasRenderingContext2D} canvas - Lienzo para recortar los ojos.
 * @returns {{face: (object|null), features: (number[]|null)}} Datos del cuadro.
 */
function readFrame(result, frame, canvas) {
  if (!result.faceLandmarks || result.faceLandmarks.length === 0) {
    return { face: null, features: null };
  }
  const landmarks = result.faceLandmarks[0];
  const pose = headPose(result.facialTransformationMatrixes[0].data);
  const values = faceValues(result.faceBlendshapes[0].categories, faceValueNames);
  const face =
    Object.keys(values).length === 0
      ? null
      : { values, head_yaw: pose.yaw, head_pitch: pose.pitch };
  const width = frame.displayWidth;
  const height = frame.displayHeight;
  const boxes = eyeBoxes(landmarks, width, height);
  if (face === null || boxes === null) {
    return { face, features: null };
  }
  if (canvas.canvas.width !== width || canvas.canvas.height !== height) {
    canvas.canvas.width = width;
    canvas.canvas.height = height;
  }
  canvas.drawImage(frame, 0, 0, width, height);
  const [left, right] = [boxes.left, boxes.right].map((box) => {
    const pixels = canvas.getImageData(box.x, box.y, box.width, box.height);
    return eyePatch(pixels.data, box.width, box.height);
  });
  // El lienzo se borra para que la imagen no quede en memoria más de lo necesario.
  canvas.clearRect(0, 0, width, height);
  const features = featureVector({ left, right, iris: irisOffsets(landmarks, width, height), head: pose });
  return { face, features };
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
      width: { ideal: config.camera.video_width },
      height: { ideal: config.camera.video_height },
      frameRate: { ideal: config.camera.gaze_hz },
    },
  });
  const [track] = stream.getVideoTracks();
  const reader = new MediaStreamTrackProcessor({ track, maxBufferSize: 1 }).readable.getReader();
  const canvas = new OffscreenCanvas(1, 1).getContext('2d', { willReadFrequently: true });
  const minIntervalMs = 1000 / config.camera.gaze_hz;
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
