import os
import shutil
import subprocess
import stat
import time
import json

from typing import Optional, Dict, Any
from urllib.parse import urlparse
from collections import defaultdict, Counter
from datetime import datetime
from pydriller import Repository
from radon.complexity import cc_visit
import matplotlib.pyplot as plt
import psutil

# --------------------------------------------------------------------
#              Fonctions utilitaires (suppression forcée sous Windows)
# --------------------------------------------------------------------
def on_rm_error(func, path, exc_info):
    """
    Gestionnaire d’erreur pour shutil.rmtree : force la suppression
    même si un fichier est verrouillé sous Windows.
    """
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception as e:
        print(f"❌ Échec suppression {path} : {e}")

def fermer_processus_git(path: str) -> None:
    """
    Parcourt tous les processus système et tente de tuer
    ceux dont la commande contient 'git' ou 'gitstats' et le chemin donné.
    Utile pour éviter que Git ou GitStats verrouille des fichiers.
    """
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            nom = proc.info['name'] or ""
            cmdl = proc.info['cmdline'] or []
            if ('git' in nom.lower() or 'gitstats' in nom.lower()) and any(path in arg for arg in cmdl):
                proc.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

def inject_token_in_url(repo_url: str, token: Optional[str]) -> str:
    """
    Si 'token' fourni, injecte le token dans l’URL HTTPS avant le nom de domaine.
    Exemple : inject_token_in_url("https://github.com/user/proj.git", "ghp_XXX")
     → "https://ghp_XXX@github.com/user/proj.git"
    """
    parsed = urlparse(repo_url)
    path = parsed.path
    if not path.endswith(".git"):
        path += ".git"
    if token:
        return f"https://{token}@{parsed.netloc}{path}"
    else:
        return f"https://{parsed.netloc}{path}"

def nettoyer_nom_repo(url: str) -> str:
    """
    Extrait un nom de dossier propre à partir d’une URL GitHub
    Exemple : "https://github.com/user/projet.git" → "projet"
    """
    path = urlparse(url).path
    repo_name = os.path.basename(path)
    return repo_name.replace(".git", "")

# --------------------------------------------------------------------
#       Analyse d’un dépôt unique (commande 'lancer_audit')
# --------------------------------------------------------------------
def lancer_audit(
    repo_url: str,
    token: Optional[str] = None,
    deadline: Optional[str] = None
) -> Dict[str, Any]:
    """
    Clone le dépôt 'repo_url' dans 'temp_repo', calcule :
      - nombre de commits par auteur,
      - fichiers les plus modifiés,
      - complexité cyclomatique par fichier .py,
      - évolution temporelle des commits,
      - co-modifications par fichier,
      - génère des graphes (commits, évolution),
      - appelle l’API GitStats backend pour générer le rapport HTML complet,
      - supprime enfin 'temp_repo'.

    Renvoie un dict contenant toutes ces métriques + l’URL vers index.html de GitStats.
    """
    repo_path = "temp_repo"
    gitstats_output_path = "static/gitstats_report"

    # 1) Nettoyage du précédent clone
    if os.path.exists(repo_path):
        fermer_processus_git(repo_path)
        shutil.rmtree(repo_path, onerror=on_rm_error)
    if os.path.exists(gitstats_output_path):
        shutil.rmtree(gitstats_output_path, onerror=on_rm_error)

    # 2) Clonage du dépôt
    url_to_clone = inject_token_in_url(repo_url, token)
    print("🔗 URL clonage utilisée :", url_to_clone)
    try:
        subprocess.check_call(["git", "clone", url_to_clone, repo_path])
        time.sleep(1)  # petit délai pour s’assurer que le clone est bien terminé
    except subprocess.CalledProcessError:
        return {"error": "❌ Clonage échoué. Vérifie l'URL ou ton token."}

    # 3) Collecte PyDriller & Radon
    commits_par_auteur = Counter()
    fichiers_modifies = Counter()
    complexites = {}
    evolution_par_auteur = defaultdict(lambda: defaultdict(int))
    co_modification = defaultdict(lambda: defaultdict(int))
    auteur_fichiers = defaultdict(set)

    try:
        for commit in Repository(repo_path).traverse_commits():
            auteur = commit.author.name or "Inconnu"
            date_str = commit.author_date.strftime("%Y-%m-%d")
            commits_par_auteur[auteur] += 1
            evolution_par_auteur[auteur][date_str] += 1

            for mod in commit.modified_files:
                fichier = mod.new_path or mod.old_path
                if not fichier:
                    continue
                fichiers_modifies[fichier] += 1
                auteur_fichiers[auteur].add(fichier)

                # Co-modifications : si un autre auteur a déjà modifié 'fichier'
                for autre_auteur, fichiers_set in auteur_fichiers.items():
                    if autre_auteur != auteur and fichier in fichiers_set:
                        co_modification[fichier][auteur] += 1
                        co_modification[fichier][autre_auteur] += 1

                # Complexité cyclomatique : uniquement pour fichiers Python
                if fichier.endswith(".py"):
                    full_path = os.path.join(repo_path, fichier)
                    if os.path.exists(full_path):
                        try:
                            with open(full_path, 'r', encoding='utf-8') as f_code:
                                code = f_code.read()
                                res = cc_visit(code)
                                score = sum(c.complexity for c in res)
                                complexites[fichier] = score
                        except Exception:
                            complexites[fichier] = -1
    except Exception as e:
        return {"error": f"Erreur pendant l'analyse des commits : {e}"}

    # 4) Création du dossier pour les images
    os.makedirs("static/images", exist_ok=True)

    # 4.a) Graphe « Commits par auteur »
    graph_path = "static/images/commits.png"
    try:
        plt.figure(figsize=(8, 4))
        plt.bar(commits_par_auteur.keys(), commits_par_auteur.values(), color='skyblue')
        plt.title("Commits par auteur")
        plt.xticks(rotation=45)
        plt.tight_layout()
        plt.savefig(graph_path)
        plt.close()
        # On retourne l’URL relative (sans leading slash, la route Flask l’affichera avec /static/… )
        graph_url = graph_path.replace("\\", "/")
    except Exception:
        graph_url = None

    # 4.b) Graphe « Évolution temporelle par auteur »
    evo_path = "static/images/evolution.png"
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
        plt.savefig(evo_path)
        plt.close()
        evolution_url = evo_path.replace("\\", "/")
    except Exception:
        evolution_url = None

    fichiers_critiques = fichiers_modifies.most_common(5)

    # 5) Appel à l’API GitStats backend
    gitstats_url = None
    try:
        response = requests.post(
            "http://127.0.0.1:5000/api/gitstats",
            json={
                "repo_path": os.path.abspath(repo_path),
                "output_path": os.path.abspath("static/gitstats_report")
            }
        )
        print("📩 Réponse brute GitStats API :", response.text)
        result = response.json()
        if result.get("success"):
            gitstats_url = "/static/gitstats_report/index.html"
        else:
            print("❌ GitStats erreur :", result.get("error"))
    except Exception as e:
        print("❌ Exception GitStats :", e)

    # 6) Nettoyage final du dossier temp_repo
    try:
        fermer_processus_git(repo_path)
        shutil.rmtree(repo_path, onerror=on_rm_error)
    except Exception as e:
        print("❌ Erreur nettoyage :", e)

    return {
        "total_commits": sum(commits_par_auteur.values()),
        "commits_par_auteur": dict(commits_par_auteur),
        "fichiers_critiques": fichiers_critiques,
        "complexites": complexites,
        "graph_url": graph_url,
        "evolution_url": evolution_url,
        "co_modification": {f: dict(a) for f, a in co_modification.items()},
        "gitstats_url": gitstats_url
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
    # Afin de garder plusieurs clones parallèles, on ajoute timestamp
    ts = int(time.time())
    repo_path = f"temp_etudiant_{base_name}_{ts}"
    if os.path.exists(repo_path):
        fermer_processus_git(repo_path)
        shutil.rmtree(repo_path, onerror=on_rm_error)

    # 1) Cloner le dépôt de l’étudiant
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
            # Initialiser l’entrée pour cette date, si besoin
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

            # Incrémenter le nombre de commits pour cette date
            TDs[date_semaine]["commits"] += 1

            # Parcourir les modifications de fichiers
            ajouts = 0
            suppressions = 0
            fichiers_touchés = 0
            for mod in commit.modified_files:
                # Certains objets ModifiedFile peuvent ne pas avoir .added_lines / .deleted_lines
                a = getattr(mod, "added_lines", 0)
                d = getattr(mod, "deleted_lines", 0)
                ajouts += a
                suppressions += d
                fichiers_touchés += 1

            TDs[date_semaine]["ajouts"] += ajouts
            TDs[date_semaine]["suppressions"] += suppressions
            TDs[date_semaine]["fichiers"] += fichiers_touchés

            # 5) Vérifier si l’étudiant a commis avant la deadline de ce samedi
            #    deadlines_etudiant est un dict { "YYYY-MM-DD": "HH:MM", … }
            if date_semaine in deadlines_etudiant:
                limite_str = f"{date_semaine} {deadlines_etudiant[date_semaine]}"
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

            # Maj totaux (pour l’instant, on additionne simplement)
            # --> on ajoutera la logique pour le pourcentage un peu plus bas
            total_commits += TDs[date_semaine]["commits"]
            total_ajouts += TDs[date_semaine]["ajouts"]
            total_suppressions += TDs[date_semaine]["suppressions"]
            total_fichiers += TDs[date_semaine]["fichiers"]
            score_global += score_TD

        # 7) Calculer les pourcentages par TD par rapport au total de lignes modifiées
        total_lignes = total_ajouts + total_suppressions
        if total_lignes > 0:
            for date_semaine, info in TDs.items():
                lignes_td = info["ajouts"] + info["suppressions"]
                # % rond à 2 décimales
                info["pourcentage"] = round(100.0 * lignes_td / total_lignes, 2)
        else:
            # Si total_lignes == 0, on garde tous les pourcentages à 0.0
            for info in TDs.values():
                info["pourcentage"] = 0.0

    except Exception as e:
        return {"error": f"Erreur pendant l’analyse des TDs de {nom_etudiant} : {e}"}

    # 8) Récupérer quelques indicateurs GitHub (branches, PR, issues)
    nb_branches = nb_pulls_all = nb_issues_all = 0
    try:
        from requests import get as _get
        # On extrait owner/repo depuis l’URL
        parsed = urlparse(repo_url)
        # URL attendue : https://github.com/owner/repo(.git)
        path = parsed.path.strip("/").replace(".git", "")
        owner, repo = path.split("/", 1)
        headers = {"Accept": "application/vnd.github.v3+json"}
        if token:
            headers["Authorization"] = f"token {token}"
        # Branches
        bres = _get(f"https://api.github.com/repos/{owner}/{repo}/branches", headers=headers)
        if bres.ok:
            nb_branches = len(bres.json())
        # Pull requests (toutes)
        pres = _get(f"https://api.github.com/repos/{owner}/{repo}/pulls?state=all", headers=headers)
        if pres.ok:
            nb_pulls_all = len(pres.json())
        # Issues (toutes)
        ires = _get(f"https://api.github.com/repos/{owner}/{repo}/issues?state=all", headers=headers)
        if ires.ok:
            nb_issues_all = len(ires.json())
    except Exception:
        pass

    # 9) Nettoyage du dépôt local
    try:
        fermer_processus_git(repo_path)
        shutil.rmtree(repo_path, onerror=on_rm_error)
    except Exception as e:
        print(f"❌ Erreur nettoyage pour {nom_etudiant} : {e}")

    return {
        "etudiant": base_name,
        "TDs": TDs,
        "total_commits": total_commits,
        "total_ajouts": total_ajouts,
        "total_suppressions": total_suppressions,
        "total_fichiers": total_fichiers,
        "score_global": round(score_global, 2),
        "nb_branches": nb_branches,
        "nb_pulls_all": nb_pulls_all,
        "nb_issues_all": nb_issues_all
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
        # Récupérer le sous-dict de deadlines pour cet étudiant (ou {} si absent)
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
        # On s'attend à deux manières de spécifier les deadlines :
        # 1) Soit un champ "deadlines" = { "YYYY-MM-DD": "HH:MM", … }
        # 2) Soit un champ "deadline" = "HH:MM" (identique chaque samedi)
        raw_dead = item.get("deadlines")
        single_dead = item.get("deadline")

        if nom and url:
            liste_etudiants[nom] = url
            if token:
                token_communs[nom] = token

            if isinstance(raw_dead, dict):
                # l'utilisateur a fourni un dict date->horaire
                deadlines_map[nom] = raw_dead
            elif isinstance(single_dead, str) and single_dead.strip():
                # on considère que tous les samedis, la deadline est la même
                # on la stocke sous la clé spéciale "global" en interne
                deadlines_map[nom] = {"global": single_dead.strip()}
            else:
                deadlines_map[nom] = {}

    return liste_etudiants, token_communs, deadlines_map
