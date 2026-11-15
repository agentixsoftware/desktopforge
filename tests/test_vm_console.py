"""Private console client must authenticate and verify the server identity."""
from pathlib import Path
import runpy
import ssl

import pytest


@pytest.fixture
def console():
    script = Path(__file__).resolve().parents[1] / 'scripts/desktopforge-vm'
    return runpy.run_path(str(script))['qmp']


def test_tls_client_checks_server_and_loads_its_certificate(console, monkeypatch, tmp_path):
    calls = []
    class Context:
        def load_cert_chain(self, certificate, key):
            calls.append(('credentials', certificate, key))
        def wrap_socket(self, raw, server_hostname):
            calls.append(('server', server_hostname))
            raise ssl.SSLCertVerificationError('wrong server')
    def context(*, cafile):
        calls.append(('ca', cafile))
        return Context()
    monkeypatch.setattr(ssl, 'create_default_context', context)
    monkeypatch.setattr(console.__globals__['socket'], 'create_connection', lambda *a, **k: object())
    console.__globals__.update(USE_TLS=True, RUN=tmp_path)
    with pytest.raises(ssl.SSLCertVerificationError):
        console('query-status')
    assert calls == [('ca', str(tmp_path/'tls/ca-cert.pem')),
                     ('credentials', str(tmp_path/'tls/client-cert.pem'), str(tmp_path/'tls/client-key.pem')),
                     ('server', '127.0.0.1')]


def test_unix_socket_rejects_regular_files(console, tmp_path):
    (tmp_path/'qmp.sock').write_text('not a socket')
    console.__globals__.update(USE_TLS=False, RUN=tmp_path)
    with pytest.raises(RuntimeError, match='control socket'):
        console('query-status')
