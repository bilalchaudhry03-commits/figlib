---
type: llm
---

A good run:
- measures the problem with figlib's check_layout rather than guessing (the labels render near 7 pt on a slide);
- raises the text to slide size (roughly 18 px or more in this 1700-wide viewBox, so 10 pt+) and grows or
  re-lays-out the boxes so the longer labels still fit inside them;
- ends with check_layout clean, and looks at the result (e.g. a screenshot) rather than relying on the linter alone.
