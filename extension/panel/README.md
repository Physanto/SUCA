# Panel lateral y fin de tarea (M2)

Interfaz del evaluador en el panel lateral de Chrome (`extension/panel/`) y el módulo `task-end` de los content scripts (`extension/content/task-end.js`). El panel crea la sesión, la mantiene durante la prueba y la cierra; controla los tres modos (`free`, `guided` y `reference`); y `task-end.js` avisa cuando la pestaña evaluada cumple la condición final de una tarea.

| Archivo | Qué contiene |
|---|---|
| `controller.js` | Toda la lógica, sin DOM. Se prueba en Node. |
| `panel.js` | La vista: dibuja el estado del controlador y le pasa lo que hace el evaluador. |
| `panel.html`, `panel.css` | Las secciones del panel y su estilo. |
| `strings.js` | Todos los textos visibles, en español. Incluye las 10 preguntas del SUS. |
| `../content/task-end.js` | Revisa la condición final de la tarea dentro de la página evaluada. |

El panel **no se reescribe** al agregar algo: se extiende el controlador, la vista y los textos (ver "Cómo agregar una pantalla").

## Estado de la sesión

`UX.session` guarda en `chrome.storage.session` el estado `{ session_id, mode, study_id, tab_id, task_id }`. **Solo el panel lo escribe**; los content scripts lo leen y se enteran de los cambios. `task_id` es la tarea activa (la captura de interacción marca con ella sus registros) o `null`. Ningún otro dato cabe ahí: lo demás vive en el estado del controlador y se pierde si el panel se cierra (ver "Límites").

## Fases y estado del controlador

El controlador publica un estado inmutable con `setState`; la vista se suscribe con `controller.subscribe(render)`. La fase (`phase`) es `loading`, `idle` (sin sesión), `starting`, `active` o `closing`. Además del estado de la sesión y de los estudios, tiene:

| Campo | Qué es |
|---|---|
| `error`, `notice` | `{ code, fields, detail }` y `{ code, ... }`. Los códigos son claves de `strings.js` (`errors`, `notices`). |
| `tab`, `tabStatus`, `failedModules` | Título y URL de la pestaña evaluada y si respondió al iniciar (`capturing`, `pending` o `unknown`). |
| `startedAt` | Inicio de la sesión según el reloj común, o `null` si el panel se abrió con la sesión ya en curso. |
| `guided` | Solo en modo guiado: `loaded`, `tasks`, `index` (tarea que toca; igual a `tasks.length` al terminar), `current` y `sus` (`answers`, `saving`, `saved`). |
| `reference` | Solo en modo referencia: `loaded`, `tasks`, `recording`, `saved`, `unsaved`, `captures` y `capturing`. |
| `camera`, `calibration` | Estado de la cámara y último resultado de cada calibración (`initial`, `final`). |

Los métodos que cambian el estado lo hacen **antes de esperar** al servidor o a la pestaña, para que un segundo clic no repita la acción.

## Flujo de cada modo

**Inicio (los tres modos).** El evaluador elige estudio, escribe el código del participante y la versión, y elige el modo. El panel comprueba que la pestaña activa sea una página web (`http` o `https`), crea la sesión (`POST /sessions`, con los tamaños de ventana y pantalla), guarda el estado con `UX.session`, avisa a la pestaña con `session.started` y, en modo guiado o referencia, carga las tareas del estudio.

**Cierre (los tres modos).** El panel vacía su acumulador de lotes, envía `session.closed` y borra el estado. **No llama a `POST /sessions/{id}/close`**: el worker cierra la sesión en el servidor después de los últimos lotes.

**Calibración y cámara (los tres modos).** Dos botones piden la calibración inicial o la final con `calibration.request`. La cámara responde con `calibration.result` (error en píxeles y en grados, y si se aceptó) y `camera.status` (`active`, `no_permission` o `error`). Sin permiso de cámara o con error, no se pide calibración y la sesión sigue sin ella.

### Libre (`free`)

Iniciar, mostrar el tiempo transcurrido y cerrar. No hay tareas ni SUS.

### Guiado (`guided`)

1. Se muestran la tarea que toca y el progreso (`1 de 4`). Con **Empezar**, el panel anota la tarea en el estado de la sesión y envía `task.started` con la condición final de la tarea (la de su primera referencia confirmada, la de menor `id`) o `null` si no tiene.
2. La tarea termina de una de tres formas, que se guardan en `ended_by`:
   - `reference`: la pestaña cumplió la condición final y envió `task.completed` (ver `task-end.js`).
   - `done`: el participante pulsó **Terminé**.
   - `gave_up`: el participante pulsó **No pude**.
3. Al terminar, el panel agrega al lote `tasks` el registro `{ task_id, t_start, t_end, ended_by }`, deja la sesión sin tarea activa y pasa a la siguiente.
4. Al terminar **todas** las tareas aparece el cuestionario SUS (ver abajo). Cerrar la sesión no exige contestarlo.

**SUS.** Usa la versión en español validada de Sevilla-Gonzalez et al. (2020, *JMIR Human Factors* 7(4):e21161), con el texto literal de sus 10 preguntas. Las respuestas (de 1 a 5) se envían con `POST /sessions/{id}/sus` cuando están las 10; el servidor calcula el puntaje. Volver a enviarlas reemplaza las anteriores, y si el envío falla se conservan para repetirlo. El panel no muestra el puntaje al participante.

### Referencia (`reference`)

El evaluador graba el recorrido correcto de una tarea para que el análisis construya su referencia.

1. Elige una tarea de la lista y pulsa **Iniciar grabación**. El panel anota la tarea en el estado de la sesión y envía `task.started` con `end_condition: null`: la grabación la termina el evaluador.
2. Hace el recorrido en la pestaña y pulsa **Terminar y guardar**. El panel agrega el registro de la tarea con `ended_by: done`, vacía el acumulador (para que el registro y los eventos lleguen primero) y llama a `POST /references` con `{ task_id, source_session_id }`. La referencia queda en borrador hasta que se confirme.
3. Si el guardado falla, la tarea queda pendiente y **Reintentar guardado** repite solo esa llamada. Mientras haya un guardado pendiente no se graba otra tarea. Cada tarea se graba una vez por sesión.
4. **Capturar pantalla** toma una captura de la pestaña evaluada para los mapas de calor: envía `screen_capture.request` con `study_id` y `screen` (`url` y `title`), y el worker captura la pestaña y la envía a `POST /captures`. Solo existe en este modo. Si la pestaña activa no es la evaluada, no captura y lo avisa. La URL sale **redactada**: sin usuario ni clave y con `redacted` como valor de `q`, `token`, `code` y los demás parámetros sensibles de la búsqueda y del fragmento, con la misma regla de la captura de interacción; si hubo que tachar algo, el título va vacío.

## `task-end.js`

Se inicia con la sesión activa en la pestaña evaluada y se detiene al cerrarla. Al recibir `task.started` con una condición, la revisa y, cuando se cumple, envía **una sola vez** `task.completed` con `ended_by: reference`. Con `end_condition: null` no hace nada.

| Tipo de condición | Se cumple cuando |
|---|---|
| `visible_text` | El texto aparece en el texto visible de la página, sin distinguir mayúsculas y con los espacios colapsados. |
| `url_pattern` | La ruta de la URL completa coincide con el patrón: `{id}` equivale a un solo segmento, los caracteres especiales se toman literalmente y la barra final no cuenta. |
| `element_present` | Hay un elemento visible con ese rol (explícito o implícito) y ese texto, recortado a 50 caracteres como lo hace la captura. |

Revisa al recibir la condición y después con un `MutationObserver`, con `popstate` y con `hashchange`, como máximo 4 veces por segundo y con una revisión final para no perder el último cambio. Como la página puede recargarse al navegar, guarda la condición en `chrome.storage.session` con su propia clave (`task_end`) y la retoma si la tarea activa de la sesión es la misma. `stop()` quita el observador, el temporizador, los oyentes y la condición guardada.

## Mensajes

El worker enruta `session.started`, `task.started` y `calibration.request` solo a la pestaña evaluada. Los de la pestaña al panel llegan directamente. El formato de cada uno está en `contracts/extension-messages.md`.

| Mensaje | Dirección | Cuándo |
|---|---|---|
| `session.started` | Panel → pestaña (vía worker) | Al iniciar la sesión. La pestaña responde con los módulos que arrancaron y los que fallaron. |
| `session.closed` | Panel → worker | Al cerrar, después de vaciar el acumulador. |
| `task.started` | Panel → pestaña (vía worker) | Al empezar una tarea (guiado) o una grabación (referencia). |
| `task.completed` | `task-end.js` → panel | La pestaña cumplió la condición final. |
| `calibration.request` | Panel → cámara (vía worker) | Al pulsar un botón de calibración. |
| `calibration.result` | Cámara → panel | Al terminar la calibración. |
| `camera.status` | Cámara → panel | Cuando cambia el estado de la cámara. |
| `screen_capture.request` | Panel → worker | Al pulsar **Capturar pantalla**. |
| `batch` | Panel → worker | Lotes `tasks`, que arma `UX.batcher` con la sesión anotada en cada registro. |

**Servidor** (por `UX.api`): `GET /studies`, `GET /studies/{id}/tasks`, `POST /sessions`, `POST /sessions/{id}/sus` y `POST /references`.

## Privacidad

El panel no lee el contenido de la página evaluada. De la pestaña solo toma el título y la URL para mostrarlos y para las capturas de pantalla, estas últimas con la URL redactada como se explicó arriba. `participant_id` es un código, no un nombre. La regla de redacción está repetida en `controller.js` porque el panel no carga `capture.js`: si cambia la lista de parámetros sensibles de `content/capture.js`, hay que cambiarla también aquí.

## Límites

- **El estado de la sesión no guarda el inicio ni las tareas hechas.** Si el panel se cierra y se vuelve a abrir a mitad de sesión, retoma la sesión y la tarea o grabación en curso (con un `t_start` nuevo), pero el tiempo transcurrido aparece como "—", la lista de tareas terminadas y de referencias guardadas empieza de cero, y las respuestas del SUS ya escritas se pierden.
- **La cámara avisa solo al cambiar.** Un panel reabierto muestra "Sin información todavía" hasta el siguiente cambio.
- **Una tarea sin terminar al cerrar la sesión no se registra**, porque el contrato de `tasks` solo describe tareas terminadas.
- **La captura de pantalla toma lo que se ve en la ventana**, por eso la pestaña evaluada debe estar activa.

## Cómo se prueba

**Pruebas automáticas** (Node, sin Chrome ni DOM, con los sustitutos de `extension/tests/fakes.js`):

```bash
npm test
```

- `extension/tests/panel-controller.test.js`: el controlador, método por método.
- `extension/tests/panel-guided-session.test.js`: una sesión guiada completa y una de referencia, con el controlador, `UX.session` y `UX.batcher` reales, comprobando el orden de todo lo que sale hacia el worker y el servidor.
- `extension/tests/task-end.test.js`: las tres condiciones, el límite de revisiones, la persistencia entre páginas y la detención.

La vista (`panel.js`) no tiene pruebas automáticas: se comprueba a mano.

**Prueba manual** con la página de prueba:

1. `python -m scripts.init_db` y `python -m scripts.load_study studies/example.yaml`; luego `python -m server` y, en otra terminal, `python -m scripts.serve_test_page`.
2. Carga `extension/` en Chrome (o recárgala en `chrome://extensions`) y abre `http://127.0.0.1:8766/`.
3. **Guiado:** inicia una sesión guiada y haz las tareas con **Empezar**, **Terminé** y **No pude**; contesta el SUS y cierra.
4. **Referencia:** inicia una sesión de referencia, graba una tarea, pulsa **Capturar pantalla** y cierra.
5. Revisa la base:

   ```bash
   python -c "import sqlite3; c = sqlite3.connect('data/suca.db'); print(c.execute('SELECT session_id, task_id, ended_by FROM session_task').fetchall()); print(c.execute('SELECT session_id, answers, score FROM sus_response').fetchall()); print(c.execute('SELECT id, task_id, status, source_session_id FROM reference').fetchall()); print(c.execute('SELECT id, screen, file_path FROM screen_capture').fetchall())"
   ```

   Cada tarea guiada debe tener su `ended_by`; el SUS, las 10 respuestas y su puntaje; la grabación de referencia, una referencia en `draft` con la sesión de origen, y la captura, su archivo en `data/captures/`.

## Cómo agregar una pantalla

Una pantalla es una sección del panel que depende del estado. Para agregar una:

1. **Estado y lógica** en `controller.js`: si necesita datos propios, agrégalos al estado (y a `idle()` para que se reinicien al cerrar) y documenta sus campos en el encabezado del archivo. Agrega los métodos que cambian el estado: cámbialo antes de esperar con `setState` y convierte los errores con `describeError`. Si hay una acción que se puede repetir con un segundo clic, protégela con una bandera en el estado.
2. **Textos** en `strings.js`: todo texto visible va ahí, en español, no en `panel.js` ni en el HTML. Los errores y avisos nuevos son claves de `errors` y `notices`.
3. **Sección** en `panel.html`, con su atributo `hidden` y los textos fijos marcados con `data-string`. Los estilos de `display` no anulan `hidden` (hay una regla global en `panel.css`).
4. **Vista** en `panel.js`: una función `render…(state)` que muestra u oculta la sección según el estado y la llena; llámala desde `render`. Conecta los botones en la parte final del archivo con `controller.método()`.
5. **Pruebas** en `panel-controller.test.js` (cada método y cada guarda) y, si cambia el orden de lo que sale, en `panel-guided-session.test.js`. Para comprobar que las pruebas detectan fallos, rompe cada regla a propósito y confirma que alguna prueba falla.
6. **Mensajes o contratos nuevos:** si la pantalla necesita un mensaje, un campo del estado de la sesión o un endpoint que no existen, no se editan aquí: abre un *issue* con la etiqueta `contract`.
