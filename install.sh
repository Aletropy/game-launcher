#!/usr/bin/env bash
echo Installing all dependencies
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
echo All dependencies installed. Start with run.sh
