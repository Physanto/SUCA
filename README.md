# SUCA

<img width="1024" height="559" alt="image" src="https://github.com/user-attachments/assets/9e0a58c2-183e-4ed7-81c4-7068f3ee68d8" />

Sistema que evalúa automáticamente la usabilidad de aplicaciones web.

Una extensión de Chrome registra lo que hace el participante (clics, cursor, scroll, formularios y navegación), su mirada estimada por webcam y sus movimientos faciales, **sin modificar la aplicación evaluada**. Un servidor local guarda los datos; un análisis en Python detecta puntos de fricción y calcula un índice de usabilidad conductual (IUC); un panel en Streamlit muestra los resultados. El IUC complementa al cuestionario SUS, no lo reemplaza.

Todo corre en una sola computadora: sin nube y sin cuentas de usuario. El video de la cámara nunca se guarda ni se envía; solo se registran valores numéricos.

## Piezas del sistema

| Pieza | Carpeta | Qué hace | Tecnología |
|---|---|---|---|
| Extensión de navegador | `extension/` | Captura interacción, mirada y rostro; muestra las tareas al participante; graba referencias | Chrome (Manifest V3), JavaScript |
| Servidor local | `server/` | Recibe los datos, los valida y los guarda | Python, FastAPI, SQLite |
| Análisis | `analysis/` | Procesa las sesiones terminadas: segmenta, detecta fricción, compara con referencias y calcula el índice | Python, pandas |
| Panel de resultados | `dashboard/` | Muestra los resultados | Streamlit |

Las cuatro piezas se conectan mediante los **contratos** de `contracts/` (formatos de datos y valores permitidos) y comparten la configuración de `config/` y las utilidades de Python de `shared/`. La carpeta `test-app/` tiene la aplicación de prueba sobre la que se usa la extensión, una tienda con versiones V0, V1 y V2; no forma parte del sistema.

## Estructura del repositorio

```
├── config/          configuración única del sistema
├── contracts/       formatos de datos, enumeraciones y mensajes
├── shared/          utilidades de Python compartidas
├── extension/       extensión de Chrome (y su página de prueba)
├── server/          servidor local
├── analysis/        análisis de sesiones
├── dashboard/       panel de resultados
├── scripts/         preparación de la base, datos simulados y verificación
├── studies/         definición de estudios y tareas (YAML)
├── test-app/        aplicación de prueba
├── notebooks/       análisis estadístico
├── tests/           pruebas de Python
└── data/            datos locales (no se versiona)
```

Cada pieza tiene su README con el detalle: [extension/](extension/README.md), [server/](server/README.md), [analysis/](analysis/README.md), [dashboard/](dashboard/README.md), [contracts/](contracts/README.md), [scripts/simulation/](scripts/simulation/README.md) y [test-app/](test-app/README.md).

## Requisitos

- **Python 3.11** o superior.
  - **Windows:** instálalo desde python.org, marcando *Add python.exe to PATH*. Incluye el lanzador `py`.
  - **macOS:** desde python.org o con Homebrew (`brew install python@3.11`).
  - **Linux:** con el gestor de paquetes de la distribución.
- **Google Chrome 116** o superior.
- **Git.**
- **Node.js 22** o superior, solo para las pruebas de la extensión. La extensión no tiene dependencias de Node.

## Instalación

1. Clona el repositorio y entra en su carpeta:

   ```bash
   git clone <url-del-repositorio> SUCA
   cd SUCA
   ```

2. Crea un entorno virtual y actívalo:

   | Sistema | Crear | Activar |
   |---|---|---|
   | Linux y macOS | `python3 -m venv .venv` | `source .venv/bin/activate` |
   | Windows (PowerShell) | `py -3.11 -m venv .venv` | `.\.venv\Scripts\Activate.ps1` |
   | Windows (símbolo del sistema) | `py -3.11 -m venv .venv` | `.venv\Scripts\activate.bat` |

   Si PowerShell no deja ejecutar el script de activación, permite los scripts locales una sola vez: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

3. Con el entorno activo, instala las dependencias (las de desarrollo incluyen las de ejecución) y el repositorio en modo editable:

   ```bash
   python -m pip install -r requirements-dev.txt
   python -m pip install -e .
   ```

   El modo editable hace que `shared`, `server`, `analysis`, `dashboard` y `scripts` se puedan importar desde cualquier lugar.

4. Comprueba la instalación con la verificación rápida (tarda unos segundos):

   ```bash
   python -m scripts.verify_base --quick
   ```

**Todos los comandos de este README se escriben igual en Windows, macOS y Linux**, con el entorno virtual activo y desde la raíz del repositorio: con el entorno activo, `python` es siempre el del entorno. Las rutas usan `/`, que también funciona en Windows.

## Configuración

Toda la configuración está en un solo archivo, `config/shared.json`. Python la lee con `shared.config.load_config()`, que valida cada valor al cargarla y falla con un mensaje que nombra la clave errónea. Para usar otro archivo (por ejemplo, en pruebas), indica su ruta en la variable de entorno `SUCA_CONFIG`.

JSON no admite comentarios, así que cada clave se documenta aquí. Todos los números son enteros positivos y no se admiten claves desconocidas.

| Clave | Valor inicial | Descripción |
|---|---|---|
| `server.host` | `127.0.0.1` | Dirección del servidor local. Debe ser de loopback: el servidor solo acepta conexiones de la misma computadora |
| `server.port` | `8765` | Puerto del servidor local |
| `server.token` | `suca-local-dev-token` | Token que la extensión envía en el encabezado `X-Api-Token`. **Es solo de desarrollo local**: no protege datos frente a terceros, porque el servidor escucha únicamente en `127.0.0.1`; evita que otras páginas abiertas en el navegador escriban en el servidor por accidente |
| `database.path` | `data/suca.db` | Base de datos SQLite de las sesiones |
| `database.mock_path` | `data/mock.db` | Base de datos de los datos simulados |
| `sending.interval_ms` | `2000` | Cada cuánto la extensión entrega los registros acumulados al servidor |
| `sending.max_batch_records` | `500` | Registros de un mismo tipo a partir de los cuales se entregan sin esperar al intervalo |
| `sending.retry_initial_ms` | `1000` | Espera antes del primer reintento de un lote que no llegó al servidor |
| `sending.retry_max_ms` | `30000` | Espera máxima entre reintentos; la espera se duplica hasta este valor |
| `capture.mousemove_hz` | `50` | Frecuencia máxima de registro del movimiento del cursor |
| `capture.scroll_hz` | `10` | Frecuencia máxima de registro del scroll |
| `capture.click_response_wait_ms` | `1500` | Tiempo que se observa la página tras un clic para saber si respondió |
| `camera.gaze_hz` | `30` | Frecuencia de muestreo de la mirada |
| `camera.face_hz` | `15` | Frecuencia de muestreo de los movimientos faciales |
| `test_page.port` | `8766` | Puerto en el que se sirve la página de prueba de la extensión |
| `test_app.port` | `8767` | Puerto en el que se sirve la app de prueba (`test-app/`) |

Las rutas relativas se resuelven desde la raíz del repositorio. La carpeta `data/` no se versiona.

**Configuración de la extensión.** La extensión no puede leer archivos fuera de su carpeta, así que usa una copia generada, `extension/config.generated.js`. Esa copia solo contiene las secciones `server`, `sending`, `capture` y `camera` (en `UX.config`), y la versión y las enumeraciones de los contratos (en `UX.contracts`). Cada vez que cambies `config/shared.json` o `contracts/enums.json`, regenérala y recarga la extensión:

```bash
python -m scripts.generate_config
```

El archivo generado se versiona y no se edita a mano. Las pruebas fallan si no coincide con lo que generaría el script.

Los umbrales del análisis no están aquí: están en `analysis/parameters.yaml`, con un comentario cada uno.

## Paso a paso

### 1. Preparar la base

El sistema guarda todo en una base SQLite local (por defecto, `data/suca.db`). El esquema completo, comentado tabla por tabla, está en `server/schema.sql`.

```bash
python -m scripts.init_db
```

- Si la base ya existe, no la toca. Si existe con otra versión del esquema, se detiene y explica cómo recrearla.
- Para crear otra base: `python -m scripts.init_db --db data/otra.db`.
- Para borrarla y crearla de nuevo, **con pérdida de todos sus datos**: `python -m scripts.init_db --reset` (pide confirmación) o `--reset --yes`. En Windows, detén antes el servidor: con el servidor en marcha, Windows no deja borrar el archivo.

Para retirar a un participante, borra su fila de `participant`: sus sesiones y todos sus datos y resultados se borran en cascada.

### 2. Cargar un estudio

Un estudio (el sistema evaluado y sus tareas) se define en un archivo YAML y se carga en la base:

```bash
python -m scripts.load_study studies/example.yaml
```

Volver a cargar el mismo archivo actualiza el estudio sin duplicarlo. El formato está descrito en `studies/example.yaml` y en `contracts/study.schema.json`. Para cargarlo en otra base, agrega `--db RUTA`.

### 3. Generar los datos simulados

Para probar el análisis y el panel sin datos de participantes:

```bash
python -m scripts.generate_mock_data
```

Crea `data/mock.db` con el estudio de ejemplo, sus referencias confirmadas, 3 sesiones guiadas (V0, V1 y V2) con problemas sembrados conocidos y 1 sesión libre. Las tablas de resultados quedan llenas con los valores esperados. Junto a la base escribe `data/mock_ground_truth.json`: los incidentes, episodios, resultados por tarea e índice que el análisis debería encontrar.

Con la misma semilla (`--seed`, por defecto 7) el resultado es idéntico en cualquier computadora. Nunca escribe sobre `database.path`. Cómo usar el constructor de sesiones en las pruebas y cómo leer la verdad de referencia: [scripts/simulation/README.md](scripts/simulation/README.md).

### 4. Ejecutar el servidor local

Con la base creada:

```bash
python -m server
```

- Escucha solo en `http://127.0.0.1:8765` y se detiene con Ctrl+C.
- Cada petición debe llevar el encabezado `X-Api-Token` con `server.token`, así que el navegador no sirve para probarlo directamente. Para comprobar que responde, desde otra terminal:

  ```bash
  python -c "import urllib.request as u; r = u.Request('http://127.0.0.1:8765/health', headers={'X-Api-Token': 'suca-local-dev-token'}); print(u.urlopen(r).read().decode())"
  ```

  Debe mostrar `"status":"ok"`, con la versión de los contratos y del esquema.

La documentación interactiva de los endpoints está en `http://127.0.0.1:8765/docs` (pulsa *Authorize* y escribe el token). Los endpoints, sus errores y cómo extender el servidor están en [server/README.md](server/README.md).

### 5. Servir la página de prueba

Los content scripts de la extensión no corren en las páginas de la propia extensión, así que la página de prueba (`extension/test-page/`) se sirve como un sitio normal, en el puerto `test_page.port`:

```bash
python -m scripts.serve_test_page
```

Queda en `http://127.0.0.1:8766/`. Tiene botones, enlaces, un formulario con validación, un menú, una búsqueda, regiones semánticas y una tienda de una sola página.

La **app de prueba** (`test-app/`), la tienda sobre la que se hacen las sesiones con participantes, se sirve igual, en el puerto `test_app.port`:

```bash
python -m scripts.serve_test_app
```

Queda en `http://127.0.0.1:8767/`. La versión (V0, V1 o V2) se elige en `http://127.0.0.1:8767/setup` antes de cada sesión. Cómo prepararla, sus datos de prueba y sus pantallas están en [test-app/README.md](test-app/README.md), y los problemas sembrados de cada versión en [test-app/PROBLEMS.md](test-app/PROBLEMS.md).

### 6. Cargar la extensión en Chrome

La extensión se carga en modo desarrollador, sin publicarla:

1. Abre `chrome://extensions` y activa **Modo de desarrollador** (arriba a la derecha).
2. Pulsa **Cargar descomprimida** y elige la carpeta `extension/` del repositorio.
3. Fija el ícono de SUCA en la barra (ícono de la pieza de rompecabezas → alfiler junto a SUCA). Al pulsarlo se abre el panel lateral.

Después de cambiar el código o la configuración, pulsa el botón de recargar de la extensión en `chrome://extensions` y recarga las pestañas abiertas. Los permisos, los módulos, el panel lateral y cómo viajan los datos están en [extension/README.md](extension/README.md).

### 7. Hacer una sesión

Con el servidor en marcha (paso 4):

1. Abre en Chrome la página que se evaluará (por ejemplo, la página de prueba del paso 5).
2. Con esa pestaña activa, pulsa el ícono de SUCA: se abre el panel lateral.
3. Elige el estudio, escribe el código del participante (por ejemplo, `P01`: nunca un nombre) y la versión (`V0`), elige el modo y pulsa **Iniciar sesión**.
4. El participante usa la página. Al terminar, pulsa **Cerrar sesión** en el panel.

Para comprobar que los clics llegaron a la base:

```bash
python -c "import sqlite3; c = sqlite3.connect('data/suca.db'); print(c.execute('SELECT session_id, type, x, y FROM event ORDER BY t DESC LIMIT 5').fetchall())"
```

### 8. Procesar las sesiones

Con sesiones terminadas en la base, analízalas:

```bash
python -m analysis.run --session 17     # una sesión
python -m analysis.run --study 1        # las sesiones cerradas de un estudio
```

- Guarda episodios, incidentes, resultados por tarea e índice en las tablas de resultados. Volver a ejecutarlo reemplaza los resultados de la sesión.
- Para usar otra base, agrega `--db RUTA`. Con `--db data/mock.db` se analizan los datos simulados, y sus resultados esperados se reemplazan hasta que vuelvas a generarla.
- Los umbrales están en `analysis/parameters.yaml`. El pipeline y cómo agregar un detector están en [analysis/README.md](analysis/README.md).

### 9. Abrir el panel de resultados

```bash
python -m streamlit run dashboard/app.py
```

Se abre en el navegador en `http://127.0.0.1:8501`; se detiene con Ctrl+C.
- En la barra lateral se elige la base (real o simulada) y el estudio.
- Para verlo con datos antes de tener sesiones reales, genera la base simulada (paso 3).
- Solo escucha en esta computadora y no envía estadísticas de uso. Lo configura `.streamlit/config.toml`, que Streamlit lee de la carpeta desde la que se ejecuta: ejecútalo siempre desde la raíz del repositorio.

Las páginas, las funciones de datos y cómo agregar una página están en [dashboard/README.md](dashboard/README.md).

### 10. Ejecutar las pruebas

```bash
python -m ruff check .     # estilo y documentación de Python
python -m ruff format .    # formato de Python (lo aplica; en GitHub se comprueba)
python -m pytest           # pruebas de Python
npm test                   # pruebas de la extensión y de la app de prueba, con node --test
```

Las mismas comprobaciones se ejecutan automáticamente en cada *pull request* y en cada cambio en `main`.

### 11. Verificar la base

```bash
python -m scripts.verify_base
```

Comprueba todo lo que no necesita Chrome y muestra un resumen, una línea por comprobación (`PASS`, `FAIL` o `SKIP`):

| Comprobación | Qué verifica |
|---|---|
| Estilo y pruebas | `ruff check`, `ruff format --check`, `pytest` y `node --test` (se salta si Node no está instalado) |
| Configuración | `config/shared.json` es válido y `extension/config.generated.js` está al día |
| Contratos | Cada ejemplo de `contracts/examples/` cumple o incumple su contrato, según su nombre |
| Base y estudio | Se crea una base y se carga el estudio de ejemplo; cargarlo de nuevo no duplica |
| Servidor | `/health` responde, el token es obligatorio y una sesión con un clic se guarda y se cierra |
| Datos simulados | Se generan igual dos veces y su verdad de referencia cubre todos los tipos de incidente |
| Panel | El acceso a datos lee la base simulada como dice su verdad de referencia |
| Análisis | El pipeline corre sobre cada sesión de la base simulada |

Todo se hace en una carpeta temporal: no toca `data/`. Termina con código 0 si nada falló. Con `--quick` salta el estilo y las pruebas (unos 10 segundos en total). Lo que necesita Chrome (cargar la extensión, el panel lateral, el envío de lotes) se comprueba a mano.

## Uso

El orden de una evaluación:

1. Preparar la base y cargar el estudio (pasos 1 y 2).
2. Iniciar el servidor local (paso 4).
3. Cargar la extensión y hacer las sesiones desde el panel lateral (pasos 6 y 7).
4. Analizar las sesiones terminadas (paso 8).
5. Revisar los resultados en el panel (paso 9).

Para trabajar sin sesiones reales, usa los datos simulados (paso 3).

## Problemas frecuentes

| Problema | Solución |
|---|---|
| `python` no existe (Windows) o es Python 2 (macOS) | Crea el entorno con `py -3.11` (Windows) o `python3` (macOS) y actívalo: dentro del entorno, `python` es el correcto |
| `ModuleNotFoundError: No module named 'shared'` (u otro paquete del proyecto) | Falta `python -m pip install -e .`, o el entorno virtual no está activo |
| `database not found` | Crea la base con `python -m scripts.init_db` (o la simulada con `python -m scripts.generate_mock_data`) |
| La base tiene otra versión del esquema | Recréala con `python -m scripts.init_db --reset` (borra sus datos) |
| El puerto 8765, 8766, 8767 u 8501 está ocupado | Cierra el programa que lo usa, o cambia `server.port`, `test_page.port` o `test_app.port` en `config/shared.json` y regenera la configuración de la extensión |
| La extensión no captura nada | El servidor debe estar en marcha; la sesión se inicia con la pestaña evaluada activa; los content scripts no corren en páginas `chrome://` ni en la Chrome Web Store; recarga la pestaña después de recargar la extensión |
| `--reset` falla en Windows | Detén antes el servidor y el panel, que tienen la base abierta |

## Privacidad

- Nunca se captura el contenido escrito en los campos de formulario.
- Nunca se guarda ni se envía video o imágenes del rostro: solo números.
- El servidor y el panel solo escuchan en `127.0.0.1`: nada sale de la computadora.
- La carpeta `data/` y cualquier dato de participantes nunca se suben al repositorio.

## Contribuir

Las convenciones de código, la propiedad de carpetas y el flujo de trabajo están en [CONTRIBUTING.md](CONTRIBUTING.md).
