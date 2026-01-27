# Agent Instructions

## Testing

- Use the default Python `unittest` module for tests in this project.
    - You can include API integration testing to this.

## Project Conventions

Each major component of this project will be placed in its own folder. This should include its requirements, configuration, etc.

For Python components, a project-wide virtual environment will be used.

## Deployment

Use Docker Compose from the repository root to run services:

```bash
sudo docker compose up -d --build
```

## Code Style

When writing Python, follow PEP8 standards with a line length maximum of 100 characters. Python function docstrings should follow the reStructuredText style with field lists (i.e., `:param x: ...`), also being succinct and clear. Variable names should make clear what the variable is for without being too long. Don't use comments for code with a clear purpose and actions.

Consider the memory usage of what you're doing and don't create enormous objects taking up excessive memory, apart from where required for model sessions.

Write secure code. 
Beautiful is better than ugly.
Explicit is better than implicit.
Simple is better than complex.
Complex is better than complicated.
Flat is better than nested.
Sparse is better than dense.
Readability counts.
Special cases aren't special enough to break the rules.
Although practicality beats purity.
Errors should never pass silently.
Unless explicitly silenced.
In the face of ambiguity, refuse the temptation to guess.
There should be one, and preferably only one, obvious way to do it.
