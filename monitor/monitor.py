"""Monitor de secuencias: lee un CSV de bitácoras, arma una cadena por sesión,
ejecuta el AFD mínimo y calcula las métricas (VP, FP, FN, precisión, exhaustividad).

Uso (desde la raíz del repositorio):
    python monitor/monitor.py --datos datos/validacion.csv
    python monitor/monitor.py --datos datos/prueba.csv --clave datos/clave_prueba.csv
    python monitor/monitor.py --cadenas PNNN MP RPND      (cadenas escritas en el momento)

El CSV puede estar separado por comas o por punto y coma (como lo guarda Excel en español).
"""
import argparse
import csv
import json
import os
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from automata import AF, AFD  # noqa: E402

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ------------------------------------------------------------ carga de autómatas
def cargar_afd(ruta):
    d = json.load(open(ruta, encoding="utf-8"))
    delta = {(q, a): r for q, fila in d["transiciones"].items() for a, r in fila.items()}
    return AFD(d["estados"], d["alfabeto"], delta, d["inicial"], d["finales"])


def cargar_afnd(ruta):
    d = json.load(open(ruta, encoding="utf-8"))
    delta = defaultdict(set)
    for t in d["transiciones"]:
        delta[(t["de"], t["simbolo"])].add(t["a"])
    return AF(d["estados"], d["alfabeto"], delta, d["inicial"], d["finales"])


# ------------------------------------------------------------ lectura de CSV
def _filas(ruta):
    """Filas de un CSV como diccionarios. Acepta BOM (Excel) y separador ',' o ';'."""
    with open(ruta, newline="", encoding="utf-8-sig") as f:
        cabecera = f.readline()
        f.seek(0)
        sep = ";" if cabecera.count(";") > cabecera.count(",") else ","
        for fila in csv.DictReader(f, delimiter=sep):
            yield {(k or "").strip(): (v or "").strip() for k, v in fila.items()}


def _orden(evento):
    """Orden cronológico: fecha_hora y, si empatan, id_evento."""
    try:
        n = int(evento["id_evento"])
    except (KeyError, ValueError):
        n = 0
    return (evento.get("fecha_hora", ""), n)


def leer_sesiones(ruta):
    """{id_sesion: (cadena, etiqueta | None, tipo_patron | None)} con eventos ordenados por fecha_hora."""
    eventos = defaultdict(list)
    for fila in _filas(ruta):
        if "id_sesion" not in fila or "simbolo" not in fila:
            raise SystemExit("El CSV debe tener las columnas id_sesion, simbolo, fecha_hora e id_evento "
                             "(separadas por coma o punto y coma).")
        eventos[fila["id_sesion"]].append(fila)
    sesiones = {}
    for sid, evs in eventos.items():
        evs.sort(key=_orden)
        cadena = "".join(e["simbolo"].upper() for e in evs)
        sesiones[sid] = (cadena, evs[0].get("etiqueta"), evs[0].get("tipo_patron"))
    return dict(sorted(sesiones.items()))


def leer_clave(ruta):
    return {r["id_sesion"]: (r["etiqueta"], r["tipo_patron"]) for r in _filas(ruta)}


# ------------------------------------------------------------ métricas
def metricas(vp, fp, fn, vn):
    prec = vp / (vp + fp) if vp + fp else 1.0
    exh = vp / (vp + fn) if vp + fn else 1.0
    return {"VP": vp, "FP": fp, "FN": fn, "VN": vn, "precision": prec, "exhaustividad": exh}


def evaluar(sesiones, prediccion, real):
    vp = sum(1 for s in sesiones if prediccion[s] and real[s])
    fp = sum(1 for s in sesiones if prediccion[s] and not real[s])
    fn = sum(1 for s in sesiones if not prediccion[s] and real[s])
    vn = sum(1 for s in sesiones if not prediccion[s] and not real[s])
    return metricas(vp, fp, fn, vn)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--datos", help="CSV de bitácoras")
    ap.add_argument("--cadenas", nargs="+", metavar="CADENA",
                    help="una o más cadenas para analizar en el momento (por ejemplo: PNNN MP RPND)")
    ap.add_argument("--clave")
    ap.add_argument("--afd", default=os.path.join(RAIZ, "automatas", "afd_minimo.json"))
    ap.add_argument("--salida")
    args = ap.parse_args()
    if not args.datos and not args.cadenas:
        ap.error("indique --datos archivo.csv o --cadenas CADENA [CADENA ...]")
    if args.datos and args.cadenas:
        ap.error("use --datos o --cadenas, no ambos")

    afd = cargar_afd(args.afd)
    patrones = {p: cargar_afnd(os.path.join(RAIZ, "automatas", f"afnd_{p.lower()}.json"))
                for p in ("P1", "P2", "P3")}

    if args.cadenas:                                   # modo cadenas escritas en el momento
        sesiones = {}
        for i, texto in enumerate(args.cadenas, 1):
            limpia = "".join(ch for ch in texto.upper() if ch not in " ,-")
            if limpia:
                sesiones[f"C{i}"] = (limpia, None, None)
    else:
        sesiones = leer_sesiones(args.datos)

    # símbolos fuera del alfabeto: se avisa y se omite la sesión (en vez de detener el programa)
    alfabeto = set(afd.sigma)
    invalidas = {sid: sorted(set(c) - alfabeto) for sid, (c, _, _) in sesiones.items() if set(c) - alfabeto}
    for sid, malos in invalidas.items():
        print(f"AVISO: {sid} tiene símbolos fuera del alfabeto {''.join(afd.sigma)}: "
              f"{', '.join(malos)}. Se omite.")
    sesiones = {sid: v for sid, v in sesiones.items() if sid not in invalidas}
    if not sesiones:
        print("No hay sesiones válidas para analizar.")
        return

    t0 = time.perf_counter()
    prediccion = {sid: afd.acepta(c) for sid, (c, _, _) in sesiones.items()}
    t_afd = time.perf_counter() - t0

    # qué patrón(es) explican cada alarma (se ejecutan los AFND de cada patrón)
    explicacion = {sid: [p for p, A in patrones.items() if A.acepta(c)] for sid, (c, _, _) in sesiones.items()}

    if args.cadenas:
        print(f"{'Cadena':<24}{'Veredicto':<11}Patrones")
        for sid, (c, _, _) in sesiones.items():
            print(f"{c:<24}{'anómala' if prediccion[sid] else 'normal':<11}{'+'.join(explicacion[sid]) or 'ninguno'}")
        return

    salida = args.salida or os.path.splitext(args.datos)[0] + "_resultados.csv"
    with open(salida, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id_sesion", "cadena", "prediccion", "patrones_detectados"])
        for sid, (c, _, _) in sesiones.items():
            w.writerow([sid, c, "anómala" if prediccion[sid] else "normal", "+".join(explicacion[sid]) or "ninguno"])
    n_alarmas = sum(prediccion.values())
    print(f"{len(sesiones)} sesiones analizadas en {t_afd * 1000:.2f} ms · {n_alarmas} marcadas como anómalas")
    print(f"Informe de anomalías: {salida}")

    # etiquetas reales: columna `etiqueta` o archivo de clave
    if args.clave:
        clave = leer_clave(args.clave)
        real = {s: clave[s][0] == "anómala" for s in sesiones}
        tipos = {s: clave[s][1] for s in sesiones}
    elif next(iter(sesiones.values()))[1] is not None:
        real = {s: v[1] == "anómala" for s, v in sesiones.items()}
        tipos = {s: v[2] for s, v in sesiones.items()}
    else:
        print("Sin etiquetas: no se calculan métricas.")
        return
    m = evaluar(list(sesiones), prediccion, real)
    print("Métricas globales:", {k: (round(v, 4) if isinstance(v, float) else v) for k, v in m.items()})
    for p in ("P1", "P2", "P3"):
        pred_p = {s: p in explicacion[s] for s in sesiones}
        real_p = {s: p in tipos[s].split("+") for s in sesiones}
        mp = evaluar(list(sesiones), pred_p, real_p)
        print(f"  {p}: VP={mp['VP']} FP={mp['FP']} FN={mp['FN']} "
              f"precisión={mp['precision']:.4f} exhaustividad={mp['exhaustividad']:.4f}")


if __name__ == "__main__":
    main()