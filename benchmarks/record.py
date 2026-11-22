"""Record the cassettes: IdroGEO's real answers to every case (needs the network).

    python -m benchmarks.record                 # every case with network checks
    python -m benchmarks.record --case sarno    # one case

Each case is run with the library through a recording transport; the search
check also records IdroGEO's answer to its own default fields (the 400 of
#9), so the constant method meets it offline. Then run
``python -m benchmarks.run --record`` and look at what changed.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
from collections.abc import Sequence
from datetime import UTC, datetime

import httpx

from benchmarks.cassettes import Recorder
from benchmarks.methods import METHODS
from benchmarks.run import answer, load_cases
from ispra_idrogeo import IdroGEO

OFFLINE = {"reliability"}


async def record(case_id: str | None = None) -> None:
    today = datetime.now(UTC).date().isoformat()
    library, constant = METHODS
    for case in load_cases():
        if case_id and case["id"] != case_id:
            continue
        if all(c["kind"] in OFFLINE for c in case["check"]):
            continue
        recorder = Recorder()
        async with httpx.AsyncClient(transport=recorder, timeout=120) as client:
            idrogeo = IdroGEO(client, retries=0)
            for check in case["check"]:
                await answer(library, idrogeo, check)
                if check["kind"] == "search":
                    with contextlib.suppress(httpx.HTTPStatusError):  # the 400 we came for
                        await answer(constant, idrogeo, check)
        print(recorder.save(case["id"], today), len(recorder.entries), "answers")


def main(argv: Sequence[str] | None = None) -> None:
    top = argparse.ArgumentParser(prog="python -m benchmarks.record", description=__doc__)
    top.add_argument("--case", help="only this case id")
    asyncio.run(record(top.parse_args(argv).case))


if __name__ == "__main__":
    main()
