"""Testhilfen: ein eigener Schluesselsatz und selbst signierte Tokens.

Ein echter Login gegen CCP laesst sich in Tests nicht fahren. Was sich testen
laesst -- und worauf es ankommt -- ist die Pruefung: dass ein Token mit
falschem Issuer, unvollstaendiger Audience oder abgelaufener Gueltigkeit
abgelehnt wird. Dafuer signiert der Test selbst.

**Alle IDs und Namen hier sind erfunden**, nach derselben Regel wie in
``demo/``: Charakter-IDs im Band ``9_000_xxx``, Strukturen ``1035…``, Namen,
die es im Spiel nicht gibt.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

#: Erfundene Kennungen -- keine davon existiert im Spiel.
CHARACTER_ID = 9_000_001
CHARACTER_NAME = "Testpilot Erfunden"
OWNER_HASH = "aaaaaaaaaaaaaaaaaaaaaaaaaaaa="
CLIENT_ID = "0123456789abcdef0123456789abcdef"
STRUCTURE_ID = 1_035_000_000_001
STATION_ID = 9_950_001

KEY_ID = "test-key-1"

_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def jwks_document() -> dict[str, Any]:
    """Der oeffentliche Schluesselsatz, wie CCP ihn ausliefern wuerde."""
    public_jwk = json.loads(
        jwt.algorithms.RSAAlgorithm.to_jwk(_private_key.public_key())  # type: ignore[no-untyped-call]
    )
    public_jwk.update({"kid": KEY_ID, "use": "sig", "alg": "RS256"})
    return {"keys": [public_jwk]}


def access_token(
    *,
    character_id: int = CHARACTER_ID,
    name: str = CHARACTER_NAME,
    owner: str = OWNER_HASH,
    scopes: Any = ("publicData", "esi-assets.read_assets.v1"),
    audience: Any = None,
    issuer: str = "login.eveonline.com",
    expires_in: int = 1200,
    kid: str | None = KEY_ID,
) -> str:
    """Ein signiertes Access Token -- per Vorgabe gueltig, auf Wunsch kaputt."""
    now = dt.datetime.now(dt.UTC)
    payload: dict[str, Any] = {
        "sub": f"CHARACTER:EVE:{character_id}",
        "name": name,
        "owner": owner,
        "scp": scopes,
        "iss": issuer,
        "aud": audience if audience is not None else [CLIENT_ID, "EVE Online"],
        "exp": int((now + dt.timedelta(seconds=expires_in)).timestamp()),
        "iat": int(now.timestamp()),
        "azp": CLIENT_ID,
        "tenant": "tranquility",
        "region": "world",
    }
    headers = {"kid": kid} if kid else {}
    return jwt.encode(payload, _private_key, algorithm="RS256", headers=headers)


def token_response(
    *, access: str | None = None, refresh: str = "refresh-eins", expires_in: int = 1200
) -> dict[str, Any]:
    """Die Antwort des Token-Endpunkts."""
    return {
        "access_token": access if access is not None else access_token(),
        "refresh_token": refresh,
        "expires_in": expires_in,
        "token_type": "Bearer",
    }


def asset(
    item_id: int,
    *,
    type_id: int = 9_900_001,
    quantity: int = 1,
    location_id: int = STRUCTURE_ID,
    location_flag: str = "Hangar",
    singleton: bool = False,
) -> dict[str, Any]:
    """Eine Zeile, wie ESI sie in der Asset-Liste liefert."""
    return {
        "item_id": item_id,
        "type_id": type_id,
        "quantity": quantity,
        "location_id": location_id,
        "location_flag": location_flag,
        "location_type": "other",
        "is_singleton": singleton,
    }
