"""Regresión logística con una persona fuera y comparación de grupos de señales.

El escalado y el entrenamiento se ajustan exclusivamente en las otras personas.
Las etiquetas proceden de reglas y tareas fallidas; su acierto mide concordancia
con esas etiquetas, nunca reconocimiento de emociones ni validación clínica.
"""

from typing import Any

import numpy as np
import pandas as pd

from analysis.ml.windows import FACIAL_FEATURES, GAZE_FEATURES, INTERACTION_FEATURES


def evaluate_models(windows: pd.DataFrame) -> dict[str, Any]:
    """Compara interacción, interacción+mirada y todas las señales en las mismas filas.

    Args:
        windows: Dataset de build_windows, con identidad anónima y etiqueta débil.

    Returns:
        Métricas por persona y variante, predicciones fuera de muestra, cantidad
        de ventanas excluidas y coeficientes del ajuste de cada pliegue.

    Raises:
        ValueError: Si faltan tres personas o ambas clases en algún entrenamiento.
        RuntimeError: Si no está instalada la dependencia opcional scikit-learn.
    """
    try:
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import balanced_accuracy_score, brier_score_loss
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
    except ImportError as error:
        raise RuntimeError("install requirements-ml.txt to train the facial comparison") from error
    variants = {
        "interaction": INTERACTION_FEATURES,
        "interaction_gaze": (*INTERACTION_FEATURES, *GAZE_FEATURES),
        "all_signals": (*INTERACTION_FEATURES, *GAZE_FEATURES, *FACIAL_FEATURES),
    }
    features = variants["all_signals"]
    valid = windows["valid"].fillna(False) & np.isfinite(windows[list(features)]).all(axis=1)
    dataset = windows[valid].copy()
    people = dataset["participant_id"].unique()
    if len(people) < 3:
        raise ValueError("at least three participants with complete windows are required")
    if not dataset["label"].isin([0, 1]).all():
        raise ValueError("labels must be binary")
    scores, predictions, coefficients = [], [], []
    for person in people:
        test = dataset[dataset["participant_id"] == person]
        train = dataset[dataset["participant_id"] != person]
        if train["label"].nunique() < 2:
            raise ValueError(f"training without participant {person} has only one class")
        for variant, names in variants.items():
            model = make_pipeline(
                StandardScaler(),
                LogisticRegression(class_weight="balanced", max_iter=1000, random_state=0),
            )
            model.fit(train[list(names)], train["label"].astype(int))
            probability = model.predict_proba(test[list(names)])[:, 1]
            prediction = (probability >= 0.5).astype(int)
            scores.append(
                {
                    "participant_id": str(person),
                    "variant": variant,
                    "windows": len(test),
                    "balanced_accuracy": float(balanced_accuracy_score(test["label"], prediction))
                    if test["label"].nunique() == 2
                    else None,
                    "brier": float(brier_score_loss(test["label"], probability)),
                    "train_participants": [str(p) for p in train["participant_id"].unique()],
                }
            )
            for row, p in zip(test.itertuples(), probability, strict=True):
                predictions.append(
                    {
                        "participant_id": str(person),
                        "session_id": int(row.session_id),
                        "t_start": float(row.t_start),
                        "variant": variant,
                        "label": int(row.label),
                        "probability": float(p),
                    }
                )
            coefficient = model.named_steps["logisticregression"].coef_[0]
            coefficients.append(
                {
                    "participant_id": str(person),
                    "variant": variant,
                    "coefficients": dict(zip(names, map(float, coefficient), strict=True)),
                }
            )
    return {
        "label_source": "weak_incident_or_failed_task_end",
        "participants": len(people),
        "windows": len(dataset),
        "excluded_windows": int((~valid).sum()),
        "scores": scores,
        "predictions": predictions,
        "coefficients": coefficients,
    }
