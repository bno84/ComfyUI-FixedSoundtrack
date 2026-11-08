# Template builder

`example_workflows/FixedSoundtrack - H3 Ref2VA 3 clips.json` is generated from
these files. Edit them, not the JSON.

1. `python3 tools/template/build.py upload` emits the flat graph and uploads it,
   the browser scripts and `example_inputs/` to a running ComfyUI
   (`--server`, default `http://127.0.0.1:8188`). Both packs must be installed.
2. In a ComfyUI browser tab's console:

   ```js
   const { app } = await import('/scripts/app.js');
   const r = await fetch('/userdata/workflows%2Ffixedsoundtrack-template.build.js', {
     headers: { 'Comfy-User': 'default' }
   });
   const { build } = await import(URL.createObjectURL(new Blob([await r.text()], {
     type: 'text/javascript'
   })));
   await build(app);
   ```

   `build_ui.js` creates the flat graph from live node schemas.
   `compact_ui.js` folds it into native subgraphs and fails unless the result
   compiles to the same API prompt as the flat graph. Both graphs are saved to
   ComfyUI's workflows. Nothing is queued.
3. `python3 tools/template/build.py fetch` downloads them, adds each node's
   Registry pack ID and the Comfy-Org model download links, and writes the
   template and `workflow.api.json`.

## Layout

Node positions and sizes, groups, and which notes stay outside subgraphs come
from `layout.json`. To change them, arrange the template in ComfyUI, save it
(or snapshot the open tab with sd-cpp's `comfyui_bridge.py`), then run
`python3 tools/template/build.py layout WORKFLOW.json` and rebuild. Nodes are
matched by title; nodes without an entry keep the builder's placement.

`validate.py` runs ComfyUI's prompt validator on `workflow.api.json` without
sampling. It needs the models and example inputs; `--rename` maps template
model names to local files.
