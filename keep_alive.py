import os
import json
from flask import Flask, make_response
from threading import Thread

app = Flask(name)

# Callback fournie par main.py pour lire le cache vanilla
_vanilla_callback = None

@app.route("/")
def home():
    return "ok"

@app.route("/health")
def health():
    return "ok"

@app.route("/vanilla.json")
def vanilla():
    try:
        payload = _vanilla_callback() if callable(_vanilla_callback) else {}
    except Exception as e:
        payload = {"error": str(e)}
    resp = make_response(json.dumps(payload), 200)
    resp.headers["Content-Type"] = "application/json"
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp

def register_vanilla_callback(fn):
    global _vanilla_callback
    _vanilla_callback = fn

def _run():
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)

def keep_alive():
    Thread(target=_run, daemon=True).start()
