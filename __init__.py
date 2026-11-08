"""Fixed Soundtrack: generate video over audio you already have."""

from .h3_audio import H3AudioTimelineSlice
from .save_video import FixedSoundtrackSaveVideo

# Node IDs are stable; saved workflows refer to them. Model-specific nodes
# carry their model's prefix, model-independent ones the pack's.
NODE_CLASS_MAPPINGS = {
    "H3AudioTimelineSlice": H3AudioTimelineSlice,
    "FixedSoundtrackSaveVideo": FixedSoundtrackSaveVideo,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "H3AudioTimelineSlice": "H3 Audio Timeline Slice",
    "FixedSoundtrackSaveVideo": "Save Video (Fixed Soundtrack)",
}
