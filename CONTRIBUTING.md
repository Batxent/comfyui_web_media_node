# Contributing

Thanks for contributing.

## Workflow

1. Fork and create a feature branch.
2. Keep changes focused and small.
3. Add or update tests when behavior changes.
4. Run tests locally:

```bash
cd /Users/tommy/Documents/GitHubOpenSources/juice/comfyui_web_media_node
python -m pytest -q
```

1. Open a pull request with:

- problem statement
- change summary
- test evidence

## Coding Notes

- Keep the node API stable where possible.
- Prefer explicit error messages for user-facing failures.
- Avoid adding heavy runtime dependencies unless necessary.
