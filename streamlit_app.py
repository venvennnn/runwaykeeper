"""Streamlit App Entrypoint for RunwayKeeper."""

import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
API_DIR = os.path.join(BASE_DIR, "apps", "api")

if API_DIR not in sys.path:
    sys.path.insert(0, API_DIR)
if BASE_DIR not in sys.path:
    sys.path.insert(1, BASE_DIR)

import app.streamlit_app
