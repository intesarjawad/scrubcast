import {
  BLANK_GLYPH,
  FAN_INK,
  FLOOR_GLYPH,
  GHOST_GLYPH,
  type Layout,
  MAX_MEMBERS,
  MAX_PLACES,
  PAGE_GLYPH,
  type Renderer,
  TICKER_GLYPH,
} from "./sheet-types";

const MAX_FANS = 8;

// The press sheet is a float target that adds ink shares: black in red, the alarm ink in green.
// A word every page prints sums to 1; a figure 24 pages print sums to 24/82.
const glyphVertex = `#version 300 es
layout(location = 0) in vec2 a_corner;
layout(location = 1) in vec4 a_at;
layout(location = 2) in vec4 a_to;
layout(location = 3) in vec4 a_uv;
layout(location = 4) in vec4 a_meta;
uniform vec2 u_view;
uniform vec2 u_atlas;
uniform float u_ink[${MAX_MEMBERS}];
uniform float u_pages;
uniform float u_fan[${MAX_FANS}];
uniform vec4 u_ghost[${MAX_PLACES / 4}];
out vec2 v_uv;
out float v_alpha;
out float v_red;
void main() {
  float member = a_meta.x;
  float kind = a_meta.y;
  vec4 rect = a_at;
  float ink = u_ink[int(member)];
  float alpha;
  if (kind == ${TICKER_GLYPH}.0) {
    alpha = abs(member - (u_pages - 1.0)) < 0.5 ? 1.0 : 0.0;
  } else if (kind == ${BLANK_GLYPH}.0) {
    alpha = ink > 0.0 ? 0.0 : a_meta.z;
  } else if (kind == ${FLOOR_GLYPH}.0) {
    alpha = ink > 0.0 ? a_meta.z : 0.0;
  } else if (kind <= ${GHOST_GLYPH}.0) {
    int place = int(${GHOST_GLYPH}.0 - kind + 0.5);
    alpha = min(1.0, ink * a_meta.z) * u_ghost[place / 4][place % 4];
  } else if (kind == ${PAGE_GLYPH}.0) {
    // A page glyph carries its weight where a fan copy carries its rank.
    alpha = min(1.0, ink * a_meta.z);
  } else {
    // Copies rise from the axis in value order: the lowest member first.
    float p = clamp(u_fan[int(kind)] * 1.6 - a_meta.z * 0.6, 0.0, 1.0);
    p = 1.0 - pow(1.0 - p, 3.0);
    rect = mix(a_at, a_to, p);
    alpha = ink > 0.0 ? ${FAN_INK} * smoothstep(0.0, 0.25, p) : 0.0;
  }
  vec2 clip = (rect.xy + a_corner * rect.zw) / u_view * 2.0 - 1.0;
  gl_Position = alpha > 0.0 ? vec4(clip.x, -clip.y, 0.0, 1.0) : vec4(2.0, 2.0, 2.0, 1.0);
  v_uv = (a_uv.xy + a_corner * a_uv.zw) / u_atlas;
  v_alpha = alpha;
  v_red = a_meta.w;
}`;

const glyphFragment = `#version 300 es
precision highp float;
uniform sampler2D u_tex;
in vec2 v_uv;
in float v_alpha;
in float v_red;
out vec4 colour;
void main() {
  float c = texture(u_tex, v_uv).a * v_alpha;
  colour = vec4(c * (1.0 - v_red), c * v_red, 0.0, 0.0);
}`;

const pageVertex = `#version 300 es
layout(location = 0) in vec2 a_corner;
out vec2 v_uv;
void main() {
  v_uv = vec2(a_corner.x, 1.0 - a_corner.y);
  gl_Position = vec4(a_corner * 2.0 - 1.0, 0.0, 1.0);
}`;

// The shared words, laid once at the share of pages landed.
const pageFragment = `#version 300 es
precision highp float;
uniform sampler2D u_page;
uniform float u_share;
in vec2 v_uv;
out vec4 colour;
void main() { colour = vec4(texture(u_page, v_uv).a * u_share, 0.0, 0.0, 0.0); }`;

const noise = `
float hash(vec2 p) {
  p = fract(p * vec2(123.34, 456.21));
  p += dot(p, p + 45.32);
  return fract(p.x * p.y);
}
float noise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash(i), hash(i + vec2(1, 0)), u.x), mix(hash(i + vec2(0, 1)), hash(i + vec2(1, 1)), u.x), u.y);
}
float fbm(vec2 p) {
  float sum = 0.0;
  float amp = 0.5;
  for (int i = 0; i < 4; i++) { sum += amp * noise(p); p *= 2.03; amp *= 0.5; }
  return sum;
}`;

const finalVertex = `#version 300 es
layout(location = 0) in vec2 a_corner;
void main() { gl_Position = vec4(a_corner * 2.0 - 1.0, 0.0, 1.0); }`;

// Ink spreads a little into the fibre around a stroke and starves on the paper's tooth where
// it is thin; a full share stays solid.
const finalFragment = `#version 300 es
precision highp float;
uniform sampler2D u_sheet;
uniform vec2 u_size;
uniform float u_dpr;
uniform vec3 u_paper;
uniform vec3 u_inkColour;
uniform vec3 u_alarmColour;
out vec4 colour;
${noise}
vec2 share(vec2 uv) { return min(texture(u_sheet, uv).rg, vec2(1.0)); }
void main() {
  vec2 uv = gl_FragCoord.xy / u_size;
  vec2 p = gl_FragCoord.xy / u_dpr;
  float tooth = fbm(p * 0.9);
  float cloud = fbm(p * 0.011);
  vec2 d0 = share(uv);
  vec2 o = vec2(0.5 * u_dpr) / u_size;
  vec2 ring = share(uv + vec2(o.x, 0.0)) + share(uv - vec2(o.x, 0.0)) +
    share(uv + vec2(0.0, o.y)) + share(uv - vec2(0.0, o.y)) +
    share(uv + o * 0.7) + share(uv - o * 0.7) +
    share(uv + vec2(o.x, -o.y) * 0.7) + share(uv + vec2(-o.x, o.y) * 0.7);
  vec2 cover = max(d0, ring / 8.0 * (0.55 + 0.2 * (cloud - 0.5)));
  cover *= 1.0 - 0.35 * smoothstep(0.55, 0.8, tooth) * (1.0 - d0);
  // Dot gain: thin ink spreads as it lands, 1 - (1 - c)^2, the same curve the 2D still draws.
  cover = 1.0 - (1.0 - cover) * (1.0 - cover);
  vec3 paper = u_paper * (1.0 + 0.05 * (tooth - 0.5) + 0.04 * (cloud - 0.5));
  colour = vec4(mix(mix(paper, u_alarmColour, cover.y), u_inkColour, cover.x), 1.0);
}`;

function rgb(hex: string): [number, number, number] {
  const match = /^#([\da-f]{2})([\da-f]{2})([\da-f]{2})$/i.exec(hex);
  if (!match) return [0, 0, 0];
  return [1, 2, 3].map((index) => Number.parseInt(match[index] ?? "0", 16) / 255) as [
    number,
    number,
    number,
  ];
}

function compile(gl: WebGL2RenderingContext, vertex: string, fragment: string) {
  const program = gl.createProgram();
  for (const [type, source] of [
    [gl.VERTEX_SHADER, vertex],
    [gl.FRAGMENT_SHADER, fragment],
  ] as const) {
    const shader = gl.createShader(type);
    if (!shader) throw new Error("Shader allocation failed");
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS))
      throw new Error(gl.getShaderInfoLog(shader) ?? "Shader did not compile");
    gl.attachShader(program, shader);
  }
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS))
    throw new Error(gl.getProgramInfoLog(program) ?? "Program did not link");
  const uniforms = new Map<string, WebGLUniformLocation | null>();
  const at = (name: string) => {
    if (!uniforms.has(name)) uniforms.set(name, gl.getUniformLocation(program, name));
    return uniforms.get(name) ?? null;
  };
  return { program, at };
}

function texture(gl: WebGL2RenderingContext, source: HTMLCanvasElement, mipmaps: boolean) {
  const handle = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, handle);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, source);
  if (mipmaps) gl.generateMipmap(gl.TEXTURE_2D);
  gl.texParameteri(
    gl.TEXTURE_2D,
    gl.TEXTURE_MIN_FILTER,
    mipmaps ? gl.LINEAR_MIPMAP_LINEAR : gl.LINEAR,
  );
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  return handle;
}

export function createRenderer(canvas: HTMLCanvasElement, layout: Layout): Renderer | null {
  if (layout.members > MAX_MEMBERS || layout.places.length > MAX_PLACES) return null;
  const context = canvas.getContext("webgl2", {
    antialias: false,
    premultipliedAlpha: true,
    alpha: false,
  });
  if (!context) return null;
  const device = context.getExtension("WEBGL_debug_renderer_info");
  const name: unknown = context.getParameter(device?.UNMASKED_RENDERER_WEBGL ?? context.RENDERER);
  // Software GL competes with interaction on the CPU and can stall context teardown.
  if (
    (typeof name === "string" && /SwiftShader|llvmpipe|Software Rasterizer/i.test(name)) ||
    !context.getExtension("EXT_color_buffer_float")
  ) {
    context.getExtension("WEBGL_lose_context")?.loseContext();
    return null;
  }
  const gl: WebGL2RenderingContext = context;
  canvas.width = Math.ceil(layout.width * layout.dpr);
  canvas.height = Math.ceil(layout.height * layout.dpr);
  const glyph = compile(gl, glyphVertex, glyphFragment);
  const page = compile(gl, pageVertex, pageFragment);
  const final = compile(gl, finalVertex, finalFragment);

  const vao = gl.createVertexArray();
  gl.bindVertexArray(vao);
  const corners = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, corners);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([0, 0, 1, 0, 0, 1, 1, 1]), gl.STATIC_DRAW);
  gl.enableVertexAttribArray(0);
  gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
  const data = new Float32Array(layout.glyphs.length * 16);
  for (const [index, item] of layout.glyphs.entries()) {
    data.set(
      [
        ...[item.at.x, item.at.y, item.at.w, item.at.h],
        ...[item.to.x, item.to.y, item.to.w, item.to.h],
        ...[item.uv.x, item.uv.y, item.uv.w, item.uv.h],
        ...[item.member, item.kind, item.kind < 0 ? item.weight : item.rank, item.red ? 1 : 0],
      ],
      index * 16,
    );
  }
  const instances = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, instances);
  gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
  for (let attribute = 1; attribute <= 4; attribute++) {
    gl.enableVertexAttribArray(attribute);
    gl.vertexAttribPointer(attribute, 4, gl.FLOAT, false, 64, (attribute - 1) * 16);
    gl.vertexAttribDivisor(attribute, 1);
  }

  const pageTexture = texture(gl, layout.page, false);
  const atlasTexture = texture(gl, layout.atlas, true);
  const sheetTexture = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, sheetTexture);
  gl.texStorage2D(gl.TEXTURE_2D, 1, gl.RGBA16F, canvas.width, canvas.height);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  const press = gl.createFramebuffer();
  gl.bindFramebuffer(gl.FRAMEBUFFER, press);
  gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, sheetTexture, 0);
  if (gl.checkFramebufferStatus(gl.FRAMEBUFFER) !== gl.FRAMEBUFFER_COMPLETE) {
    gl.getExtension("WEBGL_lose_context")?.loseContext();
    return null;
  }

  const paper = rgb(layout.paper);
  const ink = rgb(layout.ink);
  const alarm = rgb(layout.alarm);
  const fans = new Float32Array(MAX_FANS);
  const inks = new Float32Array(MAX_MEMBERS);
  const ghosts = new Float32Array(MAX_PLACES);

  return {
    draw(frame) {
      gl.bindFramebuffer(gl.FRAMEBUFFER, press);
      gl.viewport(0, 0, canvas.width, canvas.height);
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.enable(gl.BLEND);
      gl.blendFunc(gl.ONE, gl.ONE);
      // Registered pages print the same words in the same place, so their shares add in one pass.
      gl.useProgram(page.program);
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, pageTexture);
      gl.uniform1i(page.at("u_page"), 0);
      gl.uniform1f(page.at("u_share"), frame.share);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);

      gl.useProgram(glyph.program);
      gl.bindTexture(gl.TEXTURE_2D, atlasTexture);
      gl.uniform1i(glyph.at("u_tex"), 0);
      gl.uniform2f(glyph.at("u_view"), layout.width, layout.height);
      gl.uniform2f(
        glyph.at("u_atlas"),
        layout.atlas.width / layout.dpr,
        layout.atlas.height / layout.dpr,
      );
      inks.set(frame.inks);
      gl.uniform1fv(glyph.at("u_ink"), inks);
      gl.uniform1f(glyph.at("u_pages"), frame.pages);
      fans.fill(0);
      fans.set(frame.fan.slice(0, MAX_FANS));
      gl.uniform1fv(glyph.at("u_fan"), fans);
      ghosts.fill(1);
      ghosts.set(frame.ghost.slice(0, MAX_PLACES));
      gl.uniform4fv(glyph.at("u_ghost"), ghosts);
      gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, layout.glyphs.length);

      gl.bindFramebuffer(gl.FRAMEBUFFER, null);
      gl.disable(gl.BLEND);
      gl.useProgram(final.program);
      gl.bindTexture(gl.TEXTURE_2D, sheetTexture);
      gl.uniform1i(final.at("u_sheet"), 0);
      gl.uniform2f(final.at("u_size"), canvas.width, canvas.height);
      gl.uniform1f(final.at("u_dpr"), layout.dpr);
      gl.uniform3f(final.at("u_paper"), ...paper);
      gl.uniform3f(final.at("u_inkColour"), ...ink);
      gl.uniform3f(final.at("u_alarmColour"), ...alarm);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    },
    dispose() {
      gl.getExtension("WEBGL_lose_context")?.loseContext();
    },
  };
}
