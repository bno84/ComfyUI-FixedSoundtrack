<!--
Describe the pack as it is now: key features, usage and caveats.
This is not a changelog. Replace outdated text instead of appending to it.
-->

# Fixed Soundtrack for ComfyUI

Generate continuous, multi-clip MiniMax H3 video over a song you already have.
The song is encoded once and held fixed during sampling; the original audio
is used as the final soundtrack.

## Install

- **ComfyUI-Manager:** search for _Fixed Soundtrack_ (`comfyui-fixedsoundtrack`).
- **comfy-cli:** `comfy node install comfyui-fixedsoundtrack`.

Requires ComfyUI **0.38.0+** and
[ComfyUI-Minimax-H3-Continuation](https://github.com/ttulttul/ComfyUI-Minimax-H3-Continuation)
**0.6.3+**. Install the continuation pack from Git or choose _nightly_ in
ComfyUI-Manager ([Registry version issue](https://github.com/ttulttul/ComfyUI-Minimax-H3-Continuation/issues/3)).
Tested at `e1768d5`.

## Template: H3 Ref2VA, three clips

Open **FixedSoundtrack - H3 Ref2VA 3 clips** under **ComfyUI-FixedSoundtrack**
in the template browser. Load your song and reference images, then write each
clip's prompt.

- Clips continue the previous latent, with one final video decode.
- Each clip accepts two reference images and an optional third. References
  can be shared across clips.
- Clip N uses `seed + N − 1` from the shared seed.
- `use_original_soundtrack` defaults on. Turn it off to use the decoded audio
  latent instead of the trimmed source song.

## H3 Audio Timeline Slice

Slices the encoded song on a continuous timeline and carries the previous
clip's audio tail through the hidden overlap. It validates timing without
encoding or sampling. Follow it with **Set Latent Noise Mask** (zero) and
**LTXV Concat AV Latent**, as shown in the template.

## Save Video (Fixed Soundtrack)

An alternative to core **Save Video** with additional codec choices:

| Container | Video | Audio |
| --- | --- | --- |
| `mp4`, `mkv` | `h264`, `h265`, `av1` | `flac`, `opus`, `aac` |
| `webm` | `av1` | `opus` |

The template defaults to H.265 + Opus in MP4, CRF 18 and 128 kbit/s audio.
Choose FLAC for lossless 24-bit audio. Set video quality with `crf` or
`video_bitrate_kbps`; `audio_bitrate_kbps` controls AAC and Opus.

## Development

With ComfyUI on `PYTHONPATH` and the continuation pack beside this pack in
`custom_nodes/` (or at `H3_CONTINUATION_PATH`):

```bash
PYTHONPATH=/path/to/ComfyUI python -m unittest discover -s tests -v
```

Edit workflows directly in ComfyUI and commit the exported JSON to
`example_workflows/`.
