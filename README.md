# APEX Agents 1.1

## Run

Install Docker, `uv`, and the Hugging Face CLI.

```bash
git clone https://github.com/Mercor-Intelligence/apex-agents-1.1.git
cd apex-agents-1.1

hf download mercor/apex-agents-v1.1 \
  --repo-type dataset \
  --include "mercor-world418-tk-02-2bdbc68c/**" \
  --local-dir tasks

cp .env.example .env

uvx --from harbor==0.20.0 harbor run \
  --env-file .env \
  -p tasks/mercor-world418-tk-02-2bdbc68c \
  -a claude-code \
  -m accounts/fireworks/models/kimi-k3
```

Put the agent and grader credentials in `.env` before running the task.
