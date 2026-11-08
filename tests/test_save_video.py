"""In-process PyAV encoding checks: no FFmpeg or FFprobe executable is used.

The node test needs ComfyUI on PYTHONPATH; the encoder tests need only PyAV and torch.
"""

import importlib.util
import itertools
import json
import math
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import av
import numpy as np
import torch

PACK = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("fixedsoundtrack_save_video", PACK / "save_video.py")
sv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sv)


def gradient(frames=24, height=48, width=64):
    return torch.linspace(0, 1, frames * height * width * 3).view(frames, height, width, 3)


def tone(seconds=1.0, rate=44100, channels=2):
    t = torch.arange(round(seconds * rate)) / rate
    return {"waveform": torch.stack([.3 * torch.sin(2 * math.pi * (440 + 220 * c) * t) for c in range(channels)])[None],
            "sample_rate": rate}


def decoded_audio(path):
    """Planar float samples [channels, samples] at the stream's own rate."""
    with av.open(str(path)) as source:
        stream = source.streams.audio[0]
        resampler = av.AudioResampler(format="fltp", layout=stream.layout.name, rate=stream.sample_rate)
        frames = [f for frame in source.decode(audio=0) for f in resampler.resample(frame)]
        frames += resampler.resample(None)
        return np.concatenate([f.to_ndarray() for f in frames], axis=1)


class EncodeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # A regression to subprocess encoding fails, even when FFmpeg happens to be installed.
        guard = patch.object(subprocess, "Popen", side_effect=AssertionError("external process"))
        guard.start()
        self.addCleanup(guard.stop)

    def path(self, name):
        return os.path.join(self.tmp.name, name)

    def test_every_supported_combination_round_trips(self):
        metadata = {"prompt": {"1": {"class_type": "X"}}, "workflow": {"nodes": []}}
        for container, video_codec, audio_codec in itertools.product(sv.CONTAINERS, sv.VIDEO_ENCODERS, sv.AUDIO_ENCODERS):
            if container == "webm" and (video_codec, audio_codec) != ("av1", "opus"):
                continue
            with self.subTest(container=container, video=video_codec, audio=audio_codec):
                path = self.path(f"{video_codec}-{audio_codec}.{container}")
                sv.encode(path, gradient(), 24, container=container, video_codec=video_codec,
                          audio=tone(), audio_codec=audio_codec, metadata=metadata)
                with av.open(path) as source:
                    video, audio = source.streams.video[0], source.streams.audio[0]
                    self.assertEqual(video.codec_context.codec.canonical_name, {"h264": "h264", "h265": "hevc", "av1": "av1"}[video_codec])
                    self.assertEqual(audio.codec_context.codec.canonical_name, audio_codec)
                    self.assertEqual(audio.sample_rate, 48000 if audio_codec == "opus" else 44100)
                    self.assertEqual(len(audio.layout.channels), 2)
                    if container == "mp4" and video_codec == "h265":
                        self.assertEqual(video.codec_tag, "hvc1")
                    self.assertEqual((video.color_primaries, video.color_trc, video.colorspace), (1, 13, 1))
                    tags = {key.lower(): value for key, value in source.metadata.items()}
                    self.assertEqual(json.loads(tags["prompt"]), metadata["prompt"])
                    self.assertEqual(json.loads(tags["workflow"]), metadata["workflow"])
                    self.assertEqual(sum(1 for _ in source.decode(video=0)), 24)
                self.assertEqual(os.listdir(self.tmp.name).count(os.path.basename(path)), 1)
        self.assertFalse([name for name in os.listdir(self.tmp.name) if name.startswith(".")])

    def test_flac_is_lossless_and_trimmed_to_the_video(self):
        audio = tone(seconds=2.0, channels=1)
        path = self.path("lossless.mkv")
        sv.encode(path, gradient(), 24, container="mkv", video_codec="h264", audio=audio, audio_codec="flac")
        samples = decoded_audio(path)
        source = audio["waveform"][0, :, :44100].numpy()
        self.assertEqual(samples.shape, source.shape)
        np.testing.assert_allclose(samples, source, atol=2 ** -22)

    def test_ten_bit_and_hdr_tags(self):
        path = self.path("hdr.mkv")
        sv.encode(path, gradient(), 24, container="mkv", video_codec="h265", bit_depth=10, color_space="HDR PQ")
        with av.open(path) as source:
            video = source.streams.video[0]
            self.assertEqual(video.codec_context.pix_fmt, "yuv420p10le")
            self.assertEqual((video.color_primaries, video.color_trc, video.colorspace), (9, 16, 9))
            self.assertFalse(source.streams.audio)

    def test_video_bitrate_replaces_crf(self):
        noise = torch.rand(48, 96, 128, 3, generator=torch.Generator().manual_seed(1))
        sizes = {}
        for kbps in (100, 2000):
            path = self.path(f"{kbps}.mp4")
            sv.encode(path, noise, 24, video_codec="h264", video_bitrate=kbps)
            sizes[kbps] = os.path.getsize(path)
            # Within a factor of two of the requested average bitrate over two seconds.
            self.assertLess(abs(math.log2(sizes[kbps] * 8 / 2 / (kbps * 1000))), 1)

    def test_invalid_choices_fail_before_writing(self):
        cases = [
            (dict(container="webm", video_codec="h265", audio_codec="opus"), "AV1 video only"),
            (dict(container="webm", video_codec="av1", audio_codec="flac"), "Opus audio only"),
            (dict(video_codec="h264", crf=52), "between 0 and 51"),
            (dict(bit_depth=12), "8 or 10"),
        ]
        for kwargs, message in cases:
            with self.subTest(**kwargs), self.assertRaisesRegex(ValueError, message):
                sv.encode(self.path("x.mp4"), gradient(), 24, audio=tone(), **kwargs)
        with self.assertRaisesRegex(ValueError, "even dimensions"):
            sv.encode(self.path("x.mp4"), gradient(width=63), 24)
        with self.assertRaisesRegex(ValueError, "1, 2 or 6 channels"):
            sv.encode(self.path("x.mp4"), gradient(), 24, audio=tone(channels=3))
        self.assertEqual(os.listdir(self.tmp.name), [])

    def test_webm_without_audio_ignores_audio_codec(self):
        sv.encode(self.path("silent.webm"), gradient(), 24, container="webm", video_codec="av1", audio_codec="flac")

    def test_cancel_leaves_no_partial_file(self):
        def cancel(written, total):
            if written == 3:
                raise InterruptedError("cancelled")
        with self.assertRaises(InterruptedError):
            sv.encode(self.path("cancelled.mp4"), gradient(), 24, audio=tone(), on_frame=cancel)
        self.assertEqual(os.listdir(self.tmp.name), [])

    def test_output_respects_umask(self):
        previous = os.umask(0o022)
        try:
            path = self.path("shared.mp4")
            sv.encode(path, gradient(), 24)
        finally:
            os.umask(previous)
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o644)

    def test_missing_encoder_names_the_pyav_build(self):
        real = av.Codec

        def codec(name, mode):
            if name == "libx265":
                raise ValueError("unavailable")
            return real(name, mode)
        with patch.object(sv.av, "Codec", side_effect=codec), self.assertRaisesRegex(RuntimeError, "lacks the libx265"):
            sv.encode(self.path("x.mp4"), gradient(), 24)


class NodeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import comfy.options
        except ImportError:
            raise unittest.SkipTest("ComfyUI is not on PYTHONPATH")
        # Select ComfyUI's CPU mode before model management probes for a GPU.
        comfy.options.enable_args_parsing()
        argv, sys.argv = sys.argv, [sys.argv[0], "--cpu"]
        import comfy.cli_args  # noqa: F401
        sys.argv = argv

    def test_saves_into_the_output_folder_with_workflow(self):
        import folder_paths
        from comfy_api.latest import InputImpl, Types

        with tempfile.TemporaryDirectory() as output:
            previous = folder_paths.get_output_directory()
            folder_paths.set_output_directory(output)
            self.addCleanup(folder_paths.set_output_directory, previous)
            video = InputImpl.VideoFromComponents(Types.VideoComponents(images=gradient(), audio=tone(), frame_rate=24))
            result = sv.FixedSoundtrackSaveVideo().save(
                video, "video/test", "mp4", "h265", -1, 0, "auto", "opus", 128,
                prompt={"1": {"class_type": "FixedSoundtrackSaveVideo"}}, extra_pnginfo={"workflow": {"nodes": []}})
            self.assertIs(result["result"][0], video)
            saved = result["ui"]["images"][0]
            self.assertEqual((saved["subfolder"], saved["type"]), ("video", "output"))
            path = os.path.join(output, saved["subfolder"], saved["filename"])
            with av.open(path) as source:
                self.assertEqual(source.streams.video[0].codec_context.pix_fmt, "yuv420p")
                self.assertEqual(source.streams.audio[0].codec_context.codec.canonical_name, "opus")
                self.assertEqual(json.loads(source.metadata["workflow"]), {"nodes": []})
                self.assertIn("1", json.loads(source.metadata["prompt"]))
            again = sv.FixedSoundtrackSaveVideo().save(video, "video/test", "mkv", "h264", 20, 0, "10", "aac", 192)
            self.assertNotEqual(again["ui"]["images"][0]["filename"], saved["filename"])


if __name__ == "__main__":
    unittest.main()
