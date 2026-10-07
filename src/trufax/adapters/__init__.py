from .base import Adapter
from .html import HtmlAdapter
from .pdf import PdfAdapter
from .xml import XmlAdapter

ADAPTERS: dict[str, type[Adapter]] = {
    "html": HtmlAdapter,
    "pdf": PdfAdapter,
    "xml": XmlAdapter,
}

__all__ = ["ADAPTERS", "Adapter"]
