"""Preserve validated proposer judgments across interrupted generations."""
from dataclasses import asdict
import json
from pathlib import Path

from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.submission_revision.evolution_provider import StructuredProviderOutput
from rubric_gen.submission_revision.evolution_serialization import canonical_sha256


class ValidatedProposerCache:
    def __init__(self, root: Path, identity: dict[str, object]):
        self.root = root
        self.identity = identity

    def path(self, request: dict[str, object]) -> Path:
        return self.root / (canonical_sha256({'identity': self.identity, 'request': request}) + '.json')

    def load(self, request: dict[str, object]) -> StructuredProviderOutput | None:
        path = self.path(request)
        if not path.exists():
            return None
        record = json.loads(path.read_text())
        if record['identity'] != self.identity or record['request'] != request:
            raise RuntimeError('proposer cache identity mismatch')
        output = StructuredProviderOutput(**record['output'])
        if canonical_sha256(record['output']) != record['output_sha256']:
            raise RuntimeError('proposer cache content mismatch')
        return output

    def save(self, request: dict[str, object], output: StructuredProviderOutput) -> None:
        value = asdict(output)
        write_json_atomic(self.path(request), {'identity': self.identity, 'request': request,
                                             'output': value, 'output_sha256': canonical_sha256(value)})
