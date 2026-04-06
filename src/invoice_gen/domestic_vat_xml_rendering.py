"""Serialize a mapped FA(3) Faktura object into an XML string."""

from __future__ import annotations

from xsdata.formats.dataclass.serializers import XmlSerializer
from xsdata.formats.dataclass.serializers.config import SerializerConfig

from ksef_schema.schemat import Faktura

_serializer = XmlSerializer(config=SerializerConfig(indent="  "))


def render_faktura_to_xml(faktura: Faktura) -> str:
    """Serialize one FA(3) Faktura object to a UTF-8 XML string."""

    return _serializer.render(faktura)
