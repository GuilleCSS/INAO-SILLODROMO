import time
import json
from .mouse_action import mover_cursor, hacer_clic
from .voice_synth import hablar_en_segundo_plano

with open('config.json', 'r') as f:
    config = json.load(f)

class GazeStateController:
    def __init__(self):
        self.system_enabled = True
        self.blink_start_time = None
        self.blink_action_triggered = False
        
        self.hx_suavizado = 0.0
        self.hy_suavizado = 0.0
        self.ultimo_clic_tiempo = 0

    def process_frame(self, hx, hy, au45_c, conf, y_51, y_57):
        current_time = time.time()
        
        if conf < config["conf_min"]:
            self.blink_start_time = None 
            return None

        is_eyes_closed = (au45_c >= 1.0)

        # 1. MECANISMO DE PAUSA
        if is_eyes_closed:
            if self.blink_start_time is None:
                self.blink_start_time = current_time
            
            elapsed = current_time - self.blink_start_time
            if elapsed >= config["blink_hold_time"] and not self.blink_action_triggered:
                self.system_enabled = not self.system_enabled
                self.blink_action_triggered = True
                estado = "Activado" if self.system_enabled else "Pausado"
                hablar_en_segundo_plano(f"Sistema {estado}")
        else:
            self.blink_start_time = None
            self.blink_action_triggered = False

        if not self.system_enabled:
            return None 

        # 2. CLIC POR BOCA
        apertura_boca = y_57 - y_51 
        boca_umbral = config.get("boca_threshold", 25.0)
        
        if apertura_boca > boca_umbral and (current_time - self.ultimo_clic_tiempo) > 1.2:
            hacer_clic()
            hablar_en_segundo_plano("Clic")
            self.ultimo_clic_tiempo = current_time

        # 3. SUAVIZADO EMA PARA LA CABEZA
        alpha = config.get("suavizado_alpha", 0.2)
        self.hx_suavizado = (alpha * hx) + ((1 - alpha) * self.hx_suavizado)
        self.hy_suavizado = (alpha * hy) + ((1 - alpha) * self.hy_suavizado)

        # 4. CÁLCULO DE MOVIMIENTO PROPORCIONAL
        dx, dy, x_dir, y_dir = self.calcular_movimiento(self.hx_suavizado, self.hy_suavizado)
        mover_cursor(dx, dy)
        
        direccion_texto = f"{x_dir} {y_dir}".strip()
        return direccion_texto if direccion_texto else "CENTRO"

    def calcular_movimiento(self, hx, hy):
        velocidad_base = config.get("mouse_speed", 5)
        limite_multiplicador = 25.0 # Elevamos el límite para que puedas cruzar la pantalla 2K
        
        dx = 0.0
        dy = 0.0
        x_dir = ""
        y_dir = ""
        
        # Eje X (Giro de cuello con aceleración CUADRÁTICA)
        if hx < -config["x_threshold"]:
            multiplicador = min((abs(hx) / config["x_threshold"]) ** 2, limite_multiplicador)
            dx = -velocidad_base * multiplicador
            x_dir = "IZQUIERDA"
        elif hx > config["x_threshold"]:
            multiplicador = min((abs(hx) / config["x_threshold"]) ** 2, limite_multiplicador)
            dx = velocidad_base * multiplicador
            x_dir = "DERECHA"
            
        # Eje Y (Inclinación de cráneo con aceleración CUADRÁTICA)
        if hy < -config["y_threshold"]:
            multiplicador = min((abs(hy) / config["y_threshold"]) ** 2, limite_multiplicador)
            dy = -velocidad_base * multiplicador
            y_dir = "ARRIBA" 
        elif hy > config["y_threshold"]:
            multiplicador = min((abs(hy) / config["y_threshold"]) ** 2, limite_multiplicador)
            dy = velocidad_base * multiplicador
            y_dir = "ABAJO"
            
        return dx, dy, x_dir, y_dir