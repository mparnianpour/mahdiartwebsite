/* View on your wall: builds a 3D model of a painting in a frame, at the
   painting's real size, and hands it to <model-viewer>, which shows it on a
   wall through the phone's camera (WebXR on Android, Quick Look on iPhone).

   The frame comes from tools/make_frame.py: a cut-out picture of the frame,
   its outline as triangles, its opening, and the area behind the opening.
   The frame keeps its own shape. The painting sits behind the opening,
   centred on the opening's centre, and the frame is scaled so the painting
   fills it; if the shapes differ, the opening shows the middle of the
   painting and the frame hides the rest. A frame whose opening is the other
   way round from the painting is turned on its side (unless it says
   "turn": false). */

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

/* Scale and place the frame around a w × h painting (metres). */
function fitFrame(frame, art) {
  const [ox0, oy0, ox1, oy1] = frame.opening;
  const ow = ox1 - ox0, oh = oy1 - oy0;
  const turn = frame.turn !== false && (art.h > art.w) !== (oh > ow);
  const [across, down] = turn ? [oh, ow] : [ow, oh];
  // The painting covers the opening, with a narrow edge hidden under the frame.
  const lip = Math.min(0.008, 0.01 * Math.min(art.w, art.h));
  const scale = Math.min((art.w - 2 * lip) / across, (art.h - 2 * lip) / down);   // metres per pixel
  const cx = (ox0 + ox1) / 2, cy = (oy0 + oy1) / 2;
  return {
    band: (ox0 + oy0 + (frame.width - ox1) + (frame.height - oy1)) / 4 * scale,
    // The opening hides part of the painting: it is another shape, or it isn't
    // a rectangle (the painting's corners go behind the frame).
    cropped: frame.rectangular === false || scale * Math.min(across / art.w, down / art.h) < 0.97,
    // Pixel in the frame picture -> metres, centred on the opening, y up.
    place: (x, y) => {
      const X = scale * (x - cx), Y = -scale * (y - cy);
      return turn ? [-Y, X] : [X, Y];
    },
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

/* A triangulated outline as one flat face at depth z, facing n. */
function faces(p, pts, tris, z, n, uv) {
  const ids = pts.map((q, i) => vertex(p, q[0], q[1], z, n, ...uv(q, i)));
  for (let i = 0; i < tris.length; i += 3) triangle(p, ids[tris[i]], ids[tris[i + 1]], ids[tris[i + 2]], n);
}

const FRONT = [0, 0, 1], BACK = [0, 0, -1];

function buildScene(frame, art) {
  const fit = fitFrame(frame, art);
  const depth = Math.min(0.09, Math.max(0.025, 0.3 * fit.band));
  const canvasZ = 0.4 * depth;

  const wood = primitive(), back = primitive(), canvas = primitive();
  const v = frame.vertices, W = frame.width, H = frame.height;
  const pts = [];
  for (let i = 0; i < v.length; i += 2) pts.push(fit.place(v[i], v[i + 1]));

  // Front and back of the frame.
  faces(wood, pts, frame.triangles, depth, FRONT, (q, i) => [v[2 * i] / W, v[2 * i + 1] / H]);
  faces(back, pts, frame.triangles, 0, BACK, () => [0, 0]);

  // Sides of the frame, along every outline, coloured by the frame at the edge.
  // The tool winds every outline the same way round the frame, so the outside
  // edge (the largest outline) tells which side of each edge the frame is on.
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

  // The painting, set back behind the opening and cut to its shape, centred on
  // the opening's centre; and a backing board of the same shape behind it.
  const av = frame.art.vertices, artPts = [];
  for (let i = 0; i < av.length; i += 2) artPts.push(fit.place(av[i], av[i + 1]));
  faces(canvas, artPts, frame.art.triangles, canvasZ, FRONT, (q) => [q[0] / art.w + 0.5, 0.5 - q[1] / art.h]);
  faces(back, artPts, frame.art.triangles, 0.002, BACK, () => [0, 0]);

  return { wood, back, canvas, depth, cropped: fit.cropped };
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
  const woodMat = glb.material("Frame", {
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
  return { blob: glb.toBlob(), painting: art, depth: scene.depth, cropped: scene.cropped };
}
