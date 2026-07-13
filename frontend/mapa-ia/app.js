/* Grafo interativo do ecossistema de IA — porte em JS puro (sem React, sem libs).
 *
 * Técnica (igual ao guia original):
 *   - Nós com posição curada num viewBox 1000x620 (layout à mão, sem física).
 *   - Um loop requestAnimationFrame aplica um drift suave escrevendo direto nos
 *     atributos SVG via refs — sem re-render por frame.
 *   - O estado de interação (hover/seleção) só troca classes CSS.
 *   - Arrastar (mouse/caneta) reposiciona; no toque, preserva o scroll.
 *   - prefers-reduced-motion desliga o drift, mantendo toda a interação.
 *
 * CSP: nenhum script inline; todos os eventos via addEventListener. */
(function () {
  "use strict";

  var data = window.MAPA_IA_DATA;
  if (!data) return;

  var SVGNS = "http://www.w3.org/2000/svg";
  var nodes = data.nodes;
  var edges = data.edges;
  var typeLabels = data.typeLabels;
  var defaultId = data.defaultId;

  var typeClass = {
    core: "typeCore",
    pessoa: "typePessoa",
    motor: "typeMotor",
    triagem: "typeTriagem",
    entrega: "typeEntrega",
    planejado: "typePlanejado"
  };

  // ---- Índices e adjacência ----
  var idToIndex = {};
  var nodeById = {};
  nodes.forEach(function (n, i) {
    idToIndex[n.id] = i;
    nodeById[n.id] = n;
  });

  var adjacency = {};
  nodes.forEach(function (n) { adjacency[n.id] = []; });
  edges.forEach(function (e) {
    if (adjacency[e[0]] && adjacency[e[0]].indexOf(e[1]) === -1) adjacency[e[0]].push(e[1]);
    if (adjacency[e[1]] && adjacency[e[1]].indexOf(e[0]) === -1) adjacency[e[1]].push(e[0]);
  });

  function radiusFor(n) {
    if (n.type === "core") return 17;
    return n.primary ? 12 : 7.5;
  }

  // ---- Elementos base ----
  var svg = document.getElementById("graph");
  var gEdges = document.getElementById("edges");
  var gNodes = document.getElementById("nodes");
  var panelTag = document.getElementById("panelTag");
  var panelTitle = document.getElementById("panelTitle");
  var panelText = document.getElementById("panelText");
  var panelConns = document.getElementById("panelConns");
  var panelChips = document.getElementById("panelChips");

  if (!svg || !gEdges || !gNodes) return;

  // ---- Estado ----
  var hovered = null;
  var selected = null;
  var basePos = nodes.map(function (n) { return { x: n.x, y: n.y }; });
  var nodeEls = {};      // id -> <g>
  var labelEls = {};     // id -> <text>
  var edgeEls = [];      // índice -> <line>
  var dragging = null;   // índice do nó sendo arrastado

  var mq = window.matchMedia("(prefers-reduced-motion: reduce)");
  var reduced = mq.matches;

  function activeId() { return hovered != null ? hovered : selected; }

  // ---- Construção do SVG ----
  edges.forEach(function () {
    var line = document.createElementNS(SVGNS, "line");
    line.setAttribute("class", "edge");
    gEdges.appendChild(line);
    edgeEls.push(line);
  });

  nodes.forEach(function (n, index) {
    var r = radiusFor(n);

    var g = document.createElementNS(SVGNS, "g");
    g.setAttribute("class", nodeClasses(n, false, false, false));
    g.setAttribute("role", "button");
    g.setAttribute("tabindex", "0");
    g.setAttribute("aria-label", typeLabels[n.type] + ": " + (n.detailTitle || n.label));

    var hit = document.createElementNS(SVGNS, "circle");
    hit.setAttribute("class", "hit");
    hit.setAttribute("r", "30");

    var halo = document.createElementNS(SVGNS, "circle");
    halo.setAttribute("class", "halo");
    halo.setAttribute("r", String(r + 5));

    var dot = document.createElementNS(SVGNS, "circle");
    dot.setAttribute("class", "dot");
    dot.setAttribute("r", String(r));

    var text = document.createElementNS(SVGNS, "text");
    text.setAttribute("class", labelClasses(n, n.primary));
    text.setAttribute("y", String(r + 17));
    text.textContent = n.label;

    g.appendChild(hit);
    g.appendChild(halo);
    g.appendChild(dot);
    g.appendChild(text);
    gNodes.appendChild(g);

    nodeEls[n.id] = g;
    labelEls[n.id] = text;

    g.addEventListener("mouseenter", function () { setHovered(n.id); });
    g.addEventListener("mouseleave", function () { setHovered(null); });
    g.addEventListener("focus", function () { setHovered(n.id); });
    g.addEventListener("blur", function () { setHovered(null); });
    g.addEventListener("click", function () { toggleSelect(n.id); });
    g.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter" || ev.key === " ") {
        ev.preventDefault();
        toggleSelect(n.id);
      }
    });
    g.addEventListener("pointerdown", function (ev) { onNodePointerDown(index, ev); });
  });

  function nodeClasses(n, isActive, isDim, isSelected) {
    var c = ["node", typeClass[n.type], n.primary ? "primary" : "secondary"];
    if (isActive) c.push("isActive");
    if (isDim) c.push("isDim");
    if (isSelected) c.push("isSelected");
    return c.join(" ");
  }

  function labelClasses(n, shown) {
    var c = ["label", n.primary ? "labelPrimary" : "labelSecondary"];
    if (shown) c.push("labelShown");
    return c.join(" ");
  }

  // ---- Estado de interação ----
  function setHovered(id) { hovered = id; render(); }
  function toggleSelect(id) { selected = (selected === id) ? null : id; render(); }
  function setSelected(id) { selected = id; render(); }

  function render() {
    var active = activeId();
    var hset = null;
    if (active) {
      hset = {};
      hset[active] = true;
      adjacency[active].forEach(function (id) { hset[id] = true; });
    }

    nodes.forEach(function (n) {
      var isActive = n.id === active;
      var inSet = hset ? !!hset[n.id] : false;
      var dim = hset !== null && !inSet;
      var isSel = selected === n.id;
      nodeEls[n.id].setAttribute("class", nodeClasses(n, isActive, dim, isSel));
      var labelShown = n.primary || inSet;
      labelEls[n.id].setAttribute("class", labelClasses(n, labelShown));
    });

    edges.forEach(function (e, i) {
      var lit = active !== null && (e[0] === active || e[1] === active);
      var dim = active !== null && !lit;
      var c = ["edge"];
      if (lit) c.push("edgeLit");
      if (dim) c.push("edgeDim");
      edgeEls[i].setAttribute("class", c.join(" "));
    });

    updatePanel(active);
  }

  function updatePanel(active) {
    if (!panelTag) return;
    var id = active || selected || defaultId;
    var info = nodeById[id] || nodeById[defaultId];

    panelTag.textContent = typeLabels[info.type];
    panelTag.setAttribute("class", "tag " + typeClass[info.type]);
    panelTitle.textContent = info.detailTitle || info.label;
    panelText.textContent = info.description;

    while (panelChips.firstChild) panelChips.removeChild(panelChips.firstChild);
    var neigh = adjacency[info.id] || [];
    if (neigh.length) {
      panelConns.hidden = false;
      neigh.forEach(function (nbId) {
        var nb = nodeById[nbId];
        if (!nb) return;
        var b = document.createElement("button");
        b.type = "button";
        b.className = "chip";
        b.textContent = nb.label;
        b.addEventListener("click", function () { setSelected(nb.id); });
        b.addEventListener("mouseenter", function () { setHovered(nb.id); });
        b.addEventListener("mouseleave", function () { setHovered(null); });
        panelChips.appendChild(b);
      });
    } else {
      panelConns.hidden = true;
    }
  }

  // ---- Posicionamento imperativo (drift + drag) ----
  function applyPositions(getPos) {
    nodes.forEach(function (n, i) {
      var p = getPos(i);
      var g = nodeEls[n.id];
      if (g) g.setAttribute("transform", "translate(" + p.x.toFixed(2) + "," + p.y.toFixed(2) + ")");
    });
    edges.forEach(function (e, i) {
      var line = edgeEls[i];
      if (!line) return;
      var ps = getPos(idToIndex[e[0]]);
      var pt = getPos(idToIndex[e[1]]);
      line.setAttribute("x1", ps.x.toFixed(2));
      line.setAttribute("y1", ps.y.toFixed(2));
      line.setAttribute("x2", pt.x.toFixed(2));
      line.setAttribute("y2", pt.y.toFixed(2));
    });
  }

  function staticApply() {
    applyPositions(function (i) { return basePos[i]; });
  }

  var rafId = 0;
  function startDrift() {
    if (reduced) return;
    var start = null;
    function loop(now) {
      if (start === null) start = now;
      var t = now - start;
      applyPositions(function (i) {
        var b = basePos[i];
        if (dragging === i) return b;
        var phase = i * 1.7;
        return {
          x: b.x + Math.sin(t * 0.0006 + phase) * 5,
          y: b.y + Math.cos(t * 0.00054 + phase) * 5
        };
      });
      rafId = window.requestAnimationFrame(loop);
    }
    rafId = window.requestAnimationFrame(loop);
  }
  function stopDrift() {
    if (rafId) { window.cancelAnimationFrame(rafId); rafId = 0; }
  }

  // ---- Drag (só mouse/caneta) ----
  function clientToSvg(cx, cy) {
    if (!svg.createSVGPoint) return null;
    var pt = svg.createSVGPoint();
    pt.x = cx; pt.y = cy;
    var ctm = svg.getScreenCTM();
    if (!ctm) return null;
    var p = pt.matrixTransform(ctm.inverse());
    return { x: p.x, y: p.y };
  }

  function onNodePointerDown(index, ev) {
    if (ev.pointerType === "touch") return;   // no toque, preserva o scroll
    ev.preventDefault();
    dragging = index;
    try { svg.setPointerCapture(ev.pointerId); } catch (e) { /* noop */ }
  }

  svg.addEventListener("pointermove", function (ev) {
    if (dragging === null) return;
    var p = clientToSvg(ev.clientX, ev.clientY);
    if (!p) return;
    basePos[dragging] = p;
    if (reduced) staticApply();   // sem drift, atualiza na mão
  });

  function endDrag(ev) {
    if (dragging === null) return;
    try { svg.releasePointerCapture(ev.pointerId); } catch (e) { /* noop */ }
    dragging = null;
  }
  svg.addEventListener("pointerup", endDrag);
  svg.addEventListener("pointerleave", endDrag);
  svg.addEventListener("pointercancel", endDrag);

  // ---- Reage a mudança de preferência de movimento ----
  function onReducedChange(e) {
    reduced = e.matches;
    stopDrift();
    staticApply();
    if (!reduced) startDrift();
  }
  if (mq.addEventListener) mq.addEventListener("change", onReducedChange);
  else if (mq.addListener) mq.addListener(onReducedChange);

  // ---- Boot ----
  staticApply();   // posições iniciais antes do primeiro frame
  render();        // classes + painel padrão
  startDrift();
})();
