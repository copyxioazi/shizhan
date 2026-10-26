"""Deterministic synthetic corpus for the 掌柜智库 domain.

Documents are generated from a fact registry, not from the web. This keeps
every number/date traceable and makes the corpus reproducible without an API.
The QA layer still uses DeepSeek (or the offline generator for smoke tests).
"""
from __future__ import annotations

from typing import Any

PRODUCTS: dict[str, dict[str, str]] = {
    "hak180": {
        "name": "兄弟(Brother) HAK180 烫金机",
        "model": "HAK180",
        "brand": "Brother",
        "temp": "10–32 °C",
        "humidity": "20%–80%",
        "power": "220 V / 50 Hz",
        "warranty": "12 个月",
        "weight": "18 kg",
        "foil_width": "20–60 mm",
        "warmup": "8 分钟",
        "clean_cycle": "每 500 次烫印",
    },
    "lm200": {
        "name": "LM-200 激光打标机",
        "model": "LM-200",
        "brand": "LaserMark",
        "temp": "15–30 °C",
        "humidity": "30%–70%",
        "power": "220 V / 50 Hz",
        "warranty": "12 个月",
        "weight": "42 kg",
        "laser_power": "20 W",
        "wavelength": "1064 nm",
        "area": "110 mm × 110 mm",
        "cooling": "风冷",
        "warmup": "5 分钟",
    },
    "tp300": {
        "name": "TP-300 标签打印机",
        "model": "TP-300",
        "brand": "LabelPro",
        "temp": "5–40 °C",
        "humidity": "20%–85%",
        "power": "220 V / 50 Hz",
        "warranty": "12 个月",
        "weight": "9 kg",
        "dpi": "300 dpi",
        "print_width": "104 mm",
        "speed": "150 mm/s",
        "media_width": "25–118 mm",
        "ribbon": "300 m",
    },
    "fl450": {
        "name": "FL-450 塑封机",
        "model": "FL-450",
        "brand": "FinishLine",
        "temp": "10–35 °C",
        "humidity": "20%–80%",
        "power": "220 V / 50 Hz",
        "warranty": "12 个月",
        "weight": "16 kg",
        "width": "450 mm",
        "temp_range": "80–140 °C",
        "speed": "0.3–1.2 m/min",
        "warmup": "5 分钟",
        "roller": "硅胶辊",
    },
    "ht600": {
        "name": "HT-600 热转印机",
        "model": "HT-600",
        "brand": "HeatTrans",
        "temp": "10–35 °C",
        "humidity": "20%–80%",
        "power": "220 V / 50 Hz",
        "warranty": "18 个月",
        "weight": "55 kg",
        "width": "600 mm",
        "temp_range": "120–200 °C",
        "pressure": "0.3–0.6 MPa",
        "air": "0.6 MPa 洁净压缩空气",
        "warmup": "10 分钟",
    },
    "bm100": {
        "name": "BM-100 装订机",
        "model": "BM-100",
        "brand": "BindMaster",
        "temp": "5–40 °C",
        "humidity": "20%–85%",
        "power": "220 V / 50 Hz",
        "warranty": "12 个月",
        "weight": "11 kg",
        "sheets": "100 张",
        "punch": "20 张",
        "margin": "3–6 mm",
        "warmup": "3 分钟",
    },
    "ct320": {
        "name": "CT-320 切纸机",
        "model": "CT-320",
        "brand": "CutTech",
        "temp": "5–40 °C",
        "humidity": "20%–85%",
        "power": "220 V / 50 Hz",
        "warranty": "12 个月",
        "weight": "28 kg",
        "width": "320 mm",
        "stack": "40 mm",
        "blade": "合金钢刀片",
        "warmup": "2 分钟",
    },
    "rs12": {
        "name": "RS-12 数字万用表",
        "model": "RS-12",
        "brand": "MeasurePro",
        "temp": "0–40 °C",
        "humidity": "≤ 80%",
        "power": "9 V 电池",
        "warranty": "12 个月",
        "weight": "0.4 kg",
        "voltage": "600 V DC/AC",
        "resistance": "20 MΩ",
        "accuracy": "±0.5%",
        "battery": "9 V 6F22",
        "calibration": "12 个月",
    },
    "generic": {
        "name": "工业设备",
        "model": "GEN-100",
        "brand": "通用",
        "temp": "5–40 °C",
        "humidity": "20%–85%",
        "power": "220 V / 50 Hz",
        "warranty": "12 个月",
        "weight": "—",
        "warmup": "5 分钟",
        "clean_cycle": "每 30 天",
    },
}

POLICIES: dict[str, dict[str, str]] = {
    "warranty_2024": {
        "name": "设备保修政策（2024 版）",
        "warranty": "12 个月",
        "return": "7 天",
        "response": "48 小时",
        "effective": "2024-01-01",
    },
    "warranty_2025": {
        "name": "设备保修政策（2025 版）",
        "warranty": "18 个月",
        "return": "15 天",
        "response": "24 小时",
        "effective": "2025-01-01",
    },
    "warranty_2026": {
        "name": "设备保修与延保政策（2026 版）",
        "warranty": "24 个月",
        "return": "30 天",
        "response": "24 小时",
        "effective": "2026-01-01",
    },
    "aftersales": {
        "name": "办公设备售后服务政策",
        "warranty": "12 个月",
        "return": "7 天",
        "response": "24 小时",
        "effective": "2025-06-01",
    },
    "return_sop": {
        "name": "返修与换货流程 SOP",
        "warranty": "12 个月",
        "return": "15 天",
        "response": "48 小时",
        "effective": "2025-07-01",
    },
}

TERMS = [
    ("烫金", "通过加热和压力把金属箔转移到承印物表面的工艺。"),
    ("激光打标", "利用聚焦激光在材料表面形成永久标记的工艺。"),
    ("热转印", "通过热量和压力把转印膜上的图案转移到承印物。"),
    ("塑封", "用塑封膜和加热辊把纸张封装起来的工艺。"),
    ("装订", "把散页纸张固定成册的工艺，包括打孔和装订。"),
    ("切纸", "使用切纸机把纸张裁切成规定尺寸的操作。"),
    ("保修期", "产品在正常使用条件下享受免费维修的期限。"),
    ("延保", "在原厂保修期结束后延长保修服务的有偿服务。"),
    ("响应时效", "服务方从受理工单到首次联系用户的时间上限。"),
    ("返修", "产品出现故障后返回服务方检测和维修的流程。"),
    ("换货", "在约定条件下用同型号或等价产品替换故障产品。"),
    ("上门服务", "服务工程师到用户现场进行检测或维修。"),
]


def _table(headers: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def _safety(p: dict[str, str]) -> list[dict[str, str]]:
    return [
        {"heading": "适用范围", "body": f"本手册适用于{p['name']}（型号 {p['model']}，品牌 {p['brand']}）的安装、操作、日常维护和故障处理。未按本手册操作造成的损坏不在保修范围内。"},
        {"heading": "安全警告", "body": "安装和维修前必须断开电源。设备附近不得放置水杯、溶剂和易燃物。激光设备运行时必须佩戴对应波长的防护眼镜，并开启排烟装置。儿童和未经培训人员不得操作设备。"},
        {"heading": "安装环境", "body": _table(["项目", "要求"], [["工作温度", p["temp"]], ["相对湿度", p["humidity"]], ["电源", p["power"]], ["设备重量", p["weight"]], ["预热时间", p.get("warmup", "5 分钟")]])},
        {"heading": "操作前检查", "body": "1. 检查电源线和插头是否破损。\n2. 检查工作台是否平稳、周边是否有足够散热空间。\n3. 检查耗材是否在有效期内。\n4. 空载运行一个循环，确认无异响和报警。"},
        {"heading": "紧急处理", "body": "出现冒烟、异味或异常高温时，立即按下急停开关并断开电源，不要用水扑灭电气火灾。人员受伤时先脱离危险区域并联系急救；设备故障记录现象后联系售后。"},
        {"heading": "日常维护", "body": "每班结束后清理碎屑和粉尘，检查传感器和急停开关是否有效。按保养周期表清洁运动部件并记录。禁止使用腐蚀性清洁剂。"},
        {"heading": "保修", "body": f"在正常使用条件下，整机保修期为 {p['warranty']}，以购机发票日期为准。保修范围、除外责任和申请流程见保修政策。"},
    ]


def _operation(p: dict[str, str]) -> list[dict[str, str]]:
    return [
        {"heading": "产品概述", "body": f"{p['name']}用于办公和轻工业场景。额定电源为 {p['power']}，工作温度为 {p['temp']}，相对湿度为 {p['humidity']}。设备应放置在平稳、通风、无强电磁干扰的台面上。"},
        {"heading": "开箱清单", "body": "1. 主机一台。\n2. 电源线一根。\n3. 说明书和保修卡各一份。\n4. 随机耗材一套。\n5. 合格证一张。开箱后如有缺件，应在签收后 7 天内联系经销商。"},
        {"heading": "安装与连接", "body": f"1. 将设备放在承重不低于 {p['weight']} 的工作台上。\n2. 连接 {p['power']} 电源，必须使用带接地的插座。\n3. 按需要连接数据线或气源。\n4. 开机预热 {p.get('warmup', '5 分钟')}，确认自检通过。"},
        {"heading": "操作步骤", "body": "1. 打开电源，等待自检完成。\n2. 在控制面板选择作业模式。\n3. 放入材料并调整定位挡板。\n4. 设置温度、速度或压力等参数。\n5. 先空载或试印一件，确认效果后批量作业。\n6. 作业结束后关闭电源并清洁台面。"},
        {"heading": "参数设置", "body": _table(["参数", "推荐值", "说明"], [["工作温度", p.get("temp_range", p["temp"]), "按材料厚度调整"], ["速度", p.get("speed", "中速"), "厚材料降速"], ["湿度", p["humidity"], "避免结露"], ["预热", p.get("warmup", "5 分钟"), "冬季适当延长"]])},
        {"heading": "日常维护", "body": "每日清洁外壳和工作台；每周检查电源线、传感器和紧固件；每月按保养表润滑运动部件。维护前必须断电。"},
        {"heading": "故障处理", "body": "设备不启动时先检查电源和急停开关；温度异常时检查传感器和加热元件；出现异响时立即停机并联系售后。不要自行拆解保修标签覆盖的部件。"},
        {"heading": "保修", "body": f"整机保修期 {p['warranty']}。耗材、人为损坏和未经授权的拆修不在保修范围内。"},
    ]


def _consumable(p: dict[str, str]) -> list[dict[str, str]]:
    return [
        {"heading": "适用耗材", "body": f"{p['name']}应使用原厂或经认证的耗材。使用非认证耗材可能造成定位偏差、废品率上升，并影响保修判定。"},
        {"heading": "规格表", "body": _table(["耗材", "规格", "更换周期"], [["主耗材", p.get("foil_width", p.get("media_width", p.get("ribbon", "标准规格"))), p.get("clean_cycle", "按实际用量")], ["清洁件", "无尘布/专用清洁剂", "每周"], ["易损件", "原厂配件", "按报警提示"]])},
        {"heading": "存储条件", "body": "耗材应存放在阴凉干燥处，避免阳光直射和高温高湿。未开封耗材的保质期以包装标注为准；开封后应密封保存并在 30 天内用完。"},
        {"heading": "更换步骤", "body": "1. 断电并等待设备冷却。\n2. 打开耗材仓，取出旧耗材。\n3. 按箭头方向装入新耗材，确认张紧度。\n4. 合上仓门，开机执行自检。\n5. 试印一件并检查效果。"},
        {"heading": "常见问题", "body": "耗材跑偏时检查导轮和张力；出现条纹时清洁辊面或更换耗材；报警提示耗材耗尽时按型号更换，不要短接传感器。"},
    ]


def _maintenance(p: dict[str, str]) -> list[dict[str, str]]:
    return [
        {"heading": "保养周期表", "body": _table(["周期", "项目", "标准"], [["每班", "清洁台面和碎屑", "无可见粉尘"], ["每周", "检查电源线、传感器", "无破损、无报警"], ["每月", "润滑运动部件", "按润滑点加注"], ["每季度", "校准温度和压力", "误差在允许范围"]])},
        {"heading": "日常保养", "body": "每班结束后断电，清除碎屑和粉尘，擦拭外壳。检查急停开关、防护罩和警示标识是否完好。填写保养记录。"},
        {"heading": "周保养", "body": "检查电源线、插头和接地；清洁传感器和散热风口；检查皮带、链条或导轨的松紧；确认无异常噪音。"},
        {"heading": "月保养", "body": f"按润滑点加注指定润滑脂；检查紧固件是否松动；清洁或更换过滤件。{p['name']}的累计运行时间达到 {p.get('clean_cycle', '规定周期')} 时，应安排深度保养。"},
        {"heading": "记录要求", "body": "每次保养记录日期、人员、项目、发现的问题和处理结果。记录至少保存 12 个月，作为保修和故障分析的依据。"},
    ]


def _troubleshooting(p: dict[str, str]) -> list[dict[str, str]]:
    return [
        {"heading": "故障排查原则", "body": "先检查电源和急停开关，再检查耗材和参数，最后检查传感器和机械部件。排查前必须断电，禁止带电插拔。"},
        {"heading": "常见故障表", "body": _table(["现象", "可能原因", "处理"], [["不上电", "电源线松动/保险丝熔断", "检查电源和保险丝"], ["温度不上升", "加热元件或传感器故障", "联系售后检测"], ["异响", "异物卡阻/轴承磨损", "停机清理或更换"], ["效果偏差", "参数不当/耗材老化", "重新试印并更换耗材"]])},
        {"heading": "处理步骤", "body": "1. 记录故障现象和报警代码。\n2. 按上表做不断电无法完成的基础检查。\n3. 需要拆机时联系售后，不要自行拆解。\n4. 修复后空载运行一个循环并试印。"},
        {"heading": "报修条件", "body": "出现冒烟、漏电、异常高温、机械卡死或重复报警时，立即停机并报修。保修期内非人为损坏免收维修费和配件费。"},
    ]


def _policy(p: dict[str, str]) -> list[dict[str, str]]:
    return [
        {"heading": "适用范围", "body": f"本政策适用于通过授权渠道购买的{p['name']}所列产品，生效日期为 {p['effective']}。政策版本以购机时适用的版本为准。"},
        {"heading": "保修期限", "body": f"整机保修期为 {p['warranty']}，自购机发票日期起算。延保服务需单独购买，延保期内适用延保条款。"},
        {"heading": "保修范围", "body": "正常使用条件下出现的材料或工艺缺陷属于保修范围。保修服务包括检测、维修或更换故障部件，更换下来的部件归服务方所有。"},
        {"heading": "除外责任", "body": "人为损坏、进水、跌落、擅自拆修、使用非认证耗材、超出规定环境使用、不可抗力造成的损坏不在保修范围内。"},
        {"heading": "申请流程", "body": f"1. 通过客服热线或在线工单提交购机凭证和故障描述。\n2. 服务方在 {p['response']} 内响应。\n3. 远程无法解决的安排返修或上门。\n4. 维修完成后由用户验收并签字。"},
        {"heading": "退换货", "body": f"自签收之日起 {p['return']} 内，符合无理由退换条件的可申请退换；人为损坏、缺少配件或影响二次销售的不适用。具体流程见返修与换货 SOP。"},
        {"heading": "争议处理", "body": "对保修判定有异议时，可要求服务方出具检测报告，并向购买渠道或消费者协会申请协调。"},
    ]


def _sop(p: dict[str, str]) -> list[dict[str, str]]:
    return [
        {"heading": "适用范围", "body": f"本 SOP 适用于{p['name']}相关产品的返修、换货和退款申请，生效日期为 {p['effective']}。"},
        {"heading": "角色与职责", "body": "客服负责受理和登记；技术支持负责远程诊断；仓储负责收货和外观检查；财务负责退款或差价结算。"},
        {"heading": "流程步骤", "body": "1. 客服核对订单、序列号和购机凭证。\n2. 技术支持远程诊断并记录故障代码。\n3. 符合条件的生成返修单或换货单。\n4. 用户寄回或工程师上门取件。\n5. 仓储验收后转维修或换货。\n6. 完成后回访并关闭工单。"},
        {"heading": "时限", "body": f"受理后 {p['response']} 内响应；返修一般 5 个工作日内完成；换货在有库存时 3 个工作日内发出。自签收之日起 {p['return']} 内可申请无理由退换。"},
        {"heading": "异常处理", "body": "外观损坏、缺件或序列号不符时，仓储拍照留证并暂停流程。超时未处理的工单升级到主管。争议由客服主管裁定并记录。"},
        {"heading": "常见争议", "body": "用户主张无理由退换但商品已拆封使用、赠品缺失、发票金额与实付不一致时，客服应先核对订单、支付记录和物流签收记录，再按平台规则处理。无法达成一致的，升级到客服主管并保留沟通记录。"},
        {"heading": "记录与归档", "body": "每张返修单保存订单号、序列号、故障描述、检测结论、处理方式和物流单号。退款和换货记录与财务凭证一并归档，保存至少 24 个月，便于审计和售后追溯。"},
    ]


def _terminology(p: dict[str, str]) -> list[dict[str, str]]:
    rows = [[term, definition] for term, definition in TERMS]
    return [
        {"heading": "术语表", "body": _table(["术语", "定义"], rows)},
        {"heading": "口径说明", "body": "回答中使用术语表的标准写法；资料原文与标准术语不一致时，先保留原文表述，再在括号中注明标准术语。不得为了统一术语而改变数字、期限或责任范围。"},
        {"heading": "使用示例", "body": "用户问“机器多久保养一次”时，应回答资料中的具体周期，并说明依据的章节；资料未给出周期时，明确说明缺少该信息，不得套用其他型号的周期。"},
    ]


def _calibration(p: dict[str, str]) -> list[dict[str, str]]:
    return [
        {"heading": "校准周期", "body": f"{p['name']}建议每 {p['calibration']} 校准一次。频繁使用、跌落或更换电池后应提前校准。校准记录应保存至少 24 个月。"},
        {"heading": "校准前准备", "body": f"准备标准源、测试线和 {p['battery']} 新电池。环境温度保持在 {p['temp']}，相对湿度不超过 80%。确认表笔无破损。"},
        {"heading": "校准步骤", "body": "1. 开机预热 5 分钟。\n2. 选择直流电压档，接入标准源。\n3. 依次检查 10 V、100 V 和 600 V 点。\n4. 检查电阻档和通断档。\n5. 记录偏差，超过允许误差时送修。"},
        {"heading": "安全注意", "body": "测量电压不得超过 600 V；测量电阻和通断前必须断电并放电；不得在潮湿环境或爆炸性气体环境中使用。"},
        {"heading": "记录", "body": "记录校准日期、环境条件、标准源编号、各测试点读数和结论。校准不合格的设备应贴停用标签并送修。"},
    ]


BUILDERS = {
    "safety": _safety,
    "operation": _operation,
    "consumable": _consumable,
    "maintenance": _maintenance,
    "troubleshooting": _troubleshooting,
    "policy": _policy,
    "sop": _sop,
    "terminology": _terminology,
    "calibration": _calibration,
}

DOC_SPECS: list[dict[str, str]] = [
    {"doc_id": "foil_consumables", "file_title": "烫金耗材与存储规范", "product": "hak180", "doc_type": "consumable", "split": "train", "version": "2026.1", "effective_date": "2026-01-01"},
    {"doc_id": "foil_maintenance", "file_title": "烫金机日常维护手册", "product": "hak180", "doc_type": "maintenance", "split": "train", "version": "2026.1", "effective_date": "2026-01-01"},
    {"doc_id": "lm200_safety", "file_title": "LM-200 激光打标机安全手册", "product": "lm200", "doc_type": "safety", "split": "train", "version": "2025.2", "effective_date": "2025-06-01"},
    {"doc_id": "lm200_operation", "file_title": "LM-200 激光打标机操作说明", "product": "lm200", "doc_type": "operation", "split": "train", "version": "2025.2", "effective_date": "2025-06-01"},
    {"doc_id": "tp300_operation", "file_title": "TP-300 标签打印机操作指南", "product": "tp300", "doc_type": "operation", "split": "train", "version": "2025.3", "effective_date": "2025-09-01"},
    {"doc_id": "tp300_consumables", "file_title": "TP-300 耗材规格与更换", "product": "tp300", "doc_type": "consumable", "split": "train", "version": "2025.3", "effective_date": "2025-09-01"},
    {"doc_id": "industrial_maintenance", "file_title": "工业设备维护通用规范", "product": "generic", "doc_type": "maintenance", "split": "train", "version": "2024.1", "effective_date": "2024-03-01"},
    {"doc_id": "terminology", "file_title": "设备术语与口径表", "product": "generic", "doc_type": "terminology", "split": "train", "version": "2026.0", "effective_date": "2026-01-01"},
    {"doc_id": "warranty_2024", "file_title": "设备保修政策（2024 版）", "policy": "warranty_2024", "doc_type": "policy", "split": "train", "version": "2024", "effective_date": "2024-01-01"},
    {"doc_id": "warranty_2025", "file_title": "设备保修政策（2025 版）", "policy": "warranty_2025", "doc_type": "policy", "split": "train", "version": "2025", "effective_date": "2025-01-01"},
    {"doc_id": "fl450_operation", "file_title": "FL-450 塑封机操作说明", "product": "fl450", "doc_type": "operation", "split": "dev", "version": "2025.1", "effective_date": "2025-03-01"},
    {"doc_id": "fl450_troubleshooting", "file_title": "FL-450 塑封机故障排除", "product": "fl450", "doc_type": "troubleshooting", "split": "dev", "version": "2025.1", "effective_date": "2025-03-01"},
    {"doc_id": "ht600_safety", "file_title": "HT-600 热转印机安全手册", "product": "ht600", "doc_type": "safety", "split": "dev", "version": "2025.2", "effective_date": "2025-05-01"},
    {"doc_id": "ht600_maintenance", "file_title": "HT-600 热转印机维护保养", "product": "ht600", "doc_type": "maintenance", "split": "dev", "version": "2025.2", "effective_date": "2025-05-01"},
    {"doc_id": "aftersales_policy", "file_title": "办公设备售后服务政策", "policy": "aftersales", "doc_type": "policy", "split": "dev", "version": "2025.6", "effective_date": "2025-06-01"},
    {"doc_id": "return_sop", "file_title": "返修与换货流程 SOP", "policy": "return_sop", "doc_type": "sop", "split": "dev", "version": "2025.7", "effective_date": "2025-07-01"},
    {"doc_id": "rs12_calibration", "file_title": "RS-12 万用表校准与安全", "product": "rs12", "doc_type": "calibration", "split": "test", "version": "2025.1", "effective_date": "2025-02-01"},
    {"doc_id": "bm100_operation", "file_title": "BM-100 装订机操作说明", "product": "bm100", "doc_type": "operation", "split": "test", "version": "2025.4", "effective_date": "2025-08-01"},
    {"doc_id": "bm100_troubleshooting", "file_title": "BM-100 装订机故障处理", "product": "bm100", "doc_type": "troubleshooting", "split": "test", "version": "2025.4", "effective_date": "2025-08-01"},
    {"doc_id": "ct320_safety", "file_title": "CT-320 切纸机安全手册", "product": "ct320", "doc_type": "safety", "split": "test", "version": "2025.2", "effective_date": "2025-04-01"},
    {"doc_id": "warranty_2026", "file_title": "设备保修与延保政策（2026 版）", "policy": "warranty_2026", "doc_type": "policy", "split": "test", "version": "2026", "effective_date": "2026-01-01"},
]


def doc_meta(spec: dict[str, str]) -> dict[str, str]:
    if "policy" in spec:
        p = POLICIES[spec["policy"]]
        item_name = p["name"]
        model = spec["doc_id"]
        brand = "掌柜智库"
    else:
        p = PRODUCTS[spec["product"]]
        item_name = p["name"]
        model = p["model"]
        brand = p["brand"]
    return {
        "doc_id": spec["doc_id"],
        "file_title": spec["file_title"],
        "item_name": item_name,
        "product_model": model,
        "brand": brand,
        "doc_type": spec["doc_type"],
        "url": f"https://kb.example.com/docs/{spec['doc_id']}",
        "version": spec.get("version", ""),
        "effective_date": spec.get("effective_date", ""),
        "split": spec["split"],
        "source_type": "synthetic",
        "source": "local",
    }


def _faq(p: dict[str, str]) -> dict[str, str]:
    if "temp" in p:
        body = (
            f"问：{p['name']}可以在什么环境使用？\n"
            f"答：工作温度为 {p['temp']}，相对湿度为 {p['humidity']}，电源为 {p['power']}。"
            f"超出范围时应先改善环境再开机。\n\n"
            f"问：日常维护要注意什么？\n"
            f"答：每班清洁台面，每周检查电源线和传感器，每月润滑运动部件；维护前必须断电。\n\n"
            f"问：出现异常如何处理？\n"
            f"答：先断电并记录报警代码和现象；不要自行拆解保修标签覆盖的部件；联系售后。\n\n"
            f"问：保修需要哪些材料？\n"
            f"答：购机发票、序列号和故障描述。整机保修期为 {p['warranty']}；"
            f"人为损坏和未经授权拆修不在保修范围内。"
        )
    else:
        body = (
            f"问：这份政策的保修期是多久？\n答：{p.get('warranty', '')}，以购机发票日期起算。\n\n"
            f"问：退换货期限是多少天？\n答：{p.get('return', '')}，以签收日期起算。\n\n"
            f"问：提交申请后多久响应？\n答：{p.get('response', '')}内响应。\n\n"
            f"问：哪些情况不在保修范围内？\n答：人为损坏、进水、跌落、擅自拆修、使用非认证耗材和不可抗力。"
        )
    return {"heading": "常见问题", "body": body}


def render_doc(spec: dict[str, str]) -> str:
    if "policy" in spec:
        p = POLICIES[spec["policy"]]
    else:
        p = PRODUCTS[spec["product"]]
    sections = BUILDERS[spec["doc_type"]](p)
    sections.append(_faq(p))
    sections.append(
        {
            "heading": "记录与培训",
            "body": "操作人员应接受设备安全、日常维护和应急处置培训。培训记录、保养记录和故障记录至少保存 12 个月。新员工上岗前应完成空载演练，确认急停、防护罩和报警功能有效。发生事故或未遂事件时，应保护现场并按要求上报。",
        }
    )
    sections.append(
        {
            "heading": "版本与生效日期",
            "body": f"本文版本为 {spec.get('version', '')}，生效日期为 {spec.get('effective_date', '')}。如与最新版政策冲突，以购机时适用的版本和当地法规为准。",
        }
    )
    sections.append(
        {
            "heading": "补充说明",
            "body": "本资料仅用于产品支持和培训。遇到资料未覆盖的问题，应先确认设备型号、批次和适用版本，再联系售后。不得把其他型号的参数直接套用到本型号。",
        }
    )
    meta = doc_meta(spec)
    front = ["---"]
    front.extend(f'{key}: "{value}"' for key, value in meta.items())
    front.append("---")
    body = [f"# {spec['file_title']}"]
    for section in sections:
        body.append(f"## {section['heading']}")
        body.append(section["body"])
    return "\n".join(front) + "\n\n" + "\n\n".join(body) + "\n"


def fact_registry() -> dict[str, Any]:
    registry: dict[str, Any] = {"products": PRODUCTS, "policies": POLICIES,
                                "terms": [{"term": t, "definition": d} for t, d in TERMS]}
    return registry
