import os
import shutil
import subprocess
import stat
import time
import requests
from urllib.parse import urlparse
from collections import defaultdict, Counter
from datetime import datetime
from pydriller import Repository
from radon.complexity import cc_visit
import matplotlib.pyplot as plt
import psutil


def nettoyer_nom_repo(url):
    path = urlparse(url).path
    repo_name = os.path.basename(path)
    return repo_name.replace(".git", "")


def on_rm_error(func, path, exc_info):
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception as e:
        print(f"❌ Échec suppression {path} : {e}")


def fermer_processus_git(path):
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            if 'git' in proc.info['name'].lower() or 'gitstats' in proc.info['name'].lower():
                if any(path in arg for arg in proc.info['cmdline']):
                    proc.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue


def inject_token_in_url(repo_url, token):
    parsed = urlparse(repo_url)
    path = parsed.path
    if not path.endswith(".git"):
        path += ".git"
    return f"https://{token}@{parsed.netloc}{path}" if token else f"https://{parsed.netloc}{path}"


def lancer_audit(repo_url, token=None, deadline=None):
    repo_path = "temp_repo"
    gitstats_output_path = "static/gitstats_report"

    # Nettoyage
    if os.path.exists(repo_path):
        fermer_processus_git(repo_path)
        shutil.rmtree(repo_path, onerror=on_rm_error)
    if os.path.exists(gitstats_output_path):
        shutil.rmtree(gitstats_output_path, onerror=on_rm_error)

    # Clonage
    url_to_clone = inject_token_in_url(repo_url, token)
    print("🔗 URL clonage utilisée :", url_to_clone)

    try:
        subprocess.check_call(["git", "clone", url_to_clone, repo_path])
        time.sleep(1)
    except subprocess.CalledProcessError:
        return {"error": "❌ Clonage échoué. Vérifie l'URL ou ton token."}

    # Initialisation des structures de données
    commits_par_auteur = Counter()
    fichiers_modifies = Counter()
    complexites = {}
    evolution_par_auteur = defaultdict(lambda: defaultdict(int))
    co_modification = defaultdict(lambda: defaultdict(int))
    auteur_fichiers = defaultdict(set)
    ajouts_par_auteur = defaultdict(int)
    suppressions_par_auteur = defaultdict(int)
    total_lignes = 0

    try:
        for commit in Repository(repo_path).traverse_commits():
            auteur = commit.author.name or "Inconnu"
            date = commit.author_date.strftime("%Y-%m-%d")
            commits_par_auteur[auteur] += 1
            evolution_par_auteur[auteur][date] += 1

            for mod in commit.modified_files:
                fichier = mod.new_path or mod.old_path
                if not fichier:
                    continue
                fichiers_modifies[fichier] += 1
                auteur_fichiers[auteur].add(fichier)

                for autre_auteur, fichiers in auteur_fichiers.items():
                    if autre_auteur != auteur and fichier in fichiers:
                        co_modification[fichier][auteur] += 1
                        co_modification[fichier][autre_auteur] += 1

                ajouts = mod.added_lines or 0
                suppressions = mod.deleted_lines or 0
                ajouts_par_auteur[auteur] += ajouts
                suppressions_par_auteur[auteur] += suppressions
                total_lignes += ajouts + suppressions

                if fichier.endswith(".py"):
                    full_path = os.path.join(repo_path, fichier)
                    if os.path.exists(full_path):
                        try:
                            with open(full_path, 'r', encoding='utf-8') as f:
                                code = f.read()
                                res = cc_visit(code)
                                score = sum(c.complexity for c in res)
                                complexites[fichier] = score
                        except:
                            complexites[fichier] = -1

    except Exception as e:
        return {"error": f"Erreur pendant l'analyse des commits : {str(e)}"}

    os.makedirs("static/images", exist_ok=True)

    # Graphique commits par auteur
    graph_path = "static/images/commits.png"
    try:
        plt.figure(figsize=(8, 4))
        plt.bar(commits_par_auteur.keys(), commits_par_auteur.values(), color='skyblue')
        plt.title("Commits par auteur")
        plt.xticks(rotation=45)
        plt.tight_layout()
        plt.savefig(graph_path)
        plt.close()
    except:
        graph_path = None

    # Graphique activité temporelle
    try:
        deadline_dt = datetime.strptime(deadline, "%Y-%m-%d") if deadline else None
        plt.figure(figsize=(10, 5))
        for auteur, dates_dict in evolution_par_auteur.items():
            dates = sorted(dates_dict.keys())
            dates_dt = [datetime.strptime(d, "%Y-%m-%d") for d in dates]
            counts = [dates_dict[d] for d in dates]
            plt.plot(dates_dt, counts, marker='o', label=auteur)
        if deadline_dt:
            plt.axvline(deadline_dt, color='black', linestyle='--', label='Deadline')
        plt.title("Activité temporelle par auteur")
        plt.xlabel("Date")
        plt.ylabel("Commits")
        plt.xticks(rotation=45)
        plt.legend()
        plt.tight_layout()
        plt.savefig("static/images/evolution.png")
        plt.close()
    except Exception as e:
        print("Erreur génération graphe évolution :", e)

    # Graphique contributions globales
    try:
        plt.figure(figsize=(8, 4))
        total = sum(ajouts_par_auteur[a] + suppressions_par_auteur[a] for a in ajouts_par_auteur)
        labels = []
        sizes = []
        for auteur in ajouts_par_auteur:
            lignes = ajouts_par_auteur[auteur] + suppressions_par_auteur[auteur]
            if lignes > 0:
                labels.append(auteur)
                sizes.append(100 * lignes / total)
        plt.pie(sizes, labels=labels, autopct='%1.1f%%')
        plt.title("Répartition des contributions (ajouts + suppressions)")
        plt.savefig("static/images/contributions.png")
        plt.close()
    except Exception as e:
        print("Erreur graphique contributions :", e)

    # Top fichiers modifiés
    fichiers_critiques = fichiers_modifies.most_common(5)

    # Appel GitStats (API backend)
    gitstats_url = None
    try:
        response = requests.post("http://127.0.0.1:5000/api/gitstats", json={
            "repo_path": os.path.abspath(repo_path),
            "output_path": os.path.abspath(gitstats_output_path)
        })
        result = response.json()
        if result.get("success"):
            gitstats_url = "/static/gitstats_report/index.html"
        else:
            print("❌ GitStats erreur :", result.get("error"))
    except Exception as e:
        print("❌ Exception GitStats :", e)

    # Nettoyage
    try:
        fermer_processus_git(repo_path)
        shutil.rmtree(repo_path, onerror=on_rm_error)
    except Exception as e:
        print("❌ Erreur nettoyage :", e)

    # Retour des résultats
    contributions = {}
    for auteur in ajouts_par_auteur:
        lignes = ajouts_par_auteur[auteur] + suppressions_par_auteur[auteur]
        pourcentage = (100 * lignes / total_lignes) if total_lignes else 0
        contributions[auteur] = {
            "ajouts": ajouts_par_auteur[auteur],
            "suppressions": suppressions_par_auteur[auteur],
            "pourcentage": round(pourcentage, 2)
        }

    return {
        "total_commits": sum(commits_par_auteur.values()),
        "commits_par_auteur": dict(commits_par_auteur),
        "fichiers_critiques": fichiers_critiques,
        "complexites": complexites,
        "graph_url": graph_path,
        "evolution": dict(evolution_par_auteur),
        "co_modification": {f: dict(a) for f, a in co_modification.items()},
        "gitstats_url": gitstats_url,
        "contributions": contributions
    }
