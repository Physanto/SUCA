/**
 * @file Configuración y contratos para la extensión.
 *
 * ARCHIVO GENERADO: no lo edites a mano. Se genera con
 * `python -m scripts.generate_config` desde config/shared.json y
 * contracts/enums.json; una prueba falla si queda desactualizado.
 *
 * Define `UX.config` y `UX.contracts` sobre globalThis, así que funciona igual
 * en los content scripts, en el service worker (importScripts) y en el panel.
 */

(function (root) {
  'use strict';

  /**
   * Congela un objeto y todo lo que contiene, para que ningún módulo pueda
   * alterar los valores compartidos.
   *
   * @param {object} value - Objeto a congelar.
   * @returns {object} El mismo objeto, congelado.
   */
  function deepFreeze(value) {
    Object.values(value).forEach((child) => {
      if (child !== null && typeof child === 'object') {
        deepFreeze(child);
      }
    });
    return Object.freeze(value);
  }

  const UX = (root.UX = root.UX || {});

  /** Configuración de la extensión: servidor, envío, captura y cámara. */
  UX.config = deepFreeze({
    "server": {
      "host": "127.0.0.1",
      "port": 8765,
      "token": "suca-local-dev-token"
    },
    "sending": {
      "interval_ms": 2000,
      "max_batch_records": 500,
      "retry_initial_ms": 1000,
      "retry_max_ms": 30000
    },
    "capture": {
      "mousemove_hz": 50,
      "scroll_hz": 10,
      "click_response_wait_ms": 1500
    },
    "camera": {
      "gaze_hz": 30,
      "face_hz": 15,
      "video_width": 1920,
      "video_height": 1080,
      "viewing_distance_cm": 50.0,
      "css_px_per_cm": 36.22,
      "distance_scale": 1.24,
      "min_distance_cm": 35.0,
      "max_distance_cm": 75.0,
      "calibration_max_error_deg": 5.0,
      "lock_exposure": true,
      "blink_threshold": 0.45,
      "off_screen_margin_px": 120.0,
      "head_range_margin_deg": 12.0,
      "gaze_hybrid": true,
      "filter_min_cutoff_hz": 0.5,
      "filter_beta": 0.003,
      "drift_check_between_tasks": true,
      "drift_correction": true,
      "drift_correction_min_error_deg": 1.0,
      "record_gaze_features": true
    }
  });

  /** Versión de los contratos y valores permitidos de cada enumeración. */
  UX.contracts = deepFreeze({
    "version": "1.7.0",
    "enums": {
      "batch_type": [
        "events",
        "gaze",
        "face",
        "tasks",
        "calibration",
        "layout",
        "gaze_features",
        "gaze_target"
      ],
      "event_type": [
        "click",
        "dblclick",
        "contextmenu",
        "mousemove",
        "scroll",
        "selection",
        "focus_in",
        "focus_out",
        "field_change",
        "form_submit",
        "validation_error",
        "screen_change",
        "click_response",
        "camera_gap"
      ],
      "validation_error_type": [
        "value_missing",
        "type_mismatch",
        "pattern_mismatch",
        "too_long",
        "too_short",
        "range_underflow",
        "range_overflow",
        "step_mismatch",
        "bad_input",
        "custom_error",
        "aria_invalid",
        "visible_message"
      ],
      "camera_gap_reason": [
        "navigation",
        "no_permission",
        "error"
      ],
      "incident_type": [
        "rage_click",
        "dead_click",
        "navigation_loop",
        "long_pause",
        "hesitation",
        "form_error",
        "field_reentry",
        "form_abandonment",
        "repeated_search",
        "task_overtime"
      ],
      "episode_type": [
        "login",
        "form",
        "search",
        "screen"
      ],
      "session_mode": [
        "free",
        "guided",
        "reference"
      ],
      "ended_by": [
        "reference",
        "done",
        "gave_up"
      ],
      "end_condition_type": [
        "visible_text",
        "url_pattern",
        "element_present"
      ],
      "step_type": [
        "click",
        "form_submit",
        "screen_change"
      ],
      "reference_status": [
        "draft",
        "confirmed"
      ],
      "gaze_zone": [
        "header",
        "nav",
        "main",
        "aside",
        "footer",
        "search",
        "grid_top_left",
        "grid_top_center",
        "grid_top_right",
        "grid_middle_left",
        "grid_middle_center",
        "grid_middle_right",
        "grid_bottom_left",
        "grid_bottom_center",
        "grid_bottom_right"
      ],
      "face_value": [
        "brow_down_left",
        "brow_down_right",
        "brow_inner_up",
        "eye_squint_left",
        "eye_squint_right",
        "eye_blink_left",
        "eye_blink_right",
        "mouth_press_left",
        "mouth_press_right",
        "mouth_frown_left",
        "mouth_frown_right",
        "mouth_smile_left",
        "mouth_smile_right"
      ],
      "calibration_type": [
        "initial",
        "final",
        "drift_check"
      ],
      "gaze_state": [
        "on_screen",
        "low_confidence",
        "off_screen",
        "blink",
        "no_face",
        "uncalibrated"
      ],
      "gaze_estimator": [
        "geometric",
        "appearance",
        "hybrid"
      ],
      "gaze_target_phase": [
        "points",
        "pursuit",
        "head",
        "validation",
        "look_away",
        "drift_check",
        "neutral_baseline"
      ],
      "camera_status": [
        "active",
        "no_permission",
        "error"
      ],
      "message_type": [
        "session.started",
        "session.closed",
        "task.started",
        "task.completed",
        "calibration.request",
        "calibration.result",
        "camera.status",
        "screen_capture.request",
        "frame.request",
        "frame.masks",
        "batch",
        "tab.identify"
      ]
    }
  });
})(globalThis);
