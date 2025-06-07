import os

from dotenv import load_dotenv
load_dotenv()

from app import create_app
app = create_app()

BACKEND_PORT = os.getenv("BACKEND_PORT")
FRONTEND_PORT  = os.getenv("FRONTEND_PORT")


# ---------- Lancement de l’application ----------
if __name__ == '__main__':
    app.run(debug=True, port=FRONTEND_PORT)

