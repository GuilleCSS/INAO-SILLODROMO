"""
Analiza diagnostico_senales.csv y propone los umbrales de navegación.

Uso:
    python analizar_senales.py

La idea es no tener que adivinar los umbrales ni pedirle a nadie que
transcriba números de una consola tapada por la app. Se usa la aplicación
con normalidad (moviendo la cabeza a los cuatro lados unas cuantas veces),
y este script mira el registro para responder dos cosas:

  1. ¿Dónde está el reposo de esta persona? (la postura neutral real)
  2. ¿Hasta dónde llega cuando de verdad hace un gesto hacia cada lado?

Con eso, el umbral de cada dirección se pone a una fracción del alcance
real hacia ESE lado, que es justo lo que los umbrales por dirección
necesitan: la cámara no responde igual en los dos sentidos de un eje.
"""

import csv
import json
import os
import sys

RUTA_POR_DEFECTO = "diagnostico_senales.csv"

# Qué tan lejos, dentro del alcance real, se pone el umbral. 0.45 = hay que
# llegar al 45 % del gesto máximo que la persona hizo hacia ese lado.
FRACCION_UMBRAL = 0.45


def percentil(valores, p):
    if not valores:
        return 0.0
    ordenados = sorted(valores)
    idx = min(len(ordenados) - 1, max(0, int(len(ordenados) * p)))
    return ordenados[idx]


def analizar(ruta):
    hx, hy = [], []
    with open(ruta, newline="") as f:
        for fila in csv.DictReader(f):
            try:
                hx.append(float(fila["hx"]))
                hy.append(float(fila["hy"]))
            except (KeyError, ValueError):
                continue

    if len(hx) < 50:
        print(f"Solo hay {len(hx)} muestras en {ruta}: muy pocas para concluir algo.")
        print("Usa la app un rato moviendo la cabeza a los cuatro lados y vuelve a correr esto.")
        return None

    # El reposo es la postura más frecuente: se pasa la mayor parte del
    # tiempo ahí, así que la mediana lo representa bien (y es inmune a los
    # extremos de los gestos, a diferencia del promedio).
    centro_x = percentil(hx, 0.50)
    centro_y = percentil(hy, 0.50)

    # Alcance real hacia cada lado. Se usa un percentil alto en vez del
    # máximo absoluto para no quedar a merced de un frame con ruido.
    izq = abs(min(percentil(hx, 0.02) - centro_x, 0.0))
    der = max(percentil(hx, 0.98) - centro_x, 0.0)
    arr = abs(min(percentil(hy, 0.02) - centro_y, 0.0))
    aba = max(percentil(hy, 0.98) - centro_y, 0.0)

    print(f"Muestras analizadas: {len(hx)}")
    print(f"Reposo estimado:     hx={centro_x:+.3f}  hy={centro_y:+.3f}")
    print()
    print("Alcance real de los gestos (desde el reposo):")
    print(f"   izquierda {izq:.3f}   derecha {der:.3f}")
    print(f"   arriba    {arr:.3f}   abajo   {aba:.3f}")
    print()

    flojos = [n for n, v in (("izquierda", izq), ("derecha", der),
                             ("arriba", arr), ("abajo", aba)) if v < 0.02]
    if flojos:
        print(f"OJO: casi no hay movimiento registrado hacia: {', '.join(flojos)}.")
        print("     Vuelve a usar la app haciendo gestos claros hacia esos lados")
        print("     antes de aplicar estos valores.")
        print()

    umbrales = {
        "navegacion_umbral_izquierda": round(izq * FRACCION_UMBRAL, 4),
        "navegacion_umbral_derecha": round(der * FRACCION_UMBRAL, 4),
        "navegacion_umbral_arriba": round(arr * FRACCION_UMBRAL, 4),
        "navegacion_umbral_abajo": round(aba * FRACCION_UMBRAL, 4),
    }

    print("Umbrales propuestos (45 % del alcance real de cada lado):")
    for k, v in umbrales.items():
        print(f'   "{k}": {v},')
    return umbrales


def aplicar(umbrales, ruta_config="config.json"):
    with open(ruta_config) as f:
        cfg = json.load(f)
    cfg.update(umbrales)
    with open(ruta_config, "w") as f:
        json.dump(cfg, f, indent=4, ensure_ascii=False)
        f.write("\n")
    print(f"\nAplicados a {ruta_config}.")


if __name__ == "__main__":
    ruta = sys.argv[1] if len(sys.argv) > 1 else RUTA_POR_DEFECTO
    if not os.path.exists(ruta):
        print(f"No existe {ruta}. Corre la app primero (el registro se crea solo).")
        sys.exit(1)

    propuesta = analizar(ruta)
    if propuesta and "--aplicar" in sys.argv:
        aplicar(propuesta)
    elif propuesta:
        print("\nPara aplicarlos:  python analizar_senales.py --aplicar")
