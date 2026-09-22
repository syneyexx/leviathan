/**
 * Leviathan Visual Builder — WebGPU 2D chrome renderer.
 * Instance-based solid rects (boxes, guides-as-rects, handles, lines-as-thin-rects).
 * Labels drawn on a Canvas2D overlay (glyph atlas would be overkill).
 * Returns null from createWebGpuBackend when GPU is unavailable.
 */

const MAX_INSTANCES = 8192;
const FLOATS_PER = 8; // x, y, w, h, r, g, b, a

const WGSL = /* wgsl */ `
struct Uniforms {
  viewport: vec2f,
  pad: vec2f,
};
@group(0) @binding(0) var<uniform> uni: Uniforms;

struct VSIn {
  @location(0) pos: vec2f,
  @location(1) inst: vec4f, // x y w h
  @location(2) color: vec4f,
};
struct VSOut {
  @builtin(position) position: vec4f,
  @location(0) color: vec4f,
};

@vertex
fn vs_main(input: VSIn) -> VSOut {
  var out: VSOut;
  let px = input.inst.x + input.pos.x * input.inst.z;
  let py = input.inst.y + input.pos.y * input.inst.w;
  let ndcX = (px / uni.viewport.x) * 2.0 - 1.0;
  let ndcY = 1.0 - (py / uni.viewport.y) * 2.0;
  out.position = vec4f(ndcX, ndcY, 0.0, 1.0);
  out.color = input.color;
  return out;
}

@fragment
fn fs_main(input: VSOut) -> @location(0) vec4f {
  return input.color;
}
`;

function lineAsRect(x1, y1, x2, y2, width, color) {
  const dx = x2 - x1;
  const dy = y2 - y1;
  const len = Math.hypot(dx, dy) || 0.001;
  const nx = (-dy / len) * (width / 2);
  const ny = (dx / len) * (width / 2);
  // Approximate axis-aligned AABB for thin lines (good enough for guides/measure)
  if (Math.abs(dx) >= Math.abs(dy)) {
    return { x: Math.min(x1, x2), y: Math.min(y1, y2) - width / 2, w: len, h: width, color };
  }
  return { x: Math.min(x1, x2) - width / 2, y: Math.min(y1, y2), w: width, h: len, color };
}

/**
 * @param {HTMLElement} host
 * @returns {Promise<null | object>}
 */
export async function createWebGpuBackend(host) {
  if (!globalThis.navigator?.gpu) return null;
  let adapter;
  try {
    adapter = await navigator.gpu.requestAdapter();
  } catch {
    return null;
  }
  if (!adapter) return null;
  let device;
  try {
    device = await adapter.requestDevice();
  } catch {
    return null;
  }

  const canvas = document.createElement("canvas");
  canvas.className = "lvb-gpu-canvas";
  canvas.setAttribute("aria-hidden", "true");
  host.appendChild(canvas);

  const labelCanvas = document.createElement("canvas");
  labelCanvas.className = "lvb-label-canvas";
  labelCanvas.setAttribute("aria-hidden", "true");
  host.appendChild(labelCanvas);
  const labelCtx = labelCanvas.getContext("2d");

  const context = canvas.getContext("webgpu");
  if (!context) {
    canvas.remove();
    labelCanvas.remove();
    device.destroy?.();
    return null;
  }

  const format = navigator.gpu.getPreferredCanvasFormat();
  const sampleCount = 1;

  const shader = device.createShaderModule({ code: WGSL });
  const pipeline = device.createRenderPipeline({
    layout: "auto",
    vertex: {
      module: shader,
      entryPoint: "vs_main",
      buffers: [
        {
          arrayStride: 8,
          stepMode: "vertex",
          attributes: [{ shaderLocation: 0, offset: 0, format: "float32x2" }],
        },
        {
          arrayStride: 32,
          stepMode: "instance",
          attributes: [
            { shaderLocation: 1, offset: 0, format: "float32x4" },
            { shaderLocation: 2, offset: 16, format: "float32x4" },
          ],
        },
      ],
    },
    fragment: {
      module: shader,
      entryPoint: "fs_main",
      targets: [
        {
          format,
          blend: {
            color: { srcFactor: "src-alpha", dstFactor: "one-minus-src-alpha", operation: "add" },
            alpha: { srcFactor: "one", dstFactor: "one-minus-src-alpha", operation: "add" },
          },
        },
      ],
    },
    primitive: { topology: "triangle-list" },
    multisample: { count: sampleCount },
  });

  // Unit quad: (0,0)-(1,1)
  const quad = new Float32Array([0, 0, 1, 0, 0, 1, 0, 1, 1, 0, 1, 1]);
  const quadBuf = device.createBuffer({
    size: quad.byteLength,
    usage: GPUBufferUsage.VERTEX | GPUBufferUsage.COPY_DST,
  });
  device.queue.writeBuffer(quadBuf, 0, quad);

  const instanceData = new Float32Array(MAX_INSTANCES * FLOATS_PER);
  const instanceBuf = device.createBuffer({
    size: instanceData.byteLength,
    usage: GPUBufferUsage.VERTEX | GPUBufferUsage.COPY_DST,
  });

  const uniformData = new Float32Array(4);
  const uniformBuf = device.createBuffer({
    size: 16,
    usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST,
  });

  const bindGroup = device.createBindGroup({
    layout: pipeline.getBindGroupLayout(0),
    entries: [{ binding: 0, resource: { buffer: uniformBuf } }],
  });

  let width = 0;
  let height = 0;
  let dpr = 1;
  let frames = 0;
  let lastFrameMs = 0;
  let lastDrawCount = 0;

  function resize() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    width = Math.max(1, Math.floor(window.innerWidth));
    height = Math.max(1, Math.floor(window.innerHeight));
    canvas.width = Math.floor(width * dpr);
    canvas.height = Math.floor(height * dpr);
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    labelCanvas.width = canvas.width;
    labelCanvas.height = canvas.height;
    labelCanvas.style.width = `${width}px`;
    labelCanvas.style.height = `${height}px`;
    context.configure({
      device,
      format,
      alphaMode: "premultiplied",
      usage: GPUTextureUsage.RENDER_ATTACHMENT,
    });
  }

  resize();

  function pushInstance(list, x, y, w, h, color) {
    if (list.count >= MAX_INSTANCES) return;
    const i = list.count * FLOATS_PER;
    instanceData[i] = x;
    instanceData[i + 1] = y;
    instanceData[i + 2] = Math.max(w, 0.5);
    instanceData[i + 3] = Math.max(h, 0.5);
    instanceData[i + 4] = color[0] ?? 1;
    instanceData[i + 5] = color[1] ?? 1;
    instanceData[i + 6] = color[2] ?? 1;
    instanceData[i + 7] = color[3] ?? 1;
    list.count += 1;
  }

  /**
   * @param {import('./scene-graph.js').createScene extends Function ? any : any} scene
   */
  function draw(scene) {
    const t0 = performance.now();
    const nodes = scene?.nodes || [];
    const batch = { count: 0 };
    const labels = [];

    for (const n of nodes) {
      if (n.type === "rect") {
        if (n.stroke && n.strokeW) {
          const sw = n.strokeW;
          pushInstance(batch, n.x, n.y, n.w, sw, n.stroke);
          pushInstance(batch, n.x, n.y + n.h - sw, n.w, sw, n.stroke);
          pushInstance(batch, n.x, n.y, sw, n.h, n.stroke);
          pushInstance(batch, n.x + n.w - sw, n.y, sw, n.h, n.stroke);
        }
        if (n.color[3] > 0.001) pushInstance(batch, n.x, n.y, n.w, n.h, n.color);
      } else if (n.type === "line") {
        const approx = lineAsRect(n.x1, n.y1, n.x2, n.y2, n.width || 1, n.color);
        pushInstance(batch, approx.x, approx.y, approx.w, approx.h, approx.color);
      } else if (n.type === "circle") {
        // Approximate circle as square (handles / measure dots)
        const d = n.r * 2;
        pushInstance(batch, n.x - n.r, n.y - n.r, d, d, n.color);
      } else if (n.type === "label") {
        labels.push(n);
      }
    }

    uniformData[0] = width;
    uniformData[1] = height;
    device.queue.writeBuffer(uniformBuf, 0, uniformData);
    if (batch.count) {
      device.queue.writeBuffer(instanceBuf, 0, instanceData.subarray(0, batch.count * FLOATS_PER));
    }

    const encoder = device.createCommandEncoder();
    const pass = encoder.beginRenderPass({
      colorAttachments: [
        {
          view: context.getCurrentTexture().createView(),
          clearValue: { r: 0, g: 0, b: 0, a: 0 },
          loadOp: "clear",
          storeOp: "store",
        },
      ],
    });
    pass.setPipeline(pipeline);
    pass.setBindGroup(0, bindGroup);
    pass.setVertexBuffer(0, quadBuf);
    pass.setVertexBuffer(1, instanceBuf);
    if (batch.count) pass.draw(6, batch.count);
    pass.end();
    device.queue.submit([encoder.finish()]);

    // Labels
    if (labelCtx) {
      labelCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
      labelCtx.clearRect(0, 0, width, height);
      labelCtx.font = "700 11px Manrope, system-ui, sans-serif";
      labelCtx.textBaseline = "middle";
      for (const lab of labels) {
        const c = lab.color || [0.94, 0.78, 0.45, 1];
        labelCtx.fillStyle = `rgba(${Math.round(c[0] * 255)},${Math.round(c[1] * 255)},${Math.round(c[2] * 255)},${c[3]})`;
        labelCtx.textAlign = lab.align || "left";
        // pill background
        const metrics = labelCtx.measureText(lab.text);
        const tw = metrics.width + 10;
        const th = 16;
        const lx = lab.align === "center" ? lab.x - tw / 2 : lab.x;
        labelCtx.fillStyle = "rgba(12,11,9,0.85)";
        labelCtx.fillRect(lx, lab.y - th / 2, tw, th);
        labelCtx.fillStyle = `rgba(${Math.round(c[0] * 255)},${Math.round(c[1] * 255)},${Math.round(c[2] * 255)},${c[3]})`;
        labelCtx.fillText(lab.text, lab.align === "center" ? lab.x : lab.x + 5, lab.y);
      }
    }

    frames += 1;
    lastFrameMs = performance.now() - t0;
    lastDrawCount = batch.count + labels.length;
  }

  function setVisible(on) {
    canvas.style.display = on ? "block" : "none";
    labelCanvas.style.display = on ? "block" : "none";
  }

  function getStats() {
    const info = {
      backend: "webgpu",
      adapter: adapter.info || {},
      features: [...(adapter.features || [])],
      limits: {
        maxBufferSize: adapter.limits?.maxBufferSize,
        maxBindGroups: adapter.limits?.maxBindGroups,
      },
      frames,
      lastFrameMs,
      drawCount: lastDrawCount,
      canvas: { width: canvas.width, height: canvas.height, dpr },
    };
    try {
      // Prefer preferredCanvasFormat only; memory estimate coarse
      info.vramEstimateMb = Math.round((canvas.width * canvas.height * 4 * 2) / (1024 * 1024) * 10) / 10;
    } catch {
      /* ignore */
    }
    return info;
  }

  function dispose() {
    try {
      device.destroy?.();
    } catch {
      /* ignore */
    }
    canvas.remove();
    labelCanvas.remove();
  }

  device.lost.then(() => {
    setVisible(false);
  });

  return {
    id: "webgpu",
    resize,
    draw,
    setVisible,
    getStats,
    dispose,
    canvas,
    labelCanvas,
  };
}
