"""Registry of supported native-PDF invoice templates.

Each entry binds a ``template_id`` to the callables that render a shell,
build the template's visibility manifest, and supply the label-anchor
set the extractor should use for PDFs produced by that template.
Callers should go through :func:`get_template` rather than importing the
underlying renderers / builders / anchor dicts directly, so adding a
new template is a single registry edit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from src.input_processing.invoice_text_field_extraction import (
    LabelAnchorSet,
    TEMPLATE_V1_ANCHORS,
    TEMPLATE_V2_ANCHORS,
)
from src.invoice_gen.domain_shell import DomesticVatInvoiceShell
from src.invoice_gen.pdf_rendering import (
    SELLER_BUYER_TEMPLATE_ID,
    SELLER_BUYER_V2_TEMPLATE_ID,
    build_seller_buyer_v2_visibility_manifest,
    build_seller_buyer_visibility_manifest,
    render_seller_buyer_block,
    render_seller_buyer_block_v2,
)
from src.invoice_gen.template_visibility import TemplateVisibilityManifest


@dataclass(frozen=True)
class TemplateSpec:
    """Callables + data a template must supply to be usable end-to-end."""

    template_id: str
    renderer: Callable[[DomesticVatInvoiceShell], bytes]
    visibility_builder: Callable[[], TemplateVisibilityManifest]
    label_anchors: LabelAnchorSet


TEMPLATE_REGISTRY: dict[str, TemplateSpec] = {
    SELLER_BUYER_TEMPLATE_ID: TemplateSpec(
        template_id=SELLER_BUYER_TEMPLATE_ID,
        renderer=render_seller_buyer_block,
        visibility_builder=build_seller_buyer_visibility_manifest,
        label_anchors=TEMPLATE_V1_ANCHORS,
    ),
    SELLER_BUYER_V2_TEMPLATE_ID: TemplateSpec(
        template_id=SELLER_BUYER_V2_TEMPLATE_ID,
        renderer=render_seller_buyer_block_v2,
        visibility_builder=build_seller_buyer_v2_visibility_manifest,
        label_anchors=TEMPLATE_V2_ANCHORS,
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
