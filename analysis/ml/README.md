# Movimientos faciales y comparación de señales

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

Pruebas: `pytest tests/analysis/test_facial_features.py
 tests/analysis/test_facial_model.py`. Las de entrenamiento requieren las
dependencias opcionales; las de rasgos no. Para cambiar definiciones, modifica
`FacialSettings`, aumenta `FEATURE_VERSION` y valida con personas independientes.
