#!/bin/bash
pip uninstall -y bandmap
rm dist/*
python3 -m build
pip install -e .
