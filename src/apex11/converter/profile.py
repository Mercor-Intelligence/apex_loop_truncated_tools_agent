"""Dataset-shape profiles.

Mercor's OSS exports share a structure — one JSON index of tasks with embedded
rubrics, one index of worlds, zipped world snapshots, per-task input and golden
files — but not their field names or layout. A profile captures those
differences so converting the next export is a new profile, not new code.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DatasetProfile:
    name: str
    description: str

    # Index files, relative to the dataset root.
    tasks_index: str = "tasks_and_rubrics.json"
    worlds_index: str = "world_descriptions.json"

    # Path templates. `{task_id}` / `{world_id}` are substituted.
    world_archive: str = "world_files_zipped/{world_id}.zip"
    task_files: str = "task_files/{task_id}"
    golden_files: str = "gold_files/{task_id}"

    # Task record fields.
    task_id_field: str = "task_id"
    task_name_field: str = "task_name"
    world_id_field: str = "world_id"
    domain_field: str = "domain"
    prompt_field: str = "prompt"
    rubric_field: str = "rubric"
    criteria_field: str = "criteria"
    verifier_id_field: str = "verifier_id"
    task_files_field: str = "task_input_files"
    expected_output_field: str = "expected_output"
    gold_response_field: str = "gold_response"
    gold_response_type_field: str = "gold_response_type"

    # World record fields.
    world_name_field: str = "world_name"
    world_description_field: str = "world_description"
    apps_field: str = "apps"

    # expected_output values graded purely on the agent's final message. Anything
    # else is graded on files and therefore needs snapshot capture.
    final_answer_outputs: frozenset[str] = field(
        default_factory=lambda: frozenset({"message_in_console"})
    )

    # Namespace for [task].name and the Harbor task dir prefix.
    org: str = "mercor"
    task_dir_prefix: str = "mercor-"


APEX_AGENTS = DatasetProfile(
    name="apex-agents",
    description=(
        "APEX-Agents: long-horizon, cross-application professional services tasks "
        "authored by investment banking analysts, management consultants and "
        "corporate lawyers."
    ),
)

PROFILES: dict[str, DatasetProfile] = {APEX_AGENTS.name: APEX_AGENTS}


def get_profile(name: str) -> DatasetProfile:
    if name not in PROFILES:
        raise KeyError(f"unknown profile {name!r}; known: {', '.join(sorted(PROFILES))}")
    return PROFILES[name]
