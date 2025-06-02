import os
import shutil
import subprocess
import stat
from urllib.parse import urlparse
from collections import defaultdict, Counter
from pydriller import Repository
from radon.complexity import cc_visit
import matplotlib.pyplot as plt
from datetime import datetime
import traceback
import os

def nettoyer_nom_repo(url):
    path = urlparse(url).path
    return os.path.basename(path).replace(".git", "")

def on_rm_error(func, path, exc_info):
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception as e:
        print(f"Erreur suppression {path} : {e}")

def inject_token_in_url(repo_url, token):
    parsed = urlparse(repo_url)
    path = parsed.path if parsed.path.endswith(".git") else parsed.path + ".git"
    return f"https://{token}@{parsed.netloc}{path}" if token else f"https://{parsed.netloc}{path}"

def lancer_audit(repo_url, token=None, deadline=None):
    repo_name = nettoyer_nom_repo(repo_url)
    base_repo_dir = "temp_repo"
    repo_path = os.path.join(base_repo_dir, repo_name)
    gitstats_output_path = os.path.join("static", "gitstats_report", repo_name)

    # Créer dossier base s'il n'existe pas
    os.makedirs(base_repo_dir, exist_ok=True)

    url_to_clone = inject_token_in_url(repo_url, token)

    # Si le repo existe déjà, faire un git pull, sinon cloner
    if os.path.exists(repo_path):
        try:
            subprocess.check_call(["git", "-C", repo_path, "pull"])
        except subprocess.CalledProcessError:
            # En cas d'erreur on peut tenter de supprimer et recloner
            shutil.rmtree(repo_path, onerror=on_rm_error)
            try:
                subprocess.check_call(["git", "clone", url_to_clone, repo_path])
            except subprocess.CalledProcessError:
                return {"error": "❌ Clonage échoué après suppression du dossier existant."}
    else:
        try:
            subprocess.check_call(["git", "clone", url_to_clone, repo_path])
        except subprocess.CalledProcessError:
            return {"error": "❌ Clonage échoué. Vérifie l'URL ou ton token."}

    # Nettoyer l'ancien rapport GitStats avant de générer un nouveau
    shutil.rmtree(gitstats_output_path, ignore_errors=True)

    # --- Reste de ton code inchangé ---
    commits_par_auteur = Counter()
    fichiers_modifies = Counter()
    complexites = {}
    evolution_par_auteur = defaultdict(lambda: defaultdict(int))
    co_modification = defaultdict(lambda: defaultdict(int))
    auteur_fichiers = defaultdict(set)

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

                if fichier.endswith(".py"):
                    full_path = os.path.join(repo_path, fichier)
                    if os.path.exists(full_path):
                        try:
                            with open(full_path, 'r', encoding='utf-8') as f:
                                res = cc_visit(f.read())
                                complexites[fichier] = sum(c.complexity for c in res)
                        except:
                            complexites[fichier] = -1
    except Exception as e:
        erreur_complete = traceback.format_exc()
        return {"error": f"Erreur d’analyse des commits : {erreur_complete}"}

    os.makedirs("static/images", exist_ok=True)
    graph_url = "static/images/commits.png"
    try:
        plt.figure(figsize=(8, 4))
        plt.bar(commits_par_auteur.keys(), commits_par_auteur.values(), color='skyblue')
        plt.title("Commits par auteur")
        plt.xticks(rotation=45)
        plt.tight_layout()
        plt.savefig(graph_url)
        plt.close()
    except:
        graph_url = None

    try:
        deadline_dt = datetime.strptime(deadline, "%Y-%m-%d") if deadline else None
        plt.figure(figsize=(10, 5))
        for auteur, dates_dict in evolution_par_auteur.items():
            dates = sorted(dates_dict.keys())
            dates_dt = [datetime.strptime(d, "%Y-%m-%d") for d in dates]
            counts = [dates_dict[d] for d in dates]
            plt.plot(dates_dt, counts, marker='o', label=auteur)
        if deadline_dt:
            plt.axvline(deadline_dt, color='red', linestyle='--', label='Deadline')
        plt.title("Évolution temporelle")
        plt.xlabel("Date")
        plt.ylabel("Commits")
        plt.legend()
        plt.tight_layout()
        plt.savefig("static/images/evolution.png")
        plt.close()
    except:
        pass

    fichiers_critiques = fichiers_modifies.most_common(5)

    try:
        subprocess.check_call(["gitstats", repo_path, gitstats_output_path])
        gitstats_url = f"/static/gitstats_report/{repo_name}/index.html"
    except Exception as e:
        gitstats_url = None
        print("Erreur GitStats :", e)

    # On ne supprime plus le repo local pour pouvoir le réutiliser plus tard
    # shutil.rmtree(repo_path, ignore_errors=True)

    return {
        "total_commits": sum(commits_par_auteur.values()),
        "commits_par_auteur": dict(commits_par_auteur),
        "fichiers_critiques": fichiers_critiques,
        "complexites": complexites,
        "graph_url": graph_url,
        "evolution": dict(evolution_par_auteur),
        "co_modification": {f: dict(a) for f, a in co_modification.items()},
        "gitstats_url": gitstats_url
    }

