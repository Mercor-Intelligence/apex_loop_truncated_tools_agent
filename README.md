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

The agent is a minimal LiteLLM tool-calling loop over the world's MCP tools.
Tool output is truncated to 200 lines or 32K characters and the agent has a
default of 250 total steps and a 10,800 second timeout.

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

Run a task:

```bash
PYTHONPATH="$PWD/apex_loop_truncated_tools_agent" \
harbor run \
  --env-file .env \
  -d mercor/apex-agents-1-1@1.0.0 \
  -i 128-jr-1-f7f95d92 \
  -a apex_loop_truncated_tools_agent:ApexLoopTruncatedToolsAgent \
  -m anthropic/claude-opus-5
```

Run the benchmark:

```bash
PYTHONPATH="$PWD/apex_loop_truncated_tools_agent" \
harbor run \
  --env-file .env \
  -d mercor/apex-agents-1-1@1.0.0 \
  -a apex_loop_truncated_tools_agent:ApexLoopTruncatedToolsAgent \
  -m anthropic/claude-opus-5
```

### Hugging Face

Install the `hf` CLI, then download the delivery and load the three shared
images:

```bash
hf download mercor/apex-agents-v1.1 \
  --repo-type dataset \
  --local-dir apex-agents-v1.1

bash apex-agents-v1.1/environment/load_images.sh
```

Run a task:

```bash
PYTHONPATH="$PWD/apex_loop_truncated_tools_agent" \
harbor run \
  --env-file .env \
  -p apex-agents-v1.1/tasks/128-jr-1-f7f95d92 \
  -a apex_loop_truncated_tools_agent:ApexLoopTruncatedToolsAgent \
  -m anthropic/claude-opus-5 \
  -y
```

Run the benchmark:

```bash
PYTHONPATH="$PWD/apex_loop_truncated_tools_agent" \
harbor run \
  --env-file .env \
  -p apex-agents-v1.1/tasks \
  -a apex_loop_truncated_tools_agent:ApexLoopTruncatedToolsAgent \
  -m anthropic/claude-opus-5
```

Replace the model with any LiteLLM-compatible `provider/model`.

## Contact

[apex@mercor.com](mailto:apex@mercor.com)
