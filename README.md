# TTS HTTP Gateway

Turns the text-to-speech (TTS) engines set up in Home Assistant into a plain web address: request the address with some text, and the speech comes back as audio. Anything that can fetch a URL can then use the voices you already have in Home Assistant, from a shell script to a phone app that lets you add your own speech engine.

You pick several engines in order, and each request falls back down the list: when the first engine (say Azure) fails, runs out of quota or is too slow, the next one (say Edge TTS) takes over.

[繁體中文](./README.zh-Hant.md)

## How it works

Each gateway has its own URL, `/api/tts_http_gateway/<name>_<random>`. The random part is the password (the same idea as [ha-mcp](https://github.com/homeassistant-ai/ha-mcp)'s secret path), so a client only needs the URL, without a token or headers.

A gateway tries its engines (Home Assistant `tts.*` entities) in order:

- Every request goes to the first engine. When an engine fails before producing its first audio, or the first audio timeout runs out, the next engine is tried.
- Once the audio has started, the engine can't change. An error after that only ends the audio early.
- When an engine's error message mentions an HTTP status, the engine is skipped for a while:
  - 429 (too many requests, or too many at once): 60 seconds
  - 401 or 403 (bad key or used-up quota): 1 hour
- Engines get the speech options converted for their integration (see [Speech options](#speech-options)), and only the ones they support; Home Assistant rejects options an engine doesn't know.
- Home Assistant's TTS file cache isn't written, or every sentence of every book would be saved as a file. Repeated sentences, like going back one, are still answered from the memory cache.
- The `X-TTS-Engine` response header names the engine that produced the audio.

## Requirements

- Home Assistant 2026.10 or newer
- At least one TTS entity

## Installation

With HACS:

1. Open this repository in HACS with the button below, and confirm adding it as a custom repository:

   [![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=yjlin0224&repository=ha_tts_http_gateway&category=integration)

   Or by hand: HACS → top-right menu → Custom repositories, enter `https://github.com/yjlin0224/ha_tts_http_gateway` with the type "Integration", then search for "TTS HTTP Gateway".
2. Download it.
3. Restart Home Assistant.

Without HACS: download `tts_http_gateway.zip` from GitHub Releases, extract it to `custom_components/tts_http_gateway` in the Home Assistant configuration directory, and restart Home Assistant.

## Configuration

Start setting it up with the button below, or go to Settings → Devices & services → Add integration → TTS HTTP Gateway:

[![Open your Home Assistant instance and start setting up TTS HTTP Gateway.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=tts_http_gateway)

| Field | Description |
| ----- | ----------- |
| Name | What Home Assistant shows; rename it any time. The URL is the name at creation in snake_case followed by 22 random letters and digits: "My Reader" gives `/api/tts_http_gateway/my_reader_<random>`. Other scripts are romanized, so 閱讀器 gives `yue_du_qi_<random>`; a name without letters or digits gives only the random part |
| Engines | Tried in the order selected. Put the fastest first and the most reliable last |
| Language | Language code passed to every engine, e.g. `zh-TW` |
| Speech rate, pitch, volume | The defaults for every request, in the units under [Speech options](#speech-options). Leave them empty for each engine's default |
| First audio timeout | How long an engine may take to produce its first audio (5 seconds by default) before the next one is tried. The last engine always gets at least 30 seconds |

The next step asks for each engine's voice, because voice names differ between platforms: `zh-TW-HsiaoChenNeural` on Azure and Edge, `cmn-TW-Wavenet-A` on Google Cloud. Engines that list their voices, like Azure Speech TTS, offer them in a dropdown; for the others, like Edge TTS, type the name. Leave a voice empty for the engine's default. The voices can also be changed later on the gateway's device page; see [Entities](#entities).

The URL is generated and can't be chosen. Once created, the integration's "Configure" shows the URL, and lets you change the engines, defaults and voices or generate a new URL. The new URL starts with the name at that time, and the old one stops working immediately.

## Usage

```
GET /api/tts_http_gateway/<name>_<random>?text=<text>
```

| Parameter | Description |
| --------- | ----------- |
| `text` | The text to speak, required; `message` works too |
| `rate`, `pitch`, `volume` | Speech options for this request, in the units under [Speech options](#speech-options), e.g. `rate=1.2&pitch=-2` |
| `voice` | The voice for this request, for every engine instead of each one's own; mostly for trying a voice out |
| `language` | The language for this request |

Each parameter overrides the setting of the same name; an empty or missing one keeps the setting.

### Speech options

Speech rate, pitch and volume use the gateway's own units, the same in the settings and in the URL, modeled on Google Cloud TTS:

| Option | Unit | Normal | Range |
| ------ | ---- | ------ | ----- |
| `rate` | A multiple of the normal speed, e.g. `1.2`; `1.2x` works too | `1` | 0.25 to 4 |
| `pitch` | Semitones up or down, e.g. `2` or `-1.5`; `2st` works too | `0` | -20 to 20 |
| `volume` | A percentage of the normal volume, e.g. `60`; `60%` works too | `100` | 0 to 100 |

Home Assistant only standardizes the voice; every integration names and scales the rest its own way. So each engine's platform has an adapter that converts the options to what that integration takes, and keeps them within what it can do:

| Integration | `rate` | `pitch` | `volume` |
| ----------- | ------ | ------- | -------- |
| [Edge TTS](https://github.com/hasscc/hass-edge-tts) | `1.5` → `+50%`, limited to 0.5 to 2 | Converted to Hz, the only unit Edge takes, as fits a female voice: `2` → `+24Hz` | `60` → `-40%` |
| [Azure Speech TTS](https://github.com/goerkasch/azure_tts) | Like Edge | `2` → `+2st`, exact | Not supported yet |
| [Microsoft TTS](https://github.com/pajeronda/microsoft) (pajeronda) | Like Edge | `2` → `+12%`, exact | `60` → `-40%` |
| [Google Cloud](https://www.home-assistant.io/integrations/google_cloud/) | `speed`, as is | As is, in semitones | `gain`: `50` → `-6` dB |
| [OpenAI TTS](https://github.com/sfortis/openai_tts) (sfortis) | `speed`, as is | Not supported | `gain_db`: `50` → `-6` dB, at least `-12` |
| [Kokoro TTS](https://github.com/beecho01/Kokoro-TTS) | `speed`, as is | Not supported | `volume_multiplier`: `50` → `0.5` |
| [Fish Audio](https://www.home-assistant.io/integrations/fish_audio/) | `speed`, limited to 0.5 to 2 | Not supported | Not supported |
| Any other integration, e.g. Home Assistant Cloud, Piper (Wyoming), ElevenLabs | Not passed | Not passed | Not passed |

Kokoro gets the voice as `persona` and Fish Audio as `voice_id`; the others as `voice`. Only Edge and Azure Speech TTS have been tried with a real engine; the other conversions follow those integrations' code. Integrations without entities, such as Baidu and Yandex, can't be picked as engines.

Every option can be left empty for the engine's default. Azure and Edge already speak at their loudest at the normal volume, so the volume can only make them quieter. While Azure Speech TTS doesn't take a volume, the volume jumps when a request falls back between Azure and Edge.

`POST` works as well, with the parameters in a form or a JSON object.

| Status | Meaning |
| ------ | ------- |
| 200 | Success; the body is audio (usually MP3) |
| 400 | Bad parameters, e.g. no `text`, or `rate`, `pitch` or `volume` not a number in its range |
| 404 | Wrong URL: no gateway has it |
| 503 | Every engine failed or is being skipped; the body lists their errors |

### Android: TTS Server

[TTS Server](https://github.com/jing332/tts-server-android) is an open-source Android app that adds speech engines to the system, so that every app that reads aloud, such as e-book readers, can use them. Add a custom TTS with this URL:

```
https://<Home Assistant URL>/api/tts_http_gateway/<name>_<random>?rate={{speakSpeed==0?'':speakSpeed>=50?1+(speakSpeed-50)/50:0.5+speakSpeed/100}}&text={{encodeURIComponent(speakText)}}
```

TTS Server's speed slider gives `speakSpeed` from 1 to 100, or 0 when the speed follows the system. The URL turns it into `rate`: 50 is `1` (normal), 100 is `2` and 1 is `0.51`, the range Azure and Edge can speak at, with each step below 50 as fine as each step above. At 0 it sends no rate, so the configured speech rate applies. Leave the header field empty.

### Example: Azure's free tier with Edge as the fallback

1. Install [Azure Speech TTS](https://github.com/goerkasch/azure_tts) with HACS and enter your Azure key; it creates `tts.azure_speech_tts`.
2. Create a gateway with the engines `tts.azure_speech_tts` and `tts.edge_tts`, in that order, and give both the voice `zh-TW-HsiaoChenNeural`, which both Azure and Edge have, so the voice doesn't change when a request falls back.

Azure's free tier (F0) allows 500,000 characters a month, 20 requests a minute and 1 request at a time, and answers 429 beyond that. The gateway then skips Azure for 60 seconds and uses Edge. Once the monthly quota is used up Azure answers 403, and the gateway tries it again every hour.

## Entities

Each gateway is a device with these entities:

- A text entity per engine, "*engine* voice", holding that engine's voice, the same as on the voices step of "Configure". Change it to switch the voice right away, without reloading the gateway; empty means the engine's default voice. Engines added to or taken out of the gateway get or lose theirs.
- A "Last engine" sensor whose state is the engine that produced the last audio. Its attributes:

  - `first_chunk_ms`: for the last request, the milliseconds from trying that engine to its first audio
  - `engines`: for each engine, `successes`, `failures`, `last_error`, and `cooldown_until` (when it's tried again, or `null` when it isn't being skipped)

The sensor's attributes change with every request, so they aren't recorded in the history. The counts start from zero again when Home Assistant restarts or the integration reloads.

## Limitations

- Anyone with the URL can use the gateway, and the URL can end up in the logs of a reverse proxy or of the app calling it. Connect over HTTPS, and generate a new URL if it leaks.
- HTTP statuses are only read from the text of error messages. An engine whose errors don't mention the status is never skipped and is tried first every time.
- An engine that times out isn't stopped: it keeps synthesizing in the background, which still counts towards its usage.
- All engines of a gateway get the same speech rate, pitch, volume and language; only the voice is set for each engine.

## Development

Requirements:

- [uv](https://docs.astral.sh/uv/) 0.13 or newer: Home Assistant 2026.10 needs Python 3.14.2 or newer, which older uv versions don't know
- [Task](https://taskfile.dev): every command runs through `task`; `task --list` lists them
- Node.js and pnpm: run `pnpm install` once to install cspell, [husky](https://typicode.github.io/husky/), commitlint and git-cliff. The pre-commit hook checks spelling, and the formatting with isort and black when Python files are staged; the commit-msg hook checks with commitlint that the commit message follows [Conventional Commits](https://www.conventionalcommits.org/) (with the Angular types; the rules are in `.commitlintrc.yaml`)
- On Windows, WSL with uv in it as well: Home Assistant doesn't support Windows, so the tests run in WSL

Common commands:

- `uv sync`: creates `.venv` with Home Assistant itself, for the editor's type checking
- `task fmt`: formats with isort and black at a line length of 99; `task lint` only checks
- `task test`: runs pytest. On Windows it runs in WSL, with the virtual environment at `~/.cache/uv-venvs/ha_tts_http_gateway` inside WSL
- `uv run python scripts/package.py --tar`: writes the integration's files as a tar to stdout, the same files as the release zip. Pipe it over SSH to a Home Assistant for development, e.g. `uv run python scripts/package.py --tar | ssh <host> "tar -x -f - -C <config directory>/custom_components/tts_http_gateway"` (the target directory must exist). Reload the integration afterwards, or restart Home Assistant after the first copy

### Releasing

Branching follows GitHub Flow (set in `.gitflow` for [git-flow-next](https://git-flow.sh)): there are only `main` and `feature/*`, no release branches, and a release is a tag on `main`.

1. Set `version` in `custom_components/tts_http_gateway/manifest.json` and `pyproject.toml` to the new version and commit it to `main`.
2. On `main`, run `task release VERSION=0.1.0` (a [SemVer](https://semver.org/) version without the `v`). It first checks that:
   - you're on `main` with no uncommitted changes, and in step with `origin/main`
   - the tag `v0.1.0` exists neither locally nor on `origin`
   - both `version` fields are `0.1.0`

   It then runs the formatting check, the tests, the spelling check and `task release:snapshot`, and when they all pass, creates the signed tag `v0.1.0` and pushes it.
3. The pushed tag makes GitHub Actions check again: that the tag is on `main`, the version, formatting, tests, spelling, and the hassfest and HACS checks. Only then is the GitHub release created with `tts_http_gateway.zip`, the file HACS installs.

To see what would be released without publishing, run `task release:snapshot`; the zip and the release notes go to `dist/`.

## License

[MIT](./LICENSE)
