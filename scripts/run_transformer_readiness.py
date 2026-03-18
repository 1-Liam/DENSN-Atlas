"""Report whether a live transformer adapter is configured in the environment."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from densn.artifact_store import artifact_version_info, write_json_artifact
from densn.transformer import (
    GroqChatTransformerAdapter,
    OpenAIChatTransformerAdapter,
    build_transformer_adapter_from_env,
)


def main() -> None:
    output_dir = ROOT / "artifacts" / "phase2"
    output_dir.mkdir(parents=True, exist_ok=True)
    version = artifact_version_info("phase2", root=ROOT)

    live_adapter = build_transformer_adapter_from_env()
    summary = {
        "artifact_version": version,
        "live_adapter_present": live_adapter is not None,
        "groq_api_key_present": bool(os.getenv("GROQ_API_KEY")),
        "groq_base_url_present": bool(os.getenv("GROQ_BASE_URL")),
        "groq_model": os.getenv("GROQ_MODEL"),
        "openai_api_key_present": bool(os.getenv("OPENAI_API_KEY")),
        "openai_base_url_present": bool(os.getenv("OPENAI_BASE_URL")),
        "densn_transformer_model": os.getenv("DENSN_TRANSFORMER_MODEL"),
        "adapter": None,
        "notes": [],
    }
    if isinstance(live_adapter, (OpenAIChatTransformerAdapter, GroqChatTransformerAdapter)):
        summary["adapter"] = live_adapter.describe()
    else:
        summary["notes"].append(
            "No live transformer adapter was instantiated because neither GROQ_API_KEY nor OPENAI_API_KEY is set."
        )

    write_json_artifact(output_dir / "transformer_readiness.json", summary, version=version)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
