# Evaluación del experimento

Responde las preguntas de validación del proyecto sobre una base **ya analizada** (`python -m analysis.run --study ID`). Solo lee la base.

| Pregunta | Qué calcula |
|---|---|
| **P1** · ¿El IUC distingue las versiones? | IUC por versión (descriptiva), Shapiro-Wilk por versión, ANOVA (eta²) y Kruskal-Wallis (épsilon²), tendencia V0 > V1 > V2 con Jonckheere-Terpstra (valor p por permutaciones) y consistencia por mitades de las tareas (impares frente a pares, con Spearman-Brown) |
| **P2** · ¿Qué relación hay entre IUC y SUS? | Spearman en total y por versión; casos discrepantes: sesiones cuyos rangos percentiles de IUC y SUS se separan 0,5 o más |
| **P3** · ¿Los detectores encuentran los problemas sembrados? | Por problema, las sesiones expuestas y en cuántas se detectó; falsas alarmas por versión y tipo; precisión en las versiones con problemas. Con la verdad de un experimento simulado, la sensibilidad |
| **P4** · ¿Acierta la referencia en el éxito y el desvío? | Acuerdo y kappa de Cohen entre lo automático y la codificación manual |

Además: éxito, duración, pasos y desvíos de cada tarea por versión. Los umbrales de éxito **no** se deciden aquí: se fijan antes del experimento.

## Uso

Requiere scipy: `pip install -r requirements-ml.txt`.

```bash
python -m scripts.evaluate_study --study 1 --friction-i-max 15 \
    --catalog studies/example-problems.yaml --output data/evaluation
```

- `--friction-i-max`: la normalización de la fricción del IUC. Mientras `friction_i_max` sea `null` en `analysis/parameters.yaml` (se fija con el piloto), el análisis no guarda el índice y hay que darla aquí. La evaluación **recalcula** el IUC de todas las sesiones con la misma función del análisis y un único valor.
- `--catalog`: los problemas sembrados (P3). Sin él, se omite P3.
- `--truth`: la verdad de un experimento simulado (`<base>_ground_truth.json`), para medir la sensibilidad.
- `--coding`: la codificación manual completada (P4).
- `--output`: escribe `summary.json` y una tabla CSV por resultado (`indexes.csv`, `detection_by_problem.csv`, `false_alarms.csv`…).
- `--db`: otra base; por defecto, `database.path`.

### Catálogo de problemas sembrados

Un YAML como `studies/example-problems.yaml`: por problema, las versiones en que está activo, la tarea donde ocurre (posición, o `null` si es fuera de las tareas), las pantallas (vacío = cualquiera) y los tipos de incidente que deberían detectarlo. Un incidente **detecta** un problema si coinciden el tipo, la tarea y la pantalla. Un problema está **expuesto** en una sesión si está activo en su versión y la sesión hizo esa tarea.

Cuando dos problemas activos comparten tarea y detectores (en la tienda, el 4 y el 6 en el pago; el 3 y el 5 en la cuenta), un mismo incidente cuenta para ambos: el informe lo advierte.

Un incidente que no explica ningún problema activo es una **falsa alarma** respecto del catálogo. Puede ser una dificultad real que el catálogo no prevé: conviene revisarla en la reproducción (`unmatched_by_type.csv`).

### Codificación manual (P4)

```bash
python -m scripts.evaluate_study --study 1 --coding-template data/coding.csv
```

La plantilla trae una fila por sesión y tarea con lo automático (`auto_success`, `auto_deviation_step`). El evaluador revisa una muestra en la reproducción y completa:

- `manual_success`: `1` si se logró, `0` si no;
- `manual_deviation_step`: el paso (desde 0) del primer desvío, o `none` si no se desvió.

Las filas vacías no se cuentan. Luego:

```bash
python -m scripts.evaluate_study --study 1 --friction-i-max 15 --coding data/coding.csv
```

## Probar con un experimento simulado

```bash
python -m scripts.simulate_experiment --db data/experiment.db
python -m analysis.run --db data/experiment.db --study 1
python -m scripts.evaluate_study --db data/experiment.db --study 1 --friction-i-max 15 \
    --catalog studies/example-problems.yaml --truth data/experiment_ground_truth.json
```

## Archivos

| Archivo | Qué hace |
|---|---|
| `shared/problems.py` | Lee y valida el catálogo de problemas sembrados (lo usa también el modelo de aprendizaje automático) |
| `repository.py` | Lee los resultados de las sesiones guiadas cerradas |
| `index.py` | IUC de cada sesión, completo y por mitades, con `analysis.usability_index` |
| `statistics.py` | Pruebas estadísticas y acuerdo |
| `detection.py` | Detección de problemas y falsas alarmas (P3) |
| `agreement.py` | Plantilla y acuerdo de la codificación manual (P4) |
| `report.py` | Junta todo, escribe el JSON y las tablas e imprime el informe |

## Pendiente

- Modelos de efectos mixtos por tarea (participante como efecto aleatorio): el diseño entre sujetos con 4 tareas los permite, pero requieren una dependencia más (statsmodels). Mientras tanto, `tasks_by_version.csv` da lo descriptivo por tarea.
