"""External service clients used by BiomniBench workflows."""

from .gemini import GeminiClient, GeminiGenerateContentResponse

__all__ = ["GeminiClient", "GeminiGenerateContentResponse"]
