"""Autómatas finitos: simulación, unión con ε, eliminación de ε,
construcción de subconjuntos y minimización (partición de Moore).

Convención: el símbolo "" representa una transición ε.
"""
from collections import deque

SIGMA = ["R", "P", "N", "D", "M", "G"]
EPS = ""


class AF:
    """Autómata finito (AFND con o sin ε).  delta: {(estado, símbolo): {estados}}"""

    def __init__(self, estados, sigma, delta, inicial, finales):
        self.Q = list(estados)
        self.sigma = list(sigma)
        self.delta = {k: set(v) for k, v in delta.items()}
        self.q0 = inicial
        self.F = set(finales)

    # ---------- simulación ----------
    def clausura(self, S):
        pila, res = list(S), set(S)
        while pila:
            q = pila.pop()
            for r in self.delta.get((q, EPS), ()):
                if r not in res:
                    res.add(r)
                    pila.append(r)
        return res

    def paso(self, S, a):
        sig = set()
        for q in S:
            sig |= self.delta.get((q, a), set())
        return self.clausura(sig)

    def acepta(self, w):
        S = self.clausura({self.q0})
        for a in w:
            S = self.paso(S, a)
            if not S:
                return False
        return bool(S & self.F)

    # ---------- métricas de tamaño ----------
    def n_transiciones(self):
        return sum(len(v) for v in self.delta.values())

    def transiciones(self):
        for (q, a), dst in sorted(self.delta.items(), key=lambda x: (str(x[0][0]), x[0][1])):
            for r in sorted(dst):
                yield q, a, r


class AFD:
    """AFD completo. delta: {(estado, símbolo): estado}"""

    def __init__(self, estados, sigma, delta, inicial, finales):
        self.Q = list(estados)
        self.sigma = list(sigma)
        self.delta = dict(delta)
        self.q0 = inicial
        self.F = set(finales)

    def acepta(self, w):
        q = self.q0
        d = self.delta
        for a in w:
            q = d[(q, a)]
        return q in self.F

    def n_transiciones(self):
        return len(self.delta)


# ------------------------------------------------------------------
def union_epsilon(automatas, nuevo_inicial="s"):
    """AFND unido: nuevo estado inicial con transiciones ε a cada inicial."""
    Q, delta, F = [nuevo_inicial], {}, set()
    sigma = automatas[0].sigma
    delta[(nuevo_inicial, EPS)] = set()
    for A in automatas:
        Q += A.Q
        F |= A.F
        for k, v in A.delta.items():
            delta[k] = set(v)
        delta[(nuevo_inicial, EPS)].add(A.q0)
    return AF(Q, sigma, delta, nuevo_inicial, F)


def eliminar_epsilon(A):
    """δ'(q,a) = ε-clausura( δ( ε-clausura(q), a ) );  F' = {q | clausura(q) ∩ F ≠ ∅}."""
    delta = {}
    for q in A.Q:
        cl = A.clausura({q})
        for a in A.sigma:
            dst = set()
            for p in cl:
                dst |= A.delta.get((p, a), set())
            dst = A.clausura(dst)
            if dst:
                delta[(q, a)] = dst
    F = {q for q in A.Q if A.clausura({q}) & A.F}
    B = AF(A.Q, A.sigma, delta, A.q0, F)
    return podar(B)


def podar(A):
    """Elimina los estados inaccesibles."""
    vis, cola = {A.q0}, deque([A.q0])
    while cola:
        q = cola.popleft()
        for a in A.sigma + [EPS]:
            for r in A.delta.get((q, a), ()):
                if r not in vis:
                    vis.add(r)
                    cola.append(r)
    Q = [q for q in A.Q if q in vis]
    delta = {k: v for k, v in A.delta.items() if k[0] in vis}
    return AF(Q, A.sigma, delta, A.q0, A.F & vis)


def subconjuntos(A):
    """Construcción de subconjuntos (solo estados accesibles).
    Devuelve (AFD con estados q0,q1,..., tabla[(nombre, conjunto, {a: nombre})])."""
    ini = frozenset(A.clausura({A.q0}))
    nombres = {ini: "q0"}
    orden = [ini]
    cola = deque([ini])
    delta = {}
    while cola:
        S = cola.popleft()
        for a in A.sigma:
            T = frozenset(A.paso(S, a))
            if T not in nombres:
                nombres[T] = f"q{len(nombres)}"
                orden.append(T)
                cola.append(T)
            delta[(nombres[S], a)] = nombres[T]
    finales = {nombres[S] for S in orden if S & A.F}
    D = AFD([nombres[S] for S in orden], A.sigma, delta, "q0", finales)
    tabla = [(nombres[S], S, {a: delta[(nombres[S], a)] for a in A.sigma}) for S in orden]
    return D, tabla


def minimizar(D):
    """Partición de Moore.  Devuelve (AFD mínimo, historial de particiones, clases finales)."""
    vis, cola = {D.q0}, deque([D.q0])
    while cola:
        q = cola.popleft()
        for a in D.sigma:
            r = D.delta[(q, a)]
            if r not in vis:
                vis.add(r)
                cola.append(r)
    Q = [q for q in D.Q if q in vis]
    bloque = {q: (1 if q in D.F else 0) for q in Q}
    historial = []

    def particion(b):
        grupos = {}
        for q in Q:
            grupos.setdefault(b[q], []).append(q)
        return sorted(grupos.values(), key=lambda g: Q.index(g[0]))

    historial.append(particion(bloque))
    while True:
        firma = {q: (bloque[q],) + tuple(bloque[D.delta[(q, a)]] for a in D.sigma) for q in Q}
        ids, nuevo = {}, {}
        for q in Q:
            nuevo[q] = ids.setdefault(firma[q], len(ids))
        if len(set(nuevo.values())) == len(set(bloque.values())):
            break
        bloque = nuevo
        historial.append(particion(bloque))
    clases = particion(bloque)
    nombre_clase = {}
    for i, g in enumerate(clases):
        for q in g:
            nombre_clase[q] = f"m{i}"
    delta = {}
    for g in clases:
        rep = g[0]
        for a in D.sigma:
            delta[(nombre_clase[rep], a)] = nombre_clase[D.delta[(rep, a)]]
    finales = {nombre_clase[q] for q in Q if q in D.F}
    M = AFD([f"m{i}" for i in range(len(clases))], D.sigma, delta, nombre_clase[D.q0], finales)
    return M, historial, clases


def equivalentes(D, A):
    """Equivale a «Compare Equivalence» de JFLAP: explora los pares (estado del AFD,
    conjunto de estados del AFND) y comprueba que la aceptación coincide en todos."""
    ini = (D.q0, frozenset(A.clausura({A.q0})))
    vis, cola = {ini}, deque([ini])
    while cola:
        q, S = cola.popleft()
        if (q in D.F) != bool(S & A.F):
            return False, (q, S)
        for a in D.sigma:
            par = (D.delta[(q, a)], frozenset(A.paso(S, a)))
            if par not in vis:
                vis.add(par)
                cola.append(par)
    return True, len(vis)
