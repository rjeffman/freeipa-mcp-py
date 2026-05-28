# Important rules for AI agents

## AI Efficiency

Most agents are more efficient when dealing with Markdown text than with JSON objects, so when implementing a tool:
- If the output is unstructured **ALWAYS** use markdown format
- If the output is big (2KB or more), prefer markdown format
- If the output is small and structured, use JSON

## Running tests locally

**ALWAYS** follow this rules when running local tests:

- If a tool is not available and needs to be installed, **ALWAYS** use a Python virtual environment in a directory under `/tmp`

## Contributing code to the repostory

It is **CRITICAL** that **ALL** rules defined in [docs/contributing.md](docs/contributing.md) are followed. There's even an available skill (`ensure-contributing-rules`) to check it.

When contributing code to the repository, you **must**:
- **Always** run the pre-commit checks, even if pre-commit hooks are not installed. The checks are available through `contrib/ci.sh`
- **Never** commit a fix or feature before it has automated tests to verify it
- **Never** commit a fix or feature without asking user if the feature/fix was tested and is ready to be commited
- If during tests an issue with the current fix/feature is found and a fix is produced, this should be commited along with the fix/feature. **Never** allow a pull request to be created with a commit for a feature and a commit the fixes the same feature
- **Always** document the usage of AI in the commit message.
