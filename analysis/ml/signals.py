"""Modelos que reconocen ventanas con problemas sembrados y qué señales aportan (P5).

Compara, con validación **dejando un participante fuera** (nunca se mezclan
ventanas de una persona entre entrenamiento y prueba):

1. **Modelo frente a reglas:** cada modelo frente a "algún detector informó un
   incidente en la ventana", sobre las mismas ventanas y etiquetas.
2. **Señales:** solo interacción, interacción + mirada e interacción + mirada +
   rostro, con las mismas filas en las tres variantes.
3. **Importancia de variables** por permutación en cada participante de prueba.

Modelos: random forest y gradient boosting (``HistGradientBoostingClassifier``),
ambos con pesos por clase. scikit-learn es una dependencia opcional
(``requirements-ml.txt``). Las etiquetas vienen del diseño del experimento
(``analysis/ml/labels.py``), no de los detectores.
"""

from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd

from analysis.ml.features import FACE_FEATURES, GAZE_FEATURES, INTERACTION_FEATURES

VARIANTS: dict[str, tuple[str, ...]] = {
    "interaction": INTERACTION_FEATURES,
    "interaction_gaze": (*INTERACTION_FEATURES, *GAZE_FEATURES),
    "all_signals": (*INTERACTION_FEATURES, *GAZE_FEATURES, *FACE_FEATURES),
}
"""Grupos de rasgos que se comparan."""

MODELS = ("random_forest", "gradient_boosting")
"""Modelos del plan del proyecto."""

MIN_PARTICIPANTS = 3
"""Participantes mínimos: cada entrenamiento necesita al menos dos personas."""


def _sklearn() -> Any:
    """Importa scikit-learn o explica cómo instalarlo."""
    try:
        import sklearn
        from sklearn import ensemble, inspection, metrics
    except ImportError as error:
        raise RuntimeError("install requirements-ml.txt to train the models") from error
    return sklearn, ensemble, inspection, metrics


def make_model(name: str, seed: int = 0) -> Any:
    """Crea un modelo sin entrenar.

    Args:
        name: ``random_forest`` o ``gradient_boosting``.
        seed: Semilla.

    Returns:
        Clasificador de scikit-learn con pesos por clase.

    Raises:
        ValueError: Si el modelo no existe.
    """
    _, ensemble, _, _ = _sklearn()
    if name == "random_forest":
        return ensemble.RandomForestClassifier(
            n_estimators=300,
            min_samples_leaf=3,
            class_weight="balanced",
            random_state=seed,
            n_jobs=-1,
        )
    if name == "gradient_boosting":
        return ensemble.HistGradientBoostingClassifier(
            max_iter=200, learning_rate=0.05, class_weight="balanced", random_state=seed
        )
    raise ValueError(f"unknown model {name!r}; expected one of {MODELS}")


def scores(
    labels: Sequence[int], predicted: Sequence[int], probability: Sequence[float] | None
) -> dict[str, float | None]:
    """Medidas de una clasificación binaria.

    Args:
        labels: Etiquetas verdaderas.
        predicted: Predicción (0 o 1).
        probability: Probabilidad de la clase 1, o ``None`` (las reglas no dan probabilidad).

    Returns:
        ``balanced_accuracy``, ``precision``, ``recall``, ``f1`` y, con
        probabilidades y ambas clases, ``roc_auc`` y ``average_precision``.
    """
    _, _, _, metrics = _sklearn()
    y, p = np.asarray(labels, int), np.asarray(predicted, int)
    both = len(set(y)) == 2
    result: dict[str, float | None] = {
        "balanced_accuracy": float(metrics.balanced_accuracy_score(y, p)) if both else None,
        "precision": float(metrics.precision_score(y, p, zero_division=0)),
        "recall": float(metrics.recall_score(y, p, zero_division=0)),
        "f1": float(metrics.f1_score(y, p, zero_division=0)),
        "roc_auc": None,
        "average_precision": None,
    }
    if probability is not None and both:
        result["roc_auc"] = float(metrics.roc_auc_score(y, probability))
        result["average_precision"] = float(metrics.average_precision_score(y, probability))
    return result


def compare_signals(
    windows: pd.DataFrame,
    *,
    models: Sequence[str] = MODELS,
    seed: int = 0,
    importance_repeats: int = 5,
) -> dict[str, Any]:
    """Compara modelos, reglas y señales con un participante fuera.

    Args:
        windows: Ventanas con rasgos, ``label``, ``rules`` y ``participant_id``.
        models: Modelos que se entrenan.
        seed: Semilla de los modelos y de las permutaciones.
        importance_repeats: Repeticiones de la importancia por permutación.

    Returns:
        ``rows`` (ventanas usadas), ``excluded`` (sin todos los rasgos),
        ``participants``, ``positive_share``, ``rules`` (medidas de las reglas),
        ``models`` (medidas de cada modelo y variante), ``importance`` (por
        modelo, de la variante con todas las señales) e ``importance_by_signal``.

    Raises:
        ValueError: Si hay menos de 3 participantes o un entrenamiento sin las dos clases.
    """
    _, _, inspection, _ = _sklearn()
    every = list(VARIANTS["all_signals"])
    complete = windows[every].notna().all(axis=1)
    data = windows[complete].reset_index(drop=True)
    people = sorted(data["participant_id"].unique())
    if len(people) < MIN_PARTICIPANTS:
        raise ValueError(
            f"at least {MIN_PARTICIPANTS} participants with complete windows are required"
        )
    labels = data["label"].astype(int).to_numpy()
    folds = [np.flatnonzero(data["participant_id"].to_numpy() == person) for person in people]
    for test in folds:
        train = np.setdiff1d(np.arange(len(data)), test)
        if len(set(labels[train])) < 2:
            raise ValueError("a training fold has only one class; more participants are needed")

    results: dict[str, Any] = {}
    importance: dict[str, dict[str, float]] = {}
    for model_name in models:
        results[model_name] = {}
        for variant, names in VARIANTS.items():
            probability = np.zeros(len(data))
            gains: list[np.ndarray] = []
            for test in folds:
                train = np.setdiff1d(np.arange(len(data)), test)
                model = make_model(model_name, seed)
                model.fit(data.loc[train, list(names)], labels[train])
                probability[test] = model.predict_proba(data.loc[test, list(names)])[:, 1]
                if variant == "all_signals" and len(set(labels[test])) == 2:
                    permuted = inspection.permutation_importance(
                        model,
                        data.loc[test, list(names)],
                        labels[test],
                        scoring="balanced_accuracy",
                        n_repeats=importance_repeats,
                        random_state=seed,
                    )
                    gains.append(permuted.importances_mean)
            results[model_name][variant] = scores(
                labels, (probability >= 0.5).astype(int), probability
            )
            if gains:
                importance[model_name] = dict(
                    zip(names, map(float, np.mean(gains, axis=0)), strict=True)
                )
    by_signal = {
        model_name: {
            signal: float(sum(values.get(name, 0.0) for name in names))
            for signal, names in (
                ("interaction", INTERACTION_FEATURES),
                ("gaze", GAZE_FEATURES),
                ("face", FACE_FEATURES),
            )
        }
        for model_name, values in importance.items()
    }
    return {
        "label_source": "seeded_problem_location",
        "rows": len(data),
        "excluded": int((~complete).sum()),
        "participants": len(people),
        "positive_share": float(labels.mean()),
        "rules": scores(labels, data["rules"].astype(int).to_numpy(), None),
        "models": results,
        "importance": importance,
        "importance_by_signal": by_signal,
    }
