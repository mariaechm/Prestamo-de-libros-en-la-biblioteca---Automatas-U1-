"""Generador de bitácoras sintéticas de préstamo de libros (equipo «book»).

Σ = {R: RESERVAR, P: PRESTAR, N: RENOVAR, D: DEVOLVER, M: MULTA, G: PAGAR_MULTA}
Una sesión = historial de un usuario con un ejemplar.

Patrones (anomalías):
  P1  la sesión contiene NNN
  P2  la sesión contiene MP
  P3  la sesión contiene D y no hay P antes de la primera D

La etiqueta de cada sesión se calcula con un oráculo independiente
(`patrones`), que NO usa autómatas.  Semilla fija: los CSV son reproducibles.

Uso:  python generador.py            (desde la carpeta datos/)
"""
import csv
import os
import random
import re
from datetime import datetime, timedelta

SEMILLA = 2026
N_VALIDACION, N_ANOMALAS_VAL = 400, 72      # 18 % anómalas
N_PRUEBA, N_ANOMALAS_PRU = 60, 11           # 18,3 % anómalas
EVENTOS = {"R": "RESERVAR", "P": "PRESTAR", "N": "RENOVAR",
           "D": "DEVOLVER", "M": "MULTA", "G": "PAGAR_MULTA"}


# ---------------------------------------------------------------- oráculo
def patrones(w):
    """Patrones que cumple la cadena w (definición literal de los lenguajes)."""
    res = []
    if "NNN" in w:
        res.append("P1")
    if "MP" in w:
        res.append("P2")
    i = w.find("D")
    if i != -1 and "P" not in w[:i]:
        res.append("P3")
    return res


def es_casi_anomala(w):
    """Normal pero cercana a un patrón: dos N seguidas (sin llegar a NNN) o una M seguida de P
    pero separadas por 1-2 eventos (sin llegar a MP)."""
    return (not patrones(w)) and ("NN" in w or re.search(r"M.{1,2}P", w) is not None)


# ---------------------------------------------------------------- generación
def caminata(rng, n, pesos=None):
    """Recorrido por el ciclo de vida de un préstamo (libre → prestado → multado)."""
    pw = pesos or {"libre": [0.3, 0.7], "prestado": [0.3, 0.45, 0.15, 0.10], "multado": [0.7, 0.1, 0.2]}
    w, estado = [], "libre"
    while len(w) < n:
        if estado == "libre":
            a = rng.choices("RP", pw["libre"])[0]
            estado = "prestado" if a == "P" else "libre"
        elif estado == "prestado":
            a = rng.choices("NDMR", pw["prestado"])[0]
            estado = "libre" if a == "D" else ("multado" if a == "M" else "prestado")
        else:
            a = rng.choices("GRD", pw["multado"])[0]
            estado = "prestado" if a == "G" else ("libre" if a == "D" else "multado")
        w.append(a)
    return "".join(w)


def largo(rng):
    return max(3, min(20, int(rng.triangular(3, 20, 7))))


def sesion_normal(rng):
    while True:
        w = caminata(rng, largo(rng))
        if not patrones(w):
            return w


def sesion_casi_anomala(rng):
    pesos = {"libre": [0.2, 0.8], "prestado": [0.45, 0.25, 0.25, 0.05], "multado": [0.5, 0.2, 0.3]}
    while True:
        w = caminata(rng, largo(rng), pesos)
        if es_casi_anomala(w):
            return w


def sesion_anomala(rng, patron):
    while True:
        if patron == "P1":
            w = caminata(rng, rng.randint(0, 5)) + "N" * rng.randint(3, 5) + caminata(rng, rng.randint(0, 5))
        elif patron == "P2":
            w = caminata(rng, rng.randint(0, 6)) + "MP" + caminata(rng, rng.randint(0, 6))
        else:  # P3: una devolución antes de cualquier préstamo
            pre = "".join(rng.choice("RGM") for _ in range(rng.randint(0, 2)))
            w = pre + "D" + caminata(rng, rng.randint(1, 8))
        if 3 <= len(w) <= 20 and patrones(w) == [patron]:
            return w


def construir(rng, n, n_anomalas, n_casi):
    """Devuelve lista de (cadena, anomala, casi) en orden aleatorio."""
    reparto = ["P1", "P2", "P3"]
    sesiones = [(sesion_anomala(rng, reparto[i % 3]), True, False) for i in range(n_anomalas)]
    sesiones += [(sesion_casi_anomala(rng), False, True) for _ in range(n_casi)]
    sesiones += [(sesion_normal(rng), False, False) for _ in range(n - n_anomalas - n_casi)]
    rng.shuffle(sesiones)
    return sesiones


# ---------------------------------------------------------------- escritura
def escribir(ruta, sesiones, rng, primer_id_sesion, primer_id_evento, con_etiqueta, clave=None):
    inicio = datetime(2026, 9, 1, 8, 0, 0)
    usuarios = [f"U-{rng.randrange(16**4):04X}" for _ in range(150)]
    cabecera = ["id_evento", "fecha_hora", "id_sesion", "actor", "evento", "simbolo"]
    if con_etiqueta:
        cabecera += ["etiqueta", "tipo_patron", "casi_anomala"]
    id_ev, filas, filas_clave = primer_id_evento, [], []
    for k, (w, anomala, casi) in enumerate(sesiones):
        sid = f"S-{primer_id_sesion + k:04d}"
        actor = rng.choice(usuarios)
        t = inicio + timedelta(hours=rng.randint(0, 24 * 55), minutes=rng.randint(0, 59))
        pats = patrones(w)
        casi = es_casi_anomala(w)
        for a in w:
            t += timedelta(hours=rng.randint(1, 72), minutes=rng.randint(0, 59))
            fila = [id_ev, t.strftime("%Y-%m-%d %H:%M:%S"), sid, actor, EVENTOS[a], a]
            if con_etiqueta:
                fila += ["anómala" if pats else "normal", "+".join(pats) if pats else "ninguno",
                         "sí" if casi else "no"]
            filas.append(fila)
            id_ev += 1
        filas_clave.append([sid, "anómala" if pats else "normal", "+".join(pats) if pats else "ninguno",
                            "sí" if casi else "no"])
    with open(ruta, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows([cabecera] + filas)
    if clave:
        with open(clave, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows([["id_sesion", "etiqueta", "tipo_patron", "casi_anomala"]] + filas_clave)
    return id_ev


def main():
    aqui = os.path.dirname(os.path.abspath(__file__))
    rng = random.Random(SEMILLA)
    val = construir(rng, N_VALIDACION, N_ANOMALAS_VAL, 80)
    sig = escribir(os.path.join(aqui, "validacion.csv"), val, rng, 1, 1, True)
    pru = construir(rng, N_PRUEBA, N_ANOMALAS_PRU, 10)
    escribir(os.path.join(aqui, "prueba.csv"), pru, rng, N_VALIDACION + 1, sig, False,
             clave=os.path.join(aqui, "clave_prueba.csv"))
    print(f"validacion.csv: {len(val)} sesiones | prueba.csv: {len(pru)} sesiones")


if __name__ == "__main__":
    main()
