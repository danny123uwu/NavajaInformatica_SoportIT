import subprocess
import datetime
from collections import Counter
import re
import os
import json

# Archivo donde guardamos, de forma persistente, todas las rutas en las que
# alguna vez se ha generado un resumen. Así la lista de logs puede mostrar
# archivos dispersos en distintas carpetas (Escritorio, Documentos, Descargas,
# Home, disco local, etc.) aunque el usuario haya cambiado de ruta varias veces.
CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".navaja_suiza_paths.json")


def _load_known_paths():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("paths", [])
        except Exception:
            return []
    return []


def _save_known_paths(paths):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"paths": paths}, f, indent=2)
    except Exception as e:
        print(f"No se pudo guardar la lista de rutas: {e}")


def register_path(path):
    """Agrega una ruta a la lista de ubicaciones conocidas donde se han guardado logs."""
    paths = _load_known_paths()
    abspath = os.path.abspath(path)
    if abspath not in paths:
        paths.append(abspath)
        _save_known_paths(paths)
    return paths


def get_known_paths():
    return _load_known_paths()


def find_all_logs():
    """Recorre TODAS las rutas conocidas (no solo la actual) y regresa la lista
    completa de resúmenes generados, incluso si están dispersos en distintas
    carpetas del sistema."""
    logs = []
    for path in _load_known_paths():
        if os.path.exists(path):
            try:
                for f in os.listdir(path):
                    if f.endswith(".txt") and f.startswith("resumen_sistema_"):
                        full = os.path.join(path, f)
                        if os.path.isfile(full):
                            logs.append({
                                "name": f,
                                "path": path,
                                "full_path": full,
                                "mtime": os.path.getmtime(full),
                            })
            except PermissionError:
                continue
    logs.sort(key=lambda x: x["mtime"], reverse=True)
    return logs


def generate_report(start, end, path, keyword=None):
    os.makedirs(path, exist_ok=True)
    register_path(path)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(path, f"resumen_sistema_{timestamp}.txt")

    cmd = ["journalctl", "-p", "err", "--no-pager"]
    if start:
        cmd.extend(["--since", start])
    if end:
        cmd.extend(["--until", end])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        raise RuntimeError(
            "journalctl no está disponible en este sistema. "
            "Esta función requiere Linux con systemd (no funciona en Windows)."
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("La consulta a journalctl tardó demasiado tiempo.")

    summary = Counter()
    pattern = re.compile(r'\w{3}\s+\d+\s\d{2}:\d{2}:\d{2}\s\S+\s\S+\[\d+\]:\s(.*)')
    keyword_lower = keyword.lower().strip() if keyword else None

    for line in result.stdout.splitlines():
        match = pattern.search(line)
        if match:
            msg = match.group(1)
            # Filtro por palabra clave: busca dentro del CONTENIDO del error,
            # no en nombres de archivo.
            if keyword_lower and keyword_lower not in msg.lower():
                continue
            msg_clean = re.sub(r'0x[0-9a-fA-F]+|\d{1,3}(\.\d{1,3}){3}', '[VALOR]', msg)
            summary[msg_clean] += 1

    with open(output_file, "w", encoding="utf-8") as f:
        f.write("=== REPORTE DE ERRORES DEL SISTEMA ===\n")
        f.write(f"Fecha de generación: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Rango buscado: Desde {start if start else 'El inicio'} hasta {end if end else 'Hoy'}\n")
        if keyword:
            f.write(f"Palabra clave filtrada: {keyword}\n")
        f.write("======================================\n\n")

        if not summary:
            f.write("No se encontraron errores en el rango especificado.\n")
        else:
            for error, count in summary.items():
                f.write(f"Ocurrencias: {count} veces\n")
                f.write(f"Detalle: {error}\n")
                f.write("-" * 30 + "\n")

    print(f"Reporte generado con éxito en: {output_file}")
    return output_file