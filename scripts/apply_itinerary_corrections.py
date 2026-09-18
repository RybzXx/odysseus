"""Apply reviewed itinerary corrections after backup and regression checks."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.itinerary.corrections import CORRECTIONS, apply_reviewed_corrections

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(apply_reviewed_corrections() if args.apply else CORRECTIONS, indent=2))
