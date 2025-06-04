import os
import shutil
import subprocess
import stat
import time
import json
from typing import Optional, Dict, Any, List
from urllib.parse import urlparse
from collections import defaultdict, Counter
from datetime import datetime
from pydriller import Repository
from radon.complexity import cc_visit
import matplotlib.pyplot as plt
import psutil  # Pour fermer les processus Git/GitStats sous Windows

# --------------------------------------------------------------------
#    Fonctions utilitaires (suppression forcée sous Windows, etc.)
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
    Utile pour éviter que Git/GitStats verrouillent des fichiers.
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
    Exemple :
      inject_token_in_url("https://github.com/user/proj.git", "ghp_XXX")
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
def lancer_audit(repo_url: str, token: Optional[str] = None, deadline: Optional[str] = None) -> Dict[str, Any]:
    """
    1) Clone le dépôt 'repo_url' dans 'temp_repo'
    2) Calcule :
       - commits par auteur,
       - fichiers les plus modifiés,
       - complexité cyclomatique (pour chaque .py),
       - évolution temporelle des commits,
       - co-modifications par fichier,
       - génère graphiques (commits.png, évolution.png),
       - appelle l’API GitStats backend pour générer le rapport HTML complet,
       - supprime 'temp_repo'.
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
        time.sleep(1)
    except subprocess.CalledProcessError:
        return {"error": "❌ Clonage échoué. Vérifie l'URL ou ton token."}

    # 3) Collecte PyDriller & Radon
    commits_par_auteur    = Counter()
    fichiers_modifies     = Counter()
    complexites           = {}
    evolution_par_auteur  = defaultdict(lambda: defaultdict(int))
    co_modification       = defaultdict(lambda: defaultdict(int))
    auteur_fichiers       = defaultdict(set)

    try:
        for commit in Repository(repo_path).traverse_commits():
            auteur   = commit.author.name or "Inconnu"
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
    except Exception:
        graph_path = None

    # 4.b) Graphe « Évolution temporelle par auteur »
    evo_path = "static/images/evolution.png"
    try:
        deadline_dt = datetime.strptime(deadline, "%Y-%m-%d") if deadline else None
        plt.figure(figsize=(10, 5))
        for auteur, dates_dict in evolution_par_auteur.items():
            dates    = sorted(dates_dict.keys())
            dates_dt = [datetime.strptime(d, "%Y-%m-%d") for d in dates]
            counts   = [dates_dict[d] for d in dates]
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
    except Exception as e:
        print("Erreur génération graphe évolution :", e)

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
        "graph_url": graph_path,
        "evolution": dict(evolution_par_auteur),
        "co_modification": {f: dict(a) for f, a in co_modification.items()},
        "gitstats_url": gitstats_url
    }

# --------------------------------------------------------------------
#        Charger et traiter le fichier tds.json (classe entière)
# --------------------------------------------------------------------
def charger_tds() -> (Dict[str, str], Dict[str, str], Dict[str, str]):
    """
    Lit 'tds.json' et renvoie trois dicts :
      - liste_etudiants : { "Alice": "https://…", … }
      - token_communs   : { "Alice": "ghp_…", … }
      - deadlines_map   : { "2025-03-07": "23:59", … }
    Gère l’absence ou le JSON mal formé.
    """
    liste_etudiants = {}
    token_communs   = {}
    deadlines_map   = {}

    if not os.path.exists("tds.json"):
        print("⚠️ tds.json introuvable. Aucun TD de classe ne sera pris en compte.")
        return liste_etudiants, token_communs, deadlines_map

    try:
        with open("tds.json", "r", encoding="utf-8") as f:
            contenu = f.read().strip()
            if not contenu:
                raise json.JSONDecodeError("Fichier vide", "", 0)
            data = json.loads(contenu)
    except json.JSONDecodeError as e:
        print(f"❌ Impossible de lire tds.json : {e}. Aucun TD de classe ne sera pris en compte.")
        return liste_etudiants, token_communs, deadlines_map
    except Exception as e:
        print(f"❌ Erreur inattendue lors du chargement de tds.json : {e}")
        return liste_etudiants, token_communs, deadlines_map

    for ent in data:
        nom      = ent.get("nom")
        repo_url = ent.get("repo_url")
        token    = ent.get("token", None)
        deadline = ent.get("deadline", None)

        if not nom or not repo_url:
            # On ignore les entrées incomplètes
            continue

        liste_etudiants[nom] = repo_url
        token_communs[nom]   = token or ""

        if deadline:
            # On fixe la deadline de chaque TD à 23:59 ce jour-là
            deadlines_map[deadline] = "23:59"

    return liste_etudiants, token_communs, deadlines_map

# --------------------------------------------------------------------
#   Analyse « TD par TD » pour un dépôt-étudiant donné
# --------------------------------------------------------------------
def analyser_etudiant(
    nom_etudiant: str,
    repo_url: str,
    token: Optional[str],
    deadlines: Dict[str, str],
    poids: Optional[Dict[str, float]]
) -> Dict[str, Any]:
    """
    Pour un étudiant donné :
      - clone son dépôt dans "temp_etudiant_<nom>",
      - pour chaque commit du samedi (weekday()==5), calcule :
         • ajouts (added_lines)
         • suppressions (deleted_lines)
         • fichiers touchés :correspond au nombre de fichiers modifiés 
         (ajoutés, supprimés ou simplement changés) lors du commit 
         (ou de l’ensemble des commits du TD), et non au nombre de lignes. 
         Les lignes ajoutées et supprimées sont comptées dans les colonnes « Ajouts » 
         et « Suppressions ».
         • score_TD = commits * w_c + (ajouts + suppressions) * w_l + fichiers * w_f
         • a_heure (commit avant la deadline du samedi)
      - renvoie un dict structuré ainsi :

        {
          "etudiant": "nom_du_repo",
          "TDs": {
             "YYYY-MM-DD": {
               "date_commit":   "YYYY-MM-DD HH:MM",
               "commits":       N,
               "ajouts":        A,
               "suppressions":  S,
               "fichiers":      F,
               "score":         X.X,
               "a_heure":       True/False
             },
             …
          },
          "total_commits":    …,
          "total_ajouts":     …,
          "total_suppressions": …,
          "total_fichiers":   …,
          "score_global":     …
        }
    """
    repo_path = f"temp_etudiant_{nettoyer_nom_repo(repo_url)}"
    if os.path.exists(repo_path):
        fermer_processus_git(repo_path)
        shutil.rmtree(repo_path, onerror=on_rm_error)

    # 1) Clonage du dépôt étudiant
    url_to_clone = inject_token_in_url(repo_url, token)
    try:
        subprocess.check_call(["git", "clone", url_to_clone, repo_path])
        time.sleep(0.5)
    except subprocess.CalledProcessError:
        return {"error": f"❌ Clonage échoué pour {nom_etudiant}."}

    # 2) Préparation des compteurs
    TDs = {}  # { "YYYY-MM-DD": { … } }
    total_commits      = 0
    total_ajouts       = 0
    total_suppressions = 0
    total_fichiers     = 0
    score_global       = 0.0

    # 3) Pondérations par défaut si non fournies
    if poids is None:
        w_c = 1.0   # poids du nombre de commits
        w_l = 0.5   # poids du total lignes ajoutées+supprimées
        w_f = 0.2   # poids des fichiers touchés
    else:
        w_c = poids.get("commits", 1.0)
        w_l = poids.get("ligne", 0.5)
        w_f = poids.get("fichier", 0.2)

    # 4) Itération sur tous les commits (PyDriller)
    try:
        for commit in Repository(repo_path).traverse_commits():
            dt = commit.author_date
            if dt.weekday() != 5:
                # Ne retenir que les samedis
                continue

            date_semaine = dt.strftime("%Y-%m-%d")

            if date_semaine not in TDs:
                TDs[date_semaine] = {
                    "date_commit":   dt.strftime("%Y-%m-%d %H:%M"),
                    "commits":       0,
                    "ajouts":        0,
                    "suppressions":  0,
                    "fichiers":      0,
                    "score":         0.0,
                    "a_heure":       True
                }

            # 4.a) Incrémenter le nbre de commits pour cette date
            TDs[date_semaine]["commits"] += 1

            # 4.b) Parcourir les modifications de fichiers
            ajouts = 0
            suppressions = 0
            fichiers_touchés = 0

            for mod in commit.modified_files:
                # AttributeError s’il n’existe pas, on utilise getattr
                a = getattr(mod, "added_lines", 0)
                d = getattr(mod, "deleted_lines", 0)
                ajouts += a
                suppressions += d
                fichiers_touchés += 1

            TDs[date_semaine]["ajouts"]      += ajouts
            TDs[date_semaine]["suppressions"]+= suppressions
            TDs[date_semaine]["fichiers"]    += fichiers_touchés

            # 5) Vérifier si commit avant la deadline du samedi
            horaire_limite = deadlines.get(date_semaine)
            if horaire_limite:
                limite_str = f"{date_semaine} {horaire_limite}"
                dt_limite = datetime.strptime(limite_str, "%Y-%m-%d %H:%M")
                if dt > dt_limite:
                    TDS = TDs[date_semaine]
                    TDS["a_heure"] = False

            # 6) Calcul du score pour ce TD
            TDS = TDs[date_semaine]
            score_TD = (
                TDS["commits"] * w_c
                + (TDS["ajouts"] + TDS["suppressions"]) * w_l
                + TDS["fichiers"] * w_f
            )
            TDs[date_semaine]["score"] = round(score_TD, 2)

            # 7) Mise à jour des totaux
            total_commits      += TDS["commits"]
            total_ajouts       += TDS["ajouts"]
            total_suppressions += TDS["suppressions"]
            total_fichiers     += TDS["fichiers"]
            score_global       += score_TD

    except Exception as e:
        return {"error": f"Erreur pendant l’analyse des TDs de {nom_etudiant} : {e}"}

    # 8) Nettoyage du dépôt local
    try:
        fermer_processus_git(repo_path)
        shutil.rmtree(repo_path, onerror=on_rm_error)
    except Exception as e:
        print(f"❌ Erreur nettoyage pour {nom_etudiant} : {e}")

    return {
        "etudiant": nettoyer_nom_repo(repo_url),
        "TDs": TDs,
        "total_commits": total_commits,
        "total_ajouts": total_ajouts,
        "total_suppressions": total_suppressions,
        "total_fichiers": total_fichiers,
        "score_global": round(score_global, 2)
    }

# --------------------------------------------------------------------
#       Analyse de tous les étudiants (classe entière)
# --------------------------------------------------------------------
def analyser_classe(
    liste_etudiants: Dict[str, str],
    token_communs: Optional[Dict[str, str]],
    deadlines: Dict[str, str],
    poids: Optional[Dict[str, float]]
) -> Dict[str, Any]:
    """
    Pour chaque étudiant de 'liste_etudiants', appelle analyser_etudiant(...)
    et renvoie un dict { nom_etudiant: résultat_analyse }.
    """
    résultats_totaux: Dict[str, Any] = {}

    for nom, url_repo in liste_etudiants.items():
        token = token_communs.get(nom) if token_communs else None
        try:
            print(f"▶️ Analyse de {nom} ({url_repo}) …")
            res = analyser_etudiant(nom, url_repo, token, deadlines, poids)
            résultats_totaux[nom] = res
        except Exception as e:
            résultats_totaux[nom] = {"error": f"Exception inattendue pour {nom} : {e}"}

    return résultats_totaux
