#!/usr/bin/env python3
"""
McNemar pentru comparatiile de ablatie DB-Navigator (test pereche, aceleasi 100 de intrebari).

Completeaza RESULTS cu rezultatele per-intrebare (1 = corect, 0 = gresit) pentru fiecare
configuratie, IN ACEEASI ORDINE a intrebarilor la toate configuratiile. Apoi:  python mcnemar.py

Foloseste testul exact binomial (two-sided, p=0,5), potrivit pentru numar mic de perechi
discordante. Nu necesita librarii externe (doar stdlib).
"""
import math

# ============================================================
# OPTIUNEA A - lipeste rezultatele per-intrebare (liste de 0/1, cate una per config).
# Toate listele trebuie sa aiba aceeasi lungime (ex. 100).
# ============================================================
RESULTS = {
    "A": [],   # ex. [1,0,1,1,0, ...]  (68,8% -> ~69 de 1 din 100)
    "B": [],   # 71,9%
    "C": [],   # 74,0%
    "D": [],   # 70,8%
    "E": [],   # 69,8%
    "F": [],   # 76,0%
}

# ============================================================
# OPTIUNEA B - incarca dintr-un CSV cu coloanele: question_id,config,correct
# Decomenteaza si adapteaza la exportul tau din query_log / public.benchmark:
# ------------------------------------------------------------
import csv
from collections import defaultdict
rows = defaultdict(dict)
with open("benchmark_results.csv", newline="") as f:
    for r in csv.DictReader(f):
        rows[r["question_id"]][r["config"]] = int(r["correct"])
order = sorted(rows)
RESULTS = {cfg: [rows[q][cfg] for q in order] for cfg in ["A", "B", "C", "D", "E", "F"]}


def mcnemar(x, y):
    if len(x) != len(y):
        raise ValueError("listele trebuie sa aiba aceeasi lungime")
    # b = primul corect si al doilea gresit ; c = invers (perechile discordante)
    b = sum(1 for xi, yi in zip(x, y) if xi == 1 and yi == 0)
    c = sum(1 for xi, yi in zip(x, y) if xi == 0 and yi == 1)
    n = b + c
    if n == 0:
        p_exact = 1.0
    else:
        k = min(b, c)
        p_exact = min(1.0, 2.0 * sum(math.comb(n, i) for i in range(k + 1)) * (0.5 ** n))
    chi2_cc = ((abs(b - c) - 1) ** 2) / n if n > 0 else 0.0
    return b, c, p_exact, chi2_cc


def acc(v):
    return 100.0 * sum(v) / len(v) if v else float("nan")


print(f"{'pereche':>9} | {'acc1':>6} {'acc2':>6} | {'b':>4} {'c':>4} | {'p (exact)':>10} | {'chi2(cc)':>8} | verdict")
print("-" * 78)
for a, bb in PAIRS:
    va, vb = RESULTS.get(a), RESULTS.get(bb)
    if not va or not vb:
        print(f"{a+' vs '+bb:>9} | (lipsesc datele pentru {a} sau {bb} - completeaza RESULTS)")
        continue
    b, c, p, chi2 = mcnemar(va, vb)
    verdict = "SEMNIFICATIV (p<0,05)" if p < 0.05 else "in zgomot (nesemnificativ)"
    a1 = f"{acc(va):.1f}"
    a2 = f"{acc(vb):.1f}"
    print(f"{a+' vs '+bb:>9} | {a1:>6} {a2:>6} | {b:>4} {c:>4} | {p:>10.4f} | {chi2:>8.2f} | {verdict}")

print()
print("Interpretare rapida:")
print(" - A vs C si A vs F ar trebui sa fie semnificative (efectele tale reale).")
print(" - C vs E: daca e SEMNIFICATIV -> interferenta e reala, sustii Î2 tare.")
print("           daca e in zgomot   -> spune doar 'stivuirea nu a batut C', nu 'a daunat'.")
