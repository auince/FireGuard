from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class InspectionBranch:
    key: str
    name: str
    default_task: str
    yolo_task: str
    prompt_profile: str
    reviewers: tuple[str, ...] = field(default_factory=tuple)
    enabled: bool = True


BRANCHES: dict[str, InspectionBranch] = {
    "indoor_hydrant": InspectionBranch(
        key="indoor_hydrant",
        name="室内消火栓",
        default_task="internal_components",
        yolo_task="internal_components",
        prompt_profile="indoor_hydrant",
        reviewers=("missing_equipment", "bend", "outlet_direction", "operation_instruction"),
    ),
    "outdoor_hydrant": InspectionBranch(
        key="outdoor_hydrant",
        name="室外消火栓",
        default_task="outdoor",
        yolo_task="outdoor_hydrant",
        prompt_profile="outdoor_hydrant",
        reviewers=("outdoor_presence", "outdoor_occupation", "outdoor_damage"),
    ),
    "fire_extinguisher": InspectionBranch(
        key="fire_extinguisher",
        name="灭火器",
        default_task="extinguisher",
        yolo_task="fire_extinguisher",
        prompt_profile="fire_extinguisher",
        reviewers=("pressure_indicator", "extinguisher_presence", "extinguisher_appearance"),
    ),
}


def get_branch(key: str | None) -> InspectionBranch:
    branch = BRANCHES.get(key or "")
    if not branch:
        raise ValueError(f"Unsupported inspection branch: {key or 'unknown'}")
    return branch


def yolo_task_for_branch(key: str | None, scope_hint: str | None = None) -> str:
    branch = get_branch(key)
    if branch.key == "indoor_hydrant" and scope_hint == "appearance":
        return "appearance"
    return branch.yolo_task
