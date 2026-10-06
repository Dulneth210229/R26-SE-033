"""
Domain Agent internal schemas.

Purpose:
These schemas are used inside the Domain Agent only. API request schemas
live in app/schemas/domain_schema.py.

Why there is no DomainAgentInput:
Unlike an early placeholder design, run()/revise() resolve the feature,
project, and approved SRS artifact from `store` internally -- the same
convention Requirement Agent and Architecture Agent follow. Callers only
ever pass a feature_id and a request body.
"""

from pydantic import BaseModel


class DomainAgentOutput(BaseModel):
    """
    Internal output returned by DomainAgent's generation step.

    enhanced_srs_markdown:
        Human-readable enhanced SRS, with inline [DOMAIN ADDED]/
        [DOMAIN ENHANCED] tags and a trailing enrichment summary section.

    enhanced_srs_json:
        Full SRS-shaped JSON (same top-level shape as Requirement Agent's
        srs_json) so Architecture/UI-UX/Coder Agents can consume it
        interchangeably with the raw SRS. New/changed items carry inline
        flags (origin, modified_by_domain_agent, domain_citation).

    domain_improvements_json:
        Human-readable "what changed and why" summary, saved as its own
        artifact (ArtifactType.DOMAIN_IMPROVEMENTS).
    """

    enhanced_srs_markdown: str
    enhanced_srs_json: dict
    domain_improvements_json: dict