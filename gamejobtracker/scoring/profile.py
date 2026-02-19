"""User profile data model loaded from profile.yaml."""

from pathlib import Path
import yaml


class CandidateProfile:
    """Structured representation of the candidate's skills and preferences."""

    def __init__(self, profile_data: dict):
        candidate = profile_data.get("candidate", profile_data)
        self.title = candidate.get("title", "")
        self.experience_years = candidate.get("experience_years", 0)
        self.industries = candidate.get("industries", [])
        self.core_skills = candidate.get("core_skills", [])
        self.technical_skills = candidate.get("technical_skills", [])
        self.preferred_titles = candidate.get("preferred_titles", {})
        self.locations = candidate.get("locations", {})
        self.notable_titles = candidate.get("notable_titles", [])

    @classmethod
    def from_config(cls, config: dict) -> "CandidateProfile":
        """Load profile from the merged config dict."""
        return cls(config.get("profile", {}))

    def get_all_skills(self) -> list[str]:
        """Return all skills combined."""
        return self.core_skills + self.technical_skills

    def get_preferred_locations(self) -> list[str]:
        """Return preferred locations."""
        return self.locations.get("preferred", [])

    def get_high_match_titles(self) -> list[str]:
        return self.preferred_titles.get("high_match", [])

    def get_medium_match_titles(self) -> list[str]:
        return self.preferred_titles.get("medium_match", [])

    def get_low_match_titles(self) -> list[str]:
        return self.preferred_titles.get("low_match", [])

    def to_prompt_text(self) -> str:
        """Format the profile as text suitable for an LLM scoring prompt."""
        lines = [
            f"Title: {self.title}",
            f"Experience: {self.experience_years}+ years",
            f"Industries: {', '.join(self.industries)}",
            f"Core skills: {', '.join(self.core_skills)}",
            f"Technical skills: {', '.join(self.technical_skills)}",
            f"Preferred titles: {', '.join(self.get_high_match_titles())}",
            f"Acceptable titles: {', '.join(self.get_medium_match_titles())}",
            f"Preferred locations: {', '.join(self.get_preferred_locations())}",
            f"Notable shipped titles: {', '.join(self.notable_titles)}",
        ]
        return "\n".join(lines)
