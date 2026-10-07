"""Batch entry point for the frozen-role profile; reuses batch accounting."""
import argparse
from pathlib import Path
import sys

import collaboration_batch as batch
import collaboration_profile_runner as profile


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    batch.runner = profile
    sys.exit(batch.execute(args.manifest))
