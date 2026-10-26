你是知识库问答数据构造专家。根据下面的证据片段，生成 {n} 个中文问答候选。

硬性要求：
1. 问题必须是真实用户会问的业务问题，能由证据直接回答；不要写“根据资料”“请阅读”这类元问题。
2. 答案只使用证据中的信息，不得引入证据之外的事实、数字、条款或结论。
3. 每条关键结论后用 [C1]、[C2] 标注依据；标签必须来自证据。
4. 不要写 URL，不要写【参考来源】；渲染器会补。
5. 不要输出思考过程或 <think>。
6. 每个候选包含：question、hyde_text（50–150 字假设答案，仅用于检索）、answer_text（中文答案，带 [Ck]）、claims（数组，含 claim_id、text、evidence_labels）、format_template（plain/steps/troubleshooting/policy/product）、difficulty（easy/medium/hard）。

证据：
{evidence}

只输出 JSON：{"samples":[...]}
