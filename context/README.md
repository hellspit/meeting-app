# Personal context

Drop `*.md` / `*.txt` files here with facts you want Claude to use when it drafts
your suggested answers — e.g. your role, your team, current projects, product
names, acronyms, people you work with, and how you like to phrase things.

- **Contents are gitignored** (only this README and `.gitkeep` are tracked), so
  nothing personal is committed.
- There is a **hard token cap** (`max_context_tokens` in `config.yaml`, ~2–3k).
  If your notes exceed it they are truncated with a visible warning — keep the
  most useful facts near the top.
- No retrieval/ranking yet (deferred): everything here is fed as one block.

Example `context/me.md`:

```
Role: Backend engineer on the Payments team.
Current work: migrating the billing service to the new ledger API.
People: Priya (my manager), Sam (tech lead).
Style: concise, lead with the decision, avoid over-promising dates.
```
