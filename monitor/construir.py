"""Construye los AFND de cada patrón, la unión con ε, la eliminación de ε, el AFD por
subconjuntos y el AFD mínimo; los verifica, los exporta (.json y .jff, diagramas .png)
y calcula las métricas del informe (informe/resultados.json).

Uso (desde la raíz):  python monitor/construir.py
"""
import itertools
import json
import math
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "datos"))
from automata import (AF, AFD, EPS, SIGMA, eliminar_epsilon, equivalentes, minimizar,  # noqa: E402
                      subconjuntos, union_epsilon)
from generador import patrones as oraculo  # noqa: E402
import monitor as mon  # noqa: E402

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUT = os.path.join(RAIZ, "automatas")
INF = os.path.join(RAIZ, "informe")
os.makedirs(AUT, exist_ok=True)
os.makedirs(os.path.join(INF, "figuras"), exist_ok=True)


# ------------------------------------------------------------------ AFND por patrón
def construir_nfas():
    S = SIGMA
    # P1: contiene NNN
    d1 = {("A0", a): {"A0"} for a in S}
    d1[("A0", "N")] |= {"A1"}
    d1[("A1", "N")] = {"A2"}
    d1[("A2", "N")] = {"A3"}
    d1.update({("A3", a): {"A3"} for a in S})
    P1 = AF(["A0", "A1", "A2", "A3"], S, d1, "A0", {"A3"})
    # P2: contiene MP
    d2 = {("B0", a): {"B0"} for a in S}
    d2[("B0", "M")] |= {"B1"}
    d2[("B1", "P")] = {"B2"}
    d2.update({("B2", a): {"B2"} for a in S})
    P2 = AF(["B0", "B1", "B2"], S, d2, "B0", {"B2"})
    # P3: contiene D y no hay P antes de la primera D (diseño natural determinista)
    d3 = {("C0", a): {"C0"} for a in ("R", "N", "M", "G")}
    d3[("C0", "D")] = {"C1"}
    d3.update({("C1", a): {"C1"} for a in S})
    P3 = AF(["C0", "C1"], S, d3, "C0", {"C1"})
    return {"P1": P1, "P2": P2, "P3": P3}


def es_determinista(A):
    return all(len(v) <= 1 for v in A.delta.values()) and not any(k[1] == EPS for k in A.delta)


# ------------------------------------------------------------------ formato
def fmt_set(S, orden):
    if not S:
        return "—"
    xs = sorted(S, key=lambda q: orden.index(q) if q in orden else 999)
    return xs[0] if len(xs) == 1 else "{" + ",".join(xs) + "}"


def tabla_nfa(A, columnas, orden=None):
    orden = orden or A.Q
    filas = []
    for q in A.Q:
        fila = {"estado": q, "inicial": q == A.q0, "final": q in A.F, "dest": {}}
        for a in columnas:
            fila["dest"][a if a else "ε"] = fmt_set(A.delta.get((q, a), set()), orden)
        filas.append(fila)
    return filas


def etiqueta_aristas(pares):
    """pares: {(src,dst): set(símbolos)} -> etiqueta legible."""
    out = {}
    for k, v in pares.items():
        if v >= set(SIGMA):
            out[k] = "Σ"
        elif len(v) >= 4 and (set(SIGMA) - v):
            out[k] = "Σ − {" + ",".join(sorted(set(SIGMA) - v, key=SIGMA.index)) + "}"
        else:
            out[k] = ",".join(sorted(v, key=lambda x: SIGMA.index(x) if x in SIGMA else -1)) if EPS not in v else "ε"
    return out


# ------------------------------------------------------------------ exportación
def a_json_afnd(A, ruta):
    d = {"tipo": "AFND", "estados": A.Q, "alfabeto": A.sigma, "inicial": A.q0, "finales": sorted(A.F),
         "transiciones": [{"de": q, "simbolo": a, "a": r} for q, a, r in A.transiciones()]}
    json.dump(d, open(ruta, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def a_json_afd(D, ruta):
    trans = {q: {a: D.delta[(q, a)] for a in D.sigma} for q in D.Q}
    d = {"tipo": "AFD", "estados": D.Q, "alfabeto": D.sigma, "inicial": D.q0, "finales": sorted(D.F),
         "transiciones": trans}
    json.dump(d, open(ruta, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def a_jff(Q, inicial, finales, aristas, ruta):
    """aristas: iterable (src, símbolo, dst); símbolo '' = ε.  Formato JFLAP (.jff)."""
    n = len(Q)
    xml = ['<?xml version="1.0" encoding="UTF-8" standalone="no"?>', "<structure>", "\t<type>fa</type>", "\t<automaton>"]
    for i, q in enumerate(Q):
        ang = 2 * math.pi * i / max(n, 1)
        x, y = 300 + 220 * math.cos(ang), 280 + 200 * math.sin(ang)
        xml.append(f'\t\t<state id="{i}" name="{q}">\n\t\t\t<x>{x:.1f}</x>\n\t\t\t<y>{y:.1f}</y>')
        if q == inicial:
            xml.append("\t\t\t<initial/>")
        if q in finales:
            xml.append("\t\t\t<final/>")
        xml.append("\t\t</state>")
    idx = {q: i for i, q in enumerate(Q)}
    for s, a, d in aristas:
        lectura = f"<read>{a}</read>" if a else "<read/>"
        xml.append(f"\t\t<transition>\n\t\t\t<from>{idx[s]}</from>\n\t\t\t<to>{idx[d]}</to>\n\t\t\t{lectura}\n\t\t</transition>")
    xml += ["\t</automaton>", "</structure>"]
    open(ruta, "w", encoding="utf-8").write("\n".join(xml))


def dibujar(nombre, Q, inicial, finales, aristas, rankdir="LR", etiquetas_nodo=None, tam=None):
    pares = {}
    for s, a, d in aristas:
        pares.setdefault((s, d), set()).add(a)
    et = etiqueta_aristas(pares)
    lineas = [f'digraph G {{ rankdir={rankdir}; nodesep=0.25; ranksep=0.3; dpi=170;',
              'node [shape=circle, fontname="DejaVu Sans", fontsize=12, width=0.45, fixedsize=false, margin=0.03];',
              'edge [fontname="DejaVu Sans", fontsize=11];', '__i [shape=point, width=0.01, label=""];']
    if tam:
        lineas.append(f'size="{tam}"; ratio=compress;')
    for q in Q:
        forma = "doublecircle" if q in finales else "circle"
        etq = (etiquetas_nodo or {}).get(q, q)
        lineas.append(f'"{q}" [shape={forma}, label="{etq}"];')
    lineas.append(f'__i -> "{inicial}";')
    for (s, d), e in et.items():
        lineas.append(f'"{s}" -> "{d}" [label="{e}"];')
    lineas.append("}")
    dot = os.path.join(INF, "figuras", nombre + ".dot")
    open(dot, "w", encoding="utf-8").write("\n".join(lineas))
    subprocess.run(["dot", "-Tpng", dot, "-o", os.path.join(INF, "figuras", nombre + ".png")], check=True)
    os.remove(dot)


def aristas_afnd(A):
    return [(q, a, r) for q, a, r in A.transiciones()]


def aristas_afd(D):
    return [(q, a, D.delta[(q, a)]) for q in D.Q for a in D.sigma]


# ------------------------------------------------------------------ medición
def medir(funcion, sesiones, repeticiones=40):
    mejor = float("inf")
    for _ in range(repeticiones):
        t0 = time.perf_counter()
        for w in sesiones:
            funcion(w)
        mejor = min(mejor, time.perf_counter() - t0)
    return mejor


def main():
    R = {}
    nfas = construir_nfas()
    for p, A in nfas.items():
        a_json_afnd(A, os.path.join(AUT, f"afnd_{p.lower()}.json"))
        a_jff(A.Q, A.q0, A.F, aristas_afnd(A), os.path.join(AUT, f"afnd_{p.lower()}.jff"))
        dibujar(f"afnd_{p.lower()}", A.Q, A.q0, A.F, aristas_afnd(A))
    R["nfa"] = {p: {"Q": A.Q, "q0": A.q0, "F": sorted(A.F), "tabla": tabla_nfa(A, SIGMA),
                    "n_estados": len(A.Q), "n_trans": A.n_transiciones(), "determinista": es_determinista(A)}
                for p, A in nfas.items()}

    # --- unión con ε
    U = union_epsilon(list(nfas.values()), "s")
    a_json_afnd(U, os.path.join(AUT, "afnd_union_eps.json"))
    a_jff(U.Q, U.q0, U.F, aristas_afnd(U), os.path.join(AUT, "afnd_union_eps.jff"))
    dibujar("afnd_union", U.Q, U.q0, U.F, aristas_afnd(U), rankdir="LR")
    R["union"] = {"Q": U.Q, "F": sorted(U.F), "eps": sorted(U.delta[("s", EPS)]),
                  "n_estados": len(U.Q), "n_trans": U.n_transiciones(),
                  "n_eps": sum(len(v) for (q, a), v in U.delta.items() if a == EPS),
                  "clausura_s": sorted(U.clausura({"s"}))}

    # --- eliminación de ε
    E = eliminar_epsilon(U)
    a_json_afnd(E, os.path.join(AUT, "afnd_sin_eps.json"))
    a_jff(E.Q, E.q0, E.F, aristas_afnd(E), os.path.join(AUT, "afnd_sin_eps.jff"))
    R["sin_eps"] = {"Q": E.Q, "F": sorted(E.F), "tabla": tabla_nfa(E, SIGMA, U.Q),
                    "n_estados": len(E.Q), "n_trans": E.n_transiciones(),
                    "clausura_s": sorted(U.clausura({"s"}))}

    # --- subconjuntos
    D, tabla_sub = subconjuntos(E)
    a_json_afd(D, os.path.join(AUT, "afd.json"))
    a_jff(D.Q, D.q0, D.F, aristas_afd(D), os.path.join(AUT, "afd.jff"))
    R["subconjuntos"] = {"n_estados": len(D.Q), "n_trans": D.n_transiciones(), "F": sorted(D.F),
                         "filas": [{"estado": n, "conjunto": fmt_set(S, U.Q), "dest": dst, "final": n in D.F,
                                    "inicial": n == "q0"} for n, S, dst in tabla_sub]}

    # --- minimización
    M, hist, clases = minimizar(D)
    a_json_afd(M, os.path.join(AUT, "afd_minimo.json"))
    a_jff(M.Q, M.q0, M.F, aristas_afd(M), os.path.join(AUT, "afd_minimo.jff"))

    # descripción semántica de cada estado del AFD mínimo
    conj = {n: S for n, S, _ in tabla_sub}
    clase_de = {q: f"m{i}" for i, g in enumerate(clases) for q in g}

    def describir(S, final):
        if final:
            return "Anomalía detectada"
        racha = max([int(q[1]) for q in S if q in ("A0", "A1", "A2")] or [0])
        partes = [f"{racha} N seguida(s)" if racha else "sin N seguidas"]
        partes.append("última M" if "B1" in S else "sin M pendiente")
        partes.append("sin P ni D" if "C0" in S else "ya hubo P")
        return "; ".join(partes)

    desc = {}
    for i, g in enumerate(clases):
        rep = g[-1] if len(g) > 1 else g[0]
        S = conj[rep]
        desc[f"m{i}"] = describir(S, rep in D.F)
    R["minimo"] = {"n_estados": len(M.Q), "n_trans": M.n_transiciones(), "F": sorted(M.F), "q0": M.q0,
                   "historial": [[g for g in particion] for particion in hist],
                   "clases": [{"estado": f"m{i}", "miembros": g, "descripcion": desc[f"m{i}"],
                               "final": f"m{i}" in M.F} for i, g in enumerate(clases)],
                   "tabla": [{"estado": q, "inicial": q == M.q0, "final": q in M.F,
                              "dest": {a: M.delta[(q, a)] for a in SIGMA}} for q in M.Q]}

    dibujar("afd_subconjuntos", D.Q, D.q0, D.F, aristas_afd(D), rankdir="LR")
    dibujar("afd_minimo", M.Q, M.q0, M.F, aristas_afd(M), rankdir="LR")

    # --- verificación
    ver = {}
    ok, n_pares = equivalentes(M, U)
    ver["min_vs_union"] = {"ok": ok, "pares": n_pares}
    ok2, n2 = equivalentes(D, U)
    ver["afd_vs_union"] = {"ok": ok2, "pares": n2}
    ok3, n3 = equivalentes(D, E)
    ver["afd_vs_sin_eps"] = {"ok": ok3, "pares": n3}
    # exhaustiva (todas las cadenas de longitud ≤ 7) contra el oráculo
    total = 0
    fallos = {"P1": 0, "P2": 0, "P3": 0, "AFD_min": 0}
    for L in range(0, 8):
        for tup in itertools.product(SIGMA, repeat=L):
            w = "".join(tup)
            ora = oraculo(w)
            total += 1
            for p, A in nfas.items():
                if A.acepta(w) != (p in ora):
                    fallos[p] += 1
            if M.acepta(w) != bool(ora):
                fallos["AFD_min"] += 1
    ver["exhaustiva"] = {"cadenas": total, "longitud_max": 7, "fallos": fallos}
    # pertenencia de las cadenas de ejemplo del modelo formal
    ejemplos = {"P1": (["PNNN", "RPNNNDG"], ["PNNDN", "PNRNN"]),
                "P2": (["DMP", "PMP"], ["MGP", "PMDGP"]),
                "P3": (["DPN", "RD"], ["PND", "RPD"])}
    R["ejemplos"] = {p: {"dentro": [(w, nfas[p].acepta(w)) for w in a], "fuera": [(w, nfas[p].acepta(w)) for w in b]}
                     for p, (a, b) in ejemplos.items()}
    R["verificacion"] = ver

    # --- trazas a mano (para la defensa)
    def traza(w):
        q, ruta = M.q0, [M.q0]
        for a in w:
            q = M.delta[(q, a)]
            ruta.append(q)
        return ruta, q in M.F

    R["trazas"] = {w: {"ruta": traza(w)[0], "acepta": traza(w)[1]} for w in ("RPND", "PNNDMGP", "PMP", "PNNNR")}

    # --- monitor: métricas y tiempos
    val = mon.leer_sesiones(os.path.join(RAIZ, "datos", "validacion.csv"))
    real = {s: v[1] == "anómala" for s, v in val.items()}
    tipos = {s: v[2] for s, v in val.items()}
    pred = {s: M.acepta(v[0]) for s, v in val.items()}
    R["metricas_val"] = mon.evaluar(list(val), pred, real)
    por_patron = {}
    for p, A in nfas.items():
        pp = {s: A.acepta(v[0]) for s, v in val.items()}
        rp = {s: p in tipos[s].split("+") for s in val}
        por_patron[p] = mon.evaluar(list(val), pp, rp)
    R["metricas_val_patron"] = por_patron
    clave = mon.leer_clave(os.path.join(RAIZ, "datos", "clave_prueba.csv"))
    pru = mon.leer_sesiones(os.path.join(RAIZ, "datos", "prueba.csv"))
    real_p = {s: clave[s][0] == "anómala" for s in pru}
    pred_p = {s: M.acepta(v[0]) for s, v in pru.items()}
    R["metricas_prueba"] = mon.evaluar(list(pru), pred_p, real_p)
    casi = {s for s, v in val.items() if v[1] == "normal" and oraculo_casi(v[0])}
    R["casi_val"] = {"n": len(casi), "falsos_positivos": sum(1 for s in casi if pred[s])}
    # prueba de sensibilidad: dos modelados erróneos de los patrones (para analizar errores)
    def variante_nn(w):   # P1 mal modelado como «contiene NN»
        return "NN" in w or "MP" in w or (w.find("D") != -1 and "P" not in w[:w.find("D")])

    def variante_d(w):    # P3 mal modelado como «contiene D»
        return "NNN" in w or "MP" in w or "D" in w

    R["sensibilidad"] = {
        "P1_como_NN": mon.evaluar(list(val), {s: variante_nn(v[0]) for s, v in val.items()}, real),
        "P3_como_contiene_D": mon.evaluar(list(val), {s: variante_d(v[0]) for s, v in val.items()}, real)}
    R["n_sesiones"] = {"val": len(val), "pru": len(pru), "val_anomalas": sum(real.values()),
                       "pru_anomalas": sum(real_p.values()),
                       "eventos_val": sum(len(v[0]) for v in val.values()),
                       "por_patron_val": {p: sum(1 for t in tipos.values() if p in t.split("+")) for p in ("P1", "P2", "P3")}}
    cadenas = [v[0] for v in val.values()]
    largos = [len(c) for c in cadenas]
    R["largos"] = {"min": min(largos), "max": max(largos), "media": sum(largos) / len(largos)}

    def tres_afnd(w):
        return [nfas["P1"].acepta(w), nfas["P2"].acepta(w), nfas["P3"].acepta(w)]

    tiempos = {"AFND P1+P2+P3 (separados)": medir(tres_afnd, cadenas),
               "AFND unido con ε": medir(U.acepta, cadenas),
               "AFND sin ε": medir(E.acepta, cadenas),
               "AFD (subconjuntos)": medir(D.acepta, cadenas),
               "AFD mínimo": medir(M.acepta, cadenas, 80)}
    R["tiempos"] = {k: {"total_ms": v * 1000, "us_por_sesion": v * 1e6 / len(cadenas)} for k, v in tiempos.items()}
    json.dump(R, open(os.path.join(INF, "resultados.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print("Estados/transiciones:",
          {p: (len(A.Q), A.n_transiciones()) for p, A in nfas.items()},
          "unión", (len(U.Q), U.n_transiciones()), "sin ε", (len(E.Q), E.n_transiciones()),
          "AFD", (len(D.Q), D.n_transiciones()), "mín", (len(M.Q), M.n_transiciones()))
    print("Verificación:", json.dumps(ver, ensure_ascii=False))
    print("Métricas val:", R["metricas_val"])
    print("Métricas prueba:", R["metricas_prueba"])
    print("Casi anómalas:", R["casi_val"])
    for k, v in R["tiempos"].items():
        print(f"  {k}: {v['us_por_sesion']:.2f} µs/sesión")


def oraculo_casi(w):
    from generador import es_casi_anomala
    return es_casi_anomala(w)


if __name__ == "__main__":
    main()
