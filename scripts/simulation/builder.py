"""Constructor de sesiones simuladas (Builder).

Arma, paso a paso, lo que la extensión capturaría en una sesión: eventos,
mirada, rostro, tareas, calibraciones y SUS, todos con la forma de los
contratos. Al mismo tiempo anota la **verdad de referencia**: los incidentes,
episodios y resultados por tarea que el análisis debería encontrar.

La sesión es una línea de tiempo. Cada método agrega algo al final y devuelve
el mismo constructor, así se encadenan::

    session = (
        SessionBuilder(study_id=1, mode="guided", seed=3)
        .on_screen(HOME)
        .with_task(task_id, path)       # empieza una tarea con su ruta esperada
        .follow(1)                      # hace la primera acción de la ruta
        .with_rage_click()              # la siguiente acción, con una ráfaga de clics
        .with_dead_click(fake_button)   # un clic sin respuesta
        .end_task("reference")          # termina la ruta y la tarea
        .build()
    )

Los patrones leen los umbrales de ``analysis/parameters.yaml``: por defecto los
superan, y la verdad los incluye. Con valores por debajo del umbral (por
ejemplo, ``with_rage_click(clicks=2)``), el patrón ocurre pero la verdad no lo
cuenta como incidente: sirve para casos negativos. El comportamiento normal
(tiempo entre acciones, respuesta de la página) nunca cruza ningún umbral.

Convenciones de la verdad de referencia:

- **Pantalla:** ruta normalizada, sin dominio ni parámetros, con ``{id}`` en
  lugar de los identificadores (``/order/{id}/confirmation``).
- **Incidente:** ``t_start`` y ``t_end`` delimitan el patrón (por ejemplo, del
  primer al último clic de la ráfaga). Un detector acierta si informa un
  incidente del mismo tipo con ``t`` dentro de ese intervalo.
- **Pasos:** clics en elementos interactivos, envíos de formulario y cambios de
  pantalla, como en las referencias.
- **Desvío:** un paso está en la ruta si es el siguiente esperado o repite uno
  ya hecho (otro clic en el mismo botón, reenviar el formulario). El primer
  paso que no cumple esto es el desvío; ``deviation_step`` es la posición
  (desde 0) del paso esperado en ese momento. ``off_path_ms`` suma el tiempo
  fuera de la ruta.
"""

import dataclasses
import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from analysis.parameters import Parameters, load_parameters
from scripts.simulation.camera import SESSION_POSE, SimulatedEyes, face_values
from shared.config import load_config

DEFAULT_START = 1_791_208_800_000.0
"""Inicio por defecto: 5 de octubre de 2026, 14:00 UTC, en ms desde 1970."""

DEFAULT_SCREEN_INFO: Mapping[str, Any] = {
    "window_width": 1280,
    "window_height": 800,
    "screen_width": 1920,
    "screen_height": 1080,
    "device_pixel_ratio": 1,
    "chrome_version": "146.0.7680.153",
}
"""Pantalla de las sesiones simuladas."""

EYE_LEAD_MS = 300.0
"""Cuánto se adelanta la mirada al cursor en las sesiones con ojos simulados."""

#: Tipos de episodio que produce un formulario.
FORM_KINDS = ("form", "search", "login")


class BuilderError(ValueError):
    """La sesión pedida no se puede construir (orden de llamadas o umbrales)."""


@dataclass(frozen=True)
class Screen:
    """Una pantalla de la aplicación simulada.

    Attributes:
        url: URL completa, como la captura la extensión.
        title: Título de la página.
        pattern: Pantalla normalizada que debería obtener el análisis.
    """

    url: str
    title: str
    pattern: str

    def record(self) -> dict[str, str]:
        """Devuelve la pantalla con la forma de ``screen`` del contrato."""
        return {"url": self.url, "title": self.title}


@dataclass(frozen=True)
class Element:
    """Un elemento de la página, con los datos de su descriptor.

    Attributes:
        tag: Etiqueta HTML.
        id: Atributo id, o ``None``.
        role: Rol ARIA, o ``None``.
        text: Texto visible (``None`` en los campos de formulario).
        selector: Selector CSS.
        box: Rectángulo ``(x, y, w, h)`` en la ventana, en píxeles CSS.
        interactive: Si es interactivo; un clic en uno no interactivo no es un paso.
    """

    tag: str
    id: str | None
    role: str | None
    text: str | None
    selector: str
    box: tuple[float, float, float, float]
    interactive: bool = True

    def descriptor(self) -> dict[str, Any]:
        """Devuelve el descriptor con la forma de ``contracts/element.schema.json``."""
        x, y, w, h = self.box
        return {
            "tag": self.tag,
            "id": self.id,
            "role": self.role,
            "text": self.text,
            "selector": self.selector,
            "box": {"x": x, "y": y, "w": w, "h": h},
            "interactive": self.interactive,
        }

    @property
    def is_text_field(self) -> bool:
        """Indica si al hacer clic recibe el foco para escribir."""
        return self.tag == "textarea" or (
            self.tag == "input" and self.role not in ("checkbox", "radio", "button")
        )


@dataclass(frozen=True)
class Click:
    """Acción de ruta: un clic en un elemento.

    Attributes:
        element: Elemento del clic.
        to: Pantalla a la que lleva, o ``None`` si la página responde sin navegar.
        required: Si el clic es un paso obligatorio de la tarea.
    """

    element: Element
    to: Screen | None = None
    required: bool = False


@dataclass(frozen=True)
class FillForm:
    """Acción de ruta: llenar los campos de un formulario y enviarlo.

    Attributes:
        form: El formulario (elemento del envío).
        fields: Campos que se llenan, en orden.
        submit: Botón de envío.
        to: Pantalla a la que lleva el envío, o ``None`` si responde sin navegar.
        kind: Episodio que forma: ``form``, ``search`` o ``login``.
        required: Si el envío es un paso obligatorio de la tarea.
    """

    form: Element
    fields: tuple[Element, ...]
    submit: Element
    to: Screen | None = None
    kind: str = "form"
    required: bool = False


@dataclass(frozen=True)
class Scroll:
    """Acción de ruta: desplazar la página (no es un paso).

    Attributes:
        to_y: Desplazamiento vertical final, en píxeles CSS.
    """

    to_y: float


@dataclass(frozen=True)
class SelectText:
    """Acción de ruta: seleccionar texto (no es un paso).

    Attributes:
        length: Caracteres seleccionados.
    """

    length: int


Action = Click | FillForm | Scroll | SelectText
"""Una acción de la ruta de una tarea."""


@dataclass(frozen=True)
class ExpectedIncident:
    """Incidente que el análisis debería detectar.

    Attributes:
        type: Tipo (``incident_type``).
        t_start: Inicio del patrón.
        t_end: Fin del patrón.
        screen: Pantalla normalizada.
        task_id: Tarea activa, o ``None``.
        element: Descriptor del elemento, o ``None``.
        problem: Número del problema sembrado que lo produce, o ``None``.
    """

    type: str
    t_start: float
    t_end: float
    screen: str
    task_id: int | None
    element: Mapping[str, Any] | None = None
    problem: int | None = None

    @property
    def t(self) -> float:
        """Ubica retornos y repeticiones al confirmarse; los demás, al inicio del patrón."""
        return self.t_end if self.type in ("navigation_loop", "repeated_search") else self.t_start


@dataclass(frozen=True)
class ExpectedEpisode:
    """Episodio que el análisis debería reconocer.

    Attributes:
        type: Tipo (``episode_type``).
        t_start: Inicio.
        t_end: Fin.
        screen: Pantalla normalizada donde ocurre.
        outcome: Resultado (``submitted``, ``abandoned``, ``result_opened``…), o ``None``.
        metrics: Métricas propias del tipo.
    """

    type: str
    t_start: float
    t_end: float
    screen: str
    outcome: str | None
    metrics: Mapping[str, Any]


@dataclass(frozen=True)
class ExpectedTask:
    """Resultado esperado de una tarea del modo guiado.

    Attributes:
        task_id: Tarea.
        ended_by: Cómo terminó (``ended_by``).
        success: Si llegó al final de la ruta, con los pasos obligatorios.
        duration_ms: Duración.
        steps: Pasos del participante en la tarea.
        path_steps: Pasos de la ruta de la referencia.
        deviation_step: Posición del paso esperado al desviarse, o ``None``.
        off_path_ms: Tiempo fuera de la ruta.
    """

    task_id: int
    ended_by: str
    success: bool
    duration_ms: float
    steps: int
    path_steps: int
    deviation_step: int | None
    off_path_ms: float


@dataclass(frozen=True)
class ExpectedIndex:
    """Índice de usabilidad esperado, calculado con las fórmulas del índice.

    Attributes:
        effectiveness: Tareas completadas sobre asignadas (0 a 100).
        time_efficiency: Promedio de ``min(1, t_ref / t)`` en las completadas.
        path_efficiency: Promedio de ``min(1, pasos_ref / pasos)`` en las completadas.
        friction: ``100 · (1 − min(1, i / i_max))``, con ``i`` incidentes por minuto de tarea.
        bui: Promedio de los cuatro.
    """

    effectiveness: float
    time_efficiency: float
    path_efficiency: float
    friction: float
    bui: float


@dataclass(frozen=True)
class SessionTruth:
    """Todo lo que el análisis debería encontrar en una sesión.

    Attributes:
        incidents: Incidentes, en orden de tiempo.
        episodes: Episodios, en orden de tiempo.
        tasks: Resultados por tarea.
        usability_index: Índice esperado, o ``None`` si no corresponde.
    """

    incidents: tuple[ExpectedIncident, ...]
    episodes: tuple[ExpectedEpisode, ...]
    tasks: tuple[ExpectedTask, ...]
    usability_index: ExpectedIndex | None


@dataclass(frozen=True)
class ReferenceRecording:
    """Lo grabado para una tarea en una sesión de modo ``reference``.

    Attributes:
        task_id: Tarea grabada.
        steps: Pasos con la forma de ``step`` de ``reference.schema.json``.
        required_steps: Posiciones de los pasos obligatorios.
        duration_ms: Duración de la grabación.
    """

    task_id: int
    steps: tuple[Mapping[str, Any], ...]
    required_steps: tuple[int, ...]
    duration_ms: float


@dataclass(frozen=True)
class SimulatedSession:
    """Una sesión simulada lista para guardar.

    Attributes:
        request: Cuerpo de ``POST /sessions`` (``requests/new-session``).
        started_at: Inicio de la sesión.
        ended_at: Cierre de la sesión.
        batches: Registros por tipo de lote, en orden de tiempo.
        sus_answers: Respuestas del SUS, o ``None``.
        truth: Verdad de referencia.
        references: Tareas grabadas, en sesiones de modo ``reference``.
    """

    request: Mapping[str, Any]
    started_at: float
    ended_at: float
    batches: Mapping[str, tuple[Mapping[str, Any], ...]]
    sus_answers: tuple[int, ...] | None
    truth: SessionTruth
    references: tuple[ReferenceRecording, ...] = ()


@dataclass
class _Task:
    """Estado de la tarea en curso."""

    task_id: int
    path: tuple[Action, ...]
    t_start: float
    next_action: int = 0
    path_steps_done: int = 0
    steps: int = 0
    deviation_step: int | None = None
    off_since: float | None = None
    off_path_ms: float = 0.0
    required: list[int] = field(default_factory=list)
    recorded: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class _FormError:
    """Error de validación pendiente para el próximo formulario."""

    field_index: int
    times: int
    erases: bool
    pause: bool
    error_type: str
    problem: int | None


@dataclass
class _SilentFailure:
    """Fallo silencioso pendiente para el próximo formulario."""

    field_index: int
    times: int
    erases: bool
    problem: int | None


class SessionBuilder:
    """Construye una sesión simulada con interfaz fluida.

    Args:
        study_id: Estudio de la sesión.
        participant_id: Código del participante.
        version: Versión del sistema evaluado.
        mode: Modo de la sesión (``free``, ``guided`` o ``reference``).
        start: Inicio, en ms desde 1970.
        seed: Semilla: la misma semilla produce exactamente la misma sesión.
        params: Parámetros del análisis; por defecto, ``parameters.yaml``.
        reference_durations: Duración de la referencia de cada tarea; habilita
            la verdad de ``task_overtime`` y del índice.
        friction_i_max: Normalización de la fricción del índice; por defecto,
            ``params.friction_i_max``. Sin valor, no se calcula el índice.
        gaze_hz: Frecuencia de la mirada; por defecto, la de la configuración.
        face_hz: Frecuencia del rostro; por defecto, la de la configuración.
        camera: Si genera mirada y rostro; por defecto, salvo en modo ``reference``.
        eyes: Si además simula los ojos con un modelo geométrico conocido: las
            características de cada cuadro (``gaze_features``), la calibración
            completa con sus objetivos y la línea base de rostro relajado
            (``gaze_target``), la disposición de cada pantalla (``layout``) y
            todos los valores faciales. Con ellos corren el reprocesamiento de
            la mirada, la atribución a elementos y el análisis facial. Las
            calibraciones ocupan su tiempo real (más de un minuto la inicial).
    """

    def __init__(
        self,
        *,
        study_id: int,
        participant_id: str = "SIM01",
        version: str = "V0",
        mode: str = "free",
        start: float = DEFAULT_START,
        seed: int = 0,
        params: Parameters | None = None,
        reference_durations: Mapping[int, float] | None = None,
        friction_i_max: float | None = None,
        gaze_hz: float | None = None,
        face_hz: float | None = None,
        camera: bool | None = None,
        eyes: bool = False,
    ) -> None:
        """Prepara una sesión vacía."""
        config = load_config()
        self._params = params or load_parameters()
        self._mousemove_ms = 1000 / config.capture.mousemove_hz
        self._scroll_ms = 1000 / config.capture.scroll_hz
        self._gaze_hz = gaze_hz or config.camera.gaze_hz
        self._face_hz = face_hz or config.camera.face_hz
        self._camera = mode != "reference" if camera is None else camera
        if eyes and not self._camera:
            raise BuilderError("eyes=True needs the camera")
        viewport = (DEFAULT_SCREEN_INFO["window_width"], DEFAULT_SCREEN_INFO["window_height"])
        # Azar propio de los ojos: no altera los tiempos ni los eventos de la sesión.
        self._eyes = SimulatedEyes(seed, viewport) if eyes else None
        self._eye_frames: list[dict[str, Any]] = []
        self._gaze_targets: list[dict[str, Any]] = []
        self._gaze_paused: list[tuple[float, float]] = []
        self._relaxed: list[tuple[float, float]] = []
        self._request = {
            "study_id": study_id,
            "participant_id": participant_id,
            "version": version,
            "mode": mode,
            "screen_info": dict(DEFAULT_SCREEN_INFO),
        }
        self._mode = mode
        self._rng = random.Random(seed)
        self._started_at = float(start)
        self._t = float(start)
        self._reference_durations = dict(reference_durations or {})
        self._i_max = friction_i_max if friction_i_max is not None else self._params.friction_i_max

        self._events: list[dict[str, Any]] = []
        self._task_records: list[dict[str, Any]] = []
        self._calibrations: list[dict[str, Any]] = []
        self._sus: tuple[int, ...] | None = None
        self._incidents: list[ExpectedIncident] = []
        self._episodes: list[ExpectedEpisode] = []
        self._tasks: list[ExpectedTask] = []
        self._references: list[ReferenceRecording] = []

        self._screen: Screen | None = None
        self._visit_start = 0.0
        self._cursor = (DEFAULT_SCREEN_INFO["window_width"] / 2, 400.0)
        self._focused: Element | None = None
        self._task: _Task | None = None
        self._search: dict[str, Any] | None = None
        self._pending_rage: tuple[int | None, int | None] | None = None
        self._pending_hesitation: tuple[float | None, int | None] | None = None
        self._pending_form_error: _FormError | None = None
        self._pending_silent_failure: _SilentFailure | None = None
        self._open_pause: dict[str, Any] | None = None
        self._skip_think = False
        self._scroll_y = 0.0
        self._screen_log: list[tuple[float, str]] = []
        self._last_click = self._t
        self._submit_time = self._t
        self._screen_change_time = self._t

        self._think_range = self._normal_think_range()

    # --- Navegación y tareas -------------------------------------------------

    def on_screen(self, screen: Screen) -> "SessionBuilder":
        """Abre una pantalla directamente (por ejemplo, al empezar la sesión).

        Args:
            screen: Pantalla.

        Returns:
            El constructor.

        Raises:
            BuilderError: Si hay una tarea en curso: dentro de una tarea se
                navega con acciones de la ruta.
        """
        if self._task is not None:
            raise BuilderError("on_screen() cannot be used during a task; use a Click with 'to'")
        self._close_search()
        self._advance(300)
        self._change_screen(screen, role=None)
        return self

    def do(self, *actions: Action) -> "SessionBuilder":
        """Hace acciones fuera de la ruta de una tarea (modo libre, inicio de sesión).

        Args:
            *actions: Acciones, en orden.

        Returns:
            El constructor.
        """
        for action in actions:
            self._run(action, role="off" if self._task else None)
        return self

    def redo(self, *actions: Action) -> "SessionBuilder":
        """Repite acciones ya hechas de la ruta (volver a abrir un menú): no son desvío.

        Args:
            *actions: Acciones de la ruta que ya se hicieron.

        Returns:
            El constructor.
        """
        self._require_task("redo")
        for action in actions:
            self._run(action, role="repeat")
        return self

    def with_task(self, task_id: int, path: Sequence[Action]) -> "SessionBuilder":
        """Empieza una tarea del modo guiado con su ruta esperada.

        La ruta no se recorre todavía: se recorre con ``follow``, con los
        patrones que consumen la siguiente acción y con ``end_task``.

        Args:
            task_id: Tarea.
            path: Acciones de la ruta de la referencia.

        Returns:
            El constructor.

        Raises:
            BuilderError: Si ya hay una tarea en curso.
        """
        if self._task is not None:
            raise BuilderError(f"task {self._task.task_id} is still open; call end_task() first")
        self._close_search()
        self._advance(300)
        self._task = _Task(task_id=task_id, path=tuple(path), t_start=self._t)
        return self

    def follow(self, actions: int | None = None) -> "SessionBuilder":
        """Hace las siguientes acciones de la ruta.

        Args:
            actions: Cuántas; por defecto, todas las que faltan.

        Returns:
            El constructor.
        """
        task = self._require_task("follow")
        remaining = len(task.path) - task.next_action
        count = remaining if actions is None else actions
        if count > remaining:
            raise BuilderError(f"task {task.task_id} has only {remaining} actions left")
        for _ in range(count):
            self._run_next()
        return self

    def end_task(self, ended_by: str = "reference") -> "SessionBuilder":
        """Termina la tarea en curso.

        Con ``reference``, primero se recorre lo que falta de la ruta (la
        página llega a la condición final). Con ``done`` o ``gave_up``, termina
        donde está.

        Args:
            ended_by: Cómo termina (``ended_by``).

        Returns:
            El constructor.
        """
        task = self._require_task("end_task")
        if ended_by == "reference":
            self.follow()
        self._check_no_pending("end_task")
        self._close_search()
        self._advance(200)
        if task.off_since is not None:
            task.off_path_ms += self._t - task.off_since
        duration = self._t - task.t_start
        self._task_records.append(
            {
                "task_id": task.task_id,
                "t_start": _round(task.t_start),
                "t_end": _round(self._t),
                "ended_by": ended_by,
            }
        )
        # Solo las sesiones guiadas tienen resultados por tarea; la grabación de
        # referencia queda en ``references``.
        if self._mode == "guided":
            self._tasks.append(
                ExpectedTask(
                    task_id=task.task_id,
                    ended_by=ended_by,
                    success=task.next_action == len(task.path),
                    duration_ms=_round(duration),
                    steps=task.steps,
                    path_steps=task.path_steps_done,
                    deviation_step=task.deviation_step,
                    off_path_ms=_round(task.off_path_ms),
                )
            )
        self._add_overtime(task, duration)
        if self._mode == "reference":
            self._references.append(
                ReferenceRecording(
                    task_id=task.task_id,
                    steps=tuple(task.recorded),
                    required_steps=tuple(task.required),
                    duration_ms=_round(duration),
                )
            )
        self._task = None
        return self

    # --- Patrones --------------------------------------------------------------

    def with_rage_click(
        self,
        element: Element | None = None,
        *,
        clicks: int | None = None,
        problem: int | None = None,
    ) -> "SessionBuilder":
        """Ráfaga de clics rápidos en un área pequeña.

        Sin ``element``, la ráfaga es la siguiente acción de la ruta (su clic, o
        el envío de su formulario): la página responde después del último clic.
        Con ``element``, es una ráfaga suelta sobre ese elemento.

        Args:
            element: Elemento de la ráfaga, o ``None`` para la siguiente acción.
            clicks: Cantidad de clics; por defecto, uno más que el mínimo de
                ``rage_click.min_clicks``. Con menos del mínimo no es incidente.
            problem: Problema sembrado que representa.

        Returns:
            El constructor.
        """
        if element is None:
            self._pending_rage = (clicks, problem)
            return self
        self._close_search()
        self._rage_burst(element, clicks, problem, role=self._pattern_role(element))
        return self

    def with_dead_click(self, element: Element, *, problem: int | None = None) -> "SessionBuilder":
        """Clic sin ninguna respuesta de la página.

        Después del clic no hay cambios ni navegación durante más que
        ``dead_click.wait_ms``.

        Args:
            element: Elemento del clic, normalmente no interactivo (una imagen
                que parece botón).
            problem: Problema sembrado que representa.

        Returns:
            El constructor.
        """
        self._close_search()
        self._think()
        self._move_to(element)
        self._focus_out(element)
        self._click_event(element, role=self._pattern_role(element))
        self._incident("dead_click", self._t, self._t, element=element, problem=problem)
        # Nada pasa: el participante espera más que el umbral antes de seguir.
        self._advance(self._params.dead_click.wait_ms * 1.4)
        self._skip_think = True
        return self

    def with_navigation_loop(
        self, away: Click, back: Click, *, problem: int | None = None
    ) -> "SessionBuilder":
        """Ir a otra pantalla y volver sin avanzar (patrón A → B → A).

        Dentro de una tarea, ir a la otra pantalla es un desvío.

        Args:
            away: Clic que lleva a la pantalla B.
            back: Clic que vuelve a la pantalla actual (A).
            problem: Problema sembrado que representa.

        Returns:
            El constructor.

        Raises:
            BuilderError: Si los clics no navegan, si ``back`` no vuelve a la
                pantalla actual o si el patrón no cabe en
                ``navigation_loop_window``.
        """
        here = self._require_screen()
        if away.to is None or back.to is None or back.to.pattern != here.pattern:
            raise BuilderError("a navigation loop needs 'away' to another screen and 'back' here")
        if self._params.navigation_loop_window < 3:
            raise BuilderError("navigation_loop_window is below 3 screens: A → B → A cannot fit")
        self._close_search()
        role = "off" if self._task else None
        self._click(away.element, to=away.to, role=role)
        left = self._screen_change_time
        self._think()
        self._click(
            back.element, to=back.to, role=role, screen_role="repeat" if self._task else None
        )
        self._incident(
            "navigation_loop", left, self._screen_change_time, screen=here.pattern, problem=problem
        )
        return self

    def with_form_error(
        self,
        field_index: int = 0,
        *,
        times: int = 1,
        erases: bool = False,
        pause: bool = False,
        error_type: str = "visible_message",
        problem: int | None = None,
    ) -> "SessionBuilder":
        """El siguiente formulario de la ruta se rechaza con un error de validación.

        Después de cada error, el participante vuelve a llenar el campo con
        error (o todos, si el formulario los borra) y lo envía de nuevo. Cada
        error es un ``form_error`` y cada campo que se vuelve a llenar, un
        ``field_reentry``.

        Args:
            field_index: Campo con el error, por posición.
            times: Cuántas veces se rechaza antes de aceptarlo.
            erases: Si el formulario borra todos los campos al mostrar el error.
            pause: Si después del primer error hay una pausa prolongada (un
                mensaje que no se entiende).
            error_type: Tipo de error (``validation_error_type``).
            problem: Problema sembrado que representa.

        Returns:
            El constructor.
        """
        self._pending_form_error = _FormError(
            field_index, times, erases, pause, error_type, problem
        )
        return self

    def with_silent_failure(
        self,
        field_index: int = 0,
        *,
        times: int = 1,
        erases: bool = False,
        problem: int | None = None,
    ) -> "SessionBuilder":
        """El siguiente formulario de la ruta falla sin un aviso que la captura reconozca.

        La página responde pero no avanza ni marca un error de validación (por
        ejemplo, un aviso general sin vínculo con el campo). La persona corrige el
        campo y lo envía de nuevo. Cada intento fallido es un ``silent_failure``.
        Como no hay ``validation_error``, el análisis ve cada intento como una
        serie de interacciones distinta: un episodio por intento y ningún
        ``field_reentry``.

        Args:
            field_index: Campo que la persona corrige, por posición.
            times: Cuántas veces falla antes de aceptarse.
            erases: Si la persona vuelve a llenar todos los campos y no solo uno.
            problem: Problema sembrado que representa.

        Returns:
            El constructor.
        """
        self._pending_silent_failure = _SilentFailure(field_index, times, erases, problem)
        return self

    def with_repeated_search(
        self, search: FillForm, results: Sequence[Screen], *, problem: int | None = None
    ) -> "SessionBuilder":
        """Varias búsquedas seguidas sin abrir ningún resultado.

        Es incidente si son al menos ``repeated_search.min_searches`` dentro de
        ``repeated_search.window_ms``.

        Args:
            search: Formulario de búsqueda (``kind="search"``).
            results: Pantalla de resultados de cada búsqueda, en orden.
            problem: Problema sembrado que representa.

        Returns:
            El constructor.
        """
        if search.kind != "search":
            raise BuilderError("with_repeated_search() needs a FillForm with kind='search'")
        role = "repeat" if self._task else None
        submits = []
        for screen in results:
            self._fill_form(dataclasses.replace(search, to=screen), role=role)
            submits.append(self._submit_time)
        span = submits[-1] - submits[0]
        settings = self._params.repeated_search
        if len(submits) >= settings.min_searches and span <= settings.window_ms:
            self._incident("repeated_search", submits[0], submits[-1], problem=problem)
        return self

    def with_long_pause(
        self, ms: float | None = None, *, problem: int | None = None
    ) -> "SessionBuilder":
        """Pausa sin ningún evento de interacción.

        Args:
            ms: Duración; por defecto, 1,5 veces ``long_pause_ms``. Si no supera
                el umbral, no es incidente.
            problem: Problema sembrado que representa.

        Returns:
            El constructor.
        """
        duration = self._params.long_pause_ms * 1.5 if ms is None else ms
        if duration > self._params.long_pause_ms:
            if not self._events:
                raise BuilderError("with_long_pause() needs an event before it")
            task_id = self._task.task_id if self._task else None
            if self._events[-1]["task_id"] != task_id:
                # El detector mide la pausa entre dos eventos de la misma tarea.
                raise BuilderError(
                    "with_long_pause() needs an event of the same task before it; "
                    "do an action of the task first"
                )
            self._open_pause = {
                "t_start": self._events[-1]["t"],
                "problem": problem,
                "screen": self._require_screen(),
                "task_id": self._task.task_id if self._task else None,
            }
        self._advance(duration)
        self._skip_think = True
        return self

    def with_hesitation(
        self, element: Element | None = None, *, ms: float | None = None, problem: int | None = None
    ) -> "SessionBuilder":
        """Cursor detenido sobre un elemento interactivo, sin activarlo.

        Sin ``element``, se detiene sobre el elemento de la siguiente acción y
        después hace esa acción. Con ``element``, se detiene sobre él y sigue
        sin hacer clic.

        Args:
            element: Elemento, o ``None`` para el de la siguiente acción.
            ms: Tiempo detenido; por defecto, entre ``hesitation_ms`` y
                ``long_pause_ms``. Si no supera ``hesitation_ms``, no es incidente.
            problem: Problema sembrado que representa.

        Returns:
            El constructor.
        """
        if element is None:
            self._pending_hesitation = (ms, problem)
            return self
        self._close_search()
        self._hesitate(element, ms, problem)
        return self

    def with_deviation_at_step(
        self, step: int, wrong: Click, back: Click | None = None
    ) -> "SessionBuilder":
        """Recorre la ruta hasta el paso indicado y ahí se desvía.

        Args:
            step: Posición (desde 0) del paso esperado al desviarse; debe caer
                al principio de una acción de la ruta.
            wrong: Clic fuera de la ruta.
            back: Clic que vuelve a la ruta (si ``wrong`` navegó), o ``None``.

        Returns:
            El constructor.
        """
        task = self._require_task("with_deviation_at_step")
        while task.path_steps_done < step and task.next_action < len(task.path):
            self._run_next()
        if task.path_steps_done != step:
            raise BuilderError(f"step {step} is not at the start of an action of the path")
        self._close_search()
        self._click(wrong.element, to=wrong.to, role="off")
        if back is not None:
            self._think()
            self._click(back.element, to=back.to, role="off", screen_role="repeat")
        return self

    def with_form_abandonment(
        self, form: FillForm, leave: Click, *, fields: int = 1, problem: int | None = None
    ) -> "SessionBuilder":
        """Llenar algunos campos de un formulario y salir sin enviarlo.

        Args:
            form: Formulario.
            leave: Clic que lleva a otra pantalla.
            fields: Cuántos campos llena antes de salir.
            problem: Problema sembrado que representa.

        Returns:
            El constructor.
        """
        if leave.to is None:
            raise BuilderError("with_form_abandonment() needs 'leave' to navigate")
        self._close_search()
        role = "off" if self._task else None
        start = None
        for element in form.fields[:fields]:
            self._click(element, role=role)
            start = start if start is not None else self._last_click
            self._type()
        screen = self._require_screen().pattern
        self._click(leave.element, to=leave.to, role=role)
        self._incident(
            "form_abandonment", self._last_click, self._last_click, screen=screen, problem=problem
        )
        self._episode(
            form.kind, start, self._last_click, screen, "abandoned", {"errors": 0, "reentries": 0}
        )
        return self

    def with_overtime(self) -> "SessionBuilder":
        """Pausas prolongadas hasta exceder el tiempo de la tarea.

        La tarea termina superando ``task_overtime_factor`` veces la duración de
        su referencia: un participante perdido.

        Returns:
            El constructor.

        Raises:
            BuilderError: Si no hay tarea o no se conoce su referencia.
        """
        task = self._require_task("with_overtime")
        reference = self._reference_durations.get(task.task_id)
        if reference is None:
            raise BuilderError(
                f"with_overtime() needs the reference duration of task {task.task_id}"
            )
        limit = task.t_start + reference * self._params.task_overtime_factor
        if not self._events or self._events[-1]["task_id"] != task.task_id:
            # Cada pausa larga va entre dos eventos de la tarea, como la mide el detector.
            self._move_by(40, 25)
        while self._t <= limit + 500:
            self.with_long_pause()
            self._move_by(40, 25)
        return self

    def with_calibration(
        self,
        type: str,
        error_deg: float,
        *,
        accepted: bool = True,
        camera_delay_ms: float | None = 45.0,
    ) -> "SessionBuilder":
        """Resultado de una calibración de mirada.

        Args:
            type: ``initial`` o ``final``.
            error_deg: Error medio en grados.
            accepted: Si se aceptó.
            camera_delay_ms: Retraso medido de la cámara, o ``None``.

        Returns:
            El constructor.
        """
        if self._eyes is not None:
            # La calibración ocupa su tiempo; la mirada queda en pausa y el rostro sigue.
            run = self._eyes.calibration(type, self._t, error_deg, accepted)
            self._eye_frames.extend(run.frames)
            self._gaze_targets.extend(run.targets)
            self._gaze_paused.append((run.start, run.end))
            self._relaxed.extend(
                (target["t_start"], target["t_end"])
                for target in run.targets
                if target["phase"] == "neutral_baseline"
            )
            self._calibrations.append(run.record)
            self._t = run.end
            return self
        self._calibrations.append(
            {
                "t": _round(self._t),
                "type": type,
                "error_px": _round(error_deg * 38.0),
                "error_deg": error_deg,
                "accepted": accepted,
                "camera_delay_ms": camera_delay_ms,
            }
        )
        return self

    def with_sus(self, answers: Sequence[int]) -> "SessionBuilder":
        """Respuestas del cuestionario SUS.

        Args:
            answers: Las 10 respuestas, de 1 a 5.

        Returns:
            El constructor.
        """
        self._sus = tuple(answers)
        return self

    def build(self) -> SimulatedSession:
        """Termina la sesión y la entrega con su verdad de referencia.

        Returns:
            Sesión simulada.

        Raises:
            BuilderError: Si queda una tarea abierta o un patrón sin usar.
        """
        if self._task is not None:
            raise BuilderError(f"task {self._task.task_id} is still open; call end_task() first")
        self._check_no_pending("build")
        if self._open_pause is not None:
            raise BuilderError("with_long_pause() needs an event after it")
        self._close_search()
        self._advance(1500)
        ended_at = self._t
        self._close_visit(ended_at)
        incidents = tuple(sorted(self._incidents, key=lambda item: (item.t_start, item.type)))
        episodes = tuple(
            _with_screen_incidents(episode, incidents)
            for episode in sorted(self._episodes, key=lambda item: (item.t_start, item.type))
        )
        batches: dict[str, tuple[Mapping[str, Any], ...]] = {"events": tuple(self._events)}
        if self._camera:
            batches["gaze"], batches["face"] = self._camera_samples(ended_at, incidents)
        if self._eyes is not None:
            batches["gaze_features"] = tuple(sorted(self._eye_frames, key=lambda f: f["t"]))
            batches["gaze_target"] = tuple(self._gaze_targets)
            batches["layout"] = self._layouts()
        if self._task_records:
            batches["tasks"] = tuple(self._task_records)
        if self._calibrations:
            batches["calibration"] = tuple(self._calibrations)
        return SimulatedSession(
            request=self._request,
            started_at=_round(self._started_at),
            ended_at=_round(ended_at),
            batches=batches,
            sus_answers=self._sus,
            truth=SessionTruth(
                incidents=incidents,
                episodes=episodes,
                tasks=tuple(self._tasks),
                usability_index=self._expected_index(incidents),
            ),
            references=tuple(self._references),
        )

    # --- Ejecución de acciones -------------------------------------------------

    def _run_next(self) -> None:
        """Hace la siguiente acción de la ruta."""
        task = self._require_task("follow")
        action = task.path[task.next_action]
        task.next_action += 1
        self._run(action, role="path")

    def _run(self, action: Action, *, role: str | None) -> None:
        """Hace una acción con el papel dado (``path``, ``off`` o ``None`` sin tarea)."""
        if isinstance(action, Scroll):
            self._scroll(action.to_y)
        elif isinstance(action, SelectText):
            self._think()
            self._emit("selection", data={"length": action.length})
        elif isinstance(action, FillForm):
            self._fill_form(action, role=role)
        else:
            self._run_click(action, role=role)

    def _run_click(self, action: Click, *, role: str | None) -> None:
        """Hace un clic de la ruta, con los patrones pendientes."""
        if self._search is not None and self._screen.pattern != self._search["screen"]:
            self._close_search()
        searching = self._search is not None
        self._apply_hesitation(action.element)
        if self._pending_rage is not None:
            clicks, problem = self._pending_rage
            self._pending_rage = None
            self._rage_burst(
                action.element, clicks, problem, role=role, to=action.to, required=action.required
            )
        else:
            self._click(action.element, to=action.to, role=role, required=action.required)
        if searching:
            self._search["result_clicks"] += 1
            self._close_search(t_end=self._last_click, outcome="result_opened")

    def _fill_form(self, action: FillForm, *, role: str | None) -> None:
        """Llena y envía un formulario, con el error de validación pendiente si lo hay."""
        if action.kind not in FORM_KINDS:
            raise BuilderError(f"unknown form kind {action.kind!r}; expected one of {FORM_KINDS}")
        if action.kind == "search":
            if self._search is None:
                self._search = {"t_start": None, "searches": 0, "result_clicks": 0}
        else:
            self._close_search()
        screen = self._require_screen().pattern
        start = None
        for element in action.fields:
            self._apply_hesitation(element)
            self._click(element, role=role)
            start = start if start is not None else self._last_click
            self._type()
        error, self._pending_form_error = self._pending_form_error, None
        silent, self._pending_silent_failure = self._pending_silent_failure, None
        if error is not None and silent is not None:
            raise BuilderError("with_form_error() and with_silent_failure() cannot share a form")
        errors = reentries = 0
        attempts = 1
        if error is not None:
            if not 0 <= error.field_index < len(action.fields):
                raise BuilderError(f"with_form_error(): the form has no field {error.field_index}")
            repeat = "repeat" if role == "path" else role
            for attempt in range(error.times):
                first_try = attempt == 0
                self._submit(
                    action,
                    role=role if first_try else repeat,
                    navigate=False,
                    required=action.required and first_try,
                )
                field_element = action.fields[error.field_index]
                self._advance(150)
                self._emit(
                    "validation_error", element=field_element, data={"error_type": error.error_type}
                )
                self._incident(
                    "form_error", self._t, self._t, element=field_element, problem=error.problem
                )
                errors += 1
                if error.pause and attempt == 0:
                    self.with_long_pause(problem=error.problem)
                again = action.fields if error.erases else (field_element,)
                for element in again:
                    self._click(element, role=repeat)
                    entered = self._last_click
                    self._type()
                    self._incident(
                        "field_reentry", entered, self._t, element=element, problem=error.problem
                    )
                    reentries += 1
                attempts += 1
            self._submit(action, role=repeat, navigate=True, screen_role=role)
        elif silent is not None:
            start = self._silent_failures(action, silent, role=role, screen=screen, start=start)
            self._submit(
                action, role="repeat" if role == "path" else role, navigate=True, screen_role=role
            )
        else:
            self._submit(action, role=role, navigate=True, required=action.required)
        if action.kind == "search":
            self._search["t_start"] = self._search["t_start"] or start
            self._search["searches"] += attempts
            self._search["screen"] = (action.to or self._screen).pattern
            self._search["last"] = self._t
            self._search["form_screen"] = self._search.get("form_screen", screen)
        else:
            metrics = (
                {"attempts": attempts, "errors": errors}
                if action.kind == "login"
                else {"errors": errors, "reentries": reentries}
            )
            outcome = "success" if action.kind == "login" else "submitted"
            self._episode(action.kind, start, self._submit_time, screen, outcome, metrics)

    def _silent_failures(
        self,
        action: FillForm,
        silent: _SilentFailure,
        *,
        role: str | None,
        screen: str,
        start: float,
    ) -> float:
        """Envíos que fallan sin aviso reconocible, cada uno seguido de la corrección del campo.

        Cada intento queda como un episodio: sin ``validation_error``, el análisis
        parte las interacciones del formulario en cada envío seguido de una edición.

        Returns:
            Inicio de la serie del intento final: el primer clic de la última corrección.
        """
        if not 0 <= silent.field_index < len(action.fields):
            raise BuilderError(f"with_silent_failure(): the form has no field {silent.field_index}")
        repeat = "repeat" if role == "path" else role
        login = action.kind == "login"
        for attempt in range(silent.times):
            first_try = attempt == 0
            self._submit(
                action,
                role=role if first_try else repeat,
                navigate=False,
                required=action.required and first_try,
            )
            sent = self._submit_time
            self._incident(
                "silent_failure", sent, sent, element=action.form, problem=silent.problem
            )
            # En el inicio de sesión, un intento seguido de otro en la misma visita no dio acceso.
            self._episode(
                action.kind,
                start,
                sent,
                screen,
                "failed" if login else "submitted",
                {"attempts": 1, "errors": 0} if login else {"errors": 0, "reentries": 0},
            )
            field_element = action.fields[silent.field_index]
            start = None
            for element in action.fields if silent.erases else (field_element,):
                self._click(element, role=repeat)
                start = start if start is not None else self._last_click
                self._type()
        return start

    def _submit(
        self,
        action: FillForm,
        *,
        role: str | None,
        navigate: bool,
        required: bool = False,
        screen_role: str | None = None,
    ) -> None:
        """Hace clic en el botón de envío y envía el formulario."""
        to = action.to if navigate else None
        if self._pending_rage is not None:
            clicks, problem = self._pending_rage
            self._pending_rage = None
            self._rage_burst(
                action.submit,
                clicks,
                problem,
                role=role,
                submit=action,
                to=to,
                required=required,
                screen_role=screen_role,
            )
            return
        self._think()
        self._move_to(action.submit)
        self._focus_out()
        self._click_event(action.submit, role=role)
        self._advance(15)
        self._submit_event(action, role=role, required=required)
        self._respond(to=to, role=screen_role or role, mutations=(3, 12))

    def _submit_event(self, action: FillForm, *, role: str | None, required: bool) -> None:
        """Emite el ``form_submit`` y anota el paso."""
        self._emit("form_submit", element=action.form)
        self._submit_time = self._t
        self._step("form_submit", action.form, role=role, required=required)

    def _click(
        self,
        element: Element,
        *,
        to: Screen | None = None,
        role: str | None,
        required: bool = False,
        screen_role: str | None = None,
    ) -> None:
        """Clic normal: pausa de decisión, movimiento, clic y respuesta de la página."""
        self._think()
        self._move_to(element)
        self._focus_out(element)
        self._click_event(element, role=role, required=required)
        if element.is_text_field and to is None:
            self._advance(30)
            if self._focused is not element:
                self._emit("focus_in", element=element)
            self._focused = element
        else:
            self._respond(to=to, role=screen_role or role, mutations=(1, 15))

    def _rage_burst(
        self,
        element: Element,
        clicks: int | None,
        problem: int | None,
        *,
        role: str | None,
        to: Screen | None = None,
        required: bool = False,
        submit: FillForm | None = None,
        screen_role: str | None = None,
    ) -> None:
        """Varios clics rápidos en el mismo lugar; la página responde después del último."""
        settings = self._params.rage_click
        count = settings.min_clicks + 1 if clicks is None else clicks
        span = settings.window_ms * 0.6
        respond_by = self._params.dead_click.wait_ms * 0.8
        if span >= respond_by:
            raise BuilderError(
                "rage_click.window_ms leaves no room to respond within dead_click.wait_ms"
            )
        self._think()
        self._move_to(element)
        self._focus_out(element)
        cx, cy = _center(element)
        first = None
        click_times = []
        for index in range(count):
            if index:
                self._advance(span / max(count - 1, 1))
            angle = self._rng.uniform(0, 2 * math.pi)
            radius = self._rng.uniform(0, settings.radius_px / 3)
            self._cursor = (cx + radius * math.cos(angle), cy + radius * math.sin(angle))
            click_role = role if index == 0 else ("repeat" if role in ("path", "repeat") else role)
            self._click_event(element, role=click_role, required=required and index == 0)
            click_times.append(_round(self._last_click))
            first = first if first is not None else self._last_click
            if submit is not None:
                self._advance(15)
                self._submit_event(submit, role=click_role, required=required and index == 0)
        screen = self._require_screen().pattern
        # La página responde antes de que venza la espera del primer clic: no hay clics muertos.
        self._advance(max(first + (span + respond_by) / 2 - self._t, 50))
        navigated = to is not None
        if navigated:
            self._change_screen(to, role=screen_role or role)
        for click_t in click_times:
            self._emit(
                "click_response",
                data={
                    "click_t": click_t,
                    "mutation_count": self._rng.randint(4, 30),
                    "navigated": navigated,
                },
            )
        if count >= settings.min_clicks:
            self._incident(
                "rage_click",
                first,
                click_times[-1],
                screen=screen,
                element=element,
                problem=problem,
            )

    def _hesitate(self, element: Element, ms: float | None, problem: int | None) -> None:
        """Detiene el cursor sobre un elemento."""
        low, high = self._params.hesitation_ms, self._params.long_pause_ms
        if high - low < 400:
            raise BuilderError("hesitation_ms and long_pause_ms are too close to tell apart")
        duration = (low + high) / 2 if ms is None else ms
        self._think()
        self._move_to(element)
        stopped = self._t
        self._advance(duration)
        if duration > low:
            self._incident("hesitation", stopped, self._t, element=element, problem=problem)
        self._skip_think = True

    def _apply_hesitation(self, element: Element) -> None:
        """Si hay una vacilación pendiente, la hace sobre el elemento de la acción."""
        if self._pending_hesitation is not None:
            ms, problem = self._pending_hesitation
            self._pending_hesitation = None
            self._hesitate(element, ms, problem)

    # --- Eventos -----------------------------------------------------------------

    def _emit(
        self,
        type: str,
        *,
        x: float | None = None,
        y: float | None = None,
        element: Element | None = None,
        data: Mapping[str, Any] | None = None,
    ) -> None:
        """Agrega un evento en el instante actual, con la pantalla y la tarea activas."""
        screen = self._require_screen()
        record: dict[str, Any] = {
            "t": _round(self._t),
            "type": type,
            "screen": screen.record(),
            "task_id": self._task.task_id if self._task else None,
        }
        if x is not None:
            record["x"], record["y"] = _round(x), _round(y)
        if element is not None:
            record["element"] = element.descriptor()
        if data is not None:
            record["data"] = dict(data)
        if self._open_pause is not None:
            pause, self._open_pause = self._open_pause, None
            self._incidents.append(
                ExpectedIncident(
                    "long_pause",
                    _round(pause["t_start"]),
                    record["t"],
                    pause["screen"].pattern,
                    pause["task_id"],
                    None,
                    pause["problem"],
                )
            )
        self._events.append(record)

    def _click_event(self, element: Element, *, role: str | None, required: bool = False) -> None:
        """Emite el clic en la posición del cursor y anota el paso si el elemento es interactivo."""
        x, y = self._cursor
        self._emit("click", x=x, y=y, element=element)
        self._last_click = self._t
        if element.interactive:
            self._step("click", element, role=role, required=required)

    def _respond(self, *, to: Screen | None, role: str | None, mutations: tuple[int, int]) -> None:
        """Respuesta de la página a un clic: navegación o cambios en la página."""
        click_t = _round(self._last_click)
        if to is not None:
            self._advance(self._rng.uniform(120, 220))
            self._change_screen(to, role=role)
        self._advance(self._rng.uniform(80, 250))
        self._emit(
            "click_response",
            data={
                "click_t": click_t,
                "mutation_count": self._rng.randint(*mutations),
                "navigated": to is not None,
            },
        )

    def _change_screen(self, screen: Screen, *, role: str | None) -> None:
        """Cambia de pantalla; si cambia la pantalla normalizada, empieza una visita nueva."""
        previous = self._screen
        self._screen = screen
        self._screen_log.append((self._t, screen.pattern))
        if previous is None or previous.pattern != screen.pattern:
            if previous is not None:
                self._close_visit(self._t, previous)
            self._visit_start = self._t
        self._emit("screen_change")
        self._screen_change_time = self._t
        self._scroll_y = 0.0
        if previous is not None:
            self._step("screen_change", None, role=role)

    def _close_visit(self, t_end: float, screen: Screen | None = None) -> None:
        """Cierra la visita a la pantalla actual como episodio ``screen``."""
        screen = screen or self._screen
        if screen is not None:
            self._episode("screen", self._visit_start, t_end, screen.pattern, None, {})

    def _focus_out(self, target: Element | None = None) -> None:
        """Quita el foco del campo activo, si el clic va a otro elemento."""
        if self._focused is not None and self._focused is not target:
            self._emit("focus_out", element=self._focused)
            self._focused = None

    def _type(self) -> None:
        """Escribe en el campo con foco: un ``field_change`` por segundo como máximo.

        Termina poco después del último cambio, así ningún hueco normal se
        acerca a la vacilación.
        """
        for _ in range(self._rng.choice((1, 2))):
            self._advance(1000)
            self._emit("field_change", element=self._focused)
        self._advance(self._rng.uniform(100, 300))

    def _scroll(self, to_y: float) -> None:
        """Desplaza la página a ``scroll_hz`` como máximo."""
        self._think()
        start = self._scroll_y
        steps = 4
        for index in range(1, steps + 1):
            self._advance(self._scroll_ms)
            self._scroll_y = start + (to_y - start) * index / steps
            self._emit("scroll", data={"scroll_x": 0, "scroll_y": _round(self._scroll_y)})

    def _move_to(self, element: Element) -> None:
        """Mueve el cursor hasta un punto del elemento, a ``mousemove_hz`` como máximo."""
        cx, cy = _center(element)
        _, _, w, h = element.box
        target = (cx + self._rng.uniform(-w / 5, w / 5), cy + self._rng.uniform(-h / 5, h / 5))
        start = self._cursor
        distance = math.dist(start, target)
        samples = max(3, min(12, int(distance / 60)))
        for index in range(1, samples + 1):
            self._advance(self._mousemove_ms)
            fraction = index / samples
            self._cursor = (
                start[0] + (target[0] - start[0]) * fraction + self._rng.uniform(-2, 2),
                start[1] + (target[1] - start[1]) * fraction + self._rng.uniform(-2, 2),
            )
            self._emit("mousemove", x=self._cursor[0], y=self._cursor[1])
        self._cursor = target

    def _move_by(self, dx: float, dy: float) -> None:
        """Mueve el cursor un poco, sin objetivo."""
        x, y = self._cursor
        for _ in range(3):
            self._advance(self._mousemove_ms)
            x, y = x + dx / 3, y + dy / 3
            self._emit("mousemove", x=x, y=y)
        self._cursor = (x, y)

    def _think(self) -> None:
        """Pausa normal antes de una acción: nunca cruza ningún umbral."""
        if self._skip_think:
            self._skip_think = False
            self._advance(150)
            return
        self._advance(self._rng.uniform(*self._think_range))

    def _advance(self, ms: float) -> None:
        """Avanza el reloj de la sesión."""
        self._t += ms

    # --- Verdad de referencia ----------------------------------------------------

    def _step(
        self, kind: str, element: Element | None, *, role: str | None, required: bool = False
    ) -> None:
        """Anota un paso de la tarea según su papel: ``path``, ``repeat`` u ``off``."""
        task = self._task
        if task is None or role is None:
            return
        task.steps += 1
        if role == "off":
            if task.deviation_step is None:
                task.deviation_step = task.path_steps_done
            if task.off_since is None:
                task.off_since = self._t
            return
        if task.off_since is not None:
            task.off_path_ms += self._t - task.off_since
            task.off_since = None
        if role == "path":
            if required:
                task.required.append(task.path_steps_done)
            task.recorded.append(
                {
                    "t": _round(self._t),
                    "type": kind,
                    "screen": self._screen.record(),
                    "element": None if element is None else element.descriptor(),
                }
            )
            task.path_steps_done += 1

    def _incident(
        self,
        type: str,
        t_start: float,
        t_end: float,
        *,
        screen: str | None = None,
        element: Element | None = None,
        problem: int | None = None,
    ) -> None:
        """Anota un incidente esperado."""
        self._incidents.append(
            ExpectedIncident(
                type=type,
                t_start=_round(t_start),
                t_end=_round(t_end),
                screen=screen or self._require_screen().pattern,
                task_id=self._task.task_id if self._task else None,
                element=None if element is None else element.descriptor(),
                problem=problem,
            )
        )

    def _episode(
        self,
        type: str,
        t_start: float,
        t_end: float,
        screen: str,
        outcome: str | None,
        metrics: Mapping[str, Any],
    ) -> None:
        """Anota un episodio esperado."""
        self._episodes.append(
            ExpectedEpisode(type, _round(t_start), _round(t_end), screen, outcome, dict(metrics))
        )

    def _close_search(
        self, *, t_end: float | None = None, outcome: str = "no_result_opened"
    ) -> None:
        """Cierra el episodio de búsqueda en curso, si lo hay."""
        if self._search is None:
            return
        search, self._search = self._search, None
        self._episode(
            "search",
            search["t_start"],
            t_end if t_end is not None else search["last"],
            search["form_screen"],
            outcome,
            {"searches": search["searches"], "result_clicks": search["result_clicks"]},
        )

    def _add_overtime(self, task: _Task, duration: float) -> None:
        """Anota ``task_overtime`` si la tarea superó el factor de su referencia."""
        reference = self._reference_durations.get(task.task_id)
        if reference is None:
            return
        limit = reference * self._params.task_overtime_factor
        if duration > limit:
            self._incidents.append(
                ExpectedIncident(
                    "task_overtime",
                    _round(task.t_start + limit),
                    _round(self._t),
                    self._screen_at(task.t_start + limit),
                    task.task_id,
                )
            )

    def _expected_index(self, incidents: Sequence[ExpectedIncident]) -> ExpectedIndex | None:
        """Índice esperado de una sesión guiada, si se conocen referencias y ``i_max``."""
        if self._mode != "guided" or not self._tasks or self._i_max is None:
            return None
        if any(task.task_id not in self._reference_durations for task in self._tasks):
            return None
        completed = [task for task in self._tasks if task.success]
        effectiveness = 100 * len(completed) / len(self._tasks)
        if completed:
            time_efficiency = 100 * _mean(
                min(1.0, self._reference_durations[task.task_id] / task.duration_ms)
                for task in completed
            )
            path_efficiency = 100 * _mean(
                min(1.0, task.path_steps / task.steps) for task in completed
            )
        else:
            time_efficiency = path_efficiency = 0.0
        task_minutes = sum(task.duration_ms for task in self._tasks) / 60_000
        per_minute = sum(1 for incident in incidents if incident.task_id is not None) / task_minutes
        friction = 100 * (1 - min(1.0, per_minute / self._i_max))
        components = (effectiveness, time_efficiency, path_efficiency, friction)
        return ExpectedIndex(
            *(round(value, 2) for value in components), bui=round(_mean(components), 2)
        )

    # --- Mirada y rostro ---------------------------------------------------------

    def _camera_samples(
        self, ended_at: float, incidents: Sequence[ExpectedIncident]
    ) -> tuple[tuple[dict[str, Any], ...], tuple[dict[str, Any], ...]]:
        """Muestras de mirada y rostro a lo largo de la sesión.

        La mirada sigue al cursor con ruido; el rostro muestra más tensión
        (cejas y labios) cerca de los incidentes. Con ojos simulados, la
        persona mira adonde irá el cursor ``EYE_LEAD_MS`` después, sin pasar a
        la pantalla siguiente: los ojos se adelantan a la mano.
        """
        positions = [
            (
                event["t"],
                event.get("x"),
                event.get("y"),
                0.0 if event["type"] == "screen_change" else event.get("data", {}).get("scroll_y"),
            )
            for event in self._events
        ]
        width = DEFAULT_SCREEN_INFO["window_width"]
        height = DEFAULT_SCREEN_INFO["window_height"]
        tense = [(item.t_start - 500, item.t_end + 2000) for item in incidents]
        gaze, face = [], []
        index, x, y, scroll = 0, width / 2, height / 2, 0.0
        ahead, ax, ay = 0, x, y
        changes = [event["t"] for event in self._events if event["type"] == "screen_change"]
        step_gaze = 1000 / self._gaze_hz
        t = self._started_at + step_gaze
        while t < ended_at:
            while index < len(positions) and positions[index][0] <= t:
                _, px, py, ps = positions[index]
                if px is not None:
                    x, y = px, py
                if ps is not None:
                    scroll = ps
                index += 1
            if any(start <= t <= end for start, end in self._gaze_paused):
                t += step_gaze
                continue
            if self._eyes is not None:
                upcoming = [change for change in changes if change > t]
                horizon = min([t + EYE_LEAD_MS, *upcoming[:1]])
                ahead = max(ahead, index)
                ax, ay = (x, y) if ahead == index else (ax, ay)
                while ahead < len(positions) and positions[ahead][0] < horizon:
                    if positions[ahead][1] is not None:
                        ax, ay = positions[ahead][1], positions[ahead][2]
                    ahead += 1
                gaze.append(self._eye_sample(t, ax, ay, scroll))
            elif self._rng.random() < 0.03:
                gaze.append({"t": _round(t), "valid": False})
            else:
                gx = min(max(x + self._rng.gauss(0, 30), 0), width)
                gy = min(max(y + self._rng.gauss(0, 30), 0), height)
                gaze.append(
                    {
                        "t": _round(t),
                        "x": _round(gx),
                        "y": _round(gy),
                        "scroll_x": 0,
                        "scroll_y": scroll,
                        "element_selector": None,
                        "zone": _zone(gx, gy, width, height),
                        "valid": True,
                    }
                )
            t += step_gaze
        step_face = 1000 / self._face_hz
        t = self._started_at + step_face
        while t < ended_at:
            tension = 0.45 if any(start <= t <= end for start, end in tense) else 0.0
            if self._eyes is not None:
                relaxed = any(start <= t <= end for start, end in self._relaxed)
                face.append(
                    {
                        "t": _round(t),
                        "values": face_values(self._rng, 0.0 if relaxed else tension),
                        "head_yaw": _round(self._rng.gauss(0, 4)),
                        "head_pitch": _round(self._rng.gauss(-3, 3)),
                        "face_detected": True,
                    }
                )
                t += step_face
                continue
            values = {
                "brow_down_left": tension + self._rng.uniform(0, 0.15),
                "brow_down_right": tension + self._rng.uniform(0, 0.15),
                "brow_inner_up": self._rng.uniform(0, 0.2),
                "eye_blink_left": self._rng.uniform(0, 0.1),
                "eye_blink_right": self._rng.uniform(0, 0.1),
                "mouth_press_left": tension * 0.8 + self._rng.uniform(0, 0.1),
                "mouth_press_right": tension * 0.8 + self._rng.uniform(0, 0.1),
                "mouth_smile_left": (0.3 - tension / 2) * self._rng.uniform(0.2, 1),
                "mouth_smile_right": (0.3 - tension / 2) * self._rng.uniform(0.2, 1),
            }
            face.append(
                {
                    "t": _round(t),
                    "values": {
                        key: round(min(max(value, 0.0), 1.0), 3) for key, value in values.items()
                    },
                    "head_yaw": _round(self._rng.gauss(0, 4)),
                    "head_pitch": _round(self._rng.gauss(-3, 3)),
                    "face_detected": True,
                }
            )
            t += step_face
        return tuple(gaze), tuple(face)

    def _eye_sample(self, t: float, x: float, y: float, scroll: float) -> dict[str, Any]:
        """Cuadro de los ojos mirando el cursor y la muestra en vivo que da.

        La persona mira donde está el cursor. El cuadro va a ``gaze_features``;
        la mirada en vivo es la estimación ruidosa de ese cuadro.
        """
        assert self._eyes is not None
        width, height = self._eyes.viewport
        look = (min(max(x, 0.0), width), min(max(y, 0.0), height))
        blinking = self._rng.random() < 0.03
        frame = self._eyes.frame(
            t,
            look,
            self._eyes.pose(SESSION_POSE),
            state="blink" if blinking else "on_screen",
            blink=0.9 if blinking else 0.02,
            scroll_y=float(scroll),
        )
        self._eye_frames.append(frame)
        if blinking:
            return {"t": _round(t), "valid": False}
        gx = min(max(frame["raw_x"], 0.0), width)
        gy = min(max(frame["raw_y"], 0.0), height)
        return {
            "t": _round(t),
            "x": _round(gx),
            "y": _round(gy),
            "scroll_x": 0,
            "scroll_y": scroll,
            "element_selector": None,
            "zone": _zone(gx, gy, width, height),
            "valid": True,
        }

    def _layouts(self) -> tuple[dict[str, Any], ...]:
        """Disposición de cada pantalla al abrirla y tras cada scroll.

        Los elementos de una pantalla son los que aparecen en los eventos de la
        sesión en esa URL, con su caja en la ventana. En la tienda simulada las
        cajas no se mueven con el scroll, así que cada disposición lleva el
        scroll de su momento y la atribución no las desplaza.
        """
        elements: dict[str, dict[str, dict[str, Any]]] = {}
        for event in self._events:
            element = event.get("element")
            if element:
                elements.setdefault(event["screen"]["url"], {}).setdefault(
                    element["selector"],
                    {
                        "selector": element["selector"],
                        "tag": element["tag"],
                        "role": element["role"],
                        "box": dict(element["box"]),
                        "fixed": False,
                        "interactive": bool(element["interactive"]),
                        "parent": None,
                    },
                )
        width = DEFAULT_SCREEN_INFO["window_width"]
        height = DEFAULT_SCREEN_INFO["window_height"]
        layouts = []
        for event in self._events:
            if event["type"] not in ("screen_change", "scroll"):
                continue
            scroll_y = (
                event.get("data", {}).get("scroll_y", 0.0) if event["type"] == "scroll" else 0.0
            )
            layouts.append(
                {
                    "t": event["t"],
                    "screen": dict(event["screen"]),
                    "viewport_width": width,
                    "viewport_height": height,
                    "scroll_x": 0,
                    "scroll_y": scroll_y,
                    "regions": [],
                    "elements": list(elements.get(event["screen"]["url"], {}).values()),
                    "truncated": False,
                }
            )
        return tuple(layouts)

    # --- Validaciones ------------------------------------------------------------

    def _normal_think_range(self) -> tuple[float, float]:
        """Pausa normal entre acciones, entre la ventana de rage click y la vacilación."""
        low = self._params.rage_click.window_ms * 1.1
        # Con los 500 ms de inicio y fin de tarea, ningún hueco normal llega a la vacilación.
        high = min(self._params.hesitation_ms, self._params.long_pause_ms) * 0.7
        if low >= high:
            raise BuilderError(
                "rage_click.window_ms is too close to hesitation_ms: normal pacing would cross them"
            )
        return low, high

    def _screen_at(self, t: float) -> str:
        """Pantalla normalizada que estaba abierta en un instante."""
        current = self._screen_log[0][1]
        for changed, pattern in self._screen_log:
            if changed > t:
                break
            current = pattern
        return current

    def _require_screen(self) -> Screen:
        """Devuelve la pantalla actual, o falla si todavía no hay ninguna."""
        if self._screen is None:
            raise BuilderError("open a screen with on_screen() first")
        return self._screen

    def _require_task(self, method: str) -> _Task:
        """Devuelve la tarea en curso, o falla si no hay ninguna."""
        if self._task is None:
            raise BuilderError(f"{method}() needs a task; call with_task() first")
        return self._task

    def _pattern_role(self, element: Element) -> str | None:
        """Papel de un clic de un patrón: fuera de la ruta dentro de una tarea."""
        return "off" if self._task and element.interactive else None

    def _check_no_pending(self, method: str) -> None:
        """Falla si quedó un patrón que esperaba la siguiente acción."""
        pending = [
            name
            for name, value in (
                ("with_rage_click", self._pending_rage),
                ("with_hesitation", self._pending_hesitation),
                ("with_form_error", self._pending_form_error),
                ("with_silent_failure", self._pending_silent_failure),
            )
            if value is not None
        ]
        if pending:
            raise BuilderError(f"{method}(): {pending} waited for an action that never came")


def count_steps(actions: Sequence[Action]) -> int:
    """Cuenta los pasos que producen unas acciones de una ruta.

    Sirve para ubicar una posición de la ruta, por ejemplo para
    ``with_deviation_at_step(count_steps(path[:2]), …)``.

    Args:
        actions: Acciones, en orden.

    Returns:
        Clics en elementos interactivos, envíos de formulario y cambios de pantalla.
    """
    total = 0
    for action in actions:
        if isinstance(action, Click):
            total += int(action.element.interactive) + int(action.to is not None)
        elif isinstance(action, FillForm):
            fields = sum(int(element.interactive) for element in action.fields)
            total += fields + 2 + int(action.to is not None)
    return total


def _round(value: float) -> float:
    """Redondea a una décima: tiempos y coordenadas."""
    return round(value, 1)


def _center(element: Element) -> tuple[float, float]:
    """Centro del rectángulo de un elemento."""
    x, y, w, h = element.box
    return x + w / 2, y + h / 2


def _mean(values: Any) -> float:
    """Promedio de una serie de números."""
    items = list(values)
    return sum(items) / len(items)


def _zone(x: float, y: float, width: float, height: float) -> str:
    """Zona de la mirada según el diseño de la tienda simulada."""
    if y < 64:
        return "header"
    if y < 104:
        return "nav"
    if y > height - 56:
        return "footer"
    if x > width - 260:
        return "aside"
    return "main"


def _with_screen_incidents(
    episode: ExpectedEpisode, incidents: Sequence[ExpectedIncident]
) -> ExpectedEpisode:
    """Agrega a una visita los incidentes ubicados en ella por su tiempo de referencia."""
    if episode.type != "screen":
        return episode
    count = sum(
        1
        for incident in incidents
        if episode.t_start <= incident.t < episode.t_end and incident.screen == episode.screen
    )
    return ExpectedEpisode(
        episode.type,
        episode.t_start,
        episode.t_end,
        episode.screen,
        episode.outcome,
        {"incidents": count},
    )
