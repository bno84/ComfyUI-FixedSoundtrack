// Reorganize the flat H3 template graph using native subgraphs.
// Preserves node values and connections; never queues a generation.
export async function compact(app, layout = null) {
  const graph = app.graph;
  if (graph.subgraphs.size) throw new Error('Expected the flat H3 chain; already has subgraphs.');
  const beforePrompt = (await app.graphToPrompt()).output;
  const original = graph._nodes.slice();
  const named = title => original.find(n => n.title === title);
  const find = (nodes, type) => nodes.find(n => n.type === type);
  const byPrefix = prefix => original.filter(n => n.title?.startsWith(prefix));

  // Native Markdown notes, preserving the substantive instructions.
  for (const old of original.filter(n => n.type === 'Note')) {
    const md = LiteGraph.createNode('MarkdownNote');
    graph.add(md);
    md.title = old.title;
    md.pos = [...old.pos];
    md.size = [...old.size];
    const text = old.widgets?.[0]?.value ?? '';
    md.widgets[0].value = `## ${old.title}\n\n` + text
      .replace('H3 · 3 Ref2VA clips · latent continuation · fixed soundtrack', '**Three Ref2VA clips · latent continuation · fixed soundtrack**')
      .replace('Durations are in FRAMES', '**Durations are in frames**')
      .replace('Kitchen attention defaults ON', '**Kitchen attention defaults on**');
    graph.remove(old);
    original[original.indexOf(old)] = md;
  }

  const wrap = (title, nodes) => {
    if (nodes.some(n => !n)) throw new Error(`Missing members for ${title}`);
    // Native conversion clones dynamic V3 nodes before their autogrow IMAGE
    // sockets have settled. Preserve endpoints by NAME, not transient slot index.
    const targets = new Map();
    const values = new Map();
    for (const n of nodes) {
      for (const input of n.inputs ?? []) if (input.link != null)
        targets.set(input.link, {id: n.id, name: input.name});
      values.set(String(n.id), new Map((n.widgets ?? []).map(w => [w.name, w.value])));
    }
    const result = graph.convertToSubgraph(new Set(nodes));
    result.subgraph.name = title;
    result.node.title = title;
    const sg = result.subgraph;
    const edges = [...sg.links.values()].map(l => ({
      id: l.id, from: l.origin_id, slot: l.origin_slot, to: l.target_id,
      targetSlot: l.target_slot, name: targets.get(l.id)?.name, type: l.type
    }));
    // Reconnect through native APIs so both endpoint slots AND topology indexes
    // agree. Assigning .link directly would disconnect reactive links.
    for (const edge of edges) sg.removeLink(edge.id);
    edges.sort((a, b) => {
      const rank = e => e.name?.startsWith('ref_images.') ? Number(e.name.split('_').at(-1)) : 100;
      return rank(a) - rank(b);
    });
    for (const edge of edges) {
      const origin = sg.getNodeById(edge.from);
      const target = sg.getNodeById(edge.to);
      let link;
      if (!target) {
        link = sg.outputNode.slots[edge.targetSlot].connect(origin.outputs[edge.slot], origin);
      } else {
        let index = edge.name ? target.inputs.findIndex(i => i.name === edge.name) : edge.targetSlot;
        if (index < 0) {
          target.addInput(edge.name, edge.type);
          index = target.inputs.findIndex(i => i.name === edge.name);
        }
        link = origin ? origin.connect(edge.slot, target, index)
          : sg.inputNode.slots[edge.slot].connect(target.inputs[index], target);
      }
      if (!link) throw new Error(`${title}: cannot restore ${edge.from} -> ${edge.to}.${edge.name}`);
    }
    for (const n of sg._nodes) for (const w of n.widgets ?? []) {
      const value = values.get(String(n.id));
      if (value?.has(w.name)) w.value = value.get(w.name);
    }
    return result;
  };
  const expose = (wrapped, node, inputName, externalName) => {
    const input = node.inputs?.find(i => i.name === inputName);
    if (!input) throw new Error(`${wrapped.node.title}: ${node.type} has no ${inputName} input`);
    if (input.link != null) throw new Error(`Cannot promote connected input ${node.title}.${inputName}`);
    const slot = wrapped.subgraph.addInput(externalName, input.type);
    if (!slot.connect(input, node)) throw new Error(`Cannot promote ${node.title}.${inputName}`);
    return slot;
  };
  const labelInputs = wrapped => {
    for (const slot of wrapped.subgraph.inputs) {
      const link = wrapped.subgraph.getLink(slot.linkIds[0]);
      const target = link && wrapped.subgraph.getNodeById(link.target_id);
      const input = target?.inputs?.[link.target_slot];
      if (!input || slot._widget) continue;
      const label = target.type === 'ComfyMathExpression' && /seed/i.test(target.title)
        ? 'Shared seed'
        : input.name === 'on_true' ? 'Original song'
        : target.type === 'TrimAudioDuration' && input.name === 'audio' ? 'Song'
        : target.type === 'TrimAudioDuration' && input.name === 'duration' ? 'Planned duration'
        : input.name === 'vae'
        ? (target.type === 'VAEDecodeAudio' ? 'Audio VAE' : 'Video VAE')
        : input.name === 'av_latent' || input.name === 'previous_av_latent'
          ? 'Previous / cumulative AV'
          : input.name.startsWith('ref_images.')
            ? `Reference ${Number(input.name.split('_').at(-1)) + 1}`
            : input.name.replaceAll('_', ' ');
      wrapped.subgraph.renameInput(slot, label);
    }
    for (const slot of wrapped.subgraph.outputs) {
      const edge = wrapped.subgraph.getLink(slot.linkIds[0]);
      const origin = edge && wrapped.subgraph.getNodeById(edge.origin_id);
      if (!origin) continue;
      let label = origin.outputs[edge.origin_slot]?.name ?? slot.name;
      if (origin.type === 'VAELoader') label = /audio/i.test(origin.title) ? 'Audio VAE' : 'Video VAE';
      if (origin.type === 'CLIPLoader') label = 'Text / vision encoder';
      if (origin.type === 'MiniMaxH3SigmaShift') label = 'Shared H3 model';
      if (origin.type === 'PrimitiveInt') label = /width/i.test(origin.title) ? 'Width'
        : /height/i.test(origin.title) ? 'Height' : /overlap/i.test(origin.title) ? 'Hidden overlap' : 'Total frames';
      if (origin.type === 'SolidMask') label = 'Audio preserve mask';
      if (origin.type === 'VAEEncodeAudio') label = 'Encoded master soundtrack';
      if (origin.type === 'PrimitiveFloat') label = 'Soundtrack offset';
      if (origin.type === 'SamplerCustomAdvanced' || origin.type === 'MiniMaxH3AppendContinuation')
        label = edge.origin_slot === 0 ? 'Cumulative AV latent' : 'Total frames';
      wrapped.subgraph.renameOutput(slot, label);
    }
  };

  // Keep native Save Video outside so its dynamic codec/quality controls and
  // render preview remain available without awkward nested dynamic-combo proxies.
  // Notes the layout keeps on the main canvas stay out of the decode subgraph.
  const outside = new Set(layout?.outside ?? []);
  const outputMembers = [...(outside.has('Output controls') ? [] : [named('Output controls')]), ...original.filter(n =>
    ['LTXVSeparateAVLatent', 'VAEDecodeTiled', 'VAEDecodeAudio', 'ComfySwitchNode', 'CreateVideo'].includes(n.type))];
  const output = wrap('Decode final video + fixed audio', outputMembers);
  const decoder = find(output.subgraph._nodes, 'VAEDecodeTiled');
  for (const [name, external] of [
    ['tile_size', 'vae_tile_size'], ['overlap', 'vae_tile_overlap'],
    ['temporal_size', 'vae_temporal_size'], ['temporal_overlap', 'vae_temporal_overlap']
  ]) expose(output, decoder, name, external);
  const create = find(output.subgraph._nodes, 'CreateVideo');
  expose(output, find(output.subgraph._nodes, 'ComfySwitchNode'), 'switch', 'use_original_soundtrack');
  expose(output, create, 'bit_depth', 'video_bit_depth');
  expose(output, create, 'color_space', 'video_color_space');
  // 24 fps and the intermediate codec=none implement the fixed H3 clock and
  // the single final encode; the meaningful final codec controls stay on Save Video.
  labelInputs(output);

  const clips = [];
  for (let i = 1; i <= 3; i++) {
    const members = byPrefix(`Clip ${i} · `).filter(n => !['LoadImage', 'PrimitiveInt'].includes(n.type));
    const wrapped = wrap(`Clip ${i} · Ref2VA ${i === 1 ? 'initial' : 'continuation'}`, members);
    const inner = wrapped.subgraph._nodes;
    const ref = find(inner, 'MiniMaxH3ReferenceToVideo');
    expose(wrapped, ref, 'prompt', 'prompt');
    expose(wrapped, ref, 'ref_image_size', 'reference_image_size');
    // Expose another optional IMAGE socket on each clip face. When unconnected,
    // the native optional reference is omitted from the compiled prompt.
    const extra = ref.inputs.find(input => input.name === 'ref_images.ref_image_2');
    if (extra) expose(wrapped, ref, extra.name, 'optional_reference_3');
    labelInputs(wrapped);
    clips.push(wrapped);
  }

  const plan = wrap('Clip durations · GPU audio encoding range', [
    ...original.filter(n => n.type === 'PrimitiveInt' && n.title.startsWith('Clip ')),
    named('Planned song duration · H3 40 Hz')
  ]);
  for (let i = 1; i <= 3; i++) {
    const frames = plan.subgraph._nodes.find(n => n.type === 'PrimitiveInt' && n.title.startsWith(`Clip ${i} · `));
    expose(plan, frames, 'value', i === 1 ? 'clip_1_frames_5_plus_17n' : `clip_${i}_new_frames_multiple_of_17`);
  }
  labelInputs(plan);

  const sharedTypes = new Set(['UNETLoader', 'CLIPLoader', 'VAELoader', 'ModelAttentionBackend',
    'MiniMaxH3SigmaShift', 'PrimitiveInt', 'PrimitiveFloat', 'KSamplerSelect', 'BasicScheduler',
    'SolidMask', 'VAEEncodeAudio', 'TrimAudioDuration', 'ComfyMathExpression']);
  const shared = wrap('Shared H3 · models, size, sampling & audio', graph._nodes.filter(n => sharedTypes.has(n.type) && !n.title.startsWith('Shared seed')));
  const inner = shared.subgraph._nodes;
  const promote = (type, pairs) => {
    const n = find(inner, type);
    for (const [name, label] of pairs) expose(shared, n, name, label);
  };
  promote('UNETLoader', [['unet_name', 'diffusion_model'], ['weight_dtype', 'weight_dtype']]);
  promote('CLIPLoader', [['clip_name', 'text_vision_encoder'], ['device', 'text_encoder_device']]);
  for (const n of inner.filter(n => n.type === 'VAELoader'))
    expose(shared, n, 'vae_name', /audio/i.test(n.title) ? 'audio_vae' : 'video_vae');
  promote('ModelAttentionBackend', [['attention', 'attention_backend']]);
  promote('MiniMaxH3SigmaShift', [['shift_video', 'video_shift'], ['shift_audio', 'audio_shift']]);
  for (const [title, label] of [
    ['Shared width · multiple of 32', 'width_multiple_of_32'],
    ['Shared height · multiple of 32', 'height_multiple_of_32'],
    ['Shared hidden overlap · 5 + 17n frames', 'hidden_overlap_5_plus_17n'],
    ['Song start offset · seconds', 'song_offset_seconds']
  ]) expose(shared, inner.find(n => n.title === title), 'value', label);
  promote('KSamplerSelect', [['sampler_name', 'sampler']]);
  promote('BasicScheduler', [['scheduler', 'scheduler'], ['steps', 'steps'], ['denoise', 'denoise']]);
  labelInputs(shared);

  // Remove the old full-size group boxes; media pickers stay visible and useful.
  for (const group of [...graph._groups]) graph.remove(group);
  const note = graph._nodes.find(n => n.type === 'MarkdownNote');
  note.pos = [0, 40]; note.size = [450, 700];
  shared.node.pos = [520, 40]; shared.node.size = [1000, 820];
  const seed = graph._nodes.find(n => n.title?.startsWith('Shared seed'));
  seed.pos = [1600, 40]; seed.size = [400, 110];
  const audio = graph._nodes.find(n => n.type === 'LoadAudio');
  audio.pos = [1600, 250]; audio.size = [400, 180];
  plan.node.pos = [1600, 540]; plan.node.size = [400, 280];
  output.node.pos = [2140, 40]; output.node.size = [650, 420];
  const save = graph._nodes.find(n => n.type === 'SaveVideo');
  save.pos = [2140, 600]; save.size = [650, 470];
  for (let i = 1; i <= 3; i++) {
    const x = (i - 1) * 700;
    const refs = graph._nodes.filter(n => n.type === 'LoadImage' && n.title.startsWith(`Clip ${i} · `));
    refs.forEach((n, j) => { n.pos = [x + j * 330, 1120]; n.size = [310, 350]; });
    clips[i-1].node.pos = [x, 1570]; clips[i-1].node.size = [650, 1000];
  }
  const addGroup = (name, bounding, color) => {
    const g = new LiteGraph.LGraphGroup(name); g.pos = bounding.slice(0, 2); g.size = bounding.slice(2); g.color = color; graph.add(g);
  };
  addGroup('Shared controls · one seed and one soundtrack', [490, 0, 1550, 930], '#35536e');
  for (let i = 1; i <= 3; i++) addGroup(`Clip ${i} · references and exposed generation inputs`, [(i-1)*700-15, 1070, 680, 1550], ['#506844','#685340','#604e6e'][i-1]);
  addGroup('Decode and final output', [2100, 0, 730, 1070], '#3e6063');
  if (layout) applyLayout(graph, layout);
  app.canvas.ds.scale = 0.29;
  app.canvas.ds.offset = [60, 50];
  graph.setDirtyCanvas(true, true);
  assertEquivalent(beforePrompt, (await app.graphToPrompt()).output);
  return {shared, clips, output, plan};
}

// Positions, sizes and groups captured by `build.py layout` from a hand-arranged
// copy. Nodes are matched by title (subgraph nodes by subgraph name); new nodes
// keep their default placement.
function applyLayout(graph, layout) {
  const place = (nodes, boxes = {}, nameOf = n => n.title) => {
    for (const n of nodes) {
      const box = boxes[nameOf(n)];
      if (box) { n.pos = [...box.pos]; n.size = [...box.size]; }
    }
  };
  place(graph._nodes, layout.nodes, n => n.subgraph?.name ?? n.title);
  if (layout.groups?.length) {
    for (const group of [...graph._groups]) graph.remove(group);
    for (const item of layout.groups) {
      const g = new LiteGraph.LGraphGroup(item.title);
      g.pos = item.bounding.slice(0, 2); g.size = item.bounding.slice(2);
      if (item.color) g.color = item.color;
      graph.add(g);
    }
  }
  for (const sg of graph.subgraphs.values()) {
    const saved = layout.subgraphs?.[sg.name];
    if (!saved) continue;
    place(sg._nodes, saved.nodes);
    if (saved.input) sg.inputNode.pos = [...saved.input];
    if (saved.output) sg.outputNode.pos = [...saved.output];
  }
}

export function assertEquivalent(before, after) {
  const normalize = prompt => Object.fromEntries(Object.entries(prompt).map(([id, node]) => [
    id.split(':').at(-1), {class_type: node.class_type, inputs: Object.fromEntries(
      Object.entries(node.inputs).map(([name, value]) => [name,
        Array.isArray(value) && value.length === 2 && typeof value[0] === 'string'
          ? [value[0].split(':').at(-1), value[1]] : value
      ]).sort(([a], [b]) => a.localeCompare(b))) }
  ]));
  const a = normalize(before), b = normalize(after);
  const differences = [...new Set([...Object.keys(a), ...Object.keys(b)])]
    .filter(id => JSON.stringify(a[id]) !== JSON.stringify(b[id]));
  if (differences.length) throw new Error(`Subgraph conversion changed API inputs for nodes: ${differences.join(', ')}`);
}
