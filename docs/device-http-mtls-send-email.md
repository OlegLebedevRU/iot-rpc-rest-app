# Send-email HTTP API — Device-Facing mTLS Endpoint

> **File:** `docs/device-http-mtls-send-email.md`
> **Version:** 1.0
> **Date:** 2026
> **See also:**
> [`client-cert-ssl-rmq-config.md`](./client-cert-ssl-rmq-config.md) · [`glossary.md`](./glossary.md) · [`mqtt-rpc-protocol.md`](./mqtt-rpc-protocol.md)

---

## Overview

The `send-email` endpoint is a **device-facing HTTP API** that allows an IoT device to upload a binary file (e.g. a log file or a report) and request the platform to deliver it to a given email address.

Authentication is performed exclusively via **mutual TLS (mTLS)**: no API key or bearer token is required. The device's identity is derived directly from its client certificate, so the `device_id` is never passed in the request body or as a URL parameter — it is extracted from the certificate automatically by the nginx ingress.

> **This endpoint is the canonical reference example for any device-facing HTTP endpoint that uses mTLS in this platform.** All future device-side HTTP integrations should follow the same pattern: dedicated port on `dev.leo4.ru`, client certificate mandatory, device identity from certificate `OU`.

---

## Architecture

```
Device
  │  POST /terem-api/v1/send-email?file_name=…&email_address=…
  │  Body: <binary file>
  │  Client cert: signed by platform CA, OU = device_id
  ▼
nginx (dev.leo4.ru:1443 or :1444)
  │  mTLS termination
  │  Extract OU from client cert subject DN → $terem_device_id
  │  Return 403 if OU is empty
  ▼
API Gateway / backend upstream
  https://<api-gateway-host>
  POST /backend-api/v1/send-email/{device_id}?file_name=…&email_address=…
  Body: binary file (forwarded as-is, unbuffered)
```

```mermaid
sequenceDiagram
    autonumber
    participant D  as Device
    participant N  as nginx (dev.leo4.ru)
    participant GW as API Gateway

    D  ->> N  : POST :1443/:1444 /terem-api/v1/send-email<br/>?file_name=…&email_address=…<br/>[mTLS client cert, body=file]
    Note over N: Verify client cert against platform CA<br/>Extract OU → device_id<br/>Reject with 403 if OU is absent
    N  ->> GW : POST /backend-api/v1/send-email/{device_id}<br/>?file_name=…&email_address=…<br/>[body forwarded unbuffered]
    GW -->> N : HTTP response
    N  -->> D : HTTP response (forwarded)
```

---

## Client Certificate Requirements

The client certificate **must**:

| Requirement | Details |
|---|---|
| Signed by | Platform CA (`ca_certificate.pem`), depth ≤ 2 |
| `OU` field | Set to the numeric `device_id` of the device (e.g. `OU=4619`) |
| `CN` field | Matches the device serial number (same as MQTT SN) |
| Key type | RSA 2048-bit or better |

> The `OU` field is the **only** mechanism by which nginx identifies the device. If `OU` is absent or empty, the request is rejected with `403 Forbidden` before it reaches the backend.

Certificate generation and signing follow the same PKI flow as for MQTT/RabbitMQ access — see [`client-cert-ssl-rmq-config.md`](./client-cert-ssl-rmq-config.md).

---

## Ingress Profiles

Two dedicated TLS ports are available. Choose based on your TLS stack:

| Port | TLS versions | Cipher profile | Intended client |
|------|-------------|----------------|-----------------|
| **1443** | TLS 1.2 + 1.3 | ECDHE-AES-GCM + ChaCha20 (modern) | Linux, macOS, Android, FreeRTOS with modern mbedTLS |
| **1444** | TLS 1.2 only | ECDHE-RSA-AES + AES-CBC RSA fallback, `@SECLEVEL=1` | Windows (Schannel / WinHTTP / .NET `HttpClient`) |

Port 1445 is reserved for a future embedded/mbedTLS profile and is currently disabled. That profile would further narrow the cipher suite to a subset safe for constrained devices such as ESP32 with mbedTLS — e.g. stripping CBC fallbacks and limiting to a single ECDHE-AES-GCM suite — while keeping full mTLS semantics identical to ports 1443/1444.

> **Windows Schannel note:** Use port 1444 if your client reports errors such as `SEC_E_ALGORITHM_MISMATCH` or fails TLS negotiation on port 1443. Port 1444 pins curves to P-256/P-384 and restricts TLS 1.2 signature algorithms to classic RSA PKCS#1-SHA to maximise Schannel compatibility.

---

## Request

```
POST https://dev.leo4.ru:<port>/terem-api/v1/send-email
```

### Query Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `file_name` | ✅ | Name of the file to attach in the email (e.g. `PlaterraTerminal.log`) |
| `email_address` | ✅ | Recipient email address (e.g. `user@example.com`) |

### Request Body

Raw binary file content. No `Content-Type` restriction is imposed by nginx; the backend may enforce its own limits.

**Maximum body size:** 25 MB (enforced by nginx `client_max_body_size 25m`).

### Headers Set by nginx (forwarded to backend)

| Header | Value | Notes |
|--------|-------|-------|
| `X-Device-Id` | `<device_id>` | Extracted from cert `OU` |
| `X-SSL-Client-Verify` | `SUCCESS` / `FAILED` / `NONE` | Result of client cert verification |
| `X-SSL-Client-Subject` | Full subject DN of client cert | E.g. `CN=a3b0000000c99999d250813,OU=4619,O=Leo4,...` |
| `X-Forwarded-For` | Device IP | Standard proxy header |

---

## Response

Nginx forwards the backend response unchanged. Typical status codes:

| HTTP Status | Source | Meaning |
|-------------|--------|---------|
| `200 OK` | Backend | File received and email queued |
| `403 Forbidden` | **nginx** | Client certificate is missing the `OU` field |
| `413 Request Entity Too Large` | **nginx** | Body exceeds 25 MB |
| `4xx` | Backend | Invalid parameters or backend-side validation error |
| `5xx` | Backend / Gateway | Backend or upstream gateway error |

---

## Code Examples

### curl — Linux / macOS

```bash
curl -X POST \
  "https://dev.leo4.ru:1443/terem-api/v1/send-email?file_name=device.log&email_address=user@example.com" \
  --cert cert.pem \
  --key  key.pem \
  --cacert ca.crt \
  --data-binary @/path/to/device.log \
  -v
```

### curl — Windows (with OpenSSL CLI)

```bat
openssl s_client -connect dev.leo4.ru:1444 ^
    -servername dev.leo4.ru ^
    -cert cert.pem -key key.pem -CAfile ca.crt

:: Or with curl for Windows (use port 1444 for Schannel compatibility):
curl -X POST ^
  "https://dev.leo4.ru:1444/terem-api/v1/send-email?file_name=device.log&email_address=user@example.com" ^
  --cert cert.pem ^
  --key  key.pem ^
  --cacert ca.crt ^
  --data-binary @device.log
```

### Python (httpx)

```python
import httpx

with httpx.Client(
    cert=("cert.pem", "key.pem"),
    verify="ca.crt",
) as client:
    with open("device.log", "rb") as f:
        response = client.post(
            "https://dev.leo4.ru:1443/terem-api/v1/send-email",
            params={
                "file_name": "device.log",
                "email_address": "user@example.com",
            },
            content=f.read(),
        )
    print(response.status_code, response.text)
```

> **Note:** Use `verify="ca.crt"` (path to the platform CA) rather than the system trust store, since the platform CA is a private CA not included in OS roots.

### C — WinHTTP (Windows, Schannel)

```c
// Load client certificate from Windows certificate store
HCERTSTORE hStore = CertOpenSystemStore(0, L"MY");
PCCERT_CONTEXT pCert = CertFindCertificateInStore(
    hStore, X509_ASN_ENCODING, 0, CERT_FIND_SUBJECT_STR, L"<device_CN>", NULL);

HINTERNET hSession = WinHttpOpen(L"Device/1.0",
    WINHTTP_ACCESS_TYPE_DEFAULT_PROXY, NULL, NULL, 0);

HINTERNET hConnect = WinHttpConnect(hSession,
    L"dev.leo4.ru", 1444, 0);  // use port 1444 for Schannel

HINTERNET hRequest = WinHttpOpenRequest(hConnect,
    L"POST",
    L"/terem-api/v1/send-email?file_name=device.log&email_address=user@example.com",
    NULL, WINHTTP_NO_REFERER, WINHTTP_DEFAULT_ACCEPT_TYPES,
    WINHTTP_FLAG_SECURE);

// Attach client certificate
WinHttpSetOption(hRequest, WINHTTP_OPTION_CLIENT_CERT_CONTEXT,
    (LPVOID)pCert, sizeof(CERT_CONTEXT));

// Send request with binary body
BOOL ok = WinHttpSendRequest(hRequest,
    WINHTTP_NO_ADDITIONAL_HEADERS, 0,
    fileBuffer, fileSize, fileSize, 0);
WinHttpReceiveResponse(hRequest, NULL);

// ... read response, cleanup handles ...
```

> **Windows certificate store:** The client certificate and its private key must be imported into the user or machine certificate store (e.g. via `certutil -importpfx`). The platform CA must be added to **Trusted Root Certification Authorities** so that Schannel can verify the server certificate.

### C# — .NET HttpClient (Windows, Schannel)

```csharp
using System.Net.Http;
using System.Security.Cryptography.X509Certificates;

var filePath = @"C:\path\to\device.log";
var fileName = "device.log";
var email = "user@example.com";

var uri =
    $"https://dev.leo4.ru:1444/terem-api/v1/send-email" +
    $"?file_name={Uri.EscapeDataString(fileName)}" +
    $"&email_address={Uri.EscapeDataString(email)}";

var handler = new HttpClientHandler();

// Option A: load client certificate from Windows certificate store (CurrentUser\My)
using var store = new X509Store(StoreName.My, StoreLocation.CurrentUser);
store.Open(OpenFlags.ReadOnly);
var byThumbprint = store.Certificates.Find(
    X509FindType.FindByThumbprint,
    "<CERT_THUMBPRINT_WITHOUT_SPACES>",
    validOnly: false
);
if (byThumbprint.Count > 0)
{
    handler.ClientCertificates.Add(byThumbprint[0]);
}

// Option B: load client certificate from PFX (placeholder path/password)
// var pfxCert = new X509Certificate2(
//     @"C:\path\to\client-cert.pfx",
//     "<PFX_PASSWORD>",
//     X509KeyStorageFlags.MachineKeySet | X509KeyStorageFlags.EphemeralKeySet
// );
// handler.ClientCertificates.Add(pfxCert);

using var http = new HttpClient(handler);
await using var stream = File.OpenRead(filePath);
using var body = new StreamContent(stream);

using var response = await http.PostAsync(uri, body);
var responseText = await response.Content.ReadAsStringAsync();

Console.WriteLine($"HTTP {(int)response.StatusCode} {response.ReasonPhrase}");
Console.WriteLine(responseText);
```

> **C# note (Windows):** Use port **1444** for Schannel compatibility. Import the platform CA into **Trusted Root Certification Authorities**, and use placeholders for certificate thumbprints, PFX path, and password.

---

## Verifying the TLS Handshake

Use `openssl s_client` to confirm the mTLS handshake succeeds before sending real data:

```bash
# Standard profile (port 1443)
openssl s_client \
  -connect dev.leo4.ru:1443 \
  -servername dev.leo4.ru \
  -cert cert.pem -key key.pem \
  -CAfile ca.crt \
  -brief

# Windows Schannel-compatible profile (port 1444)
openssl s_client \
  -connect dev.leo4.ru:1444 \
  -servername dev.leo4.ru \
  -cert cert.pem -key key.pem \
  -CAfile ca.crt \
  -tls1_2 \
  -brief
```

A successful handshake prints `Verification: OK` and `SSL handshake has read … bytes`.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `403 Forbidden: client certificate OU is required` | `OU` field absent in client cert | Re-issue the certificate with `OU=<device_id>` |
| `SSL handshake failure` on port 1443 (Windows) | Schannel rejects modern cipher suite or curve | Switch to port **1444** |
| `SSL handshake failure` — server cert not trusted | Platform CA not in trust store | Pass `--cacert ca.crt` (curl) or add CA to OS trust store |
| `413 Request Entity Too Large` | File > 25 MB | Compress or split the file before sending |
| `curl: (60) SSL certificate problem` | Wrong CA file | Verify `ca.crt` is the platform CA that signed the server cert |

---

## How Device Identity Is Derived

nginx extracts the `device_id` from the **`OU` field** of the client certificate Subject Distinguished Name using the following map rule:

```nginx
map $ssl_client_s_dn $terem_device_id {
    default "";
    ~(^|,)\s*OU=([^,/]+)(,|$) $2;   # RFC 4514 comma-separated DN
    ~(^|/)OU=([^/]+)(/|$)    $2;   # OpenSSL slash-separated DN
}
```

Both `CN=device,OU=4619,O=Leo4` and `/O=Leo4/OU=4619/CN=device` notation are matched.

The extracted value is forwarded to the backend as both:
- the `{device_id}` path segment in `POST /backend-api/v1/send-email/{device_id}`
- the `X-Device-Id` request header

> **Note:** This differs from the MQTT/RabbitMQ authentication, where the `CN` (Common Name) is used as the device identifier (SN). For this HTTP endpoint, the `OU` field carries the numeric `device_id`. A correctly issued platform certificate has both fields populated consistently.

---

## Adding a New Device-Facing mTLS HTTP Endpoint

This endpoint is the **reference pattern** for any future device-facing HTTP API. To add a new endpoint:

1. **Define a new `location` block** in [`nginx-configs/dev_leo4_ru/terem_email_mtls.conf`](../nginx-configs/dev_leo4_ru/terem_email_mtls.conf) (or a new `.conf` file for a different service) pointing to the appropriate backend upstream.
2. **Use the same `$terem_device_id` map** (already defined at the top of [`nginx-configs/dev_leo4_ru/terem_email_mtls.conf`](../nginx-configs/dev_leo4_ru/terem_email_mtls.conf)) — no changes needed if the new endpoint is in the same `conf` file.
3. **Include [`nginx-configs/dev_leo4_ru/snippets/terem_email_proxy.inc`](../nginx-configs/dev_leo4_ru/snippets/terem_email_proxy.inc)** or create a similar snippet that:
   - Rejects with `403` when `$terem_device_id` is empty
   - Passes `X-Device-Id`, `X-SSL-Client-Verify`, `X-SSL-Client-Subject` headers to the backend
   - Disables `auth_jwt_enabled` (mTLS is the sole auth mechanism on these ports)
4. **Expose the port** in `compose.yaml` under the `nginx-mutual` service if a new dedicated port is required.
5. **Document the endpoint** in `docs/` following this file as a template.
