"""
relevant_dom package
====================
Contains the RelevantDOMBuilder — the Domain-Aware HTML filter.

Its only job: decide which sections of a cleaned HTML page are worth
sending to Gemini. It never extracts business values.
"""

from modules.relevant_dom.builder import RelevantDOMBuilder

__all__ = ["RelevantDOMBuilder"]
