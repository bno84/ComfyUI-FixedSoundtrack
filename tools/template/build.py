#!/usr/bin/env python3
"""Build the H3 three-clip template through a running ComfyUI; never queues a generation.

  python3 tools/template/build.py upload [--server URL]
      Emit the declarative graph and upload it, the browser builders and the
      example inputs to ComfyUI's user data. Then run build() in the browser.
  python3 tools/template/build.py fetch [--server URL]
      Download the saved graphs, add Registry pack IDs and model download
      links, and write them to example_workflows/ and tools/template/.
"""

import argparse
import json
from pathlib import Path
import re
import urllib.parse
import urllib.request
import uuid

PACK = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
NAME = "FixedSoundtrack - H3 Ref2VA 3 clips"
API_NAME = "fixedsoundtrack-template.api.json"
PACK_ID = "comfyui-fixedsoundtrack"
CONTINUATION_ID = "comfyui-minimax-h3-continuation"
CONTINUATION_VERSION = "e1768d5fdfc6f9519d2090dcf78458c2d9625f80"
HF = "https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main"
DASIWA = "https://civitai.com/models/2877206?modelVersionId=3392061"
MODEL = "dasiwa_minimax_h3_ref2va_v4_pruned_turbo_int8.safetensors"
DOWNLOADS = {
    "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors": "text_encoders",
    "minimax_h3_video_vae_fp16.safetensors": "vae",
    "minimax_h3_audio_vae_fp32.safetensors": "vae",
}
INPUTS = ["fixedsoundtrack-subject.png", "fixedsoundtrack-setting.png", "fixedsoundtrack-song.flac"]
nodes, links, groups = [], [], []


def node(key, kind, title, x, y, widgets=None, size=None):
    nodes.append(dict(key=key, type=kind, title=title, pos=[x, y], widgets=widgets or {}, size=size))
    return key


def link(source, slot, target, name):
    links.append([source, slot, target, name])


def group(title, x, y, width, height, color):
    groups.append(dict(title=title, bounding=[x, y, width, height], color=color))


group("01 · SHARED — models, attention, resolution and sampling", 0, 0, 3650, 760, "#35536e")
node("guide", "Note", "START HERE", 20, 55, {"text":
     "H3 · 3 Ref2VA clips · latent continuation · fixed soundtrack\n\n"
     "Load your song and two references per clip, then write each clip's prompt. Connect more IMAGE sockets on a clip for more references, or pipe one image loader into several clips.\n\n"
     "Durations are in FRAMES at fixed 24 fps. Clip 1: 5 + 17n (124 ≈ 5.17 s). Clips 2/3: NEW frames, multiples of 17 (119 ≈ 4.96 s each). Overlap is hidden and adds no output duration. Default total: 362 frames ≈ 15.08 s.\n\n"
     "The song is trimmed to the planned duration, encoded once, and frozen while each clip samples video. Short songs fail with a clear error. The output muxes the original song by default; see Output controls.\n\n"
     "One shared seed: clip N samples with seed + N − 1.\n\n"
     f"Models: [DaSiWa MiniMax H3 Hybrid v4 Turbo]({DASIWA}) (INT8, 4 steps, res_multistep/sgm_uniform, shifts 7/4, CFG-free BasicGuider) in diffusion_models. "
     f"Text encoder and VAEs: [Comfy-Org/MiniMax-H3](https://huggingface.co/Comfy-Org/MiniMax-H3). For other H3 checkpoints, adjust steps, sampler and shifts.\n\n"
     "Comfy Kitchen attention (INT8, Nvidia and AMD only) can be faster than the default PyTorch attention.\n\n"
     "Requires ComfyUI-Minimax-H3-Continuation 0.6.3 or newer, installed from Git."}, [620, 650])
node("model", "UNETLoader", "Shared H3 model · DaSiWa Hybrid v4 Turbo", 690, 60,
     {"unet_name": MODEL, "weight_dtype": "default"}, [510, 130])
node("attention", "ModelAttentionBackend", "Attention backend", 690, 260, {"attention": "pytorch attention"}, [510, 100])
node("shift", "MiniMaxH3SigmaShift", "Shared H3 video / audio shifts", 690, 430, {"shift_video": 7.0, "shift_audio": 4.0}, [510, 140])
link("model", 0, "attention", "model")
link("attention", 0, "shift", "model")
node("clip", "CLIPLoader", "Shared H3 text / vision encoder", 1280, 60,
     {"clip_name": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors", "type": "minimax"}, [540, 150])
node("video_vae", "VAELoader", "Shared H3 video VAE", 1280, 290, {"vae_name": "minimax_h3_video_vae_fp16.safetensors"}, [540, 100])
node("audio_vae", "VAELoader", "Shared H3 audio VAE", 1280, 460, {"vae_name": "minimax_h3_audio_vae_fp32.safetensors"}, [540, 100])
node("seed", "PrimitiveInt", "Shared seed · clip N uses seed + N − 1", 3300, 60, {"value": 741101}, [310, 110])
node("width", "PrimitiveInt", "Shared width · multiple of 32", 1890, 60, {"value": 832}, [320, 90])
node("height", "PrimitiveInt", "Shared height · multiple of 32", 1890, 230, {"value": 480}, [320, 90])
node("overlap", "PrimitiveInt", "Shared hidden overlap · 5 + 17n frames", 1890, 400, {"value": 22}, [320, 90])
node("sampler", "KSamplerSelect", "Shared sampler", 2310, 60, {"sampler_name": "res_multistep"}, [330, 90])
node("schedule", "BasicScheduler", "Shared schedule · full denoise", 2310, 230, {"scheduler": "sgm_uniform", "steps": 4, "denoise": 1.0}, [330, 150])
link("shift", 0, "schedule", "model")
node("zero_mask", "SolidMask", "Preserve audio · zero denoise", 2310, 470, {"value": 0.0, "width": 1, "height": 1}, [330, 130])
node("audio", "LoadAudio", "Your song", 2750, 60, {"audio": "fixedsoundtrack-song.flac"}, [470, 160])
node("encode_audio", "VAEEncodeAudio", "Encode selected song range ONCE", 2750, 310, {}, [470, 100])
node("audio_trim", "TrimAudioDuration", "Trim song BEFORE GPU encoding", 2750, 750, {}, [470, 150])
node("audio_duration", "ComfyMathExpression", "Planned song duration · H3 40 Hz", 2750, 1000,
     {"expression": "round((a + b + c) * 40 / 24) / 40"}, [470, 150])
node("audio_offset_grid", "ComfyMathExpression", "Song offset · quantize once to 40 Hz", 3300, 750,
     {"expression": "round(a * 40) / 40"}, [470, 150])
link("audio", 0, "audio_trim", "audio")
link("audio_duration", 0, "audio_trim", "duration")
link("audio_offset_grid", 0, "audio_trim", "start_index")
link("audio_trim", 0, "encode_audio", "audio")
link("audio_vae", 0, "encode_audio", "vae")
node("audio_offset", "PrimitiveFloat", "Song start offset · seconds", 2750, 500, {"value": 0.0}, [470, 90])
link("audio_offset", 0, "audio_offset_grid", "values.a")

previous = None
total = None
for i in range(1, 4):
    x = (i - 1) * 1250
    p = f"c{i}_"
    group(f"0{i+1} · CLIP {i} — own references, prompt and duration", x, 850, 1180, 2520, ["#506844", "#685340", "#604e6e"][i-1])
    node(p+"frames", "PrimitiveInt", f"Clip {i} · {'total frames · 5 + 17n' if i == 1 else 'NEW frames · multiple of 17'}", x+30, 910,
         {"value": 124 if i == 1 else 119}, [500, 90])
    link(p+"frames", 0, "audio_duration", f"values.{chr(96+i)}")
    for j, label in enumerate(["subject", "setting"]):
        node(p+f"ref{j}", "LoadImage", f"Clip {i} · <Picture {j+1}> · {label}", x+30+j*590, 1120,
             {"image": f"fixedsoundtrack-{label}.png"}, [510, 480])
    prompt = (f"subject_definitions:\n<Subject 1> is the person in <Picture 1>; preserve their appearance and clothing. "
              f"<Picture 2> supplies the setting.\n\nsummary:\nA continuous music-video performance, segment {i} of three.\n\n"
              "retention_analysis:\nPreserve the reference subject's identity and the setting. Continue the preceding movement naturally.\n\n"
              "detailed_description:\n<Subject 1> performs in the setting from <Picture 2>, with natural lip movements synchronized to the soundtrack. "
              + ["A gentle camera push-in begins as the performer turns toward the camera.",
                 "Continue the camera movement while the performer gestures and takes a small step forward.",
                 "Continue the performance and camera movement, ending on a calm, expressive close-up."][i-1])
    node(p+"ref2va", "MiniMaxH3ReferenceToVideo", f"Clip {i} · Ref2VA prompt & references", x+30, 1710,
         {"prompt": prompt, "ref_image_size": "match"}, [590, 610])
    for source, name in [("clip", "clip"), ("video_vae", "vae"), ("audio_vae", "audio_vae"), ("width", "width"), ("height", "height")]:
        link(source, 0, p+"ref2va", name)
    link(p+"ref0", 0, p+"ref2va", "ref_images.ref_image_0")
    link(p+"ref1", 0, p+"ref2va", "ref_images.ref_image_1")
    if i == 1:
        link(p+"frames", 0, p+"ref2va", "length")
        window, window_slot = p+"ref2va", 1
        conditioning, cond_slot = p+"ref2va", 0
    else:
        node(p+"window", "MiniMaxH3GuidedContinuationWindow", f"Clip {i} · unchanged upstream window", x+670, 1710, {}, [460, 210])
        link(previous, 0, p+"window", "previous_av_latent")
        link("overlap", 0, p+"window", "overlap_frames")
        link(p+"frames", 0, p+"window", "extension_frames")
        link(p+"window", 1, p+"ref2va", "length")
        window, window_slot = p+"window", 0
        node(p+"guide", "MiniMaxH3LatentTailGuide", f"Clip {i} · preceding AV tail → self-attention", x+670, 2020, {}, [460, 220])
        link(p+"ref2va", 0, p+"guide", "positive")
        link(previous, 0, p+"guide", "previous_av_latent")
        link(window, window_slot, p+"guide", "target_av_latent")
        link(p+"window", 2, p+"guide", "overlap_video_tokens")
        link(p+"window", 3, p+"guide", "overlap_audio_tokens")
        conditioning, cond_slot = p+"guide", 0
    node(p+"audio_slice", "H3AudioTimelineSlice", f"Clip {i} · exact soundtrack slice + carried audio", x+30, 2420,
         {"start_frame": 0, "overlap_audio_tokens": 0, "source_offset_seconds": 0.0}, [590, 220])
    link("encode_audio", 0, p+"audio_slice", "master_audio_latent")
    link(window, window_slot, p+"audio_slice", "window")
    # The shared source offset was already applied before encoding. Slicing is
    # relative to this trimmed master and must not apply it a second time.
    if i > 1:
        link(previous, 0, p+"audio_slice", "previous_av_latent")
        link(*total, p+"audio_slice", "start_frame")
        link(p+"window", 3, p+"audio_slice", "overlap_audio_tokens")
    node(p+"audio_mask", "SetLatentNoiseMask", f"Clip {i} · standard audio mask", x+690, 2430, {}, [440, 90])
    link(p+"audio_slice", 0, p+"audio_mask", "samples")
    link("zero_mask", 0, p+"audio_mask", "mask")
    node(p+"av", "LTXVConcatAVLatent", f"Clip {i} · standard AV assembly", x+690, 2600, {}, [440, 100])
    link(window, window_slot, p+"av", "video_latent")
    link(p+"audio_mask", 0, p+"av", "audio_latent")
    node(p+"guider", "BasicGuider", f"Clip {i} · CFG-free H3 guidance", x+30, 2790, {}, [500, 90])
    link("shift", 0, p+"guider", "model")
    link(conditioning, cond_slot, p+"guider", "conditioning")
    # Same-shaped windows would otherwise draw identical noise from one seed.
    node(p+"noise", "RandomNoise", f"Clip {i} · noise · seed + {i-1}", x+30, 2950, {}, [500, 90])
    node(p+"seed", "ComfyMathExpression", f"Clip {i} · seed offset", x+30, 3000, {"expression": f"a + {i-1}"}, [500, 150])
    link("seed", 0, p+"seed", "values.a")
    link(p+"seed", 1, p+"noise", "noise_seed")
    node(p+"sample", "SamplerCustomAdvanced", f"Clip {i} · sample video with fixed audio", x+690, 2800, {}, [440, 170])
    for source, name in [(p+"noise", "noise"), (p+"guider", "guider"), ("sampler", "sampler"), ("schedule", "sigmas"), (p+"av", "latent_image")]:
        link(source, 0, p+"sample", name)
    if i == 1:
        previous, total = p+"sample", (p+"frames", 0)
    else:
        node(p+"append", "MiniMaxH3AppendContinuation", f"Clip {i} · append only NEW frames", x+690, 3090, {}, [440, 210])
        link(previous, 0, p+"append", "previous_av_latent")
        link(p+"sample", 0, p+"append", "sampled_window")
        for index, name in [(2, "overlap_video_tokens"), (3, "overlap_audio_tokens"), (4, "transition_video_tokens"), (5, "transition_audio_tokens")]:
            link(p+"window", index, p+"append", name)
        previous, total = p+"append", (p+"append", 1)
    node(p+"report", "PreviewAny", f"Clip {i} · audio timing report", x+30, 3200, {}, [590, 230])
    link(p+"audio_slice", 1, p+"report", "source")


group("05 · JOINED OUTPUT — all 3 clips, one latent decode", 3870, 850, 1150, 1920, "#3e6063")
node("out_note", "Note", "Output controls", 3910, 920, {"text":
     "The final cumulative AV latent contains all three clips with duplicated context removed. Decode video once. Use original soundtrack defaults ON: mux the continuous trimmed source after video decoding, bypassing audio VAE loss and audio transition seams. OFF uses decoded fixed audio.\n\n"
     "The same source offset and planned range feed conditioning and final audio. No per-clip audio joins or fades are needed. Save Video still applies the chosen container's audio codec; this is waveform replacement, not compressed-stream copying.\n\n"
     "Keep playback at 24 fps. Change tiled VAE controls here if needed. Final video lands under output/video/FixedSoundtrack/.\n\n"
     "To inspect an earlier clip, reconnect Separate AV Latent to clip 1's sampler or clip 2's append.\n\n"
     "Each audio report lists exact fresh/carried token counts. The source offset is shared; per-clip durations drive the continuous audio timeline automatically."}, [1020, 300])
node("out_av", "LTXVSeparateAVLatent", "Separate final cumulative AV", 3910, 1340, {}, [470, 100])
link(previous, 0, "out_av", "av_latent")
node("decode_video", "VAEDecodeTiled", "Final video · tiled VAE controls", 3910, 1570,
     {"tile_size": 512, "overlap": 64, "temporal_size": 64, "temporal_overlap": 8}, [470, 210])
link("out_av", 0, "decode_video", "samples")
link("video_vae", 0, "decode_video", "vae")
node("decode_audio", "VAEDecodeAudio", "Decode the preserved soundtrack", 4460, 1570, {}, [470, 110])
link("out_av", 1, "decode_audio", "samples")
link("audio_vae", 0, "decode_audio", "vae")
node("output_audio", "ComfySwitchNode", "Final soundtrack · original source ON / decoded audio OFF", 4460, 1750,
     {"switch": True}, [470, 140])
link("audio_trim", 0, "output_audio", "on_true")
link("decode_audio", 0, "output_audio", "on_false")
node("create_video", "CreateVideo", "Joined video · 24 fps", 3910, 1930, {"fps": 24.0, "codec": "none"}, [470, 200])
link("decode_video", 0, "create_video", "images")
link("output_audio", 0, "create_video", "audio")
node("save_video", "SaveVideo", "Save / preview joined music video", 3910, 2270,
     {"filename_prefix": "video/FixedSoundtrack/h3_three_clips", "format": "mp4", "format.codec": "h264"}, [1020, 380])
link("create_video", 0, "save_video", "video")



def request(server, path, data=None, content_type=None):
    req = urllib.request.Request(server + path, data=data, headers={"Comfy-User": "default"})
    if content_type:
        req.add_header("Content-Type", content_type)
    with urllib.request.urlopen(req, timeout=60) as response:
        return response.read()


def put_userdata(server, name, data):
    path = "/userdata/" + urllib.parse.quote("workflows/" + name, safe="") + "?overwrite=true"
    request(server, path, data, "application/octet-stream")


def upload_input(server, path):
    boundary = uuid.uuid4().hex
    body = b"".join([
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n".encode(),
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{path.name}\"\r\n"
        "Content-Type: application/octet-stream\r\n\r\n".encode(), path.read_bytes(), f"\r\n--{boundary}--\r\n".encode(),
    ])
    request(server, "/upload/image", body, f"multipart/form-data; boundary={boundary}")


def upload(server):
    spec = dict(name=NAME, api_name=API_NAME, nodes=nodes, links=links, groups=groups)
    put_userdata(server, "fixedsoundtrack-template.build.json", json.dumps(spec, indent=2).encode())
    for script in ["build_ui.js", "compact_ui.js"]:
        put_userdata(server, "fixedsoundtrack-template." + script.removesuffix("_ui.js") + ".js", (HERE / script).read_bytes())
    for name in INPUTS:
        path = PACK / "example_inputs" / name
        if path.exists():
            upload_input(server, path)
        else:
            print(f"Missing example input, not uploaded: {path.relative_to(PACK)}")
    print("Uploaded. Run build() in a ComfyUI browser tab, then: build.py fetch")


def annotate(workflow, server, version):
    """Record each node's pack and models, as ComfyUI-Manager would."""
    info = json.loads(request(server, "/object_info"))
    core = json.loads(request(server, "/system_stats"))["system"]["comfyui_version"]
    wrappers = {graph["id"] for graph in workflow.get("definitions", {}).get("subgraphs", [])}
    for graph in [workflow, *workflow.get("definitions", {}).get("subgraphs", [])]:
        for n in graph["nodes"]:
            if n["type"] in wrappers:
                continue
            module = info.get(n["type"], {}).get("python_module", "nodes")
            props = n.setdefault("properties", {})
            props.pop("aux_id", None)
            if module.startswith("custom_nodes."):
                pack = module.split(".")[1]
                props["cnr_id"], props["ver"] = {
                    "ComfyUI-FixedSoundtrack": (PACK_ID, version),
                    "ComfyUI-Minimax-H3-Continuation": (CONTINUATION_ID, CONTINUATION_VERSION),
                }[pack]
            else:
                props["cnr_id"], props["ver"] = "comfy-core", core
            for value in n.get("widgets_values") or []:
                if value in DOWNLOADS:
                    props["models"] = [{"name": value, "url": f"{HF}/{DOWNLOADS[value]}/{value}", "directory": DOWNLOADS[value]}]


def fetch(server):
    version = re.search(r'^version = "([^"]+)"', (PACK / "pyproject.toml").read_text(), re.M).group(1)
    workflow = json.loads(request(server, "/userdata/" + urllib.parse.quote(f"workflows/{NAME}.json", safe="")))
    annotate(workflow, server, version)
    (PACK / f"example_workflows/{NAME}.json").write_text(json.dumps(workflow, indent=2, ensure_ascii=False) + "\n")
    api = json.loads(request(server, "/userdata/" + urllib.parse.quote(f"workflows/{API_NAME}", safe="")))
    (HERE / "workflow.api.json").write_text(json.dumps(api, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote example_workflows/{NAME}.json and tools/template/workflow.api.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["upload", "fetch"])
    parser.add_argument("--server", default="http://127.0.0.1:8188")
    args = parser.parse_args()
    {"upload": upload, "fetch": fetch}[args.command](args.server.rstrip("/"))
