// Olympus World viewer - watch only. Draws the world and reads the gods' journals.
import * as THREE from './vendor/three.module.js';
import { OrbitControls } from './vendor/OrbitControls.js';
import { mergeGeometries } from './vendor/BufferGeometryUtils.js';

const MAT = {
  stone: { c: '#9a968f' }, marble: { c: '#efeae0', r: 0.45 }, wood: { c: '#8a5a33' },
  brick: { c: '#a5482f' }, glass: { c: '#bfe3ff', o: 0.45, r: 0.1 }, gold: { c: '#e9b949', m: 0.85, r: 0.3 },
  bronze: { c: '#b0793a', m: 0.7, r: 0.4 }, clay: { c: '#c47a52' }, grass: { c: '#5fae55' },
  water: { c: '#3d8fd1', o: 0.75, r: 0.15 }, cloth: { c: '#d6648b' }, iron: { c: '#5d6470', m: 0.7, r: 0.45 },
  crystal: { c: '#b48cff', o: 0.8, e: '#6a3fd0', r: 0.1 }, sand: { c: '#dcc58f' },
  obsidian: { c: '#22202a', r: 0.2 }, leaves: { c: '#3f8a3a' },
};

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

// ------------------------------------------------------------------ scene
const host = $('scene');
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setSize(innerWidth, innerHeight);
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.outputColorSpace = THREE.SRGBColorSpace;
host.appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.fog = new THREE.Fog(0xc9d6ff, 70, 300);
const camera = new THREE.PerspectiveCamera(50, innerWidth / innerHeight, 0.1, 1000);
camera.position.set(30, 28, 38);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.maxPolarAngle = 1.45;
controls.minDistance = 4;
controls.maxDistance = 160;

// sky dome with a vertical gradient
const skyUniforms = { top: { value: new THREE.Color('#3f6fd8') }, bottom: { value: new THREE.Color('#c9d6ff') } };
const sky = new THREE.Mesh(
  new THREE.SphereGeometry(400, 32, 16),
  new THREE.ShaderMaterial({
    uniforms: skyUniforms, side: THREE.BackSide, depthWrite: false, fog: false,
    vertexShader: 'varying vec3 vP; void main(){ vP = (modelMatrix*vec4(position,1.0)).xyz; gl_Position = projectionMatrix*viewMatrix*vec4(vP,1.0); }',
    fragmentShader: 'uniform vec3 top; uniform vec3 bottom; varying vec3 vP; void main(){ float h = clamp(normalize(vP).y*1.6+0.1,0.0,1.0); gl_FragColor = vec4(mix(bottom, top, h),1.0); }',
  }));
scene.add(sky);

// stars (visible at night)
const starGeo = new THREE.BufferGeometry();
const sp = [];
for (let i = 0; i < 900; i++) {
  const t = Math.random() * Math.PI * 2, p = Math.random() * 1.3;
  sp.push(Math.cos(t) * Math.cos(p) * 380, Math.sin(p) * 380 + 10, Math.sin(t) * Math.cos(p) * 380);
}
starGeo.setAttribute('position', new THREE.Float32BufferAttribute(sp, 3));
const stars = new THREE.Points(starGeo, new THREE.PointsMaterial({ color: 0xffffff, size: 1.6, transparent: true, opacity: 0, fog: false }));
scene.add(stars);

const hemi = new THREE.HemisphereLight(0xdfe6ff, 0x8a83c9, 0.9);
scene.add(hemi);
const sun = new THREE.DirectionalLight(0xfff3dd, 1.6);
sun.castShadow = true;
sun.shadow.mapSize.set(2048, 2048);
Object.assign(sun.shadow.camera, { left: -60, right: 60, top: 60, bottom: -60, near: 1, far: 260 });
scene.add(sun, sun.target);

// clouds
const clouds = new THREE.Group();
const cloudMat = new THREE.MeshLambertMaterial({ color: 0xffffff, transparent: true, opacity: 0.92 });
for (let i = 0; i < 18; i++) {
  const c = new THREE.Group();
  for (let j = 0; j < 5; j++) {
    const s = new THREE.Mesh(new THREE.SphereGeometry(3 + Math.random() * 3, 12, 8), cloudMat);
    s.position.set(j * 4 - 8 + Math.random() * 2, Math.random() * 2, Math.random() * 4);
    s.scale.y = 0.55;
    c.add(s);
  }
  c.position.set(Math.random() * 300 - 150, 55 + Math.random() * 20, Math.random() * 300 - 150);
  clouds.add(c);
}
scene.add(clouds);

// ------------------------------------------------------------------ shaders the gods write (1.4)
// A god writes only the BODY of a small function; the viewer wraps it, test-compiles it in a scratch
// WebGL context, and only then draws with it. If it fails (or is too slow) the last working one stays.
const GLSL_HELPERS = `float hash(vec2 p){ p = fract(p * vec2(123.34, 456.21)); p += dot(p, p + 45.32); return fract(p.x * p.y); }
float noise(vec2 p){ vec2 i = floor(p); vec2 f = fract(p); float a = hash(i); float b = hash(i + vec2(1.0, 0.0));
  float c = hash(i + vec2(0.0, 1.0)); float d = hash(i + vec2(1.0, 1.0)); vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(a, b, u.x) + (c - a) * u.y * (1.0 - u.x) + (d - b) * u.x * u.y; }
float fbm(vec2 p){ float v = 0.0; float a = 0.5; for (int i = 0; i < 5; i++) { v += a * noise(p); p *= 2.0; a *= 0.5; } return v; }
`;
const SIGS = {
  sky: 'vec3 shade(vec3 dir, float time, float daylight, vec3 top, vec3 bottom)',
  water: 'vec3 shade(vec2 p, float time, float daylight, vec3 base)',
  ground: 'vec3 shade(vec2 p, float time, float daylight, vec3 base)',
};
const DEFAULT_BODY = {
  sky: 'return mix(bottom, top, clamp(dir.y * 1.6 + 0.1, 0.0, 1.0));',
  water: 'return base * (0.9 + 0.1 * noise(p * 0.6 + vec2(time * 0.2, 0.0)));',
  ground: 'return base;',
};
const SHADES = { ...DEFAULT_BODY };          // the body each target is drawn with right now
const shadeTime = { value: 0 }, shadeDay = { value: 1 };
const shadeFn = (target, body) => `${GLSL_HELPERS}\n${SIGS[target]} {\n${body}\n}\n`;

function shadedStandard(params, target) {
  const m = new THREE.MeshStandardMaterial(params);
  const body = SHADES[target];
  m.onBeforeCompile = (sh) => {
    sh.uniforms.uTime = shadeTime; sh.uniforms.uDay = shadeDay;
    sh.vertexShader = 'varying vec3 vWP;\n' + sh.vertexShader.replace('#include <begin_vertex>',
      '#include <begin_vertex>\nvWP = (modelMatrix * vec4(transformed, 1.0)).xyz;');
    sh.fragmentShader = 'uniform float uTime;\nuniform float uDay;\nvarying vec3 vWP;\n' + shadeFn(target, body)
      + sh.fragmentShader.replace('vec4 diffuseColor = vec4( diffuse, opacity );',
        'vec4 diffuseColor = vec4( clamp(shade(vWP.xz, uTime, uDay, diffuse), 0.0, 1.0), opacity );');
  };
  m.customProgramCacheKey = () => target + ':' + body;
  return m;
}

const testGL = (() => { try { return document.createElement('canvas').getContext('webgl2'); } catch { return null; } })();
function testShader(target, body) {
  // returns null if it compiles and links, otherwise the error text
  const gl = testGL;
  if (!gl) return null;
  const call = target === 'sky' ? 'shade(normalize(vP), uTime, uDay, uTop, uBottom)' : 'shade(vP.xz, uTime, uDay, uBase)';
  const fs = `#version 300 es\nprecision highp float;\nuniform float uTime; uniform float uDay; uniform vec3 uTop; uniform vec3 uBottom; uniform vec3 uBase;\nin vec3 vP;\nout vec4 fragOut;\n${shadeFn(target, body)}\nvoid main(){ fragOut = vec4(${call}, 1.0); }`;
  const vs = '#version 300 es\nin vec3 position; out vec3 vP; void main(){ vP = position; gl_Position = vec4(position, 1.0); }';
  const make = (type, src) => { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s); return s; };
  const v = make(gl.VERTEX_SHADER, vs), f = make(gl.FRAGMENT_SHADER, fs);
  let err = null;
  if (!gl.getShaderParameter(f, gl.COMPILE_STATUS)) err = (gl.getShaderInfoLog(f) || 'it did not compile').trim();
  else {
    const p = gl.createProgram(); gl.attachShader(p, v); gl.attachShader(p, f); gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) err = (gl.getProgramInfoLog(p) || 'it did not link').trim();
    gl.deleteProgram(p);
  }
  gl.deleteShader(v); gl.deleteShader(f);
  return err ? err.replace(/\s+/g, ' ').slice(0, 280) : null;
}

function skyMaterial() {
  return new THREE.ShaderMaterial({
    uniforms: { uTop: skyUniforms.top, uBottom: skyUniforms.bottom, uTime: shadeTime, uDay: shadeDay },
    side: THREE.BackSide, depthWrite: false, fog: false,
    vertexShader: 'varying vec3 vP; void main(){ vP = (modelMatrix*vec4(position,1.0)).xyz; gl_Position = projectionMatrix*viewMatrix*vec4(vP,1.0); }',
    fragmentShader: `uniform vec3 uTop; uniform vec3 uBottom; uniform float uTime; uniform float uDay; varying vec3 vP;\n${shadeFn('sky', SHADES.sky)}\nvoid main(){ gl_FragColor = vec4(clamp(shade(normalize(vP), uTime, uDay, uTop, uBottom), 0.0, 1.0), 1.0); }`,
  });
}
sky.material.dispose();
sky.material = skyMaterial();

// ------------------------------------------------------------------ graphics the gods tune (1.4)
let GFX = { sun_color: '#fff3dd', sun_strength: 1, sun_tilt: 20, ambient_color: '#dfe6ff', ambient_strength: 1,
            shadows: 'soft', grid: true, hills: 0, materials: {}, effects: [], ponds: [], paths: [] };
function vnoise(x, z) {
  const h = (a, b) => { const s = Math.sin(a * 127.1 + b * 311.7) * 43758.5453; return s - Math.floor(s); };
  const ix = Math.floor(x), iz = Math.floor(z), fx = x - ix, fz = z - iz;
  const ux = fx * fx * (3 - 2 * fx), uz = fz * fz * (3 - 2 * fz);
  const a = h(ix, iz), b = h(ix + 1, iz), c = h(ix, iz + 1), d = h(ix + 1, iz + 1);
  return a + (b - a) * ux + (c - a) * uz + (a - b - c + d) * ux * uz;
}

let half = 40;
let ground, grid, edge;
function buildGround(h) {
  half = h;
  [ground, grid, edge].forEach((o) => o && scene.remove(o));
  ground = new THREE.Mesh(new THREE.PlaneGeometry(1200, 1200, 220, 220), shadedStandard({ color: '#aaa4ea', roughness: 0.95 }, 'ground'));
  ground.rotation.x = -Math.PI / 2;
  ground.receiveShadow = true;
  grid = new THREE.GridHelper(h * 2, h / 2, 0xffffff, 0xffffff);
  grid.material.transparent = true;
  grid.material.opacity = 0.55;
  grid.position.y = 0.01;
  const pts = [[-h, -h], [h, -h], [h, h], [-h, h], [-h, -h]].map(([x, z]) => new THREE.Vector3(x, 0.03, z));
  edge = new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineBasicMaterial({ color: 0x5a4fcf, transparent: true, opacity: 0.5 }));
  grid.visible = GFX.grid !== false;
  scene.add(ground, grid, edge);
  applyHills(GFX.hills || 0);
}
function applyHills(amount) {
  // gentle hills only OUTSIDE the world's edge, so nothing the gods built floats or sinks
  const pos = ground.geometry.attributes.position;
  for (let i = 0; i < pos.count; i++) {
    const x = pos.getX(i), z = -pos.getY(i);
    const d = Math.max(Math.abs(x), Math.abs(z));
    const t = Math.min(1, Math.max(0, (d - half - 8) / 70));
    const ramp = t * t * (3 - 2 * t);
    pos.setZ(i, amount > 0 ? amount * 22 * ramp * (0.3 + 0.7 * vnoise(x * 0.025, z * 0.025)) : 0);
  }
  pos.needsUpdate = true;
  ground.geometry.computeVertexNormals();
}
buildGround(40);

// ------------------------------------------------------------------ sprites
const LABEL_K = 0.05;
function textSprite(text, { bg = 'rgba(251,246,233,0.95)', fg = '#23213a', size = 34, maxW = 520, pad = 18, border = '#e7dcc0', scale = 0.012 } = {}) {
  const cv = document.createElement('canvas');
  const ctx = cv.getContext('2d');
  const font = `600 ${size}px system-ui, Segoe UI, sans-serif`;
  ctx.font = font;
  const words = String(text).split(/\s+/);
  const lines = [];
  let line = '';
  for (const w of words) {
    const t = line ? line + ' ' + w : w;
    if (ctx.measureText(t).width > maxW && line) { lines.push(line); line = w; } else line = t;
    if (lines.length >= 3) break;
  }
  if (lines.length < 3 && line) lines.push(line);
  if (lines.length === 3 && words.join(' ').length > lines.join(' ').length) lines[2] = lines[2].replace(/.{0,2}$/, '…');
  const w = Math.min(maxW, Math.max(...lines.map((l) => ctx.measureText(l).width))) + pad * 2;
  const lh = size * 1.25;
  const h = lines.length * lh + pad * 1.4;
  cv.width = Math.ceil(w); cv.height = Math.ceil(h);
  const c2 = cv.getContext('2d');
  c2.font = font;
  c2.fillStyle = bg; c2.strokeStyle = border; c2.lineWidth = 3;
  const r = Math.min(22, h / 2);
  c2.beginPath(); c2.roundRect(1.5, 1.5, cv.width - 3, cv.height - 3, r); c2.fill(); c2.stroke();
  c2.fillStyle = fg; c2.textBaseline = 'top';
  lines.forEach((l, i) => c2.fillText(l, pad, pad * 0.7 + i * lh));
  const tex = new THREE.CanvasTexture(cv);
  tex.colorSpace = THREE.SRGBColorSpace;
  const spr = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthWrite: false, depthTest: false, transparent: true, sizeAttenuation: false }));
  // fixed on-screen size, so names stay readable from far away
  spr.userData.px = [cv.width * scale, cv.height * scale];
  spr.scale.set(cv.width * scale * LABEL_K, cv.height * scale * LABEL_K, 1);
  spr.renderOrder = 10;
  return spr;
}
function disposeSprite(s) { if (!s) return; s.material.map.dispose(); s.material.dispose(); s.parent && s.parent.remove(s); }

// ------------------------------------------------------------------ gods
const gods = new Map(); // id -> {group, data, label, labelKey, bubble, bubbleText, pos}
const pickables = [];
const STATUS_WORD = { idle: '', walking: 'walking', thinking: 'thinking…', resting: 'resting', reading: 'reading' };

function makeGod(a) {
  const g = new THREE.Group();
  const body = new THREE.Group();
  const robeMat = new THREE.MeshStandardMaterial({ color: a.color, roughness: 0.6 });
  const robe = new THREE.Mesh(new THREE.CylinderGeometry(0.32, 0.6, 1.4, 18), robeMat);
  robe.position.y = 0.7;
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.32, 20, 14), new THREE.MeshStandardMaterial({ color: '#f1d7c0', roughness: 0.7 }));
  head.position.y = 1.68;
  const halo = new THREE.Mesh(new THREE.TorusGeometry(0.3, 0.04, 8, 28), new THREE.MeshStandardMaterial({ color: a.color, emissive: a.color, emissiveIntensity: 1.2 }));
  halo.position.y = 2.18; halo.rotation.x = Math.PI / 2;
  [robe, head].forEach((m) => { m.castShadow = true; m.userData.agentId = a.id; pickables.push(m); });
  body.add(robe, head, halo);
  g.add(body);
  g.position.set(a.x, 0, a.z);
  scene.add(g);
  return { group: g, body, halo, data: a, label: null, labelKey: '', bubble: null, bubbleText: null, last: new THREE.Vector3(a.x, 0, a.z) };
}

function updateGodVisual(o, a) {
  o.data = a;
  const key = a.name + '|' + a.status;
  if (key !== o.labelKey) {
    disposeSprite(o.label);
    const word = STATUS_WORD[a.status] ?? a.status;
    o.label = textSprite(word ? `${a.name} · ${word}` : a.name, { size: 30, pad: 14, scale: 0.011 });
    o.label.position.y = 2.75;
    o.group.add(o.label);
    o.labelKey = key;
  }
  if (a.said !== o.bubbleText) {
    disposeSprite(o.bubble); o.bubble = null;
    if (a.said) {
      o.bubble = textSprite(`“${a.said}”`, { bg: '#ffffff', size: 30, maxW: 560, scale: 0.012, border: a.color });
      o.bubble.position.y = 3.9;
      o.group.add(o.bubble);
    }
    o.bubbleText = a.said;
  }
}

// ------------------------------------------------------------------ structures
// Every shape is built to fill a 1x1x1 box centred on 0, then scaled to w/h/d.
function unit(g) { g.computeVertexNormals(); return g; }
function extrudeUnit(shape) {
  const g = new THREE.ExtrudeGeometry(shape, { depth: 1, bevelEnabled: false, curveSegments: 16 });
  g.translate(0, 0, -0.5);
  return g;
}
const SHAPE_GEOS = {
  box: new THREE.BoxGeometry(1, 1, 1),
  cylinder: new THREE.CylinderGeometry(0.5, 0.5, 1, 24),
  pyramid: (() => { const g = new THREE.ConeGeometry(Math.SQRT1_2, 1, 4); g.rotateY(Math.PI / 4); return g; })(),
  sphere: new THREE.SphereGeometry(0.5, 24, 16),
  cone: new THREE.ConeGeometry(0.5, 1, 24),
  dome: (() => { const g = new THREE.SphereGeometry(0.5, 24, 12, 0, Math.PI * 2, 0, Math.PI / 2); g.scale(1, 2, 1); g.translate(0, -0.5, 0); return g; })(),
  arch: (() => {
    const sh = new THREE.Shape();
    sh.moveTo(-0.5, -0.5); sh.lineTo(-0.3, -0.5); sh.lineTo(-0.3, 0.05);
    sh.absarc(0, 0.05, 0.3, Math.PI, 0, true);
    sh.lineTo(0.3, -0.5); sh.lineTo(0.5, -0.5); sh.lineTo(0.5, 0.5); sh.lineTo(-0.5, 0.5); sh.lineTo(-0.5, -0.5);
    return extrudeUnit(sh);
  })(),
  stairs: (() => {
    const parts = [];
    for (let i = 0; i < 5; i++) {
      const g = new THREE.BoxGeometry(1, (i + 1) / 5, 1 / 5);
      g.translate(0, -0.5 + (i + 1) / 10, 0.5 - (i + 0.5) / 5);   // rises toward -z
      parts.push(g.toNonIndexed());
    }
    return unit(mergeGeometries(parts));
  })(),
  wedge: (() => { const sh = new THREE.Shape(); sh.moveTo(-0.5, -0.5); sh.lineTo(0.5, -0.5); sh.lineTo(-0.5, 0.5); sh.lineTo(-0.5, -0.5); return extrudeUnit(sh); })(),
  ring: (() => { const g = new THREE.TorusGeometry(0.4, 0.1, 12, 36); g.scale(1, 1, 5); return g; })(),
};
// plants are two pieces: [geometry, material override]
const TRUNK = (() => { const g = new THREE.CylinderGeometry(0.07, 0.1, 0.45, 10); g.translate(0, -0.275, 0); return g; })();
const CANOPY = (() => { const g = new THREE.ConeGeometry(0.45, 0.8, 14); g.translate(0, 0.1, 0); return g; })();
const BUSH = (() => { const g = new THREE.SphereGeometry(0.5, 14, 10); return g; })();

const matCache = {};
const glowMats = [];
function material(name, color, glow) {
  const key = `${name}|${color || ''}|${glow ? 1 : 0}`;
  if (matCache[key]) return matCache[key];
  const m = MAT[name] || MAT.stone;
  const o = (GFX.materials || {})[name] || {};
  const c = color || o.color || m.c;
  const own = o.glow > 0 && !glow;
  const mat = new THREE.MeshStandardMaterial({
    color: c, roughness: o.roughness ?? m.r ?? 0.8, metalness: o.metalness ?? m.m ?? 0,
    transparent: m.o !== undefined, opacity: m.o ?? 1,
    emissive: glow || own ? c : (m.e || '#000000'), emissiveIntensity: glow ? 1 : (own ? o.glow * 0.6 : (m.e ? 0.5 : 0)),
  });
  if (glow) glowMats.push(mat);
  matCache[key] = mat;
  return mat;
}
function stripAttrs(g) {
  g = g.index ? g.toNonIndexed() : g.clone();
  for (const k of Object.keys(g.attributes)) if (k !== 'position' && k !== 'normal') g.deleteAttribute(k);
  g.clearGroups();
  return g;
}
const PREP = {};
function prepped(key, geo) { return PREP[key] || (PREP[key] = stripAttrs(geo)); }

// soft halo used for glowing parts at night
const haloTex = (() => {
  const cv = document.createElement('canvas'); cv.width = cv.height = 128;
  const g = cv.getContext('2d'); const gr = g.createRadialGradient(64, 64, 0, 64, 64, 64);
  gr.addColorStop(0, 'rgba(255,255,255,0.9)'); gr.addColorStop(0.35, 'rgba(255,255,255,0.35)'); gr.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = gr; g.fillRect(0, 0, 128, 128);
  const t = new THREE.CanvasTexture(cv); t.colorSpace = THREE.SRGBColorSpace; return t;
})();
const halos = [];
const MAX_HALOS = 400;

const structures = new Map(); // id -> {group, count, name, center}
const _m = new THREE.Matrix4(), _q = new THREE.Quaternion(), _e = new THREE.Euler(), _p = new THREE.Vector3(), _s = new THREE.Vector3();

function partPieces(p) {
  const shape = SHAPE_GEOS[p.shape] ? p.shape : (p.shape === 'tree' || p.shape === 'bush' ? p.shape : 'box');
  if (shape === 'tree') return [['trunk', TRUNK, 'wood', null], ['canopy', CANOPY, p.material === 'stone' ? 'leaves' : p.material, p.color]];
  if (shape === 'bush') return [['bush', BUSH, p.material === 'stone' ? 'leaves' : p.material, p.color]];
  return [[shape, SHAPE_GEOS[shape], p.material, p.color]];
}

function buildStructureMesh(s) {
  const g = new THREE.Group();
  const buckets = new Map();
  let top = 0;
  for (const p of s.parts) {
    _p.set(p.dx, p.y + p.h / 2, p.dz);
    _q.setFromEuler(_e.set(0, THREE.MathUtils.degToRad(p.rot || 0), 0));
    _s.set(p.w, p.h, p.d);
    _m.compose(_p, _q, _s);
    for (const [gk, geo, matName, color] of partPieces(p)) {
      const mk = `${matName}|${color || ''}|${p.glow ? 1 : 0}`;
      if (!buckets.has(mk)) buckets.set(mk, { mat: material(matName, color, p.glow), geos: [] });
      buckets.get(mk).geos.push(prepped(gk, geo).clone().applyMatrix4(_m));
    }
    if (p.glow && halos.length < MAX_HALOS) {
      const h = new THREE.Sprite(new THREE.SpriteMaterial({ map: haloTex, color: p.color || (MAT[p.material] || MAT.stone).c, blending: THREE.AdditiveBlending, depthWrite: false, transparent: true, opacity: 0 }));
      const r = Math.max(p.w, p.h, p.d) * 2.6 + 1.5;
      h.scale.set(r, r, 1);
      h.position.set(p.dx, p.y + p.h / 2, p.dz);
      h.userData.halo = true;
      g.add(h); halos.push(h);
    }
    top = Math.max(top, p.y + p.h);
  }
  for (const { mat, geos } of buckets.values()) {
    const merged = mergeGeometries(geos, false);
    geos.forEach((x) => x.dispose());
    if (!merged) continue;
    const mesh = new THREE.Mesh(merged, mat);
    mesh.castShadow = true; mesh.receiveShadow = true;
    g.add(mesh);
  }
  return { g, top };
}

function disposeStructure(o) {
  o.group.traverse((x) => {
    if (x.isMesh) x.geometry.dispose();
    if (x.userData.halo) { const i = halos.indexOf(x); if (i >= 0) halos.splice(i, 1); x.material.dispose(); }
  });
  scene.remove(o.group);
}

function syncStructures(list) {
  const seen = new Set();
  for (const s of list) {
    seen.add(s.id);
    const ex = structures.get(s.id);
    if (ex && ex.count === s.parts.length && ex.name === s.name) continue;
    if (ex) disposeStructure(ex);
    const { g, top } = buildStructureMesh(s);
    const lbl = textSprite(s.name, { size: 28, pad: 12, bg: 'rgba(35,33,58,0.82)', fg: '#fbf6e9', border: 'rgba(0,0,0,0)', scale: 0.012 });
    lbl.position.y = top + 1.6;
    g.add(lbl);
    g.position.set(s.x, 0, s.z);
    scene.add(g);
    structures.set(s.id, { group: g, count: s.parts.length, name: s.name, center: new THREE.Vector3(s.x, top / 2, s.z) });
  }
  for (const [id, o] of structures) if (!seen.has(id)) { disposeStructure(o); structures.delete(id); }
}

// ------------------------------------------------------------------ weather
const PRECIP = 2200;
const rainGeo = new THREE.BufferGeometry();
const rainPos = new Float32Array(PRECIP * 6);
rainGeo.setAttribute('position', new THREE.BufferAttribute(rainPos, 3));
const rain = new THREE.LineSegments(rainGeo, new THREE.LineBasicMaterial({ color: 0xbfd0ff, transparent: true, opacity: 0.55 }));
const snowGeo = new THREE.BufferGeometry();
const snowPos = new Float32Array(PRECIP * 3);
snowGeo.setAttribute('position', new THREE.BufferAttribute(snowPos, 3));
const snow = new THREE.Points(snowGeo, new THREE.PointsMaterial({ color: 0xffffff, size: 0.45, map: haloTex, transparent: true, opacity: 0.95, depthWrite: false }));
rain.frustumCulled = snow.frustumCulled = false;
scene.add(rain, snow);
for (let i = 0; i < PRECIP; i++) {
  const x = Math.random() * 120 - 60, y = Math.random() * 50, z = Math.random() * 120 - 60;
  rainPos.set([x, y, z, x, y - 0.9, z], i * 6);
  snowPos.set([x, y, z], i * 3);
}
let env = { weather: 'clear', sky: '#3f6fd8', horizon: '#cdd8ff', ground: '#aaa4ea', fog: 0.2, clouds: 0.5 };
let flash = 0, nextFlash = 5;
let lastDaylight = 1;

function stepWeather(dt, t) {
  const w = env.weather;
  rain.visible = w === 'rain' || w === 'storm';
  snow.visible = w === 'snow';
  const cx = controls.target.x, cz = controls.target.z;
  if (rain.visible) {
    const sp = (w === 'storm' ? 45 : 32) * dt;
    for (let i = 0; i < PRECIP; i++) {
      const o = i * 6;
      rainPos[o + 1] -= sp; rainPos[o + 4] -= sp;
      if (rainPos[o + 4] < 0) {
        const x = cx + Math.random() * 120 - 60, z = cz + Math.random() * 120 - 60, y = 40 + Math.random() * 10;
        rainPos[o] = rainPos[o + 3] = x; rainPos[o + 2] = rainPos[o + 5] = z; rainPos[o + 1] = y; rainPos[o + 4] = y - 0.9;
      }
    }
    rainGeo.attributes.position.needsUpdate = true;
  }
  if (snow.visible) {
    for (let i = 0; i < PRECIP; i++) {
      const o = i * 3;
      snowPos[o + 1] -= 2.2 * dt;
      snowPos[o] += Math.sin(t + i) * 0.3 * dt;
      if (snowPos[o + 1] < 0) { snowPos[o] = cx + Math.random() * 120 - 60; snowPos[o + 2] = cz + Math.random() * 120 - 60; snowPos[o + 1] = 40 + Math.random() * 10; }
    }
    snowGeo.attributes.position.needsUpdate = true;
  }
  // Zeus's lightning
  if (w === 'storm') {
    nextFlash -= dt;
    if (nextFlash <= 0) { flash = 0.25; nextFlash = 4 + Math.random() * 10; }
  }
  if (flash > 0) flash = Math.max(0, flash - dt);
  // glow brighter at night
  const night = 1 - lastDaylight;
  for (const m of glowMats) m.emissiveIntensity = 0.5 + night * 1.6;
  for (const h of halos) h.material.opacity = Math.min(0.85, night * 0.95 + (w === 'storm' || w === 'mist' ? 0.2 : 0));
}

// ------------------------------------------------------------------ sky by time of day + world look
const C = (h) => new THREE.Color(h);
const NIGHT_TOP = C('#080b26'), NIGHT_BOT = C('#262a5a'), DUSK_BOT = C('#f2a07b'), GREY = C('#7d8296');
const groundColor = new THREE.Color('#aaa4ea');
function applyEnvironment(e) {
  if (!e) return;
  env = e;
  groundColor.set(e.ground || '#aaa4ea');
  if (ground) ground.material.color.copy(groundColor);
  const n = Math.round((e.clouds ?? 0.5) * clouds.children.length * (e.weather === 'cloudy' || e.weather === 'rain' || e.weather === 'storm' ? 1.6 : 1));
  clouds.children.forEach((c, i) => { c.visible = i < n; });
}
function applyTime(clock) {
  const d = clock.daylight;
  lastDaylight = d;
  const mins = clock.minutes;
  const w = env.weather;
  const gloom = w === 'storm' ? 0.65 : (w === 'rain' ? 0.45 : (w === 'cloudy' || w === 'snow' ? 0.25 : (w === 'mist' ? 0.3 : 0)));
  const dusk = Math.max(0, 1 - Math.abs(d - 0.18) / 0.18) * (d < 0.6 ? 1 : 0);
  const top = NIGHT_TOP.clone().lerp(C(env.sky || '#3f6fd8'), d).lerp(GREY, gloom * d);
  const bot = NIGHT_BOT.clone().lerp(C(env.horizon || '#cdd8ff'), d).lerp(DUSK_BOT, dusk * 0.6 * (1 - gloom)).lerp(GREY, gloom * 0.7 * d);
  if (flash > 0) { top.lerp(C('#ffffff'), 0.6); bot.lerp(C('#ffffff'), 0.6); }
  skyUniforms.top.value.copy(top);
  skyUniforms.bottom.value.copy(bot);
  scene.fog.color.copy(bot);
  const fog = Math.min(1, (env.fog ?? 0.2) + (w === 'mist' ? 0.55 : 0) + (w === 'snow' || w === 'rain' ? 0.15 : 0) + (w === 'storm' ? 0.25 : 0));
  scene.fog.near = 90 - fog * 80;
  scene.fog.far = 340 - fog * 250;
  stars.material.opacity = Math.max(0, 1 - d * 2.2) * (1 - gloom);
  const ang = (mins / 1440) * Math.PI * 2 - Math.PI / 2;
  sun.position.set(Math.cos(ang) * 90, Math.max(8, Math.sin(ang) * 110), Math.tan(THREE.MathUtils.degToRad(GFX.sun_tilt ?? 20)) * 110);
  sun.intensity = (0.15 + d * 1.6) * (1 - gloom * 0.7) * (GFX.sun_strength ?? 1) + (flash > 0 ? 2.5 : 0);
  hemi.intensity = (0.35 + d * 0.65) * (GFX.ambient_strength ?? 1) + (flash > 0 ? 1.5 : 0);
  shadeDay.value = d;
  cloudMat.color.copy(C('#5b5f98').lerp(C('#ffffff'), d)).lerp(GREY, gloom);
}

// ------------------------------------------------------------------ applying the gods' graphics (1.4)
const EFFECT_LOOK = {   // default colour, size, glowing?, how it moves
  fireflies: ['#fff27a', 0.55, true, 'drift'], sparkles: ['#ffffff', 0.35, true, 'twinkle'],
  embers: ['#ff8a3d', 0.32, true, 'rise'], bubbles: ['#bfe8ff', 0.45, false, 'bob'],
  petals: ['#ffb7d5', 0.5, false, 'fall'], leaves: ['#d98b2b', 0.55, false, 'fall'], dust: ['#e8dcc0', 0.22, false, 'dust'],
};
const effects = [];
const extras = new THREE.Group();   // ponds and paths
scene.add(extras);
const pondMats = [];
const gfxSeen = {};
const changed = (k, v) => { const j = JSON.stringify(v ?? null); if (gfxSeen[k] === j) return false; gfxSeen[k] = j; return true; };

function applyGraphics(g) {
  GFX = Object.assign({}, GFX, g);
  sun.color.set(GFX.sun_color || '#fff3dd');
  hemi.color.set(GFX.ambient_color || '#dfe6ff');
  if (grid) grid.visible = GFX.grid !== false;
  if (changed('shadows', GFX.shadows)) {
    sun.castShadow = GFX.shadows !== 'off';
    renderer.shadowMap.type = GFX.shadows === 'sharp' ? THREE.PCFShadowMap : THREE.PCFSoftShadowMap;
    scene.traverse((o) => { if (o.material) o.material.needsUpdate = true; });
  }
  if (changed('hills', GFX.hills) && ground) applyHills(GFX.hills || 0);
  if (changed('materials', GFX.materials) && structures.size) {
    for (const k of Object.keys(matCache)) delete matCache[k];
    glowMats.length = 0;
    for (const o of structures.values()) disposeStructure(o);
    structures.clear();
    if (state?.structures) syncStructures(state.structures);
  }
  if (changed('effects', GFX.effects)) buildEffects(GFX.effects || []);
  if (changed('extras', [GFX.ponds, GFX.paths])) buildExtras(GFX.ponds || [], GFX.paths || []);
}

function buildEffects(list) {
  for (const e of effects) { scene.remove(e.points); e.points.geometry.dispose(); e.points.material.dispose(); }
  effects.length = 0;
  for (const spec of list.slice(0, 4)) {
    const look = EFFECT_LOOK[spec.kind];
    if (!look) continue;
    const n = Math.round(80 + (spec.amount ?? 0.5) * 520);
    const pos = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) pos.set([(Math.random() * 2 - 1) * half * 1.15, 0.3 + Math.random() * 14, (Math.random() * 2 - 1) * half * 1.15], i * 3);
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    const mat = new THREE.PointsMaterial({ color: spec.color || look[0], size: look[1], map: haloTex, transparent: true, depthWrite: false,
      opacity: 0.9, blending: look[2] ? THREE.AdditiveBlending : THREE.NormalBlending });
    const points = new THREE.Points(geo, mat);
    points.frustumCulled = false;
    scene.add(points);
    effects.push({ kind: spec.kind, move: look[3], glow: look[2], points, pos, n });
  }
}

function stepEffects(dt, t) {
  const night = 1 - lastDaylight;
  const lim = half * 1.15;
  for (const e of effects) {
    const p = e.pos;
    for (let i = 0; i < e.n; i++) {
      const o = i * 3;
      if (e.move === 'drift') { p[o] += Math.sin(t * 0.7 + i) * 0.7 * dt; p[o + 2] += Math.cos(t * 0.6 + i * 1.3) * 0.7 * dt; p[o + 1] += Math.sin(t * 1.1 + i) * 0.3 * dt; }
      else if (e.move === 'rise' || e.move === 'bob') { p[o + 1] += (e.move === 'rise' ? 1.3 : 0.6) * dt; p[o] += Math.sin(t * 2 + i) * 0.3 * dt; if (p[o + 1] > 14) p[o + 1] = 0.3; }
      else if (e.move === 'fall') { p[o + 1] -= 0.8 * dt; p[o] += Math.sin(t * 1.3 + i) * 0.8 * dt; if (p[o + 1] < 0.2) p[o + 1] = 14; }
      else if (e.move === 'dust') { p[o] += 0.25 * dt; if (p[o] > lim) p[o] = -lim; }
    }
    if (e.move !== 'twinkle') e.points.geometry.attributes.position.needsUpdate = true;
    e.points.material.opacity = e.move === 'twinkle' ? 0.45 + 0.45 * Math.sin(t * 3)
      : e.kind === 'fireflies' ? 0.25 + night * 0.7 + 0.1 * Math.sin(t * 5) : 0.85;
  }
}

function buildExtras(ponds, paths) {
  for (const c of [...extras.children]) { extras.remove(c); c.geometry.dispose(); if (!pondMats.includes(c.material)) c.material.dispose(); }
  for (const m of pondMats) m.dispose();
  pondMats.length = 0;
  for (const p of ponds) {
    const mat = shadedStandard({ color: p.color || '#3d8fd1', roughness: 0.12, metalness: 0.1, transparent: true, opacity: 0.86 }, 'water');
    pondMats.push(mat);
    const m = new THREE.Mesh(new THREE.CircleGeometry(p.radius, 48), mat);
    m.rotation.x = -Math.PI / 2;
    m.position.set(p.x, 0.035, p.z);
    m.receiveShadow = true;
    extras.add(m);
  }
  for (const p of paths) {
    const [x0, z0] = p.from, [x1, z1] = p.to;
    const len = Math.hypot(x1 - x0, z1 - z0);
    const geo = new THREE.PlaneGeometry(len, p.width || 1.6);
    geo.rotateX(-Math.PI / 2);
    const m = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ color: p.color || '#d9c9a3', roughness: 0.9 }));
    m.rotation.y = Math.atan2(-(z1 - z0), x1 - x0);
    m.position.set((x0 + x1) / 2, 0.022, (z0 + z1) / 2);
    m.receiveShadow = true;
    extras.add(m);
  }
}

// which shader each target uses: the newest that compiles (and isn't too slow), else the last good one
const tested = new Map();       // hash -> null (works) or error text
const reported = new Set();
let watching = null;            // {target, hash, until, base}
function report(target, hash, ok, error) {
  const key = `${target}|${hash}|${ok}`;
  if (reported.has(key)) return;
  reported.add(key);
  fetch('/api/shader_result', { method: 'POST', headers: { 'X-Olympus': '1', 'Content-Type': 'application/json' },
    body: JSON.stringify({ target, hash, ok, error: error || '' }) }).catch(() => {});
}
function bodyFor(target, cur) {
  if (!cur) return DEFAULT_BODY[target];
  if (cur.status !== 'failed') {
    if (!tested.has(cur.hash)) tested.set(cur.hash, testShader(target, cur.code));
    const err = tested.get(cur.hash);
    if (err === null) { if (cur.status === 'untested') report(target, cur.hash, true); return cur.code; }
    report(target, cur.hash, false, err);
  }
  const lg = cur.last_good;
  if (lg && lg.code) {
    const key = 'lg:' + lg.hash;
    if (!tested.has(key)) tested.set(key, testShader(target, lg.code));
    if (tested.get(key) === null) return lg.code;
  }
  return DEFAULT_BODY[target];
}
function applyShaders(shaders) {
  for (const target of ['sky', 'water', 'ground']) {
    const cur = shaders[target];
    const body = bodyFor(target, cur);
    if (body === SHADES[target]) continue;
    SHADES[target] = body;
    if (target === 'sky') { const old = sky.material; sky.material = skyMaterial(); old.dispose(); }
    if (target === 'ground' && ground) { const old = ground.material; ground.material = shadedStandard({ color: groundColor.clone(), roughness: 0.95 }, 'ground'); old.dispose(); }
    if (target === 'water') buildExtras(GFX.ponds || [], GFX.paths || []);
    if (cur && body === cur.code) watching = { target, hash: cur.hash, until: performance.now() + 6000, base: fps };
  }
}

// speed guard: a god's shader that drags the viewer below 20 frames a second is switched off and reported
let fps = 60;
let shaderBroke = false;
renderer.debug.onShaderError = () => { shaderBroke = true; };
function watchSpeed(dt) {
  if (dt > 0 && document.visibilityState === 'visible') fps = fps * 0.95 + (1 / dt) * 0.05;
  if (!watching) return;
  const w = watching;
  const tooSlow = performance.now() > w.until && w.base >= 28 && fps < 20;
  if (shaderBroke || tooSlow) {
    shaderBroke = false;
    watching = null;
    const err = tooSlow ? `too slow: the viewer dropped to ${Math.round(fps)} frames a second` : 'it broke while drawing';
    tested.set(w.hash, err);
    report(w.target, w.hash, false, err);
    if (state?.shaders) applyShaders(state.shaders);
  } else if (performance.now() > w.until + 4000) watching = null;
}

// ------------------------------------------------------------------ selection / camera
let selected = null;
const ray = new THREE.Raycaster();
const ndc = new THREE.Vector2();
let downAt = null;
renderer.domElement.addEventListener('pointerdown', (e) => { downAt = [e.clientX, e.clientY]; });
renderer.domElement.addEventListener('pointerup', (e) => {
  if (!downAt || Math.hypot(e.clientX - downAt[0], e.clientY - downAt[1]) > 5) return;
  ndc.set((e.clientX / innerWidth) * 2 - 1, -(e.clientY / innerHeight) * 2 + 1);
  ray.setFromCamera(ndc, camera);
  const hit = ray.intersectObjects(pickables, false)[0];
  if (hit) select(hit.object.userData.agentId);
});
$('godclose').onclick = () => select(null);

let flyTo = null;
function select(id) {
  selected = id;
  filter = id || 'all';
  renderFilters();
  refreshFeed();
  renderGodCard();
}
function focusOn(v) { flyTo = v.clone(); }

// ------------------------------------------------------------------ data
let state = null;
let rev = null;
let lastStatus = null;

async function poll() {
  try {
    const r = await fetch('/api/state' + (rev !== null ? `?rev=${rev}` : ''), { cache: 'no-store' });
    const s = await r.json();
    if (s.half && s.half !== half) buildGround(s.half);
    if (s.graphics) applyGraphics(s.graphics);
    if (s.structures) { syncStructures(s.structures); state && (state.structures = s.structures); }
    s.structures = s.structures || state?.structures || [];
    rev = s.rev;
    state = s;
    for (const a of s.agents) {
      if (!gods.has(a.id)) gods.set(a.id, makeGod(a));
      updateGodVisual(gods.get(a.id), a);
    }
    applyEnvironment(s.environment);
    if (s.shaders) applyShaders(s.shaders);
    applyTime(s.clock);
    renderHud(s);
    renderGodCard();
    if (!filtersBuilt) renderFilters();
    if (tab === 'places') renderPlaces();
    if (tab === 'inventions') renderInventions();
    renderReqCount();
    if (tab === 'requests') renderRequests();
  } catch (e) {
    $('status').innerHTML = '<b>Can’t reach the world.</b> Is the black Olympus window still open?';
  }
}

function renderHud(s) {
  const st = s.status;
  const wx = s.environment && s.environment.weather !== 'clear' ? ` · ${s.environment.weather}` : '';
  $('clock').textContent = `Day ${s.clock.day} · ${s.clock.time}${wx}`;
  let line;
  if (s.paused) line = '<b>Paused.</b> Time has stopped.';
  else if (st.thinking) line = `<b>${esc(st.thinking)}</b> is thinking…`;
  else line = `${s.agents.length} gods · ${s.structure_count} places built`;
  if (st.mode === 'fake') line += ' · <b>test mode (no AI)</b>';
  $('status').innerHTML = line;
  $('usage').innerHTML =
    `Local thoughts today <b>${st.local_used}</b><br>` +
    `Gemini <b>${st.gemini ? `${st.gemini_used}/${st.gemini_cap}` : 'off'}</b> · Web reads <b>${st.web_used}/${st.web_cap}</b>` +
    `<div class="verline">v${esc(st.version)} · <button class="linkbtn" id="chkupd">${checking ? 'checking…' : 'check for updates'}</button>${updMsg ? ' · ' + esc(updMsg) : ''}</div>`;
  $('chkupd').onclick = checkUpdates;
  renderUpdate(st.update);
  const err = $('error');
  if (st.last_error) { err.hidden = false; err.textContent = st.last_error; } else err.hidden = true;
  const pb = $('pause');
  pb.textContent = s.paused ? 'Resume' : 'Pause';
  pb.classList.toggle('on', s.paused);
  lastStatus = st;
}

function renderGodCard() {
  const card = $('godcard');
  if (!selected || !state) { card.hidden = true; return; }
  const a = state.agents.find((x) => x.id === selected);
  if (!a) { card.hidden = true; return; }
  card.hidden = false;
  $('gdot').style.background = a.color;
  $('gname').textContent = a.name;
  $('gtitle').textContent = a.title;
  $('gstatus').textContent = STATUS_WORD[a.status] || a.status || 'idle';
  if (!STATUS_WORD[a.status] && a.status === 'idle') $('gstatus').textContent = 'standing still';
  $('genergy').style.width = Math.max(2, a.energy) + '%';
  $('ggoal').textContent = a.goal || '—';
  $('gthought').textContent = a.thought ? `“${a.thought}”` : '—';
  $('gprojrow').hidden = !a.project;
  if (a.project) $('gproject').textContent = `${a.project.name} — ${a.project.total - a.project.left}/${a.project.total} parts built`;
  $('gselfrow').hidden = !a.summary;
  $('gsummary').textContent = a.summary || '';
  $('ginterests').innerHTML = (a.interests || []).map((i) => `<span class="chip">${esc(i)}</span>`).join('');
}

// ------------------------------------------------------------------ panel
let tab = 'events';
let filter = 'all';
let filtersBuilt = false;
document.querySelectorAll('.tabs button').forEach((b) => b.onclick = () => {
  tab = b.dataset.tab;
  document.querySelectorAll('.tabs button').forEach((x) => x.classList.toggle('on', x === b));
  refreshFeed();
});
$('pause').onclick = async () => {
  await fetch(state?.paused ? '/api/resume' : '/api/pause', { method: 'POST', headers: { 'X-Olympus': '1' } });
  poll();
};

function renderFilters() {
  if (!state) return;
  filtersBuilt = true;
  const chips = [`<button class="chip ${filter === 'all' ? 'on' : ''}" data-f="all">Everyone</button>`]
    .concat(state.agents.map((a) => `<button class="chip ${filter === a.id ? 'on' : ''}" data-f="${a.id}"><span class="dot" style="background:${a.color}"></span>${esc(a.name)}</button>`));
  $('filters').innerHTML = chips.join('');
  $('filters').querySelectorAll('.chip').forEach((c) => c.onclick = () => {
    const f = c.dataset.f;
    selected = f === 'all' ? null : f;
    filter = f;
    renderFilters(); refreshFeed(); renderGodCard();
  });
}

const nameOf = (id) => state?.agents.find((a) => a.id === id)?.name || (id ? id : 'The world');
const colorOf = (id) => state?.agents.find((a) => a.id === id)?.color || '#9aa0c8';
const meta = (i, badge = '') => `<div class="meta"><span class="dot" style="background:${colorOf(i.agent)}"></span><span class="who">${esc(nameOf(i.agent))}</span><span>Day ${i.day} · ${esc(i.time)}</span>${badge ? `<span class="badge">${badge}</span>` : ''}</div>`;

async function refreshFeed() {
  if (tab === 'places') return renderPlaces();
  if (tab === 'inventions') return renderInventions();
  if (tab === 'requests') { reqSig = ''; return renderRequests(); }
  const q = new URLSearchParams({ kind: tab });
  if (filter !== 'all') q.set('agent', filter);
  let items = [];
  try { items = await (await fetch('/api/journal?' + q, { cache: 'no-store' })).json(); } catch { return; }
  const feed = $('feed');
  const keepScroll = feed.scrollTop;
  if (!items.length) {
    const msg = { events: 'Nothing has happened yet.', diaries: 'No diary entries yet. Each god reflects once a day, and may write whenever they like.', searches: 'Nobody has looked anything up yet.', talks: 'No conversations yet.' }[tab];
    feed.innerHTML = `<div class="empty">${msg}</div>`;
    return;
  }
  if (tab === 'events') {
    feed.innerHTML = items.map((i) => `<div class="ev"><span class="when">Day ${i.day} ${esc(i.time)}</span><span class="dot" style="background:${colorOf(i.agent)}"></span><span>${esc(i.text)}</span></div>`).join('');
  } else if (tab === 'diaries') {
    feed.innerHTML = items.map((i) => `<div class="card">${meta(i, i.kind === 'reflection' ? 'nightly reflection' : 'diary')}<div class="body">${esc(i.text)}</div></div>`).join('');
  } else if (tab === 'searches') {
    feed.innerHTML = items.map((i) => `<div class="card ${i.ok ? '' : 'failed'}">${meta(i, 'searching')}
      <div class="look">looking up <b>“${esc(i.query)}”</b></div>
      ${i.title ? `<div class="look">reading: <a href="${esc(i.url)}" target="_blank" rel="noopener">${esc(i.title)}</a></div>` : ''}
      ${i.reflection ? `<div class="quote">“${esc(i.reflection)}”</div>` : ''}</div>`).join('');
  } else if (tab === 'talks') {
    feed.innerHTML = items.map((i) => `<div class="card">${meta(i, i.to ? 'to ' + esc(nameOf(i.to)) : 'aloud')}<div class="body">“${esc(i.text)}”</div></div>`).join('');
  }
  feed.scrollTop = keepScroll;
}

function renderInventions() {
  const feed = $('feed');
  let list = (state?.designs || []).slice();
  if (filter !== 'all') list = list.filter((d) => d.inventor === filter);
  const e = state?.environment;
  const look = e && e.by ? `<div class="card"><div class="meta"><span class="dot" style="background:${colorOf(e.by)}"></span><span class="who">${esc(nameOf(e.by))}</span><span class="badge">shaped the world</span></div>
    <div class="look">weather <b>${esc(e.weather)}</b> · <span class="swatch" style="background:${esc(e.sky)}"></span> sky · <span class="swatch" style="background:${esc(e.horizon)}"></span> horizon · <span class="swatch" style="background:${esc(e.ground)}"></span> ground</div>
    ${e.reason ? `<div class="quote">“${esc(e.reason)}”</div>` : ''}</div>` : '';
  const g = state?.graphics, sh = state?.shaders || {};
  const shLine = Object.entries(sh).map(([t, v]) => `<div class="look">${esc(t)} shader <b>“${esc(v.name)}”</b> by ${esc(nameOf(v.by))}: ${
    v.status === 'ok' ? 'on screen' : v.status === 'untested' ? 'waiting for the viewer to test it' : 'didn’t work (' + esc(v.error) + ')'}${
    v.status === 'failed' && v.last_good ? ` · showing “${esc(v.last_good.name)}” instead` : ''}</div>`).join('');
  const gfxCard = g && (g.by || shLine) ? `<div class="card"><div class="meta">${g.by ? `<span class="dot" style="background:${colorOf(g.by)}"></span><span class="who">${esc(nameOf(g.by))}</span>` : ''}<span class="badge">graphics</span></div>
    <div class="look">sun <span class="swatch" style="background:${esc(g.sun_color)}"></span> ×${g.sun_strength} · light <span class="swatch" style="background:${esc(g.ambient_color)}"></span> ×${g.ambient_strength} · shadows ${esc(g.shadows)}${g.hills ? ' · hills ' + g.hills : ''}${g.grid === false ? ' · no grid' : ''}</div>
    ${(g.effects || []).length ? `<div class="look">effects: ${g.effects.map((e) => esc(e.kind)).join(', ')}</div>` : ''}
    ${(g.ponds || []).length || (g.paths || []).length ? `<div class="look">${(g.ponds || []).length} pond(s) · ${(g.paths || []).length} path(s)</div>` : ''}
    ${Object.keys(g.materials || {}).length ? `<div class="look">restyled: ${Object.keys(g.materials).map(esc).join(', ')}</div>` : ''}
    ${shLine}${g.reason ? `<div class="quote">“${esc(g.reason)}”</div>` : ''}</div>` : '';
  if (!list.length) { feed.innerHTML = look + gfxCard + '<div class="empty">No inventions yet. When a god invents something (a column, a lamp, a fountain), anyone can build it, and it shows up here.</div>'; return; }
  list.sort((a, b) => (b.uses - a.uses) || (b.created?.real || '').localeCompare(a.created?.real || ''));
  feed.innerHTML = look + gfxCard + list.map((d) => `<div class="card">
    <div class="meta"><span class="dot" style="background:${colorOf(d.inventor)}"></span><span class="who">${esc(d.name)}</span><span class="badge">used ${d.uses}×</span></div>
    <div class="look">invented by ${esc(nameOf(d.inventor))} · ${d.parts} parts${d.version > 1 ? ` · version ${d.version}` : ''}</div>
    ${d.description ? `<div class="quote">${esc(d.description)}</div>` : ''}</div>`).join('');
}

function renderPlaces() {
  const feed = $('feed');
  let list = (state?.structures || []).slice();
  if (filter !== 'all') list = list.filter((s) => s.builder === filter || (s.contributors || []).includes(filter));
  if (!list.length) { feed.innerHTML = '<div class="empty">The plain is still empty. Whatever appears here, they decided to build.</div>'; return; }
  list.sort((a, b) => (b.updated?.real || '').localeCompare(a.updated?.real || ''));
  feed.innerHTML = list.map((s) => `<div class="card place" data-id="${s.id}">
    <div class="meta"><span class="dot" style="background:${colorOf(s.builder)}"></span><span class="who">${esc(s.name)}</span><span class="badge">${s.parts.length} parts</span></div>
    <div class="look">built by ${esc(nameOf(s.builder))}${(s.contributors || []).length > 1 ? ' with ' + s.contributors.filter((c) => c !== s.builder).map(nameOf).map(esc).join(', ') : ''}</div>
    ${s.purpose ? `<div class="quote">${esc(s.purpose)}</div>` : ''}</div>`).join('');
  feed.querySelectorAll('.place').forEach((el) => el.onclick = () => {
    const o = structures.get(el.dataset.id);
    if (o) { selected = null; renderGodCard(); focusOn(o.center); }
  });
}

// ------------------------------------------------------------------ requests (1.4)
// When a god needs something they can't make, they ask you (the Watcher). You answer here;
// "Copy for Claude" puts the request on your clipboard so you can paste it to Claude to have it built.
let reqSig = '';
const reqNotes = {};
const REQ_BADGE = { open: ['waiting for you', 'wait'], promised: ['you said yes', 'yes'], given: ['given', 'yes'], declined: ['you said no', 'no'] };
function renderReqCount() {
  const n = (state?.requests || []).filter((r) => r.status === 'open').length;
  const el = $('reqcount');
  el.hidden = !n;
  el.textContent = n;
}
function reqText(r) {
  const who = nameOf(r.by);
  return `Olympus World request from ${who} (Day ${r.made?.day}, ${r.made?.time}):\n` +
    `${who} wants: ${r.what}\n` + (r.why ? `Why: ${r.why}\n` : '') +
    `Please add this to Olympus World for ${who}.`;
}
async function copyText(t) {
  try { await navigator.clipboard.writeText(t); return true; } catch { /* fall back below */ }
  const ta = document.createElement('textarea');
  ta.value = t; document.body.appendChild(ta); ta.select();
  let ok = false;
  try { ok = document.execCommand('copy'); } catch { ok = false; }
  ta.remove();
  return ok;
}
function renderRequests() {
  const feed = $('feed');
  if (feed.contains(document.activeElement) && document.activeElement.tagName === 'TEXTAREA') return;   // don't wipe a note you're typing
  let list = (state?.requests || []).slice();
  if (filter !== 'all') list = list.filter((r) => r.by === filter);
  const sig = JSON.stringify(list.map((r) => [r.id, r.status, r.answer])) + filter;
  if (sig === reqSig) return;
  reqSig = sig;
  const order = { open: 0, promised: 1, given: 2, declined: 2 };
  list.sort((a, b) => (order[a.status] - order[b.status]) ||
    (a.status === 'open' ? (a.made?.real || '').localeCompare(b.made?.real || '') : (b.made?.real || '').localeCompare(a.made?.real || '')));
  const intro = `<div class="card intro">When a god needs or wants something they can't make themselves, they ask you here.
    Say <b>yes</b>, then press <b>Copy for Claude</b> and paste it to Claude to have it built.
    Press <b>Done</b> once it's installed so they know they have it.</div>`;
  if (!list.length) { feed.innerHTML = intro + '<div class="empty">No requests yet.</div>'; return; }
  feed.innerHTML = intro + list.map((r) => {
    const [label, cls] = REQ_BADGE[r.status] || [r.status, ''];
    const live = r.status === 'open' || r.status === 'promised';
    const ans = r.answered ? `<div class="ans">You ${r.status === 'given' ? 'gave it' : r.status === 'promised' ? 'said yes' : 'said no'} on Day ${r.answered.day} · ${esc(r.answered.time)}${r.answer ? `: <i>“${esc(r.answer)}”</i>` : ''}</div>` : '';
    return `<div class="card req ${r.status}" data-id="${esc(r.id)}">
      <div class="meta"><span class="dot" style="background:${colorOf(r.by)}"></span><span class="who">${esc(nameOf(r.by))}</span><span>asks for</span><span class="badge ${cls}">${label}</span></div>
      <div class="what"><b>${esc(r.what)}</b></div>
      ${r.why ? `<div class="quote">“${esc(r.why)}”</div>` : ''}
      <div class="when2">Day ${r.made?.day} · ${esc(r.made?.time || '')}</div>
      ${ans}
      ${live ? `<textarea placeholder="Note to ${esc(nameOf(r.by))} (optional)" data-note="${esc(r.id)}">${esc(reqNotes[r.id] || '')}</textarea>
      <div class="acts">
        ${r.status === 'open' ? `<button class="btn yes" data-ans="promised">Yes, I'll get it</button>` : ''}
        <button class="btn" data-ans="given">Done, it's theirs</button>
        <button class="btn" data-ans="declined">No</button>
        <button class="btn copy" data-copy="1">Copy for Claude</button>
      </div>` : ''}
    </div>`;
  }).join('');
  feed.querySelectorAll('textarea[data-note]').forEach((t) => t.oninput = () => { reqNotes[t.dataset.note] = t.value; });
  feed.querySelectorAll('.card.req').forEach((card) => {
    const r = list.find((x) => x.id === card.dataset.id);
    card.querySelectorAll('[data-ans]').forEach((b) => b.onclick = async () => {
      b.disabled = true;
      try {
        await fetch('/api/requests/answer', { method: 'POST', headers: { 'X-Olympus': '1', 'Content-Type': 'application/json' },
          body: JSON.stringify({ id: r.id, status: b.dataset.ans, note: reqNotes[r.id] || '' }) });
        delete reqNotes[r.id];
      } catch { b.disabled = false; }
      reqSig = ''; poll();
    });
    const cb = card.querySelector('[data-copy]');
    if (cb) cb.onclick = async () => { cb.textContent = (await copyText(reqText(r))) ? 'Copied!' : 'Couldn’t copy'; setTimeout(() => { cb.textContent = 'Copy for Claude'; }, 1800); };
  });
}

// ------------------------------------------------------------------ updates
let checking = false, updMsg = '', updating = false, updVersionBefore = null;
const post = (url) => fetch(url, { method: 'POST', headers: { 'X-Olympus': '1' } }).then((r) => r.json());
async function checkUpdates() {
  checking = true; updMsg = ''; poll();
  try {
    const u = await post('/api/update/check');
    updMsg = u.error ? `couldn't check: ${u.error}` : (u.available ? '' : 'you have the latest');
  } catch { updMsg = "couldn't check"; }
  checking = false; poll();
}
function renderUpdate(u) {
  const b = $('updbtn');
  const avail = u && u.available;
  b.hidden = !avail || updating;
  if (avail) b.textContent = `Update to ${avail.version}`;
  if (updating) {
    $('updlog').hidden = false;
    $('updlog').textContent = (u && u.log && u.log.length ? u.log.join('\n') : 'Starting…');
    if (u && u.error && !u.installing) {
      $('updlog').textContent += `\n\nThe update didn't install. Your world is still running on the old version.`;
      $('updgo').hidden = true; $('updlater').textContent = 'Close'; updating = false;
    }
  }
}
$('updbtn').onclick = () => {
  const a = state?.status?.update?.available;
  if (!a) return;
  $('updtitle').textContent = `Olympus World ${a.version}`;
  $('updnotes').textContent = a.notes || 'A new version is ready.';
  $('updlog').hidden = true; $('updgo').hidden = false; $('updgo').disabled = false; $('updlater').textContent = 'Later';
  $('updmodal').hidden = false;
};
$('updlater').onclick = () => { $('updmodal').hidden = true; };
$('updgo').onclick = async () => {
  updating = true; updVersionBefore = state?.status?.version;
  $('updgo').disabled = true; $('updlater').textContent = 'Close';
  $('updlog').hidden = false; $('updlog').textContent = 'Starting…';
  try { await post('/api/update/install'); } catch {}
  // wait for the world to come back on the new version, then reload the page
  const t0 = Date.now();
  const wait = setInterval(async () => {
    try {
      const s = await (await fetch('/api/state', { cache: 'no-store' })).json();
      renderUpdate(s.status.update);
      if (s.status.version !== updVersionBefore) { clearInterval(wait); $('updlog').textContent += '\nDone. Reloading…'; setTimeout(() => location.reload(), 800); }
      if (!updating) clearInterval(wait);
    } catch { $('updlog').textContent = ($('updlog').textContent.split('\nRestarting')[0]) + '\nRestarting the world…'; }
    if (Date.now() - t0 > 120000) { clearInterval(wait); $('updlog').textContent += '\nThis is taking a while. If the world doesn\'t come back, double-click the Olympus World icon.'; }
  }, 1500);
};

// ------------------------------------------------------------------ loop
const clock = new THREE.Clock();
function frame() {
  const dt = Math.min(0.1, clock.getDelta());
  const t = clock.elapsedTime;
  for (const o of gods.values()) {
    const a = o.data;
    const g = o.group;
    const k = Math.min(1, dt * 4);
    const nx = g.position.x + (a.x - g.position.x) * k;
    const nz = g.position.z + (a.z - g.position.z) * k;
    const moving = Math.hypot(nx - g.position.x, nz - g.position.z) > 0.002;
    if (moving) g.rotation.y = Math.atan2(nx - g.position.x, nz - g.position.z);
    g.position.x = nx; g.position.z = nz;
    o.body.position.y = moving ? Math.abs(Math.sin(t * 9)) * 0.12 : 0;
    const resting = a.status === 'resting';
    o.body.rotation.z += ((resting ? Math.PI / 2 : 0) - o.body.rotation.z) * k;
    o.body.position.y += resting ? 0.35 : 0;
    o.halo.rotation.z += dt * (a.status === 'thinking' ? 6 : 0.6);
    o.halo.material.emissiveIntensity = a.status === 'thinking' ? 1.4 + Math.sin(t * 8) * 0.8 : 1.0;
  }
  stepWeather(dt, t);
  shadeTime.value = t;
  stepEffects(dt, t);
  watchSpeed(dt);
  if (state) applyTime(state.clock);
  for (const c of clouds.children) { c.position.x += dt * 1.2; if (c.position.x > 180) c.position.x = -180; }
  if (selected && gods.has(selected)) flyTo = gods.get(selected).group.position.clone().setY(1);
  if (flyTo) {
    const delta = flyTo.clone().sub(controls.target).multiplyScalar(Math.min(1, dt * 3));
    controls.target.add(delta);
    camera.position.add(delta);
    if (!selected && delta.length() < 0.01) flyTo = null;
  }
  sun.target.position.copy(controls.target);
  controls.update();
  renderer.render(scene, camera);
  requestAnimationFrame(frame);
}

addEventListener('resize', () => {
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
});

await poll();
renderFilters();
refreshFeed();
setInterval(poll, 1000);
setInterval(() => { if (tab !== 'places' && tab !== 'inventions' && tab !== 'requests') refreshFeed(); }, 3000);
frame();
