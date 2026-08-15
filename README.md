# APEX Agents 1.1

## Run

Install [Docker](https://docs.docker.com/get-started/get-docker/) and
[`uv`](https://docs.astral.sh/uv/getting-started/installation/), then run:

```bash
git clone --recurse-submodules https://github.com/Mercor-Intelligence/apex-agents-1.1.git
cd apex-agents-1.1
uv sync
uv run hf download mercor/apex-agents-v1.1 \
  --repo-type dataset \
  --local-dir .runtime/tasks
cp .env.example .env
bash .runtime/tasks/prepare_images.sh
```

Add the API keys for the agent and grader to `.env`. The defaults use
`ANTHROPIC_API_KEY` and `OPENAI_API_KEY`; any valid `KEY=VALUE` entry is
forwarded to both, so other providers work too.

The Hugging Face dataset is already in Harbor format. List its tasks:

```bash
find .runtime/tasks/tasks -mindepth 1 -maxdepth 1 -type d -exec basename {} \; | sort
```

Run a tested example task:

```bash
bash .runtime/tasks/run_task.sh mercor-world418-tk-02-2bdbc68c
```
