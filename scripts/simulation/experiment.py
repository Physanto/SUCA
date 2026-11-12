"""Experimento simulado: participantes entre sujetos repartidos en V0, V1 y V2.

Reproduce el diseño del experimento con datos falsos: cada participante usa
una sola versión, hace las 4 tareas guiadas y responde el SUS. Cada problema
sembrado de su versión le afecta con cierta probabilidad (a algunos no les
cuesta nada), algunos se detienen a pensar aunque no haya un problema (las
falsas alarmas reales de los detectores) y en V2 algunos abandonan la última
tarea. El SUS baja con la versión, con variación entre personas.

La verdad de cada participante dice qué problemas tenía su versión (pasó por
todos, porque la ruta de las tareas los atraviesa) y cuáles le afectaron. Con
ella se prueban las medidas del experimento antes de tener participantes.
"""

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from scripts.simulation.builder import (
    DEFAULT_START,
    Action,
    Click,
    SessionBuilder,
    SimulatedSession,
)
from scripts.simulation.scenarios import (
    ADDRESS_LINK,
    CONFIRMATION,
    HELP,
    HELP_BACK,
    LOGIN,
    LOGIN_ACTION,
    MENU_HELP,
    MENU_MORE,
    MOCK_FACE_HZ,
    MOCK_FRICTION_I_MAX,
    MOCK_GAZE_HZ,
    SEARCH,
    TASKS,
    ZOOM_BADGE,
    StudyContext,
    results,
)

VERSIONS: Mapping[str, tuple[int, ...]] = {
    "V0": (),
    "V1": (1, 2, 3, 4),
    "V2": (1, 2, 3, 4, 5, 6, 7, 8),
}
"""Problemas sembrados activos en cada versión, como en la tienda de prueba."""

SUS_MEAN: Mapping[str, float] = {"V0": 80.0, "V1": 66.0, "V2": 52.0}
"""SUS medio esperado por versión; cada persona se aparta de él."""

SUS_SPREAD = 9.0
"""Desvío del SUS entre personas de la misma versión."""

DEFAULT_AFFECTED = 0.8
"""Probabilidad de que un problema de la versión afecte al participante."""

DEFAULT_FALSE_ALARM = 0.25
"""Probabilidad de que un participante se detenga a pensar sin que haya un problema."""

GIVE_UP_V2 = 0.3
"""Probabilidad de abandonar la tarea 4 en V2, si los problemas 3 y 5 le afectaron."""

SESSION_GAP_MS = 3_600_000
"""Separación entre el inicio de dos sesiones."""


@dataclass(frozen=True)
class ParticipantPlan:
    """Lo que le pasa a un participante simulado.

    Attributes:
        index: Posición del participante (desde 1); fija su semilla y su hora.
        participant_id: Código anónimo.
        version: Versión que usa.
        exposed: Problemas de su versión: pasa por todos.
        affected: Problemas que le afectan: los que producen un patrón observable.
        false_alarm: Si se detiene a pensar en la tarea 1 sin que haya un problema.
        gave_up: Si abandona la tarea 4.
        sus_answers: Respuestas del SUS.
        error_deg: Error de la calibración inicial.
    """

    index: int
    participant_id: str
    version: str
    exposed: tuple[int, ...]
    affected: tuple[int, ...]
    false_alarm: bool
    gave_up: bool
    sus_answers: tuple[int, ...]
    error_deg: float


def plan_experiment(
    per_version: int,
    *,
    seed: int = 7,
    affected: float = DEFAULT_AFFECTED,
    false_alarm: float = DEFAULT_FALSE_ALARM,
) -> list[ParticipantPlan]:
    """Reparte participantes entre las versiones y decide qué le pasa a cada uno.

    La asignación es balanceada y en orden aleatorio, como en el experimento.

    Args:
        per_version: Participantes por versión.
        seed: Semilla: la misma da el mismo experimento.
        affected: Probabilidad de que un problema afecte a un participante.
        false_alarm: Probabilidad de una pausa sin problema.

    Returns:
        Un plan por participante, en orden de sesión.

    Raises:
        ValueError: Si ``per_version`` no es positivo o una probabilidad no está entre 0 y 1.
    """
    if per_version < 1:
        raise ValueError(f"per_version must be positive, got {per_version}")
    if not (0 <= affected <= 1 and 0 <= false_alarm <= 1):
        raise ValueError("probabilities must be between 0 and 1")
    rng = random.Random(seed)
    versions = [version for version in VERSIONS for _ in range(per_version)]
    rng.shuffle(versions)
    plans = []
    for index, version in enumerate(versions, start=1):
        exposed = VERSIONS[version]
        hit = tuple(problem for problem in exposed if rng.random() < affected)
        gave_up = version == "V2" and {3, 5} <= set(hit) and rng.random() < GIVE_UP_V2
        target = min(100.0, max(0.0, rng.gauss(SUS_MEAN[version], SUS_SPREAD)))
        plans.append(
            ParticipantPlan(
                index=index,
                participant_id=f"E{index:02d}",
                version=version,
                exposed=exposed,
                affected=hit,
                false_alarm=rng.random() < false_alarm,
                gave_up=gave_up,
                sus_answers=sus_answers_for(target, rng),
                error_deg=round(rng.uniform(1.3, 2.6), 2),
            )
        )
    return plans


def sus_answers_for(score: float, rng: random.Random) -> tuple[int, ...]:
    """Respuestas del SUS cuyo puntaje queda cerca del pedido.

    Cada ítem aporta de 0 a 4 puntos (×2,5): los impares, respuesta − 1; los
    pares, 5 − respuesta. Se reparte el puntaje entre los ítems con ruido.

    Args:
        score: Puntaje buscado, de 0 a 100.
        rng: Azar.

    Returns:
        Las 10 respuestas, de 1 a 5.
    """
    per_item = score / 25
    answers = []
    for item in range(10):
        points = min(4, max(0, round(per_item + rng.gauss(0, 0.6))))
        answers.append(points + 1 if item % 2 == 0 else 5 - points)
    return tuple(answers)


def participant_session(context: StudyContext, plan: ParticipantPlan) -> SimulatedSession:
    """Sesión guiada de un participante según su plan.

    Args:
        context: Estudio cargado, con las duraciones de las referencias.
        plan: Lo que le pasa al participante.

    Returns:
        Sesión simulada con su verdad de referencia.
    """
    hit = set(plan.affected)
    builder = SessionBuilder(
        study_id=context.study_id,
        participant_id=plan.participant_id,
        version=plan.version,
        mode="guided",
        start=DEFAULT_START + plan.index * SESSION_GAP_MS,
        seed=context.seed * 1000 + plan.index,
        params=context.params,
        reference_durations=context.reference_durations,
        friction_i_max=context.params.friction_i_max or MOCK_FRICTION_I_MAX,
        gaze_hz=MOCK_GAZE_HZ,
        face_hz=MOCK_FACE_HZ,
        eyes=True,
    )
    builder.with_calibration("initial", plan.error_deg).on_screen(LOGIN)
    if 7 in hit:
        builder.with_rage_click(problem=7)
    builder.do(LOGIN_ACTION)

    builder.with_task(*_task(context, 1))
    if 8 in hit:
        builder.with_repeated_search(
            SEARCH, [results("audfonos inalambricos"), results("audifonos inlambricos")], problem=8
        )
    if plan.false_alarm:
        # Se detiene a pensar ante los resultados sin que nada falle: el detector lo verá y
        # no es un problema sembrado. Va entre dos eventos de la tarea, como lo mide el detector.
        builder.follow(1).with_long_pause()
    builder.end_task("reference")

    builder.with_task(*_task(context, 2)).follow(2)
    if 1 in hit:
        builder.with_dead_click(ZOOM_BADGE, problem=1)
    builder.follow(1)
    if 2 in hit:
        builder.with_rage_click(problem=2)
    builder.end_task("reference")

    builder.with_task(*_task(context, 3)).follow(1)
    if 4 in hit:
        builder.with_form_error(1, erases=True, problem=4)
    builder.follow(2)
    if 6 in hit:
        builder.with_form_error(0, times=2, pause=True, error_type="custom_error", problem=6)
    builder.end_task("reference")

    builder.with_task(*_task(context, 4)).follow(1)
    if 3 in hit:
        builder.with_navigation_loop(
            Click(MENU_HELP, to=HELP), Click(HELP_BACK, to=CONFIRMATION), problem=3
        )
        builder.with_long_pause(problem=3).redo(Click(MENU_MORE))
    if 5 in hit:
        builder.follow(1).with_hesitation(ADDRESS_LINK, problem=5)
    if plan.gave_up:
        builder.with_overtime().end_task("gave_up")
    else:
        builder.end_task("reference")
    final = round(plan.error_deg + 0.3, 2)
    return builder.with_calibration("final", final).with_sus(plan.sus_answers).build()


def _task(context: StudyContext, position: int) -> tuple[int, Sequence[Action]]:
    """Id y ruta de una tarea, para ``with_task``."""
    return context.task_id(position), TASKS[position - 1].path
