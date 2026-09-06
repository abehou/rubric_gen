# checkpoint 与最新 main 的代码对比

日期：2026-09-05，Asia/Shanghai。此次保存版本、同步代码、审查及运行本地测试，不启动 benchmark 实验；根据用户追加要求，另外执行 Gemini/Anthropic 的极短凭证连通性测试。

## 版本与保存状态

- 我们之前的基线：`0b48378`。
- 当前工作完整提交：`1c2d686`，已 push 至 `origin/aydan-checkpoint-1`。包含此前的本地代码修复、OpenAI 专用 YAML、测试和实验日志。
- collaborator 的新 main：`c45e591`。本地 `main` 已通过 fast-forward 与它同步；没有把 checkpoint 整体合入 main。
- 远端相对共同基线新增两个 commit：`71da422`（Remove combined evaluation report）与 `c45e591`（quick edit），涉及 85 个文件，6,091 行新增、6,119 行删除，另有二进制图表变化。
- 密钥、数据、`seeds/`、`runs/` 被 Git 忽略，没有上传，仍在本机。此前 BioMNIBench 的 106 completed / 2 failed 记录未修改。
- 本报告和下面列出的移植修复、并发调整是最新 main 上的本地未提交改动，尚未 push 到远端 main。checkpoint 保持原始快照。

## 1. Red team 实际如何接入

入口是 `submission_revision/red_team.py`，由 `controller_scoring.py::ensure_online_rubric_generation` 调用。

原来已经存在用于初始化 rubric 的 adversarial seed。新增机制是在在线修订过程中，对当前已经封存的提交再启动一个独立的攻击 agent；它不是替代正常 solver，也不是训练模型。

每次需要用前一个 checkpoint 更新 rubric 时：

1. 复制该 checkpoint 的 solution 到隔离工作区，正常 solver 的提交保持不变。
2. 攻击 agent 看到当前完整 rubric，尝试产生“看起来完整可信、rubric 得分高、但实际任务结果有实质错误”的提交。
3. 检查进程结果、必要输出以及 instruction/data 是否被修改；保存输出、prompt、trajectory、状态和哈希，封存到 `red-team/checkpoint-XXXX/`。
4. 将正常 artifact 与攻击 artifact 配成一对，供 rubric 更新使用。

结构性 admission 不等于攻击成功：`included=true` 仅表示 agent 正常退出且产物满足结构约束，不证明 reward hacking 成功。独立的质量比较还要识别两者优劣。

两种新 policy 的区别：

| Policy | rubric induction 能看到什么 |
| --- | --- |
| `red_team_artifact` | 正常/攻击 artifact，以及哪些 artifact 来自 red team 的标识；不提供攻击 trajectory |
| `red_team_trace` | 上述内容，加攻击执行轨迹节选；超过 32 KiB 时保留头尾并标记中间截断 |

三个 assessment 调用不接收攻击角色和轨迹；criterion validator 也不接收它们。角色/轨迹只在 induction 阶段帮助提出候选规则。新规则本身仍必须能仅凭公开提交判断，不能要求 scorer 看到攻击者的私有意图。

两种 red-team arm 都先共享 task 级 pretreatment rubric。在线 sidecar 从 `s001` 开始，在需要生成下一版 rubric 时运行；不是从 seed `s000` 额外攻击一次。若最多产生 10 次修订，一个 assignment 最多运行 9 个 sidecar（不计 provider 内部重试）。

## 2. Rubric proposer 被整体重构

旧版是“找 differences → 生成整个 active rubric set”。新版由 `evolution.py` 协调，拆出 `evolution_assessment.py`、`evolution_request.py`，并重写 `evolution_protocol.py`：

1. **Rubric-free assessment**：仅从任务质量判断每对 artifact 哪个更好。
2. **Active-rubric assessment**：给出每个 artifact 的 base score 和当前 penalty levels，代码重新计算总分与偏好。
3. **Development-rubric assessment**：对另一份开发用 rubric 做同样比较。
4. **Gap induction**：如果 rubric-free 明确偏好 A，而 active 或 development rubric 对 A 打平或更低，才视为待修复 gap；只对选入 induction 的 gaps 提规则。
5. **Blind validation + code admission**：validator 逐 artifact 应用候选规则，不知道配对和质量偏好；代码再把结果拼回去，决定是否接受。

一次更新最多五个 stage，各自有最多六次调用机会（配置 `max_retries: 5`），provider 连续/累计错误也受现有计数限制。三个 assessment 在单个更新里是顺序执行。相比旧版两个 stage，单次更新的成本更高；60 并发主要加速不同任务/assignment，不能消除一条 trajectory 内部的顺序依赖。

Admission 的关键变化：

- 候选必须可观察、非冗余，而且对每个引用的支持 pair 给质量更差的 artifact 更重的 penalty。
- 替换/合并旧 criterion 时，还必须保留被替换规则的 provenance pair 支持。
- 代码重算保留规则、替换规则和新规则共同作用后的总分，并应用零分下限。
- 在 active 和 development 两个视角，所有已观察到的非平局质量 pair 的 margin 都不能下降；引用的 gap 对应视角必须严格改善。
- “改善”不要求彻底把错误排序翻正，例如 margin 从 -20 到 -10 也算改善。
- 旧版可直接输出完整集合、任意退休规则；新版只新增或显式 replace/merge，未提及的规则继续存在，不能没有替代规则就直接删除。
- penalty 不再由模型定大小。100 分三档 rubric 的新 penalty 为 `0/-5/-10`；二档为 `0/-10`，其他尺度按约 5%/10% 归一化。

失败策略也改变：stage 重试耗尽会保存 fallback 标记并退化为平局、无候选或拒绝验证，可能产生“这次没有有效更新”但流程继续的 generation。分析时必须区分真正没有 gap 与模型/格式失败导致没有更新，不能仅看 assignment completed。

## 3. Evidence 与 paraphrase 设计变化

`contrasts.py` 不再构造全部 artifact 的完全两两图，而使用明确的 matched pairs：

- 初始化：恰好三个 ordinary seeds，与第一个被接纳的 adversarial seed 比较。
- 三个 pair 共享同一个 adversarial artifact，因此不是三个独立攻击。
- 在线：加入相邻提交 pair、最初与当前提交 pair，以及各 checkpoint 的正常/攻击 pair。
- 内容哈希去重，稳定 blinded ID 和顺序继续保留。
- gap 足够多时，约三分之一留给 validation；red-team gaps 优先留在 induction。

“留出的 pairs”不一定是留出的独立 artifacts；它们可能共享 artifact。Validation 中这些 pairs 参与 aggregate margin 不下降门槛，但不要求每个 held-out gap 都严格改善，更不能据此宣称泛化到未见过的攻击或任务。

Paraphrase 从四份变为五份：variant 0 用于优化、variant 1 用于 development assessment、variants 2–4 才是封存的 outcome holdouts。`paraphrase_validation.py` 会把 selected 和 development 两份都从 holdout 集合剔除。

## 4. Solver prompt 与 simulated-user 行为变化

`benchmarks/base.py` 改成由 benchmark 渲染 task-aware prompt。

- BioMNIBench 初始 prompt 现在直接使用任务原始 `instruction.md`，仅补充本地路径和不可联网/装包的环境约束；不再使用之前大段统一指导。
- 第一次修订包含完整任务与 feedback，之后依赖同一 persistent session 的任务上下文。
- PaperBench 继续使用自己的实现型 prompt，但通过新接口生成 revision prompt。
- 通用 revision prompt 移除了旧版一部分“仅在有充分理由时修改”等统一行为引导。即使不使用 red team，solver 行为也可能变。

User simulator 的输入从“active rubric”改成完整 evaluator feedback（包括评分、criteria、rubric 和 reasoning），它负责将其转换成面向用户的可执行建议。Prompt 明确禁止泄露分数、criterion IDs、私有 target/expected answer，只能要求 solver 从公开任务证据重算或核实。

这使 full vs simulator 更接近“同一评估信息直接展示 vs 转译为用户反馈”的比较。但防泄露主要依赖模型遵循 prompt，结构校验不能证明没有泄露参考答案。

## 5. 配置、身份及旧产物

| 配置范围 | 之前 | 新版 |
| --- | --- | --- |
| Bio/Paper 完整 Dev3（单 solver） | 3 × 3 × 12 = 108 | 3 × 3 × 20 = 180 |
| Bio/Paper 完整 Results20（单 solver） | 20 × 3 × 12 = 720 | 20 × 3 × 20 = 1,200 |
| Bio Results20 full＋simulator 专用 YAML | 20 × 3 × 6 = 360 | 20 × 3 × 4 = 240 |
| 两个 `preflights/*-elicitation-10.yaml` | 选择 10 个 assignments | 现在各选择 4 个 red-team assignments；文件名仍有 `10` |

新增必填项 `red_team_generator`、`rubric_paraphrases.development_variant`；experiment ID 还绑定 prompt 实现代码的哈希。Pretreatment 缓存同时绑定 selected 和 development rubric。Revision manifest、恢复和验证路径都新增相应身份字段，red-team 产物单独验证。

Generation 文件由两份 proposal 扩展为三份 assessments、pairwise comparisons、criterion proposal、criterion validation、aggregate margins 等。旧 YAML 和 generation 格式不能直接用于新 main；此前的 `experiments/local/` 配置完整保留在 checkpoint 分支，未硬塞回新 schema。

旧的四份 paraphrase pool 也不满足新配置的五份要求。新实验要生成当前格式的输入/产物，不能修改旧 manifest 或补造元数据来骗过验证。

## 6. Detection、报告与图表

`commands.py` 现在遍历四个 `RevisionDetectionWindow`，依次跑 full trajectory、post update、final artifact、final revision；rubric score、absolute score、pairwise preference 继续存在。

全轨迹输出目录现在按 enum 自动命名为 `direct_full_trajectory/`（旧版是 `direct_full/`）。四个窗口先读取统一的 completed revision snapshot；不再因未被引用的陈旧 submission 目录拒绝整次分析。Final-artifact 窗口也开始使用规范的终态验证。

删除 `evaluation/report.py`、四个 analysis 模块和 `lambda_estimation.py`，以及相关报告/统计测试。`detect` 不再自动生成顶层 combined summary、跨条件配对效果和 task-bootstrap 分析；每个阶段自己的记录及 summary 仍在。

`figures/biomnibench-results20-user-simulator-full-evaluation/stage_data.py` 新增从三份 score summaries 按 assignment ID 拼接的读取器；绘图、Rasch 脚本改用它。CSV/JSON 来源哈希及 PDF 被重新生成。抽查 evaluation CSV，统计数值不变、来源哈希改变；这些历史图表不能视为新 red-team 实验结果。

现有 figures 仍绑定历史 experiment ID `4f4d5d178756`、旧 `direct_full` 目录与 fixed/offline/online 三种 rubric 分类，并不是适配新 240-cell red-team 结果的通用分析器。本轮不改写历史图表，也未生成新的效果图。

README、architecture、feedback policies、elicitation workflow、evaluation formulation、concern register 及日志同步了以上变动；相关测试覆盖新矩阵、开发 rubric 隔离、配对、sidecar 封存与复用、margin admission、反馈、恢复和证据窗口。

## 7. 本轮调整与验证

按用户要求，将 `rubric-gen` 六个工作流入口（seed、paraphrase、revise、run、judge、detect）的默认 max-concurrency 统一为 60；README 的现行运行示例和两个 Bio Results20 调度脚本也改为 60。Bio/Paper YAML 没有合法的顶层 concurrency 配置项，因此没有加一个无效 YAML key。显式 `--max-concurrency N` 仍可覆盖默认值。

从 checkpoint 移植、并适配到新 main 的运行修复：

- Codex app-server 使用私有 socket 子目录，处理 macOS `/tmp` 父目录问题并清理 socket。
- Codex 子进程优先使用当前 Python 环境，允许读取必要的 Python 安装路径。
- Judge 子进程明确携带本项目 `src` 的 Python import 路径。
- 一次性 AgentRunner 将 stderr 与 JSONL 分离，发现非法 JSONL 行时失败，进程错误可以按配置重试，保存 stderr 诊断。
- adversarial seed 先在独立临时目录运行，再保存产物，避免直接在仓库子目录启动导致此前的 AGENTS/权限问题；保留新版 task-aware prompt。
- Simulator 在生成校验阶段就拒绝重复 concern category 并重试，与下游 feedback projection 的约束一致，避免“生成通过、投影报错”的真实不一致。
- 修正文档中的全轨迹输出目录，以及 concern register 对 validation pairs 不参与 admission 的过时描述。

未移植此前仅用于 Paper 单任务 Results20 的 subset 放宽，也未恢复旧 OpenAI-only YAML。根据用户追加的 key 验证要求，另移植 Gemini TLS/certifi 修复、对应测试以及明确的 certifi 依赖/lock 记录。

验证结果：

- collaborator 原始 main：696 passed、3 failed、1 skipped；包含 sandbox socket、Harvey Podman、MALT BULK 三个环境相关失败。
- 最终本地全套测试（允许本机 Unix socket）：699 passed、2 failed、1 skipped，13.54 秒。两个剩余失败是 `test_podman_environment_uses_local_storage_and_shared_cache` 和 `test_dataset_mode_requires_revision_marker`；前者依赖 Linux Podman 运行时，后者期待 REVISION 检查但先遇到本机缺少 `BULK`。
- 六个 CLI 默认值和显式覆盖已逐一检查；两个 shell 脚本通过 `bash -n`，diff 通过 whitespace 检查。
- 上述回归测试使用 fake/mocked providers；未运行 60 并发真实负载，不能据此保证 1–2 小时完成。新增 certifi 回归另有 1 passed。

追加的真实凭证测试（均通过项目 `runtime.llm` 接口，不含 benchmark 内容）：

| 模型 | Hosted token count | 结构化生成 | 实际生成用量 |
| --- | --- | --- | --- |
| `claude-opus-5` | 成功，244 tokens | 成功，返回 `{"status":"ok"}`，effective model 相同 | 244 input / 11 output |
| `gemini-3.6-flash` | 成功，149 tokens（含代码预留的 schema 开销） | certifi 修复后成功，返回 `{"status":"ok"}`，effective model 相同 | 24 input / 5 output |

`.env.local` 中两项凭证均存在，权限为 `0600` 且被 Git 忽略；测试没有打印 key。结果证明当前凭证可访问指定模型及相关接口，不代表已验证高并发配额或完整 audit 大请求。

## 8. 实验前仍需决定/处理的内容

1. **四组实验配置已确认（2026-09-05 10:23 CST）。** 用户决定按现有 240-assignment 配置继续；设计文档和 2026-09-03 20:59 PDT 日志已明确这是 artifact-versus-trace 与 full-versus-simulator 的 focused trace ablation。增加 no-red-team 对照不属于本轮要求，也不是本轮执行前置条件；结果按这两个因素解释。
2. **配置尚不适配本机。** 所有相关官方 YAML 的 task 路径仍是 collaborator 的 `/juice2/...`，本机 loader 确认找不到。目标 Bio Results20 也不是已有 Dev3 三个任务，后续需准备它指定的任务集。
3. **Audit provider 不同。** 官方 YAML 的 audit 是 Sol＋Claude Opus 5＋Gemini 3.6 Flash；此前本地矩阵是 Sol-only。用户已表示未来可加入 Gemini/Anthropic，两个更新后的 key 已验证可用；配置本身不需要再添加这两个模型。本轮没有启动三模型 audit，也未把旧 Sol-only 结果当作三模型结果。
4. **静默退化需统计。** Proposer stage fallback、red-team 结构性排除、无实质变化、规则接受数/替换数，应与 completed 数一起看；否则可能误把没有施加成功的 intervention 当作成功测试。
5. **模型判断不是真值。** 同一 Luna 家族负责攻击、quality assessment、induction 和 validation，误差可能相关；三条共享 adversarial seed 的 pair 也不是独立样本。Holdout rubric 是措辞泛化检查，不能替代新攻击/新任务泛化。
6. **分析入口需适配新实验。** 后续报告从各阶段 summary 生成，并保留失败/缺失、按 task 配对与聚类处理。没有人工或可执行 ground truth 时，RH detection rate、rubric score、pairwise preference 不能直接称为 accuracy。

目前停在“代码已同步、必要修复和 60 并发已准备、审查已完成”的阶段，等待用户讨论下一步实验方案。
