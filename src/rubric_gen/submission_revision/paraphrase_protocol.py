"""Own the structure-preserving rubric wording protocol."""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass

from rubric_gen.artifacts.hashing import sha256_text
from rubric_gen.submission_revision.judging.scoring import parse_rubric_levels_strict


PARAPHRASE_RUN_KIND = "rubric-gen-shared-rubric-paraphrase-pool"
PARAPHRASE_PROTOCOL = "wording-only-rubric-paraphrase"
PARAPHRASE_MAX_OUTPUT_TOKENS = 32_768
PARAPHRASE_VARIANT_KIND = "sealed-wording-only-rubric-paraphrase"
LEAF_ID_PATTERN = re.compile(r"^PaperBench leaf ID:\s*(\S+)\s*$", re.MULTILINE)
CRITERION_HEADER_PATTERN = re.compile(
    r"^(?P<prefix>[ \t]*Criterion[ \t]+(?P<number>\d+)[ \t]*:[ \t]*)"
    r"(?P<text>\S[^\r\n]*?)(?P<suffix>[ \t]*)$",
    re.MULTILINE,
)
_DESCRIPTION_LINE = re.compile(
    r"^(?P<prefix>[ \t]*Description:[ \t]*)"
    r"(?P<text>\S[^\r\n]*?)(?P<suffix>[ \t]*)$",
    re.MULTILINE,
)
_LEVELS_LINE = re.compile(r"^[ \t]*Levels:[ \t]*[^\r\n]+$", re.MULTILINE)
_LEVEL_DESCRIPTION = re.compile(
    r"^(?P<prefix>[ \t]*\[(?P<label>[A-Z])\]:[ \t]*)"
    r"(?P<text>\S[^\r\n]*)$",
    re.MULTILINE,
)
_FIXED_PREAMBLE_LINE = re.compile(
    r"^(?:[ \t]*RUBRIC:|[ \t]*#{1,6}[ \t]+|[ \t]*Total Points:|"
    r"[ \t]*CRITERIA(?:[ \t]|\()|[ \t]*Scoring protocol:|"
    r"[ \t]*Score normalization maximum:)"
)
_PREFIXED_PREAMBLE_LINE = re.compile(
    r"^(?P<prefix>[ \t]*(?:Notes|Purpose):[ \t]*)"
    r"(?P<text>\S[^\r\n]*?)(?P<suffix>[ \t]*)$"
)
_NUMBER_TOKEN = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?%?")
_NUMBER_PLACEHOLDER = re.compile(r"«NUMBER_[A-Z]+»")
_STRUCTURAL_WORDING_LINE = re.compile(
    r"^[ \t]*(?:Criterion[ \t]+\d+[ \t]*:|Description:|Levels:|"
    r"\[[A-Z]\]:|PaperBench leaf ID:|Scoring protocol:|"
    r"Score normalization maximum:|Total Points:|CRITERIA(?:[ \t]|\())",
    re.MULTILINE,
)

PARAPHRASE_INSTRUCTIONS = f"""Prompt contract: {PARAPHRASE_PROTOCOL}

Rewrite only the supplied wording fields. The program owns and copies all rubric
structure. You cannot edit criterion numbers, criterion order, level labels,
point values, scoring directives, normalization, or PaperBench leaf IDs. Do not
return those fields. Each request contains one complete criterion or the rubric
preamble.

Preserve all semantics within each wording field. Preserve every requirement,
exception, factual anchor, number, filename, command, identifier, example, and
scoring direction. Keep each number with the phrase that it qualifies. Do not
move content between fields. Do not add, remove, merge, split, weaken,
strengthen, clarify, or repair criteria. Do not adapt the rubric to a
submission. Do not turn examples into requirements or requirements into
examples.

Tokens such as `«NUMBER_A»` stand for exact numeric text owned by the program.
Copy each token exactly once. You may reorder a complete phrase when its meaning
does not change. Do not translate, spell out, duplicate, or add numeric text.

Change enough wording that the result is a real paraphrase. Return only the
`wording` object required by the response schema. Keep each value on one line.
Do not use Markdown code fences.
"""


@dataclass(frozen=True)
class WordingSlot:
    key: str
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class WordingRequestGroup:
    group_id: str
    slots: tuple[WordingSlot, ...]

    @property
    def fields(self) -> dict[str, str]:
        fields: dict[str, str] = {}
        seen_text: set[str] = set()
        for slot in self.slots:
            if slot.text in seen_text:
                continue
            fields[slot.key] = _protect_number_tokens(slot.text)
            seen_text.add(slot.text)
        return fields

    @property
    def field_keys(self) -> dict[str, str]:
        first_key_by_text: dict[str, str] = {}
        return {
            slot.key: first_key_by_text.setdefault(slot.text, slot.key)
            for slot in self.slots
        }

    def response_schema(self) -> dict[str, object]:
        fields = self.fields
        return {
            "type": "object",
            "additionalProperties": False,
            "required": ["wording"],
            "properties": {
                "wording": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": list(fields),
                    "properties": {
                        key: {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": max(64, len(text) * 3),
                            "pattern": _protected_wording_pattern(text),
                        }
                        for key, text in fields.items()
                    },
                },
            },
        }

    def expand(self, wording: object) -> dict[str, str]:
        if type(wording) is not dict or set(wording) != set(self.fields):
            raise ValueError("paraphraser wording fields do not match the master")
        replacements: dict[str, str] = {}
        field_keys = self.field_keys
        for slot in self.slots:
            protected_value = wording[field_keys[slot.key]]
            if type(protected_value) is not str:
                raise ValueError(f"{slot.key} must be a string")
            value = _restore_number_tokens(slot, protected_value)
            replacements[slot.key] = value
        return self.validate_replacements(replacements)

    def validate_replacements(self, value: object) -> dict[str, str]:
        expected_keys = {slot.key for slot in self.slots}
        if type(value) is not dict or set(value) != expected_keys:
            raise ValueError("saved paraphrase fields do not match the master")
        replacements: dict[str, str] = {}
        for slot in self.slots:
            replacement = value[slot.key]
            if type(replacement) is not str:
                raise ValueError(f"{slot.key} must be a string")
            validate_wording_value(slot, replacement)
            replacements[slot.key] = replacement
        if all(replacements[slot.key] == slot.text for slot in self.slots):
            raise ValueError("paraphraser returned an unchanged wording unit")
        return replacements


@dataclass(frozen=True)
class WordingTemplate:
    source: str
    slots: tuple[WordingSlot, ...]

    @property
    def groups(self) -> tuple[WordingRequestGroup, ...]:
        grouped: dict[str, list[WordingSlot]] = {}
        for slot in self.slots:
            if slot.key.startswith("preamble_"):
                group_id = "preamble"
            else:
                match = re.match(r"criterion_([1-9][0-9]*)_", slot.key)
                if match is None:
                    raise ValueError(f"invalid rubric wording field: {slot.key}")
                group_id = f"criterion-{int(match.group(1)):03d}"
            grouped.setdefault(group_id, []).append(slot)
        return tuple(
            WordingRequestGroup(group_id, tuple(slots))
            for group_id, slots in grouped.items()
        )

    @property
    def fixed_fragments(self) -> tuple[str, ...]:
        fragments: list[str] = []
        cursor = 0
        for slot in self.slots:
            fragments.append(self.source[cursor:slot.start])
            cursor = slot.end
        fragments.append(self.source[cursor:])
        return tuple(fragments)

    def render(self, wording: object) -> str:
        expected_keys = {slot.key for slot in self.slots}
        if type(wording) is not dict or set(wording) != expected_keys:
            raise ValueError("paraphraser wording fields do not match the master")
        replacements: dict[str, str] = {}
        for slot in self.slots:
            value = wording[slot.key]
            if type(value) is not str:
                raise ValueError(f"{slot.key} must be a string")
            validate_wording_value(slot, value)
            replacements[slot.key] = value

        pieces: list[str] = []
        cursor = 0
        for slot in self.slots:
            pieces.append(self.source[cursor:slot.start])
            pieces.append(replacements[slot.key])
            cursor = slot.end
        pieces.append(self.source[cursor:])
        return "".join(pieces)


def wording_template(rubric: str) -> WordingTemplate:
    if type(rubric) is not str or not rubric.strip():
        raise ValueError("rubric must be a non-empty string")
    if "```" in rubric:
        raise ValueError("rubric must not contain Markdown code fences")

    levels_by_criterion = parse_rubric_levels_strict(rubric)
    headers = list(CRITERION_HEADER_PATTERN.finditer(rubric))
    expected_numbers = list(range(1, len(headers) + 1))
    actual_numbers = [int(header.group("number")) for header in headers]
    if actual_numbers != expected_numbers:
        raise ValueError("rubric criterion numbers must be contiguous from 1")

    slots = _preamble_slots(rubric, headers[0].start())
    for index, header in enumerate(headers):
        block_end = (
            headers[index + 1].start() if index + 1 < len(headers) else len(rubric)
        )
        number = int(header.group("number"))
        slots.extend(
            _criterion_slots(
                rubric,
                header,
                block_end,
                tuple(levels_by_criterion[f"criterion_{number}"]),
            )
        )
    return _validated_template(rubric, slots)


def _preamble_slots(rubric: str, end: int) -> list[WordingSlot]:
    slots: list[WordingSlot] = []
    preamble = rubric[:end]
    preamble_index = 0
    offset = 0
    for line in preamble.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        if not content.strip() or _FIXED_PREAMBLE_LINE.match(content) is not None:
            offset += len(line)
            continue
        start, slot_end = _preamble_text_bounds(content, offset)
        preamble_index += 1
        slots.append(WordingSlot(
            key=f"preamble_{preamble_index:02d}",
            start=start,
            end=slot_end,
            text=rubric[start:slot_end],
        ))
        offset += len(line)
    return slots


def _preamble_text_bounds(content: str, offset: int) -> tuple[int, int]:
    prefixed = _PREFIXED_PREAMBLE_LINE.match(content)
    if prefixed is not None:
        return offset + prefixed.start("text"), offset + prefixed.end("text")
    leading = len(content) - len(content.lstrip())
    trailing = len(content.rstrip())
    return offset + leading, offset + trailing


def _criterion_slots(
    rubric: str,
    header: re.Match[str],
    block_end: int,
    expected_labels: tuple[str, ...],
) -> list[WordingSlot]:
    number = int(header.group("number"))
    slots = [
        WordingSlot(
            key=f"criterion_{number}_title",
            start=header.start("text"),
            end=header.end("text"),
            text=header.group("text"),
        )
    ]
    levels_line = _criterion_levels_line(rubric, header, block_end, number)
    descriptions = list(
        _DESCRIPTION_LINE.finditer(rubric, header.end(), levels_line.start())
    )
    if len(descriptions) > 1:
        raise ValueError(
            f"criterion_{number} contains more than one Description line"
        )
    if descriptions:
        description = descriptions[0]
        slots.append(WordingSlot(
            key=f"criterion_{number}_description",
            start=description.start("text"),
            end=description.end("text"),
            text=description.group("text"),
        ))
    slots.extend(
        _level_description_slots(
            rubric,
            levels_line,
            block_end,
            number,
            expected_labels,
        )
    )
    return slots


def _criterion_levels_line(
    rubric: str,
    header: re.Match[str],
    block_end: int,
    number: int,
) -> re.Match[str]:
    levels_lines = list(_LEVELS_LINE.finditer(rubric, header.end(), block_end))
    if len(levels_lines) != 1:
        raise ValueError(f"criterion_{number} must contain exactly one Levels line")
    return levels_lines[0]


def _level_description_slots(
    rubric: str,
    levels_line: re.Match[str],
    block_end: int,
    number: int,
    expected_labels: tuple[str, ...],
) -> list[WordingSlot]:
    matches = list(_LEVEL_DESCRIPTION.finditer(rubric, levels_line.end(), block_end))
    if [match.group("label") for match in matches] != list(expected_labels):
        raise ValueError(
            f"criterion_{number} must contain one description for each level"
        )
    slots = []
    for index, match in enumerate(matches):
        next_start = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else block_end
        )
        end = next_start
        while end > match.start("text") and rubric[end - 1].isspace():
            end -= 1
        slots.append(WordingSlot(
            key=f"criterion_{number}_level_{match.group('label')}",
            start=match.start("text"),
            end=end,
            text=rubric[match.start("text"):end],
        ))
    return slots


def _validated_template(rubric: str, slots: list[WordingSlot]) -> WordingTemplate:
    slots.sort(key=lambda slot: slot.start)
    if not slots:
        raise ValueError("rubric contains no paraphrasable wording")
    if len({slot.key for slot in slots}) != len(slots):
        raise ValueError("rubric contains duplicate wording fields")
    for left, right in zip(slots, slots[1:]):
        if left.end > right.start:
            raise ValueError(f"rubric wording fields overlap at {right.key}")
    return WordingTemplate(source=rubric, slots=tuple(slots))


def _number_placeholder(index: int) -> str:
    label = ""
    value = index + 1
    while value:
        value, remainder = divmod(value - 1, 26)
        label = chr(ord("A") + remainder) + label
    return f"«NUMBER_{label}»"


def _protect_number_tokens(value: str) -> str:
    if "«" in value or "»" in value:
        raise ValueError("rubric wording contains reserved number delimiters")
    index = 0

    def replace(_match: re.Match[str]) -> str:
        nonlocal index
        placeholder = _number_placeholder(index)
        index += 1
        return placeholder

    return _NUMBER_TOKEN.sub(replace, value)


def _protected_wording_pattern(value: str) -> str:
    placeholders = _NUMBER_PLACEHOLDER.findall(value)
    gap = r"[^«»\r\n]*"
    if not placeholders:
        return r"^[^«»\r\n]+$"
    allowed = "(?:" + "|".join(
        re.escape(placeholder) for placeholder in placeholders
    ) + ")"
    return "^" + gap + "(?:" + allowed + gap + ")*$"


def _restore_number_tokens(slot: WordingSlot, value: str) -> str:
    numbers = _NUMBER_TOKEN.findall(slot.text)
    expected = [_number_placeholder(index) for index in range(len(numbers))]
    actual = _NUMBER_PLACEHOLDER.findall(value)
    if Counter(actual) != Counter(expected) or re.fullmatch(
        _protected_wording_pattern(_protect_number_tokens(slot.text)),
        value,
    ) is None:
        raise ValueError(
            f"{slot.key} changed its numeric placeholders; expected "
            f"{expected}, got {actual}"
        )
    restored = value
    for placeholder, number in zip(expected, numbers):
        restored = restored.replace(placeholder, number)
    return restored


def validate_wording_value(slot: WordingSlot, value: str) -> None:
    if not value or value != value.strip():
        raise ValueError(f"{slot.key} must be non-empty without outer whitespace")
    if "\r" in value or "\n" in value:
        raise ValueError(f"{slot.key} must stay on one line")
    if "```" in value:
        raise ValueError(f"{slot.key} must not contain Markdown code fences")
    if _STRUCTURAL_WORDING_LINE.search(value) is not None:
        raise ValueError(f"{slot.key} must not contain rubric structure")
    expected_numbers = _NUMBER_TOKEN.findall(slot.text)
    actual_numbers = _NUMBER_TOKEN.findall(value)
    if Counter(actual_numbers) != Counter(expected_numbers):
        raise ValueError(
            f"{slot.key} changed its numbers; expected "
            f"{expected_numbers}, got {actual_numbers}"
        )




def group_source_sha256(group: WordingRequestGroup) -> str:
    return sha256_text(json.dumps(
        [[slot.key, slot.text] for slot in group.slots],
        ensure_ascii=False,
        separators=(",", ":"),
    ))


def duplicate_title_collisions(
    groups: tuple[WordingRequestGroup, ...],
    results: dict[str, _GroupGeneration],
) -> tuple[tuple[tuple[str, str, str], ...], ...]:
    by_title: dict[str, list[tuple[str, str, str]]] = {}
    for group in groups:
        result = results[group.group_id]
        for key, title in result.replacements.items():
            if not key.endswith("_title"):
                continue
            normalized = " ".join(title.lower().split())
            by_title.setdefault(normalized, []).append(
                (group.group_id, key, title)
            )
    return tuple(
        tuple(entries)
        for entries in by_title.values()
        if len(entries) > 1
    )
