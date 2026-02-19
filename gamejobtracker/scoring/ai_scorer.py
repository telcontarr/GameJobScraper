"""AI-powered job scorer using the Anthropic Claude API."""

import json
import logging

import anthropic

from gamejobtracker.scoring.profile import CandidateProfile
from gamejobtracker.utils.text_processing import truncate

logger = logging.getLogger(__name__)


class AIScorer:
    """Scores jobs using Claude API for nuanced matching."""

    def __init__(self, config: dict, profile: CandidateProfile):
        api_key = config.get("api_keys", {}).get("anthropic", "")
        self.client = anthropic.Anthropic(api_key=api_key) if api_key else None
        self.profile = profile
        self.model = (
            config.get("scoring", {}).get("ai_model", "claude-sonnet-4-20250514")
        )

    def is_available(self) -> bool:
        return self.client is not None

    def score_job(
        self, title: str, company: str, location: str | None, description: str | None
    ) -> tuple[float, str]:
        """Score a single job against the candidate profile.

        Returns (score: 0.0-1.0, reasoning: str).
        """
        if not self.client:
            return 0.0, "AI scorer unavailable (no API key)"

        prompt = self._build_prompt(title, company, location, description)

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}],
            )
            return self._parse_response(response.content[0].text)
        except anthropic.APIError:
            logger.exception("Claude API error while scoring '%s' at '%s'", title, company)
            return 0.0, "AI scoring failed (API error)"
        except Exception:
            logger.exception("Unexpected error in AI scorer")
            return 0.0, "AI scoring failed (unexpected error)"

    def _build_prompt(
        self, title: str, company: str, location: str | None, description: str | None
    ) -> str:
        profile_text = self.profile.to_prompt_text()
        desc_truncated = truncate(description or "No description available", 3000)

        return f"""You are a job-matching assistant. Score how well this job posting matches the candidate profile below.

CANDIDATE PROFILE:
{profile_text}

JOB LISTING:
Title: {title}
Company: {company}
Location: {location or "Not specified"}
Description:
{desc_truncated}

Score this job from 0.0 to 1.0 based on:
1. Title relevance — is this a level/world/environment design role?
2. Seniority match — senior or lead level preferred, mid-level acceptable
3. Industry match — games industry required
4. Skills overlap — Unreal Engine, open-world, encounter design, etc.
5. Location compatibility — Remote, Boston MA, or Providence RI preferred

Respond ONLY with valid JSON, no other text:
{{"score": 0.85, "reasoning": "One sentence explaining the match quality"}}"""

    def _parse_response(self, text: str) -> tuple[float, str]:
        """Parse the JSON response from the LLM."""
        try:
            # Handle potential markdown code fences
            cleaned = text.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1]
                cleaned = cleaned.rsplit("```", 1)[0]
            cleaned = cleaned.strip()

            data = json.loads(cleaned)
            score = float(data.get("score", 0))
            reasoning = str(data.get("reasoning", ""))
            score = max(0.0, min(1.0, score))
            return score, reasoning
        except (json.JSONDecodeError, ValueError, KeyError):
            logger.warning("Failed to parse AI response: %s", text[:200])
            return 0.0, f"Parse error: {text[:100]}"
