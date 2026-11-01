# Captura de interacción (M1)

Módulo `capture` de los content scripts (`extension/content/capture.js`). Registra lo que hace el participante en la página evaluada y lo entrega como lotes `events` con `ctx.batcher.add('events', registro)`. **Nunca captura lo que el participante escribe.**

## Cómo arranca y se detiene

`bootstrap.js` lo inicia cuando hay una sesión activa y esta es la pestaña evaluada, y lo detiene al cerrar la sesión:

- `start(ctx)` valida la configuración, pone los oyentes y registra la pantalla inicial. Si una frecuencia o la espera de respuesta no es un número positivo, o si el contrato no trae los tipos de error esperados, lanza un error antes de escuchar nada.
- `stop()` quita todos los oyentes, desconecta los observadores y cancela los temporizadores y registros pendientes. No deja estado entre páginas: cada carga completa vuelve a ejecutar el módulo.

Del contexto (`ctx`) usa: `ctx.clock` (reloj común), `ctx.batcher` (`add` y `flush`), `ctx.session.get()` (tarea activa), `ctx.config.capture` (`mousemove_hz`, `scroll_hz`, `click_response_wait_ms`) y `ctx.contracts.enums.validation_error_type`.

## Qué registra

El formato de cada registro es `contracts/batches/events.schema.json`. Todos llevan `t` (reloj común), `type`, `screen` (URL y título, ver Privacidad) y `task_id`.

| Evento | Qué se guarda |
|---|---|
| `click`, `dblclick`, `contextmenu` | Coordenadas del puntero (`x`, `y`), descriptor del elemento y `data: {}` |
| `mousemove` | Coordenadas del puntero (`x`, `y`). Sin elemento, para no recorrer la página decenas de veces por segundo. Como máximo `capture.mousemove_hz` por segundo (50) |
| `scroll` | Posición de la página en `data.scroll_x` y `data.scroll_y` (nunca negativa). Sin `x` ni `y`: esos campos son siempre la posición del puntero. Como máximo `capture.scroll_hz` por segundo (10). Solo el scroll de la página; el de cajas internas se ignora |
| `selection` | Solo la longitud de lo seleccionado, en `data.length`; nunca el texto. Se registra una vez, cuando la selección lleva 300 ms sin cambiar. No se registra si está vacía ni si empieza o termina en un campo |
| `focus_in`, `focus_out` | El campo (`input` salvo `hidden`, `textarea`, `select` o zona editable), descrito él mismo y no el interactivo más cercano. `data: {}` |
| `field_change` | El campo y solo que hubo un cambio; nunca el valor. Como máximo uno por segundo por campo |
| `form_submit` | El formulario. El navegador solo lo avisa si pasó la validación; un intento con errores genera `validation_error` |
| `validation_error` | El campo y el tipo de error en `data.error_type` (`validation_error_type`). Tres orígenes, ver abajo |
| `click_response` | Solo si la página respondió a un `click` en `capture.click_response_wait_ms` (1,5 s): `data.click_t` (el `t` del clic), `data.mutation_count` y `data.navigated` |
| `screen_change` | La pantalla nueva, en `screen`. Se registra al iniciar la captura y cuando la dirección cambia |

`camera_gap` es un tipo de evento del contrato, pero lo produce el módulo de cámara, no este.

### Muestreo de cursor y scroll

El primer movimiento o scroll se registra de inmediato. Los que llegan antes de que pase el intervalo mínimo (1000 ÷ frecuencia) no se pierden: se guarda el último y se registra al cumplirse el intervalo, para conservar la posición donde terminó el movimiento. `t` es la hora de entrega, así que dos registros nunca quedan más cerca que el intervalo. Los oyentes son pasivos.

### Cambios de pantalla

Cada carga de página ejecuta de nuevo el módulo, que al iniciar registra la pantalla actual: la de cada carga completa o la primera de la sesión si se inició sobre una página ya cargada. Para las aplicaciones de una sola página, el módulo (que corre en un contexto aislado y no puede interceptar el `pushState` de la página) compara `location.href` cada 250 ms y, 50 ms después de cada `popstate` o `hashchange`, para dar tiempo a la página de actualizar su título. Solo cuenta la dirección: un cambio de `#` es un cambio de pantalla y un cambio solo del título no lo es.

**Espera del título.** Muchas aplicaciones actualizan el título un instante después de la dirección (se observó en react.dev y GitHub), y registrar de inmediato dejaba la misma URL con dos títulos. Por eso, al detectar un cambio de dirección el módulo mira el título cada 50 ms y registra el `screen_change` en cuanto el título es distinto del de la pantalla anterior, o a los 500 ms como máximo si no cambia (hay páginas que no lo cambian). El registro lleva la **hora de la detección** (`t`) y la tarea de ese momento, aunque se entregue después, así que no altera el orden de los eventos. Si llega otro cambio de dirección mientras se espera, el anterior se registra de inmediato con el título que se alcanzó a ver. Un cambio pendiente no se pierde al cerrar la sesión (`stop`) ni al descargarse la página (`pagehide`).

Límites: un cambio de ida y vuelta (A → B → A) en menos de 250 ms no se ve; y una página que tarde más de 500 ms en actualizar el título seguirá dejando el título anterior.

### Respuesta tras un clic y clics muertos

Cada `click` crea un `MutationObserver` propio sobre todo el documento (hijos, atributos y texto), antes de que el sitio atienda el clic. Al terminar la espera se cuentan los cambios, incluidos los que el navegador aún no había entregado, y el observador se desconecta. Se registra `click_response` si hubo cambios o si `navigated` es verdadero: la URL cambió (aplicaciones de una sola página, también con `#`) o la página se descargó durante la espera. En ese último caso se registra de inmediato y se vacía el acumulador, que ya había vaciado lo suyo con el mismo aviso.

**Si no hubo nada, no se registra nada**: un `click` sin su `click_response` (unido por `click_t`) es lo que el análisis toma como clic muerto. Solo se vigila `click`, no `dblclick` ni `contextmenu`. `stop()` abandona las esperas pendientes sin registrar nada.

Limitación: en una página con cambios constantes (un reloj, un carrusel) todos los clics parecerán tener respuesta, y no se detectarán clics muertos.

### Errores de validación

Tres orígenes, en este orden de prioridad:

1. **Nativa:** el evento `invalid` que el navegador dispara en cada campo inválido al intentar enviar. Se registra el primer problema de `validity` según el orden de la enumeración del contrato (las propiedades se derivan de ella: `value_missing` → `valueMissing`). Cada intento fallido se registra.
2. **`aria-invalid`:** un observador que mira solo ese atributo en todo el documento registra cuando un campo pasa a `"true"`.
3. **Mensaje visible:** 200 ms después de salir de un campo se comprueba si tiene un mensaje de error visible con texto, declarado con `aria-errormessage` o, entre los de `aria-describedby`, uno con `role="alert"` o con `err`, `invalid` o `danger` en su `id` o `class` (para no tomar el texto de ayuda como error). Solo se mira si hay texto, no cuál es.

Los orígenes 2 y 3 se registran una sola vez mientras el error siga presente, y de nuevo si desaparece y reaparece.

### Tarea activa

`task_id` es la tarea activa de `ctx.session.get()`, o `null` si no hay tarea o sesión. **Es la del momento del hecho, no la de la entrega:** los registros que se entregan después (`click_response`, `selection`, `validation_error` de aria y de mensaje visible, y `mousemove` y `scroll` retrasados) llevan la tarea que estaba activa cuando ocurrió lo que los causó. Así, si un clic termina la tarea, su respuesta sigue siendo de esa tarea aunque ya se haya cerrado cuando se entrega.

## Descriptor del elemento

Forma de `contracts/element.schema.json`:

| Campo | Cómo se obtiene |
|---|---|
| `tag`, `id` | Etiqueta en minúsculas y atributo `id` (o `null`) |
| `role` | El atributo `role` o, si no tiene, el rol implícito de la etiqueta (`a` con `href` → `link`, `h1`–`h6` → `heading`, `input` según su `type`…) |
| `text` | Texto visible con espacios colapsados, recortado a 50 caracteres; `null` si no hay o si una regla de privacidad lo impide |
| `selector` | `#id` o la ruta desde `body` con `:nth-of-type` |
| `box` | `getBoundingClientRect()` como `x`, `y`, `w`, `h` |
| `interactive` | Enlace con `href`, botón, campo, elemento con rol interactivo o con `onclick` |

**Elemento interactivo más cercano:** si el clic cae en un `span` dentro de un botón, se describe el botón. Si ningún ancestro es interactivo, se describe el destino exacto. Los eventos de formulario describen siempre el campo mismo.

## Privacidad

**Regla:** nunca se guarda lo que el participante escribe, ni nada de los campos de contraseña. La captura no lee `value` ni los datos del evento `input` (`data`, `inputType`), y solo registra que un campo cambió y cuál es.

| Dato | Regla |
|---|---|
| `text` del descriptor | Solo en elementos **interactivos** (botones, enlaces, pestañas…). En contenedores, párrafos, títulos y mensajes es `null`: podrían repetir lo que el participante escribió (un mensaje enviado, una vista previa) o mostrar datos personales, y los pasos de una tarea son solo clics en interactivos |
| `text` en campos | `null` en `input`, `textarea` y `select` (incluidas las contraseñas), en zonas `contenteditable`, en cuadros de texto personalizados (rol `textbox`, `searchbox`, `combobox` o `spinbutton`) y en todo elemento que esté dentro de uno, que contenga uno o contenga un `textarea` (su contenido inicial puede ser texto ya escrito) |
| `text` de elementos grandes | `null` si el elemento tiene más de 1000 caracteres de texto: no sirve como etiqueta y leerlo tardaba más de 100 ms en un enlace que envolvía una página entera |
| `selection` | Solo la longitud. No se registra si la selección empieza o termina en un campo, una zona editable o un cuadro de texto personalizado |
| `screen.url` | Se quitan usuario y clave de la dirección y se reemplaza por `redacted` el valor de los parámetros sensibles, tanto en la búsqueda (`?q=…`) como en el fragmento (`#access_token=…`, `#/buscar?q=…`): `q`, `query`, `search`, `s`, `keyword`, `keywords`, `term`, `email`, `user`, `username`, `token`, `access_token`, `id_token`, `refresh_token`, `key`, `api_key`, `apikey`, `password`, `pass`, `pwd`, `auth`, `session`, `sid`, `code` y `otp`. El resto se conserva (`?view=cart&id=1`, `#/ruta`), porque muchas aplicaciones identifican la pantalla con ellos. Aplica a todos los registros; un cambio solo en un parámetro redactado sigue registrándose como cambio de pantalla |
| `screen.title` | Se guarda tal cual, **salvo cuando la URL tuvo que redactarse**: entonces va vacío (el contrato admite un título vacío), porque el título de una página de resultados suele repetir lo buscado ("Resultados de …") |

**Límites conocidos** (no se pueden resolver desde la captura):

- Un sitio que escriba lo buscado en el título sin ponerlo en la URL (por ejemplo, con una petición en segundo plano) lo dejaría en la base.
- El `text` de un elemento **interactivo** que repita lo escrito (un botón que muestra tu último mensaje) se guarda tal cual, recortado a 50 caracteres.
- El `id` y el `selector` se toman de la página tal como están.
- Un campo que dibuja lo escrito con `div` sin rol de cuadro de texto ni `contenteditable` (algunos editores de código) no se distingue del contenido normal; su texto solo se guardaría si el elemento clicado es interactivo.
- Los *iframes* no se capturan.

## Rendimiento

Medido en Chrome sobre una página con unos 12 000 elementos, cargando el módulo con un contexto de prueba (microsegundos o milisegundos por evento, solo lo que cuesta la captura):

| Qué | Costo |
|---|---|
| `mousemove` | 1,4 µs por evento (a 50 por segundo, despreciable) |
| `scroll` | 35 µs por evento (la lectura de la posición de la página) |
| `click` | Unos 0,4 ms; hasta 1 ms en la página grande |
| Cambios de la página mientras espera un clic | +0,35 µs por cambio y por clic en espera |
| `click` en un enlace que envuelve toda una página | 0,7 ms (antes de limitar el texto, 129 ms) |

## Cómo se prueba

**Pruebas automáticas**, con un DOM mínimo en memoria, reloj y temporizadores falsos (`extension/tests/capture.test.js`):

```bash
npm test
```

Cubren cada tipo de evento, el muestreo, la tarea del momento del hecho, el estado de sesión real y la privacidad: valores "canario" en todo tipo de campo, y campos y eventos que lanzan un error si el código lee `value`, `data` o `inputType`. Para comprobar que las pruebas de privacidad detectan fallos, se rompió cada regla a propósito y alguna prueba falló en cada caso.

**Prueba manual** con la página de prueba:

1. `python -m scripts.init_db` y `python -m scripts.load_study studies/example.yaml`; luego `python -m server` y, en otra terminal, `python -m scripts.serve_test_page`.
2. Carga `extension/` en Chrome (o recárgala en `chrome://extensions`). **Recarga la pestaña de la página antes de iniciar la sesión**: una pestaña abierta antes no tiene el módulo y el panel avisa "La pestaña todavía no respondió".
3. Abre `http://127.0.0.1:8766/`, inicia una sesión desde el panel y haz clics (simple, doble y derecho), escribe en los formularios, selecciona texto, desplázate y navega; cierra la sesión.
4. Revisa los eventos en la base:

   ```bash
   python -c "import sqlite3; c = sqlite3.connect('data/suca.db'); print(c.execute('SELECT type, COUNT(*) FROM event GROUP BY type').fetchall())"
   ```

**Privacidad en la base:** escribe en los formularios textos reconocibles (por ejemplo `CANARIO-1`) y búscalos en todas las columnas de todas las tablas de `data/suca.db`, distinguiendo mayúsculas. No debe haber ninguna coincidencia fuera de los límites conocidos de arriba.

## Cómo agregar un tipo de evento

1. **Contrato:** revisa su forma en `contracts/batches/events.schema.json` y su valor en `event_type` de `contracts/enums.json`. Si falta algo, abre un *issue* con la etiqueta `contract`: no se edita aquí.
2. **Oyente:** agrega una función que reciba el evento del navegador y, en `start`, regístrala en `root.document` (o en `root`) en fase de captura; en `stop`, quítala con los mismos argumentos. Si necesita una frecuencia o una espera, léela de `ctx.config.capture` y valídala en `start` con `requirePositive`.
3. **Registro:** entrégalo con `record(t, tipo, campos)`, que agrega `screen` (con la URL ya redactada) y `task_id`. Si el registro se entrega **después** del hecho (con un temporizador o un observador), lee `activeTask()` en el momento del hecho y pásalo como cuarto argumento.
4. **Privacidad:** no leas `value` ni los datos del evento; no guardes texto salvo con las reglas de `textOf`; si usa un elemento, descríbelo con `describe`.
5. **Limpieza:** todo temporizador, observador o estado que cree debe cancelarse o reiniciarse en `stop`.
6. **Pruebas:** agrega sus pruebas a `extension/tests/capture.test.js`, incluida la de `task_id`, y revisa que la prueba de "un registro de cada tipo de evento" siga cubriendo todos los tipos del contrato (falla si aparece uno nuevo sin cubrir) y que la matriz de privacidad lo incluya.
7. **Documentación:** descríbelo en la tabla de arriba y en este README.
