"""
Síntesis de voz (edge-tts + pygame), con caché y una cola en el mismo proceso.

Antes, cada frase lanzaba un proceso de Python nuevo desde cero (arrancar
el intérprete + reimportar todo) Y sintetizaba por internet cada vez,
aunque fuera una frase que ya se había dicho antes ("Avanzando", "Sistema
Activado", los nombres de los puntos de calibración, etc. son un
vocabulario fijo que se repite todo el tiempo). Eso hacía que la voz se
sintiera con varios segundos de retraso.

Ahora: un solo hilo en segundo plano vive todo el programa y procesa una
cola en orden (nunca se pisan dos frases), y el audio de cada frase se
guarda en caché la primera vez que se dice — las siguientes veces se
reproduce directo desde disco, sin esperar la red.
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

VOZ = "es-MX-JorgeNeural"

# Sin deformar la voz, y un poco más lento que lo normal.
#
# Antes iba a "+10%" de velocidad y "-15Hz" de tono. Las dos cosas juegan en
# contra de que Alexa entienda: desplazar el tono corre los formantes (la
# huella acústica que distingue una vocal de otra) y hablar rápido recorta
# la articulación. Las voces neurales ya suenan naturales por sí solas; lo
# mejor que se puede hacer por el reconocimiento es no deformarlas.
VELOCIDAD = "-8%"
VOLUMEN = "+0%"
TONO = "+0Hz"

CACHE_DIR = "cache_voz"


# ============================================================
# CACHÉ DE AUDIO
# ============================================================

def _archivo_cache(texto):
    """
    La clave incluye los ajustes de voz, no solo el texto.

    Si dependiera solo del texto, cambiar de voz, velocidad o tono no
    tendría ningún efecto audible: se seguiría reproduciendo el audio viejo
    guardado con los ajustes anteriores, y habría que borrar la caché a mano
    para notar el cambio. Así cada combinación tiene su propio archivo y el
    cambio se aplica solo.
    """
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


# ============================================================
# REPRODUCIR
# ============================================================

def _reproducir(archivo):
    pygame.mixer.music.load(archivo)
    pygame.mixer.music.play()
    while pygame.mixer.music.get_busy():
        time.sleep(0.02)


# ============================================================
# COLA EN SEGUNDO PLANO (un solo hilo, dentro del mismo proceso)
# ============================================================

_cola = queue.Queue()
_hilo_iniciado = False
_lock_hilo = threading.Lock()


def _procesar_cola():
    pygame.mixer.init()
    while True:
        texto = _cola.get()
        try:
            # Toda la frase como UN solo audio, incluidos los comandos de
            # Alexa. Antes se partía en "Alexa" + pausa fija + orden, para
            # no esperar a la red a media frase; con la caché eso ya no hace
            # falta, y partirla salía peor: el corte artificial entre dos
            # archivos suena robótico, mientras que la coma de "Alexa, apaga
            # enchufe dos" ya hace que el sintetizador ponga una pausa con
            # entonación natural. Cuanto más se parezca a una persona
            # hablando, mejor lo reconoce el Echo.
            _reproducir(_asegurar_audio(texto.strip()))
        except Exception as e:
            print(f"[voz] Error reproduciendo '{texto}': {e}")
        finally:
            _cola.task_done()


def hablar_en_segundo_plano(texto):
    global _hilo_iniciado
    if not _hilo_iniciado:
        with _lock_hilo:
            if not _hilo_iniciado:
                threading.Thread(target=_procesar_cola, daemon=True).start()
                _hilo_iniciado = True
    _cola.put(texto)


# ============================================================
# PRUEBA MANUAL: python modulos/voice_synth.py "texto a decir"
# ============================================================

if __name__ == "__main__":
    if len(sys.argv) > 1:
        pygame.mixer.init()
        _reproducir(_asegurar_audio(sys.argv[1]))
