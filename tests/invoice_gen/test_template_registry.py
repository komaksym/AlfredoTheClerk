"""Unit tests for the template registry introduced in M5 slice 1."""

from __future__ import annotations

import pytest

from src.invoice_gen.pdf_rendering import (
    SELLER_BUYER_TEMPLATE_ID,
    build_seller_buyer_visibility_manifest,
    render_seller_buyer_block,
)
from src.invoice_gen.template_registry import (
    TEMPLATE_REGISTRY,
    TemplateSpec,
    get_template,
)


def test_seller_buyer_v1_is_registered() -> None:
    """The v1 template must be registered so existing callers keep working."""

    assert SELLER_BUYER_TEMPLATE_ID in TEMPLATE_REGISTRY


def test_registry_spec_binds_expected_callables() -> None:
    """The v1 spec should point at the same callables the registry wraps."""

    spec = get_template(SELLER_BUYER_TEMPLATE_ID)

    assert isinstance(spec, TemplateSpec)
    assert spec.template_id == SELLER_BUYER_TEMPLATE_ID
    assert spec.renderer is render_seller_buyer_block
    assert spec.visibility_builder is build_seller_buyer_visibility_manifest


def test_get_template_raises_for_unknown_id() -> None:
    """Unknown template_ids must list the registered ids in the error."""

    with pytest.raises(KeyError) as excinfo:
        get_template("no_such_template")

    message = str(excinfo.value)
    assert "no_such_template" in message
    assert SELLER_BUYER_TEMPLATE_ID in message
