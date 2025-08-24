# keep_alive.py
import os
from threading import Thread
from flask import Flask, jsonify, make_response

_app = Flask(__name__)
_TIERS_PROVIDER = lambda: {"tier1": [], "tier2": [], "tier3": [], "tier4": [], "tier5": []}

def set_tiers_provider(fn):
    """main.py nous passe une fonction qui renvoie le dernier JSON tiers."""
    global _TIERS_PROVIDER
    _TIERS_PROVIDER = fn

@_app.route("/")
def root():
    return "OK"

@_app.route("/tiers.json")
def tiers_json():
    data = _TIERS_PROVIDER()
    resp = make_response(jsonify(data))
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Cache-Control"] = "no-store"
    return resp

def _run():
    port = int(os.getenv("PORT", "10000"))
    _app.run(host="0.0.0.0", port=port)

def keep_alive():
    Thread(target=_run, daemon=True).start()
