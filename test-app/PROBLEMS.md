# Problemas sembrados de la tienda Ceiba

Catálogo de los problemas de usabilidad que se activan por versión. Para cada uno: dónde está, qué tipo de problema es, en qué se diferencia de V0, qué se espera que hagan los participantes y qué detector del análisis debería identificarlo.

| # | Clave (`versions.js`) | Problema | Pantalla | Tarea | V1 | V2 |
|---|---|---|---|---|---|---|
| 1 | `button_like_image` | Imagen que parece botón pero no lo es | Detalle de producto | 2 | ✓ | ✓ |
| 2 | `slow_add_to_cart` | Botón que tarda 3 s en responder sin indicador de carga | Detalle de producto | 2 | ✓ | ✓ |
| 3 | `illogical_account_menu` | Opción importante dentro de un menú poco lógico | Menú "Mi cuenta" | 4 | ✓ | ✓ |
| 4 | `form_clears_on_error` | Formulario que borra los datos al mostrar un error | Pago | 3 | ✓ | ✓ |
| 5 | `low_contrast_link` | Enlace con bajo contraste | Mi cuenta | 4 | | ✓ |
| 6 | `ambiguous_error` | Mensaje de error ambiguo | Pago | 3 | | ✓ |
| 7 | `slow_login` | Inicio de sesión lento y sin retroalimentación | Iniciar sesión | (antes de la tarea 1) | | ✓ |
| 8 | `strict_search` | Buscador que no tolera errores de escritura | Búsqueda | 1 | | ✓ |

Las tareas son las de `studies/example.yaml`. Cualquier combinación se activa con la versión personalizada (`/setup` o `?problems=1,4`).

## Reglas de diseño

- **Realistas, no evidentes.** Cada problema existe en sitios reales y se puede superar sin ayuda.
- **La ruta ideal no cambia.** Las pantallas, los textos y los roles de los pasos ideales son los mismos en V0, V1 y V2. Los problemas agregan fricción sobre esa ruta, así una sola referencia grabada sirve para las tres versiones. Lo comprueba `e2e/walkthrough.js`, que pasa en las tres.
- **V0 es la versión bien hecha** del mismo elemento: respuesta visible en menos de 100 ms, indicadores de carga, errores claros que conservan lo escrito y contraste AA.
- **Un clic "sin respuesta"** es uno tras el cual la página no cambia en 1,5 s, el tiempo que la captura observa la página. Los problemas 1, 2 y 7 no cambian **nada** del DOM en ese tiempo, ni siquiera un atributo.
- **Revisión en el piloto.** Si un problema no afecta a los participantes, o los afecta demasiado, se ajusta antes del experimento.

---

## 1. Imagen que parece botón pero no lo es

- **Ubicación:** detalle de producto (`/product/{id}`), bajo la imagen del producto.
- **Tipo:** affordance falsa (un elemento que parece interactivo y no lo es).
- **V0:** botón "Ampliar imagen" que abre la imagen grande en un diálogo.
- **Con el problema:** en su lugar hay una imagen (`img`) con el aspecto exacto del botón: borde, lupa, el texto "Ampliar imagen" y cursor de mano. Pulsarla no hace nada.
- **Comportamiento esperado:** uno o dos clics en la imagen, quizás más, y luego seguir con la tarea.
- **Detector esperado:** `dead_click` (clic en un elemento no interactivo sin cambios en la página). Si insiste rápido: `rage_click`.
- **Ruta ideal:** no la toca; ampliar la imagen no es parte de ninguna tarea.

## 2. Botón que tarda 3 s en responder sin indicador de carga

- **Ubicación:** detalle de producto, botón "Agregar al carrito" (tarea 2).
- **Tipo:** falta de retroalimentación del estado del sistema.
- **V0:** el botón cambia al instante a "Agregando…" con un indicador, y en menos de medio segundo lleva al carrito.
- **Con el problema:** durante 3 s no cambia nada en la página. Los clics de mientras se ignoran (el carrito recibe una sola vez las unidades elegidas). Después lleva al carrito como en V0.
- **Comportamiento esperado:** varios clics seguidos en el botón, pensando que no funcionó.
- **Detector esperado:** `rage_click`. Cada clic también queda sin respuesta en 1,5 s: `dead_click`.
- **Ruta ideal:** el mismo botón, la misma pantalla de llegada y la misma cantidad en el carrito.

## 3. Opción importante dentro de un menú poco lógico

- **Ubicación:** menú del botón "Mi cuenta" del encabezado (tarea 4).
- **Tipo:** organización y nombres poco claros (arquitectura de la información).
- **V0:** el menú tiene "Ver mi cuenta", "Mis pedidos", "Ayuda" y "Cerrar sesión".
- **Con el problema:** el menú tiene siete opciones sin orden lógico: "Mi perfil", "Datos de envío", "Mis cupones", "Novedades", "Ayuda", "Mis pedidos" y "Ver mi cuenta", al final. Dos son señuelos:
  - "Mi perfil" lleva a los datos personales, que no tienen la dirección;
  - "Datos de envío" lleva a la ayuda sobre tiempos de entrega.
- **Comportamiento esperado:** entrar a un señuelo, volver, releer el menú.
- **Detector esperado:** `navigation_loop` (ida y vuelta entre pantallas) y `long_pause` (más de 5 s sin interacción mientras busca).
- **Ruta ideal:** "Mi cuenta" → "Ver mi cuenta" → "Cambiar dirección de envío" → "Guardar". Los textos, roles y destinos son los mismos que en V0; solo cambia la posición dentro del menú.

## 4. Formulario que borra los datos al mostrar un error

- **Ubicación:** pago con tarjeta (`/checkout/payment`, tarea 3).
- **Tipo:** pérdida de trabajo del usuario ante un error, con un formato de entrada estricto.
- **V0:** el número de la tarjeta se acepta con o sin espacios. Si hay un error, se marca el campo, se explica qué corregir y lo escrito se conserva.
- **Con el problema:**
  - el número solo se acepta **sin espacios**. La tarjeta de prueba se muestra con espacios, como una real, y la regla solo aparece en el *placeholder* ("Solo números, sin espacios"), que no se ve mientras el campo tiene texto;
  - al pulsar "Pagar" con un error, **se borran los cuatro datos de la tarjeta**;
  - el mensaje del campo sí dice qué corregir ("sin espacios ni guiones").
- **Comportamiento esperado:** casi todos copian el número con espacios, reciben el error, ven el formulario vacío y vuelven a escribir todo.
- **Detector esperado:** `form_error` (aparece un error de validación) y `field_reentry` (vuelve a campos que ya había llenado).
- **Ruta ideal:** los mismos campos y el mismo botón; se completa al escribir el número sin espacios.

## 5. Enlace con bajo contraste

- **Ubicación:** "Mi cuenta" (`/account`), enlace "Cambiar dirección de envío" (tarea 4).
- **Tipo:** visibilidad (contraste por debajo de WCAG AA).
- **V0:** enlace verde, en negrita y subrayado; contraste mayor que 4,5:1.
- **Con el problema:** el mismo enlace en gris muy claro (contraste de alrededor de 1,6:1 sobre la tarjeta blanca), en letra pequeña y sin subrayado.
- **Comportamiento esperado:** recorrer la pantalla con el cursor y la mirada sin encontrarlo; detenerse sobre la tarjeta "Dirección de envío".
- **Detector esperado:** `hesitation` (cursor detenido sobre un elemento interactivo sin activarlo) y `long_pause`.
- **Ruta ideal:** el mismo texto, rol y destino.

## 6. Mensaje de error ambiguo

- **Ubicación:** pago con tarjeta (`/checkout/payment`, tarea 3).
- **Tipo:** mensajes de error que no ayudan a reconocer ni a corregir el error.
- **V0:** cada campo con error se marca y se explica (por ejemplo, el formato del vencimiento con un ejemplo).
- **Con el problema:**
  - el vencimiento solo se acepta como **MM/AAAA**. La tarjeta de prueba muestra "12/29", y la regla solo aparece en el *placeholder* ("MM/AAAA"); desaparece la ayuda "MM/AA" que V0 muestra sobre el campo;
  - cualquier error de los datos de la tarjeta se informa con un solo mensaje genérico: "No pudimos procesar el pago. Revisa los datos e inténtalo de nuevo. (Código E-102)", sin marcar ningún campo.
- **Comportamiento esperado:** reintentos sin cambios, pausas para releer y cambios en campos que estaban bien.
- **Detector esperado:** `form_error` repetido, `field_reentry` y `long_pause`.
- **En V2, junto con el problema 4:** el primer error suele ser por los espacios del número. El formulario se borra y el mensaje no dice por qué. Con los campos vacíos se ven los dos *placeholders* ("Solo números, sin espacios" y "MM/AAAA"), y eso permite resolverlo.
- **Ruta ideal:** los mismos campos y el mismo botón.

## 7. Inicio de sesión lento y sin retroalimentación

- **Ubicación:** "Iniciar sesión" (`/login`), botón "Ingresar", antes de la tarea 1.
- **Tipo:** falta de retroalimentación del estado del sistema en un episodio de inicio de sesión.
- **V0:** el botón cambia al instante a "Ingresando…" con un indicador, y entra en menos de un segundo.
- **Con el problema:** durante 4 s no cambia nada en la página, y los envíos de mientras se ignoran. Después entra (o muestra el error de credenciales) como en V0.
- **Comportamiento esperado:** varios clics en "Ingresar" o pulsar Enter de nuevo.
- **Detector esperado:** `rage_click` y `dead_click` en el botón, y un episodio `login` más largo.
- **Ruta ideal:** no la toca; el inicio de sesión ocurre antes de las tareas.

## 8. Buscador que no tolera errores de escritura

- **Ubicación:** búsqueda del encabezado y resultados (`/search?q=…`, tarea 1).
- **Tipo:** prevención de errores (el sistema no tolera variaciones razonables de lo que escribe la persona).
- **V0:** la búsqueda ignora mayúsculas y tildes, acepta prefijos ("audi") y tolera errores pequeños ("audfonos", "inlambricos").
- **Con el problema:** sigue ignorando mayúsculas y tildes, pero exige palabras completas y bien escritas. Con un error de escritura muestra "No encontramos productos…".
- **Comportamiento esperado:** quien escribe con un error repite la búsqueda corrigiendo una letra a la vez.
- **Detector esperado:** `repeated_search` (dos o más búsquedas en 60 s sin abrir un resultado).
- **Ruta ideal:** con "audífonos inalámbricos" (con o sin tildes) los resultados son los mismos que en V0.

---

## Comprobación

Con la app servida (`python -m scripts.serve_test_app`):

```bash
node test-app/e2e/problems.js                       # los 8 problemas
node test-app/e2e/problems.js --only 4              # uno solo
node test-app/e2e/walkthrough.js --version V2       # las 4 tareas siguen completándose
```

`problems.js` abre la tienda dos veces por problema: con solo ese problema (`?problems=N`), donde comprueba el problema, y en V0, donde comprueba el comportamiento correcto. Para los problemas de clics sin respuesta (1, 2 y 7) cuenta los cambios del DOM en 1,5 s, como la captura. Para el 5 mide la relación de contraste.

## Cómo agregar o cambiar un problema

1. Agrégalo al catálogo `PROBLEMS` de `public/js/versions.js` y, si corresponde, a una versión en `VERSIONS`.
2. Cambia el comportamiento solo con `ctx.problems.has('clave')` y deja intacta la ruta ideal.
3. Documéntalo aquí con el mismo formato y agrega su comprobación a `e2e/problems.js`.
