# Páginas de prueba de la extensión

Sirve esta carpeta desde la raíz del proyecto:

```bash
python -m scripts.serve_test_page
```

`index.html` reúne interacciones de captura. `attention.html` mide la atribución
de la mirada contra objetivos conocidos. Abre la URL indicada por el servidor
con `/attention.html`, ajusta las Opciones de la extensión al monitor y crea una
sesión con calibración inicial. Amplía la ventana para que todos los objetivos
quepan antes de crear la sesión. Pulsa **Empezar** una sola vez y sigue las
instrucciones durante un minuto, sin pulsar los objetivos ni escribir.

El guion incluye contenido amplio, dos enlaces de 60 × 16 px, un aviso pequeño,
vacío y teclado. Cada objetivo dura 3 s. `attention-script.json` es la fuente
del orden y los tiempos; el banco descarta los primeros 500 ms de cada paso.
El borde no altera las cajas de los elementos. Un cambio de tamaño, scroll o
pestaña interrumpe la ejecución: descarta esa sesión para el banco y repite con
una sesión nueva. No se reinicia el guion dentro de la misma sesión.

Para cambiar los objetivos, modifica el JSON y conserva los selectores del HTML
sin mover sus cajas durante la ejecución. Las pruebas del guion se ejecutan con
`npm test`. La precisión real requiere cámara, consentimiento y revisión manual.
