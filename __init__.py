"""Fixed Soundtrack: generate video over audio you already have."""

from .h3_audio import H3AudioTimelineSlice

# Node IDs are stable; saved workflows refer to them. Model-specific nodes
# carry their model's prefix, model-independent ones the pack's.
NODE_CLASS_MAPPINGS = {
    "H3AudioTimelineSlice": H3AudioTimelineSlice,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "H3AudioTimelineSlice": "H3 Audio Timeline Slice",
}
