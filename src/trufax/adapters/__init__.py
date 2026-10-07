from .base import Adapter
from .html import HtmlAdapter
from .json_api import JsonAdapter
from .pdf import PdfAdapter
from .spreadsheet import SpreadsheetAdapter
from .xml import XmlAdapter

ADAPTERS: dict[str, type[Adapter]] = {
    "html": HtmlAdapter,
    "pdf": PdfAdapter,
    "xml": XmlAdapter,
    "json": JsonAdapter,
    "spreadsheet": SpreadsheetAdapter,
}

__all__ = ["ADAPTERS", "Adapter"]
