"""MiniMax H3: slice a fixed soundtrack for latent continuation; masking stays in standard nodes."""

import math

import torch


def audio_boundary(frame):
    """Match H3 Continuation's cumulative 24 fps -> 40 Hz boundary rule."""
    return round(frame * 40 / 24)


def h3_streams(latent, name):
    samples = latent.get("samples")
    if not getattr(samples, "is_nested", False) or len(samples.tensors) != 2:
        raise ValueError(f"{name} must be a native H3 joint AV latent")
    video, audio = samples.tensors
    if video.ndim != 5 or video.shape[:2] != (1, 24):
        raise ValueError(f"{name}: expected H3 video [1,24,T,H,W]")
    if video.shape[2] < 2 or (video.shape[2] - 2) % 5:
        raise ValueError(f"{name}: video is outside H3's 5k+2 latent grid")
    if audio.ndim != 4 or audio.shape[:3] != (1, 32, 2):
        raise ValueError(f"{name}: expected H3 stereo audio [1,32,2,T]")
    return video, audio


class H3AudioTimelineSlice:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "master_audio_latent": ("LATENT", {"tooltip": "Encode the complete stereo soundtrack once with the H3 audio VAE."}),
            "window": ("LATENT", {"tooltip": "Initial Ref2VA AV latent, or upstream Guided Continuation Window."}),
            "start_frame": ("INT", {"default": 0, "min": 0, "max": 10000000,
                                    "tooltip": "New content's cumulative start frame: 0 for clip 1; previous Append Continuation total_length thereafter."}),
            "overlap_audio_tokens": ("INT", {"default": 0, "min": 0, "max": 1000000,
                                             "tooltip": "0 initially; connect the upstream window's exact overlap_audio_tokens thereafter."}),
            "source_offset_seconds": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 100000.0, "step": 0.025,
                                               "tooltip": "Skip into the master soundtrack. Rounded once to its 40 Hz grid, shared by all clips."}),
        }, "optional": {
            "previous_av_latent": ("LATENT", {"tooltip": "Previous cumulative sampled AV latent; its audio tail fills the overlap without re-encoding."}),
        }}

    RETURN_TYPES = ("LATENT", "STRING")
    RETURN_NAMES = ("window_audio_latent", "report")
    FUNCTION = "slice_audio"
    CATEGORY = "audio/H3"
    DESCRIPTION = ("Slice an encoded master on cumulative H3 audio boundaries and prepend the previous AV audio tail. "
                   "Apply standard Set Latent Noise Mask (zero) and Concat AV Latent afterwards. No encoding, sampling or masking here.")

    def slice_audio(self, master_audio_latent, window, start_frame, overlap_audio_tokens,
                    source_offset_seconds, previous_av_latent=None):
        master = master_audio_latent.get("samples")
        if not torch.is_tensor(master) or getattr(master, "is_nested", False):
            raise ValueError("master_audio_latent must contain the bare encoded H3 audio tensor")
        if master.ndim != 4 or master.shape[:2] != (1, 32) or master.shape[2] not in (1, 2):
            raise ValueError("Encode a mono or stereo soundtrack with the H3 audio VAE: expected [1,32,1 or 2,T]")
        # H3 encodes stereo lanes independently; duplicate an encoded mono lane.
        if master.shape[2] == 1:
            master = master.expand(-1, -1, 2, -1)
        if not math.isfinite(source_offset_seconds) or source_offset_seconds < 0:
            raise ValueError("source_offset_seconds must be finite and nonnegative")
        video, target_audio = h3_streams(window, "window")
        window_frames = (video.shape[2] - 2) // 5 * 17 + 5
        overlap = int(overlap_audio_tokens)
        start = int(start_frame)
        if start < 0 or overlap < 0:
            raise ValueError("start_frame and overlap_audio_tokens must be nonnegative")
        if previous_av_latent is None:
            if start != 0 or overlap != 0:
                raise ValueError("A continuation needs previous_av_latent; the first clip starts at frame 0 with no overlap")
            new_frames = window_frames
            tail = target_audio[..., :0]
        else:
            prev_video, prev_audio = h3_streams(previous_av_latent, "previous_av_latent")
            previous_frames = (prev_video.shape[2] - 2) // 5 * 17 + 5
            if start != previous_frames or prev_audio.shape[-1] != audio_boundary(start):
                raise ValueError("start_frame must match the previous cumulative clip and its exact audio boundary")
            # A valid H3 guide tail has 5k+2 video tokens. Infer its k from the
            # audio count, then verify against the cumulative clock (not duration rounding).
            matches = [n for n in range(5, min(start, window_frames - 17) + 1, 17)
                       if audio_boundary(start) - audio_boundary(start - n) == overlap]
            if len(matches) != 1:
                raise ValueError("overlap_audio_tokens does not describe a valid H3 continuation overlap")
            new_frames = window_frames - matches[0]
            if new_frames < 17 or new_frames % 17:
                raise ValueError("Fresh continuation frames must be a positive multiple of 17")
            tail = prev_audio[..., -overlap:]
        fresh_count = audio_boundary(start + new_frames) - audio_boundary(start)
        if target_audio.shape[-1] != overlap + fresh_count:
            raise ValueError("Window audio length disagrees with cumulative timing; use the upstream window unchanged")
        offset = round(source_offset_seconds * 40)
        begin = offset + audio_boundary(start)
        end = offset + audio_boundary(start + new_frames)
        if end > master.shape[-1]:
            raise ValueError(f"Soundtrack is too short: need {end} audio tokens ({end / 40:.3f}s), have {master.shape[-1]}. "
                             "Choose a longer source or reduce clip durations.")
        fresh = master[..., begin:end].to(target_audio)
        audio = torch.cat((tail.to(target_audio), fresh), dim=-1).clone()
        report = (f"New video frames {start}:{start + new_frames}; master audio tokens {begin}:{end} "
                  f"({fresh_count} fresh) + {overlap} carried = {audio.shape[-1]} window tokens. "
                  f"Source offset {offset / 40:.3f}s. Apply a zero audio noise mask before sampling.")
        return ({"samples": audio}, report)
