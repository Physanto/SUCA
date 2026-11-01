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

**Respuesta tras un clic y clics muertos.** Cada `click` crea un `MutationObserver` propio sobre todo el documento (hijos, atributos y texto), antes de que el sitio atienda el clic. Al terminar la espera se cuentan los cambios, incluidos los que el navegador aún no había entregado, y el observador se desconecta. Se registra `click_response` si hubo cambios o si `navigated` es verdadero: la URL cambió (aplicaciones de una sola página, también con `#`) o la página se descargó durante la espera (en ese caso se registra de inmediato y se vacía el acumulador, que ya había vaciado lo suyo con el mismo aviso). **Si no hubo nada, no se registra nada**: un `click` sin su `click_response` (unido por `click_t`) es lo que el análisis toma como clic muerto. Solo se vigila `click`, no `dblclick` ni `contextmenu`. `stop()` abandona las esperas pendientes sin registrar nada.

Limitación: en una página con cambios constantes (un reloj, un carrusel) todos los clics parecerán tener respuesta, y no se detectarán clics muertos.

**Errores de validación.** Tres orígenes, en este orden de prioridad:

1. **Nativa:** el evento `invalid` que el navegador dispara en cada campo inválido al intentar enviar. Se registra el primer problema de `validity` según el orden de la enumeración del contrato (las propiedades se derivan de ella: `value_missing` → `valueMissing`). Cada intento fallido se registra.
2. **`aria-invalid`:** un observador que mira solo ese atributo en todo el documento registra cuando un campo pasa a `"true"`.
3. **Mensaje visible:** 200 ms después de salir de un campo se comprueba si tiene un mensaje de error visible con texto, declarado con `aria-errormessage` o, entre los de `aria-describedby`, uno con `role="alert"` o con `err`, `invalid` o `danger` en su `id` o `class` (para no tomar el texto de ayuda como error). Solo se mira si hay texto, no cuál es.

Los orígenes 2 y 3 se registran una sola vez mientras el error siga presente, y de nuevo si desaparece y reaparece.

**Muestreo.** El primer movimiento o scroll se registra de inmediato. Los que llegan antes de que pase el intervalo mínimo (1000 ÷ frecuencia) no se pierden: se guarda el último y se registra al cumplirse el intervalo, para conservar la posición donde terminó el movimiento. Las frecuencias se leen de `ctx.config.capture` al iniciar; si no son números positivos, el módulo no arranca. Los oyentes son pasivos y `stop()` descarta lo pendiente.

Todos los registros llevan `t` (reloj común), `screen` (URL y título actuales) y `task_id` (la tarea activa de `ctx.session.get()`, o `null`). El formato es `contracts/batches/events.schema.json`.

Los demás tipos de evento (cambios de pantalla) se agregan en las siguientes tareas de M1 y se documentan aquí al hacerlo.

## Descriptor del elemento

Forma de `contracts/element.schema.json`:

| Campo | Cómo se obtiene |
|---|---|
| `tag`, `id` | Etiqueta en minúsculas y atributo `id` (o `null`) |
| `role` | El atributo `role` o, si no tiene, el rol implícito de la etiqueta (`a` con `href` → `link`, `h1`–`h6` → `heading`, `input` según su `type`…) |
| `text` | Texto visible con espacios colapsados, recortado a 50 caracteres; `null` si no hay |
| `selector` | `#id` o la ruta desde `body` con `:nth-of-type` |
| `box` | `getBoundingClientRect()` como `x`, `y`, `w`, `h` |
| `interactive` | Enlace con `href`, botón, campo, elemento con rol interactivo o con `onclick` |

**Elemento interactivo más cercano:** si el clic cae en un `span` dentro de un botón, se describe el botón. Si ningún ancestro es interactivo, se describe el destino exacto.

## Privacidad

- `text` es `null` en `input`, `textarea` y `select` (incluidas las contraseñas), dentro de una zona `contenteditable` y en elementos que contienen una.
- Nunca se lee `value` ni ningún contenido escrito.
- Los eventos de formulario nunca leen `value` ni los datos del evento `input` (`data`, `inputType`).
- `text` también es `null` en los elementos con rol de cuadro de texto (`textbox`, `searchbox`, `combobox`, `spinbutton`) y en los que contienen un `textarea` (su contenido inicial puede ser texto ya escrito).
- De una selección solo se guarda su longitud, y no se guarda la hecha dentro de campos.

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
