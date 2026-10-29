import json

from app.beta import build_beta_metrics
from app.database import SessionLocal


def main() -> None:
    with SessionLocal() as db:
        print(json.dumps(build_beta_metrics(db), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
