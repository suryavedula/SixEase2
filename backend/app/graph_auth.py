"""Microsoft Graph delegated auth — authorization-code + PKCE (TASK-061, EPIC-08).

Switches the Graph transport from app-only (client-credentials, graph_mail._token)
to DELEGATED: the RM signs in with their own Microsoft account via a web "Sign in
with Microsoft" button, and the app then reads/sends THROUGH the shared mailbox on
their behalf (Mail.Read.Shared / Mail.Send.Shared). This keeps the human-in-the-loop
boundary honest — every Graph call is attributable to the signed-in RM, never a
faceless daemon.

MSAL's ConfidentialClientApplication does the OAuth heavy lifting (PKCE, refresh).
MSAL is synchronous, so each network call is offloaded with asyncio.to_thread to
avoid blocking the event loop. The token cache is persisted in Redis so the RM
stays signed in across restarts; the short-lived auth-code "flow" (state +
code_verifier) is parked in Redis between the login redirect and the callback.

No-fallbacks: `get_access_token()` raises NotSignedInError when no valid token or
usable refresh token exists — callers surface "RM must sign in", never a silent
app-only substitution.
"""

import asyncio
import json

from app.config import get_settings
from app.logging import get_logger
from app.redis_client import redis_client

settings = get_settings()
log = get_logger(__name__)

# Single-RM workbench → a single shared token cache + account. Keyed in Redis.
_CACHE_KEY = "ms_graph:token_cache"
_FLOW_PREFIX = "ms_graph:flow:"
_FLOW_TTL = 600  # seconds — the login→callback round trip is short-lived.
_CACHE_TTL = 60 * 60 * 24 * 90  # 90d — refresh-token lifetime ceiling; refreshed on use.


class NotSignedInError(RuntimeError):
    """No valid delegated token and no usable refresh token — the RM must sign in."""


def _scopes() -> list[str]:
    # MSAL injects openid/profile/offline_access itself; they must NOT be listed.
    return [s.strip() for s in settings.ms_graph_scopes.split(",") if s.strip()]


async def _load_cache():
    """Build a SerializableTokenCache hydrated from Redis (empty if absent)."""
    import msal

    cache = msal.SerializableTokenCache()
    raw = await redis_client.get(_CACHE_KEY)
    if raw:
        cache.deserialize(raw)
    return cache


async def _save_cache(cache) -> None:
    """Persist the cache back to Redis only when MSAL mutated it."""
    if cache.has_state_changed:
        await redis_client.set(_CACHE_KEY, cache.serialize(), ex=_CACHE_TTL)


def _build_app(cache):
    """Construct a confidential client bound to the given token cache."""
    import msal

    return msal.ConfidentialClientApplication(
        client_id=settings.ms_graph_client_id,
        authority=f"{settings.ms_graph_authority}/{settings.ms_graph_tenant_id}",
        client_credential=settings.ms_graph_client_secret,
        token_cache=cache,
    )


async def build_login_url() -> str:
    """Begin auth-code+PKCE: stash the flow in Redis, return the Microsoft auth URL."""
    cache = await _load_cache()
    app = _build_app(cache)
    flow = await asyncio.to_thread(
        app.initiate_auth_code_flow,
        _scopes(),
        redirect_uri=settings.ms_graph_redirect_uri,
    )
    if "state" not in flow or "auth_uri" not in flow:
        raise RuntimeError("MSAL failed to initiate the auth-code flow")
    await redis_client.set(_FLOW_PREFIX + flow["state"], json.dumps(flow), ex=_FLOW_TTL)
    log.info("graph_auth.login_initiated")
    return flow["auth_uri"]


async def redeem_code(auth_response: dict) -> dict:
    """Exchange the callback code for tokens; persist the cache. Returns id_token claims.

    Raises ValueError on a missing/expired flow state and RuntimeError on an OAuth
    error — the callback route maps both to a failed-sign-in redirect.
    """
    state = auth_response.get("state")
    if not state:
        raise ValueError("Missing OAuth state in callback")
    raw = await redis_client.get(_FLOW_PREFIX + state)
    if not raw:
        raise ValueError("Unknown or expired OAuth flow state")
    flow = json.loads(raw)

    cache = await _load_cache()
    app = _build_app(cache)
    result = await asyncio.to_thread(app.acquire_token_by_auth_code_flow, flow, auth_response)
    await redis_client.delete(_FLOW_PREFIX + state)

    if "error" in result:
        raise RuntimeError(f"{result.get('error')}: {result.get('error_description')}")
    await _save_cache(cache)
    log.info("graph_auth.signed_in")
    return result.get("id_token_claims", {})


async def _first_account(app):
    accounts = await asyncio.to_thread(app.get_accounts)
    return accounts[0] if accounts else None


async def get_access_token() -> str:
    """Return a valid delegated access token, refreshing silently if needed.

    Raises NotSignedInError when no account is cached or the silent refresh fails —
    the caller must prompt the RM to sign in again. No app-only fallback.
    """
    cache = await _load_cache()
    app = _build_app(cache)
    account = await _first_account(app)
    if account is None:
        raise NotSignedInError("No signed-in Microsoft account — RM must sign in")

    result = await asyncio.to_thread(app.acquire_token_silent, _scopes(), account=account)
    await _save_cache(cache)
    if not result or "access_token" not in result:
        raise NotSignedInError("Silent token refresh failed — RM must sign in again")
    return result["access_token"]


async def current_account() -> dict | None:
    """Return {username, name} for the signed-in RM, or None if not signed in."""
    cache = await _load_cache()
    app = _build_app(cache)
    account = await _first_account(app)
    if account is None:
        return None
    # MSAL account dicts carry `username`; `name` may be absent depending on tenant.
    return {"username": account.get("username"), "name": account.get("name")}


async def sign_out() -> None:
    """Forget the signed-in account and drop the cached tokens from Redis."""
    cache = await _load_cache()
    app = _build_app(cache)
    for acc in await asyncio.to_thread(app.get_accounts):
        await asyncio.to_thread(app.remove_account, acc)
    await _save_cache(cache)
    await redis_client.delete(_CACHE_KEY)
    log.info("graph_auth.signed_out")
