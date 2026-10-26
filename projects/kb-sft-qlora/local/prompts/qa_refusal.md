你是知识库问答数据构造专家。当前模式：{mode}。生成 {n} 个中文问答候选。

模式规则：
- no_evidence：没有证据支持该问题。主题为“{topic}”。生成一个自然的用户问题；答案必须明确拒绝回答，列出缺少哪些信息，不得出现 [n] 引用，不得写【参考来源】。
- partial：证据 C1 只支持问题的一部分；另一部分“{missing_topic}”不在证据中。生成一个自然的问题；答案先回答有依据的部分并用 [C1] 标注，再列出无法确认的部分；missing_info 至少 1 条。
- conflict：C1 和 C2 对同一事实给出不同说法。生成一个自然的问题；答案并列呈现两种说法并分别用 [C1]、[C2] 标注，不作裁定，不写“应以……为准”；conflict_values 列出两个具体值。

通用要求：
1. 不得引入证据之外的事实、数字或条款。
2. 不要写 URL，不要写【参考来源】（no_evidence 模式也不要写）。
3. 不要输出思考过程或 <think>。
4. 每个候选包含：question、hyde_text、answer_text、claims（有证据时）、missing_info、conflict_values、format_template、difficulty。

证据：
{evidence}

只输出 JSON：{"samples":[...]}
