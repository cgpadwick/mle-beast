# Third-Party Licenses

mle-beast depends on the following open-source packages. Each is governed by its own license, listed below.

## Runtime dependencies

| Package | License | Project URL |
|---|---|---|
| [pocketflow](https://github.com/The-Pocket/PocketFlow) | MIT | https://github.com/The-Pocket/PocketFlow |
| [instructor](https://github.com/instructor-ai/instructor) | MIT | https://github.com/instructor-ai/instructor |
| [openai](https://github.com/openai/openai-python) | Apache-2.0 | https://github.com/openai/openai-python |
| [litellm](https://litellm.ai) | MIT | https://litellm.ai |
| [pydantic](https://github.com/pydantic/pydantic) | MIT | https://github.com/pydantic/pydantic |
| [PyYAML](https://pyyaml.org/) | MIT | https://pyyaml.org/ |
| [pytest](https://docs.pytest.org/en/latest/) | MIT | https://docs.pytest.org/en/latest/ |

## Optional web dependencies (`pip install mle-beast[web]`)

| Package | License | Project URL |
|---|---|---|
| [fastapi](https://github.com/fastapi/fastapi) | MIT | https://github.com/fastapi/fastapi |
| [uvicorn](https://uvicorn.dev/) | BSD-3-Clause | https://uvicorn.dev/ |
| [Jinja2](https://github.com/pallets/jinja/) | BSD-3-Clause | https://github.com/pallets/jinja/ |
| [python-multipart](https://github.com/Kludex/python-multipart) | Apache-2.0 | https://github.com/Kludex/python-multipart |

## Regeneration

To regenerate this file (e.g., after adding a dependency):

```bash
pip install pip-licenses
pip-licenses --packages pocketflow instructor openai litellm pydantic pyyaml pytest \
                       fastapi uvicorn jinja2 python-multipart \
             --format=markdown --with-urls
```

The full license text for each dependency is included in its installed `dist-info/` directory.
