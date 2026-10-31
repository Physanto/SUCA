# App de prueba: tienda Ceiba

Tienda en línea ficticia sobre la que se valida el sistema. Tiene tres versiones con el mismo código:

| Versión | Problemas sembrados |
|---|---|
| **V0** | Ninguno: la tienda sigue buenas prácticas de usabilidad |
| **V1** | Problemas 1 a 4 |
| **V2** | Problemas 1 a 8 (los de V1 y cuatro más) |

Además, la versión **personalizada** activa cualquier combinación de problemas, uno por uno.

El catálogo de problemas, con su ubicación, tipo, comportamiento esperado y detector esperado, está en [PROBLEMS.md](PROBLEMS.md).

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
| Envío | Viene lleno con los datos de la cuenta (dirección `Carrera 7 # 45-12`, Medellín) |
| Pago con tarjeta | Número `4111 1111 1111 1111`, nombre `ANA GOMEZ`, vencimiento `12/29`, código `123` |

Los datos que se muestran son los mismos en todas las versiones. En V1 y V2, el pago exige formatos más estrictos que los mostrados (problemas 4 y 6 de [PROBLEMS.md](PROBLEMS.md)).

## Pantallas

| Ruta | Pantalla | Sesión |
|---|---|---|
| `/login` | Inicio de sesión | — |
| `/` | Inicio: portada, categorías y destacados | — |
| `/search?q=…` | Resultados de búsqueda | — |
| `/products` | Todos los productos | — |
| `/category/{slug}` | Listado de una categoría | — |
| `/offers` | Ofertas | — |
| `/product/{id}` | Detalle de producto, con opiniones en `#resenas` | — |
| `/cart` | Carrito | — |
| `/checkout/shipping` | Compra, paso 1: envío | Requerida |
| `/checkout/payment` | Compra, paso 2: pago | Requerida |
| `/order/{id}/confirmation` | Compra, paso 3: pedido confirmado | Requerida |
| `/account` | Mi cuenta: datos, dirección y pedidos | Requerida |
| `/account/address` | Dirección de envío | Requerida |
| `/account/profile` | Datos personales | Requerida |
| `/account/orders/{id}` | Detalle de un pedido | Requerida |
| `/help` | Centro de ayuda; cada pregunta tiene un ancla (`/help#olvide-mi-contrasena`) | — |
| `/terms.html` | Términos y condiciones: página aparte, fuera de la aplicación | — |
| `/setup` | Página del evaluador | — |

Sin sesión iniciada, las rutas que la requieren llevan a `/login` y, al ingresar, vuelven a la ruta pedida.

### Comportamientos de sitios reales

La tienda incluye a propósito comportamientos comunes en la web que una herramienta de captura debe manejar:

| Comportamiento | Dónde |
|---|---|
| Cambio de pantalla con `pushState`, botón Atrás con `popstate` y recarga de cualquier ruta | Toda la tienda |
| Ids numéricos en la ruta (`/product/101`, `/order/5012/confirmation`) | Detalle, confirmación, pedidos |
| Consulta que cambia sin cambiar de pantalla (`replaceState`, sin entrada nueva en el historial) | Ordenar y filtrar listados (`?sort=price_asc&discount=1`) |
| Contenido que se agrega sin navegar | "Cargar más productos" |
| Ancla en la misma pantalla (solo cambia el fragmento) | "Ver opiniones" (`#resenas`) |
| Ancla en otra pantalla | "¿Olvidaste tu contraseña?" → `/help#olvide-mi-contrasena` |
| Navegación completa a otro documento | `/terms.html` y su regreso |
| Redirecciones | Rutas con sesión requerida, compra con el carrito vacío |
| Diálogo modal (`<dialog>`) que se cierra con Escape o con un clic fuera | "Ampliar imagen" |
| Menú desplegable con `aria-expanded` | "Mi cuenta" |
| Secciones desplegables (`details`) | Centro de ayuda |
| Carga asíncrona con indicador ("Cargando…", "Agregando…") | Pantallas con datos y botones de acción |
| Avisos emergentes y mensajes `role="status"` | Carrito, dirección, datos personales |
| Validación nativa del navegador | Inicio de sesión, boletín |
| Validación propia con `aria-invalid` y mensajes por campo | Envío, pago, cuenta |
| Campo de contraseña que pasa a texto | "Mostrar contraseña" |
| Formulario opcional, ajeno a las tareas | Boletín del pie |
| Foco que se mueve al título al cambiar de pantalla | Toda la tienda |

Las sugerencias de búsqueda mientras se escribe se dejaron fuera a propósito: abrirían una segunda ruta para la tarea 1 (ir al producto sin pasar por los resultados).

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
│   ├── terms.html      términos y condiciones, fuera de la aplicación
│   ├── css/styles.css
│   ├── images/         ilustraciones SVG propias
│   └── js/
│       ├── main.js     punto de composición: versión, estado, rutas y dibujo
│       ├── versions.js configuración de versiones y catálogo de problemas
│       ├── settings.js versión guardada y parámetros de la URL
│       ├── shop.js     estado de la tienda y sus acciones
│       ├── router.js   rutas con el historial del navegador
│       ├── data.js     productos, cuenta y tarjeta de prueba
│       ├── search.js, cart.js, listing.js, validation.js, format.js, reviews.js   lógica sin DOM
│       ├── dom.js, ui.js, fields.js, layout.js             piezas de interfaz
│       ├── timing.js   tiempos de respuesta simulados
│       └── views/      una pantalla por archivo (listing.js: listado compartido)
├── tests/              pruebas de la lógica con node --test
└── e2e/                recorrido automático en Chrome sin interfaz
```

Sin librerías, sin empaquetador y sin red: módulos ES que el navegador carga directamente.

## Pruebas

```bash
npm test                                   # lógica de la tienda (y la extensión), con node --test
python -m pytest tests/config/test_serve_test_app.py   # servidor de la app
```

**Recorrido en Chrome.** Con la app servida, `node test-app/e2e/walkthrough.js` abre Chrome sin interfaz, en una ventana de 920 × 800 (el espacio que deja el panel lateral). Se comporta como una persona, con clics del ratón y texto desde el teclado:

1. inicia sesión y hace las 4 tareas del estudio de ejemplo;
2. después prueba las demás funciones: listados, diálogo, anclas, cuenta, boletín, página de términos y recuperación de contraseña.

Falla si:
- alguna tarea no llega a su estado final;
- ordenar o saltar a un ancla cambia de pantalla;
- la página muestra `null`, `undefined` o `NaN`;
- hay errores de JavaScript.

```bash
node test-app/e2e/walkthrough.js                    # V0 en http://127.0.0.1:8767
node test-app/e2e/walkthrough.js --version V1 --url http://127.0.0.1:8767
```

Pasa en V0, V1 y V2: así se comprueba que los problemas sembrados no cambian la ruta ideal de ninguna tarea.

**Problemas sembrados.** `node test-app/e2e/problems.js` comprueba cada problema por separado. Con solo ese problema activo debe verse el problema, y en V0 el comportamiento correcto. El detalle está en [PROBLEMS.md](PROBLEMS.md).

Busca Chrome en las ubicaciones habituales; si está en otra, indícala con la variable `CHROME_PATH`. No se ejecuta en la integración continua.

## Validar V0 con una persona ajena

Antes del piloto, alguien que no conoce el proyecto debe completar las 4 tareas en V0 sin ayuda. Si no lo logra, V0 tiene un problema que nadie sembró, y eso arruinaría la comparación entre versiones.

1. **La persona:** mayor de edad y sin participación en el proyecto. No se registran su nombre ni ningún dato suyo.
2. **Preparación:**
   - sirve la app;
   - en `/setup` elige **V0** y pulsa **Guardar y preparar para un participante**;
   - deja la ventana del tamaño que tendrá en las sesiones (con el panel lateral de Chrome abierto, si se usará). No hace falta la extensión.
3. **Instrucciones a la persona:** "Vas a usar una tienda en línea de prueba. Primero inicia sesión con la cuenta de demostración que aparece en la pantalla. Luego te daré cuatro tareas, una a la vez; hazlas como las harías en casa. Evaluamos la tienda, no a ti. Si te atascas, dímelo, pero no podré ayudarte."
4. **Tareas:** lee en voz alta, una a la vez, las instrucciones de `studies/example.yaml`, sin cambiarlas ni explicarlas, y deja a la vista la tarea escrita (una tarjeta por tarea): la 4 tiene una dirección que hay que copiar. Pasa a la siguiente cuando la persona diga que terminó.
5. **Durante la prueba:** no ayudes, no señales y no confirmes. Si pide ayuda, responde: "¿Qué harías si estuvieras solo?". Una tarea que pasa de 5 minutos cuenta como no completada.
6. **Registro, por tarea:**
   - si la completó sin ayuda;
   - el tiempo aproximado;
   - dónde dudó o se equivocó.

   Al final, pregúntale qué le resultó difícil. Las notas van fuera del repositorio y nunca con datos de la persona.
7. **Criterio:** las 4 tareas completadas sin ayuda. Si alguna falla, corrige lo que causó el problema en V0 y repite con **otra** persona: la primera ya conoce las tareas.

## Problemas frecuentes

| Síntoma | Causa y solución |
|---|---|
| La versión elegida "se pierde" o aparece el carrito de otra sesión | La tienda guarda sus datos por dirección: `localhost:8767` y `127.0.0.1:8767` son tiendas distintas para el navegador. Usa siempre `http://127.0.0.1:8767` |
| Quedó el carrito, el pedido o la dirección del participante anterior | Prepara la tienda en `/setup` (o abre `/login?version=…`) antes de cada participante |
| La página queda en blanco | La app se abrió como archivo o con otro servidor. Sírvela con `python -m scripts.serve_test_app`, que entrega los módulos de JavaScript con el tipo correcto también en Windows |
| Un cambio en el código no se ve | Recarga la página. El servidor pide no guardar caché, pero una pestaña abierta conserva el código hasta recargar |
| El puerto 8767 está ocupado | Cambia `test_app.port` en `config/shared.json` |

## Cómo extenderla

**Agregar un problema sembrado:**

1. Agrégalo al catálogo `PROBLEMS` de `public/js/versions.js` (clave, número, título y pantalla) y, si corresponde, a una versión en `VERSIONS`.
2. En la pantalla afectada, cambia el comportamiento solo si está activo: `if (ctx.problems.has('mi_problema')) { … }`.
3. Comprueba que no cambia la ruta ideal de ninguna tarea (pantallas, textos y roles de los pasos).
4. Documéntalo en `PROBLEMS.md`, agrega su comprobación a `e2e/problems.js` y una prueba de su lógica si la tiene.

**Agregar una pantalla:** crea `public/js/views/mi-pantalla.js` con una función `render(ctx, { params, query })` que devuelve `{ title, node }` (o `{ redirect }`, o `{ notFound: true }`) y regístrala en `ROUTES` de `public/js/main.js`. Si la pantalla carga datos, espera `LATENCY.page` para simular el servidor. Cada pantalla tiene un `h1` con `tabindex="-1"`, que recibe el foco al llegar.

**Reglas:** el código va en inglés y los textos del sitio en español. Nada en la tienda puede depender de la extensión ni facilitarle la captura.
