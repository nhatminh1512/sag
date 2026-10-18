# Hướng dẫn sử dụng `sag`

`sag` là pipeline 7 bước cho một task code:

```
plan → write-test → execute → review → verify → remember → improve
```

Mỗi bước là **một agent riêng** (Claude / Grok / DeepSeek), giao việc bằng file,
có self-check trước khi chuyển bước. Một process "Chief of Staff"
(`orchestrator.py`) chỉ **route**, không tự viết code.

---

## 1. Yêu cầu

- Python 3.10+
- Các CLI đã cài: `claude`, `grok`, `dsh`
- Key:
  - `DEEPSEEK_API_KEY` trong `~/.hermes/.env` (orchestrator tự load)
  - Claude đã login (`~/.claude/.credentials.json`)
  - Grok đã login
- Repo đích phải là **git repo** (có `.git`)

Kiểm tra nhanh:

```bash
cd ~/sag
python3 orchestrator.py --help
claude --version && grok --version && dsh --version
```

---

## 2. Chạy nhanh

```bash
cd ~/sag

# xem trước flow, không gọi AI
python3 orchestrator.py "Add a GET /ping endpoint" --repo /path/to/repo --dry-run

# chạy full, không dừng gate
python3 orchestrator.py "Add a GET /ping endpoint" --repo /path/to/repo --auto
```

Mặc định `repo` lấy từ `config.json` (`/path/to/your/repo`). Nên chạy trên
**bản copy** nếu không muốn repo thật bị thay đổi:

```bash
cp -a /path/to/your/repo /tmp/sag_run
cd ~/sag
python3 orchestrator.py "Add a GET /ping endpoint" --repo /tmp/sag_run --auto
```

---

## 3. `sag` — setup một lần, dùng hằng ngày

### Setup (một lần cho mỗi repo)

```bash
cd /path/to/repo
sag setup
```

Wizard sẽ:
- nhận repo (git root);
- dò `claude`, `grok`, `dsh` và cho bạn gán từng bước;
- dò test command (`test_regressions.py` / `npm test` / pytest);
- ghi `.sag/config.json`, copy harness skills vào `.sag/harness/skills/`,
  tạo `memory/`, `runs/`, `library/`, `guardrails.json`.

`--yes` nhận mặc định, `--force` ghi đè, `--test-cmd` chỉ định test command.

### Kiểm tra

```bash
sag check
```

### Dùng hằng ngày

```bash
cd /path/to/repo
sag                  # hỏi task rồi chạy
sag "mô tả task"     # chạy luôn
sag --auto           # bỏ human gate
sag --steps plan,write-test
```

### Xem lại

```bash
sag report                       # run gần nhất
sag report --run-id 20261018-182024
sag demo                         # dry-run, không gọi model
```

### Task-level recursion (tuỳ chọn)

```bash
sag --k 2                        # baseline + 1 proposal/probe rồi compose
sag --k 3 --mode sequential      # tinh chỉnh qua nhiều vòng
sag --k 2 --baseline-run .sag/runs/20261018-183610
sag --k 2 --full-probe           # probe cả plan..verify (đắt)
```

Cơ chế: **Propose** (đọc evidence, sửa tối đa 1 `SKILL.md`) → **Probe** (chạy
lại các bước bị ảnh hưởng trên bản copy/worktree với harness mới) → **Compose**
(chọn theo hành vi: test xanh, review approve, verify nhất quán với review) →
**Reflect** (lưu harness thắng + bài học vào `.sag/library/`).

Điểm: `test_ok×3 + approve×2 + consistent×3 + criteria×0.1`; hoà thì giữ baseline.
Probe chỉ chạy từ bước bị ảnh hưởng sớm nhất tới `verify`, nên sửa skill
`verify` chỉ tốn ~1 lần chấm, không phải cả pipeline.

## 4. Chạy từng bước

```bash
# chỉ plan
python3 orchestrator.py "..." --steps plan

# plan + viết test
python3 orchestrator.py "..." --steps plan,write-test

# tiếp tục một run đã có
python3 orchestrator.py --run-id 20261018-172206 --steps execute,review --auto
```

Các option:

| Option | Ý nghĩa |
|---|---|
| `--repo` | repo đích (mặc định trong config) |
| `--steps` | danh sách bước, cách nhau dấu phẩy |
| `--run-id` | tiếp tục run cũ |
| `--auto` | bỏ human gate |
| `--dry-run` | chỉ in flow, không gọi AI |

---

## 5. Khi nào dừng lại cho bạn duyệt

Mặc định pipeline **dừng trước `execute`** — sau khi đã có `plan.md` và test
(RED). Bạn đọc rồi mới cho chạy tiếp:

```bash
python3 orchestrator.py "..." --steps plan,write-test          # dừng
# đọc plan.md, test-plan.md
python3 orchestrator.py --run-id <id> --steps execute,review,verify,remember,improve
```

`git commit` / merge **luôn thủ công** — không có bước nào tự commit.

---

## 6. Review verdict

Bước `review` trả về một trong hai:

- **APPROVE** → pipeline đi tiếp.
- **REQUEST_CHANGES** → pipeline **dừng** (sau khi đã ghi `review.md`).

Khi bị REQUEST_CHANGES, đọc `review.md`, sửa (tay hoặc chạy lại `execute` với
`review.md` làm input), rồi chạy lại:

```bash
python3 orchestrator.py --run-id <id> --steps execute,review --auto
```

Hiện chưa có vòng fix tự động (review → fix → re-review). Đó là cải tiến tiếp
theo, và chính bước `improve` sẽ đề xuất nó.

## 7. Cấu hình `config.json`

```json
{
  "repo": "/path/to/your/repo",
  "test_cmd": ".venv/bin/python test_regressions.py",
  "steps": {
    "plan":       {"cli": "claude", "permission": "acceptEdits", "model": "claude"},
    "write-test": {"cli": "grok",   "permission": "auto",        "model": "grok"},
    "execute":    {"cli": "dsh",    "permission": "auto",        "model": "deepseek-flash"},
    "review":     {"cli": "claude", "permission": "acceptEdits", "model": "claude"},
    "verify":     {"cli": "grok",   "permission": "auto",        "model": "grok"},
    "remember":   {"cli": "none"},
    "improve":    {"cli": "claude", "permission": "acceptEdits", "model": "claude"}
  },
  "gates": ["execute", "apply"],
  "timeout_s": 900
}
```

- **`test_cmd`**: lệnh test **thật** của repo. Rất quan trọng — orchestrator dùng
  nó để kiểm tra test phải RED trước `execute` và PASS sau `execute`.
- **`steps[].cli`**: `claude` | `grok` | `dsh` | `none`.
- **`steps[].permission`**: `claude` dùng `acceptEdits` (mode `plan` chỉ đọc,
  không ghi được file) — `grok`/`dsh` dùng `auto`.
- **`gates`**: các bước cần bạn xác nhận.
- **`timeout_s`**: timeout mỗi agent.

Đổi model cho một bước = sửa đúng dòng đó, không cần sửa code.

---

## 8. Skills của từng bước

Mỗi bước có một **role card** riêng tại:

```
~/sag/skills/<step>/SKILL.md
  plan/  write-test/  execute/  review/  verify/  remember/  improve/
```

Orchestrator đọc file này, bỏ frontmatter, rồi **inject vào prompt** của model.
Muốn đổi hành vi một bước (ví dụ bắt reviewer soi kỹ hơn, hay test author viết
test nhỏ hơn) → sửa đúng `SKILL.md` đó, không cần chạm vào Python.

Lưu ý: đây là skill **của orchestrator**. Mỗi CLI còn có skill system riêng:

| CLI | Nơi đặt skill |
|---|---|
| Claude Code | `~/.claude/skills/`, `./.claude/skills/` |
| Grok | `~/.grok/skills/`, `./.grok/skills/` — **và đọc cả `~/.claude/skills/`** |
| dsh | skill qua profile (`~/.dsh/profiles/...`) |

## 9. Output ở đâu

```
~/sag/runs/<timestamp>/
  task.txt
  prompts/<step>.md        prompt chính xác đã gửi cho agent
  log.jsonl                rc + thời gian + đuôi output mỗi bước
  plan.md
  test-plan.md
  test-output-red.txt      bằng chứng test đỏ trước execute
  diff.patch
  execution.md
  review.md
  verify.json              {pass, criteria[], reasons[]}
  test-output.txt
  improve.md

~/sag/memory/
  decisions.md             quyết định qua các run
  lessons.md               lỗi + bài học
  context.md               context repo
  improvements.md          gợi ý cải tiến SOP
```

Nếu một bước fail, orchestrator in `Run dir: ...` để bạn xem log.

---

## 10. Lỗi thường gặp

| Lỗi | Nguyên nhân | Cách sửa |
|---|---|---|
| `planner did not write plan.md` | Claude chạy `--permission-mode plan` (read-only) | đặt `permission: acceptEdits` cho bước `plan` |
| `tests PASS before execute` | test mới không được nối vào runner thật | xem `test-plan.md`; sửa prompt/test_cmd để test nằm đúng file repo chạy |
| `MISSING_CREDENTIAL ... deepseek-official` | `DEEPSEEK_API_KEY` không có trong env | kiểm tra `~/.hermes/.env`; orchestrator tự load nhưng key phải tồn tại |
| `no TTY for the human gate` | chạy non-interactive | thêm `--auto`, hoặc chạy trong terminal thật |
| Grok chậm (3–6 phút) | bình thường | tăng `timeout_s` nếu cần |
| `executor produced no diff` | dsh không sửa file | xem `log.jsonl` bước execute; có thể prompt chưa đủ rõ |

---

## 11. Mở rộng

- **Thêm bước**: thêm tên vào `STEPS`, viết hàm `do_<step>`, đăng ký trong
  `IMPL`, thêm prompt + entry trong `config.json`.
- **Đổi rubric verify**: sửa `prompt_verify()` — đây là nơi định nghĩa "đạt".
- **Đổi model từng bước**: chỉ sửa `config.json`.
- **Bỏ human gate**: `--auto`.

---

## 12. Nguyên tắc thiết kế (để không phá vỡ kiến trúc)

1. Orchestrator **không viết code** — chỉ route và gate.
2. Mỗi bước có **role + prompt + output file riêng**.
3. Handoff bằng **file**, không nhét transcript vào prompt.
4. Mỗi bước **tự kiểm tra** trước khi nộp (plan đủ section, test RED, execute
   chạy suite, verify có evidence).
5. Test author **độc lập** với executor.
6. Hành động không đảo ngược (commit/merge) **luôn do người duyệt**.
