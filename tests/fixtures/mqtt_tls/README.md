# MQTT TLS Test Fixtures

These self-signed certificates and private keys are test-only resources for
Mosquitto TLS integration tests. They are valid from 2024-01-01 through
2036-01-01 and must never be used in production.

- `ca.crt` / `ca.key`: test certificate authority
- `server.crt` / `server.key`: certificate for `localhost`, `127.0.0.1`,
  and `::1`
- `client.crt` / `client.key`: mutual-TLS client identity
- `untrusted-ca.crt`: unrelated authority used to verify trust failures
