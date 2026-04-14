"""Test fixtures — raw PDF inputs for integration tests.

Three fixture categories exercise the main route families:

- simple_text.pdf: Text-heavy, single-column, simple layout → fast_text_route
- dual_column_or_formula.pdf: Two-column layout with text → complex_pdf_route
- ocr_like.pdf: Image-heavy, minimal text → ocr_heavy_route
"""
