# Estudios y piloto

Cada YAML define un estudio y sus tareas en orden. Para apps externas se deja
`recorded_fields: []`. El nombre identifica el estudio al volver a cargarlo.
No reordenes tareas de un estudio con sesiones.

Prepara una app desplegada con 2–4 tareas acordadas con el equipo:

```bash
python -m scripts.prepare_pilot --name "App del equipo" --url https://example.org \
  --task "Busca un elemento del catálogo." --task "Abre su detalle." \
  --output studies/pilot-example.yaml
python -m scripts.load_study studies/pilot-example.yaml
```

Sustituye el ejemplo por la URL y las tareas reales. El generador valida el
estudio y no reemplaza archivos existentes. Si necesitas registrar un campo de
una tarea con datos ficticios, decláralo explícitamente en el YAML; nunca
contraseñas, tarjetas ni datos personales.

Antes de la prueba configura el monitor en **Opciones** de la extensión,
comprueba la barra de 10 cm con una regla, registra la distancia y recarga la
extensión si cambió el código. Enciende el servidor con `python -m server`.
Usa el consentimiento informado aprobado por el proyecto. Se guardan números
del rostro y de los ojos, sin video ni imágenes del rostro.

Desde el panel lateral: estudio, participante anónimo, calibración inicial,
tareas guiadas, comprobaciones entre tareas y SUS. Anota el error de cada
calibración y cualquier interrupción. Mantén la cámara centrada a la altura de
los ojos y luz frontal difusa. Los iframes y el interior de shadow DOM quedan
fuera de la captura.

```bash
python -m analysis.run --study ID
streamlit run dashboard/app.py
```

Revisa incidentes, IUC, reproducción y mapas de clics, cursor y mirada. En el
log debe aparecer `attributed N fixations`. El piloto valida el flujo completo;
la precisión de mirada se mide aparte con objetivos conocidos.

Para esa medición se incluye `attention.yaml`. Sirve la página con
`python -m scripts.serve_test_page`, carga el estudio y abre la URL declarada.
Al cerrar y analizar la sesión:

```bash
python -m scripts.attention_bench --session ID --json data/attention-ID.json
python -m scripts.gaze_bench --session ID --json data/gaze-ID.json
```

El guion dura un minuto. No ajustes las probabilidades hasta medirlas con
cámara real y comprobar la reproducción. Una sesión de 15 minutos con giros
naturales de cabeza sigue siendo necesaria para revisar estabilidad y deriva.

`example-problems.yaml` es el catálogo de problemas sembrados de la app de
prueba, en el formato que usa la evaluación del experimento
(`scripts/evaluation/README.md`). Si cambia un problema de la app, cámbialo
también ahí.
