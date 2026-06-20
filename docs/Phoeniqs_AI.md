# Phoeniqs AI — Access & Setup

[Phoeniqs](https://console.phoeniqs.com/) provides shared LLM API credits for
SwissHacks 2026 — frontier and open-source models without your own keys. The
same key works for your application and for coding agents.

---

## 1. General usage

Phoeniqs exposes an **OpenAI-compatible API**, so any SDK or tool that accepts a
custom base URL works unchanged.

[Phoeniqs model documentation](https://documentation.phoeniqs.com/maas/active-models/)

- **Base URL:** `https://maas.phoeniqs.com/v1`
- **API key:** from the console, starts with `sk-...`
- **Models:** listed in the console; pass the id (e.g. `inference-gpt-oss-120b`)
  as the `model` field.

```python
from openai import OpenAI

client = OpenAI(api_key="sk-...", base_url="https://maas.phoeniqs.com/v1")
resp = client.chat.completions.create(
    model="inference-gpt-oss-120b",
    messages=[{"role": "user", "content": "Hello"}],
)
```

Or via env vars (picked up by most OpenAI-compatible tools):

```bash
export OPENAI_API_KEY="sk-..."
export OPENAI_BASE_URL="https://maas.phoeniqs.com/v1"
```

### Model notes

- **Not all open-source models integrate the same way.** Some can't reliably do
  tool calls or drive an MCP server — test before committing to one.
- **Coding:** `inference-glm-51-754b` worked best. `inference-deepseek-v32` had
  trouble producing correct tool calls.
- **SIX MCP:** `inference-qwen3-vl-235b` worked best for driving the SIX tools.

> Credits are shared across all participants — cache responses where you can.

---

## 2. For coding - OpenCode

[OpenCode](https://opencode.ai/) is an AI coding agent. Easiest path:

1. **Install the desktop app** and open **Settings → Providers -> Custom**, pointing it
   at the Phoeniqs base URL + your `sk-...` key. This is the simplest setup, and
   the models you add are also available from the CLI.
2. **CLI is optional** — install it separately if you want a terminal workflow;
   it shares the same config, so models added in the app just work there too.
