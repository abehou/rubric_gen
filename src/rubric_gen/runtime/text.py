"""Small text-shape helpers shared across workflows."""


def ensure_trailing_newline(text: str) -> str:
    return text if text.endswith("\n") else text + "\n"


def extract_json_object(text: str) -> str:
    """Extract one outer JSON object, tolerating Markdown fences."""
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("response did not contain a JSON object")
    return stripped[start : end + 1]
