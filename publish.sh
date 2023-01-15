#!/bin/bash
pip uninstall -y bandmap
rm dist/*
python3 -m build
python3 -m twine upload dist/*
