"""Phase 0a — download the Kaggle datasets used by GigSim into data/raw/ (git-ignored).

Authentication is optional for these public datasets (they download anonymously).
To authenticate anyway (either works):
  1. KAGGLE_API_TOKEN in the environment or .env (the "Generate New Token"
     key from https://www.kaggle.com/settings/api)
  2. ~/.kaggle/kaggle.json ({"username": ..., "key": ...})
  3. KAGGLE_USERNAME + KAGGLE_KEY in the environment or .env

Idempotent: datasets whose target directory already contains CSVs are skipped.
Run from the repo root:  python data/scripts/download.py  (or `make download`)
"""

import contextlib
import io
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

DATASETS = [
    "asaniczka/upwork-job-postings-dataset-2024-50k-records",
    "asaniczka/all-jobs-on-upwork-200k-plus",
    "ahmedmyalo/upwork-freelance-jobs-60k",
    "asaniczka/freelance-contracts-dataset-1-3-million-entries",
    "sarveshchhetri/freelancer-success-earnings-and-churn-prediction",
    "adityammantri/trial-1",
]


def load_env_file() -> None:
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> int:
    load_env_file()
    has_creds = (os.environ.get("KAGGLE_API_TOKEN")
                 or (os.environ.get("KAGGLE_USERNAME") and os.environ.get("KAGGLE_KEY"))
                 or Path.home().joinpath(".kaggle", "kaggle.json").exists())
    if not has_creds:
        print("[warn] no Kaggle credentials found - public datasets still download "
              "anonymously; set KAGGLE_API_TOKEN in .env if a dataset requires auth",
              file=sys.stderr)

    with contextlib.redirect_stdout(io.StringIO()):
        import kaggle

    raw_dir = REPO_ROOT / "data" / "raw"
    for dataset in DATASETS:
        target = raw_dir / dataset.split("/")[1]
        existing = [f for f in target.glob("*") if not f.name.endswith(".kaggle-partial")]
        if target.exists() and existing:
            print(f"[skip]     {dataset} -> {target} (files already present)")
            continue
        print(f"[download] {dataset} -> {target}")
        target.mkdir(parents=True, exist_ok=True)
        try:
            kaggle.api.dataset_download_files(dataset, path=str(target), unzip=True)
        except Exception as exc:  # noqa: BLE001 - keep downloading the remaining datasets
            print(f"[error]    {dataset} failed: {exc}", file=sys.stderr)
            return 1
    print("[done] all datasets available under data/raw/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
