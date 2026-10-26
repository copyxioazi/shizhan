请只根据【参考内容】评估【答案】，不要使用外部知识。

评分标准：
- faithfulness：答案中的每个事实、数字、日期、条款是否都能在被引用的片段中找到依据；1=大量编造，5=全部有依据。
- citation_correctness：每条 [n] 是否指向真正支持该句的片段；1=引用错乱，5=完全正确。
- completeness：是否覆盖问题要求的关键条件、范围和例外；1=严重遗漏，5=完整。
- format：是否符合要求的回答格式（引用、来源块、步骤/故障/政策结构）；1=格式错误，5=完全符合。
- refusal_correct：拒答样本是否在证据不足时拒答；非拒答样本填 true。
- missing_info_quality：拒答时是否准确列出缺少的信息；1=空泛，5=具体可执行。
- conflict_neutral：冲突样本是否并列两种说法、未擅自裁定。
- conflict_both_sides：冲突样本是否两种说法都呈现。

输出 JSON：
{"faithfulness":1-5,"citation_correctness":1-5,"completeness":1-5,"format":1-5,"refusal_correct":true/false,"missing_info_quality":1-5,"conflict_neutral":true/false,"conflict_both_sides":true/false,"unsupported_claims":["..."],"verdict":"accept|reject","reason":"..."}

【参考内容】
{context}

【问题】
{question}

【答案】
{answer}
