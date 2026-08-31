# QwenPaw HintBlock 提示注入改造设计

- 文档类型：功能设计
- 日期：2026-08-31
- 适用版本：QwenPaw `main`、AgentScope `2.0.7.post1`、
  ReMe AI `0.4.1.5`
- 状态：待评审，尚未实施

## 1. 执行摘要与设计决策

QwenPaw 当前把多种“模型可见、用户不可见”的运行时信息包装为
`TextBlock`，再依赖 `<system-info>`、`<system-notification>`、message name
或 metadata 在 Console 恢复历史时隐藏。Mission Master 指令、loop
continuation、后台工具通知、skill 正文和动态时间是主要案例。

问题的根源不是 XML 标签，而是系统混淆了四个独立维度：

1. 内容是否发送给模型；
2. 内容是否展示给用户；
3. 内容是否保存在会话 context；
4. 内容是否进入语义长期记忆。

AgentScope `HintBlock` 只解决第一个维度的类型表达。Console event、session
state、context archive 和 memory backend 仍需要分别定义边界。

本方案采用以下最终决策：

| 决策 | 结论 |
|---|---|
| 内部提示类型 | 使用 assistant `Msg` 中的 `HintBlock` |
| XML 标签 | 可保留模型语义结构，但不再承担 UI 隐藏职责 |
| Console | 所有内部 HintBlock 不进入可见 transcript；内部 HintBlockEvent 默认不发送或在 projection 层丢弃 |
| live context | session/runtime hint 保留，保证模型连续性和 session resume |
| 一次性增强 | 模型使用后按 block id 删除，不进入后续 context |
| compression | 允许 hint 指导 continuation summary，并增加语义回归测试 |
| Scroll | 完整 blocks 可恢复；FTS、headline 和 recall 不包含 hint 正文 |
| Memory backend | 先建立 legacy-compatible projection，再交给 ReMe、ADBPG、proactive 原有逻辑 |
| context archive | 为恢复保留 hint，但按内部数据执行访问控制和 retention |
| source | 用于选择明确的 memory 兼容投影策略；所有已知 source 必须有测试 |

实施顺序调整为：先建立 memory/UI 边界和测试，再迁移高价值注入点，随后
启用原生时间注入，最后处理 Scroll/offload 的增强项。

## 2. HintBlock 语义与生命周期

### 2.1 AgentScope 行为

当前安装版本定义：

```python
class HintBlock(BaseModel):
    type: Literal["hint"] = "hint"
    hint: str | list[TextBlock | DataBlock]
    source: str | None = None
```

关键约束：

- HintBlock 只能放在 `role="assistant"` 的 `Msg` 中；user/system message
  不接受 HintBlock。
- formatter 会把 HintBlock 转换成独立的 user-role provider message。
  HintBlock 在 state 中的宿主 role 与最终 wire role 不相同。
- `hint` 支持文本或 `TextBlock | DataBlock` 列表，可承载后台工具的多模态
  结果。
- HintBlock 持久化与 HintBlockEvent 展示相互独立。AgentScope 默认 Console
  会渲染 HintBlockEvent。
- AgentScope runtime-state 会把 HintBlock 持久写入 context，用于时间感知、
  任务提醒和 prompt cache 稳定性。

### 2.2 生命周期分类

```text
ephemeral hint        -> 本轮 reasoning 后删除
session/runtime hint  -> AgentState 与 Scroll blocks 保留，UI 隐藏
compression hint      -> 只作为本次压缩指令，不写入 live context
memory backend input  -> 投影为迁移前的等价 Msg/TextBlock 视图
context archive       -> 为恢复保留，按内部数据治理
```

典型映射：

| 类型 | 示例 | 生命周期 |
|---|---|---|
| runtime | current time、task state、context length | 保留到被压缩；需要时重新注入 |
| loop control | Mission/Goal continuation、doom-loop reminder | 保留在当前回复上下文，允许参与压缩 |
| tool offload | 后台工具完成通知与结果 | 默认 session 级；仅一次消费的结果可改为 ephemeral |
| retrieval | RAG、memory recall | 优先 ephemeral；确需跨轮引用时才持久 |
| compression instruction | `/compact <instructions>` | 仅进入 compression model input |
| user-visible content | 用户输入、assistant 最终回答、命令结果 | 不使用 HintBlock |

这里的“等价”不是简单保证 memory backend 不报错，而是要求迁移前后的
memory 输入在
以下方面保持一致：

- 相同的消息角色和时间顺序；
- 相同的可提取文本，包括 `<system-reminder>`、`<system-notification>`、
  Mission Master prompt、skill 正文、上传文件路径提示和 Bootstrap guidance；
- 当前会被 turn snapshot 排除的内部控制消息，迁移后仍然排除；
- 多模态提示中原先位于顶层的 TextBlock/DataBlock，在 ReMe 副本中恢复为
  原先的顶层结构。

## 3. QwenPaw 提示信息盘点

### 3.1 第一批迁移范围

| 注入点 | 当前实现 | 主要问题 | 目标实现 |
|---|---|---|---|
| `runtime/runtime.py::_apply_context_injections` | user Msg + TextBlock | API 名为 hint，但内容可能进入 transcript/memory | 真实用户消息之后追加 assistant Msg + HintBlock |
| `tool_calls/_hint.py` | assistant Msg 中的 notification/result TextBlock/DataBlock | 被当作 assistant 回复展示；wire role 不符合“新观察”语义 | 单个多模态 HintBlock，包含 notification 与 result |
| `agents/react_agent.py` loop continuation | synthetic user Msg + tagged TextBlock | 依赖 metadata/name/tag 多层过滤 | append 到当前 assistant reply 的 HintBlock |
| Mission 首轮 | Master prompt 覆盖真实 user TextBlock | 用户卡片显示内部 Master 指令 | user TextBlock 只保留任务；Master 指令放 assistant HintBlock |
| slash skill fallback | 用户文本尾部拼接 `<skill>` | 历史展示依赖正则；skill 正文可能被当用户事实 | typed command 保持 user TextBlock；skill body 放 assistant HintBlock |
| `agents/utils/message_processing.py::_format_uploaded_file_hint` | 下载路径提示插入真实 user Msg 的 TextBlock | 内部本地路径可能展示给用户；ReMe/ADBPG 已能读取 | DataBlock 保留在 user Msg；路径提示放后继 assistant HintBlock |
| `agents/hooks/bootstrap.py` | guidance 前插真实 user TextBlock | 内部 bootstrap 控制指令被归为用户正文 | 原始 user text 保留；guidance 放后继 assistant HintBlock |

loop continuation 的统一改造覆盖 Mission、Goal、custom loop、doom-loop 和
completion rubric，不分别为每个 gate 建立私有注入协议。上传文件提示和
Bootstrap guidance 都要求 memory compatibility projection 恢复原来的 user
文本位置：上传提示恢复到对应 DataBlock 之后，Bootstrap guidance 恢复到首个
user TextBlock 之前。

### 3.2 Formatter 与 request-transform 产生的提示

以下路径也会生成“给模型看的提示文本”，但它们运行在 provider request 的
深拷贝或 wire payload 上，不写入 live context：

| 路径 | 生成内容 | 生命周期 | 设计结论 |
|---|---|---|---|
| `providers/capping_formatter.py::CappingFormatterMixin` | oversized/unprepared media placeholder | 单次 provider wire request | 保持 formatter placeholder，不迁移为 HintBlock |
| `agents/model_factory.py::_replace_media_reference` | deleted/download-failed/oversized media placeholder | normalized request copy | 保持 TextBlock；不得进入 UI、Scroll 或 memory |
| `model_factory.py` media dedup/video substitution | already-shown/omitted placeholder | 单次 provider wire request | 保持 provider adapter 行为 |
| `message_request_normalizer.py` capability downgrade | unsupported-media placeholder | retry request copy | 保持 request-only，不回写 state |
| visual compression `visual_context`/`visual_history` | user-role images、recovery marker、env tail | 单次压缩后的 request copy | 保持 user role；不改为 HintBlock |

`CappingFormatterMixin` 不是 UI 泄漏来源。把它生成的 placeholder 持久化为
HintBlock 反而会改变 session、memory 和下一轮请求，因此禁止这样改造。它与
HintBlock 的交点只在于：后台工具等迁移为多模态 HintBlock 后，formatter
必须递归处理 `HintBlock.hint` 内的 DataBlock，并保持原有 cap、失败降级和
provider-specific media 行为。

当前源码已经支持递归收集 HintBlock 内的本地 media，并覆盖 OpenAI image、
Anthropic video、DashScope video 的准备路径；但仍有两个缺口：

- capability downgrade 的 `_strip_media_blocks_in_place()` 只递归
  ToolResultBlock，不递归 HintBlock，fallback 后可能继续携带不支持的 media；
- OpenAI video substitution 跳过所有 assistant Msg，HintBlock 中只有 video
  时当前会被 formatter 整条丢弃。迁移 background tool video 前必须增加文本
  fallback 或显式禁止该组合，不能静默损失模型观察。

### 3.3 System prompt contributor

`MultimodalHintContributor`、`DriverPolicyHintContributor` 和
`EnvContextContributor` 虽然也生成 hint/guidance，但当前只组成 system
prompt，不进入 Console transcript 或 memory backend。不能仅因名称中有
`hint` 就迁移：

- multimodal capability、Driver policy 保持 system prompt contributor；
- env 中动态 Current date 按下一节迁移到 AgentScope runtime-state HintBlock；
- 若未来把其他 contributor 改为 HintBlock，其 memory 策略必须是
  `exclude_as_before`，避免新增长期记忆输入。

### 3.4 时间与运行状态

当前 `build_env_context()` 把 `Current date` 放入动态 system prompt，
`QwenPawReActAgent` 同时配置
`InjectionConfig(inject_runtime_state=False)`。

目标方案：

- 启用 AgentScope `inject_runtime_state=True`；
- timezone 使用 QwenPaw `user_timezone`；
- 设置 `emit_hint_event=False`；
- 从动态 system prompt 删除 `Current date`；
- 固定 OS、shell、workspace 等信息继续留在 system prompt；
- 使用 AgentScope 默认 runtime-state template，不额外建立 QwenPaw 时间协议。

旧时间被 Scroll/native compression 移出 active context 后，AgentScope 会因
找不到对应 source 的时间 hint 而重新注入当前时间。

### 3.5 暂缓迁移

| 注入点 | 暂缓原因 |
|---|---|
| Scroll `<system-info>[context compressed]...` placeholder | 已有 synthetic id 和 metadata 隐藏；迁移会改变 role、FTS、visual compression 和恢复假设 |
| visual compression 的 `visual_context` / `visual_history` | 依赖 user-role 多模态布局、token 收益计算和 recovery marker，应单独设计 |
| auto-memory-search 模拟 tool interaction | tool call/result pairing 是协议语义，不是普通提示 |
| Scroll continuation summary / eviction index | 属于 context 表示，不是 UI 泄漏的原始注入点 |

### 3.6 明确保留现有 block 类型

以下内容不迁移为 HintBlock：

- 用户输入和 assistant 最终回答；
- `/mission status`、`/mission list`、错误消息和命令帮助；
- 普通 tool call/result；
- 用户中断工具时补写的 `ToolResultBlock(state=INTERRUPTED)`；
- file read continuation 等真正属于工具输出的提醒；
- provider formatter/request-transform 层为 media 能力生成的临时 placeholder。

### 3.7 QwenPaw 已有支持

- `app/chats/utils.py` 恢复历史时已跳过 `type="hint"`；
- `runtime/envelope.py` 已不渲染 HintBlockEvent；
- `model_factory.py` 已支持 HintBlock 的 user-role wire 转换及本地多模态；
- `/compact <instructions>` 已使用 `HintBlock(source="user")`；
- AgentScope provider formatter 已覆盖主要模型后端。

因此改造重点是统一注入与生命周期，不是新增一种前端消息类型。

## 4. Context 与 Memory 兼容性矩阵

### 4.1 AgentScope 原生能力

| 组件 | 当前行为 | 判断 |
|---|---|---|
| `AgentState.context` | HintBlock 完整 JSON 序列化与恢复 | 正式支持，必须保留 |
| formatter | HintBlock 转换为独立 user wire message | 正式支持，需验证顺序 |
| token counting | 计算文本和多模态 hint | 正式支持 |
| native compression | 已有 hint 和显式 compression instructions 都对 summarizer 可见 | 支持，但需语义测试 |
| runtime-state | 按 source 检测旧 hint，压缩后自动补注入 | 可直接采用 |
| workspace offload | 完整 Msg 写入 context JSONL | 支持恢复，但会保存 hint 明文 |
| RAG middleware | 默认 `persist_hint=False`，reasoning 后删除 | 可作为 ephemeral 模式参考 |
| Agentic Memory | 查询取 `get_text_content()`；召回结果用 HintBlock | 不自动采集 hint |
| Mem0 middleware | 写回仅使用 user query 和 final assistant text | HintBlock 不进入 Mem0 |
| ReMe middleware | 召回结果使用 HintBlock；写回仅排除自身 `name="memory"`，其他 hint 原样 dump | 只支持 recall→model，不具备通用 hint→memory 语义 |

### 4.2 QwenPaw Scroll

已有能力：

- provider token counting 已计算 HintBlock；
- `msg_to_entries()` 使用 `get_text_content()`，hint 不进入 FTS content；
- 完整 blocks JSON 可以保存并恢复 HintBlock；
- `recall_history` 不渲染 hint；
- splitter 可按 block 边界保留或压缩 assistant HintBlock。

需要补强：

- hint-only assistant message 不生成无意义 searchable row；
- blocks round-trip、split、recall 和 continuation summary 增加明确测试；
- compression summary 不能把控制模板误写为“用户事实”；
- 旧 synthetic user stub 和 XML cleanup 至少保留一个兼容周期。

### 4.3 ReMe Light `0.4.1.5`

必须区分 AgentScope 上游 middleware 和 QwenPaw 当前实际运行链路：

| 链路 | HintBlock 行为 |
|---|---|
| AgentScope `ReMeMiddleware` recall→model | `_build_memory_message()` 构造 assistant Msg + HintBlock，formatter 再转成 provider user message |
| AgentScope `ReMeMiddleware` agent→memory | turn increment 只排除其自身 `name="memory"` 消息；其他 HintBlock 未展开、未过滤，直接 `model_dump()` 给 `auto_memory` |
| AgentScope query extraction | 只读取输入 user Msg 的 `get_text_content()`；不读取 HintBlock |
| QwenPaw 当前运行链路 | `BaseMemoryManager.build_middlewares()` 使用 QwenPaw `MemoryMiddleware`，没有挂载 AgentScope `ReMeMiddleware` |

因此，“AgentScope ReMeMiddleware 使用 HintBlock”只证明召回记忆可以通过
HintBlock 提供给模型，不代表它能把对话 HintBlock 正文写入长期记忆。上游
middleware 也不能自动修复 QwenPaw 当前路径，因为它并未参与该路径。

QwenPaw `MemoryMiddleware` 先通过 `_messages_for_user_turn()` 或已保存的 turn
snapshot 选出本轮消息，再调用 `ReMeLightMemoryManager.auto_memory()`；后者最终
由 `summarize()` 把
`Msg.model_dump(mode="json")` 原样传给 `auto_memory_step`。源码与可执行验证
结果如下：

| 链路 | 实际行为 |
|---|---|
| 输入解析 | `_to_msg()` 使用 AgentScope `Msg.model_validate()`，能解析 HintBlock |
| daily note 提炼 | `format_history()` 只取 `get_text_content()`，不会把 hint 发给 memory LLM |
| raw session 保存 | `_sanitize_msg_for_save()` 不删除 hint，完整正文写入 JSONL |
| session read/index/search | 渲染时只取 `get_text_content()`，hint 不可检索 |
| hint-only message | 提炼时跳过；raw JSONL 仍保存；渲染只剩无正文消息头 |

结论：ReMe 不会因 HintBlock 产生 schema error，也不会把 hint 提炼为 daily
note。它会把 HintBlock 保存在 raw session，但 `format_history()`、索引和搜索
均不消费其正文，形成“可序列化但无记忆效果”的非对称支持。也正因为
`get_text_content()` 忽略 HintBlock，如果 QwenPaw 只是把原有 TextBlock 改成
HintBlock，ReMe 会丢失迁移前能够读取的内容，造成记忆效果回退。因此 ReMe
不能直接消费迁移后的 live Msg，也不能统一删除 HintBlock，而必须消费一个
保持旧行为的 compatibility projection。

各迁移点的旧行为基线与目标投影如下。该投影是所有 memory backend 共用的
输入边界；表中的 ReMe 视角用于说明信息最完整的消费路径：

| source/场景 | 迁移前 memory 视图 | 迁移后的 shared compatibility projection |
|---|---|---|
| background tool offload | assistant message 中的 notification 和 result 顶层 blocks | 将 HintBlock 的 string 或子 blocks 展开回同一 assistant message |
| Mission 首轮 | external user message 中的完整 Mission prompt | 使用共享 Mission formatter 重建同一份完整 user text |
| slash skill | external user text 后拼接完整 `<skill>` block | 使用共享 skill formatter 将 hint 重新合并到同一 user text |
| uploaded file | 路径提示位于 external user Msg 内对应 DataBlock 之后 | 按原 DataBlock id/index 将提示插回同一 user Msg |
| Bootstrap | guidance 位于首个 external user TextBlock 之前 | 将 guidance 前插回同一 user Msg |
| runtime context injection | 位于 external user marker 之前，被 turn snapshot 排除 | 删除该 hint carrier，继续不提交给 ReMe |
| loop continuation | internal user message，被 `_messages_for_user_turn()` 排除 | 删除对应 loop hint，继续不提交给 ReMe |
| AgentScope runtime time/tasks | 旧实现只在 system prompt，ReMe 看不到 | 删除 runtime-state hint，避免新增 memory 输入 |
| `/compact` instructions | 只传给 compression model，不在 live turn 中 | 保持不提交给 ReMe |

兼容投影的主落点必须是 QwenPaw `MemoryMiddleware`：在它完成 external-user
turn/snapshot 选择之后、调用具体 memory manager 之前执行。这样 ReMe、ADBPG
及未来接入同一 middleware 的 backend 共用一份兼容语义，而不是只在
`ReMeLightMemoryManager.summarize()` 内打补丁。它操作深拷贝并保留原消息 id、
role、created_at、metadata、block 顺序和消息顺序，不修改 live AgentState 或
Scroll 数据。

proactive 的 session reader 不经过该 auto-memory 调用点，必须在自己的
text-only 清理之前调用同一个纯 projection 函数。若未来 QwenPaw 改用
AgentScope `ReMeMiddleware`，则必须在其 `_write_back()` 调用 `auto_memory`
之前接入同一投影契约，不能假设上游现状已经处理。

对未知 HintBlock source，不允许静默丢弃。默认策略是展开为同消息 TextBlock
并记录 warning，从而优先避免 memory 信息损失；测试必须推动所有生产 source
进入显式策略表。

需要合并回 user Msg 的 HintBlock carrier 必须在 namespaced metadata 中按
HintBlock id 记录稳定的 target 与 position。上传文件使用对应 DataBlock id 作为
anchor；Bootstrap 使用 `before_first_text`；skill 使用 `append_text`。不得依赖
迁移后的相邻消息下标猜测位置，因为 Scroll split/compression 可能改变邻接关系。

版本注意：ReMe `0.4.1.5` 的 `core` extra 元数据约束 AgentScope
`2.0.4.post1`，QwenPaw 实际运行 `2.0.7.post1`。当前组合已验证可用，但需
纳入依赖兼容测试。

### 4.4 ADBPG、proactive memory 与 session

- ADBPG 只持久化 external user-role `get_text_content()`。Mission/skill 从
  user TextBlock 拆成 assistant HintBlock 后，如果不先重建 legacy view，
  ADBPG 会丢失原先能够保存的内容；
- proactive session reader 只保留 `type="text"`。它也必须在 text-only 清理前
  应用同一 compatibility projection；
- shared projection 只恢复迁移前的消息表示；之后 ReMe 继续读取全角色文本、
  ADBPG 继续只持久化 user、proactive 继续执行原有 text-only 清理。因此既不
  减少原来可见的信息，也不扩大各 backend 原有的采集范围；
- AgentScope session/state 可以直接 round-trip HintBlock；
- 不迁移历史 JSON，新逻辑只影响新消息；
- manual `/compact` instructions 不写入 live context，也不参与 ReMe 投影。

## 5. 已确认的源码遗漏与风险

### 5.1 展示边界

HintBlock 本身不保证前端不可见。AgentScope 默认 Console 会渲染
HintBlockEvent，runtime/RAG 可以配置 emit，inbox/team 等链路还会主动发出
event。QwenPaw 必须同时控制：

- 实时 event projection；
- session/history projection；
- 调试视图是否允许查看内部 hint。

### 5.2 Message ordering

formatter 会把 assistant message 中的 HintBlock 拆成独立 user wire
message。迁移时最大的模型行为风险是顺序变化，而不是序列化失败。

必须断言：

- 首轮为真实 user task，随后是 assistant-hosted hint 转换出的 user reminder；
- loop hint 位于当前 assistant 结果之后、下一次 reasoning 之前；
- hint 前后的 tool call/result pairing 不被拆断。

### 5.3 Memory 与归档

- ReMe 的 `get_text_content()` 不读取 HintBlock；缺少 compatibility projection
  会直接丢失原 TextBlock 中的工具提醒、Mission 和 skill 信息；
- ADBPG/proactive 同样依赖 TextBlock；只修 ReMe 会导致不同 memory backend
  在迁移后产生不一致行为；
- 如果直接把 HintBlock 交给 ReMe，hint 正文会进入 raw session JSONL，却不会
  进入 memory LLM 和 search/index，形成“落盘但无效果”的不一致状态；
- projection 后参与 raw session、提炼和检索的内容必须与迁移前一致；不得因为
  block 类型变化减少 reminder 信息，也不得让迁移前被排除的控制信息新增进入
  memory；
- 按 source 选择投影是为了恢复迁移前语义，不是为了隐藏内容。错误的 source
  映射会改变 ReMe 的角色归因、消息顺序或正文；
- AgentScope/QwenPaw context offloader 会保存完整 hint，这是 session recovery
  语义，但需要独立的数据保留策略；
- AgentScope workspace offloader 只外置顶层 base64 DataBlock，未递归处理
  HintBlock 或 ToolResultBlock 内嵌数据，可能生成超大 JSONL；
- source 并非所有 middleware 都填写；未知 source 必须采用保守的文本展开并
  告警，不能静默删除；
- 高频 memory retrieval 的持久 hint 会累积 token，应优先采用 ephemeral
  生命周期或提供明确清理点。

### 5.4 语义风险

native compression 会把 active context 中的 HintBlock 发送给 summarizer。
这对于 Mission 状态、工具结果和运行提醒是合理的，但 summarizer 可能把控制
文本错误归因为用户要求。必须用测试约束 summary 的归因和表述。

### 5.5 Formatter 与多模态 HintBlock

- capping、media preparation、能力降级和 visual compression 都只应修改请求
  副本；任何回写 live context 的变化都属于行为回归；
- `HintBlock.hint` 可以包含 TextBlock/DataBlock，所有递归 block walker 必须
  对 HintBlock 和 ToolResultBlock 采用一致的遍历策略；
- cap placeholder 只对当前模型请求可见，memory projection 必须恢复迁移前的
  原始 DataBlock/TextBlock 视图，而不是保存 provider-specific placeholder；
- provider 不支持某类 HintBlock media 时必须生成明确的文本 fallback，不能像
  当前 OpenAI hint-only video 路径一样静默形成空 formatted message；
- visual compression 的 synthetic user role 是 provider 输入协议，不是用户身份
  归因；它作用于深拷贝且不进入 memory，因此不应机械替换为 assistant
  HintBlock。

## 6. 目标架构与数据流

### 6.1 Block 契约

```text
真实用户/assistant 内容        -> TextBlock / DataBlock
tool-call 协议结果              -> ToolResultBlock
模型可见、用户不可见的运行状态  -> assistant Msg + HintBlock
一次性检索/增强内容              -> ephemeral HintBlock
provider 临时适配内容            -> formatter 层转换，不写入 state
```

XML tag 只描述模型语义，例如 `<current-time>` 或 `<tasks>`；UI、memory 和
retention 决策只依据 typed block 和生命周期元数据。

### 6.2 写入与投影

```text
                          +--> model formatter: HintBlock -> user wire message
typed Msg -> live context +--> UI projection: drop HintBlock
                          +--> Scroll: keep blocks, omit searchable text
                          +--> QwenPaw MemoryMiddleware
                               +--> compatibility projection: restore legacy view
                               +--> ReMe / ADBPG existing filters
                          +--> proactive session reader
                               +--> same projection -> text-only cleanup
                          +--> context archive: keep for recovery, protect data
```

应集中提供两个边界能力：

1. internal hint 构造规则：统一 assistant role、source 命名和 event 策略；
2. shared memory compatibility projection：由 QwenPaw `MemoryMiddleware` 在
   turn selection 后调用，按照 source 将 HintBlock 展开、合并、重建或排除，
   生成迁移前等价的消息副本，再交给 ReMe、ADBPG 各自的既有过滤逻辑；
   proactive 在自己的 session-reader 边界复用同一纯函数，不修改 live
   context。

compatibility projection 只处理消息表示差异，不重新判断“什么值得记忆”。
记忆内容选择继续由现有 turn snapshot 和各 memory backend 的既有逻辑完成。

### 6.3 注入顺序

- 首轮：真实 user Msg 在前，Mission/skill/runtime assistant HintBlock 在后；
- ReAct continuation：HintBlock append 到当前 reply 的 assistant message；
- 后台工具：多模态 HintBlock 在下一次 reasoning 前进入 context；
- formatter：统一负责 HintBlock 到 provider user message 的转换；
- 调用方禁止手工伪造 user-role hint。

### 6.4 Source 命名

source 用于诊断、去重和生命周期识别，建议稳定命名：

```text
qwenpaw:runtime-state
qwenpaw:context-injection
qwenpaw:mission-master
qwenpaw:loop:mission
qwenpaw:loop:goal
qwenpaw:loop:custom
qwenpaw:tool-offload
qwenpaw:skill
qwenpaw:uploaded-file
qwenpaw:bootstrap
user
```

`qwenpaw:memory-recall` 不列为当前生产 source：QwenPaw auto-memory-search
目前使用完整 tool call/result interaction，不是 HintBlock；AgentScope 上游
ReMe recall 则使用保留的 `name="memory"` carrier，并由其 middleware 自行排除
写回。两条机制不能混用 source 规则。

source 同时作为 memory compatibility projection 的路由键。每个迁移 source
必须明确声明以下策略之一：

```text
expand_same_message      # 恢复为同角色、同位置的 TextBlock/DataBlock
merge_previous_user      # 按 metadata anchor/position 合并回目标 user message
rebuild_previous_user    # 调用共享 formatter 重建原 user message
exclude_as_before        # 迁移前未进入 memory turn，继续排除
```

未知或空 source 默认 `expand_same_message` 并记录 warning，保证不会无声丢失
信息；生产 source 缺少显式策略应由测试失败发现。

## 7. 详细实现设计

### 7.1 模块边界

新增两个小模块，不把 memory 规则散落到各注入点：

```text
src/qwenpaw/agents/hints.py
    source 常量
    carrier metadata schema 常量
    assistant HintBlock/carrier 构造函数

src/qwenpaw/agents/memory/hint_projection.py
    source -> projection action 注册表
    project_messages_for_memory(messages)
```

`hints.py` 不依赖任何 memory backend；`hint_projection.py` 只依赖 AgentScope
message model 和前者的稳定常量，不导入 ReMe、ADBPG 或 proactive。这样 UI、
formatter 和注入代码不反向依赖 memory 实现。

核心 API：

```python
def project_messages_for_memory(
    messages: Sequence[Msg],
) -> list[Msg]:
    """Return the pre-migration-equivalent memory view."""
```

契约：

- 输入顺序不变；只允许删除旧行为中本来不可见的 hint carrier；
- 含任何 HintBlock 时返回深复制消息，不修改 AgentState、snapshot 或 Scroll；
- 无 HintBlock 时走 fast path，不执行 JSON dump/validate；
- 已知 source 必须命中显式 action；未知 source 保守展开并 warning；
- projection 是幂等的：对投影结果再次调用，结果不变；
- 不捕获 backend 异常，不承担“什么值得记忆”的业务判断。

### 7.2 Carrier metadata schema

一个 assistant Msg 可以包含多个 HintBlock，因此 target 信息不能只存在于消息
级单值字段。统一使用可 JSON round-trip 的版本化 metadata：

```json
{
  "qwenpaw_hint_projection": {
    "version": 1,
    "blocks": {
      "<hint-block-id>": {
        "target_msg_id": "<external-user-msg-id>",
        "position": "after_block_id",
        "anchor_block_id": "<data-block-id>",
        "renderer_version": 1,
        "renderer_context": {}
      }
    }
  }
}
```

允许的 position 仅有：

```text
before_first_text   # Bootstrap guidance
append_text         # slash skill
after_block_id      # uploaded-file path hint
replace_content     # Mission legacy memory view
```

projection action 由稳定的 `HintBlock.source` 注册表决定，不重复写入 metadata。
metadata 只携带无法从 source 推导的 target/position/anchor，以及 Mission 等
versioned renderer 所需的少量结构字段；禁止复制完整 prompt。schema version
未知、target 丢失或 anchor 不存在时不得丢内容：降级为
`expand_same_message` 并 warning。

### 7.3 Projection actions

| action | 行为 | 使用场景 |
|---|---|---|
| `expand_same_message` | HintBlock string 变为同位置 TextBlock；子 blocks 展开到同位置 | background tool offload、未知 source fallback |
| `merge_target_user` | 按 metadata 将 hint text 插入目标 external user Msg | skill、upload、Bootstrap |
| `replace_target_user` | 使用共享 legacy renderer 重建目标 user content | Mission 首轮 |
| `exclude_as_before` | 删除 HintBlock；carrier 为空时才删除 carrier Msg | runtime injection、loop continuation、runtime-state |

实现顺序固定为：建立 id 索引、按消息/block 原顺序执行 action、清理空 carrier、
最后验证所有 known-source HintBlock 均已消费。多个 block 指向同一 user 时按 carrier
消息顺序和 block 顺序稳定合并。

### 7.4 接入点与失败语义

```text
MemoryMiddleware._flush_auto_memory()
    select turn snapshots/messages
    -> project_messages_for_memory()
    -> memory_manager.auto_memory()

proactive_utils
    load session Msg
    -> project_messages_for_memory()
    -> existing text-only cleanup
```

projection 必须在 turn snapshot 选择之后：提前投影会污染 live context 和 Scroll；
放到 `ReMeLightMemoryManager.summarize()` 又无法覆盖 ADBPG。turn snapshot 保存
HintBlock 原始结构，flush 时投影，因此跨 compression/retry 仍能恢复旧 memory
视图。

失败规则：

- unknown source：展开正文并 warning；
- known source 缺 metadata/target：展开正文并 warning；
- malformed HintBlock：由 AgentScope Msg validation 在更早边界拒绝；
- projection 自身意外异常：本轮 memory 写回失败并保留 pending snapshot，不能
  回退为直接提交原 HintBlock，因为那会产生静默记忆回退；
- UI/model/live context 不受 memory projection 失败影响。

### 7.5 各注入点的具体改造

| 注入点 | live representation | memory action | 特殊要求 |
|---|---|---|---|
| context injection | standalone assistant HintBlock carrier | exclude | 保留 priority 排序；模型使用后是否持久由生命周期决定 |
| background tool | 原 assistant Msg 内单个多模态 HintBlock | expand same | notification/result 顺序、DataBlock id 不变 |
| loop continuation | append 到当前 assistant Msg | exclude | 只移除 hint，不删除同消息 assistant 正文/tool blocks |
| Mission 首轮 | external user task + assistant Mission HintBlock | replace target | shared legacy renderer 必须恢复原完整 Mission user prompt |
| slash skill | typed command + assistant skill HintBlock | merge append | 抽取共享 `build_skill_hint()`，旧/new renderer 共用 |
| uploaded file | user DataBlock + 后继 assistant path HintBlock | merge after anchor | 一个 user 多文件时每个 block 独立 anchor |
| Bootstrap | 原 user text + 后继 assistant guidance HintBlock | merge before | completion flag 行为不随迁移改变 |
| runtime time/tasks | AgentScope runtime-state HintBlock | exclude | source 去重、压缩后补注入保持上游行为 |

Mission 不把完整 legacy prompt 同时复制到 metadata，避免 session 体积近似翻倍。
应把现有 prompt 构造拆成共享的结构化 parts，并提供两个纯 renderer：model hint
renderer 与 legacy memory renderer。Mission HintBlock 使用有固定顺序的多个
TextBlock 保存 intro、master prompt 和 phase instruction；metadata 只保存
renderer version、mission name 和 loop_dir。legacy renderer 将目标 user task
重新插入旧模板位置，golden test 固定其精确输出。model renderer 采用更自然的
“可见 task 在前、内部执行说明在后”，不重复 task。

### 7.6 模型输入等价边界

迁移后 live message role 必然变化，因此分四类验收：

1. `exclude_as_before`：memory 输入必须完全一致，模型侧 hint 内容与旧内部控制
   内容及相对顺序一致；
2. user merge：memory 输入完全一致；provider wire 允许拆成相邻 user messages，
   模型可见文本不得缺失、重复或乱序；
3. Mission replace：memory 输入完全一致；模型侧明确采用 task-first 顺序，允许
   相对旧 prompt 发生这一项已声明的重排，但不得缺失或重复；
4. background tool：内容与多模态顺序一致，wire role 从 assistant observation
   变为 HintBlock 转换的 user observation 是明确的预期差异，必须单独 A/B。

禁止把“role/mission order 有意变化”写成“raw provider payload 完全一致”。
测试报告必须同时列出相同项和预期差异项。

## 8. 分阶段改造方案

### Phase 0：契约测试与边界固定

- [ ] 提交迁移前 Msg/UI/memory/provider/Scroll golden fixtures
- [ ] 实现 benchmark harness 并保存同机 `before.json`
- [ ] 增加 assistant-only HintBlock validation 测试
- [ ] 增加主要 provider formatter 顺序测试
- [ ] 固定 Console event 与 history projection 的隐藏契约
- [ ] 增加 AgentState/Scroll round-trip 测试
- [ ] 增加 compression 对已有 hint 和 instructions 的测试
- [ ] 为每个迁移点保存迁移前 memory backend 输入 golden fixture

验证：尚未迁移注入点时，测试已经固定 UI、模型、持久化和各 memory backend
输入基线。

### Phase 1：Memory 兼容投影与 UI 边界

- [ ] 新增 `agents/hints.py` 的 source 与 metadata schema
- [ ] 新增 `agents/memory/hint_projection.py` 纯函数
- [ ] 实现纯函数式 shared memory compatibility projection
- [ ] 实现 expand、merge、replace、exclude 四种显式策略
- [ ] 未知 source 默认展开并 warning，禁止静默丢失
- [ ] 保留 message id、role、created_at、metadata 和顺序
- [ ] 保证投影不修改 live AgentState
- [ ] 覆盖 text+hint、hint-only、multimodal hint
- [ ] 明确内部 HintBlockEvent 默认不进入 QwenPaw envelope
- [ ] ReMe 对投影结果执行原有全角色文本处理
- [ ] ADBPG 对投影结果执行原有 user-only 处理
- [ ] proactive 在投影后执行原有 text-only 清理
- [ ] 增加 Hypothesis 顺序、幂等、round-trip 和 no-loss 属性测试
- [ ] 固定 AgentScope ReMeMiddleware 的方向性契约：recall 使用 HintBlock、
  自身 memory carrier 不写回、其他 HintBlock 当前仍原样提交

验证：对每个迁移点，ReMe 的 `format_history()`、ADBPG 的 user payload 和
proactive 的 cleaned text 分别与迁移前 golden fixture 完全一致；用户
transcript 不展示内部 hint。

### Phase 2：高价值注入点迁移

- [ ] runtime context injection 改为 assistant HintBlock
- [ ] background tool notification/result 改为多模态 HintBlock
- [ ] loop continuation 改为 append assistant HintBlock
- [ ] Mission user task 与 Master hint 拆分
- [ ] Mission prompt 拆成结构化 parts、model hint renderer 与 legacy renderer
- [ ] slash skill typed text 与 skill hint 拆分
- [ ] uploaded-file path TextBlock 与 user DataBlock 拆分
- [ ] Bootstrap guidance 与首个 user TextBlock 拆分
- [ ] 为每个 source 注册并验证对应 memory projection 策略
- [ ] 保留 legacy XML/name/metadata cleanup 兼容旧 session

验证：模型可见内容不缺失或重复；Mission task-first 和预期 role 差异通过
provider golden 单独声明；各 memory backend 输入完全等价，Console 实时流和
历史恢复不展示内部内容。

### Phase 3：Formatter/HintBlock 多模态兼容

- [ ] 抽取统一 recursive block walker，覆盖 HintBlock 和 ToolResultBlock
- [ ] capability downgrade 递归剥离 HintBlock 内不支持的 media
- [ ] OpenAI HintBlock video 提供明确文本 fallback，禁止静默丢弃
- [ ] 将现有“OpenAI HintBlock video is skipped”空消息测试基线替换为明确
  fallback 契约
- [ ] 覆盖 HintBlock 内 image/audio/video 的 cap、deleted、download-failed、
  dedup 和 provider fallback
- [ ] 断言所有 formatter/request transform 只修改 deep copy
- [ ] 保持 capping placeholder 不进入 AgentState、Scroll 和 memory

### Phase 4：原生时间注入

- [ ] 启用 AgentScope runtime-state injection
- [ ] timezone 使用 user timezone
- [ ] 设置 `emit_hint_event=False`
- [ ] 删除 env system prompt 中的动态 current date
- [ ] runtime-state source 配置为 `qwenpaw:runtime-state`
- [ ] memory projection 对 runtime-state 使用 `exclude_as_before`
- [ ] 验证首次调用、时间间隔、timezone 变化和压缩后补注入
- [ ] 验证 system prompt cache 不再因时间变化失效

### Phase 5：Scroll 与归档增强

- [ ] hint-only message 不生成 searchable row
- [ ] blocks/FTS/headline/recall/split 全链路测试
- [ ] compression summary 不把控制 hint 归因为用户事实
- [ ] 递归外置 HintBlock/ToolResultBlock 内嵌 base64 data
- [ ] context archive 定义访问控制和 retention
- [ ] 评估 memory/RAG recall 是否应默认 ephemeral
- [ ] 清理一个兼容周期后的 legacy synthetic hint 逻辑

### Phase 6：上游依赖收敛

- [ ] 向 AgentScope ReMeMiddleware 提交可配置 compatibility projection
- [ ] 向 ReMe 增加 HintBlock 输入语义和 AgentScope 组合测试
- [ ] 向 AgentScope 修复 recursive base64 offload
- [ ] QwenPaw 升级包含修复的版本
- [ ] 上游修复落地后移除 QwenPaw 临时兼容代码

### Phase 7：效果与性能验收

- [ ] 运行全部 unit/contract/integration tests，通过率 100%
- [ ] 生成同机 `after.json` 和 `comparison.md`
- [ ] 检查 memory exact equality、provider expected deltas 与 session/token size
- [ ] 在用户明确启用时运行 `manual_real` A/B，并记录模型、参数和成本
- [ ] 对每个性能门槛给出 pass/fail，不用主观描述替代数据

验证：功能、memory 效果、模型行为和性能报告全部满足第 9 节标准后才允许移除
legacy cleanup 或扩大 HintBlock 迁移范围。

## 9. 测试矩阵与验收标准

### 9.1 迁移前 golden baseline

Phase 0 必须先在未修改注入逻辑的代码上生成并人工审阅 fixture，保存到：

```text
tests/fixtures/hintblock_migration/
    context_injection.json
    background_tool_text.json
    background_tool_multimodal.json
    loop_continuation.json
    mission_first_turn.json
    slash_skill.json
    uploaded_files.json
    bootstrap.json
    runtime_state.json
```

fixture 使用固定 message/block id、created_at、metadata 和平台无关路径，包含：

- 迁移前 Msg JSON；
- Console 清理后的可见 transcript；
- ReMe `format_history()` 文本；
- ADBPG user payload；
- proactive cleaned text；
- 各 provider 的 wire message 摘要、role 顺序和模型可见文本；
- Scroll searchable text 与 blocks JSON 大小。

迁移后测试构造新的 HintBlock 表示，再执行 compatibility projection。Memory
侧必须与 fixture 精确相等；不能在测试中调用“新旧共用的同一个待测函数”同时
生成 expected 和 actual，否则会掩盖 renderer 回归。

### 9.2 分层效果验证

| 层级 | 比对方式 | 硬性要求 |
|---|---|---|
| Projection unit | old Msg JSON vs projected new Msg canonical view | role、name、block 顺序、文本/DataBlock 描述完全一致 |
| ReMe | old/new `format_history()` | 字符串完全一致；hint-only 不得变 empty |
| ADBPG | `_filter_user_messages()` 输出 | user id、文本和顺序完全一致 |
| proactive | projection 后再执行 `_clean_message_content()` | cleaned session text 完全一致 |
| UI | legacy cleanup output vs HintBlock projection output | 用户正文/回答一致；内部 hint 为零泄漏 |
| Scroll | round-trip、FTS、recall、split | blocks 可恢复；searchable text 不新增 hint |
| Compression | fake summarizer 捕获输入 | continuation 所需内容存在；控制文字不归因为用户事实 |
| Provider | OpenAI Chat/Responses、Anthropic、DashScope、Gemini、Ollama wire golden | 内容不缺失/重复/乱序；预期 role 差异显式列出 |
| End-to-end | scripted model/tool harness | tool pairing、loop、Mission、skill、upload 行为一致 |

属性测试使用 Hypothesis 生成混合 TextBlock/DataBlock/HintBlock、多个 target、空
carrier、未知 source 和 JSON round-trip，验证：纯函数、幂等、顺序稳定、无内容
静默丢失。Windows/Linux/macOS 都运行路径与序列化测试。

真实模型 A/B 作为 `manual_real` 测试，不在未授权情况下调用付费 API。使用同一
model、参数、初始 session 和工具 stub，对 Mission、skill、background tool、
loop、upload、Bootstrap 各至少 3 个案例，记录成功率、工具选择、迭代数、token
和 latency。新实现不得出现旧实现没有的功能失败；role 有意变化的场景单独报告，
不与纯文本场景混算。

### 9.3 性能基准设计

不引入 `pytest-benchmark` 运行时依赖。新增可重复执行的独立脚本：

```text
scripts/benchmarks/hintblock_projection_benchmark.py
docs/benchmarks/hintblock-migration/
    before.json
    after.json
    comparison.md
```

脚本在同一进程、同一 fixture 上交替运行 legacy path 与 migrated path，warm-up
后多批采样，使用 `perf_counter_ns`、`statistics` 和 `tracemalloc` 输出环境信息、
p50/p95、吞吐、峰值分配及序列化字节数。场景至少包括：

| 场景 | 规模 | 目的 |
|---|---|---|
| no-hint fast path | 8 messages | 普通聊天不得承担明显额外成本 |
| typical turn | 8 messages / 2 hints | 日常 Mission/skill/tool 场景 |
| batched auto-memory | 100 messages / 20 hints | interval flush 与 snapshot 恢复 |
| proactive session | 1000 messages / 100 hints | 长 session text cleanup |
| multimodal | 20 hints / 40 DataBlocks | copy、serialization 与 media metadata 成本 |

比较的完整路径是“选择后的 messages → projection → backend payload dump”，而不
只测一个空函数。同步记录 live AgentState JSON、projected ReMe payload、provider
wire payload 和 token estimate，避免 CPU 很快但 context 膨胀。

初始性能门槛：

1. 不新增任何 network/LLM 调用；
2. known-source projected ReMe payload 的有效文本/token 与 legacy 完全一致；
3. no-hint fast path p95 新增耗时不超过 `0.1 ms`；
4. typical turn projection p95 不超过 `2 ms`，100-message batch 不超过 `20 ms`；
5. typical live session JSON 增长不超过 `15%`，不得复制完整 Mission legacy
   prompt 到 metadata；
6. 模型文本 token 增长不超过 `5%`，且不得由重复 task/hint 导致；
7. 性能报告必须给出 before/after 原始数字，不能只写“影响可忽略”。

时间门槛在同机 A/B 中执行，不作为跨平台共享 runner 的脆弱单测；CI 使用结构、
payload 大小、token 和“无额外调用”这些确定性 guard。Phase 0 基线完成后可以
收紧门槛，若需放宽必须在评审中说明原因。

| 维度 | 必测场景 |
|---|---|
| Console | 实时 HintBlockEvent、reload history、debug view |
| Mission | 用户卡片只显示任务；模型收到完整 Master prompt |
| Goal/loop | continuation 触发下一轮；不创建 synthetic user card |
| Skill | typed command 可见；skill body 对模型可见、对用户不可见 |
| Upload | DataBlock 正常显示；本地路径 hint 对模型可见、对用户不可见 |
| Bootstrap | 原 user text 可见；guidance 对模型可见、对用户不可见 |
| Tool offload | text/image 结果可恢复 reasoning；无 orphan tool message |
| Formatter | OpenAI Chat/Responses、Anthropic、DashScope、Gemini、Ollama |
| Media capping | HintBlock 内 image/audio/video 的 oversized、deleted、download-failed、dedup |
| Provider fallback | unsupported HintBlock media 有文本 fallback；不产生空消息或重复失败 |
| Ordering | user task、assistant text、hint、tool call/result 的最终 wire 顺序 |
| Scroll | count、split、blocks、FTS、reload、recall、continuation summary |
| ReMe | 每个迁移点的 projected history 与迁移前 golden fixture 一致 |
| ADBPG/proactive | Mission/skill 等旧可见内容与迁移前一致；旧不可见控制信息仍不采集 |
| Compression | hint 可指导 continuation，但不被写成用户事实 |
| Offload | context 可恢复；内嵌 base64 不直接进入 JSONL |
| Session | 新 HintBlock round-trip；旧 TextBlock/XML session 可恢复 |
| Time | 首轮、间隔、timezone 变化、压缩后补注入 |

最低验收条件：

1. 所有既有 unit tests 通过率 100%；
2. 每个迁移点同时证明“模型可见”和“用户不可见”；
3. provider 最终消息顺序符合设计，不破坏 tool pairing；
4. 每个迁移点对所有 memory backend 的 role、顺序和有效文本与迁移前一致；
   ReMe 额外要求 `format_history()` 完全一致；
5. Scroll searchable text 与 recall 不包含内部提示；
6. AgentState 和 context archive 可以恢复需要持久化的 hint；
7. hint-only、multimodal hint、旧 session 均有回归覆盖。
8. formatter、media preparation、fallback 和 visual compression 不修改 live
   AgentState，provider placeholder 不进入 memory。

## 10. 上游改进建议

### 10.1 ReMe

- 提供调用方可配置的 message projection hook；
- 明确 HintBlock 默认不进入 `get_text_content()` 的语义；
- raw session 应保存 projection 后真正参与 memory 的消息，而不是保存不可见的
  HintBlock；
- 增加 AgentScope `2.0.7.post1` 组合测试并放宽或更新依赖声明。

### 10.2 AgentScope

- ReMeMiddleware 应保留 recall→model 的 HintBlock 注入，同时在
  agent→memory 写回方向提供 projection hook；默认仍排除自身
  `name="memory"` carrier，其他 HintBlock 可由调用方按 source 展开、合并、
  重建或排除；
- workspace offloader 应递归处理 HintBlock/ToolResultBlock 内嵌 DataBlock；
- formatter 的 media preparation、capability downgrade 和 provider fallback
  应共享递归 ContentBlock walker；
- 长期记忆 middleware 应提供统一的 `persist_hint` 或 memory projection
  契约；
- 内部 middleware 的 source 命名和 HintBlockEvent 默认策略应保持一致。

上游改进不阻塞 QwenPaw 当前版本的边界修复。

## 11. 回滚策略与结论

每个 Phase 独立提交并可单独回滚：

- Phase 1 仅影响 memory/UI projection；
- Phase 2 按注入点逐项迁移；
- Phase 3 仅修复 formatter/request-copy 的 HintBlock media 递归兼容；
- Phase 4 只调整时间来源；
- Phase 5 不改变核心 agent loop；
- Phase 6 仅在上游版本可用后执行；
- Phase 7 只增加验收报告与测试，不改变运行时；
- legacy cleanup 在兼容周期结束前保留。

最大风险是 formatter message ordering 和 compression 归因，不是 HintBlock
schema。生产迁移前必须先建立 shared memory legacy-compatible projection、
golden fixture 和 UI projection 测试。

最终目标不是“把所有 `<system-info>` 替换为 HintBlock”，而是建立统一契约：

```text
HintBlock 表达模型侧内部状态；
生命周期决定是否留在 context；
projection 决定是否展示；
compatibility projection 保证所有 memory backend 迁移前后看到同样的信息；
formatter projection 只改变单次 provider 请求，不污染 context 或 memory；
archive policy 决定是否以及保存多久。
```

## 12. 实施记录（2026-08-31）

实施分支：`feat/hintblock-memory-projection`。

### 12.1 已完成

- 新增 `agents/hints.py`：集中管理 source、metadata schema 和 assistant
  carrier 构造；
- 新增 `agents/memory/hint_projection.py`：实现 expand、merge、replace、
  exclude 四类 memory projection，并提供无 Hint 零拷贝快路径；
- MemoryMiddleware、BaseMemoryManager task queue、ReMe direct summarize、
  ADBPG 和 proactive 均在各自边界执行幂等 projection；
- background tool、runtime context、loop continuation、Mission、slash skill、
  uploaded-file、Bootstrap、AgentScope runtime-state 和 Scroll placeholder
  已迁移为 assistant HintBlock；
- Mission 将用户 task 与内部执行提示分离，renderer metadata 不复制完整
  legacy prompt；memory projection 精确重建迁移前 user prompt；
- Scroll 的 FTS `content` 不写入内部 hint，但 `blocks` 保留原始结构；显式
  `expand` 可以恢复 background/Mission/skill 等持久 hint，runtime/loop/time
  等临时 hint 不进入 recall；
- formatter 的媒体预处理递归进入 HintBlock；OpenAI 不支持的 hint video
  使用明确文本 fallback；deleted/oversized media 变换仅作用于 request copy；
- 启用 AgentScope runtime-state injection，使用用户时区、稳定 source，并设置
  `emit_hint_event=False`。

### 12.2 效果验证

- ReMe 0.4.1.5 `format_history()`：迁移前 TextBlock 与迁移后 projection
  字符串完全相等；原始未投影 HintBlock 的结果仍为 `(empty)`，证明 projection
  是 ReMe 获得原信息的必要兼容层；
- ADBPG：slash skill 等 merge 场景的 user payload 与迁移前完全相等；
- proactive：projection 在 text-only cleanup 之前执行，能够保留原
  `<system-reminder>`；
- Scroll：hint body 不进入 searchable content，但结构可持久化并在 expand
  恢复；
- Console/history：HintBlock 不生成用户可见内容，相关 UI 回归 52 项通过；
- provider：OpenAI/Anthropic/DashScope/Gemini 等 formatter 相关 52 项通过，
  包括 nested media、fallback 和 live-state purity。

### 12.3 测试结果

- Hint/memory/Scroll/formatter/mission/upload 等相关回归：`544 passed`；
- memory/context/conversation integration：`32 passed`；
- 最终变更链路复测：`118 passed`；
- 全量 unit：`10102 passed, 21 skipped`；其中 1 个本次相关旧断言已修正并
  单独通过；15 个 collection error 来自环境自动加载的 `pytest-base-url`
  session/function fixture scope 冲突，使用 `-p no:base_url` 后对应
  `40 passed`；
- `flake8`、新增模块 `pylint`、AST、JSON、`compileall` 和
  `git diff --check` 均通过；仓库固定 Black 23.3 与系统 Python 3.14 的
  `ast.Str` 不兼容，已使用 qwenpaw Conda 环境 Black 26.5.1 按 79 列完成
  等价格式化。

### 12.4 性能结果

同机 300 次采样、30 次 warm-up，完整数据位于
`docs/benchmarks/hintblock-migration/`：

| 场景 | before p95 | after p95 | 增量 |
|---|---:|---:|---:|
| no hint | 0.031 ms | 0.037 ms | 0.006 ms |
| typical | 0.040 ms | 0.150 ms | 0.110 ms |
| 100-message batch | 0.845 ms | 2.601 ms | 1.756 ms |
| 1000-message proactive | 7.354 ms | 69.341 ms | 61.987 ms |
| multimodal | 0.254 ms | 0.907 ms | 0.653 ms |

六项验收门槛全部通过：无 Hint 开销、典型/100-message p95、典型 session
增长、token estimate 和有效 memory payload equality。1000-message proactive
没有同步请求链路门槛，其 69.341 ms 数据保留在报告中供后续优化比较。

### 12.5 尚未执行

- `manual_real` 真实付费模型 A/B 未执行，因为没有获得付费调用授权；
- AgentScope/ReMe 上游 PR 未提交，本分支先保留 QwenPaw compatibility
  projection；
- 未移除 legacy XML/display cleanup，确保旧 session 继续兼容；应在至少一个
  兼容周期后单独评审。
