import os

import shutil
import subprocess
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from flask import Flask, request, render_template, redirect, url_for, Response
from ..audit_utils import (
    lancer_audit,
    nettoyer_nom_repo,
    analyser_classe,
    charger_tds
)

# Chemin vers l’exécutable gitstats (pour la route /analyser)
GITSTATS_PATH = r"C:\Users\NCD\AppData\Local\Programs\Python\Python38-32\Scripts\gitstats.exe"

from flask import Blueprint
gitstats_bp = Blueprint('gitstats_bp', __name__)


# ---------- GitStats : cloner + générer rapport complet ----------
@gitstats_bp.route('/analyser', methods=['POST'])
def analyser():
    """
    Route qui clone un dépôt et exécute l’exécutable GitStats pour
    générer le rapport HTML complet. Ensuite, on redirige vers une page
    qui chargera l’iframe /static/gitstats_report/<repo>/index.html.
    """
    repo_url = request.form.get('repo_url')
    if not repo_url:
        return "URL manquante", 400

    nom_repo = nettoyer_nom_repo(repo_url)
    clone_path = os.path.join("temp_repos", nom_repo)
    rapport_path = os.path.join("static", "gitstats_report", nom_repo)

    # Suppression des anciens dossiers s’ils existent
    if os.path.exists(clone_path):
        shutil.rmtree(clone_path)
    if os.path.exists(rapport_path):
        shutil.rmtree(rapport_path)

    # 1) Cloner le dépôt
    try:
        subprocess.check_call(["git", "clone", repo_url, clone_path])
    except subprocess.CalledProcessError as e:
        return f"Erreur lors du clonage du dépôt : {e}", 500

    # 2) Exécuter GitStats
    try:
        subprocess.check_call([GITSTATS_PATH, clone_path, rapport_path])
    except subprocess.CalledProcessError as e:
        return f"Erreur lors de l'exécution de GitStats : {e}", 500

    # 3) Rediriger vers la vue qui chargera l’iframe du rapport
    return redirect(url_for('voir_gitstats', repo=nom_repo))


@gitstats_bp.route('/gitstats/<repo>')
def voir_gitstats(repo):
    """
    Affiche le template gitstats_view.html, qui doit inclure une iframe
    pointant sur /static/gitstats_report/<repo>/index.html
    """
    return render_template('gitstats_view.html', repo=repo)