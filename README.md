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

Try these assignment questions in **Simple mode**. The expected results are:

- How can you help me? — A description of what the app can do.
- What are the main genes involved in lung cancer? — ALK, RET, ROS1, STK11, and KRAS.
- What is the median value expression of genes involved in breast cancer? —
  BRCA2 0.032, BRCA1 0.094, TP53 0.233, GATA3 0.602, CDH1 0.561, ESR1 0.716,
  MAP3K1 0.701, HER2 0.42, PIK3CA 0.449, and AKT1 0.278.
- What is the median value expression of genes involved in esophageal cancer? — A message that the dataset has no records for it.

Turn on **Advanced mode** to try an analysis such as “Which genes are shared by
breast and prostate cancers?” or “What is the highest recorded median expression
for each cancer?” The result includes the executed SQL.

## Design and trade-offs

```text
Browser ──► FastAPI ──► agent ──HTTP──► Ollama
                           │
                           └──► tools ──► CSV
```

Compose runs two services. FastAPI serves the static HTML, CSS and JavaScript and
handles `POST /api/chat`. Ollama is reachable on the internal Compose network.
The browser accesses only FastAPI. Each submitted question is independent.

The app runs Qwen locally through Ollama. This keeps questions on the machine
and makes setup possible without an API key or a hosted inference service. The
trade-off is a model download on first launch, plus CPU and memory use on the
laptop. Response times depend on the machine. The compact local model also has
less capacity for complex reasoning and SQL generation than a larger model
available through a hosted API.

Simple mode prioritizes reliability. For one cancer at a time, users can list
recorded genes or retrieve their stored median expression values. Ollama
identifies the request, and Python validates it. Python calls `get_targets` to
list genes and then calls `get_expressions` if medians are requested. The second
tool takes the cancer too, since the same gene can have different values across
cancers. Keeping the scope small makes the supported queries easier to verify.
In one run with the local model, all 24 questions in the
[simple benchmark](tests/benchmark_simple.json) produced the expected response,
including requests that needed clarification or were outside the supported scope.

Advanced mode prioritizes flexibility. Ollama generates SQL, so users can ask
for comparisons, rankings, and aggregations without a separate tool for each
analysis. Python runs the query in read-only SQLite and displays the returned
rows and the SQL. That flexibility comes at the cost of reliability. A query can
run successfully and still answer a different question, making an incorrect
result easy to mistake for a correct one. In one run of the
[advanced benchmark](tests/benchmark_sql.json), 14 of 20 results matched the CSV
reference. The local model failed to translate all five of the hardest questions
into SQL that captured the requested analysis. These limitations are why the
mode is marked experimental.

## Run the tests

Install Python 3.14, then run these commands from the repository root.

**macOS**

```sh
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
```

**Windows (PowerShell)**

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

If an existing `.venv` reports `No module named pip`, run its Python executable
with `-m ensurepip`, then retry the installation.

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

## AI-assisted development pros and cons

To build this project, I used Codex with a ChatGPT Plus subscription alongside
VS Code.

I think the biggest trap with AI is letting it write all the code without
discussing the design with it beforehand. You can end up spending too much time
trying to understand why the code was written that way. Code you didn't think
through yourself is hard to read, even with AI tools to explain it.

AI also tends to do too much sometimes. That's why it's important to give it a
clear scope. For this project, I thought a React app was overkill, but ChatGPT
recommended one. I went with plain HTML, CSS, and JavaScript because the interface
only needed a form and a results view. ChatGPT also doubted that the app could
work reliably with a local LLM.

The biggest pro I see in using AI to code is that it can challenge my design. My
process is always to come up with a design and ask the AI to challenge it, explain
how it would have done it, and give me the pros and cons of both approaches. I
generally don't agree with everything, but it rarely fails to bring up something
I hadn't thought about.

Another pro is saving time on the frontend and unit tests when a project has to
move fast. I wanted a very simple frontend and to spend as little time as possible
on it while still understanding it. I wanted unit tests because I can't imagine
a project without them. With such a short deadline, I used AI to help write them
so I could spend more time on the most important parts of the code.

For the most important parts of the code, I use AI as a reviewer. Sometimes I ask
it to write code based on pseudocode I wrote first. I always make sure to review
the code afterward in VS Code.
