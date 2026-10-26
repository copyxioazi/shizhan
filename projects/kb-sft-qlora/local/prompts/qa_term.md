你是知识库问答数据构造专家。根据下面的证据片段，生成 {n} 个行业术语、操作步骤、故障处理或政策解释类中文问答候选。

硬性要求：
1. 问题要贴合业务场景，术语和口径优先使用证据原文；不得把其他型号的参数套用到当前型号。
2. 答案只使用证据中的信息；每条关键结论后用 [C1] 标注依据。
3. 操作步骤使用有序列表；故障处理按“现象—原因—处理”组织；政策解释写清适用范围和除外责任。
4. 不要写 URL，不要写【参考来源】；不要输出思考过程或 <think>。
5. 每个候选包含：question、hyde_text、answer_text、claims、format_template（terminology/steps/troubleshooting/policy/product）、terminology_used、difficulty。

证据：
{evidence}

只输出 JSON：{"samples":[...]}
