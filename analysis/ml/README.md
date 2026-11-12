# Modelo de ventanas, movimientos faciales y comparación de señales

El módulo tiene dos partes:

1. **El modelo del proyecto** (pregunta P5): ventanas de 5 s etiquetadas por
   los problemas sembrados, random forest y gradient boosting, comparación con
   las reglas y entre señales, e importancia de variables. Es la sección
   "Modelo de ventanas de 5 s" más abajo.
2. **Movimientos faciales** relativos a una línea base neutra (lo que sigue),
   que el modelo usa como rasgos y que el panel muestra junto a los incidentes.
   La comparación con **etiquetas débiles** de `windows.py` y `model.py` fue un
   paso previo; el modelo del proyecto la reemplaza para responder P5.


Este módulo prepara ventanas de 2 s relativas a una línea base neutra de cada
persona. No infiere emociones. La calibración inicial registra 10 s mirando el
centro con el rostro relajado, marcados como `neutral_baseline` en `gaze_target`
(contratos 1.7.0). No se usa ese tramo para entrenar o evaluar la mirada.

`facial.py` extrae descenso de cejas, elevación interna de cejas, presión de
labios, entrecerrar los ojos y cierre de párpados como diferencias respecto de
las medianas neutras. Cuenta transiciones de cierre para la tasa de parpadeo.
Excluye pose absoluta de más de 20°, ventanas con menos de 80 % de muestras
útiles y huecos de más de 250 ms. La línea base requiere 80 muestras útiles y
8 s cubiertos. Estas definiciones iniciales están versionadas como `facial-1`;
son umbrales de desarrollo que requieren revisión con datos reales.

`windows.py` combina tasas de interacción, mirada y movimientos faciales. Solo
etiqueta como 1 las ventanas con incidente o final de tarea fallida. Son
**etiquetas débiles**: medir concordancia con reglas no demuestra por sí solo
que el modelo reconozca dificultades reales. Las demás ventanas son controles
provisionales. Se excluyen calibraciones, ventanas finales incompletas y datos
sin línea base marcada; nunca se inventa una para sesiones antiguas.

```bash
python -m analysis.run --study ID
python -m scripts.facial_bench --study ID --output data/facial-ID
# Dependencias opcionales, para después de recoger suficientes participantes:
pip install -r requirements-ml.txt
python -m scripts.facial_bench --study ID --output data/facial-ID --train
```

Los CSV y JSON contienen datos locales; deben conservarse dentro de `data/`.
No se escribe en la base ni se añade un clasificador al flujo del participante.

`model.py` compara interacción, interacción+mirada y todas las señales con
regresión logística y una persona fuera. Usa las mismas ventanas completas en
las tres variantes. El escalado se ajusta solo con las personas de entrenamiento,
incluidas todas sus sesiones. Requiere al menos tres personas y dos clases en
cada entrenamiento; con una sola clase de prueba omite la exactitud equilibrada.
Informa puntuación de Brier, predicciones fuera de muestra y coeficientes. No hay
búsqueda de hiperparámetros sobre la persona dejada fuera.

Hallazgos compara movimientos junto a incidentes con ventanas a más de 5 s de
todos ellos, dentro de la misma sesión. La ausencia de línea base o de controles
se muestra como dato faltante.

## Modelo de ventanas de 5 s (P5)

| Archivo | Qué hace |
|---|---|
| `features.py` | Rasgos de cada ventana de 5 s: interacción, mirada y rostro. Ninguno usa los incidentes de los detectores |
| `labels.py` | Etiqueta: 1 si la persona estaba en la tarea y la pantalla de un problema sembrado activo en su versión, según el catálogo (`shared/problems.py`). Las mismas tareas y pantallas en una versión sin el problema valen 0 |
| `signals.py` | Random forest y gradient boosting con un participante fuera; reglas como base de comparación; variantes solo interacción, interacción + mirada y todas las señales; importancia por permutación |

```bash
python -m analysis.run --study ID
pip install -r requirements-ml.txt
python -m scripts.ml_experiment --study ID --catalog studies/example-problems.yaml --output data/ml-ID
```

- **Ventanas:** desde el fin de la calibración inicial, una tras otra; se
  descartan las que se cruzan con otro procedimiento de la cámara.
- **Etiquetas del diseño, no de las reglas:** la comparación "modelo frente a
  reglas" no es circular. Las reglas se miden como "algún incidente en la
  ventana", sobre las mismas ventanas y etiquetas.
- **Mismas filas en todas las variantes:** se usan solo las ventanas con todos
  los rasgos (con mirada y con línea base facial); el informe dice cuántas quedan fuera.
- **Medidas fuera de muestra**, juntando las predicciones de todos los
  participantes dejados fuera: exactitud equilibrada, precisión, sensibilidad,
  F1, AUC y precisión media.
- **Importancia** por permutación (exactitud equilibrada) en cada participante
  de prueba con ambas clases, y su suma por señal.
- Escribe `windows.csv` (datos locales: dentro de `data/`) y `report.json`.
- Se prueba con un experimento simulado (`scripts.simulate_experiment`); sus
  resultados solo muestran que el flujo funciona, no que las señales aporten
  con personas reales.

## Pruebas

`pytest tests/analysis/test_ml_signals.py tests/analysis/test_facial_features.py
 tests/analysis/test_facial_model.py`. Las de entrenamiento requieren las
dependencias opcionales; las de rasgos no. Para cambiar definiciones, modifica
`FacialSettings`, aumenta `FEATURE_VERSION` y valida con personas independientes.
