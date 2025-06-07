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

API_URL = "http://127.0.0.1:5000/api/stats"  
# si vous avez un endpoint externe pour stats dépôt unique
AUDIT_API_URL = "http://127.0.0.1:4000/api/audit" 



# ---------- Audit d’un dépôt unique (dashboard) ----------
@app.route('/audit', methods=['GET', 'POST'])
def audit():
    """
    Formulaire pour lancer un audit sur un dépôt unique.
    Lorsque le formulaire est soumis (POST), on appelle lancer_audit()
    et on affiche le résultat dans dashboard.html.
    """
    if request.method == 'POST':
        repo_url = request.form.get('repo_url')
        # (Optionnel) vous pouvez également accepter une date de deadline
        deadline = request.form.get('deadline', None)

        audit_response = requests.post(AUDIT_API_URL)
        try:
            result_audit = audit_response.json()
            #app.logger.debug(f"Réponse analyse : {data}")
        except Exception:
            return f"Erreur JSONDecode lors de l'analyse de l'audit : contenu reçu = {audit_response.text}"
        if not audit_response.ok or result_audit.get("status") != "success":
            return f"Erreur lors de l'analyse de l'audit : {audit_response.text}"
        
        graph_evolution_url = evolution_graph(result_audit)
        graph_commit_url = commit_graph(result_audit)

        return render_template('dashboard.html', result=result_audit, repo_url=repo_url)
    # En GET, on affiche simplement un dashboard vide (sans résultat)
    return render_template(
        'dashboard.html', 
        result_audit=result_audit,
        graph_evolution_url=graph_evolution_url,
        graph_commit_url=graph_commit_url
    )


@app.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    """
    Alias de /audit pour supporter les deux URL.
    """
    if request.method == "POST":
        repo_url = request.form.get("repo_url")
        token = request.form.get("token", "")
        deadline = request.form.get("deadline", None)
        result = lancer_audit(repo_url, token, deadline)
        return render_template("dashboard.html", result=result, repo_url=repo_url)
    return render_template("dashboard.html", result=None)