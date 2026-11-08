"""Fixed Soundtrack: generate video over audio you already have."""

from .h3_audio import H3AudioTimelineSlice

# Node IDs are model-specific and stable; saved workflows refer to them.
NODE_CLASS_MAPPINGS = {"H3AudioTimelineSlice": H3AudioTimelineSlice}
NODE_DISPLAY_NAME_MAPPINGS = {"H3AudioTimelineSlice": "H3 Audio Timeline Slice"}
