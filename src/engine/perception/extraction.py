"""Fact extraction from conversations — purely regex-based, no LLM calls."""

from __future__ import annotations

import re
import time


# Common non-name words to filter
_STOP_WORDS = {
    "the", "and", "but", "for", "not", "you", "all", "can", "had", "her",
    "was", "one", "our", "out", "are", "has", "his", "how", "its", "may",
    "new", "now", "old", "see", "way", "who", "did", "get", "let", "say",
    "she", "too", "use", "yes", "hey", "hello", "good", "sure", "well",
    "here", "there", "just", "that", "this", "what", "when", "where",
    "will", "with", "about", "been", "have", "from", "they", "know",
    "want", "been", "call", "come", "each", "make", "like", "long",
    "look", "many", "some", "them", "then", "very", "would", "could",
    "should", "into", "over", "such", "take", "than", "also", "back",
    "only", "other", "time", "help", "nice", "great", "think",
}


def extract_person_name(transcript: str) -> str | None:
    """Extract a person's name from a transcript.

    Patterns: "I'm X", "my name is X", "call me X", "X here", "this is X".
    Returns name or None.
    """
    if not transcript:
        return None

    patterns = [
        r"(?:I'm|I am|i'm|i am)\s+([A-Z][a-z]{1,15})",
        r"(?:my name is|my name's)\s+([A-Z][a-z]{1,15})",
        r"(?:call me|they call me)\s+([A-Z][a-z]{1,15})",
        r"(?:this is|it's)\s+([A-Z][a-z]{1,15})\b(?:\s+here|\s+speaking)?",
        r"^([A-Z][a-z]{1,15})\s+here\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, transcript)
        if match:
            name = match.group(1)
            if name.lower() not in _STOP_WORDS and len(name) > 1:
                return name

    return None


def extract_facts(transcript: str, response: str = "", person: str | None = None) -> list[dict]:
    """Extract factual statements from a conversation.

    Patterns for schedules, preferences, possessions, identity.
    Returns list of fact dicts with auto-generated tags.
    """
    facts = []

    if not transcript:
        return facts

    # Schedule patterns: "at 3pm", "tomorrow at", "every Monday"
    schedule_patterns = [
        r"(?:at|by|around|before|after)\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM))",
        r"(?:every|each)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday|morning|evening|week|day)",
        r"(?:tomorrow|tonight|later today|this afternoon|this evening|next week)",
    ]
    for pattern in schedule_patterns:
        match = re.search(pattern, transcript, re.IGNORECASE)
        if match:
            # Extract surrounding context (up to 60 chars around match)
            start = max(0, match.start() - 20)
            end = min(len(transcript), match.end() + 40)
            context = transcript[start:end].strip()
            facts.append({
                "time": time.time(),
                "source": "conversation",
                "text": context,
                "tags": ["schedule"],
                "person": person,
            })
            break  # One schedule fact per utterance

    # Preference patterns: "I like", "I love", "I hate", "I prefer", "my favorite"
    pref_patterns = [
        (r"(?:I|i)\s+(?:like|love|enjoy|prefer)\s+(.{3,50}?)(?:\.|,|!|\?|$)", "likes"),
        (r"(?:I|i)\s+(?:hate|dislike|don't like|can't stand)\s+(.{3,50}?)(?:\.|,|!|\?|$)", "dislikes"),
        (r"(?:my|My)\s+favorite\s+(?:\w+\s+)?(?:is|are)\s+(.{3,40}?)(?:\.|,|!|\?|$)", "likes"),
    ]
    for pattern, tag in pref_patterns:
        match = re.search(pattern, transcript)
        if match:
            facts.append({
                "time": time.time(),
                "source": "conversation",
                "text": match.group(0).strip(),
                "tags": ["preference", tag],
                "person": person,
            })

    # Possession patterns: "I have", "I own", "I got"
    poss_patterns = [
        r"(?:I|i)\s+(?:have|own|got|bought)\s+(?:a|an|the|some|my)?\s*(.{3,40}?)(?:\.|,|!|\?|$)",
    ]
    for pattern in poss_patterns:
        match = re.search(pattern, transcript)
        if match:
            item = match.group(1).strip()
            if len(item) > 3 and not any(w in item.lower() for w in ("question", "problem", "idea")):
                facts.append({
                    "time": time.time(),
                    "source": "conversation",
                    "text": match.group(0).strip(),
                    "tags": ["possession"],
                    "person": person,
                })

    # Identity patterns: "I'm a", "I work as", "I'm from"
    identity_patterns = [
        r"(?:I'm|I am|i'm|i am)\s+(?:a|an)\s+(\w+(?:\s+\w+)?)",
        r"(?:I|i)\s+(?:work|works)\s+(?:as|at|in|for)\s+(.{3,40}?)(?:\.|,|!|\?|$)",
        r"(?:I'm|I am|i'm|i am)\s+from\s+(.{3,30}?)(?:\.|,|!|\?|$)",
    ]
    for pattern in identity_patterns:
        match = re.search(pattern, transcript)
        if match:
            facts.append({
                "time": time.time(),
                "source": "conversation",
                "text": match.group(0).strip(),
                "tags": ["identity"],
                "person": person,
            })

    return facts
