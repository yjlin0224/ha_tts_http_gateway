# CLAUDE.md

用一般的 HTTP 網址提供 Home Assistant TTS 引擎、並依序 fallback 的自訂整合（domain `tts_http_gateway`）。先讀 `README.md`。用繁體中文回覆使用者。

## 背景：Home Assistant TTS 的行為（讀 2026.10 原始碼得出）

- gateway 透過 `hass.data[DATA_TTS_MANAGER].async_create_result_stream(..., use_file_cache=False)` 建立串流，再呼叫 `async_set_message`。公開的 `tts.async_create_stream` 不能關掉檔案快取，所以用內部的 SpeechManager；Home Assistant 改版時先檢查這裡。
- 合成在背景 task（`TTSCache.async_load_data`）裡進行，gateway 只是讀取者。引擎在 gateway 讀到第一段之前就出錯的話，`async_stream_data` 一開始就會拋出錯誤，即使引擎已經吐出部分音訊，所以這種情況也能 fallback。測試「音訊開始後才出錯」時，假引擎要在兩段之間 `await` 一下。
- 背景 task 不會因為 gateway 放棄而停止：逾時的引擎會繼續合成，結果留在記憶體快取裡。
- `process_options` 會拒絕引擎 `supported_options` 以外的選項，也會拒絕 `supported_languages` 以外的語言，所以 gateway 只傳引擎支援的語音選項。
- edge-tts 7.3 驗證 `rate`、`volume` 要符合 `^[+-]\d+%$`、`pitch` 要符合 `^[+-]\d+Hz$`，不合就拋 `ValueError`。轉換器輸出的一定是這種格式。Edge 的 pitch 只收 Hz，轉換器用女聲基頻 200 Hz 近似（`EDGE_PITCH_BASE_HZ`）；Azure 直接用半音。Microsoft 語音服務只能唸 0.5～2 倍速，正常音量就是最大聲。gateway 沒有 0～100 的 `speed`：用戶端自己換算成 `rate`，README 有 TTS Server 的範本。
- 引擎回報錯誤的方式各不相同：goerkasch/azure_tts 拋出 `HomeAssistantError("Azure TTS failed with HTTP 429: ...")`；hass-edge-tts 拋出 `NoAudioReceived` 轉成的 `HomeAssistantError`。HTTP 狀態碼只能從錯誤文字解析（`gateway.http_status`）。
- 檔案快取的檔名 regex 要求 engine 是 `tts.` 開頭，但 gateway 不寫檔案快取，所以不受影響。

## 檔案與指令

- `custom_components/tts_http_gateway/`：
  - `gateway.py`：`Gateway` 依序嘗試引擎、冷卻和統計。
  - `speech.py`：語音選項（voice、rate、pitch、volume）的單位以 Google Cloud TTS 為準：rate 是倍數（1 正常，0.25～4），pitch 是半音（0 正常，-20～20），volume 是正常音量的百分比（100 正常，0～100）。設定和網址參數都用這套單位，`parse_option` 解析。`ADAPTERS` 依實體註冊表的 `platform` 把它們轉成各整合的名稱和格式，再只留引擎 `supported_options` 裡有的；沒有轉換器的平台只拿到 voice。新增平台就是在 `ADAPTERS` 加一個函式。各平台參數的調查結果在 README 的 Speech options。目前只有 Edge 和 Azure Speech TTS 實機測過；pajeronda/microsoft、google_cloud、sfortis/openai_tts、Kokoro、fish_audio 的轉換器是照它們的原始碼寫的，只有單元測試。legacy provider（百度、Yandex、核心的 microsoft）沒有實體，選不到。
  - `view.py`：`/api/tts_http_gateway/{endpoint}` 的 GET／POST，解析參數、串流回應。沒有 token：endpoint 的隨機部分就是密鑰，錯誤的 endpoint 一律回 404，不透露任何資訊。
  - `config_flow.py`：兩頁，第二頁 `voices` 是每個引擎各自的聲音（欄位名稱是實體 ID，存成 options 的 `voices`），聲音清單來自實體的 `async_get_supported_voices`，沒有清單（例如 Edge）就是文字欄位。網址的 `voice=` 會取代所有引擎的聲音。entry 版本 1.2；1.1 的單一 `voice` 由 `async_migrate_entry` 複製給每個引擎。endpoint 是名稱的 slugify 加 22 個隨機英數字（仿 ha-mcp 的 secret path），存在 entry 的 `data`，使用者不能自訂；名稱只是 entry 的標題，可以隨時改。引擎等設定放在 `options`。沒有 unique ID，同名的 gateway 靠隨機部分區分。
  - `sensor.py`：「最後使用的引擎」感測器，屬性不寫入 recorder。
  - `text.py`：每個引擎一個聲音文字實體（unique ID `<entry_id>_voice_<engine>`），跟 options 的 `voices` 是同一份。改值時直接更新 `gateway.voices` 和 `gateway.loaded_options` 再存回 options；`_async_update_listener` 看到 options 跟 `loaded_options` 相同就不重新載入。引擎被移出清單時，setup 會把它的聲音實體從實體註冊表移除。
  - `translations/en.json`、`translations/zh-Hant.json`：兩份要一致。自訂整合不用 `strings.json`。
- `tests/`：`conftest.py` 用 `MockModule`／`MockPlatform` 載入假的 `tts.first`（非串流，像 Azure 沒有 volume）和 `tts.second`（串流，像 Edge），並讓它們的平台使用 Edge 的轉換器。
- 所有指令都透過 `task`（`task --list`）執行；`package.json` 只放 Node 工具（`prepare`、`spell`）。
  - `task fmt`、`task lint`：isort 和 black，設定在 `pyproject.toml`（行寬 99）。
  - `task test`：pytest。Home Assistant 用到 `fcntl`，不能在 Windows 上執行，所以在 Windows 上會透過 `wsl.exe` 在 WSL 裡跑，虛擬環境用 `UV_PROJECT_ENVIRONMENT` 指到 WSL 的 `~/.cache/uv-venvs/ha_tts_http_gateway`，不跟 Windows 的 `.venv` 共用。
  - `task spell`：cspell。新的專有名詞加進 `cspell.config.yaml`。
  - `deploy.bat`：不在 git 裡（`.gitignore` 忽略 `*.bat`），因為主機和路徑是使用者這台電腦的設定。它把 `scripts/package.py --tar` 的輸出經 SSH 解開到使用者 Home Assistant 的 `custom_components/`，取代舊的版本。不用 `tar` 指令打包，是因為 Task 在 Windows 上會換成它內建、不支援 `-C` 相對路徑的 tar，而且 `package.py` 在每個平台排除的檔案都一樣。複製後要重新載入整合（第一次要重新啟動 Home Assistant），這兩件事都要先問使用者。
  - `task release:snapshot`：產生 `dist/tts_http_gateway.zip` 和發布說明，不發布。
  - `task release VERSION=X.Y.Z`：檢查後建立有簽章的 `vX.Y.Z` tag 並推送，會觸發 `release.yaml`。**這是對外發布，只有使用者明確要求時才執行。**
- **要同步的地方：**
  - 版本在 `manifest.json` 和 `pyproject.toml` 各一份，`scripts/check_version.py` 會檢查。
  - `pytest-homeassistant-custom-component` 固定了 Home Assistant 的版本；升級時一起更新 `hacs.json` 的 `homeassistant`，以及 `ha-ffmpeg`、`mutagen`（照 Home Assistant 裡 `ffmpeg`、`tts` 的 `manifest.json`）。
  - git-cliff 的版本只在 `package.json`（精確版本），CI 也用 pnpm 安裝。
  - `README.md`（英文，主要）和 `README.zh-Hant.md`（繁中）內容要一致。HACS 和 GitHub 顯示的是 `README.md`。

## commit message

嚴格的 Conventional Commits，type 照 Angular convention。husky 的 `commit-msg` hook 會用 commitlint（`.commitlintrc.yaml`）檢查。

- 英文。主旨用祈使句、小寫開頭、結尾不加句點，說**改了什麼**；標題（含 type）最多 72 字元。
- **不加 scope**：只有一個整合，寫 `fix:`，不寫 `fix(view):`。
- **一定要有 body**：主旨下空一行，用散文寫具體改了什麼（檔案、函式），再寫為什麼，以及什麼刻意沒動。
- 不相容的變更在 type 後面加 `!`（例如 `feat!:`），會列在發布說明的「Breaking changes」。
- 一筆 commit 只做一件事。

type 依**改動的性質**選，不是依改到哪種檔案：

| type | 用途 |
|---|---|
| `feat` | 使用者看得到的新功能或行為 |
| `fix` | 修正錯誤的行為 |
| `perf` | 只改善效能，行為不變 |
| `refactor` | 重構，行為和效能都不變 |
| `style` | **只有**不改變意義的格式調整（black、isort、空白）。外觀或行為的改變是 `feat` 或 `fix` |
| `test` | 只動測試 |
| `docs` | 只動文件（README、CLAUDE.md、註解） |
| `build` | 建置系統或依賴（`pyproject.toml`、`uv.lock`、`package.json`、`Taskfile.yaml`、`cliff.toml`、`scripts/`） |
| `ci` | CI 設定（`.github/workflows/`） |
| `chore` | 其他不影響程式的雜務（拼字字典、hook、編輯器設定） |
| `revert` | 還原先前的 commit |

翻譯檔（`translations/`）的修改是 `feat` 或 `fix`，因為使用者看得到。git-cliff 的發布說明只列 `feat`、`fix`、`perf`、`revert`，以及標了 `!` 的 commit（`cliff.toml`）。

## 分支與發布

- 使用 git-flow-next，設定在可以 commit 的 `.gitflow`；修改後用 `git flow config sync` 同步到 `.git/config`。
- 嚴格的 GitHub Flow：只有 `main`（base）和 `feature/*`（topic）。不要加 `develop`、`release/*`、`hotfix/*`、`chore/*`、`fix/*`；修 bug、雜務也都用 `feature/*`。
- `feature.finish` 設定了 `keep = true`（finish 後保留分支）和 `push = true`（finish 後把 `main` 推到 `origin`）。保留分支是使用者的偏好，跟標準 GitHub Flow 不同，不要改回去。
- 發布就是在 `main` 上打 tag，沒有 release 分支。使用者的 git 設定了 `commit.gpgsign`，但沒有設定 `tag.gpgSign`，所以 `task release` 明確使用 `git tag --sign`。
- HACS 用 `hacs.json` 的 `zip_release` 安裝 release 附的 `tts_http_gateway.zip`，zip 裡直接是整合的檔案（`scripts/package.py`）。版本取自 tag，所以 tag 必須跟 `manifest.json` 一致。
- CI 的 HACS 檢查忽略 `brands`：只有預設商店裡的整合才需要在 home-assistant/brands 登記。

## 慣例

- 所有純文字檔都是 **LF、UTF-8、無 BOM**，`.gitattributes` 已固定 `eol=lf`。用 Python 寫檔時要注意 `newline` 和 `encoding`。
- 程式碼、註解和發布說明用英文；README 以英文為主，另有繁中版。
- 除非使用者要求，否則不要 commit 或 push。

## 驗證方式

- 單元測試（`task test`）涵蓋 fallback、冷卻、逾時、音訊開始後的錯誤、參數、錯誤的 endpoint 和設定流程。
- 實機測試在使用者的 Home Assistant 上進行：執行 `deploy.bat` 後重新載入，用 curl 打 gateway，檢查 `X-TTS-Engine` 和感測器屬性。
- 使用者的 Azure 是免費方案 F0：每分鐘 20 個請求、同時 1 個、每月 50 萬字。測試時不要連續大量請求，也不要把金鑰印出來；金鑰只存在 Azure Speech TTS 整合裡。
