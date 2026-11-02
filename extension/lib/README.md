# Librerías de la cámara

Archivos de terceros que usa el motor de cámara (`extension/camera/`). Se copian tal cual, sin modificar, porque la extensión no tiene empaquetador. Solo los carga el documento *offscreen* de la extensión; ninguna página web puede pedirlos.

| Archivo | Origen | Versión | Licencia | SHA-256 |
|---|---|---|---|---|
| `vision_bundle.mjs` | npm `@mediapipe/tasks-vision` | 1.2.0 | Apache-2.0 | `870da5cfc43bfcf2a8b0f14e8152dae8c7e701722e1191b0e592b94b81b4127a` |
| `vision_wasm_internal.js` | npm `@mediapipe/tasks-vision` (`wasm/`) | 1.2.0 | Apache-2.0 | `85c1a342be70427987f900969a5f26e17557351111364e6585e97fb03e93e108` |
| `vision_wasm_internal.wasm` | npm `@mediapipe/tasks-vision` (`wasm/`) | 1.2.0 | Apache-2.0 | `bcc13df22d3d69ec8cbe8e280989356d844ae00f4523eb82072d2484f44134dc` |
| `face_landmarker.task` | `storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/` | float16, versión 1 | Apache-2.0 | `64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff` |
| `LICENSE-mediapipe.txt` | Repositorio `google-ai-edge/mediapipe` | — | Texto de la licencia Apache-2.0 | — |

- **Solo la variante con SIMD** del WebAssembly: Chrome 116 o más la soporta, y así no se suben las otras dos (unos 27 MB).
- `vision_bundle.mjs` termina con una referencia a su mapa de fuentes, que no se incluye: DevTools puede avisar que no lo encuentra. No afecta el funcionamiento.
- **Mirada sin WebGazer.** La mirada se estima con los puntos del rostro que entrega este mismo modelo (ver `extension/camera/README.md`). WebGazer 3.5.3 se evaluó y se descartó: trae su propia copia de MediaPipe (17 MB) y un segundo modelo de rostro por cuadro, y su licencia es GPL-3.0.

## Actualizar

1. Descargar el paquete (`npm pack @mediapipe/tasks-vision@<versión>`) y copiar `vision_bundle.mjs`, `wasm/vision_wasm_internal.js` y `wasm/vision_wasm_internal.wasm`.
2. Actualizar la tabla, con la nueva suma (`sha256sum *`).
3. Repetir la prueba manual de la cámara (`extension/camera/README.md`).
