# APEX Agents 1.1

This private repository contains the code required to download, prepare, and run
APEX Agents 1.1 tasks. Task prompts, rubrics, input files, reference outputs,
and world data remain in the separate private Hugging Face dataset.

## Requirements

- Docker
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/)
- Read access to `mercor/apex-agents-v1.1-test`
- A model-provider credential supported by the selected agent

Allow roughly 8 GB for the dataset download and additional space for Docker
images and run artifacts.

## Prepare the tasks

```bash
git clone --recurse-submodules https://github.com/Mercor-Intelligence/apex-agents-1.1.git
cd apex-agents-1.1
uv sync

export HF_TOKEN="<read token for the private dataset>"
./scripts/prepare_from_hf.sh
```

For an existing clone, initialize the pinned runtime dependency first:

```bash
git submodule update --init --recursive
```

The preparation command:

1. verifies that the Hugging Face dataset is private;
2. downloads and validates all 452 tasks and 31 worlds;
3. builds the tool configuration for every world;
4. converts the source package into the local runnable layout; and
5. validates the generated output.

All downloaded and generated data is written under `.runtime/`, which is ignored
by Git.

## Repository layout

- `src/apex11/` contains the download, validation, conversion, and container helper code.
- `runtime/` contains only the Docker image definitions and build entrypoint.
- `scripts/prepare_from_hf.sh` is the single user-facing preparation command.
- `vendor/archipelago` is a pinned submodule to the public runtime dependency.

To prepare only selected tasks while still validating the complete source:

```bash
./scripts/prepare_from_hf.sh \
  --task-id task_2bdbc68cef03435db2777c73b5e8643e
```

## Run a task

Build the shared Docker images once:

```bash
bash .runtime/tasks/prepare_images.sh
```

List the generated task directory names and run one:

```bash
find .runtime/tasks/tasks -mindepth 1 -maxdepth 1 -type d -exec basename {} \; | sort
bash .runtime/tasks/run_task.sh <task-directory>
```

The run output is stored under `.runtime/tasks/jobs/` by default. Set `MODEL`,
`AGENT`, `GRADING_MODEL`, or `OUTPUT_DIR` to override the generated defaults.

## License

Original material in this repository is licensed under the Creative Commons
Attribution 4.0 International license. See `LICENSE`. The Archipelago submodule
retains its Apache 2.0 license in `vendor/archipelago/LICENSE`.

Copyright 2026 Mercor.
