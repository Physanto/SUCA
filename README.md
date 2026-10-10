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
