"""Closed response contract for explicit task-required enforcement."""

from dataclasses import dataclass, field
from typing import Any

import jsonschema

from .evolution_artifacts import single_line
from .trace_defense_evidence_v2 import (
    EVIDENCE_CONTRACT_VERSION,
    EvidenceContractError,
    PublicDocument,
    bind_references,
    references_schema,
    source_manifest,
)
from .trace_defense_schema import obj


SCHEMA_VERSION = "trace-defense-task-required-enforcement-schema-1"
VALIDATION_VERSION = "trace-defense-task-required-enforcement-validation-1"


def enforcement_schema(documents):
    return obj(
        decision={"type": "string", "enum": ["pass", "correct", "undecidable"]},
        requirement={"type": "string", "maxLength": 650},
        corrective_action={"type": "string", "maxLength": 650},
        preserve_supported_work={"type": "string", "maxLength": 650},
        evidence_refs=references_schema(documents),
        reason={"type": "string", "maxLength": 1_200},
    )


@dataclass(frozen=True)
class EnforcementContract:
    stage: str
    schema: dict
    documents: dict[str, PublicDocument] = field(default_factory=dict)
    native_ids: dict[str, str] = field(default_factory=dict)

    def identity(self):
        return {
            "schema_version": SCHEMA_VERSION,
            "validation_version": VALIDATION_VERSION,
            "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
            "sources": source_manifest(self.documents, self.native_ids),
            "allowed_actions": [],
            "labels": [],
        }

    def validate(self, value):
        errors = [
            {"field": ".".join(map(str, item.absolute_path)) or "$", "reason": item.message}
            for item in jsonschema.Draft202012Validator(self.schema).iter_errors(value)
        ]
        if errors:
            raise EvidenceContractError(errors)
        if self.stage != "enforcement":
            raise ValueError("enforcement contract used for another stage")
        if not value["reason"].strip():
            errors.append({"field": "reason", "reason": "nonempty_explanation_required"})
        decision = value["decision"]
        if decision == "correct":
            for key in ("requirement", "corrective_action", "preserve_supported_work"):
                try:
                    single_line(value[key], key, 650)
                except ValueError as exc:
                    errors.append({"field": key, "reason": str(exc)})
        elif value["requirement"] or value["corrective_action"]:
            errors.append({
                "field": "requirement/corrective_action",
                "reason": "non-correction_must_not_supply_solver_direction",
            })
        resolved = []
        try:
            resolved = bind_references(value["evidence_refs"], self.documents)
        except EvidenceContractError as exc:
            errors.extend(
                {**item, "field": item["field"].replace("references", "evidence_refs", 1)}
                for item in exc.errors
            )
        if decision == "correct":
            source_ids = {item["source_id"] for item in resolved}
            if not source_ids & {"task", "selected_rubric", "development_rubric"}:
                errors.append({"field": "evidence_refs", "reason": "missing_explicit_requirement_source"})
            if not source_ids & {"artifact", "execution_witness"}:
                errors.append({"field": "evidence_refs", "reason": "missing_current_failure_source"})
        if errors:
            raise EvidenceContractError(errors)
        return {"evidence_refs": resolved}

    def repair_locks(self, value):
        if not isinstance(value, dict):
            return None
        properties = self.schema["properties"]
        valid = {}
        for key, item in value.items():
            if key in properties and not list(
                jsonschema.Draft202012Validator(properties[key]).iter_errors(item)
            ):
                valid[key] = item
        locked = {key: item for key, item in valid.items() if key != "evidence_refs"}
        if not locked:
            return None
        editable = [key for key in properties if key not in locked]
        return {
            "allowed_edit_fields": editable,
            "locked_fields": locked,
            "repair_kind": (
                "locator_repair"
                if set(editable) <= {"evidence_refs"} and set(value) == set(properties)
                else "schema_repair"
            ),
        }
