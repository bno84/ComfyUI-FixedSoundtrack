#!/usr/bin/env python3
"""Validate the template's API prompt with ComfyUI's own validator; never enqueues or samples.

Run with ComfyUI on PYTHONPATH, both packs in ComfyUI/custom_nodes/, and the
template's models and example inputs available. For local files under other
names, pass --rename TEMPLATE_NAME=LOCAL_NAME (repeatable).
"""

import argparse
import asyncio
import json
from pathlib import Path
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--prompt", type=Path, default=Path(__file__).with_name("workflow.api.json"))
parser.add_argument("--comfyui", type=Path, default=Path("/opt/ComfyUI"))
parser.add_argument("--input-directory")
parser.add_argument("--extra-model-paths")
parser.add_argument("--rename", action="append", default=[])
args = parser.parse_args()
sys.argv = ["validate-fixedsoundtrack-template", "--cpu"]

import execution  # noqa: E402
import folder_paths  # noqa: E402
import nodes  # noqa: E402
from utils.extra_config import load_extra_path_config  # noqa: E402


async def main():
    if args.input_directory:
        folder_paths.set_input_directory(args.input_directory)
    if args.extra_model_paths:
        load_extra_path_config(args.extra_model_paths)
    await nodes.init_extra_nodes(init_custom_nodes=False, init_api_nodes=False)
    for name in ["ComfyUI-FixedSoundtrack", "ComfyUI-Minimax-H3-Continuation"]:
        if not await nodes.load_custom_node(str(args.comfyui / "custom_nodes" / name)):
            raise RuntimeError(f"Failed to load {name}")
    renames = dict(item.split("=", 1) for item in args.rename)
    prompt = json.loads(args.prompt.read_text())
    for node in prompt.values():
        for key, value in node["inputs"].items():
            if isinstance(value, str) and value in renames:
                node["inputs"][key] = renames[value]
    missing = {n["class_type"] for n in prompt.values()} - nodes.NODE_CLASS_MAPPINGS.keys()
    if missing:
        raise RuntimeError(f"Missing node types: {sorted(missing)}")
    result = await execution.validate_prompt("fixedsoundtrack-validation-only", prompt, None)
    print(json.dumps(result, indent=2, default=str))
    if not result[0] or result[3]:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
