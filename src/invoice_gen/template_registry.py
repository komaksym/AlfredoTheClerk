"""Registry of supported native-PDF invoice templates.

Each entry binds a ``template_id`` to the callables that render a shell
and build the template's visibility manifest. Callers that today reach
for ``render_seller_buyer_block`` or
``build_seller_buyer_visibility_manifest`` directly should go through
:func:`get_template` instead, so adding a second template in M5 is a
registry edit rather than a scatter of caller updates.

Label anchors for the extractor will be added to
:class:`TemplateSpec` when the extractor is parameterized in a later
M5 step; keeping this file minimal today keeps the refactor diff
small.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from src.invoice_gen.domain_shell import DomesticVatInvoiceShell
from src.invoice_gen.pdf_rendering import (
    SELLER_BUYER_TEMPLATE_ID,
    build_seller_buyer_visibility_manifest,
    render_seller_buyer_block,
)
from src.invoice_gen.template_visibility import TemplateVisibilityManifest


@dataclass(frozen=True)
class TemplateSpec:
    """Callables a template must supply to be usable end-to-end."""

    template_id: str
    renderer: Callable[[DomesticVatInvoiceShell], bytes]
    visibility_builder: Callable[[], TemplateVisibilityManifest]


TEMPLATE_REGISTRY: dict[str, TemplateSpec] = {
    SELLER_BUYER_TEMPLATE_ID: TemplateSpec(
        template_id=SELLER_BUYER_TEMPLATE_ID,
        renderer=render_seller_buyer_block,
        visibility_builder=build_seller_buyer_visibility_manifest,
    ),
}


def get_template(template_id: str) -> TemplateSpec:
    """Look up a :class:`TemplateSpec` by ``template_id``.

    Raises :class:`KeyError` with the list of registered ids when the
    lookup fails, so the caller sees what is available instead of a
    bare ``KeyError('foo')``.
    """

    try:
        return TEMPLATE_REGISTRY[template_id]
    except KeyError:
        registered = ", ".join(sorted(TEMPLATE_REGISTRY)) or "<none>"
        raise KeyError(
            f"unknown template_id {template_id!r}; registered: {registered}"
        ) from None
