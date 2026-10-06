#!/usr/bin/env bash
set -e
python -m pip install --upgrade pip
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
