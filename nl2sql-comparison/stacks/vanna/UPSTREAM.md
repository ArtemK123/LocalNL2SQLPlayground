# Vanna stack upstream

| Field | Value |
|-------|--------|
| **Active fork** | [drharunyuksel/datachat](https://github.com/drharunyuksel/datachat) |
| **Pinned commit** | `33a30fb63ecf8f3d299093a30f24415a8e200592` (2026-04-06) |
| **PyPI package** | `datachat` (installs Python module `vanna`) |
| **Original (archived)** | [vanna-ai/vanna](https://github.com/vanna-ai/vanna) — archived 2026-03-29, last release v2.0.2 |

There is no new official repo under the `vanna-ai` GitHub org. Vanna 2.0 lives on the archived
`vanna-ai/vanna` repo and PyPI `vanna==2.0.2`. For AWS experiments we install the **DataChat**
fork instead: same Vanna 2.0 agent API, plus bug fixes (serialization, PostgreSQL prompts).

Harness stack name remains `vanna` (framework slot). Rebuild the container after changing the pin:

```powershell
.\scripts\local\up-stack.ps1 -Stack vanna -Build
# AWS:
.\scripts\aws\start-stack.ps1 -Stack vanna
```
