# Coding Agent Instructions

This `AGENTS.md` applies to coding agents working in this repository.

# Source of Truth

- Use `docs/` as the canonical source for stable architecture, protocol, and high-level goal and technical choices.
- Use `agent/` to get current actively-developing feature's context.
- No edition in `docs/` unless user ordered. Allowed to update progress and deliever in-progress documents at `agent/`
- Keep implementation and planning artifacts in `agent/` unless a task explicitly requires another location.

# Required Coding Guidance

1. **All milestones must be E2E verified.**
   Passing unit, mock, or stub tests alone does not mean the work is done.
2. **Add Google-style docstrings for non-trivial functions.**
3. **Pause and reflect on low-quality code before finalizing changes.**
   Explicitly check for hard-coded variables/paths, overly complicated logic, and repeated code blocks, then improve or justify them.
4. **Fallback and Mock are Discouraged**
   Expose issues better sooner than later.