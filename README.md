# APEX Agents 1.1

## Run

Install [Docker](https://docs.docker.com/get-started/get-docker/) and
[`uv`](https://docs.astral.sh/uv/getting-started/installation/). The tasks are
ready-to-run Harbor tasks hosted on Hugging Face.

```bash
git clone --recurse-submodules https://github.com/Mercor-Intelligence/apex-agents-1.1.git
cd apex-agents-1.1
uvx --from huggingface-hub hf download mercor/apex-agents-v1.1 \
  --repo-type dataset \
  --local-dir .runtime/tasks
cp .env.example .env
bash .runtime/tasks/prepare_images.sh
bash .runtime/tasks/run_task.sh mercor-world418-tk-02-2bdbc68c
```

Put the agent and grader credentials in `.env`. Any valid `KEY=VALUE` entry is
forwarded to both.
