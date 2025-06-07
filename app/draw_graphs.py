import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime
from flask import current_app as app
import logging # Import logging for more generic log handling if 'app.logger' is not always available

# Configure basic logging if app.logger isn't set up yet
# logging.basicConfig(level=logging.DEBUG)


def class_score_graph(resultats_classe):
    # 3) Générer un graphique « Score global par étudiant »
    noms = list(resultats_classe.keys())
    scores = [
        resultats_classe[n]["score_global"] if "score_global" in resultats_classe[n] else 0.0
        for n in noms
    ]
    
    # Define the base directory for saving all images
    image_save_directory = os.path.join("app", "static", "images")
    os.makedirs(image_save_directory, exist_ok=True)
    
    full_image_filepath = os.path.join(image_save_directory, "classe_score.png")

    try:
        plt.figure(figsize=(8, 4))
        plt.bar(noms, scores, color='mediumseagreen')
        plt.title("Score global par étudiant")
        plt.xticks(rotation=45)
        plt.tight_layout()
        plt.savefig(full_image_filepath)      
        plt.close()
        
        # The URL for the browser
        graph_classe_url = "/static/images/classe_score.png"
        
    except Exception as e:
        app.logger.error(f"Erreur lors de la génération du graphique des scores de classe : {e}")
        graph_classe_url = None
        
    app.logger.debug(f"Generated graph URL: {graph_classe_url}")
    return graph_classe_url


def commit_graph(result_audit):
    commits_par_auteur = result_audit.get('commits_par_auteur', {})
    base_name = result_audit.get('base_name', 'default_repo') # Use .get() for safety

    # Define the base directory for saving all images
    image_save_directory = os.path.join("app", "static", "images")
    os.makedirs(image_save_directory, exist_ok=True)
    
    # Define the full filesystem path for this specific image
    full_image_filepath = os.path.join(image_save_directory, f"{base_name}_commits.png")
    
    graph_commits_url = None # Initialize outside try-except

    # Graph Commits
    try:
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.bar(commits_par_auteur.keys(), commits_par_auteur.values(), color='skyblue')
        ax.set_title("Commits par auteur")
        ax.tick_params(axis='x', rotation=45)
        plt.tight_layout()
        
        plt.savefig(full_image_filepath) # Save to the correct filesystem path
        plt.close(fig) # Close the figure to free memory

        # The URL for the browser
        graph_commits_url = f"/static/images/{base_name}_commits.png"
        
    except Exception as e: # Catch specific exception if possible, or general Exception
        app.logger.error(f"Erreur lors de la génération du graphique des commits pour {base_name}: {e}")
        
    app.logger.debug(f"Generated commit graph URL: {graph_commits_url}")
    return graph_commits_url



def evolution_graph(result_audit):
    evolution_par_auteur = result_audit.get('evolution_par_auteur', {})
    deadline = result_audit.get('deadline', None)
    base_name = result_audit.get('base_name', 'default_repo') # Use .get() for safety

    # Define the base directory for saving all images
    image_save_directory = os.path.join("app", "static", "images")
    os.makedirs(image_save_directory, exist_ok=True)
    
    # Define the full filesystem path for this specific image
    full_image_filepath = os.path.join(image_save_directory, f"{base_name}_evolution.png")
    
    graph_evolution_url = None # Initialize outside try-except

    # Graph Évolution
    try:
        fig, ax = plt.subplots(figsize=(10, 5))
        for au, dates in evolution_par_auteur.items():
            xs = sorted(dates.keys()) # Ensure sorting keys, not the dict itself
            ys = [dates[d] for d in xs]
            dx = [datetime.strptime(d, "%Y-%m-%d") for d in xs]
            ax.plot(dx, ys, marker='o', label=au)
            
        if deadline:
            try:
                dl = datetime.strptime(deadline, "%Y-%m-%d")
                ax.axvline(dl, color='black', linestyle='--', label='Deadline')
            except ValueError:
                app.logger.warning(f"Format de date de deadline invalide: {deadline}. Ignoré.")
                
        ax.set_title("Évolution temporelle")
        ax.set_xlabel("Date")
        ax.set_ylabel("Commits")
        ax.tick_params(axis='x', rotation=45)
        ax.legend()
        plt.tight_layout()
        
        plt.savefig(full_image_filepath) # Save to the correct filesystem path
        plt.close(fig) # Close the figure to free memory
        
        # The URL for the browser
        graph_evolution_url = f"/static/images/{base_name}_evolution.png"
        
    except Exception as e: # Catch specific exception if possible, or general Exception
        app.logger.error(f"Erreur lors de la génération du graphique d'évolution pour {base_name}: {e}")
        
    app.logger.debug(f"Generated evolution graph URL: {graph_evolution_url}")
    return graph_evolution_url