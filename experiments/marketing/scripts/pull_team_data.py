"""두 팀 브랜치의 합성 데이터를 git show 로 꺼내 data/team/ 에 저장.

커밋하지 않음 — data/ 는 .gitignore 에 포함.

사용법:
    cd experiments/marketing
    python -m scripts.pull_team_data
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "data" / "team"

C2_BRANCH = "origin/feat/review-insight"
C2_DATA = "services/review-insight/data/synthetic"
STORES = ("store_basak", "store_mongle", "store_ongi")
FILES = ("store.json", "reviews.json", "labels.json")


def git_show(ref: str, path: str) -> bytes:
    result = subprocess.run(
        ["git", "show", f"{ref}:{path}"],
        capture_output=True,
        cwd=BASE.parent,  # experiments/ (git root)
    )
    if result.returncode != 0:
        raise RuntimeError(f"git show {ref}:{path} 실패: {result.stderr.decode()}")
    return result.stdout


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    for store in STORES:
        store_dir = OUT / store
        store_dir.mkdir(exist_ok=True)
        for fname in FILES:
            src = f"{C2_DATA}/{store}/{fname}"
            data = git_show(C2_BRANCH, src)
            dest = store_dir / fname
            dest.write_bytes(data)
            print(f"  {dest.relative_to(BASE)}")

    print(f"\n저장 완료: {OUT.relative_to(BASE)}")


if __name__ == "__main__":
    main()
