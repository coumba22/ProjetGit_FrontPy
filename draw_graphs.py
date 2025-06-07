import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime

def class_score_graph(resultats_classe):
    # 3) Générer un graphique « Score global par étudiant »
    noms = list(resultats_classe.keys())
    scores = [
        resultats_classe[n]["score_global"] if "score_global" in resultats_classe[n] else 0.0
        for n in noms
    ]

    # Créer le dossier si nécessaire
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
        # URL relative à passer au template
        graph_classe_url = "/" + graph_classe_path.replace("\\", "/")
    except Exception:
        graph_classe_url = None
    return graph_classe_url

def commit_graph(result_audit):

    commits_par_auteur = result_audit['commits_par_auteur']
    base_name = result_audit['base_name']

    # Création dossier images
    os.makedirs("static/images", exist_ok=True)

    # Graph Commits
    try:
        fig, ax = plt.subplots(figsize=(8,4))
        ax.bar(commits_par_auteur.keys(), commits_par_auteur.values(), color='skyblue')
        ax.set_title("Commits par auteur")
        ax.tick_params(axis='x', rotation=45)
        plt.tight_layout()
        p = f"static/images/{base_name}_commits.png"
        plt.savefig(p); plt.close(fig)
        graph_commits_url = p.replace("\\", "/")
    except:
        graph_commits_url = None

    return graph_commits_url

def evolution_graph(result_audit):

    evolution_par_auteur = result_audit['evolution_par_auteur']
    deadline = result_audit['deadline']
    base_name = result_audit['base_name']

    # Création dossier images
    os.makedirs("static/images", exist_ok=True)

    # Graph Évolution
    try:
        fig, ax = plt.subplots(figsize=(10,5))
        for au, dates in evolution_par_auteur.items():
            xs = sorted(dates)
            ys = [dates[d] for d in xs]
            dx = [datetime.strptime(d, "%Y-%m-%d") for d in xs]
            ax.plot(dx, ys, marker='o', label=au)
        if deadline:
            dl = datetime.strptime(deadline, "%Y-%m-%d")
            ax.axvline(dl, color='black', linestyle='--', label='Deadline')
        ax.set_title("Évolution temporelle")
        ax.set_xlabel("Date"); ax.set_ylabel("Commits")
        ax.tick_params(axis='x', rotation=45)
        ax.legend()
        plt.tight_layout()
        p2 = f"static/images/{base_name}_evolution.png"
        plt.savefig(p2); plt.close(fig)
        graph_evolution_url = p2.replace("\\", "/")
    except:
        graph_evolution_url = None

    return graph_evolution_url