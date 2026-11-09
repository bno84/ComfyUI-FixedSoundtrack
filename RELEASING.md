# Releasing

Releases are tag-driven. `.github/workflows/ci.yml` runs the checks on every
push and pull request. A pushed `v*` tag also publishes to the
[Comfy Registry](https://registry.comfy.org/publishers/bno84), after the checks
pass.

## Before the first release

- Replace the stand-ins in `example_inputs/` with redistributable demo media,
  update the workflow in `example_workflows/` and its thumbnail.
- Add a template screenshot to `docs/` and the README.

## Video Finish dependency

The template saves with Video Finish's `VideoFinishSaveVideo`. CI installs
Video Finish at `VIDEOFINISH_REF`, which must be a pushed commit of
`bno84/ComfyUI-VideoFinish`. Publish a Video Finish version with that node
before a Fixed Soundtrack release that needs it.

## One-time setup

Create a personal access token on the Registry publisher page. Add it to this
repository as an Actions secret named `REGISTRY_ACCESS_TOKEN` (Settings →
Secrets and variables → Actions).

## Release

1. Set the new version in `pyproject.toml` (`X.Y.Z`, semantic versioning).
   Commit it, e.g. `build: releases X.Y.Z`.
2. Push `main`: `git push origin main`. Wait for CI to pass on that exact
   commit before tagging. If another commit is added, wait for its CI too.
3. Create a signed, annotated tag on the tested commit. Its message becomes
   the Registry changelog:

   ```bash
   git tag -s vX.Y.Z -m "Short summary

   Longer notes for the Registry's Updates section."
   ```

4. Push only the tag: `git push origin vX.Y.Z`. The tag workflow repeats
   the checks and publishes only after they pass.

## What CI checks before publishing

- The tag matches the `pyproject.toml` version.
- `comfy node validate`: Registry metadata and comfy-cli's security scan.
  The scan's rules (`exec`, `eval`, one-line multi-statements) fail here,
  although comfy-cli itself only warns for now.
- Python unit and integration tests against ComfyUI and the pinned
  continuation pack (`H3_CONTINUATION_REF`), on Python 3.10 and 3.12.
- ComfyUI loads the pack and the continuation pack on CPU: no import
  failure and all node types register. The template may only use node types
  that ComfyUI, this pack and the continuation pack provide. Every
  backend node needs a pack entry (`cnr_id`): ComfyUI only adds them when
  ComfyUI-Manager is installed.

The ComfyUI version tested is `COMFYUI_REF` in the workflow. Keep it equal to
`requires-comfyui` in `pyproject.toml` when raising either.

If a check fails, nothing is published. Fix it, then move the tag
(`git tag -d vX.Y.Z`, `git push origin :refs/tags/vX.Y.Z`) and push again.
Treat a published version as final; release fixes as a new version.
