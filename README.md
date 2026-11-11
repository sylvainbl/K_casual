# Gene Expression Explorer

A local web prototype for exploring the supplied gene expression dataset in natural language.

## Run the app

Install Docker Desktop on macOS or Windows 11 and start it. On Windows, use Linux containers.
From this repository, run:

```sh
docker compose up --build
```

The first launch downloads the Docker images and the default model,
[Qwen3 4B Instruct](https://ollama.com/library/qwen3:4b-instruct). Allow about
6 GB of downloads in total, including about 2.5 GB for the model weights.
Ollama stores the model in a Docker volume. When the application starts,
open [http://localhost:8000](http://localhost:8000). Inference runs locally on the CPU.
The app requires no API key. Use Ctrl+C to stop both services. Run
`docker compose logs ollama` to check download progress or diagnose startup issues.

Try these questions from the assignment:

- How can you help me?
- What are the main genes involved in lung cancer?
- What is the median value expression of genes involved in breast cancer?
- What is the median value expression of genes involved in esophageal cancer?

## Test on a 16 GB laptop

The assignment sets a maximum of 16 GB of RAM for the whole laptop. To leave
room for the operating system and browser, test with about 8 GB allocated to
Docker Desktop. On macOS, set the memory limit in **Settings → Resources**.
On Windows 11 with WSL 2, set an 8 GB memory limit in WSL Settings and restart
WSL and Docker Desktop. See the [Docker Desktop settings](https://docs.docker.com/desktop/settings-and-maintenance/settings/)
and [WSL configuration](https://learn.microsoft.com/windows/wsl/wsl-config).

To simulate slower CPU inference, start the stack with a two-CPU quota and
two inference threads for Ollama. On macOS:

```sh
OLLAMA_CPUS=2 docker compose up --build
```

In Windows PowerShell:

```powershell
$env:OLLAMA_CPUS = "2"
docker compose up --build
```

Run `docker stats` in a second terminal while trying the four questions above.
Time the first request after startup and repeat it with the model already loaded.
Check for a capability explanation, a lung gene list, a breast expression
table and a no-records response for esophageal cancer.

Compose caps Ollama at 5 GiB and FastAPI at 256 MiB. Ollama keeps one model
loaded and runs one inference at a time with a 4,096-token context. The app
allows up to 768 generated tokens and sets a five-minute request timeout by
default. The `MODEL_MAX_OUTPUT_TOKENS` and `MODEL_TIMEOUT_SECONDS` environment
variables override those defaults. An incomplete query decision returns an error.

## Design and trade-offs

```text
Browser ──► FastAPI ──► agent ──HTTP──► Ollama
                           │
                           └──► tools ──► CSV
```

Compose runs two services. FastAPI serves the static HTML, CSS and JavaScript and
handles `POST /api/chat`. Ollama is reachable on the internal Compose network.
The browser accesses only FastAPI. Each submitted question is independent.

The local model interprets the question in one Ollama call and returns a decision
with the operation, scope, cancers, and gene symbols. Python validates the decision
before using the data tools. Comparisons, rankings, calculations, and lookups for
multiple cancers receive a message explaining the supported scope. For a valid
expression query, Python looks up the cancer, retrieves the requested medians, and
reports any requested genes with missing values.

The expression tool takes the cancer as well as the gene list because the same gene
can have different values across cancers. The app shows the median stored for each
gene and lists associated genes without ranking them. Esophageal cancer is absent
from the dataset and yields a no-records response.

Local inference simplifies account setup and keeps questions on the machine. It
requires a model download and CPU latency varies by computer. The small model can
misinterpret an ambiguous or complex question. This prototype focuses on one cancer
per question. The frontend uses standard browser APIs for one form and one result
view, which keeps setup free of a separate frontend build.

## Run the tests

With Python 3.14, install the locked dependencies and run the suite.

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

The tests check that a shared gene retains the value for the selected cancer,
that unsupported and invalid decisions cannot reach the data tools, and that
missing cancers and genes receive appropriate responses. They also check that
the API renders Markdown with raw HTML disabled. The agent tests simulate Ollama
responses and require no model download.

## Update dependencies

Edit the direct dependencies in `requirements.in`, then regenerate the pinned
`requirements.txt` with `uv`.

```sh
uv pip compile --universal --python-version 3.14 requirements.in -o requirements.txt
```

## AI-assisted development

A coding assistant helped scaffold the application, draft the interface and build
the checks. It speeds up iteration and offers alternatives for review. It can also
suggest plausible code with incorrect assumptions, especially around package APIs,
tool schemas or the meaning of a dataset column. The supplied CSV, the automated
checks and actual Ollama responses provide evidence for reviewing the result.
