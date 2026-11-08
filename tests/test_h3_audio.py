"""CPU integration checks against unchanged upstream continuation and standard nodes.

Needs ComfyUI on PYTHONPATH and ComfyUI-Minimax-H3-Continuation either beside this
pack in custom_nodes/ or at H3_CONTINUATION_PATH.
"""

import importlib.util
import os
from pathlib import Path
import sys
import unittest

import torch
from comfy.nested_tensor import NestedTensor
from comfy.sampler_helpers import prepare_mask
from comfy_extras.nodes_lt import LTXVConcatAVLatent
from nodes import SetLatentNoiseMask


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


PACK = Path(__file__).resolve().parent.parent
CONTINUATION = Path(os.environ.get("H3_CONTINUATION_PATH", PACK.parent / "ComfyUI-Minimax-H3-Continuation"))
slice_module = load("fixedsoundtrack_h3_audio", PACK / "h3_audio.py")
upstream = load("h3_continuation_test", CONTINUATION / "continuation_nodes.py")


def empty(frames):
    return {"samples": NestedTensor((
        torch.zeros(1, 24, upstream.video_latent_t(frames), 2, 2),
        torch.zeros(1, 32, 2, upstream.audio_t_at_frame_boundary(frames)),
    ))}


class AudioSliceTests(unittest.TestCase):
    def setUp(self):
        self.master = {"samples": torch.arange(10000, dtype=torch.float32).view(1, 1, 1, -1).expand(1, 32, 2, -1)}
        self.node = slice_module.H3AudioTimelineSlice()

    def assemble(self, window, start, overlap=0, previous=None, offset=0):
        audio, _ = self.node.slice_audio(self.master, window, start, overlap, offset, previous)
        masked = SetLatentNoiseMask().set_mask(audio, torch.zeros(1, 1, 1))[0]
        result = LTXVConcatAVLatent.execute(window, masked).result[0]
        torch.testing.assert_close(result["samples"].tensors[0], window["samples"].tensors[0])
        self.assertEqual(torch.count_nonzero(result["noise_mask"].tensors[1]).item(), 0)
        self.assertTrue(torch.all(result["noise_mask"].tensors[0] == 1))
        for stream, mask, expected in zip(result["samples"].tensors, result["noise_mask"].tensors, [1, 0]):
            expanded = prepare_mask(mask, stream.shape, stream.device)
            self.assertEqual(expanded.shape, stream.shape)
            self.assertTrue(torch.all(expanded == expected))
        return result

    def test_three_clip_workflow_and_long_chain_have_no_audio_gaps(self):
        cumulative = self.assemble(empty(124), 0)
        start = 124
        fresh_counts = set()
        for _ in range(24):
            window, _, ov, oa, tv, ta = upstream.MiniMaxH3GuidedContinuationWindow.execute(cumulative, 22, 119).result
            sampled = self.assemble(window, start, oa, cumulative)
            fresh_counts.add(sampled["samples"].tensors[1].shape[-1] - oa)
            # The guide consumes our exact assembled target with the upstream API.
            positive = [[torch.zeros(1, 1, 4), {}]]
            guide = upstream.MiniMaxH3LatentTailGuide.execute(positive, cumulative, sampled, ov, oa).result[0]
            torch.testing.assert_close(guide[0][1]["minimax_keyframes"][0]["audio_latent"], cumulative["samples"].tensors[1][..., -oa:])
            cumulative, start = upstream.MiniMaxH3AppendContinuation.execute(cumulative, sampled, ov, oa, tv, ta).result
            torch.testing.assert_close(cumulative["samples"].tensors[1], self.master["samples"][..., :slice_module.audio_boundary(start)])
        self.assertEqual(fresh_counts, {198, 199})

    def test_mixed_duration_and_overlap_with_offset(self):
        cumulative = self.assemble(empty(243), 0, offset=0.075)
        start = 243
        for overlap, fresh in [(39, 102), (5, 51), (56, 170), (22, 119)]:
            window, _, ov, oa, tv, ta = upstream.MiniMaxH3GuidedContinuationWindow.execute(cumulative, overlap, fresh).result
            sampled = self.assemble(window, start, oa, cumulative, offset=0.075)
            cumulative, start = upstream.MiniMaxH3AppendContinuation.execute(cumulative, sampled, ov, oa, tv, ta).result
            torch.testing.assert_close(cumulative["samples"].tensors[1], self.master["samples"][..., 3:3 + slice_module.audio_boundary(start)])

    def test_rejects_short_audio_wrong_start_and_wrong_overlap(self):
        with self.assertRaisesRegex(ValueError, "too short"):
            self.node.slice_audio({"samples": self.master["samples"][..., :10]}, empty(124), 0, 0, 0)
        previous = self.assemble(empty(124), 0)
        window, _, _, oa, _, _ = upstream.MiniMaxH3GuidedContinuationWindow.execute(previous, 22, 119).result
        with self.assertRaisesRegex(ValueError, "start_frame"):
            self.node.slice_audio(self.master, window, 125, oa, 0, previous)
        with self.assertRaisesRegex(ValueError, "overlap"):
            self.node.slice_audio(self.master, window, 124, oa + 1, 0, previous)

    def test_mono_master_is_duplicated_without_changing_samples(self):
        mono = {"samples": self.master["samples"][:, :, :1]}
        result, _ = self.node.slice_audio(mono, empty(124), 0, 0, 0)
        torch.testing.assert_close(result["samples"], self.master["samples"][..., :207])


if __name__ == "__main__":
    unittest.main()
