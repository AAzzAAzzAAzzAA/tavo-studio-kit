# Security

Do not publish API keys, private endpoint URLs, private chats, or unredacted Android probe reports.

Local secrets belong in `.env.local`, which is ignored by Git and excluded from package zips.

If you find a security issue in this Dev Kit, open a private GitHub security advisory after the repository exists. If the issue is in Tavo itself, report it to the Tavo maintainers instead.

When sharing logs, redact:

- `Authorization` headers
- bearer tokens
- API keys
- private model endpoints
- private chat content
