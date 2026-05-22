# Presale PDF build

Regenerate the PDF from the Markdown source:

```bash
cd docs/presale
pip install -r requirements-pdf.txt
python build_pdf.py
```

The PDF dependencies are intentionally kept separate from the repository `uv.lock`.
If you prefer `uv`, use an isolated environment and install the same requirements there.

Output file:

- `leo4-vendor-execution-layer-response.pdf`
