# Cámara: mirada, rostro y calibración

Estima hacia dónde mira el participante y registra sus movimientos faciales con una sola webcam. **Solo guarda números: ningún cuadro de video sale del navegador.**

## Cómo está armada

```
 Pestaña evaluada (content scripts)            Documento offscreen de la extensión
 ┌──────────────────────────────────┐          ┌──────────────────────────────────────┐
 │ content/camera.js                │  conexión│ camera/engine.html                   │
 │  · muestras gaze (elemento, zona)│◄─────────┤  engine-main.mjs: webcam → MediaPipe │
 │  · muestras face                 │ "camera" │    Face Landmarker → características │
 │  · eventos camera_gap            ├─────────►│  engine.js: modelo de mirada,        │
 │ content/calibration.js           │ pedidos  │    huecos, estadísticas              │
 │  · capa de 9 + 5 puntos          │          │                                      │
 └───────────────┬──────────────────┘          └──────────────────┬───────────────────┘
                 │ lotes gaze, face, calibration, events          │ camera.status
                 ▼                                                ▼
           service worker ──► servidor                      panel lateral
```

- **El motor vive en un documento offscreen** (`camera/engine.html`), no en la página. El worker lo crea al empezar la sesión y lo cierra al terminarla, lo que apaga la cámara. Como no se recarga al navegar:
  - la cámara se abre **una sola vez** por sesión y el permiso es de la extensión, no de cada sitio;
  - el modelo de mirada entrenado en la calibración sigue sirviendo después de cada navegación;
  - MediaPipe carga sus archivos de WebAssembly desde la extensión, sin depender de la política de seguridad de cada sitio.
- **Un solo modelo para todo.** MediaPipe Face Landmarker da, por cada cuadro, los 478 puntos del rostro (incluidos los iris), los valores de los movimientos faciales y la orientación de la cabeza. La mirada se calcula con esos mismos puntos (ver "Mirada"), así que no hay un segundo modelo de rostro corriendo en paralelo.
- **GPU o CPU, según la computadora.** El motor empieza con la GPU y mide sus primeros 20 cuadros. Si tarda más de 25 ms por cuadro, carga también la CPU, la mide y se queda con la más rápida (en Chrome sin aceleración gráfica, la GPU simulada puede ser cinco veces más lenta). La elección se ve en `stats` (`delegate`, `benchmark_ms`). **Las dos necesitan WebGL**: MediaPipe recibe cada cuadro como una textura WebGL aunque analice con la CPU (ver "Preparación de la computadora").
- **Adaptadores.** `createFaceProvider` (en `engine-main.mjs`) es el único lugar que conoce a MediaPipe; `gaze-model.js` y `eye-features.js` forman el estimador de mirada. Cambiar de librería no toca ni la pestaña ni el motor.

## Archivos

| Archivo | Dónde corre | Qué hace |
|---|---|---|
| `camera/engine.html` | Offscreen | Carga las utilidades comunes, las piezas de cálculo y `engine-main.mjs` |
| `camera/engine-main.mjs` | Offscreen | Punto de composición: abre la webcam, lee cada cuadro con `MediaStreamTrackProcessor`, lo analiza con MediaPipe y se lo pasa al motor. Reintenta si la cámara falla o falta el permiso |
| `camera/engine.js` | Offscreen | Motor sin dependencias del navegador: conexiones con la pestaña, pedidos de la calibración, intervalos sin datos y estadísticas |
| `camera/gaze-model.js` | Offscreen | Regresión ridge de las características de los ojos al punto de la ventana, y suavizado |
| `camera/eye-features.js` | Offscreen | Parches de 10 × 6 de cada ojo, posición de los iris y vector de 130 características |
| `camera/webgl.js` | Offscreen | Comprueba que se puede crear un contexto WebGL antes de abrir la webcam |
| `camera/face-features.js` | Offscreen | Valores faciales del contrato desde los de MediaPipe, y orientación de la cabeza desde la matriz de transformación |
| `camera/strings.js` | Pestaña y página del permiso | Textos visibles de la calibración y del permiso, en español |
| `camera/permission.html`, `permission.js` | Pestaña de la extensión | Pide el permiso de cámara una vez por computadora |
| `content/camera.js` | Pestaña evaluada | Módulo `camera`: conexión con el motor y registro de `gaze`, `face` y `camera_gap` |
| `content/camera/zones.js` | Pestaña evaluada | Zona y selector del elemento de cada punto de mirada |
| `content/calibration.js` | Pestaña evaluada | Módulo `calibration`: capa de calibración y validación |
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
| `gaze` | A `camera.gaze_hz` (30 Hz), salvo durante la calibración | `x`, `y` en la ventana; `scroll_x`, `scroll_y`; `element_selector` (el elemento en ese punto, con el mismo formato de selector que la captura de eventos); `zone`; `valid` |
| `face` | A `camera.face_hz` (15 Hz) | Los valores de `face_value` (entre 0 y 1), `head_yaw` y `head_pitch` en grados, `face_detected` |
| `calibration` | Al terminar cada intento de calibración | `type`, `error_px`, `error_deg`, `accepted`, `camera_delay_ms` (por ahora `null`, ver abajo) |
| `events` (`camera_gap`) | Cuando vuelven los datos, o al cerrar la sesión | Inicio (`t`), fin (`data.t_end`, `null` si no volvieron) y motivo (`navigation`, `no_permission`, `error`) |

Casos de una muestra `gaze` **no válida** (`valid: false`):
- sin rostro, o todavía sin calibración: `x` e `y` en `null`;
- la mirada cae fuera de la ventana (por ejemplo, en el panel lateral): `x` e `y` se guardan, sin elemento ni zona.

**Zonas.** Primero la región semántica más cercana que contiene al elemento mirado: `search` (`role="search"` o `<search>`), `header`, `nav`, `main`, `aside`, `footer`, por etiqueta o por rol ARIA. Un `header` o `footer` dentro de `article`, `section`, `main`, `nav` o `aside` no cuenta, porque es de esa sección y no de la página. Si no hay región, una cuadrícula de 3 × 3 de la ventana (`grid_top_left` … `grid_bottom_right`).

**Pantalla de `camera_gap`.** Solo origen y ruta, con el título vacío: la búsqueda y el fragmento pueden llevar lo que escribió el participante. El evento lo registra la página que recibe los datos de nuevo, así que tras una navegación lleva la pantalla nueva.

**Hora de cada muestra.** Es el momento en que el cuadro llegó al motor, con el reloj común (`UX.clock`), antes de analizarlo, así que el tiempo de análisis no atrasa las muestras (su mediana se ve en `stats.delay_ms`). Lo que sí las atrasa es la demora del sensor y del controlador de la webcam hasta que el cuadro llega, que el navegador no informa. Ese es el retraso que corresponde a `camera_delay_ms` en el registro `calibration` y en `analysis/parameters.yaml`; mientras no se mida, el registro lo deja en `null`. **No copies `stats.delay_ms` a `parameters.yaml`:** la limpieza desplazaría la mirada y el rostro un tiempo que ya está descontado.

## Mirada

El método sigue a WebGazer:
1. Con los puntos del rostro se recorta cada ojo, se pasa a gris, se reduce a 10 × 6 y se ecualiza el histograma (60 valores por ojo).
2. Se agregan la posición de cada iris entre sus comisuras y párpados (4 valores) y la orientación y posición de la cabeza (6 valores). En total, 130 características.
3. Una **regresión ridge** las lleva a un punto de la ventana. Las características se estandarizan y la penalización se elige entre 0,1 y 1000 por validación cruzada, dejando fuera un punto de calibración a la vez.
4. Se suaviza con un promedio exponencial (peso 0,35 del punto nuevo), que se reinicia al perder el rostro.

El modelo se entrena **solo** en la calibración: los clics de la sesión no lo modifican (WebGazer, por defecto, aprende de cada clic, y eso mezclaría la interacción con la medición).

## Calibración

El panel lateral envía `calibration.request` con `type`:

- **`initial`:** pantalla de instrucciones → 9 puntos (en el 10 %, 50 % y 90 % del ancho y del alto, en orden al azar). El participante mira cada uno y hace clic; se usan los cuadros desde 400 ms antes hasta 1000 ms después del clic, mientras el punto se achica. Luego, 5 puntos de validación distintos (centro y 30 %/70 %), sin clic: se espera 700 ms y se mide durante 1000 ms la distancia entre la mirada estimada y el punto.
- **`final`:** solo la validación, con el modelo de la calibración inicial, para medir cuánto se degradó.

Resultado:
- `error_px`: distancia media entre la mirada y el punto, en píxeles CSS, sobre todas las muestras de la validación.
- `error_deg`: ese error en grados de ángulo visual: `atan(error_px / css_px_per_cm / viewing_distance_cm)`.
- `accepted`: `error_deg ≤ calibration_max_error_deg`.

Se envía `calibration.result` al panel y el registro `calibration` al servidor. Si no se acepta, la capa ofrece **Repetir** o **Continuar**, y cada intento queda registrado. Si la cámara todavía está arrancando (el motor carga MediaPipe y su modelo), la capa muestra "Preparando la cámara…" y espera hasta 20 s. **No hay resultado** si la cámara no está activa, si no se detectó el rostro o si se cancela con **Cancelar** o con Escape; la capa lo explica, y el panel ve el estado de la cámara por `camera.status`.

Durante la calibración la mirada no se registra, y los clics, el movimiento del cursor y la rueda sobre la capa no llegan a la captura de eventos: la capa los intercepta en `window`, antes que los oyentes de `document`. La rueda y las teclas de desplazamiento (espacio, flechas, Re Pág, Av Pág, Inicio, Fin) no mueven la página que está debajo. Si la sesión se cierra en medio de una calibración, la capa se quita y ese intento no registra nada.

## Configuración (`camera` en `config/shared.json`)

| Clave | Valor | Para qué |
|---|---|---|
| `gaze_hz` | 30 | Frecuencia máxima de análisis y de muestras de mirada |
| `face_hz` | 15 | Frecuencia de muestras faciales |
| `video_width`, `video_height` | 640, 480 | Resolución que se pide a la webcam |
| `viewing_distance_cm` | 60 | Distancia del participante a la pantalla |
| `css_px_per_cm` | 55.7 | Píxeles CSS por centímetro de la pantalla. Se mide una vez por pantalla: ancho de la ventana en píxeles CSS (`innerWidth` con el navegador maximizado) dividido por el ancho visible en cm. 55.7 es el portátil del laboratorio (1920 px en 34,5 cm); 37.8 sería una pantalla de 96 píxeles por pulgada |
| `distance_scale` | 1.0 | Corrección de la distancia a la cámara, propia de cada webcam (ver "Encuadre"). 1.0 sin ajustar |
| `calibration_max_error_deg` | 5.0 | Umbral para aceptar una calibración. **Provisional:** se ajusta en el piloto |

## Conexión entre la pestaña y el motor

Es interna de la cámara: una conexión `chrome.runtime.connect({ name: 'camera' })`, que abre `content/camera.js` y atiende el motor. Si el motor todavía no existe, la pestaña reintenta cada segundo.

| Del motor a la pestaña | Datos |
|---|---|
| `hello` | `status`, `calibrated` y `started_at`, el momento en que arrancó ese motor (al conectar) |
| `status` | `status`: `active`, `no_permission` o `error` |
| `frame` | `t`, `face_detected`, `values`, `head_yaw`, `head_pitch`, `gaze` (`{x, y}` o `null`) |
| `gap` | `t`, `t_end`, `reason` |
| `reply` | `id` del pedido, `ok` y los datos de la respuesta, o `error` |

| De la pestaña al motor (`kind: 'request'`, con `id`) | Datos | Respuesta |
|---|---|---|
| `calibration.reset` | — | `ok` |
| `calibration.point` | `x`, `y`, `t_start`, `t_end`, `group` | `samples`: cuadros usados |
| `calibration.fit` | — | `ok`, `samples`, `groups`, `lambda`, `cv_error_px` |
| `stats` | — | `delegate` (`GPU` o `CPU`), `benchmark_ms` (tiempo medio por cuadro de cada procesador probado), `status`, `calibrated`, `frames`, `hz`, `delay_ms`, `face_ratio` |
| `flush` | — | `gap`: el intervalo abierto con `t_end: null`, o `null` |

Cada pedido espera la respuesta hasta 3 s. El `flush` del cierre espera solo 1,5 s, menos que los 2 s que `modules.js` da a cada `stop()`: si el motor está ocupado (por ejemplo, cargando el modelo), la cámara se detiene sin su último hueco en vez de quedar fuera del cierre de la sesión.

**Intervalos sin datos (motor).** Un intervalo se abre cuando la última pestaña se desconecta (`navigation`) o la cámara pasa a `no_permission` o `error`. Empieza en el último cuadro entregado y se cierra con el primer cuadro que vuelve a llegar a una pestaña. No se registran los de menos de 250 ms.

**Motor reemplazado (pestaña).** Si Chrome cierra el documento offscreen a mitad de sesión, la pestaña pierde la conexión con un motor que sí existía y se lo dice al worker preguntando su id (`tab.identify`, lo mismo que pregunta al cargar cada página); el worker crea otro motor y la pestaña se reconecta sola en un segundo. El motor nuevo no conoce el hueco ni tiene la calibración. La pestaña lo nota porque el `started_at` del `hello` cambia: registra un `camera_gap` con `reason: error` desde su último cuadro hasta el primero del motor nuevo (o `t_end: null` si la sesión se cierra antes), y la mirada queda `valid: false` hasta una calibración nueva. Si el reemplazo coincide con una carga completa de página, la página nueva no tiene un cuadro anterior y ese hueco no se registra.

## Privacidad

- Cada cuadro se analiza en el motor y se cierra enseguida (`frame.close()`). El lienzo donde se recortan los ojos se borra en cada cuadro.
- Por la conexión y en los lotes solo viajan números. La pestaña evaluada nunca recibe la imagen.
- `lib/` no es accesible desde las páginas web (no hay `web_accessible_resources`).

## Pruebas

`npm test` incluye `camera-math.test.js` (modelo de mirada, ojos, rostro), `camera-engine.test.js` (motor con cuadros sintéticos) y `camera-content.test.js` (registro en la pestaña, zonas y calibración con una capa falsa) y `camera-webgl.test.js` (comprobación de WebGL). Además, `pytest` ejecuta `tests/contracts/test_camera_records.py`, que corre `extension/tests/camera-records.js` con Node y valida contra los contratos cada registro que produce la pestaña (`gaze`, `face`, `calibration` y `camera_gap`), incluso cuando el motor envía datos de más. La capa visual real (`createOverlay`) necesita un DOM: se revisa en la prueba manual.

### Prueba manual (con la cámara real)

1. Comprueba WebGL en `chrome://gpu` (paso 4 de "Preparación de la computadora"). Carga la extensión (si ya estaba cargada, **recárgala** en `chrome://extensions`) y da el permiso de cámara en la página que se abre al instalar.
2. Inicia el servidor y la app de prueba, y empieza una sesión desde el panel.
3. En `chrome://extensions` → SUCA → **Inspeccionar vistas: camera/engine.html**, en la consola del motor no debe haber errores. Mientras hay sesión, Chrome muestra el indicador de cámara en uso.
4. Pide una calibración inicial desde el panel y complétala. Anota `error_px`, `error_deg` y si se aceptó.
5. **Frecuencia, retraso y CPU:** en la consola del motor, el estado (`hz`, `delay_ms`, `delegate`, `benchmark_ms`, `face_ratio`) se lee con:
   ```javascript
   const p = chrome.runtime.connect({ name: 'camera' });
   p.onMessage.addListener((m) => m.kind === 'reply' && console.log(m));
   p.postMessage({ kind: 'request', action: 'stats', id: 1 });
   ```
   (esta conexión cuenta como una pestaña más; ciérrala con `p.disconnect()`). La CPU se mira en el **Administrador de tareas de Chrome** (Shift+Esc), en la fila del documento offscreen y en la de la pestaña.
6. **Orientación:** gira la cabeza hacia tu derecha: `head_yaw` debe ser positivo. Mira hacia arriba: `head_pitch` debe ser positivo.
7. **Navegación:** navega a otra página con recarga completa (no dentro de la aplicación de una sola página): debe quedar un `camera_gap` con `reason: navigation` y la mirada debe seguir sin calibrar de nuevo.
8. **Sin video:** en DevTools de la pestaña evaluada → **Network**, durante la sesión no debe haber más que los mensajes de la extensión; en el servidor, los lotes `gaze` y `face` solo traen números.
9. **Capa de calibración:** durante una calibración, mueve el cursor, usa la rueda y las flechas: la página de abajo no se desplaza y en la base no quedan `mousemove` ni `scroll` de ese tiempo. Pide una calibración apenas empieza la sesión: la capa debe mostrar "Preparando la cámara…" y seguir sola cuando la cámara esté activa.
10. **Motor reemplazado:** con la sesión en curso y la calibración hecha, en la consola del service worker (`chrome://extensions` → SUCA → **Inspeccionar vistas: service worker**) ejecuta `chrome.offscreen.closeDocument()`, sin recargar la pestaña. En uno o dos segundos debe aparecer de nuevo `camera/engine.html` en las vistas; en la base debe quedar un `camera_gap` con `reason: error`, y la mirada debe pasar a `valid: false` hasta calibrar otra vez.
11. Cierra la sesión: el indicador de cámara de Chrome se apaga.
