// Graficos en SVG puro. Sin libreria de charts: el payload mas chico posible
// es tambien la opcion mas performante, y estas formas son simples.
//
// Reglas aplicadas: marcas finas (linea 2px), grilla y ejes como hairlines
// solidos (nunca punteados), una sola serie por eje (nunca doble eje),
// etiquetas selectivas, y vista de tabla siempre disponible como alternativa
// accesible.

const NS = "http://www.w3.org/2000/svg";

function el(name, attrs = {}) {
  const node = document.createElementNS(NS, name);
  for (const [key, value] of Object.entries(attrs)) {
    node.setAttribute(key, value);
  }
  return node;
}

function niceTicks(min, max, count = 5) {
  if (min === max) return [min];
  const span = max - min;
  const rawStep = span / count;
  const mag = Math.pow(10, Math.floor(Math.log10(rawStep)));
  const norm = rawStep / mag;
  const step = (norm >= 5 ? 10 : norm >= 2 ? 5 : norm >= 1 ? 2 : 1) * mag;
  const ticks = [];
  for (let t = Math.ceil(min / step) * step; t <= max + 1e-9; t += step) {
    ticks.push(t);
  }
  return ticks;
}

export function formatNumber(value, digits = 2) {
  return Number(value).toLocaleString("es-AR", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function formatDate(epochSeconds) {
  return new Date(epochSeconds * 1000).toLocaleString("es-AR", {
    day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
  });
}

/**
 * Grafico de linea con crosshair y tooltip.
 * Una sola serie: el titulo de la tarjeta la nombra, no hace falta leyenda.
 */
export function lineChart(container, points, options = {}) {
  const { valueLabel = "Equity", digits = 2 } = options;
  container.innerHTML = "";
  if (!points.length) {
    container.innerHTML = '<p class="empty">Sin datos para graficar.</p>';
    return;
  }

  const W = 900;
  const H = 300;
  // El alto reserva la banda del eje X: si no, las etiquetas quedan
  // recortadas y la tarjeta desarrolla un scroll interno.
  const pad = { top: 14, right: 18, bottom: 30, left: 56 };
  const plotW = W - pad.left - pad.right;
  const plotH = H - pad.top - pad.bottom;

  const xs = points.map((p) => p.x);
  const ys = points.map((p) => p.y);
  const xMin = Math.min(...xs);
  const xMax = Math.max(...xs);
  const yMinRaw = Math.min(...ys);
  const yMaxRaw = Math.max(...ys);
  const yPad = (yMaxRaw - yMinRaw) * 0.08 || Math.abs(yMaxRaw) * 0.05 || 1;
  const yMin = yMinRaw - yPad;
  const yMax = yMaxRaw + yPad;

  const sx = (x) => pad.left + (xMax === xMin ? plotW / 2 : ((x - xMin) / (xMax - xMin)) * plotW);
  const sy = (y) => pad.top + plotH - ((y - yMin) / (yMax - yMin)) * plotH;

  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img" });
  svg.appendChild(el("title")).textContent = `${valueLabel} a lo largo del tiempo`;

  for (const tick of niceTicks(yMin, yMax, 5)) {
    const y = sy(tick);
    svg.appendChild(el("line", {
      class: "gridline", x1: pad.left, x2: W - pad.right, y1: y, y2: y,
    }));
    const label = el("text", {
      class: "tick", x: pad.left - 9, y: y + 4, "text-anchor": "end",
    });
    label.textContent = formatNumber(tick, digits);
    svg.appendChild(label);
  }

  svg.appendChild(el("line", {
    class: "axis-line",
    x1: pad.left, x2: W - pad.right, y1: pad.top + plotH, y2: pad.top + plotH,
  }));

  // Etiquetas de tiempo solo en los extremos: una por punto seria ruido.
  const first = el("text", {
    class: "tick", x: pad.left, y: H - 8, "text-anchor": "start",
  });
  first.textContent = formatDate(xMin);
  svg.appendChild(first);
  const last = el("text", {
    class: "tick", x: W - pad.right, y: H - 8, "text-anchor": "end",
  });
  last.textContent = formatDate(xMax);
  svg.appendChild(last);

  const d = points.map((p, i) => `${i ? "L" : "M"}${sx(p.x)} ${sy(p.y)}`).join(" ");
  svg.appendChild(el("path", { class: "series-line", d }));

  // --- Capa de interaccion ---
  const crosshair = el("line", {
    class: "crosshair", y1: pad.top, y2: pad.top + plotH, opacity: 0,
  });
  const dot = el("circle", { class: "focus-dot", r: 4.5, opacity: 0 });
  svg.appendChild(crosshair);
  svg.appendChild(dot);

  const hit = el("rect", {
    x: pad.left, y: pad.top, width: plotW, height: plotH, fill: "transparent",
  });
  svg.appendChild(hit);
  container.appendChild(svg);

  const tooltip = document.createElement("div");
  tooltip.className = "tooltip";
  container.appendChild(tooltip);

  function nearest(clientX) {
    const box = svg.getBoundingClientRect();
    const xValue = xMin + ((clientX - box.left) / box.width * W - pad.left) / plotW * (xMax - xMin);
    let best = points[0];
    let bestGap = Infinity;
    for (const point of points) {
      const gap = Math.abs(point.x - xValue);
      if (gap < bestGap) { bestGap = gap; best = point; }
    }
    return best;
  }

  function show(event) {
    const point = nearest(event.clientX);
    const px = sx(point.x);
    const py = sy(point.y);
    crosshair.setAttribute("x1", px);
    crosshair.setAttribute("x2", px);
    crosshair.setAttribute("opacity", 1);
    dot.setAttribute("cx", px);
    dot.setAttribute("cy", py);
    dot.setAttribute("opacity", 1);

    tooltip.innerHTML =
      `<div class="t-label">${formatDate(point.x)}</div>` +
      `<div class="t-value">${valueLabel}: ${formatNumber(point.y, digits)}</div>`;
    const box = svg.getBoundingClientRect();
    const left = (px / W) * box.width;
    tooltip.style.left = `${Math.min(Math.max(left + 12, 0), box.width - 150)}px`;
    tooltip.style.top = `${(py / H) * box.height - 12}px`;
    tooltip.style.opacity = 1;
  }

  function hide() {
    crosshair.setAttribute("opacity", 0);
    dot.setAttribute("opacity", 0);
    tooltip.style.opacity = 0;
  }

  hit.addEventListener("pointermove", show);
  hit.addEventListener("pointerleave", hide);
}

/**
 * Barras horizontales. Una sola serie, un solo color: la longitud ya codifica
 * la magnitud, pintar cada barra de un tono distinto no agrega informacion.
 */
export function barChart(container, items, options = {}) {
  const { digits = 0 } = options;
  container.innerHTML = "";
  if (!items.length) {
    container.innerHTML = '<p class="empty">Sin datos todavia.</p>';
    return;
  }

  const rowH = 30;
  const gap = 8;
  const W = 900;
  const labelW = 90;
  const valueW = 90;
  const H = items.length * (rowH + gap);
  const max = Math.max(...items.map((i) => i.value), 1);
  const barMax = W - labelW - valueW - 16;

  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img" });
  items.forEach((item, index) => {
    const y = index * (rowH + gap);
    const label = el("text", {
      class: "tick", x: labelW - 10, y: y + rowH / 2 + 4, "text-anchor": "end",
    });
    label.textContent = item.label;
    svg.appendChild(label);

    const width = Math.max((item.value / max) * barMax, item.value > 0 ? 2 : 0);
    svg.appendChild(el("rect", {
      class: "bar", x: labelW, y: y + 6, width, height: rowH - 12, rx: 4,
    }));

    // Etiqueta directa fuera de la barra: dentro se recortaria en las cortas.
    const value = el("text", {
      class: "tick", x: labelW + width + 10, y: y + rowH / 2 + 4,
    });
    value.textContent = formatNumber(item.value, digits);
    svg.appendChild(value);
  });

  container.appendChild(svg);
}
