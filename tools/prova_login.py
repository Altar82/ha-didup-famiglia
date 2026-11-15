"""Prova il login Argo fuori da Home Assistant e salva la dashboard grezza.

Uso (serve solo aiohttp:  pip install aiohttp):
    python3 tools/prova_login.py SC12345 nomeutente
La password viene chiesta a terminale. Con -v mostra il log dettagliato del flusso.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import importlib.util
import json
import logging
import sys
from pathlib import Path

import aiohttp

BASE = Path(__file__).resolve().parent.parent / "custom_components" / "didup_famiglia"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, BASE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


api = _load("api")
parse = _load("parse")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("school_code")
    ap.add_argument("username")
    ap.add_argument("--version", default="1.30.2", help="argo-client-version")
    ap.add_argument("-v", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if a.v else logging.INFO)
    pwd = getpass.getpass("Password Argo: ")

    async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar()) as s:
        c = api.ArgoClient(s, a.version, school_code=a.school_code, username=a.username, password=pwd)
        profiles = await c.async_login()
        print(f"Login OK: {len(profiles)} profili")
        for p in profiles:
            raw = await c.async_get_dashboard(p)
            out = Path(f"dashboard_{p.unique_id}.json")
            out.write_text(json.dumps(raw, indent=2, ensure_ascii=False, default=str))
            d = parse.parse_dashboard(raw)
            print(
                f"- {p.name} ({p.class_name}): voti={len(d.grades)} media={d.average} "
                f"compiti={len(d.homework)} assenze={len(d.absences)} note={len(d.notes)} "
                f"bacheca={len(d.notices)} -> {out}"
            )


if __name__ == "__main__":
    asyncio.run(main())
