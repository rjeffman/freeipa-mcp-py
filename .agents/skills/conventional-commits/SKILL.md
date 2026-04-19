---
name: conventional-commits
description: Use when creating git commits - ensures all commit messages follow the Conventional Commits v1.0.0 specification for automated changelog generation and semantic versioning
---

# Conventional Commits Specification

**IMPORTANT**: Every git commit MUST follow this specification. This is not optional.

## Commit Message Structure

```
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

### Components

1. **Type** (REQUIRED): Describes the category of change
2. **Scope** (OPTIONAL): Provides additional contextual information
3. **Description** (REQUIRED): Short summary in present tense
4. **Body** (OPTIONAL): Longer explanation of the change
5. **Footer(s)** (OPTIONAL): Metadata like breaking changes, issue references, sign-offs

## Commit Types

### Mandatory Types (per specification)

- **feat**: A new feature (correlates with MINOR in semantic versioning)
- **fix**: A bug fix (correlates with PATCH in semantic versioning)

### Recommended Additional Types

- **build**: Changes to build system or external dependencies
- **ci**: Changes to CI configuration files and scripts
- **docs**: Documentation only changes
- **perf**: Performance improvements
- **refactor**: Code change that neither fixes a bug nor adds a feature
- **style**: Changes that don't affect code meaning (formatting, whitespace)
- **test**: Adding missing tests or correcting existing tests
- **chore**: Other changes that don't modify src or test files

### Type Selection Guide

| Change | Type | Reasoning |
|--------|------|-----------|
| Add new function/feature | `feat` | Introduces new functionality |
| Fix a bug | `fix` | Patches existing code |
| Update documentation | `docs` | Only affects documentation |
| Refactor without behavior change | `refactor` | Improves code structure |
| Add/update tests | `test` | Test-related changes |
| Update CI/CD pipeline | `ci` | CI configuration changes |
| Update dependencies | `build` | Build system changes |
| Performance optimization | `perf` | Makes code faster |
| Format code (no logic change) | `style` | Formatting only |
| Maintenance tasks | `chore` | Housekeeping |

## Scope

The scope provides additional context about what part of the codebase is affected:

- Use lowercase
- Keep it short and meaningful
- Use parentheses: `feat(parser):`
- Examples: `api`, `cli`, `parser`, `auth`, `database`, `ui`

**When to use scope:**
- When the change is isolated to a specific component
- To make the changelog more organized
- To help identify what area of code changed

**When to omit scope:**
- When the change affects multiple areas
- For small/simple projects
- When a scope isn't meaningful

## Description

- MUST be in lowercase (first word after colon)
- Use imperative, present tense: "change" not "changed" nor "changes"
- Don't capitalize first letter
- No period (.) at the end
- Keep it under 72 characters
- Be concise but descriptive

### Good Examples
```
feat: add user authentication endpoint
fix: prevent race condition in cache invalidation
docs: update API documentation for v2.0
```

### Bad Examples
```
feat: Added user authentication endpoint  # Wrong tense
fix: Fixes race condition                 # Wrong tense, capitalized
docs: Updated the API docs.               # Wrong tense, has period
```

## Breaking Changes

Breaking changes MUST be indicated in one or both of these ways:

### Method 1: Exclamation Mark
```
feat!: remove support for Python 3.8
refactor(api)!: change response format to JSON-API spec
```

### Method 2: Footer
```
feat: add configuration file support

BREAKING CHANGE: environment variable configuration is no longer supported.
Use the new config.yaml file instead.
```

**Use both methods for critical breaking changes to maximize visibility.**

## Body

- Separated from description by one blank line
- Use to explain:
  - WHY the change was needed (motivation)
  - HOW it differs from previous behavior
  - Any side effects or consequences
- Use imperative, present tense
- Can be multiple paragraphs
- Wrap at 72 characters per line

Example:
```
fix: prevent memory leak in connection pool

The connection pool was not properly closing idle connections,
causing memory to grow unbounded over time. This adds a new
idle timeout configuration and ensures connections are properly
cleaned up after the timeout expires.
```

## Footers

Footers appear after the body (or description if no body), separated by one blank line.

### Common Footer Types

#### Breaking Change
```
BREAKING CHANGE: API endpoints now require authentication
```

#### Issue References
```
Fixes #123
Closes #456
Refs #789
```

#### Authorship and Sign-off
```
Signed-off-by: Jane Doe <jane@example.com>
Co-authored-by: John Smith <john@example.com>
Assisted-by: Claude:claude-sonnet-4-5
Reviewed-by: Alice Johnson <alice@example.com>
```

#### Other Metadata
```
Change-Id: I1234567890abcdef
Acked-by: Maintainer Name <maintainer@example.com>
```

### Footer Format

- Use `Token: value` or `Token #value` format
- Tokens can be multi-word: `Reviewed-by`, `BREAKING CHANGE`
- Can have multiple footers
- Each footer on its own line

## Complete Examples

### Simple Feature
```
feat: add support for markdown tables
```

### Feature with Scope
```
feat(parser): add ability to parse nested arrays
```

### Breaking Change (Method 1)
```
feat!: drop support for Node.js 12

Node.js 12 reached end-of-life. This version now requires Node.js 14+.

BREAKING CHANGE: Node.js 12 is no longer supported
```

### Bug Fix with Body
```
fix: prevent race condition in database connection pool

The pool was not properly locking when checking out connections,
causing occasional crashes under high concurrency. Added mutex
locking around the checkout operation.

Fixes #123
```

### Multiple Footers
```
feat(auth): implement OAuth2 authentication

Add support for OAuth2 authentication flow with refresh tokens.
This enables integration with third-party identity providers.

Implements #456
Reviewed-by: Security Team <security@example.com>
Signed-off-by: Developer Name <dev@example.com>
```

### Refactor with Breaking Change
```
refactor(api)!: change response format to JSON-API specification

Previously the API returned custom JSON structure. This changes
all API responses to follow the JSON-API v1.1 specification for
better interoperability with standard tooling.

BREAKING CHANGE: All API response structures have changed.
See migration guide at docs/migration-v2.md
```

## Workflow Checklist

Before committing, verify:

- [ ] Type is appropriate for the change
- [ ] Description is concise, lowercase, present tense, under 72 chars
- [ ] No period at end of description
- [ ] Scope is used if change is isolated to specific component
- [ ] Breaking changes marked with `!` and/or `BREAKING CHANGE:` footer
- [ ] Body explains WHY if the change is not obvious
- [ ] All required footers present (e.g., `Signed-off-by` if required by project)
- [ ] Issue references included if applicable
- [ ] AI assistance attributed if substantial (e.g., `Assisted-by:`)

## Project-Specific Requirements

When working on a project, check for additional requirements:

1. **Required footers**: Some projects require `Signed-off-by` (DCO)
2. **AI attribution**: Projects may require `Assisted-by:` for AI-assisted commits
3. **Issue tracking**: Required issue references in footers
4. **Scope conventions**: Project-specific scope names
5. **Additional types**: Custom types beyond the standard set

**Always check the project's CONTRIBUTING.md file for additional requirements.**

## Common Mistakes to Avoid

❌ **Wrong tense**
```
feat: added new feature  # Should be "add"
fix: fixed bug          # Should be "fix"
```

❌ **Capitalized description**
```
feat: Add new feature  # Should be lowercase
```

❌ **Period at end**
```
feat: add new feature.  # Remove the period
```

❌ **Vague description**
```
feat: updates           # Too vague
fix: bug fix           # Not descriptive
```

❌ **Missing breaking change indicator**
```
feat: remove deprecated API  # Needs ! or BREAKING CHANGE footer
```

✅ **Correct versions**
```
feat: add new feature
fix: prevent null pointer exception
feat!: remove deprecated API
```

## Tools and Automation

Conventional Commits enables:

- **Automated changelog generation**: Tools like `conventional-changelog`
- **Semantic versioning**: Automatically determine next version number
- **Release notes**: Generate release notes from commits
- **Commit linting**: Enforce format with `commitlint`
- **Git hooks**: Validate commits before they're accepted

## References

- Specification: https://www.conventionalcommits.org/en/v1.0.0/
- Semantic Versioning: https://semver.org/
- Keep a Changelog: https://keepachangelog.com/

---

**Remember**: Following this specification is not just about formatting—it enables powerful automation for changelog generation, versioning, and project communication. Every commit is a communication tool for both humans and machines.
