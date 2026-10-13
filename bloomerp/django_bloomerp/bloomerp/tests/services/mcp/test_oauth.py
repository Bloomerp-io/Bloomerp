"""Protocol contract and public-network transport checks for outbound MCP OAuth."""

import base64
import hashlib
import socket
from typing import Any
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

import httpx
from bloomerp.services.mcp.oauth import (
    MCPAuthenticationError,
    PublicHTTPTransport,
    begin_authorization,
    client_metadata,
    discover,
    exchange_code,
    remote_request,
    seal,
    unseal,
    verify_api_key,
)
from django.test import SimpleTestCase

ENDPOINT = "https://tools.example.com/mcp"
ISSUER = "https://auth.example.com/tenant"
CALLBACK = (
    "https://bloomerp.example.com/bloomai/mcp-integrations/create/oauth/callback/"
)
CLIENT_METADATA = (
    "https://bloomerp.example.com/bloomai/mcp-integrations/oauth/client-metadata.json/"
)


def protocol_response(method: str, url: str, **kwargs: Any) -> httpx.Response:
    """Return RFC9728/RFC8414 discovery and token responses for a remote server."""
    request = httpx.Request(method, url)
    if url == ENDPOINT:
        return httpx.Response(
            401,
            request=request,
            headers={
                "WWW-Authenticate": 'Bearer resource_metadata="https://tools.example.com/resource", scope="tools:read"'
            },
        )
    if url in {
        "https://tools.example.com/resource",
        "https://tools.example.com/.well-known/oauth-protected-resource/mcp",
    }:
        return httpx.Response(
            200,
            request=request,
            json={
                "resource": ENDPOINT,
                "authorization_servers": [ISSUER],
                "scopes_supported": ["tools:all"],
            },
        )
    if url == "https://auth.example.com/.well-known/oauth-authorization-server/tenant":
        return httpx.Response(
            200,
            request=request,
            json={
                "issuer": ISSUER,
                "authorization_endpoint": "https://auth.example.com/authorize",
                "token_endpoint": "https://auth.example.com/token",
                "code_challenge_methods_supported": ["S256"],
                "token_endpoint_auth_methods_supported": [
                    "none",
                    "client_secret_basic",
                    "client_secret_post",
                ],
                "client_id_metadata_document_supported": True,
                "authorization_response_iss_parameter_supported": True,
            },
        )
    if url == "https://auth.example.com/token":
        return httpx.Response(
            200,
            request=request,
            json={
                "access_token": "issued-token-secret",
                "refresh_token": "refresh-token-secret",
                "token_type": "Bearer",
                "expires_in": 3600,
            },
        )
    return httpx.Response(404, request=request)


class TestMCPOAuthProtocol(SimpleTestCase):
    """Verify protocol parameters and secure temporary state without external accounts."""

    def begin(self, **overrides: Any) -> tuple[str, dict[str, Any]]:
        """Construct authorization for the standard metadata-based public client."""
        return begin_authorization(
            ENDPOINT, CALLBACK, CLIENT_METADATA, owner_id="user-1", **overrides
        )

    def test_discovery_pkce_resource_and_scope_challenge(self) -> None:
        """Verify discovery, metadata client IDs and authoritative challenged scopes."""
        with patch(
            "bloomerp.services.mcp.oauth.remote_request", side_effect=protocol_response
        ) as remote:
            location, pending = self.begin(scopes="requested:scope")
            query = parse_qs(urlsplit(location).query)
            self.assertEqual(query["client_id"], [CLIENT_METADATA])
            self.assertEqual(query["resource"], [ENDPOINT])
            self.assertEqual(query["scope"], ["tools:read"])
            self.assertEqual(query["code_challenge_method"], ["S256"])
            expected = (
                base64.urlsafe_b64encode(
                    hashlib.sha256(pending["verifier"].encode()).digest()
                )
                .rstrip(b"=")
                .decode()
            )
            self.assertEqual(query["code_challenge"], [expected])
            tokens = exchange_code(pending, "returned-code")
            self.assertEqual(
                tokens["credentials"]["access_token"], "issued-token-secret"
            )
            self.assertEqual(tokens["credentials"]["issuer"], ISSUER)
            data = remote.call_args.kwargs["data"]
            self.assertEqual(data["code_verifier"], pending["verifier"])
            self.assertEqual(data["resource"], ENDPOINT)
            self.assertEqual(data["redirect_uri"], CALLBACK)
            self.assertNotIn("verifier", query)

    def test_pre_registered_confidential_client_uses_basic_auth(self) -> None:
        """Verify registered client secrets are encoded for token requests only."""
        with patch(
            "bloomerp.services.mcp.oauth.remote_request", side_effect=protocol_response
        ) as remote:
            location, pending = self.begin(
                client_id="registered client", client_secret="secret:client"
            )
            self.assertNotIn("secret:client", location)
            exchange_code(pending, "returned-code")
            header = remote.call_args.kwargs["headers"]["Authorization"]
            self.assertEqual(
                base64.b64decode(header[6:]).decode(),
                "registered+client:secret%3Aclient",
            )

    def test_dynamic_registration_fallback(self) -> None:
        """Verify servers without metadata clients can register a public PKCE client."""

        def dynamic_response(method: str, url: str, **kwargs: Any) -> httpx.Response:
            """Replace only registration capabilities and the registration response."""
            if url == "https://auth.example.com/register":
                self.assertEqual(kwargs["payload"]["redirect_uris"], [CALLBACK])
                return httpx.Response(
                    201,
                    request=httpx.Request(method, url),
                    json={
                        "client_id": "dynamic-client",
                        "token_endpoint_auth_method": "none",
                    },
                )
            response = protocol_response(method, url, **kwargs)
            if "oauth-authorization-server" in url:
                metadata = response.json() | {
                    "client_id_metadata_document_supported": False,
                    "registration_endpoint": "https://auth.example.com/register",
                }
                return httpx.Response(200, request=response.request, json=metadata)
            return response

        with patch(
            "bloomerp.services.mcp.oauth.remote_request", side_effect=dynamic_response
        ):
            location, pending = self.begin()
        self.assertEqual(pending["client_id"], "dynamic-client")
        self.assertEqual(
            parse_qs(urlsplit(location).query)["client_id"], ["dynamic-client"]
        )

    def test_oidc_discovery_fallback_and_root_resource_metadata(self) -> None:
        """Verify path/root resource discovery and both OIDC compatibility URLs."""

        def fallback_response(method: str, url: str, **kwargs: Any) -> httpx.Response:
            """Serve metadata at root and at the issuer's appended OIDC location."""
            request = httpx.Request(method, url)
            if url == ENDPOINT:
                return httpx.Response(401, request=request)
            if url == "https://tools.example.com/.well-known/oauth-protected-resource":
                return protocol_response("GET", "https://tools.example.com/resource")
            if url == ISSUER + "/.well-known/openid-configuration":
                return protocol_response(
                    "GET",
                    "https://auth.example.com/.well-known/oauth-authorization-server/tenant",
                )
            return httpx.Response(404, request=request)

        with patch(
            "bloomerp.services.mcp.oauth.remote_request", side_effect=fallback_response
        ):
            resource, metadata, scope = discover(ENDPOINT)
        self.assertEqual(resource["resource"], ENDPOINT)
        self.assertEqual(metadata["issuer"], ISSUER)
        self.assertEqual(scope, "")

    def test_missing_pkce_wrong_resource_and_missing_registration_fail(self) -> None:
        """Reject incompatible or mismatched metadata rather than inventing authorization."""
        for replacement, expected in (
            ({"code_challenge_methods_supported": []}, "PKCE"),
            ({"issuer": "https://wrong.example.com"}, "issuer"),
            ({"client_id_metadata_document_supported": False}, "pre-registered"),
            (
                {"token_endpoint_auth_methods_supported": ["client_secret_basic"]},
                "client secret",
            ),
        ):

            def invalid_metadata(
                method: str,
                url: str,
                replacement: dict[str, Any] = replacement,
                **kwargs: Any,
            ) -> httpx.Response:
                """Return one independently invalid authorization-server metadata value."""
                response = protocol_response(method, url, **kwargs)
                if "oauth-authorization-server" in url:
                    return httpx.Response(
                        200,
                        request=response.request,
                        json=response.json() | replacement,
                    )
                return response

            with (
                self.subTest(replacement=replacement),
                patch(
                    "bloomerp.services.mcp.oauth.remote_request",
                    side_effect=invalid_metadata,
                ),
                self.assertRaisesRegex(MCPAuthenticationError, expected),
            ):
                self.begin()

    def test_temporary_state_is_encrypted(self) -> None:
        """Verify session state hides PKCE, client secrets and tokens in every backend."""
        encrypted = seal(
            {"verifier": "secret-verifier", "client_secret": "client-secret"}
        )
        self.assertNotIn("secret-verifier", encrypted)
        self.assertNotIn("client-secret", encrypted)
        self.assertEqual(unseal(encrypted)["verifier"], "secret-verifier")
        with self.assertRaises(MCPAuthenticationError):
            unseal("invalid")

    def test_client_application_type_matches_callback_origin(self) -> None:
        """Verify OIDC registration identifies hosted web and localhost native clients."""
        self.assertEqual(
            client_metadata(CLIENT_METADATA, CALLBACK)["application_type"], "web"
        )
        self.assertEqual(
            client_metadata(CLIENT_METADATA, "http://localhost/callback")[
                "application_type"
            ],
            "native",
        )

    def test_bounded_requests_do_not_follow_redirects(self) -> None:
        """Verify the real HTTP request helper never follows remote redirect targets."""

        def redirected(request: httpx.Request) -> httpx.Response:
            """Advertise an unsafe redirect that must never receive a request."""
            self.assertEqual(request.headers["Accept-Encoding"], "identity")
            self.assertEqual(str(request.url), ENDPOINT)
            return httpx.Response(
                302,
                headers={"Location": "https://127.0.0.1/internal"},
                stream=httpx.ByteStream(b""),
            )

        with patch(
            "bloomerp.services.mcp.oauth.PublicHTTPTransport",
            return_value=httpx.MockTransport(redirected),
        ):
            response = remote_request("GET", ENDPOINT)
        self.assertEqual(response.status_code, 302)

    def test_oversized_and_compressed_metadata_are_rejected(self) -> None:
        """Verify remote metadata cannot exceed the size limit or inflate compressed payloads."""
        for headers, content in (
            ({}, b"x" * 1_048_577),
            ({"Content-Encoding": "gzip"}, b"not-needed"),
        ):

            def oversized(
                request: httpx.Request,
                headers: dict[str, str] = headers,
                content: bytes = content,
            ) -> httpx.Response:
                """Return one independently invalid streamed metadata response."""
                return httpx.Response(
                    200, headers=headers, stream=httpx.ByteStream(content)
                )

            with (
                self.subTest(headers=headers),
                patch(
                    "bloomerp.services.mcp.oauth.PublicHTTPTransport",
                    return_value=httpx.MockTransport(oversized),
                ),
                self.assertRaises(MCPAuthenticationError),
            ):
                remote_request("GET", ENDPOINT)

    def test_public_transport_pins_dns_and_preserves_tls_hostname(self) -> None:
        """Verify requests connect to the validated public address with original TLS/Host."""
        transport = PublicHTTPTransport()
        with (
            patch(
                "bloomerp.services.mcp.oauth.socket.getaddrinfo",
                return_value=[
                    (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
                ],
            ),
            patch.object(
                transport.transport, "handle_request", return_value=Mock()
            ) as send,
        ):
            transport.handle_request(httpx.Request("GET", ENDPOINT))
        request = send.call_args.args[0]
        self.assertEqual(request.url.host, "93.184.216.34")
        self.assertEqual(request.headers["Host"], "tools.example.com")
        self.assertEqual(request.extensions["sni_hostname"], "tools.example.com")
        transport.close()

    def test_private_transport_targets_rejected_before_request(self) -> None:
        """Verify loopback, metadata-service addresses and mixed DNS cannot be fetched."""
        for address in ("127.0.0.1", "169.254.169.254", "10.1.1.1", "::1"):
            transport = PublicHTTPTransport()
            with (
                self.subTest(address=address),
                patch(
                    "bloomerp.services.mcp.oauth.socket.getaddrinfo",
                    return_value=[
                        (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))
                    ],
                ),
                patch.object(transport.transport, "handle_request") as send,
            ):
                with self.assertRaises(MCPAuthenticationError):
                    transport.handle_request(httpx.Request("GET", ENDPOINT))
                send.assert_not_called()
            transport.close()

    def test_api_key_probe_rejects_denials_and_marks_405_unverified(self) -> None:
        """Verify failed probes never report a successfully connected account."""
        for status in (401, 403, 500):
            with (
                self.subTest(status=status),
                patch(
                    "bloomerp.services.mcp.oauth.remote_request",
                    return_value=httpx.Response(status),
                ),
                self.assertRaises(MCPAuthenticationError),
            ):
                verify_api_key(ENDPOINT, "key-secret")
        with patch(
            "bloomerp.services.mcp.oauth.remote_request",
            return_value=httpx.Response(405),
        ):
            self.assertEqual(verify_api_key(ENDPOINT, "key-secret"), "pending")
