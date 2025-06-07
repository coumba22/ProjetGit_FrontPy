import os
import io
import json
import requests
import shutil
import subprocess
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from ..draw_graphs import class_score_graph, evolution_graph, commit_graph 

from flask import Flask, request, render_template, redirect, url_for, Response
from flask import current_app as app

# si vous avez un endpoint externe pour stats dépôt unique
BACKEND_PORT = os.getenv("BACKEND_PORT")
STATS_API_URL = f"http://127.0.0.1:{BACKEND_PORT}/api/stats"

from flask import Blueprint
stats_bp = Blueprint('stats_bp', __name__)


# ---------- Statistiques de la classe ----------
@stats_bp.route('/stats')
def stats_page():
    stats_response = requests.post(STATS_API_URL)

    try:
        resultats_classe = stats_response.json()
    except Exception:
        return f"Erreur JSONDecode lors de l'analyse des stats : contenu reçu = {stats_response.text}"
    if not stats_response.ok or resultats_classe.get("status") != "success":
        return f"Erreur lors de l'analyse des stats : {stats_response.text}"

    graph_classe_url= class_score_graph(resultats_classe['resultatsClasse'])

    # 4) Renvoyer le template
    return render_template(
        'stats.html',
        resultats_classe=resultats_classe['resultatsClasse'],
        graph_classe_url=graph_classe_url
    )


@stats_bp.route('/stats/auteur/<nom>')
def auteur_details(nom):
    """
    Exemple de route si vous voulez récupérer un auteur spécifique
    d’un dépôt unique via l’API externe (API_URL). Pas utilisé dans la vue de la classe.
    """
    response = requests.get(API_URL)
    data = response.json()
    author_data = data.get("authors", {}).get(nom)
    if not author_data:
        return f"Auteur '{nom}' introuvable", 404
    return render_template("auteur.html", nom=nom, stats=author_data)




# ---------- Routes pour afficher les images des statistiques d’un dépôt unique ----------
@stats_bp.route('/stats/graph.png')
def stats_graph():
    response = requests.get(API_URL)
    data = response.json()

    authors = list(data["authors"].keys())
    commits = [data["authors"][a]["commits"] for a in authors]

    plt.figure(figsize=(8, 4))
    plt.bar(authors, commits, color='mediumseagreen')
    plt.title('Nombre de commits par auteur')
    plt.xlabel('Auteur')
    plt.ylabel('Commits')

    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    plt.close()
    return Response(buf.getvalue(), mimetype='image/png')


@stats_bp.route('/stats/additions.png')
def additions_graph():
    response = requests.get(API_URL)
    data = response.json()

    authors = list(data["authors"].keys())
    additions = [data["authors"][a]["additions"] for a in authors]

    plt.figure(figsize=(8, 4))
    plt.bar(authors, additions, color='dodgerblue')
    plt.title('Additions par auteur')
    plt.xlabel('Auteur')
    plt.ylabel('Lignes ajoutées')

    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    plt.close()
    return Response(buf.getvalue(), mimetype='image/png')


@stats_bp.route('/stats/deletions.png')
def deletions_graph():
    response = requests.get(API_URL)
    data = response.json()

    authors = list(data["authors"].keys())
    deletions = [data["authors"][a]["deletions"] for a in authors]

    plt.figure(figsize=(8, 4))
    plt.bar(authors, deletions, color='crimson')
    plt.title('Suppressions par auteur')
    plt.xlabel('Auteur')
    plt.ylabel('Lignes supprimées')

    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    plt.close()
    return Response(buf.getvalue(), mimetype='image/png')


@stats_bp.route('/stats/files_changed.png')
def files_changed_graph():
    response = requests.get(API_URL)
    data = response.json()

    authors = list(data["authors"].keys())
    files_changed = [data["authors"][a]["files_changed"] for a in authors]

    plt.figure(figsize=(8, 4))
    plt.bar(authors, files_changed, color='orange')
    plt.title('Fichiers modifiés par auteur')
    plt.xlabel('Auteur')
    plt.ylabel('Fichiers modifiés')

    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    plt.close()
    return Response(buf.getvalue(), mimetype='image/png')