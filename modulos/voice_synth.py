"""
Síntesis de voz (edge-tts + pygame), con caché y una cola en el mismo proceso.

El programa dice siempre las mismas frases: "Avanzando", "Sistema pausado",
las órdenes para Alexa. Por eso cada audio se guarda en disco la primera vez
y después se reproduce desde ahí, sin esperar a la red. Un único hilo en
segundo plano atiende la cola en orden, así que dos frases nunca se pisan.
"""

import os
import sys
import time
import queue
import asyncio
import hashlib
import threading

import edge_tts
import pygame

# Voz mexicana, igual que el idioma en que está configurada la Alexa: es lo
# que mejor reconoce. La otra mexicana disponible es es-MX-JorgeNeural
# (hombre); cambiar esta línea basta, la caché se regenera sola.
VOZ = "es-MX-DaliaNeural"

# Velocidad y tono van neutros a propósito. Mover el tono corre los formantes
# (lo que distingue una vocal de otra) y cambiar la velocidad rompe el ritmo
# con el que la voz fue entrenada; en las dos cosas Alexa entiende peor. El
# volumen sí conviene subirlo un poco, porque no deforma nada y mejora la
# señal frente al micrófono — pero no más, que saturado se reconoce peor.
VELOCIDAD = "+0%"
VOLUMEN = "+15%"
TONO = "+0Hz"

# Qué separa "Alexa" de la orden, o sea la pausa entre las dos. Medido sobre
# "Alexa[sep] enciende rasuradora": con coma dura 3.00 s y no se oye pausa;
# con punto, 3.88 s con ~0.9 s de silencio. Los puntos suspensivos y el punto
# y coma no agregan nada.
#
# Partir la frase en dos audios y esperar en medio parece dar control exacto,
# pero sale peor: cada clip arrastra su propio relleno (1.15 s entre los dos),
# así que pedir 0.25 s da 1.45 s reales. Un solo audio gana.
SEPARADOR_ALEXA = ". "

CACHE_DIR = "cache_voz"


# --- Caché de audio ---


def _archivo_cache(texto):
    """La clave incluye los ajustes de voz, no solo el texto. Si dependiera
    solo del texto, cambiar de voz o de tono no se oiría: seguiría sonando el
    audio viejo y habría que borrar la caché a mano."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    firma = f"{texto}|{VOZ}|{VELOCIDAD}|{VOLUMEN}|{TONO}"
    clave = hashlib.md5(firma.encode("utf-8")).hexdigest()
    return os.path.join(CACHE_DIR, f"{clave}.mp3")


async def _generar_audio(texto, archivo):
    comunicacion = edge_tts.Communicate(
        text=texto, voice=VOZ, rate=VELOCIDAD, volume=VOLUMEN, pitch=TONO
    )
    await comunicacion.save(archivo)


async def _asegurar_audio_async(texto):
    ruta = _archivo_cache(texto)
    if not os.path.exists(ruta):
        await _generar_audio(texto, ruta)
    return ruta


def _asegurar_audio(texto):
    return asyncio.run(_asegurar_audio_async(texto))


def _con_pausa(texto):
    """Cambia la coma que sigue a "Alexa" por SEPARADOR_ALEXA, para que el
    sintetizador deje una pausa antes de la orden. El resto de las frases
    (avisos del sistema, calibración) se quedan como están."""
    texto = texto.strip()
    if texto.lower().startswith("alexa,"):
        orden = texto.split(",", 1)[1].strip()
        if SEPARADOR_ALEXA.strip() in (".", "!", "?") and orden:
            # Mayúscula tras el punto: así el texto queda como dos oraciones
            # de verdad, que es la forma en que se midió la pausa.
            orden = orden[0].upper() + orden[1:]
        return "Alexa" + SEPARADOR_ALEXA + orden
    return texto


def _reproducir(archivo):
    pygame.mixer.music.load(archivo)
    pygame.mixer.music.play()
    while pygame.mixer.music.get_busy():
        time.sleep(0.02)


# --- Cola en segundo plano ---

_cola = queue.Queue()
_hilo_iniciado = False
_lock_hilo = threading.Lock()


def _procesar_cola():
    pygame.mixer.init()
    while True:
        texto = _cola.get()
        try:
            _reproducir(_asegurar_audio(_con_pausa(texto)))
        except Exception as e:
            # Que falle la voz no puede tumbar el hilo: si se muere, el
            # programa deja de hablar para siempre sin avisar. Se reporta y
            # se sigue con la siguiente frase.
            print(f"[voz] Error reproduciendo '{texto}': {e}")
        finally:
            _cola.task_done()


def hablar_en_segundo_plano(texto):
    """Encola una frase y regresa de inmediato. Lo llama el hilo de la
    interfaz, que no puede quedarse esperando a que termine el audio."""
    global _hilo_iniciado
    if not _hilo_iniciado:
        with _lock_hilo:
            if not _hilo_iniciado:
                threading.Thread(target=_procesar_cola, daemon=True).start()
                _hilo_iniciado = True
    _cola.put(texto)


# Prueba suelta: python modulos/voice_synth.py "texto a decir"

if __name__ == "__main__":
    if len(sys.argv) > 1:
        pygame.mixer.init()
        _reproducir(_asegurar_audio(sys.argv[1]))
