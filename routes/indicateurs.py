import os
import io
import json
import requests
import shutil
import subprocess
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from draw_graphs import class_score_graph, evolution_graph, commit_graph 

from flask import Flask, request, render_template, redirect, url_for, Response
from flask import current_app as app
from audit_utils import (
    lancer_audit,
)

# ---------- Indicateurs par TD (pour /stats de la classe) – exemples ----------
@app.route('/indicateurs/graph.png')
def indicateurs_graph():
    response = requests.get("http://127.0.0.1:5000/api/indicateurs")
    data = response.json()

    plt.figure(figsize=(10, 5))
    auteurs = set()
    for td_data in data.values():
        auteurs.update(td_data.keys())
    auteurs = sorted(list(auteurs))
    td_names = list(data.keys())

    width = 0.2
    x = range(len(auteurs))

    for i, td in enumerate(td_names):
        scores = [data[td].get(auteur, {}).get("score", 0) for auteur in auteurs]
        plt.bar([xi + i * width for xi in x], scores, width=width, label=td)

    plt.xticks([xi + width for xi in x], auteurs, rotation=45)
    plt.ylabel("Score d'implication")
    plt.title("Scores par auteur et TD")
    plt.legend()
    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    plt.close()
    return Response(buf.getvalue(), mimetype='image/png')


@app.route('/indicateurs/grouped-graph.png')
def grouped_scores_graph():
    response = requests.get("http://127.0.0.1:5000/api/indicateurs/groupes")
    data = response.json()

    tds = list(data.keys())
    groupes = set()
    for td in data:
        groupes.update(data[td].keys())
    groupes = sorted(groupes)

    width = 0.15
    x = range(len(tds))
    plt.figure(figsize=(10, 5))

    for i, groupe in enumerate(groupes):
        scores = [data[td].get(groupe, 0) for td in tds]
        offset = [(pos + (i - len(groupes)/2) * width) for pos in x]
        plt.bar(offset, scores, width=width, label=groupe)

    plt.xticks(range(len(tds)), tds)
    plt.xlabel("TD")
    plt.ylabel("Score moyen")
    plt.title("Scores par groupe et par TD")
    plt.legend()
    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format="png")
    buf.seek(0)
    plt.close()
    return Response(buf.getvalue(), mimetype="image/png")