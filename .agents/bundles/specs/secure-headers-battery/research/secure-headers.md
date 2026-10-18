---
type: Research
title: Secure-headers battery prior art
description: Prior-art survey and Litestar 2.24 behavior findings that fix the secure-headers battery's defaults and hook choice.
tags: [research, security, headers, litestar]
---

# Secure-headers battery research

Gathered 2026-10-16 for issue #14. Confidence is high for the local-code, experiment and RFC findings (F1, F3-F6, F9, F12) and medium for the fetched-summary findings (F7, F10); re-verify those against upstream docs before quoting them in user-facing docs.

## Findings

- **F1 - No equivalent exists.** Litestar 2.24.0 has no security-headers middleware (only CORS, CSRF, allowed_hosts, compression, response_cache, ...). PyPI `litestar-secure` returned 404; a web search found no community Litestar plugin.
- **F2 - Prior art.** `secure.py` 2.0.1 (`SecureASGIMiddleware`, presets BALANCED/BASIC/STRICT, overwrites existing headers by default). Helmet.js and Django `SecurityMiddleware` are the conventions to follow.
- **F3 - OpenAPI UIs need a relaxed CSP.** Litestar 2.24 Swagger/Scalar/Redoc/RapiDoc/Stoplight pages use inline scripts/styles and CDN hosts (cdn.jsdelivr.net, unpkg.com, cdn.redoc.ly, fonts.googleapis.com) with no nonce support. A default CSP with `default-src`/`script-src` would break `/schema`. A CSP with only non-fetch directives (`frame-ancestors`, `base-uri`, `form-action`, `object-src`) does not.
- **F4 - Route-level middleware misses 404/405.** An app-level `Litestar(middleware=[...])` ASGI middleware added its header to 200 and handler-raised 500 responses but NOT to router-level 404 (unknown path) or 405 (wrong method), because user middleware is built per route handler.
- **F5 - `before_send` covers everything.** `Litestar(before_send=[hook])` with `MutableScopeHeaders.from_message(msg).setdefault(...)` added the header to 200, 404 and 405. The hook receives every outgoing message type, so it must filter on `http.response.start`.
- **F7 - Defaults differ across prior art.** Referrer-Policy: Django `same-origin`, helmet/OWASP `no-referrer`, secure.py `strict-origin-when-cross-origin`. X-Frame-Options: helmet `SAMEORIGIN`, OWASP `DENY`. HSTS: helmet on (1 year + includeSubDomains), Django off, OWASP 2 years.
- **F8 - OWASP / MDN.** `X-XSS-Protection` is deprecated; never send `1`, omit it (or send `0`). `frame-ancestors` supersedes `X-Frame-Options`; `ALLOW-FROM` is obsolete. `Permissions-Policy` syntax is `directive=(allowlist)` comma-separated (`camera=(), geolocation=(self "https://x")`). `Cache-Control: no-store`, `Clear-Site-Data` and `COEP: require-corp` are application-semantic and unsuitable as blanket defaults.
- **F9 - Header names.** ASGI raw header names are lowercase bytes; `MutableScopeHeaders` lowercases and latin-1 encodes names.
- **F10 - Precedence.** Django leaves handler-set headers alone; secure.py overwrites. Both conventions exist.
- **F11 - Report-Only.** `Content-Security-Policy-Report-Only` is a separate header, never blocks, and needs `report-to`/`report-uri` to be useful.
- **F12 - HSTS.** RFC 6797 s7.2/s8.1: a host MUST NOT send STS over non-secure transport and a UA MUST ignore it there. Preload (hstspreload.org) needs `max-age >= 31536000`, `includeSubDomains` and `preload`; removal takes months. Never emit `preload` implicitly.

## Limitations

- Redoc `blob:` workers and `fonts.gstatic.com` needs were not verified from primary sources.
- The 404/405 middleware gap was tested on Litestar 2.24.0 / Python 3.14 only; the lower bound `litestar>=2` is unchecked, and `before_send` on websocket scopes was not exercised.
- helmet's current version and Django's exact defaults came via fetch summaries.
