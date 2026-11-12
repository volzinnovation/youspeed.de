from http.client import HTTPResponse
from io import BytesIO
from time import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode, urlsplit

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from inspector.keycloak_login import KeycloakLogin
from inspector.server import InspectorHandler


ORIGIN = "https://inspector.example.test"
ISSUER = "https://identity.example.test/auth/realms/panoramax"


@pytest.fixture
def login():
    return KeycloakLogin("inspector", origin=ORIGIN, issuer=ISSUER,
                         client_id="youspeed-inspector", client_secret="test-secret")


@pytest.fixture
def issuer(login, monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(login.jwks, "get_signing_key_from_jwt",
                        lambda token: SimpleNamespace(key=key.public_key()))

    def start(*, roles=None, **overrides):
        response = login.start()
        headers = dict(response.headers)
        query = parse_qs(urlsplit(headers["Location"]).query)
        assert query["code_challenge_method"] == ["S256"]
        assert query["redirect_uri"] == [ORIGIN + "/auth/callback"]
        claims = {"sub": "account-1", "iss": ISSUER, "aud": login.client_id,
                  "exp": int(time()) + 60, "iat": int(time()), "nonce": query["nonce"][0],
                  "resource_access": roles or {login.client_id: {"roles": ["reader"]}}}
        claims.update(overrides)
        token = jwt.encode(claims, key, algorithm="RS256")

        def exchange(url, **kwargs):
            assert url == ISSUER + "/protocol/openid-connect/token"
            assert kwargs["data"]["code"] == "code-from-keycloak"
            assert kwargs["data"]["code_verifier"]
            assert not kwargs["allow_redirects"]
            return SimpleNamespace(status_code=200, json=lambda: {"id_token": token})

        monkeypatch.setattr("requests.post", exchange)
        callback = urlencode({"code": "code-from-keycloak", "state": query["state"][0]})
        return headers["Set-Cookie"].split(";", 1)[0], callback

    return start


@pytest.mark.parametrize(("claims", "status"), [
    ({}, 200),
    ({"nonce": "another-browser"}, 401),
    ({"aud": "youspeed-osm"}, 401),
    ({"iss": "https://another.example.test/realms/panoramax"}, 401),
    ({"roles": {"youspeed-osm": {"roles": ["user", "admin"]}}}, 403),
])
def test_callback_validates_identity_and_tool_roles(login, issuer, claims, status):
    cookie, query = issuer(**claims)
    assert login.callback({}, query).status == 400
    response = login.callback({"Cookie": cookie}, query)
    assert response.status == status
    assert login.callback({"Cookie": cookie}, query).status == 400
    if status == 200:
        session_cookie = response.headers[-1][1]
        assert "Secure; HttpOnly; SameSite=Lax" in session_cookie
        identity = login.identity({"Cookie": session_cookie.split(";", 1)[0]})
        assert identity.subject == "account-1"
        assert identity.roles == {"reader"}


def test_inspector_http_requires_session_and_review_role(login, issuer):
    server = SimpleNamespace(keycloak_login=login, allowed_hosts={urlsplit(ORIGIN).netloc, "localhost"})

    def request(method, path, **headers):
        fields = {"Host": urlsplit(ORIGIN).netloc, **headers}
        raw = f"{method} {path} HTTP/1.0\r\n" + "".join(f"{k}: {v}\r\n" for k, v in fields.items()) + "\r\n"
        output = BytesIO()
        socket = SimpleNamespace(makefile=lambda *_: BytesIO(raw.encode()), sendall=output.write)
        InspectorHandler(socket, ("127.0.0.1", 0), server)
        response = HTTPResponse(SimpleNamespace(makefile=lambda *_: BytesIO(output.getvalue())))
        response.begin()
        return response.status, response.getheaders()

    assert request("GET", "/inspector/")[0] == 303
    assert request("GET", "/inspector/api/crops")[0] == 401
    assert request("GET", "/inspector/api/crops", Host="localhost")[0] == 403
    cookie, query = issuer()
    status, headers = request("GET", "/auth/callback?" + query,
                              Cookie=cookie, **{"Sec-Fetch-Site": "cross-site"})
    assert status == 200
    session_cookie = next(value.split(";", 1)[0] for name, value in headers
                          if name == "Set-Cookie" and value.startswith(login.session_cookie + "="))
    assert request("GET", "/inspector/", Cookie=session_cookie)[0] == 200
    assert request("POST", "/inspector/api/crops/review/save",
                   Cookie=session_cookie, Origin=ORIGIN)[0] == 403
    assert request("POST", "/auth/logout", Cookie=session_cookie, Origin=ORIGIN)[0] == 200
    assert request("GET", "/inspector/api/crops", Cookie=session_cookie)[0] == 401
