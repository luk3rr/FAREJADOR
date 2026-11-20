# Filename: gen_api_types.py
# Created on: November 21, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

"""Write web/src/api/types.ts from the OpenAPI schema of the API.

Run it after changing a response model of the API:

    uv run python scripts/gen_api_types.py
"""

from pathlib import Path

from farejador.web.typegen import generate_types

TARGET = Path(__file__).resolve().parent.parent / "web" / "src" / "api" / "types.ts"


def main() -> None:
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(generate_types(), encoding="utf-8")
    print(f"wrote {TARGET}")


if __name__ == "__main__":
    main()
