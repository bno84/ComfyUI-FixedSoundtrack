# Agent guidance

This is the standalone ComfyUI Fixed Soundtrack pack: video generation over a
fixed, user-supplied soundtrack. Keep registered node IDs such as
`H3AudioTimelineSlice` stable; saved workflows refer to them. Prefix new
model-specific nodes with their model (e.g. `LTX…`) and keep their code in its
own module; prefix model-independent nodes with `FixedSoundtrack`. Do not
modify or monkeypatch ComfyUI-Minimax-H3-Continuation; the template uses it
unchanged. Masking, latent encoding and sampling stay in standard nodes.

`FixedSoundtrackSaveVideo` encodes in-process with PyAV, like core Save Video:
no ffmpeg executable, subprocesses or scratch files. Keep it that way; its
tests fail if anything starts a process.

Workflows in `example_workflows/` are tracked directly. Edit them in ComfyUI
and commit the exported editor JSON, including native subgraphs and layout.
Keep `cnr_id` entries on every backend node, including nodes inside subgraphs.

Use the bno84 Git identity and signed conventional commits. Commit bodies
explain the change, then `### Why` and relevant `### Testing` notes.
Append `Assisted-by: MODEL-ID` when creating or significantly changing commits.
Do not add redundant Co-Authored-By lines for agents.

Run the tests with ComfyUI on `PYTHONPATH` and the continuation pack beside
this one: `python -m unittest discover -s tests -v`.

Publishing and remote pushes require user authorization. Local development
does not require or access Registry tokens.
