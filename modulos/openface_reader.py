import os
import time
import glob
import subprocess
import json

with open('config.json', 'r') as f:
    config = json.load(f)

def find_generated_csv(directory):
    while True:
        csv_files = glob.glob(os.path.join(directory, "*.csv"))
        if csv_files:
            return csv_files[0]
        time.sleep(0.3)

def stream_openface_csv(csv_path):
    with open(csv_path, "r") as f:
        header = None
        while header is None:
            line = f.readline()
            if line.strip():
                header = [col.strip() for col in line.strip().split(",")]
        
        head_yaw_idx = header.index("pose_Ry") 
        head_pitch_idx = header.index("pose_Rx") 
        conf_idx = header.index("confidence")
        au45_idx = header.index("AU45_c") if "AU45_c" in header else None
        y_51_idx = header.index("y_51")
        y_57_idx = header.index("y_57")

        # 68 puntos faciales 2D (para dibujar la malla en la interfaz)
        if "x_0" in header and "y_67" in header:
            lm_x = [header.index(f"x_{i}") for i in range(68)]
            lm_y = [header.index(f"y_{i}") for i in range(68)]
        else:
            lm_x = lm_y = []

        while True:
            line = f.readline()
            if not line:
                time.sleep(0.005)
                continue
            
            parts = [p.strip() for p in line.strip().split(",")]
            if len(parts) != len(header):
                continue
            
            try:
                hx = float(parts[head_yaw_idx])
                hy = float(parts[head_pitch_idx])
                conf = float(parts[conf_idx])
                au45 = float(parts[au45_idx]) if au45_idx is not None else 0.0
                y_51 = float(parts[y_51_idx])
                y_57 = float(parts[y_57_idx])
                puntos = [(float(parts[ix]), float(parts[iy])) for ix, iy in zip(lm_x, lm_y)]

                yield hx, hy, au45, conf, y_51, y_57, puntos
            except ValueError:
                continue

def lanzar_openface():
    if os.path.exists(config["output_dir"]):
        for f in glob.glob(os.path.join(config["output_dir"], "*")):
            try: os.remove(f)
            except: pass
    else:
        os.makedirs(config["output_dir"], exist_ok=True)

    # Leemos el índice de la cámara desde el config.json (convertido a string)
    cam_idx = str(config.get("camera_index", 0))

    comando = [
        config["openface_bin"],
        "-device", cam_idx,  # <--- Usamos la variable dinámica aquí
        "-cam_width", config["cam_width"],   
        "-cam_height", config["cam_height"], 
        "-out_dir", config["output_dir"],
        "-pose", "-aus", "-2Dfp", "-nomask" 
    ]
    return subprocess.Popen(comando)