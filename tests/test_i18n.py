"""The translation layer: catalogs, fallbacks and language selection."""

from __future__ import annotations

import pytest

from i18n import (
    LANGUAGE_ENV_VAR,
    SOURCE_LANGUAGE,
    available_languages,
    current_language,
    register_catalog,
    set_language,
    tr,
)


@pytest.fixture(autouse=True)
def source_language():
    """Every test starts and ends on the source language."""

    set_language(SOURCE_LANGUAGE)
    yield
    set_language(SOURCE_LANGUAGE)


def test_without_a_catalog_the_source_text_is_returned():
    assert tr("Preparar directo") == "Preparar directo"


def test_a_registered_catalog_is_used():
    register_catalog("xx", {"Preparar directo": "Prepare stream"})

    assert set_language("xx") == "xx"
    assert tr("Preparar directo") == "Prepare stream"


def test_an_untranslated_string_falls_back_to_the_source_text():
    register_catalog("xx", {"Preparar directo": "Prepare stream"})
    set_language("xx")

    assert tr("Finalizar directo") == "Finalizar directo"


def test_the_source_language_is_always_available():
    assert SOURCE_LANGUAGE in available_languages()
    assert current_language() == SOURCE_LANGUAGE


def test_a_registered_language_is_listed():
    register_catalog("zz", {})

    assert "zz" in available_languages()


def test_a_language_tag_is_normalized():
    register_catalog("PT-BR", {"Preparar directo": "Preparar transmissão"})

    assert set_language("pt_BR") == "pt"
    assert tr("Preparar directo") == "Preparar transmissão"


def test_an_unavailable_language_falls_back_instead_of_failing(caplog):
    caplog.set_level("WARNING", logger="i18n")

    assert set_language("tlh") == SOURCE_LANGUAGE
    assert "No catalog" in caplog.text


def test_the_environment_variable_selects_the_language(monkeypatch):
    register_catalog("yy", {"Preparar directo": "Prepare"})
    monkeypatch.setenv(LANGUAGE_ENV_VAR, "yy")

    assert set_language() == "yy"
    assert tr("Preparar directo") == "Prepare"


def test_an_unknown_environment_value_falls_back(monkeypatch):
    monkeypatch.setenv(LANGUAGE_ENV_VAR, "kli")

    assert set_language() == SOURCE_LANGUAGE


def test_the_source_language_cannot_be_registered():
    with pytest.raises(ValueError):
        register_catalog(SOURCE_LANGUAGE, {})


def test_an_empty_language_cannot_be_registered():
    with pytest.raises(ValueError):
        register_catalog("   ", {})


def test_the_catalog_is_copied_and_not_referenced():
    catalog = {"Preparar directo": "A"}
    register_catalog("vv", catalog)

    catalog["Preparar directo"] = "B"
    set_language("vv")

    assert tr("Preparar directo") == "A"


def test_switching_back_to_the_source_language_stops_translating():
    register_catalog("ww", {"Preparar directo": "Prepare"})
    set_language("ww")
    assert tr("Preparar directo") == "Prepare"

    set_language(SOURCE_LANGUAGE)

    assert tr("Preparar directo") == "Preparar directo"
