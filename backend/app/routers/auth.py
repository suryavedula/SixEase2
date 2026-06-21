"""Microsoft Graph delegated sign-in (TASK-061, EPIC-08).

Web authorization-code + PKCE so the RM signs in with their own Microsoft account;
the app then reads/sends through the shared mailbox on their behalf. These routes
only orchestrate the redirect dance — MSAL + the Redis-backed token cache live in
`app.graph_auth`.

Flow:
  1. SPA → GET /auth/ms/login        → 307 to Microsoft's authorize endpoint
  2. Microsoft → GET /auth/ms/callback?code=... → exchange code, cache tokens
                                        → 307 back to the SPA (?signin=ok | error)
  3. SPA polls GET /auth/ms/status    → {signed_in, username, name}
  4. SPA → POST /auth/ms/logout       → forget the account
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app import graph_auth
from app.config import get_settings
from app.logging import get_logger

router = APIRouter(prefix="/auth/ms", tags=["auth"])
settings = get_settings()
log = get_logger(__name__)


class AuthStatus(BaseModel):
    signed_in: bool
    username: str | None = None
    name: str | None = None


def _post_login_url(error: str | None = None) -> str:
    """Where the callback bounces the browser back to (the SPA), with a status flag."""
    base = settings.ms_graph_post_login_redirect or (
        settings.cors_origins_list[0] if settings.cors_origins_list else "/"
    )
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}signin_error={error}" if error else f"{base}{sep}signin=ok"


@router.get("/login")
async def login() -> RedirectResponse:
    """Kick off sign-in: redirect the browser to Microsoft's login page."""
    if not settings.ms_graph_delegated_enabled:
        raise HTTPException(
            status_code=503,
            detail="Microsoft sign-in is not configured (set MS_GRAPH_* and MS_GRAPH_AUTH_MODE=delegated)",
        )
    url = await graph_auth.build_login_url()
    return RedirectResponse(url, status_code=307)


@router.get("/callback")
async def callback(request: Request) -> RedirectResponse:
    """OAuth redirect target: exchange the code for tokens, bounce back to the SPA."""
    params = dict(request.query_params)
    if "error" in params:
        log.warning(
            "auth.callback_error",
            error=params.get("error"),
            description=params.get("error_description"),
        )
        return RedirectResponse(_post_login_url(error=params.get("error")), status_code=307)
    try:
        await graph_auth.redeem_code(params)
    except Exception as exc:  # noqa: BLE001 — any failure → SPA shows a sign-in error
        log.warning("auth.redeem_failed", error=str(exc))
        return RedirectResponse(_post_login_url(error="signin_failed"), status_code=307)
    return RedirectResponse(_post_login_url(), status_code=307)


@router.get("/status", response_model=AuthStatus)
async def status() -> AuthStatus:
    """Report whether the RM is signed in (the SPA polls this on load + after login)."""
    account = await graph_auth.current_account()
    if not account:
        return AuthStatus(signed_in=False)
    return AuthStatus(signed_in=True, username=account.get("username"), name=account.get("name"))


@router.post("/logout")
async def logout() -> AuthStatus:
    """Forget the signed-in account and drop the cached tokens."""
    await graph_auth.sign_out()
    return AuthStatus(signed_in=False)
