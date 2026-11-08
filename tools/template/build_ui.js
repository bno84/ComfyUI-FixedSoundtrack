// Materialize the declarative graph using the installed frontend's node schemas.
// Run in a ComfyUI tab after `build.py upload`. Never queues a generation.
export async function build(app) {
  const response = await fetch('/userdata/workflows%2Ffixedsoundtrack-template.build.json', {headers: {'Comfy-User': 'default'}});
  if (!response.ok) throw new Error(`Read graph specification: ${response.status}`);
  const spec = await response.json();
  await app.loadGraphData({last_node_id: 0, last_link_id: 0, nodes: [], links: [], groups: [], config: {}, extra: {}, version: 0.4}, true, true, spec.name);
  const lookup = {};
  for (const item of spec.nodes) {
    const n = LiteGraph.createNode(item.type);
    if (!n) throw new Error(`Missing node: ${item.type}`);
    app.graph.add(n);
    n.title = item.title;
    n.pos = item.pos;
    for (const [name, value] of Object.entries(item.widgets)) {
      let w = n.widgets?.find(w => w.name === name);
      if (!w && name === 'text' && item.type === 'Note') w = n.widgets?.[0];
      if (!w) throw new Error(`${item.key}: missing widget ${name}`);
      w.value = value;
      w.callback?.(value, app.canvas, n);
    }
    if (item.size) n.size = item.size;
    lookup[item.key] = n;
  }
  for (const [from, slot, to, name] of spec.links) {
    const target = lookup[to];
    const index = target.inputs?.findIndex(i => i.name === name);
    if (index === undefined || index < 0) throw new Error(`${to}: missing input ${name}; found ${target.inputs?.map(i=>i.name)}`);
    if (!lookup[from].connect(slot, target, index)) throw new Error(`Cannot connect ${from}:${slot} -> ${to}:${name}`);
  }
  for (const item of spec.groups) {
    const group = new LiteGraph.LGraphGroup(item.title);
    group.color = item.color;
    group.pos = item.bounding.slice(0, 2);
    group.size = item.bounding.slice(2);
    app.graph.add(group);
  }
  app.canvas.ds.scale = 0.24;
  app.canvas.ds.offset = [120, 100];
  app.graph.setDirtyCanvas(true, true);
  const compactResponse = await fetch('/userdata/workflows%2Ffixedsoundtrack-template.compact.js', {headers: {'Comfy-User': 'default'}});
  if (!compactResponse.ok) throw new Error(`Read subgraph builder: ${compactResponse.status}`);
  const { compact } = await import(URL.createObjectURL(new Blob([await compactResponse.text()], {type: 'text/javascript'})));
  await compact(app);
  const prompt = await app.graphToPrompt();
  const save = async (name, value) => {
    const r = await fetch('/userdata/' + encodeURIComponent('workflows/' + name) + '?overwrite=true', {
      method: 'POST', headers: {'Content-Type': 'application/json', 'Comfy-User': 'default'}, body: JSON.stringify(value, null, 2)
    });
    if (!r.ok) throw new Error(`Save ${name}: ${r.status} ${await r.text()}`);
  };
  await save(`${spec.name}.json`, prompt.workflow);
  await save(spec.api_name, prompt.output);
  return {nodes: app.graph._nodes.length, subgraphs: app.graph.subgraphs.size, apiNodes: Object.keys(prompt.output).length, name: spec.name};
}
