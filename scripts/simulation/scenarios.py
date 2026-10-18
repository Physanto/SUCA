"""Escenarios de los datos simulados: una tienda en línea y sus sesiones.

La tienda tiene las pantallas, los elementos y las rutas de las 4 tareas de
``studies/example.yaml``. Con ellos se arman las sesiones de la base simulada:

- una sesión de grabación de referencia (modo ``reference``) con las 4 tareas;
- tres sesiones guiadas, una por versión del sistema:
  - **V0:** sin problemas;
  - **V1:** 4 problemas sembrados;
  - **V2:** 8 problemas sembrados (los de V1 y 4 más), un desvío en un paso
    conocido y una tarea abandonada;
- una sesión libre con varios problemas.

Los problemas sembrados son los del catálogo ``SEEDED_PROBLEMS``; cada
incidente esperado indica de cuál viene. En las tres versiones la tienda y las
rutas son las mismas: los problemas se simulan con el comportamiento del
participante.

Las funciones de escenario reciben un ``StudyContext`` y devuelven la sesión
construida. También sirven en las pruebas: por ejemplo,
``guided_v1(context).truth`` tiene los incidentes esperados de esa sesión.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any
from urllib.parse import quote_plus

from analysis.parameters import Parameters
from scripts.simulation.builder import (
    DEFAULT_START,
    Action,
    Click,
    Element,
    FillForm,
    Screen,
    Scroll,
    SelectText,
    SessionBuilder,
    SimulatedSession,
    count_steps,
)

#: Una hora, en ms: separa el inicio de cada sesión simulada.
HOUR_MS = 3_600_000

MOCK_GAZE_HZ = 10
"""Frecuencia de la mirada en los datos simulados (la extensión usa la de la
configuración). Es menor para que la base sea pequeña y se genere rápido."""

MOCK_FACE_HZ = 5
"""Frecuencia del rostro en los datos simulados, por la misma razón."""

MOCK_FRICTION_I_MAX = 15.0
"""Normalización de la fricción (incidentes por minuto de tarea) para el índice
simulado mientras ``friction_i_max`` sea ``null`` en ``parameters.yaml``. Es un
valor provisional y alto porque las sesiones simuladas son cortas (los
incidentes por minuto suben); el real se fija con el piloto."""

SEEDED_PROBLEMS: Mapping[int, Mapping[str, Any]] = MappingProxyType(
    {
        1: {"problem": "Imagen que parece botón pero no lo es", "detectors": ["dead_click"]},
        2: {
            "problem": "Botón que tarda en responder sin indicador de carga",
            "detectors": ["rage_click"],
        },
        3: {
            "problem": "Opción importante dentro de un menú poco lógico",
            "detectors": ["navigation_loop", "long_pause"],
        },
        4: {
            "problem": "Formulario que borra los datos al mostrar un error",
            "detectors": ["form_error", "field_reentry"],
        },
        5: {"problem": "Enlace con bajo contraste", "detectors": ["hesitation", "long_pause"]},
        6: {
            "problem": "Mensaje de error ambiguo",
            "detectors": ["form_error", "field_reentry", "long_pause"],
        },
        7: {
            "problem": "Inicio de sesión lento y sin retroalimentación",
            "detectors": ["rage_click"],
        },
        8: {
            "problem": "Buscador que no tolera errores de escritura",
            "detectors": ["repeated_search"],
        },
    }
)
"""Catálogo de problemas sembrados: V1 tiene del 1 al 4; V2, del 1 al 8."""


# --- Pantallas -----------------------------------------------------------------

_SHOP = "https://shop.local"

LOGIN = Screen(f"{_SHOP}/login", "Iniciar sesión · Tienda", "/login")
HOME = Screen(f"{_SHOP}/", "Inicio · Tienda", "/")
PRODUCT = Screen(
    f"{_SHOP}/product/101", "Audífonos inalámbricos SoundMax · Tienda", "/product/{id}"
)
CART = Screen(f"{_SHOP}/cart", "Carrito · Tienda", "/cart")
SHIPPING = Screen(f"{_SHOP}/checkout/shipping", "Envío · Tienda", "/checkout/shipping")
PAYMENT = Screen(f"{_SHOP}/checkout/payment", "Pago · Tienda", "/checkout/payment")
CONFIRMATION = Screen(
    f"{_SHOP}/order/5012/confirmation", "Pedido confirmado · Tienda", "/order/{id}/confirmation"
)
HELP = Screen(f"{_SHOP}/help", "Ayuda · Tienda", "/help")
ACCOUNT = Screen(f"{_SHOP}/account", "Mi cuenta · Tienda", "/account")
ADDRESS = Screen(f"{_SHOP}/account/address", "Dirección de envío · Tienda", "/account/address")
OFFERS = Screen(f"{_SHOP}/offers", "Ofertas · Tienda", "/offers")


def results(query: str) -> Screen:
    """Pantalla de resultados de una búsqueda.

    Args:
        query: Texto buscado.

    Returns:
        Pantalla ``/search`` con la consulta en la URL.
    """
    return Screen(f"{_SHOP}/search?q={quote_plus(query)}", "Resultados · Tienda", "/search")


# --- Elementos -----------------------------------------------------------------
# Rectángulos en una ventana de 1280 × 800: encabezado arriba (y < 64), menú de
# navegación (64–104), contenido, columna lateral a la derecha y pie abajo.


def _input(id: str, role: str | None, box: tuple[float, float, float, float]) -> Element:
    """Campo de formulario: su texto nunca se captura."""
    return Element("input", id, role, None, f"#{id}", box)


def _form(id: str, role: str, box: tuple[float, float, float, float]) -> Element:
    """Formulario: elemento del envío, no interactivo."""
    return Element("form", id, role, None, f"#{id}", box, interactive=False)


SEARCH_FORM = _form("search", "search", (480, 12, 420, 40))
SEARCH_INPUT = _input("q", "searchbox", (484, 16, 320, 32))
SEARCH_BUTTON = Element("button", "search-go", "button", "Buscar", "#search-go", (812, 16, 84, 32))
MENU_MORE = Element("button", "menu-more", "button", "Más", "#menu-more", (1090, 16, 64, 32))
MENU_HELP = Element("a", "menu-help", "menuitem", "Ayuda", "#menu-help", (1040, 56, 180, 32))
MENU_ACCOUNT = Element(
    "a", "menu-account", "menuitem", "Mi cuenta", "#menu-account", (1040, 88, 180, 32)
)
CART_LINK = Element("a", "cart-link", "link", "Carrito", "#cart-link", (1180, 16, 80, 32))
NAV_HOME = Element("a", "nav-home", "link", "Inicio", "#nav-home", (40, 72, 80, 24))
NAV_OFFERS = Element("a", "nav-offers", "link", "Ofertas", "#nav-offers", (140, 72, 80, 24))

LOGIN_FORM = _form("login-form", "form", (440, 200, 400, 300))
LOGIN_USER = _input("user", "textbox", (460, 260, 360, 36))
LOGIN_PASSWORD = _input("password", None, (460, 330, 360, 36))
LOGIN_SUBMIT = Element(
    "button", "login-submit", "button", "Entrar", "#login-submit", (460, 400, 120, 40)
)

RESULT_1 = Element(
    "a",
    None,
    "link",
    "Audífonos inalámbricos SoundMax",
    "#results > li:nth-of-type(1) > a",
    (80, 180, 420, 28),
)

QTY_PLUS = Element("button", "qty-plus", "button", "+", "#qty-plus", (720, 360, 36, 36))
ADD_TO_CART = Element(
    "button", "add-to-cart", "button", "Agregar al carrito", "#add-to-cart", (720, 420, 220, 44)
)
#: Problema 1: una imagen con forma de botón que no hace nada.
ZOOM_BADGE = Element(
    "img", "zoom-badge", None, None, "#zoom-badge", (420, 520, 120, 40), interactive=False
)

CHECKOUT = Element("button", "checkout", "button", "Comprar", "#checkout", (860, 560, 160, 44))

SHIP_FORM = _form("shipping", "form", (120, 140, 640, 460))
SHIP_NAME = _input("ship-name", "textbox", (140, 190, 400, 36))
SHIP_ADDRESS = _input("ship-address", "textbox", (140, 260, 400, 36))
SHIP_CITY = _input("ship-city", "textbox", (140, 330, 400, 36))
SHIP_SUBMIT = Element(
    "button", "ship-continue", "button", "Continuar", "#ship-continue", (140, 420, 160, 44)
)

PAY_CARD = _input("pay-card", "radio", (140, 180, 20, 20))
PAY_TRANSFER = _input("pay-transfer", "radio", (140, 220, 20, 20))
PAY_FORM = _form("payment", "form", (120, 260, 640, 360))
CARD_NUMBER = _input("card-number", "textbox", (140, 290, 400, 36))
CARD_EXPIRY = _input("card-expiry", "textbox", (140, 360, 180, 36))
CARD_CVC = _input("card-cvc", "textbox", (340, 360, 120, 36))
PAY_SUBMIT = Element("button", "pay", "button", "Pagar", "#pay", (140, 440, 160, 44))

HELP_BACK = Element("a", "help-back", "link", "Volver", "#help-back", (40, 120, 80, 24))

#: Problema 5: enlace de bajo contraste.
ADDRESS_LINK = Element(
    "a", "address-link", "link", "Dirección de envío", "#address-link", (140, 220, 200, 24)
)
ADDRESS_FORM = _form("address-form", "form", (120, 160, 640, 300))
ADDRESS_FIELD = _input("address", "textbox", (140, 200, 480, 36))
ADDRESS_SAVE = Element(
    "button", "address-save", "button", "Guardar", "#address-save", (140, 270, 140, 44)
)

NEWSLETTER_FORM = _form("newsletter", "form", (40, 748, 600, 44))
NEWSLETTER_EMAIL = _input("newsletter-email", "textbox", (60, 752, 300, 36))
NEWSLETTER_SUBMIT = Element(
    "button", "newsletter-go", "button", "Suscribirme", "#newsletter-go", (370, 752, 140, 36)
)


# --- Acciones y tareas ----------------------------------------------------------

LOGIN_ACTION = FillForm(
    LOGIN_FORM, (LOGIN_USER, LOGIN_PASSWORD), LOGIN_SUBMIT, to=HOME, kind="login"
)
SEARCH = FillForm(
    SEARCH_FORM, (SEARCH_INPUT,), SEARCH_BUTTON, to=results("audifonos inalambricos"), kind="search"
)
NEWSLETTER = FillForm(NEWSLETTER_FORM, (NEWSLETTER_EMAIL,), NEWSLETTER_SUBMIT)


@dataclass(frozen=True)
class TaskSpec:
    """Una tarea del estudio de ejemplo con su ruta y su referencia.

    Attributes:
        position: Posición de la tarea en ``studies/example.yaml``.
        path: Acciones de la ruta correcta.
        end_condition: Condición final confirmada.
        candidates: Condiciones finales que propondría el análisis.
    """

    position: int
    path: tuple[Action, ...]
    end_condition: Mapping[str, str]
    candidates: tuple[Mapping[str, str], ...]


TASKS: tuple[TaskSpec, ...] = (
    TaskSpec(
        1,
        (SEARCH, Click(RESULT_1, to=PRODUCT)),
        {"type": "url_pattern", "pattern": "/product/{id}"},
        ({"type": "visible_text", "text": "Audífonos inalámbricos SoundMax"},),
    ),
    TaskSpec(
        2,
        (Scroll(220), SelectText(48), Click(QTY_PLUS), Click(ADD_TO_CART, to=CART)),
        {"type": "element_present", "text": "Audífonos inalámbricos SoundMax × 2", "role": "row"},
        ({"type": "url_pattern", "pattern": "/cart"},),
    ),
    TaskSpec(
        3,
        (
            Click(CHECKOUT, to=SHIPPING),
            FillForm(SHIP_FORM, (SHIP_NAME, SHIP_ADDRESS, SHIP_CITY), SHIP_SUBMIT, to=PAYMENT),
            Click(PAY_CARD, required=True),
            FillForm(
                PAY_FORM,
                (CARD_NUMBER, CARD_EXPIRY, CARD_CVC),
                PAY_SUBMIT,
                to=CONFIRMATION,
                required=True,
            ),
        ),
        {"type": "visible_text", "text": "Pedido confirmado"},
        ({"type": "url_pattern", "pattern": "/order/{id}/confirmation"},),
    ),
    TaskSpec(
        4,
        (
            Click(MENU_MORE),
            Click(MENU_ACCOUNT, to=ACCOUNT),
            Click(ADDRESS_LINK, to=ADDRESS),
            FillForm(ADDRESS_FORM, (ADDRESS_FIELD,), ADDRESS_SAVE, required=True),
        ),
        {"type": "visible_text", "text": "Dirección actualizada"},
        ({"type": "url_pattern", "pattern": "/account/address"},),
    ),
)
"""Las 4 tareas del estudio de ejemplo, en orden."""


# --- Contexto y sesiones --------------------------------------------------------


@dataclass(frozen=True)
class StudyContext:
    """Lo que necesitan los escenarios del estudio cargado en la base.

    Attributes:
        study_id: Estudio de ejemplo.
        task_ids: Id de cada tarea, en orden de posición.
        params: Parámetros del análisis.
        seed: Semilla base; cada sesión usa una derivada.
        reference_durations: Duración de la referencia de cada tarea, por id;
            vacía hasta grabar la sesión de referencia.
    """

    study_id: int
    task_ids: tuple[int, ...]
    params: Parameters
    seed: int = 7
    reference_durations: Mapping[int, float] = field(default_factory=dict)

    def task_id(self, position: int) -> int:
        """Devuelve el id de la tarea de una posición (desde 1)."""
        return self.task_ids[position - 1]


def _builder(context: StudyContext, index: int, **options: Any) -> SessionBuilder:
    """Constructor de la sesión número ``index`` de los datos simulados."""
    i_max = context.params.friction_i_max or MOCK_FRICTION_I_MAX
    return SessionBuilder(
        study_id=context.study_id,
        start=DEFAULT_START + index * HOUR_MS,
        seed=context.seed * 100 + index,
        params=context.params,
        reference_durations=context.reference_durations,
        friction_i_max=i_max,
        gaze_hz=MOCK_GAZE_HZ,
        face_hz=MOCK_FACE_HZ,
        **options,
    )


def _task(context: StudyContext, position: int) -> tuple[int, tuple[Action, ...]]:
    """Id y ruta de una tarea, para ``with_task``."""
    return context.task_id(position), TASKS[position - 1].path


def reference_recording(context: StudyContext) -> SimulatedSession:
    """El evaluador graba la ruta correcta de las 4 tareas (modo ``reference``).

    Args:
        context: Estudio cargado.

    Returns:
        Sesión con una grabación por tarea en ``references``.
    """
    builder = _builder(context, 0, participant_id="REF01", mode="reference").on_screen(LOGIN)
    builder.do(LOGIN_ACTION)
    for spec in TASKS:
        builder.with_task(*_task(context, spec.position)).follow().end_task("done")
    return builder.build()


def guided_v0(context: StudyContext) -> SimulatedSession:
    """Sesión guiada en V0: las 4 tareas por la ruta correcta, sin incidentes.

    Args:
        context: Estudio cargado, con las duraciones de las referencias.

    Returns:
        Sesión simulada.
    """
    builder = (
        _builder(context, 1, participant_id="P01", version="V0", mode="guided")
        .with_calibration("initial", 1.6)
        .on_screen(LOGIN)
        .do(LOGIN_ACTION)
    )
    for spec in TASKS:
        builder.with_task(*_task(context, spec.position)).end_task("reference")
    return builder.with_calibration("final", 1.9).with_sus([5, 1, 5, 1, 4, 2, 5, 1, 5, 2]).build()


def _task_2_with_problems_1_and_2(builder: SessionBuilder, context: StudyContext) -> None:
    """Tarea 2 con la imagen que parece botón (1) y el botón lento (2)."""
    (
        builder.with_task(*_task(context, 2))
        .follow(2)
        .with_dead_click(ZOOM_BADGE, problem=1)
        .follow(1)
        .with_rage_click(problem=2)
        .end_task("reference")
    )


def _task_4_lost_in_the_menu(builder: SessionBuilder, context: StudyContext) -> SessionBuilder:
    """Inicio de la tarea 4: abre el menú, entra a Ayuda, vuelve y se queda pensando (3)."""
    return (
        builder.with_task(*_task(context, 4))
        .follow(1)
        .with_navigation_loop(
            Click(MENU_HELP, to=HELP), Click(HELP_BACK, to=CONFIRMATION), problem=3
        )
        .with_long_pause(problem=3)
        .redo(Click(MENU_MORE))
    )


def guided_v1(context: StudyContext) -> SimulatedSession:
    """Sesión guiada en V1, con los problemas 1 a 4. Completa las 4 tareas.

    Args:
        context: Estudio cargado, con las duraciones de las referencias.

    Returns:
        Sesión simulada.
    """
    builder = (
        _builder(context, 2, participant_id="P02", version="V1", mode="guided")
        .with_calibration("initial", 1.8)
        .on_screen(LOGIN)
        .do(LOGIN_ACTION)
    )
    builder.with_task(*_task(context, 1)).end_task("reference")
    _task_2_with_problems_1_and_2(builder, context)
    (
        builder.with_task(*_task(context, 3))
        .follow(1)
        .with_form_error(1, erases=True, problem=4)
        .end_task("reference")
    )
    _task_4_lost_in_the_menu(builder, context).end_task("reference")
    return builder.with_calibration("final", 2.1).with_sus([4, 2, 4, 2, 3, 3, 4, 2, 4, 3]).build()


def guided_v2(context: StudyContext) -> SimulatedSession:
    """Sesión guiada en V2, con los problemas 1 a 8.

    Además se desvía en un paso conocido de la tarea 3 (elige transferencia
    antes que tarjeta) y abandona la tarea 4 después de perderse en el menú.

    Args:
        context: Estudio cargado, con las duraciones de las referencias.

    Returns:
        Sesión simulada.
    """
    builder = (
        _builder(context, 3, participant_id="P03", version="V2", mode="guided")
        .with_calibration("initial", 2.2)
        .on_screen(LOGIN)
        .with_rage_click(problem=7)
        .do(LOGIN_ACTION)
    )
    (
        builder.with_task(*_task(context, 1))
        .with_repeated_search(
            SEARCH, [results("audfonos inalambricos"), results("audifonos inlambricos")], problem=8
        )
        .end_task("reference")
    )
    _task_2_with_problems_1_and_2(builder, context)
    path_3 = TASKS[2].path
    (
        builder.with_task(*_task(context, 3))
        .follow(1)
        .with_form_error(1, erases=True, problem=4)
        .with_deviation_at_step(count_steps(path_3[:2]), wrong=Click(PAY_TRANSFER))
        .with_form_error(0, times=2, pause=True, error_type="custom_error", problem=6)
        .end_task("reference")
    )
    (
        _task_4_lost_in_the_menu(builder, context)
        .follow(1)
        .with_hesitation(ADDRESS_LINK, problem=5)
        .with_overtime()
        .end_task("gave_up")
    )
    return builder.with_calibration("final", 2.6).with_sus([3, 4, 2, 4, 2, 4, 3, 3, 2, 4]).build()


def free_v1(context: StudyContext) -> SimulatedSession:
    """Sesión libre en V1: navega la tienda y encuentra varios problemas.

    Busca con errores de escritura (8), hace clic en la imagen que parece botón
    (1), insiste en el botón lento (2), va y vuelve de Ofertas, se queda
    pensando y abandona el formulario del boletín.

    Args:
        context: Estudio cargado.

    Returns:
        Sesión simulada.
    """
    return (
        _builder(context, 4, participant_id="P04", version="V1", mode="free")
        .with_calibration("initial", 1.7)
        .on_screen(HOME)
        .with_repeated_search(
            SEARCH, [results("audfonos"), results("audifonos inlambricos")], problem=8
        )
        .do(SEARCH, Click(RESULT_1, to=PRODUCT))
        .with_dead_click(ZOOM_BADGE, problem=1)
        .with_rage_click(ADD_TO_CART, problem=2)
        .do(Click(CART_LINK, to=CART))
        .with_navigation_loop(Click(NAV_OFFERS, to=OFFERS), Click(CART_LINK, to=CART))
        .with_long_pause()
        .with_form_abandonment(NEWSLETTER, leave=Click(NAV_HOME, to=HOME))
        .with_calibration("final", 2.0)
        .build()
    )


PARTICIPANT_SCENARIOS: tuple[tuple[str, Callable[[StudyContext], SimulatedSession]], ...] = (
    ("guided_v0", guided_v0),
    ("guided_v1", guided_v1),
    ("guided_v2", guided_v2),
    ("free_v1", free_v1),
)
"""Sesiones de participantes de la base simulada, con su nombre en la verdad de referencia."""
