# Testing

## Unit Tests

Run unit tests (no live server required):

```bash
pytest tests/test_ipaclient.py -v
```

## Integration Tests

Integration tests require a live IPA server and valid Kerberos credentials.

### Setup

1. Obtain Kerberos ticket:
   ```bash
   kinit admin@DEMO1.FREEIPA.ORG
   ```

2. Run integration tests:
   ```bash
   pytest tests/test_ipaclient_integration.py -v
   ```

Or run with the marker:
```bash
pytest -m integration -v
```

### Using ipa.demo1.freeipa.org

The public demo server is available for testing:
- Server: `ipa.demo1.freeipa.org`
- Username: `admin`
- Password: `Secret123`

```bash
kinit admin@DEMO1.FREEIPA.ORG
# Enter password: Secret123
pytest -m integration -v
```

## Coverage

Run tests with coverage:

```bash
pytest --cov=ipaclient --cov-report=html --cov-report=term
```

View HTML coverage report:
```bash
open htmlcov/index.html
```
