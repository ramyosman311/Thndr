"""Development seed data: constants only, no logic.

These are initial DATA rows, not permanent application assumptions. The
strategy buckets, allocation percentages, and asset list here are exactly
as specified for this developer's initial portfolio (Phase 4 approval) —
they are read once by seed.py to populate the database, and are never
referenced from business/domain logic (see FINANCIAL_RULES.md, "Database
Is the Source of Truth").

Timestamps in SEED_SNAPSHOTS are stored as given, with UTC attached as the
timezone since none was specified in the source data — this is a seeding
convention, not a business rule.
"""

from datetime import datetime, timezone
from decimal import Decimal

from app.models.enums import AssetType

# --- Assets --------------------------------------------------------------
# Rows for the `assets` table. No business logic reads these symbols by
# name; they are plain data.
SEED_ASSETS = [
    {"symbol": "CLOUDZ", "name": "كلاودز", "asset_type": AssetType.SAVINGS, "currency": "EGP", "market": None},
    {"symbol": "BWA", "name": "بلتون وفرة", "asset_type": AssetType.FUND, "currency": "EGP", "market": None},
    {"symbol": "AZN", "name": "أزيموت نقد", "asset_type": AssetType.FUND, "currency": "EGP", "market": None},
    {
        "symbol": "TMGH",
        "name": "Talaat Moustafa Group Holding",
        "asset_type": AssetType.STOCK,
        "currency": "EGP",
        "market": "EGX",
    },
    {"symbol": "ETEL", "name": "Telecom Egypt", "asset_type": AssetType.STOCK, "currency": "EGP", "market": "EGX"},
    {
        "symbol": "EFID",
        "name": "Edita Food Industries",
        "asset_type": AssetType.STOCK,
        "currency": "EGP",
        "market": "EGX",
    },
    {"symbol": "GOLD", "name": "Thndr Gold", "asset_type": AssetType.GOLD, "currency": "EGP", "market": None},
]

# --- EGX price configuration (Phase 13, updated with Mubasher) ------------
# Provider configuration for the EGX-listed EQUITY assets only -- TMGH,
# ETEL, EFID (asset_type=STOCK, market="EGX" above). BWA and AZN are
# deliberately excluded here even though an earlier phase brief listed them
# as "potential EGX assets": both are FUND-type (mutual fund NAV) assets in
# this seed data with no `market` set, not EGX-listed equities, so no stock-
# exchange provider applies to them -- see DECISIONS.md, "EGX Provider
# Decision (Phase 13)". CLOUDZ and GOLD are likewise never assigned an EGX
# equity provider.
#
# Mubasher (providers/mubasher_provider.py) is primary for all three --
# its payload shape was independently verified via a live network test
# performed OUTSIDE this sandbox (this sandbox's own outbound network
# blocks www.mubasher.info, same default-deny policy that also blocks
# Yahoo/EGID/EGXAPI -- see DECISIONS.md, "Mubasher Provider Decision").
# The adapter itself is therefore mock-tested, not live-tested from within
# this environment. Yahoo is retained as `secondary_provider` for each --
# the exact same symbols Phase 13 already configured -- so the existing
# primary-\>secondary-\>DB-\>PRICE_UNAVAILABLE fallback chain is preserved
# rather than narrowed to a single provider.
SEED_ASSET_PRICE_CONFIGS = {
    "TMGH": {
        "primary_provider": "mubasher",
        "primary_provider_symbol": "TMGH",
        "secondary_provider": "yahoo",
        "secondary_provider_symbol": "TMGH.CA",
        "automated_fetching_enabled": True,
    },
    "ETEL": {
        "primary_provider": "mubasher",
        "primary_provider_symbol": "ETEL",
        "secondary_provider": "yahoo",
        "secondary_provider_symbol": "ETEL.CA",
        "automated_fetching_enabled": True,
    },
    "EFID": {
        "primary_provider": "mubasher",
        "primary_provider_symbol": "EFID",
        "secondary_provider": "yahoo",
        "secondary_provider_symbol": "EGS305I1C011.CA",
        "automated_fetching_enabled": True,
    },
}

# --- Portfolio configuration ----------------------------------------------
PORTFOLIO_CONFIG_NAME = "Main Portfolio"
EMERGENCY_ASSET_SYMBOL = "CLOUDZ"

SEED_PORTFOLIO_CONFIG = {
    "name": PORTFOLIO_CONFIG_NAME,
    "base_currency": "EGP",
    "emergency_excluded": True,
    "telegram_enabled": False,
}

# --- Strategy buckets ------------------------------------------------------
# bucket name -> {description, member asset symbols}. These are initial
# data, not permanent categories — buckets can be added, edited, disabled,
# or replaced later through the database/API/UI without a code change.
SEED_STRATEGY_BUCKETS = {
    "Growth / Investment Funds": {
        "description": "Growth-oriented investment fund holdings.",
        "assets": ["BWA"],
    },
    "Defensive / Fixed Income": {
        "description": "Defensive, cash-like / fixed-income fund holdings.",
        "assets": ["AZN"],
    },
    "Individual Stocks": {
        "description": "Directly held individual EGX-listed stocks.",
        "assets": ["TMGH", "ETEL", "EFID"],
    },
    "Gold": {
        "description": "Physical/digital gold holdings.",
        "assets": ["GOLD"],
    },
    "Emergency Cash": {
        "description": "Reserve/emergency cash, excluded from risk and investment allocation.",
        "assets": ["CLOUDZ"],
    },
    "Free Cash": {
        "description": "Uninvested, undeployed cash target.",
        "assets": [],
    },
}

# --- Allocation targets -----------------------------------------------------
# bucket name -> AllocationTarget field values. Deliberately independent
# fields per FINANCIAL_RULES.md: target != maximum != allow_new_buy.
#
# "Emergency Cash" intentionally has NO entry here: it is excluded from
# allocation math entirely via portfolio_configs.emergency_asset_id /
# emergency_excluded, not given a target weight.
SEED_ALLOCATION_TARGETS = {
    "Growth / Investment Funds": {
        "target_percent": Decimal("55"),
        "minimum_percent": None,
        "maximum_percent": None,
        "allow_new_buy": True,
        "priority": 1,
    },
    "Defensive / Fixed Income": {
        "target_percent": Decimal("25"),
        "minimum_percent": None,
        "maximum_percent": None,
        "allow_new_buy": True,
        "priority": 2,
    },
    "Individual Stocks": {
        # No target percent: only a hard maximum. This is NOT a 15% target
        # — the future rebalancing engine must freeze new buys at/above
        # this maximum, and must never auto-sell to enforce it.
        "target_percent": None,
        "minimum_percent": None,
        "maximum_percent": Decimal("15"),
        "allow_new_buy": True,
        "priority": 3,
    },
    "Gold": {
        # Target for NEW purchases only. Existing gold is untouched,
        # remains visible, and no sell rule is implied.
        "target_percent": Decimal("0"),
        "minimum_percent": None,
        "maximum_percent": None,
        "allow_new_buy": False,
        "priority": 4,
    },
    "Free Cash": {
        "target_percent": Decimal("5"),
        "minimum_percent": None,
        "maximum_percent": None,
        "allow_new_buy": True,
        "priority": 5,
    },
}

# --- Historical snapshots ---------------------------------------------------
# Portfolio VALUE snapshots in EGP, at a point in time. Not transactions,
# not quantities, not purchase prices — see FINANCIAL_RULES.md
# ("Snapshot != Transaction"). Quantities/costs are never inferred from
# these values, and no transaction rows are created from them.
SEED_SNAPSHOTS = [
    {
        "snapshot_at": datetime(2026, 9, 7, 12, 35, tzinfo=timezone.utc),
        "label": "Snapshot 1",
        "values": {
            "CLOUDZ": Decimal("100006"),
            "TMGH": Decimal("1292"),
            "ETEL": Decimal("1287"),
            "EFID": Decimal("1204"),
            "BWA": Decimal("4983"),
            "AZN": Decimal("1042"),
            "GOLD": Decimal("961"),
        },
    },
    {
        "snapshot_at": datetime(2026, 9, 7, 21, 51, tzinfo=timezone.utc),
        "label": "Snapshot 2",
        "values": {
            "CLOUDZ": Decimal("100050"),
            "TMGH": Decimal("1300"),
            "ETEL": Decimal("1300"),
            "EFID": Decimal("1220"),
            "BWA": Decimal("5045"),
            "AZN": Decimal("1042"),
            "GOLD": Decimal("956"),
        },
    },
    {
        "snapshot_at": datetime(2026, 9, 8, 10, 10, tzinfo=timezone.utc),
        "label": "Snapshot 3",
        "values": {
            "CLOUDZ": Decimal("100093"),
            "TMGH": Decimal("1288"),
            "ETEL": Decimal("1349"),
            "EFID": Decimal("1250"),
            "BWA": Decimal("5074"),
            "AZN": Decimal("1043"),
            "GOLD": Decimal("957"),
        },
    },
    {
        "snapshot_at": datetime(2026, 9, 8, 21, 52, tzinfo=timezone.utc),
        "label": "Snapshot 4",
        "values": {
            "CLOUDZ": Decimal("100137"),
            "TMGH": Decimal("1274"),
            "ETEL": Decimal("1321"),
            "EFID": Decimal("1251"),
            "BWA": Decimal("5037"),
            "AZN": Decimal("1043"),
            "GOLD": Decimal("948"),
        },
    },
    {
        "snapshot_at": datetime(2026, 9, 9, 9, 20, tzinfo=timezone.utc),
        "label": "Snapshot 5",
        "values": {
            "CLOUDZ": Decimal("100137"),
            "TMGH": Decimal("1274"),
            "ETEL": Decimal("1321"),
            "EFID": Decimal("1251"),
            "BWA": Decimal("5037"),
            "AZN": Decimal("1043"),
            "GOLD": Decimal("955"),
        },
    },
]
