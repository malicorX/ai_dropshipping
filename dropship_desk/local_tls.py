"""Self-signed TLS for local eBay OAuth callbacks (eBay forces https:// redirect URLs)."""

from __future__ import annotations

import ipaddress
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from dropship_desk import config


def cert_paths() -> tuple[Path, Path]:
    config.ensure_data_dir()
    folder = config.DATA_DIR / "certs"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "localhost.pem", folder / "localhost-key.pem"


def ensure_local_tls() -> tuple[Path, Path]:
    """Create a 127.0.0.1/localhost cert if missing. Returns (cert, key)."""
    cert_file, key_file = cert_paths()
    if cert_file.is_file() and key_file.is_file():
        return cert_file, key_file

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(timezone.utc)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
                    x509.DNSName("localhost"),
                    x509.DNSName("127.0.0.1"),
                ]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    key_file.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert_file, key_file
