# APEX-Agents 1.1: `apex_loop_truncated_tools_agent`

<a href="https://arxiv.org/abs/2601.14242"><img src="https://img.shields.io/badge/📝-Paper-b31b1b"></a>
<a href="http://mercor.com/blog/introducing-apex-agents"><img src="https://img.shields.io/badge/📰-Blog-0ea5e9"></a>
<a href="https://huggingface.co/datasets/mercor/apex-agents-v1.1"><img src="https://img.shields.io/badge/🤗-Data-yellow"></a>
<a href="https://hub.harborframework.com/datasets/mercor/apex-agents-1-1"><img src="https://img.shields.io/badge/⚓-Harbor%20Hub-1f6feb"></a>
<a href="https://www.mercor.com/apex/apex-agents-leaderboard/"><img src="https://img.shields.io/badge/🏆-Leaderboard-f59e0b"></a>
<a href="mailto:apex@mercor.com"><img src="https://img.shields.io/badge/✉️-Contact-green"></a>

This repository contains the reference agent implementation for APEX-Agents 1.1.
The tasks, world seeds, and shared runtime images are in the Harbor Hub and
Hugging Face datasets.

The agent connects to the world's MCP gateway, exposes those tools to the
model, and loops until the model replies without a tool call or the step
budget is spent. Tool output is truncated to 200 lines or 32,768 characters,
whichever comes first, so a long output cannot fill the context window. The
defaults are 250 steps and a 10,800 second timeout, and the trajectory is
converted to ATIF before it is returned.

## Usage

Install Docker and `uv`, then install Harbor:

```bash
uv tool install harbor==0.20.0
```

Clone this repository, then set the API key for your model provider and any
grader credentials in `.env`:

```bash
git clone https://github.com/Mercor-Intelligence/apex_loop_truncated_tools_agent.git
cd apex_loop_truncated_tools_agent
cp .env.example .env
```

### Harbor Hub

Download the dataset:

```bash
harbor dataset download mercor/apex-agents-1-1@1.1
```

Run the benchmark:

```bash
PYTHONPATH="$PWD/apex_loop_truncated_tools_agent" \
harbor run \
  --env-file .env \
  -d mercor/apex-agents-1-1@1.1 \
  -a apex_loop_truncated_tools_agent:ApexLoopTruncatedToolsAgent \
  -m anthropic/claude-opus-5
```

### Hugging Face

Install the `hf` CLI, then download the shared images, selected task, and its
world seed:

```bash
hf download mercor/apex-agents-v1.1 \
  --repo-type dataset \
  --include "environment/**" \
  --include "tasks/world418-tk-02-2bdbc68c/**" \
  --include "worlds/law-world-418-benchmark--(world_e3d122de4d7f445cb69c42b915d96381)/**" \
  --local-dir apex-agents-v1.1

bash apex-agents-v1.1/environment/load_images.sh
```

Run the task:

```bash
PYTHONPATH="$PWD/apex_loop_truncated_tools_agent" \
harbor run \
  --env-file .env \
  -p apex-agents-v1.1/tasks/world418-tk-02-2bdbc68c \
  -a apex_loop_truncated_tools_agent:ApexLoopTruncatedToolsAgent \
  -m anthropic/claude-opus-5 \
  -y
```

Replace the model with any LiteLLM-compatible `provider/model`.

## Contact

[apex@mercor.com](mailto:apex@mercor.com)
