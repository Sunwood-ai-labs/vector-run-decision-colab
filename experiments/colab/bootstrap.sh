#!/usr/bin/env bash
# Run only in the dedicated Colab VM; does not manage any Colab sessions.
set -euo pipefail
cd "${VECTOR_RUN_ROOT:-/content/vector-run}"
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/0.12.23/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"
uv --version
uv pip install --system --index-url https://download.pytorch.org/whl/cu130 'torch==2.11.0'
uv pip install --system -r experiments/colab/requirements.txt
if ! command -v node >/dev/null 2>&1; then
  node_archive=$(mktemp)
  curl -fsSL https://nodejs.org/dist/v24.15.0/node-v24.15.0-linux-x64.tar.xz -o "$node_archive"
  tar -xJf "$node_archive" -C /usr/local --strip-components=1
  rm -f "$node_archive"
fi
node --version
uv run --no-project --no-managed-python --no-sync python -c 'import torch; print({"torch": torch.__version__, "cuda": torch.version.cuda, "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None}); assert torch.cuda.is_available(), "Dedicated runtime has no available CUDA GPU"'
