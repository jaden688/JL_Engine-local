from __future__ import annotations

import math
import re
from dataclasses import dataclass


@dataclass
class TurnSignals:
    """Lightweight per-turn signals derived from user text."""

    sentiment: float  # -1..1
    arousal: float  # 0..1
    directive: bool  # user wants brevity/precision
    confusion: float  # 0..1
    pace: float  # 0..1 (0=slow,1=fast)
    memory_density: float  # 0..1 suggested memory pressure


class SignalScorer:
    """
    Heuristic scorer for a single user message.
    Avoids external models; uses simple lexical cues + length.
    """

    POS_WORDS = {
        "great",
        "awesome",
        "thanks",
        "good",
        "fantastic",
        "excellent",
        "happy",
        "joy",
        "wonderful",
        "brilliant",
        "support",
        "clarity",
        "help",
        "solve",
        "guide",
        "create",
        "build",
        "innovate",
        "progress",
        "success",
        "win",
        "improve",
        "calm",
        "relaxed",
        "relief",
        "confident",
        "thankful",
        "appreciate",
        "grateful",
        "team",
        "collaborate",
        "ally",
        "energized",
        "motivated",
        "inspired",
        "bright",
        "spark",
        "positive",
        "optimistic",
        "steady",
        "resilient",
        "glad",
        "hopeful",
        "focus",
        "clarify",
        "achieve",
        "resolve",
        "empower",
        "assist",
    }
    NEG_WORDS = {
        "bad",
        "hate",
        "angry",
        "annoyed",
        "frustrated",
        "upset",
        "broken",
        "issue",
        "problem",
        "confused",
        "lost",
        "stuck",
        "sad",
        "terrible",
        "awful",
        "worst",
        "fail",
        "error",
        "panic",
        "worry",
        "anxiety",
        "fear",
        "hurt",
        "tired",
        "exhausted",
        "depressed",
        "miserable",
        "scared",
        "danger",
        "crash",
        "stop",
        "delay",
        "weak",
        "stress",
        "tension",
        "dread",
        "overwhelmed",
        "rude",
        "hostile",
        "suck",
    }
    DIRECTIVE_PHRASES = {
        "be concise",
        "just answer",
        "short answer",
        "no fluff",
        "get to the point",
        "bullet points",
        "keep it short",
        "fast summary",
        "direct answer",
        "only the essentials",
        "tell me the facts",
        "focus",
        "minimal words",
        "skip the fluff",
        "straight answer",
        "rapid response",
    }
    CONFUSE_WORDS = {
        "confused",
        "lost",
        "stuck",
        "don't get",
        "not sure",
        "unclear",
        "huh",
        "what",
        "why",
        "help",
    }

    def score(self, text: str) -> TurnSignals:
        t = text.lower()
        words = re.findall(r"[a-z']+", t)
        wlen = len(words)

        pos_hits = sum(1 for w in words if w in self.POS_WORDS)
        neg_hits = sum(1 for w in words if w in self.NEG_WORDS)
        sentiment = (pos_hits - neg_hits) / max(1, wlen)
        sentiment = max(-1.0, min(1.0, sentiment * 6.0))  # scale up, clamp

        directive = any(phrase in t for phrase in self.DIRECTIVE_PHRASES)
        confusion_hits = sum(1 for w in words if w in self.CONFUSE_WORDS) + t.count("?")
        confusion = max(0.0, min(1.0, confusion_hits / max(3, wlen)))

        # crude arousal: exclamations + uppercase + length
        exclaim = t.count("!")
        upper_hits = sum(1 for w in words if len(w) > 1 and w.isupper())
        arousal = (
            (wlen * 0.04)  # ~0.4 at 10 words
            + (0.25 if exclaim > 0 else 0.0)
            + max(0, exclaim - 1) * 0.05  # extra boost for multiple !
            + (0.20 if upper_hits > 0 else 0.0)
        )
        arousal = max(0.0, min(1.0, arousal))

        # pace: based on brevity (shorter = faster) plus exclamations
        pace = (min(wlen, 30) / 30.0) + (0.10 if exclaim > 0 else 0.0)  # 0..1 over first 30 words
        pace = max(0.0, min(1.0, pace))

        # memory density suggestion: longer + more questions => higher
        memory_density = (wlen / 35.0) + (confusion_hits * 0.08)  # ~0.3 at 10 words, ~0.57 at 20
        memory_density = max(0.0, min(1.0, memory_density))

        return TurnSignals(
            sentiment=sentiment,
            arousal=arousal,
            directive=directive,
            confusion=confusion,
            pace=pace,
            memory_density=memory_density,
        )


if __name__ == "__main__":
    # Example usage and testing block
    scorer = SignalScorer()
    test_phrases = [
        "That's great, thanks!",
        "This is TERRIBLE, I hate it. It's so frustrating and broken.",
        "Just give me the answer, be concise.",
        "I'm a bit confused, why is that? Can you explain?",
        "WOW that's amazing, I love it! SO COOL!",
        "ok",
        "What?",
        "I don't get it, I'm stuck. This is awful.",
    ]

    for phrase in test_phrases:
        signals = scorer.score(phrase)
        print(f'Text: "{phrase}"')
        # Print signals rounded to 2 decimal places for readability
        for signal, value in signals.__dict__.items():
            val = f"{value:.2f}" if isinstance(value, float) else value
            print(f"  - {signal}: {val}")
        print("-" * 20)
