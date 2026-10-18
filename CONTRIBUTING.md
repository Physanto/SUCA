# Guía de contribución

Reglas y convenciones para trabajar en este repositorio. Léela completa antes de tu primer cambio.

## Contenido

1. [Idioma](#1-idioma)
2. [Documentación del código](#2-documentación-del-código)
3. [Diseño](#3-diseño)
4. [Contratos](#4-contratos)
5. [Propiedad de carpetas](#5-propiedad-de-carpetas)
6. [Ramas y revisiones](#6-ramas-y-revisiones)
7. [Datos y privacidad](#7-datos-y-privacidad)
8. [Commits](#8-commits)
9. [Seguimiento](#9-seguimiento)
10. [Definición de terminado](#10-definición-de-terminado)

---

## 1. Idioma

**El código se escribe en inglés. La documentación, en español.**

| En inglés | En español |
|---|---|
| Nombres de variables, funciones, clases y módulos | Docstrings y comentarios |
| Nombres de archivos y carpetas | README, CONTRIBUTING y README de cada módulo |
| Tablas y columnas de la base de datos | Descripciones (`description`) en los esquemas JSON |
| Claves JSON, claves de configuración y valores de enumeraciones | Textos que ven el participante y el evaluador |
| Rutas de la API | |
| Nombres de pruebas | |
| Mensajes de log y errores técnicos | |
| Mensajes de commit | |

- **Archivos:** Python en `snake_case`; JavaScript, HTML y CSS en `kebab-case`.
- **Datos de contratos:** todo lo definido en `contracts/` usa `snake_case` en todos los lenguajes, también en JavaScript. El resto del código JavaScript usa `camelCase`.
- **Textos de la extensión para el participante:** centralizados en `extension/panel/strings.js`, no repartidos por el código.

### Nombres de los conceptos en el código

| Concepto | Nombre en el código |
|---|---|
| Estudio, tarea, participante | `study`, `task`, `participant` |
| Sesión | `session` |
| Modo libre / guiado / referencia | `free` / `guided` / `reference` |
| Lote | `batch` |
| Evento | `event` |
| Muestra de mirada / facial | `gaze` / `face` |
| Calibración | `calibration` |
| Referencia | `reference` |
| Condición final | `end_condition` |
| Pasos obligatorios | `required_steps` |
| Fin de tarea: por referencia / terminé / no pude | `ended_by`: `reference` / `done` / `gave_up` |
| Episodio | `episode` |
| Incidente | `incident` |
| Resultado de tarea | `task_result` |
| Punto de desvío | `deviation_step` |
| Índice de usabilidad conductual (IUC) | `bui` (*behavioral usability index*), tabla `usability_index` |
| Efectividad, eficiencia temporal, eficiencia de ruta, fricción | `effectiveness`, `time_efficiency`, `path_efficiency`, `friction` |
| Captura de pantalla | `screen_capture` |
| Zona de mirada | `zone` |
| Panel lateral de la extensión | `extension/panel/` |
| Panel de resultados | `dashboard/` |
| Datos simulados | `mock data` |
| Parámetros del análisis | `parameters` |

---

## 2. Documentación del código

Todo archivo, clase y función pública lleva documentación en español. Los comentarios dentro del código explican **por qué**, no **qué**: el qué ya lo dice el código.

### 2.1 Python: docstrings estilo Google

Las etiquetas de sección (`Args`, `Returns`, `Raises`, `Attributes`) quedan en inglés porque así las reconocen las herramientas de documentación; el contenido va en español. `ruff` comprueba los docstrings con la convención Google.

```python
"""Detectores de fricción sobre los eventos de una sesión.

Cada detector es una estrategia registrada; la función ``detect`` los
ejecuta todos y combina sus incidentes.
"""

from analysis.registry import Registry


class RageClickDetector:
    """Detecta varios clics rápidos en un área pequeña.

    Attributes:
        incident_type: Tipo de incidente según ``contracts/enums.json``.
    """

    incident_type = "rage_click"

    def find(self, data: SessionData, params: Parameters) -> pd.DataFrame:
        """Busca ráfagas de clics que superen los umbrales configurados.

        Args:
            data: Datos de la sesión, ya limpios y con pantallas asignadas.
            params: Umbrales cargados desde ``parameters.yaml``.

        Returns:
            DataFrame con un incidente por fila. Vacío si no hay ninguno.
        """
        # Se agrupa por pantalla porque un cambio de pantalla corta la ráfaga.
        ...


def detect(data: SessionData, params: Parameters) -> pd.DataFrame:
    """Ejecuta todos los detectores registrados y combina sus resultados.

    Args:
        data: Datos de la sesión, ya limpios y con pantallas asignadas.
        params: Umbrales cargados desde ``parameters.yaml``.

    Returns:
        DataFrame con las columnas de la tabla ``incident``.

    Raises:
        ColumnValidationError: Si un detector devuelve columnas incorrectas.
    """
```

Los *type hints* son obligatorios en Python.

### 2.2 JavaScript: JSDoc

```javascript
/**
 * @file Acumula registros y los entrega al service worker por lotes.
 */

/**
 * Agrega un registro al lote de su tipo. El lote se envía al cumplirse
 * el intervalo configurado o al alcanzar el máximo de registros.
 *
 * @param {string} type - Tipo de lote según `contracts/enums.json`.
 * @param {object} record - Registro que cumple el esquema de su tipo.
 * @returns {void}
 */
function add(type, record) {
  // Se copia el registro para que cambios posteriores no alteren el lote.
  ...
}
```

### 2.3 Otros formatos

| Formato | Cómo se documenta |
|---|---|
| SQL | Comentario `--` antes de cada tabla y en las columnas no evidentes |
| YAML | Comentarios `#` en cada sección y en cada umbral |
| JSON Schema | Campo `description` en español en el esquema y en cada propiedad |
| JSON de configuración | No admite comentarios: se documenta en el README |
| HTML y CSS | Comentarios `<!-- -->` y `/* */` en las secciones no evidentes |
| Pruebas | Nombre en inglés que describe el comportamiento; docstring en español si el caso no es obvio |

### 2.4 README de cada módulo

Cada módulo tiene un `README.md` en su carpeta que explica qué hace, cómo probarlo y cómo extenderlo. La documentación del repositorio es autosuficiente: no remite a documentos externos.

---

## 3. Diseño

**Principio:** la arquitectura más simple que cubra el sistema. SOLID y los patrones se aplican donde resuelven un problema concreto, no por costumbre.

### 3.1 SOLID en este proyecto

| Principio | Cómo se aplica aquí |
|---|---|
| **S** · Responsabilidad única | Cada archivo o clase hace una cosa. Transporte (HTTP, mensajes de Chrome), lógica y persistencia van separados. Por ejemplo, en el servidor `routes.py` solo traduce HTTP, `services.py` coordina y `repositories.py` persiste. |
| **O** · Abierto/cerrado | Donde se prevé crecimiento (tipos de lote, detectores, episodios, módulos de la extensión, páginas del panel), se agrega una pieza registrándola, sin modificar el código que las orquesta. |
| **L** · Sustitución | Cualquier implementación de una interfaz reemplaza a otra sin romper a quien la usa; por ejemplo, un repositorio de prueba en lugar del de SQLite. |
| **I** · Segregación de interfaces | Interfaces pequeñas por consumidor. Servidor, análisis y panel no comparten un repositorio gigante. |
| **D** · Inversión de dependencias | La lógica depende de abstracciones (`typing.Protocol` en Python; objetos inyectados en JavaScript). Las dependencias concretas se crean en un solo punto de composición: la fábrica de la app del servidor, el orquestador del análisis y el arranque de la extensión. |

### 3.2 Patrones del proyecto

Son los únicos previstos. Si un cambio parece necesitar otro, se discute antes en un *issue*.

| Patrón | Dónde | Problema que resuelve |
|---|---|---|
| Repository | `server/repositories.py`, `analysis/loader.py`, `dashboard/data.py` | Aislar el SQL de la lógica; permitir sustitutos en pruebas |
| Strategy + Registry | Manejadores de lotes, detectores, detectores de episodio, módulos de la extensión | Agregar variantes sin modificar al orquestador |
| Pipeline | `analysis/run.py` | Etapas encadenadas, validadas y recalculables |
| Facade | `shared/contracts.py`, `UX.batcher`, funciones públicas de cada etapa del análisis | Ocultar librerías y mecanismos internos detrás de una entrada simple |
| Adapter | `extension/common/platform.js`, `GazeProvider`, `FaceProvider` | Aislar las APIs de Chrome y las librerías externas |
| Observer / Pub-Sub | `UX.messages`, suscripción a `UX.session` | Comunicar partes de la extensión sin que se conozcan |
| Mediator | `extension/worker.js` | Enrutar mensajes entre el panel lateral y los content scripts |
| Application Factory | `server/app.py` (`create_app`) | Crear la app con otra configuración en pruebas |
| Builder | `scripts/simulation/builder.py` | Construir sesiones simuladas legibles para pruebas |
| Value Object | Configuración y parámetros | Valores inmutables y validados al cargar |

### 3.3 Reglas contra la complejidad

- No crear una abstracción sin un uso real ahora o uno previsto explícitamente.
- Si no hay variación, una función simple es mejor que una clase.
- Nada de: ORM, contenedores de inyección de dependencias, microservicios, colas de mensajes, frameworks de interfaz en la extensión, empaquetadores ni jerarquías de herencia profundas.
- Fallar rápido: validar en los bordes (lotes que llegan, configuración, columnas entre etapas del análisis) con errores claros.

---

## 4. Contratos

- `contracts/` es la única fuente de formatos de datos y valores de enumeraciones.
- Ningún valor de enumeración se escribe a mano en el código si puede leerse del contrato.
- Toda validación de contratos en Python pasa por `shared/contracts.py`.

---

## 5. Propiedad de carpetas

Cada integrante modifica solo sus carpetas. `.github/CODEOWNERS` hace que GitHub pida la aprobación del dueño en cada cambio.

| Ruta | Dueño |
|---|---|
| `contracts/`, `config/`, `shared/`, `server/`, `scripts/`, `studies/`, `.github/` | Líder |
| `extension/manifest.json`, `extension/common/`, `extension/worker.js`, `extension/content/bootstrap.js`, `extension/test-page/` | Líder |
| `analysis/run.py`, `analysis/loader.py`, `analysis/columns.py`, `analysis/registry.py`, `analysis/parameters.py`, `analysis/parameters.yaml` | Líder |
| `extension/content/camera.js`, `extension/content/calibration.js`, `extension/lib/` | Líder (cámara) |
| `extension/content/capture.js` | Integrante B (captura) |
| `extension/panel/`, `extension/content/task-end.js` | Integrante B (sesión y modos) |
| `test-app/` | Integrante B (app de prueba) |
| `analysis/cleaning.py`, `analysis/screens.py`, `analysis/episodes.py`, `analysis/detectors.py` | Integrante C (fricción) |
| `analysis/reference.py`, `analysis/usability_index.py` | Integrante C (referencia e índice) |
| `dashboard/` | Integrante C (panel) |
| `analysis/ml/`, `notebooks/` | Integrante C (aprendizaje automático) |
| `tests/` | El dueño del código que se prueba |

Los archivos de la raíz (`README.md`, `CONTRIBUTING.md`, `pyproject.toml`, `requirements*.txt`, `package.json`, `.gitignore`) también son del líder.

### 5.1 Cambios en archivos compartidos

Los archivos del líder conectan los módulos: contratos, configuración, servidor, manifiesto, utilidades comunes de la extensión, orquestador del análisis y parámetros. **Nadie más los modifica directamente.**

Si necesitas un cambio (un campo nuevo, un permiso nuevo en el manifiesto, un parámetro nuevo):

1. Abre un *issue* con la etiqueta `contract` que explique qué necesitas y por qué.
2. El líder hace el cambio, actualiza los datos simulados y avisa a los afectados.

- **Cambios compatibles** (agregar un campo opcional, un tipo de incidente nuevo): se aprueban sin más.
- **Cambios que rompen** (renombrar o quitar un campo, cambiar un tipo): requieren acuerdo de los afectados.

---

## 6. Ramas y revisiones

- `main` está protegida: nadie hace *push* directo.
- Una rama por tarea, con el prefijo del módulo: `m1/element-descriptor`, `m4/rage-click`.
- Ramas cortas: una funcionalidad por rama.
- Todo entra a `main` por *pull request*, con las pruebas automáticas en verde y la aprobación del dueño de los archivos tocados.

---

## 7. Datos y privacidad

- La carpeta `data/` **nunca** se sube.
- Mientras los módulos no estén integrados, se trabaja con los **datos simulados** que genera el repositorio.
- **Nunca** se suben datos de participantes, ni siquiera de prueba entre compañeros.
- **Nunca** se captura el contenido escrito en campos de formulario: solo que hubo un cambio y en qué campo.
- **Nunca** se guarda ni se envía video o imágenes del rostro: solo números.

---

## 8. Commits

Mensajes **en inglés** con [Conventional Commits](https://www.conventionalcommits.org/):

```
<tipo>(<ámbito opcional>): <descripción en imperativo>
```

| Tipo | Uso |
|---|---|
| `feat` | Funcionalidad nueva |
| `fix` | Corrección de un error |
| `test` | Pruebas nuevas o corregidas |
| `docs` | Solo documentación |
| `refactor` | Cambio interno sin cambiar el comportamiento |
| `chore` | Mantenimiento: dependencias, configuración, estructura |
| `ci` | Integración continua |

Ejemplos:

```
feat(server): add batch ingestion
fix(capture): ignore password fields
test(analysis): cover rage click detector
```

- Commits pequeños, uno por cambio lógico.
- `ruff` y todas las pruebas en verde antes de cada commit.
- Los mensajes describen el cambio; no incluyen firmas ni atribuciones automáticas de herramientas.

### Antes de cada commit

- [ ] `ruff check .`, `pytest` y `npm test` pasan.
- [ ] Todo archivo, clase y función pública nuevos tienen documentación en español.
- [ ] Nombres en inglés; textos para el usuario en español.
- [ ] Ningún archivo ajeno modificado.
- [ ] Ningún dato real ni carpeta `data/`.
- [ ] El mensaje del commit está en inglés.

Antes de abrir un *pull request*, `python -m scripts.verify_base` comprueba además la base, el servidor, los datos simulados, el análisis y el panel.

---

## 9. Seguimiento

- Cada tarea es un *issue* en GitHub, con la etiqueta de su módulo (`M1`, `M2`…) y un responsable.
- El tablero del proyecto tiene las columnas Pendiente, En curso, En revisión y Terminado.

---

## 10. Definición de terminado

Una tarea está terminada cuando:

- su código está en `main` mediante un *pull request* aprobado;
- tiene pruebas y pasan;
- respeta los contratos;
- todo archivo, clase y función pública está documentado en español;
- el README del módulo explica cómo usarlo, probarlo y extenderlo.
