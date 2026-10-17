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

Las cuatro piezas se conectan mediante los **contratos** de `contracts/` (formatos de datos y valores permitidos) y comparten la configuración de `config/` y las utilidades de Python de `shared/`. La carpeta `test-app/` contiene una aplicación de prueba sobre la que se usa la extensión; no forma parte del sistema.

## Estructura del repositorio

```
├── config/          configuración única del sistema
├── contracts/       formatos de datos, enumeraciones y mensajes
├── shared/          utilidades de Python compartidas
├── extension/       extensión de Chrome
├── server/          servidor local
├── analysis/        análisis de sesiones
├── dashboard/       panel de resultados
├── scripts/         scripts de preparación y datos simulados
├── studies/         definición de estudios y tareas (YAML)
├── test-app/        aplicación de prueba
├── notebooks/       análisis estadístico
├── tests/           pruebas de Python
└── data/            datos locales (no se versiona)
```

## Requisitos

- Python 3.11 o superior.
- Node.js 22 o superior (solo para ejecutar las pruebas de la extensión).
- Google Chrome.
- Git.

## Instalación

1. Clona el repositorio y entra en su carpeta.

2. Crea y activa un entorno virtual:

   ```bash
   python -m venv .venv
   source .venv/bin/activate        # Linux y macOS
   .venv\Scripts\activate           # Windows
   ```

3. Instala las dependencias de desarrollo (incluyen las de ejecución):

   ```bash
   pip install -r requirements-dev.txt
   ```

4. Instala el repositorio en modo editable, para que `shared`, `server`, `analysis`, `dashboard` y `scripts` se puedan importar desde cualquier lugar:

   ```bash
   pip install -e .
   ```

La extensión no tiene dependencias de Node: no hace falta `npm install`.

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

Las rutas relativas se resuelven desde la raíz del repositorio. La carpeta `data/` no se versiona.

### Configuración de la extensión

La extensión no puede leer archivos fuera de su carpeta, así que usa una copia generada, `extension/config.generated.js`. Esa copia solo contiene lo que la extensión necesita: las secciones `server`, `sending`, `capture` y `camera` (en `UX.config`), y la versión y las enumeraciones de los contratos (en `UX.contracts`). Cada vez que cambies `config/shared.json` o `contracts/enums.json`, regenérala:

```bash
python -m scripts.generate_config
```

El archivo generado se versiona y no se edita a mano. Las pruebas fallan si no coincide con lo que generaría el script.

## Base de datos

El sistema guarda todo en una base SQLite local (por defecto `data/suca.db`). El esquema completo, comentado tabla por tabla, está en `server/schema.sql`.

1. Crea la base:

   ```bash
   python -m scripts.init_db
   ```

   Si la base ya existe, no la toca. Si existe con otra versión del esquema, se detiene y explica cómo recrearla. Para crear otra base, usa `--db`:

   ```bash
   python -m scripts.init_db --db data/otra.db
   ```

2. Carga el estudio de ejemplo (o el tuyo):

   ```bash
   python -m scripts.load_study studies/example.yaml
   ```

   Volver a cargar el mismo archivo actualiza el estudio sin duplicarlo. El formato de los estudios está descrito en `studies/example.yaml` y en `contracts/study.schema.json`.

Para borrar la base y crearla de nuevo, **con pérdida de todos sus datos**:

```bash
python -m scripts.init_db --reset          # pide confirmación
python -m scripts.init_db --reset --yes    # sin confirmación
```

Para retirar a un participante, borra su fila de `participant`: sus sesiones y todos sus datos y resultados se borran en cascada.

## Servidor local

Con la base creada, inicia el servidor:

```bash
python -m server
```

Escucha solo en `http://127.0.0.1:8765` (`server.host` y `server.port`). Cada petición debe llevar el encabezado `X-Api-Token` con `server.token`:

```bash
curl -H "X-Api-Token: suca-local-dev-token" http://127.0.0.1:8765/health
```

Los endpoints, sus errores y cómo extender el servidor están en [server/README.md](server/README.md).

## Extensión de Chrome

La extensión se carga en modo desarrollador, sin publicarla:

1. Abre `chrome://extensions` y activa **Modo de desarrollador** (arriba a la derecha).
2. Pulsa **Cargar descomprimida** y elige la carpeta `extension/` del repositorio.
3. Fija el ícono de SUCA en la barra; al pulsarlo se abre el panel lateral.

Si cambias `config/shared.json` o `contracts/enums.json`, regenera la configuración de la extensión (`python -m scripts.generate_config`) y recárgala desde `chrome://extensions`. Después de recargarla, recarga también las pestañas abiertas.

Requiere Chrome 116 o superior y el servidor local en marcha. Los permisos, las utilidades comunes y cómo viajan los datos están en [extension/README.md](extension/README.md).

## Pruebas

Con el entorno virtual activado, desde la raíz del repositorio:

```bash
ruff check .     # estilo y documentación de Python
pytest           # pruebas de Python
npm test         # pruebas de la extensión con node --test
```

Las mismas comprobaciones se ejecutan automáticamente en cada *pull request* y en cada cambio en `main`.

## Uso

Las instrucciones para iniciar el servidor, cargar la extensión, ejecutar el análisis y abrir el panel se agregarán a medida que cada pieza esté disponible.

## Privacidad

- Nunca se captura el contenido escrito en los campos de formulario.
- Nunca se guarda ni se envía video o imágenes del rostro: solo números.
- La carpeta `data/` y cualquier dato de participantes nunca se suben al repositorio.

## Contribuir

Las convenciones de código, la propiedad de carpetas y el flujo de trabajo están en [CONTRIBUTING.md](CONTRIBUTING.md).
