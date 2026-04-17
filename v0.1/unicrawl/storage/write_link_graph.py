import json
from datetime import datetime, timezone
from pathlib import Path


def write_link_graph(base_output_dir: Path, root_url: str) -> None:
    pages_dir = base_output_dir / "pages" / "by-url-hash"
    adjacency: dict[str, list[dict[str, str]]] = {}
    all_nodes: set[str] = set()
    edge_count = 0

    for links_path in sorted(pages_dir.glob("*/outgoing-links.json")):
        try:
            payload = json.loads(links_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        source = payload.get("source_normalized_url")
        if not isinstance(source, str):
            continue

        parsed_edges: list[dict[str, str]] = []
        edges_payload = payload.get("edges")
        if isinstance(edges_payload, list):
            for entry in edges_payload:
                if not isinstance(entry, dict):
                    continue
                target = entry.get("target")
                edge_type = entry.get("type")
                if isinstance(target, str) and edge_type in {"link", "redirect"}:
                    parsed_edges.append({"target": target, "type": edge_type})
        else:
            redirect_to = payload.get("redirect_to")
            if isinstance(redirect_to, str):
                parsed_edges.append({"target": redirect_to, "type": "redirect"})
            outgoing_links = payload.get("outgoing_links")
            if isinstance(outgoing_links, list):
                for entry in outgoing_links:
                    if isinstance(entry, str):
                        parsed_edges.append({"target": entry, "type": "link"})

        adjacency[source] = parsed_edges
        all_nodes.add(source)
        for edge in parsed_edges:
            all_nodes.add(edge["target"])
        edge_count += len(parsed_edges)

    graph_payload = {
        "root_url": root_url,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "node_count": len(all_nodes),
        "edge_count": edge_count,
        "nodes": sorted(all_nodes),
        "adjacency": {source: targets for source, targets in sorted(adjacency.items())},
    }
    graph_json = json.dumps(graph_payload, indent=2)
    (base_output_dir / "link-graph.json").write_text(graph_json, encoding="utf-8")
    (base_output_dir / "link-graph-viewer.html").write_text(_build_viewer_html(graph_json), encoding="utf-8")


def _build_viewer_html(graph_json: str) -> str:
    escaped_graph_json = graph_json.replace("</script>", "<\\/script>")
    template = '''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Unicrawl Link Graph</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f4efe7;
      --panel: rgba(255, 250, 242, 0.94);
      --ink: #1d1a16;
      --muted: #6f665c;
      --accent: #0057b8;
      --line: rgba(29, 26, 22, 0.12);
      --outgoing: rgba(0, 87, 184, 0.72);
      --incoming: rgba(202, 103, 2, 0.82);
      --redirect: rgba(155, 93, 229, 0.9);
      --node: rgba(29, 26, 22, 0.42);
      --root: rgba(0, 87, 184, 0.98);
      --highlight: rgba(220, 55, 92, 0.95);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Georgia, "Iowan Old Style", "Palatino Linotype", serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(0, 87, 184, 0.12), transparent 30%),
        radial-gradient(circle at bottom right, rgba(202, 103, 2, 0.14), transparent 28%),
        var(--bg);
      min-height: 100vh;
    }
    .app {
      display: grid;
      grid-template-columns: 360px minmax(0, 1fr);
      min-height: 100vh;
    }
    .sidebar {
      border-right: 1px solid var(--line);
      background: var(--panel);
      backdrop-filter: blur(10px);
      padding: 24px;
      overflow: auto;
    }
    .stage {
      position: relative;
      min-height: 100vh;
      overflow: hidden;
    }
    .stage canvas {
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      display: block;
    }
    .hud {
      position: absolute;
      top: 18px;
      right: 18px;
      z-index: 1;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 12px 14px;
      max-width: 340px;
    }
    h1 { margin: 0 0 8px; font-size: 1.8rem; }
    h2 { margin: 0 0 8px; font-size: 1.05rem; }
    p, li { line-height: 1.45; }
    .muted { color: var(--muted); }
    .stats { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 18px 0; }
    .stat { background: white; border: 1px solid var(--line); border-radius: 14px; padding: 12px; }
    .stat strong { display: block; font-size: 1.1rem; margin-bottom: 4px; }
    input[type=search] {
      width: 100%;
      padding: 12px 14px;
      border-radius: 12px;
      border: 1px solid var(--line);
      background: white;
      color: var(--ink);
      font: inherit;
    }
    .results, .neighbor-list {
      list-style: none;
      padding: 0;
      margin: 12px 0 0;
      display: grid;
      gap: 8px;
    }
    .results button, .neighbor-list button {
      width: 100%;
      text-align: left;
      border: 1px solid var(--line);
      background: white;
      border-radius: 12px;
      padding: 10px 12px;
      cursor: pointer;
      color: inherit;
      font: inherit;
    }
    .results button:hover, .neighbor-list button:hover { border-color: var(--accent); }
    .neighbor-list { max-height: 220px; overflow: auto; }
    .section { margin-top: 22px; }
    .legend { display: flex; gap: 12px; flex-wrap: wrap; font-size: 0.95rem; margin-top: 14px; }
    .legend span { display: inline-flex; gap: 6px; align-items: center; }
    .swatch { width: 12px; height: 12px; border-radius: 999px; display: inline-block; }
    .empty { padding: 24px; color: var(--muted); }
    .overview-note { margin-top: 10px; }
    @media (max-width: 900px) {
      .app { grid-template-columns: 1fr; }
      .sidebar { border-right: 0; border-bottom: 1px solid var(--line); }
      .stage { min-height: 65vh; }
    }
  </style>
</head>
<body>
  <div class="app">
    <aside class="sidebar">
      <h1>Link Graph</h1>
      <p class="muted">The canvas shows the complete graph overview. Click a node or search for a URL to inspect its local neighborhood.</p>
      <input id="search" type="search" placeholder="Search URLs" autocomplete="off" />
      <ul id="results" class="results"></ul>

      <div class="stats">
        <div class="stat"><strong id="nodeCount">0</strong><span class="muted">nodes</span></div>
        <div class="stat"><strong id="edgeCount">0</strong><span class="muted">edges</span></div>
      </div>

      <div class="section">
        <h2>Selected</h2>
        <p id="selectedUrl" class="muted">Choose a page to inspect its neighborhood.</p>
        <div class="stats">
          <div class="stat"><strong id="outgoingCount">0</strong><span class="muted">outgoing</span></div>
          <div class="stat"><strong id="incomingCount">0</strong><span class="muted">incoming</span></div>
        </div>
        <p id="renderNote" class="muted"></p>
      </div>

      <div class="section">
        <h2>Neighbors</h2>
        <ul id="neighborList" class="neighbor-list"></ul>
      </div>

      <div class="legend">
        <span><i class="swatch" style="background: var(--outgoing);"></i> outgoing link</span>
        <span><i class="swatch" style="background: var(--incoming);"></i> incoming link</span>
        <span><i class="swatch" style="background: var(--redirect);"></i> redirect</span>
      </div>
    </aside>

    <main class="stage">
      <div class="hud">
        <strong id="rootLabel"></strong>
        <div class="muted" id="generatedAt"></div>
        <div class="muted overview-note" id="overviewNote"></div>
      </div>
      <canvas id="overviewCanvas"></canvas>
      <canvas id="highlightCanvas"></canvas>
    </main>
  </div>

  <script id="graph-data" type="application/json">__GRAPH_JSON__</script>
  <script>
    const graph = JSON.parse(document.getElementById("graph-data").textContent);
    const adjacency = graph.adjacency || {};
    const nodes = graph.nodes || Object.keys(adjacency);
    const rootNode = nodes.includes(graph.root_url) ? graph.root_url : (nodes[0] || null);
    const reverse = new Map();
    const outgoingTargets = new Map();

    for (const node of nodes) {
      reverse.set(node, []);
      outgoingTargets.set(node, []);
    }

    for (const [source, edges] of Object.entries(adjacency)) {
      const targets = [];
      for (const edge of edges) {
        if (!edge || typeof edge.target !== "string") continue;
        targets.push(edge.target);
        if (!reverse.has(edge.target)) reverse.set(edge.target, []);
        reverse.get(edge.target).push({ source, type: edge.type || "link" });
      }
      outgoingTargets.set(source, targets);
    }

    const searchInput = document.getElementById("search");
    const resultsEl = document.getElementById("results");
    const selectedUrlEl = document.getElementById("selectedUrl");
    const outgoingCountEl = document.getElementById("outgoingCount");
    const incomingCountEl = document.getElementById("incomingCount");
    const renderNoteEl = document.getElementById("renderNote");
    const neighborListEl = document.getElementById("neighborList");
    const overviewCanvas = document.getElementById("overviewCanvas");
    const highlightCanvas = document.getElementById("highlightCanvas");
    const overviewCtx = overviewCanvas.getContext("2d");
    const highlightCtx = highlightCanvas.getContext("2d");

    document.getElementById("nodeCount").textContent = String(graph.node_count || nodes.length);
    document.getElementById("edgeCount").textContent = String(graph.edge_count || 0);
    document.getElementById("rootLabel").textContent = graph.root_url || "Link graph";
    document.getElementById("generatedAt").textContent = `Generated ${graph.generated_at || ""}`;
    document.getElementById("overviewNote").textContent = "Full overview layout uses BFS rings from the crawl root. Use the mouse wheel to zoom at the cursor and drag to pan; selected node highlights on top of the complete graph.";

    let selectedNode = rootNode;
    let positions = new Map();
    let orderedNodes = [];
    let layoutWidth = 0;
    let layoutHeight = 0;
    let viewScale = 1;
    let viewOffsetX = 0;
    let viewOffsetY = 0;
    let activePointerId = null;
    let lastPointerX = 0;
    let lastPointerY = 0;
    let dragDistance = 0;
    let suppressNextClick = false;

    highlightCanvas.style.cursor = "grab";
    highlightCanvas.style.touchAction = "none";

    function trimLabel(url) {
      const withoutScheme = url.startsWith("https://")
        ? url.slice(8)
        : url.startsWith("http://")
          ? url.slice(7)
          : url;
      const withoutTrailingSlash = withoutScheme.endsWith("/")
        ? withoutScheme.slice(0, -1)
        : withoutScheme;
      return withoutTrailingSlash.slice(0, 56);
    }

    function colorFor(relation) {
      if (relation.includes("redirect")) return "var(--redirect)";
      if (relation === "incoming") return "var(--incoming)";
      return "var(--outgoing)";
    }

    function toScreen(position) {
      const centerX = layoutWidth / 2;
      const centerY = layoutHeight / 2;
      return {
        x: centerX + (position.x - centerX) * viewScale + viewOffsetX,
        y: centerY + (position.y - centerY) * viewScale + viewOffsetY,
      };
    }

    function fromScreen(point) {
      const centerX = layoutWidth / 2;
      const centerY = layoutHeight / 2;
      return {
        x: centerX + (point.x - centerX - viewOffsetX) / viewScale,
        y: centerY + (point.y - centerY - viewOffsetY) / viewScale,
      };
    }

    function pointFromClient(clientX, clientY) {
      const rect = highlightCanvas.getBoundingClientRect();
      return {
        x: clientX - rect.left,
        y: clientY - rect.top,
      };
    }

    function setScaleAroundPoint(nextScale, screenPoint) {
      const clampedScale = Math.min(8, Math.max(0.35, nextScale));
      const worldPoint = fromScreen(screenPoint);
      const centerX = layoutWidth / 2;
      const centerY = layoutHeight / 2;

      viewScale = clampedScale;
      viewOffsetX = screenPoint.x - centerX - (worldPoint.x - centerX) * viewScale;
      viewOffsetY = screenPoint.y - centerY - (worldPoint.y - centerY) * viewScale;
    }

    function resizeCanvas(canvas, width, height) {
      const dpr = window.devicePixelRatio || 1;
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      const ctx = canvas.getContext("2d");
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      return ctx;
    }

    function computeLayout(width, height) {
      const depthByNode = new Map();
      if (rootNode) {
        const queue = [rootNode];
        let cursor = 0;
        depthByNode.set(rootNode, 0);
        while (cursor < queue.length) {
          const current = queue[cursor++];
          const currentDepth = depthByNode.get(current);
          for (const target of outgoingTargets.get(current) || []) {
            if (depthByNode.has(target)) {
              continue;
            }
            depthByNode.set(target, currentDepth + 1);
            queue.push(target);
          }
        }
      }

      let maxKnownDepth = 0;
      for (const depth of depthByNode.values()) {
        if (depth > maxKnownDepth) {
          maxKnownDepth = depth;
        }
      }
      const unknownDepth = maxKnownDepth + 1;
      const layers = new Map();
      for (const node of nodes) {
        const depth = depthByNode.has(node) ? depthByNode.get(node) : unknownDepth;
        if (!layers.has(depth)) {
          layers.set(depth, []);
        }
        layers.get(depth).push(node);
      }

      const centerX = width / 2;
      const centerY = height / 2;
      const maxRadius = Math.min(width, height) * 0.44;
      const depthLevels = Array.from(layers.keys()).sort((a, b) => a - b);
      const ringCount = Math.max(depthLevels.length - 1, 1);
      const ringGap = ringCount === 0 ? 0 : maxRadius / ringCount;

      positions = new Map();
      orderedNodes = [];
      for (const depth of depthLevels) {
        const layerNodes = layers.get(depth);
        layerNodes.sort();
        if (depth === 0 && layerNodes.includes(rootNode)) {
          positions.set(rootNode, { x: centerX, y: centerY, depth });
          orderedNodes.push(rootNode);
          const remainder = layerNodes.filter((node) => node !== rootNode);
          if (remainder.length === 0) {
            continue;
          }
          const radius = Math.max(28, ringGap * 0.6);
          remainder.forEach((node, index) => {
            const angle = (Math.PI * 2 * index) / remainder.length;
            positions.set(node, {
              x: centerX + radius * Math.cos(angle),
              y: centerY + radius * Math.sin(angle),
              depth,
            });
            orderedNodes.push(node);
          });
          continue;
        }

        const radius = Math.max(28, ringGap * depth);
        const angleOffset = depth * 0.37;
        layerNodes.forEach((node, index) => {
          const angle = angleOffset + (Math.PI * 2 * index) / Math.max(layerNodes.length, 1);
          positions.set(node, {
            x: centerX + radius * Math.cos(angle),
            y: centerY + radius * Math.sin(angle),
            depth,
          });
          orderedNodes.push(node);
        });
      }

      layoutWidth = width;
      layoutHeight = height;
    }

    function drawOverview() {
      overviewCtx.clearRect(0, 0, layoutWidth, layoutHeight);
      overviewCtx.lineWidth = 0.5;
      for (const [source, edges] of Object.entries(adjacency)) {
        const sourcePos = positions.get(source);
        if (!sourcePos) continue;
        const sourceScreen = toScreen(sourcePos);
        for (const edge of edges) {
          const targetPos = positions.get(edge.target);
          if (!targetPos) continue;
          const targetScreen = toScreen(targetPos);
          overviewCtx.beginPath();
          overviewCtx.moveTo(sourceScreen.x, sourceScreen.y);
          overviewCtx.lineTo(targetScreen.x, targetScreen.y);
          overviewCtx.strokeStyle = edge.type === "redirect"
            ? "rgba(155, 93, 229, 0.08)"
            : "rgba(0, 87, 184, 0.03)";
          overviewCtx.stroke();
        }
      }

      for (const node of orderedNodes) {
        const position = positions.get(node);
        if (!position) continue;
        const screenPos = toScreen(position);
        overviewCtx.beginPath();
        overviewCtx.arc(screenPos.x, screenPos.y, node === rootNode ? 2.8 : 1.25, 0, Math.PI * 2);
        overviewCtx.fillStyle = node === rootNode ? "var(--root)" : "var(--node)";
        overviewCtx.fill();
      }
    }

    function neighborsFor(node) {
      const outgoingEdges = (adjacency[node] || []).map((edge) => ({
        url: edge.target,
        relation: edge.type === "redirect" ? "redirect" : "outgoing",
        label: edge.type === "redirect" ? `redirect: ${edge.target}` : `outgoing: ${edge.target}`,
      }));
      const incomingEdges = (reverse.get(node) || []).map((edge) => ({
        url: edge.source,
        relation: edge.type === "redirect" ? "incoming_redirect" : "incoming",
        label: edge.type === "redirect" ? `incoming_redirect: ${edge.source}` : `incoming: ${edge.source}`,
      }));
      return {
        outgoing: outgoingEdges,
        incoming: incomingEdges,
        combined: [...outgoingEdges, ...incomingEdges],
      };
    }

    function drawHighlight(node) {
      highlightCtx.clearRect(0, 0, layoutWidth, layoutHeight);
      if (!node || !positions.has(node)) {
        return;
      }

      const centerPos = positions.get(node);
      const centerScreen = toScreen(centerPos);
      const neighborhood = neighborsFor(node);
      const highlightEntries = neighborhood.combined;
      for (const entry of highlightEntries) {
        const targetPos = positions.get(entry.url);
        if (!targetPos) continue;
        const targetScreen = toScreen(targetPos);
        highlightCtx.beginPath();
        highlightCtx.moveTo(centerScreen.x, centerScreen.y);
        highlightCtx.lineTo(targetScreen.x, targetScreen.y);
        highlightCtx.strokeStyle = colorFor(entry.relation);
        highlightCtx.lineWidth = entry.relation.includes("redirect") ? 2.2 : 1.6;
        if (entry.relation.includes("redirect")) {
          highlightCtx.setLineDash([6, 4]);
        } else {
          highlightCtx.setLineDash([]);
        }
        highlightCtx.stroke();
      }
      highlightCtx.setLineDash([]);

      for (const entry of highlightEntries.slice(0, 120)) {
        const targetPos = positions.get(entry.url);
        if (!targetPos) continue;
        const targetScreen = toScreen(targetPos);
        highlightCtx.beginPath();
        highlightCtx.arc(targetScreen.x, targetScreen.y, 3.2, 0, Math.PI * 2);
        highlightCtx.fillStyle = colorFor(entry.relation);
        highlightCtx.fill();
      }

      highlightCtx.beginPath();
      highlightCtx.arc(centerScreen.x, centerScreen.y, 5.4, 0, Math.PI * 2);
      highlightCtx.fillStyle = "var(--highlight)";
      highlightCtx.fill();

      highlightCtx.font = "13px Georgia";
      highlightCtx.fillStyle = "rgba(29, 26, 22, 0.92)";
      highlightCtx.fillText(trimLabel(node), centerScreen.x + 10, centerScreen.y - 10);
    }

    function renderResults(query) {
      const normalized = query.trim().toLowerCase();
      const matches = normalized
        ? nodes.filter((node) => node.toLowerCase().includes(normalized)).slice(0, 40)
        : nodes.slice(0, 20);
      resultsEl.innerHTML = "";
      for (const node of matches) {
        const button = document.createElement("button");
        button.textContent = node;
        button.addEventListener("click", () => selectNode(node));
        const item = document.createElement("li");
        item.appendChild(button);
        resultsEl.appendChild(item);
      }
      if (matches.length === 0) {
        resultsEl.innerHTML = '<li class="empty">No matching URLs.</li>';
      }
    }

    function renderDetails(node) {
      if (!node) {
        selectedUrlEl.textContent = "Choose a page to inspect its neighborhood.";
        outgoingCountEl.textContent = "0";
        incomingCountEl.textContent = "0";
        renderNoteEl.textContent = "";
        neighborListEl.innerHTML = '<li class="empty">No node selected.</li>';
        return;
      }

      const neighborhood = neighborsFor(node);
      const outgoing = neighborhood.outgoing;
      const incoming = neighborhood.incoming;
      const combined = neighborhood.combined;
      const displayed = combined.slice(0, 120);

      selectedUrlEl.textContent = node;
      outgoingCountEl.textContent = String(outgoing.length);
      incomingCountEl.textContent = String(incoming.length);
      renderNoteEl.textContent = displayed.length < combined.length
        ? `Showing ${displayed.length} of ${combined.length} neighbors in the list.`
        : `${combined.length} neighbors listed.`;

      neighborListEl.innerHTML = "";
      for (const entry of displayed) {
        const item = document.createElement("li");
        const button = document.createElement("button");
        button.textContent = entry.label;
        button.addEventListener("click", () => selectNode(entry.url));
        item.appendChild(button);
        neighborListEl.appendChild(item);
      }
      if (displayed.length === 0) {
        neighborListEl.innerHTML = '<li class="empty">No incoming or outgoing edges.</li>';
      }
    }

    function selectNode(node) {
      selectedNode = node;
      renderDetails(node);
      drawHighlight(node);
    }

    function findNearestNode(clientX, clientY) {
      const rect = highlightCanvas.getBoundingClientRect();
      const x = clientX - rect.left;
      const y = clientY - rect.top;
      let nearestNode = null;
      let nearestDistance = Infinity;

      for (const node of orderedNodes) {
        const position = positions.get(node);
        if (!position) continue;
        const screenPos = toScreen(position);
        const dx = screenPos.x - x;
        const dy = screenPos.y - y;
        const distance = Math.hypot(dx, dy);
        if (distance < nearestDistance) {
          nearestDistance = distance;
          nearestNode = node;
        }
      }

      return nearestDistance <= 12 ? nearestNode : null;
    }

    function layoutAndRender() {
      const rect = overviewCanvas.parentElement.getBoundingClientRect();
      resizeCanvas(overviewCanvas, rect.width, rect.height);
      resizeCanvas(highlightCanvas, rect.width, rect.height);
      computeLayout(rect.width, rect.height);
      drawOverview();
      drawHighlight(selectedNode);
    }

    highlightCanvas.addEventListener("click", (event) => {
      if (suppressNextClick) {
        suppressNextClick = false;
        return;
      }
      const node = findNearestNode(event.clientX, event.clientY);
      if (node) {
        selectNode(node);
      }
    });

    highlightCanvas.addEventListener("wheel", (event) => {
      event.preventDefault();
      const factor = event.deltaY < 0 ? 1.15 : 1 / 1.15;
      const screenPoint = pointFromClient(event.clientX, event.clientY);
      setScaleAroundPoint(viewScale * factor, screenPoint);
      drawOverview();
      drawHighlight(selectedNode);
    }, { passive: false });

    highlightCanvas.addEventListener("pointerdown", (event) => {
      if (event.pointerType === "mouse" && event.button !== 0) {
        return;
      }
      activePointerId = event.pointerId;
      lastPointerX = event.clientX;
      lastPointerY = event.clientY;
      dragDistance = 0;
      highlightCanvas.style.cursor = "grabbing";
      highlightCanvas.setPointerCapture(event.pointerId);
    });

    highlightCanvas.addEventListener("pointermove", (event) => {
      if (event.pointerId !== activePointerId) {
        return;
      }

      const deltaX = event.clientX - lastPointerX;
      const deltaY = event.clientY - lastPointerY;
      if (deltaX === 0 && deltaY === 0) {
        return;
      }

      dragDistance += Math.hypot(deltaX, deltaY);
      lastPointerX = event.clientX;
      lastPointerY = event.clientY;
      viewOffsetX += deltaX;
      viewOffsetY += deltaY;
      drawOverview();
      drawHighlight(selectedNode);
    });

    function endPan(event) {
      if (event.pointerId !== activePointerId) {
        return;
      }

      if (highlightCanvas.hasPointerCapture(event.pointerId)) {
        highlightCanvas.releasePointerCapture(event.pointerId);
      }
      if (dragDistance > 4) {
        suppressNextClick = true;
      }
      activePointerId = null;
      dragDistance = 0;
      highlightCanvas.style.cursor = "grab";
    }

    highlightCanvas.addEventListener("pointerup", endPan);
    highlightCanvas.addEventListener("pointercancel", endPan);

    searchInput.addEventListener("input", (event) => renderResults(event.target.value));
    window.addEventListener("resize", layoutAndRender);

    renderResults("");
    layoutAndRender();
    selectNode(selectedNode);
  </script>
</body>
</html>
'''
    return template.replace("__GRAPH_JSON__", escaped_graph_json)
