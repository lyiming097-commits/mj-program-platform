from io import BytesIO
from decimal import Decimal, ROUND_HALF_UP
from xml.sax.saxutils import escape

from django.http import HttpResponse
from django.utils import timezone


def _filename(order, suffix):
    return f"xiancai-order-{order.order_no}.{suffix}"


def _contract_filename(order):
    return f"sales-contract-{order.order_no}.pdf"


def _text(value, default="-"):
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _pdf_text(value, default="-"):
    return escape(_text(value, default)).replace("\n", "<br/>")


def _money(value):
    amount = Decimal(str(value or "0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{amount:,.2f}"


def _quantity(value):
    amount = Decimal(str(value or "0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if amount == amount.to_integral():
        return str(int(amount))
    return f"{amount.normalize():f}"


def _rmb_upper(value):
    amount = Decimal(str(value or "0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if amount == 0:
        return "人民币零元整"

    digits = "零壹贰叁肆伍陆柒捌玖"
    units = ["", "拾", "佰", "仟"]
    group_units = ["", "万", "亿", "兆"]

    def group_to_upper(num):
        parts = []
        zero_pending = False
        for index, unit in enumerate(reversed(units)):
            divisor = 10 ** (3 - index)
            digit = (num // divisor) % 10
            if digit == 0:
                if parts:
                    zero_pending = True
                continue
            if zero_pending:
                parts.append("零")
                zero_pending = False
            parts.append(f"{digits[digit]}{unit}")
        return "".join(parts)

    integer = int(amount)
    fraction = int((amount - Decimal(integer)) * 100)
    groups = []
    while integer:
        groups.append(integer % 10000)
        integer //= 10000

    integer_parts = []
    zero_between = False
    for idx in range(len(groups) - 1, -1, -1):
        group = groups[idx]
        if group == 0:
            if integer_parts:
                zero_between = True
            continue
        if (zero_between or (integer_parts and group < 1000)) and not integer_parts[-1].endswith("零"):
            integer_parts.append("零")
        integer_parts.append(f"{group_to_upper(group)}{group_units[idx]}")
        zero_between = False
    integer_text = "".join(integer_parts) or "零"

    jiao = fraction // 10
    fen = fraction % 10
    fraction_text = ""
    if jiao:
        fraction_text += f"{digits[jiao]}角"
    if fen:
        if not jiao:
            fraction_text += "零"
        fraction_text += f"{digits[fen]}分"
    if not fraction_text:
        fraction_text = "整"
    return f"人民币{integer_text}元{fraction_text}"


def export_order_excel(order):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "线材订单"

    title_font = Font(size=16, bold=True)
    header_fill = PatternFill("solid", fgColor="E8EEF7")
    bold = Font(bold=True)

    ws["A1"] = "智慧教室线材商城订单清单"
    ws["A1"].font = title_font
    ws.merge_cells("A1:K1")
    ws.append([])
    ws.append(["订单号", order.order_no, "收货地址", order.project_name, "收货人", order.customer_name, "手机号", order.customer_phone])
    ws.append([
        "签单公司",
        order.signing_company_name,
        "开户银行",
        order.signing_opening_bank,
        "税号",
        order.signing_tax_number,
        "账号",
        order.signing_bank_account,
    ])
    ws.append(["下单时间", order.created_at.strftime("%Y-%m-%d %H:%M"), "线材总根数", order.total_cables, "金额", float(order.total_amount)])
    ws.append(["备注", order.remark])
    ws.append([])

    headers = ["清单", "下单倍数", "分类", "线材名称", "型号", "规格", "数量", "单根长度(米)", "总根数", "计价数量", "小计"]
    ws.append(headers)
    header_row = ws.max_row
    for cell in ws[header_row]:
        cell.font = bold
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")

    for package in order.packages.all():
        for item in package.items.all():
            ws.append([
                package.package_name,
                package.package_quantity,
                item.category_b,
                item.product_abbr or item.product_label,
                item.product_model,
                item.spec_text,
                item.quantity_per_package,
                float(item.length_m) if item.length_m is not None else "",
                item.total_quantity,
                float(item.billing_quantity),
                float(item.line_total),
            ])

    widths = [18, 8, 12, 28, 18, 34, 10, 12, 10, 12, 12]
    for idx, width in enumerate(widths, start=1):
        ws.column_dimensions[chr(64 + idx)].width = width
    for row in ws.iter_rows(min_row=1, max_row=ws.max_row):
        for cell in row:
            cell.alignment = Alignment(vertical="center", wrap_text=True)

    output = BytesIO()
    wb.save(output)
    response = HttpResponse(
        output.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{_filename(order, "xlsx")}"'
    return response


def export_order_pdf(order):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch, mm
    from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont

    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))

    seller_name = "杭州迈杰教育科技有限公司"
    seller_bank = "招商银行股份有限公司杭州余杭支行"
    seller_tax_no = "91330110685829101A"
    seller_account = "5719 0586 6410 606"
    contract_date = timezone.localtime(order.locked_at or order.created_at).strftime("%Y年%m月%d日")
    buyer_name = _text(order.signing_company_name, order.external_account_name or order.owner_name or "甲方")
    half_amount = (Decimal(str(order.total_amount or "0")) * Decimal("0.5")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=0.39 * inch,
        leftMargin=0.39 * inch,
        topMargin=0.79 * inch,
        bottomMargin=0.63 * inch,
    )
    styles = getSampleStyleSheet()
    base = ParagraphStyle(
        "CN",
        parent=styles["Normal"],
        fontName="STSong-Light",
        fontSize=10.5,
        leading=16,
        spaceAfter=0,
    )
    title = ParagraphStyle("TitleCN", parent=base, fontSize=16, leading=22, alignment=TA_CENTER, spaceAfter=8)
    company_title = ParagraphStyle("CompanyTitleCN", parent=title, fontSize=15, leading=20, spaceAfter=6)
    section = ParagraphStyle("SectionCN", parent=base, fontSize=10.5, leading=16, spaceBefore=7, spaceAfter=3)
    small = ParagraphStyle("SmallCN", parent=base, fontSize=8.5, leading=11)
    table_text = ParagraphStyle("TableCN", parent=small, alignment=TA_CENTER)
    table_left = ParagraphStyle("TableLeftCN", parent=small, alignment=TA_LEFT)
    signature_label = ParagraphStyle("SignatureLabelCN", parent=base, alignment=TA_RIGHT)
    signature_value = ParagraphStyle("SignatureValueCN", parent=base, alignment=TA_LEFT)

    def p(text, style=base):
        return Paragraph(_pdf_text(text), style)

    def raw_p(text, style=base):
        return Paragraph(text, style)

    product_rows = [[
        p("产品名称", table_text),
        p("规格型号", table_text),
        p("单位", table_text),
        p("数量", table_text),
        raw_p("含税单价<br/>（元）", table_text),
        raw_p("税率<br/>（%）", table_text),
        raw_p("金额<br/>（元）", table_text),
        raw_p("品牌<br/>型号", table_text),
        raw_p("备注<br/>（定制要求等）", table_text),
    ]]
    for package in order.packages.all():
        for item in package.items.all():
            unit = _text(item.source_unit, "根")
            quantity = item.billing_quantity if unit == "米" else item.total_quantity
            remark_parts = [
                item.category_b,
                item.spec_text,
                item.note,
                package.package_name if package.package_name not in {"直接下单", "线材下单"} else "",
                f"清单倍数：{package.package_quantity}" if package.package_quantity and package.package_quantity > 1 else "",
            ]
            product_rows.append([
                p(item.product_abbr or item.product_label, table_left),
                p(item.product_model, table_left),
                p(unit, table_text),
                p(_quantity(quantity), table_text),
                p(_money(item.unit_price), table_text),
                p("13", table_text),
                p(_money(item.line_total), table_text),
                p(item.product_brand or item.product_model or "-", table_left),
                p("；".join([_text(part, "") for part in remark_parts if _text(part, "")]), table_left),
            ])
    if len(product_rows) == 1:
        product_rows.append([p("-", table_text), p("-", table_text), p("-", table_text), p("0", table_text), p("0.00", table_text), p("13", table_text), p("0.00", table_text), p("-", table_text), p("-", table_text)])

    product_table = Table(
        product_rows,
        colWidths=[23 * mm, 24 * mm, 10 * mm, 13 * mm, 18 * mm, 14 * mm, 20 * mm, 26 * mm, 40 * mm],
        repeatRows=1,
    )
    product_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "STSong-Light"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("LEADING", (0, 0), (-1, -1), 11),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.white),
    ]))

    total_table = Table(
        [[
            p("总金额<br/>（大写）：", table_text),
            p(_rmb_upper(order.total_amount), table_left),
            p("总金额（￥）：", table_text),
            p(_money(order.total_amount), table_left),
        ]],
        colWidths=[28 * mm, 77 * mm, 31 * mm, 42 * mm],
    )
    total_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "STSong-Light"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (0, 0), "CENTER"),
        ("ALIGN", (2, 0), (2, 0), "CENTER"),
    ]))

    def meta_table():
        rows = [
            [
                p("甲方（买方）：", signature_label),
                p(buyer_name, signature_value),
                p("日    期：", signature_label),
                p(contract_date, signature_value),
            ],
            [
                p("乙方（卖方）：", signature_label),
                p(seller_name, signature_value),
                p("合同编号：", signature_label),
                p(order.order_no, signature_value),
            ],
        ]
        table = Table(rows, colWidths=[32 * mm, 72 * mm, 28 * mm, 46 * mm], rowHeights=[9 * mm, 9 * mm])
        table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), "STSong-Light"),
            ("FONTSIZE", (0, 0), (-1, -1), 10.5),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        return table

    def signature_table():
        rows = [
            ["甲  方（盖章）：", buyer_name, "乙  方（盖章）：", seller_name],
            ["代表人（签字）：", "", "代表人（签字）：", ""],
            ["开 户 银 行：", _text(order.signing_opening_bank, ""), "开 户 银 行：", seller_bank],
            ["税       号：", _text(order.signing_tax_number, ""), "税       号：", seller_tax_no],
            ["账       号：", _text(order.signing_bank_account, ""), "账       号：", seller_account],
            ["签 约 时 间：", contract_date, "签 约 时 间：", contract_date],
        ]
        data = [[p(label, signature_label), p(value, signature_value), p(right_label, signature_label), p(right_value, signature_value)] for label, value, right_label, right_value in rows]
        table = Table(data, colWidths=[31 * mm, 58 * mm, 31 * mm, 58 * mm], rowHeights=[8 * mm] * len(data))
        table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), "STSong-Light"),
            ("FONTSIZE", (0, 0), (-1, -1), 10.5),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        return table

    story = [
        Paragraph(seller_name, company_title),
        Paragraph("销售合同", title),
        meta_table(),
        Spacer(1, 4),
        p("供需双方本着平等互利、诚实信用的原则，经友好协商，就下述产品买卖事宜达成一致，订立本合同。"),
        p("第一条 产品内容及金额：", section),
        product_table,
        total_table,
        p("第二条 质量与技术标准", section),
        p("乙方提供的产品应符合本合同附件《产品清单》中约定的规格、型号、技术参数及配置要求。"),
        p("第三条  付款及结算期限、方式", section),
        raw_p(
            f"3.1 付款方式：根据双方约定，合同签订后3个工作日内，甲方支付合同总额的50%货款即"
            f"<b>{_money(half_amount)}元</b>，剩余50%货款<b>{_money(half_amount)}元</b>在发货前一次性付清。",
            base,
        ),
        p(f"乙方收款账户信息如下：\n账户名：{seller_name}\n开户行： {seller_bank}\n账  号： {seller_account}"),
        p("3.2 乙方发货后三个工作日内开具增值税专用发票，并交付给甲方。"),
        p("第四条  交货时间、地点、验收及物权交付", section),
        p("4.1 交货时间：预付款到账后 20 天左右。"),
        p(f"4.2 交货地点：{_text(order.project_name)}"),
        p(f"收货人：{_text(order.customer_name)}　联系方式：{_text(order.customer_phone)}"),
        p("（具体地址，避免有分校或因地址不明确发错货的情况）。若甲方临时因其他特殊情况变更交货地点，必须在乙方发货前及时告知乙方，甲方承担实际运费差价。"),
        p("4.3 运输方式：乙方负责送货到合同约定地点，并承担运费。甲方负责当地的卸货工作，并承担相应卸货费用。"),
        p("4.4 货物的保管权交接及货物的签收："),
        p("4.4.1 货物的保管权交接：乙方货物到达甲方交货地点。如果甲乙双方对货物交接有异议，甲方有权拒绝接收，乙方货物的保管义务由乙方承担。如甲方同意接收，则默认货物下车即视同交接给甲方，甲方应当履行对货物的妥善保管义务。若因甲方未尽妥善保管义务，导致货物出现雨淋、人为损坏、丢失等情况乙方不承担任何责任。"),
        p("4.4.2 货物的签收："),
        p("4.4.2.1 货物清单比较容易的情况：甲方在收货后需及时对货物进行清点，并在货物明细签收单上签字。"),
        p("4.4.2.2 货物数量较多，现场清点有困难的情况：甲方需在货物交接时，按照发货清单上的包装数量进行清点，并在货物包装清单上签字（建议甲方对货物包装进行拍照留存）。在三个工作日内及时清点货物明细清单，并向乙方出具货物明细签收单。一周内未出具货物明细签收单且未提出书面异议视为默认签收无异议。"),
        p("4.5 货物物权交接约定："),
        p("4.5.1 乙方确认收到甲方的全额货款后，双方认同货物的物权完成交接（即货物的所有权由乙方交接给甲方，甲方同时拥有货物的保管权和物权）。"),
        p("4.5.2 如果乙方只收到甲方的部分货款。在能有效区分的前提下，甲方拥有实际支付部分货款的物权。如果无法有效区分，在甲方支付完全额货款前，乙方拥有全部货物的物权。双方沟通无效的情况下，乙方有权收回甲方的货物保管权，取回全部货物。"),
        p("4.5.3 若因甲方未及时付款等原因导致乙方物权不能按时交接，乙方视情况对物权进行处置，包括但不限于收回物权、限制产品试用等，由此造成的损失由甲方承担。"),
        p("第五条  违约责任", section),
        p("5.1 甲乙双方在合同签订后，不得无故解除，违约解除合同的，须向对方支付合同金额20%的违约金。"),
        p("5.2 乙方逾期交付产品的，每逾期一日，乙方应按逾期交付产品总金额千分之一向甲方支付违约金。"),
        p("5.3 甲方逾期支付货款的，每逾期一日，甲方应按逾期支付货款总金额千分之一向乙方支付违约金。逾期超过【30】个工作日，乙方有权解除合同，并要求甲方支付合同总价款【20%】的违约金，且乙方有权到项目现场取回未付款项所对应的货物，甲方应予以配合。"),
        p("第六条  争议解决", section),
        p("因本合同引起的或与本合同有关的任何争议，双方应友好协商解决；协商不成的，任何一方均有权向供方所在地有管辖权的人民法院提起诉讼。"),
        p("第七条  其他约定", section),
        p("7.1 本合同自双方盖章之日起生效。"),
        p("7.2 本合同壹式贰份，供需双方各执壹份，自双方签字盖章后回传日生效，传真、复印件具有同等效力。"),
        p("7.3 本合同履行过程中，如需变更，须经双方协商一致并签订书面补充协议。"),
    ]
    if order.remark:
        story.extend([p("备注：" + order.remark), Spacer(1, 4)])
    story.extend([Spacer(1, 10), KeepTogether(signature_table())])

    doc.build(story)
    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{_contract_filename(order)}"'
    return response
