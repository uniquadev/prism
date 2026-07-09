(function () {
  const MIN_ZOOM = 0.25;
  const MAX_ZOOM = 8;
  const ZOOM_STEP = 1.2;

  function currentTheme() {
    return document.body.getAttribute("data-md-color-scheme") === "slate"
      ? "dark"
      : "default";
  }

  async function renderMermaidBlocks() {
    if (!window.mermaid) {
      return;
    }

    window.mermaid.initialize({
      startOnLoad: false,
      securityLevel: "strict",
      theme: currentTheme()
    });

    const blocks = document.querySelectorAll("pre.mermaid-source:not([data-mermaid-rendered])");

    for (let index = 0; index < blocks.length; index += 1) {
      const block = blocks[index];
      const code = block.querySelector("code");
      const source = code ? code.textContent.trim() : block.textContent.trim();

      if (!source) {
        continue;
      }

      block.setAttribute("data-mermaid-rendered", "true");

      try {
        const id = `mini-sharp-mermaid-${Date.now()}-${index}`;
        const result = await window.mermaid.render(id, source);
        const container = document.createElement("div");
        container.className = "mermaid-rendered mermaid-zoomable";
        container.innerHTML = result.svg;
        block.replaceWith(container);
        normalizeMermaidSvg(container);
        addMermaidZoom(container);

        if (typeof result.bindFunctions === "function") {
          result.bindFunctions(container);
        }
      } catch (error) {
        block.classList.add("mermaid-error");
        console.error("Mermaid render failed:", error);
      }
    }
  }

  function normalizeMermaidSvg(container) {
    const svg = container.querySelector("svg");

    if (!svg) {
      return;
    }

    const box = getSvgBox(svg);

    if (box) {
      container.style.setProperty("--mermaid-viewbox-width", `${Math.ceil(box.width)}px`);
      svg.style.setProperty("--mermaid-aspect-ratio", `${box.width} / ${box.height}`);
    }

    svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
    svg.removeAttribute("height");
  }

  function addMermaidZoom(container) {
    const svg = container.querySelector("svg");

    if (!svg || container.querySelector(".mermaid-zoom-button")) {
      return;
    }

    const button = document.createElement("button");
    button.type = "button";
    button.className = "mermaid-zoom-button";
    button.setAttribute("aria-label", "Expand diagram");
    button.title = "Expand diagram";
    button.innerHTML = [
      '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">',
      '<path d="M5 5h6v2H8.4l3.1 3.1-1.4 1.4L7 8.4V11H5V5Zm8 0h6v6h-2V8.4l-3.1 3.1-1.4-1.4L15.6 7H13V5Zm-2.9 7.5 1.4 1.4L8.4 17H11v2H5v-6h2v2.6l3.1-3.1Zm3.8 0 3.1 3.1V13h2v6h-6v-2h2.6l-3.1-3.1 1.4-1.4Z"/>',
      "</svg>"
    ].join("");

    button.addEventListener("click", function () {
      openMermaidZoom(svg);
    });

    container.addEventListener("dblclick", function () {
      openMermaidZoom(svg);
    });

    container.appendChild(button);
  }

  function openMermaidZoom(svg) {
    const viewer = getMermaidViewer();
    const clone = svg.cloneNode(true);
    clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    const box = getSvgBox(clone);

    clone.classList.add("mermaid-viewer-svg");
    clone.removeAttribute("style");

    if (box) {
      clone.setAttribute("width", Math.ceil(box.width));
      clone.setAttribute("height", Math.ceil(box.height));
      clone.setAttribute("preserveAspectRatio", "xMidYMid meet");
    }

    viewer.canvas.replaceChildren(clone);
    viewer.open(box);
  }

  function getMermaidViewer() {
    if (window.__miniSharpMermaidViewer) {
      return window.__miniSharpMermaidViewer;
    }

    const element = document.createElement("div");
    element.className = "mermaid-viewer";
    element.setAttribute("aria-hidden", "true");
    element.setAttribute("role", "dialog");
    element.setAttribute("aria-modal", "true");
    element.setAttribute("aria-label", "Expanded Mermaid diagram");
    element.hidden = true;

    element.innerHTML = [
      '<div class="mermaid-viewer__toolbar" aria-label="Diagram controls">',
      viewerButton("minus", "Zoom out", '<path d="M5 11h14v2H5z"/>'),
      viewerButton("plus", "Zoom in", '<path d="M11 5h2v6h6v2h-6v6h-2v-6H5v-2h6z"/>'),
      viewerButton("reset", "Reset view", '<path d="M12 5a7 7 0 1 1-6.32 4H3l3.5-3.5L10 9H7.78A5 5 0 1 0 12 7z"/>'),
      viewerButton("close", "Close", '<path d="m6.4 5 5.6 5.6L17.6 5 19 6.4 13.4 12l5.6 5.6-1.4 1.4-5.6-5.6L6.4 19 5 17.6l5.6-5.6L5 6.4z"/>'),
      "</div>",
      '<div class="mermaid-viewer__stage" tabindex="0">',
      '<div class="mermaid-viewer__canvas"></div>',
      "</div>"
    ].join("");

    document.body.appendChild(element);

    const stage = element.querySelector(".mermaid-viewer__stage");
    const canvas = element.querySelector(".mermaid-viewer__canvas");
    const buttons = {
      close: element.querySelector('[data-mermaid-viewer-action="close"]'),
      plus: element.querySelector('[data-mermaid-viewer-action="plus"]'),
      minus: element.querySelector('[data-mermaid-viewer-action="minus"]'),
      reset: element.querySelector('[data-mermaid-viewer-action="reset"]')
    };

    const state = {
      box: null,
      dragging: false,
      gesture: null,
      lastX: 0,
      lastY: 0,
      pointers: new Map(),
      scale: 1,
      x: 0,
      y: 0
    };

    function setTransform() {
      canvas.style.transform = `translate(${state.x}px, ${state.y}px) scale(${state.scale})`;
      element.style.setProperty("--mermaid-viewer-zoom", `"${Math.round(state.scale * 100)}%"`);
    }

    function reset() {
      const rect = stage.getBoundingClientRect();
      const box = state.box || {
        width: Math.max(canvas.scrollWidth, 1),
        height: Math.max(canvas.scrollHeight, 1)
      };
      const pad = Math.min(96, Math.max(40, rect.width * 0.08));
      const fitScale = Math.min(
        (rect.width - pad) / box.width,
        (rect.height - pad) / box.height
      );

      state.scale = clamp(fitScale, MIN_ZOOM, 2.6);
      state.x = (rect.width - box.width * state.scale) / 2;
      state.y = (rect.height - box.height * state.scale) / 2;
      setTransform();
    }

    function zoomBy(factor, clientX, clientY) {
      const rect = stage.getBoundingClientRect();
      const centerX = typeof clientX === "number" ? clientX - rect.left : rect.width / 2;
      const centerY = typeof clientY === "number" ? clientY - rect.top : rect.height / 2;
      const nextScale = clamp(state.scale * factor, MIN_ZOOM, MAX_ZOOM);
      const ratio = nextScale / state.scale;

      state.x = centerX - (centerX - state.x) * ratio;
      state.y = centerY - (centerY - state.y) * ratio;
      state.scale = nextScale;
      setTransform();
    }

    function beginPinch() {
      const points = getPointerPoints();

      if (points.length < 2) {
        state.gesture = null;
        return;
      }

      const rect = stage.getBoundingClientRect();
      const center = getPointCenter(points[0], points[1], rect);
      const distance = getPointDistance(points[0], points[1]);

      state.gesture = {
        centerX: center.x,
        centerY: center.y,
        contentX: (center.x - state.x) / state.scale,
        contentY: (center.y - state.y) / state.scale,
        distance,
        scale: state.scale
      };
    }

    function updatePinch() {
      const points = getPointerPoints();

      if (points.length < 2 || !state.gesture) {
        return;
      }

      const rect = stage.getBoundingClientRect();
      const center = getPointCenter(points[0], points[1], rect);
      const distance = getPointDistance(points[0], points[1]);
      const ratio = distance / Math.max(state.gesture.distance, 1);
      const nextScale = clamp(state.gesture.scale * ratio, MIN_ZOOM, MAX_ZOOM);

      state.scale = nextScale;
      state.x = center.x - state.gesture.contentX * nextScale;
      state.y = center.y - state.gesture.contentY * nextScale;
      setTransform();
    }

    function getPointerPoints() {
      return Array.from(state.pointers.values());
    }

    function getPointDistance(a, b) {
      return Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY);
    }

    function getPointCenter(a, b, rect) {
      return {
        x: (a.clientX + b.clientX) / 2 - rect.left,
        y: (a.clientY + b.clientY) / 2 - rect.top
      };
    }

    function updateGestureAfterPointerEnd() {
      const points = getPointerPoints();

      if (!points.length) {
        state.dragging = false;
        state.gesture = null;
        stage.classList.remove("is-dragging");
        return;
      }

      if (points.length === 1) {
        state.dragging = true;
        state.gesture = null;
        state.lastX = points[0].clientX;
        state.lastY = points[0].clientY;
        stage.classList.add("is-dragging");
        return;
      }

      state.dragging = false;
      stage.classList.remove("is-dragging");
      beginPinch();
    }

    function close() {
      element.hidden = true;
      element.setAttribute("aria-hidden", "true");
      document.body.classList.remove("mermaid-viewer-open");
      state.pointers.clear();
      state.dragging = false;
      state.gesture = null;
      stage.classList.remove("is-dragging");
      canvas.replaceChildren();
    }

    stage.addEventListener("wheel", function (event) {
      event.preventDefault();
      const direction = event.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP;
      zoomBy(direction, event.clientX, event.clientY);
    }, { passive: false });

    stage.addEventListener("pointerdown", function (event) {
      event.preventDefault();
      state.pointers.set(event.pointerId, {
        clientX: event.clientX,
        clientY: event.clientY
      });

      if (typeof stage.setPointerCapture === "function") {
        try {
          stage.setPointerCapture(event.pointerId);
        } catch (error) {
          // Synthetic pointer events and some interrupted touch streams may not
          // have an active pointer by the time capture is requested.
        }
      }

      if (state.pointers.size === 1) {
        state.dragging = true;
        state.gesture = null;
        state.lastX = event.clientX;
        state.lastY = event.clientY;
        stage.classList.add("is-dragging");
        return;
      }

      state.dragging = false;
      stage.classList.remove("is-dragging");
      beginPinch();
    });

    stage.addEventListener("pointermove", function (event) {
      if (!state.pointers.has(event.pointerId)) {
        return;
      }

      event.preventDefault();
      state.pointers.set(event.pointerId, {
        clientX: event.clientX,
        clientY: event.clientY
      });

      if (state.pointers.size >= 2) {
        updatePinch();
        return;
      }

      if (!state.dragging) {
        return;
      }

      state.x += event.clientX - state.lastX;
      state.y += event.clientY - state.lastY;
      state.lastX = event.clientX;
      state.lastY = event.clientY;
      setTransform();
    });

    stage.addEventListener("pointerup", function (event) {
      state.pointers.delete(event.pointerId);

      if (typeof stage.releasePointerCapture === "function" && stage.hasPointerCapture(event.pointerId)) {
        try {
          stage.releasePointerCapture(event.pointerId);
        } catch (error) {
          // Capture may already have been released by the browser.
        }
      }

      updateGestureAfterPointerEnd();
    });

    stage.addEventListener("pointercancel", function (event) {
      state.pointers.delete(event.pointerId);
      updateGestureAfterPointerEnd();
    });

    element.addEventListener("click", function (event) {
      if (event.target === element) {
        close();
      }
    });

    document.addEventListener("keydown", function (event) {
      if (element.hidden) {
        return;
      }

      if (event.key === "Escape") {
        close();
      }
    });

    buttons.close.addEventListener("click", close);
    buttons.plus.addEventListener("click", function () {
      zoomBy(ZOOM_STEP);
    });
    buttons.minus.addEventListener("click", function () {
      zoomBy(1 / ZOOM_STEP);
    });
    buttons.reset.addEventListener("click", reset);

    window.__miniSharpMermaidViewer = {
      canvas,
      element,
      open: function (box) {
        state.box = box;
        element.hidden = false;
        element.setAttribute("aria-hidden", "false");
        document.body.classList.add("mermaid-viewer-open");

        window.requestAnimationFrame(function () {
          reset();
          stage.focus();
        });
      }
    };

    return window.__miniSharpMermaidViewer;
  }

  function viewerButton(action, label, path) {
    return [
      `<button type="button" class="mermaid-viewer__button" data-mermaid-viewer-action="${action}" aria-label="${label}" title="${label}">`,
      '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">',
      path,
      "</svg>",
      "</button>"
    ].join("");
  }

  function getSvgBox(svg) {
    const viewBox = svg.getAttribute("viewBox");

    if (viewBox) {
      const parts = viewBox.split(/[\s,]+/).map(Number);

      if (parts.length === 4 && parts.every(Number.isFinite) && parts[2] > 0 && parts[3] > 0) {
        return {
          width: parts[2],
          height: parts[3]
        };
      }
    }

    const width = parseSvgLength(svg.getAttribute("width"));
    const height = parseSvgLength(svg.getAttribute("height"));

    if (width && height) {
      return { width, height };
    }

    return null;
  }

  function parseSvgLength(value) {
    if (!value) {
      return null;
    }

    const parsed = Number.parseFloat(value);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  }

  function clamp(value, min, max) {
    return Math.min(Math.max(value, min), max);
  }

  if (window.document$ && typeof window.document$.subscribe === "function") {
    window.document$.subscribe(renderMermaidBlocks);
  } else {
    document.addEventListener("DOMContentLoaded", renderMermaidBlocks);
  }
})();
