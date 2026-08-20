from cryptography import x509
from cryptography.x509.oid import ExtensionOID

from dropship_desk.local_tls import ensure_local_tls


def test_ensure_local_tls_writes_pem(tmp_path, monkeypatch):
    import dropship_desk.config as cfg

    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    cert, key = ensure_local_tls()
    assert cert.is_file()
    assert key.is_file()
    assert b"BEGIN CERTIFICATE" in cert.read_bytes()
    assert b"BEGIN RSA PRIVATE KEY" in key.read_bytes()
    loaded = x509.load_pem_x509_certificate(cert.read_bytes())
    san = loaded.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME)
    names = san.value.get_values_for_type(x509.DNSName)
    assert "localhost" in names
    cert2, key2 = ensure_local_tls()
    assert cert2 == cert
    assert key2 == key
