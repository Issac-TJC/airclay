from pathlib import Path
from airclay.data_tools.synthetic import make_fixtures
from airclay.data_tools.dataset import create_split

ROOT=Path(__file__).resolve().parents[1]
folder=ROOT/"runs/synthetic_smoke_data"
make_fixtures(folder)
create_split(folder,ROOT/"runs/smoke_split.json",allow_small=True)
print("Created synthetic plumbing fixtures only; not a gesture recognition dataset.")
