"""Browser login for YouSpeed tools using the existing Keycloak realm."""
from base64 import urlsafe_b64encode
from dataclasses import dataclass
from hashlib import sha256
from html import escape
from http.cookies import SimpleCookie, CookieError
import os
from pathlib import Path
import re
import secrets
import ssl
from threading import Lock
from time import monotonic
from urllib.parse import parse_qs, urlencode, urlsplit

LOGIN = "/auth/login"
CALLBACK = "/auth/callback"
ACCOUNT = "/auth/account"
LOGOUT = "/auth/logout"
STATUS = "/auth/status"

ROLES = {
    "inspector": frozenset({"reader", "reviewer", "admin"}),
    "osm": frozenset({"user"}),
}


@dataclass(frozen=True)
class Identity:
    subject: str
    roles: frozenset[str]


@dataclass(frozen=True)
class LoginResponse:
    status: int
    body: str = ""
    headers: tuple = ()


def cookie_value(headers, name):
    cookies = SimpleCookie()
    try:
        cookies.load(headers.get("Cookie", ""))
    except CookieError:
        return ""
    return cookies[name].value if name in cookies else ""


class KeycloakLogin:
    paths = frozenset({LOGIN, CALLBACK, ACCOUNT, LOGOUT, STATUS})
    login_path = LOGIN
    callback_path = CALLBACK
    logout_path = LOGOUT

    def __init__(self, tool, *, origin, issuer, client_id, client_secret):
        import jwt
        import requests
        for url, is_origin in ((origin, True), (issuer, False)):
            parsed = urlsplit(url)
            if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                    or parsed.password or parsed.query or parsed.fragment
                    or (is_origin and parsed.path)):
                raise ValueError("Keycloak issuer and tool origin must be canonical HTTPS URLs")
        self.origin, self.issuer = origin, issuer.rstrip("/")
        self.client_id, self.client_secret = client_id, client_secret
        self.protocol = self.issuer + "/protocol/openid-connect"
        self.redirect_uri = origin + CALLBACK
        self.home = "/inspector/" if tool == "inspector" else "/"
        self.roles = ROLES[tool]
        self.session_cookie = f"__Host-youspeed-{tool}"
        self.flow_cookie = self.session_cookie + "-login"
        # PyJWT fetches keys with urllib. Use the same CA bundle as the token request.
        ca_bundle = os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("CURL_CA_BUNDLE") or requests.certs.where()
        tls = ssl.create_default_context(cafile=ca_bundle if not os.path.isdir(ca_bundle) else None,
                                         capath=ca_bundle if os.path.isdir(ca_bundle) else None)
        self.jwks = jwt.PyJWKClient(self.protocol + "/certs", timeout=5, ssl_context=tls)
        self.flows, self.sessions = {}, {}
        self.lock = Lock()

    @classmethod
    def from_env(cls, tool, *, origin=None):
        prefix = "YOUSPEED_" + tool.upper() + "_OIDC_"
        config = {key: os.environ.get(prefix + key, "") for key in
                  ("ISSUER", "CLIENT_ID", "CLIENT_SECRET_FILE", "ORIGIN")}
        if not any(config.values()):
            return None
        if not all(config[key] for key in ("ISSUER", "CLIENT_ID", "CLIENT_SECRET_FILE")):
            raise ValueError(f"Incomplete {prefix} configuration")
        if origin and config["ORIGIN"] and origin != config["ORIGIN"]:
            raise ValueError("OIDC origin must match the tool's public origin")
        public_origin = origin or config["ORIGIN"]
        secret = Path(config["CLIENT_SECRET_FILE"]).read_text().strip()
        if not secret or not public_origin:
            raise ValueError("OIDC requires a public HTTPS origin and a client secret")
        return cls(tool, origin=public_origin, issuer=config["ISSUER"],
                   client_id=config["CLIENT_ID"], client_secret=secret)

    def remember(self, entries, value, ttl):
        key = secrets.token_urlsafe(32)
        now = monotonic()
        with self.lock:
            for expired in [k for k, (until, _) in entries.items() if until <= now]:
                del entries[expired]
            if len(entries) >= 1024:
                return None
            entries[key] = now + ttl, value
        return key

    def lookup(self, entries, key, *, consume=False):
        with self.lock:
            until, value = (entries.pop(key, (0, None)) if consume
                            else entries.get(key, (0, None)))
            return value if until > monotonic() else None

    def identity(self, headers):
        return self.lookup(self.sessions, cookie_value(headers, self.session_cookie))

    def cookie(self, name, value, age):
        return ("Set-Cookie", f"{name}={value}; Path=/; Max-Age={age}; Secure; HttpOnly; SameSite=Lax")

    def start(self):
        state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
        key = self.remember(self.flows, (state, nonce, verifier), 300)
        if not key:
            return self.page(503, "Zu viele Anmeldeversuche. Bitte später erneut versuchen.")
        challenge = urlsafe_b64encode(sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        query = urlencode({"client_id": self.client_id, "redirect_uri": self.redirect_uri,
                           "response_type": "code", "scope": "openid", "state": state,
                           "nonce": nonce, "code_challenge": challenge, "code_challenge_method": "S256"})
        return LoginResponse(303, headers=(("Location", self.protocol + "/auth?" + query),
                                          self.cookie(self.flow_cookie, key, 300)))

    def exchange(self, code, nonce, verifier):
        import jwt
        import requests
        response = requests.post(self.protocol + "/token", timeout=8, allow_redirects=False,
                                 auth=(self.client_id, self.client_secret),
                                 data={"grant_type": "authorization_code", "code": code,
                                       "redirect_uri": self.redirect_uri, "code_verifier": verifier})
        if response.status_code != 200:
            raise ValueError("Token exchange failed")
        token = response.json()["id_token"]
        signing_key = self.jwks.get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, signing_key, algorithms=["RS256"], audience=self.client_id,
                            issuer=self.issuer, options={"require": ["sub", "exp", "iat", "nonce"],
                                                         "strict_aud": True})
        if claims["nonce"] != nonce or claims.get("azp", self.client_id) != self.client_id:
            raise ValueError("Token does not match login request")
        subject = claims["sub"]
        if not subject or len(subject) > 255:
            raise ValueError("Invalid account identifier")
        client_roles = claims.get("resource_access", {}).get(self.client_id, {}).get("roles", [])
        if not isinstance(client_roles, list) or not all(isinstance(role, str) for role in client_roles):
            raise ValueError("Invalid client roles")
        return Identity(subject, self.roles.intersection(client_roles))

    def callback(self, headers, query):
        import jwt
        import requests
        key = cookie_value(headers, self.flow_cookie)
        flow = self.lookup(self.flows, key, consume=True)
        fields = parse_qs(query, keep_blank_values=True, max_num_fields=12)
        state, code = fields.get("state", []), fields.get("code", [])
        cleared = (self.cookie(self.flow_cookie, "", 0),)
        if (not flow or len(state) != 1 or not re.fullmatch(r"[A-Za-z0-9_-]{43}", state[0])
                or not secrets.compare_digest(flow[0], state[0]) or len(code) != 1 or not code[0]):
            return self.page(400, "Anmeldung abgelaufen. Bitte erneut anmelden.", cleared)
        try:
            identity = self.exchange(code[0], flow[1], flow[2])
        except (jwt.PyJWTError, requests.RequestException, ValueError, KeyError, TypeError, AttributeError):
            return self.page(401, "Anmeldung fehlgeschlagen. Bitte erneut versuchen.", cleared)
        if not identity.roles:
            return self.page(403, "Dieses Konto hat keinen Zugang zu diesem Tool.", cleared)
        session_key = self.remember(self.sessions, identity, 1800)
        if not session_key:
            return self.page(503, "Der Dienst ist ausgelastet. Bitte später erneut versuchen.", cleared)
        self.lookup(self.sessions, cookie_value(headers, self.session_cookie), consume=True)
        # A fresh document resets the cross-site redirect chain from Keycloak.
        home = escape(self.home, quote=True)
        return self.page(200, f'<a href="{home}">Zum Tool</a>',
                         cleared + (self.cookie(self.session_cookie, session_key, 1800),),
                         head=f'<meta http-equiv="refresh" content="0;url={home}">')

    def page(self, status, message, headers=(), *, head=""):
        retry = f'<p><a href="{LOGIN}">Anmelden</a></p>' if status >= 400 else ""
        return LoginResponse(status, '<!doctype html><html lang="de"><head><meta charset="utf-8">'
                             '<meta name="viewport" content="width=device-width,initial-scale=1">'
                             f'<title>YouSpeed · Anmeldung</title>{head}</head><body><main>'
                             f'{message}{retry}</main></body></html>', headers)

    def route(self, path, method, headers, query=""):
        if method == "GET" and path == STATUS:
            return LoginResponse(204 if self.identity(headers) else 401)
        if method == "GET" and path == LOGIN:
            return self.start()
        if method == "GET" and path == CALLBACK:
            try:
                return self.callback(headers, query)
            except ValueError:
                return self.page(400, "Ungültige Anmeldung. Bitte erneut versuchen.")
        if method == "GET" and path == ACCOUNT and self.identity(headers):
            return self.page(200, f'<form method="post" action="{LOGOUT}">'
                             '<button>Von diesem Tool abmelden</button></form>')
        if method == "POST" and path == LOGOUT and headers.get("Origin") == self.origin:
            self.lookup(self.sessions, cookie_value(headers, self.session_cookie), consume=True)
            return self.page(200, f'<p>Abgemeldet.</p><a href="{LOGIN}">Erneut anmelden</a>',
                             (self.cookie(self.session_cookie, "", 0),))
        return self.page(403, "Anmeldung erforderlich.")

    def login_required(self):
        return LoginResponse(303, headers=(("Location", LOGIN),))
