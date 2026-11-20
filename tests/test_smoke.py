# Filename: test_smoke.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

import farejador


def test_package_exposes_version() -> None:
    assert farejador.__version__ == "0.1.0"
