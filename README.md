# APEX Agents 1.1

## Run

Install [Docker](https://docs.docker.com/get-started/get-docker/) and
[`uv`](https://docs.astral.sh/uv/getting-started/installation/), then run:

```bash
git clone --recurse-submodules https://github.com/Mercor-Intelligence/apex-agents-1.1.git
cd apex-agents-1.1
uv sync
./scripts/prepare_from_hf.sh
bash .runtime/tasks/prepare_images.sh
```

List the prepared tasks:

```bash
find .runtime/tasks/tasks -mindepth 1 -maxdepth 1 -type d -exec basename {} \; | sort
```

Run one task:

```bash
bash .runtime/tasks/run_task.sh <task-directory>
```
