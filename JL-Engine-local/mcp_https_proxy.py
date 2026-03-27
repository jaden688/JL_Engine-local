"""Local HTTPS reverse proxy for the JL Engine MCP server.

This proxy keeps the MCP transport on localhost, but exposes it over HTTPS so
browser-based clients such as HuggingChat can accept the URL.

Default flow:
  HuggingChat -> https://localhost:8443/mcp -> this proxy -> http://127.0.0.1:8002/mcp

The proxy also generates a local CA and server certificate on first run, then
imports the CA into the current user's Windows trust store so the browser can
trust the localhost TLS endpoint.
"""

from __future__ import annotations

import ipaddress
import os
import ssl
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterable
from urllib.parse import urlsplit, urlunsplit

import httpx

try:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
except Exception as exc:  # pragma: no cover - environment should already have it
    raise SystemExit(
        "cryptography is required to generate the local TLS certificates. "
        "Install the jl-engine-local environment or run `uv sync` in JL-Engine-local."
    ) from exc

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BACKEND_URL = "http://127.0.0.1:8002"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8443
DEFAULT_PUBLIC_HOST = "localhost"
CERT_DIR = Path(os.getenv("JL_MCP_PROXY_CERT_DIR", str(REPO_ROOT / ".jl_mcp_https")))
LOG_FILE = CERT_DIR / "proxy.log"
BACKEND_URL = os.getenv("JL_MCP_BACKEND_URL", DEFAULT_BACKEND_URL).rstrip("/")
HOST = os.getenv("JL_MCP_PROXY_HOST", DEFAULT_HOST).strip() or DEFAULT_HOST
PORT = int(os.getenv("JL_MCP_PROXY_PORT", str(DEFAULT_PORT)) or DEFAULT_PORT)
PUBLIC_HOST = os.getenv("JL_MCP_PUBLIC_HOST", DEFAULT_PUBLIC_HOST).strip() or DEFAULT_PUBLIC_HOST
TRUST_CA = str(os.getenv("JL_MCP_TRUST_CA", "1")).strip().lower() not in {"0", "false", "off", "no"}

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "content-length",
    "content-encoding",
}


def _log(message: str) -> None:
    CERT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(f"[{stamp}] {message}\n")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _write_pem(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _load_pem_private_key(path: Path):
    return serialization.load_pem_private_key(path.read_bytes(), password=None)


def _load_pem_cert(path: Path):
    return x509.load_pem_x509_certificate(path.read_bytes())


def _generate_ca_bundle() -> tuple[Path, Path, rsa.RSAPrivateKey, x509.Certificate]:
    key_path = CERT_DIR / "ca.key.pem"
    cert_path = CERT_DIR / "ca.crt.pem"
    if key_path.exists() and cert_path.exists():
        return key_path, cert_path, _load_pem_private_key(key_path), _load_pem_cert(cert_path)

    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Local"),
            x509.NameAttribute(NameOID.LOCALITY_NAME, "Localhost"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "JL Engine"),
            x509.NameAttribute(NameOID.COMMON_NAME, "JL Engine Local MCP CA"),
        ]
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(_utc_now() - timedelta(days=1))
        .not_valid_after(_utc_now() + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=False,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .sign(private_key=key, algorithm=hashes.SHA256())
    )
    _write_pem(
        key_path,
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ),
    )
    _write_pem(cert_path, cert.public_bytes(serialization.Encoding.PEM))
    return key_path, cert_path, key, cert


def _generate_server_bundle(
    ca_key: rsa.RSAPrivateKey,
    ca_cert: x509.Certificate,
) -> tuple[Path, Path]:
    key_path = CERT_DIR / "server.key.pem"
    cert_path = CERT_DIR / "server.crt.pem"
    if key_path.exists() and cert_path.exists():
        return key_path, cert_path

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    san_entries: list[x509.GeneralName] = [
        x509.DNSName("localhost"),
        x509.DNSName(PUBLIC_HOST),
        x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
    ]
    try:
        san_entries.append(x509.IPAddress(ipaddress.ip_address("::1")))
    except ValueError:
        pass
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Local"),
            x509.NameAttribute(NameOID.LOCALITY_NAME, "Localhost"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "JL Engine"),
            x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
        ]
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(_utc_now() - timedelta(days=1))
        .not_valid_after(_utc_now() + timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName(san_entries), critical=False)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .sign(private_key=ca_key, algorithm=hashes.SHA256())
    )
    _write_pem(
        key_path,
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ),
    )
    _write_pem(cert_path, cert.public_bytes(serialization.Encoding.PEM))
    return key_path, cert_path


def _trust_ca_windows(ca_cert_path: Path) -> bool:
    if os.name != "nt":
        return False
    try:
        result = subprocess.run(
            ["certutil", "-user", "-addstore", "Root", str(ca_cert_path)],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return True
        text = (result.stdout or "") + (result.stderr or "")
        if "certutil: -addstore command FAILED" in text:
            return False
        return result.returncode == 0
    except Exception:
        return False


def _ensure_tls_assets() -> tuple[Path, Path]:
    CERT_DIR.mkdir(parents=True, exist_ok=True)
    ca_key_path, ca_cert_path, ca_key, ca_cert = _generate_ca_bundle()
    server_key_path, server_cert_path = _generate_server_bundle(ca_key, ca_cert)
    if TRUST_CA:
        trusted = _trust_ca_windows(ca_cert_path)
        _log(f"CA trust {'succeeded' if trusted else 'was skipped or already present'}")
    else:
        _log("CA trust installation disabled by JL_MCP_TRUST_CA")
    return server_key_path, server_cert_path


# Allowed CORS origins — restricted to local addresses (DEFAULT_PUBLIC_HOST=localhost, DEFAULT_PORT=8443).
_ALLOWED_CORS_ORIGINS: set[str] = {
    "http://localhost",
    "http://localhost:8000",
    "http://localhost:8080",
    "http://127.0.0.1",
    "http://127.0.0.1:8000",
    "http://127.0.0.1:8080",
    f"https://{DEFAULT_PUBLIC_HOST}:{DEFAULT_PORT}",
    f"https://localhost:{DEFAULT_PORT}",
    f"https://127.0.0.1:{DEFAULT_PORT}",
}


def _cors_origin(origin: str | None) -> str:
    if origin and origin in _ALLOWED_CORS_ORIGINS:
        return origin
    return "http://localhost"


def _copy_request_headers(source) -> dict[str, str]:
    headers: dict[str, str] = {}
    for key, value in source.items():
        if key.lower() in HOP_BY_HOP_HEADERS or key.lower() == "host":
            continue
        headers[key] = value
    return headers


def _emit_cors_headers(handler: BaseHTTPRequestHandler) -> None:
    origin = handler.headers.get("Origin")
    handler.send_header("Access-Control-Allow-Origin", _cors_origin(origin))
    handler.send_header("Vary", "Origin")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
    req_headers = handler.headers.get("Access-Control-Request-Headers")
    handler.send_header(
        "Access-Control-Allow-Headers",
        req_headers or "Authorization, Content-Type, Accept, Origin, X-Requested-With",
    )


class ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        _log(f"{self.client_address[0]} - {fmt % args}")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        _emit_cors_headers(self)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        self._proxy("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._proxy("POST")

    def do_PUT(self) -> None:  # noqa: N802
        self._proxy("PUT")

    def do_PATCH(self) -> None:  # noqa: N802
        self._proxy("PATCH")

    def do_DELETE(self) -> None:  # noqa: N802
        self._proxy("DELETE")

    def do_HEAD(self) -> None:  # noqa: N802
        self._proxy("HEAD")

    def _proxy(self, method: str) -> None:
        body = b""
        content_length = self.headers.get("Content-Length")
        if content_length:
            try:
                length = int(content_length)
            except ValueError:
                length = 0
            if length > 0:
                body = self.rfile.read(length)

        upstream_url = f"{BACKEND_URL}{self.path}"
        request_headers = _copy_request_headers(self.headers)

        try:
            timeout = httpx.Timeout(60.0, connect=5.0)
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                with client.stream(
                    method,
                    upstream_url,
                    headers=request_headers,
                    content=body if body else None,
                ) as upstream:
                    response_body = upstream.read()
                    self.send_response(upstream.status_code)
                    _emit_cors_headers(self)
                    for key, value in upstream.headers.items():
                        if key.lower() in HOP_BY_HOP_HEADERS:
                            continue
                        self.send_header(key, value)
                    self.send_header("Content-Length", str(len(response_body)))
                    self.end_headers()
                    if method != "HEAD":
                        self.wfile.write(response_body)
                        self.wfile.flush()
        except Exception as exc:
            _log(f"Proxy error: {exc}")
            payload = b'{"error":"proxy_failed","detail":"An internal proxy error occurred."}'
            self.send_response(HTTPStatus.BAD_GATEWAY)
            _emit_cors_headers(self)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)


def main() -> int:
    server_key_path, server_cert_path = _ensure_tls_assets()
    httpd = ThreadingHTTPServer((HOST, PORT), ProxyHandler)
    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ssl_ctx.load_cert_chain(certfile=str(server_cert_path), keyfile=str(server_key_path))
    httpd.socket = ssl_ctx.wrap_socket(httpd.socket, server_side=True)

    _log(f"Listening on https://{PUBLIC_HOST}:{PORT}/mcp")
    _log(f"Forwarding to {BACKEND_URL}")
    _log(f"Serving from cert store {CERT_DIR}")
    if TRUST_CA:
        _log("Browser trust is handled via the local Windows current-user root store when possible.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        _log("Shutting down.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
