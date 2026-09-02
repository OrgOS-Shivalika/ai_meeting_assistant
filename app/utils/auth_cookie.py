"""Where the session cookie is written.

Its own module because two places set it and they cannot import each other:
`api/auth_router` (login, change-password) and `dependencies/auth` (the
sliding refresh, which keeps an active session from hitting the 7-day wall).
"""

from fastapi import Response

from app.config.settings import settings


def set_auth_cookie(response: Response, token: str, remember: bool = True) -> None:
    """Attach the session JWT as an HttpOnly cookie.

    HttpOnly + SameSite is the whole point of the move off localStorage:
    the browser sends it automatically on same-origin requests and the WS
    handshake, but no page script can read it, so an XSS payload can't
    steal the session. Secure/SameSite come from settings so a dev on
    http://localhost and an HTTPS deployment can both work.

    `remember` is the login form's "Keep me signed in". Omitting `max_age`
    (and `expires`) is what makes a cookie a SESSION cookie — the browser
    drops it when it closes. With `max_age` set it survives, which is what
    the checkbox is asking for. The token's own TTL is unchanged either way:
    this decides how long the BROWSER keeps the cookie, not how long the
    credential stays valid.
    """
    response.set_cookie(
        key=settings.AUTH_COOKIE_NAME,
        value=token,
        max_age=settings.AUTH_COOKIE_MAX_AGE if remember else None,
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite=settings.AUTH_COOKIE_SAMESITE,
        path="/",
    )
