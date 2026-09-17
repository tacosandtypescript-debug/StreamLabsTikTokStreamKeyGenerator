"""Tests for the diagnostic report export."""

from __future__ import annotations

import platform
import re
import zipfile
from datetime import datetime
from pathlib import Path

import pytest

import diagnostics
from config_store import ActiveSession, AppConfig, ConfigError, ConfigLoadResult
from diagnostics import (
    DIAGNOSTICS_PREFIX,
    MAX_ISSUE_BODY,
    REDACTED,
    REPORT_ENTRY_NAME,
    build_report,
    default_report_path,
    issue_url,
    scrub,
    system_summary,
)
from logging_setup import log_file_path
from version import __version__

FAKE_TOKEN = "slobs-9f8e7d6c5b4a3210"
FAKE_SESSION_ID = "sesion-1122334455667788"


def _write_log(tmp_path: Path, text: str, name: str = "app.log") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _entry_texts(destination: Path) -> dict[str, str]:
    with zipfile.ZipFile(destination) as archive:
        return {
            name: archive.read(name).decode("utf-8") for name in archive.namelist()
        }


class _StoreWithSession:
    """Stand-in for ConfigStore exposing one saved Streamlabs session."""

    def load(self) -> ConfigLoadResult:
        return ConfigLoadResult(
            config=AppConfig(active_session=ActiveSession(session_id=FAKE_SESSION_ID))
        )


class _BrokenStore:
    """Stand-in for ConfigStore when the configuration file is unreadable."""

    def load(self) -> ConfigLoadResult:
        raise ConfigError("configuración ilegible")


def test_scrub_removes_an_exact_secret():
    cleaned = scrub(f"token guardado: {FAKE_TOKEN}\n", [FAKE_TOKEN])

    assert FAKE_TOKEN not in cleaned
    assert cleaned == f"token guardado: {REDACTED}\n"


def test_scrub_ignores_short_and_blank_secrets():
    # Deliberate minimum length: a five-character value is configuration-like
    # and replacing it would mangle every log line that happens to contain it.
    text = "modo abc12 y vacío  "

    assert scrub(text, ["abc12", "", "   "]) == text


def test_scrub_redacts_an_authorization_header():
    cleaned = scrub(f"Authorization: Bearer {FAKE_TOKEN}\n")

    assert FAKE_TOKEN not in cleaned
    assert cleaned == f"Authorization: {REDACTED}\n"


def test_scrub_redacts_an_authorization_header_inside_a_repr():
    cleaned = scrub(f"headers={{'Authorization': 'Bearer {FAKE_TOKEN}'}}\n")

    assert FAKE_TOKEN not in cleaned
    assert "Authorization" in cleaned
    assert REDACTED in cleaned


def test_scrub_redacts_a_bare_bearer_token():
    cleaned = scrub(f"usando Bearer {FAKE_TOKEN} para la petición")

    assert cleaned == f"usando Bearer {REDACTED} para la petición"


def test_scrub_redacts_a_token_assignment():
    cleaned = scrub(f"token={FAKE_TOKEN} fin")

    assert cleaned == f"token={REDACTED} fin"


def test_scrub_redacts_a_json_token_field():
    cleaned = scrub(f'{{"token": "{FAKE_TOKEN}", "otro": 1}}')

    assert FAKE_TOKEN not in cleaned
    assert cleaned == f'{{"token": "{REDACTED}", "otro": 1}}'


def test_scrub_redacts_a_json_stream_key_field():
    cleaned = scrub('{"stream_key": "live_987654321", "game": "Minecraft"}')

    assert "live_987654321" not in cleaned
    assert cleaned == '{"stream_key": "«oculto»", "game": "Minecraft"}'


def test_scrub_redacts_a_stream_key_assignment():
    cleaned = scrub("stream_key=live_987654321\n")

    assert cleaned == f"stream_key={REDACTED}\n"


@pytest.mark.parametrize(
    "key",
    ["access_token", "refresh_token", "code_verifier", "api_key", "password", "secret"],
)
def test_scrub_redacts_every_declared_key_name(key):
    value = "valor-secreto-123456"

    cleaned = scrub(f"{key}={value}")

    assert value not in cleaned
    assert cleaned == f"{key}={REDACTED}"


def test_scrub_is_case_insensitive():
    cleaned = scrub(f"TOKEN={FAKE_TOKEN}\nStream_Key: live_987654\n")

    assert FAKE_TOKEN not in cleaned
    assert "live_987654" not in cleaned


def test_scrub_leaves_a_normal_log_line_untouched():
    line = (
        "2024-05-06 07:08:09 INFO streamlabs_client: "
        "cuenta validada, sesión iniciada correctamente (200 en 0.42 s)"
    )

    assert scrub(line, [FAKE_TOKEN]) == line


def test_scrub_keeps_long_values_that_are_not_secrets():
    # There is no blanket rule for "long looking" strings, which is what keeps
    # identifiers, URLs and checksums useful in a report.
    line = f"sesión {FAKE_SESSION_ID} activa en https://streamlabs.com/dashboard"

    assert scrub(line, []) == line


def test_system_summary_reports_the_environment():
    summary = system_summary()

    assert summary["Versión de la aplicación"] == __version__
    assert summary["Versión de Python"] == platform.python_version()
    assert summary["Archivo de registro"] == str(log_file_path())
    assert summary["Carpeta de registros"]
    assert summary["Sistema operativo"]
    assert summary["Arquitectura"]
    assert summary["Ruta del programa"]
    assert summary["Instalación"]
    assert summary["Empaquetado"] in {"sí", "no"}
    assert all(isinstance(value, str) and value for value in summary.values())


def test_system_summary_never_exposes_a_token_or_a_session_id(monkeypatch):
    monkeypatch.setenv("STREAMLABS_TOKEN", FAKE_TOKEN)
    monkeypatch.setattr(diagnostics, "ConfigStore", _StoreWithSession)

    summary = system_summary()
    blob = "\n".join(f"{key}={value}" for key, value in summary.items())

    assert all(value != FAKE_TOKEN for value in summary.values())
    assert FAKE_TOKEN not in blob
    assert FAKE_SESSION_ID not in blob
    # The session itself is reported as a bare yes/no, never with its identifier.
    assert summary["Sesión de Streamlabs guardada"] == "sí"


def test_system_summary_survives_an_unreadable_configuration(monkeypatch):
    monkeypatch.setattr(diagnostics, "ConfigStore", _BrokenStore)

    assert system_summary()["Sesión de Streamlabs guardada"] == "no se pudo comprobar"


def test_build_report_creates_a_zip_with_the_summary(tmp_path):
    destination = tmp_path / "informe.zip"
    summary = {"Versión de la aplicación": "9.9.9", "Sistema operativo": "Windows 11"}

    result = build_report(
        destination,
        summary=summary,
        log_path=_write_log(tmp_path, "INFO arranque correcto\n"),
    )

    assert result == destination
    assert destination.is_file()
    texts = _entry_texts(destination)

    assert list(texts) == [REPORT_ENTRY_NAME]
    assert "Versión de la aplicación: 9.9.9" in texts[REPORT_ENTRY_NAME]
    assert "Sistema operativo: Windows 11" in texts[REPORT_ENTRY_NAME]
    assert "---" in texts[REPORT_ENTRY_NAME]
    assert "INFO arranque correcto" in texts[REPORT_ENTRY_NAME]


def test_build_report_redacts_the_token_in_every_entry(tmp_path):
    log = _write_log(
        tmp_path,
        f"INFO token={FAKE_TOKEN}\n"
        f'INFO {{"token": "{FAKE_TOKEN}"}}\n'
        f"INFO Authorization: Bearer {FAKE_TOKEN}\n",
    )
    _write_log(tmp_path, f"INFO antiguo stream_key={FAKE_TOKEN}\n", name="app.log.1")

    destination = build_report(
        tmp_path / "informe.zip",
        summary=system_summary(),
        log_path=log,
        secret_values=[FAKE_TOKEN, "   "],
    )

    assert FAKE_TOKEN in log.read_text(encoding="utf-8")
    texts = _entry_texts(destination)

    assert list(texts) == [REPORT_ENTRY_NAME, "app.log.1"]
    for name, text in texts.items():
        assert FAKE_TOKEN not in text, name
        assert REDACTED in text, name


def test_build_report_scrubs_the_summary_too(tmp_path):
    destination = build_report(
        tmp_path / "informe.zip",
        summary={"Detalle de la cuenta": f"token={FAKE_TOKEN}"},
        log_path=None,
        secret_values=[FAKE_TOKEN],
    )

    text = _entry_texts(destination)[REPORT_ENTRY_NAME]

    assert FAKE_TOKEN not in text
    assert REDACTED in text


def test_build_report_includes_rotated_logs(tmp_path):
    log = _write_log(tmp_path, "INFO actual\n")
    _write_log(tmp_path, "INFO uno\n", name="app.log.1")
    _write_log(tmp_path, "INFO dos\n", name="app.log.2")

    destination = build_report(tmp_path / "informe.zip", summary={}, log_path=log)

    texts = _entry_texts(destination)

    assert list(texts) == [REPORT_ENTRY_NAME, "app.log.1", "app.log.2"]
    assert "INFO uno" in texts["app.log.1"]
    assert "INFO dos" in texts["app.log.2"]


def test_build_report_without_a_log_still_produces_a_valid_zip(tmp_path):
    destination = tmp_path / "informe.zip"

    build_report(
        destination,
        summary={"Versión de la aplicación": "1.0"},
        log_path=tmp_path / "no-existe.log",
    )

    texts = _entry_texts(destination)

    assert list(texts) == [REPORT_ENTRY_NAME]
    assert "No se encontró el archivo de registro" in texts[REPORT_ENTRY_NAME]


def test_build_report_accepts_a_missing_log_path(tmp_path):
    destination = build_report(tmp_path / "informe.zip", summary={}, log_path=None)

    assert "No se encontró el archivo de registro" in _entry_texts(destination)[
        REPORT_ENTRY_NAME
    ]


def test_build_report_creates_the_parent_directory_and_leaves_no_partial_file(tmp_path):
    destination = tmp_path / "sub" / "informe.zip"

    build_report(destination, summary={}, log_path=None)

    assert destination.is_file()
    assert list(tmp_path.rglob("*.part")) == []


def test_build_report_cleans_up_when_the_archive_cannot_be_written(tmp_path, monkeypatch):
    def boom(self, name, data):
        raise OSError("disco lleno")

    monkeypatch.setattr(diagnostics.zipfile.ZipFile, "writestr", boom)
    destination = tmp_path / "informe.zip"

    with pytest.raises(OSError):
        build_report(destination, summary={}, log_path=None)

    assert not destination.exists()
    assert list(tmp_path.rglob("*.part")) == []


def test_build_report_raises_for_an_unusable_destination(tmp_path):
    blocker = tmp_path / "bloqueo.txt"
    blocker.write_text("no soy una carpeta", encoding="utf-8")

    with pytest.raises(OSError):
        build_report(blocker / "informe.zip", summary={}, log_path=None)


def test_build_report_keeps_only_the_tail_of_a_long_log(tmp_path, monkeypatch):
    monkeypatch.setattr(diagnostics, "MAX_LOG_TAIL_CHARS", 500)
    log = _write_log(
        tmp_path,
        "INICIO-DEL-REGISTRO\n" + "x" * 4000 + "\nFINAL-DEL-REGISTRO\n",
    )

    destination = build_report(tmp_path / "informe.zip", summary={}, log_path=log)

    text = _entry_texts(destination)[REPORT_ENTRY_NAME]

    assert "FINAL-DEL-REGISTRO" in text
    assert "INICIO-DEL-REGISTRO" not in text


def test_default_report_path_uses_the_injected_time(tmp_path, monkeypatch):
    monkeypatch.setattr(diagnostics, "default_download_dir", lambda: tmp_path / "Descargas")

    path = default_report_path(datetime(2024, 5, 6, 7, 8, 9))

    assert path.name == f"{DIAGNOSTICS_PREFIX}-20240506-070809.zip"
    assert path.parent == tmp_path / "Descargas"


def test_default_report_path_uses_the_current_time_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr(diagnostics, "default_download_dir", lambda: tmp_path)

    path = default_report_path()

    assert re.fullmatch(r"diagnostico-\d{8}-\d{6}\.zip", path.name)
    stamp = datetime.strptime(path.name[len(DIAGNOSTICS_PREFIX) + 1 : -4], "%Y%m%d-%H%M%S")
    assert abs((datetime.now() - stamp).total_seconds()) < 60


# --------------------------------------------------------------------------- #
#  El aviso de un problema                                                    #
# --------------------------------------------------------------------------- #


def _issue_body(url: str) -> str:
    from urllib.parse import parse_qs, urlparse

    return parse_qs(urlparse(url).query)["body"][0]


def test_the_issue_link_points_at_this_repository():
    url = issue_url()

    assert url.startswith(f"{diagnostics.REPOSITORY_URL}/issues/new?")
    assert "title=" in url


def test_the_issue_carries_the_facts_that_help():
    body = _issue_body(issue_url())

    assert __version__ in body
    assert platform.system() in body
    assert "Empaquetado" in body


def test_the_issue_never_publishes_the_user_paths():
    # The full report has them, and that is fine for a file on the user's desk; a
    # public issue is another thing, because those paths carry the user's name.
    summary = system_summary()
    body = _issue_body(issue_url(summary))

    for field in ("Ruta del programa", "Carpeta de registros", "Archivo de registro"):
        assert field not in body
        assert summary[field] not in body


def test_the_issue_never_carries_a_secret():
    url = issue_url(problem=f"el token {FAKE_TOKEN} falla")

    assert FAKE_TOKEN in url  # lo que escribe el usuario es suyo
    assert FAKE_TOKEN not in _issue_body(issue_url())


def test_what_the_user_wrote_is_kept():
    body = _issue_body(issue_url(problem="Al preparar el directo dice que no hay token"))

    assert "Al preparar el directo dice que no hay token" in body


def test_without_a_description_there_is_a_placeholder():
    body = _issue_body(issue_url())

    assert "cuéntalo aquí" in body


def test_the_body_cannot_grow_without_limit():
    summary = {f"campo {index}": "x" * 200 for index in range(50)}

    assert len(_issue_body(issue_url(summary))) <= MAX_ISSUE_BODY
