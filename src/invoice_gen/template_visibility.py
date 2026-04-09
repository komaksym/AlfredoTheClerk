"""Frozen template-visibility manifests for benchmark scoring.

This module owns the M2 visibility contract for the domestic VAT
pipeline. Visibility manifests answer a different question than
comparison policies:

* comparison policy  -> *how* one field should be compared
* visibility manifest -> *whether* one template actually renders that
  field and therefore allows it to be scored at all

A :class:`TemplateVisibilityManifest` enumerates, for one concrete
template identifier, which scoreable field paths are ``VISIBLE`` on
that template and which are ``NOT_RENDERED``. Paths that are absent
from a manifest default to ``NOT_RENDERED`` at the benchmark layer:
that is the safest default and prevents accidental over-scoring when
a manifest is incomplete.

Wildcards: list and dict members use ``[*]`` in manifest paths, mirroring
the same syntax used by :class:`ComparisonPolicy`. :meth:`status_for`
tries the literal path first, then substitutes any concrete ``[<index>]``
or ``[<key>]`` segment with ``[*]`` before falling back, so a single
entry covers every position.

The ``no_pdf`` manifest is the bootstrap/benchmark-only template id for
the pre-PDF stage: every enumerated path is marked ``NOT_RENDERED`` so
that no field is scored until a real renderer exists.

Any breaking change to the manifest JSON encoding must bump
``TEMPLATE_VISIBILITY_SCHEMA_VERSION``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any


TEMPLATE_VISIBILITY_SCHEMA_VERSION = 1
NO_PDF_TEMPLATE_ID = "no_pdf"


# --- Core manifest types --------------------------------------------------


class TemplateVisibilityError(Exception):
    """One error raised while building or applying a visibility manifest."""


class VisibilityStatus(Enum):
    """Whether one field path is rendered by the template."""

    VISIBLE = "visible"
    NOT_RENDERED = "not_rendered"


@dataclass(frozen=True, kw_only=True)
class TemplateVisibilityManifest:
    """Frozen field-path → visibility mapping for one template."""

    template_id: str
    fields: Mapping[str, VisibilityStatus]

    def __post_init__(self) -> None:
        """Require a non-empty template identifier."""

        if not self.template_id:
            raise TemplateVisibilityError(
                "template visibility manifest requires a non-empty template_id"
            )

    def status_for(self, path: str) -> VisibilityStatus | None:
        """Return the status for ``path`` or ``None`` if it is absent.

        Lookup tries the literal path first, then a wildcard form built
        by replacing every ``[<index>]`` or ``[<key>]`` segment with
        ``[*]``. ``None`` means the manifest says nothing about this
        path; callers decide how to interpret that (benchmark scoring
        treats it as ``NOT_RENDERED``).
        """

        status = self.fields.get(path)
        if status is not None:
            return status
        wildcarded = _WILDCARD_PATTERN.sub("[*]", path)
        if wildcarded != path:
            return self.fields.get(wildcarded)
        return None

    def is_visible(self, path: str) -> bool:
        """Return ``True`` only when ``path`` is explicitly ``VISIBLE``.

        Absent paths and ``NOT_RENDERED`` paths both return ``False``.
        """

        return self.status_for(path) is VisibilityStatus.VISIBLE


# --- Default manifest -----------------------------------------------------


def build_no_pdf_visibility_manifest(
    scored_paths: Iterable[str],
) -> TemplateVisibilityManifest:
    """Return the default ``no_pdf`` manifest for the pre-PDF benchmark stage.

    Every path in ``scored_paths`` is marked ``NOT_RENDERED`` so that
    nothing is actually scored until a real renderer exists; duplicates
    are collapsed and the output ordering is deterministic.
    """

    return TemplateVisibilityManifest(
        template_id=NO_PDF_TEMPLATE_ID,
        fields={
            path: VisibilityStatus.NOT_RENDERED
            for path in sorted(set(scored_paths))
        },
    )


_WILDCARD_PATTERN = re.compile(r"\[[^\]]+\]")
_MANIFEST_KEYS = frozenset({"schema_version", "template_id", "fields"})
_MANIFEST_REQUIRED_KEYS = frozenset({"schema_version", "template_id", "fields"})


# --- JSON encoding / decoding ---------------------------------------------


def manifest_to_dict(
    manifest: TemplateVisibilityManifest,
) -> dict[str, Any]:
    """Encode one manifest as a JSON-ready dict with sorted field paths."""

    return {
        "schema_version": TEMPLATE_VISIBILITY_SCHEMA_VERSION,
        "template_id": manifest.template_id,
        "fields": {
            path: status.value
            for path, status in sorted(manifest.fields.items())
        },
    }


def manifest_to_json(manifest: TemplateVisibilityManifest) -> str:
    """Encode one manifest as a deterministic, pretty-printed JSON string."""

    return json.dumps(
        manifest_to_dict(manifest),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )


def manifest_from_dict(data: Any) -> TemplateVisibilityManifest:
    """Decode one manifest from its JSON-ready dict form.

    Rejects unknown top-level keys, missing required keys, unknown
    schema versions, empty template ids, and unknown status strings.
    """

    if not isinstance(data, dict):
        raise TemplateVisibilityError(
            "template visibility payload must be a JSON object"
        )

    extra = sorted(key for key in data if key not in _MANIFEST_KEYS)
    if extra:
        raise TemplateVisibilityError(
            f"template visibility payload has unknown keys: {extra}"
        )

    missing = sorted(_MANIFEST_REQUIRED_KEYS - data.keys())
    if missing:
        raise TemplateVisibilityError(
            f"template visibility payload is missing required keys: {missing}"
        )

    schema_version = data["schema_version"]
    if schema_version != TEMPLATE_VISIBILITY_SCHEMA_VERSION:
        raise TemplateVisibilityError(
            "unsupported template visibility schema_version: "
            f"{schema_version!r}"
        )

    template_id = data["template_id"]
    if not isinstance(template_id, str) or not template_id:
        raise TemplateVisibilityError(
            "template visibility template_id must be a non-empty string"
        )

    fields_raw = data["fields"]
    if not isinstance(fields_raw, dict):
        raise TemplateVisibilityError(
            "template visibility fields must be a JSON object"
        )

    fields: dict[str, VisibilityStatus] = {}
    for path, status_raw in fields_raw.items():
        if not isinstance(path, str) or not path:
            raise TemplateVisibilityError(
                "template visibility fields key must be a non-empty string, "
                f"got {path!r}"
            )
        try:
            status = VisibilityStatus(status_raw)
        except ValueError as exc:
            raise TemplateVisibilityError(
                "template visibility fields"
                f"[{path!r}] has unknown status: {status_raw!r}"
            ) from exc
        fields[path] = status

    return TemplateVisibilityManifest(
        template_id=template_id,
        fields=fields,
    )


def manifest_from_json(text: str) -> TemplateVisibilityManifest:
    """Decode one manifest from its JSON string form.

    Malformed JSON is re-raised as :class:`TemplateVisibilityError` so
    the loader stays a single exception type for callers.
    """

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise TemplateVisibilityError(f"invalid JSON: {exc}") from exc
    return manifest_from_dict(data)
