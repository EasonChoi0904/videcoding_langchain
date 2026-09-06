"""生成答辩演示用的示例电商知识库数据(通过本机 API 上传入库)。

用法(先启动后端:start.bat):
    .venv\\Scripts\\python.exe scripts\\create_demo_data.py

生成内容:
- 知识库「手机数码商品库」:手机参数 Excel(15 款)+ 手机售后 FAQ(md)
- 知识库「大家电商品库」:家电参数 Excel(8 款)+ 冰箱说明书(docx)

输出:上传、解析、分块统计;解析完成后可在问答页直接体验。
"""
import time
import sys
from pathlib import Path

# Windows 控制台默认 GBK,重定向为标准 UTF-8 输出(emoji/✔ 等符号可正常打印)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import httpx
import pandas as pd

BASE_URL = "http://127.0.0.1:8000/api"
ADMIN = ("admin", "123456")
OUT_DIR = Path(__file__).resolve().parent / "demo_files"

# ---------------- 演示内容定义 ----------------
PHONES = [
    ["XMS15P", "小米15 Pro", "6.73英寸", "5400mAh", "90W", "4499元", "骁龙8至尊版"],
    ["XMS15", "小米15", "6.36英寸", "5400mAh", "90W", "3999元", "骁龙8至尊版"],
    ["XMRK80", "红米K80", "6.67英寸", "6550mAh", "120W", "2499元", "骁龙8 Gen3"],
    ["HWP70P", "华为P70 Pro", "6.8英寸", "5050mAh", "100W", "6499元", "麒麟9010"],
    ["HWM60P", "华为Mate60 Pro", "6.82英寸", "5000mAh", "88W", "6999元", "麒麟9000S"],
    ["OPFX8", "OPPO Find X8", "6.59英寸", "5630mAh", "80W", "4199元", "天玑9400"],
    ["VIVOX200", "vivo X200", "6.67英寸", "5800mAh", "90W", "4299元", "天玑9400"],
    ["GL60", "荣耀60", "6.67英寸", "4800mAh", "66W", "2499元", "骁龙778G"],
    ["GLMG7", "荣耀Magic7", "6.78英寸", "5650mAh", "100W", "4499元", "骁龙8至尊版"],
    ["IP16P", "iPhone 16 Pro", "6.3英寸", "3582mAh", "40W", "7999元", "A18 Pro"],
    ["IP16", "iPhone 16", "6.1英寸", "3561mAh", "30W", "5999元", "A18"],
    ["SM25U", "三星Galaxy S25 Ultra", "6.9英寸", "5000mAh", "45W", "9699元", "骁龙8 Elite"],
    ["ONEP13", "一加13", "6.82英寸", "6000mAh", "100W", "4499元", "骁龙8至尊版"],
    ["NUBZ70", "努比亚Z70 Ultra", "6.85英寸", "6150mAh", "80W", "4599元", "骁龙8 Elite"],
    ["ZTES50", "中兴天机S50", "6.7英寸", "5100mAh", "66W", "1999元", "骁龙7 Gen3"],
]
PHONE_COLS = ["商品编码", "商品名称", "屏幕尺寸", "电池容量", "快充功率", "起售价", "处理器"]

PHONE_FAQ_MD = """# 手机数码售后政策 FAQ

## 退换货政策
- 自签收之日起 7 天内无理由退货,15 天内出现质量问题可换新。
- 退货需保持商品、配件、包装完好,并出示购买凭证。
- 已激活的 iPhone 等含激活限制机型,拆封激活后不支持无理由退货。

## 保修政策
- 整机保修 1 年,屏幕、主板等主要部件同样保修 1 年。
- 电池保修 6 个月(非人为损耗)。人为损坏、进水、私拆不在保修范围。
- 保修期内维修免费;过保维修需自付配件费与人工费,可先电话询价。

## 以旧换新
- 支持主流品牌手机以旧换新,旧机评估价 + 平台补贴可直接抵扣新机款。
- 换新流程:在线估价 → 快递上门取旧机 → 检测报价 → 差价多退少补。

## 物流与签收
- 现货 48 小时内发货,预售机型按页面提示时间发货。
- 收货后请当着快递员面开箱检查,如遇外观破损可拒收或 24 小时内联系客服。

## 常见问题
- Q:手机充电发热正常吗? A:快充时轻微发热属正常现象,若异常烫手请停止使用并送检。
- Q:系统升级后更耗电怎么办? A:升级后 2-3 天属正常优化期,之后如仍异常可恢复出厂设置测试。
- Q:如何查询附近官方维修点? A:在商品详情页「服务」入口或联系在线客服获取最近网点。
"""

APPLIANCES = [
    ["HDK-XS01", "海尔零嵌冰箱501L", "冰箱", "501升", "一级能效", "零嵌安装", "4299元"],
    ["HDK-XS02", "海尔零嵌冰箱386L", "冰箱", "386升", "一级能效", "零嵌安装", "3299元"],
    ["MDS-GM3", "美的洗烘一体机10kg", "洗衣机", "10公斤", "一级能效", "洗烘一体", "2899元"],
    ["MDS-TK3", "美的变频空调1.5匹", "空调", "1.5匹", "新一级能效", "冷暖变频", "2399元"],
    ["GRZ-326", "格力云佳空调1.5匹", "空调", "1.5匹", "新一级能效", "冷暖变频", "2599元"],
    ["SMTX-300", "松下波轮洗衣机8kg", "洗衣机", "8公斤", "二级能效", "波轮全自动", "1699元"],
    ["FIDX-60", "老板烟灶套装", "厨电", "侧吸22m³", "—", "烟灶联动", "3599元"],
    ["SDMS-800", "美的电饭煲4L", "厨电", "4升", "一级能效", "IH电磁加热", "599元"],
]
APPLIANCE_COLS = ["商品编码", "商品名称", "品类", "主要参数", "能效等级", "功能特点", "售价"]

FRIDGE_DOCX_NOTES = [
    ("海尔零嵌冰箱 501L 使用说明书(节选)", "title"),
    ("安全须知", "h"),
    ("1. 请使用独立 220V/10A 电源插座,禁止使用拖线板与其他大功率电器共用一个插座。", "p"),
    ("2. 冰箱四周需保留散热空间:顶部 ≥10cm,两侧 ≥2cm,背面 ≥5cm。", "p"),
    ("3. 首次通电前静置 2 小时以上,通电后待冷藏室温度降至 4℃ 以下再放入食材。", "p"),
    ("温度调节与使用", "h"),
    ("冷藏室推荐设定 2~4℃,冷冻室 -18℃;夏季可适当调低档位,冬季调高档位。", "p"),
    ("内置智能感温探头会自动补偿环境温度变化,一般无需手动频繁调节。", "p"),
    ("零嵌安装说明", "h"),
    ("本机支持两侧零嵌(柜体与冰箱侧面间距 ≥2cm 即满足散热),背部无需预留空间。", "p"),
    ("安装时柜体深度建议 ≥640mm,开门角度需 ≥110° 以保证抽屉可完全抽出。", "p"),
    ("清洁与维护", "h"),
    ("每月清洁一次门封条与内胆,使用中性清洁剂,勿用钢丝球与强酸强碱。", "p"),
    ("长期不用请断电、清空并开门通风 3 天以上,防止异味与霉变。", "p"),
    ("主要参数表", "h"),
]

FRIDGE_TABLE = [
    ["产品型号", "HDK-XS01"],
    ["总容积", "501 升(冷藏 316L / 冷冻 185L)"],
    ["能效等级", "一级"],
    ["噪音", "≤ 35dB(A)"],
    ["制冷方式", "风冷无霜"],
    ["额定功率", "120W"],
    ["外形尺寸(宽深高)", "830×636×1910mm"],
]


def _ensure_files():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(PHONES, columns=PHONE_COLS).to_excel(
        OUT_DIR / "手机商品参数表.xlsx", index=False
    )
    pd.DataFrame(APPLIANCES, columns=APPLIANCE_COLS).to_excel(
        OUT_DIR / "家电商品参数表.xlsx", index=False
    )
    (OUT_DIR / "手机售后FAQ.md").write_text(PHONE_FAQ_MD, encoding="utf-8")

    import docx

    doc = docx.Document()
    for text, kind in FRIDGE_DOCX_NOTES:
        if kind == "title":
            doc.add_heading(text, level=0)
        elif kind == "h":
            doc.add_heading(text, level=1)
        else:
            doc.add_paragraph(text)
    table = doc.add_table(rows=0, cols=2)
    for row in FRIDGE_TABLE:
        cells = table.add_row().cells
        cells[0].text, cells[1].text = row
    doc.save(OUT_DIR / "海尔零嵌冰箱501L说明书.docx")
    print(f"演示文件已生成到 {OUT_DIR}")


def _login(client: httpx.Client) -> str:
    resp = client.post("/auth/login", json={"username": ADMIN[0], "password": ADMIN[1]})
    resp.raise_for_status()
    return resp.json()["access_token"]


def _kb_id(client: httpx.Client, token: str, name: str) -> int:
    kbs = client.get("/kb", headers={"Authorization": f"Bearer {token}"}).json()
    for kb in kbs:
        if kb["name"] == name:
            return kb["id"]
    resp = client.post(
        "/kb",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": name, "description": "演示用商品知识库", "category": name[:3]},
    )
    resp.raise_for_status()
    return resp.json()["id"]


def _upload(client: httpx.Client, token: str, kb_id: int, path: Path):
    # 已存在相同文件则跳过(脚本可重复执行)
    with open(path, "rb") as f:
        resp = client.post(
            f"/documents/kb/{kb_id}/upload",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": (path.name, f, "application/octet-stream")},
        )
    if resp.status_code == 409:
        print(f"  - 跳过(已上传过): {path.name}")
        return None
    resp.raise_for_status()
    print(f"  + 已上传: {path.name} → 文档#{resp.json()['id']}")
    return resp.json()["id"]


def main():
    _ensure_files()
    if not Path(__file__).resolve().parents[1].joinpath(".env").exists():
        pass  # Key 在环境变量或 .env,API 层会自行报错
    with httpx.Client(base_url=BASE_URL, timeout=30) as client:
        token = _login(client)
        headers = {"Authorization": f"Bearer {token}"}

        phone_kb = _kb_id(client, token, "手机数码商品库")
        home_kb = _kb_id(client, token, "大家电商品库")

        print("\n[1/2] 上传手机数码商品库:")
        _upload(client, token, phone_kb, OUT_DIR / "手机商品参数表.xlsx")
        _upload(client, token, phone_kb, OUT_DIR / "手机售后FAQ.md")

        print("\n[2/2] 上传大家电商品库:")
        _upload(client, token, home_kb, OUT_DIR / "家电商品参数表.xlsx")
        _upload(client, token, home_kb, OUT_DIR / "海尔零嵌冰箱501L说明书.docx")

    # 轮询解析状态直到全部完成
    print("\n等待解析入库(向量化需要调用百炼接口)…")
    with httpx.Client(base_url=BASE_URL, timeout=30) as client:
        token = _login(client)
        headers = {"Authorization": f"Bearer {token}"}
        while True:
            docs = []
            for kb in client.get("/kb", headers=headers).json():
                docs += client.get(f"/documents/kb/{kb['id']}", headers=headers).json()
            running = [d for d in docs if d["parse_status"] in ("pending", "parsing")]
            if not running:
                break
            time.sleep(2)
        for d in docs:
            status = {"done": "✔ 完成", "failed": "✘ 失败"}.get(d["parse_status"], d["parse_status"])
            print(f"  {d['filename']}: {status} · {d['chunk_count']} 个分块" + (f" · {d['error_msg'][:60]}" if d["error_msg"] else ""))
    print("\n演示数据就绪!登录 http://localhost:5173 开始体验(admin/123456)")


if __name__ == "__main__":
    sys.exit(main())
