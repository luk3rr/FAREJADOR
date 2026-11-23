# Filename: conftest.py
# Created on: November 23, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""The deploy scripts only run on the Linux server, so their tests run only on Linux."""

import sys

collect_ignore = (
    []
    if sys.platform == "linux"
    else ["test_bootstrap_script.py", "test_update_script.py", "test_verify_script.py"]
)
