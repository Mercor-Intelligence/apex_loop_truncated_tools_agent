# `apex_loop_truncated_tools_agent`

This repository contains only the APEX truncated-loop agent. The tasks, world
seeds, and three shared runtime images are in the private Hugging Face dataset.

## Run one task

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
