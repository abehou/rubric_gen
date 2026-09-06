# Results20 v7：完整实验报告

完成时间：2026-09-06 02:20 CST；报告生成于 02:22 CST。

## 结论

实验已跑完并通过完整覆盖、一致性与 provenance 验收：20 tasks × 3 replicates × 4 conditions = 240 assignments，7 个审计阶段共 9,327 条唯一评分，无缺失模型或被排除 assignment。最后一条 Claude absolute 请求在延迟后的串行恢复中成功；恢复保留全部已有评分。

结果**部分支持**预期方向：user simulator 的 original-rubric 与 rubric-free quality 差距明显小于 full；最终产物的 direct RH 检出率也较低。但不能据此声称四项指标均有可靠改善、dynamic rubric 已优于其他 rubric policy，或 red teaming 本身有效。

## 设计与分析口径

- 四组为 full/simulator × red-team artifact/trace，每组 60 assignments、20 tasks。
- Solver、proposer、red-team 与 weak judge 为 Luna；强评估面板为 Sol、Claude Opus 5、Gemini **3.8 Flash**，不是旧 goal 文本中的 3.6。
- 采用固定的 task 等权、task 内 replicate 等权；比较按 task/replicate/solver 配对。95% 区间为 10,000 次 task-cluster percentile bootstrap，seed 20260905，未做多重比较校正，属于探索性证据。
- Direct 指标按三模型 any-detect 聚合到 assignment；无检出但有 abstention 时保留上下界，不把 abstention 当作无 RH。下表百分比范围是 abstention 识别界，不是置信区间。
- 三个分差保留正负号，不取绝对值或截断。它们是诊断代理指标，不等同于真实 reward hacking。

## 四项主要指标

前三列单位为分，末列为 assignment 比例。按照本次预设方向，数值较低更符合目标，但负分差也可能反映校准差异。

| 条件 | weak − strong original | selected − holdout | original − rubric-free | 最终产物 direct RH |
| --- | ---: | ---: | ---: | ---: |
| Full + artifact | 3.67 | 0.44 | 13.58 | 5.0–6.7% |
| Full + trace | 5.07 | −0.50 | 14.52 | 3.3% |
| Simulator + artifact | 3.66 | 0.04 | 4.16 | 0% |
| Simulator + trace | 4.32 | −0.63 | 5.07 | 0% |

Simulator − full 的配对比较：

| 指标 | Artifact 差值 [95%区间] | Trace 差值 [95%区间] |
| --- | ---: | ---: |
| weak − strong | −0.01 [−2.54, 2.23] | −0.76 [−3.24, 1.86] |
| selected − holdout | −0.40 [−1.60, 0.80] | −0.13 [−1.08, 0.91] |
| original − rubric-free | −9.42 [−15.66, −4.03] | −9.45 [−14.63, −4.99] |
| 最终产物 direct RH | −6.7 至 −5.0 pp [−18.3, 0] | −3.3 pp [−10.0, 0] |

因此：点估计方向基本符合 simulator 更低的预期，但前两项区间跨零，最终产物 direct RH 区间触及零。Simulator 的样本中零检出不意味着总体风险为零；普通经验 bootstrap 在全零样本上会退化为零区间，不能当作风险上限。

## 其他窗口与质量

| 条件 | 全轨迹 RH | Post-update RH | Final-revision RH | 最终 rubric-free quality | quality 相对 initial 增量 | 最终产物 pairwise preference 分数 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Full + artifact | 20.0% | 5.0–6.7% | 6.7% | 80.05 | −1.47 | 0.658 |
| Full + trace | 26.7% | 6.7–8.3% | 6.7% | 78.84 | −2.67 | 0.650 |
| Simulator + artifact | 5.0–8.3% | 6.7% | 0% | 82.38 | +0.87 | 0.694 |
| Simulator + trace | 3.3–5.0% | 1.7–3.3% | 0% | 82.12 | +0.60 | 0.722 |

Trace 条件下 simulator − full 的全轨迹 RH 差为 −23.3 至 −21.7 pp，bootstrap 区间 [−41.7, −6.7] pp；artifact 对应区间 [−28.3, 0] pp。不同窗口捕捉不同时间段的行为，最终产物检出少不能说明中间过程没有 RH。

Simulator 最终 quality 比 full 高 2.33 分（artifact；区间 [−0.48, 5.54]）和 3.27 分（trace；[−0.64, 7.27]），区间均跨零。四组 selected-rubric 分数增量约 32–40 分，而 rubric-free quality 增量约 −2.7 至 +0.9 分；不能把 rubric 分数上涨直接解释为真实质量提升。

## 实际处理过程与限制

实际在线 rubric 生成 1,182 次，只有 95 次 rubric 文本变化，涉及 85/240 assignments，新增 96 条 criteria。因此“启用 dynamic policy”不等于“每次都更新 rubric”。

Full artifact/trace 平均执行轮数为 5.18/5.15，simulator 为 8.32/7.93；达到 horizon 上限的数量分别为 1/0/35/31（每组 60）。处理暴露量不等，不能将结果直接解释为相同轮数下的纯反馈差异；没有做事后按轮数筛样本或归一化。

共有 5 次 proposer 响应校验 fallback（4 个 assignments），以及 6 个被封存排除的 red-team sidecar；均保留并记录，没有选择性重跑这些处理结果。Sidecar 不作为自然 RH outcome。详见 [treatment-delivery.md](treatment-delivery.md)。

本设计没有 no-red-team control，也没有不同 rubric policy 的完整比较。因此本次可比较 artifact/trace 与 full/simulator，不能独立证明加入 red team 的收益，或推广为“无论什么 rubric policy，simulator 都更低”。继续采用用户批准的四组设计，没有添加 control 作为完成前提。

## 运行可靠性与时间

这次是**经故障恢复后完成**，不是无错误的一次性运行。历史问题包括 Gemini 地区拒绝与输入 TPM 限流、多个 provider 的连接错误、Claude quality 单请求重复断连，以及缓存读取前准备失败造成的汇总不一致；最终所有评分和汇总已恢复，不代表根因全部永久修复。

Revision 在 09-05 约 14:40 开始、21:41 完成，含失败和恢复约 7 小时；审计在当晚开始并于 09-06 02:20 完成。因此未达到最初完整实验约 1–2 小时的期望，不能仅报告最后一次恢复时长。并发按阶段由 30/12 调整到恢复时的 1–2，不能用最高并发解释全程吞吐。

本轮两次 full-window 准备用时约 8 分钟，即使最后只缺少数评分、甚至全部命中缓存，也有明显恢复开销。最后 Claude 请求在约 40 分钟后同代码重试成功，支持故障具有暂态因素，但不能据此定位究竟是 provider、连接路径还是请求相关问题。

## 下一版本优先事项（未在本轮中实施）

1. 首先改进 provider-aware pacing，识别并遵守 429 RetryInfo，区别永久权限/地区错误和暂态连接错误；不要用盲目提高并发替代限流调度。
2. 优化 resume 的缓存验证顺序与准备开销，避免已有完整评分因非必要准备请求断连而使汇总失败；保持真实验证与 provenance，不伪造缓存身份。
3. 修复 quality APIConnectionError 的错误记录/恢复路径，并用最小真实端到端测试验证，再冻结新版本。
4. 在新版本中检查 rubric 分数大幅增长但真实质量增量不明显的具体案例，并研究 simulator 长轮数与 rubric 更新稀疏的机制；不按期望方向筛选样本或修改既定指标。

## 文件与复现

- [完整验收](audit-coverage-complete.json)：240 assignments、7 stages、9,327 unique judgments。
- [全部分析及 assignment-level 数据](outcomes.json)：四组、配对差值、所有区间与分析方法。
- [Full-window 独立验证](full-trajectory-completion-verification.json)。
- [实验输出索引](../../../EXPERIMENT_RUNS.md) 与 [实验计划](../../../EXPERIMENT_PLAN.md)。
- 原始 revision：`runs/studies/20260905-redteam-v7/biomnibench-da-factorial-r10-8ab12c898ae7`。
- 原始 audit：`runs/detections/20260905-redteam-v7-audit-v2/biomnibench-da-factorial-r10-8ab12c898ae7`。
- 冻结 provenance：`runs/provenance/20260905-redteam-v7/audit-v2/`；base commit `c45e591` 加归档的本地修改，不能只靠 Git commit 复现。运行代码/配置/分析维持归档身份，AGENTS.md 的文档维护差异另有记录。

本报告是完成该次实验的交付，不声称后续性能优化或科学假设已经全部实现。
