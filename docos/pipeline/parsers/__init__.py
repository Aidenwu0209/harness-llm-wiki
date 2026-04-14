"""Parsers package — concrete parser backend implementations."""

from docos.pipeline.parsers.basic_text import BasicTextFallbackParser
from docos.pipeline.parsers.stdlib_pdf import StdlibPDFParser

__all__ = ["BasicTextFallbackParser", "StdlibPDFParser"]
