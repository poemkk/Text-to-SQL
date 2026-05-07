# 8. 原型系统实现、讨论与结论

## 8.1 原型系统设计目标

前文已经从方法设计和实验结果两个层面验证了 A²V-SQL 框架的有效性。为了进一步说明该框架不仅能够作为离线实验流程运行，而且能够被组织为一个可交互、可展示、可解释的系统闭环，本文实现了一个 A²V-SQL 原型系统。该系统围绕自然语言问题输入、schema context 构建、候选 SQL 生成与展示、执行验证、错误反馈修复、EASE 最终选择以及结果返回等环节展开，用于展示 A²V-SQL 从用户问题到最终 SQL 输出的完整流程。
该原型系统的设计目标主要包括三个方面。第一，验证 A²V-SQL 的工程可实现性，使 generate、validate、repair 和 select 这些核心步骤能够在统一界面中连续呈现，而不是仅停留在实验脚本、日志文件或表格结果中。第二，增强系统可解释性，使用户能够直观看到模型生成 SQL 所依赖的 schema context、候选来源、执行证据、修复轨迹和最终选择理由，而不仅是最终 SQL 本身。第三，突出本文在选择阶段上的改进，即将最终 practical selector 明确设置为 EASE-Selector，而不是早期的 rule-based selector，从而更符合本文后续实验中关于 selector bottleneck 的分析结论。
需要说明的是，本文原型系统的目标并不是构建生产级数据库问答平台。为了保证论文截图和答辩演示的稳定性，系统当前主要复用已有实验缓存结果，并结合确定性 repair 规则完成交互展示，而不是在演示阶段实时调用外部 LLM API。因此，该系统更适合作为研究型 prototype，用于证明 A²V-SQL 及其 EASE 选择机制具备转化为真实系统流程的可行性。

## 8.2 原型系统总体架构

A²V-SQL 原型系统采用前后端分离结构。前端基于 React 与 Vite 实现，负责任务入口、数据库与方法选择、自然语言问题输入以及 schema context、候选轨迹、修复过程和最终结果的可视化展示；后端基于 FastAPI 实现，负责数据读取、schema context 构建、候选 SQL 组织、SQLite 执行验证、repair 调用以及最终 EASE selector 决策。整体上，系统可以划分为用户交互层、服务处理层和执行验证层三部分。
其中，用户交互层面向论文展示和答辩演示，强调输入入口与中间过程的可视化；服务处理层实现 A²V-SQL 的核心闭环，包括 schema grounding、候选生成组织、执行验证、错误反馈修复和最终语义选择；执行验证层则负责与数据库环境交互，返回 exec_ok、错误信息、结果表和结果行数等证据。图 8.1 展示了原型系统的主界面入口，包含任务类型选择、数据库选择、自然语言输入框以及生成按钮，能够直接体现系统具备完整的交互入口，而不是静态实验页面。
在此基础上，图 8.2 进一步展示了原型系统的总体架构及其核心流程。与早期只强调“rule-based selector”不同，当前原型系统在第 4 步已经明确重构为 EASE final selection。也就是说，系统并不是在验证和修复之后通过简单的启发式规则输出结果，而是进一步结合 question-schema alignment、candidate SQL structure、execution evidence 和 repair trace 来完成最终 practical SQL 的选择。这一改动与论文实验部分关于 selector enhancement 的结论保持一致。

![图 8.1 A²V-SQL 原型系统主界面](/Users/kankan/Downloads/杂项/lunwen/spider_thesis/output/playwright/fig8_1_main_interface.png)

![图 8.2 A²V-SQL 原型系统总体架构与核心流程](/Users/kankan/Downloads/杂项/lunwen/spider_thesis/output/playwright/fig8_2_schema_and_candidates.png)

## 8.3 原型系统功能模块

从功能角度看，原型系统可以划分为五个模块。
第一，任务输入与配置模块。该模块提供任务类型选择、数据库选择、方法选择、示例问题切换和自然语言问题输入框。虽然系统保留了 SQL、Python 和 Java 三类任务入口，但论文展示部分以 SQL 主流程为核心，Python 与 Java 更多承担迁移能力展示作用，而不在主截图中展开复杂交互。
第二，schema context 展示模块。该模块根据用户问题对数据库表名和字段名进行 question-aware 召回，并利用外键关系补全邻接表，形成用于 SQL 生成和解释的 schema context。界面中同时展示高亮字段、匹配理由和外键关系，使用户能够看到候选 SQL 并非在“无 schema grounding”的条件下生成。
第三，候选 SQL 与验证轨迹模块。系统会展示多个候选 SQL 的来源、原始语句、初次执行状态、最终执行状态以及结果行数，用于体现多候选生成、执行验证和候选池保留机制。对于论文而言，这一模块的意义在于证明原型系统展示的并不是单一模型输出，而是一个包含竞争候选与执行证据的 candidate pool。
第四，执行验证与错误反馈修复模块。对于执行失败的 SQL，系统会展示原始错误信息，并调用 repair 模块生成修复 SQL，再次执行并给出 re-validation 结果。该模块对应 A²V-SQL 的核心创新之一，即通过数据库环境提供的 error feedback 将生成错误转化为可利用的修复信号。
第五，EASE 选择与最终结果展示模块。该模块根据候选 SQL 的执行状态、修复轨迹、结果证据以及语义匹配特征进行最终选择，并展示 selected source、selection reason、semantic features 以及最终执行结果表。当前系统中最终的 practical selector 明确设定为 EASE-Selector，这也是与旧版原型和早期 rule-based selector 最大的区别。

## 8.4 原型系统运行流程

原型系统的一次完整 SQL 运行流程如下。
首先，用户在前端选择任务类型为 SQL，并指定数据库、方法设置和自然语言问题。前端将这些信息发送给 FastAPI 后端。
其次，后端根据当前问题构建 schema context。具体做法是从问题中提取关键词，与表名和字段名进行匹配，并通过外键关系补全与当前问题强相关的邻接表，从而形成 question-aware schema pruning 结果。
然后，系统从已有实验缓存中读取对应数据库和问题的候选 SQL 集合，并对候选进行逐条执行验证。若候选 SQL 可以直接执行，则记录执行状态、结果表和结果行数；若执行失败，则保留数据库返回的错误信息，并触发 repair 逻辑生成修复 SQL，再进行 re-validation。
接着，系统将所有候选的原始执行状态、repair 状态、最终执行状态和证据摘要统一整理为 candidate trace。与早期采用简单 source priority 和 repair flag 的规则不同，当前原型系统将这些证据进一步交给 EASE-Selector，利用 question-schema alignment、candidate SQL structure、execution evidence、repair trace 以及 pairwise semantic correction 等语义特征进行最终选择。
最后，前端同时展示 schema context、候选轨迹、Validate-Repair-Re-validate 面板、EASE selector decision 和 final execution result，从而形成从自然语言输入到最终 SQL 返回的完整闭环。该流程说明，A²V-SQL 的价值不在于单次生成，而在于生成、验证、修复和选择共同构成的完整系统链路。

## 8.5 原型系统展示案例

如图 8.3 所示，原型系统主界面的第一屏主要保留论文展示真正需要的交互入口，包括任务类型选择、数据库选择、方法选择、自然语言问题输入框和生成按钮。相比早期版本中较多与工作区无关的信息，当前界面已被重构为适合论文截图和答辩展示的紧凑布局，使评审能够在一张图中直接看到系统的输入入口和实验配置入口。
图 8.4 展示了 schema context 与候选 SQL 的联合展示结果。对于给定问题，系统首先召回与问题相关的表、字段和外键关系，再展示多个候选 SQL 及其验证轨迹。这一界面用于证明原型系统并不是简单把自然语言问题交给一个通用模型后直接返回 SQL，而是先进行 schema grounding，再组织 candidate pool，为后续验证和选择提供结构化基础。
图 8.5 展示了 Validate、Repair 与 Re-validate 的关键过程。在候选集合中，如果原始 SQL 因表名错误、字段名错误或其他数据库错误而无法执行，系统会展示具体 error message，并基于 error-feedback 生成 repair SQL。修复后的 SQL 再次进入执行验证环节，从而将数据库错误转化为可利用的修复信号。该部分是 A²V-SQL 与普通 Text-to-SQL demo 的核心区别。
图 8.6 展示了最终的 EASE selector decision 与结果返回。与早期强调 rule-based selector 不同，当前展示明确将最终方法写为 EASE，并给出 selection reason、selection evidence 和 semantic features。这样，系统不仅能够展示“选中了哪条 SQL”，还能够展示“为什么它被选中”。这一点与实验部分的 selector analysis 保持一致，也更能体现本文关于 semantic selection enhancement 的核心贡献。

![图 8.3 原型系统主界面与输入入口](/Users/kankan/Downloads/杂项/lunwen/spider_thesis/output/playwright/fig8_1_control_panel.png)

![图 8.4 Schema context、候选 SQL 与验证轨迹展示界面](/Users/kankan/Downloads/杂项/lunwen/spider_thesis/output/playwright/fig8_2_candidate_trace_focus.png)

![图 8.5 SQL 执行验证与错误反馈修复界面](/Users/kankan/Downloads/杂项/lunwen/spider_thesis/output/playwright/fig8_3_validation_repair.png)

![图 8.6 EASE 最终选择与执行结果展示界面](/Users/kankan/Downloads/杂项/lunwen/spider_thesis/output/playwright/fig8_4_selector_and_result.png)

## 8.6 讨论与系统局限性

从研究展示角度看，当前原型系统已经能够较完整地证明 A²V-SQL 的工程闭环：自然语言问题可以进入 schema grounding，候选可以被执行验证，错误可以被修复，而最终结果可以由 EASE-Selector 进行 practical selection。然而，该系统仍然存在若干局限。
第一，当前原型系统主要面向论文展示与答辩场景，因此其重点是“展示完整研究流程”，而不是构建大规模在线数据库问答平台。在并发请求处理、权限控制、SQL 安全审查、日志审计和异常恢复等方面，系统仍未达到生产级要求。
第二，当前交互式主流程仍以 SQLite 为主。虽然本文实验部分已经扩展到 DuckDB、PostgreSQL 和 MySQL，并验证了 multi-backend validation 的有效性，但在原型系统中，多后端更多体现在框架展示和指标说明层，而不是统一的在线切换执行层。
第三，当前原型系统中的 repair 与 selector 仍然以研究演示稳定性为优先。repair 模块主要用于稳定展示典型执行错误的修复过程，而 EASE 选择结果则主要依赖缓存结果和可解释的语义证据展示。对于更复杂的语义歧义、长链 JOIN 路径选择和更高成本的在线 pairwise judging，仍有进一步增强空间。
第四，虽然系统保留了 Python 和 Java 的任务入口，以体现 A²V 思想的可迁移性，但第八章展示重点仍然是 SQL 主流程。这意味着跨任务统一交互界面的完整性还有继续扩展的空间。

## 8.7 本章小结与未来工作

本章介绍了 A²V-SQL 原型系统的设计目标、总体架构、功能模块和运行流程，并结合交互界面展示了自然语言输入、schema context 构建、候选 SQL 展示、执行验证、错误反馈修复和 EASE 最终选择的完整闭环。原型系统的实现表明，本文提出的 A²V-SQL 框架不仅能够在离线实验中取得较好的结果，也能够被组织成可交互、可解释、可展示的系统流程。
从结论上看，原型系统进一步强化了本文的一个核心观点：对于 Text-to-SQL 这类可执行任务，系统的最终质量不应仅由单次生成结果决定，而应由生成、验证、修复和选择共同构成的闭环决定。特别是随着 repair 扩大可执行候选池之后，最终 practical performance 的瓶颈转向 selector 阶段，因此在原型系统中明确采用 EASE-Selector 作为最终选择器，具有与实验结论一致的理论和工程意义。
未来工作可以从三个方向继续推进。第一，引入更强的在线 LLM service 与更完整的 pairwise semantic judging，使 EASE 在复杂歧义问题上的语义判断能力进一步增强。第二，将 SQLite、DuckDB、PostgreSQL 和 MySQL 统一接入交互式原型，实现真正的多后端在线切换与结果对比。第三，扩展 Python 和 Java 路由的细粒度可视化，使跨任务的 A²V 原型系统更加完整和统一。
