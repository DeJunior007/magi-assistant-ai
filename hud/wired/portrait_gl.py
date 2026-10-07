"""Retrato da Condessa na GPU (OpenGL fora da tela): malhas que entortam e pós-processamento.

O ``PartsPortrait`` calcula o movimento (respiração, olhar, inclinação, balanço) e monta uma lista
de ``GLOp`` — cada camada com a mesma transformação do desenho em CPU e um tipo de deformação. Aqui
cada camada vira uma malha texturizada:

- ``HAIR``: a raiz fica presa e a ponta ondula com atraso (onda que desce pela mecha) e com a
  inércia do movimento da cabeça (``drag``). A maria-chiquinha e a ponta dela usam a mesma raiz,
  então a curva é contínua e não aparece emenda.
- ``BREATH``: o peito incha e desincha (deformação, não translação do bloco).
- ``IRIS``: a íris deslocada e recortada pelo contorno do olho no próprio shader.

Depois, um passe de tela inteira aplica contorno de luz (rim light) na cor do humor, aberração
cromática (sustos) e interferência de sinal (núcleo fora do ar). O resultado volta como ``QImage``
e o HUD desenha como sempre. Se o OpenGL não subir, ``ok`` fica falso e o retrato segue na CPU.
"""

from __future__ import annotations

import logging
import struct
from dataclasses import dataclass, field

from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QOffscreenSurface, QOpenGLContext, QSurfaceFormat, QTransform

log = logging.getLogger(__name__)

RIGID, HAIR, BREATH, IRIS = 0, 1, 2, 3
GL_FLOAT, GL_TRIANGLES, GL_BLEND, GL_COLOR_BUFFER_BIT = 0x1406, 0x0004, 0x0BE2, 0x4000
GL_ONE, GL_ONE_MINUS_SRC_ALPHA, GL_TEXTURE_2D, GL_TEXTURE0 = 1, 0x0303, 0x0DE1, 0x84C0
CELL = (32.0, 20.0)  # tamanho da célula da malha (px do quadro de 1024): fino na vertical

VS = """#version 330 core
layout(location=0) in vec2 pos; layout(location=1) in vec2 uv;
uniform vec3 rowx; uniform vec3 rowy;          // transformação 2D (QTransform)
uniform int kind; uniform float t;
uniform vec4 hair;                             // raiz y, comprimento, amplitude, fase
uniform float freq; uniform vec2 drag; uniform float breath;
out vec2 v_uv;
void main() {
    vec2 p = pos;
    if (kind == 1) {
        float w = clamp((p.y - hair.x) / hair.y, 0.0, 1.0);
        float w2 = w * w;
        p.x += hair.z * w2 * sin(t * freq + hair.w - w * 2.4) + drag.x * w2;
        p.y += drag.y * w2 * 0.35 + abs(drag.x) * w2 * 0.12;
    } else if (kind == 2) {
        float b = exp(-pow((p.y - 830.0) / 170.0, 2.0));
        p.y -= breath * b;
        p.x += (p.x - 512.0) * 0.0035 * breath * b;
    }
    vec3 h = vec3(p, 1.0);
    vec2 q = vec2(dot(rowx, h), dot(rowy, h));
    gl_Position = vec4(q.x / 512.0 - 1.0, 1.0 - q.y / 512.0, 0.0, 1.0);
    v_uv = uv;
}"""

FS = """#version 330 core
in vec2 v_uv; out vec4 col;
uniform sampler2D tex; uniform sampler2D mask; uniform int kind; uniform vec2 iris;
void main() {
    vec4 c;
    if (kind == 3) {
        c = texture(tex, v_uv - iris);
        c.a *= texture(mask, v_uv).a;
    } else {
        c = texture(tex, v_uv);
    }
    col = vec4(c.rgb * c.a, c.a);
}"""

POST_VS = """#version 330 core
out vec2 uv;
void main() {
    vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
    uv = p;  // mesma orientação da FBO das camadas (a leitura final já desvira)
    gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}"""

POST_FS = """#version 330 core
in vec2 uv; out vec4 col;
uniform sampler2D src; uniform vec2 texel; uniform vec3 rimc;
uniform float rim; uniform float aberr; uniform float glitch; uniform float t;
void main() {
    vec2 u = uv;
    if (glitch > 0.0) {  // sinal ruim: faixas horizontais deslizando
        float band = floor(u.y * 48.0);
        float on = step(0.55, fract(sin(band + floor(t * 9.0)) * 43758.5));
        u.x += glitch * 0.03 * sin(band * 12.9 + t * 37.0) * on;
    }
    vec4 c = texture(src, u);
    if (aberr > 0.0) {
        c.r = texture(src, u + vec2(aberr, 0.0) * texel).r;
        c.b = texture(src, u - vec2(aberr, 0.0) * texel).b;
    }
    // contorno de luz: borda do recorte voltada para a luz (de cima, à esquerda)
    vec2 L = normalize(vec2(-1.0, 1.0)) * texel * 5.0;
    float edge = clamp(c.a - texture(src, u + L).a, 0.0, 1.0);
    c.rgb += rimc * edge * rim * c.a;
    col = c;
}"""


@dataclass
class GLOp:
    rel: str  # camada (parts/…, eyes/…, mouth/…) relativa à pasta do retrato
    xf: QTransform
    kind: int = RIGID
    hair: tuple[float, float, float, float] = (0.0, 1.0, 0.0, 0.0)  # raiz y, comprimento, amplitude, fase
    freq: float = 1.0
    iris: tuple[float, float] = (0.0, 0.0)  # deslocamento da íris (px do quadro de 1024)


@dataclass
class Post:
    rim: float = 0.3
    rim_color: tuple[float, float, float] = (0.8, 0.7, 1.0)
    aberr: float = 0.0  # px
    glitch: float = 0.0  # 0..1


@dataclass
class _Layer:
    tex: object
    vao: object
    vbo: object
    count: int
    box: QRectF
    mask: object = None


@dataclass
class GLPortrait:
    folder: object  # Path
    ok: bool = False
    _ready: bool = False
    _layers: dict = field(default_factory=dict)

    # -- inicialização ------------------------------------------------------------------------

    def _init(self) -> bool:
        if self._ready:
            return self.ok
        self._ready = True
        try:
            from PySide6.QtOpenGL import QOpenGLShader, QOpenGLShaderProgram, QOpenGLVertexArrayObject

            fmt = QSurfaceFormat()
            fmt.setVersion(3, 3)
            fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
            self.ctx = QOpenGLContext()
            self.ctx.setFormat(fmt)
            if not self.ctx.create():
                raise RuntimeError("contexto OpenGL indisponível")
            self.surf = QOffscreenSurface()
            self.surf.setFormat(self.ctx.format())
            self.surf.create()
            if not self.ctx.makeCurrent(self.surf):
                raise RuntimeError("makeCurrent falhou")
            self.gl = self.ctx.functions()

            def program(vs: str, fs: str):
                prog = QOpenGLShaderProgram()
                if not (prog.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Vertex, vs)
                        and prog.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Fragment, fs)
                        and prog.link()):
                    raise RuntimeError(prog.log())
                return prog

            self.prog = program(VS, FS)
            self.post = program(POST_VS, POST_FS)
            self.empty_vao = QOpenGLVertexArrayObject()
            self.empty_vao.create()
            self._fbo_size = 0
            self.ok = True
            log.info("retrato na GPU: OpenGL %d.%d", fmt.majorVersion(), fmt.minorVersion())
        except Exception as exc:  # noqa: BLE001 — qualquer falha de GL volta para a CPU
            log.warning("retrato na GPU indisponível (%s); seguindo na CPU", exc)
            self.ok = False
        return self.ok

    def _fbos(self, side: int) -> None:
        if self._fbo_size == side:
            return
        from PySide6.QtOpenGL import QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat

        ff = QOpenGLFramebufferObjectFormat()
        ff.setAttachment(QOpenGLFramebufferObject.Attachment.NoAttachment)
        self.fbo_a = QOpenGLFramebufferObject(side, side, ff)
        self.fbo_b = QOpenGLFramebufferObject(side, side, ff)
        self._fbo_size = side

    # -- camadas --------------------------------------------------------------------------------

    def _crop(self, rel: str, box: QRectF | None = None) -> tuple[QImage, QRectF] | None:
        from .portrait import _alpha_box

        img = QImage(str(self.folder / rel))
        if img.isNull():
            return None
        img = img.convertToFormat(QImage.Format.Format_RGBA8888)
        if img.width() != 1024:
            img = img.scaled(1024, 1024)
        if box is None:
            ab = _alpha_box(img)
            if ab is None:
                return None
            x0, y0, x1, y1 = ab
            box = QRectF(x0, y0, x1 - x0, y1 - y0)
        return img.copy(box.toRect()), box

    def _layer(self, rel: str) -> _Layer | None:
        if rel in self._layers:
            return self._layers[rel]
        from PySide6.QtOpenGL import QOpenGLBuffer, QOpenGLTexture, QOpenGLVertexArrayObject

        layer = None
        mask = None
        if rel == "parts/iris.png":  # a íris usa a caixa da abertura do olho, com a máscara junto
            opening = self._crop("parts/eye_open.png")
            got = self._crop(rel, opening[1]) if opening else None
            if opening and got:
                mask = QOpenGLTexture(opening[0])
        else:
            got = self._crop(rel)
        if got is not None:
            img, box = got
            tex = QOpenGLTexture(img)
            tex.setMinificationFilter(QOpenGLTexture.Filter.LinearMipMapLinear)
            tex.setMagnificationFilter(QOpenGLTexture.Filter.Linear)
            tex.setWrapMode(QOpenGLTexture.WrapMode.ClampToEdge)
            if mask is not None:
                mask.setWrapMode(QOpenGLTexture.WrapMode.ClampToEdge)
            data = _grid(box)
            vao = QOpenGLVertexArrayObject()
            vao.create()
            vao.bind()
            vbo = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
            vbo.create()
            vbo.bind()
            vbo.allocate(data, len(data))
            self.prog.bind()
            self.prog.enableAttributeArray(0)
            self.prog.setAttributeBuffer(0, GL_FLOAT, 0, 2, 16)
            self.prog.enableAttributeArray(1)
            self.prog.setAttributeBuffer(1, GL_FLOAT, 8, 2, 16)
            vao.release()
            layer = _Layer(tex, vao, vbo, len(data) // 16, box, mask)
        self._layers[rel] = layer
        return layer

    # -- desenho --------------------------------------------------------------------------------

    def render(self, side: int, ops: list[GLOp], t: float, drag: tuple[float, float], breath: float,
               post: Post) -> QImage | None:
        if not self._init() or not self.ctx.makeCurrent(self.surf):
            return None
        gl = self.gl
        self._fbos(side)
        self.fbo_a.bind()
        gl.glViewport(0, 0, side, side)
        gl.glClearColor(0, 0, 0, 0)
        gl.glClear(GL_COLOR_BUFFER_BIT)
        gl.glEnable(GL_BLEND)
        gl.glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA)
        prog = self.prog
        prog.bind()
        prog.setUniformValue1f("t", t)
        prog.setUniformValue("drag", float(drag[0]), float(drag[1]))
        prog.setUniformValue1f("breath", breath)
        prog.setUniformValue1i("tex", 0)
        prog.setUniformValue1i("mask", 1)
        for op in ops:
            layer = self._layer(op.rel)
            if layer is None:
                continue
            x = op.xf
            prog.setUniformValue("rowx", x.m11(), x.m21(), x.dx())
            prog.setUniformValue("rowy", x.m12(), x.m22(), x.dy())
            prog.setUniformValue1i("kind", op.kind)
            prog.setUniformValue("hair", *[float(v) for v in op.hair])
            prog.setUniformValue1f("freq", op.freq)
            if op.kind == IRIS:
                prog.setUniformValue("iris", op.iris[0] / layer.box.width(), op.iris[1] / layer.box.height())
                if layer.mask is not None:
                    layer.mask.bind(1)
            layer.tex.bind(0)
            layer.vao.bind()
            gl.glDrawArrays(GL_TRIANGLES, 0, layer.count)
            layer.vao.release()
        # pós-processamento
        self.fbo_b.bind()
        gl.glClear(GL_COLOR_BUFFER_BIT)
        gl.glDisable(GL_BLEND)
        self.post.bind()
        gl.glActiveTexture(GL_TEXTURE0)
        gl.glBindTexture(GL_TEXTURE_2D, self.fbo_a.texture())
        self.post.setUniformValue1i("src", 0)
        self.post.setUniformValue("texel", 1.0 / side, 1.0 / side)
        self.post.setUniformValue("rimc", *[float(v) for v in post.rim_color])
        self.post.setUniformValue1f("rim", post.rim)
        self.post.setUniformValue1f("aberr", post.aberr)
        self.post.setUniformValue1f("glitch", post.glitch)
        self.post.setUniformValue1f("t", t)
        self.empty_vao.bind()
        gl.glDrawArrays(GL_TRIANGLES, 0, 3)
        self.empty_vao.release()
        img = self.fbo_b.toImage()
        self.fbo_b.release()
        return img


def _grid(box: QRectF) -> bytes:
    """Triângulos de uma grade sobre ``box`` (x, y em px do quadro de 1024; u, v de 0 a 1)."""
    cols = max(2, int(box.width() / CELL[0]))
    rows = max(2, int(box.height() / CELL[1]))
    out: list[float] = []

    def v(i: int, j: int) -> tuple[float, float, float, float]:
        u, w = i / cols, j / rows
        return box.left() + u * box.width(), box.top() + w * box.height(), u, w

    for j in range(rows):
        for i in range(cols):
            a, b, c, d = v(i, j), v(i + 1, j), v(i, j + 1), v(i + 1, j + 1)
            out += [*a, *c, *b, *b, *c, *d]
    return struct.pack(f"{len(out)}f", *out)
