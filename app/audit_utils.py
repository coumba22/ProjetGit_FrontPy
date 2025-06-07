import os
import shutil
import subprocess
import stat
import time
import json
import requests  # utilisé pour l’API GitStats

from typing import Optional, Dict, Any
from urllib.parse import urlparse
from collections import defaultdict, Counter
from datetime import datetime
from pydriller import Repository
from radon.complexity import cc_visit
import matplotlib.pyplot as plt
import psutil
import re

# --------------------------------------------------------------------
# Fonctions utilitaires (suppression forcée sous Windows)
# --------------------------------------------------------------------
def on_rm_error(func, path, exc_info):
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception as e:
        print(f"❌ Échec suppression {path} : {e}")

def fermer_processus_git(path: str) -> None:
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            nom = proc.info['name'] or ""
            cmdl = proc.info['cmdline'] or []
            if ('git' in nom.lower() or 'gitstats' in nom.lower()) and any(path in arg for arg in cmdl):
                proc.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

def inject_token_in_url(repo_url: str, token: Optional[str]) -> str:
    parsed = urlparse(repo_url)
    path = parsed.path
    if not path.endswith(".git"):
        path += ".git"
    if token:
        return f"https://{token}@{parsed.netloc}{path}"
    else:
        return f"https://{parsed.netloc}{path}"

def nettoyer_nom_repo(url: str) -> str:
    path = urlparse(url).path
    repo_name = os.path.basename(path)
    return repo_name.replace(".git", "")


# --------------------------------------------------------------------
# Analyse d’un dépôt unique (commande 'lancer_audit')
# --------------------------------------------------------------------
def lancer_audit(
    repo_url: str,
    token: Optional[str] = None,
    deadline: Optional[str] = None
) -> Dict[str, Any]:
    timestamp = int(time.time())
    base_name = nettoyer_nom_repo(repo_url)
    repo_path = f"temp_repo_{timestamp}_{base_name}"
    gitstats_output_path = "static/gitstats_report"

    # Nettoyage éventuel
    if os.path.exists(repo_path):
        fermer_processus_git(repo_path)
        shutil.rmtree(repo_path, onerror=on_rm_error)
    if os.path.exists(gitstats_output_path):
        shutil.rmtree(gitstats_output_path, onerror=on_rm_error)

    # Clonage
    url_to_clone = inject_token_in_url(repo_url, token)
    try:
        subprocess.check_call(["git", "clone", url_to_clone, repo_path])
        time.sleep(1)
    except subprocess.CalledProcessError:
        return {"error": "❌ Clonage échoué. Vérifie l'URL ou ton token."}

    # Comptages
    commits_par_auteur         = Counter()
    fichiers_modifies          = Counter()
    complexites                = {}
    evolution_par_auteur       = defaultdict(lambda: defaultdict(int))
    co_modification            = defaultdict(lambda: defaultdict(int))
    auteur_fichiers            = defaultdict(set)
    lignes_ajoutees_par_auteur = Counter()
    lignes_supprimees_par_auteur = Counter()

    try:
        for commit in Repository(repo_path).traverse_commits():
            au = commit.author.name or "Inconnu"
            dstr = commit.author_date.strftime("%Y-%m-%d")

            commits_par_auteur[au] += 1
            evolution_par_auteur[au][dstr] += 1

            for mod in commit.modified_files:
                # fichiers
                f = mod.new_path or mod.old_path
                if not f:
                    continue
                fichiers_modifies[f] += 1
                auteur_fichiers[au].add(f)

                # co-modifs
                for autre, s in auteur_fichiers.items():
                    if autre != au and f in s:
                        co_modification[f][au]    += 1
                        co_modification[f][autre] += 1

                    # … à l’intérieur du for commit … for mod in commit.modified_files: …
                    # Complexité cyclomatique : on tente systématiquement (radon ne lira
                    # que le Python, et lèvera une exception sinon)
                    full_path = os.path.join(repo_path, f)
                    if os.path.exists(full_path):
                        try:
                            with open(full_path, 'r', encoding='utf-8') as f_code:
                                code = f_code.read()
                                res = cc_visit(code)
                                complexites[f] = sum(c.complexity for c in res)
                        except Exception:
                            # pas un fichier Python ou parse error → on ignore
                            pass

                # … fin de la boucle Repository(traverse_commits()) …

                # Après avoir collecté TOUTES les complexités, on ne conserve QUE le Top 10
                if complexites:
                    top10 = sorted(complexites.items(), key=lambda x: x[1], reverse=True)[:10]
                    complexites = dict(top10)


                # lignes ajoutées/supprimées
                a = getattr(mod, "added_lines", 0)
                d = getattr(mod, "deleted_lines", 0)
                if a:
                    lignes_ajoutees_par_auteur[au] += a
                if d:
                    lignes_supprimees_par_auteur[au] += d

    except Exception as e:
        return {"error": f"Erreur pendant l'analyse des commits : {e}"}

    # GARDER TOP 10 des fichiers Python les plus complexes
    if complexites:
        top10 = sorted(complexites.items(), key=lambda x: x[1], reverse=True)[:10]
        complexites = dict(top10)

    # Contributions par auteur
    contributions = {}
    total_changed = 0
    for au in set(lignes_ajoutees_par_auteur) | set(lignes_supprimees_par_auteur):
        A = lignes_ajoutees_par_auteur.get(au, 0)
        D = lignes_supprimees_par_auteur.get(au, 0)
        T = A + D
        total_changed += T
        contributions[au] = {"added": A, "deleted": D, "total": T}

    # pourcentages
    for au, info in contributions.items():
        pct = round(100 * info["total"] / total_changed, 2) if total_changed > 0 else 0.0
        info["percent"] = pct

    # Graph Commits
    try:
        fig, ax = plt.subplots(figsize=(8,4))
        ax.bar(commits_par_auteur.keys(), commits_par_auteur.values(), color='skyblue')
        ax.set_title("Commits par auteur")
        ax.tick_params(axis='x', rotation=45)
        plt.tight_layout()
        p = f"app/static/images/commits_{base_name}.png"
        plt.savefig(p); plt.close(fig)
        graph_url = p.replace("\\", "/")
    except:
        graph_url = None

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
        p2 = f"app/static/images/evolution_{base_name}.png"
        plt.savefig(p2); plt.close(fig)
        evolution_url = p2.replace("\\", "/")
    except:
        evolution_url = None

    fichiers_critiques = fichiers_modifies.most_common(5)

    # Appel API GitStats
    gitstats_url = None
    try:
        resp = requests.post(
            "http://127.0.0.1:{FRONTEND_PORT}/api/gitstats",
            json={
                "repo_path": os.path.abspath(repo_path),
                "output_path": os.path.abspath(gitstats_output_path)
            }
        )
        data = resp.json()
        if data.get("success"):
            gitstats_url = "/static/gitstats_report/index.html"
    except Exception as e:
        print("❌ Exception GitStats :", e)

    # Nettoyage du clone
    try:
        fermer_processus_git(repo_path)
        shutil.rmtree(repo_path, onerror=on_rm_error)
    except Exception as e:
        print("❌ Erreur nettoyage :", e)

    return {
        "total_commits":          sum(commits_par_auteur.values()),
        "commits_par_auteur":     dict(commits_par_auteur),
        "contributions":          contributions,
        "fichiers_critiques":     fichiers_critiques,
        "complexites":            complexites,
        "co_modification":        {f: dict(a) for f,a in co_modification.items()},
        "graph_url":              graph_url,
        "evolution_url":          evolution_url,
        "gitstats_url":           gitstats_url
    }



# --------------------------------------------------------------------
#        Analyse « TD par TD » pour un dépôt-étudiant
# --------------------------------------------------------------------
def analyser_etudiant(
    nom_etudiant: str,
    repo_url: str,
    token: Optional[str],
    deadlines_etudiant: Dict[str, str],
    poids: Optional[Dict[str, float]]
) -> Dict[str, Any]:
    """
    Pour un étudiant donné :
      - clone son dépôt dans 'temp_etudiant_<nom>_<timestamp>',
      - pour chaque commit du samedi (weekday() == 5), calcule
        'ajouts', 'suppressions', 'fichiers touchés', 'score_TD',
        'pourcentage' (par rapport au total de lignes modifiées),
        indique s’il est à l’heure ou non (en comparant l’heure du commit
        à la deadline de ce samedi tirée de deadlines_etudiant),
      - renvoie un dict :
         {
            "etudiant": "<nom_repo>",
            "TDs": {
               "YYYY-MM-DD": {
                  "date_commit": "YYYY-MM-DD HH:MM",
                  "commits": N,
                  "ajouts": A,
                  "suppressions": S,
                  "fichiers": F,
                  "score": X.X,
                  "pourcentage": Y.Y,       # % du total de lignes modifiées
                  "a_heure": True/False
               }, …
            },
            "total_commits": …,
            "total_ajouts": …,
            "total_suppressions": …,
            "total_fichiers": …,
            "score_global": …,
            "nb_branches": …,
            "nb_pulls_all": …,
            "nb_issues_all": …
         }
    """
    base_name = nettoyer_nom_repo(repo_url)
    ts = int(time.time())
    repo_path = f"temp_etudiant_{base_name}_{ts}"
    if os.path.exists(repo_path):
        fermer_processus_git(repo_path)
        shutil.rmtree(repo_path, onerror=on_rm_error)

    # 1) Cloner le dépôt
    url_to_clone = inject_token_in_url(repo_url, token)
    try:
        subprocess.check_call(["git", "clone", url_to_clone, repo_path])
        time.sleep(0.5)
    except subprocess.CalledProcessError:
        return {"error": f"❌ Clonage échoué pour {nom_etudiant}."}

    # 2) Initialisation des compteurs
    TDs: Dict[str, Dict[str, Any]] = {}
    total_commits = 0
    total_ajouts = 0
    total_suppressions = 0
    total_fichiers = 0
    score_global = 0.0

    # 3) Pondérations par défaut si non fournies
    if poids is None:
        w_c = 1.0    # poids sur nombre de commits
        w_l = 0.5    # poids sur lignes (ajouts + suppressions)
        w_f = 0.2    # poids sur fichiers touchés
    else:
        w_c = poids.get("commits", 1.0)
        w_l = poids.get("ligne", 0.5)
        w_f = poids.get("fichier", 0.2)

    # 4) Itérer sur tous les commits avec PyDriller
    try:
        for commit in Repository(repo_path).traverse_commits():
            dt = commit.author_date
            # Ne retenir que les samedis (weekday()==5)
            if dt.weekday() != 5:
                continue

            date_semaine = dt.strftime("%Y-%m-%d")
            if date_semaine not in TDs:
                TDs[date_semaine] = {
                    "date_commit": dt.strftime("%Y-%m-%d %H:%M"),
                    "commits": 0,
                    "ajouts": 0,
                    "suppressions": 0,
                    "fichiers": 0,
                    "score": 0.0,
                    "pourcentage": 0.0,
                    "a_heure": True
                }

            # Incrémenter le nombre de commits
            TDs[date_semaine]["commits"] += 1

            # Parcourir les modifications de fichiers
            ajouts = 0
            suppressions = 0
            fichiers_touchés = 0
            for mod in commit.modified_files:
                a = getattr(mod, "added_lines", 0)
                d = getattr(mod, "deleted_lines", 0)
                ajouts += a
                suppressions += d
                fichiers_touchés += 1

            TDs[date_semaine]["ajouts"] += ajouts
            TDs[date_semaine]["suppressions"] += suppressions
            TDs[date_semaine]["fichiers"] += fichiers_touchés

            # 5) Vérifier la deadline pour ce samedi
            #    deadlines_etudiant : { "YYYY-MM-DD": "HH:MM", … } ou {"global": "HH:MM"}
            if date_semaine in deadlines_etudiant:
                limite_str = f"{date_semaine} {deadlines_etudiant[date_semaine]}"
                try:
                    dt_limite = datetime.strptime(limite_str, "%Y-%m-%d %H:%M")
                    if dt > dt_limite:
                        TDs[date_semaine]["a_heure"] = False
                except Exception:
                    pass
            elif "global" in deadlines_etudiant:
                limite_str = f"{date_semaine} {deadlines_etudiant['global']}"
                try:
                    dt_limite = datetime.strptime(limite_str, "%Y-%m-%d %H:%M")
                    if dt > dt_limite:
                        TDs[date_semaine]["a_heure"] = False
                except Exception:
                    pass

            # 6) Calcul du score pour ce TD
            score_TD = (
                TDs[date_semaine]["commits"] * w_c
                + (TDs[date_semaine]["ajouts"] + TDs[date_semaine]["suppressions"]) * w_l
                + TDs[date_semaine]["fichiers"] * w_f
            )
            TDs[date_semaine]["score"] = round(score_TD, 2)

            # Maj totaux
            total_commits += TDs[date_semaine]["commits"]
            total_ajouts += TDs[date_semaine]["ajouts"]
            total_suppressions += TDs[date_semaine]["suppressions"]
            total_fichiers += TDs[date_semaine]["fichiers"]
            score_global += score_TD

        # 7) Calculer les pourcentages par TD (par rapport au total de lignes modifiées)
        total_lignes = total_ajouts + total_suppressions
        if total_lignes > 0:
            for info in TDs.values():
                lignes_td = info["ajouts"] + info["suppressions"]
                info["pourcentage"] = round(100.0 * lignes_td / total_lignes, 2)
        else:
            for info in TDs.values():
                info["pourcentage"] = 0.0

    except Exception as e:
        return {"error": f"Erreur pendant l’analyse des TDs de {nom_etudiant} : {e}"}

        # 8) Récupérer quelques indicateurs GitHub (branches, PR, issues, reviews, CI/CD)
    nb_branches = nb_pr_total = nb_pr_open = nb_pr_closed = nb_pr_merged = 0
    nb_reviews = 0
    nb_ci_total = nb_ci_success = nb_ci_failure = 0

    try:
        from requests import get as _get
        parsed = urlparse(repo_url)
        owner, repo = parsed.path.strip("/").replace(".git", "").split("/", 1)
        headers = {"Accept": "application/vnd.github.v3+json"}
        if token:
            headers["Authorization"] = f"token {token}"

        # -- Branches
        bres = _get(f"https://api.github.com/repos/{owner}/{repo}/branches", headers=headers)
        if bres.ok:
            nb_branches = len(bres.json())

        # -- Pull‐requests (toutes)
        prs = []
        page = 1
        while True:
            r = _get(
                f"https://api.github.com/repos/{owner}/{repo}/pulls?state=all&per_page=100&page={page}",
                headers=headers
            )
            if not r.ok:
                break
            batch = r.json()
            if not batch:
                break
            prs.extend(batch)
            page += 1
        nb_pr_total  = len(prs)
        nb_pr_open   = sum(1 for pr in prs if pr.get("state") == "open")
        nb_pr_closed = sum(1 for pr in prs if pr.get("state") == "closed")
        nb_pr_merged = sum(1 for pr in prs if pr.get("merged_at") is not None)

        # -- Code reviews
        for pr in prs:
            num = pr.get("number")
            rr = _get(f"https://api.github.com/repos/{owner}/{repo}/pulls/{num}/reviews", headers=headers)
            if rr.ok:
                nb_reviews += len(rr.json())

        # -- CI/CD via GitHub Actions
        runs = []
        page = 1
        while True:
            cr = _get(
                f"https://api.github.com/repos/{owner}/{repo}/actions/runs?per_page=100&page={page}",
                headers=headers
            )
            if not cr.ok:
                break
            data = cr.json().get("workflow_runs", [])
            if not data:
                break
            runs.extend(data)
            page += 1
        nb_ci_total   = len(runs)
        nb_ci_success = sum(1 for run in runs if run.get("conclusion") == "success")
        nb_ci_failure = sum(1 for run in runs if run.get("conclusion") not in (None, "success"))

    except Exception as e:
        # en cas d’erreur, on laisse tout à 0
        print(f"❌ Erreur GitHub API pour {owner}/{repo} : {e}")

    # 9) Nettoyage du clone
    try:
        fermer_processus_git(repo_path)
        shutil.rmtree(repo_path, onerror=on_rm_error)
    except Exception as e:
        print(f"❌ Erreur nettoyage pour {nom_etudiant} : {e}")

    # 10) Retour avec les nouveaux champs
    return {
        "etudiant": base_name,
        "TDs": TDs,
        "total_commits": total_commits,
        "total_ajouts": total_ajouts,
        "total_suppressions": total_suppressions,
        "total_fichiers": total_fichiers,
        "score_global": round(score_global, 2),
        "nb_branches": nb_branches,
        "nb_pr_total": nb_pr_total,
        "nb_pr_open": nb_pr_open,
        "nb_pr_closed": nb_pr_closed,
        "nb_pr_merged": nb_pr_merged,
        "nb_reviews": nb_reviews,
        "nb_ci_total": nb_ci_total,
        "nb_ci_success": nb_ci_success,
        "nb_ci_failure": nb_ci_failure
    }



# --------------------------------------------------------------------
#            Analyse de tous les étudiants (classe entière)
# --------------------------------------------------------------------
def analyser_classe(
    liste_etudiants: Dict[str, str],
    token_communs: Optional[Dict[str, str]],
    deadlines_map: Dict[str, Dict[str, str]],
    poids: Optional[Dict[str, float]]
) -> Dict[str, Any]:
    """
    Itère sur tous les étudiants de 'liste_etudiants':
      - pour chaque étudiant, appelle analyser_etudiant(...)
      - stocke le résultat dans un dict { nom_etudiant: résultat }
    Retourne ce dict.

    liste_etudiants : { "Alice": "https://..alice.git", "Bob": "..." }
    token_communs   : { "Alice": "ghp_XXX", "Bob": "ghp_YYY" } (optional)
    deadlines_map   : { "Alice": {"2025-03-07":"18:00", ...}, "Bob": {...} }
    poids           : { "commits": 1.0, "ligne": 0.5, "fichier": 0.2 }
    """
    résultats_totaux: Dict[str, Any] = {}

    for nom, url_repo in liste_etudiants.items():
        token = token_communs.get(nom) if token_communs else None
        deadlines_etudiant = deadlines_map.get(nom, {})
        try:
            print(f"▶️ Analyse de {nom} ({url_repo}) …")
            res = analyser_etudiant(nom, url_repo, token, deadlines_etudiant, poids)
            résultats_totaux[nom] = res
        except Exception as e:
            résultats_totaux[nom] = {"error": f"Exception inattendue pour {nom} : {e}"}

    return résultats_totaux


# --------------------------------------------------------------------
#            Chargement du fichier tds.json (liste des étudiants)
# --------------------------------------------------------------------
def charger_tds(tds_path: str = "tds.json") -> (
    Dict[str, str],
    Dict[str, str],
    Dict[str, Dict[str, str]]
):
    """
    Ouvre 'tds.json' et retourne :
      - liste_etudiants : { "Alice": "url_repo_Alice", … }
      - token_communs   : { "Alice": "ghp_XXX", … } (seulement s’il y a un token non vide)
      - deadlines_map   : { "Alice": {"2025-03-07": "18:00", … }, "Bob": {…} }

    Si le fichier est absent ou vide, renvoie trois dicts vides.
    """
    if not os.path.exists(tds_path):
        return {}, {}, {}
    try:
        with open(tds_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        return {}, {}, {}

    liste_etudiants: Dict[str, str] = {}
    token_communs: Dict[str, str] = {}
    deadlines_map: Dict[str, Dict[str, str]] = {}

    for item in data:
        nom = item.get("nom")
        url = item.get("repo_url")
        token = item.get("token", "")
        raw_dead = item.get("deadlines")
        single_dead = item.get("deadline")

        if nom and url:
            liste_etudiants[nom] = url
            if token:
                token_communs[nom] = token

            if isinstance(raw_dead, dict):
                deadlines_map[nom] = raw_dead
            elif isinstance(single_dead, str) and single_dead.strip():
                deadlines_map[nom] = {"global": single_dead.strip()}
            else:
                deadlines_map[nom] = {}

    return liste_etudiants, token_communs, deadlines_map
