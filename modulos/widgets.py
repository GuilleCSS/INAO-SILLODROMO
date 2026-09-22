"""
Widgets personalizados de Sillodromo.

Se usan desde interfaz.ui como *widgets promovidos* de Qt Designer
(header: modulos/widgets.h), así que el diseño se sigue editando en Designer.

- TileButton       -> promovido desde QPushButton
- VistaCamara      -> promovido desde QWidget
- IndicadorCabeza  -> promovido desde QWidget
- IndicadorBoca    -> promovido desde QWidget

Propiedades dinámicas que TileButton lee del .ui:
    icono            "arriba" | "izquierda" | "derecha" | "power"
    acento           color hex, ej. "#22C55E"
    subtitulo        texto pequeño bajo el título
    subtituloActivo  texto mientras el botón está presionado
"""

import json

from PyQt5.QtWidgets import QPushButton, QWidget, QSizePolicy
from PyQt5.QtCore import Qt, QRectF, QPointF
from PyQt5.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QFontMetrics, QPainterPath,
    QLinearGradient, QRadialGradient, QPolygonF, QTransform
)

with open("config.json", "r") as f:
    config = json.load(f)


# --- Paleta ---

BG = "#0A0F1C"
SURFACE = "#111827"
SURFACE_2 = "#18223A"
BORDER = "#26324D"
TEXT = "#E8EEF9"
MUTED = "#8B9AB8"

GREEN = "#22C55E"
BLUE = "#3B82F6"
AMBER = "#F59E0B"
RED = "#EF4444"
CYAN = "#22D3EE"
SLATE = "#64748B"

FUENTE = "Segoe UI"


def mezclar(c1, c2, t):
    a, b = QColor(c1), QColor(c2)
    return QColor(
        int(a.red() + (b.red() - a.red()) * t),
        int(a.green() + (b.green() - a.green()) * t),
        int(a.blue() + (b.blue() - a.blue()) * t),
    )


def con_alpha(color, alpha):
    c = QColor(color)
    c.setAlpha(alpha)
    return c


def fuente(px, peso=QFont.Bold):
    f = QFont(FUENTE)
    f.setPixelSize(max(9, int(px)))
    f.setWeight(peso)
    return f


def fuente_ajustada(texto, px, ancho, peso=QFont.Bold):
    """Reduce el tamaño hasta que el texto quepa en `ancho`."""
    f = fuente(px, peso)
    while px > 11 and QFontMetrics(f).horizontalAdvance(texto) > ancho:
        px -= 1
        f = fuente(px, peso)
    return f


def pill(p, rect, texto, color, relleno_alpha=45):
    """Etiqueta redondeada dibujada (para overlays)."""
    p.setPen(QPen(con_alpha(color, 150), 1))
    p.setBrush(con_alpha("#000000", 150))
    p.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
    p.setBrush(con_alpha(color, relleno_alpha))
    p.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
    p.setPen(QColor(TEXT))
    p.drawText(rect, Qt.AlignCenter, texto)


# --- Iconos ---


def dibujar_flecha(p, centro, tam, rotacion, color):
    puntos = [(0, -0.95), (0.85, -0.05), (0.3, -0.05), (0.3, 0.9),
              (-0.3, 0.9), (-0.3, -0.05), (-0.85, -0.05)]
    poly = QPolygonF([QPointF(x * tam / 2, y * tam / 2) for x, y in puntos])
    t = QTransform()
    t.translate(centro.x(), centro.y())
    t.rotate(rotacion)
    poly = t.map(poly)
    p.setPen(QPen(QColor(color), max(2.0, tam * 0.06), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(QColor(color))
    p.drawPolygon(poly)


def dibujar_power(p, centro, tam, color):
    r = tam * 0.38
    p.setPen(QPen(QColor(color), max(2.5, tam * 0.11), Qt.SolidLine, Qt.RoundCap))
    p.setBrush(Qt.NoBrush)
    rect = QRectF(centro.x() - r, centro.y() - r + tam * 0.05, 2 * r, 2 * r)
    p.drawArc(rect, 120 * 16, 300 * 16)
    p.drawLine(QPointF(centro.x(), centro.y() - tam * 0.45),
               QPointF(centro.x(), centro.y() - tam * 0.02))


def dibujar_icono(p, nombre, centro, tam, color):
    if nombre == "arriba":
        dibujar_flecha(p, centro, tam, 0, color)
    elif nombre == "abajo":
        dibujar_flecha(p, centro, tam, 180, color)
    elif nombre == "izquierda":
        dibujar_flecha(p, centro, tam, -90, color)
    elif nombre == "derecha":
        dibujar_flecha(p, centro, tam, 90, color)
    elif nombre == "power":
        dibujar_power(p, centro, tam, color)


class TileButton(QPushButton):
    """Botón grande dibujado a mano, pensado para control con la cabeza."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hover = False
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(70, 44)

    def _prop(self, nombre, defecto=""):
        valor = self.property(nombre)
        return defecto if valor is None else str(valor)

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)

        titulo = self.text()
        icono = self._prop("icono")
        acento_hex = self._prop("acento", BLUE)
        acento = QColor(acento_hex)
        activo = self.isDown()
        subtitulo = self._prop("subtituloActivo") if activo else ""
        subtitulo = subtitulo or self._prop("subtitulo")

        r = QRectF(self.rect()).adjusted(4, 4, -4, -4)
        w, h = r.width(), r.height()
        # Radio bajo a propósito: junto con el espaciado mínimo entre tiles
        # en la interfaz, se leen como zonas grandes contiguas en vez de
        # botones sueltos, más fáciles de acertar con el cursor.
        radio = min(12.0, min(w, h) * 0.10)

        if activo:
            for i, a in enumerate((80, 45, 20)):
                p.setPen(QPen(con_alpha(acento, a), 2))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(r.adjusted(-1 - i, -1 - i, 1 + i, 1 + i), radio + i, radio + i)
            grad = QLinearGradient(r.topLeft(), r.bottomRight())
            grad.setColorAt(0, acento.lighter(118))
            grad.setColorAt(1, acento.darker(135))
            p.setBrush(QBrush(grad))
            p.setPen(QPen(acento.lighter(150), 2.5))
            color_fg, color_sub, color_icono = QColor("#FFFFFF"), QColor(255, 255, 255, 220), QColor("#FFFFFF")
        elif self._hover:
            grad = QLinearGradient(r.topLeft(), r.bottomLeft())
            grad.setColorAt(0, mezclar(SURFACE_2, acento_hex, 0.30))
            grad.setColorAt(1, mezclar(SURFACE, acento_hex, 0.16))
            p.setBrush(QBrush(grad))
            p.setPen(QPen(acento.lighter(115), 3))
            color_fg, color_sub, color_icono = QColor(TEXT), QColor(TEXT), acento.lighter(125)
        else:
            grad = QLinearGradient(r.topLeft(), r.bottomLeft())
            grad.setColorAt(0, QColor(SURFACE_2))
            grad.setColorAt(1, QColor(SURFACE))
            p.setBrush(QBrush(grad))
            p.setPen(QPen(QColor(BORDER), 1.5))
            color_fg, color_sub, color_icono = QColor(TEXT), QColor(MUTED), acento

        p.drawRoundedRect(r, radio, radio)

        if w > h * 1.8:
            # --- horizontal: icono + texto, el bloque completo centrado ---
            # (antes el icono quedaba pegado a la izquierda con el texto
            # extendiéndose a la derecha; en botones muy anchos como Avanzar/
            # Regresar eso se veía corrido hacia la orilla. Ahora se mide el
            # texto real y se centra el grupo icono+texto como una unidad.)
            s = h * 0.5
            gap = h * 0.14
            ancho_max_texto = max(10.0, w - s - h * 0.5)

            f = fuente_ajustada(titulo, h * 0.26, ancho_max_texto)
            alto_t = QFontMetrics(f).height()
            ancho_titulo = QFontMetrics(f).horizontalAdvance(titulo)

            if subtitulo:
                fs = fuente_ajustada(subtitulo, h * 0.15, ancho_max_texto, QFont.Normal)
                alto_s = QFontMetrics(fs).height()
                ancho_texto = max(ancho_titulo, QFontMetrics(fs).horizontalAdvance(subtitulo))
            else:
                ancho_texto = ancho_titulo

            ancho_grupo = s + gap + ancho_texto
            x_inicio = r.center().x() - ancho_grupo / 2
            centro = QPointF(x_inicio + s / 2, r.center().y())

            self._badge(p, centro, s, acento, activo)
            if icono:
                dibujar_icono(p, icono, centro, s * 0.55, color_icono)

            x_txt = centro.x() + s / 2 + gap
            caja_texto = ancho_texto + 4
            if subtitulo:
                y0 = r.center().y() - (alto_t + alto_s) / 2
                p.setFont(f)
                p.setPen(color_fg)
                p.drawText(QRectF(x_txt, y0, caja_texto, alto_t), Qt.AlignLeft | Qt.AlignVCenter, titulo)
                p.setFont(fs)
                p.setPen(color_sub)
                p.drawText(QRectF(x_txt, y0 + alto_t, caja_texto, alto_s), Qt.AlignLeft | Qt.AlignVCenter, subtitulo)
            else:
                p.setFont(f)
                p.setPen(color_fg)
                p.drawText(QRectF(x_txt, r.top(), caja_texto, h), Qt.AlignLeft | Qt.AlignVCenter, titulo)
        else:
            # --- vertical: icono arriba ---
            con_sub = bool(subtitulo) and h > 120
            s = min(w * 0.36, h * (0.36 if con_sub else 0.42))
            centro = QPointF(r.center().x(), r.top() + h * (0.38 if con_sub else 0.40))
            self._badge(p, centro, s, acento, activo)
            if icono:
                dibujar_icono(p, icono, centro, s * 0.55, color_icono)
            ancho = w * 0.9
            f = fuente_ajustada(titulo, min(h * 0.1, 40), ancho)
            alto_t = QFontMetrics(f).height()
            y_t = centro.y() + s / 2 + h * 0.05
            p.setFont(f)
            p.setPen(color_fg)
            p.drawText(QRectF(r.left(), y_t, w, alto_t), Qt.AlignCenter, titulo)
            if con_sub:
                fs = fuente_ajustada(subtitulo, min(h * 0.055, 20), ancho, QFont.Normal)
                p.setFont(fs)
                p.setPen(color_sub)
                p.drawText(QRectF(r.left(), y_t + alto_t + 2, w, QFontMetrics(fs).height()),
                           Qt.AlignCenter, subtitulo)
        p.end()

    def _badge(self, p, centro, s, acento, activo):
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 40) if activo else con_alpha(acento, 40))
        p.drawEllipse(centro, s / 2, s / 2)


# Segmentos de los 68 puntos faciales (formato iBUG, el que daba OpenFace).
# Con MediaPipe el rastreo se ve directo sobre el video y no se mandan
# puntos, así que esto solo se dibuja si algún día vuelve a haber backend sin
# imagen; se conserva porque es el único respaldo visual en ese caso.
SEGMENTOS = [
    (range(0, 17), False),   # mandíbula
    (range(17, 22), False),  # ceja derecha
    (range(22, 27), False),  # ceja izquierda
    (range(27, 31), False),  # puente nasal
    (range(31, 36), False),  # base nariz
    (range(36, 42), True),   # ojo derecho
    (range(42, 48), True),   # ojo izquierdo
]
BOCA_EXT = range(48, 60)
BOCA_INT = range(60, 68)


class VistaCamara(QWidget):
    """
    Panel de cámara. Muestra el video en vivo y encima el estado (rostro,
    clic, pausa). Si no llega imagen, cae a dibujar solo la malla facial,
    que al menos deja ver que el rastreo sigue vivo.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(240, 150)
        self.imagen = None
        self.puntos = []
        self.rostro = False
        self.clic = False
        self.pausado = False
        self.modo = "iniciando"   # iniciando | vivo | rastreo
        self.espejo = bool(config.get("camara_espejo", True))
        self.cw = float(config.get("cam_width", 1280))
        self.ch = float(config.get("cam_height", 720))
        # Con video se prefiere la cara limpia: se ve mejor cómo se está
        # moviendo la cabeza. Sin video la malla se dibuja de todos modos.
        self.mostrar_malla = bool(config.get("mostrar_malla", False))

    # --- API ---

    def set_frame(self, qimage):
        self.imagen = qimage
        self.modo = "vivo"
        self.update()

    def set_sin_video(self):
        self.imagen = None
        self.modo = "rastreo"
        self.update()

    def set_estado(self, estado):
        self.puntos = estado.get("puntos") or []
        self.rostro = estado.get("rostro", False)
        self.clic = estado.get("clic", False)
        self.pausado = not estado.get("sistema", True)
        if self.modo == "iniciando":
            self.modo = "rastreo"
        if self.imagen is None:
            self.update()

    # --- Dibujo ---

    def _area_video(self, r):
        """Rectángulo 16:9 (o el aspecto real) centrado dentro de r."""
        if self.imagen is not None:
            aspecto = self.imagen.width() / max(1, self.imagen.height())
        else:
            aspecto = self.cw / self.ch
        if r.width() / r.height() > aspecto:
            h = r.height()
            w = h * aspecto
        else:
            w = r.width()
            h = w / aspecto
        return QRectF(r.center().x() - w / 2, r.center().y() - h / 2, w, h)

    def _mapear(self, area, x, y):
        nx = x / self.cw
        if self.espejo:
            nx = 1.0 - nx
        return QPointF(area.left() + nx * area.width(), area.top() + (y / self.ch) * area.height())

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)

        r = QRectF(self.rect())
        area = self._area_video(r)
        radio = 16.0

        clip = QPainterPath()
        clip.addRoundedRect(area, radio, radio)
        p.setClipPath(clip)

        # Fondo
        grad = QRadialGradient(area.center(), max(area.width(), area.height()) * 0.7)
        grad.setColorAt(0, QColor("#132038"))
        grad.setColorAt(1, QColor("#070B15"))
        p.fillRect(area, QBrush(grad))

        if self.imagen is not None:
            p.drawImage(area, self.imagen)
            # viñeta suave para que los overlays se lean bien
            sombra = QLinearGradient(area.topLeft(), area.bottomLeft())
            sombra.setColorAt(0, QColor(0, 0, 0, 110))
            sombra.setColorAt(0.25, QColor(0, 0, 0, 0))
            sombra.setColorAt(0.75, QColor(0, 0, 0, 0))
            sombra.setColorAt(1, QColor(0, 0, 0, 120))
            p.fillRect(area, QBrush(sombra))
        else:
            self._rejilla(p, area)

        hay_rostro = self.rostro and len(self.puntos) >= 68
        if self.imagen is not None:
            # Hay video: se ve la cara tal cual. La malla solo se superpone
            # si se pide explícitamente, y no se tapa la cara con mensajes
            # (el chip del encabezado ya avisa si no se detecta el rostro).
            if hay_rostro and self.mostrar_malla:
                self._malla(p, area, solo=False)
        elif hay_rostro:
            self._malla(p, area, solo=True)
        elif self.modo != "iniciando":
            self._mensaje_centro(p, area, "Buscando rostro…",
                                 "Colócate frente a la cámara")
        else:
            self._mensaje_centro(p, area, "Iniciando cámara…",
                                 "Cargando modelos de OpenFace")

        if self.pausado:
            p.fillRect(area, QColor(10, 15, 28, 150))
            self._mensaje_centro(p, area, "SISTEMA PAUSADO",
                                 f"Cierra los ojos {config.get('blink_hold_time', 3.5):g} s para reanudar",
                                 color=AMBER)

        p.setClipping(False)

        # Overlays
        p.setFont(fuente(13, QFont.Bold))
        if self.modo == "vivo":
            etiqueta, color = "●  EN VIVO", RED
        elif self.modo == "rastreo":
            etiqueta, color = "●  RASTREO FACIAL", CYAN
        else:
            etiqueta, color = "●  INICIANDO", AMBER
        ancho = QFontMetrics(p.font()).horizontalAdvance(etiqueta) + 28
        pill(p, QRectF(area.left() + 14, area.top() + 14, ancho, 30), etiqueta, color)

        if self.clic:
            txt = "CLIC MANTENIDO"
            ancho = QFontMetrics(p.font()).horizontalAdvance(txt) + 28
            pill(p, QRectF(area.right() - 14 - ancho, area.top() + 14, ancho, 30), txt, GREEN, 120)

        # Borde
        p.setPen(QPen(QColor(GREEN if self.clic else BORDER), 2 if self.clic else 1.5))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(area.adjusted(0.5, 0.5, -0.5, -0.5), radio, radio)
        p.end()

    def _rejilla(self, p, area):
        p.setPen(QPen(QColor(255, 255, 255, 12), 1))
        paso = max(24.0, area.width() / 24)
        x = area.left()
        while x < area.right():
            p.drawLine(QPointF(x, area.top()), QPointF(x, area.bottom()))
            x += paso
        y = area.top()
        while y < area.bottom():
            p.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
            y += paso

    def _malla(self, p, area, solo):
        pts = [self._mapear(area, x, y) for x, y in self.puntos[:68]]
        base = QColor(CYAN)
        grosor = 2.2 if solo else 1.6

        def trazo(indices, cerrado, color, g):
            poly = QPolygonF([pts[i] for i in indices])
            p.setBrush(Qt.NoBrush)
            if solo:  # halo
                p.setPen(QPen(con_alpha(color, 55), g * 4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                p.drawPolygon(poly) if cerrado else p.drawPolyline(poly)
            p.setPen(QPen(con_alpha(color, 230), g, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPolygon(poly) if cerrado else p.drawPolyline(poly)

        for indices, cerrado in SEGMENTOS:
            trazo(indices, cerrado, base, grosor)

        color_boca = QColor(GREEN if self.clic else CYAN)
        if self.clic:
            p.setPen(Qt.NoPen)
            p.setBrush(con_alpha(GREEN, 70))
            p.drawPolygon(QPolygonF([pts[i] for i in BOCA_INT]))
        trazo(BOCA_EXT, True, color_boca, grosor + 0.6)
        trazo(BOCA_INT, True, color_boca, grosor)

        p.setPen(Qt.NoPen)
        p.setBrush(con_alpha("#FFFFFF", 200 if solo else 170))
        rad = 2.2 if solo else 1.8
        for pt in pts:
            p.drawEllipse(pt, rad, rad)

    def _mensaje_centro(self, p, area, titulo, sub, color=TEXT):
        p.setPen(QColor(color))
        p.setFont(fuente(min(30, area.height() * 0.07), QFont.Bold))
        alto = QFontMetrics(p.font()).height()
        y = area.center().y() - alto
        p.drawText(QRectF(area.left(), y, area.width(), alto), Qt.AlignCenter, titulo)
        p.setPen(QColor(MUTED))
        p.setFont(fuente(min(17, area.height() * 0.045), QFont.Normal))
        p.drawText(QRectF(area.left(), y + alto + 4, area.width(), alto), Qt.AlignCenter, sub)


class IndicadorCabeza(QWidget):
    """Mini joystick: dónde está la cabeza respecto al umbral de gesto."""

    def __init__(self, parent=None):
        super().__init__(parent)
        # Desviación respecto al centro aprendido, en fracción del umbral:
        # 0 = en reposo, ±1 = justo en el umbral. Dibujar hx/hy crudos con una
        # escala fija no sirve — depende del backend, y el punto termina
        # clavado en un borde mostrando la cabeza girada todo el tiempo.
        self.frac_x = 0.0
        self.frac_y = 0.0
        self.rostro = False

    def actualizar(self, frac_x, frac_y, rostro):
        self.frac_x, self.frac_y, self.rostro = frac_x, frac_y, rostro
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        lado = min(self.width(), self.height())
        c = QPointF(self.width() / 2, self.height() / 2)
        R = lado / 2 - 3

        p.setPen(QPen(QColor(BORDER), 2))
        p.setBrush(QColor(SURFACE_2))
        p.drawEllipse(c, R, R)

        # La caja punteada es el umbral real de gesto: dentro es zona muerta,
        # fuera dispara un paso. Sirve para ver de un vistazo si la
        # calibración quedó bien.
        escala = (R - 7) / 1.4      # una fracción de 1.4 llega al borde
        lado_caja = escala
        zona = QRectF(c.x() - lado_caja, c.y() - lado_caja, 2 * lado_caja, 2 * lado_caja)
        p.setPen(QPen(QColor(BORDER), 1, Qt.DashLine))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(zona, 3, 3)

        if not self.rostro:
            p.setPen(QColor(MUTED))
            p.setFont(fuente(lado * 0.32))
            p.drawText(self.rect(), Qt.AlignCenter, "?")
            return

        fx = max(-1.4, min(1.4, self.frac_x))
        fy = max(-1.4, min(1.4, self.frac_y))
        fuera = abs(self.frac_x) >= 1.0 or abs(self.frac_y) >= 1.0
        color = QColor(CYAN if fuera else MUTED)
        punto = QPointF(c.x() + fx * escala, c.y() + fy * escala)
        p.setPen(QPen(con_alpha(color, 130), 2))
        p.drawLine(c, punto)
        p.setPen(Qt.NoPen)
        p.setBrush(con_alpha(color, 60))
        p.drawEllipse(punto, 11, 11)
        p.setBrush(color)
        p.drawEllipse(punto, 6.5, 6.5)


class IndicadorBoca(QWidget):
    """Barra de apertura de boca con la marca del umbral de clic."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.apertura = 0.0
        self.clic = False
        # El umbral llega en vivo desde el controlador, ya ajustado a la boca
        # cerrada real de la persona. Esto es solo el valor de arranque.
        self.umbral = float(config.get("boca_delta_on", 15.0))

    def actualizar(self, apertura, clic, umbral=None):
        self.apertura, self.clic = apertura, clic
        if umbral is not None:
            self.umbral = umbral
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        p.setFont(fuente(13, QFont.DemiBold))
        p.setPen(QColor(GREEN if self.clic else MUTED))
        p.drawText(QRectF(0, 0, w, h / 2), Qt.AlignLeft | Qt.AlignVCenter,
                   "BOCA · CLIC MANTENIDO" if self.clic else "BOCA · CLIC")

        barra = QRectF(0, h / 2 + 4, w, min(16.0, h / 2 - 8))
        rad = barra.height() / 2
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(SURFACE_2))
        p.drawRoundedRect(barra, rad, rad)

        maximo = self.umbral * 1.5
        t = max(0.0, min(1.0, self.apertura / maximo))
        if t > 0.02:
            relleno = QRectF(barra.left(), barra.top(), max(barra.height(), barra.width() * t), barra.height())
            g = QLinearGradient(relleno.topLeft(), relleno.topRight())
            base = QColor(GREEN if self.clic else CYAN)
            g.setColorAt(0, base.darker(140))
            g.setColorAt(1, base)
            p.setBrush(QBrush(g))
            p.drawRoundedRect(relleno, rad, rad)

        xu = barra.left() + barra.width() * (self.umbral / maximo)
        p.setPen(QPen(QColor(TEXT), 2))
        p.drawLine(QPointF(xu, barra.top() - 4), QPointF(xu, barra.bottom() + 4))
