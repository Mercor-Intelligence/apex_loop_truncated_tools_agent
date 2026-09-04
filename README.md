# `apex_loop_truncated_tools_agent`

<a href="https://arxiv.org/abs/2601.14242"><img src="https://img.shields.io/badge/📝-Paper-b31b1b"></a>
<a href="http://mercor.com/blog/introducing-apex-agents"><img src="https://img.shields.io/badge/📰-Blog-0ea5e9"></a>
<a href="https://huggingface.co/datasets/mercor/apex-agents-v1.1"><img src="https://img.shields.io/badge/🤗-Data-yellow"></a>
<a href="https://hub.harborframework.com/datasets/mercor/apex-agents-1-1"><img src="https://img.shields.io/badge/⚓-Harbor%20Hub-1f6feb"></a>
<a href="https://www.mercor.com/apex/apex-agents-leaderboard/"><img src="https://img.shields.io/badge/🏆-Leaderboard-f59e0b"></a>
<a href="mailto:apex@mercor.com"><img src="https://img.shields.io/badge/✉️-Contact-green"></a>

**Akul Datta, Austin Bennett, Bertie Vidgen**

This repository contains only the APEX truncated-loop agent — the agent behind
every published APEX-Agents result. Harbor selects the agent when a job starts
rather than in the task files, so the benchmark itself cannot record which agent
it expects. That is what this repository and `apex-agents-1.1.job.yaml` are for.

The tasks and worlds live separately, and you can get them from either channel:

| Channel | What it gives you |
|:---|:---|
| [Harbor Hub `mercor/apex-agents-1-1`](https://hub.harborframework.com/datasets/mercor/apex-agents-1-1) | 240 tasks; runtime images pulled from public ECR |
| [Hugging Face `mercor/apex-agents-v1.1`](https://huggingface.co/datasets/mercor/apex-agents-v1.1) | The same 240 tasks as a self-contained delivery, with image archives and world seeds on disk |

Both carry identical tasks and rubrics. They differ only in how the runtime
arrives.

## Version pin

This agent is pinned, deliberately. `apex_loop_truncated_tools_agent/manifest.json`
records the Studio revision it was vendored from and the SHA-256 of its system
prompt. The published leaderboard numbers were produced by exactly this code at
`max_steps = 250` and `timeout = 10800`. Upgrading it to a newer Studio revision
will change agent behaviour and your results will no longer be comparable to the
published ones.

## Run from Harbor Hub

> **Harbor does not pick the agent for you.** Running the dataset without an
> agent falls back to Harbor's built-in `oracle` agent, which replays the
> reference solution and scores near-perfectly. Always pass the APEX agent
> explicitly, via `-c apex-agents-1.1.job.yaml` or `-a apex_loop_truncated_tools_agent:ApexLoopTruncatedToolsAgent`.


Install Docker and `uv`. Clone this repository, then pull the dataset:

```bash
git clone https://github.com/Mercor-Intelligence/apex_loop_truncated_tools_agent.git
cd apex_loop_truncated_tools_agent
cp .env.example .env

export HARBOR_API_KEY=<your-key>
uvx --from harbor==0.20.0 harbor dataset download mercor/apex-agents-1-1@1.1
```

Set `ANTHROPIC_API_KEY` and any grader credentials in `.env`. The runtime images
come from public ECR on first run, so there is no load step.

Run the whole benchmark with the pinned settings:

```bash
PYTHONPATH="$PWD/apex_loop_truncated_tools_agent" \
uvx --from harbor==0.20.0 harbor run \
  --env-file .env \
  -c apex-agents-1.1.job.yaml \
  -m anthropic/claude-opus-5
```

Or run a single task:

```bash
PYTHONPATH="$PWD/apex_loop_truncated_tools_agent" \
uvx --from harbor==0.20.0 harbor run \
  --env-file .env \
  -p apex-agents-1-1/world418-tk-02-2bdbc68c \
  -a apex_loop_truncated_tools_agent:ApexLoopTruncatedToolsAgent \
  -m anthropic/claude-opus-5 \
  -y
```

## Run from Hugging Face

Install Docker, `uv`, and the `hf` CLI, then clone this repository and download
the shared images, selected task, and its world seed:

```bash
git clone https://github.com/Mercor-Intelligence/apex_loop_truncated_tools_agent.git
cd apex_loop_truncated_tools_agent

hf download mercor/apex-agents-v1.1 \
  --repo-type dataset \
  --include "environment/**" \
  --include "tasks/world418-tk-02-2bdbc68c/**" \
  --include "worlds/law-world-418-benchmark--(world_e3d122de4d7f445cb69c42b915d96381)/**" \
  --local-dir apex-agents-v1.1

bash apex-agents-v1.1/environment/load_images.sh
cp .env.example .env
```

Set `ANTHROPIC_API_KEY` and any grader credentials in `.env`, then run:

```bash
PYTHONPATH="$PWD/apex_loop_truncated_tools_agent" \
uvx --from harbor==0.20.0 harbor run \
  --env-file .env \
  -p apex-agents-v1.1/tasks/world418-tk-02-2bdbc68c \
  -a apex_loop_truncated_tools_agent:ApexLoopTruncatedToolsAgent \
  -m anthropic/claude-opus-5 \
  -y
```

Replace the model with any LiteLLM-compatible `provider/model`. The task's
configured grader is used when `GRADING_MODEL` is blank. If an existing
`apex-*:v1` tag points to a different image, the loader exits without replacing
it; rerun with `--restore` only when you intend to activate this delivery's
images.

## Contact

[apex@mercor.com](mailto:apex@mercor.com)
