# Split-Brain Workstation — As-Built Record (Rev F)

Surveyed 2026-08-25. Every value below was probed live (SSH to the phone, `nvidia-smi`/CIM on the PC).
Companion artifact: https://claude.ai/code/artifact/529a6da5-40ec-4dca-8e2c-400ba7a239de

## Decision

Odysseus stays on the phone. The laptop gains Ollama as a **tiered** endpoint that never holds VRAM at idle.

1. Unloading is correctness, not thrift — the laptop is a daily driver running Steam, Epic, Riot Vanguard,
   Discord, Spotify and four browsers. All 1868 MiB currently on the GPU is graphics context, not compute.
   Free VRAM is a number that moves.
2. Nothing needs building — Odysseus stores backends in a `model_endpoints` SQL table
   (`base_url`, `api_key`, `endpoint_kind`). Adding the laptop is one row.
3. Two tiers — the existing `localhost:8200` shim needs no GPU and stays enabled as fallback
   for when the laptop is gaming, asleep, or away.
4. Embeddings stay on the phone — `fastembed`/`chromadb`/`onnxruntime` all work under glibc.
   Memory, documents and research keep functioning with the laptop off; only generation crosses the link.

## Brains — rybz3070 / 100.82.8.53

| | |
|---|---|
| Chassis | Lenovo laptop, daily driver |
| CPU | AMD Ryzen 7 5800H, 8C/16T |
| RAM | 31.9 GB (12.2 GB free at probe) |
| GPU | NVIDIA RTX 3070 **Laptop**, 8192 MiB |
| VRAM | 1868 used / **6164 free**, 19% util, 52°C, 19.8 W idle |
| Driver | 546.30; no CUDA toolkit (`nvcc` absent — not needed for Ollama) |
| OS | Windows 11 Home 10.0.26200 |
| Disks | C: 79 GB free · D: 128 GB free · G: 75 GB free |
| Python | 3.14.4 via `py` |
| WSL | `wsl.exe` present, unused |
| Tailscale | 1.96.3 |
| Inference | **none installed** — no Ollama, llama.cpp, LM Studio |

## Body — galaxy-s24-ultra / 100.117.120.93

| | |
|---|---|
| Device | Samsung SM-S928B (Galaxy S24 Ultra) |
| OS | Android 16, unrooted |
| SoC | SM8650, arm64-v8a |
| RAM | 10 GiB total, 5.0 GiB available |
| Swap | 11 GiB (2.0 GiB used) |
| Storage | 222 GB, 156 GB free |
| Termux | Python 3.13.13, Node v26.3.1 |
| Desktop | XFCE4 on TigerVNC `:1` |
| Container | proot-distro `ubuntu` → Ubuntu 26.04 LTS "Resolute Raccoon", 11 GB |
| Guest Python | 3.14.4 |
| Docker | impossible (unrooted Android) |

**Path correction:** the live rootfs is
`/data/data/com.termux/files/usr/var/lib/proot-distro/containers/ubuntu/rootfs`.
The legacy `installed-rootfs/ubuntu` path is an empty 15 KB stub and reads as an uninstalled distro.

## Odysseus — installed component

| Property | Value | State |
|---|---|---|
| Location | `/root/odysseus` (inside proot) | verified |
| Branch | `dev` @ `ed18192a8ebd235ce38826ee5428e53445ec2455`, 2026-06-19 | ~2 months old |
| Launcher | `/root/run-odysseus.sh` | verified |
| Web bind | `0.0.0.0:7000` | tailnet-wide |
| Vector store | chroma 1.5.9 → `127.0.0.1:8100`, path `data/chroma` | working |
| Embeddings | fastembed 0.8.0, onnxruntime 1.27.0 | working |
| Runtime | fastapi 0.137.2, uvicorn 0.49.0, numpy 2.4.6, httpx 0.28.1 | verified |
| `.env` | `LLM_HOST=localhost`, `SEARXNG_INSTANCE` | points nowhere useful |
| History | 3 sessions, 18 chat messages in `data/app.db` | has been used |
| Process | no uvicorn, no chroma running | stopped |
| Service files | `install-service.sh`, `odysseus-ui.service` | systemd — unusable under proot |

### `model_endpoints` table

| ID | Name | base_url | kind | enabled |
|---|---|---|---|---|
| `bf229841` | Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai` | api | **no** |
| `4108b5ab` | localhost:8200 | `http://localhost:8200/v1` | local | yes |
| *(to add)* | Laptop GPU | `http://100.82.8.53:11434/v1` | local | — |

**Live defect:** `settings.json` has `default_endpoint_id=bf229841` (the *disabled* Gemini endpoint)
with `default_model=models/gemini-2.5-flash`. The default resolves to a switched-off backend,
while the only enabled backend is a Termux shim onto cloud models.

## Port map (probed by TCP connect — `ss`/`netstat` are blind without root)

| Port | Service | Where | State |
|---|---|---|---|
| 7000 | Odysseus web UI | proot | reserved, free |
| 8100 | ChromaDB | proot | reserved, free |
| 8200 | Antigravity OpenAI shim (`antigravity_openai_proxy.py`) | Termux | listening |
| 8022 | sshd | Termux | listening |
| 5901 | Xvnc `:1` / XFCE4 | Termux | listening |
| 8096 | Jellyfin | proot | listening |
| 8989 | Sonarr | proot | listening |
| 9696 | Prowlarr | proot | listening |
| 9091 | transmission-daemon | proot | listening |
| 8191 | FlareSolverr | Termux | listening |
| 5354 | DoH proxy | Termux | configured, down |
| 5984 | Obsidian sync | Termux | configured, down |
| 11434 | Ollama | laptop | nothing there |

## Modularity contract — five seams

- **S1 — Model endpoint.** A row in `model_endpoints`. Any OpenAI-compatible `/v1` URL.
  Swap Ollama for llama.cpp, vLLM, LM Studio or a hosted API by editing one field.
- **S2 — Runtime host.** State currently at `/root/odysseus/data`, *inside* the rootfs.
  Moving it out via `ODYSSEUS_DATA_DIR` is what makes the container disposable.
- **S3 — Transport.** Tailscale. MagicDNS does **not** resolve from Termux (`rybz3070` unresolvable),
  so this degrades to a literal IP — keep `100.82.8.53` in exactly one place.
- **S4 — Lifecycle.** Entirely laptop-side. `OLLAMA_KEEP_ALIVE=0` now; a wake-proxy later if
  cold starts break. The phone never learns which.
- **S5 — Supervision.** `~/.termux/boot/start_linux.sh` already governs sshd and VNC with
  check-then-start idempotence. Odysseus joins it. The shipped systemd unit is dead weight.

## Model policy

**The ceiling is not 8 GB — it is whatever `nvidia-smi` reports free right now** (6164 MiB at survey,
and it shrinks when a browser or game opens). One rule governs every future swap:

    weights_on_disk + KV_cache <= free VRAM

Ollama's listed size *is* the weights. The KV cache is what triggers the OOM and grows with context
length — budget ~1 GB at 32K unless quantised.

### Roster (sizes from the Ollama registry, 2026-08-25)

| Model | Size | Context | Capabilities | Headroom at 6.16 GB |
|---|---|---|---|---|
| `qwen3.5:4b` | 3.4 GB | 256K | vision, tools, thinking | 2.7 GB — **default** |
| `qwen2.5-coder:7b` | ~4.7 GB | 32K | tools | 1.4 GB — coding slot |
| `qwen3:8b` | 5.2 GB | 40K | tools, thinking | 0.9 GB — idle only |
| `qwen3.5:4b-q8_0` | 5.3 GB | 256K | vision, tools, thinking | 0.8 GB — idle only |
| `granite4.2:8b-q4_K_M` | 5.3 GB | — | — | 0.8 GB — idle only |
| `qwen3.5:9b` | 6.6 GB | 256K | — | **does not fit** |

Default is `qwen3.5:4b` — not because it is the largest that fits, but because the 5.2–5.3 GB
candidates only load while the desktop is quiet. At 3.4 GB it survives the same contention that
forced the tiered architecture. Whether `qwen3:8b` at Q4 beats `qwen3.5:4b` at Q8 is undetermined
(benchmark source unavailable); pull both and judge — 10.5 GB against 128 GB free on D:.

### Rules

| # | Rule | Level | Done when |
|---|---|---|---|
| 5.1 | Treat live free VRAM as the budget, never 8192 MiB | MUST | `--query-gpu=memory.free` read before any pull |
| 5.2 | Pull `qwen3.5:4b` as default | MUST | generates with no offload spill, browser open |
| 5.3 | Pull `qwen3:8b` and `qwen2.5-coder:7b` as alternates | SHOULD | all three in the Odysseus picker |
| 5.4 | Cap context at 16–32K rather than accepting 256K | SHOULD | long session runs without OOM |
| 5.5 | KV-cache quantisation: `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0` | MAY | same context at lower VRAM |
| 5.6 | Pull anything >=6 GB | WONT | — |

### Swapping a model, end to end

`ollama pull <name>` on the laptop -> it appears in the Odysseus picker automatically (the endpoint's
`model_refresh_mode` is `auto`) -> select per chat, or set as default. No config file, no restart,
nothing edited on the phone. That is seam S1 doing its job.

## Remaining work

| # | Work | Where | Level | Done when |
|---|---|---|---|---|
| 1.1 | Install Ollama for Windows | laptop | MUST | `ollama --version` answers |
| 1.2 | `OLLAMA_HOST=0.0.0.0:11434` as persistent env var, not shell export | laptop | MUST | phone gets JSON from `/api/tags` |
| 1.3 | `OLLAMA_KEEP_ALIVE=0` | laptop | MUST | VRAM back to baseline <10 s after a reply |
| 1.4 | Pull `qwen3.5:4b` (see Model policy) | laptop | MUST | generation with no CPU-offload spill |
| 1.5 | Allow inbound 11434 on the Tailscale interface | laptop | SHOULD | 1.2 succeeds |
| 2.1 | Add the endpoint row | phone | MUST | laptop models appear in the picker |
| 2.2 | Repoint the broken default | phone | MUST | fresh chat loads the model (watch `nvidia-smi`) |
| 2.3 | Keep `:8200` enabled as tier 2 | phone | SHOULD | both backends switchable per chat |
| 3.1 | Cold-start test after 10 min idle | both | MUST | reply returns, no client timeout |
| 4.1 | Start Odysseus from the Termux boot script | phone | MUST | survives a reboot unattended |
| 4.2 | Confirm auth gates the `0.0.0.0` bind | phone | MUST | login prompt from the laptop |
| 4.3 | Move data out of the rootfs (S2) | phone | SHOULD | rebuild container, state survives |
| — | Run weights on the phone | — | WONT | |
| — | Host Odysseus on the laptop | — | WONT | |
| — | Docker anywhere on the phone | — | WONT | |
| — | Expose any port to the public internet | — | WONT | |

## Open

- **Q1 — resolved.** Dissolved rather than answered: a roster replaces a single pick, so the use
  case is chosen per chat instead of at install time. See Model policy above.
- **Q2 (risk)** — the laptop sleeps. "Always on" was stated, but this is a lid-closed consumer
  laptop. If it suspends, tier 1 vanishes and tier 2 carries the load. Pin the power policy.
- **Q3 (blocks 2.4)** — embeddings on phone or laptop? Setting `LLM_HOST` also moves
  `EMBEDDING_URL` (defaults to `http://{LLM_HOST}:11434/v1/embeddings`). Phone-side works today.
- **Q4 (blocks 4.4)** — pull latest `dev` or freeze at `ed18192`?

---

# As-Built — Rev D (2026-08-26)

## Built and verified

| Item | Result |
|---|---|
| 1.1 | Ollama 0.32.15 installed (winget, user scope) |
| 1.2 | `OLLAMA_HOST=0.0.0.0:11434` at User scope; phone confirmed `REACHABLE 200` |
| 1.3 | `OLLAMA_KEEP_ALIVE=0`; VRAM returns to baseline, no ollama compute process at idle |
| 1.4 | Roster complete, manifests verified: `qwen3.5:4b` 3.4 GB, `qwen2.5-coder:7b` 4.7 GB, `qwen3:8b` 5.2 GB (12.4 GB total). `qwen2.5-coder:7b` needed a second pull. |
| 1.5 | Not needed — Tailscale traffic already permitted; phone reaches 11434 |
| 2.1 | Endpoint `182e58cc` "Laptop GPU (rybz3070)" -> `http://100.82.8.53:11434/v1`, enabled |
| 2.2 | Default repointed: `bf229841`/`models/gemini-2.5-flash` -> `182e58cc`/`qwen3.5:4b` |
| 2.3 | `localhost:8200` left enabled as tier 2 |
| 3.1 | **Done.** Cold start from the phone over Tailscale against the configured base URL: **5.9 s**, VRAM fully released beforehand. Budget was 30-60 s. |
| 4.1 | Odysseus added to `Start_All.sh`, `Stop_All.sh`, `Status.sh` (marker-delimited) |
| 4.2 | Auth confirmed: `/` -> 302 `/login`, `/api/settings` -> 401 over Tailscale |
| 4.3 | State copied to `/data/data/com.termux/files/home/odysseus-data` (133 MB); `ODYSSEUS_DATA_DIR` set; ChromaDB `--path` repointed. Original left in place as fallback. |

## Fixed along the way (not in the original spec)

**FastEmbed embedding lane was dead.** `model.onnx` was a `.incomplete` stub, so memory,
document RAG, deep research and the tool index all had no embedding lane — which removes the
main reason for keeping Odysseus on the phone. Two causes: an interrupted download, and
fastembed resolving a newer revision (`model_optimized.onnx`) than Odysseus pins
(`model.onnx` @ `5f1b8cd7`). Now: `FastEmbed loaded`, `ToolIndex initialized (lanes=['fastembed'])`.

## RESOLVED — GPU driver updated 2026-08-26

Was: `CUDA error: device kernel image is invalid` on driver **546.30 / CUDA 12.3** (Nov 2023),
which could not run Ollama 0.32.15's compiled CUDA kernels. `OLLAMA_LLM_LIBRARY=cpu` held the
system working meanwhile.

Now: driver **610.88 / CUDA 13.3**. `setup_ollama_host.ps1` detected it, removed the CPU
override automatically, and re-verified. GPU inference confirmed by VRAM trace — free VRAM fell
7612 -> 4707 MiB during generation (~2.9 GB of weights resident) and returned to 7612 MiB with
zero ollama compute processes afterwards, so `OLLAMA_KEEP_ALIVE=0` holds on the GPU path.

First-ever GPU request took 74 s (one-time kernel warm-up). Every subsequent cold start is ~6 s.

## Notes

- `qwen3.5:4b` is a *thinking* model — it emits `reasoning` tokens, so `max_tokens` needs headroom.
- The tray app (`ollama app.exe`) cannot be used: with `OLLAMA_HOST=0.0.0.0` its readiness probe
  never succeeds, so it retries forever and nothing listens. `ollama serve` is run directly instead,
  with a Startup-folder shortcut for autostart.
- `pgrep -f "uvicorn app:app"` self-matches any shell command containing that string. Use `ps -ef`
  when checking from an SSH one-liner.
- **The Ollama process can be alive while nothing listens.** Seen after an abrupt stop: `ollama.exe`
  present in the process list, port 11434 refusing. `ollama list` still works (it reads the store
  directly), so it is not a reliable liveness check — probe the port. Re-running
  `setup_ollama_host.ps1` clears it; the script kills the stale process and restarts.
- **Driver 5xx renamed the `nvidia-smi` header field.** `CUDA Version:` became
  `CUDA UMD Version:`, which silently broke the GPU-capability check in `setup_ollama_host.ps1`
  and would have kept forcing the CPU fallback after a successful driver update. The pattern now
  accepts both: `CUDA(?:\s+UMD)?\s+Version:`.
- **A batched `ollama pull` can skip a model without failing loudly.** The first run pulled
  `qwen3.5:4b` and `qwen3:8b` but left `qwen2.5-coder:7b` absent. Verify against
  `~/.ollama/models/manifests/registry.ollama.ai/library/`, not against the pull transcript.

## Scripts added

| File | Runs on | Purpose |
|---|---|---|
| `setup_ollama_host.ps1` | PC | Idempotent endpoint setup: env vars, server, autostart, firewall, verify |
| `push_and_run.py` | PC | Pushes a script to the phone and runs it (`--proot` for the Ubuntu guest) |
| `odysseus_endpoint.py` | phone | Registers/updates the model endpoint row; repoints the default |
| `odysseus_autostart.py` | phone | Adds Odysseus to the three shortcut scripts |
| `odysseus_relocate_data.py` | phone | Moves state out of the rootfs (seam S2) |
| `odysseus_fetch_embeddings.py` | guest | Repairs the FastEmbed model download |

---

# Operations

## Resetting the Odysseus admin password

Odysseus keeps one bcrypt hash in `<data>/auth.json` under `users.<name>.password_hash`.
There is no reset CLI; `setup.py` regenerates the account when `auth.json` is absent.

    # 1. stop Odysseus  (see the pkill warning below)
    ~/.shortcuts/Stop_All.sh

    # 2. back up and remove the auth store
    D=/data/data/com.termux/files/home/odysseus-data
    cp -p $D/auth.json $D/auth.json.bak-$(date +%Y%m%d-%H%M%S)
    rm -f $D/auth.json

    # 3. regenerate -- ODYSSEUS_DATA_DIR MUST be passed explicitly (see below)
    proot-distro login ubuntu -- bash -lc "cd /root/odysseus && \
      ODYSSEUS_DATA_DIR=$D ODYSSEUS_SKIP_ADMIN_PROMPT=1 ./venv/bin/python setup.py"

    # 4. restart
    ~/.shortcuts/Start_All.sh

Step 3 prints `Temporary password: <token>`. To choose the password instead of having one
generated, set `ODYSSEUS_ADMIN_PASSWORD` (and optionally `ODYSSEUS_ADMIN_USER`) on the same line;
`setup.py` prefers env vars over the prompt over a random token.

Verify without a browser:

    curl -s -X POST http://127.0.0.1:7000/api/auth/login \
      -H "Content-Type: application/json" \
      -d '{"username":"admin","password":"<token>"}'
    # -> {"ok":true,"username":"admin"}

Performed 2026-08-26. Previous hash preserved at `auth.json.bak-20260826-125154`.

## Failure modes hit during the reset

- **`setup.py` does not read `ODYSSEUS_DATA_DIR` from `.env`.** The running app does; `setup.py`
  does not. Without the explicit env var it resolved to the *original* in-rootfs data directory and
  reported `[skip] auth.json already exists` while the relocated store sat empty. Because the
  original copy was deliberately left as a fallback, this fails silently rather than erroring.

- **`pkill -f "app:app"` kills the SSH session running it.** Same self-match as `pgrep -f`: the
  remote command line contains the pattern, so pkill matches its own shell and the connection dies
  mid-command. Use a bracket class that the regex matches but the literal command line does not:
  `pkill -f "[u]vicorn app:app"`. Prefer `~/.shortcuts/Stop_All.sh`, which runs from a script file
  whose command line is just the script path.

- **The login route is `POST /api/auth/login` with a JSON body.** `POST /login` returns 405.

---

# Rev E (2026-08-26) — Hybrid graphics, AI mode, monitoring

## Hybrid mode: the desktop moved off the discrete GPU

BIOS Hybrid mode was enabled, then the AMD driver installed (31.0.12044.3, no reboot needed).

| | Pre-Hybrid | Hybrid, basic driver | Hybrid + AMD driver |
|---|---|---|---|
| Panel | 144Hz on the 3070 | **60Hz** | **144Hz on the iGPU** |
| VRAM used | ~1100 MiB | 668 MiB | **208 MiB** |
| VRAM free | 7058 MiB | 7351 MiB | **7811 MiB** |
| Apps rendering on the 3070 | ~23 | ~23 | **3** |

**753 MiB of VRAM recovered.** `qwen3.5:9b` (6.4 GB) now leaves ~1.4 GB for KV cache
instead of ~700 MiB.

Two costs, both measured:

- **The iGPU reserves ~4 GB of system RAM.** `TotalVisibleMemorySize` fell from 31.9 GB to
  **27.9 GB**. This is permanent while Hybrid mode is on.
- **Between enabling Hybrid and installing the AMD driver the panel ran at 60Hz**, because
  Windows fell back to the Microsoft Basic Display Adapter. Presented as general system lag.

The iGPU is `PCI\VEN_1002&DEV_1638` (Cezanne Vega). Before Hybrid mode it did not enumerate
in Windows *at all* — not as disabled, not as hidden. Absence is what a firmware-disabled
device looks like.

## The CPU regression was self-inflicted, not Ollama 0.33.0

Rev D attributed 100%-CPU inference to Ollama's self-upgrade. **That was wrong.**

The real cause: `OLLAMA_LLM_LIBRARY=cpu` persisted at **Process scope** in the shell that
launched the server. User and Machine scope were both clean, so nothing in the persisted
environment hinted at it. Every server started from that shell inherited `cpu`.

`setup_ollama_host.ps1` had the matching defect: its unset branch cleared the process
variable only when the *persisted* value was non-empty, so a stale process-scope value
survived untouched.

A second instance of the same class surfaced immediately after: an **empty** `OLLAMA_MODELS`
at Process scope shadowed the User value, and Ollama reported 0 models while all six sat on
disk. `OLLAMA_MODELS` is now a variable `setup_ollama_host.ps1` owns and sets explicitly.

Fixed and verified: `qwen3.5:9b` loads 6.4 GB, runs `100% GPU`, releases on completion.

Also fixed: driver 5xx renamed the `nvidia-smi` header field from `CUDA Version:` to
`CUDA UMD Version:`, which broke the capability check and would have silently kept forcing
CPU after a successful driver update.

## Built

| File | Runs on | Purpose |
|---|---|---|
| `ai_mode.ps1` | laptop | `ai` / `gaming` / `status`; closes, records, restores |
| `ai_mode_config.json` | laptop | toggle list, 12 candidates, 5 enabled by default |
| `workstation_status.py` | laptop | read-only JSON on `:11435` — `/status`, `/config` |
| `setup_workstation_autostart.ps1` | laptop | one Ollama entry + the status service |
| `dashboard_ai_panel.py` | phone | AI Workstation panel, 10 live rows |
| `dashboard_ai_wire.py` | phone | idempotent patcher for `dashboard.py` |
| `phone_reclaim.py` | phone | installs `Reclaim_RAM.sh` / `Restore_Media.sh` |

**Design decisions worth keeping:**

- The status service is **read-only by construction** — no POST, no kill path. A writable
  service on the tailnet was rejected in design; a read-only one carries none of that risk.
- **`/api/ps` is the cross-machine GPU signal.** `size_vram == size` means 100% GPU. The phone
  cannot run `nvidia-smi`, and this removes the need for an agent on the laptop.
- **Config is served, not copied.** The phone reads `/config` live, so there is one source of
  truth rather than two files drifting apart.
- **Gaming mode does not stop Ollama.** With `KEEP_ALIVE=0` an idle server holds no VRAM.
- **Shell components are unlistable.** `$NeverClose` lives in the script, not the config, so
  no toggle can take the desktop down.

## Three PowerShell bugs, all found by testing

- **`Set-Content -Encoding utf8` writes a BOM on 5.1.** `json.load` rejects it, so the status
  service reported `mode: normal` while AI mode was active. Same trap already recorded for
  Odysseus's `.env`. Now written via `[IO.File]::WriteAllText` with `UTF8Encoding($false)`,
  and read with `utf-8-sig` defensively.
- **A second `ai` run wiped the restore list.** Idempotent on processes, destructive to the
  record — Gaming mode could never restore anything. Now accumulates onto prior state.
- **`ConvertFrom-Json` on `[]` yields `$null`**, and `@($null)` is a one-element array holding
  null. It round-tripped into the file as a stray `[]` entry and crashed the restore loop,
  because **`-ErrorAction SilentlyContinue` does not suppress parameter *binding* validation**.

Two more 5.1 quirks hit along the way:

- `ConvertTo-Json -AsArray` is PowerShell 7+; on 5.1 it throws and aborts the script silently.
- 5.1 serialises a one-element array as a bare object, so the brackets must be forced back on.
- `$raw | ConvertFrom-Json | Where-Object {...}` unrolls differently from assigning first and
  then filtering. The two-step form is the one that behaves.

## Autostart resolved

Ollama 0.33.0's upgrade added its own `Ollama.lnk`, which launches the tray app — and the tray
app cannot serve on `0.0.0.0`, because its readiness probe treats the bind address as a
destination. With both entries present the two raced for 11434 and after one reboot **neither**
survived. The vendor shortcut is now parked as `Ollama.lnk.disabled`.

Startup folder now holds `Ollama Server (Odysseus).lnk` and `Workstation Status.lnk`.

## Verified

- AI mode closed Overwolf (5 processes), recorded both paths; Gaming mode relaunched both.
- Status service reported `mode: ai`, `restorable: Overwolf, Overwolf Browser` — the phone
  sees laptop mode changes.
- All ten dashboard rows resolve from the phone.
- Under AI mode: "nothing rendering on the dGPU".

## Not done

- **`Reclaim_RAM.sh` has never been run.** Deployed and syntax-checked only; it stops the
  media stack, so it was left for a deliberate test.
- **The phone dashboard has not been seen rendered** — every field was verified through the
  data path, not visually.
- **`dashboard.py` has no autostart.** It never did; it is launched from the XFCE desktop.
- Three apps (Epic Games Launcher, EOS overlay, Lenovo Vantage) were closed by the pre-fix
  run with their restore record destroyed. All are logon-start and return on reboot.

---

# Rev F (2026-08-29) — Empty model store, and the Google Workspace path

## The tray app is not dead — the CLI resurrects it

Rev E parked `Ollama.lnk` and called autostart resolved. It was not.

The Ollama CLI launches `ollama app.exe` whenever it finds no server on 11434. Once the
Startup-folder server is gone, the next `ollama` command anywhere on the machine brings the
tray back as a fallback. Parking the shortcut removes one entry point, not the mechanism.

**The tray-spawned server builds its own environment and does not inherit `OLLAMA_MODELS`.**
It reads the default store at `C:\Users\hmoha\.ollama\models`, which is empty, while all
manifests sit on `D:\ollama-models`.

Observed at 12:58 on 2026-08-29:

| | |
|---|---|
| `ollama app.exe` PID 21752 | started 12:58:31 |
| `ollama.exe serve` PID 29988 | started 12:58:32, child of the above |
| `/api/tags` | reachable, `model_count: 0` |
| Startup shortcut | correct — target `ollama.exe`, args `serve` |
| `Ollama.lnk.disabled` | still parked |
| Run keys | no Ollama entry |

Three signals distinguish a tray-spawned server from a correct one:

- binds `::` instead of `0.0.0.0` — it never received `OLLAMA_HOST`
- `ollama list` returns a bare header
- `ollama app.exe` is present in the process table

**This also explains both earlier "Ollama did not autostart" reports.** A server *was*
running each time. It was the wrong one, serving an empty library.

Fixed by killing both processes and relaunching `ollama.exe serve` with the User-scope
variables read explicitly. Eight models returned; verified over `100.82.8.53:11434` and
`100.82.8.53:11435/status`.

**Durable fix not yet applied:** rename `ollama app.exe` to `ollama app.exe.disabled` so the
CLI's fallback fails instead of starting a mis-configured server.

## The dashboard was right

`model_count: 0` was an honest report of laptop state, not a phone-side or transport fault.
The monitoring seam did the job it was built for — first time it has caught something.

## Model roster as of this revision

Eight models, ~85 GB on `D:\ollama-models`, D: 89.9 GB free.

| Model | Size |
|---|---|
| `qwen3.6:35b-a3b` | 21.07 GB |
| `gpt-oss:20b` | 12.85 GB |
| `mistral-nemo:12b` | 6.59 GB |
| `qwen3.5:9b` | 6.14 GB |
| `qwen3-vl:8b` | 5.72 GB |
| `qwen3:8b` | 4.87 GB |
| `qwen2.5-coder:7b` | 4.36 GB |
| `qwen3.5:4b` | 3.16 GB |

`qwen3.6:35b-a3b` has been pulled but never loaded. Whether it runs is still unmeasured.

## File-size polling was wrong a third time

During the `qwen3.6` pull I measured zero store growth over 45 s and a 77-minute-old partial
write, and reported the download stalled. It completed normally minutes later.

Three wrong calls from the same method this project: a completed blob called stalled, a
preallocation burst read as 584 MB/s, and this. **Store growth is not evidence about pull
state.** Ask the pull.

## Google Workspace email — what Odysseus actually requires

Odysseus ships a `google_workspace` provider preset (`static/js/settings.js:2928`) carrying
`oauth: 'google'`. UI path: Settings → Integrations → Email accounts → provider →
**Connect with Google**.

The button redirects to `/api/email/oauth/google/authorize`, which fails with
`GOOGLE_OAUTH_CLIENT_ID not set — add it to .env` (`routes/email_routes.py:3405`).

**`.env` on the phone holds three keys** — `LLM_HOST`, `SEARXNG_INSTANCE`,
`ODYSSEUS_DATA_DIR`. No Google credentials. Nothing has been configured.

### Two paths

**App Password.** Select the plain `gmail` preset, which carries no `oauth` key and is
ordinary IMAP/SMTP (`imap.gmail.com:993`, `smtp.gmail.com:465`). A Workspace address
authenticates against those hosts like a consumer one. Requires the Workspace admin to have
enabled IMAP and permitted app passwords, plus 2SV on the account.

**OAuth.** Requires in `.env`:

```
GOOGLE_OAUTH_CLIENT_ID=...
GOOGLE_OAUTH_CLIENT_SECRET=...
GOOGLE_OAUTH_REDIRECT_URI=http://localhost:7000/api/email/oauth/google/callback
```

Odysseus requests scope `https://mail.google.com/ email`, stores tokens encrypted through
`src.secret_storage.encrypt`, and auto-fills `imap.gmail.com:993` / `smtp.gmail.com:587` on
callback.

### Two traps in the OAuth path

**Redirect URI.** Omitting `GOOGLE_OAUTH_REDIRECT_URI` makes Odysseus derive it from the
request `Host` header (`email_routes.py:3407`). Browsing from the laptop yields
`http://100.117.120.93:7000/...`, and Google refuses to register a private IP — only
`http://localhost` and `http://127.0.0.1` are accepted over plain HTTP. Pin the variable to
`localhost` and run the authorisation from a browser on the phone, where Odysseus listens on
`0.0.0.0:7000`.

**Restricted scope.** `https://mail.google.com/` is restricted. On an External consent screen
in Testing mode, refresh tokens expire after 7 days. An Internal consent screen — available
only to the domain administrator — avoids both the verification review and the expiry.

`.env` is read at startup; Odysseus must be restarted after editing it.

## Open

- Rename `ollama app.exe` to kill the tray fallback for good.
- Load `qwen3.6:35b-a3b` and read the `PROCESSOR` split from `ollama ps`.
- Google Workspace: awaiting the choice of path and whether the domain is administered here.

---

# Rev G (2026-08-29) — Agents could not read email; three source patches

## No agent could call an email tool, and the accounts were never the problem

Four Gmail/mxrouting accounts were added, the mail UI worked, and every agent
call failed with `Unknown tool type: list_emails`. Cause: **the name the prompt
advertises is not a name the dispatcher can execute.**

- `agent_loop.py:439` renders the tool as a fenced ` ```list_emails ` block.
- The tool index selects those bare names — verified by querying it live:
  `list_emails`, `read_email`, `send_email`, `bulk_email`, … for an email query.
- `TOOL_TAGS` accepts them as executable blocks, so the parser builds one.
- `_execute_tool_block_impl` has **no** email branch, `_MCP_TOOL_MAP` holds only
  bash/python/file/web/image, and `TOOL_HANDLERS` has no email keys. All eight
  tested names returned `False` against both registries.
- The block falls to `else:` → `Unknown tool type` (`tool_execution.py:919`).

The capability was present the entire time: the built-in MCP server connects
with 14 tools and is reachable as `mcp__email__<tool>`. Only the advertised name
never reached an executor. `agent_loop.py:1147-1152` lists both forms in one
set — this checkout sits mid-refactor (`ed18192`, "move session tools to the
agent_tools registry"), and `src/agent_tools/` has no email module.

**The model was following instructions correctly.** Its own reasoning — "the
system prompt explicitly defines `list_emails`" — was right.

## A second, independent latency cause on the same page

`_keepalive_loop` pings endpoints every 60s to prevent cold starts, resolving
targets via `model_discovery.warmup_ping_urls()` — a port scan of `localhost`
and `host.docker.internal`. The only backend is a tailnet row, so the scan found
**0 endpoints 12,761 times** while costing 1-6s of phone CPU a minute, and never
once pinged the laptop it exists to keep warm.

## Measured before the fixes

| | |
|---|---|
| IMAP list, per account, cold | 0.85-2.19s (LOGIN 0.53-1.11s of it) |
| Four accounts serial | 7.14s · 33,462 messages |
| LLM call, cold-load component | 4.19-5.99s (`OLLAMA_KEEP_ALIVE=0`) |
| LLM answer, end to end | 7.4-42.9s, one 80.8s |
| Tailscale RTT, phone → laptop | 34 ms — never the problem |

## Three patchers, all marker-delimited, idempotent by refusal, with backups

| File | Target | Change |
|---|---|---|
| `odysseus_email_list_pool.py` | `routes/email_routes.py` | List path acquires from `_IMAP_POOL` instead of a fresh LOGIN per call; four in-body `conn.logout()` removed (`finally` is the sole disposal point); faulted conns release with `ok=False`; `_pooled_release` disposes of a connection it displaces; one timing line per list call |
| `odysseus_keepalive_endpoints.py` | `app.py` | Keep-alive reads enabled `model_endpoints` rows instead of port-scanning |
| `odysseus_email_tool_dispatch.py` | `src/tool_execution.py` | `qualify_email_tool_name()` maps the 14 bare email tool names to `mcp__email__<tool>` at the dispatch boundary, before the if/elif chain |

The dispatch fix normalises **at the boundary** rather than adding
`_MCP_TOOL_MAP` entries, deliberately: the existing `mcp__` branch injects
`_EMAIL_MCP_OWNER_ARG` into the arguments, and a `_MCP_TOOL_MAP` entry would
have skipped owner scoping. Verified — an unscoped call is refused:
`Tool 'mcp__email__list_emails' is restricted to admin users on this deployment.`

`resolve_contact` / `manage_contact` are excluded from the mapping; they have
their own native branches and keep them.

## Verified after restart

| | Before | After |
|---|---|---|
| List call connection | `conn=1.03s (fresh)` every call | `conn=0.20s` **(reused)**, total 2.18s → 1.35s |
| Port scans | every 61s, 12,761 total | **0** since restart |
| Warmup pings | none ever reached the laptop | 28, incl. `http://100.82.8.53:11434/v1/models` |
| Agent email call | `Unknown tool type: list_emails` | `Tool executed: mcp: mcp__email__list_emails -> exit_code=0`, agent summarised the real inbox |

## Native function calling is off, and that is why the model must write fences

`agent_loop.py:2113` disables native tool schemas for Ollama OpenAI-compat URLs
unless the endpoint row sets `supports_tools=True`. All three `model_endpoints`
rows have `supports_tools = NULL`, so every model is forced onto the fenced-block
path. `qwen3.5:4b` fails at it — one observed attempt emitted
` ```json ` / `[mcp__email__list_emails]`, putting the tool name in the content
instead of the fence tag. `qwen3.6:35b-a3b` formats it correctly.

Not changed. One field, reversible, but it carries a documented risk (Ollama
models emitting a native tool_call token then stopping, issue #1567).

## Open

- `supports_tools=1` on `182e58cc` — enable native function calling and measure.
- `OLLAMA_KEEP_ALIVE` conditional on `ai`/`gaming` mode; ~4-6s per LLM call.
- `qwen3.6:35b-a3b` is 21 GB against ~6-8 GB of VRAM; LLM calls on it were seen
  failing after 60s and succeeding in 49-92s.
- Durable on-disk email header cache — nothing survives a restart today; the
  three in-memory caches are 8s (list), 30min (bodies), 60s (connections).
- The 60s unread-dot poll still costs a full 50-header FETCH per cycle.
- Upstream is ~2 months ahead; all three patches will conflict on a rebase.

---

# Rev H (2026-08-29) — Empty and truncated LLM replies

## Two symptoms, one arithmetic error

Replies stopped mid-sentence or came back empty, intermittently. Cause: the two
halves of the stack disagreed about the context window by **32x**.

- Ollama serves `context_length: 4096` — its default. The OpenAI-compat `/v1`
  path gives a client no way to raise it; only `OLLAMA_CONTEXT_LENGTH` does.
- Odysseus assumed **131072**: `KNOWN_CONTEXT_WINDOWS['qwen3'] = 131072`
  (`model_context.py:184`) prefix-matches every qwen3.x model. `/v1/models`
  carries no context field for it to correct itself from.
- Odysseus's agent prompt measured **2749 tokens** — 67% of the real window
  before a single tool result landed. Its own metrics reported
  `context_percent: 2.1` at the time.
- Ollama truncates silently: a ~7000-token prompt came back reporting
  `prompt_tokens=2050`, with no error.

**Is it Ollama's fault?** Trigger, not culprit. Both models emit a perfect
fenced tool block on a small prompt (qwen3.5:9b in 6.3s, qwen3.6:35b-a3b in
102.2s). Neither side is wrong alone; the disagreement is.

## Thinking models make the overflow invisible

`qwen3.6:35b-a3b` and `qwen3.5:9b` emit reasoning to a separate channel and
leave `content` empty until it ends. Asked to reply `BANANA-42`, the 35B
returned `content: ""` with **671 characters** in `reasoning` and
`finish_reason: length`. Given a large enough budget it answered correctly:
671 chars of reasoning, 9 of content.

So an exhausted budget looks like nothing at all — which is what
`Agent round N summary: 0 chars` records.

**The non-streaming path could not see that channel.** Streaming accepted
`reasoning_content` / `reasoning` / `thinking` (`llm_core.py:2133`);
non-streaming accepted only `content` / `reasoning_content`, duplicated at two
sites. Ollama emits `reasoning`. The duplication is why the two drifted.

## Context sizing, measured on qwen3.5:9b

| `num_ctx` | GPU offload | Throughput |
|---|---|---|
| 4096 | 100% | 59.2 tok/s |
| **8192** | **100%** | **58.8 tok/s** |
| 16384 | 86% | 38.5 tok/s |
| 32768 | 78% | 21.1 tok/s |

8192 doubles the window for nothing. Above it the KV cache pushes weights off
the 8 GB card and throughput collapses. `qwen3.6:35b-a3b` for comparison:
22.48 GB against `size_vram` 5.34 GB — **24% offload**, 16.8-31.3 tok/s.

## Built

| File | Target | Change |
|---|---|---|
| `setup_ollama_host.ps1` | laptop env | Owns `OLLAMA_CONTEXT_LENGTH` (8192) beside HOST/KEEP_ALIVE/MODELS; `-ContextLength` param |
| `odysseus_local_served_context.py` | `src/model_context.py` | `ODYSSEUS_LOCAL_SERVED_CONTEXT` caps the assumed window for local endpoints, applied once in `_get_context_length_cached` |
| `odysseus_nonstreaming_call_path.py` | `src/llm_core.py` | Shared `_openai_message_text()` reads all four channels at both non-streaming sites; `DEFAULT_TIMEOUT` 30 → 120 |
| `odysseus_tool_fence_inline_json.py` | `src/tool_parsing.py` | `_TOOL_BLOCK_RE` accepts a JSON payload on the fence line |

The ceiling is declared, not probed: `/api/ps` reports the served window only
while a model is resident, and `OLLAMA_KEEP_ALIVE=0` unloads it between every
call, so a probe would find nothing almost every time. The two numbers must be
kept equal by hand — `OLLAMA_CONTEXT_LENGTH` on the laptop,
`ODYSSEUS_LOCAL_SERVED_CONTEXT` in Odysseus's `.env`.

`DEFAULT_TIMEOUT` was 30s against 16.8-58.8 tok/s and completions observed at
26-92s, producing `attempt 1 failed after 30.04s:` with an empty error string —
a read timeout, not an upstream failure. `CONNECT_TIMEOUT` stays 10s, so a dead
host still fails fast.

## The fence parser discarded a valid call

qwen3.5:9b emitted ```` ```list_email_accounts{} ```` — right tool, right
arguments, right closing fence, no newline after the tag. `_TOOL_BLOCK_RE`
required `\s*\n`, so the agent logged `0 tool blocks` and lost the call to one
missing character.

The newline is not decoration: it stops ```` ```bash_something ```` matching the
tag `bash`. It is kept, with one alternative added — a zero-width lookahead at
`{` or `[`, neither of which can continue an identifier. Regression-tested
across 8 cases including that guard.

## Verified after restart

| | Before | After |
|---|---|---|
| Served context | 4096 | 8192 at 100% offload |
| Odysseus's assumed window | 131072 | 8192 (`Local endpoint serves 8192; capping qwen3.5:9b from 131072`) |
| Reported context use | `context_percent: 2.1` (actually 67%) | 37.9%, honest |
| Agent turn | intermittent empty / truncated | 5 of 5 clean: 0 empty, 0 truncated |
| Email tool dispatch | — | `Tool executed: mcp: mcp__email__list_email_accounts -> exit_code=0`, all four accounts returned |

One verified turn used **5855 input tokens** — it would have overflowed the old
4096 window outright.

## Open

- Acceptance asked for 20 consecutive clean turns; **5 were run**. The sample
  supports the fix but does not meet the bar.
- `_parse_ollama_response` (native `/api/chat`) still reads only
  `message["content"]` and would drop a `thinking` field the same way. This
  deployment talks to `/v1`, so it is unreached here — left alone deliberately.
- `qwen3.6:35b-a3b` remains at 24% offload. `qwen3.5:9b` fits at 100% and
  formats tool calls correctly; which model to standardise on is undecided.
- `OLLAMA_KEEP_ALIVE=0` still costs 4-6s per call; the mode-conditional
  keep-alive is unbuilt.
- The iGPU-on-model-load trigger is unbuilt, and the phone-side button would
  reverse Rev E's read-only status service.
- Five local patches now; all conflict on a future upstream rebase.

---

# Rev I (2026-08-29) — Cloud models, hidden models, markdown tables, keep-alive

## Ollama Cloud works here, and needs no API key

`ollama signin` was already done. `~/.ollama` holds an ed25519 keypair, not a
bearer token — the machine signs its own requests. `config.json` holds no
credential. Cloud models are reached through the ORDINARY local endpoint
(`http://100.82.8.53:11434/v1`), so Odysseus needs no new endpoint row.

Measured against the live endpoint:

| model | latency | fenced tool block | notes |
|---|---|---|---|
| `gemma4:31b-cloud` | **0.5 s** | correct, **0 reasoning tokens** | 262K context, tools + thinking + vision |
| `gpt-oss:120b-cloud` | 1.5 s | correct | 307 chars reasoning; **hallucinated fake accounts** after the block |
| `gpt-oss:20b-cloud` | resolves | — | 131K context |
| `qwen3.5:397b-cloud` | **HTTP 402** | — | needs a paid subscription |
| `qwen3-coder:480b`, `deepseek-v3.1:671b`, `kimi-k2:1t`, `glm-4.6`, `minimax-m2` | **retired** | — | June–July 2026 |

End to end through Odysseus, `gemma4:31b-cloud` answered in **3.84 s** against
15.9 s for local `qwen3.5:9b`.

**Free tier:** no published numbers. "Light usage", session limits resetting
every 5 hours and weekly limits every 7 days. Pro is $20/mo for "50x more". The
402 proves tier gating is real despite the docs claiming all cloud models are
available on all plans.

A separate "Ollama Cloud" endpoint row (`https://ollama.com/api`) failed with
Unauthorized. Probed without a key: `https://ollama.com/v1/models` → 200,
`https://ollama.com/api/chat/completions` → **404**. The OpenAI-compat base is
`/v1`; `/api` is the native path. That row is redundant while the laptop is up —
its only value is reaching cloud models with the laptop off.

## Six LOCAL models were hidden; the cloud model was not

`/api/models` showed 3 of 9. Not a cloud problem — the inverse:

    cached_models  9 entries, including gemma4:31b-cloud
    hidden_models  qwen3.6:35b-a3b, gpt-oss:20b, mistral-nemo:12b,
                   qwen3-vl:8b, qwen3.5:9b, qwen2.5-coder:7b

`hidden_models` is written **only** by `GET /api/model-endpoints/{id}/probe`,
which sends a real "Say OK" completion per model with an **8-second timeout**
(`model_routes.py:597`). `/api/models?refresh=true` updates `cached_models` and
never clears `hidden_models`, so one transient failure hides a model until
someone re-probes.

Every hidden model passed the same probe when re-measured cold:

| model | state | size | cold load |
|---|---|---|---|
| qwen3.5:4b | visible | 3.39 GB | 4.88 s |
| qwen3:8b | visible | 5.23 GB | 3.61 s |
| qwen2.5-coder:7b | hidden | 4.68 GB | 3.73 s |
| qwen3-vl:8b | hidden | 6.14 GB | **7.50 s** |
| qwen3.5:9b | hidden | 6.59 GB | 5.31 s |
| mistral-nemo:12b | hidden | 7.07 GB | 6.41 s |

So the list was a stale snapshot of one bad run — most plausibly during this
day's Ollama outages (the laptop reset and two proxy restarts, all
self-inflicted). `OLLAMA_KEEP_ALIVE=0` guaranteed every probe was a cold load,
and `qwen3-vl:8b` sat 0.5 s from the limit.

## KEEP_ALIVE is no longer 0

Set to **10m**, owned by `setup_ollama_host.ps1`. Verified: a model stays
resident with an `expires_at` stamp instead of unloading instantly.

This knowingly retires Rev E's guarantee that an idle server holds no VRAM. The
trade: at 0, every request paid a 4-6 s cold load and the 8 s probe timed out
often enough to hide six models. Reclaiming VRAM before gaming is now a
deliberate act — `ai_mode.ps1 gaming`, or `-KeepAlive 0`.

## Markdown tables did not render — three defects, one symptom

Odysseus renders markdown with a hand-rolled renderer (`static/js/markdown.js`),
not marked or markdown-it; `document.js` imports the same module, so chat and the
document viewer share every defect. Diagnosed by reproducing the renderer in
Node, then confirmed against the live page.

**The reported symptom was none of the obvious candidates.** `mdToHtml` measured
in the browser:

    | id | subject |                        -> 1 <table>
    | id | subject | open |  (link in cell) -> 0 <table>, 3 <p>

`markdown.js:576` replaces every `<a>` with an `___ALLOWED_HTML_n___` placeholder
BEFORE the table rule, which then bailed on any placeholder. Every row of an
inbox table carries an `[Open Email](...)` link, so every such table rendered as
plain pipe text.

| Patcher | Target | Defect fixed |
|---|---|---|
| `odysseus_table_leading_newline.py` | `markdown.js` | The rule's leading boundary group consumed the newline before a table and never restored it, welding `## Results` to the table and stopping it being a heading |
| `odysseus_table_inline_placeholder_guard.py` | `markdown.js` | Guard narrowed to `___CODE_BLOCK_` only — an inline `<a>` placeholder no longer kills the whole table |
| `odysseus_table_escaped_pipe.py` | `markdown/tableRow.js` | `splitTableRow` split on every pipe, so GFM's escaped pipe opened a phantom column |

Verified live in the user's session: the message went from 0 tables to a
**101-row, 5-column table**, and after the escaped-pipe fix **every row had
exactly 5 cells** (`rowsNotFiveCells: 0`). An email subject containing an escaped
pipe now renders intact in one cell.

**Static assets are served without cache-busting.** Two normal reloads served a
stale module and nearly produced a false "the fix does not work" report;
`Ctrl+Shift+R` was required.

Not fixed, same function: a separator row anywhere but line 2 renders as literal
dashes; `</tbody>` can close without an opening `<tbody>` (browser-repaired).

## Cloud models must be exempt from the local context ceiling

`ODYSSEUS_LOCAL_SERVED_CONTEXT` (Rev H) caps any endpoint `is_local_endpoint()`
calls local. Cloud models are reached through that same local URL, so the cap
clamped `gemma4:31b-cloud` from 262144 to 8192. `odysseus_local_served_context.py`
now exempts models whose tag is `cloud` or ends `-cloud`; the patch was reverted
from backup and re-applied rather than layered.

Odysseus also validated new sessions against a **stale** model list and rejected
`gemma4:31b-cloud` until `GET /api/models?refresh=true`.

## Built

| File | Runs on | Purpose |
|---|---|---|
| `throttle_proxy.py` | laptop | CONNECT proxy pacing Ollama's downloads; rate changed live via `throttle_rate.txt` without dropping tunnels |
| `benchmark_agent_models.py` | laptop | Ranks models on A1 capability / A2 tool format / A3 real Odysseus agent turns / A5 context headroom |

Ollama has no download rate limit (`pull` takes only `--insecure`;
`OLLAMA_MAX_TRANSFER_STREAMS` is a stream count), and Windows QoS throttles
egress only and needs elevation. **The pull runs in the SERVER, not the CLI**, so
the proxy variables must be set on the process running `ollama serve` — at
process scope only, never persisted.

Two self-inflicted failures while building it, both costing download progress:

- Restarting the server to attach the proxy discarded 2.3 GB.
- `RELAY_TIMEOUT` applied to both directions; the idle client-to-upstream
  direction hit its 5-minute timeout and `relay` shut down BOTH sockets, killing
  the live transfer. Ollama reported `max retries exceeded: unexpected EOF` at
  4.5 GB. A read timeout is now a poll interval, not a deadline. After the fix
  the pull resumed at 4.6 GB rather than restarting — so the earlier resets were
  this bug, not Ollama's downloader.

`benchmark_agent_models.py` reaches Odysseus directly across the tailnet (40 ms),
no SSH hop. Two defects caught by its own smoke test before any real run: the
truncation heuristic flagged a completed list item as truncated because it ends
on a letter, and offload % read empty because `KEEP_ALIVE=0` unloaded the model
before `/api/ps` was queried.

## Model inventory

`gemma4:31b` pulled — 19 GB, digest verified. Dense, **60 layers**, 30.7B params.
`gemma4:26b` is **MoE: 25.2B total, 3.8B active** — the same architecture class as
`qwen3.6:35b-a3b`, and 16 GB rather than 19 GB.

The Unsloth `UD-Q4_K_XL` build exists (18.8 GB) but is not meaningfully smaller
than Ollama's 19 GB. No q6_K tag exists for gemma4:31b, and building one needs
~62 GB of full-precision weights. llama.cpp is not installed.

## Decisions taken

- `OLLAMA_KEEP_ALIVE` = **10m**.
- Un-hide models via **F1** (re-probe), not a direct PATCH.
- Benchmark **N = 5** turns per model.
- Pull `gemma4:26b`.

## Patch inventory — verified present 2026-08-29

Every marker below was grepped live in the guest tree. Each patcher is
marker-delimited, takes a timestamped backup, and refuses to run twice; revert
from the `.bak-*` copy rather than re-running.

| # | Patcher | Target file | Marker | Rev |
|---|---|---|---|---|
| 1 | `odysseus_email_list_pool.py` | `routes/email_routes.py` | `odysseus-list-pool` | G |
| 2 | `odysseus_keepalive_endpoints.py` | `app.py` | `odysseus-keepalive-endpoints` | G |
| 3 | `odysseus_email_tool_dispatch.py` | `src/tool_execution.py` | `odysseus-email-tool-dispatch` | G |
| 4 | `odysseus_local_served_context.py` | `src/model_context.py` | `odysseus-local-served-context` | H, amended I |
| 5 | `odysseus_nonstreaming_call_path.py` | `src/llm_core.py` | `odysseus-nonstreaming-call-path` | H |
| 6 | `odysseus_tool_fence_inline_json.py` | `src/tool_parsing.py` | `odysseus-tool-fence-inline-json` | H |
| 7 | `odysseus_table_leading_newline.py` | `static/js/markdown.js` | `odysseus-table-leading-newline` | I |
| 8 | `odysseus_table_inline_placeholder_guard.py` | `static/js/markdown.js` | `odysseus-table-inline-placeholder-guard` | I |
| 9 | `odysseus_table_escaped_pipe.py` | `static/js/markdown/tableRow.js` | `odysseus-table-escaped-pipe` | I |

Nine patches across seven files; `markdown.js` carries two. Patch 8 refuses to
apply unless patch 7 is present — it builds on the `match` binding patch 7
introduces.

Laptop-side configuration is not patched but is owned by
`setup_ollama_host.ps1`: `OLLAMA_HOST`, `OLLAMA_KEEP_ALIVE` (10m),
`OLLAMA_MODELS`, `OLLAMA_CONTEXT_LENGTH` (8192).

Phone-side configuration lives in Odysseus's `.env`:
`ODYSSEUS_LOCAL_SERVED_CONTEXT=8192`, which must be kept equal to
`OLLAMA_CONTEXT_LENGTH` by hand.

The checkout is `ed18192` on `dev`, ~2 months behind upstream. Every patch above
conflicts on a rebase.

## Open

- Benchmark not yet run: it waits on the `gemma4:26b` pull, the throttle
  teardown, and the F1 re-probe, in that order.
- A4 (answer quality on real email triage) needs a human judge and is unbuilt.
- Throttle proxy still in the path of all Ollama traffic, including cloud
  inference.
- The iGPU-on-model-load trigger is unbuilt. `ai_mode.ps1` already writes
  `GpuPreference=1` for three executables, but Windows binds a process to a GPU
  at creation, so a running app cannot be moved — only closed.
- **Nine local patches now** across seven files; all conflict on a future
  upstream rebase.

---

# Rev J (2026-08-29) — Model benchmark, N=5

Ranked by `benchmark_agent_models.py`: A1 capability, A2 tool-call format, A3
real Odysseus agent turns, A5 context headroom. Served window 8192,
`OLLAMA_KEEP_ALIVE=10m`, one model resident at a time.

| model | cold | warm tok/s | offload | A2 | clean/empty/trunc | peak ctx | median turn |
|---|---|---|---|---|---|---|---|
| `gemma4:31b-cloud` | 1.2 s RTT | n/a remote | n/a | pass | **5 / 0 / 0** | **8.4%** | **10.9 s** |
| `gemma4:26b` MoE | 36.3 s | 35.6 | ~5% | pass | 4 / 0 / 1 | 50.0% | 166.7 s |
| `qwen3.5:9b` | 4.4 s | **61.9** | **100%** | **FAIL** | 1 / 0 / 4 | 98.0% | 4.9 s |
| `qwen3.6:35b-a3b` | 36.7 s | 31.7 | 24% | pass | **0 / 0 / 5** | 98.0% | 9.8 s |
| `gemma4:31b` dense | 60.1 s | **2.3** | ~5% | pass | 2 / 0 / 1 of 3 | — | ~1055 s |

`gemma4:31b` was abandoned after 3 turns: 2.3 tok/s and ~20 minutes per turn is
conclusive. Offload for the two 18-19 GB models was measured by hand; the
harness's `/api/ps` lookup returned empty because the model had been evicted by
the time it queried.

## Findings

**Only the cloud model completes agent turns.** Every local model fails
somewhere: `qwen3.6:35b-a3b` — the configured default — went 0 of 5.

**Throughput predicts nothing.** `qwen3.5:9b` is the fastest local decoder
(61.9 tok/s) and the only model that fits entirely in VRAM (100% offload), and
it scored 1 of 5 while failing the tool-format test outright, refusing with
"I don't have access to your personal information". Ranking on tok/s would have
selected the worst agent in the set. This is the second time this project has
been misled by speed: `qwen3.5:4b` is faster still and cannot format a tool call
at all.

**Dense vs MoE, same size class:** 2.3 tok/s (`gemma4:31b`, dense 30.7B) against
35.6 tok/s (`gemma4:26b`, 25.2B total / 3.8B active). A 15x gap. The MoE
hypothesis was correct about decoding speed.

**`gemma4:26b`'s 167 s median is verbosity, not slowness.** At 35.6 tok/s it
decodes fine; its turns ran 6,000-15,600 characters, and one hit 50% of the
window and truncated.

**Both qwen models peaked at exactly 98.0% context** — 8,028 of 8,192 tokens —
on prompts where `gemma4:26b` peaked at 50% and the cloud model at 8.4%. They
fill the window and stop. The 8192 setting was chosen by measuring offload and
throughput (Rev H) and is ample for the gemma models; whether it starves the
qwen family is untested. 16384 costs 86% offload / 38.5 tok/s.

## Method notes

Two harness defects were caught by its own smoke test before the run: a
truncation heuristic that flagged a completed list item as truncated because it
ends on a letter, and an offload reading that came back empty because
`KEEP_ALIVE=0` unloaded the model before `/api/ps` was queried.

One defect was caught by a machine restart mid-run: results were written only at
the end, so the restart destroyed `benchmark_results.json` for four completed
models. The log survived and the data was recovered from it. The harness now
writes after every model.

Still defective: `laptop_state()` records `OLLAMA_KEEP_ALIVE` from the
benchmark's own process rather than the server's setting, so the first run's
header claimed 0 when the server was at 10m.

## The probe cannot pass a large model

`GET /api/model-endpoints/{id}/probe` (F1) was run to clear `hidden_models` and
made it worse — 7 of 11 models timed out and were hidden, including both gemma4
models and `qwen3.5:9b`, which had loaded in 5.31 s when measured alone.

The probe sends a real completion with an **8-second timeout**. `gemma4:31b`
takes 60 s to load. No keep-alive setting changes this: every model still pays
its first load, and with 10m retention each probed model then lingers, competing
for 8 GB of VRAM. F1 is structurally incapable of passing a large model on this
hardware.

Cleared instead with F2 — `PATCH /api/model-endpoints/182e58cc/models`
`{"hidden": []}` — which restored all 11.

## Open

- `qwen3.6:35b-a3b` remains the configured default and scored 0 of 5. No
  replacement has been chosen.
- Whether 16384 rescues the qwen models is untested.
- A4 (whether an answer is *correct*, not merely complete) is unbuilt and needs
  a human judge.
- The cloud path sends email content to Ollama's servers and is bounded by an
  unpublished free-tier cap.

---

# Rev K (2026-08-29) — AI mode widened, and a second GPU host planned

## `ai_mode_config.json` now closes Brave and Edge WebView

Both were `enabled: false` by design — the "ram" category held the user's
working apps and AI mode left them alone. Both were switched to `enabled: true`
on request, to free RAM before the benchmark.

Enabled candidates are now:

| app | category |
|---|---|
| Epic Games Launcher | gpu |
| Epic EOS Overlay | gpu |
| Lenovo Vantage | gpu |
| Overwolf | gpu |
| Overwolf Browser | gpu |
| **Brave** | **ram** |
| **Edge WebView** | **ram** |

This is persistent: every future `ai_mode.ps1 ai` closes them, not just the run
it was requested for.

Measured effect across both AI-mode runs:

| | RAM free | VRAM free |
|---|---|---|
| before | 12.9 GB | 7300 MiB |
| after Epic/Overwolf (601 MB of candidates) | 13.4 GB | 7421 MiB |
| after Brave + Edge WebView (52 processes) | **15.2 GB** | 7412 MiB |

VRAM needed no reclaiming at any point — Hybrid mode keeps the desktop on the
iGPU and nothing was rendering on the dGPU.

**Chrome closed at the same time and was not requested.** It was not in the
candidate list and `ai_mode.ps1` matches by process name, so it was not closed
directly; the cause was not established. The Claude browser extension lost its
connection with it, which is how the closure was noticed. Anything relying on
Edge WebView respawns its own copy on next use.

## Second GPU host — prepared, not executed

A second laptop with an RTX 3060 is to be added. Its VRAM was never confirmed,
which blocks the decision: a laptop 3060 is typically 6 GB, less than this
machine's 8 GB 3070, and would add parallelism but no new capability.

Established while preparing:

- **Two GPUs in two machines cannot pool VRAM for one model.** USB-C provides a
  network link, not a GPU interconnect, and Ollama does not shard a model across
  hosts. A second host runs a *second* model; it does not make a large one fit.
- **The USB-C cable is unnecessary.** Tailscale already carries this traffic for
  the phone (seam S3), needs no cable, and inference payloads are small — compute
  is the scarce resource, not bandwidth.
- **`setup_ollama_host.ps1` is portable.** Its only machine-specific value is
  `$ModelStore`, a parameter; the sole hardcoded literal is the `100.*` filter
  used to discover the Tailscale address. Running it on the second host
  reproduces this one's configuration exactly.

Steps handed over: confirm VRAM with `nvidia-smi`, `winget install` Ollama and
Tailscale, `tailscale up`, then `setup_ollama_host.ps1 -ModelStore <path>`. The
host then becomes a second `model_endpoints` row (seam S1) once its tailnet
address is known.

## State at close

| | |
|---|---|
| Ollama | running, 11 models, `KEEP_ALIVE=10m`, `CONTEXT_LENGTH=8192` |
| Throttle proxy | stopped; Ollama restarted without proxy variables |
| Odysseus | running, 11 models visible, `hidden_models` cleared |
| AI mode | active; 6 apps recorded for restore |
| Local patches | 9 across 7 files, all markers verified present |

## Open

- The configured default model, `qwen3.6:35b-a3b`, scored 0 of 5 in Rev J and
  has not been replaced.
- Whether `ai_mode_config.json` should keep Brave and Edge WebView enabled, given
  the unexplained Chrome closure.
- The second host's VRAM, which decides whether it is worth configuring.
- A4 — whether a model's answers are *correct* — remains unbuilt and needs a
  human judge.

---

# Rev L (2026-08-29) — Correction: VRAM *can* be pooled across the two laptops

## The Rev K claim was wrong

Rev K states that "two GPUs in two machines cannot pool VRAM for one model" and
that "Ollama does not shard a model across hosts." The second half is correct.
**The first half is not.**

llama.cpp ships an RPC backend — `ggml-rpc-server.exe` — that shards one model
across hosts and pools their VRAM. A working setup is documented in
`D:\AI_Projects_2026\AIconnection\DISTRIBUTED_SETUP_GUIDE.md`:

| | |
|---|---|
| Host / master | RTX 3070, 8 GB — `100.82.8.53` |
| Worker / RPC node | RTX 3050, 4 GB — `100.112.156.50` |
| Pooled VRAM | **12 GB** |
| Tensor split | `-ts 2,1` |
| RPC port | 50052 |
| Transport | Tailscale mesh, ~3 ms |

The limitation that *is* real: USB-C between these two machines does not create
a networking bridge, because both are AMD Ryzen and Thunderbolt Networking is
not available without host-to-host bridge hardware. Tailscale was selected
instead and verified. Rev K reached the right conclusion about the cable for the
wrong reason.

Worker firewall fix recorded in the guide:
`New-NetFirewallRule -DisplayName "llama-rpc-50052" -Direction Inbound -LocalPort 50052 -Protocol TCP -Action Allow -Profile Any`

## Installed

`C:\llama.cpp\` on the host, Windows CUDA 12.4 prebuilt `b10687`:
`llama-server.exe`, `ggml-rpc-server.exe`, `ggml-cuda.dll`, plus the CUDA 12.4
runtime DLLs. Launcher `run_pooled_server.ps1` serves an OpenAI-compatible API
on `0.0.0.0:8080`, defaulting to `C:\models\qwen2.5-14b-instruct-q4_k_m.gguf`
with `-ngl 99 -sm layer -ts 2,1 -c 8192 -fa`.

This is the llama.cpp runtime Rev I recorded as "not installed". That is now out
of date for the host.

## What pooling does not change for the benchmarked models

Every model in the Rev J benchmark is larger than the pooled 12 GB:

| model | size | fits 12 GB pooled |
|---|---|---|
| `qwen3.6:35b-a3b` | 22 GB | no |
| `gemma4:31b` | 19 GB | no |
| `gemma4:26b` | 18 GB | no |
| `qwen3.5:9b` | 6.6 GB | yes — but it already fit 8 GB alone |

Pooling opens the 8–12 GB band, which is why the guide targets a 14B Q4. It does
not make the 18–22 GB models fit.

## Open

- A retest on the pooled endpoint is not a re-run of the existing harness:
  `benchmark_agent_models.py` measures A1 through Ollama-specific endpoints
  (`/api/ps`, `/api/generate`) that llama.cpp does not serve. A2 and A3 would
  work against `:8080/v1` unchanged.
- The benchmarked models live in Ollama's blob store, not as loose GGUF files;
  running them under llama.cpp requires extracting or re-downloading them.
- No model in the 8–12 GB band has been benchmarked. That is the band pooling
  actually unlocks.

---

# Rev M (2026-08-30) — Pooled inference measured; Ollama blobs vs upstream GGUF

## VRAM pooling works, and costs 10x throughput

`gemma4:26b` served across both laptops via llama.cpp RPC and generated tokens.
Measured against the same model on the single 3070 (Rev J):

| configuration | throughput |
|---|---|
| Ollama, single RTX 3070 | **35.6 tok/s** |
| Pooled 3070 + 3050 over RPC | **3.44 tok/s** |

The mechanism is sound — layers distributed, host VRAM reached 7465 MiB, worker
held its share, server answered. The model is 16.95 GB against 12 GB pooled, so
it still spilled to host RAM; pooling did not make it fit, it added a Tailscale
hop per token on top of spilling that was already happening.

Content came back **empty** on both generations despite 200 completion tokens —
the thinking-channel behaviour recorded in Rev H.

Pooling would pay in the 8-12 GB band, which nothing benchmarked occupies:
the models are 6.6 GB or 17-25 GB.

## Three defects in the distributed setup files

All three were in `D:\AI_Projects_2026\AIconnection\`, all now corrected.

**The tensor split ran backwards.** The guide documented `-ts 2,1` as
"2 parts on RTX 3070 : 1 part on RTX 3050". Under `--rpc`, device 0 is `RPC0`
(the worker) and device 1 is `CUDA0` (the host) — so it put **two-thirds of
every model on the 4 GB card**. Proven by arithmetic: `-ts 6,1` asked the worker
for 14.45 GB of a 16.95 GB model, exactly 6/7. Corrected to `-ts 1,6`, after
which the model loaded and served.

**`-fa` swallowed the next argument.** Build b10687 changed `-fa` to require a
value (`on|off|auto`), so bare `-fa` consumed `--host` and the server aborted:
`unknown value for --flash-attn: '--host'`. Corrected to `-fa on`.

**`-ngl 99` is not an rpc-server option** in this build — it is a llama-server
flag. The worker command now reads `-d CUDA0,CPU`, which also exposes the
worker's ~10 GB of free RAM so a KV-cache allocation has somewhere to land
instead of aborting.

The first failure was exactly that: the worker's 4 GB card accepted its layers
then could not fit a 679 MB KV buffer.

## Ollama blobs are not interchangeable with upstream GGUF

Two of the four local benchmark models will not load in llama.cpp at all:

| model | error |
|---|---|
| `gemma4:31b` | `done_getting_tensors: wrong number of tensors; expected 1189, got 833` |
| `qwen3.5:9b` | `qwen35.rope.dimension_sections has wrong array length; expected 4, got 3` |

Neither file is corrupt. Gemma 4 is multimodal and llama.cpp expects text plus
vision tower in one file; Ollama's `gemma4:31b` tag ships only the 833 text
tensors and **no projector layer at all**. Confirmed against the manifests:

| model | model blob | projector |
|---|---|---|
| `gemma4:26b` | 16.95 GB | 1.19 GB separate |
| `qwen3.6:35b-a3b` | 21.72 GB | 0.90 GB separate |
| `gemma4:31b` | 19.87 GB | **none** |
| `qwen3.5:9b` | 6.59 GB | none |

Matches ollama/ollama#16784. The fix is an upstream-packed GGUF, not a
different binary — `unsloth/gemma-4-31B-it-GGUF:UD-Q4_K_XL`, 18.8 GB,
downloading.

**Correction to an earlier claim in this session:** `qwen3.5:9b` was said to
need "a newer llama.cpp build". There isn't one — **b10687 is the latest
release** (2026-08-29) and is what is installed. It is the same GGUF-conversion
class of problem, not staleness.

Also noted: the installed build is CUDA **12.4** while driver 610.88 exposes
CUDA **13.3**, and b10687 ships a 13.3 variant. Downloaded, not yet installed,
to `C:\llama.cpp-cuda13\` rather than over the working 12.4 tree.

## Odysseus endpoint for the pooled server

Created via the API rather than `odysseus_endpoint.py`, which would also have
repointed the default model and required stopping the app.

| | |
|---|---|
| id | `4b4c381d` |
| name | Pooled 3070+3050 (llama.cpp RPC) |
| base_url | `http://100.82.8.53:8080/v1` |
| supports_tools | **false**, deliberately |

`supports_tools=false` forces the fenced-block path. Port 8080 is not recognised
as Ollama-compat, so llama.cpp would otherwise receive native tool schemas while
every Rev J measurement used fenced blocks — the comparison would not hold.

## Six candidate models fetched

Chosen for the 12 GB VRAM / 28 GB RAM envelope. Five present, one pulling:

| model | size | architecture | state |
|---|---|---|---|
| `granite4.2:3b` | 2.2 GB | dense | present |
| `granite4.2:8b` | 5.3 GB | dense, **switchable thinking** | present |
| `gemma4:12b` | 7.6 GB | dense, 256K ctx | present |
| `muse-glimmer:30b` | 18 GB | dense | present |
| `granite4.2:30b` | 17 GB | dense | present |
| `nemotron-3.5-lightning:30b` | 25 GB | **MoE, 3B active**, 1M ctx | pulling |

`granite4.2:8b` and `gemma4:12b` fit the 3070 alone, avoiding the 10x pooling
penalty entirely. `granite4.2`'s `enable_thinking` / `reasoning_effort` controls
target the Rev J failure where both qwen models filled 98.0% of the window
reasoning and truncated every turn.

None has been benchmarked yet.

## Built

| File | Purpose |
|---|---|
| `fetch_benchmark_models.ps1` | Fetches every model and loose file unattended, retrying and resuming |
| `watch_fetch_progress.ps1` | Read-only live progress window |

The fetch script runs as Windows Scheduled Task `FetchBenchmarkModels`, so it
survives the session that started it — four agent background tasks were killed
mid-download earlier, losing both pull queues. It suppresses sleep for its own
lifetime via `SetThreadExecutionState`, since a sleeping laptop stops every
transfer.

Two defects found in it during the night:

- **curl ran with `-s`**, so a stalled connection burned all four retries while
  moving zero bytes and logging nothing. Now runs without `-s` and aborts a
  connection below 5 KB/s for 60s so the retry can start a fresh one.
- **`ollama pull` had no timeout.** `granite4.2:30b` sat 60 minutes producing
  nothing while the retry loop could not fire, because the call never returned.
  Pulls are now bounded at 45 minutes, killed and retried.

## Two recurrences of already-recorded traps

**The tray app hijacked Ollama again** (Rev F). `ollama app.exe` was serving on
11434 with the default empty store at `C:\Users\hmoha\.ollama\models` while
107 GB of blobs sat on D:. `ollama list` returned empty and every pull failed
silently for roughly an hour. Fixed by killing both processes and restarting
through `setup_ollama_host.ps1`.

**Store size was used as evidence about pull state** — three times in one
session, against Rev F's explicit warning. Ollama **preallocates** a blob at
full size and writes into it, so length never changes while content fills.
`granite4.2:30b` was reported as failed on this basis; it had completed. The
reliable local signal is the partial blob's **mtime**, which is what
`watch_fetch_progress.ps1` displays.

## Open

- No new model has been benchmarked. `granite4.2:8b` is the cheapest test and
  fits the 3070 alone.
- `nemotron-3.5-lightning:30b` (25 GB) still pulling; it is the only MoE of the
  three 30B candidates.
- The Unsloth GGUF (12.81 / 17.53 GB) and CUDA 13.3 runtime (0.11 / 0.36 GB)
  are queued behind the models; the hardened curl path has not been exercised.
- CUDA 13.3 downloaded but not installed and not A/B tested.
- `qwen3.5:9b` has no upstream GGUF fetched; it scored 1 of 5 in Rev J.
- Agent turns (A3) have never been run against the pooled endpoint `4b4c381d`.
- `benchmark_agent_models.py` measures A1 through Ollama-only endpoints and
  cannot measure llama.cpp without rework.

---

# Rev N (2026-08-30) — Every disk-side download signal is wrong; the server's stream is not

## Rev M's "reliable local signal" is wrong, and it cost a healthy download

Rev M says the partial blob's **mtime** is the reliable indicator that a pull is
alive. It is not. Four signals were measured against `nemotron-3.5-lightning:30b`
while it was demonstrably downloading at ~4.5 MB/s:

| signal | reading | why it lies |
|---|---|---|
| blob size | 23.68 GB, constant | preallocated at full length before a byte arrives (Rev F) |
| blob mtime | frozen 22 min | writes land at offsets inside the preallocated file; NTFS defers the directory-entry timestamp |
| chunk ledger `Completed` | **0 for 33 min** | flushed on process **exit**, not while running — a resume checkpoint, not a counter |
| NTFS valid data length | 22.0 GB when 11.3 GB had arrived | 26 chunks write in parallel at spread offsets, so it is a high-water mark |

Acting on the chunk ledger, this session declared the pull STALLED and killed it.
It had 8.97 GB down. **The diagnosis was wrong; the download was healthy the whole
time.** Nothing was lost — Ollama resumed from the checkpoint — but a stall
detector built on that signal would kill every long pull it supervised.

The one contrary reading that was correct got dismissed: aggregate NIC receive
showed a steady 5.02 MB/s, which matched 8.97 GB over 33 minutes exactly. It was
attributed to other processes because per-process `IO Read Bytes/sec` showed
5 KB/s — socket traffic does not land in that counter.

## What actually works: `POST /api/pull` dedupes

Issuing `POST /api/pull {"model":X,"stream":true}` for a model **already being
pulled** attaches to that same download and streams its exact figures:

    {"status":"pulling 5c19f6282f4f","total":25430738944,"completed":11327967616}

Verified: bandwidth did not double, and detaching did not cancel the primary
pull. This is the only true live signal and is now the single source for both
the viewer and the supervisor.

## Three defects fixed in the fetch path

**The pull was orphaned and unkillable.** `Start-Process` detaches, so the
`ollama pull` outlived the script that started it. The task exited
`0xC000013A` (STATUS_CONTROL_C_EXIT) seconds after launching at 11:34, leaving a
pull with no parent — so the 45-minute bound could never fire against it. It
would have hung forever. `Get-OrphanedPulls` now reaps parentless pulls at
startup; only parentless ones, so a supervised pull is never touched.

**The 45-minute bound could not tell slow from dead.** Replaced with a byte-based
supervisor polling the server stream every 15 s, killing after
`$PullStallSeconds` (300) of a frozen count. Non-byte phases — manifest
resolution, digest verification — reset the clock rather than counting as stall.

**The log went silent for an hour.** A progress line is now written every 5 min.

**The task did not survive its session, which is the one thing it exists for.**
`Set-ScheduledTask -Principal` to S4U needs elevation and was denied. Instead the
trigger now repeats every 15 minutes for 2 days; `MultipleInstances=IgnoreNew`
means a repeat fires only when no instance is running, so a killed run
self-heals and the script's "safe to re-run" invariant does the rest.

## Built

| File | Purpose |
|---|---|
| `ollama_pull_progress.ps1` | `Get-OllamaPullState` (server stream), `Get-RunningPullModel`, `Get-OrphanedPulls`, formatters |
| `watch_fetch_progress.ps1` | rewritten: real progress bar, speed, ETA, STALLED and ORPHANED states |
| `fetch_benchmark_models.ps1` | orphan reaper, byte-based stall abort, periodic progress logging |

`Get-OllamaPullState` must only be called when a pull is already in flight —
calling it with none running would **start** one. `Get-RunningPullModel` is the
guard, and both the viewer and the supervisor use it.

## A third recurrence of the self-match trap

`Where-Object { $_.CommandLine -match 'fetch_benchmark' }` matched the very shell
running the query, and `Stop-Process` on the result killed this session's own
PowerShell — the same hazard recorded against `pgrep -f` in the Odysseus build
log. Fixed by excluding `$PID` and matching the exact `-File <path>` form.

## State at close

`nemotron-3.5-lightning:30b` resumed at 11.68 GB and passed 52.5% at 5.3 MB/s,
ETA ~36 min, supervised, zero orphans. Five of six models present.

## Open

- Still no model benchmarked. `granite4.2:8b` remains the cheapest first test.
- The two loose files (Unsloth GGUF, CUDA 13.3 runtime) are queued behind
  nemotron; the hardened curl path is still unexercised.
- Why the 11:34 task run took `0xC000013A` was never established. The repeating
  trigger makes it survivable, not diagnosed.

---

# Rev O (2026-08-30) — Downloads complete; benchmark preflight is now a script

## All six candidate models present, both loose files complete

    granite4.2:3b  granite4.2:8b  gemma4:12b
    muse-glimmer:30b  granite4.2:30b  nemotron-3.5-lightning:30b
    gemma-4-31B-it-UD-Q4_K_XL.gguf   17.53 GB  complete
    cudart-llama-bin-win-cuda-13.3-x64.zip  390,970,417 bytes  complete

`nemotron-3.5-lightning:30b` finished at 13:37 after resuming from 11.68 GB.

## The cudart zip was logged INCOMPLETE forever, and the file was fine

`$Files[].Size` held `391004000` against a true `390970417` — 33,583 bytes high,
an unverified literal used as a completeness predicate. The zip opened cleanly
with all three DLLs. Contract blame: the postcondition tested against a wrong
expectation, not a wrong file.

Fixed by `Get-ExpectedSize`, which takes Content-Length from a HEAD request and
falls back to the literal only when offline. The size now comes from the
authority that owns it. A mismatch is logged as a `SIZE` line rather than
silently adopted.

## The fetch task is disabled again

The 15-minute repeating trigger existed to heal an interrupted download. The
queue is complete, so it now only writes noise. Task disabled; re-enable with
`Enable-ScheduledTask -TaskName FetchBenchmarkModels` if a model goes missing.

## Two outages found while checking benchmark preconditions

**Tailscale was still starting**, so the phone read as unreachable on port 7000
while ICMP replied. It came up on its own; no action was needed, but the
transient reads exactly like Odysseus being down.

**Ollama had stopped serving entirely** — no process, nothing on 11434, after
running since 07:26. Restarted through `setup_ollama_host.ps1 -SkipFirewall`,
which is check-then-act and reported every setting already correct. Cause not
established. Note the ambient email tasks on the phone generate against this
endpoint, so they were failing for the duration.

## Built: `benchmark_preflight.ps1`

One read-only command that checks every clause of the harness's declared
precondition plus the environment facts that silently change results. Exit 0
only when nothing FAILs; every FAIL names its own fix.

Measured 13:51 — 13 of 14 PASS:

| clause | verdict |
|---|---|
| ollama `/api/ps` | PASS |
| `OLLAMA_CONTEXT_LENGTH` 8192, `KEEP_ALIVE` 10m, `MODELS` D: | PASS |
| no pull running, no model resident | PASS |
| GPU free 7875 of 8192 MiB | PASS |
| `granite4.2:3b`, `granite4.2:8b`, `gemma4:12b` installed | PASS |
| tailscale sees `galaxy-s24-ultra` | PASS |
| odysseus port 7000 | PASS |
| endpoint reachable by tailnet IP | PASS |
| **odysseus session cookie** | **FAIL — absent** |

The cookie is the only blocker and only a human can supply it: devtools on a
logged-in Odysseus tab, Application > Cookies > `odysseus_session`.

## Runbook — from a cold session to a benchmark run

    # 1. preconditions; fixes are named in the output
    powershell -File D:\ai_projects_2026\TermuxSamsung\benchmark_preflight.ps1 -Cookie <cookie>

    # 2. if ollama is down
    powershell -File D:\ai_projects_2026\TermuxSamsung\setup_ollama_host.ps1 -SkipFirewall

    # 3. if a model is missing
    Enable-ScheduledTask -TaskName FetchBenchmarkModels
    Start-ScheduledTask  -TaskName FetchBenchmarkModels
    powershell -File D:\ai_projects_2026\TermuxSamsung\watch_fetch_progress.ps1

    # 4. round one: the three models that fit the 3070 alone
    py benchmark_agent_models.py --cookie <cookie> --turns 5 ^
       --models granite4.2:3b,granite4.2:8b,gemma4:12b ^
       --out benchmark_results_round1.json

## The worker laptop stays off for round one

Asked whether to start the llama.cpp RPC server on the worker. No, and none of
the four reasons depends on the open scope questions:

1. `granite4.2:3b` (2.2 GB), `granite4.2:8b` (5.3 GB) and `gemma4:12b` (7.6 GB)
   all fit the 3070's 8 GB alone.
2. **A1 cannot be measured against llama.cpp.** `measure_capability` uses
   `/api/generate` with `keep_alive` and reads offload from `/api/ps` — both
   Ollama-native. A2 and A3 could reach port 8080 by flag; A1 cannot.
3. Rev M measured pooling at 35.6 -> 3.44 tok/s, and it did not make a 17 GB
   model fit 12 GB pooled VRAM.
4. The worker only matters for the three 30B models, whose scope is still open.

## Open

- **Session cookie** — the one blocking precondition.
- **Which workload decides.** A3 runs agent turns, but the ambient lane that
  actually ships (`summarize_emails`, `check_email_urgency`,
  `draft_email_replies`) are `task_type=action` built-ins that never traverse
  the agent loop. The deciding metric may no longer match production.
- **Whether the three 30B models are in scope at all**, given Rev M's own
  finding that pooling does not pay in the 17-25 GB band.
- **Served window held at 8192.** Three candidates were picked partly for
  context behaviour (`granite4.2` switchable thinking, `gemma4:12b` 256K,
  nemotron 1M); holding it fixed will not exercise that.
- Why Ollama stopped serving, and why the 11:34 fetch run took `0xC000013A`.

---

# Rev P (2026-08-30) — Round one, A1 + A2 measured

## The cookie precondition was stricter than the work

`main()` exited without a session cookie even for `--skip-agent`, which talks
only to Ollama — and `visible_models()` already returns None when Odysseus
cannot be reached. Blame: an over-strict precondition, which blocked every local
measurement whenever nobody was logged in. Now the cookie is required only when
agent turns will actually run.

## Results, served window 8192, KEEP_ALIVE 10m, one model resident at a time

| model | cold | warm tok/s | offload | A2 fenced | A2 newline |
|---|---|---|---|---|---|
| `granite4.2:3b` | 2.04 s | **126.2** | **100%** | **FAIL** | FAIL |
| `granite4.2:8b` | 3.11 s | 49.1 | 92% | pass | pass |
| `gemma4:12b` | 8.71 s | 13.8 | 69% | pass | pass |

`granite4.2:8b` beats the configured default `qwen3.6:35b-a3b` (Rev J: 31.7 tok/s,
24% offload) on both A1 axes while passing A2.

## Throughput misled for the third time

`granite4.2:3b` is the fastest decoder measured on this hardware — 126.2 tok/s at
100% offload — and it **refused the tool-format probe outright**:

    I don't have a record of any email accounts you've stored in

That is the same failure `qwen3.5:9b` produced in Rev J, and `qwen3.5:4b` before
it. Ranking on tok/s would have picked the worst agent in the set a third time.

## `gemma4:12b` does not fit the 3070

69% offload at 7.6 GB against 8192 MiB with an 8192 window — it spills, and
13.8 tok/s is the cost. It was chosen as a model that fits the card alone; it
does not.

## Open

- **A3 and A5 are unmeasured** — they need the Odysseus session cookie, which
  only a human can supply. A3 is the deciding metric; nothing here selects a
  model on its own.
- Whether `gemma4:12b` becomes resident at a smaller window is untested.
- The three 30B models remain unmeasured and out of round one.

**Round one is written up in `research/benchmark/ROUND1.md`** — steps, results, the blocked A3 step, and the three conditions that must hold before the worker laptop is started.

# Rev Q (2026-08-30) — HANDOFF.md pushed for phone-side agent

## Behavioral re-verification pass, read-only

A Claude Code session re-checked every Verified claim in Rev A–M against live
state: phone runtime, git, patch markers, ambient scheduling, the
`ToolRunSecurityContext` boundary, laptop config, and the ops-seam pricing
read path. Findings and the resulting open unknowns are recorded in
`HANDOFF.md`, not duplicated here.

## HANDOFF.md written and pushed

A self-contained handoff doc — condensed Rev A–M history, the findings above,
inherited guardrails, and 8 open unknowns — was written to the repo root and
pushed:

    origin  https://github.com/RybzXx/odysseus.git
    branch  daily-driver
    commit  c82226d..4e59927

Target reader: a separate CLI coding agent operating directly on the
phone-side checkout, not this laptop session.

## Sync mechanism decided: git primary, SSH-copy fallback

Candidates considered: git sync, a direct SSH-copy script, a Syncthing
daemon, routing through the existing Google Workspace ops-seam channel, and
an SSHFS remote mount. Git was chosen — reuses the existing `origin` remote,
handles conflicts via merge, and leaves a commit history; the Google-channel
option was rejected outright for conflicting with the no-Google-writes
guardrail. A direct SSH-copy fallback (reusing the `ssh_termux.py` /
`push_and_run.py` pattern already in this project) is the agreed backup for
when git isn't reachable, on condition that any fallback-delivered change is
committed back into git the next time that side has access.

## Live re-verification blocked this session

SSH (100.117.120.93:8022) refused on 3 attempts — another instance was using
it. The `adb` fallback reached the device but `Termux:RunCommandService`
enforces a `dangerous`-level Android permission
(`com.termux.permission.RUN_COMMAND`) that the `adb shell` / `com.android.shell`
identity cannot hold; `pm grant` returned success but the subsequent
`am startservice` call still threw the permission `SecurityException`. The
phone-side clone's `origin`/branch match to `RybzXx/odysseus` on
`daily-driver` was therefore not re-confirmed this session — carried into
`HANDOFF.md` as Unknown #8.

## Unknown #8 resolved — and the phone side had already acted

User confirmed both devices can push and pull `HANDOFF.md` through `origin`/`daily-driver`.
Pulling to reconcile a local edit surfaced two commits already pushed from the phone side (an
"Antigravity" session), ahead of the laptop's `4e59927`:

    0ab09e1  fix(tableRow): non-string input returns [""] not []
    cc50119  docs(HANDOFF): record first on-device pytest run + close Unknowns 1 & 8

First on-device pytest run: 3157 passed, 1 failed, 2 skipped, 128 warnings, 528s. The failure
(`test_non_string_row_falls_back_to_empty_cell`) was fixed in `static/js/markdown/tableRow.js` —
non-string input now early-returns `['']` instead of falling through to `[]`. Unknowns #1
(pytest suite runnable) and #8 (phone clone matches laptop's origin/branch) are closed in
`HANDOFF.md`. Local laptop clone fast-forwarded to `cc50119`.

---

# Rev Q (2026-08-30) — The supervisor was dead for 12 hours; context ceiling is now per-model

## The watchdog had no watchdog

`supervise_services.sh` logged its last line at **07:31:52** and was gone when
checked at ~22:45 — no `STORM:` line, no crash trace, nothing. It had not
stopped on purpose; it was killed. `boot.log` ends with
`Terminated nohup python src/flaresolverr.py`, so Android reaping is hitting
`nohup`'d background processes generally, not this one specifically.

**Everything it guards ran unsupervised for roughly twelve hours** — including
`uvicorn app:app`, and therefore Odysseus's in-process ambient task queue. The
whole of that day's benchmark work happened inside that window.

An earlier claim in this session that `sshd` was *unsupervised* was **wrong**:
`Start_All.sh` guards it at line 8, and the supervisor reads its patterns from
that file. `sshd` was supervised in principle; the supervisor was simply dead,
so nothing acted. That is why SSH stayed down until restarted by hand.

## Fix: a mutual watchdog chain, because neither scheduler survives alone

`termux-job-scheduler` was the obvious answer and **does not work here** — the
`termux-api` CLI package is installed but the Termux:API *Android app* is not,
so every invocation hangs and returns nothing (verified detached, 0 bytes after
25 s). Android's JobScheduler is therefore unavailable.

Installed `cronie` instead and wired two processes to keep each other alive:

| watcher | watches | how |
|---|---|---|
| `crond` (every 15 min) | `supervise_services.sh` | `ensure_supervisor.sh` |
| `supervise_services.sh` (every 60 s) | `crond` + 6 services | `Start_All.sh` guard |

`crond` was added to `Start_All.sh`'s guard list, so the supervisor restarts
cron and cron restarts the supervisor. Neither dying alone takes the chain
down; only a simultaneous death needs a reboot.

`phone/ensure_supervisor.sh` is the new piece. It refuses to restart a
supervisor that stopped on a **storm** — that is a deliberate decision, and
resuming it would restart the thrash it stopped. It distinguishes the two by
comparing only *lifecycle* lines (`supervising N services` vs `STORM:`), so its
own log output cannot push the verdict out of a tail window.

Proven end to end: cron executed a 1-minute probe at 23:05:00; killing
`uvicorn` brought Odysseus back via the supervisor with no human action.

## The self-match trap bit twice more

`pkill -f crond` and `pkill -f "uvicorn app:app"` each matched the SSH shell
whose own command line carried the pattern, killing the session mid-command.
Fourth and fifth occurrences in this project. Both the fix and the test now
split the literal (`P=cro; pkill -f "${P}nd"`), and `ensure_supervisor.sh`
excludes `$$` and `$PPID` from its own `pgrep` for the same reason — that
hazard was found while testing this very file, where a wrapper command that
merely *mentioned* the supervisor made the check report it up while it was down.

## Context ceiling is now per-model, and measured

`ODYSSEUS_LOCAL_SERVED_CONTEXT` was one number for every local model. That is
wrong in both directions: KV cache scales with the window, so a 2 GB model has
headroom a 25 GB one does not.

This is **not cosmetic**. `get_context_length()` feeds `num_ctx` on the
Ollama-native path (`llm_core._build_ollama_payload`), so the ceiling decides
the KV cache Ollama actually allocates.

New grammar, backward compatible with the bare integer:

    8192                      -> default 8192
    8192,granite4.2:3b=49152  -> default 8192, that model 49152

Measured on the RTX 3070 (8 GB) via `/api/ps` `size_vram`:

| model | ctx | total | offload |
|---|---|---|---|
| `granite4.2:3b` | 8192 | 2.72 GB | 100% |
| `granite4.2:3b` | 32768 | 4.64 GB | 100% |
| `granite4.2:3b` | **49152** | **5.81 GB** | **100%** |
| `granite4.2:3b` | 65536 | 7.37 GB | 79% |
| `granite4.2:8b` | 8192 | 6.37 GB | 92% |
| `granite4.2:8b` | 32768 | 10.27 GB | 56% |

So **49152 is the 3b's measured maximum at full GPU residency** — a 6x increase
— and `granite4.2:8b` is already spilling at 8192, where raising the window
would cost throughput rather than buy context.

Live verification after restart: `granite4.2:3b` reports 49152,
`granite4.2:8b` and `gemma4:26b` report 8192.

## The models actually in daily use cannot benefit

`gemma4:26b` (17 GB) and `nemotron-3.5-lightning:30b` (25 GB) already spill at
8192 — 29% and 19% offload measured in round two. There is no context headroom
for them on 8 GB; raising their window makes them slower, not more capable.
The per-model mechanism helps the small models and correctly leaves these alone.

## Open

- **Why the supervisor was killed is still unknown.** The chain now recovers
  from it, but the cause is undiagnosed. Termux battery-optimisation exemption
  is the untested suspect.
- **Termux:API app is not installed**, so `termux-job-scheduler` remains dead.
  Installing it would allow replacing cron with Android's own scheduler.
- `phone/` is versioned by convention only — this project is not a git repo, so
  `ensure_supervisor.sh` has no history behind it.

---

# Rev R (2026-08-31) — Context discovery fixed at the source; output tokens separated from it

## Correction to Rev Q

Rev Q claimed the models in daily use "cannot benefit" from a larger context.
**That was wrong, and it cited the wrong evidence.** It leaned on round two's
29%/19% offload figures, which describe *model weights* spilling to RAM — they
say nothing about KV-cache headroom. `qwen3.6:35b-a3b` was holding only
**4.98 GB of its 20.95 GB in VRAM with ~1.2 GB free**, which is exactly the
headroom the claim asserted away without measuring.

## Raising the ceiling alone did nothing — it only caps

Setting per-model entries to native windows left `qwen3.6:35b-a3b` and
`nemotron-3.5-lightning:30b` both reporting 131072. The ceiling logic is:

    if ceiling is not None and ctx > ceiling:
        ctx = ceiling

It lowers a discovered value and can never raise one. Both models were being
*discovered* at 131072, below their new ceilings, so nothing lifted them.

## Root cause: Odysseus never asked Ollama

`_query_context_length` probed llama.cpp's `/slots` for local endpoints but had
no Ollama equivalent, so every Ollama model fell through to
`KNOWN_CONTEXT_WINDOWS`. That table's keys are coarse prefixes and go stale:

| table key | table value | model's real window |
|---|---|---|
| `qwen3` | 131072 | `qwen3.6:35b-a3b` = **262144** |
| `nemotron` | 131072 | `nemotron-3.5-lightning:30b` = **1048576** |
| `mistral-nemo` | 128000 | `mistral-nemo:12b` = **1024000** |

**Fix (`0bc7c29`): probe Ollama's `/api/show`**, which carries each model's own
GGUF metadata as `<arch>.context_length`. Asking the server removes the table
from this path and cannot drift as models are added — `qwen3.6:27b`, pulled
after the change, needed no entry at all.

Keys containing `rope`/`original` are excluded: that is the pre-scaling
training window, where `gpt-oss` reports 4096 against a real 131072.

The two local probes answer different questions and both are kept:
llama.cpp `/slots` reports the window being **served**, Ollama `/api/show` the
window **supported**.

## Every model now serves its native window

`ODYSSEUS_LOCAL_SERVED_CONTEXT` carries a per-model spec; verified live after
restart, on existing sessions as well as new ones:

| model | context |
|---|---|
| `nemotron-3.5-lightning:30b` | 1048576 |
| `mistral-nemo:12b` | 1024000 |
| `qwen3.6:35b-a3b` | 262144 |
| `gemma4:26b` | 262144 |
| `gpt-oss:20b` | 131072 |
| `granite4.2:3b` | 131072 |
| unlisted | 8192 (default) |

**These are supported windows, not free capacity.** On 8 GB VRAM a 256K or 1M
KV cache spills heavily to system RAM — `granite4.2:3b` was measured dropping
to 79% offload at merely 65536. Expect slower long-context generation and
possible load failures at the 1M settings. Set at the user's explicit
instruction after that caution was given; every `.env` backup is on the phone.

## Output tokens are a separate parameter, now explicit

`DEFAULT_MAX_TOKENS` went 0 -> **8192** (`95ca848`, restoring `95528a1` which
`0469c06` had reverted pending live testing).

This is `num_predict`, **not** `num_ctx`. In `_build_ollama_payload` they are
set independently, and context was verified unchanged after the change
(262144 / 1048576 identical before and after).

At 0, Odysseus omitted `num_predict` and deferred to each model's own Modelfile
default — unstated per model, and sometimes small enough that a reasoning model
spent the entire budget on `<think>...` and returned empty content. That is the
empty-response failure reproduced live against `gemma4:26b`.

## Also this session

- **`qwen3.6:27b` pulled** (17 GB). There is no 26b in the qwen3.6 line; the
  real sizes are 27b (dense) and 35b (`-a3b`, MoE). Being dense, expect it in
  the ~2.8 tok/s band the other dense 30B-class models measured in round two,
  not the 21.3 tok/s the MoE reached.
- Laptop rebooted mid-session; Ollama restarted via `setup_ollama_host.ps1`.
  Phone SSH read as down purely because Tailscale was still starting.

## Open

- **VRAM cost at these native windows is unmeasured.** Two background
  measurement runs of `qwen3.6:35b-a3b` at 8192/16384/32768 were killed before
  producing output; the caution above rests on `granite4.2:3b` data instead.
- `qwen3.6:27b` is installed but unbenchmarked.
- Why the supervisor was killed (Rev Q) is still undiagnosed.

---

# Rev S (2026-08-31) — Operations panel: agent tools already existed; a human panel was built, then repointed at Supabase

## Starting point

Bil Weekend ops MCP tools (`worklist_structural`, `worklist_full`, `propose_change` in `mcp_servers/ops_server.py`, plus their `tool_capabilities.py` classification and tests) already existed uncommitted in the repo before this session. They called a Bil Weekend Next.js API — `/api/agent/ops/attention`, `/api/agent/ops/proposals` — that was never built, and no `agent_proposals` table existed to back `propose_change` either. `create_ops_agent_tasks.py` (also pre-existing, dated 2026-08-31) already documented both as pending steps.

## Human-viewable Operations panel built

New: `routes/operations/operations_routes.py`, `static/js/operations.js`, vendored `jkanban.min.js`/`.css` (Apache-2.0, bundles Dragula for drag/drop), a `rail-operations` rail button + `tool-operations-btn` sidebar entry wired into `static/index.html`/`static/app.js` following the existing Memory/Email/Notes/Calendar panel pattern.

Design chosen via a #design/#spec pass: a kanban board, columns = the six-value status enum, backed by the same client `ops_server.py` already used, so there is one worklist and one approval gate whether a change comes from an agent or a human drag. A new `OperationsNote` table (`core/database.py`) + `add_note` MCP tool let an agent leave notes visible in the panel, local to Odysseus rather than Bil Weekend's schema (which has no notes field).

## Discovered: the Bil Weekend website API was never provisioned

Checked directly against the live phone deployment (not guessed): `OPS_API_BASE_URL`/`OPS_AGENT_TOKEN` were unset in `/root/odysseus/.env`, unset in shell profiles, absent from the running process's environment, and the `mcp_servers` DB table (a separate config path for user-added servers, not used by built-ins) held zero rows.

## Redesign: Supabase direct

User provided `.bilweekend.env.local` (Bil Weekend's own web-app env: Supabase URL, service-role key, among other unrelated secrets) and directed the transport be changed from the Bil Weekend website API to calling Supabase directly, since that's the actual data store.

Live schema was queried (read-only, via the service-role key) rather than guessed: 22 tables exposed via PostgREST. Relevant ones — `bookings`, `contacts`, `curated_requests` (each `id` + a jsonb `data` blob), `queue_requests` (flat, self-contained), `operations_followup` (follow-up state keyed by `source`+`source_id`), `operators`.

`ops_server.py` and `operations_routes.py` were rewritten to query Supabase's PostgREST API directly (`SUPABASE_URL`/`SUPABASE_SERVICE_ROLE_KEY` — the same variable names Bil Weekend's own app uses) and merge the four source tables against `operations_followup` in Python, replacing the merge Bil Weekend's backend would have done. Live-verified before pushing: 104 rows merged correctly (20 bookings / 48 contacts / 33 curated / 3 queue; 60 New / 43 Replied / 1 Rejected), structural projection confirmed to drop all customer PII.

Status-change writes (`propose_change`, `POST /api/operations/status`) were left deliberately paused — they now raise a clear error/501 rather than write anywhere — because no `agent_proposals` table exists to stage a reviewable change into. Whether writes should go direct to `operations_followup`/`queue_requests` or wait on a real proposals table was raised and left undecided.

## Deployment

`SUPABASE_URL`/`SUPABASE_SERVICE_ROLE_KEY` set in the phone's `/root/odysseus/.env`; the earlier `OPS_API_BASE_URL` line (from the abandoned website-API design) removed. The phone had pre-existing, unrelated uncommitted edits (`src/constants.py`, `src/llm_core.py`, `src/model_context.py` + several `.bak` files, from 2026-08-30 `DEFAULT_MAX_TOKENS` work) — stashed (`stash@{0}`) before the first pull rather than risking a conflict; left stashed, not applied, not dropped.

Four commits pushed to `origin/daily-driver` and pulled onto the phone in sequence, with a service restart (`Stop_All.sh`/`Start_All.sh`) after the ones touching Python:
- `6e8fa7b` — panel (routes, JS module, vendored jKanban, DB table, MCP tool).
- `aa786fe` — surfaced the backend's actual error text instead of a bare HTTP status.
- `f852225` — Supabase-direct rewrite.
- `33717c7` — scrollbar fix, hide-Replied, List view, view-switch caching.

## Post-deploy fixes, in order encountered

- First load showed a 503 — correct, not a bug: confirmed the full chain (rail button → panel → `require_admin` → backend → "not configured") worked end-to-end while the token genuinely didn't exist yet.
- `operations.js`'s error handling only showed the HTTP status; changed to read the backend's `detail`/`message` body field.
- Kanban board had no working horizontal scrollbar: `jkanban.min.css` floats board columns, and a float wraps to a new line instead of overflowing under `white-space:nowrap` — fixed by overriding `.kanban-board` to `display:inline-block; float:none`.
- "Replied" (43 of the 104 live rows) hidden from both views by default — hardcoded via a `HIDDEN_STATUSES` set, not yet user-configurable.
- A List view (flat table) was added alongside the board, toggled from the modal header — deliberately not a clone of Bil Weekend's own admin table.
- No caching existed anywhere (every open re-hit Supabase live). Switching Board ↔ List now reuses the last fetch from memory instead of refetching; the in-memory copy is cleared on close. No longer-lived cache (surviving a close/reopen, or a server-side TTL) was built.

## Open

- Status-change write path — direct write vs. a real proposals table — is an explicit undecided fork, not an oversight.
- Bil Weekend's fourth inbound source, "App Bookings," lives in a separate Supabase project outside the current service-role key's reach; entirely absent from the panel.
- Status/limit filter controls: the backend accepts both params; no UI control was ever wired to them.
- The hidden-status set is a single hardcoded value ("Replied"), not a setting.
- Whether "Operations" should become one instance of a general Board/Project module (raised in the original #frame discussion about per-website project boards) was never revisited after Operations was built standalone.

---

# Rev T (2026-08-31) — Brave automation bridge built; Projects Hub empty-state and task creation repaired

## Brave browser extension & automation bridge

A Manifest V3 extension was constructed in `odysseus-brave-extension/` (`manifest.json`, `background.js`, `content.js`, `popup.html`, `popup.js`, `bridge_server.py`). The extension attaches via `chrome.debugger` (CDP) to active browser tabs and pairs with a local FastAPI/WebSocket server on `127.0.0.1:8765`, enabling scriptable DOM clicking, text typing, key event dispatching, and full-fidelity screenshot captures. An in-page HUD overlay was injected with a 1-click *"📌 Link to Project"* action.

## Second instance deployed on port 7002

Worktree 2 (`odysseus-agent-2`, branch `local-agent-2`) had its Python environment provisioned and was launched on port 7002 with an isolated data directory (`ODYSSEUS_DATA_DIR=.../data`). Navigating Brave to `http://localhost:7002/` verified operational status and active Agent HUD pairing.

## Projects Hub modal repairs

1. **Empty-State Guarding:** Replaced silent `if (!_currentProject) return;` exits in `static/js/projects.js` with tab-aware empty states displaying contextual prompts and a 1-click `+ New Project` button.
2. **Backdrop Event Hijacking:** Removed a duplicate `.modal-backdrop` element that intercepted mouse clicks on tabs/buttons and triggered modal dismissal.
3. **Window Drag Arguments:** Corrected `makeWindowDraggable(modalEl, { content, header })`.
4. **Modal Lifecycle Wiring:** Registered `projects-modal` and `operations-modal` in `modalManager.js` `_AUTO_WIRE`.

## Task creation & two-way disk synchronization

1. **Optimistic Task Input:** Wrapped task creation in `<form id="proj-task-form">`, supporting instant item insertion without screen-wiping or dropping keyboard focus, enabling continuous rapid-fire entry.
2. **Silent Background Reloading:** Updated `_loadProjectDetail(id, silent=true)` to avoid screen flashing during checkbox toggles, deletes, and additions.
3. **Disk Sync (`PROJECT.md`):** Implemented `sync_tasks_to_manifest_file()` in `src/projects_manager.py` and hooked it into `POST`, `PATCH`, and `DELETE` task endpoints in `routes/projects/projects_routes.py`. Any UI or API modification to tasks immediately syncs the `## Active Tasks` checklist in `PROJECT.md`.

## Notes-style To-Do upgrade architecture

Completed `#research`, `#design`, and `#spec` passes defining the blueprint for bringing custom `.note-check-dot` SVG circles, inline `contentEditable` editing, continuous rapid-entry, and confetti celebration animations into the Projects Hub.

## Extensive Notes & Viewable Attachments Parity

1. **Database & Model Extension (`core/database.py`):**
   - Added `project_id = Column(String, nullable=True, index=True)` and `attachments = Column(Text, nullable=True)` to `Note` model.
   - Added `_migrate_notes_project_and_attachments()` automated migration in `init_db()`.
2. **Notes API Integration (`routes/note/note_routes.py`):**
   - Extended `NoteCreate` and `NoteUpdate` schemas to accept `project_id` and `attachments`.
   - Updated `GET /api/notes` with `project_id` query parameter for project-scoped note queries.
   - Added `attachments` and `project_id` to `_note_to_dict` serialization.
3. **Projects Hub UI (`static/js/projects.js`):**
   - **Expanding Quick-Add Composer:** Single-line compact bar expanding into 3-mode composer (`[ 📝 Note ]` | `[ ✓ Checklist ]` | `[ 📎 Attach File ]`) with color palette picker, pin toggle, dropzone, and close button.
   - **Keep-Style Note Cards:** Color themes (`yellow`, `green`, `cyan`, `blue`, `amber`, `rose`, `purple`, `default`), pinned section (`📌 Pinned`), filter chips, inline checklist row addition, and real-time search.
   - **Viewable Image Lightbox:** Clicking image attachments opens a full-screen dark backdrop modal with zoom, download, and copy link actions.
   - **Document & PDF Viewer:** Clicking document attachments opens a formatted viewer modal with syntax-highlighted reader and PDF iframe viewer.
   - **Drag-and-Drop Dropzone:** Multi-file drag-and-drop file upload supporting images, documents, code, text, CSV, and audio.
4. **Manifest Synchronization (`src/projects_manager.py`):**
   - Added `sync_notes_to_manifest_file()` writing `## Project Notes` into `PROJECT.md`.

## Commits

Pushed to `dev`, `daily-driver`, and `local-agent-2`:
- `ddce552` — feat(app): add /projects and /operations deep-link routes
- `c58594c` — fix(projects): replace window.prompt()/confirm()-based New Project and Add Link with inline forms
- `b6f5983` — fix(projects): fix modal markup, tab click handlers, and make empty-state tab-aware
- `2ae1fbe` — feat(projects): add optimistic task creation, form submit, and disk manifest synchronization
- `8dbeb7d` — feat(projects): implement Notes-style checklist parity with animated check-dots, inline editing, and agent sessions
- `31bf977` / `850f4b4` / `ce0d10d` — feat(projects): extensive notes parity with viewable image lightbox and document viewer

## Sequential AI Execution Queue & In-Flight Halting

1. **Client-Side Queue (`static/js/projects.js`):**
   - Implemented `_projectTaskQueue` orchestrating sequential AI summary calls to prevent concurrent worker contention.
   - Added visual `⏳ Queued (#N)` badge and toast notifications.
   - Added `AbortController` cancellation with a pressable **Halt** button on processing cards.
2. **Audit Logging (`src/projects_manager.py`):**
   - Built `append_project_execution_log()` recording timestamped status (`completed`, `fallback`, `halted`), model used, and output snippet into `PROJECT.md` `## Execution Log` and `<project>/logs/execution.log`.

## Unified Non-Chat System Activity & Query Logging Subsystem

1. **Database Schema (`core/database.py`):**
   - Created `SystemQueryLog` ORM model recording all non-chat queries, background jobs, tool runs, model latency, token counts, errors, and metadata with indexed fields.
2. **Telemetry Engine (`src/system_logger.py`):**
   - Implemented `log_system_query()`, `get_system_logs()`, `get_system_log_stats()`, and `prune_system_logs()`.
   - Built 10-minute duplicate stacking / incrementing for periodic background checks.
   - Bounded retention: capped at 10,000 records with automated 30-day pruning.
   - Strict isolation: interactive user chats remain exclusively in `session_messages`.
3. **API Endpoints (`routes/system/activity_log_routes.py`):**
   - Mounted `GET /api/system/activity-logs` (filtering, pagination, search), `GET /api/system/activity-logs/stats`, and `DELETE /api/system/activity-logs/clear`.
4. **Module Telemetry Hooks:**
   - Projects (`routes/projects/projects_routes.py`), Tasks (`src/task_scheduler.py`), and Email (`src/builtin_actions.py`).
5. **Observability UI Hub (`static/js/activityLog.js`, `static/index.html`):**
   - Added sidebar **`⚡ Activity Log`** button with dynamic running activity dot indicator.
   - Draggable modal viewer with real-time stats banner, module chips (`All`, `Projects`, `Tasks`, `Email`, `Operations`), status filter, text search, expandable payload inspector, latency badge, and 3s live polling.

---

# Rev U (2026-09-01) — Android widget: status gap found, recorded

Not a build entry — this project (`OdysseusWork/odysseus-android-widget`, a Kotlin/Gradle app, sibling to `odysseus-brave-extension`) had no record anywhere: not here, not in `PROJECTS_CATALOG_RECORD.md`. This entry exists to close that gap with what's actually confirmed, not to claim it's finished.

**Confirmed, by reading the source and the filesystem:**
- Real source tree under `app/src/main/java/com/odysseus/widget/`: `OdysseusWidgetProvider.kt`, `OdysseusRemoteViewsFactory.kt`, `OdysseusWidgetService.kt`, `network/ApiClient.kt`, `network/RouteManager.kt`, `model/ToDoItem.kt`, `model/ProjectItem.kt`, `ui/QuickAddActivity.kt`, `ui/SettingsActivity.kt`, plus widget/activity layout XMLs.
- `ApiClient.kt` calls a real, already-merged backend: `GET/POST /api/companion/todos` and `/api/companion/todos/toggle` (`companion/routes.py`, `companion/todos.py`, on `daily-driver`/`local-agent-2`) — `fetchTodos`, `toggleTodo`, `createTodo` are implemented, not stubbed.
- No `TODO`/`FIXME`/stub/placeholder markers anywhere in the widget's source.
- A `debug` build's compiled artifacts exist under `app/build/`, so it has built successfully at least once.

**Not confirmed — genuinely unknown, not guessed:**
- Whether it currently installs and runs correctly on the phone (not tested this pass — reading only).
- Whether every UI path (quick-add, settings, toggle-from-launcher) is wired end-to-end versus just the pieces read here.
- Who is doing the remaining work on it, or what "remaining work" even consists of — no task list exists for this project anywhere.

---

# Rev V (2026-09-01) — Five bugs fixed and live-verified; Overview screen built; widget build toolchain fixed; one Activity left mid-build

## Bugs found, root-caused, fixed, and verified on the real device/server (not just compiled)

1. **`companion/todos.py`: `project.task_completed` double-counts under concurrent identical toggle requests.** Read-modify-write race on a locally-read `cur_state`. Fixed by recomputing from `COUNT(*) WHERE completed=True` instead of incrementing a cached value. Regression test (`tests/test_companion_todos_counter_race.py`) reproduces the race via two SQLAlchemy sessions holding stale identity-map references; verified to fail against the pre-fix code and pass after.
2. **`static/js/projects.js`: the Projects-tab search box could regress to an older, shorter query mid-typing.** `_renderLandingPage` had no request-sequencing; whichever concurrent render *resolved* last won the DOM replace, not whichever was *typed* last. Fixed with a monotonic `_landingRenderSeq` token, verified against a standalone reproduction of the exact promise ordering.
3. **`static/js/projects.js`: editing one task's title while a checkbox/delete/add fired on a different task silently lost the edit.** Those handlers called a full, destructive `_renderTasksTab` rebuild unconditionally. Fixed via `_flushPendingTaskEdit()`, which commits and awaits any in-progress title edit before that rebuild runs.
4. **`static/js/projects.js`: `_saveComposerState` was called from 4 places but never defined anywhere.** Every call threw `ReferenceError`, aborting the handler before it reached the code that actually changed state — this is why clicking Checklist/Attach File in the note composer appeared stuck on Note, and why the note-search box did nothing on every keystroke (a bug an earlier pass in this same session missed, having checked render timing but not this first line). Fixed: the function now captures the title input's live value into `_composerTitle` before a destructive re-render; checklist rows already live-synced independently and didn't need it.
5. **Android widget: tapping "Project Task" in Quick Add never actually attached it to a chosen project.** `QuickAddActivity` never passed a `targetId`; the server silently fell back to whichever project was most recently updated anywhere in the system. Fixed with a project-picker `Spinner` defaulting to the widget's current list filter (`RouteManager.filterProjectId`), with override.

All five were deployed to the live phone (fresh ws-01 backup taken first each time) and re-verified post-deploy — including a real end-to-end widget test: recovered the widget's actual configured API token from its own SharedPreferences, triggered a real `ACTION_TOGGLE` broadcast against a real task, and confirmed via direct DB query that the counter fix holds under the real server, then reverted the test data back to its original state.

## Widget build toolchain: fixed a real, separate bug in the process

No `gradlew` existed in `odysseus-android-widget/`. Gradle 9.3.1 was already cached locally (`~/.gradle/wrapper/dists`), invoked directly — but the build failed with "SDK location not found" despite `local.properties` visibly containing the correct `sdk.dir`. Root cause: the file had a UTF-8 BOM, which `java.util.Properties.load()` does not strip, corrupting the `sdk.dir` key. Rewritten without the BOM; builds clean since.

## New: widget "Daily Overview" screen — built, deployed, tested live

- Backend: `GET /api/companion/email-summary` (new — cross-account unread/urgent counts, reads the same cached state file `action_check_email_urgency` writes, same owner-slug algorithm duplicated rather than imported since neither existing call site needed to change). `GET /api/companion/projects` now also returns each project's already-stored `agent_summary` column (no migration needed).
- Widget: new `OverviewActivity` (read-only, dialog-themed, matching `QuickAddActivity`'s pattern) showing cross-project task progress + each project's agent summary + the email unread/urgent counts, opened via a new dedicated button (`btn_overview`) on the widget's home-screen surface.
- Verified live on-device: screenshotted the open Overview screen showing real data (115 unread / 23 urgent; 6 real projects with real agent-summary text and correct progress counts), and confirmed the Close button dismisses cleanly with no crash.

## Left mid-build, not finished — stated plainly, not glossed over

A second widget feature (tap a to-do row's body to open a read-only detail view, distinct from tapping its checkbox to toggle) was in progress when this recording pass started:
- Written: `TaskDetailActivity.kt`, `activity_task_detail.xml`, the `EXTRA_VIEW_DETAIL`-based click-routing split in `OdysseusRemoteViewsFactory.kt` and `OdysseusWidgetProvider.kt`.
- **Not done: `TaskDetailActivity` is not yet registered in `AndroidManifest.xml`, the project has not been rebuilt since these changes, and none of it has been installed or tested on the device.** Confirmed by grepping the manifest (zero matches) immediately before writing this entry.


# Rev W (2026-09-02) — Fork merged into agent-2; eleven defects triaged and fixed; all verified live on the phone

## Correction to Rev V

Rev V's closing claim (line 2101) was false by the time it was read. It stated `TaskDetailActivity` "is not yet registered in `AndroidManifest.xml`, the project has not been rebuilt since these changes, and none of it has been installed or tested on the device." All three parts were wrong: the activity was registered at `AndroidManifest.xml:58`, the debug APK carried an mtime of Sep 1 18:25, and the device reported `lastUpdateTime=2026-09-01 18:25:57`. The feature was verified working on-device this session by tapping a real widget row. The Rev V entry appears to have been written from a grep that missed, and was never re-checked.

## Worktree state and merge

`local-agent-2` was 12 commits behind `daily-driver` and did not contain the Organisers, Overview Hub, or itinerary modules at all — an earlier pass in this session wrongly reported that "AI Work Organisers" and "Overview" did not exist, because the session was scoped to a worktree that predated them. Fast-forwarded `3075272` → `c2e7692` (26 files, +5742).

Mid-session the user committed the fix set as `04abbd5` and merged both agent worktrees into `daily-driver` as `dbed04c`, before this session had committed anything. All nine changed files were confirmed byte-identical in `daily-driver` afterwards, and the two affected test suites re-run there green (11/11) — the merge with agent-1's work introduced no conflict. `local-agent-2` was stale on origin at `3075272` and was pushed to `04abbd5`.

`04abbd5` also swept in `scratch/` and eight `scripts/test_*.py` files: 2091 insertions total against 248 belonging to the fix set.

## Eleven defects: dispositions

Nine were real and are fixed. One was not a defect. One could not be recovered.

1. **D1 `routes/organisers/organisers_routes.py:209` — an organiser with no target accounts and no rules matched every email in the index.** The account filter was skipped when `target_accounts` was empty, after which the "no rules specified" branch returned `True` unconditionally. Proved by controlled experiment against the live API before the fix: `preview-matches` with empty rules returned 161 of 161. Now returns `False` when no criterion is declared at all. The same function also let an email carrying no `account_key` bypass an account filter entirely (`if acc_id and acc_id not in target_accounts`); it now fails the filter instead.
2. **D2 `routes/overview/overview_routes.py:288` — accounts discovered from the email stream put a display label in the `email` field and could yield two defaults.** Real descriptors use an address or `""`; discovered ones were filled with `"Account a1b2c3d4"`. The per-append default rule (`acc_k == "default" or len(accounts_out) == 0`) marked both the first discovered account and a later literal `"default"`. Single-default is now enforced as an invariant over the finished list.
3. **D3 `static/app.js` — `/operations` was served by `app.py` since it shipped but had no `_routeOpen` entry.** The route returned the SPA and nothing opened.
4. **D4 — `/organisers` existed nowhere.** Added the `app.py` route and the map entry.
5. **D5 `static/js/overview.js:1007` — two competing deep-link mechanisms for `/overview`.** `overview.js` carried its own bare `setTimeout(openOverview, 200)` racing `app.js`'s `deferRouteOpener`. The timer was removed; `_routeOpen` now owns it.
6. **D6 `src/builtin_mcp.py` — `mcp_servers/organisers_server.py` shipped but was never registered** in `_BUILTIN_SERVERS`, despite commit `1eb1d2f` claiming MCP tools.
7. **D7 `organisers_routes.py` — `memory_lane` was written on create/update and never read.** Now read, but see "known inert" below.
8. **D8 — not a defect.** `linked_project_ids` is empty on all seven seeded organisers because `DEFAULT_ORGANISERS` deliberately defines `memory_lane` and no project links; linking is manual and the empty state already exists at `workOrganisers.js:728`. No change made.
9. **D9 — unrecoverable.** Its identity was lost when the conversation was compacted. Rather than guess, the codebase was re-derived from scratch, which surfaced four defects not in the original list (recorded below). *(Identity supplied by the user and fixed in Rev X: Operations table string defects — a duplicated unit and unsuppressed "Not known" placeholders.)*
10. **D10 `odysseus-android-widget/AndroidManifest.xml` — both dialog activities inherited `app_name` ("Odysseus Gateway") as their title and recents entry.** Given explicit `android:label` values.
11. **D11 `overview_routes.py:544` — an authentication bypass, not the dead code it was first taken for.** `require_user` raises 401 for unauthenticated callers and 403 for API tokens; a bare `except Exception` swallowed both and fell through to `owner=None`, whose cache key is `"__global__"` — the shared briefing bucket, served to anyone, with the API-token guard discarded. Now called bare, matching every other route in the repo.

## Four further defects, found while re-deriving the list

- `organisers_routes.py` called `mem_mgr.load_all()` unscoped, returning every user's memories in organiser detail on a multi-user deploy. Now scoped to the caller.
- The account-key bypass in `_matches_rule`, described under D1.
- `/projects` and `/operations` were absent from `index.html`'s per-route favicon and title maps, so bookmarking either fell back to the boat icon and a generic title.
- `index.html`'s `modulepreload` for `app.js` carried a different `?v=` than its `<script>` tag (`20260815toolapproval4` vs `20260831notesparity1`), so the preload warmed a URL the page never requested.

## Verification

Four regression tests were added and each was confirmed to fail against the pre-fix code: unauthenticated `/api/overview` must 401; an organiser with no criteria must match nothing; an email with no account key must fail an account filter; discovered accounts must yield exactly one default and never a label in the `email` field.

Fixing D11 broke two existing overview tests, which had been passing *through* the bypass. They were updated to authenticate with the same mock auth middleware the organisers tests already use, and the SWR fixture row was re-keyed from the shared `__global__` bucket to `admin`.

The full suite is 5872 tests across 804 files and has no bounded runtime here; a background attempt was killed after ~20 minutes with no output. Scope was narrowed to the 28 files reachable from the changed modules: **481 passed, 1 skipped, 4 failed**. All four failures were proved pre-existing by stashing the `builtin_mcp.py` edit and reproducing them identically — two are in the npx cache-check fallback, two are `read_text()` without an `encoding=` argument choking on cp1252 under Windows. *(Rev X correction: the npx pair was recorded here as `KeyError: 'args'`. The measured symptom is an assertion failure — the tests never reached the fallback, because `_npm_cache_roots()` also consults the LOCALAPPDATA npm cache, which the tests did not clear.)* `tests/test_ops_server_request_building.py` additionally fails to collect (`_attention_params` no longer exists in `ops_server`), also pre-existing.

## Live verification on the phone

The phone was already at `dbed04c` and its server (pid 30455) had 7604 s of elapsed time at probe, placing its start ~13:50 — six minutes after the 13:43 commit, so it was running the new code.

- **D1** — "Receipts and Payments" (0 accounts, 0 senders, 0 keywords, 0 domains) now matches **0 emails**; the six seeded organisers correctly vary at 27/15/26/10/13/26. Confirmed at function level under the server's own venv: `_matches_rule(email, [], {})` → `False`, account-only → `True`.
- **D2** — after `force_refresh`, exactly one default (was two) and the `default` account's `email` is `""` (was `"Primary Inbox"`).
- **D3 / D4 / D5** — `/operations` opens the Operations modal; `/organisers` serves and auto-opens with the title "Work Organisers — Odysseus"; the served `overview.js` no longer contains the old timer and `/overview` opens exactly one modal. Served HTML confirms preload and script `?v=` now match.
- **D6** — on-device under the server venv: `REGISTERED: [image_gen, memory, rag, email, ops, organisers]`.
- **D11** — the `try/except` is gone on the device; `owner = require_user(request)` is bare.

**A stale cache produced a false negative worth remembering.** The first live read of `/api/overview` showed D2 apparently unfixed — two defaults, label in the email field. That was a stale SWR payload computed by the old code and still sitting in the `OverviewCache` table; `force_refresh=true` proved the fix was live. Anything cached there survives a deploy and keeps serving old-code output until it revalidates.

## Known inert: D7

The `memory_lane` fix is deployed and correct but has no effect on current data. The live memory store holds 10 entries, all owner `admin`, with categories `{fact:5, preference:3, contact:1, identity:1}`. None intersects the organiser category vocabulary (`operations/strategy/partnerships/finance/tech/personal`) and none uses a namespaced `organisers:` category, though the seeds write lanes in exactly that form (`organisers:bilweekend_ops`). Linked Memories therefore shows 0 for every organiser, as it did before. An earlier draft of the fix made the lane *replace* `category_group`, which would have guaranteed 0 forever; it was changed to match either. Making the tab useful requires something to write memories tagged with a lane.

## Widget: committed, rebuilt, installed, verified

`odysseus-android-widget` had 10 modified files plus six untracked ones — including `TaskDetailActivity.kt`, `OverviewActivity.kt`, their layouts, `EmailSummary.kt`, and `app/build.gradle.kts`. The task-detail feature was running on the device and had never been tracked in git. Committed as `35d7a18` (16 files, +592). **This repo has no git remote**, so it cannot be pushed; it exists only on this machine.

Rebuilt with the cached Gradle 9.3.1 (still no `gradlew` in the project; the Rev V BOM fix in `local.properties` is holding), installed with `adb install -r` to preserve the widget's configured API token. The home-screen widget survived the reinstall and still reported "Synced (Tailscale)". Tapping a to-do row's body launched `TaskDetailActivity` as top-resumed activity and the dialog title rendered **"Task Detail"**, not "Odysseus Gateway" — `Theme.MaterialComponents.DayNight.Dialog` does render the activity label as the dialog title, contrary to the expectation held while making the fix. Device left restored: dialog closed, zero `TaskDetailActivity` instances, launcher focused.

## Open

- **`dev` is not merged.** It sits at `3075272`, 17 commits behind `daily-driver` (`dbed04c`) and 0 ahead. It is the stated main/PR branch.
- **The abandoned stash on the phone persists** — `phone-local-edits-before-operations-pull`, 108 insertions across `src/model_context.py`, `src/llm_core.py`, `src/constants.py`.
- **D9's identity remains unknown.**
- **The unified WorkBench design is unchosen.** Five candidates plus one hybrid were presented and evaluated across seven dimensions; no selection was made, and no code was written for it.
- **`odysseus-android-widget` has no remote**, so all widget history is single-copy on this machine.

# Rev X (2026-09-02) — `dev` retired, D9 and D7 fixed and verified live, the test suite made runnable

## Corrections to Rev W

Two of Rev W's statements were measurably wrong, and both are corrected in place above rather than only here.

- **`dev` was recorded as eight commits behind `daily-driver`.** It was 17 behind and 0 ahead — strictly behind, with no unique commits.
- **The npx cache-check failures were recorded as `KeyError: 'args'`.** The measured symptom is an assertion failure. The tests never reached the fallback they claimed to exercise.

Rev W's D9 entry stands as written — "unrecoverable" was an honest account of what that session knew — with a forward pointer added. Its identity was supplied by the user this session.

## Branch convergence and the retirement of `dev`

`daily-driver` was fast-forwarded to Rev W and now carries this session's work. `dev` was 17 behind and 0 ahead, and `git merge-base --is-ancestor dev daily-driver` confirmed `3075272` is reachable from `daily-driver`, so deleting it lost nothing. The GitHub default branch was repointed to `daily-driver` **before** the delete, because GitHub refuses to delete the default branch. `dev` is gone locally and on `origin`.

`upstream` was not touched. This repo is a fork and `upstream/HEAD` still points at that project's own `dev`.

The brief described four worktrees including one for `dev`. There is no `dev` worktree — the fourth is `odysseus-fork-perf`, detached at `c4e3661`.

## The abandoned stash is gone

`git diff stash@{0} HEAD` returned **0 lines** for all three files (`src/constants.py`, `src/llm_core.py`, `src/model_context.py`), re-measured on the phone immediately before the drop rather than trusted from Rev W. Dropped as `88c2787f66d1fdadee55dd74d14a5843d3ea42fd`; the SHA was recorded first, so the drop is reversible while the object survives gc. `git stash list` is now empty.

## D9 — the Operations table rendered its sources' placeholders

**The buggy renderer was server-side, not in `operations.js`.** The lead pointed at `_isEmptyDetailValue` (`operations.js:581`), but that helper serves the raw-record detail view. The table renders `row.summary`, composed in `mcp_servers/ops_server.py:_fetch_merged_worklist`; `_rowSummaryLine` only joins it with a middle dot.

Bil Weekend's intake does not write NULL for a field nobody filled in. Read from the live `queue_requests` table, verbatim:

| Rendered | Stored | Column |
| --- | --- | --- |
| `10 days days` | `'10 days'` | `trip_days` (free text, already carries the unit) |
| `Not Known  days` | `'Not Known '` | `trip_days` (note the trailing space) |
| `Not Known` | `'Not Known'` | `regions` |
| `+Not known` | `'+Not known'` | `phone` |
| `-Not known` | `'-Not known'` | `email` |
| `- Tour/Full service` | `'- Tour/Full service'` | `service_type` — a real value |

Two filters let every one of these through: `[s for s in summary if s]` server-side and `filter(Boolean)` in the client both test truthiness, and a non-empty placeholder is truthy. The only defect Odysseus itself introduced was appending the unit unconditionally; the rest is faithful rendering of dirty upstream data.

Fixed with `_is_empty_value`, `_day_count_summary` and `_contact_field` in the composer, applied at all four summary sites plus the `name`, `email` and `phone` fields. The leading dash on `service_type` is left verbatim: it is a bullet marker on a real value, and stripping it would delete information. `_isEmptyDetailValue` stays where it is — the detail view renders the raw record with empties behind a "show N empty fields" toggle, so it cannot share a helper whose job is to suppress them.

**A correction to this session's own research.** The reported `-Not known` was first attributed to `phone` holding `'+Not known'`. Both exist. `phone` holds `'+Not known'` and `email` holds `'-Not known'`, and the first fix covered only the former. The server-side probe reported clean summaries and would have justified calling D9 done while the user's exact reported string was still on screen. **Reading the live DOM is what caught it.**

## D7 — a writer existed, and two MCP tools raised on every call

The brief's premise was that nothing writes memories tagged with an organiser lane. A writer exists: `record_work_insight` in `mcp_servers/organisers_server.py`. It could never have worked.

`Memory` carries `id, text, category, source, owner, session_id, timestamp`. It has no `content`, no `lane`, no `tags`. Verified by execution on the device:

- `record_work_insight` raised `TypeError: 'content' is an invalid keyword argument for Memory`
- `get_work_organiser_detail` raised `AttributeError: type object 'Memory' has no attribute 'lane'`, which fires whenever `memory_lane` is set — **all seven organisers**

Rev W's D6 fix registered `organisers_server` in `_BUILTIN_SERVERS`. That is what made two broken tools reachable by the model: a correct fix exposed a latent defect.

**There are also two memory stores, and the writer targeted the wrong one.** `MemoryManager` reads `memory.json` (`/data/data/com.termux/files/home/odysseus-data/memory.json`, 10 entries, all owner `admin`). The SQLAlchemy `memories` table holds **0 rows**. The HTTP route reads the JSON store; the MCP tool wrote the SQL table. Repairing the constructor alone would have written to a store nothing reads — inert in a way no test would have caught.

Per the user's decision this is a **crash-stop only**. The memory-matching rule is extracted to `_organiser_memories` in `organisers_routes.py` and shared with the MCP server so the two cannot drift. `record_work_insight` now refuses plainly and advertises itself as unavailable. How a memory legitimately acquires an organiser lane remains open, deferred with the WorkBench decision.

Verified live: all seven organisers return valid JSON, `record_work_insight` returns its refusal, `memory_notes=0` throughout — honest, because nothing writes lanes yet.

**Incidental finding.** The seeded slugs do not match their lanes: `bilweekend-tour-ops` carries lane `organisers:bilweekend_ops` (hyphens against underscores). The `organisers:{slug}` fallback would never reproduce a seeded lane.

## D8 — no UI path exists, and none was built

`linked_project_ids` appears in **zero** files under `static/`. The API accepts it on create (`organisers_routes.py:564`) and update (`:615`), and `_createNewOrganiser` sends only `name`, `category_group`, `icon`, `priority`. The three MCP organiser tools do not link projects either.

It is populatable only by a direct API call. Reported, not built, as the brief directed.

## Test health — the suite was never slow, it was aborting

**A single collection error aborts the entire pytest session before any test runs.** `tests/test_ops_server_request_building.py` could not be imported: all ten of its tests exercise `_attention_params`, deleted in `f852225` when Operations moved to reading Supabase directly. That one file is why the suite had never completed here. Collection of all 5872 tests takes 21 seconds. The file was deleted rather than skipped — it tests an HTTP param builder for an API that was never built.

With collection unblocked, measured on identical code:

| | Windows | Linux guest (the phone) |
| --- | --- | --- |
| Before this session | 181 failed, 5677 passed, 3 errors, 967.89s | not run |
| After | **122 failed, 5762 passed, 2 errors, 922.59s** | **15 failed, 5878 passed, 0 errors, 895.40s** |

**107 of the 122 Windows failures are platform artifacts.** The dominant causes are `os.fchown` and `socket.AF_UNIX` (POSIX-only), further `read_text()` calls without `encoding=` choking on cp1252, node subprocess timeouts, and Windows path semantics. The Linux guest is where the server runs and is the reference environment; Windows is not a trustworthy signal for this suite.

Three failure classes were fixed:

- **~60 JS tests** passed a Windows path into a node ESM import, so node read the drive letter as a URL scheme and raised `ERR_UNSUPPORTED_ESM_URL_SCHEME`. Converted **32 import sites across 23 files** from `as_posix()` to `as_uri()` — the pattern eight files in this suite already used. The single `fs.readFileSync` call keeps `as_posix()`: it takes a path, not a URL.
- **All 8 bare `read_text()` calls** in `test_security_regressions.py` were given `encoding="utf-8"`, not only the two that happened to fail. The rest are the same latent bug waiting on a different input file. That file is now 99 passed, 0 failed.
- **2 npx cache tests** asserted the subprocess fallback but never reached it. `_npm_cache_roots()` also consults the LOCALAPPDATA npm cache, which the tests never cleared and which really does contain `@playwright/mcp`, so the probe short-circuited to `True`. On Windows `expanduser("~")` reads `USERPROFILE`, so setting `HOME` did not redirect it either.

**The runnable command**, in the guest, under the server's own venv:

    cd /root/odysseus && ./venv/bin/python -m pytest -p no:randomly --continue-on-collection-errors -q

`--continue-on-collection-errors` is belt-and-braces now that the orphan is gone. Roughly 15 minutes. Launch it with `setsid nohup` wrapping the whole `proot-distro login`: a plain `nohup` inside the guest dies when the SSH session ends.

**The 15 remaining Linux failures**, none in code touched this session: `test_external_context_tool_gate` (4), `test_fenced_example_not_executed_for_native_models` (2), `test_research_report_read` (2), and one each in `test_docs_no_orphan_images`, `test_itinerary_module`, `test_llm_core_ollama`, `test_plan_mode`, `test_pr6020_browser_review_regressions`, `test_runtime_paths`, `test_tool_index_schema_parity`. `test_itinerary_module` sits in the Operations automation module, which the brief puts out of scope — reported, not touched.

## A four-minute outage, self-healed

The server was down for roughly four minutes during the second deploy. The restart method is to kill the uvicorn pid and let `supervise_services.sh` rebuild it on its 60-second poll. The second kill landed while the supervisor was still inside its restart window, and an 80-second wait proved shorter than this device's uvicorn boot time, so the probe read a false "still down" and prompted another check instead of patience. The supervisor recovered it unaided, logging `down [uvicorn app:app] -- running Start_All.sh`.

Process identity across the session: `30455`, then `13952`, then `15394`. `etimes` remains the only usable deploy signal; the proot clock makes `lstart` meaningless.

Backup taken before any mutation: `/data/data/com.termux/files/home/odysseus-data/revx-backup-20260902-174925`, holding `app.db`, `memory.json`, both changed source files, and the stash and HEAD SHAs.

## Decisions taken

- **`dev` retired**, GitHub default repointed to `daily-driver`, branch deleted.
- **D9 fixed in the composer**, not the client, so every consumer gets clean data — including the MCP worklist tool the model reads.
- **D7 crash-stopped only.** The lane-semantics question is tied to the WorkBench decision.
- **Test reference environment is the Linux guest.** Windows remains usable but its failure count is not a health signal.
- **`service_type`'s leading dash renders verbatim.** It is data, not a formatting defect.

## Open

- ~~**The unified WorkBench is still unchosen.**~~ C1 (Tabbed Shell) and C2 (Cockpit Drilldown) were evaluated across nine dimensions. C1 wins on cost, risk and reversibility; C2 wins on phone-width fit and the AI-integration phase, at the price of making the 120s two-tier SWR cache load-bearing for every screen and needing a back stack nothing in the codebase has. Deferred by the user until tasks 1–7 landed. They have. *(Resolved in Rev Y: C2 chosen, S2 layered view host.)*
- **D7's design question stands.** Nothing writes an organiser lane, and `record_work_insight` now says so out loud.
- **`registerWidget` in `overview.js` has zero callers.** A descriptor-based widget registry, unused — a latent asset for C2 and dormant under C1.
- **Module access is inconsistent.** `/projects` and `/operations` route through ES imports; `/overview` and `/organisers` through `window.*` globals. `projects.js` alone does not use `modalManager`. That normalisation is owed under either WorkBench candidate.
- **15 Linux test failures remain uncharacterised** beyond their names.
- **`odysseus-android-widget` still has no remote**, so all widget history is single-copy on this machine.

# Rev Y (2026-09-02) — WorkBench chosen: C2 cockpit, S2 layered view host

Rev X left the unified WorkBench unchosen. It is now decided, and specified to the point where implementation can start. No implementation code was written.

## What was chosen

**C2 — Cockpit Drilldown**, over C1 (Tabbed Shell). Overview becomes the WorkBench home; cards and rows drill into the relevant module rendered on the same surface, with a back stack. Chosen on the two dimensions the user weighted: phone viewport, and the AI-integration phase that follows. Its accepted price is that the 120s two-tier SWR cache becomes load-bearing for every screen.

**S2 — Layered view host**, over S1 (body-swap strangler) and S3 (container-agnostic refactor). Views are sibling layers kept alive and toggled by the `hidden` property; the layer beneath is never re-rendered.

- **S1 was rejected** because back would re-render the home, and Overview's filter state would have to be captured and replayed — the state-capture machinery it was meant to avoid.
- **S3 was rejected as a starting point**, not as an end state. It is where this should eventually land, but it changes all four module lifecycles at once with no fallback, on a daily driver.

**Back must preserve scroll position and filter state.** This is what makes S2's memory cost worth paying, and is the reason S1 lost.

**Navigation uses the History API**, `pushState` per view, so the Android back gesture pops one level instead of closing the whole surface.

Three supporting choices: all layers stay resident with a memory-measurement gate and a defined eviction fallback; the five existing routes are reused as view URLs; and a view registry (`registerView` with `mount`/`unmount`) replaces direct module access.

## Findings that drove the decision

All were read from the code this session.

- **Overview already contains two ad-hoc drilldowns.** `data-drill-proj` (`overview.js:707`, wired at `:812`) navigates to a project, and `#overview-open-organisers-btn` (`:495`) calls `window.openOrganisers()`. C2's core gesture existed already, hardcoded twice. This made C2 substantially cheaper than the Rev X evaluation assumed.
- **`app.py` registers exact-path SPA handlers with no catch-all** (`:958`–`:976`). `/projects/abc123` would 404 on a hard reload, so drill identity must travel in query parameters rather than path segments. This settled the URL scheme.
- **`modalManager` is a minimize/restore registry, not a modal factory.** Its surface is `register/unregister/minimize/restore/toggle/close/injectMinimizeButton`. Rev X's note that `projects.js` alone does not use it remains accurate, but the gap is narrower than "a different modal system" — each module builds its own DOM regardless.
- **Overview's filter state is module-level**, not per-instance: `_emailDaysFilter`, `_emailAccountFilter`, `_emailUnreadOnly`, `_opsFilterSource`. Making Overview a view means moving these into instance state.
- ~~**`registerWidget` still has zero callers.**~~ Under C2 it folds into the view registry's descriptor rather than staying dormant. *(Done in Rev Z: deleted, folded into `registerView`.)*

**A consequence forced by S2:** the home is itself a layer, so `overview.js` stops owning a modal and becomes a registered view like the other four. The shell above it owns only the header, back control and layer stack.

## Specified but not built

Nine work packages were specified with obligations and done-conditions: shell, view registry, layer stack, history integration, the Overview-to-home refactor, the three module views, cache policy, and verification. The existing `openProjects/openOperations/openOrganisers/openOverview` entry points stay working — that is the reversibility guarantee, and deleting them is explicitly deferred to a later step.

Two verification items carry real risk. The memory gate is unmeasured: Operations alone renders roughly 200 rows in the live table read today, and five resident layers on the device is an open question — failing it triggers the eviction fallback. Live verification must happen at phone width on the device, consistent with the standing bar.

## Open

- ~~**Two spec clarifications are unanswered.**~~ Whether `/overview` should open the WorkBench-with-home or keep a standalone Overview modal in parallel; and whether D7's lane-writer belongs inside the WorkBench work, where an organiser view could own a "record insight" action, or stays a separate decision. *(Resolved in Rev Z for the first: `/overview` opens the WorkBench, and `openOverview()` survives as chrome around the same mount, so there is one renderer. The second stands.)*
- **D7's design question is now unblocked** but still undecided. It was tied to this choice, which has been made.
- **The 15 Linux test failures remain uncharacterised** beyond their names.
- **Five branches exist only locally** — `feature/agent-dev` and four `local-agent1-ops-*`. All are identical to `daily-driver` and carry no unique work; publishing or deleting them is undecided.

# Rev Z (2026-09-02/03) — WorkBench built, the Activity Log repaired, colour made themeable

Three deliveries. The first two are live on the phone; the third is built and
verified locally but not deployed.

## Corrections to Rev Y and to this session's own research

Rev Y's record of the decision stands. Several factual claims made while
executing it did not, and all were overturned by measurement rather than review.

- **The theme system writes 29 CSS variables, not five.** Five base, ten
  `--hl-*`, and fourteen "advanced" slots applied by looping `ADV_KEYS`
  (`theme.js:182`). The last fourteen are set indirectly — `setProperty(css, …)`
  over a table — which is why grepping for literal names missed them.
- **`--brand-color` is set at runtime.** It is `ADV_KEYS[4]`, defaulting to the
  accent. "Not defined anywhere" was true of the stylesheet and false of the
  running app.
- **The phone runs the `claude` theme, not `dark`.** `--bg #262624`,
  `--fg #f5f4f0`, `--panel #30302e`, `--red #c6613f`. The cyan `#9cdef2` quoted
  earlier is `style.css`'s `:root` default, measured on a local dev server with
  no stored theme.
- **There are 16 built-in themes, not 17.**
- **`#e8a33d` is not activityLog's invention.** It is the fallback of 54
  `var(--accent, #e8a33d)` usages across the app.

## The WorkBench, built — `f44d802`

Nine work packages from the Rev Y spec, in 630 lines of `static/js/workbench.js`
plus adapters in the four view modules. The shell owns header, back control and
layer stack; it owns no view content.

**Back preserves state because a covered layer is hidden, never destroyed.**
Verified live on the phone: home scrolled to 300 with the ops filter on
`curated`, drilled into Operations on a real record, and back restored **both**.
That is the property S2 was chosen for, and it is now measured rather than
argued.

Also verified live: three layers deep with `hidden` reading `[true,true,false]`;
a cold load of `/operations` synthesising the home layer beneath so one back
press lands on the cockpit; back at depth 1 tearing the surface down with no
empty shell; and all four `openX()` still opening standalone on `document.body`.

**Record identity travels in query params** — `/projects?project=…`,
`/operations?q=…` — because `app.py` registers exact-path SPA handlers with no
catch-all and `/projects/<id>` would 404 on reload.

**Two CSS overrides carry ids on purpose.** `style.css` and each module inset
their windows through id-scoped rules; a class-only selector cannot outrank
them, and without the overrides a layer rendered one sidebar-width narrow. Found
in the browser, not in review.

**`overview.js` stopped owning a modal.** Its four filter variables moved from
module scope into per-instance state, since two instances can now exist.
`openOverview()` survives as chrome around the same `mount()`, so there is one
renderer rather than two that can drift. `registerWidget` was deleted and folded
into `registerView` — it had no callers, and one registry beats two.

**Deployed with zero downtime.** Static files serve from disk under `no-cache`,
so the pull alone sufficed; pid 15394 never restarted.

**Two done-conditions were not met and are recorded as such.** The phone-width
layout (spec 1.4/8.3) was never visually confirmed — the browser window refused
to resize below 1874px, so only the media rule's presence on the device was
verified. The memory gate (8.2) was measured off-device: four resident layers
cost 2,773 DOM nodes with heap flat at ~14 MB, but not in the phone's own
browser. The eviction fallback (3.5) is therefore unimplemented, its trigger
unmeasured.

## The Activity Log, repaired — `210b62e`

The panel was both unreadable and untruthful. Both are fixed; the diagnosis of
each was wrong on the first attempt.

**Unreadable: a column flex container inheriting `align-items: center`.**
`#activity-log-modal` carried the `modal` class while setting its own
`flex-direction: column`. The base `.modal` rule's `align-items: center`
shrink-wraps every child to max-content in a column container, and
`.act-preview-text` is `white-space: nowrap` — so one long result string
stretched the list to **29,531px inside a 918px panel** and every row rendered
blank. The `text-overflow: ellipsis` already written was inert because the
element was never narrower than its own text.

**My first hypothesis was wrong and a probe caught it.** `min-width: 0` alone
changed nothing. Only `align-items: stretch` collapsed the list to 903px. The
panel already positioned and sized itself — it was always the
`.overview-modal` shape — so it now carries its own class and the base rule
cannot reach it.

**Untruthful: 18 of 57 rows recorded a total failure as a success**, with the
header reading `Errors: 0` throughout. `_result_is_config_error` matches three
phrases about missing model config, so a DNS failure fell through it, and
`_result_has_work` then answered "this run did work" for a report of nothing but
errors. A third predicate, `_pass_report_status`, reads what an account error
line actually looks like; the two existing predicates keep their names honest
rather than being widened into lies.

**Separately, 29 of 57 rows carried a status the log has no vocabulary for.**
`task_scheduler` mirrored `TaskRun`'s words — success, aborted, skipped — into a
log whose vocabulary is completed/running/error/fallback/halted. `success` had
no badge style, no filter option and no place in any count. `normalise_status`
is now a precondition of the logger itself, so no future writer can reintroduce
the leak; a caller-side fix would have needed repeating at every call site.

**Assets.** The module bound to `--bg-elev`, `--accent` and `--fg-muted`, none
of which are ever set, so every rule ran on a hardcoded Tailwind fallback and
the panel was theme-blind. It now uses the real variables, and a module-local
`ICONS` const of Feather SVG replaced five emoji — `checkCircle`, `alertCircle`
and `clock` copied byte-identically from `overview.js`.

**A migration was run beyond the spec's default.** Spec 7.1 chose to leave
history alone; on the device that meant 51% of visible rows would still render
the unstyled badge, which is the defect itself. Spec 7.2 sanctioned the
alternative as MAY, `app.db` was backed up minutes earlier, and 29 rows were
mapped `success → completed`. Zero illegal statuses remain.

**This deploy cost 6–8 minutes of downtime.** Unlike the WorkBench change it
touched Python. The probe loop read 300s of HTTP 000 while a process existed —
the Rev X trap again: this device's uvicorn boot outlasts an impatient wait, and
the supervisor cycled it once more before it listened. Pid went 15394 → 14363 →
15566, self-healed.

**Historical rows still read `COMPLETED` over pure error text.** The classifier
applies to new runs only. Re-classifying stored `result_preview` values was
deliberately not done: retroactively rewriting what an audit log *said* is a
heavier act than repairing an illegal vocabulary.

## Colour made themeable — `ecafbcd`, not yet deployed

**How themes actually work.** A theme is five colours; everything else derives
from them in HSL. `deriveSyntaxColors` sets the rule the codebase follows: hue
carries the meaning and is fixed (40 amber, 210 blue, 180 cyan, 20 orange),
saturation adapts to the theme clamped, lightness flips on `isDark = bgL < 50`.
A second layer, `generateHarmonyColors`, builds all five base colours from one
accent. Consumption is a cascade: `var(--slot, var(--theme-var, literal))`.

**`--red` is not red — it is the accent.** `terminal`'s is `#00ff41` green,
`ocean`'s `#4facfe` blue, `gpt`'s `#949494` grey. `computeAdvancedDefaults`
spends it on `brandColor`, `sendBtnBg`, `toggleActive` and the favicon.

**`deriveStatusColors` applies that rule to operation status**, emitting
`--status-error/warn/busy/ok/idle` from `applyColors` and from `index.html`'s
head script so the first paint is themed. Five modules consume them:
activityLog, overview, operations, workOrganisers, tasks — 29 usages.

**The spec's own `busy` design was overturned by its verification step.**
Passing the accent through failed twice: 2.24:1 against the panel on `paper`,
below the 3.0 gate; and on `terminal`, whose accent is green, `busy` and `ok`
landed **0.4° apart**, indistinguishable. A fifth fixed hue removed both
problems and deleted the one exception to the fixed-hue rule. Measured across
all 16 themes: worst contrast **3.61** (`cute`/ok), closest hue pair **33.2°**
(`paper`, error/warn).

Verified live by switching themes in the browser: `paper` yields dark tokens on
a white panel, `terminal` light tokens on black, and every badge tracks its
token exactly. Organiser priority badges and Overview urgency badges follow;
the urgency pair was proved with a mounted probe, the dev dataset having no
urgent mail.

**Suite across all three deliveries: 122 failed, 5816 passed, 2 errors** — the
same 122 as the Rev X baseline throughout, with 54 new tests added across the
three commits and no failure in any module touched.

## Measurements worth keeping

- **1,338 variable usages run permanently on their fallbacks**, across 20 names.
  `--accent` alone accounts for 1,073 and is never defined or set. It is not
  broken — 701 of those read `var(--accent, var(--red…))` and cascade correctly
  — it is an override slot nobody populates.
- **196 usages in `style.css` have no fallback at all.** Bare `var(--accent)` on
  `background` (62), `border-color` (36), `color` (27) and others. With the
  variable unset the declaration is invalid at computed-value time. How many are
  visibly wrong is unmeasured; CSSOM cannot enumerate them because shorthands
  expand to longhands that drop the `var()` token.
- **A documented semantic palette already exists and nothing themes it.**
  `style.css:14` names `--color-error --color-success --color-warning
  --color-danger`, defined as fixed hexes in `:root`: 259 usages between them.
  They were left alone — aliasing them onto the new tokens would theme 259 call
  sites in one move. *(Corrected in Rev AB: it is not one move. Roughly a third
  of those usages are backgrounds, and one alias cannot serve both text and
  fill. The header line reference is also stale — `2bba4ce` rewrote it.)*
- **The two derivation copies have drifted.** `index.html`'s `advMap` carries
  `--accent-primary`, `--accent-error`, `--section-accent` and `--toggle-bg`;
  `theme.js`'s `ADV_KEYS` carries none of them. A stored custom theme setting
  `accentPrimary` would have it applied on first paint and never again.
- **`style.css:13` is factually wrong.** It claims `--accent-primary` and
  `--accent-error` are "set by theme.js". Neither ever is.
- **`--green` is themed by nobody.** `#50fa7b` in every theme including the four
  light ones, while its sibling `--red` is fully themed.

## Decisions taken

- **WorkBench ships with `openX()` intact.** Deleting the standalone openers is
  the S3 end state and stays a later step.
- **Status is normalised at the logger, not at its callers.** One precondition
  beats four call sites that can each drift.
- **`--status-*` sits alongside `--color-*` rather than replacing it.** The
  right end state is one family; converting 259 call sites was outside the
  approved scope.
- **Status hues are fixed, not accent-derived.** An error must read as an error
  on a green-accented theme.
- **Audit history is not retroactively re-classified.** An illegal vocabulary
  was repaired; a past judgement was not rewritten.

## Open

- **The theme work is committed but not deployed.** `ecafbcd` is verified
  locally across four themes; the phone still renders status colour from
  literals until it is pulled.
- **Phone-width layout is unverified** for the WorkBench, and the memory gate
  was measured off-device.
- **259 `--color-*` usages remain unthemed**, and 196 bare `var(--accent)`
  usages remain fallback-less. *(Rev AB measured the first: it is not the
  one-line alias Rev Z promised — see there.)*
- **Two literals stay in activityLog** — a model pill and a latency badge.
  Neither is an operation status and no token means them.
- ~~**Two defects found while reading, unfixed:**~~ `activityLog.js` calls
  `makeWindowDraggable(_modal, dragHandle)` where `{content, header}` is
  required, so the drag handle has never worked; and `_render()` replaces the
  whole `innerHTML` every 3s, so the search box loses focus on each keystroke.
  *(Both fixed in Rev AA, `ac64323`.)*
- **`extract_email_events` cannot report a partial failure.** It has no direct
  log call, so its status reaches the log only through the scheduler's
  success/error boolean.
- **The 15 Linux test failures remain uncharacterised** beyond their names.
- **Five branches exist only locally**, all identical to `daily-driver`.

# Rev AA (2026-09-03) — two silent Activity Log defects, and a phone that went offline

## The phone is unreachable, and nothing was deployed

Rev Z's colour work (`ecafbcd`) and this entry's fixes are committed and pushed
but **not on the device**. Tailscale reports `galaxy-s24-ultra` as
`offline, last seen 5h ago`; six TCP attempts across three rounds to both 8022
and 7000 timed out, while this machine's own tailnet link stayed healthy.

**Nothing was mutated.** The backup never ran and neither did the pull, so the
phone sits at `210b62e` — the Activity Log repair — and still renders status
colour from literals.

The outstanding deploy is two commits, both static-only, so it needs no restart
and costs no downtime. `origin/daily-driver` carries everything.

## Two defects that produced no error

Both had been live since the module shipped in `c801984`, and neither was
caught by any test, because in both cases the code ran without complaint and
simply did nothing useful.

### The drag handle never worked

`makeWindowDraggable(modal, options)` reads `options.content` and
`options.header`, and returns immediately if either is missing
(`windowDrag.js:60`). The call passed a bare element where the options object
belongs, so both were `undefined` and the helper no-opped on every open.

**A wrong-shaped argument throws nothing and logs nothing.** Meanwhile
`.act-header` set `cursor: move`, so the panel advertised a gesture it could
not perform — the only visible symptom was a cursor that lied.

This panel is its own content: it has no `.modal-content` wrapper, unlike the
Operations and Projects windows. Docking stays off deliberately — the dock
rules are written `.modal.modal-right-docked …` and this panel is not a
`.modal`, so enabling it would add a class that styles nothing.

### Typing in the search box lost focus on every keystroke

`_render` assigned `_modal.innerHTML`, rebuilding the whole panel — including
the focused input and its caret. The `input` handler calls `_fetchLogs`, which
re-renders, so **each character replaced the element being typed into**. The 3s
poll did the same to an idle caret.

**The fix is the split, not a focus-restore hack.** `_buildChrome` writes the
panel and wires it once; `_render` touches only the four counters, the chip
counts and the row list. Row clicks became one delegated listener on the
container, since rows are the one thing that genuinely is replaced. `close()`
hides rather than destroys, so a reopen reuses the chrome and its listeners.

## Verified in a browser

- **Drag**: a real mousedown/mousemove/mouseup sequence moved the panel by
  exactly the delta — **+160x, +100y**.
- **Typing**: five characters kept the input as the same DOM node, focused,
  with a correctly advancing caret.
- **The poll**: a mid-word caret at position 2 survived **8.8 seconds across
  three polls**, unmoved.
- **Seven prior behaviours regression-checked**: expand and collapse, chip
  filtering with exclusive active state, status filtering (2 error rows, all
  genuinely `error`), reset to 8, close and reopen reusing the same element
  with listeners alive, and the dragged position surviving that reopen.

**Suite: 122 failed, 5831 passed, 2 errors** — the same 122 as the Rev X
baseline, with 15 more passing.

## A correction to this session's own test

**The first version of the new test was wrong, and the code was right.** It
asserted that every control is looked up at most once; `#act-list` is
legitimately addressed twice — once to wire the delegated row listener, once
for `_render` to write rows into. The assertion was rewritten to express the
real invariant (listeners attached once) rather than loosened to pass.

## Open

- ~~**Two commits are undeployed**~~ — `ecafbcd` and `ac64323`, plus this
  record. Both static-only; the phone needs `git pull --ff-only` when it
  returns. *(Deployed in Rev AB: the phone is at `5c0df2e`, zero downtime.)*
- **Each search keystroke still fires its own request.** It predates this work
  and is a rate concern, not a focus one.
- **259 `--color-*` usages remain unthemed**, and 196 bare `var(--accent)`
  usages remain fallback-less. *(Rev AB measured the first: it is not the
  one-line alias Rev Z promised — see there.)*
- **Phone-width layout is unverified** for the WorkBench, and its memory gate
  was measured off-device.
- **D7's lane-writer, the 15 Linux test failures, and five local-only
  branches** all stand from earlier revisions.

# Rev AB (2026-09-03) — the colour work deployed, and a promised one-liner withdrawn

## Deployed — the phone is at `5c0df2e`

The phone returned to the tailnet (`active; direct 192.168.0.209:39180`) and the
three outstanding commits went out together: `ecafbcd` status-colour derivation,
`ac64323` drag and search-focus fixes, `5c0df2e` the Rev AA record.

**Zero downtime.** All static, so `git pull` sufficed; pid 15566 was never
restarted and its `etimes` climbed unbroken through the deploy. Backup taken
first at `/root/odysseus-backups/colour-20260903-090334`, HEAD `210b62e`.

### The derivation reproduced its predicted values on the device

Under the `claude` theme the five tokens resolved to `#d2898b` error, `#cfab81`
warn, `#8db8ce` busy, `#87c596` ok, `#bb98cd` idle — identical to what the
offline sweep computed for `claude` before any of it shipped. All 78 badges
track their token.

### The truthfulness fix caught real failures in production

**The header reads `Errors: 21` where it read `Errors: 0` yesterday.** The cause
is visible in the log: while the phone was off the tailnet, email polling failed
repeatedly with `[Errno -3] Temporary failure in name resolution`. Those runs,
dated 06:00–08:04 today, are all correctly labelled `error`. Before this work
every one would have been recorded `success` and the header would still say
zero.

### Drag and focus verified on the device

Mousedown converted the centring transform into explicit `left/top`
(477px, 93px) and the move landed at exactly +120/+70. Typing `err` with the
caret at position 1 kept the input as the same DOM node, focused, caret intact,
across a five-second wait spanning two polls while the list re-rendered from 78
rows to 38.

**Two verification scripts hit a 45-second CDP timeout**, and the cause was not
the drag: awaiting `requestAnimationFrame` during the 3s poll, with 78 rows and
4,000-character previews re-rendering, was enough to stall the evaluate.
Synchronous versions ran fine. The chrome/render split removed the panel
rebuild, but the row list is still rebuilt wholesale on every poll. At 57 rows
this was invisible; at 78 it is measurable, and the log has no automatic
pruning.

## A promised one-liner withdrawn

**Rev Z said aliasing `--color-*` onto the derived tokens was "a one-line change
in `:root`". That was wrong, and measuring how those variables are consumed is
what showed it.**

| | `color` | `background` | `border` |
|---|---|---|---|
| `--color-error` | 54 | 20 | 23 |
| `--color-danger` | 11 | 6 | 4 |
| `--color-success` | 15 | 11 | 5 |
| `--color-warning` | 10 | **13** | 4 |

`--color-warning` is a fill more often than it is text. A token tuned for
text-on-panel contrast is a different problem as a background carrying text, and
one alias cannot serve both uses.

**About half the fills are tints** — `color-mix(… 12%, transparent)` — safe with
any hue. The rest are solid fills, roughly fourteen sites.

**Those fills already fail contrast today.** White on the current literals is
**1.95:1** at worst across the sixteen themes, with error best at 3.41. The
derived tokens give 1.77 worst. Aliasing would not introduce a failure; it would
leave an existing one differently broken — not a good enough reason to change
259 computed colours on a daily driver.

**Doing it properly needs a background-safe surface variant plus edits to those
fourteen fill sites.** That is a new member of the token family and a design
decision, so it was not taken unilaterally.

## The stylesheet header described a system that does not exist — `2bba4ce`

`style.css`'s variable header claimed `--accent-primary` and `--accent-error`
are "set by theme.js". Neither ever is. It listed five core variables as the
theme-public surface when `applyColors` writes 29, and gave no hint that `--red`
is the accent rather than a hue.

Rewritten to state which variables are written at runtime, which are fixed hex
that no theme touches, and which are override slots nobody fills — `--accent`
alone has 1,073 usages and is declared by no one. Comment-only; no selector,
declaration or value changed.

## Verification

Seven failures appeared in the stylesheet-adjacent run and all seven are
pre-existing. The one that targets `static/style.css` was proven so directly:
stashing the edit and running it against HEAD fails identically. All seven
appear in the pre-change baseline.

## Open

- **`2bba4ce` is undeployed.** Comment-only with no user-visible effect; it
  should ride along with the next change rather than justify its own deploy.
- **The `--color-*` unification is unresolved** and now has a measured shape:
  a surface variant plus fourteen fill sites.
- **The activity log re-renders every row every three seconds.** 78 rows today,
  growing, with no automatic pruning.
- **196 bare `var(--accent)` usages remain fallback-less**, and each search
  keystroke still fires its own request.
- **Phone-width layout is unverified** for the WorkBench, and its memory gate
  was measured off-device.
- **D7's lane-writer, the 15 Linux test failures, and five local-only
  branches** stand from earlier revisions.

# Rev AC (2026-09-03) — The three AI-integration modules measured against the live phone, then rebuilt

## What this rev is

No code changed. This is a `#frame` → `#research` → `#design` → `#spec` pass over the AI integrations in Overview, Operations and AI Work Organisers, performed in `odysseus-agent-1` (`local-agent-1`) and measured against the live phone instance rather than the local checkout. The spec is published at `https://claude.ai/code/artifact/319781bc-27e8-462e-83ec-f3473048c713` — nine sections, 49 numbered work packages, each carrying an obligation level and a done-condition.

## Why the phone, and not this checkout

Every email table in all three worktrees is empty. `email_message_index`, `email_summaries`, `email_body_preview_cache`, `email_ai_replies` and `email_urgency_alerts` hold zero rows in `odysseus-agent-1`, `odysseus-agent-2` and `odysseus-fork` alike, and `memory.json` is `[]` in each. Every fault in these modules is invisible here. The phone (`odysseus-data/`, Termux) holds 475 indexed emails, 99 summaries, 141 AI reply records, 7 organisers and 10 memories, so it is the only environment where these modules can be observed at all.

## Six measurements from the live instance

- **157 of 157** `per_uid` entries in `email_urgency_state_admin.json` carry only `reason`. No `snippet`, no `preview`, no `summary` on any row.
- **85 of 154** stream emails have a real stored summary in `email_summaries`, bullet-formatted with an explicit `Action:` / `Action items:` line.
- **4** distinct `reason` values across all 157 rows: `bulk marketing/newsletter` (80), `categorized by email metadata` (41), `action likely needed` (30), `urgent wording` (6).
- **5** populated tag facets: `action-needed` 31, `travel` 21, `receipt` 15, `calendar` 9, `bills` 3.
- **0** organisers with a linked project. All 7 hold `linked_project_ids` of `None` or `[]`.
- **0** memories whose category intersects an organiser lane. The 10 live memories are `fact`, `preference`, `identity`, `contact`; the lanes are `organisers:*`. The intersection is empty.

## The Overview email row prints itself twice, and the real summaries are unreachable

`overview_routes.py:146` composes `snippet` as `msg.get("snippet") or msg.get("preview") or ai_comm or ""`, and line 152 sets `ai_comment` to the same `ai_comm`. With no live row carrying a snippet or preview, both fields resolve to `reason` on every row, and `overview.js:634-635` renders both. The duplicate is total, not intermittent.

The stored summaries are fetched and then never used. The branch at `overview_routes.py:143` — `if not ai_comm and mid_clean in ai_summaries` — is unreachable, because `reason` is present on 100% of rows and always satisfies the preceding `or`. 85 real summaries are read out of SQLite on every request and discarded.

## The duration filter is a whole-payload parameter

`_emailDaysFilter` is sent to `/api/overview` as `email_days` (`overview.js:517`) and every duration click refetches (`overview.js:762-764`). The SWR cache is keyed `{owner}:{email_days}` (`overview_routes.py:504`, `:524`), so each duration holds a separate full-payload bucket carrying its own copy of the ops radar. The ops data itself is not date-filtered — `_fetch_operations_radar_data()` takes no days argument and returns `inquiries[:25]` unconditionally — so the observable effect is a forced refetch and re-render of a panel whose contents cannot change.

## Organiser keyword rules match subjects only

`_matches_rule` reads `email.get("snippet")` at `organisers_routes.py:249`, but `_get_recent_emails` selects no snippet or body column. Every keyword rule has been matching against the subject line alone. `email_body_preview_cache` holds one row on the phone, so a snippet source has to be established before anything is built on this matcher.

## The organiser edit form omits everything the API accepts

`update_organiser` accepts `icon`, `color`, `target_accounts`, `linked_project_ids`, `memory_lane`, `is_active` and `sort_order` (`organisers_routes.py:615-641`). The save payload at `workOrganisers.js:814-825` sends five fields: `name`, `ai_instructions`, `category_group`, `priority`, `rules`. Three of the user's reported faults reduce to this single omission:

- **Icons are fixed** because the form has no icon field. The user's own "Receipts and Payments" organiser carries the default `briefcase` for this reason. `_getIconSvg` also only maps six names, so a seventh organiser cannot be visually distinct anyway.
- **Linked tasks never work** because `linked_project_ids` is never sent, so the task query at `:515-517` is skipped entirely. 66 project tasks exist to link to.
- **Colour is unreachable** for the same reason.

## D7 answered: the memory tab is empty for a vocabulary reason

Rev X left this open as "nothing writes an organiser lane". Measured: nothing writes one, and nothing could match one if it did. The 10 live memories carry generic categories, the lanes are namespaced `organisers:*`, no memory text contains a slug, and the two read paths disagree with each other — the card badge uses `load_all()` with `category == category_group` (`:378-389`) while the tab uses `load(owner)` with `category in {memory_lane, category_group}` (`:303-345`). Different scoping, different predicate.

## Reply inference is blocked on data, not logic

All 475 indexed rows are INBOX. `_email_index_upsert` has exactly two call sites, both inside list and search handlers, both writing whichever folder is being viewed — the index is a side effect of browsing, not a sweep. `to_text` and `cc_text` are indexed and selected but never read by the matcher, so outbound mail cannot match a sender rule, because the sender is the user. `email_message_index` stores `message_id` and no `in_reply_to` or `references`, so reply chains cannot be reconstructed from it.

## A stale comment claims the Operations MCP server is inert. It is not.

`src/builtin_mcp.py:77-78` states the ops server is "Inert without `OPS_API_BASE_URL` and `OPS_AGENT_TOKEN`". Neither variable is read anywhere in the repository — those two lines are their only occurrence. `mcp_servers/ops_server.py` uses `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`, both of which are set in `odysseus-agent-1/.env` and match the parent `.bilweekend.env.local`. The comment describes an architecture that was replaced.

## Decisions taken

- **Summary slot resolves from `email_summaries`, falling back to the subject line.** `reason` is never eligible as body text; it becomes a triage chip. The action is parsed out of the summary into the blue pill.
- **Duration filters client-side.** One fetch per refresh at the widest window; `email_days` stops being a request parameter; Operations gains its own duration control.
- **Panels resize by grid track, not by free position.** Saved absolute rectangles do not survive the 1320px-desktop-to-390px-phone span, and both viewports are in daily use. Reorder reuses `dragSort.js`; no runtime dependency is added, the project still has none.
- **Live layout persists to `localStorage`, named presets to `user_prefs.json`.** A named preset should follow the user between desktop and phone; an in-flight drag position should not.
- **Categorisation gains an override table, and rules stay live.** `(owner, account_key, uid) → organiser_id` with an explicit exclusion. Overrides win, resolved in one shared function used by the HTTP route, the MCP server and the overview payload alike — three call sites computing membership independently is how the two memory counts drifted apart.
- **Memories get a new organiser lane, plus a labelled reference section.** New memories are written with `organisers:<slug>`; the 10 existing memories are not rewritten, and are surfaced per organiser through the rules the user already maintains. Embedding matching was rejected: a tab whose purpose is showing why things are grouped should not group by an unexplainable score.
- **Fixtures are derived from a scrubbed phone snapshot, not invented.** A hand-written fixture would naturally populate `snippet` and hide the duplicate-summary fault entirely. The done-condition is inverted deliberately: reverting the fix must break a test.
- **Section 4.1 was promoted ahead of the filter work.** Building an organiser filter on a matcher that silently ignores body text would under-report; the snippet fix lands first.

## Open

- **The snippet source is undecided.** Either `email_body_preview_cache` gets populated during indexing, or `email_message_index` gains a snippet column. This is the one item that could not be resolved from the code.
- **Whether the Overview modal is opened on the phone at all** is unverified. It decides whether the narrow-viewport constraint on saved layouts is load-bearing.
- **`email_ai_replies` holds 141 rows whose contents were not inspected.** Whether they carry sent text or generated suggestions decides whether drafting in the user's own voice has a corpus.
- **`work_organisers` does not exist in `odysseus-agent-1/data/app.db`.** That database is otherwise live — 66 tasks, 10+ projects — and predates the model. The app has not booted in this worktree since organisers landed.
- **The unified WorkBench remains unchosen**, carried forward from Rev X. Nothing in this rev depends on it.

## What was implemented

Sections
8, 9.1, 1, 2, 6, 5, 3 and 4 of the spec were implemented in the same session,
under `#code`. What stands unimplemented is section 7 (reply inference), 5.5-5.6
(the organiser category summary and its use as inference signal), and 9.2
(live verification on the phone).

## A revision-letter collision

`static/js/overview.js` carries a header referring to "SYSTEM_RECORD Rev Y" for
the WorkBench refactor that moved the Overview out of its own window. That is a
different Rev Y from this one, written by another worktree's session, and this
file holds only this entry under that letter. Whoever reconciles the two records
should renumber one of them; the code comment currently points at a revision
that does not describe what it claims.

## The snippet source, decided

Body text for organiser keyword rules comes from `email_body_preview_cache`,
joined into `_get_recent_emails`. No new fetching was added: the email module
already warms recent message bodies into that cache when a folder is listed
(`_schedule_recent_email_warm`), and the gap was purely that nothing read it.
A keyword appearing only in a message body now matches; one appearing only in a
subject still does.


## Section 7 implemented: the system can now see the user's own replies

The message index recorded whichever folder was being browsed, and nobody
browses Sent -- so it held 475 received messages and nothing the user wrote.
Section 7 is what closes that.

`index_sent_mail` in `routes/email_pollers.py` selects the Sent folder readonly,
fetches headers only, and upserts them into `email_message_index` under their
real folder name. Folder discovery reuses the candidate list the auto-summarize
pass already carries (`Sent`, `INBOX/Sent`, `Sent Items`, `[Gmail]/Sent Mail`,
`Sent Mail`). It is registered as the `index_sent_mail` builtin action, so it is
scheduled like any other recurring email task; `days_back` in the task prompt
controls the window, defaulting to 1 for a daily pass and taking a larger value
for a backfill. Capped at 500 messages per account per pass.

`email_message_index` gained `in_reply_to` and `references_hdr`, with a lazy
ALTER for databases that predate them -- verified against a populated 475-row
database, both columns added, no rows lost. The list parser now extracts both
from the RFC822 header it was already fetching, so the keys cost no extra
traffic.

Recipient matching is deliberately restricted to outbound mail. On a received
message the sender is the correspondent and the recipient is the user, so
matching recipients there would make a rule naming someone claim every message
addressed to them. `_matches_rule` therefore consults `to_text`/`cc_text` only
when the folder is a Sent folder.

The stream marks a row `replied` when the user's sent mail names its Message-ID
in `In-Reply-To` or `References`, ranks those above equivalent unanswered rows,
and shows a Replied badge. The lookup returns nothing until the Sent index is
populated, so ordering is unchanged for anyone who has not run the task.

## Decisions taken in this pass

- **Sent is fetched on a schedule**, headers only, daily by default with a
  backfill window available. The user sanctioned the traffic.
- **Body text for keyword rules comes from `email_body_preview_cache`**, joined
  in rather than fetched. No new IMAP traffic was added for it.
- **Recipient matching is outbound-only**, for the reason above.
- **7.5 (drafting in the user's voice) is not implemented.** The corpus now
  exists, but generation is a separate piece of work.


## Deployed and verified live (Rev AC)

Deployed by fast-forwarding `daily-driver` to this work -- `origin/daily-driver`
held nothing this branch lacked, so no merge was needed. The phone pulled inside
the proot guest, because running git from Termux against the guest's checkout
uses Termux's HOME and finds no deploy key. Backup first:
`odysseus-data/revac-backup-20260903-150039` holding app.db, memory.json,
scheduled_emails.db, the urgency state file and the previous HEAD sha.

The server was killed and rebuilt by the supervisor on its poll: down at
roughly 30s, new pid 15297 answering at 60s.

Measured against live mail after deploy, 30-day window, 50 rows:

| Condition | Before | After |
|---|---|---|
| Rows printing the same string twice | every row | 0 |
| Triage label rendered as body text | every row | 0 |
| Rows showing a real stored summary | 0 | 36 |
| Rows falling back to the subject | n/a | 14 |
| Rows with an empty body | n/a | 0 |
| Rows with an action pill | 0 | 24 |
| Organisers offered as filters | 0 | 7 |
| Rows carrying organiser membership | 0 | 50 of 50 |
| Rows matched to an organiser | 0 | 35 |
| Rows marked replied | 0 | 17 |

`index_sent_mail` was run once with a 90-day backfill, as sanctioned. It indexed
150 messages from `[Gmail]/Sent Mail` and 9 from `Sent`; 94 rows now carry
threading keys. Organiser coverage rose from 28 rows to 35 once sent mail was
present, which is recipient matching doing its work.

The action parser hit 24 of the 36 rows carrying a summary -- two thirds. The
remaining third are summaries that name no action, which is the correct outcome
rather than a parse failure.

## Still open after this rev

- **5.5 / 5.6** -- the AI category summary for an organiser, and feeding
  accumulated overrides back as inference signal. Neither started.
- **7.5** -- drafting in the user's voice. The corpus now exists; generation does not.
- **The Tasks tab and the two memory sections were not verified live.** Both are
  UI paths needing a browser; the payload they read was verified, the rendering
  was not.

# Rev AD (2026-09-03) — Navbar & sidebar grouped by workflow horizon

## The problem: an undifferentiated technical catalog

The sidebar previously dumped 15 tools into a flat `#tools-section` without
workflow hierarchy or temporal horizon. Operational tools used continuously
throughout the day (`Operations`, `Projects`, `AI Work Organisers`) sat directly
interleaved with personal time/thought cadence tools (`Calendar`, `Tasks`,
`Notes`, `Deep Research`) and occasional developer utilities (`Cookbook`,
`Compare`, `Gallery`, `Theme`).

## What was built

The sidebar information architecture is partitioned into high-signal daily
cadence sections:

1. **Persistent Inputs** (preserved):
   `New Chat`, `Search`, `Chats` (`#sessions-section`), `Email` (`#email-section`).
2. **Daily Work** (`#daily-work-section`, expanded by default):
   Business execution engine: `Operations`, `AI Work Organisers`, `Projects`.
3. **Planning & Focus** (`#planning-focus-section`, expanded by default):
   Personal agency and cadence: `Calendar`, `Tasks` (with `#assistant-notif-dot`),
   `Notes`, and `Deep Search` (`#tool-research-btn`).
4. **Utilities & System** (`#tools-section`, collapsed by default):
   `Overview`, `Brain`, `Library` (with `#library-new-doc-btn`), `Activity Log`
   (with `#activity-log-indicator`), `Compare`, `Cookbook`, `Gallery`, `Theme`.

## Invariants preserved

- **ID Invariance**: All 15 button element IDs (`#tool-operations-btn`,
  `#tool-organisers-btn`, etc.) and their `#rail-*` counterparts remain exactly
  as originally named. `modalManager.js`, `app.js` and `workOrganisers.js`
  continue to bind and route without changes.
- **Section Lifecycle Integration**: The two new sections adopt the standard
  `.section .section-header-flex` shape, automatically inheriting chevron
  injection, domino keyframe animations, and `localStorage['section-collapsed']`
  persistence from `static/js/section-management.js`.
- **Spatial Symmetry**: The collapsed `#icon-rail` is re-ordered to match the
  new vertical groupings, divided with `.rail-separator` elements so collapsing
  the sidebar preserves muscle memory.
- **Settings & UI Visibility**: `static/js/ui_visibility.js` and
  `tests/test_ui_visibility_js.py` updated to register `daily-work-section` and
  `planning-focus-section` with cascading visibility rules.
