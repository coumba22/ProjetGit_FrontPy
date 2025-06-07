from flask import Flask, render_template
from flask_cors import CORS
import os

def create_app():

    app = Flask(__name__)
    CORS(app)

    from .routes.audit import audit_bp
    from .routes.gitstats import gitstats_bp 
    from .routes.indicateurs import indicateurs_bp
    from .routes.stats import stats_bp

    app.register_blueprint(audit_bp)
    app.register_blueprint(gitstats_bp)
    app.register_blueprint(indicateurs_bp)
    app.register_blueprint(stats_bp)

    # ---------- Page d'accueil ----------
    @app.route('/')
    def index():
        os.makedirs("static/images", exist_ok=True)
        return render_template('index.html')


    return app