## 2025-05-18 - Hardcoded Secrets in Config
**Vulnerability:** Hardcoded API keys (Groq) and Flask secret key found directly in `app.py`.
**Learning:** Hardcoded secrets in source code expose sensitive credentials if the codebase is ever compromised or made public. Also using `os.urandom()` for Flask secret key breaks session state when running with multiple gunicorn workers.
**Prevention:** Always use environment variables for sensitive credentials (`os.getenv`). Avoid generating dynamic random secrets at runtime if multiple workers are expected.
