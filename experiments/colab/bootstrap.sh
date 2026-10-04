#!/usr/bin/env bash
# Run only in the dedicated Colab VM; does not manage any Colab sessions.
set -euo pipefail
cd "${VECTOR_RUN_ROOT:-/content/vector-run-decision-colab}"
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/0.12.23/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"
uv --version
uv pip install --system --index-url https://download.pytorch.org/whl/cu130 'torch==2.11.0'
uv pip install --system -r experiments/colab/requirements.txt
# Some Colab images contain an old optional torchao that Transformers 5.17
# rejects even for an unquantized model. Remove only that incompatible extra.
old_torchao=$(uv run --no-project --no-managed-python --no-sync python - <<'PY'
import importlib.metadata
from packaging.version import Version
try:
    version = importlib.metadata.version("torchao")
except importlib.metadata.PackageNotFoundError:
    print("no")
else:
    print("yes" if Version(version) < Version("0.16.0") else "no")
PY
)
if [[ "$old_torchao" == "yes" ]]; then
  uv pip uninstall --system torchao
fi
if ! command -v node >/dev/null 2>&1 || [[ "$(node --version)" != "v24.15.0" ]]; then
  node_archive=$(mktemp)
  curl -fsSL https://nodejs.org/dist/v24.15.0/node-v24.15.0-linux-x64.tar.xz -o "$node_archive"
  tar -xJf "$node_archive" -C /usr/local --strip-components=1
  rm -f "$node_archive"
fi
node --version
uv run --no-project --no-managed-python --no-sync python -c 'import torch; print({"torch": torch.__version__, "cuda": torch.version.cuda, "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None}); assert torch.cuda.is_available(), "Dedicated runtime has no available CUDA GPU"'
