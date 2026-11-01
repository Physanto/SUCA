# Captura de interacción (M1)

Módulo `capture` de los content scripts (`extension/content/capture.js`). Registra lo que hace el participante en la página evaluada y lo entrega como lotes `events` con `ctx.batcher.add('events', registro)`. **Nunca captura lo que el participante escribe.**

Arranca y se detiene con la sesión, a través de `bootstrap.js`: `start(ctx)` pone los oyentes y `stop()` los quita todos. No guarda estado entre páginas.

## Qué registra

| Evento | Qué se guarda |
|---|---|
| `click`, `dblclick`, `contextmenu` | Coordenadas del puntero (`x`, `y`), descriptor del elemento y `data: {}` |
| `mousemove` | Coordenadas del puntero (`x`, `y`). Sin elemento, para no recorrer la página decenas de veces por segundo. Como máximo `capture.mousemove_hz` por segundo (50) |
| `scroll` | Posición de la página en `data.scroll_x` y `data.scroll_y` (nunca negativa). Sin `x` ni `y`: esos campos son siempre la posición del puntero. Como máximo `capture.scroll_hz` por segundo (10). Solo el scroll de la página; el de cajas internas se ignora |
| `selection` | Solo la longitud de lo seleccionado, en `data.length`; nunca el texto. Sin `x`, `y` ni elemento. Se registra una vez, cuando la selección lleva 300 ms sin cambiar. No se registra si está vacía ni si se hizo dentro de un campo de formulario o una zona editable (su longitud revelaría cuánto escribió el participante) |
| `focus_in`, `focus_out` | El campo (`input` salvo `hidden`, `textarea`, `select` o zona editable), descrito él mismo y no el interactivo más cercano. `data: {}` |
| `field_change` | El campo y solo que hubo un cambio; nunca el valor. Como máximo uno por segundo por campo |
| `form_submit` | El formulario. El navegador solo lo avisa si pasó la validación; un intento con errores genera `validation_error` |
| `validation_error` | El campo y el tipo de error en `data.error_type` (`validation_error_type`). Tres orígenes, ver abajo |
| `click_response` | Solo si la página respondió a un `click` en `capture.click_response_wait_ms` (1,5 s): `data.click_t` (el `t` del clic), `data.mutation_count` y `data.navigated`. Sin `x`, `y` ni elemento |
| `screen_change` | La pantalla nueva, en `screen` (URL y título). Sin `x`, `y` ni elemento. Se registra al iniciar la captura y cuando la dirección cambia |

**Cambios de pantalla.** Cada carga de página ejecuta de nuevo el módulo, que al iniciar registra la pantalla actual: la de cada carga completa o la primera de la sesión si se inició sobre una página ya cargada. Para las aplicaciones de una sola página, el módulo (que corre en un contexto aislado y no puede interceptar el `pushState` de la página) compara `location.href` cada 250 ms y, 50 ms después de cada `popstate` o `hashchange`, para dar tiempo a la página de actualizar su título. Solo cuenta la dirección: un cambio de `#` es un cambio de pantalla y un cambio solo del título no lo es. Límites: un cambio de ida y vuelta (A → B → A) en menos de 250 ms no se ve, y si la página actualiza el título mucho después de la dirección, el registro lleva el título anterior. La URL se guarda completa, con su parte de búsqueda (pendiente de revisar en la revisión de privacidad).

**Respuesta tras un clic y clics muertos.** Cada `click` crea un `MutationObserver` propio sobre todo el documento (hijos, atributos y texto), antes de que el sitio atienda el clic. Al terminar la espera se cuentan los cambios, incluidos los que el navegador aún no había entregado, y el observador se desconecta. Se registra `click_response` si hubo cambios o si `navigated` es verdadero: la URL cambió (aplicaciones de una sola página, también con `#`) o la página se descargó durante la espera (en ese caso se registra de inmediato y se vacía el acumulador, que ya había vaciado lo suyo con el mismo aviso). **Si no hubo nada, no se registra nada**: un `click` sin su `click_response` (unido por `click_t`) es lo que el análisis toma como clic muerto. Solo se vigila `click`, no `dblclick` ni `contextmenu`. `stop()` abandona las esperas pendientes sin registrar nada.

Limitación: en una página con cambios constantes (un reloj, un carrusel) todos los clics parecerán tener respuesta, y no se detectarán clics muertos.

**Errores de validación.** Tres orígenes, en este orden de prioridad:

1. **Nativa:** el evento `invalid` que el navegador dispara en cada campo inválido al intentar enviar. Se registra el primer problema de `validity` según el orden de la enumeración del contrato (las propiedades se derivan de ella: `value_missing` → `valueMissing`). Cada intento fallido se registra.
2. **`aria-invalid`:** un observador que mira solo ese atributo en todo el documento registra cuando un campo pasa a `"true"`.
3. **Mensaje visible:** 200 ms después de salir de un campo se comprueba si tiene un mensaje de error visible con texto, declarado con `aria-errormessage` o, entre los de `aria-describedby`, uno con `role="alert"` o con `err`, `invalid` o `danger` en su `id` o `class` (para no tomar el texto de ayuda como error). Solo se mira si hay texto, no cuál es.

Los orígenes 2 y 3 se registran una sola vez mientras el error siga presente, y de nuevo si desaparece y reaparece.

**Muestreo.** El primer movimiento o scroll se registra de inmediato. Los que llegan antes de que pase el intervalo mínimo (1000 ÷ frecuencia) no se pierden: se guarda el último y se registra al cumplirse el intervalo, para conservar la posición donde terminó el movimiento. Las frecuencias se leen de `ctx.config.capture` al iniciar; si no son números positivos, el módulo no arranca. Los oyentes son pasivos y `stop()` descarta lo pendiente.

Todos los registros llevan `t` (reloj común), `screen` (URL y título actuales) y `task_id` (la tarea activa de `ctx.session.get()`, o `null` si no hay tarea o sesión). **La tarea es la del momento del hecho, no la de la entrega:** los registros que se entregan después (`click_response`, `selection`, `validation_error` de aria y de mensaje visible, y `mousemove` y `scroll` retrasados) llevan la tarea que estaba activa cuando ocurrió lo que los causó. Así, si un clic termina la tarea, su respuesta sigue siendo de esa tarea aunque ya se haya cerrado cuando se entrega. El formato es `contracts/batches/events.schema.json`.

Todos los tipos de evento de la captura están documentados arriba.

## Descriptor del elemento

Forma de `contracts/element.schema.json`:

| Campo | Cómo se obtiene |
|---|---|
| `tag`, `id` | Etiqueta en minúsculas y atributo `id` (o `null`) |
| `role` | El atributo `role` o, si no tiene, el rol implícito de la etiqueta (`a` con `href` → `link`, `h1`–`h6` → `heading`, `input` según su `type`…) |
| `text` | Texto visible con espacios colapsados, recortado a 50 caracteres; `null` si no hay o si el elemento no es interactivo ni está permitido por las reglas de privacidad |
| `selector` | `#id` o la ruta desde `body` con `:nth-of-type` |
| `box` | `getBoundingClientRect()` como `x`, `y`, `w`, `h` |
| `interactive` | Enlace con `href`, botón, campo, elemento con rol interactivo o con `onclick` |

**Elemento interactivo más cercano:** si el clic cae en un `span` dentro de un botón, se describe el botón. Si ningún ancestro es interactivo, se describe el destino exacto.

## Privacidad

**Regla:** nunca se guarda lo que el participante escribe, ni nada de los campos de contraseña. La captura no lee `value` ni los datos del evento `input` (`data`, `inputType`), y solo registra que un campo cambió y cuál es.

**Qué se guarda de cada evento y qué se descarta:**

| Dato | Regla |
|---|---|
| `text` del descriptor | Solo en elementos **interactivos** (botones, enlaces, pestañas…). En contenedores, párrafos, títulos y mensajes es `null`: podrían repetir lo que el participante escribió (un mensaje enviado, una vista previa) o mostrar datos personales, y los pasos de una tarea son solo clics en interactivos |
| `text` en campos | `null` en `input`, `textarea` y `select` (incluidas las contraseñas), en zonas `contenteditable`, en cuadros de texto personalizados (rol `textbox`, `searchbox`, `combobox` o `spinbutton`) y en todo elemento que esté dentro de uno, que contenga uno o contenga un `textarea` (su contenido inicial puede ser texto ya escrito) |
| `selection` | Solo la longitud. No se registra si la selección empieza o termina en un campo, una zona editable o un cuadro de texto personalizado |
| `screen.url` | Se quitan usuario y clave de la dirección y se reemplaza por `redacted` el valor de los parámetros sensibles, tanto en la búsqueda (`?q=…`) como en el fragmento (`#access_token=…`, `#/buscar?q=…`): `q`, `query`, `search`, `s`, `keyword`, `keywords`, `term`, `email`, `user`, `username`, `token`, `access_token`, `id_token`, `refresh_token`, `key`, `api_key`, `apikey`, `password`, `pass`, `pwd`, `auth`, `session`, `sid`, `code` y `otp`. El resto se conserva (`?view=cart&id=1`, `#/ruta`), porque muchas aplicaciones identifican la pantalla con ellos. Esto aplica a todos los registros, no solo a `screen_change`; un cambio solo en un parámetro redactado sigue registrándose como cambio de pantalla |
| Mirada y rostro | No son de este módulo |

**Límites conocidos (no se pueden resolver desde la captura):**

- El **título** del documento (`screen.title`) no se limpia: un buscador que lo escriba con lo buscado ("Resultados de audífonos") lo dejaría en la base.
- El `text` de un elemento **interactivo** que repita lo escrito (un botón que muestra tu último mensaje) se guarda tal cual, recortado a 50 caracteres.
- El `id` y el `selector` se toman de la página tal como están.
- Una página con un campo que dibuja lo escrito con `div` sin rol de cuadro de texto ni `contenteditable` (algunos editores de código) no se puede distinguir de contenido normal; su texto solo se guardaría si el elemento clicado es interactivo.
- Los *iframes* no se capturan.

**Cómo se comprueba:** las pruebas cargan valores "canario" en todo tipo de campo, disparan cada tipo de evento sobre cada uno y fallan si el canario aparece en cualquier parte de un registro; los campos y los eventos de prueba lanzan un error si el código lee `value`, `data` o `inputType`. Además se rompió cada regla a propósito para confirmar que alguna prueba lo detecta. La revisión manual busca lo escrito en toda la base (`data/suca.db`).

## Cómo se prueba

Pruebas automáticas, con un DOM mínimo en memoria (`extension/tests/capture.test.js`):

```bash
npm test
```

Prueba manual con la página de prueba:

1. `python -m scripts.init_db`, luego `python -m server` y, en otra terminal, `python -m scripts.serve_test_page`.
2. Carga `extension/` en Chrome, abre `http://127.0.0.1:8766/` e inicia una sesión desde el panel.
3. Haz clic, doble clic y clic derecho; cierra la sesión.
4. Revisa los eventos en la base:

   ```bash
   python -c "import sqlite3; c = sqlite3.connect('data/suca.db'); print(c.execute('SELECT type, x, y, element FROM event ORDER BY t DESC LIMIT 10').fetchall())"
   ```

## Cómo agregar un tipo de evento

1. Revisa su forma en `contracts/batches/events.schema.json`; si falta algo, abre un *issue* con la etiqueta `contract`.
2. Agrega su oyente en `start` y quítalo en `stop`.
3. Crea el registro con la misma estructura (`t`, `type`, `screen`, `task_id` y lo que exija su tipo) y entrégalo con `ctx.batcher.add('events', registro)`.
4. Agrega sus pruebas a `extension/tests/capture.test.js` y documéntalo en este README.
