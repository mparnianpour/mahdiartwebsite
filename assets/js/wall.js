/* View on your wall: builds a 3D model of a painting in the carved wood frame,
   at the painting's real size, and hands it to <model-viewer>, which shows it
   on a wall through the phone's camera (WebXR on Android, Quick Look on iPhone).

   The frame comes from tools/make_frame.py: a cut-out picture of the wood
   and its outline as triangles. Corners and the ornament in the middle of each
   side keep their shape; only the stretches between them grow or shrink to fit
   the painting. Upright paintings get the frame turned on its side. */

const DEFAULT_LONG_SIDE = 1.0;   // metres, when a work has no size

/* "230 × 130 cm" -> [2.3, 1.3] in metres, or null. */
export function parseSize(text) {
  if (!text) return null;
  const m = String(text).match(/(\d+(?:[.,]\d+)?)\s*[×xX*]\s*(\d+(?:[.,]\d+)?)\s*(mm|cm|m|in|")?/);
  if (!m) return null;
  const unit = { mm: 0.001, cm: 0.01, m: 1, in: 0.0254, '"': 0.0254 }[m[3] || "cm"];
  const a = parseFloat(m[1].replace(",", ".")) * unit;
  const b = parseFloat(m[2].replace(",", ".")) * unit;
  return a > 0 && b > 0 ? [a, b] : null;
}

/* Painting size in metres. The photo decides the proportions and which way up
   it is; the written size decides how big it is (its longest side). */
function paintingSize(size, imgW, imgH) {
  const dims = parseSize(size);
  const long = dims ? Math.max(dims[0], dims[1]) : DEFAULT_LONG_SIDE;
  return imgW >= imgH
    ? { w: long, h: long * imgH / imgW, known: !!dims }
    : { w: long * imgW / imgH, h: long, known: !!dims };
}

const sum = (ranges) => ranges.reduce((t, [a, b]) => t + b - a, 0);

/* How far a point moves when the stretches along one side are scaled by k. */
function stretched(v, ranges, k) {
  let out = v;
  for (const [a, b] of ranges) out += (k - 1) * Math.min(Math.max(v - a, 0), b - a);
  return out;
}

/* Fit the frame's opening to a w × h opening (metres, frame lying landscape).
   Stretches along the top grow by kx and along the sides by ky = 1 / kx, so
   neither direction is distorted much more than the other. */
function fitFrame(frame, w, h) {
  const [ox0, oy0, ox1, oy1] = frame.opening;
  const ow = ox1 - ox0, oh = oy1 - oy0;
  const lx = sum(frame.stretch.x), ly = sum(frame.stretch.y);
  const ratio = w / h;
  const gap = (k) => (ow + (k - 1) * lx) - ratio * (oh + (1 / k - 1) * ly);
  let lo = 0.05, hi = 20;
  for (let i = 0; i < 60; i++) {
    const mid = Math.sqrt(lo * hi);
    if (gap(mid) < 0) lo = mid; else hi = mid;
  }
  const kx = Math.sqrt(lo * hi), ky = 1 / kx;
  const scale = w / (ow + (kx - 1) * lx);   // metres per pixel of the frame picture
  const cx = (stretched(ox0, frame.stretch.x, kx) + stretched(ox1, frame.stretch.x, kx)) / 2;
  const cy = (stretched(oy0, frame.stretch.y, ky) + stretched(oy1, frame.stretch.y, ky)) / 2;
  const band = (ox0 + oy0 + (frame.width - ox1) + (frame.height - oy1)) / 4 * scale;
  return {
    band,
    // Pixel in the frame picture -> metres, centred on the opening, y up.
    map: (x, y) => [
      scale * (stretched(x, frame.stretch.x, kx) - cx),
      -scale * (stretched(y, frame.stretch.y, ky) - cy),
    ],
  };
}

/* Geometry ---------------------------------------------------------------- */

function primitive() {
  return { pos: [], nor: [], uv: [], idx: [] };
}

function vertex(p, x, y, z, n, u, v) {
  p.pos.push(x, y, z);
  p.nor.push(n[0], n[1], n[2]);
  p.uv.push(u, v);
  return p.pos.length / 3 - 1;
}

/* Add a triangle wound so that it faces along n. */
function triangle(p, a, b, c, n) {
  const P = p.pos;
  const ux = P[3 * b] - P[3 * a], uy = P[3 * b + 1] - P[3 * a + 1], uz = P[3 * b + 2] - P[3 * a + 2];
  const vx = P[3 * c] - P[3 * a], vy = P[3 * c + 1] - P[3 * a + 1], vz = P[3 * c + 2] - P[3 * a + 2];
  const facing = (uy * vz - uz * vy) * n[0] + (uz * vx - ux * vz) * n[1] + (ux * vy - uy * vx) * n[2];
  if (facing >= 0) p.idx.push(a, b, c); else p.idx.push(a, c, b);
}

function quad(p, corners, n, uvs) {
  const ids = corners.map((c, i) => vertex(p, c[0], c[1], c[2], n, uvs[i][0], uvs[i][1]));
  triangle(p, ids[0], ids[1], ids[2], n);
  triangle(p, ids[0], ids[2], ids[3], n);
}

const FRONT = [0, 0, 1], BACK = [0, 0, -1];

function buildScene(frame, art) {
  // The frame is drawn landscape; an upright painting turns it on its side.
  const upright = art.h > art.w;
  const lip = Math.min(0.008, 0.01 * Math.min(art.w, art.h));   // canvas edge hidden under the frame
  const fit = upright
    ? fitFrame(frame, art.h - 2 * lip, art.w - 2 * lip)
    : fitFrame(frame, art.w - 2 * lip, art.h - 2 * lip);
  const place = upright
    ? (x, y) => { const [X, Y] = fit.map(x, y); return [-Y, X]; }
    : fit.map;
  const depth = Math.min(0.09, Math.max(0.025, 0.3 * fit.band));
  const canvasZ = 0.4 * depth;

  const wood = primitive(), back = primitive(), canvas = primitive();
  const v = frame.vertices, W = frame.width, H = frame.height;
  const pts = [];
  for (let i = 0; i < v.length; i += 2) pts.push(place(v[i], v[i + 1]));

  // Front and back of the frame.
  const front = pts.map((p, i) => vertex(wood, p[0], p[1], depth, FRONT, v[2 * i] / W, v[2 * i + 1] / H));
  const rear = pts.map((p) => vertex(back, p[0], p[1], 0, BACK, 0, 0));
  const t = frame.triangles;
  for (let i = 0; i < t.length; i += 3) {
    triangle(wood, front[t[i]], front[t[i + 1]], front[t[i + 2]], FRONT);
    triangle(back, rear[t[i]], rear[t[i + 1]], rear[t[i + 2]], BACK);
  }

  // Sides of the frame, along every outline, coloured by the wood at the edge.
  // The tool winds every outline the same way round the wood, so the outside
  // edge (the largest outline) tells which side of each edge the wood is on.
  const areas = frame.rings.map((ring) => ring.reduce((sum, id, i) => {
    const a = pts[id], b = pts[ring[(i + 1) % ring.length]];
    return sum + a[0] * b[1] - b[0] * a[1];
  }, 0));
  const side = Math.sign(areas.reduce((a, b) => (Math.abs(b) > Math.abs(a) ? b : a)));
  for (const ring of frame.rings) {
    for (let i = 0; i < ring.length; i++) {
      const ia = ring[i], ib = ring[(i + 1) % ring.length];
      const a = pts[ia], b = pts[ib];
      const dx = b[0] - a[0], dy = b[1] - a[1];
      const len = Math.hypot(dx, dy);
      if (len < 1e-7) continue;
      const n = [side * dy / len, -side * dx / len, 0];
      const ua = [v[2 * ia] / W, v[2 * ia + 1] / H], ub = [v[2 * ib] / W, v[2 * ib + 1] / H];
      quad(wood, [[a[0], a[1], depth], [b[0], b[1], depth], [b[0], b[1], 0], [a[0], a[1], 0]], n, [ua, ub, ub, ua]);
    }
  }

  // The painting, set back inside the frame, and a backing board behind it.
  const hw = art.w / 2, hh = art.h / 2;
  quad(canvas, [[-hw, hh, canvasZ], [hw, hh, canvasZ], [hw, -hh, canvasZ], [-hw, -hh, canvasZ]], FRONT,
    [[0, 0], [1, 0], [1, 1], [0, 1]]);
  quad(back, [[-hw, hh, 0.002], [hw, hh, 0.002], [hw, -hh, 0.002], [-hw, -hh, 0.002]], BACK,
    [[0, 0], [0, 0], [0, 0], [0, 0]]);

  return { wood, back, canvas, depth };
}

/* glTF binary --------------------------------------------------------------- */

class GLB {
  constructor() {
    this.chunks = [];
    this.length = 0;
    this.json = {
      asset: { version: "2.0", generator: "mahdiartwebsite wall.js" },
      scene: 0,
      scenes: [{ nodes: [0] }],
      nodes: [{ name: "Framed painting", mesh: 0 }],
      meshes: [{ primitives: [] }],
      materials: [], textures: [], images: [],
      samplers: [{ magFilter: 9729, minFilter: 9987, wrapS: 33071, wrapT: 33071 }],
      accessors: [], bufferViews: [], buffers: [],
    };
  }

  view(bytes, target) {
    const pad = (4 - (this.length % 4)) % 4;
    if (pad) { this.chunks.push(new Uint8Array(pad)); this.length += pad; }
    const view = { buffer: 0, byteOffset: this.length, byteLength: bytes.byteLength };
    if (target) view.target = target;
    this.chunks.push(new Uint8Array(bytes.buffer, bytes.byteOffset, bytes.byteLength));
    this.length += bytes.byteLength;
    return this.json.bufferViews.push(view) - 1;
  }

  accessor(array, type, size, target, bounds) {
    const componentType = array instanceof Float32Array ? 5126 : array instanceof Uint16Array ? 5123 : 5125;
    const acc = { bufferView: this.view(array, target), componentType, count: array.length / size, type };
    if (bounds) {
      acc.min = [Infinity, Infinity, Infinity];
      acc.max = [-Infinity, -Infinity, -Infinity];
      for (let i = 0; i < array.length; i += 3) {
        for (let j = 0; j < 3; j++) {
          acc.min[j] = Math.min(acc.min[j], array[i + j]);
          acc.max[j] = Math.max(acc.max[j], array[i + j]);
        }
      }
    }
    return this.json.accessors.push(acc) - 1;
  }

  texture(bytes, mimeType) {
    const image = this.json.images.push({ bufferView: this.view(bytes), mimeType }) - 1;
    return this.json.textures.push({ sampler: 0, source: image }) - 1;
  }

  material(name, pbr) {
    return this.json.materials.push({ name, pbrMetallicRoughness: { metallicFactor: 0, ...pbr } }) - 1;
  }

  primitive(p, material) {
    const count = p.pos.length / 3;
    const indices = count > 65535 ? new Uint32Array(p.idx) : new Uint16Array(p.idx);
    this.json.meshes[0].primitives.push({
      attributes: {
        POSITION: this.accessor(new Float32Array(p.pos), "VEC3", 3, 34962, true),
        NORMAL: this.accessor(new Float32Array(p.nor), "VEC3", 3, 34962),
        TEXCOORD_0: this.accessor(new Float32Array(p.uv), "VEC2", 2, 34962),
      },
      indices: this.accessor(indices, "SCALAR", 1, 34963),
      material,
    });
  }

  toBlob() {
    const pad = (4 - (this.length % 4)) % 4;
    if (pad) { this.chunks.push(new Uint8Array(pad)); this.length += pad; }
    this.json.buffers.push({ byteLength: this.length });
    let json = new TextEncoder().encode(JSON.stringify(this.json));
    const jsonPad = (4 - (json.length % 4)) % 4;
    if (jsonPad) {
      const padded = new Uint8Array(json.length + jsonPad).fill(0x20);
      padded.set(json);
      json = padded;
    }
    const header = new Uint32Array([0x46546c67, 2, 12 + 8 + json.length + 8 + this.length]);
    return new Blob([
      header, new Uint32Array([json.length, 0x4e4f534a]), json,
      new Uint32Array([this.length, 0x004e4942]), ...this.chunks,
    ], { type: "model/gltf-binary" });
  }
}

/* Images ------------------------------------------------------------------ */

async function loadImage(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Could not load ${url} (${res.status})`);
  const bytes = new Uint8Array(await res.arrayBuffer());
  const bitmap = await createImageBitmap(new Blob([bytes]));
  const jpeg = bytes[0] === 0xff && bytes[1] === 0xd8;
  const png = bytes[0] === 0x89 && bytes[1] === 0x50;
  if (jpeg || png) return { bytes, mime: jpeg ? "image/jpeg" : "image/png", width: bitmap.width, height: bitmap.height };
  // glTF only takes JPEG and PNG, so anything else is redrawn as a JPEG.
  const canvas = document.createElement("canvas");
  canvas.width = bitmap.width;
  canvas.height = bitmap.height;
  canvas.getContext("2d").drawImage(bitmap, 0, 0);
  const blob = await new Promise((done) => canvas.toBlob(done, "image/jpeg", 0.9));
  return { bytes: new Uint8Array(await blob.arrayBuffer()), mime: "image/jpeg", width: bitmap.width, height: bitmap.height };
}

/* Build the framed painting as a .glb Blob.
   frameUrl: folder with frame.json and the frame picture
   imageUrl: the painting's photo; size: e.g. "230 × 130 cm" (optional) */
export async function buildFramedPainting({ frameUrl, imageUrl, size }) {
  const base = new URL(frameUrl.replace(/\/?$/, "/"), location.href);
  const frame = await (await fetch(new URL("frame.json", base))).json();
  const [woodImg, artImg] = await Promise.all([
    loadImage(new URL(frame.image, base).href),
    loadImage(imageUrl),
  ]);
  const art = paintingSize(size, artImg.width, artImg.height);
  const scene = buildScene(frame, art);

  const glb = new GLB();
  const woodMat = glb.material("Carved wood", {
    baseColorTexture: { index: glb.texture(woodImg.bytes, woodImg.mime) }, roughnessFactor: 0.7,
  });
  const backMat = glb.material("Back of the frame", {
    baseColorFactor: [0.23, 0.15, 0.09, 1], roughnessFactor: 0.95,
  });
  const canvasMat = glb.material("Painting", {
    baseColorTexture: { index: glb.texture(artImg.bytes, artImg.mime) }, roughnessFactor: 0.9,
  });
  glb.primitive(scene.wood, woodMat);
  glb.primitive(scene.back, backMat);
  glb.primitive(scene.canvas, canvasMat);
  return { blob: glb.toBlob(), painting: art, depth: scene.depth };
}
