"""LLM-based structured fact extractor."""
import logging
import os
from pathlib import Path
from typing import Any, Optional

from jinja2 import Environment, FileSystemLoader

from extractor.schemas import AnyFact, parse_facts

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_system_prompt() -> str:
    return (_PROMPTS_DIR / "extraction_system.txt").read_text(encoding="utf-8")


def _render_user_prompt(
    page_url: str,
    page_type: str,
    page_score: int,
    page_text: str,
    industry: str,
) -> str:
    env = Environment(loader=FileSystemLoader(str(_PROMPTS_DIR)))
    template = env.get_template("extraction_user.jinja")
    return template.render(
        page_url=page_url,
        page_type=page_type,
        page_score=page_score,
        page_text=page_text[:8000],  # token safety ceiling
        industry=industry,
    )


class FactExtractor:
    def __init__(self, llm_client: Any):
        self._client = llm_client
        self._system_prompt = _load_system_prompt()

    def extract(
        self,
        page_text: str,
        page_url: str,
        page_type: str,
        page_score: int,
        industry: str,
    ) -> list[AnyFact]:
        user_prompt = _render_user_prompt(
            page_url=page_url,
            page_type=page_type,
            page_score=page_score,
            page_text=page_text,
            industry=industry,
        )
        try:
            response = self._client.chat.completions.create(
                messages=[
                    {"role": "system", "content": self._system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                model=os.environ.get("LLM_MODEL_DIRECT", "gemini-2.5-flash"),
            )
            raw_content = response.choices[0].message.content
            return parse_facts(raw_content)
        except Exception as exc:
            logger.error("LLM extraction failed for %s: %s", page_url, exc)
            return []
