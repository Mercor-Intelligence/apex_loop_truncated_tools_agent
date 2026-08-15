"""Turn a task's rubric into the grading config the archipelago runner reads.

Mirrors what ``archipelago/examples/hugging_face_task`` builds at run time, so a
converted task grades through the same evaluator as the published numbers.
"""

from typing import Any

from .profile import DatasetProfile

# Criterion-level LLM judge; `output_llm` is in the OSS eval allowlist.
EVAL_CONFIG_ID = "ec_output_llm"
EVAL_CONFIGS: list[dict[str, Any]] = [
    {
        "eval_config_id": EVAL_CONFIG_ID,
        "eval_config_name": "Output LLM Verifier",
        "eval_defn_id": "output_llm",
        "eval_config_values": {},
    }
]

SCORING_CONFIG: dict[str, Any] = {
    "scoring_config_id": "sc_default",
    "scoring_config_name": "Default Scoring",
    "scoring_defn_id": "template",
    "scoring_config_values": {},
}

DEFAULT_JUDGE_MODEL = "openai/gpt-5.2"


def build_verifiers(
    task: dict[str, Any], profile: DatasetProfile
) -> list[dict[str, Any]]:
    task_id = task[profile.task_id_field]
    world_id = task[profile.world_id_field]
    return [
        {
            "verifier_id": criterion[profile.verifier_id_field],
            "verifier_version": 1,
            "world_id": world_id,
            "task_id": task_id,
            "eval_config_id": EVAL_CONFIG_ID,
            "verifier_values": {
                "criteria": criterion[profile.criteria_field],
                # The first criterion carries the task's primary objective.
                "is_primary_objective": index == 0,
            },
            "verifier_index": index,
            "verifier_dependencies": None,
        }
        for index, criterion in enumerate(task.get(profile.rubric_field) or [])
    ]


def build_grading_config(
    task: dict[str, Any], profile: DatasetProfile, judge_model: str = DEFAULT_JUDGE_MODEL
) -> dict[str, Any]:
    verifiers = build_verifiers(task, profile)
    if not verifiers:
        raise ValueError(f"task {task[profile.task_id_field]} has an empty rubric")
    return {
        "metadata": {
            "task_id": task[profile.task_id_field],
            "task_name": task.get(profile.task_name_field),
            "world_id": task[profile.world_id_field],
            "domain": task.get(profile.domain_field),
            "expected_output": task.get(profile.expected_output_field),
        },
        "grading_settings": {
            "llm_judge_model": judge_model,
            "llm_judge_extra_args": None,
        },
        "verifiers": verifiers,
        "eval_configs": EVAL_CONFIGS,
        "scoring_config": SCORING_CONFIG,
    }


def needs_snapshot(task: dict[str, Any], profile: DatasetProfile) -> bool:
    """Whether grading reads world files, and so requires snapshot capture.

    Final-answer-only tasks skip it, which saves the capture on every trial.
    """
    expected = str(task.get(profile.expected_output_field) or "")
    return expected not in profile.final_answer_outputs


def golden_reference(task: dict[str, Any], profile: DatasetProfile) -> str | None:
    """The gold answer text, when the task has one that isn't a file pointer."""
    if task.get(profile.gold_response_type_field) != "text":
        return None
    return (task.get(profile.gold_response_field) or "").strip() or None
