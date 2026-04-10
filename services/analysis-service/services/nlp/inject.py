"""Natural language incident injection (P5-2-2).

Parses natural language commands like "Inject a severe security breach
in Terminal B affecting gate B07" into structured incident injection
payloads.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from services.nlp.llm import is_llm_available, llm_chat_json

logger = logging.getLogger(__name__)

# ── LLM system prompt ───────────────────────────────────────

SYSTEM_PROMPT = """You are a parser for airport incident injection commands at Arthur International Airport (KART).

Given a natural language command, extract the incident parameters as JSON:
{
  "type": "security_breach|runway_incursion|system_failure|medical_emergency|baggage_fire|bird_strike|weather_emergency",
  "severity": "low|medium|high|critical",
  "location": "terminal-a|terminal-b|terminal-c|runway-09L|runway-09R|runway-27L|runway-27R|gate-A01|gate-B07|...",
  "description": "Brief description of the incident"
}

Valid incident types: security_breach, runway_incursion, system_failure, medical_emergency, baggage_fire, bird_strike, weather_emergency
Valid severities: low, medium, high, critical
Valid locations: terminal-a, terminal-b, terminal-c, runway-09L, runway-09R, runway-27L, runway-27R, gate-{letter}{number} (e.g. gate-A01..A14, B01..B14, C01..C14)

If the command is not an incident injection request, return:
{"error": "Not an incident injection command"}"""


# ── Template patterns for fallback ───────────────────────────

INCIDENT_TYPES = {
    "security breach": "security_breach",
    "security": "security_breach",
    "runway incursion": "runway_incursion",
    "incursion": "runway_incursion",
    "system failure": "system_failure",
    "failure": "system_failure",
    "medical": "medical_emergency",
    "medical emergency": "medical_emergency",
    "baggage fire": "baggage_fire",
    "fire": "baggage_fire",
    "bird strike": "bird_strike",
    "bird": "bird_strike",
    "weather": "weather_emergency",
}

SEVERITY_PATTERNS = {
    "critical": "critical",
    "severe": "critical",
    "major": "high",
    "high": "high",
    "medium": "medium",
    "moderate": "medium",
    "minor": "low",
    "low": "low",
}

LOCATION_PATTERNS = [
    (re.compile(r"terminal\s*[aA]", re.I), "terminal-a"),
    (re.compile(r"terminal\s*[bB]", re.I), "terminal-b"),
    (re.compile(r"terminal\s*[cC]", re.I), "terminal-c"),
    (re.compile(r"runway\s*09\s*[lL]", re.I), "runway-09L"),
    (re.compile(r"runway\s*09\s*[rR]", re.I), "runway-09R"),
    (re.compile(r"runway\s*27\s*[lL]", re.I), "runway-27L"),
    (re.compile(r"runway\s*27\s*[rR]", re.I), "runway-27R"),
    (re.compile(r"gate\s*([A-C])(\d{1,2})", re.I), None),  # dynamic
]


async def parse_incident_command(command: str) -> dict[str, Any]:
    """Parse a natural language incident injection command.

    Returns a dict with either 'incident' (structured payload) or 'error'.
    """
    if is_llm_available():
        result = await _llm_parse(command)
        if result and "error" not in result:
            return {"incident": result, "source": "llm"}
        if result and "error" in result:
            pass  # Fall through to template

    # Template fallback
    result = _template_parse(command)
    if result:
        return {"incident": result, "source": "template"}

    return {"error": "Could not parse incident command. Try: 'Inject a [severity] [type] in [location]'"}


async def _llm_parse(command: str) -> dict[str, Any] | None:
    """Use LLM to parse the incident command."""
    return await llm_chat_json(SYSTEM_PROMPT, command)


def _template_parse(command: str) -> dict[str, Any] | None:
    """Regex-based incident extraction."""
    text = command.lower()

    # Extract incident type
    incident_type = None
    for phrase, itype in INCIDENT_TYPES.items():
        if phrase in text:
            incident_type = itype
            break
    if not incident_type:
        return None

    # Extract severity
    severity = "medium"  # default
    for phrase, sev in SEVERITY_PATTERNS.items():
        if phrase in text:
            severity = sev
            break

    # Extract location
    location = "terminal-a"  # default
    for pattern, loc in LOCATION_PATTERNS:
        match = pattern.search(command)
        if match:
            if loc is None:
                # Gate pattern
                letter = match.group(1).upper()
                number = match.group(2).zfill(2)
                location = f"gate-{letter}{number}"
            else:
                location = loc
            break

    return {
        "type": incident_type,
        "severity": severity,
        "location": location,
        "description": f"NL-injected: {command}",
    }
