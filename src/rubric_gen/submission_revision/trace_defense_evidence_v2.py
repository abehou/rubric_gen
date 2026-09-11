"""Exact source addresses for learning. Address validity is not semantic verification."""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import re
from typing import Any, Mapping, Sequence

EVIDENCE_CONTRACT_VERSION = 'numbered-public-sources-v2.1'


class EvidenceContractError(ValueError):
    """An invalid pointer/schema operation, not a scientific rejection."""
    def __init__(self, errors: list[dict[str, Any]]) -> None:
        self.errors = errors
        super().__init__(repr(errors))


@dataclass(frozen=True)
class PublicDocument:
    source_id: str
    text: str
    lines: tuple[str, ...] = field(init=False, repr=False)
    char_offsets: tuple[int, ...] = field(init=False, repr=False)
    byte_offsets: tuple[int, ...] = field(init=False, repr=False)
    content_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.source_id, str) or not self.source_id:
            raise ValueError('source_id must be nonempty')
        if not isinstance(self.text, str):
            raise TypeError('canonical public text must be a str')
        lines = tuple(self.text.splitlines(keepends=True))
        chars, octets = [0], [0]
        for line in lines:
            chars.append(chars[-1] + len(line))
            octets.append(octets[-1] + len(line.encode('utf-8')))
        assert ''.join(lines) == self.text
        object.__setattr__(self, 'lines', lines)
        object.__setattr__(self, 'char_offsets', tuple(chars))
        object.__setattr__(self, 'byte_offsets', tuple(octets))
        object.__setattr__(self, 'content_sha256', sha256(self.text.encode('utf-8')).hexdigest())

    def model_record(self) -> dict[str, Any]:
        return {'source_id': self.source_id, 'source_sha256': self.content_sha256,
                'line_count': len(self.lines),
                'numbered_text': ''.join(f'[L{i:06d}] {line}' for i, line in enumerate(self.lines, 1))}

    def resolve(self, start_line: int, end_line: int) -> dict[str, Any]:
        if type(start_line) is not int or type(end_line) is not int:
            raise ValueError('line bounds must be integers, not booleans')
        if not 1 <= start_line <= end_line <= len(self.lines):
            raise ValueError('line bounds fall outside their named public source')
        start, end = self.char_offsets[start_line-1], self.char_offsets[end_line]
        byte_start, byte_end = self.byte_offsets[start_line-1], self.byte_offsets[end_line]
        excerpt = self.text[start:end]
        assert self.text.encode('utf-8')[byte_start:byte_end] == excerpt.encode('utf-8')
        return {'source_id': self.source_id, 'source_sha256': self.content_sha256,
                'start_line': start_line, 'end_line': end_line, 'char_start': start, 'char_end': end,
                'byte_start': byte_start, 'byte_end': byte_end, 'text': excerpt}


def references_schema(documents: Mapping[str, PublicDocument]) -> dict[str, Any]:
    if not documents or any(key != doc.source_id for key, doc in documents.items()):
        raise ValueError('documents must be a nonempty correctly keyed mapping')
    max_line = max(len(doc.lines) for doc in documents.values())
    if max_line == 0:
        raise ValueError('cannot request references to entirely empty public sources')
    return {'type': 'array', 'minItems': 0, 'maxItems': 6,
            'items': {'type': 'object', 'additionalProperties': False,
                      'required': ['source_id', 'start_line', 'end_line'],
                      'properties': {'source_id': {'type': 'string', 'enum': list(documents)},
                                     'start_line': {'type': 'integer', 'minimum': 1, 'maximum': max_line},
                                     'end_line': {'type': 'integer', 'minimum': 1, 'maximum': max_line}}}}


def bind_references(references: Any, documents: Mapping[str, PublicDocument], *,
                    required_sources: Sequence[str] = ()) -> list[dict[str, Any]]:
    errors, resolved, seen = [], [], set()
    if not isinstance(references, list):
        raise EvidenceContractError([{'field': 'references', 'reason': 'expected_array'}])
    if len(references) > 6:
        errors.append({'field': 'references', 'reason': 'at_most_six_ranges'})
    for index, ref in enumerate(references):
        name = f'references[{index}]'
        if not isinstance(ref, dict) or set(ref) != {'source_id', 'start_line', 'end_line'}:
            errors.append({'field': name, 'reason': 'invalid_reference_fields'}); continue
        source_id = ref['source_id']
        if not isinstance(source_id, str) or source_id not in documents:
            errors.append({'field': name+'.source_id', 'reason': 'unknown_source'}); continue
        try:
            span = documents[source_id].resolve(ref['start_line'], ref['end_line'])
        except (TypeError, ValueError) as exc:
            errors.append({'field': name, 'reason': str(exc)}); continue
        key = (source_id, ref['start_line'], ref['end_line'])
        if key not in seen:
            resolved.append(span); seen.add(key)
    for source_id in required_sources:
        if source_id not in documents:
            raise ValueError('required_sources references an unavailable document')
        if not any(span['source_id'] == source_id for span in resolved):
            errors.append({'field': 'references', 'reason': 'missing_required_source', 'source_id': source_id})
    if errors:
        raise EvidenceContractError(errors)
    return resolved


def allowed_actions(active_learned_ids: Sequence[str]) -> tuple[str, ...]:
    ids = tuple(active_learned_ids)
    if any(not isinstance(cid, str) or re.fullmatch(r'elicited_[0-9a-f]{16}', cid) is None for cid in ids):
        raise ValueError('only actual active learned-criterion IDs are replaceable')
    if len(ids) != len(set(ids)):
        raise ValueError('active learned IDs must be unique')
    return ('NO_SUPPORTED_RELATION', 'PREFERENCE_CONFLICT', 'ADD', *('REPLACE:'+cid for cid in ids))


def replacement_for_action(action: str, active_learned_ids: Sequence[str]) -> tuple[str, ...]:
    if action not in allowed_actions(active_learned_ids):
        raise ValueError('action is not in the explicit allowed-action registry')
    if action == 'ADD':
        return ()
    if action.startswith('REPLACE:'):
        return (action.removeprefix('REPLACE:'),)
    raise ValueError('a scientific null/conflict diagnosis cannot create a candidate')


def native_criterion_payload(compiled: Mapping[str, Any], *, witness_pair_id: str,
                             action: str, active_learned_ids: Sequence[str]) -> dict[str, Any]:
    if set(compiled) != {'title', 'requirement', 'levels'}:
        raise ValueError('compiler returns only criterion content')
    replaces = replacement_for_action(action, active_learned_ids)
    return {'title': compiled['title'], 'requirement': compiled['requirement'], 'levels': compiled['levels'],
            'provenance_pair_ids': [witness_pair_id], 'replaces': list(replaces)}


def source_manifest(documents, native_ids):
    if set(documents) != set(native_ids):
        raise ValueError('every source alias must have exactly one native identity')
    return {alias: {'native_id': native_ids[alias], 'source_sha256': doc.content_sha256,
                    'line_count': len(doc.lines)} for alias, doc in documents.items()}
