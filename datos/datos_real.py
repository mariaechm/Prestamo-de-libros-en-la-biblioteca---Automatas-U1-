"""Datos HÍBRIDOS para el monitor (equipo «book»).

REALES  : los préstamos (P) de «Checkouts By Title (Physical Items)», Seattle Public Library
          (código del ejemplar, título, tipo de ítem, colección y fecha_hora del préstamo).
SINTÉTICOS: usuarios y los eventos que ese conjunto no registra: reservas (R), renovaciones (N),
          devoluciones (D), multas (M) y pagos de multa (G).  Las fechas sintéticas se ubican
          dentro del intervalo real entre préstamos consecutivos del mismo ejemplar.
Las etiquetas salen del oráculo de generador.py (definición literal de P1, P2 y P3).
Semilla fija: la salida es reproducible.

Uso (desde la raíz del repositorio):
    python datos/preparar_real.py --entrada datos/real/seattle.csv
Salida: datos/validacion_real.csv, datos/prueba_real.csv, datos/clave_prueba_real.csv
"""
import argparse
import csv
import os
import random
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from generador import EVENTOS, es_casi_anomala, patrones  # noqa: E402

SEMILLA = 2026
FORMATOS = ["%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y %I:%M:%S %p",
            "%m/%d/%Y %H:%M", "%Y-%m-%d"]
# nombres posibles de cada columna (se comparan en minúsculas y sin « _ »)
CANDIDATAS = {
    "fecha": ["checkoutdatetime", "cout", "checkoutdate", "fecha"],
    "ejemplar": ["itembarcode", "barcode", "itemnumber", "itemid"],
    "titulo": ["title", "itemtitle", "titulo"],
    "tipo": ["itemtype", "materialtype", "tipo"],
    "coleccion": ["collection", "collcode", "itemcollection", "coleccion"],
}


def norm(s):
    return s.lower().replace("_", "").replace(" ", "")


def detectar(cabecera, forzadas):
    res = {}
    mapa = {norm(c): c for c in cabecera}
    for clave, opciones in CANDIDATAS.items():
        if forzadas.get(clave):
            res[clave] = forzadas[clave]
            continue
        res[clave] = next((mapa[o] for o in opciones if o in mapa), None)
    return res


def parsear(texto):
    texto = texto.strip()
    for f in FORMATOS:
        try:
            return datetime.strptime(texto, f)
        except ValueError:
            pass
    return None


# ------------------------------------------------------------------ construcción de sesiones
def horas(h):
    return timedelta(hours=h)


def reparto(t0, t1, n):
    """n instantes estrictamente ordenados dentro de (t0, t1)."""
    paso = (t1 - t0) / (n + 1)
    return [t0 + paso * (i + 1) for i in range(n)]


def construir_sesion(rng, prestamos, modo):
    """prestamos: lista de dicts (fecha, ejemplar, titulo, tipo, coleccion) del MISMO ejemplar, ordenados.
    modo: None (normal/casi) | 'P1' | 'P2' | 'P3'.  Devuelve lista de (fecha, símbolo, prestamo|None)."""
    ev = []
    anomalia_en = rng.randrange(len(prestamos))
    for i, p in enumerate(prestamos):
        tp = p["fecha"]
        sig = prestamos[i + 1]["fecha"] if i + 1 < len(prestamos) else None
        # reserva antes del préstamo
        if rng.random() < 0.45:
            ev.append((tp - horas(rng.randint(1, 72)), "R", None))
        ev.append((tp, "P", p))
        # renovaciones y devolución, entre el préstamo y el siguiente préstamo real
        k = rng.choices([0, 1, 2], [0.45, 0.35, 0.20])[0]
        if modo == "P1" and i == anomalia_en:
            k = rng.randint(3, 4)
        limite = sig - horas(1) if sig else tp + timedelta(days=rng.randint(7, 40))
        if limite <= tp:
            limite = tp + timedelta(seconds=30)
        td = tp + (limite - tp) * rng.uniform(0.6, 0.98)
        ev += [(t, "N", None) for t in reparto(tp, td, k)]
        ev.append((td, "D", None))
        # multa por devolución tardía
        if rng.random() < 0.30:
            fin = sig - timedelta(seconds=10) if sig else td + timedelta(days=3)
            if fin <= td:
                fin = td + timedelta(seconds=30)
            if modo == "P2" and i + 1 < len(prestamos) and i == min(anomalia_en, len(prestamos) - 2):
                ev.append((reparto(td, fin, 1)[0], "M", None))      # M y luego P directo -> MP
            elif rng.random() < 0.6:
                a, b = reparto(td, fin, 2)
                ev += [(a, "M", None), (b, "G", None)]               # multa pagada
            else:
                a, b = reparto(td, fin, 2)
                ev += [(a, "M", None), (b, "R", None)]               # casi anómala: M R P
    if modo == "P2" and not any(s == "M" for _, s, _ in ev):
        ev.insert(0, (prestamos[0]["fecha"] - horas(2), "M", None))  # sesión de un solo préstamo
    if modo == "P3":
        ev.insert(0, (prestamos[0]["fecha"] - horas(rng.randint(2, 48)), "D", None))
    ev.sort(key=lambda e: e[0])
    return ev


def cadena(ev):
    return "".join(s for _, s, _ in ev)


def generar(rng, grupos, n, n_anom, n_casi):
    """grupos: lista de listas de préstamos reales (por ejemplar), ya barajada. Consume grupos distintos."""
    pedidos = [("P%d" % (1 + i % 3)) for i in range(n_anom)] + ["casi"] * n_casi + [None] * (n - n_anom - n_casi)
    rng.shuffle(pedidos)
    sesiones, idx = [], 0
    for modo in pedidos:
        for _ in range(500):                       # reintentos hasta cumplir el modo
            if idx >= len(grupos):
                raise SystemExit("No hay suficientes ejemplares con préstamos reales para armar las sesiones.")
            g = grupos[idx]
            m = rng.choice([1, 2, 3]) if len(g) >= 3 else min(len(g), rng.choice([1, 2]))
            ps = g[:m]
            ev = construir_sesion(rng, ps, modo if modo in ("P1", "P2", "P3") else None)
            w = cadena(ev)
            ok = 3 <= len(w) <= 20
            if modo in ("P1", "P2", "P3"):
                ok = ok and patrones(w) == [modo]
            elif modo == "casi":
                ok = ok and not patrones(w) and es_casi_anomala(w)
            else:
                ok = ok and not patrones(w)
            idx += 1
            if ok:
                sesiones.append((ev, w))
                break
    return sesiones, idx


# ------------------------------------------------------------------ escritura
def escribir(ruta, sesiones, rng, primer_sid, primer_ev, con_etiqueta, ruta_clave=None):
    usuarios = [f"U-{rng.randrange(16**4):04X}" for _ in range(150)]
    cab = ["id_evento", "fecha_hora", "id_sesion", "actor", "evento", "simbolo"]
    if con_etiqueta:
        cab += ["etiqueta", "tipo_patron", "casi_anomala"]
    cab += ["ejemplar", "titulo", "tipo_item", "coleccion", "origen"]
    id_ev, filas, clave = primer_ev, [], []
    n_real = n_total = 0
    for k, (ev, w) in enumerate(sesiones):
        sid = f"S-{primer_sid + k:04d}"
        actor = rng.choice(usuarios)
        pats = patrones(w)
        casi = es_casi_anomala(w)
        ref = next(p for _, s, p in ev if p)
        for t, s, p in ev:
            fila = [id_ev, t.strftime("%Y-%m-%d %H:%M:%S"), sid, actor, EVENTOS[s], s]
            if con_etiqueta:
                fila += ["anómala" if pats else "normal", "+".join(pats) or "ninguno", "sí" if casi else "no"]
            fila += [ref["ejemplar"], ref["titulo"], ref["tipo"], ref["coleccion"], "real" if p else "sintético"]
            filas.append(fila)
            id_ev += 1
            n_total += 1
            n_real += 1 if p else 0
        clave.append([sid, "anómala" if pats else "normal", "+".join(pats) or "ninguno", "sí" if casi else "no"])
    with open(ruta, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows([cab] + filas)
    if ruta_clave:
        with open(ruta_clave, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows([["id_sesion", "etiqueta", "tipo_patron", "casi_anomala"]] + clave)
    return id_ev, n_real, n_total


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--entrada", required=True, help="CSV descargado de Seattle (5src-czff)")
    ap.add_argument("--col-fecha"), ap.add_argument("--col-ejemplar"), ap.add_argument("--col-titulo")
    ap.add_argument("--col-tipo"), ap.add_argument("--col-coleccion")
    ap.add_argument("--n-validacion", type=int, default=400)
    ap.add_argument("--n-prueba", type=int, default=60)
    a = ap.parse_args()

    aqui = os.path.dirname(os.path.abspath(__file__))
    with open(a.entrada, newline="", encoding="utf-8-sig") as f:
        lector = csv.DictReader(f)
        col = detectar(lector.fieldnames, {"fecha": a.col_fecha, "ejemplar": a.col_ejemplar, "titulo": a.col_titulo,
                                           "tipo": a.col_tipo, "coleccion": a.col_coleccion})
        print("Columnas detectadas:", col)
        if not col["fecha"] or not col["ejemplar"]:
            raise SystemExit(f"No encontré la columna de fecha o de ejemplar. Columnas del CSV: {lector.fieldnames}\n"
                             "Indíquelas con --col-fecha y --col-ejemplar.")
        por_ejemplar, leidas, malas = {}, 0, 0
        for fila in lector:
            leidas += 1
            t = parsear(fila[col["fecha"]])
            if t is None or not fila[col["ejemplar"]].strip():
                malas += 1
                continue
            por_ejemplar.setdefault(fila[col["ejemplar"]].strip(), []).append({
                "fecha": t.replace(microsecond=0), "ejemplar": fila[col["ejemplar"]].strip(),
                "titulo": (fila.get(col["titulo"]) or "").strip() if col["titulo"] else "",
                "tipo": (fila.get(col["tipo"]) or "").strip() if col["tipo"] else "",
                "coleccion": (fila.get(col["coleccion"]) or "").strip() if col["coleccion"] else ""})
    print(f"Filas leídas: {leidas} · descartadas por fecha/ejemplar inválidos: {malas} · ejemplares: {len(por_ejemplar)}")

    grupos = []
    for lista in por_ejemplar.values():
        lista.sort(key=lambda p: p["fecha"])
        # préstamos separados al menos 2 horas, para poder ubicar eventos sintéticos entre ellos
        depurada = [lista[0]]
        for p in lista[1:]:
            if p["fecha"] - depurada[-1]["fecha"] >= timedelta(hours=2):
                depurada.append(p)
        grupos.append(depurada)
    rng = random.Random(SEMILLA)
    grupos.sort(key=lambda g: g[0]["ejemplar"])          # orden determinista antes de barajar
    rng.shuffle(grupos)

    n_anom_val = round(a.n_validacion * 0.18)
    n_anom_pru = round(a.n_prueba * 0.18)
    val, usados = generar(rng, grupos, a.n_validacion, n_anom_val, 80)
    pru, _ = generar(rng, grupos[usados:], a.n_prueba, n_anom_pru, 10)   # ejemplares distintos a los de validación
    sig, r1, t1 = escribir(os.path.join(aqui, "validacion_real.csv"), val, rng, 1, 1, True)
    _, r2, t2 = escribir(os.path.join(aqui, "prueba_real.csv"), pru, rng, a.n_validacion + 1, sig, False,
                         os.path.join(aqui, "clave_prueba_real.csv"))
    print(f"validacion_real.csv: {len(val)} sesiones, {t1} eventos ({100 * r1 / t1:.1f} % reales: los P)")
    print(f"prueba_real.csv: {len(pru)} sesiones, {t2} eventos ({100 * r2 / t2:.1f} % reales)")
    print(f"Anómalas: validación {n_anom_val}, prueba {n_anom_pru}")


if __name__ == "__main__":
    main()