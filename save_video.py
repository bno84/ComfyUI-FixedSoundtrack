"""Save a VIDEO with a choice of video and audio codec, encoded in-process by PyAV.

Like ComfyUI's Save Video: no ffmpeg executable, pipes or scratch files. The
file is written under a hidden sibling name and renamed into place once
complete, so a failed or cancelled save never leaves a truncated video.
"""

from fractions import Fraction
import json
import math
import os

import av
import torch
from av.video.reformatter import ColorPrimaries, ColorRange, ColorTrc

CONTAINERS = {"mp4": "mp4", "mkv": "matroska", "webm": "webm"}
VIDEO_ENCODERS = {"h264": "libx264", "h265": "libx265", "av1": "libsvtav1"}
AUDIO_ENCODERS = {"flac": "flac", "opus": "libopus", "aac": "aac"}
# WebM only stores these; MP4 and MKV store every codec offered here.
WEBM_CODECS = {"video": {"av1"}, "audio": {"opus"}}
# Core Save Video's H.264 and AV1 defaults; 28 is x265's equivalent of x264's 23.
DEFAULT_CRF = {"h264": 23, "h265": 28, "av1": 30}
MAX_CRF = {"h264": 51, "h265": 51, "av1": 63}
LAYOUTS = {1: "mono", 2: "stereo", 6: "5.1"}
COLOR_TRANSFERS = {"sRGB": ColorTrc.IEC61966_2_1, "HDR": ColorTrc.ARIB_STD_B67, "HDR PQ": ColorTrc.SMPTE2084}
BT709_NCL, BT2020_NCL = 1, 9
AUDIO_CHUNK = 4096


def check_encoders(video_codec, audio_codec=None):
    """Check the libraries PyAV actually uses, not an unrelated ffmpeg executable."""
    missing = []
    for name in (VIDEO_ENCODERS[video_codec], AUDIO_ENCODERS.get(audio_codec)):
        if name is None:
            continue
        try:
            av.Codec(name, "w")
        except (ValueError, av.error.FFmpegError):
            missing.append(name)
    if missing:
        raise RuntimeError(f"This PyAV build lacks the {', '.join(missing)} encoder. Choose another codec, "
                           "or install a PyAV build that has it; an ffmpeg executable does not change PyAV's libraries.")


def color_properties(color_space):
    """Core Save Video's tags: BT.709 with the sRGB curve, or BT.2020 with HLG or PQ."""
    hdr = color_space != "sRGB"
    return {"color_primaries": ColorPrimaries.BT2020 if hdr else ColorPrimaries.BT709,
            "color_trc": COLOR_TRANSFERS[color_space],
            "colorspace": BT2020_NCL if hdr else BT709_NCL,
            "color_range": ColorRange.MPEG}


def tag_values(metadata):
    """JSON-encode non-string values, as core Save Video does for prompt and workflow."""
    return {key: value if isinstance(value, str) else json.dumps(value) for key, value in (metadata or {}).items()}


def validate(images, container, video_codec, crf, audio, audio_codec, bit_depth, color_space):
    if container not in CONTAINERS:
        raise ValueError(f"Unknown container {container!r}; choose {', '.join(CONTAINERS)}")
    if video_codec not in VIDEO_ENCODERS:
        raise ValueError(f"Unknown video codec {video_codec!r}; choose {', '.join(VIDEO_ENCODERS)}")
    if audio_codec not in AUDIO_ENCODERS:
        raise ValueError(f"Unknown audio codec {audio_codec!r}; choose {', '.join(AUDIO_ENCODERS)}")
    if container == "webm" and video_codec not in WEBM_CODECS["video"]:
        raise ValueError("WebM stores AV1 video only here; choose av1, or the mp4 or mkv container")
    if container == "webm" and audio is not None and audio_codec not in WEBM_CODECS["audio"]:
        raise ValueError("WebM stores Opus audio only here; choose opus, or the mp4 or mkv container")
    if not -1 <= crf <= MAX_CRF[video_codec]:
        raise ValueError(f"{video_codec} CRF must be between 0 and {MAX_CRF[video_codec]}, or -1 for the default")
    if bit_depth not in (8, 10):
        raise ValueError("Bit depth must be 8 or 10")
    if color_space not in COLOR_TRANSFERS:
        raise ValueError(f"Unsupported color space {color_space!r}")
    if images.ndim != 4 or images.shape[0] == 0 or images.shape[-1] < 3:
        raise ValueError("Expected at least one RGB frame shaped [frames, height, width, channels]")
    height, width = images.shape[1:3]
    if width % 2 or height % 2:
        raise ValueError(f"{video_codec} 4:2:0 output requires even dimensions, got {width}x{height}")


def _video_stream(output, images, rate, video_codec, crf, video_bitrate, bit_depth, color_space):
    stream = output.add_stream(VIDEO_ENCODERS[video_codec], rate=rate)
    stream.height, stream.width = images.shape[1:3]
    stream.pix_fmt = "yuv420p10le" if bit_depth == 10 else "yuv420p"
    for name, value in color_properties(color_space).items():
        setattr(stream.codec_context, name, value)
    options = {}
    if video_bitrate > 0:
        # Average bitrate: x264/x265 ABR, SVT-AV1 VBR.
        stream.bit_rate = video_bitrate * 1000
    else:
        crf = DEFAULT_CRF[video_codec] if crf < 0 else crf
        if video_codec == "av1" and crf == 0:
            options["svtav1-params"] = "lossless=1"  # As core: SVT-AV1 has no CRF 0.
        else:
            options["crf"] = str(crf)
    if video_codec == "h265":
        options["x265-params"] = "log-level=warning"
        # Apple players and browsers need hvc1, not FFmpeg's default hev1.
        stream.codec_context.codec_tag = "hvc1"
    stream.options = options
    return stream


def _audio_stream(output, audio_codec, audio_bitrate, sample_rate, layout):
    encoder = av.Codec(AUDIO_ENCODERS[audio_codec], "w")
    rate = 48000 if audio_codec == "opus" else sample_rate
    rates = encoder.audio_rates
    if rates and rate not in rates:
        rate = min(rates, key=lambda value: abs(value - rate))
    stream = output.add_stream(AUDIO_ENCODERS[audio_codec], rate=rate, layout=layout)
    if audio_codec == "flac":
        stream.codec_context.format = "s32"  # FFmpeg's FLAC encoder stores 24-bit samples.
    else:
        stream.bit_rate = audio_bitrate * 1000
    return stream


def _rgb_frame(image, bit_depth, pix_fmt, color_space):
    rgb = image[..., :3].float().clamp(0, 1)
    if bit_depth == 10:
        # 16-bit RGB keeps float precision through the conversion to 10-bit YUV.
        frame = av.VideoFrame.from_ndarray((rgb * 65535).round().to(torch.uint16).cpu().numpy(), format="rgb48le")
    else:
        frame = av.VideoFrame.from_ndarray((rgb * 255).round().to(torch.uint8).cpu().numpy(), format="rgb24")
    frame = frame.reformat(format=pix_fmt, dst_colorspace=BT709_NCL if color_space == "sRGB" else BT2020_NCL,
                           dst_color_range=ColorRange.MPEG)
    for name, value in color_properties(color_space).items():
        setattr(frame, name, value)
    return frame


def encode(path, images, frame_rate, *, container="mp4", video_codec="h265", crf=-1, video_bitrate=0,
           bit_depth=8, color_space="sRGB", audio=None, audio_codec="flac", audio_bitrate=192,
           metadata=None, on_frame=None):
    """Encode [frames, H, W, C] float images and optional ComfyUI AUDIO to path.

    crf -1 uses the codec's default; video_bitrate > 0 (kbit/s) replaces CRF.
    audio_bitrate (kbit/s) applies to AAC and Opus; FLAC is lossless. Audio is
    trimmed to the video's duration, as core Save Video does.
    on_frame(written, total) runs after each frame and may raise to cancel.
    """
    validate(images, container, video_codec, crf, audio, audio_codec, bit_depth, color_space)
    check_encoders(video_codec, audio_codec if audio is not None else None)
    rate = Fraction(round(Fraction(frame_rate) * 1000), 1000)
    if rate <= 0:
        raise ValueError("Frame rate must be positive")
    frames = images.shape[0]
    waveform = None
    if audio is not None:
        source_rate = int(audio["sample_rate"])
        waveform = audio["waveform"][0]
        if waveform.shape[0] not in LAYOUTS:
            raise ValueError(f"Audio needs 1, 2 or 6 channels, got {waveform.shape[0]}")
        waveform = waveform[:, :math.ceil(source_rate * frames / rate)].float().cpu().contiguous().numpy()

    path = os.fspath(path)
    folder, name = os.path.split(os.path.abspath(path))
    # Reserve a random sibling with normal output permissions, respecting the umask.
    # mkstemp's owner-only mode would survive os.replace and break shared outputs.
    temporary = os.path.join(folder, f".{name}.{os.urandom(8).hex()}.partial")
    os.close(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666))
    try:
        options = {"movflags": "use_metadata_tags+faststart"} if container == "mp4" else {}
        with av.open(temporary, "w", format=CONTAINERS[container], options=options) as output:
            output.metadata.update(tag_values(metadata))
            video = _video_stream(output, images, rate, video_codec, crf, video_bitrate, bit_depth, color_space)
            sound = None
            if waveform is not None and waveform.shape[1]:
                layout = LAYOUTS[waveform.shape[0]]
                sound = _audio_stream(output, audio_codec, audio_bitrate, source_rate, layout)
            fed = 0

            def feed_audio(until):
                # PyAV resamples and reframes to the encoder's format, rate and frame size.
                nonlocal fed
                while sound is not None and fed < min(until, waveform.shape[1]):
                    chunk = av.AudioFrame.from_ndarray(waveform[:, fed:fed + AUDIO_CHUNK], format="fltp", layout=layout)
                    chunk.sample_rate, chunk.pts, chunk.time_base = source_rate, fed, Fraction(1, source_rate)
                    output.mux(sound.encode(chunk))
                    fed += chunk.samples

            for n in range(frames):
                # Interleave audio with video rather than appending it after all frames.
                feed_audio(math.ceil(source_rate * (n + 1) / rate) if sound is not None else 0)
                frame = _rgb_frame(images[n], bit_depth, video.pix_fmt, color_space)
                frame.pts, frame.time_base = n, 1 / rate
                output.mux(video.encode(frame))
                if on_frame:
                    on_frame(n + 1, frames)
            output.mux(video.encode(None))
            if sound is not None:
                feed_audio(waveform.shape[1])
                output.mux(sound.encode(None))
        os.replace(temporary, path)
    except BaseException:
        try:
            os.remove(temporary)
        except FileNotFoundError:
            pass
        raise


class FixedSoundtrackSaveVideo:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "video": ("VIDEO", {"tooltip": "The video to save, e.g. from Create Video."}),
            "filename_prefix": ("STRING", {"default": "video/ComfyUI",
                                           "tooltip": "May include formatting such as %date:yyyy-MM-dd% or %Empty Latent Image.width%."}),
            "container": (list(CONTAINERS), {"default": "mp4",
                                             "tooltip": "MP4 and MKV store every codec here; WebM stores AV1 with Opus only."}),
            "video_codec": (list(VIDEO_ENCODERS), {"default": "h265",
                                                   "tooltip": "CPU encoders: libx264, libx265 (tagged hvc1) and SVT-AV1."}),
            "crf": ("INT", {"default": -1, "min": -1, "max": 63,
                            "tooltip": "Lower means higher quality and larger files. -1: h264 23, h265 28, av1 30. "
                                       "AV1 0 is lossless. Ignored when video_bitrate_kbps is set."}),
            "video_bitrate_kbps": ("INT", {"default": 0, "min": 0, "max": 500000, "step": 100,
                                           "tooltip": "0 uses CRF. Otherwise an average bitrate in kbit/s, instead of CRF."}),
            "bit_depth": (["auto", "8", "10"], {"default": "auto",
                                                "tooltip": "auto keeps the video's depth: 8-bit, or 10-bit for HDR from Create Video."}),
            "audio_codec": (list(AUDIO_ENCODERS), {"default": "flac",
                                                   "tooltip": "FLAC is lossless (24-bit). Opus is resampled to 48 kHz. Ignored without audio."}),
            "audio_bitrate_kbps": ("INT", {"default": 192, "min": 16, "max": 512, "step": 16,
                                           "tooltip": "AAC and Opus bitrate in kbit/s. FLAC ignores it."}),
        }, "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"}}

    RETURN_TYPES = ("VIDEO",)
    RETURN_NAMES = ("video",)
    OUTPUT_TOOLTIPS = ("The input video, unchanged.",)
    FUNCTION = "save"
    OUTPUT_NODE = True
    CATEGORY = "video"
    DESCRIPTION = ("Save Video with H.264, H.265 or AV1 and FLAC, Opus or AAC audio, by CRF or bitrate. "
                   "Encodes in-process with PyAV like core Save Video, embedding the workflow.")

    def save(self, video, filename_prefix, container, video_codec, crf, video_bitrate_kbps, bit_depth,
             audio_codec, audio_bitrate_kbps, prompt=None, extra_pnginfo=None):
        import comfy.model_management as mm
        import comfy.utils
        import folder_paths
        from comfy.cli_args import args

        components = video.get_components()
        color_space = video.get_color_space()
        color_space = "sRGB" if color_space in (None, "auto") else color_space
        depth = 10 if (video.get_bit_depth() if bit_depth == "auto" else int(bit_depth)) >= 10 else 8
        width, height = video.get_dimensions()
        folder, name, counter, subfolder, _ = folder_paths.get_save_image_path(
            filename_prefix, folder_paths.get_output_directory(), width, height)
        file = f"{name}_{counter:05}_.{container}"
        metadata = None
        if not args.disable_metadata:
            metadata = {**(extra_pnginfo or {}), **({"prompt": prompt} if prompt is not None else {})}
        bar = comfy.utils.ProgressBar(components.images.shape[0])

        def on_frame(written, total):
            mm.throw_exception_if_processing_interrupted()
            bar.update_absolute(written, total)

        encode(os.path.join(folder, file), components.images, components.frame_rate,
               container=container, video_codec=video_codec, crf=crf, video_bitrate=video_bitrate_kbps,
               bit_depth=depth, color_space=color_space, audio=components.audio, audio_codec=audio_codec,
               audio_bitrate=audio_bitrate_kbps, metadata=metadata, on_frame=on_frame)
        return {"ui": {"images": [{"filename": file, "subfolder": subfolder, "type": "output"}], "animated": (True,)},
                "result": (video,)}
