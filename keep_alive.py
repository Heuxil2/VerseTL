# keep_alive.py
from flask import Flask
from threading import Thread
import os

app = Flask('')

@app.route('/')
def home():
    return "Bot is running!"

def run():
    # Render fournit automatiquement le port via la variable d'environnement PORT
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    # Lance le serveur Flask dans un thread séparé
    t = Thread(target=run)
    t.daemon = True  # Permet au thread de s'arrêter si le bot se ferme
    t.start()
