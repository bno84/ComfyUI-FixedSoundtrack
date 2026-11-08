<!--
Describe the pack as it is now: key features, usage and caveats.
This is not a changelog. Replace outdated text instead of appending to it.
-->

# Fixed Soundtrack for ComfyUI

Generate a continuous, multi-clip video over a song you already have. The
soundtrack stays fixed: it is encoded once, frozen in each clip's sampler, and
muxed back unchanged. Only the video is generated, clip after clip, following
the song's timeline.

The first supported model is MiniMax H3 (Ref2VA) with latent continuation.
The node IDs name their model, so support for other audio-video models can be
added without breaking saved workflows.

## Install

- **ComfyUI-Manager:** search for _Fixed Soundtrack_ (Registry ID
  `comfyui-fixedsoundtrack`) and install it.
- **comfy-cli:** `comfy node install comfyui-fixedsoundtrack`.
- **Manually:** `git clone https://github.com/bno84/ComfyUI-FixedSoundtrack` into
  `ComfyUI/custom_nodes/`.

The H3 template also needs
[ComfyUI-Minimax-H3-Continuation](https://github.com/ttulttul/ComfyUI-Minimax-H3-Continuation)
**0.6.3 or newer**. The Registry currently offers only 0.1.0, which lacks the
continuation window, tail guide and append nodes. Install it from Git: in
ComfyUI-Manager choose the _nightly_ version, or `git clone` it into
`custom_nodes/`. Tested at `e1768d5`.

Restart ComfyUI afterwards. Requires ComfyUI 0.38.0 or newer. No Python
dependencies beyond ComfyUI's own.

## Template: H3 Ref2VA, three clips

Open **FixedSoundtrack - H3 Ref2VA 3 clips** from the template browser under
**ComfyUI-FixedSoundtrack**. Load your song and two reference images per clip,
then write each clip's prompt.

- **Continuous video.** Clips 2 and 3 continue the previous clip through the
  upstream latent tail guide. The final cumulative latent is decoded once.
- **Fixed song.** The song is trimmed to the planned duration and encoded once.
  Each clip gets its exact slice on H3's 24 fps / 40 Hz clocks, and the
  sampler leaves that audio untouched while it generates video.
- **Original audio in the output.** `use_original_soundtrack` (default on)
  muxes the trimmed source after video decoding: no audio VAE loss and no
  seams at clip boundaries. Off uses the decoded audio latent instead.
- **Saved as H.265 + Opus.** The pack's own **Save Video** writes MP4 at
  CRF 18 with 128 kbit/s Opus. Choose `flac` there to keep the song lossless.
- **One seed, distinct noise.** Clip N samples with `seed + N − 1`.
- **Compact canvas.** Six native subgraphs: shared settings, duration planning,
  one per clip, and decode. Settings are promoted to subgraph inputs, so
  they can also be driven by links. Each clip has two reference sockets and an
  optional third; pipe one image loader into several clips to share references.

### Models

The template uses the maintainer's file names and subfolders:

| Model | Folder | Source |
| --- | --- | --- |
| `minimax-h3/DasiwaMinimaxH3_dasiwaHybridV4Turbo_int8.safetensors` | `diffusion_models` | [DaSiWa MiniMax H3 · Hybrid v4 Turbo](https://civitai.com/models/2877206?modelVersionId=3392061) (INT8) |
| `minimax-h3/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` | `text_encoders` | [Comfy-Org/MiniMax-H3](https://huggingface.co/Comfy-Org/MiniMax-H3) |
| `MiniMax-H3-video_vae_fp16.safetensors` | `vae` | [Comfy-Org/MiniMax-H3](https://huggingface.co/Comfy-Org/MiniMax-H3) `minimax_h3_video_vae_fp16` |
| `minimax-h3/minimax_h3_audio_vae_fp32.safetensors` | `vae` | [Comfy-Org/MiniMax-H3](https://huggingface.co/Comfy-Org/MiniMax-H3) |

If yours are stored elsewhere, pick them in the shared settings subgraph.
The template offers downloads for the Comfy-Org files. Defaults suit the
turbo checkpoint: 832×480, res_multistep / sgm_uniform, 4 steps, video/audio
shifts 7 / 4, CFG-free guidance, Comfy Kitchen attention. Adjust steps, sampler and shifts
for other H3 checkpoints. Kitchen attention is INT8 and runs only on Nvidia and
AMD GPUs; choose PyTorch attention elsewhere.

### Durations

Everything runs at 24 fps, and durations are frame counts:

- Clip 1: `5 + 17n` frames. Default **124** (~5.17 s).
- Clips 2 and 3: **new** frames, a positive multiple of 17. Default **119** each.
- Hidden overlap: `5 + 17n`, at least 5, shared. Default **22**. It adds no runtime.

The core Preview as Text node below the duration controls displays a compact
text table when run: each clip's duration and end time in the joined
video, with duplicated overlap removed. Calculations and formatting live
inside the clip-duration subgraph.

The defaults give 362 frames (~15.08 s). Keep each sampled window within the
checkpoint's range, normally about 124–362 frames. Invalid timing, and songs
too short for the plan, fail with a clear error. The song start offset is
quantized to 25 ms.

## Node: H3 Audio Timeline Slice

**audio/H3 → H3 Audio Timeline Slice** returns one clip's audio latent:

1. The previous cumulative clip's exact audio tail, for the hidden overlap.
2. Fresh tokens of the once-encoded song between `round(start × 40/24)` and
   `round(end × 40/24)`, so boundaries never drift across many clips.

It checks the window, overlap and start frame against the cumulative clock
and refuses invalid combinations. It doesn't encode, mask or sample. Apply a
standard **Set Latent Noise Mask** (zero) and **LTXV Concat AV Latent**
afterwards, as the template does. Mono encodings are duplicated into stereo.

## Node: Save Video (Fixed Soundtrack)

**video → Save Video (Fixed Soundtrack)** is a drop-in for core **Save Video**
with the codec choices core lacks, so a song can stay lossless in the output:

| Container | Video | Audio |
| --- | --- | --- |
| `mp4`, `mkv` | `h264`, `h265`, `av1` | `flac`, `opus`, `aac` |
| `webm` | `av1` | `opus` |

- **Quality.** `crf` (-1 uses h264 23, h265 28, av1 30; AV1 0 is lossless), or
  an average `video_bitrate_kbps` instead. `audio_bitrate_kbps` sets AAC and
  Opus; FLAC is lossless 24-bit.
- **Like core.** It takes a `VIDEO` (e.g. from **Create Video**) and keeps its
  color space (sRGB, HDR HLG or PQ) and, on `auto`, its bit depth. Audio is
  trimmed to the video. The workflow and prompt are embedded as the same
  container tags core writes. H.265 in MP4 is tagged `hvc1`.
- **In-process.** PyAV encodes in ComfyUI's process, as core does: no ffmpeg
  executable or scratch files. The file is written under a hidden name and
  renamed when complete, so a cancelled save leaves nothing behind.

Encoders are PyAV's own CPU builds (libx264, libx265, SVT-AV1), not your
system ffmpeg's. Browsers may not preview H.265 or MKV in the ComfyUI queue;
the saved file is unaffected.

## Development

Tests need ComfyUI on `PYTHONPATH` and the continuation pack beside this one in
`custom_nodes/` (or at `H3_CONTINUATION_PATH`):

```bash
PYTHONPATH=/path/to/ComfyUI python -m unittest discover -s tests -v
```

The template is generated; see [`tools/template/`](tools/template/README.md).

## License

MIT
