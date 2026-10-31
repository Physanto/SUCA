# App de prueba: tienda Ceiba

Tienda en línea ficticia sobre la que se valida el sistema. Tiene tres versiones con el mismo código:

| Versión | Problemas sembrados |
|---|---|
| **V0** | Ninguno: la tienda sigue buenas prácticas de usabilidad |
| **V1** | Problemas 1 a 4 |
| **V2** | Problemas 1 a 8 (los de V1 y cuatro más) |

Además, la versión **personalizada** activa cualquier combinación de problemas, uno por uno.

> **Estado:** las versiones ya se eligen y el catálogo de problemas está definido en `public/js/versions.js`, pero los problemas todavía no cambian la tienda: por ahora las tres versiones se comportan como V0. Cada problema se agregará con su documentación (ubicación, tipo, comportamiento esperado y detector esperado) en `PROBLEMS.md`.

La tienda no forma parte del sistema: es un sitio web más, que se evalúa como caja negra. No usa nada de la extensión ni tiene atributos, identificadores o avisos para facilitar la captura. Los productos, precios, cuentas y pagos son falsos: nada sale de la computadora.

## Servirla

```bash
python -m scripts.serve_test_app
```

Queda en `http://127.0.0.1:8767/` (puerto `test_app.port` de `config/shared.json`). Escucha solo en esta computadora. Como es una aplicación de una sola página con rutas reales, cualquier ruta sin extensión (`/product/101`, `/cart`…) devuelve `index.html`, así que recargar o abrir un enlace directo funciona.

## Preparar una sesión

Antes de iniciar la sesión en la extensión:

1. Abre `http://127.0.0.1:8767/setup`, la página del evaluador (no tiene enlaces desde la tienda).
2. Elige la versión, o **Personalizada** y los problemas que quieras.
3. Pulsa **Guardar y preparar para un participante**. Se cierra la sesión de la tienda, se vacían el carrito y los pedidos, la dirección vuelve a la inicial y se abre la pantalla de inicio de sesión.
4. En el panel lateral de la extensión elige **la misma versión**.

Atajo con el mismo efecto: abrir la tienda con un parámetro, por ejemplo `http://127.0.0.1:8767/login?version=V1` o `…/login?problems=2,7`. La tienda guarda la versión, deja todo listo para un participante nuevo y quita el parámetro de la dirección. Así las direcciones son idénticas en todas las versiones.

La versión elegida se guarda en el navegador (`localStorage`) y se mantiene al recargar, hasta que se elija otra.

### Datos de prueba

El participante nunca escribe datos propios: la tienda muestra los que necesita.

| Dónde | Dato |
|---|---|
| Inicio de sesión | Correo `ana.gomez@correo.test`, contraseña `Ceiba2026` |
| Envío | Viene lleno con los datos de la cuenta |
| Pago con tarjeta | Número `4111 1111 1111 1111`, nombre `ANA GOMEZ`, vencimiento `12/29`, código `123` |

## Pantallas

| Ruta | Pantalla | Sesión |
|---|---|---|
| `/login` | Inicio de sesión | — |
| `/` | Inicio: portada, categorías y destacados | — |
| `/search?q=…` | Resultados de búsqueda | — |
| `/category/{slug}` | Listado de una categoría | — |
| `/offers` | Ofertas | — |
| `/product/{id}` | Detalle de producto | — |
| `/cart` | Carrito | — |
| `/checkout/shipping` | Compra, paso 1: envío | Requerida |
| `/checkout/payment` | Compra, paso 2: pago | Requerida |
| `/order/{id}/confirmation` | Compra, paso 3: pedido confirmado | Requerida |
| `/account` | Mi cuenta: datos, dirección y pedidos | Requerida |
| `/account/address` | Dirección de envío | Requerida |
| `/help` | Centro de ayuda | — |
| `/setup` | Página del evaluador | — |

Sin sesión iniciada, las rutas que la requieren llevan a `/login` y, al ingresar, vuelven a la ruta pedida.

### Estados finales de las tareas del estudio de ejemplo

Son los que se pueden confirmar como condición final de cada tarea (`studies/example.yaml`). Son iguales en las tres versiones.

| Tarea | Estado final |
|---|---|
| 1. Buscar los audífonos y abrir el primero | Ruta `/product/101`, título "Audífonos inalámbricos SoundMax" |
| 2. Agregar dos unidades al carrito | Ruta `/cart`, texto "Audífonos inalámbricos SoundMax × 2" en el resumen |
| 3. Comprar pagando con tarjeta | Ruta `/order/{id}/confirmation`, texto "Pedido confirmado" |
| 4. Cambiar la dirección de envío | Ruta `/account/address`, texto "Dirección actualizada" |

La ruta ideal de cada tarea (pantallas, textos y roles de cada paso) es la misma en todas las versiones. Los problemas sembrados agregan fricción sobre esa ruta, sin cambiarla, para que una sola referencia grabada sirva para las tres versiones.

## Estructura

```
test-app/
├── package.json        marca los .js como módulos ES (también en las pruebas)
├── public/             lo que se sirve
│   ├── index.html      esqueleto: encabezado, contenido y pie
│   ├── css/styles.css
│   ├── images/         ilustraciones SVG propias
│   └── js/
│       ├── main.js     punto de composición: versión, estado, rutas y dibujo
│       ├── versions.js configuración de versiones y catálogo de problemas
│       ├── settings.js versión guardada y parámetros de la URL
│       ├── shop.js     estado de la tienda y sus acciones
│       ├── router.js   rutas con el historial del navegador
│       ├── data.js     productos, cuenta y tarjeta de prueba
│       ├── search.js, cart.js, validation.js, format.js   lógica sin DOM
│       ├── dom.js, ui.js, fields.js, layout.js             piezas de interfaz
│       ├── timing.js   tiempos de respuesta simulados
│       └── views/      una pantalla por archivo
├── tests/              pruebas de la lógica con node --test
└── e2e/                recorrido automático en Chrome sin interfaz
```

Sin librerías, sin empaquetador y sin red: módulos ES que el navegador carga directamente.

## Pruebas

```bash
npm test                                   # lógica de la tienda (y la extensión), con node --test
python -m pytest tests/config/test_serve_test_app.py   # servidor de la app
```

**Recorrido en Chrome.** Con la app servida, `node test-app/e2e/walkthrough.js` abre Chrome sin interfaz (en una ventana de 920 × 800, el espacio que deja el panel lateral) e inicia sesión y hace las 4 tareas del estudio de ejemplo como una persona: clics del ratón y texto desde el teclado. Falla si alguna tarea no llega a su estado final o si la página tiene errores de JavaScript.

```bash
node test-app/e2e/walkthrough.js                    # V0 en http://127.0.0.1:8767
node test-app/e2e/walkthrough.js --version V1 --url http://127.0.0.1:8767
```

Busca Chrome en las ubicaciones habituales; si está en otra, indícala con la variable `CHROME_PATH`. No se ejecuta en la integración continua.

## Cómo extenderla

**Agregar un problema sembrado:**

1. Agrégalo al catálogo `PROBLEMS` de `public/js/versions.js` (clave, número, título y pantalla) y, si corresponde, a una versión en `VERSIONS`.
2. En la pantalla afectada, cambia el comportamiento solo si está activo: `if (ctx.problems.has('mi_problema')) { … }`.
3. Comprueba que no cambia la ruta ideal de ninguna tarea (pantallas, textos y roles de los pasos).
4. Documéntalo en `PROBLEMS.md` y agrega una prueba de su lógica si la tiene.

**Agregar una pantalla:** crea `public/js/views/mi-pantalla.js` con una función `render(ctx, { params, query })` que devuelve `{ title, node }` (o `{ redirect }`, o `{ notFound: true }`) y regístrala en `ROUTES` de `public/js/main.js`. Si la pantalla carga datos, espera `LATENCY.page` para simular el servidor. Cada pantalla tiene un `h1` con `tabindex="-1"`, que recibe el foco al llegar.

**Reglas:** el código va en inglés y los textos del sitio en español. Nada en la tienda puede depender de la extensión ni facilitarle la captura.
