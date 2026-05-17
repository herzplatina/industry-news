# Python Style Rules

Synthesized from [PEP 8](https://peps.python.org/pep-0008/), [The Hitchhiker's Guide to Python](https://docs.python-guide.org/writing/style/), and [Clean Code in Python](https://testdriven.io/blog/clean-code-python/).

---

## 1. Naming

- **Functions, variables, parameters, modules**: `snake_case`
- **Classes and exceptions**: `CapWords`
- **Module-level constants**: `UPPER_SNAKE_CASE`
- **Internal/private names**: single leading underscore (`_name`)
- Use descriptive names — a reader should know what a variable holds without surrounding context
- No single-character names except throwaway loop vars (`i`, `k`, `v` in short comprehensions are OK)
- Avoid abbreviations unless universally understood in context (`url`, `id` are fine; `s`, `n`, `tmp` are not)

## 2. Imports

- Group in order: **standard library → third-party → local**, each group separated by a blank line
- One module per `import` line; `from X import A, B, C` on one line is fine
- No wildcard imports (`from X import *`)
- All imports at the top of the file, after any module docstring, before module-level code

## 3. Line Length & Layout

- **Maximum 88 characters** per line (Black's default; more practical than PEP 8's 79)
- Long function signatures, calls, and data structures: break across lines with one item per line and a trailing comma on the last item
- Prefer implicit line continuation inside parentheses over backslash `\`
- Multi-line natural-language strings (prompts, help text, SQL) are exempt from the length limit
- 4 spaces per indentation level; never tabs
- Two blank lines before and after every top-level function or class definition
- One blank line between methods within a class

## 4. Functions

- Each function does **one thing** — if you need "and" to describe it, split it
- Annotate every parameter and the return type (see §5)
- Prefer ≤ 3 positional arguments; beyond that, keyword arguments with defaults improve call-site clarity
- Return early for guard/error cases to keep the happy path unindented
- All return paths should either return a value or `None` — never mix implicitly
- No mutable default arguments — use `None` and assign inside the function body

## 5. Type Hints

- Annotate all function signatures: parameters **and** return type (including `-> None`)
- Use built-in generics — `list[str]`, `dict[str, int]`, `tuple[str, ...]` — not `typing.List` (Python 3.9+)
- Use `X | None` not `Optional[X]`, and `X | Y` not `Union[X, Y]` (Python 3.10+)
- Make collection type parameters specific: `set[str]` not bare `set`, `dict[str, Any]` not bare `dict`

## 6. Exception Handling

- Catch the **most specific** exception type; never use bare `except:`
- Keep `try` blocks as small as possible — only the lines that can raise, not a whole function body
- Chain exceptions explicitly: `raise NewError("msg") from original_exc`

## 7. Pythonic Idioms

- `if not seq:` / `if seq:` — not `if len(seq) == 0:` / `if len(seq) > 0:`
- `if x is None:` / `if x is not None:` — not `== None` or `!= None`
- `isinstance(x, T)` — not `type(x) == T`
- `"".join(parts)` — not string concatenation in a loop
- `d.get(key, default)` — when a missing key should silently return a default
- `with open(...) as f:` — always use context managers for files and connections
- f-strings for all string interpolation; never `%` formatting or `.format()` where f-strings suffice
- List comprehensions over `map()`/`filter()` when the expression fits readably on one line

## 8. DRY (Don't Repeat Yourself)

- If the same logic appears in two or more places, extract it to a shared function or module
- Shared utilities that don't belong to a single domain go in `src/utils.py`
- Sibling functions with near-identical bodies should be collapsed into a single private helper with the differing parts passed as parameters

## 9. Constants over Magic Numbers

- Every numeric or string literal that carries independent meaning or might need tuning belongs in a named constant
- Define constants at module level in `UPPER_SNAKE_CASE`, immediately after imports
- Use underscore separators in large numeric literals: `20_000` not `20000`

## 10. Comments

- Write comments only to explain **why**, not what — well-named code already explains what
- No commented-out code; use git history to recover deleted code
- Inline comments: use sparingly, only when non-obvious; at least 2 spaces before `#`
- No docstrings for internal/private functions unless the reasoning is genuinely non-obvious to a reader
