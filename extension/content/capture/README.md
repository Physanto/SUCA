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

**Muestreo.** El primer movimiento o scroll se registra de inmediato. Los que llegan antes de que pase el intervalo mínimo (1000 ÷ frecuencia) no se pierden: se guarda el último y se registra al cumplirse el intervalo, para conservar la posición donde terminó el movimiento. Las frecuencias se leen de `ctx.config.capture` al iniciar; si no son números positivos, el módulo no arranca. Los oyentes son pasivos y `stop()` descarta lo pendiente.

Todos los registros llevan `t` (reloj común), `screen` (URL y título actuales) y `task_id` (la tarea activa de `ctx.session.get()`, o `null`). El formato es `contracts/batches/events.schema.json`.

Los demás tipos de evento (formularios, respuesta tras un clic y cambios de pantalla) se agregan en las siguientes tareas de M1 y se documentan aquí al hacerlo.

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
