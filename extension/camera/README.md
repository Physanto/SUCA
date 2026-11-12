# Cámara: mirada, rostro y calibración

Estima hacia dónde mira el participante y registra sus movimientos faciales con una sola webcam. **Solo guarda números: ningún cuadro de video sale del navegador.**

## Cómo está armada

```
 Pestaña evaluada (content scripts)            Documento offscreen de la extensión
 ┌──────────────────────────────────┐          ┌──────────────────────────────────────┐
 │ content/camera.js                │  conexión│ camera/engine.html                   │
 │  · muestras gaze (zona, estado)  │◄─────────┤  engine-main.mjs: webcam 1080p →     │
 │  · muestras face, gaze_features  │ "camera" │    MediaPipe → ojos recortados →     │
 │  · eventos camera_gap            ├─────────►│    iris refinado → características   │
 │ content/calibration.js           │ pedidos  │  engine.js: estimador, monitor,      │
 │  · puntos, punto en movimiento,  │          │    filtro, deriva, huecos            │
 │    cabeza, validación, deriva    │          │                                      │
 └───────────────┬──────────────────┘          └──────────────────┬───────────────────┘
                 │ lotes gaze, face, gaze_features, calibration,  │ camera.status
                 │ gaze_target, events                            │
                 ▼                                                ▼
           service worker ──► servidor                      panel lateral
```

- **El motor vive en un documento offscreen** (`camera/engine.html`), no en la página. El worker lo crea al empezar la sesión y lo cierra al terminarla, lo que apaga la cámara. Como no se recarga al navegar:
  - la cámara se abre **una sola vez** por sesión y el permiso es de la extensión, no de cada sitio;
  - el modelo de mirada entrenado en la calibración sigue sirviendo después de cada navegación;
  - MediaPipe carga sus archivos de WebAssembly desde la extensión, sin depender de la política de seguridad de cada sitio.
- **Un solo modelo de rostro.** MediaPipe Face Landmarker da, por cada cuadro, los 478 puntos del rostro (incluidos los iris), los valores de los movimientos faciales y la pose de la cabeza. La mirada se calcula con esos mismos puntos más el iris refinado en la imagen de alta resolución (ver "Mirada"), así que no hay un segundo modelo de rostro corriendo en paralelo.
- **GPU o CPU, según la computadora.** El motor empieza con la GPU y mide sus primeros 20 cuadros. Si tarda más de 25 ms por cuadro, carga también la CPU, la mide y se queda con la más rápida (en Chrome sin aceleración gráfica, la GPU simulada puede ser cinco veces más lenta). La elección se ve en `stats` (`delegate`, `benchmark_ms`). **Las dos necesitan WebGL**: MediaPipe recibe cada cuadro como una textura WebGL aunque analice con la CPU (ver "Preparación de la computadora").
- **Adaptadores.** `createFaceProvider` (en `engine-main.mjs`) es el único lugar que conoce a MediaPipe. El estimador de mirada (`gaze-estimator.js`) recibe sus candidatos inyectados: cambiar de librería o agregar un estimador no toca ni la pestaña ni el motor.

## Archivos

| Archivo | Dónde corre | Qué hace |
|---|---|---|
| `camera/engine.html` | Offscreen | Carga las utilidades comunes, las piezas de cálculo y `engine-main.mjs` |
| `camera/engine-main.mjs` | Offscreen | Punto de composición: abre la webcam a 1080p, fija su exposición, lee cada cuadro con `MediaStreamTrackProcessor`, lo analiza con MediaPipe, recorta solo los ojos para refinar los iris y arma las características. Reintenta si la cámara falla o falta el permiso |
| `camera/engine.js` | Offscreen | Motor sin dependencias del navegador: conexiones con la pestaña; estimación, monitor y filtro de la mirada; pedidos de la calibración (puntos, punto en movimiento, ajuste, deriva); intervalos sin datos y estadísticas |
| `camera/numeric.js` | Offscreen | Álgebra: sistemas simétricos, Levenberg-Marquardt, mediana y percentiles |
| `camera/iris-refine.js` | Offscreen | Centro del iris con precisión sub-píxel: bordes del iris a lo largo de rayos y círculo ajustado con RANSAC |
| `camera/eye-features.js` | Offscreen | Características de los ojos: semillas del iris, párpados, recorte, posición del iris en anchos de ojo (geométrico) y parches de 10 × 6 (apariencia) |
| `camera/gaze-geometry.js` | Offscreen | Estimador geométrico: pose de la cabeza más giro del ojo, rayo cortado con la pantalla, 11 parámetros por persona |
| `camera/gaze-model.js` | Offscreen | Estimador por apariencia (ridge sobre los parches, como WebGazer) y la ridge que corrige el residuo del geométrico |
| `camera/gaze-estimator.js` | Offscreen | Estimador combinado: entrena los dos y usa el de menor error en validación cruzada |
| `camera/gaze-monitor.js` | Offscreen | Estado y confianza de cada cuadro: en pantalla, fuera, parpadeo, sin rostro |
| `camera/gaze-filter.js` | Offscreen | Filtro One Euro |
| `camera/webgl.js` | Offscreen | Comprueba que se puede crear un contexto WebGL antes de abrir la webcam |
| `camera/face-features.js` | Offscreen | Valores faciales del contrato desde los de MediaPipe, y pose de la cabeza desde la matriz de transformación |
| `camera/strings.js` | Pestaña y página del permiso | Textos visibles de la calibración y del permiso, en español |
| `camera/permission.html`, `permission.js` | Pestaña de la extensión | Pide el permiso de cámara una vez por computadora |
| `content/camera.js` | Pestaña evaluada | Módulo `camera`: conexión con el motor y registro de `gaze`, `face`, `gaze_features` y `camera_gap` |
| `content/camera/zones.js` | Pestaña evaluada | Zona y selector del elemento de cada punto de mirada |
| `content/calibration.js` | Pestaña evaluada | Módulo `calibration`: capa de calibración, validación y comprobación de deriva; registra `calibration` y `gaze_target` |
| `lib/` | Offscreen | MediaPipe y su modelo (`lib/README.md`) |

## Preparación de la computadora

El documento offscreen no puede mostrar el aviso de permiso de Chrome. Por eso:

1. Al **instalar** la extensión se abre la página **"Permiso de cámara para SUCA"**: pulsa **Permitir la cámara** y elige **Permitir** en el aviso de Chrome. El permiso queda guardado para la extensión.
2. Si en una sesión la cámara informa `no_permission`, el worker vuelve a abrir esa página (una vez por sesión). Al dar el permiso, el motor lo detecta y arranca solo, sin reiniciar la sesión.
3. Si alguna vez se negó: en esa página, haz clic en el ícono de la cámara de la barra de direcciones (o en Configuración del sitio) y elige **Permitir**.
4. **WebGL activo.** Abre `chrome://gpu`: en **WebGL** y **WebGL2** debe decir *Hardware accelerated*. Si dice *Disabled* o *Unavailable*, activa **Usar la aceleración de gráficos cuando esté disponible** en `chrome://settings/system` y reinicia Chrome. Sin WebGL, MediaPipe carga pero falla en el primer cuadro, con la GPU y también con la CPU. Por eso el motor lo comprueba al arrancar: si no hay WebGL, no abre la webcam, informa `error` al panel y escribe en su consola `camera disabled: WebGL is not available…`. No reintenta, porque el cambio exige reiniciar Chrome; la sesión siguiente lo vuelve a comprobar.

## Qué se registra

| Lote | Cuándo | Contenido |
|---|---|---|
| `gaze` | A `camera.gaze_hz` (30 Hz), salvo durante la calibración | `x`, `y` en la ventana; `scroll_x`, `scroll_y`; `element_selector`; `zone`; `valid`; `state` y `confidence` del monitor |
| `gaze_features` | A `camera.gaze_hz`, **también durante la calibración**, si `camera.record_gaze_features` | Pose de la cabeza, distancia, punto medio de los ojos en la imagen, posición de cada iris y apertura de los párpados, parpadeo, estado, confianza y punto antes del filtro (`raw_x`, `raw_y`). Solo números de la zona de los ojos: ni imágenes ni la malla del rostro |
| `face` | A `camera.face_hz` (15 Hz) | Los valores de `face_value` (entre 0 y 1), `head_yaw` y `head_pitch` en grados, `face_detected` |
| `calibration` | Al terminar cada calibración, validación o comprobación de deriva | `type` (`initial`, `final`, `drift_check`), `error_px`, `error_deg`, `accepted`, `viewing_distance_cm`, `css_px_per_cm`, `precision_deg`, `return_error_deg`, `estimator`, `camera_delay_ms`; en `drift_check`, `corrected` y la corrección acumulada |
| `gaze_target` | Por cada punto mostrado en la capa | Tramo de tiempo, procedimiento, fase (`points`, `pursuit`, `head`, `validation`, `look_away`, `drift_check`) y posición (el recorrido, en el punto en movimiento) |
| `events` (`camera_gap`) | Cuando vuelven los datos, o al cerrar la sesión | Inicio (`t`), fin (`data.t_end`, `null` si no volvieron) y motivo (`navigation`, `no_permission`, `error`) |

Estados de una muestra `gaze` (`gaze_state`):
- `on_screen` / `low_confidence`: mira la pantalla. La confianza baja con el iris sin refinar, con la cabeza fuera del rango visto en la calibración (dentro de `camera.head_range_margin_deg`) y en los primeros 150 ms al volver de mirar fuera. `valid` es verdadero si además el punto cae dentro de la ventana;
- `off_screen`: mira fuera de la pantalla (el teclado, la habitación): la cabeza giró más allá del margen, o el punto cae a más de `camera.off_screen_margin_px` de la ventana. Sin `x` ni `y`;
- `blink`: ojos cerrados (`camera.blink_threshold`, o párpados mucho más cerrados que en la calibración);
- `no_face`, `uncalibrated`: sin rostro, o todavía sin calibración.

Una muestra que mira la pantalla pero cae fuera de la ventana (por ejemplo, en el panel lateral) guarda `x` e `y`, sin elemento ni zona, con `valid: false`.

**Zonas.** Primero la región semántica más cercana que contiene al elemento mirado: `search` (`role="search"` o `<search>`), `header`, `nav`, `main`, `aside`, `footer`, por etiqueta o por rol ARIA. Un `header` o `footer` dentro de `article`, `section`, `main`, `nav` o `aside` no cuenta, porque es de esa sección y no de la página. Si no hay región, una cuadrícula de 3 × 3 de la ventana (`grid_top_left` … `grid_bottom_right`). Las capturas de la pestaña registran además la disposición de la pantalla (lote `layout`, ver `extension/README.md`), con la que el análisis vuelve a asignar zona y elemento a la mirada reprocesada.

**Pantalla de `camera_gap`.** Solo origen y ruta, con el título vacío: la búsqueda y el fragmento pueden llevar lo que escribió el participante. El evento lo registra la página que recibe los datos de nuevo, así que tras una navegación lleva la pantalla nueva.

**Hora de cada muestra.** Es el momento en que el cuadro llegó al motor, con el reloj común (`UX.clock`), antes de analizarlo, así que el tiempo de análisis no atrasa las muestras (su mediana se ve en `stats.delay_ms`). Lo que sí las atrasa es la demora del sensor y del controlador de la webcam: la calibración inicial la mide con el punto en movimiento y la guarda en `camera_delay_ms` del registro `calibration`. Para que la limpieza la descuente, cópiala a `camera_delay_ms` de `analysis/parameters.yaml` después del piloto. **No copies `stats.delay_ms`:** la limpieza desplazaría la mirada y el rostro un tiempo que ya está descontado.

## Mirada

**Por qué así.** A 640 × 480 y 60 cm, mover la mirada 1° desplaza el iris unos 0,17 px en la imagen: ningún modelo baja de 4–5° con eso. A 1080p son ~0,5 px, alcanzables refinando el borde del iris con precisión sub-píxel. Y un modelo que no sabe dónde está la cabeza solo funciona si la persona no se mueve de la postura en que calibró.

Por cada cuadro:
1. **Iris refinado** (`iris-refine.js`). Se recorta solo cada ojo, a la resolución de la cámara (hasta 200 px de ancho). Desde el iris de MediaPipe se lanzan 48 rayos y en cada uno se busca el borde del iris contra la esclera (el mayor salto de oscuro a claro, con posición sub-píxel); se descartan los bordes sobre los párpados y se ajusta un círculo con RANSAC. Si no se puede, queda el de MediaPipe y la confianza baja. Con luz visible y ojos oscuros la pupila casi no se distingue del iris: por eso se usa el borde del iris.
2. **Dos estimadores** (`gaze-estimator.js`):
   - **Geométrico** (`gaze-geometry.js`): el ojo gira dentro de la cabeza en proporción al desplazamiento del iris (`h`, `v`, en anchos de ojo; la apertura de los párpados ayuda en vertical); la dirección suma el giro de la cabeza; el rayo sale del punto medio entre los ojos, ubicado en 3D con su posición en la imagen y la distancia, y se corta con el plano de la pantalla. 11 parámetros por persona, ajustados con Levenberg-Marquardt, más una ridge pequeña para el residuo si la validación cruzada dice que ayuda. Como sabe dónde está la cabeza, tolera inclinarse, acercarse o girar.
   - **Apariencia** (`gaze-model.js`): la ridge de antes, al estilo WebGazer, sobre los ojos reducidos a 10 × 6, el iris y la pose.

   La calibración entrena los dos y usa el de menor error en validación cruzada (dejando fuera un objetivo a la vez). El elegido se informa en `estimator`.
3. **Corrección de deriva**: el desplazamiento acumulado de las comprobaciones de deriva se suma al punto.
4. **Monitor** (`gaze-monitor.js`): estado y confianza (ver "Qué se registra").
5. **Filtro One Euro** (`gaze-filter.js`): suaviza mucho en una fijación y casi nada en un salto de la mirada. Se reinicia al volver de mirar fuera, para no mezclar el teclado con la página; en un parpadeo conserva su estado.

El modelo se entrena **solo** en la calibración: los clics de la sesión no lo modifican (eso mezclaría la interacción con la medición y sesgaría la comparación entre mirada e interacción). Las comprobaciones de deriva solo desplazan la mirada; no reentrenan.

Al cerrar la sesión, el análisis vuelve a estimar la mirada con todos los puntos conocidos (`analysis/README.md`, "Mirada").

## Calibración

El panel lateral envía `calibration.request` con `type`:

- **`initial`** (poco más de un minuto): pantalla de instrucciones con el encuadre, y tres partes:
  1. **13 puntos** (cuadrícula de 3 × 3 en el 10, 50 y 90 % y cuatro intermedios en el 30 y 70 %), en orden al azar. El participante mira cada uno y hace clic; se usan los cuadros desde 300 ms antes hasta 800 ms después del clic, sin parpadeos y sin los que se alejan de la mediana de su punto.
  2. **Punto en movimiento** (12 s, curva de Lissajous desde el centro, a una velocidad que se sigue con la vista). Se descarta el primer segundo. El motor busca el retraso (de 0 a 300 ms) que mejor alinea la mirada estimada con el punto: es `camera_delay_ms`. Con ese retraso, el recorrido se suma al entrenamiento.
  3. **Movimiento de cabeza** (8 s): el punto central fijo mientras la persona mueve la cabeza despacio. Separa la cabeza del ojo y fija el rango de posturas que el monitor considera "calibrado".

  Después, la validación.
- **`final`**: solo la validación, con el modelo de la inicial, para medir cuánto se degradó. No comprueba el encuadre.
- **`drift_check`** (unos segundos): tres puntos con clic (el centro y dos esquinas). El motor mide el error y, si `camera.drift_correction` lo permite y el error supera `camera.drift_correction_min_error_deg`, desplaza la mirada en el error medio. El panel la pide al terminar cada tarea del modo guiado (`camera.drift_check_between_tasks`) y con el botón "Comprobar la mirada".

**Validación:** 8 puntos sin clic (en el 20/80 % y 30/50/70 %, distintos de los de calibración): se espera 700 ms y se mide 1000 ms. Luego un noveno: el participante mira el teclado, cuenta hasta tres y vuelve al punto; la capa espera a que el monitor note la salida y la vuelta (hasta 6 s), deja pasar 300 ms y mide.

Resultado (registro `calibration`):
- `error_px`, `error_deg`: distancia media entre la mirada y el punto en todas las muestras, en píxeles CSS y en grados de ángulo visual (`atan(error_px / css_px_per_cm / distancia)`, con la distancia medida en la validación o, si no hay, `viewing_distance_cm`);
- `precision_deg`: temblor, la raíz cuadrática media de la distancia entre muestras consecutivas de cada punto;
- `return_error_deg`: error del punto al volver del teclado;
- `accepted`: `error_deg ≤ calibration_max_error_deg`;
- `estimator`, `camera_delay_ms` y, en `drift_check`, `corrected` y la corrección acumulada (`error_*` es siempre el de antes de corregir).

Cada punto mostrado queda en un lote `gaze_target`, para medir y reprocesar la mirada después.

## Encuadre

Antes de la calibración **inicial**, la pantalla de instrucciones comprueba que la persona esté bien ubicada, sin mostrar el video: una figura (cabeza y hombros) se mueve con ella como en un espejo, sobre un óvalo que marca dónde debería verse la cara (si está fuera del rango de distancias, el óvalo tiene el tamaño que tendría en el borde más cercano del rango). La figura es verde cuando todo está bien y naranja si no, y una lista dice qué corregir:

| Comprobación | Criterio | Indicación si falla |
|---|---|---|
| Rostro | Visible en al menos el 80 % de los cuadros del último segundo | "No se ve tu cara…" |
| Distancia | Entre `min_distance_cm` y `max_distance_cm` (de 35 a 75 cm): cada persona se sienta donde le es cómodo, porque la calibración mide su distancia | "Estás muy cerca / muy lejos (unos N cm)" |
| Centrado horizontal | El centro de la cara a menos del 15 % del ancho de la imagen del centro | "Muévete un poco hacia tu izquierda / derecha" |
| Centrado vertical | A menos del 20 % del alto | "Inclina la cámara un poco hacia arriba / abajo (en un portátil, la pantalla hacia atrás / adelante)" |
| De frente | Cabeza girada menos de 15° a un lado | "Gira la cabeza hacia la pantalla" |

La **inclinación vertical de la cabeza no se exige**: en un portátil la cámara está en el borde de la pantalla y la persona mira un poco hacia abajo. Lo que importa es que no cambie de postura después de calibrar.

**Comenzar** se habilita solo con todo bien. **Comenzar de todos modos** deja seguir al evaluador si la estimación falla (por ejemplo, con una webcam sin ajustar o con poca luz); la distancia queda igual registrada en la calibración.

**Cómo se calcula.** En cada cuadro, el motor toma los puntos del rostro de MediaPipe (centro y ancho de la cara en la imagen) y la posición de la cabeza (`tz`, en centímetros). MediaPipe supone un ángulo de visión típico de webcam, así que la distancia de una cámara concreta puede salir corrida. Por eso se corrige con `camera.distance_scale`.

**Ajuste de la distancia, una vez por cámara.** Con `distance_scale` en 1.0, siéntate con un metro a una distancia conocida de la pantalla (por ejemplo 60 cm, de los ojos a la cámara), pide una calibración inicial y mira la distancia que muestra la pantalla de instrucciones (por ejemplo, "unos 48 cm"). Pon en `config/shared.json` `distance_scale` = distancia medida ÷ distancia mostrada (60 ÷ 48 = 1.25), regenera la configuración (`python -m scripts.generate_config`) y recarga la extensión. Repítelo si cambias de webcam. La calibración de la mirada, en cambio, se hace en **cada sesión**, porque depende de la persona y de su postura.

Se envía `calibration.result` al panel y el registro `calibration` al servidor. Si no se acepta, la capa ofrece **Repetir** o **Continuar**, y cada intento queda registrado. Si la cámara todavía está arrancando (el motor carga MediaPipe y su modelo), la capa muestra "Preparando la cámara…" y espera hasta 20 s. **No hay resultado** si la cámara no está activa, si no se detectó el rostro o si se cancela con **Cancelar** o con Escape; la capa lo explica, y el panel ve el estado de la cámara por `camera.status`.

Durante la calibración la mirada no se registra, y los clics, el movimiento del cursor y la rueda sobre la capa no llegan a la captura de eventos: la capa los intercepta en `window`, antes que los oyentes de `document`. La rueda y las teclas de desplazamiento (espacio, flechas, Re Pág, Av Pág, Inicio, Fin) no mueven la página que está debajo. Si la sesión se cierra en medio de una calibración, la capa se quita y ese intento no registra nada.

## Pantalla y distancia de cada equipo

Las pantallas no son iguales. `config/shared.json` trae la del laboratorio; en otro equipo se ajusta en la **página de opciones** de la extensión (clic derecho en el ícono de SUCA → Opciones, o `chrome://extensions` → Detalles → Opciones de extensión), abierta **en la pantalla donde se hará la prueba**:

- **Tamaño:** la diagonal en pulgadas (con botones para los tamaños comunes) o, más exacto, el ancho visible medido con regla. La página calcula `css_px_per_cm` con el tamaño de la pantalla en píxeles CSS y dibuja una barra que debe medir 10 cm.
- **Distancia:** la habitual y el rango aceptado (con valores típicos de portátil y de monitor). La cámara mide la distancia real en cada cuadro; estos valores son la referencia y el rango del encuadre.

Se guarda en `chrome.storage.local` (`screen_setup`, `common/screen-setup.js`) y vale para ese navegador hasta que se cambie o se vuelva a los valores por defecto. La calibración inicial lo muestra antes de empezar, lo pasa al motor (`calibration.reset` con `css_px_per_cm`) y lo registra en cada calibración (`css_px_per_cm`). El análisis usa la pantalla y la mediana de las distancias medidas de cada sesión, no las de la configuración.

## Configuración (`camera` en `config/shared.json`)

| Clave | Valor | Para qué |
|---|---|---|
| `gaze_hz` | 30 | Frecuencia máxima de análisis y de muestras de mirada |
| `face_hz` | 15 | Frecuencia de muestras faciales |
| `video_width`, `video_height` | 1920, 1080 | Resolución que se pide a la webcam. La que entrega de verdad se ve en `stats.video` |
| `viewing_distance_cm` | 50 | Distancia de referencia: la que usa `error_deg` si la calibración no pudo medir la del participante. Se cambia por equipo en las opciones (ver "Pantalla y distancia de cada equipo") |
| `css_px_per_cm` | 36.22 | Píxeles CSS por centímetro de la pantalla: ancho de la pantalla en píxeles CSS (`screen.width`) dividido por su ancho visible en cm. **No** `innerWidth`: con el panel lateral o las herramientas de desarrollo abiertas da la mitad y los grados salen inflados. 36.22 es el monitor del laboratorio (1920 px en 53 cm). El estimador geométrico la usa para pasar centímetros a píxeles. Se cambia por equipo en las opciones |
| `distance_scale` | 1.24 | Corrección de la distancia a la cámara, propia de cada webcam (ver "Encuadre") |
| `min_distance_cm`, `max_distance_cm` | 35, 75 | Distancias aceptables a la cámara antes de calibrar. Se cambian por equipo en las opciones |
| `calibration_max_error_deg` | 5.0 | Umbral para aceptar una calibración. **Provisional:** se ajusta en el piloto |
| `lock_exposure` | true | Fijar exposición, foco y balance de blancos 3 s después de abrir la webcam, si lo permite (`stats.exposure_locked`) |
| `blink_threshold` | 0.45 | Parpadeo de MediaPipe desde el que un cuadro es `blink` y no entrena |
| `off_screen_margin_px` | 120 | Distancia fuera de la ventana desde la que la mirada es `off_screen` |
| `head_range_margin_deg` | 12 | Grados que la cabeza puede salir del rango calibrado antes de `off_screen` |
| `gaze_hybrid` | true | Combinar geométrico y apariencia según la postura (`hybrid`). En `false` se usa solo el de menor error de validación cruzada; sirve para comparar ambos modos con el banco de pruebas mientras el híbrido no esté validado con cámara real |
| `filter_min_cutoff_hz`, `filter_beta` | 0.5, 0.003 | Filtro One Euro: reducen el temblor de una fijación ~60 % y siguen un salto de 600 px en ~66 ms |
| `drift_check_between_tasks` | true | El panel pide una comprobación de deriva al terminar cada tarea guiada, salvo la última |
| `drift_correction` | true | Si las comprobaciones corrigen; en `false` solo miden (sesiones del banco de pruebas) |
| `drift_correction_min_error_deg` | 1.0 | Error mínimo para corregir |
| `record_gaze_features` | true | Registrar el lote `gaze_features` (lo necesitan el banco de pruebas y el reprocesamiento) |

## Conexión entre la pestaña y el motor

Es interna de la cámara: una conexión `chrome.runtime.connect({ name: 'camera' })`, que abre `content/camera.js` y atiende el motor. Si el motor todavía no existe, la pestaña reintenta cada segundo.

| Del motor a la pestaña | Datos |
|---|---|
| `hello` | `status`, `calibrated` y `started_at`, el momento en que arrancó ese motor (al conectar) |
| `status` | `status`: `active`, `no_permission` o `error` |
| `frame` | `t`, `face_detected`, `values`, `head_yaw`, `head_pitch`, `framing` (`{x, y, width, distance_cm}` o `null`, ver "Encuadre"), `gaze` (`{x, y}` filtrado, o `null`), `gaze_state`, `gaze_confidence` y `features` (los números de `gaze_features` del cuadro, con `raw_x` y `raw_y`, o `null`) |
| `gap` | `t`, `t_end`, `reason` |
| `reply` | `id` del pedido, `ok` y los datos de la respuesta, o `error` |

| De la pestaña al motor (`kind: 'request'`, con `id`) | Datos | Respuesta |
|---|---|---|
| `calibration.reset` | `viewport` (`{width, height}`) y, opcional, `css_px_per_cm` (pantalla de este equipo) | `ok` |
| `calibration.point` | `x`, `y`, `t_start`, `t_end`, `group`, `phase` (`points` o `head`) | `samples`: cuadros usados |
| `calibration.pursuit` | `points` (recorrido `[{t, x, y}]`), `t_start`, `t_end` | `samples` |
| `calibration.fit` | — | `ok`, `estimator`, `samples`, `groups`, `lambda`, `cv_error_px`, `candidates` (error de cada estimador), `camera_delay_ms` |
| `calibration.drift` | `points` (`[{x, y, t_start, t_end}]`), `correct`, `min_error_px` | `ok`, `samples`, `error_px`, `corrected`, `correction` (`{x, y}` acumulada) |
| `stats` | — | `delegate`, `benchmark_ms`, `video` (resolución y cuadros por segundo reales), `exposure_locked`, `status`, `calibrated`, `estimator`, `correction`, `last_fit`, `frames`, `hz`, `delay_ms`, `face_ratio` |
| `flush` | — | `gap`: el intervalo abierto con `t_end: null`, o `null` |

Cada pedido espera la respuesta hasta 3 s. El `flush` del cierre espera solo 1,5 s, menos que los 2 s que `modules.js` da a cada `stop()`: si el motor está ocupado (por ejemplo, cargando el modelo), la cámara se detiene sin su último hueco en vez de quedar fuera del cierre de la sesión.

**Intervalos sin datos (motor).** Un intervalo se abre cuando la última pestaña se desconecta (`navigation`) o la cámara pasa a `no_permission` o `error`. Empieza en el último cuadro entregado y se cierra con el primer cuadro que vuelve a llegar a una pestaña. No se registran los de menos de 250 ms.

**Motor reemplazado (pestaña).** Si Chrome cierra el documento offscreen a mitad de sesión, la pestaña pierde la conexión con un motor que sí existía y se lo dice al worker preguntando su id (`tab.identify`, lo mismo que pregunta al cargar cada página); el worker crea otro motor y la pestaña se reconecta sola en un segundo. El motor nuevo no conoce el hueco ni tiene la calibración. La pestaña lo nota porque el `started_at` del `hello` cambia: registra un `camera_gap` con `reason: error` desde su último cuadro hasta el primero del motor nuevo (o `t_end: null` si la sesión se cierra antes), y la mirada queda `uncalibrated` hasta una calibración nueva. Si el reemplazo coincide con una carga completa de página, la página nueva no tiene un cuadro anterior y ese hueco no se registra.

## Privacidad

- Cada cuadro se analiza en el motor y se cierra enseguida (`frame.close()`). Solo se recorta el rectángulo de cada ojo, en un lienzo pequeño que se borra en cada cuadro; el cuadro completo nunca se copia.
- Por la conexión y en los lotes solo viajan números. La pestaña evaluada nunca recibe la imagen. `gaze_features` guarda solo la zona de los ojos (posición del iris y párpados) y la pose: no la malla completa del rostro. Aun así es un dato sensible (Ley 1581) y debe figurar en el consentimiento; con `camera.record_gaze_features` en `false` no se registra (y no hay reprocesamiento ni banco de pruebas).
- `lib/` no es accesible desde las páginas web (no hay `web_accessible_resources`).

## Pruebas

`npm test` incluye `camera-math.test.js` (ojos y rostro), `iris-refine.test.js` (iris sintéticos con centro conocido), `gaze-estimation.test.js` (álgebra, estimador geométrico con una persona simulada que cambia de postura, estimador combinado, filtro y monitor), `camera-engine.test.js` (motor con cuadros sintéticos: calibración, punto en movimiento, deriva, fuera de pantalla), `camera-content.test.js` (registro en la pestaña, zonas y calibración con una capa falsa) y `camera-webgl.test.js`. Además, `pytest` ejecuta `tests/contracts/test_camera_records.py`, que corre `extension/tests/camera-records.js` con Node y valida contra los contratos cada registro que produce la pestaña (`gaze`, `face`, `gaze_features`, `calibration`, `gaze_target` y `camera_gap`), incluso cuando el motor envía datos de más; y `tests/analysis/test_gaze_bench.py` comprueba que el modelo geométrico de Python da lo mismo que el de JavaScript. La capa visual real (`createOverlay`) necesita un DOM: se revisa en la prueba manual.

### Prueba manual (con la cámara real)

1. Comprueba WebGL en `chrome://gpu` (paso 4 de "Preparación de la computadora"). Carga la extensión (si ya estaba cargada, **recárgala** en `chrome://extensions`) y da el permiso de cámara en la página que se abre al instalar.
2. Inicia el servidor y la app de prueba, y empieza una sesión desde el panel.
3. En `chrome://extensions` → SUCA → **Inspeccionar vistas: camera/engine.html**, en la consola del motor no debe haber errores. Mientras hay sesión, Chrome muestra el indicador de cámara en uso.
4. **Encuadre:** pide una calibración inicial desde el panel. Acércate, aléjate, muévete a los lados y gira la cabeza: la figura y las indicaciones deben seguirte, y **Comenzar** solo se habilita con la figura verde. Con un metro, comprueba la distancia que muestra (y ajusta `distance_scale` si hace falta, ver "Encuadre").
5. Completa la calibración: los 13 puntos, el punto en movimiento, el movimiento de cabeza y la validación con la vuelta del teclado. Anota `error_deg`, `precision_deg`, `return_error_deg`, `estimator`, `camera_delay_ms` y si se aceptó.
6. **Frecuencia, resolución, retraso y CPU:** en la consola del motor (que al abrir la webcam muestra `camera delivers {width, height, frame_rate}`), el estado (`video`, `exposure_locked`, `estimator`, `hz`, `delay_ms`, `delegate`, `benchmark_ms`, `face_ratio`) se lee con:
   ```javascript
   const p = chrome.runtime.connect({ name: 'camera' });
   p.onMessage.addListener((m) => m.kind === 'reply' && console.log(m));
   p.postMessage({ kind: 'request', action: 'stats', id: 1 });
   ```
   (esta conexión cuenta como una pestaña más; ciérrala con `p.disconnect()`). La CPU se mira en el **Administrador de tareas de Chrome** (Shift+Esc), en la fila del documento offscreen y en la de la pestaña.
7. **Orientación:** gira la cabeza hacia tu derecha: `head_yaw` debe ser positivo. Mira hacia arriba: `head_pitch` debe ser positivo.
8. **Navegación:** navega a otra página con recarga completa (no dentro de la aplicación de una sola página): debe quedar un `camera_gap` con `reason: navigation` y la mirada debe seguir sin calibrar de nuevo.
9. **Sin video:** en DevTools de la pestaña evaluada → **Network**, durante la sesión no debe haber más que los mensajes de la extensión; en el servidor, los lotes `gaze` y `face` solo traen números.
10. **Capa de calibración:** durante una calibración, mueve el cursor, usa la rueda y las flechas: la página de abajo no se desplaza y en la base no quedan `mousemove` ni `scroll` de ese tiempo. Pide una calibración apenas empieza la sesión: la capa debe mostrar "Preparando la cámara…" y seguir sola cuando la cámara esté activa.
11. **Motor reemplazado:** con la sesión en curso y la calibración hecha, en la consola del service worker (`chrome://extensions` → SUCA → **Inspeccionar vistas: service worker**) ejecuta `chrome.offscreen.closeDocument()`, sin recargar la pestaña. En uno o dos segundos debe aparecer de nuevo `camera/engine.html` en las vistas; en la base debe quedar un `camera_gap` con `reason: error`, y la mirada debe pasar a `valid: false` hasta calibrar otra vez.
12. **Mirar fuera y volver:** con la sesión en curso, mira el teclado unos segundos: en la base, las muestras `gaze` quedan `off_screen` y sin `x`; al volver, las primeras salen `low_confidence`. Parpadea: `blink`.
13. **Deriva:** en modo guiado, al terminar una tarea aparece la comprobación rápida; en la base queda un registro `calibration` de tipo `drift_check`. También desde el botón "Comprobar la mirada".
14. Cierra la sesión: el indicador de cámara de Chrome se apaga. Corre `python -m analysis.run --session <id>`: el resumen incluye `gaze …°`; y `python -m scripts.gaze_bench --session <id>` muestra el error en grados por fase, región, postura y tiempo.

### Línea base facial y combinación según postura

La calibración inicial comienza con 10 s de rostro relajado mirando el centro.
El tramo se marca `neutral_baseline` (contratos 1.7.0), mientras la captura
facial continúa. No se añade al entrenamiento ni a la evaluación de mirada.
El análisis facial exige esa marca y no inventa una para sesiones anteriores.

Si `camera.gaze_hybrid` está activo, entrenaron tanto apariencia como geometría
y se registró la pose, el motor informa `hybrid`. Cerca de la mediana de la postura calibrada combina ambos
puntos con pesos inversos al cuadrado de sus errores de validación cruzada.
El peso de apariencia decrece de forma gaussiana según el cambio de yaw,
pitch y distancia normalizado por la dispersión central de la calibración.
Fuera de esa postura predomina el geométrico. Sus ángulos de entrada se limitan
al rango calibrado más `head_range_margin_deg`; el monitor conserva la pose
original para decidir si mira fuera de pantalla. Sin pose o con un solo modelo
se conserva la selección por menor error de validación cruzada.

El error de cada candidato se informa separado. El modo híbrido deja su propio
`cv_error_px` en null: los errores de sus componentes no miden la combinación.
La validación de puntos posterior sigue determinando si se acepta calibración.
La mejora en uso natural requiere cámara real, una sesión de 15 minutos con
giros de cabeza y revisión de los bancos; no se supone a partir de la simulación.
