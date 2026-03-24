"""
Google Gemini / Vertex AI Client (google-genai SDK >= 1.5)
Unterstützt:
  - LLM_PROVIDER=gemini  → Gemini Developer API (API-Key, lokal)
  - LLM_PROVIDER=vertex  → Vertex AI (Service Account, Prod, DSGVO)
"""
import os
from google import genai
from google.genai import types as genai_types
from app.config import settings
import logging

logger = logging.getLogger(__name__)


class GeminiClient:
    """Client für Gemini Developer API oder Vertex AI (neues google-genai SDK)"""

    def __init__(self):
        if settings.llm_provider == "vertex":
            if not settings.vertex_project_id:
                raise ValueError("VERTEX_PROJECT_ID nicht konfiguriert")
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = settings.google_application_credentials
            self.client = genai.Client(
                vertexai=True,
                project=settings.vertex_project_id,
                location=settings.vertex_location,
            )
            self.model_name = settings.vertex_model
            logger.info(f"[LLM: VERTEX AI] Modell: {self.model_name} | Region: {settings.vertex_location} | Projekt: {settings.vertex_project_id}")

        elif settings.llm_provider == "gemini":
            if not settings.gemini_api_key:
                raise ValueError("GEMINI_API_KEY nicht konfiguriert")
            self.client = genai.Client(api_key=settings.gemini_api_key)
            self.model_name = settings.gemini_model
            logger.info(f"[LLM: GEMINI API] Modell: {self.model_name}")

        else:
            raise ValueError(f"GeminiClient erfordert llm_provider=gemini oder vertex, nicht '{settings.llm_provider}'")

    def generate(self, prompt: str) -> str:
        """Einfacher Text-Aufruf (synchron — für run_in_executor geeignet)."""
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=prompt,
        )
        return response.text

    def generate_content(self, prompt: str, system_instruction: str = None) -> str:
        """Text-Aufruf mit optionaler System-Instruction."""
        if system_instruction:
            config = genai_types.GenerateContentConfig(
                system_instruction=system_instruction,
            )
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=config,
            )
        else:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
            )
        return response.text
