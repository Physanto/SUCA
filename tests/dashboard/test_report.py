"""Informe de resultados: gráficas SVG, veredicto, documento HTML y su generación."""

import dataclasses
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from dashboard import findings as findings_module
from dashboard import report, report_inputs, report_svg
from dashboard.data import DashboardData
from dashboard.report import ReportInputs
from dashboard.report_svg import Bar, TimelineRow
from scripts import study_report

VOID = {"meta", "img", "br", "hr", "input", "link"}


class Balanced(HTMLParser):
    """Comprueba que cada etiqueta abierta se cierra, en orden."""

    def __init__(self) -> None:
        """Empieza con la pila vacía."""
        super().__init__()
        self.stack: list[str] = []
        self.errors: list[str] = []
        self.scripts = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        """Apila la etiqueta, salvo las que no se cierran."""
        if tag == "script":
            self.scripts += 1
        if tag not in VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: Any) -> None:
        """Las etiquetas que se cierran solas no entran en la pila."""

    def handle_endtag(self, tag: str) -> None:
        """Quita la etiqueta de la pila; si no era la última, es un error."""
        if not self.stack or self.stack.pop() != tag:
            self.errors.append(tag)


def make_inputs(**changes: Any) -> ReportInputs:
    """Datos mínimos y coherentes para el informe."""
    sessions = pd.DataFrame(
        {
            "session_id": [1, 2, 3, 4],
            "participant_id": ["A", "B", "C", "D"],
            "version": ["V0", "V0", "V2", "V2"],
            "bui": [90.0, 88.0, 55.0, 60.0],
        }
    )
    answers = pd.DataFrame(
        {
            "session_id": [1, 2, 3, 4],
            "participant_id": ["A", "B", "C", "D"],
            "version": ["V0", "V0", "V2", "V2"],
            "answers": [[5, 1, 5, 1, 5, 1, 5, 1, 5, 1]] * 2 + [[3, 4, 2, 4, 2, 4, 3, 3, 2, 4]] * 2,
            "score": [100.0, 100.0, 32.5, 32.5],
        }
    )
    found = pd.DataFrame(
        [
            {
                "severity": "Alta",
                "screen": "/login",
                "element": "#login-form",
                "incident": "Fallo sin aviso",
                "people": 2,
                "share": 0.5,
                "times": 3,
                "by_version": "V0 0/2 · V2 2/2",
                "failed_tasks": 1,
                "also_in_baseline": False,
                "meaning": "Falló sin explicarlo.",
                "check": "Qué mensaje vio.",
                "examples": "C (1:02)",
                "recommendation": "Mostrar el error junto al campo.",
            }
        ]
    )
    tasks = pd.DataFrame(
        {
            "position": [1],
            "instruction": ["Inicia sesión"],
            "success_rate": [0.9],
            "median_s": [20.0],
            "main_incident": ["Fallo sin aviso (3)"],
        }
    )
    incidents = pd.DataFrame(
        {"session_id": [3, 3, 4], "type": ["silent_failure", "dead_click", "silent_failure"]}
    )
    values: dict[str, Any] = {
        "study": "Tienda de prueba",
        "system": "App de ejemplo",
        "generated_at": "12/11/2026 10:00",
        "source": "prueba.db",
        "versions": ["V0", "V2"],
        "sessions": sessions,
        "summary": pd.DataFrame(),
        "tasks": tasks,
        "findings": found,
        "incidents": incidents,
        "index": pd.DataFrame(
            {
                "session_id": [1, 3],
                "version": ["V0", "V2"],
                "effectiveness": [100.0, 50.0],
                "time_efficiency": [90.0, 60.0],
                "path_efficiency": [90.0, 60.0],
                "friction": [95.0, 40.0],
                "bui": [93.0, 52.0],
            }
        ),
        "sus_answers": answers,
    }
    values.update(changes)
    return ReportInputs(**values)


# --- SVG -------------------------------------------------------------------------------------


def test_bars_are_clamped_escaped_and_deterministic() -> None:
    bars = [Bar("A <b>", 150, "150", "good"), Bar("B", None), Bar("C", -5)]
    first = report_svg.bar_chart(bars, maximum=100, title="t", description="d")
    assert first == report_svg.bar_chart(bars, maximum=100, title="t", description="d")
    assert "A &lt;b&gt;" in first and "<b>" not in first
    track = 720 - report_svg.LABEL_WIDTH - 90
    assert f'width="{track:.1f}"' in first  # el 150 se recorta al máximo
    assert "—" in first  # sin dato
    assert report_svg.bar_chart([], maximum=1, title="t", description="d").startswith("<p")


def test_the_sus_scale_marks_the_average_and_every_answer() -> None:
    svg = report_svg.sus_scale([("A · V0", 92.5), ("B · V2", 32.5)])
    for name in ("Pobre", "Aceptable", "Bueno", "Excelente", "promedio 68", "A · V0 · 92"):
        assert name in svg
    assert svg.count("<circle") == 2


def test_the_timeline_draws_tasks_and_marks_and_a_legend() -> None:
    row = TimelineRow("A · V0", 60000, [(0, 20000, "T1")], [(10000, 0), (30000, 1)])
    svg = report_svg.timeline([row], ["Clic sin respuesta", "Pausa larga"])
    assert svg.count("<circle") == 4  # dos incidentes y dos de la leyenda
    assert "T1" in svg and "Pausa larga" in svg
    assert report_svg.timeline([], []).startswith("<p")


# --- Veredicto -------------------------------------------------------------------------------


def test_good_signals_give_a_usable_reading() -> None:
    inputs = make_inputs(
        sus_answers=make_inputs().sus_answers.assign(score=90.0),
        findings=make_inputs().findings.iloc[0:0],
        tasks=make_inputs().tasks.assign(success_rate=0.95),
    )
    assert report.verdict(inputs).tone == "good"


def test_one_bad_signal_makes_the_reading_serious_and_it_says_why() -> None:
    reading = report.verdict(make_inputs(tasks=make_inputs().tasks.assign(success_rate=0.3)))
    assert reading.tone == "bad" and "problemas serios" in reading.headline
    cards = {card.title: card for card in reading.cards}
    assert cards["Tareas completadas"].tone == "bad" and cards["Tareas completadas"].value == "30 %"
    assert cards["SUS"].value.startswith("66")


def test_mixed_signals_give_a_mixed_reading() -> None:
    inputs = make_inputs(
        sus_answers=make_inputs().sus_answers.assign(score=70.0),
        tasks=make_inputs().tasks.assign(success_rate=0.7),
        findings=make_inputs().findings.assign(severity="Media"),
    )
    assert report.verdict(inputs).tone == "ok"


def test_without_any_signal_the_reading_says_there_is_not_enough_data() -> None:
    empty = make_inputs(
        sus_answers=make_inputs().sus_answers.iloc[0:0],
        tasks=make_inputs().tasks.iloc[0:0],
        findings=make_inputs().findings.iloc[0:0],
        sessions=make_inputs().sessions.assign(bui=None),
    )
    reading = report.verdict(empty)
    assert reading.tone == "muted" and "Sin datos suficientes" in reading.headline


def test_few_sessions_per_version_are_flagged_as_unreliable() -> None:
    texts = " ".join(report.verdict(make_inputs()).paragraphs)
    assert "poco fiables" in texts  # 2 sesiones por versión
    many = make_inputs(
        sessions=pd.concat([make_inputs().sessions] * 3, ignore_index=True).assign(
            session_id=range(12)
        )
    )
    assert "poco fiables" not in " ".join(report.verdict(many).paragraphs)


# --- Documento -------------------------------------------------------------------------------


def test_the_document_has_every_section_and_is_self_contained() -> None:
    html = report.render(make_inputs(conclusions="Corregir el login primero."))
    for anchor, _ in report.TOC:
        assert f'id="{anchor}"' in html
    assert "Corregir el login primero." in html and "Mostrar el error junto al campo." in html
    assert "Fallo sin aviso" in html and "Calificación" in html
    parser = Balanced()
    parser.feed(html)
    assert not parser.errors and not parser.stack
    assert parser.scripts == 0
    # Sin recursos externos: nada se descarga al abrirlo.
    assert not re.findall(r'(?:src|href)="https?://', html) and "@import" not in html
    assert '<html lang="es">' in html and "<title>" in html


def test_the_report_escapes_everything_that_comes_from_the_data() -> None:
    hostile = "<script>alert(1)</script>"
    inputs = make_inputs(
        study=hostile,
        conclusions=hostile,
        findings=make_inputs().findings.assign(element=hostile, recommendation=hostile),
    )
    html = report.render(inputs)
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_the_nielsen_table_carries_its_caveat_and_the_scale_its_reference() -> None:
    html = report.render(make_inputs())
    assert "no una evaluación heurística" in html
    assert "promedio 68" in html
    assert "Ayudar a reconocer, diagnosticar y recuperarse de errores" in html


def test_without_sus_iuc_or_tasks_each_section_says_so() -> None:
    html = report.render(
        make_inputs(
            sus_answers=make_inputs().sus_answers.iloc[0:0],
            index=make_inputs().index.iloc[0:0],
            tasks=make_inputs().tasks.iloc[0:0],
            findings=make_inputs().findings.iloc[0:0],
            incidents=make_inputs().incidents.iloc[0:0],
        )
    )
    assert "Nadie respondió el SUS" in html and "Sin IUC" in html
    assert "Sin resultados por tarea" in html and "No hay incidentes" in html
    parser = Balanced()
    parser.feed(html)
    assert not parser.errors and not parser.stack


def test_more_findings_than_the_limit_go_into_a_table() -> None:
    many = pd.concat([make_inputs().findings] * (report.TOP_FINDINGS + 3), ignore_index=True)
    html = report.render(make_inputs(findings=many))
    assert html.count('class="finding"') == report.TOP_FINDINGS
    assert "Otros hallazgos" in html


# --- Datos de la base y comandos -------------------------------------------------------------


def test_collect_reads_a_study_and_draws_the_heatmaps(data: DashboardData) -> None:
    inputs = report_inputs.collect(data, 1, ["guided", "free"], source="mock.db")
    assert len(inputs.sessions) == 4 and inputs.source == "mock.db"
    assert not inputs.findings.empty and (inputs.findings["recommendation"] == "").all()
    assert inputs.heatmaps
    assert all(f.data_uri.startswith("data:image/jpeg;base64,") for f in inputs.heatmaps)
    assert {f.layer for f in inputs.heatmaps} <= {"Clics", "Mirada"}
    assert inputs.timelines and inputs.timeline_legend
    assert len(inputs.sus_answers) == 3  # las sesiones guiadas respondieron el SUS


def test_collect_filters_by_mode_and_version(data: DashboardData) -> None:
    inputs = report_inputs.collect(data, 1, ["guided"], ["V2"])
    assert inputs.versions == ["V2"] and len(inputs.sessions) == 1
    assert set(inputs.incidents["session_id"]) <= set(inputs.sessions["session_id"])


def test_collect_refuses_unknown_studies_and_empty_filters(data: DashboardData) -> None:
    with pytest.raises(LookupError, match="does not exist"):
        report_inputs.collect(data, 99, ["guided"])
    with pytest.raises(LookupError, match="no sessions"):
        report_inputs.collect(data, 1, ["guided"], ["V9"])


def test_the_reviewed_recommendations_reach_the_document(data: DashboardData) -> None:
    inputs = report_inputs.collect(data, 1, ["guided", "free"])
    reviewed = inputs.findings.assign(recommendation="Recomendación de prueba")
    html = report.render(dataclasses.replace(inputs, findings=reviewed))
    assert "Recomendación de prueba" in html
    assert 'src="data:image/jpeg;base64,' in html
    parser = Balanced()
    parser.feed(html)
    assert not parser.errors and not parser.stack


def test_the_severity_names_the_report_uses_exist() -> None:
    assert set(findings_module.SEVERITIES) == {"Alta", "Media", "Baja"}


def test_the_command_writes_the_report(
    mock: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "salida" / "informe.html"
    conclusions = tmp_path / "conclusiones.txt"
    conclusions.write_text("Lo primero es el login.", encoding="utf-8")
    code = study_report.main(
        [
            "--db", str(mock.path), "--study", "1", "--modes", "guided", "free",
            "--conclusions", str(conclusions), "--output", str(output),
        ]
    )  # fmt: skip
    assert code == 0
    html = output.read_text(encoding="utf-8")
    assert "Lo primero es el login." in html and "Informe de usabilidad" in html
    assert "informe:" in capsys.readouterr().out


def test_the_command_reports_a_missing_study_and_a_missing_database(
    mock: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert study_report.main(["--db", str(mock.path), "--study", "99"]) == 1
    assert "does not exist" in capsys.readouterr().err
    assert study_report.main(["--db", str(tmp_path / "nada.db"), "--study", "1"]) == 1
    assert "error" in capsys.readouterr().err
