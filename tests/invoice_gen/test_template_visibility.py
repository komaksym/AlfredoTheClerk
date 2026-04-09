"""Tests for frozen template-visibility manifests.

Covers the ``no_pdf`` default builder, literal-first / wildcard-fallback
lookup semantics, deterministic JSON encoding, and every decode-time
validation path (unknown schema version, unknown keys, unknown status,
malformed JSON).
"""

from __future__ import annotations

import json

import pytest

from src.invoice_gen.template_visibility import (
    NO_PDF_TEMPLATE_ID,
    TEMPLATE_VISIBILITY_SCHEMA_VERSION,
    TemplateVisibilityError,
    TemplateVisibilityManifest,
    VisibilityStatus,
    build_no_pdf_visibility_manifest,
    manifest_from_dict,
    manifest_from_json,
    manifest_to_dict,
    manifest_to_json,
)


# --- build_no_pdf_visibility_manifest ------------------------------------


def test_build_no_pdf_manifest_marks_every_path_not_rendered() -> None:
    """The default pre-PDF manifest must hide every scored path."""

    manifest = build_no_pdf_visibility_manifest(
        ["shell.currency", "summary.invoice_gross_total"]
    )

    assert manifest.template_id == NO_PDF_TEMPLATE_ID
    assert manifest.fields == {
        "shell.currency": VisibilityStatus.NOT_RENDERED,
        "summary.invoice_gross_total": VisibilityStatus.NOT_RENDERED,
    }


# --- Manifest lookup -----------------------------------------------------


def test_manifest_wildcard_lookup_collapses_indexed_segments() -> None:
    """A ``[*]`` visibility rule must match concrete indexes."""

    manifest = TemplateVisibilityManifest(
        template_id="template-a",
        fields={
            "shell.line_items[*].description": VisibilityStatus.VISIBLE,
        },
    )

    assert manifest.status_for("shell.line_items[7].description") is (
        VisibilityStatus.VISIBLE
    )
    assert manifest.is_visible("shell.line_items[7].description") is True


def test_manifest_literal_path_takes_precedence_over_wildcard() -> None:
    """A literal visibility rule must win over the wildcard fallback."""

    manifest = TemplateVisibilityManifest(
        template_id="template-a",
        fields={
            "shell.line_items[*].description": VisibilityStatus.NOT_RENDERED,
            "shell.line_items[0].description": VisibilityStatus.VISIBLE,
        },
    )

    assert manifest.status_for("shell.line_items[0].description") is (
        VisibilityStatus.VISIBLE
    )


# --- JSON round-trip and determinism -------------------------------------


def test_manifest_round_trips_through_json() -> None:
    """A manifest must survive a deterministic JSON round-trip."""

    original = TemplateVisibilityManifest(
        template_id="template-a",
        fields={
            "shell.currency": VisibilityStatus.VISIBLE,
            "summary.invoice_gross_total": VisibilityStatus.NOT_RENDERED,
        },
    )

    decoded = manifest_from_json(manifest_to_json(original))

    assert decoded == original


def test_manifest_to_json_is_deterministic() -> None:
    """Two encodings of the same manifest must be byte-identical."""

    manifest = TemplateVisibilityManifest(
        template_id="template-a",
        fields={"shell.currency": VisibilityStatus.VISIBLE},
    )

    assert manifest_to_json(manifest) == manifest_to_json(manifest)


# --- Decode-time validation ----------------------------------------------


def test_manifest_from_dict_rejects_unknown_schema_version() -> None:
    """Bumping the schema version must raise on decode."""

    payload = manifest_to_dict(
        TemplateVisibilityManifest(
            template_id="template-a",
            fields={"shell.currency": VisibilityStatus.VISIBLE},
        )
    )
    payload["schema_version"] = TEMPLATE_VISIBILITY_SCHEMA_VERSION + 1

    with pytest.raises(TemplateVisibilityError, match="schema_version"):
        manifest_from_dict(payload)


def test_manifest_from_dict_rejects_unknown_keys() -> None:
    """Extra top-level keys must be rejected."""

    payload = manifest_to_dict(
        TemplateVisibilityManifest(
            template_id="template-a",
            fields={"shell.currency": VisibilityStatus.VISIBLE},
        )
    )
    payload["extra"] = "nope"

    with pytest.raises(TemplateVisibilityError, match="unknown keys"):
        manifest_from_dict(payload)


def test_manifest_from_dict_rejects_unknown_status() -> None:
    """Unknown visibility statuses must raise."""

    payload = {
        "schema_version": TEMPLATE_VISIBILITY_SCHEMA_VERSION,
        "template_id": "template-a",
        "fields": {"shell.currency": "sometimes"},
    }

    with pytest.raises(TemplateVisibilityError, match="unknown status"):
        manifest_from_dict(payload)


def test_manifest_from_json_rejects_invalid_json() -> None:
    """Malformed JSON must raise a TemplateVisibilityError."""

    with pytest.raises(TemplateVisibilityError, match="invalid JSON"):
        manifest_from_json("not json {")


def test_manifest_to_json_emits_sorted_keys() -> None:
    """The encoded manifest must sort field paths deterministically."""

    text = manifest_to_json(
        TemplateVisibilityManifest(
            template_id="template-a",
            fields={
                "summary.invoice_gross_total": VisibilityStatus.NOT_RENDERED,
                "shell.currency": VisibilityStatus.VISIBLE,
            },
        )
    )
    decoded = json.loads(text)

    assert decoded["schema_version"] == TEMPLATE_VISIBILITY_SCHEMA_VERSION
    assert list(decoded["fields"].keys()) == [
        "shell.currency",
        "summary.invoice_gross_total",
    ]
