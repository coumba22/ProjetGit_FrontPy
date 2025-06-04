import os
import io
import json
import requests
import shutil
import subprocess
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from flask import Flask, request, render_template, redirect, url_for, Response
from audit_utils import (
    lancer_audit,
    nettoyer_nom_repo,
    analyser_classe,
    charger_tds
)

GITSTATS_PATH = r"C:\Users\NCD\AppData\Local\Programs\Python\Python38-32\Scripts\gitstats.exe"

app = Flask(__name__)
API_URL = "http://127.0.0.1:5000/api/stats"


# ---------- Page d'accueil ----------
@app.route('/')
def index():
    return render_template('index.html')


# ---------- Audit d’un dépôt unique (dashboard) ----------
@app.route('/audit', methods=['GET', 'POST'])
def audit():
    """
    Formulaire pour lancer un audit sur un dépôt unique.
    Redirige ou affiche les résultats dans dashboard.html.
    """
    if request.method == 'POST':
        repo_url = request.form.get('repo_url')
        token = request.form.get('token', '')
        result = lancer_audit(repo_url, token)
        return render_template('dashboard.html', result=result, repo_url=repo_url)
    return render_template('dashboard.html', result=None)


@app.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    """
    Même fonction que /audit : on reprend juste la logique pour la route /dashboard.
    """
    if request.method == "POST":
        repo_url = request.form.get("repo_url")
        token = request.form.get("token", "")
        result = lancer_audit(repo_url, token)
        return render_template("dashboard.html", result=result, repo_url=repo_url)
    return render_template("dashboard.html", result=None)


# ---------- GitStats (cloner + générer rapport complet) ----------
@app.route('/analyser', methods=['POST'])
def analyser():
    repo_url = request.form.get('repo_url')
    if not repo_url:
        return "URL manquante", 400

    nom_repo = nettoyer_nom_repo(repo_url)
    clone_path = os.path.join("temp_repos", nom_repo)
    rapport_path = os.path.join("static", "gitstats_report", nom_repo)

    if os.path.exists(clone_path):
        shutil.rmtree(clone_path)
    if os.path.exists(rapport_path):
        shutil.rmtree(rapport_path)

    try:
        subprocess.check_call(["git", "clone", repo_url, clone_path])
    except subprocess.CalledProcessError:
        return "Erreur lors du clonage du dépôt", 500

    try:
        subprocess.check_call([GITSTATS_PATH, clone_path, rapport_path])
    except subprocess.CalledProcessError:
        return "Erreur lors de l'exécution de GitStats", 500

    return redirect(url_for('voir_gitstats', repo=nom_repo))


@app.route('/gitstats/<repo>')
def voir_gitstats(repo):
    return render_template('gitstats_view.html', repo=repo)


# ---------- Statistiques de la classe ----------
@app.route('/stats')
def stats_page():
    """
    Charge tds.json, analyse chaque dépôt d’étudiant, puis affiche
    le tableau complet dans stats.html.
    """
    liste_etudiants, token_communs, deadlines_map = charger_tds()
    if not liste_etudiants:
        return render_template('stats.html', résultats_classe={})

    # On ne passe pas de pondérations ici (None) => valeurs par défaut
    résultats_classe = analyser_classe(liste_etudiants, token_communs, deadlines_map, poids=None)

    # Générer un graphique « score global par étudiant »
    noms = list(résultats_classe.keys())
    scores = [résultats_classe[n]["score_global"] if "score_global" in résultats_classe[n] else 0.0 for n in noms]

    os.makedirs("static/images", exist_ok=True)
    graph_classe_path = "static/images/classe_score.png"
    try:
        plt.figure(figsize=(8, 4))
        plt.bar(noms, scores, color='mediumseagreen')
        plt.title("Score global par étudiant")
        plt.xticks(rotation=45)
        plt.tight_layout()
        plt.savefig(graph_classe_path)
        plt.close()
        graph_classe_url = "/" + graph_classe_path.replace("\\", "/")
    except Exception:
        graph_classe_url = None

    return render_template(
        'stats.html',
        résultats_classe=résultats_classe,
        graph_classe_url=graph_classe_url
    )


@app.route('/stats/auteur/<nom>')
def auteur_details(nom):
    """
    (Optionnel) Si vous souhaitez afficher les détails d’un auteur spécifique
    au sein de l’analyse d’un dépôt unique.
    """
    response = requests.get(API_URL)
    data = response.json()
    author_data = data["authors"].get(nom)
    if not author_data:
        return f"Auteur '{nom}' introuvable", 404
    return render_template("auteur.html", nom=nom, stats=author_data)


# ---------- Routes pour afficher les images des statistiques d’un dépôt unique ----------
@app.route('/stats/graph.png')
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


@app.route('/stats/additions.png')
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


@app.route('/stats/deletions.png')
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


@app.route('/stats/files_changed.png')
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


# ---------- Indicateurs (par TD / classe / …) - exemple pour `/stats` de la classe ----------
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


# ---------- Lancement de l’application ----------
if __name__ == '__main__':
    os.makedirs("static/images", exist_ok=True)
    app.run(debug=True, port=5001)
