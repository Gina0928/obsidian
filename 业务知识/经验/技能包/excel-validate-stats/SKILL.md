---
name: excel-validate-stats
agent_created: true
description: |
  This skill validates, checks, and computes statistics for Excel inventory
  (库存) files. It covers three workflows: (A) validate/deduplicate a single
  inventory file then compute totals; (B) compare two inventory files via a diff
  tool and cross-validate the diff results; (C) a lightweight Python-only
  side-by-side total comparison of two files. All totals use Decimal for lossless
  precision.

  NEVER modify any input file (红线原则, highest priority): every output is a NEW
  file (<source>_重复行合并.xlsx / <source>_差异.xlsx / same-name .txt), inputs are
  never written back or overwritten — in compare workflows BOTH files stay
  read-only. Every run fingerprint-verifies (size + mtime) each input before and
  after processing and prints an explicit `输入文件只读确认 ✓` line per input.

  Engine policy (JAR-FIRST): `demo-0.0.1-SNAPSHOT.jar` (the original Spring Boot
  tool) is STRONGLY preferred. Discovery order: explicit --jar > cached
  last-known-good path (~/.workbuddy/excel-validate-stats.jar.txt) > walk up
  from the source file's directory looking in target/ / demo/target/ (files
  usually live inside the demo project) > safe known locations (skill dir /
  CWD / home explicit paths; home subdirectories are never scanned to avoid
  sandbox blocks). Only when no JAR is found (or Java fails) does the bundled
  pure-Python implementation run — so the skill works on any machine with
  Python 3 + openpyxl, and uses the official JAR wherever it is installed.
  NOTE: the JAR's validate mode MARKS strict duplicates (重复标记
  "重复行校验不通过...未执行合并") instead of merging; validate_merge.py detects
  this and falls back to the Python merge so the workflow always delivers a
  clean deduplicated file.

  This skill should be used when the user wants to:
  - Validate, check, or initialize inventory data. Trigger keywords (中文):
    库存校验, 校验库存, 校验一下库存, 初始化校验, 初始化核对, 初始化库存,
    库存初始化校验, 库存初始化核对, 验证库存, 库存验证, 库存盘点, 盘点,
    核对库存, 库存核对.
  - Count/report totals: 库存总数量 (inventory quantity), 金额总数量 (monetary
    amount), inventory counting, 库存统计, 金额统计.
  - Compare two inventory Excel files, compute differences, or cross-validate
    them. Trigger keywords: 对比, 比较, 差异, 文件对比, 差额计算,
    交叉验证, 文件差异, 差额, 比对.
  - Process any .xlsx/.xlsm inventory file for deduplication, statistics, or diffing.

  Natural-language triggers include: "统计这个excel的库存", "算一下总数量和总金额",
  "帮我验证并统计这个表格", "初始化校验一下这个库存表", "校验一下库存",
  "帮我初始化校验这个库存", "库存初始化核对一下", "盘点一下库存", "库存盘点",
  "对比这两个文件", "两个文件对比库存差异", "比较这两个excel的库存和金额",
  "对比一下这两个表的库存", "统计两个表的差异", "校验这两个表的库存差异".
  Also trigger whenever the user drops an .xlsx/.xlsm file and asks for
  validation, totals, comparison, or inventory checking.
---

# Excel Validate & Stats

Three workflows: **validate** (single file → deduplicate → stats), **compare** (two files → diff → stats → cross-validate), and **compare-stats** (two files → stats only → side-by-side deltas, no diff needed). All stats use Python's `Decimal` for lossless precision.

## 红线原则：绝不修改任何输入文件（最高优先级，不可违背）

**任何工作流、任何引擎（JAR 或 Python）、任何场景下，都不得修改、覆盖、回写、原地编辑用户提供的任何输入 Excel 文件。** 这是本技能的最高原则，优先级高于一切引擎策略与输出便利。

- **输入文件永远只读**：脚本只通过 `openpyxl.load_workbook(..., data_only=True)` 读取输入，从不保存回输入路径；JAR 引擎在**临时目录**中运行（`inv_val_*` / `inv_cmp_*`），输入先被复制到临时目录，JAR 的任何输出都只落在临时目录，完成后仅把新产物文件（`_重复行合并.xlsx` / `_差异.xlsx`）移动回源文件目录，输入副本随临时目录一并删除。
- **所有产物都是新建文件**：`<source>_重复行合并.xlsx`、`<source>_差异.xlsx`、同名 `.txt` 统计存档。它们可能覆盖**上一次运行生成的同名产物**，但绝不触碰输入。
- **对比/比对场景（Workflow B / C）双保险**：文件A 和 文件B **两个输入都只读**，差异文件是新建的第三个文件。任何情况下都不得以"对比需要"为由改写任一侧输入。
- **可验证的确认**：脚本在入口记录每个输入文件的**指纹（大小 + 修改时间）**，全部流程结束后复核。未变 → 打印 `输入文件只读确认 ✓ <label>: <name> (大小/修改时间未变)`；变了 → 打印严重警告并以非零码退出（红线违反，立即终止并检查原因）。
- **若怀疑输入被修改**：对比 `md5sum` 前后值（或文件属性），并检查是否存在与输入同名的产物文件被误当成输入。产物文件命名始终带 `_重复行合并` / `_差异` / `.txt` 后缀，与原始文件不可能同名。

**引擎策略（重要，JAR 优先）：** 两个依赖工具的流程（去重校验 / 差异生成）**默认优先使用 `demo-0.0.1-SNAPSHOT.jar`**。JAR 发现顺序：
1. `--jar <path>` 显式指定（缺失即报错）；
2. **缓存路径** `~/.workbuddy/excel-validate-stats.jar.txt`（首次成功后写入，之后秒定位）；
3. **源文件上级目录向上查找**：从输入文件所在目录逐级向上找 `target/`、`demo/target/` 下的 `demo-0.0.1-SNAPSHOT.jar`（库存文件通常位于 demo 工程内，JAR 在工程 `target/` 下）；
4. 安全已知位置（技能目录 / CWD / 用户主目录的显式路径，仅遍历技能目录与 CWD 的一级子目录）。
**用户主目录的一级子目录（~/.ssh、~/.gnupg 等）刻意不扫描**，避免触发沙箱权限拦截。

**仅当 JAR 找不到（或 Java 执行失败）时才回退到纯 Python 实现。** 注意：JAR 的 `validate` 模式对"严格重复"（五键相同且进价相同）的语义是**标记而不合并**（重复标记列写入"重复行校验不通过...未执行合并"）；`validate_merge.py` 会在 JAR 产出后自动检测重复标记，**发现未合并的严格重复时回退 Python 引擎完成合并兜底**，并在 stdout 明确打印引擎切换，保证最终交付的仍是干净去重文件。纯 Python 的 Workflow C（仅并排对比）不依赖任何工具。

## 意图识别 (Intent routing) — 如何选工作流

收到请求后，**先判断意图关键词 + 文件数量**，再路由到对应工作流。任何"校验/检查/初始化/盘点/核对"类中文词都应优先触发本技能，不要误判为普通表格处理。

| 用户意图 / 关键词 | 文件数量 | 路由到 |
|---|---|---|
| 校验 / 库存校验 / 校验库存 / 初始化校验 / 初始化核对 / 初始化库存 / 库存初始化校验 / 库存初始化核对 / 验证库存 / 库存验证 / 盘点 / 库存盘点 / 核对库存 | **1 个** | **Workflow A**：先去重校验再统计。若用户明确说"已校验/不用验证"，或文件名已含`重复行合并`，则跳过校验直接统计（仅跑 Step A3）。 |
| 统计 / 总数量 / 总金额 / 库存总数量 / 金额总数量 / 算一下 | 1 个 | **Workflow A（仅统计）**：直接对文件跑 `calculate_stats.py`，无需 Java。 |
| 对比 / 比较 / 差异 / 文件对比 / 差额 / 交叉验证 / 比对 | **2 个** | 需要逐行差异文件 + 交叉验证 → **Workflow B**；仅要并排总额对比、不要差异文件 → **Workflow C**。 |

额外判断：
- 用户只给 1 个文件却说"对比/比较" → 多半是希望对这个文件做校验并核对总数，走 Workflow A（仅统计或校验+统计）。
- 关键词同时出现"校验"和"对比"（如"对比并校验库存差异"）→ 优先 Workflow B。

## Core principle: never lose precision

All calculations use Python's `Decimal`. Inventory quantities can have up to 3 decimal places,
unit prices up to 6 decimal places. `float` would silently drop digits — `Decimal` preserves
every digit exactly.

---

## 结果报告规范（每次执行必须输出，且必须包含确定性指标数据）

**无论走哪条工作流，执行结束后都必须向用户输出一份结果报告。** 报告中必须包含
**确定性（可复现、精确无误）的指标数据** —— 即：所有数字均来自脚本以 `Decimal`
精确计算的真实结果，与一并保存的同名 `.txt` 文件完全一致。**禁止用自然语言模糊带过，
禁止估算、禁止四舍五入后只给近似值、禁止用"已统计完成"之类空话替代具体数字。**

### 报告展示形式（强制）：以 Markdown 表格呈现

**每次执行结束后，除展示脚本 stdout 外，还必须把核心指标整理成 Markdown 表格发给用户。**
表格列（单文件场景）：

| 指标 | 数值 |
|---|---|
| 文件名 | 实际处理的 Excel 文件名 |
| Excel 总行数 | `ws.max_row`，含表头 |
| 数据行数 | 参与统计的行数（有库存数量的行） |
| 是否有重复行 | ✓ 无 / ✗ 存在 N 行重复（附组数与判定列） |
| 库存总数量 | 库存数量列求和（`Decimal` 精确值） |
| 金额总数量 | Σ(库存数量 × 进价)（`Decimal` 精确值）；无进价列则标"不适用" |
| 统计存档 | 同目录生成的 `.txt` 路径（权威记录） |

双文件场景在表格中加入 文件A / 文件B / 差异文件 各自的上述指标与差额、交叉验证结论。
**stdout 原始文本与表格数据必须一致**；stdout 先展示，表格紧随其后，两者数字严格相同。

### 报告必备字段（缺项必须显式标注，禁止静默跳过）

**单文件（Workflow A / A 仅统计）：**
| 字段 | 说明 |
|---|---|
| 文件名 | 实际处理的 Excel 文件名 |
| Excel 总行数 | 含表头（`ws.max_row`）|
| 数据行数 | 参与统计的数据行数 |
| 是否有重复行 | ✓ 无 / ✗ 存在；附 重复行数、重复组数、判定列 |
| 库存总数量 | 库存数量列求和（`Decimal` 精确值）|
| 金额总数量 | Σ(库存数量 × 进价)（`Decimal` 精确值）|
| 统计存档 | 同目录生成的 `.txt` 路径（权威记录）|

**双文件对比（Workflow B，含差异文件 + 交叉验证）：**
在单文件字段基础上，额外包含：
| 字段 | 说明 |
|---|---|
| 文件A / 文件B 各自的 库存总数量、金额总数量、数据行数、Excel总行数、重复行 | 两侧分别统计 |
| 差额 (A − B) | 库存数量差、金额数量差（`Decimal` 精确值）|
| 差异文件统计 | 差异 Excel 的 库存总数量、金额总数量、数据行数 |
| 交叉验证 | 数量是否匹配（`delta == -diff`），明确给出 ✓ 匹配 / ✗ 不匹配 |
| 各 .txt 存档 | 三个 Excel 各自对应的统计文件绝对路径 |

**双文件对比（Workflow C，仅并排总额）：**
包含文件A、文件B 各自的 库存总数量 / 金额总数量 / 数据行数 / Excel总行数 / 重复行、
差额 (A − B)，以及各 `.txt` 路径。

### 输出要求
1. 直接展示脚本/工具的真实 stdout 输出，**先展示报告，再决定是否需要补充说明**。不要只做口头总结。
2. **必须用 Markdown 表格呈现核心指标**（见上文"报告展示形式"），表格数字与 stdout、`.txt` 存档严格一致。
3. 数字保留完整精度；数值很长时，可同时给出"规范化值"与"原始精度"两种展示（脚本已支持）。
4. 报告末尾固定附两句（脚本会自动输出，原样展示即可）：
   - `本报告指标均由 Decimal 精确计算，与同名 .txt 存档一致，结果可复现。`
   - `输入文件只读确认 ✓ 文件A/文件B/输入文件（指纹校验：大小/修改时间未变）—— 原始文件未被修改。`
5. 若某字段因缺列 / 缺值无法计算（如缺少进价列），必须显式标注（例：`无进价列，金额总数量 = 不适用`），不得静默跳过。
6. 即使走"跳过校验 / 仅统计"等轻量路径，也必须输出上述对应字段的报告，不得省略。

---

## Workflow A: Validate (single file)

Use when the user provides **one** Excel file and wants to validate/deduplicate it, then get stats. This is the canonical workflow for requests phrased as 库存校验, 校验库存, 初始化校验, 初始化核对, 库存初始化核对, 盘点, 核对库存, or "帮我初始化校验这个库存表".

### Step A1: Deduplicate / merge (Java if JAR present, else Python)

Run the bundled `validate_merge.py` on the source file. It groups data rows by the
5-key combo (外部商品编码 / 库位 / 供应商编码 / 仓库供应商编码 / 生产日期), sums
库存数量 per group, and writes `<source>_重复行合并.xlsx` **next to the source file**.
The original file is never modified.

```bash
python "<skill-base>/scripts/validate_merge.py" "<absolute-path-to-file.xlsx>"
```

- **引擎选择（JAR 优先）**：脚本按 `--jar` > 缓存路径 > 源文件上级目录（`target/`、`demo/target/`）> 安全已知位置 的顺序探测 `demo-0.0.1-SNAPSHOT.jar`。找到就用 Java `validate` 模式；找不到（或 Java 执行失败）就回退到内置纯 Python 去重。**JAR 对严格重复只标记不合并**，脚本会检测 `重复标记` 列并自动回退 Python 完成合并兜底，stdout 会打印引擎与原因。
- 可用 `--jar <path>` 显式指定 JAR（若指定却失败则直接报错，不静默回退）；`--force-python` 强制走 Python 实现（便于在无 Java 环境或比对一致性时使用）。
- Pass the **full absolute path** (Windows backslash, or `/d/...` Git-Bash style — both are auto-normalized).
- The script auto-skips if `<source>_重复行合并.xlsx` already exists (use `--overwrite` to regenerate).
- If a 金额/金额总数量 column exists, the merged row's amount is recomputed as 合并数量 × 进价 so the file stays internally consistent.
- **输出格式与原文件一致（Python 兜底引擎）**：当走 Python 去重时，`validate_merge.py` 不再新建空白工作簿，而是**以源文件为骨架**——加载源工作簿、保留其表头行与所有工作表级样式（工作表名 `Sheet1`、列宽、表头字体/字号/加粗/填充、日期列数字格式 `yyyy\-mm\-dd`、冻结窗格等），仅清空并重写为去重后的数据行，且每个输出单元格都从源文件首个数据行对应列**拷贝样式**（`inv_io.write_workbook_preserving_format`）。这样产物在视觉与格式上和原始文件完全一致，JAR 产物本就如此，二者不再有差异。原文件只被读取、输出另存为新文件，红线原则不受影响。
- **输入只读保证**：脚本执行末尾自动打印 `输入文件只读确认 ✓ 输入文件: <name> (大小/修改时间未变)`，证明源文件从头到尾只读、未被修改（见顶部红线原则）。

### Step A2: Calculate totals

Run the bundled script on the output file and show results directly:

```bash
python "<skill-base>/scripts/calculate_stats.py" "<path-to>\output_重复行合并.xlsx"
```

The script auto-detects quantity and price columns, reports **Excel 总行数（含表头）**、
**数据行数**、**重复行检测结果（重复行数/组数，按 外部商品编码+库位+供应商编码+
仓库供应商编码+生产日期 组合判定，缺关键列时退化为整行判定）**，并以 `Decimal` 精度
计算 库存总数量 / 金额总数量，打印结构化报告并保存同名 `.txt` 存档。也支持
`--json` 参数输出机器可读结果（便于整理成表格）。
**按「结果报告规范」输出**：直接展示脚本 stdout（含文件名、Excel 总行数、数据行数、
重复行判定、库存总数量、金额总数量、统计存档路径），并**以 Markdown 表格呈现核心指标**，
末尾附"结果可复现"说明。

### If validation is not needed

If the user says "不用验证" or the file is already validated, skip Steps A1-A2 and run Step A3 directly on the file they provide. **This lightweight path still must output the full result report (单文件字段) per the 结果报告规范 — never omit the report just because validation was skipped.**

---

## Workflow B: Compare (two files)

Use when the user provides **two** Excel files and wants to compare them, get a diff Excel, and cross-validate the results.

### Step B1: Run the compare_and_validate.py script (Java-preferred, Python-fallback)

This is the one-step entry point — it handles everything: generating the diff
Excel (via the JAR when available, else pure Python), computing stats for all
three Excel files, calculating deltas, cross-validating, and producing a
side-by-side summary report. The engine used is printed in the report
(`差异生成引擎: java | python`).

```bash
python "<skill-base>/scripts/compare_and_validate.py" "<absolute-path-to-file1.xlsx>" "<absolute-path-to-file2.xlsx>"
```

**Parameters:**
- First positional arg: source file (full absolute path) — this is the "primary" file for comparison
- Second positional arg: compare file (full absolute path) — this is the "secondary" file to compare against
- `--jar <path>` (optional): explicitly point at `demo-0.0.1-SNAPSHOT.jar` (forces Java; failure is reported loudly instead of falling back)
- `--force-python` (optional): skip Java detection and use the pure-Python diff generator
- `--out-dir` (optional): directory for the generated `{source}_差异.xlsx` (default: the **source file's own directory**, which guarantees the output persists in this sandbox)

Both file paths may be Windows backslash absolute or `/d/...` Git-Bash style — they are auto-normalized.

**What the script does (in order):**

1. **Loads** both files and groups each by the 5-key combo, summing 库存数量 per key
2. **Generates** `{source}_差异.xlsx`, mirroring the JAR's compare semantics exactly:
   - same 5-key present in BOTH files with 进价 **within 0.01** (a price gap ≤ one cent is treated as "same price") → one row whose 库存数量 = compare_qty − source_qty (net increment; rows whose rounded increment is 0 are dropped, matching the JAR's "删除增量=0的行" rule).
   - same 5-key present in BOTH files with 进价 **differing by more than 0.01** → TWO rows: a "remove-source" row (库存数量 = −source_qty at the source 进价) and an "add-compare" row (库存数量 = +compare_qty at the compare 进价). This is how the JAR expresses a price change, and is why such keys appear as duplicate 5-key groups in the diff file. Verified: the Python fallback now reproduces the JAR's diff metrics exactly (same row count, same 250 duplicate groups, same 金额总数量 to the last digit) on the 1221 dataset.
   - **输出格式与原文件一致（Python 兜底引擎）**：当走 Python 差异生成时，`compare_and_validate.py` 同样不再新建空白工作簿，而是**以源文件 A 为骨架**（保留其工作表名 `Sheet1`、列宽、表头样式、日期列数字格式等），仅重写差异数据行并逐单元格拷贝源文件首个数据行的样式（`inv_io.write_workbook_preserving_format`）。因此 Python 兜底产出的差异文件在视觉与格式上与 JAR 产物、与源文件完全一致。
3. **Calculates stats** for all three Excel files (source, compare, diff) using the same `Decimal` logic — saves `{filename}.txt` for each
4. **Computes deltas** directly from the Excel data: `delta_qty = source_qty - compare_qty`, `delta_amt = source_amt - compare_amt`
5. **Cross-validates**: checks whether the calculated deltas match the diff file's totals (quantity should satisfy `delta + diff == 0`)
6. **Prints** a side-by-side summary report to stdout
7. **校验输入只读（红线原则）**：复核文件A/文件B 的指纹（大小+修改时间），逐行打印
   `输入文件只读确认 ✓ 文件A(源文件): <name> (大小/修改时间未变)` 与 `✓ 文件B(对比文件): ...`；
   若任一输入被意外修改，打印严重警告并以非零码（3）退出。**对比/比对全程两个输入文件都只读，
   差异文件是新建的第三个文件，绝不覆盖任一侧输入。**

All `.txt` stats files are generated from the actual Excel data — the diff Excel is the authoritative source for cross-validation.

### Step B3: Show the report to the user

The script outputs a self-contained summary. **按「结果报告规范」输出**：直接展示脚本 stdout
（含文件A/文件B 各自的 库存总数量、金额总数量、数据行数，差额 A−B，差异文件统计，以及明确
的 ✓/✗ 交叉验证结论与各 `.txt` 存档路径），并在末尾附"结果可复现"说明。该报告已覆盖
双文件对比的全部必备字段，无需额外改写，原样呈现即可。

### Expected report format

```
============================================================
库存对比与交叉验证报告
============================================================

文件A (源文件): 1518-I.xlsx
  数据行数:    1500
  库存总数量:  140871.752
  金额总数量:  1166409.006

文件B (对比文件): 1518-II.xlsx
  数据行数:    1480
  库存总数量:  130500.500
  金额总数量:  1080000.123

------------------------------------------------------------
差额计算 (A - B):
  库存数量差:  +10371.252
  金额数量差:  +86408.883

差异文件 (1518-I_差异.xlsx) 统计:
  数据行数:    1520
  库存总数量:  -10371.252
  金额总数量:  -86408.883

------------------------------------------------------------
交叉验证:
  库存数量差额:  +10371.252  (A - B)
  差异文件数量:  -10371.252  (增量方向)
  数量验证:      ✓ 匹配  (delta == -diff)

  金额差额:      +86408.883  (A - B, 简单相减)
  差异文件金额:  -86408.883  (逐行: 增量×进价)
  注: 金额二者计算方式不同, 仅做参考对比
--------------------------------------------------------------
输入文件只读校验:
  输入文件只读确认 ✓ 文件A(源文件): 1518-I.xlsx (大小/修改时间未变)
  输入文件只读确认 ✓ 文件B(对比文件): 1518-II.xlsx (大小/修改时间未变)
============================================================
```

---

## Workflow C: Compare Stats (two files, no Java)

Use when the user provides **two** Excel files but only wants to compare their totals side-by-side — no diff file generation, no cross-validation against a diff Excel. This is a lightweight, Python-only workflow.

### Step C1: Run compare_stats.py

```bash
python "<skill-base>/scripts/compare_stats.py" "<absolute-path-to-file1.xlsx>" "<absolute-path-to-file2.xlsx>"
```

Both file paths **must be full absolute paths**.

**What the script does (in order):**

1. **Validates** both input files exist and are .xlsx/.xlsm
2. **Calculates stats** for each Excel — uses the same `calculate_stats.py` logic (`Decimal` precision)
3. **Saves** a same-name `.txt` file alongside each Excel
4. **Computes deltas**: `delta_qty = A_qty - B_qty`, `delta_amt = A_amt - B_amt`
5. **Prints** a side-by-side summary report to stdout
6. **校验输入只读（红线原则）**：复核两个输入文件的指纹并打印 `输入文件只读确认 ✓` 行
   （同 Workflow B；任一输入被意外修改则严重警告并以非零码退出）

### Step C2: Show the report to the user

The script outputs a self-contained summary. **按「结果报告规范」输出**：直接展示脚本 stdout
（含文件A/文件B 各自的 库存总数量、金额总数量、数据行数，差额 A−B，以及各 `.txt` 存档路径），
并在末尾附"结果可复现"说明。该报告已覆盖双文件对比（仅并排总额）的全部必备字段。

### When to use Workflow C vs Workflow B

- **Workflow C (compare_stats.py)**: User only wants totals comparison. No Java, no diff file, no cross-validation. Fast and simple.
- **Workflow B (compare_and_validate.py)**: User wants full comparison with diff Excel generation, per-row matching, and cross-validation of the diff file totals against computed deltas.

---

## How the scripts work

### calculate_stats.py

1. Reads Excel headers from row 1
2. Finds **库存数量** column (exact match → then keyword: 库存/数量/现存/结存)
3. Finds **进价** column (exact match → then keyword: 进价/单价/价格/成本)
4. Reports **Excel 总行数** (`ws.max_row`, 含表头) 与 **数据行数**（有库存数量的行）
5. Detects **重复行**：按关键列组合（外部商品编码/库位/供应商编码/仓库供应商编码/生产日期）
   统计出现次数，输出 重复行数、重复组数、最多 3 组示例；缺关键列时退化为整行判定
6. Sums 库存数量 with `Decimal` → **库存总数量**
7. Sums `库存数量 × 进价` with `Decimal` → **金额总数量**（无进价列时显式标注不适用）
8. Prints structured report to stdout AND auto-saves a `.txt` file next to the Excel
9. `--json` flag outputs machine-readable JSON (Decimal serialized as string)

`analyze_inventory()` returns a dict with all metrics (file_name, excel_total_rows,
data_row_count, qty_col_name, price_col_name, total_quantity, total_amount,
dup_row_count, dup_group_count, dup_examples, dup_columns_used, no_qty_rows,
missing_price_rows, has_price_col). `calculate_totals()` is kept as a backward-
compatible 5-tuple wrapper for older callers.

### compare_stats.py

1. Accepts two Excel file paths (absolute paths required)
2. Imports and calls `calculate_totals()` from `calculate_stats.py` for each file
3. Saves a same-name `.txt` stats file alongside each Excel
4. Computes deltas (A - B) with `Decimal` precision
5. Prints a side-by-side comparison report

### inv_io.py (shared helpers)

Imported by every script. Centralizes:
- `load_sheet()` — open an Excel, return headers, cleaned headers, data rows, and detected column indices (库存数量 / 进价 / 5-key).
- `normalize_path()` — accepts Windows backslash, forward-slash, **or `/d/...` Git-Bash style** paths and resolves them to a Windows absolute `Path`. This removes the old "java/python can't read Git-Bash paths" friction — callers no longer need to translate paths by hand.
- `get_cell_decimal()` / `cell_key_value()` — Decimal-safe cell reading and key normalization.
- `build_row_key()` — 5-key combo (with whole-row fallback) used by both dedup and diff.
- `write_workbook_preserving_format(src_path, header_row_index, data_rows, out_path, sheet_title=None)` — generate `out_path` **from a copy of `src_path`'s workbook**, keeping every visual style of the original (sheet name, column widths, header style, per-cell data style incl. date number formats, freeze panes) and only replacing the data rows. Each output cell copies the style of `src_path`'s first data row at the same column. This is what makes the Python fallback's `_重复行合并.xlsx` / `_差异.xlsx` visually identical to the original file (and to the JAR's output). The source is only read; output is saved to a new path.

### validate_merge.py (去重合并：JAR 优先，Python 兜底)

1. 引擎选择（JAR 优先）：按 `--jar` > 缓存路径 > 源文件上级目录（`target/`、`demo/target/`）> 安全已知位置的顺序探测 `demo-0.0.1-SNAPSHOT.jar`；找到则调用其 `validate` 模式（在临时工作目录中运行，再把产出文件移回源文件旁）。**JAR 对严格重复（五键相同且进价相同）只写入重复标记、不合并**；脚本用 `find_unmerged_duplicate_rows()` 检测产出文件的 `重复标记` 列，发现未合并行时打印警告并回退下方纯 Python 合并逻辑完成兜底（`--jar` 显式指定时同样兜底，因为这是语义差异而非引擎故障）。
2. 纯 Python 分支：通过 `inv_io.load_sheet()` 读取源文件。
3. 按 5 键组合分组（缺关键列时退化为整行）。
4. 每个唯一键写一行：保留首次出现的各列，并将 **库存数量 = 组内数量之和**；若有 金额/金额总数量 列，则重算为 合并数量 × 进价。
5. 保存 `<source>_重复行合并.xlsx` **到源文件旁**（原始文件不动）。若合并文件已存在则跳过，除非 `--overwrite`。
6. `--jar <path>` 强制走 Java（失败即报错）；`--force-python` 强制走 Python。
7. **格式一致性**：Python 分支通过 `inv_io.write_workbook_preserving_format(源文件, header_row_index=1, data_rows, out_path)` 生成产物——以源工作簿为骨架保留全部样式（工作表名、列宽、表头样式、日期数字格式等），仅重写数据行并逐单元格拷贝源首个数据行的样式，从而让 Python 产物与 JAR 产物、与原始文件在视觉/格式上完全一致。

### compare_and_validate.py

Orchestrates the full compare → diff → stats → cross-validate pipeline. Imports `calculate_stats` for the stats logic and `inv_io` for loading. The diff Excel is generated by the JAR when available (Java `compare` mode, run in a temp dir with inputs copied in, output moved next to source), otherwise by the bundled pure-Python generator (one row per union key; 库存数量 = compare − source increment). One row per union key; 库存数量 = compare − source increment. All file I/O uses auto-normalized absolute paths, and the diff file is written to the source's directory by default so it persists in this sandbox. All `.txt` stats files are generated by reading the actual Excel files — the diff Excel is the authoritative data source for cross-validation. The cross-validation itself is engine-agnostic: it reads the generated diff Excel and checks the quantity identity, so it works identically for Java- or Python-made diff files.

### java_bridge.py (shared — JAR detection + invocation)

- `find_jar(explicit=None, near_source=None)` — resolves the demo JAR, JAR-first: explicit `--jar` > cached path (`~/.workbuddy/excel-validate-stats.jar.txt`, written on first success) > source-relative walk (up from the input file's dir checking `target/`, `demo/target/`, and `target/*.jar`) > safe known locations (skill dir / CWD / home explicit paths + one subdir level of skill dir & CWD only — **home subdirectories are never scanned**, avoiding sandbox blocks on `~/.ssh`, `~/.gnupg`, etc.). Returns a `Path` or `None`.
- `java_validate(jar, source)` / `java_compare(jar, source, compare, out_dir)` — copy inputs into a temp work dir, invoke `java -jar <jar> <mode> <basePath> <files>`, move the produced `<source>_重复行合并.xlsx` / `<source>_差异.xlsx` next to the source, then delete the temp dir (so the user's source dirs stay clean). Java output is decoded utf-8 → GBK (Chinese Windows).
- `find_unmerged_duplicate_rows(xlsx)` — reads the `重复标记` column of a JAR-validate output and returns (marked_count, first_markers); used to detect JAR-marked strict duplicates so callers can fall back to the Python merge.
- Both raise on failure; callers decide whether to fail loud (explicit `--jar`) or degrade to Python (auto-detect).

---

## Troubleshooting

### openpyxl 未安装
所有脚本依赖 `openpyxl`。若报错 `No module named openpyxl`，安装即可：
```bash
pip install openpyxl
```

### "无法找到库存数量列" (Cannot find quantity column)
表头未匹配到预期列名。脚本先精确匹配 `库存数量`，再按关键词回退
（库存 / 数量 / 现存 / 结存）。都不匹配时，向用户确认哪一列是库存数量，再据此处理。

### "无法找到进价列" (Cannot find price column)
进价列同理：先精确匹配 `进价`，再按关键词回退（进价 / 单价 / 价格 / 成本）。
缺失时报告会显式标注「无进价列，金额总数量 = 不适用」，不会报错中断。

### 重复行判定说明
重复行按 外部商品编码 + 库位 + 供应商编码 + 仓库供应商编码 + 生产日期 五列组合判定。
列名检测先精确匹配、再做子串回退（例如表头 `外部商品编码 1.支持...` 也能识别），
大幅减少因导出模板带说明文字而退化成"整行判定"的情况；只有完全缺失关键列时才退化为
"整行值组合"判定，报告中会显示实际使用的判定列。
**已校验文件（含 `重复行合并` / `校验合并` 字样）应显示 ✓ 无重复行；
若显示 ✗ 存在重复，说明去重不彻底，应提示用户重新校验。**

### JAR 与 Python 引擎的语义差异（严格重复）
JAR `validate` 模式对"严格重复"（五键相同 **且进价相同**）的行为是**标记而不合并**：
在 `重复标记` 列写入 `重复行校验不通过(首条,共N条)，未执行合并` / `重复行校验不通过(与第X行)，未执行合并`，
两行都保留。这与 Python 引擎（五键相同即合并数量）不同。
- `validate_merge.py` 已自动处理：JAR 产出后用 `find_unmerged_duplicate_rows()` 检测 `重复标记` 列，
  发现未合并行即打印警告并回退 Python 合并兜底，最终文件仍是干净去重文件，报告不受影响。
- 若手动用 JAR 直接处理文件（不经脚本）后看到上述标记，属 JAR 的保守校验设计：严格重复被当作数据问题
  留给人工复核，而非自动合并。

### JAR 发现被沙箱拦截 / 找不到 JAR
若运行脚本时发现回退到了 Python（stdout 打印"未找到 demo-0.0.1-SNAPSHOT.jar"）：
1. 确认 JAR 位置，用 `--jar <绝对路径>` 显式指定（首次运行会写入缓存，之后自动秒定位）；
2. 或把输入文件放在 demo 工程内（如 `<demo>/src/main/resources/static/...`），脚本会从文件所在目录
   向上在 `target/` / `demo/target/` 中找到 JAR；
3. 已知问题：旧版 `find_jar` 会遍历用户主目录一级子目录（`~/.ssh`、`~/.gnupg` 等），在沙箱中会触发
   权限拦截；现已移除该扫描，改为源文件上级目录 + 缓存 + 显式路径，不访问敏感目录。

### 表头带说明文字 / 列名不一致（如 仓供应商 vs 仓库供应商编码）
部分导出（如麒麟系统模板）会在表头单元格里塞长说明（`外部商品编码 1.支持外部商家的商品编码 ...`），
或把 `仓库供应商编码` 写成 `仓供应商`。脚本已对五键列做子串回退，多数情况可自动识别；
若仍识别不到（如 `仓供应商` 与 `仓库供应商编码` 既不等同也无包含关系），手动处理：
1. 用 `openpyxl` 做一份清洗副本：保留表头首个词、并把 `仓供应商` 改名为 `仓库供应商编码`。
2. 在清洗副本上跑 `validate_merge` / `compare_and_validate`。
3. 输出改名回干净文件名；原始源文件从不修改。

### 输入文件安全（红线原则）
本技能**绝不修改任何输入 Excel**：所有产物（`_重复行合并.xlsx` / `_差异.xlsx` / 同名 `.txt`）
都是新建文件；JAR 引擎在临时目录运行、只把产物移回源目录。每次执行末尾脚本会自动打印
`输入文件只读确认 ✓`（指纹 = 大小 + 修改时间，执行前后对比）。
- 若该行显示 `!! ... 已被修改` 或退出码为 3，说明输入被意外改动（可能来自其他进程 / 手动编辑），
  立即停止并核对：产物文件是否被误当成输入？是否有同名文件覆盖？
- 复核方法：执行前后分别 `md5sum <输入文件>` 对比；正常情况两值必须完全一致。
- 产物文件命名始终带 `_重复行合并` / `_差异` / `.txt` 后缀，与原始文件不可能同名；
  把产物文件再当输入处理时同样只读、会生成下一级后缀文件，原始文件依旧不动。

### 大数据量对比会被前台超时中断（1.5 万行以上必读）
Workflow B（双文件对比）在 1.6 万行级别上实测耗时约 **2 分 34 秒**，前台 Bash 默认 120s
超时会被 SIGTERM 杀掉（exit code 1、stdout 为空），容易误判为脚本报错。
处理方式：**直接以 run_in_background 后台执行 `compare_and_validate.py`，再用 TaskOutput
阻塞等待取回完整报告**（本会话 1211 批次即如此完成，结果完全正常）。
单文件的 Workflow A（去重校验 / 统计）耗时在秒级，前台执行即可，无需后台。

### 沙箱：工作区外写入不持久
本沙箱的持久化只保证当前工作目录（CWD）下的写入。脚本已默认把合并文件 / 差异文件写到
**源文件所在目录**（即用户提供的路径，通常已在 CWD 内），因此产物可正常留存；
除非用户明确要求，否则不要把输出写到 `D:/compareFile/...` 这类固定绝对目录。
另外 `os.remove` 会被安全删除钩子拦截（回收站不可用）并抛 `OSError`，删除临时文件请用
PowerShell 工具：`Remove-Item -Force <path>`。

### 路径写法（本沙箱）
脚本内部已用 `inv_io.normalize_path()` 统一处理路径：Windows 反斜杠绝对路径、
正斜杠 `D:/...`、以及 Git-Bash 风格 `/d/...` 都会被正确解析为 Windows 绝对路径。
调用脚本时直接传用户给的路径即可，无需手动翻译。

### 精度说明
数量与金额均以 `Decimal` 计算，不丢精度。写入 Excel 时数值以 `float` 落盘（库存数量最多 3 位、
进价最多 6 位小数，常规范围可无损回读）；真正的权威精度记录在同源 `.txt` 存档与脚本 stdout 中。
