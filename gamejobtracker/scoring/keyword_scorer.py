"""Keyword-based job scorer — fast, free, no API needed."""

import logging
import re

from gamejobtracker.scoring.profile import CandidateProfile

logger = logging.getLogger(__name__)

# Title keyword scores — how relevant is this job title?
TITLE_SCORES = {
    "level designer": 1.0,
    "world designer": 1.0,
    "senior level designer": 1.0,
    "lead level designer": 1.0,
    "senior world designer": 1.0,
    "lead world designer": 1.0,
    "principal level designer": 1.0,
    "environment designer": 0.85,
    "technical level designer": 0.85,
    "technical designer": 0.6,
    "game designer": 0.55,
    "content designer": 0.5,
    "quest designer": 0.45,
    "encounter designer": 0.45,
    "narrative designer": 0.3,
    "systems designer": 0.3,
    "combat designer": 0.6,
    "multiplayer designer": 0.5,
}

SENIORITY_SCORES = {
    "principal": 1.0,
    "staff": 0.95,
    "senior": 1.0,
    "lead": 1.0,
    "sr.": 1.0,
    "sr ": 1.0,
    "director": 0.7,
    "manager": 0.5,
    "mid": 0.5,
    "ii": 0.5,
    "iii": 0.8,
    "junior": 0.1,
    "jr.": 0.1,
    "jr ": 0.1,
    "entry": 0.05,
    "intern": 0.0,
    "associate": 0.2,
}

SKILL_KEYWORDS = [
    ("unreal engine", 1.0),
    ("unreal", 0.9),
    ("ue5", 1.0),
    ("ue4", 0.9),
    ("blueprints", 0.8),
    ("pcg", 0.7),
    ("procedural content generation", 0.8),
    ("open world", 0.9),
    ("open-world", 0.9),
    ("encounter design", 0.9),
    ("level blockout", 0.9),
    ("blockout", 0.8),
    ("greybox", 0.8),
    ("whitebox", 0.8),
    ("environmental storytelling", 0.85),
    ("combat design", 0.8),
    ("combat space", 0.85),
    ("player flow", 0.8),
    ("metrics", 0.5),
    ("readability", 0.6),
    ("dungeon", 0.8),
    ("mmo", 0.7),
    ("mmorpg", 0.75),
    ("rpg", 0.7),
    ("live service", 0.6),
    ("live-service", 0.6),
    ("pvp", 0.6),
    ("multiplayer", 0.5),
    ("narrative", 0.4),
    ("aaa", 0.7),
    ("lua", 0.5),
    ("python", 0.4),
    ("c#", 0.4),
    ("perforce", 0.4),
    ("jira", 0.3),
]


class KeywordScorer:
    """Rule-based scoring with weighted keyword matching."""

    def __init__(self, profile: CandidateProfile):
        self.profile = profile

    def score_job(self, title: str, description: str | None, location: str | None, is_remote: bool) -> tuple[float, str]:
        """Score a job based on keyword matching.

        Returns (score: 0.0-1.0, reasoning: str).
        """
        title_score = self._score_title(title)
        seniority_score = self._score_seniority(title, description)
        skills_score = self._score_skills(description or "")
        location_score = self._score_location(location, is_remote)

        combined = (
            title_score * 0.35
            + seniority_score * 0.20
            + skills_score * 0.30
            + location_score * 0.15
        )

        # Clamp to 0-1
        combined = max(0.0, min(1.0, combined))

        reasoning = (
            f"Title: {title_score:.2f}, "
            f"Seniority: {seniority_score:.2f}, "
            f"Skills: {skills_score:.2f}, "
            f"Location: {location_score:.2f}"
        )

        return combined, reasoning

    def _score_title(self, title: str) -> float:
        """Score based on how well the job title matches desired roles."""
        title_lower = title.lower()
        best_score = 0.0

        for keyword, score in TITLE_SCORES.items():
            if keyword in title_lower:
                best_score = max(best_score, score)

        return best_score

    def _score_seniority(self, title: str, description: str | None) -> float:
        """Score based on seniority level match."""
        text = (title + " " + (description[:500] if description else "")).lower()
        best_score = 0.5  # Default: assume mid-level if unspecified

        for keyword, score in SENIORITY_SCORES.items():
            if keyword in text:
                best_score = max(best_score, score)

        return best_score

    def _score_skills(self, description: str) -> float:
        """Score based on skill keyword overlap in description."""
        if not description:
            return 0.3  # Neutral when no description available

        desc_lower = description.lower()
        matched_scores = []

        for keyword, weight in SKILL_KEYWORDS:
            if keyword in desc_lower:
                matched_scores.append(weight)

        if not matched_scores:
            return 0.1

        # Average of top skills matched, weighted by count
        matched_scores.sort(reverse=True)
        top_scores = matched_scores[:10]  # Cap to prevent over-weighting
        avg = sum(top_scores) / len(top_scores)

        # Bonus for having many matches (breadth)
        breadth_bonus = min(0.2, len(matched_scores) * 0.02)

        return min(1.0, avg + breadth_bonus)

    def _score_location(self, location: str | None, is_remote: bool) -> float:
        """Score based on location compatibility."""
        if is_remote:
            return 1.0

        if not location:
            return 0.5  # Unknown location — neutral

        loc_lower = location.lower()
        preferred = [loc.lower() for loc in self.profile.get_preferred_locations()]

        for pref in preferred:
            if pref in loc_lower or loc_lower in pref:
                return 1.0

        # Check acceptable locations
        acceptable = [loc.lower() for loc in self.profile.locations.get("acceptable", [])]
        for acc in acceptable:
            if acc in loc_lower or loc_lower in acc:
                return 0.7

        return 0.2  # Unmatched location
