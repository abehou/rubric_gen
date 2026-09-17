"""Closed response contract for explicit task-required enforcement."""

from dataclasses import dataclass, field
from typing import Any
import re

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
EXECUTION_VERIFIED_SCHEMA_VERSION = "trace-defense-execution-verified-schema-1"
EXECUTION_VERIFIED_VALIDATION_VERSION = "trace-defense-execution-verified-validation-1"
_NUMERIC = re.compile(
    r"(?<![\w.])[+-]?(?:\d+(?:,\d{3})*(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?%?"
)


def enforcement_schema(documents, *, execution_verified=False):
    if execution_verified:
        return obj(
            decision={"type": "string", "enum": ["pass", "correct", "undecidable"]},
            prior_issue_status={
                "type": "string",
                "enum": [
                    "not_applicable", "unresolved", "resolved_execution",
                    "resolved_downgrade",
                ],
            },
            requirement={"type": "string", "maxLength": 650},
            defect={"type": "string", "maxLength": 900},
            public_evidence={"type": "string", "maxLength": 1_200},
            corrective_action={"type": "string", "maxLength": 900},
            preserve_supported_work={"type": "string", "maxLength": 650},
            if_execution_unavailable={"type": "string", "maxLength": 650},
            evidence_refs=references_schema(documents),
            reason={"type": "string", "maxLength": 1_500},
        )
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
    execution_verified: bool = False
    prior_issue: dict[str, Any] | None = None

    def identity(self):
        return {
            "schema_version": (
                EXECUTION_VERIFIED_SCHEMA_VERSION if self.execution_verified else SCHEMA_VERSION
            ),
            "validation_version": (
                EXECUTION_VERIFIED_VALIDATION_VERSION
                if self.execution_verified else VALIDATION_VERSION
            ),
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
        if self.execution_verified:
            if errors:
                raise EvidenceContractError(errors)
            return self._validate_execution_verified(value, errors)
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

    def _validate_execution_verified(self, value, errors):
        if not value["reason"].strip():
            errors.append({"field": "reason", "reason": "nonempty_explanation_required"})
        direction_fields = (
            "requirement", "defect", "public_evidence", "corrective_action",
            "preserve_supported_work", "if_execution_unavailable",
        )
        decision = value["decision"]
        prior_status = value["prior_issue_status"]
        if decision == "correct":
            for key in direction_fields:
                try:
                    single_line(value[key], key, self.schema["properties"][key]["maxLength"])
                except ValueError as exc:
                    errors.append({"field": key, "reason": str(exc)})
        elif any(value[key] for key in direction_fields):
            errors.append({
                "field": "/".join(direction_fields),
                "reason": "non-correction_must_not_supply_solver_direction",
            })

        if self.prior_issue is None:
            if prior_status != "not_applicable":
                errors.append({"field": "prior_issue_status", "reason": "no_prior_issue"})
        elif decision == "correct":
            if prior_status != "unresolved":
                errors.append({"field": "prior_issue_status", "reason": "active_issue_must_remain_or_resolve"})
            for key in (
                "requirement", "defect", "corrective_action",
                "preserve_supported_work", "if_execution_unavailable",
            ):
                if value[key] != self.prior_issue.get(key):
                    errors.append({"field": key, "reason": "unresolved_issue_identity_changed"})
        elif decision == "pass":
            if prior_status not in {"resolved_execution", "resolved_downgrade"}:
                errors.append({"field": "prior_issue_status", "reason": "prior_issue_resolution_required"})
        else:
            errors.append({"field": "decision", "reason": "active_issue_cannot_become_undecidable"})

        resolved = []
        try:
            resolved = bind_references(value["evidence_refs"], self.documents)
        except EvidenceContractError as exc:
            errors.extend(
                {**item, "field": item["field"].replace("references", "evidence_refs", 1)}
                for item in exc.errors
            )
        source_ids = {item["source_id"] for item in resolved}
        if decision == "correct":
            if not source_ids & {"task", "selected_rubric", "development_rubric", "prior_issue"}:
                errors.append({"field": "evidence_refs", "reason": "missing_explicit_requirement_source"})
            if not source_ids & {"artifact", "execution_witness", "execution_delta"}:
                errors.append({"field": "evidence_refs", "reason": "missing_current_failure_source"})
            grounded_numbers = set(_NUMERIC.findall("\n".join(
                item["text"] for item in resolved
            )))
            directed_numbers = set(_NUMERIC.findall("\n".join(
                value[key] for key in direction_fields
            )))
            if not directed_numbers <= grounded_numbers:
                errors.append({
                    "field": "solver_direction",
                    "reason": "numeric_literal_not_present_in_cited_public_evidence",
                })
        if self.prior_issue is not None and decision == "pass":
            if "artifact" not in source_ids:
                errors.append({"field": "evidence_refs", "reason": "resolution_lacks_current_artifact"})
            if prior_status == "resolved_execution" and "execution_delta" not in source_ids:
                errors.append({"field": "evidence_refs", "reason": "execution_resolution_lacks_fresh_delta"})
            if "prior_issue" not in source_ids:
                errors.append({"field": "evidence_refs", "reason": "resolution_lacks_prior_issue"})
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
