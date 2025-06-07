import os
from flask import Flask, request, render_template

app = Flask(__name__)
from routes import audit, gitstats, indicateurs, stats


# ---------- Page d'accueil ----------
@app.route('/')
def index():
    return render_template('index.html')


# ---------- Lancement de l’application ----------
if __name__ == '__main__':
    os.makedirs("static/images", exist_ok=True)
    app.run(debug=True, port=5001)

