from datetime import date
from decimal import Decimal

from django.db import migrations


PRESALES_NODES = [
    ("early-approval", "前期立项", "approval"),
    ("early-plan", "前期方案", "delivery"),
    ("budget-match", "预算匹配", "delivery"),
    ("project-filing", "项目申报", "delivery"),
    ("early-plan-result", "前期结果", "result"),
    ("late-approval", "后期立项", "approval"),
    ("late-plan", "后期方案", "delivery"),
    ("device-plan", "设备方案", "delivery"),
    ("budget", "工程预算", "delivery"),
    ("device-budget", "设备预算", "delivery"),
    ("cost-control", "工程成本管控", "delivery"),
    ("device-cost-control", "设备成本管控", "delivery"),
    ("rendering", "效果图", "delivery"),
    ("tender-plan", "招标方案", "delivery"),
    ("layout", "平面设计", "delivery"),
    ("bid-prep", "投标准备", "delivery"),
    ("construction-result", "结项结果", "result"),
    ("construction", "施工图", "delivery"),
    ("project-end", "结束标识", "end"),
]

MIDSALES_NODES = [
    ("midsales-project", "项目立项", "approval"),
    ("construction-work", "工程施工", "delivery"),
    ("furniture-install", "家具安装", "delivery"),
    ("device-install", "设备安装", "delivery"),
    ("device-debug", "设备调试", "delivery"),
    ("school-support", "开学保障", "delivery"),
    ("project-acceptance", "项目验收", "approval"),
    ("midsales-project-end", "结束标识", "end"),
]

AFTERSALES_NODES = [
    ("onsite-service", "上门售后", "delivery"),
    ("mail-service", "寄件售后", "delivery"),
    ("school-inspection", "开学巡检", "delivery"),
]


def seed_service_data(apps, _schema_editor):
    Provider = apps.get_model("after_sales_api", "ServiceProvider")
    Project = apps.get_model("after_sales_api", "ServiceProject")
    Node = apps.get_model("after_sales_api", "ProjectNode")
    Assignment = apps.get_model("after_sales_api", "ProjectAssignment")
    Event = apps.get_model("after_sales_api", "ProjectEvent")
    Ticket = apps.get_model("after_sales_api", "ServiceTicket")
    Message = apps.get_model("after_sales_api", "TicketMessage")
    Feedback = apps.get_model("after_sales_api", "FieldFeedback")
    Reward = apps.get_model("after_sales_api", "Reward")
    Settlement = apps.get_model("after_sales_api", "Settlement")
    Resource = apps.get_model("after_sales_api", "ServiceResource")
    Case = apps.get_model("after_sales_api", "WorkflowCase")

    audit = {
        "created_by": "system-seed",
        "created_actor_id": "system-seed",
        "updated_by": "system-seed",
        "updated_actor_id": "system-seed",
    }
    providers = {}
    provider_rows = [
        ("demo-zhang", "张师傅", "installer", "138****6721", "杭州", ["杭州", "宁波", "绍兴"], ["讲台安装", "中控联调", "平台接入"], "certified", "4.80", 8, 36),
        ("demo-li", "李工", "maintenance", "137****9082", "宁波", ["宁波", "舟山", "台州"], ["中控联调", "录播联动", "平台接入"], "certified", "4.70", 6, 29),
        ("demo-wang", "王师傅", "partner", "159****3310", "绍兴", ["绍兴", "杭州", "湖州"], ["智慧板书", "讲台安装"], "pending", "4.50", 3, 11),
        ("demo-chen", "陈工", "support", "136****7612", "金华", ["金华", "衢州", "丽水"], ["智慧板书", "录播联动", "平台接入"], "certified", "4.90", 7, 42),
        ("demo-xu", "徐工", "support", "139****8175", "杭州", ["杭州", "湖州", "嘉兴"], ["平台接入", "智慧板书", "录播联动"], "certified", "4.90", 9, 48),
    ]
    for user_id, name, role, phone, city, regions, skills, cert, score, month_orders, total_orders in provider_rows:
        providers[user_id] = Provider.objects.create(
            auth_user_id=user_id,
            name=name,
            role=role,
            phone=phone,
            city=city,
            regions=regions,
            skills=skills,
            certification_status=cert,
            score=Decimal(score),
            month_orders=month_orders,
            total_orders=total_orders,
            bio="迈杰售后技术服务演示档案",
            **audit,
        )

    projects = {}
    project_rows = [
        (
            "PS-2026-001", "presales", "星河客户-2026年-浙江工业大学智慧教室项目", "星河客户",
            "business-liuyang", "业务员-刘洋", "early-plan", "浙江工业大学智慧教室建设需求及方案深化。",
            "杭州市西湖区浙江工业大学项目现场", PRESALES_NODES, set(),
        ),
        (
            "MS-2026-001", "midsales", "浙江工业大学智慧教室项目", "浙江工业大学",
            "manager-chen", "项目经理-陈明", "device-install", "工程施工完成，进入设备安装与联调。",
            "杭州市拱墅区浙江工业大学项目现场", MIDSALES_NODES, {"school-support"},
        ),
        (
            "AS-2026-001", "aftersales", "浙江工商大学智慧教室售后服务", "浙江工商大学",
            "aftersales-li", "售后部-李工", "onsite-service", "上门排查平台接入与讲台接线问题。",
            "杭州市钱塘区浙江工商大学项目现场", AFTERSALES_NODES, {"mail-service", "school-inspection"},
        ),
    ]
    for code, service_type, name, customer, owner_id, owner_name, current_key, summary, address, template, disabled in project_rows:
        business_data = {
            "source": "迈杰售后技术服务软件原型",
            "products": ["迈杰智能讲台", "融合中控", "平台接入"],
        }
        if service_type == "aftersales":
            business_data.update({
                "managerContact": "售后部-李工，电话 13800000000",
                "expectedDuration": "4 小时",
                "feeAgreement": "上门服务费 1200 元",
                "feeRemark": "含基础搬运与现场指导，不含高空作业。",
                "products": [
                    {
                        "name": "迈杰智能讲台",
                        "quantity": 1,
                        "carryNeed": "需要搬运到指定位置",
                        "installNeed": "需要完成安装",
                        "debugNeed": "需要",
                    },
                    {
                        "name": "融合中控",
                        "quantity": 1,
                        "carryNeed": "不需要",
                        "installNeed": "不需要",
                        "debugNeed": "需要",
                    },
                ],
            })
        project = Project.objects.create(
            code=code,
            service_type=service_type,
            name=name,
            customer=customer,
            owner_user_id=owner_id,
            owner_name=owner_name,
            status="in_progress",
            current_node_key=current_key,
            address=address,
            province="浙江",
            planned_start_date=date(2026, 7, 1),
            planned_end_date=date(2026, 8, 31),
            summary=summary,
            business_data=business_data,
            **audit,
        )
        projects[code] = project
        current_index = next(index for index, row in enumerate(template) if row[0] == current_key)
        for index, (key, label, kind) in enumerate(template):
            enabled = key not in disabled
            if not enabled:
                status = "skipped"
            elif index < current_index:
                status = "completed"
            elif key == current_key:
                status = "active"
            else:
                status = "pending"
            node_business_data = {}
            if service_type == "presales" and status == "completed" and kind == "approval":
                node_business_data = {"outcome": "approved", "outcomeLabel": "立项成功"}
            Node.objects.create(
                project=project,
                node_key=key,
                name=label,
                sequence=index + 1,
                kind=kind,
                description=f"{label}节点业务记录",
                enabled=enabled,
                status=status,
                estimated_fee=Decimal("1200.00") if service_type == "aftersales" and key == "onsite-service" else None,
                business_data=node_business_data,
                **audit,
            )
        Event.objects.create(
            project=project,
            event_type="seed_imported",
            title="导入原型演示项目",
            detail=summary,
            after_values={"currentNodeKey": current_key, "serviceType": service_type},
            auth_user_id="system-seed",
            auth_user_name="系统初始化",
            actor_user_id="system-seed",
            actor_name="系统初始化",
        )

    assignment_rows = [
        ("PS-2026-001", "early-plan", "demo-xu", "方案与平台支持"),
        ("MS-2026-001", "device-install", "demo-zhang", "设备安装"),
        ("MS-2026-001", "device-install", "demo-chen", "技术支持"),
        ("AS-2026-001", "onsite-service", "demo-zhang", "上门服务"),
    ]
    for project_code, node_key, user_id, role in assignment_rows:
        project = projects[project_code]
        Assignment.objects.create(
            project=project,
            node=Node.objects.get(project=project, node_key=node_key),
            provider=providers[user_id],
            role=role,
            status="assigned",
            note="由演示项目初始化指派",
            **audit,
        )

    aftersales = projects["AS-2026-001"]
    onsite = Node.objects.get(project=aftersales, node_key="onsite-service")
    ticket = Ticket.objects.create(
        code="TK-20260624-001",
        project=aftersales,
        node=onsite,
        title="平台接入日志需要技术确认",
        ticket_type="资料权限",
        priority="medium",
        status="in_progress",
        owner_user_id="demo-chen",
        owner_name="陈工",
        reporter_user_id="demo-zhang",
        reporter_name="张师傅",
        description="现场已重新登录平台，仍提示账号权限不足，需要核对平台日志和账号绑定关系。",
        business_data={"source": "现场安装反馈", "customerContacted": True},
        **audit,
    )
    Message.objects.create(
        ticket=ticket,
        author_user_id="demo-zhang",
        author_name="张师傅",
        actor_user_id="demo-zhang",
        message_type="text",
        content="现场照片和日志截图已补充，请确认是否可以关闭。",
        status_snapshot="in_progress",
    )
    Ticket.objects.create(
        code="TK-20260624-002",
        project=projects["MS-2026-001"],
        node=Node.objects.get(project=projects["MS-2026-001"], node_key="device-install"),
        title="设备安装现场进场时间协调",
        ticket_type="现场异常",
        priority="high",
        status="assigned",
        owner_user_id="manager-chen",
        owner_name="项目经理-陈明",
        reporter_user_id="demo-zhang",
        reporter_name="张师傅",
        description="施工队和学校门卫登记时间不一致，需要协调进场。",
        **audit,
    )

    accepted_feedback = Feedback.objects.create(
        project=aftersales,
        node=onsite,
        provider=providers["demo-zhang"],
        feedback_type="resource_suggestion",
        content="建议在平台接入资料中增加账号权限检查清单，减少现场等待。",
        status="accepted",
        rating=5,
        review_note="建议有效，已转资料维护。",
        reviewed_by="system-seed",
        reward_generated=True,
        business_data={"source": "安装完成反馈"},
        **audit,
    )
    Feedback.objects.create(
        project=projects["MS-2026-001"],
        node=Node.objects.get(project=projects["MS-2026-001"], node_key="device-install"),
        provider=providers["demo-chen"],
        feedback_type="issue",
        content="现场中控线序与说明书版本不一致，等待确认。",
        status="submitted",
        business_data={"urgency": "high"},
        **audit,
    )

    Reward.objects.create(
        code="RW-20260624-001",
        provider=providers["demo-zhang"],
        project=aftersales,
        feedback=accepted_feedback,
        reward_type="prize",
        title="安装反馈抽奖",
        description="完成真实安装反馈并提交有效资料建议。",
        prize="工具收纳包",
        status="approved",
        **audit,
    )
    Reward.objects.create(
        code="RW-20260623-002",
        provider=providers["demo-xu"],
        project=projects["PS-2026-001"],
        reward_type="points",
        title="平台联调建议采纳奖励",
        description="联调日志提示建议被采纳。",
        points=50,
        status="issued",
        **audit,
    )

    Settlement.objects.create(
        code="SET-20260727-001",
        project=projects["MS-2026-001"],
        service_type="midsales",
        customer="浙江工业大学",
        bearer="company",
        service_content="工程施工、设备安装和现场技术支持",
        budget_amount=Decimal("40000.00"),
        final_amount=Decimal("37600.00"),
        order_amount=Decimal("37600.00"),
        status="pending",
        subject_type="company",
        subject_name="迈杰科技有限公司",
        remark="待内部核销",
        **audit,
    )
    Settlement.objects.create(
        code="SET-20260727-002",
        project=aftersales,
        service_type="aftersales",
        customer="浙江工商大学",
        bearer="customer",
        service_content="上门售后服务费",
        budget_amount=Decimal("1200.00"),
        final_amount=Decimal("1200.00"),
        order_amount=Decimal("1200.00"),
        received_amount=Decimal("1200.00"),
        invoice_due_amount=Decimal("1200.00"),
        status="pending",
        invoice_type="增值税普通发票",
        remark="已收款待核销",
        **audit,
    )

    Resource.objects.create(
        project=projects["MS-2026-001"],
        node_key="device-install",
        title="设备安装资料包",
        resource_type="manual",
        audience="assigned",
        summary="设备清单、安装说明、接线图与现场检查项。",
        content="安装前核对包装、型号标签、产品外观和接线要求。",
        tags=["设备安装", "接线说明", "现场检查"],
        enabled=True,
        **audit,
    )
    Resource.objects.create(
        project=aftersales,
        node_key="onsite-service",
        title="平台接入故障排查清单",
        resource_type="debug",
        audience="assigned",
        summary="账号权限、网络连通、设备编号和日志检查。",
        content="现场先核对网络、账号绑定关系与设备编号，再提交日志。",
        tags=["平台接入", "故障排查"],
        enabled=True,
        **audit,
    )
    Resource.objects.create(
        title="迈杰智能讲台公开安装示范",
        resource_type="video",
        audience="public",
        summary="标准产品安装示范，定制项目以现场资料为准。",
        content="公开示范资料不替代项目专属安装要求。",
        tags=["智能讲台", "公开示范"],
        enabled=True,
        **audit,
    )

    case_rows = [
        ("CP-2026-001", "complaint", "资料权限申请流程偏长", "demo-zhang", "张师傅", "售后资料权限", "安装人员到现场后仍需二次审批，影响安装节奏。", "aftersales-li", "售后部-李工"),
        ("HP-2026-001", "support", "设备接线远程支持", "demo-zhang", "张师傅", "现场技术支持", "智慧讲台接线后无法识别中控信号，需要远程支持。", "demo-chen", "陈工"),
        ("RA-2026-001", "reward_application", "现场紧急联调奖励申请", "manager-chen", "项目经理-陈明", "现场服务奖励", "安装人员主动加班完成联调，避免第二天重复进场。", "regional-zhou", "区域经理-周宁"),
    ]
    for code, case_type, title, applicant_id, applicant_name, category, content, handler_id, handler_name in case_rows:
        Case.objects.create(
            code=code,
            case_type=case_type,
            title=title,
            applicant_user_id=applicant_id,
            applicant_name=applicant_name,
            target_user_id="demo-zhang" if case_type == "reward_application" else "",
            target_name="张师傅" if case_type == "reward_application" else "",
            category=category,
            urgency="urgent" if code.endswith("001") else "normal",
            content=content,
            handler_user_id=handler_id,
            handler_name=handler_name,
            current_step="accept",
            status="pending",
            business_data={"history": [{"from": "raise", "to": "accept", "note": "事项已提交受理"}]},
            **audit,
        )


def remove_seed_service_data(apps, _schema_editor):
    Provider = apps.get_model("after_sales_api", "ServiceProvider")
    Project = apps.get_model("after_sales_api", "ServiceProject")
    Ticket = apps.get_model("after_sales_api", "ServiceTicket")
    Feedback = apps.get_model("after_sales_api", "FieldFeedback")
    Reward = apps.get_model("after_sales_api", "Reward")
    Settlement = apps.get_model("after_sales_api", "Settlement")
    Resource = apps.get_model("after_sales_api", "ServiceResource")
    Case = apps.get_model("after_sales_api", "WorkflowCase")

    Reward.objects.filter(code__in=["RW-20260624-001", "RW-20260623-002"]).delete()
    Feedback.objects.filter(
        created_by="system-seed",
        project__code__in=["PS-2026-001", "MS-2026-001", "AS-2026-001"],
    ).delete()
    Ticket.objects.filter(code__in=["TK-20260624-001", "TK-20260624-002"]).delete()
    Settlement.objects.filter(code__in=["SET-20260727-001", "SET-20260727-002"]).delete()
    Resource.objects.filter(created_by="system-seed", title__in=[
        "设备安装资料包",
        "平台接入故障排查清单",
        "迈杰智能讲台公开安装示范",
    ]).delete()
    Case.objects.filter(code__in=["CP-2026-001", "HP-2026-001", "RA-2026-001"]).delete()
    Project.objects.filter(code__in=["PS-2026-001", "MS-2026-001", "AS-2026-001"]).delete()
    Provider.objects.filter(auth_user_id__in=["demo-zhang", "demo-li", "demo-wang", "demo-chen", "demo-xu"]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("after_sales_api", "0002_service_domain"),
    ]

    operations = [
        migrations.RunPython(seed_service_data, remove_seed_service_data),
    ]
