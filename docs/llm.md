# Local LLM Setup (llama.cpp)

This project supports an optional local LLM path via `llama-cpp-python`. It is disabled by default and falls back to extractive answers.

## Install
```bash
cd backend
uv venv
source .venv/bin/activate
uv pip install -e ".[dev,llm]"
```

## Get a GGUF Model
- Download a GGUF model you are allowed to use and redistribute.
- Check the model license explicitly (weights are often licensed separately from code).

### Download via Hugging Face CLI (recommended with uv)
The `hf` CLI is shipped with `huggingface_hub` and can be run without installing via `uvx`:

```bash
uvx hf download <org>/<repo> --local-dir ./models
```

Example of an Apache-2.0 licensed GGUF model:
```bash
uvx hf download llmware/qwen2.5-vl-3b-instruct-gguf --local-dir ./models
```

Then set `RAG_LLM_MODEL_PATH` to the `.gguf` file in `./models`.

## Environment Variables
```bash
export RAG_USE_LLM=1
export RAG_LLM_MODEL_PATH=/absolute/path/to/model.gguf
```

Optional tuning:
- `RAG_LLM_CTX` (default: `2048`)
- `RAG_LLM_THREADS` (default: `4`)
- `RAG_LLM_GPU_LAYERS` (default: `0` for CPU; increase on GPU machine)
- `RAG_LLM_CHAT_FORMAT` (override chat template if your model needs it)

## Run
```bash
uvicorn app.main:app --reload
```

## Notes
- If `RAG_USE_LLM=1` and `RAG_LLM_MODEL_PATH` is missing, the API returns a 400 error.
- The LLM is instructed to answer in Italian and only use provided context.
