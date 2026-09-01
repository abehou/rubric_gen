"""Shared contracts for revision detection windows."""

from __future__ import annotations

from enum import StrEnum


class RevisionDetectionWindow(StrEnum):
    """Select the fixed behavioral period exposed to the direct detector."""

    FULL_TRAJECTORY = "full_trajectory"
    POST_UPDATE = "post_update"
    FINAL_ARTIFACT = "final_artifact"
    FINAL_REVISION = "final_revision"


POST_UPDATE_BASELINE_INDEX = 2
POST_UPDATE_FIRST_AFFECTED_INDEX = 3
MINIMUM_POST_UPDATE_REVISIONS = POST_UPDATE_FIRST_AFFECTED_INDEX
