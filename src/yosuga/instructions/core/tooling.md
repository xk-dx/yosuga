# Tooling Rules

- Prefer reading context before editing files.
- Keep edits minimal and localized.
- Preserve public behavior unless requested to change.
- Use structured tool schemas and deterministic calls.
- Do not run destructive commands unless explicitly approved.
- Avoid interactive shell commands that wait for stdin or prompts.
- When a command may prompt interactively, prefer a non-interactive flag, a scripted answer, or a different workflow.
- For scaffolding commands like `npm create`, `npm init`, or `vite`, use an empty target directory or explicit non-interactive options instead of launching the prompt flow.
