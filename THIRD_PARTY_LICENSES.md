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
| [python-multipart](https://github.com/Kludex/python-multipart) | Apache-2.0 | https://github.com/Kludex/python-multipart |

## Bundled frontend assets

The Python wheel ships a pre-built React single-page app at `mle_beast/web/static/`. That bundle includes the following third-party libraries (each in its own license-compliant minified form):

| Package | License | Project URL |
|---|---|---|
| [react](https://react.dev) | MIT | https://github.com/facebook/react |
| [react-dom](https://react.dev) | MIT | https://github.com/facebook/react |
| [scheduler](https://github.com/facebook/react/tree/main/packages/scheduler) | MIT | https://github.com/facebook/react |

Build tooling (not shipped in the bundle, used only at build time):

| Package | License | Project URL |
|---|---|---|
| [vite](https://vitejs.dev) | MIT | https://github.com/vitejs/vite |
| [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react) | MIT | https://github.com/vitejs/vite-plugin-react |

License notices for the libraries embedded in the bundle are preserved inline in the minified JS via the licenses' standard "Copyright … MIT" comment headers. The full license text for each lives in `prototypes/dashboard/node_modules/<pkg>/LICENSE` after `npm install`.

## Regeneration

To regenerate this file (e.g., after adding a dependency):

```bash
pip install pip-licenses
pip-licenses --packages pocketflow instructor openai litellm pydantic pyyaml pytest \
                       fastapi uvicorn python-multipart \
             --format=markdown --with-urls
```

The full license text for each dependency is included in its installed `dist-info/` directory.
