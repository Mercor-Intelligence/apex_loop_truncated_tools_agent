# `apex_loop_truncated_tools_agent`

This repository contains only the self-contained APEX truncated-loop agent.
Task data stays in the private Hugging Face dataset.

## Run one task

Install Docker, `uv`, and the `hf` CLI:

```bash
hf download mercor/apex-agents-v1.1 \
  --repo-type dataset \
  --include "mercor-world418-tk-02-2bdbc68c/**" \
  --local-dir tasks

cp .env.example .env
```

Set `ANTHROPIC_API_KEY` and any grader credentials in `.env`, then run:

```bash
PYTHONPATH="$PWD/apex_loop_truncated_tools_agent" \
uvx --from harbor==0.20.0 harbor run \
  --env-file .env \
  -p tasks/mercor-world418-tk-02-2bdbc68c \
  -a apex_loop_truncated_tools_agent:ApexLoopTruncatedToolsAgent \
  -m anthropic/claude-opus-5 \
  -y
```

Replace the model with any LiteLLM-compatible `provider/model`. The task's
configured grader is used when `GRADING_MODEL` is blank.
