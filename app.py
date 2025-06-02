import os
import io
import requests
import shutil
import subprocess
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from flask import Flask, request, render_template, redirect, url_for, Response
from audit_utils import lancer_audit, nettoyer_nom_repo

GITSTATS_PATH = r"C:\Users\NCD\AppData\Local\Programs\Python\Python38-32\Scripts\gitstats.exe"

app = Flask(__name__)
API_URL = "http://127.0.0.1:5000/api/stats"


# ---------- Page d'accueil ----------
@app.route('/')
def index():
    return render_template('index.html')


# ---------- Routes audit/dashboard ----------
@app.route("/dashboard", methods=["GET", "POST"])
@app.route("/audit", methods=["GET", "POST"])
def dashboard():
    if request.method == "POST":
        repo_url = request.form.get("repo_url")
        token = request.form.get("token")
        result = lancer_audit(repo_url, token)
        return render_template("dashboard.html", result=result, repo_url=repo_url)
    return render_template("dashboard.html", result=None)


# ---------- GitStats manuel ----------
@app.route('/analyser', methods=['POST'])
def analyser():
    repo_url = request.form.get('repo_url')
    if not repo_url:
        return "URL manquante", 400

    nom_repo = nettoyer_nom_repo(repo_url)
    clone_path = os.path.join("temp_repo")
    rapport_path = os.path.join("static", "gitstats_report")

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


# ---------- Statistiques ----------
@app.route('/stats')
def stats_page():
    response = requests.get(API_URL)
    data = response.json()
    return render_template('stats.html', data=data)


@app.route('/stats/auteur/<nom>')
def auteur_details(nom):
    response = requests.get(API_URL)
    data = response.json()
    author_data = data["authors"].get(nom)
    if not author_data:
        return f"Auteur '{nom}' introuvable", 404
    return render_template("auteur.html", nom=nom, stats=author_data)


@app.route('/stats/graph.png')
def stats_graph():
    response = requests.get(API_URL)
    data = response.json()
    authors = list(data["authors"].keys())
    commits = [data["authors"][a]["commits"] for a in authors]

    plt.figure(figsize=(8, 4))
    plt.bar(authors, commits)
    plt.title('Commits par auteur')
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
    plt.bar(authors, additions)
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
    plt.bar(authors, deletions)
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
    plt.bar(authors, files_changed)
    plt.title('Fichiers modifiés par auteur')
    plt.xlabel('Auteur')
    plt.ylabel('Fichiers modifiés')

    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    plt.close()
    return Response(buf.getvalue(), mimetype='image/png')


# ---------- Indicateurs ----------
@app.route('/indicateurs/graph.png')
def indicateurs_graph():
    response = requests.get("http://127.0.0.1:5000/api/indicateurs")
    data = response.json()

    auteurs = set()
    for td_data in data.values():
        auteurs.update(td_data.keys())
    auteurs = sorted(list(auteurs))
    td_names = list(data.keys())

    width = 0.2
    x = range(len(auteurs))

    plt.figure(figsize=(10, 5))
    for i, td in enumerate(td_names):
        scores = [data[td].get(auteur, {}).get("score", 0) for auteur in auteurs]
        plt.bar([xi + i * width for xi in x], scores, width=width, label=td)

    plt.xticks([xi + width for xi in x], auteurs, rotation=45)
    plt.ylabel("Score")
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
    groupes = sorted({g for td in data.values() for g in td})

    width = 0.15
    x = range(len(tds))
    plt.figure(figsize=(10, 5))

    for i, groupe in enumerate(groupes):
        scores = [data[td].get(groupe, 0) for td in tds]
        offsets = [xi + (i - len(groupes)/2) * width for xi in x]
        plt.bar(offsets, scores, width=width, label=groupe)

    plt.xticks(range(len(tds)), tds)
    plt.xlabel("TD")
    plt.ylabel("Score moyen")
    plt.title("Scores par groupe et TD")
    plt.legend()
    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format="png")
    buf.seek(0)
    plt.close()
    return Response(buf.getvalue(), mimetype="image/png")


# ---------- Lancement ----------
if __name__ == '__main__':
    os.makedirs("static/images", exist_ok=True)
    app.run(debug=True, port=5001)
