"""One dated registry for every locally estimated provider price."""

from __future__ import annotations


PRICING_AS_OF = "2026-08-17"
PRICING_SOURCES = {
    "openai": "https://developers.openai.com/api/docs/pricing",
    "anthropic": "https://platform.claude.com/docs/en/about-claude/pricing",
    "google": "https://ai.google.dev/gemini-api/docs/pricing",
}

OPENAI_PRIORITY_MULTIPLIER = 2.0
OPENAI_LONG_CONTEXT_THRESHOLD = 272_000
OPENAI_LONG_INPUT_MULTIPLIER = 2.0
OPENAI_LONG_OUTPUT_MULTIPLIER = 1.5

OPENAI_PRICES_PER_MILLION = {
    "gpt-5.6-luna": {
        "input": 0.2,
        "cached": 0.02,
        "cache_write": 0.25,
        "output": 1.2,
    },
    "gpt-5.6-terra": {
        "input": 2.0,
        "cached": 0.2,
        "cache_write": 2.5,
        "output": 12.0,
    },
    "gpt-5.6-sol": {
        "input": 5.0,
        "cached": 0.5,
        "cache_write": 6.25,
        "output": 30.0,
    },
}

ANTHROPIC_PRICES_PER_MILLION = {
    "claude-opus-5": {
        "input": 5.0,
        "cached": 0.5,
        "cache_write": 6.25,
        "output": 25.0,
    },
    "claude-opus-4-8": {
        "input": 5.0,
        "cached": 0.5,
        "cache_write": 6.25,
        "output": 25.0,
    },
}

GEMINI_PRICES_PER_MILLION = {
    "gemini-3.5-flash": {
        "input": 1.5,
        "cached": 0.15,
        "output": 9.0,
    },
    "gemini-3.1-pro-preview": {
        "input": 2.0,
        "cached": 0.2,
        "output": 12.0,
        "long_input": 4.0,
        "long_cached": 0.4,
        "long_output": 18.0,
        "long_threshold": 200_000.0,
    },
}

HOSTED_PRICES_PER_MILLION = {
    **OPENAI_PRICES_PER_MILLION,
    **ANTHROPIC_PRICES_PER_MILLION,
    **GEMINI_PRICES_PER_MILLION,
}

# Terminal Gemini sessions expose cumulative model totals rather than
# per-request context lengths. Use the published long-context tier for Pro,
# which makes this estimate conservative for short requests.
GEMINI_TERMINAL_PRICES_PER_MILLION = {
    "gemini-3.1-pro-preview": {
        "input": 4.00,
        "output": 18.00,
        "cached": 0.40,
    },
    "gemini-3.1-pro-preview-customtools": {
        "input": 4.00,
        "output": 18.00,
        "cached": 0.40,
    },
    "gemini-3.5-flash": {"input": 1.50, "output": 9.00, "cached": 0.15},
    "gemini-3.1-flash-lite": {
        "input": 0.25,
        "output": 1.50,
        "cached": 0.025,
    },
    "gemini-3-flash-preview": {
        "input": 0.50,
        "output": 3.00,
        "cached": 0.05,
    },
    "gemini-3-flash": {"input": 0.50, "output": 3.00, "cached": 0.05},
}
