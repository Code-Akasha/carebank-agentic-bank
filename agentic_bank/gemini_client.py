from __future__ import annotations

import json
import logging
from typing import Any

from .config import get_settings

logger = logging.getLogger(__name__)


class GeminiClient:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._client = None
        if self._settings.gemini_api_key:
            try:
                import google.generativeai as genai

                genai.configure(api_key=self._settings.gemini_api_key)
                self._client = genai.GenerativeModel(self._settings.gemini_model)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Gemini client init failed: %s", exc)
                self._client = None

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def generate_json(self, *, schema_hint: Any, context: dict[str, Any]) -> Any | None:
        if not self._client:
            return None

        prompt = (
            "You are a banking proxy. Return JSON only. "
            "Do not include markdown. Ensure response matches the schema example.\n"
            f"Schema example:\n{json.dumps(schema_hint, indent=2)}\n\n"
            f"Request context:\n{json.dumps(context, indent=2)}\n"
        )

        try:
            result = self._client.generate_content(
                prompt,
                generation_config={
                    "temperature": 0.2,
                    "response_mime_type": "application/json",
                },
            )
            text = getattr(result, "text", None) or ""
            return _extract_json(text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Gemini generation failed: %s", exc)
            return None


def _extract_json(text: str) -> Any | None:
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned.replace("json", "", 1).strip()
    for start in ("{", "["):
        idx = cleaned.find(start)
        if idx != -1:
            cleaned = cleaned[idx:]
            break
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return None
