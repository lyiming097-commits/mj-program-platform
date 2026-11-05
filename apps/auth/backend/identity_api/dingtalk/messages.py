"""One outbound attempt per recipient; message POSTs must never be auto-retried."""
import json
import os

import requests

from .client import DingTalkAPIError, _get_app_access_token, get_client_config


def robot_config():
    app_key, secret = get_client_config()
    return os.getenv("DINGTALK_ROBOT_CODE", "").strip() or app_key, bool(app_key and secret)


def send_text(robot_code, kind, target_id, content):
    return send_message(robot_code, kind, target_id, "sampleText", {"content": content})


def send_markdown(robot_code, kind, target_id, params):
    return send_message(robot_code, kind, target_id, "sampleMarkdown", params)


def send_message(robot_code, kind, target_id, message_key, params):
    def result(status, message, code="", http_status=None, receipt=""):
        return dict(status=status, message=message, error_code=code[:128],
                    http_status=http_status, process_query_key=receipt[:512])

    try:
        token = _get_app_access_token()
    except DingTalkAPIError:
        return result("failed", "未能获取机器人发送凭据，请检查应用配置", "token_unavailable")
    body = {"robotCode": robot_code, "msgKey": message_key,
            "msgParam": json.dumps(params, ensure_ascii=False)}
    if kind == "group":
        endpoint = "groupMessages/send"
        body["openConversationId"] = target_id
    else:
        endpoint = "oToMessages/batchSend"
        body["userIds"] = [target_id]
    try:
        response = requests.post(
            "https://api.dingtalk.com/v1.0/robot/" + endpoint,
            headers={"x-acs-dingtalk-access-token": token}, json=body,
            timeout=(5, 15), allow_redirects=False,
        )
    except requests.RequestException:
        return result("unknown", "连接中断或超时，请核实钉钉消息后再决定是否重新发送", "connection_uncertain")
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    code = str(payload.get("code") or "")
    receipt = payload.get("processQueryKey")
    if response.status_code == 200:
        if kind == "person" and payload.get("invalidStaffIdList"):
            return result("failed", "收件人无效，请检查员工钉钉账号", "invalid_recipient", 200)
        if kind == "person" and payload.get("flowControlledStaffIdList"):
            return result("failed", "该收件人被限流，请稍后再发送", "recipient_flow_controlled", 200)
        if isinstance(receipt, str) and receipt:
            return result("accepted", "钉钉已受理", http_status=200, receipt=receipt)
    if response.status_code >= 500 or response.status_code in (200, 408) or code == "unknown.send.result":
        return result("unknown", "未取得明确发送结果，请核实钉钉消息", "upstream_uncertain", response.status_code)
    # Never persist/log an upstream response or exception containing credentials.
    messages = {
        "invalidParameter.robotCode.auth": "机器人与应用凭据不匹配",
        "invalid.openConversationId": "群标识无效，请检查群聊登记信息",
        "bot.stopped": "机器人已停用",
        "robot.oto.notExist": "员工与机器人的单聊会话不可用",
        "chatbotId.notAllow.sendOTO": "机器人暂不允许主动发送私聊",
        "auth.error": "机器人发送权限不足",
        "unauthorized": "机器人发送权限不足",
        "send.too.fast": "发送过于频繁，请稍后再发送",
    }
    return result("failed", messages.get(code, "钉钉拒绝发送，请检查权限、收件对象或机器人配置"),
                  code if code in messages else "upstream_rejected", response.status_code)
