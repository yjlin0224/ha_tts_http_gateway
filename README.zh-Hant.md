# TTS HTTP Gateway

把 Home Assistant 裡設定好的文字轉語音（TTS）引擎變成一個網址：帶著文字請求這個網址，就會拿到朗讀的音訊。只要能讀取網址的程式，都能使用你在 Home Assistant 裡已經有的聲音，從 shell 腳本，到可以自己加入朗讀引擎的手機 App 都行。

你可以依序選擇好幾個引擎，每個請求會逐一往下 fallback：第一個引擎（例如 Azure）出錯、額度用完或太慢時，改由下一個（例如 Edge TTS）接手。

[English](./README.md)

## 運作方式

每個 gateway 有自己的網址 `/api/tts_http_gateway/<名稱>_<隨機字串>`。隨機字串就是密碼（跟 [ha-mcp](https://github.com/homeassistant-ai/ha-mcp) 的 secret path 相同的做法），呼叫它的程式只要填網址，不用另外帶 token 或標頭。

gateway 依序嘗試它的引擎（Home Assistant 的 `tts.*` 實體）：

- 每個請求先交給第一個引擎。引擎在產生第一段音訊前出錯，或超過「首段音訊逾時」，就改試下一個。
- 音訊一開始送出，就不能再換引擎。之後才發生的錯誤只會讓音訊提早結束。
- 引擎的錯誤訊息提到 HTTP 狀態碼時，會暫時跳過它：
  - 429（請求太頻繁或同時請求太多）：跳過 60 秒
  - 401、403（金鑰錯誤或額度用完）：跳過 1 小時
- 語音選項會轉成各整合接受的格式（見[語音選項](#語音選項)），而且只傳引擎支援的；Home Assistant 會拒絕引擎不認得的選項。
- 不寫入 Home Assistant 的 TTS 檔案快取，否則每本書的每一句都會存成檔案。重複的句子（例如倒回上一句）仍然會由記憶體快取直接回應。
- 回應的 `X-TTS-Engine` 標頭標示這段音訊是哪個引擎產生的。

## 需求

- Home Assistant 2026.10 以上
- 至少一個 TTS 實體

## 安裝

用 HACS：

1. 按下面的按鈕在 HACS 開啟這個存放庫，並確認加入為自訂存放庫：

   [![在你的 Home Assistant 中用 HACS 開啟這個存放庫。](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=yjlin0224&repository=ha_tts_http_gateway&category=integration)

   也可以手動加入：HACS → 右上角選單 → 自訂存放庫，存放庫填 `https://github.com/yjlin0224/ha_tts_http_gateway`，類型選「Integration」，再搜尋「TTS HTTP Gateway」。
2. 下載。
3. 重新啟動 Home Assistant。

不用 HACS：從 GitHub Releases 下載 `tts_http_gateway.zip`，解壓縮到 Home Assistant 設定資料夾的 `custom_components/tts_http_gateway`，再重新啟動 Home Assistant。

## 設定

按下面的按鈕開始設定，或到 設定 → 裝置與服務 → 新增整合 → TTS HTTP Gateway：

[![在你的 Home Assistant 中開始設定 TTS HTTP Gateway。](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=tts_http_gateway)

| 欄位 | 說明 |
| ---- | ---- |
| 名稱 | Home Assistant 顯示的名稱，之後隨時可以改。網址用建立時的名稱轉成 snake_case，再加上 22 個隨機英數字，例如「My Reader」會產生 `/api/tts_http_gateway/my_reader_<隨機字串>`。中文會轉成拼音，例如「閱讀器」會變成 `yue_du_qi_<隨機字串>`；沒有任何字母或數字的名稱只會有隨機字串 |
| 引擎 | 依選擇的順序嘗試。最快的放第一個，最可靠的放最後 |
| 語言 | 傳給每個引擎的語言代碼，例如 `zh-TW` |
| 語速、音高、音量 | 每個請求的預設值，單位見[語音選項](#語音選項)。留空就用各引擎的預設值 |
| 首段音訊逾時 | 引擎產生第一段音訊的時間上限（預設 5 秒），超過就改試下一個。最後一個引擎至少有 30 秒 |

下一頁設定每個引擎的聲音，因為不同平台的聲音名稱不一樣：Azure 和 Edge 是 `zh-TW-HsiaoChenNeural`，Google Cloud 是 `cmn-TW-Wavenet-A`。會提供聲音清單的引擎（例如 Azure Speech TTS）可以從下拉選單選；其他引擎（例如 Edge TTS）要自己輸入名稱。留空就用那個引擎的預設聲音。之後也可以在 gateway 的裝置頁面修改聲音，見[實體](#實體)。

網址是自動產生的，不能自己指定。建立後，在整合的「設定」裡可以看到網址、修改引擎、預設值和聲音，或產生新的網址。新網址以當時的名稱開頭，舊網址會立即失效。

## 使用方式

```
GET /api/tts_http_gateway/<名稱>_<隨機字串>?text=<文字>
```

| 參數 | 說明 |
| ---- | ---- |
| `text` | 要朗讀的文字，必填；也可以寫成 `message` |
| `rate`、`pitch`、`volume` | 這次請求的語音選項，單位見[語音選項](#語音選項)，例如 `rate=1.2&pitch=-2` |
| `voice` | 這次請求的聲音，會取代所有引擎各自的聲音；主要用來試聽聲音 |
| `language` | 這次請求使用的語言 |

每個參數都會覆蓋同名的設定；留空或沒帶就沿用設定。

### 語音選項

語速、音高和音量用 gateway 自己的單位，設定和網址參數都一樣，以 Google Cloud TTS 為準：

| 選項 | 單位 | 正常值 | 範圍 |
| ---- | ---- | ------ | ---- |
| `rate` | 正常速度的倍數，例如 `1.2`；也可以寫 `1.2x` | `1` | 0.25～4 |
| `pitch` | 升降幾個半音，例如 `2`、`-1.5`；也可以寫 `2st` | `0` | -20～20 |
| `volume` | 正常音量的百分比，例如 `60`；也可以寫 `60%` | `100` | 0～100 |

Home Assistant 只統一了聲音這個選項，其他選項每個整合的名稱和單位都不一樣。所以每個引擎的平台都有一個轉換器，把選項轉成那個整合接受的格式，並限制在它做得到的範圍內：

| 整合 | `rate` | `pitch` | `volume` |
| ---- | ------ | ------- | -------- |
| [Edge TTS](https://github.com/hasscc/hass-edge-tts) | `1.5` → `+50%`，限制在 0.5～2 | 換算成 Edge 唯一接受的 Hz，以女聲為準：`2` → `+24Hz` | `60` → `-40%` |
| [Azure Speech TTS](https://github.com/goerkasch/azure_tts) | 同 Edge | `2` → `+2st`，精確 | 目前不支援 |
| [Microsoft TTS](https://github.com/pajeronda/microsoft)（pajeronda） | 同 Edge | `2` → `+12%`，精確 | `60` → `-40%` |
| [Google Cloud](https://www.home-assistant.io/integrations/google_cloud/) | `speed`，直接使用 | 直接使用，單位是半音 | `gain`：`50` → `-6` dB |
| [OpenAI TTS](https://github.com/sfortis/openai_tts)（sfortis） | `speed`，直接使用 | 不支援 | `gain_db`：`50` → `-6` dB，最低 `-12` |
| [Kokoro TTS](https://github.com/beecho01/Kokoro-TTS) | `speed`，直接使用 | 不支援 | `volume_multiplier`：`50` → `0.5` |
| [Fish Audio](https://www.home-assistant.io/integrations/fish_audio/) | `speed`，限制在 0.5～2 | 不支援 | 不支援 |
| 其他整合，例如 Home Assistant Cloud、Piper（Wyoming）、ElevenLabs | 不傳 | 不傳 | 不傳 |

聲音在 Kokoro 會傳成 `persona`、在 Fish Audio 傳成 `voice_id`，其他都是 `voice`。只有 Edge 和 Azure Speech TTS 用真的引擎試過，其他的轉換是照著那些整合的程式碼寫的。沒有實體的整合（例如百度、Yandex）不能選為引擎。

每個選項都可以留空，留空就用引擎的預設值。Azure 和 Edge 的正常音量就已經是最大聲，所以音量只能調小。在 Azure Speech TTS 支援音量之前，請求在 Azure 和 Edge 之間 fallback 時，音量會跳動。

也可以用 `POST`，參數放在表單或 JSON 物件裡。

| 狀態碼 | 意義 |
| ------ | ---- |
| 200 | 成功，內容是音訊（通常是 MP3） |
| 400 | 參數錯誤，例如沒有 `text`，或 `rate`、`pitch`、`volume` 不是範圍內的數字 |
| 404 | 網址錯誤，沒有對應的 gateway |
| 503 | 所有引擎都失敗或正在暫停，內容是各引擎的錯誤原因 |

### Android：TTS Server

[TTS Server](https://github.com/jing332/tts-server-android) 是開源的 Android App，可以替系統加入朗讀引擎，讓電子書閱讀器等會朗讀的 App 都能使用。新增「自訂 TTS」，網址填：

```
https://<Home Assistant 網址>/api/tts_http_gateway/<名稱>_<隨機字串>?rate={{speakSpeed==0?'':speakSpeed>=50?1+(speakSpeed-50)/50:0.5+speakSpeed/100}}&text={{encodeURIComponent(speakText)}}
```

TTS Server 的語速拉桿會給出 1～100 的 `speakSpeed`，選「跟隨系統」時是 0。網址會把它換算成 `rate`：50 是 `1`（正常），100 是 `2`，1 是 `0.51`，剛好是 Azure 和 Edge 做得到的範圍，而且 50 以下每一格的變化跟 50 以上一樣細。0 時不送語速，改用設定裡的語速。頭欄位留空。

### 範例：Azure 免費方案加 Edge 備援

1. 用 HACS 安裝 [Azure Speech TTS](https://github.com/goerkasch/azure_tts) 並輸入 Azure 金鑰，會建立 `tts.azure_speech_tts`。
2. 建立 gateway，引擎依序選 `tts.azure_speech_tts`、`tts.edge_tts`，兩個的聲音都設成 `zh-TW-HsiaoChenNeural`（Azure 和 Edge 都有這個聲音），fallback 時聲音才不會改變。

Azure 免費方案（F0）每月 50 萬字、每分鐘 20 個請求、同時只能處理 1 個請求，超過時會回應 429。這時 gateway 會讓 Azure 暫停 60 秒、改用 Edge；額度用完時會回應 403，暫停 1 小時後再試。

## 實體

每個 gateway 是一個裝置，底下有這些實體：

- 每個引擎一個文字實體「*引擎* 聲音」，存放那個引擎的聲音，跟「設定」第二頁的聲音是同一份。修改後馬上生效，不用重新載入 gateway；留空就用引擎的預設聲音。gateway 增減引擎時，這些實體也會跟著增減。
- 「最後使用的引擎」感測器，狀態是最後一次產生音訊的引擎。屬性：

  - `first_chunk_ms`：最後一次請求，從開始嘗試那個引擎到收到第一段音訊的毫秒數
  - `engines`：每個引擎的 `successes`（成功次數）、`failures`（失敗次數）、`last_error`（最後一次的錯誤）、`cooldown_until`（暫停到什麼時候，沒有暫停時是 `null`）

每個請求都會改變感測器的屬性，所以屬性不寫入歷史紀錄；Home Assistant 重新啟動或重新載入整合後，計數會歸零。

## 限制

- 知道網址就能使用，而網址可能出現在反向代理或呼叫它的程式的紀錄中。請透過 HTTPS 連線，外流時就產生新的網址。
- 只能從錯誤訊息的文字判斷 HTTP 狀態碼。錯誤訊息沒有提到狀態碼的引擎不會被暫停，每次都會先試它。
- 逾時的引擎不會被中斷，它會在背景繼續合成，仍然會計入它的用量。
- 每個 gateway 的所有引擎共用同一組語速、音高、音量和語言；只有聲音是每個引擎各自設定。

## 開發

需要：

- [uv](https://docs.astral.sh/uv/) 0.13 以上：Home Assistant 2026.10 需要 Python 3.14.2 以上，較舊的 uv 找不到這個版本
- [Task](https://taskfile.dev)：所有指令都透過 `task` 執行，`task --list` 列出全部
- Node.js 與 pnpm：先執行一次 `pnpm install`，安裝 cspell、[husky](https://typicode.github.io/husky/)、commitlint 與 git-cliff。pre-commit hook 會檢查拼字，暫存了 Python 檔案時再用 isort 和 black 檢查格式；commit-msg hook 會用 commitlint 檢查 commit message 是否符合 [Conventional Commits](https://www.conventionalcommits.org/zh-hant/)（type 採 Angular convention，規則見 `.commitlintrc.yaml`）
- Windows 上還需要 WSL，裡面也要裝 uv：Home Assistant 不支援 Windows，測試會在 WSL 裡執行

常用指令：

- `uv sync`：建立 `.venv`，裡面有 Home Assistant 本身，給編輯器做型別檢查
- `task fmt`：用 isort 和 black 格式化，行寬 99；`task lint` 只檢查不修改
- `task test`：執行 pytest。在 Windows 上會改在 WSL 裡執行，虛擬環境放在 WSL 的 `~/.cache/uv-venvs/ha_tts_http_gateway`
- `uv run python scripts/package.py --tar`：把整合的檔案打包成 tar 輸出到 stdout，跟 release 的 zip 內容相同。可以接 SSH 複製到開發用的 Home Assistant，例如 `uv run python scripts/package.py --tar | ssh <主機> "tar -x -f - -C <設定資料夾>/custom_components/tts_http_gateway"`（目標資料夾要先存在）。複製後要重新載入整合；第一次複製則要重新啟動 Home Assistant

### 發布

分支採用 GitHub Flow（設定在 `.gitflow`，給 [git-flow-next](https://git-flow.sh) 使用）：只有 `main` 和 `feature/*`，沒有 release 分支，發布就是在 `main` 上打 tag。

1. 把 `custom_components/tts_http_gateway/manifest.json` 和 `pyproject.toml` 的 `version` 改成新版本，提交到 `main`。
2. 在 `main` 上執行 `task release VERSION=0.1.0`（版本號照 [SemVer](https://semver.org/lang/zh-TW/)，不加 `v`）。它會先確認：
   - 目前在 `main`、工作目錄沒有未提交的變更、跟 `origin/main` 一致
   - `v0.1.0` 這個 tag 在本機和 `origin` 都還不存在
   - 兩個 `version` 都是 `0.1.0`

   接著執行格式檢查、測試、拼字檢查和 `task release:snapshot`，全部通過後建立有簽章的 `v0.1.0` tag 並推送。
3. tag 推送後，GitHub Actions 會先在 CI 上再檢查一次：tag 是否在 `main` 上、版本、格式、測試、拼字、hassfest 和 HACS 的檢查。通過後才建立 GitHub Release，附上 `tts_http_gateway.zip`，HACS 安裝的就是這個檔案。

只想確認發布內容、不發布的話，執行 `task release:snapshot`，zip 和發布說明會放在 `dist/`。

## 授權

[MIT](./LICENSE)
