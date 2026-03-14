"""
WalletDNA — Case Manager
========================
Each investigation is a named case directory under cases/.

Structure:
    cases/
        BDAG-Investigation-01/
            case.json          ← wallet list + metadata
            profiles/
                0x4c39...json  ← cached profile, has fetched_at
                TVM6Ku...json

case.json format:
    {
        "name": "BDAG-Investigation-01",
        "created": "2026-03-12",
        "description": "optional",
        "wallets": [
            {"address": "0x...", "label": "Suspect #1", "chain": "ETH"}
        ]
    }

Cache logic:
    - Profile exists + fetched_at < 24h  → use cached
    - Profile exists + fetched_at > 24h  → auto re-fetch
    - Profile missing                    → fetch live, save
    - Force refresh                      → re-fetch regardless
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)

# Root cases directory — sits at project root
CASES_DIR = Path(__file__).parent.parent.parent / "cases"
CACHE_TTL_HOURS = 24


# ─── Address Detection ────────────────────────────────────────────────────────


def detect_chain(address: str) -> Optional[str]:
    addr = address.strip()
    if re.match(r"^0x[0-9a-fA-F]{40}$", addr):
        return "ETH"
    if re.match(r"^T[1-9A-HJ-NP-Za-km-z]{33}$", addr):
        return "TRX"
    if re.match(r"^D[1-9A-HJ-NP-Za-km-z]{32,34}$", addr):
        return "DOGE"
    return None


# ─── Case Manager ─────────────────────────────────────────────────────────────


class CaseManager:
    """
    CRUD operations for cases.  Caller is responsible for all display logic.
    """

    def __init__(self, cases_dir: Optional[Path] = None):
        self.root = cases_dir or CASES_DIR
        self.root.mkdir(parents=True, exist_ok=True)

    # ── Discovery ──────────────────────────────────────────────────────────────

    def list_cases(self) -> list[dict]:
        """
        Return all cases as summary dicts sorted newest-first.
        Each dict: {name, path, wallet_count, created, last_run, profile_count}
        """
        cases = []
        for d in sorted(self.root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if not d.is_dir():
                continue
            case_file = d / "case.json"
            if not case_file.exists():
                continue
            try:
                meta = self._load_case_file(d)
                profile_count = (
                    len(list((d / "profiles").glob("*.json"))) if (d / "profiles").exists() else 0
                )
                cases.append(
                    {
                        "name": meta["name"],
                        "path": d,
                        "wallet_count": len(meta.get("wallets", [])),
                        "created": meta.get("created", "unknown"),
                        "description": meta.get("description", ""),
                        "last_run": meta.get("last_run"),
                        "profile_count": profile_count,
                    }
                )
            except Exception as e:
                logger.warning("case_list_parse_error", dir=d.name, error=str(e))
        return cases

    def case_exists(self, name: str) -> bool:
        return (self.root / name / "case.json").exists()

    # ── Create / Open ──────────────────────────────────────────────────────────

    def create_case(self, name: str, description: str = "") -> Path:
        """
        Create a new empty case.  Raises FileExistsError if already present.
        Returns path to case directory.
        """
        case_dir = self.root / name
        if case_dir.exists():
            raise FileExistsError(f"Case '{name}' already exists.")
        case_dir.mkdir(parents=True)
        (case_dir / "profiles").mkdir()

        case_data = {
            "name": name,
            "created": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "description": description,
            "wallets": [],
        }
        self._write_case_file(case_dir, case_data)
        logger.info("case_created", name=name)
        return case_dir

    def open_case(self, name: str) -> dict:
        """
        Load case metadata.  Raises FileNotFoundError if not present.
        """
        case_dir = self.root / name
        if not (case_dir / "case.json").exists():
            raise FileNotFoundError(f"Case '{name}' not found.")
        return self._load_case_file(case_dir)

    def get_case_dir(self, name: str) -> Path:
        return self.root / name

    # ── Wallet Management ──────────────────────────────────────────────────────

    def add_wallets(self, name: str, entries: list[dict]) -> tuple[int, int]:
        """
        Add wallets to a case.  Each entry: {"address": str, "label": str}.
        Chain is auto-detected and injected.
        Returns (added_count, skipped_count).
        """
        case_dir = self.root / name
        meta = self._load_case_file(case_dir)
        existing = {w["address"].lower() for w in meta.get("wallets", [])}

        added = 0
        skipped = 0
        for entry in entries:
            addr = entry["address"].strip()
            if not addr:
                continue
            chain = detect_chain(addr)
            if not chain:
                logger.warning("add_wallets_unrecognised", address=addr[:16])
                skipped += 1
                continue
            if addr.lower() in existing:
                skipped += 1
                continue
            meta.setdefault("wallets", []).append(
                {
                    "address": addr,
                    "label": entry.get("label", f"Wallet #{len(meta['wallets']) + 1}"),
                    "chain": chain,
                }
            )
            existing.add(addr.lower())
            added += 1

        self._write_case_file(case_dir, meta)
        logger.info("wallets_added", case=name, added=added, skipped=skipped)
        return added, skipped

    def remove_wallet(self, name: str, address: str) -> bool:
        """Remove a wallet from a case by address.  Returns True if removed."""
        case_dir = self.root / name
        meta = self._load_case_file(case_dir)
        before = len(meta.get("wallets", []))
        meta["wallets"] = [
            w for w in meta.get("wallets", []) if w["address"].lower() != address.lower()
        ]
        if len(meta["wallets"]) == before:
            return False
        self._write_case_file(case_dir, meta)
        # Also remove cached profile if present
        self._delete_profile(case_dir, address)
        return True

    def relabel_wallet(self, name: str, address: str, label: str) -> bool:
        """Update the label for a wallet.  Returns True if found and updated."""
        case_dir = self.root / name
        meta = self._load_case_file(case_dir)
        for w in meta.get("wallets", []):
            if w["address"].lower() == address.lower():
                w["label"] = label
                self._write_case_file(case_dir, meta)
                return True
        return False

    def get_wallets(self, name: str) -> list[dict]:
        """Return wallet list for a case."""
        meta = self.open_case(name)
        return meta.get("wallets", [])

    # ── Profile Cache ──────────────────────────────────────────────────────────

    def load_profile(self, name: str, address: str) -> Optional[dict]:
        """
        Load cached profile for this address within this case.
        Returns None if not cached.
        """
        path = self._profile_path(name, address)
        if not path.exists():
            return None
        try:
            with open(path) as f:
                return json.load(f)
        except Exception as e:
            logger.warning("profile_load_failed", address=address[:12], error=str(e))
            return None

    def save_profile(self, name: str, profile: dict) -> None:
        """Save a profile dict to this case's profiles directory."""
        address = profile.get("address", "unknown")
        path = self._profile_path(name, address)
        profile["fetched_at"] = datetime.now(timezone.utc).isoformat()
        (path.parent).mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(profile, f, indent=2, default=str)
        logger.info("profile_saved", case=name, address=address[:12])

    def is_profile_fresh(self, name: str, address: str) -> bool:
        """
        Return True if the cached profile is < CACHE_TTL_HOURS old.
        Returns False if missing, expired, or unparseable.
        """
        profile = self.load_profile(name, address)
        if not profile:
            return False
        fetched_at = profile.get("fetched_at")
        if not fetched_at:
            return False
        try:
            ts = datetime.fromisoformat(fetched_at)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age = datetime.now(timezone.utc) - ts
            return age < timedelta(hours=CACHE_TTL_HOURS)
        except Exception:
            return False

    def load_all_profiles(self, name: str) -> list[dict]:
        """Load all cached profiles for a case."""
        case_dir = self.root / name
        profiles_dir = case_dir / "profiles"
        if not profiles_dir.exists():
            return []
        profiles = []
        for p in profiles_dir.glob("*.json"):
            try:
                with open(p) as f:
                    profiles.append(json.load(f))
            except Exception:
                pass
        return profiles

    def wipe_profiles(self, name: str) -> int:
        """Delete all cached profiles for a case.  Wallet list survives."""
        case_dir = self.root / name
        profiles_dir = case_dir / "profiles"
        count = 0
        if profiles_dir.exists():
            for p in profiles_dir.glob("*.json"):
                p.unlink()
                count += 1
        logger.info("profiles_wiped", case=name, count=count)
        return count

    # ── Metadata Updates ───────────────────────────────────────────────────────

    def touch_last_run(self, name: str) -> None:
        """Stamp last_run on the case metadata."""
        case_dir = self.root / name
        meta = self._load_case_file(case_dir)
        meta["last_run"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        self._write_case_file(case_dir, meta)

    # ── Delete ─────────────────────────────────────────────────────────────────

    def delete_case(self, name: str) -> bool:
        """
        Delete a case directory entirely.
        Returns False if not found.
        WARNING: irreversible.
        """
        import shutil

        case_dir = self.root / name
        if not case_dir.exists():
            return False
        shutil.rmtree(case_dir)
        logger.info("case_deleted", name=name)
        return True

    # ── Internal ───────────────────────────────────────────────────────────────

    def _load_case_file(self, case_dir: Path) -> dict:
        with open(case_dir / "case.json") as f:
            return json.load(f)

    def _write_case_file(self, case_dir: Path, data: dict) -> None:
        with open(case_dir / "case.json", "w") as f:
            json.dump(data, f, indent=2)

    def _profile_path(self, name: str, address: str) -> Path:
        case_dir = self.root / name
        return case_dir / "profiles" / f"{address.lower()}.json"

    def _delete_profile(self, case_dir: Path, address: str) -> None:
        path = case_dir / "profiles" / f"{address.lower()}.json"
        if path.exists():
            path.unlink()
