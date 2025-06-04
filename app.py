import os
import io
import requests
import shutil
import subprocess
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from flask import Flask, request, render_template, redirect, url_for, Response

# On importe toutes les fonctions utilitaires inclues dans audit_utils.py
from audit_utils import (
    lancer_audit,
    nettoyer_nom_repo,
    charger_tds,
    analyser_classe
)

# Si vous utilisez GitStats localement, vous pouvez conserver cette constante
GITSTATS_PATH = r"C:\Users\NCD\AppData\Local\Programs\Python\Python38-32\Scripts\gitstats.exe"

app = Flask(__name__)

# URL de l’API de statistiques (back-end ). 
API_URL = "http://127.0.0.1:5000/api/stats"


# ---------- Page d’accueil ----------
@app.route('/')
def index():
    return render_template('index.html')


# ---------- Route pour l’audit « manuel » d’un dépôt unique (micro-UI) ----------
@app.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    if request.method == 'POST':
        repo_url = request.form.get('repo_url', '').strip()
        token = request.form.get('token', '').strip() or None

        if not repo_url:
            # Si l’utilisateur n’a pas saisi d’URL, on réaffiche l’erreur
            return render_template('dashboard.html', error="URL manquante.", result=None)

        # Lancer l’audit (PyDriller, Radon, GitStats via API backend…)
        result = lancer_audit(repo_url, token)

        return render_template('dashboard.html', repo_url=repo_url, result=result)

    # GET
    return render_template('dashboard.html', repo_url=None, result=None)



# ---------- Route de redirection vers GitStats pour un dépôt cloné ----------
@app.route('/analyser', methods=['POST'])
def analyser():
    """
    Si vous voulez conserver la fonctionnalité « lancer GitStats sur un dépôt cloné » séparément :
      - clone sous temp_repos/<nom_repo>
      - exécute GitStats (chemin dans GITSTATS_PATH)
      - redirige vers /gitstats/<repo>
    """
    repo_url = request.form.get('repo_url')
    if not repo_url:
        return "URL manquante", 400

    nom_repo    = nettoyer_nom_repo(repo_url)
    clone_path  = os.path.join("temp_repos", nom_repo)
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
    """
    Affiche la page qui contient l’iframe pointant vers static/gitstats_report/<repo>/index.html
    """
    return render_template('gitstats_view.html', repo=repo)


# ---------- Route « Stats de la classe » (multiples dépôts) ----------
@app.route('/stats')
def stats_page():
    """
    Lit tds.json, puis appelle analyser_classe() pour tous les étudiants.
    Transmet à stats.html un dict { nom_etudiant: résultats }.
    """
    # 1) Charger tds.json
    liste_etudiants, token_communs, deadlines_map = charger_tds()

    # 2) Lancer l’analyse pour chaque étudiant
    #    (poids par défaut : None)
    résultats_classe = analyser_classe(
        liste_etudiants=liste_etudiants,
        token_communs=token_communs,
        deadlines=deadlines_map,
        poids=None
    )

    return render_template('stats.html', résultats_classe=résultats_classe)


# ---------- Détails d’un auteur (route existante) ----------
@app.route('/stats/auteur/<nom>')
def auteur_details(nom):
    """
    Si vous souhaitez conserver la vue individuelle d’un auteur unique
    (basée sur l’API externe API_URL), on laisse ce code en l’état.
    """
    response = requests.get(API_URL)
    data = response.json()
    author_data = data["authors"].get(nom)
    if not author_data:
        return f"Auteur '{nom}' introuvable", 404
    return render_template("auteur.html", nom=nom, stats=author_data)


# ---------- Route « graphique commits par auteur » (issue du back-end) ----------
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


# ---------- Indicateurs « TD » (si utilisés) ----------
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
    # On s’assure que le dossier d’images existe
    os.makedirs("static/images", exist_ok=True)
    app.run(debug=True, port=5001)
