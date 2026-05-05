"""Unit tests for the template registry introduced in M5 slice 1."""

from __future__ import annotations

import pytest

from src.input_processing.invoice_text_field_extraction import (
    TEMPLATE_V1_ANCHORS,
    TEMPLATE_V2_ANCHORS,
)
from src.invoice_gen.pdf_rendering import (
    SELLER_BUYER_TEMPLATE_ID,
    SELLER_BUYER_V2_TEMPLATE_ID,
    build_seller_buyer_v2_visibility_manifest,
    build_seller_buyer_visibility_manifest,
    render_seller_buyer_block,
    render_seller_buyer_block_v2,
)
from src.invoice_gen.template_registry import (
    TEMPLATE_REGISTRY,
    TemplateSpec,
    get_template,
)


def test_both_templates_are_registered() -> None:
    """v1 and v2 must both be registered for M5 Slice 1."""

    assert set(TEMPLATE_REGISTRY) == {
        SELLER_BUYER_TEMPLATE_ID,
        SELLER_BUYER_V2_TEMPLATE_ID,
    }


def test_v1_spec_binds_expected_callables_and_anchors() -> None:
    """The v1 spec must point at the v1 renderer, builder, and anchors."""

    spec = get_template(SELLER_BUYER_TEMPLATE_ID)

    assert isinstance(spec, TemplateSpec)
    assert spec.template_id == SELLER_BUYER_TEMPLATE_ID
    assert spec.renderer is render_seller_buyer_block
    assert spec.visibility_builder is build_seller_buyer_visibility_manifest
    assert spec.label_anchors is TEMPLATE_V1_ANCHORS


def test_v2_spec_binds_expected_callables_and_anchors() -> None:
    """The v2 spec must point at v2-specific callables and its own anchors."""

    spec = get_template(SELLER_BUYER_V2_TEMPLATE_ID)

    assert isinstance(spec, TemplateSpec)
    assert spec.template_id == SELLER_BUYER_V2_TEMPLATE_ID
    assert spec.renderer is render_seller_buyer_block_v2
    assert spec.visibility_builder is build_seller_buyer_v2_visibility_manifest
    assert spec.label_anchors is TEMPLATE_V2_ANCHORS


def test_each_template_has_its_own_anchors() -> None:
    """v1 and v2 anchor dicts must be distinct objects with divergent values."""

    v1_anchors = get_template(SELLER_BUYER_TEMPLATE_ID).label_anchors
    v2_anchors = get_template(SELLER_BUYER_V2_TEMPLATE_ID).label_anchors

    assert v1_anchors is not v2_anchors
    assert v1_anchors["seller"] != v2_anchors["seller"]
    assert v1_anchors["buyer"] != v2_anchors["buyer"]
    assert v1_anchors["invoice_number"] != v2_anchors["invoice_number"]


def test_get_template_raises_for_unknown_id() -> None:
    """Unknown template_ids must list the registered ids in the error."""

    with pytest.raises(KeyError) as excinfo:
        get_template("no_such_template")

    message = str(excinfo.value)
    assert "no_such_template" in message
    assert SELLER_BUYER_TEMPLATE_ID in message
    assert SELLER_BUYER_V2_TEMPLATE_ID in message
